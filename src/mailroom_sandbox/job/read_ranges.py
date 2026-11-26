"""Read-range recording for the floor document inspector.

For every LLM call made while a document goes through the pipeline, record which
character ranges of the document's normalised working text the request contained.
Matching runs against the working text; only offsets are stored, never text.

Ranges are half-open ``[start, end)`` offsets into the working text, sorted, merged and
trimmed of leading and trailing whitespace. ``matched_chars`` is the number of distinct
request characters covered by a placed match (whitespace trimmed from a match edge is not
counted); a request character is never counted twice. ``unplaced_pieces`` counts request
pieces of at least 12 non-whitespace characters that could not be placed, either because
they are not in the document or because the per-request lookup budget
(``MAX_UNANCHORED_LOOKUPS``) ran out; downstream shows such requests as partly measured.

Sections: matcher, document context, recorder. Call seams are appended after them.

The per-document context holds one mutable state object in a ``ContextVar``. LangGraph may
run node callbacks in a copied context, so callbacks and seams only *mutate* that object
(guarded by a lock); ``document()`` is the one place that sets and resets the variable.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from bisect import bisect_left
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypedDict

# --- matcher ---------------------------------------------------------------

SHINGLE = 48
STRIDE = 16
MAX_RANGES = 64
MAX_DOC_CHARS = 3_000_000
MAX_REQUEST_CHARS = 3_000_000
MAX_UNANCHORED_LOOKUPS = 256  # whole-document uniqueness checks per request
_MAX_CANDIDATES = 8  # doc positions tried per shingle (repetitive text)
_BLOCK = 256
_MAX_ANCHORED_SCAN = 400_000_000  # doc chars scanned by anchored finds per request
_MAX_GAP_CHARS = 64_000  # request gaps larger than this are not gap-filled
_MIN_UNANCHORED = 12  # non-whitespace chars needed to map a piece without an anchor
_BLANK_LINE = re.compile(r"\n\s*\n")


class MatchResult(TypedDict):
    ranges: list[list[int]]
    request_chars: int
    matched_chars: int
    doc_chars: int
    unplaced_pieces: int  # pieces of >= 12 non-whitespace chars left unplaced
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


def _substantial(piece: str) -> bool:
    return sum(not c.isspace() for c in piece) >= _MIN_UNANCHORED


def _unique_in_doc(doc: str, piece: str) -> int:
    """Offset of ``piece`` if it occurs exactly once in ``doc``, else -1."""
    pos = doc.find(piece)
    if pos < 0 or doc.find(piece, pos + 1) >= 0:
        return -1
    return pos


def _fill_gaps(
    doc: str, request: str, bulk: list[tuple[int, int, int, int]], found: list[list[int]]
) -> tuple[int, int]:
    """Anchored gap-fill: map short pieces between bulk matches.

    Returns ``(chars matched, unplaced substantial pieces)``. Unanchored uniqueness
    lookups are limited to ``MAX_UNANCHORED_LOOKUPS`` per request.
    """
    n = len(request)
    gaps: list[tuple[int, int, int, int]] = []  # req_lo, req_hi, doc_lo, doc_hi
    prev_re, prev_de = 0, 0
    for rs, re_, ds, de in bulk:
        gaps.append((prev_re, rs, prev_de, ds))
        prev_re, prev_de = re_, de
    gaps.append((prev_re, n, prev_de, len(doc)))
    has_anchor = bool(bulk)
    matched = 0
    unplaced = 0
    lookups = 0
    scanned = 0
    for req_lo, req_hi, doc_lo, doc_hi in gaps:
        if req_hi - req_lo <= 0 or req_hi - req_lo > _MAX_GAP_CHARS:
            continue
        anchored = has_anchor and doc_hi >= doc_lo
        cursor = doc_lo

        def place(text: str) -> bool:
            nonlocal cursor, matched, lookups, scanned
            pos = -1
            if anchored and scanned + (doc_hi - cursor) <= _MAX_ANCHORED_SCAN:
                pos = doc.find(text, cursor, doc_hi)
                scanned += (pos - cursor) if pos >= 0 else (doc_hi - cursor)
            if pos >= 0:
                cursor = pos + len(text)
            else:
                if not _substantial(text) or lookups >= MAX_UNANCHORED_LOOKUPS:
                    return False
                lookups += 1
                pos = _unique_in_doc(doc, text)
                if pos < 0:
                    return False
            found.append([pos, pos + len(text)])
            matched += len(text)
            return True

        for piece in _pieces(request, req_lo, req_hi):
            if place(piece):
                continue
            if "\n" not in piece:
                unplaced += _substantial(piece)
                continue
            # A label line glued to the text by a single newline: try line by line.
            for line in piece.split("\n"):
                line = line.strip()
                if line and not place(line):
                    unplaced += _substantial(line)
    return matched, unplaced


def match_ranges(index: ShingleIndex, request: str) -> MatchResult:
    """Ranges ``[start, end)`` of the document text that appear verbatim in ``request``."""
    request = request or ""
    result: MatchResult = {
        "ranges": [],
        "request_chars": len(request),
        "matched_chars": 0,
        "doc_chars": index.doc_chars,
        "unplaced_pieces": 0,
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
    filled, result["unplaced_pieces"] = _fill_gaps(doc, request, bulk, found)
    matched += filled
    result["ranges"] = _cap_ranges(_merge_ranges(found))
    result["matched_chars"] = matched
    return result


# --- document context ------------------------------------------------------


def text_hash(text: str) -> str:
    """Short content tag of a working text: sha1 over its UTF-8 bytes, first 16 hex characters.

    Read records and ``doc_texts/index.jsonl`` carry it, and the floor digest builder recomputes it
    from the stored file, so ranges are only shown against the exact text the agents saw. It is a
    content tag, not a security control. ``reports/dashboard/build_floor_digest.py`` repeats these
    two lines (it is stdlib-only); a test keeps them equal.
    """
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


class _DocState:
    """Mutable per-document state shared by every callback that runs for the document."""

    def __init__(self, doc_id: str, raw_text: str | None,
                 sink: Callable[[dict], None] | None,
                 text_sink: Callable[[str, str], None] | None) -> None:
        self.doc_id = doc_id
        self.raw_text = raw_text if isinstance(raw_text, str) else None
        self.working_text: str | None = None
        self.text_hash: str | None = None  # of the working text; None until intake hands it over
        self.sink = sink
        self.text_sink = text_sink
        self.index: ShingleIndex | None = None  # built lazily, from the working text once known
        self.calls = 0
        self.read_calls = 0
        self.read_errors = 0
        self.read_ms = 0.0
        self.nodes: list[str] = []
        self.lock = threading.Lock()

    def basis_and_index(self) -> tuple[str, ShingleIndex]:
        with self.lock:
            if self.index is None:
                if self.working_text is not None:
                    self.index = ShingleIndex(self.working_text)
                else:
                    self.index = ShingleIndex(self.raw_text)
            return ("working" if self.working_text is not None else "raw"), self.index

    def count_error(self) -> None:
        with self.lock:
            self.read_errors += 1


_STATE: ContextVar[_DocState | None] = ContextVar("sandbox_read_ranges", default=None)


@contextmanager
def document(doc_id: str, raw_text: str | None, sink: Callable[[dict], None] | None,
             text_sink: Callable[[str, str], None] | None = None) -> Iterator[None]:
    """Record read ranges for every LLM call made for ``doc_id`` inside this scope.

    ``raw_text`` is the row's text, used until the intake node hands over the working text.
    A ``None`` ``sink`` makes every recorder call a no-op.
    """
    token = _STATE.set(_DocState(str(doc_id), raw_text, sink, text_sink))
    try:
        yield
    finally:
        _STATE.reset(token)


def set_working_text(text: str) -> None:
    """Adopt ``text`` as the document's working text (once) and hand it to the text sink."""
    state = _STATE.get()
    if state is None or state.sink is None or not isinstance(text, str) or not text:
        return
    with state.lock:
        if state.working_text is not None:
            return
        state.working_text = text
        try:
            state.text_hash = text_hash(text)
        except Exception:  # noqa: BLE001 - e.g. a lone surrogate; records then carry no hash
            state.text_hash = None
        state.index = None  # rebuilt lazily from the working text
    if state.text_sink is not None:
        try:
            state.text_sink(state.doc_id, text)
        except Exception:  # noqa: BLE001 - recording must never break a document
            state.count_error()


