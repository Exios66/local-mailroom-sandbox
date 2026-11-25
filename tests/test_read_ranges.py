"""Range matcher: which character ranges of the working text a request contained."""

from __future__ import annotations

import random
import time

from agents.intake import sliding_windows
from langchain_agents.specialist_agents import _SpecialistBase

from mailroom_sandbox.job.read_ranges import (
    MAX_DOC_CHARS,
    MAX_RANGES,
    SHINGLE,
    ShingleIndex,
    match_ranges,
)


def _numbered_text(n_chars: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    paras: list[str] = []
    total = 0
    i = 0
    while total < n_chars:
        para = f"Section {i}. " + rng.randbytes(60).hex()
        paras.append(para)
        total += len(para) + 2
        i += 1
    return "\n\n".join(paras)[:n_chars]


def test_sliding_windows_map_to_exact_offsets():
    text = _numbered_text(120_000)
    index = ShingleIndex(text)
    windows = sliding_windows(text, 30_000, 2_000)
    assert len(windows) > 1
    for window, start in windows:
        result = match_ranges(index, "PROMPT HEADER\n" + window)
        assert result["skipped"] is None
        assert result["ranges"] == [[start, start + len(window)]]
        assert result["matched_chars"] == len(window)
        assert result["request_chars"] == len(window) + len("PROMPT HEADER\n")
        assert result["doc_chars"] == len(text)


def test_split_chunks_map_per_paragraph():
    rng = random.Random(3)
    paras = []
    for i in range(400):
        paras.append(f"Clause {i}: " + rng.randbytes(40).hex())
        if i % 7 == 0:
            paras.append("   \n ")  # whitespace-only paragraph, dropped by the splitter
    text = "\n\n".join(paras)
    index = ShingleIndex(text)
    chunks = _SpecialistBase._split_chunks(text, 20_000, 1_000)
    assert len(chunks) > 1
    for chunk in chunks:
        result = match_ranges(index, "SYSTEM\n" + chunk)
        ranges = result["ranges"]
        assert ranges
        assert all(0 <= a < b <= len(text) for a, b in ranges)
        covered = bytearray(len(text))
        for a, b in ranges:
            covered[a:b] = b"\x01" * (b - a)
        for para in chunk.split("\n\n"):
            if not para.strip():
                continue
            pos = text.find(para)
            assert pos >= 0
            for k, ch in enumerate(para):
                if not ch.isspace():
                    assert covered[pos + k], (pos + k, para[:20])


def test_unrelated_request_has_no_ranges():
    index = ShingleIndex(_numbered_text(50_000))
    result = match_ranges(index, "Z" * 5_000 + "unrelated words " * 300)
    assert result["ranges"] == []
    assert result["matched_chars"] == 0
    assert result["skipped"] is None
    assert result["request_chars"] > 0


def test_empty_or_missing_text_is_skipped():
    for text in ("", None):
        result = match_ranges(ShingleIndex(text), "anything at all " * 20)
        assert result["skipped"] == "no_text"
        assert result["ranges"] == []
        assert result["matched_chars"] == 0
        assert result["doc_chars"] == 0


def test_oversized_input_is_skipped():
    big = "a" * (MAX_DOC_CHARS + 1)
    result = match_ranges(ShingleIndex(big), "a" * 100)
    assert result["skipped"] == "size"
    assert result["ranges"] == []

    # An oversized request is skipped too.
    small_index = ShingleIndex(_numbered_text(10_000))
    assert match_ranges(small_index, "b" * (MAX_DOC_CHARS + 1))["skipped"] == "size"

    # 2M-character document, 600k-character request: matching alone stays under 2 s.
    rng = random.Random(11)
    doc = rng.randbytes(1_000_000).hex()
    assert len(doc) == 2_000_000
    index = ShingleIndex(doc)
    parts: list[str] = []
    total = 0
    while total < 600_000:
        if rng.random() < 0.5:
            start = rng.randrange(0, len(doc) - 5_000)
            part = doc[start : start + rng.randrange(60, 5_000)]
        else:
            part = "~" + rng.randbytes(rng.randrange(30, 200)).hex()
        parts.append(part)
        total += len(part)
    request = "".join(parts)[:600_000]
    t0 = time.perf_counter()
    result = match_ranges(index, request)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, elapsed
    assert result["skipped"] is None
    assert result["matched_chars"] > 0

    # Worst case for a scan: nothing ever matches.
    miss = ("~" + rng.randbytes(300_000).hex())[:600_000]
    t0 = time.perf_counter()
    result = match_ranges(index, miss)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, elapsed
    assert result["ranges"] == []


def test_ranges_are_capped_and_merged():
    rng = random.Random(5)
    blocks = [rng.randbytes(40).hex() for _ in range(200)]
    assert all(len(b) > SHINGLE + 16 for b in blocks)
    # Gaps of different sizes between blocks in the document.
    doc = "".join(b + ("#" * (1 + i % 9)) + rng.randbytes(5).hex() for i, b in enumerate(blocks))
    request = "".join(f"<<{i}>>" + b for i, b in enumerate(blocks))
    result = match_ranges(ShingleIndex(doc), request)
    ranges = result["ranges"]
    assert 0 < len(ranges) <= MAX_RANGES
    assert ranges == sorted(ranges)
    for (_, e1), (s2, _) in zip(ranges, ranges[1:]):
        assert e1 < s2
    # Every block remains covered after merging.
    covered = bytearray(len(doc))
    for a, b in ranges:
        covered[a:b] = b"\x01" * (b - a)
    for b in blocks:
        pos = doc.find(b)
        assert all(covered[pos : pos + len(b)])
    assert result["matched_chars"] == sum(len(b) for b in blocks)


def _covered(ranges, n):
    cov = bytearray(n)
    for a, b in ranges:
        cov[a:b] = b"\x01" * (b - a)
    return cov


def test_short_paragraphs_in_split_chunks_are_covered():
    rng = random.Random(9)
    heads = ["ARTICLE II", "1.2 Term", "2026-11-25", "Section 4", "Recitals"]
    paras: list[str] = []
    for i in range(300):
        paras.append(f"{heads[i % 5]} #{i}")
        paras.append("   ")
        paras.append("")
        paras.append(f"Body {i}: " + rng.randbytes(45).hex())
    text = "\n\n".join(paras)
    index = ShingleIndex(text)
    chunks = _SpecialistBase._split_chunks(text, 20_000, 1_000)
    assert len(chunks) > 1
    for chunk in chunks:
        result = match_ranges(index, "SYSTEM\n\n" + chunk)
        cov = _covered(result["ranges"], len(text))
        for para in chunk.split("\n\n"):
            if not para.strip():
                continue
            pos = text.find(para)
            assert pos >= 0
            for k, ch in enumerate(para):
                if not ch.isspace():
                    assert cov[pos + k], (pos + k, para[:30])


def test_short_quoted_value_unique_is_mapped():
    text = _numbered_text(30_000)
    value = "Zebulon Quarry Ltd.!"  # 20 chars, appears once
    pos = 12_345
    text = text[:pos] + value + text[pos:]
    result = match_ranges(ShingleIndex(text), "Extract the party named below.\n\n" + value)
    assert result["ranges"] == [[pos, pos + len(value)]]
    assert result["matched_chars"] == len(value)


def test_short_ambiguous_value_is_not_mapped():
    text = _numbered_text(30_000)
    value = "Zebulon Quarry Ltd.!"
    assert len(value) == 20
    text = text[:5_000] + value + text[5_000:20_000] + value + text[20_000:]
    result = match_ranges(ShingleIndex(text), "Extract the party named below.\n\n" + value)
    assert result["ranges"] == []
    assert result["matched_chars"] == 0


def test_repeated_boilerplate_attributes_in_order():
    block = "BOILERPLATE: " + "the parties agree to the standard terms of this schedule. " * 2
    block = block[:100]
    assert len(block) == 100
    pieces = []
    starts = []
    pos = 0
    for i in range(12):
        line = f"Distinct line number {i} with unique tail {i * 7919:06d}\n"
        pieces.append(line)
        pos += len(line)
        starts.append(pos)
        pieces.append(block + "\n")
        pos += len(block) + 1
    doc = "".join(pieces)
    s9 = starts[9]
    request = doc[s9 - 20 : s9 + 100 + 20]
    result = match_ranges(ShingleIndex(doc), request)
    ranges = result["ranges"]
    assert ranges
    assert ranges[0][0] <= s9 and ranges[-1][1] >= s9 + 100
    assert all(s9 - 20 <= a and b <= s9 + 120 for a, b in ranges)

    # Sequential reading through repeats lands on the next occurrence, not the first.
    reads = doc[starts[3] - 60 : starts[3] + 100] + "\n#\n" + block
    result = match_ranges(ShingleIndex(doc), reads)
    assert any(a <= starts[4] and b >= starts[4] + 100 for a, b in result["ranges"])
    assert not any(a <= starts[0] and b >= starts[0] + 100 for a, b in result["ranges"])
