"""Read-range recording for the floor document inspector.

For every LLM call made while a document goes through the pipeline, record which
character ranges of the document's normalised working text the request contained.
Matching runs against the working text; only offsets are stored, never text.

Sections: matcher (below). Context, recorder and seam sections are appended after it.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from typing import TypedDict

# --- matcher ---------------------------------------------------------------

SHINGLE = 48
STRIDE = 16
MAX_RANGES = 64
MAX_DOC_CHARS = 3_000_000
MAX_REQUEST_CHARS = 3_000_000
_MAX_CANDIDATES = 8  # doc positions tried per shingle (repetitive text)
_BLOCK = 256
_MAX_GAP_CHARS = 64_000  # request gaps larger than this are not gap-filled
_MIN_UNANCHORED = 12  # non-whitespace chars needed to map a piece without an anchor
_BLANK_LINE = re.compile(r"\n\s*\n")


class MatchResult(TypedDict):
    ranges: list[list[int]]
    request_chars: int
    matched_chars: int
    doc_chars: int
    skipped: str | None  # "size", "no_text" or None


class ShingleIndex:
    """Strided index of the document's ``SHINGLE``-character substrings."""

    def __init__(self, text: str | None) -> None:
        self.text = text or ""
        self.doc_chars = len(self.text)
        self.skipped: str | None = None
        self.table: dict[str, list[int]] = {}
        if not self.text:
            self.skipped = "no_text"
        elif self.doc_chars > MAX_DOC_CHARS:
            self.skipped = "size"
        else:
            table = self.table
            text = self.text
            for i in range(0, self.doc_chars - SHINGLE + 1, STRIDE):
                table.setdefault(text[i : i + SHINGLE], []).append(i)


def _common_prefix(a: str, ai: int, b: str, bi: int) -> int:
    """Length of the common run of ``a[ai:]`` and ``b[bi:]``."""
    limit = min(len(a) - ai, len(b) - bi)
    n = 0
    while n < limit:
        step = min(_BLOCK, limit - n)
        if a[ai + n : ai + n + step] == b[bi + n : bi + n + step]:
            n += step
            continue
        while a[ai + n] == b[bi + n]:
            n += 1
        break
    return n


def _common_suffix(a: str, ae: int, b: str, be: int, limit: int) -> int:
    """Length of the common run ending just before ``a[ae]`` and ``b[be]``."""
    limit = min(limit, ae, be)
    n = 0
    while n < limit:
        step = min(_BLOCK, limit - n)
        if a[ae - n - step : ae - n] == b[be - n - step : be - n]:
            n += step
            continue
        while a[ae - n - 1] == b[be - n - 1]:
            n += 1
        break
    return n


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _cap_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Merge the smallest gaps first until at most ``MAX_RANGES`` remain."""
    excess = len(ranges) - MAX_RANGES
    if excess <= 0:
        return ranges
    gaps = sorted(range(len(ranges) - 1), key=lambda i: (ranges[i + 1][0] - ranges[i][1], i))
    close = set(gaps[:excess])
    out: list[list[int]] = [list(ranges[0])]
    for i in range(1, len(ranges)):
        if (i - 1) in close:
            out[-1][1] = ranges[i][1]
        else:
            out.append(list(ranges[i]))
    return out


def _pieces(request: str, lo: int, hi: int) -> list[str]:
    """Stripped, non-empty pieces of ``request[lo:hi]`` split on blank lines."""
    out: list[str] = []
    pos = lo
    for m in _BLANK_LINE.finditer(request, lo, hi):
        out.append(request[pos : m.start()].strip())
        pos = m.end()
    out.append(request[pos:hi].strip())
    return [p for p in out if p]


def _unique_in_doc(doc: str, piece: str) -> int:
    """Offset of ``piece`` if it occurs exactly once in ``doc``, else -1."""
    if sum(not c.isspace() for c in piece) < _MIN_UNANCHORED:
        return -1
    pos = doc.find(piece)
    if pos < 0 or doc.find(piece, pos + 1) >= 0:
        return -1
    return pos


def _fill_gaps(
    doc: str, request: str, bulk: list[tuple[int, int, int, int]], found: list[list[int]]
) -> int:
    """Anchored gap-fill: map short pieces between bulk matches. Returns chars matched."""
    n = len(request)
    gaps: list[tuple[int, int, int, int]] = []  # req_lo, req_hi, doc_lo, doc_hi
    prev_re, prev_de = 0, 0
    for rs, re_, ds, de in bulk:
        gaps.append((prev_re, rs, prev_de, ds))
        prev_re, prev_de = re_, de
    gaps.append((prev_re, n, prev_de, len(doc)))
    has_anchor = bool(bulk)
    matched = 0
    for req_lo, req_hi, doc_lo, doc_hi in gaps:
        if req_hi - req_lo <= 0 or req_hi - req_lo > _MAX_GAP_CHARS:
            continue
        anchored = has_anchor and doc_hi >= doc_lo
        cursor = doc_lo
        for piece in _pieces(request, req_lo, req_hi):
            pos = doc.find(piece, cursor, doc_hi) if anchored else -1
            if pos >= 0:
                cursor = pos + len(piece)
            else:
                pos = _unique_in_doc(doc, piece)
                if pos < 0:
                    continue
            found.append([pos, pos + len(piece)])
            matched += len(piece)
    return matched


def match_ranges(index: ShingleIndex, request: str) -> MatchResult:
    """Ranges ``[start, end)`` of the document text that appear verbatim in ``request``."""
    request = request or ""
    result: MatchResult = {
        "ranges": [],
        "request_chars": len(request),
        "matched_chars": 0,
        "doc_chars": index.doc_chars,
        "skipped": index.skipped,
    }
    if index.skipped:
        return result
    if len(request) > MAX_REQUEST_CHARS:
        result["skipped"] = "size"
        return result

    doc = index.text
    table = index.table
    n = len(request)
    found: list[list[int]] = []
    bulk: list[tuple[int, int, int, int]] = []  # request lo/hi, doc lo/hi (verified)
    matched = 0
    prev_doc_end = 0
    floor = 0  # request chars before this are already covered by an earlier match
    i = 0
    last = n - SHINGLE
    while i <= last:
        cands = table.get(request[i : i + SHINGLE])
        if cands is None:
            i += 1
            continue
        best_len = 0
        best_doc = 0
        best_req = 0
        k = bisect_left(cands, prev_doc_end)
        for j in (cands[k:] + cands[:k])[:_MAX_CANDIDATES]:
            right = _common_prefix(request, i + SHINGLE, doc, j + SHINGLE)
            left = _common_suffix(request, i, doc, j, i - floor)
            length = SHINGLE + left + right
            if length > best_len:
                best_len, best_doc, best_req = length, j - left, i - left
        floor = best_req + best_len
        i = floor
        prev_doc_end = best_doc + best_len
        bulk.append((best_req, floor, best_doc, prev_doc_end))
        # A coincidental whitespace edge (a header's trailing newline against a
        # paragraph break) is not a read of the document: trim it.
        s, e = best_doc, best_doc + best_len
        while s < e and doc[s].isspace():
            s += 1
        while e > s and doc[e - 1].isspace():
            e -= 1
        if e <= s:
            continue
        found.append([s, e])
        matched += e - s
    matched += _fill_gaps(doc, request, bulk, found)
    result["ranges"] = _cap_ranges(_merge_ranges(found))
    result["matched_chars"] = matched
    return result