def _enter_node(node: str) -> None:
    state = _STATE.get()
    if state is None:
        return
    try:
        with state.lock:
            state.nodes.append(node)
    except Exception:  # noqa: BLE001
        state.count_error()


def _exit_node(node: str) -> None:
    state = _STATE.get()
    if state is None:
        return
    try:
        with state.lock:
            for i in range(len(state.nodes) - 1, -1, -1):
                if state.nodes[i] == node:
                    del state.nodes[i]
                    break
    except Exception:  # noqa: BLE001
        state.count_error()


def current_node() -> str | None:
    """The innermost open tracked node of the current document, if any."""
    state = _STATE.get()
    if state is None:
        return None
    with state.lock:
        return state.nodes[-1] if state.nodes else None


def stats() -> dict[str, Any]:
    """``{read_calls, read_errors, read_ms}`` for the current document."""
    state = _STATE.get()
    if state is None:
        return {"read_calls": 0, "read_errors": 0, "read_ms": 0.0}
    with state.lock:
        return {"read_calls": state.read_calls, "read_errors": state.read_errors,
                "read_ms": round(state.read_ms, 3)}


# --- recorder --------------------------------------------------------------


def record(agent: str, request: str, *, node: str | None = None) -> None:
    """Match ``request`` against the document and hand one offsets-only record to the sink."""
    state = _STATE.get()
    if state is None or state.sink is None:
        return None
    t0 = time.perf_counter()
    try:
        basis, index = state.basis_and_index()
        with state.lock:
            state.calls += 1
            call = state.calls
            attributed = node or (state.nodes[-1] if state.nodes else None)
        result = match_ranges(index, request if isinstance(request, str) else "")
        rec: dict[str, Any] = {
            "doc": state.doc_id, "call": call, "agent": agent, "node": attributed,
            "ts": time.time(), "basis": basis, "ranges": result["ranges"],
            "request_chars": result["request_chars"], "matched_chars": result["matched_chars"],
            "doc_chars": result["doc_chars"], "unplaced_pieces": result["unplaced_pieces"],
        }
        if result["skipped"]:
            rec["skipped"] = result["skipped"]
        if basis == "working" and state.text_hash:
            rec["text_hash"] = state.text_hash  # pairs these ranges with the stored text
        state.sink(rec)
    except Exception:  # noqa: BLE001 - recording must never break a document
        state.count_error()
    finally:
        with state.lock:
            state.read_calls += 1
            state.read_ms += (time.perf_counter() - t0) * 1000
    return None


# --- seams: observe every chat agent request --------------------------------
#
# Recorded text is the document-bearing portion only (see ``_request_text``); the
# measured request sizes are over that portion, not the full request sent.
#
# The observer sits on each target class's ``_call_structured`` and delegates with the exact same
# arguments, recording the request text once the call guard admits it. It is always the
# OUTERMOST layer: the sampling layer may replace the call path (the native
# endpoint), so only an outer observer sees every request.
#
# ``functools.wraps`` copies the wrapped function's ``__dict__``, so a marker
# attribute alone cannot identify a layer. Layers are identified by identity in
# ``_OBSERVERS`` instead; the attribute is kept only as a human-readable tag.

import functools  # noqa: E402
import inspect  # noqa: E402
import logging  # noqa: E402
import weakref  # noqa: E402

_log = logging.getLogger(__name__)
_OBSERVERS: "weakref.WeakSet[Any]" = weakref.WeakSet()


def is_observer(fn: Any) -> bool:
    """True only for a function this module built (identity, not an inherited marker)."""
    try:
        return fn in _OBSERVERS
    except TypeError:
        return False


def strip_observer(fn: Any) -> Any:
    """``fn`` with any observer layers removed (through ``__wrapped__``)."""
    while is_observer(fn):
        fn = fn.__wrapped__
    return fn


def _request_text(self: Any, bound_args: dict[str, Any]) -> tuple[str, str]:
    """The document-bearing part of a request: agent name, caller-passed system text, user message.

    Only the ``system_prompt`` argument is used, and only when the caller passed a plain ``str``.
    No agent method or attribute is ever called or read (``system_prompt()`` mutates agent state
    and may fetch from Langfuse), apart from ``agent_name``. So ``request_chars`` and
    ``matched_chars`` are measured over this portion, not the full request sent: the JSON-mode
    note, the schema, skills, tools, memory and the augmented system prompt are excluded.
    Ranges locate document text, which the agents carry in the user message.
    """
    name = str(getattr(self, "agent_name", "") or "")
    system = bound_args.get("system_prompt")
    user = bound_args.get("user_message")
    parts = [name, system if isinstance(system, str) else "", user if isinstance(user, str) else ""]
    return name, "\n".join(parts)


class _PendingRead:
    """One chat request waiting to be recorded: the agent name and the request text.

    ``status`` is ``None`` until a call guard has decided: ``"recorded"`` once the guard admitted
    the request (``admit_pending``), ``"refused"`` when it refused it (``refuse_pending``). Calls
    that never meet a guard (non-OpenRouter routes, the native sampling endpoint) stay ``None`` and
    are recorded when the observed call returns or raises.
    """

    __slots__ = ("agent", "text", "status", "lock")

    def __init__(self, agent: str, text: str) -> None:
        self.agent = agent
        self.text = text
        self.status: str | None = None
        self.lock = threading.Lock()


_PENDING: ContextVar[_PendingRead | None] = ContextVar("sandbox_read_pending", default=None)


def _settle(pending: _PendingRead, outcome: str) -> None:
    """Move ``pending`` to ``outcome`` once; the first move to ``recorded`` writes the record."""
    with pending.lock:
        if pending.status == "recorded" or (pending.status == "refused" and outcome != "recorded"):
            return
        pending.status = outcome
    if outcome == "recorded":
        record(pending.agent, pending.text)


def admit_pending() -> None:
    """A call guard let the current request go out: record it now (once per logical request)."""
    pending = _PENDING.get()
    if pending is not None:
        _settle(pending, "recorded")


def refuse_pending() -> None:
    """A call guard refused the current request: it was never sent, so it is never recorded."""
    pending = _PENDING.get()
    if pending is not None:
        _settle(pending, "refused")


def _observe(inner: Any) -> Any:
    try:
        signature: inspect.Signature | None = inspect.signature(inner)
    except (TypeError, ValueError):
        signature = None

    @functools.wraps(inner)
    def _call_structured(self, *args, **kwargs):
        pending: _PendingRead | None = None
        if _STATE.get() is not None and signature is not None:
            try:
                bound = signature.bind(self, *args, **kwargs)
                name, text = _request_text(self, bound.arguments)
                pending = _PendingRead(name, text)
            except Exception:  # noqa: BLE001 - observing must never change a call
                state = _STATE.get()
                if state is not None:
                    state.count_error()
        if pending is None:
            return inner(self, *args, **kwargs)
        # The request is recorded when the provider guard admits it (``admit_pending``), so a call the
        # run cap or the document ceiling refused never shows as read; a call that meets no guard is
        # recorded once it returns or raises.
        token = _PENDING.set(pending)
        try:
            return inner(self, *args, **kwargs)
        finally:
            _PENDING.reset(token)
            if pending.status is None:
                _settle(pending, "recorded")

    # wraps() copied the inner layer's __dict__: drop markers that are not ours.
    _call_structured.__dict__.pop("__sandbox_sampling__", None)
    _call_structured.__sandbox_read_ranges__ = True  # type: ignore[attr-defined]
    _OBSERVERS.add(_call_structured)
    return _call_structured


def observe_class(cls: Any) -> bool:
    """Put exactly one observer on top of ``cls._call_structured``. True when patched."""
    current = cls.__dict__.get("_call_structured")
    if current is None:
        return False
    cls._call_structured = _observe(strip_observer(current))
    return True


def install_call_observer() -> int:
    """Observe every sampling target. Idempotent; returns the number of classes patched."""
    from mailroom_sandbox import sampling

    patched = 0
    for module_name, class_name in sampling._TARGETS:
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            patched += bool(observe_class(cls))
        except Exception as exc:  # noqa: BLE001 - optional (pipeline extra)
            _log.debug("%s.%s unavailable - not observed: %s", module_name, class_name, exc)
    return patched
