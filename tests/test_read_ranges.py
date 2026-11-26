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
    # Capping merged the smallest gaps: the ranges span unread text and say so.
    assert result["ranges_approx"] is True


def test_uncapped_ranges_are_exact():
    result = match_ranges(ShingleIndex("abc def ghi jkl mno pqr"), "abc def ghi jkl mno pqr")
    assert result["ranges_approx"] is False


def test_candidate_rotation_stays_in_order_without_copying_the_whole_list():
    """A repetitive document with more candidates than the cap: matches stay in document order."""
    doc = ("AB" * 24) * 500
    request = doc[:2000]
    result = match_ranges(ShingleIndex(doc), request)
    assert result["matched_chars"] > 0
    assert result["ranges"] == sorted(result["ranges"])


def test_oversized_gap_pieces_count_as_unplaced():
    """A request gap too large to scan keeps its pieces unmeasured, not silently covered."""
    left, right = "Q" * 100, "Z" * 100
    gap = "unmatchedword " * 6_000  # 78,000 chars > _MAX_GAP_CHARS
    doc = left + "\n\n" + right
    request = left + "\n\n" + gap + "\n\n" + right
    result = match_ranges(ShingleIndex(doc), request)
    assert result["unplaced_pieces"] >= 1
    assert result["matched_chars"] > 0


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


def test_header_glued_by_single_newline_is_covered():
    rng = random.Random(21)
    prefix = "".join(f"Intro line {i} " + rng.randbytes(20).hex() + "\n\n" for i in range(40))
    body = "\n\n".join(rng.randbytes(40).hex() for _ in range(10))
    # The document has a whitespace-only paragraph the request omits, so the
    # short heading does not connect to the body and only the label-line split finds it.
    doc = prefix + "ARTICLE II\n\n   \n\n" + body + "\n\n" + rng.randbytes(40).hex()
    window = "ARTICLE II\n\n" + body
    start = len(prefix)
    request = "File: x.txt\n\nDocument text:\n" + window
    result = match_ranges(ShingleIndex(doc), request)
    assert any(a == start for a, _ in result["ranges"]), result["ranges"]
    assert all(a >= start for a, _ in result["ranges"])
    assert result["ranges"][0][1] == start + len("ARTICLE II")


def test_window_edge_whitespace_is_trimmed():
    text = _numbered_text(60_000)
    a = text.index("\n\n", 10_000) + 2
    b = text.index("\n\n", 40_000)
    window = text[a - 2 : b + 2]  # contiguous slice that starts and ends in "\n\n"
    assert window.startswith("\n\n") and window.endswith("\n\n")
    result = match_ranges(ShingleIndex(text), "Document text:\n" + window)
    assert result["ranges"] == [[a, b]]
    assert result["matched_chars"] == b - a


def test_many_small_gaps_stay_within_bound():
    rng = random.Random(1)
    doc = " ".join(rng.randbytes(5).hex() for _ in range(400_000))[:2_000_000]
    index = ShingleIndex(doc)

    # 1. Doc slices alternating with short unmatched lines, 600k characters.
    parts: list[str] = []
    total = 0
    while total < 600_000:
        s = rng.randrange(0, len(doc) - 200)
        parts.append(doc[s : s + 100])
        parts.append("\n\nzzjunk" + rng.randbytes(4).hex() + "\n\n")
        total += 120
    alternating = "".join(parts)
    # 2. Thousands of short unmatched lines in one gap just under 64k, no bulk match.
    lines = "\n\n".join("junkline number %d abc" % i for i in range(2500))
    # 3. The same lines after one bulk match.
    anchored = doc[1000:1200] + "\n\n" + lines

    timings = {}
    results = {}
    for name, request in (("alternating", alternating), ("lines", lines), ("anchored", anchored)):
        t0 = time.perf_counter()
        results[name] = match_ranges(index, request)
        timings[name] = time.perf_counter() - t0
    for name, elapsed in timings.items():
        assert elapsed < 2.0, (name, timings)
    assert results["alternating"]["unplaced_pieces"] > 0
    assert results["alternating"]["skipped"] is None
    assert results["anchored"]["matched_chars"] >= 190
    assert match_ranges(ShingleIndex(None), "x" * 100)["unplaced_pieces"] == 0


# --- context and recorder (Task 2) -------------------------------------------

import json  # noqa: E402
import threading  # noqa: E402

from mailroom_sandbox.job import read_ranges  # noqa: E402
from mailroom_sandbox.job.checkpoint import RunStore  # noqa: E402


def _doc(n: int = 2000, seed: int = 3) -> str:
    return _numbered_text(n, seed)


def test_working_text_replaces_raw_basis():
    raw = _doc(1500, seed=1)
    working = _doc(1500, seed=2)
    out: list[dict] = []
    texts: list[tuple[str, str]] = []
    with read_ranges.document("d1", raw, out.append, lambda d, t: texts.append((d, t))):
        read_ranges.record("sorter", "Document text:\n" + raw[100:700], node="classify")
        read_ranges.set_working_text(working)
        read_ranges.record("sorter", "Document text:\n" + working[200:900], node="classify")
    assert [r["basis"] for r in out] == ["raw", "working"]
    assert [r["call"] for r in out] == [1, 2]
    assert out[0]["ranges"] == [[100, 700]]
    assert out[1]["ranges"] == [[200, 900]]
    assert out[1]["doc"] == "d1" and out[1]["agent"] == "sorter" and out[1]["node"] == "classify"
    assert isinstance(out[1]["ts"], float) and "unplaced_pieces" in out[1]
    assert texts == [("d1", working)]  # handed to the text sink exactly once
    read_ranges.set_working_text(working)  # outside a scope: no-op
    assert texts == [("d1", working)]


def test_recording_errors_never_raise():
    def bad_sink(rec):
        raise RuntimeError("disk full")

    with read_ranges.document("d2", _doc(), bad_sink, lambda d, t: None):
        assert read_ranges.record("sorter", "anything") is None
        assert read_ranges.stats()["read_errors"] == 1
        assert read_ranges.stats()["read_calls"] == 1
    # a failing text sink is swallowed and counted too
    def bad_text(d, t):
        raise OSError("nope")

    with read_ranges.document("d3", _doc(), lambda r: None, bad_text):
        read_ranges.set_working_text(_doc())
        assert read_ranges.stats()["read_errors"] == 1


def test_no_sink_is_a_noop_and_outside_scope_is_a_noop():
    assert read_ranges.record("sorter", "x") is None
    assert read_ranges.current_node() is None
    assert read_ranges.stats() == {"read_calls": 0, "read_errors": 0, "read_ms": 0.0}
    with read_ranges.document("d4", _doc(), None, None):
        read_ranges.record("sorter", "x")
        assert read_ranges.stats()["read_calls"] == 0


def test_contexts_are_per_thread():
    results: dict[str, list[dict]] = {}
    errors: list[BaseException] = []

    def work(name: str) -> None:
        try:
            text = _doc(3000, seed=hash(name) % 1000)
            out: list[dict] = []
            with read_ranges.document(name, text, out.append, lambda d, t: None):
                for k in range(50):
                    read_ranges.record("sorter", "Document text:\n" + text[k : k + 400])
            results[name] = out
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    for name, out in results.items():
        assert len(out) == 50
        assert {r["doc"] for r in out} == {name}
        assert [r["call"] for r in out] == list(range(1, 51))


def test_mutation_in_a_copied_context_reaches_the_document():
    import contextvars

    text = _doc()
    out: list[dict] = []
    with read_ranges.document("d5", text, out.append, lambda d, t: None):
        ctx = contextvars.copy_context()
        ctx.run(read_ranges._enter_node, "classify")
        ctx.run(read_ranges.record, "sorter", "Document text:\n" + text[:500])
        assert read_ranges.current_node() == "classify"
        ctx.run(read_ranges._exit_node, "classify")
        assert read_ranges.current_node() is None
    assert out[0]["node"] == "classify"


def test_reads_hold_no_text(tmp_path):
    text = _doc(4000)
    store = RunStore(tmp_path / "run")
    with read_ranges.document("../weird/id", text, store.append_read, store.write_doc_text):
        read_ranges.set_working_text(text)
        read_ranges.record("sorter", "Document text:\n" + text[100:1900] + "\nTASK " * 40)
    lines = [json.loads(ln) for ln in store.reads_path.read_text().splitlines()]
    assert len(lines) == 1

    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)

    assert all(len(s) <= 64 for s in strings(lines[0]))


def test_doc_text_files_never_use_the_raw_doc_id(tmp_path):
    import hashlib

    store = RunStore(tmp_path / "run")
    store.write_doc_text("../../etc/x", "hello")
    store.write_doc_text("../../etc/x", "hello")  # idempotent
    name = hashlib.sha1(b"../../etc/x").hexdigest()[:16] + ".txt"
    d = store.dir / "doc_texts"
    assert (d / name).read_text(encoding="utf-8") == "hello"
    index = [json.loads(ln) for ln in (d / "index.jsonl").read_text().splitlines()]
    assert index == [{"doc": "../../etc/x", "file": name, "text_hash": read_ranges.text_hash("hello")}]
    assert sorted(p.name for p in d.iterdir()) == sorted([name, "index.jsonl"])


def _index_rows(store):
    path = store.doc_texts_dir / "index.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _stored_text(store, doc):
    import hashlib

    name = hashlib.sha1(doc.encode(), usedforsecurity=False).hexdigest()[:16] + ".txt"
    return (store.doc_texts_dir / name).read_bytes().decode("utf-8")


def test_resumed_document_keeps_the_last_attempts_text_and_one_index_entry(tmp_path):
    """Two attempts (a resume opens a new store object) leave attempt 2's text, paired with its doc_chars."""
    from mailroom_sandbox.tui import floor_app

    first, second = _doc(480, seed=11), _doc(920, seed=12)
    run_dir = tmp_path / "run"
    for attempt, text in ((1, first), (2, second)):
        store = RunStore(run_dir)  # a resume is a new process: a new store object over the same directory
        with read_ranges.document("d1", text, store.append_read, store.write_doc_text):
            read_ranges.set_working_text(text)
            read_ranges.record("sorter", "Document text:\n" + text[10:300])
    store = RunStore(run_dir)
    assert _stored_text(store, "d1") == second
    assert [r["doc"] for r in _index_rows(store)] == ["d1"]
    assert sorted(p.name for p in store.doc_texts_dir.iterdir()) == sorted(
        [_index_rows(store)[0]["file"], "index.jsonl"]), "no temp file is left behind"
    # the digest keeps attempt 2's sequence, so its doc_chars is the stored text's length
    (run_dir / "items.jsonl").write_text(json.dumps({"item_id": "d1", "ok": True}) + "\n")
    (run_dir / "nodes.jsonl").write_text("")
    (run_dir / "dataset.jsonl").write_text(json.dumps({"id": "d1", "doc_text": second}) + "\n")
    run, _ = floor_app.load_builder().build_run("run", run_dir, set())
    reads = next(r for r in run["docs"] if r["id"] == "d1")["debug"]["reads"]
    assert reads["doc_chars"] == len(_stored_text(store, "d1")) == 920


def test_read_records_carry_the_text_hash_the_index_and_file_agree_on(tmp_path):
    text = _doc(1500, seed=21)
    store = RunStore(tmp_path / "run")
    with read_ranges.document("d1", text, store.append_read, store.write_doc_text):
        read_ranges.record("intake", "Document text:\n" + text[:300])  # raw basis: no hash
        read_ranges.set_working_text(text)
        read_ranges.record("sorter", "Document text:\n" + text[10:400])
    raw, working = [json.loads(ln) for ln in store.reads_path.read_text().splitlines()]
    assert raw["basis"] == "raw" and "text_hash" not in raw
    assert working["basis"] == "working" and working["text_hash"] == read_ranges.text_hash(text)
    assert _index_rows(store)[0]["text_hash"] == working["text_hash"]
    assert read_ranges.text_hash(_stored_text(store, "d1")) == working["text_hash"]


def test_equal_length_resume_that_dies_before_any_read_is_withheld(tmp_path):
    """Attempt 2 rewrites the text (same length) and dies before a read record: attempt 1's ranges must not pair."""
    from mailroom_sandbox.tui import floor_app

    first = _doc(600, seed=31)
    second = _doc(600, seed=32)
    assert len(first) == len(second) and first != second
    run_dir = tmp_path / "run"
    store = RunStore(run_dir)
    with read_ranges.document("d1", first, store.append_read, store.write_doc_text):
        read_ranges.set_working_text(first)
        read_ranges.record("sorter", "Document text:\n" + first[10:300])
    resumed = RunStore(run_dir)
    with read_ranges.document("d1", second, resumed.append_read, resumed.write_doc_text):
        read_ranges.set_working_text(second)  # the attempt dies here, before any record
    assert _stored_text(resumed, "d1") == second
    assert [r["text_hash"] for r in _index_rows(resumed)] == [read_ranges.text_hash(second)]
    (run_dir / "items.jsonl").write_text(json.dumps({"item_id": "d1", "ok": True}) + "\n")
    (run_dir / "nodes.jsonl").write_text("")
    (run_dir / "dataset.jsonl").write_text(json.dumps({"id": "d1", "doc_text": second}) + "\n")
    builder = floor_app.load_builder()
    reads = next(r for r in builder.build_run("run", run_dir, set())[0]["docs"] if r["id"] == "d1")["debug"]["reads"]
    assert reads["doc_chars"] == len(second)  # the length check alone would pass
    assert reads["text_pairing"] == "different"
    # and a normal resume whose attempt 2 did read is paired again
    with read_ranges.document("d1", second, resumed.append_read, resumed.write_doc_text):
        read_ranges.set_working_text(second)
        read_ranges.record("sorter", "Document text:\n" + second[10:300])
    reads = next(r for r in builder.build_run("run", run_dir, set())[0]["docs"] if r["id"] == "d1")["debug"]["reads"]
    assert reads["text_pairing"] == "match"


def test_missing_index_entry_is_repaired_without_duplicating(tmp_path):
    """An index append lost in a crash is added by the next write; a third write adds nothing."""
    run_dir = tmp_path / "run"
    store = RunStore(run_dir)
    store.write_doc_text("d1", "first")
    store.write_doc_text("d2", "other")
    (store.doc_texts_dir / "index.jsonl").write_text("")  # the crash lost both appends
    resumed = RunStore(run_dir)
    resumed.write_doc_text("d1", "second")
    assert [r["doc"] for r in _index_rows(resumed)] == ["d1"]
    resumed.write_doc_text("d1", "third")
    RunStore(run_dir).write_doc_text("d1", "fourth")
    assert [r["doc"] for r in _index_rows(resumed)] == ["d1"]
    assert _stored_text(resumed, "d1") == "fourth"
    # a torn last line (no newline) is not glued to the next entry
    (resumed.doc_texts_dir / "index.jsonl").write_text('{"doc": "d9", "fi')
    RunStore(run_dir).write_doc_text("d2", "x")
    rows = [ln for ln in (resumed.doc_texts_dir / "index.jsonl").read_text().splitlines()]
    assert json.loads(rows[-1])["doc"] == "d2" and rows[0] == '{"doc": "d9", "fi'


def test_legacy_index_line_without_a_hash_is_upgraded_in_place(tmp_path):
    """A store written before text_hash existed keeps one line per doc; the next write adds the hash."""
    run_dir = tmp_path / "run"
    store = RunStore(run_dir)
    store.write_doc_text("d1", "text")
    store.write_doc_text("d2", "other")
    index = store.doc_texts_dir / "index.jsonl"
    index.write_text("".join(json.dumps({k: v for k, v in r.items() if k != "text_hash"}) + "\n"
                             for r in _index_rows(store)))
    RunStore(run_dir).write_doc_text("d1", "text")
    rows = {r["doc"]: r for r in _index_rows(store)}
    assert sorted(rows) == ["d1", "d2"] and rows["d1"]["text_hash"] == read_ranges.text_hash("text")
    assert "text_hash" not in rows["d2"], "untouched documents keep their old line"


def test_doc_text_is_written_newline_exact(tmp_path):
    """CRLF and lone CR survive the write byte for byte, so offsets cannot shift on any platform."""
    store = RunStore(tmp_path / "run")
    text = "a\r\nb\rc\nd\u2028e \u00e9"
    store.write_doc_text("d1", text)
    assert _stored_text(store, "d1") == text
    assert (store.doc_texts_dir / _index_rows(store)[0]["file"]).read_bytes() == text.encode("utf-8")


# --- call observer ------------------------------------------------------------
import sys  # noqa: E402
import types  # noqa: E402

from mailroom_sandbox import sampling  # noqa: E402

_DOC = "".join(f"Clause {i}. " + "alpha beta gamma delta " * 6 + "\n\n" for i in range(40))


def _fake_target(monkeypatch, *, langchain: bool = False):
    calls: list[tuple] = []
    result = {"ok": True}

    if langchain:
        class Agent:
            agent_name = "contracts_specialist"
            model = "m"

            def system_prompt(self):
                return "SYS"

            def _call_structured(self, user_message, json_schema, system_prompt=None,
                                 temperature=None, max_tokens=None, pages=None):
                calls.append((user_message, json_schema, system_prompt, temperature))
                return result
        module = "langchain_agents.base_agent"
    else:
        class Agent:  # type: ignore[no-redef]
            agent_name = "sorter"
            system_prompt = "SYSTEM TEXT"

            def _call_structured(self, user_message, json_schema, temperature=0.1,
                                 system_prompt=None, max_tokens=None, reasoning_effort=None, pages=None):
                calls.append((user_message, json_schema, temperature, system_prompt))
                return result
        module = "fake_obs_agents"

    fake = types.ModuleType(module)
    fake.BaseAgent = Agent
    monkeypatch.setitem(sys.modules, module, fake)
    monkeypatch.setattr(sampling, "_TARGETS", ((module, "BaseAgent"),))
    monkeypatch.setattr(sampling, "_PATCHED", set())
    monkeypatch.setattr(sampling, "_OVERRIDES", {})
    monkeypatch.setattr(sampling, "_EXTRA", {})
    return Agent, calls, result


def _layers(fn):
    out = []
    while fn is not None:
        out.append(fn)
        fn = getattr(fn, "__wrapped__", None)
    return out


def test_observer_sees_every_call_and_changes_nothing(monkeypatch):
    Agent, calls, result = _fake_target(monkeypatch)
    original = Agent.__dict__["_call_structured"]
    assert read_ranges.install_call_observer() == 1
    assert read_ranges.install_call_observer() == 1  # idempotent
    assert Agent.__dict__["_call_structured"].__wrapped__ is original
    records: list[dict] = []
    schema = {"type": "object"}
    with read_ranges.document("d1", _DOC, records.append):
        out = Agent()._call_structured(_DOC[:300], schema, 0.5, max_tokens=7)
        out2 = Agent()._call_structured(user_message=_DOC[400:700], json_schema=schema)
    assert out is result and out2 is result
    assert calls == [(_DOC[:300], schema, 0.5, None), (_DOC[400:700], schema, 0.1, None)]
    assert len(records) == 2
    assert [r["agent"] for r in records] == ["sorter", "sorter"]
    assert records[0]["ranges"][0][0] == 0
    assert all("SYSTEM TEXT" not in json.dumps(r) for r in records)  # offsets only
    # outside a document nothing is recorded and the call still works
    assert Agent()._call_structured("x", schema) is result


def test_observer_never_calls_agent_methods(monkeypatch):
    Agent, calls, result = _fake_target(monkeypatch, langchain=True)
    counter = {"n": 0}

    def system_prompt(self):
        counter["n"] += 1
        raise RuntimeError("must not be called")

    Agent.system_prompt = system_prompt
    read_ranges.install_call_observer()
    records: list[dict] = []
    with read_ranges.document("d1", _DOC, records.append):
        assert Agent()._call_structured(_DOC[:300], {}) is result
    assert counter["n"] == 0 and len(calls) == 1 and len(records) == 1
    assert records[0]["request_chars"] == len("contracts_specialist\n\n") + 300


def test_observer_passes_exceptions_through_and_never_raises_itself(monkeypatch):
    Agent, calls, _ = _fake_target(monkeypatch)
    read_ranges.install_call_observer()

    def boom(*a, **k):
        raise RuntimeError("sink down")

    with read_ranges.document("d1", _DOC, boom):
        Agent()._call_structured(_DOC[:300], {})  # sink failure is swallowed
        Agent()._call_structured(object(), {})  # non-string request is tolerated
    assert len(calls) == 2
    assert read_ranges.stats()["read_calls"] == 0  # no active document: zeros


def test_observer_stays_outermost_across_reactivation(monkeypatch):
    Agent, calls, _ = _fake_target(monkeypatch)
    knobs = {"sorter": {"temperature": 0.7}}

    def sampling_layers():
        return [f for f in _layers(Agent.__dict__["_call_structured"])
                if f.__dict__.get("__sandbox_sampling__") and not read_ranges.is_observer(f)]

    for step in ("none", "on", "off", "on", "on"):
        sampling.apply_sampling_overrides(knobs if step == "on" else None)
        read_ranges.install_call_observer()
        top = Agent.__dict__["_call_structured"]
        assert read_ranges.is_observer(top)
        assert sum(read_ranges.is_observer(f) for f in _layers(top)) == 1
        if step == "on":
            assert len(sampling_layers()) == 1
            assert not read_ranges.is_observer(top.__wrapped__)
    # sampling installed beneath an existing observer, not in front of it
    sampling._PATCHED.clear()
    sampling.apply_sampling_overrides(knobs)
    assert read_ranges.is_observer(Agent.__dict__["_call_structured"])
    assert len(sampling_layers()) == 1
    records: list[dict] = []
    with read_ranges.document("d1", _DOC, records.append):
        Agent()._call_structured(_DOC[:300], {}, 0.1)
    assert calls[-1][2] == 0.7 and len(records) == 1


def test_native_endpoint_calls_are_seen(monkeypatch):
    Agent, calls, _ = _fake_target(monkeypatch, langchain=True)
    seen: list = []

    def fake_native(self, bound, override):
        seen.append(bound.arguments["user_message"])
        return {"native": True}

    monkeypatch.setattr(sampling, "_native_structured_completion", fake_native)
    sampling.apply_sampling_overrides({"contracts_specialist": {"max_tokens": 8192, "top_p": 0.8}})
    read_ranges.install_call_observer()
    records: list[dict] = []
    with read_ranges.document("d1", _DOC, records.append):
        out = Agent()._call_structured(_DOC[:300], {})
    assert out == {"native": True} and seen == [_DOC[:300]] and calls == []
    assert len(records) == 1 and records[0]["agent"] == "contracts_specialist"


# --- chat reads and the call guard ------------------------------------------------
# A request the run cap or the document ceiling refuses never goes out, so it is never "read"
# (the Decisions path has the same rule). Guarded calls record once the guard admits them; calls
# with no guard in their path (non-OpenRouter, the native endpoint) record when the call returns.
import pytest  # noqa: E402

from mailroom_sandbox import provider_pins  # noqa: E402
from mailroom_sandbox.job import api_budget, call_guard  # noqa: E402


class _GuardClient:
    def __init__(self, base_url):
        self.base_url = base_url


@pytest.fixture
def guarded_agent(monkeypatch):
    """A fake vendored agent whose ``_call_structured`` goes through the real provider-pin wrapper."""
    sent: list[dict] = []

    def original(client, **kwargs):
        sent.append(kwargs)
        return types.SimpleNamespace(model=kwargs.get("model"), model_extra={"provider": "P"})

    retry = types.ModuleType("llm.retry")
    retry.retry_chat_completion = original
    llm = types.ModuleType("llm")
    llm.retry = retry
    base = types.ModuleType("agents.base")
    base.retry_chat_completion = original
    agents = types.ModuleType("agents")
    agents.base = base
    lc_base = types.ModuleType("langchain_agents.base_agent")
    lc_base.ChatOpenAI = type("ChatOpenAI", (), {})
    lc = types.ModuleType("langchain_agents")
    lc.base_agent = lc_base
    for name, mod in (("llm", llm), ("llm.retry", retry), ("agents", agents), ("agents.base", base),
                      ("langchain_agents", lc), ("langchain_agents.base_agent", lc_base)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(provider_pins, "_ORIGINAL", None)
    monkeypatch.setattr(provider_pins, "_LC_ORIGINAL", None)
    provider_pins.apply_provider_pins({})

    Agent, _calls, _result = _fake_target(monkeypatch)

    def _call_structured(self, user_message, json_schema, temperature=0.1, system_prompt=None,
                         max_tokens=None, reasoning_effort=None, pages=None):
        # What the vendored agent does: one logical call, possibly several completions inside it.
        for _ in range(self.completions):
            base.retry_chat_completion(self.client, model="vendor/model", messages=[])
        return {"ok": True}

    Agent.completions = 1
    Agent.client = _GuardClient("https://openrouter.ai/api/v1")
    Agent._call_structured = _call_structured
    read_ranges.install_call_observer()
    call_guard.disarm()
    yield Agent, sent
    call_guard.disarm()
    provider_pins.restore()


def _guard(cap: float, ceiling: int = 40) -> None:
    call_guard.arm(api_budget.ApiBudget(cap, 0.10, 0.25, ["qwen/qwen3.5-9b"]), ceiling=ceiling)


def test_a_chat_call_the_guard_refuses_records_no_read(guarded_agent):
    Agent, sent = guarded_agent
    _guard(cap=0.05)
    call_guard._STATE["budget"].add_usage({"prompt_tokens": 600_000, "completion_tokens": 1})  # past the cap
    records: list[dict] = []
    with call_guard.document(), read_ranges.document("d1", _DOC, records.append):
        with pytest.raises(Exception, match="call refused"):
            Agent()._call_structured(_DOC[:300], {})
        assert read_ranges.stats()["read_calls"] == 0
    assert records == [] and sent == []  # nothing recorded, nothing sent


def test_a_chat_call_the_guard_admits_records_one_read_per_logical_call(guarded_agent):
    Agent, sent = guarded_agent
    Agent.completions = 3  # retries inside one logical call
    _guard(cap=1_000.0)
    records: list[dict] = []
    with call_guard.document(), read_ranges.document("d1", _DOC, records.append):
        Agent()._call_structured(_DOC[:300], {})
    assert len(sent) == 3 and len(records) == 1
    assert records[0]["agent"] == "sorter" and records[0]["call"] == 1 and records[0]["ranges"][0][0] == 0


def test_the_per_document_ceiling_refusal_is_not_a_read_either(guarded_agent):
    Agent, sent = guarded_agent
    _guard(cap=1_000.0, ceiling=1)
    records: list[dict] = []
    with call_guard.document(), read_ranges.document("d1", _DOC, records.append):
        Agent()._call_structured(_DOC[:300], {})
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 1})  # the first call finished
        with pytest.raises(Exception, match="per-document ceiling"):
            Agent()._call_structured(_DOC[400:700], {})
    assert len(sent) == 1 and len(records) == 1


def test_an_unguarded_chat_call_still_records_one_read(guarded_agent):
    Agent, sent = guarded_agent
    Agent.client = _GuardClient("https://example.modal.run/v1")  # not OpenRouter: no guard in the path
    _guard(cap=0.05)
    call_guard._STATE["budget"].add_usage({"prompt_tokens": 600_000, "completion_tokens": 1})
    records: list[dict] = []
    with call_guard.document(), read_ranges.document("d1", _DOC, records.append):
        Agent()._call_structured(_DOC[:300], {})
    assert len(sent) == 1 and len(records) == 1


def test_an_unguarded_chat_call_that_raises_is_still_recorded(guarded_agent):
    Agent, _sent = guarded_agent

    def failing(self, user_message, json_schema, **kw):
        raise RuntimeError("endpoint down")

    Agent._call_structured = failing
    read_ranges.install_call_observer()
    records: list[dict] = []
    with read_ranges.document("d1", _DOC, records.append):
        with pytest.raises(RuntimeError, match="endpoint down"):
            Agent()._call_structured(_DOC[:300], {})
    assert len(records) == 1  # the request went out; only a guard refusal means it did not


def test_short_candidate_lists_try_each_doc_position_once(monkeypatch):
    """The rotated candidate window never re-takes a position already in its suffix."""
    seen: list[tuple[int, int]] = []
    real = read_ranges._common_prefix

    def counting(a, ai, b, bi):
        seen.append((ai, bi))
        return real(a, ai, b, bi)

    monkeypatch.setattr(read_ranges, "_common_prefix", counting)
    size, stride = read_ranges.SHINGLE, read_ranges.STRIDE
    shingle = ("the quick brown fox jumps over the lazy dog " * 4)[:size]
    gap = "#" * (-(size + 7) % stride + 7)  # the second copy starts on the index's stride grid too
    doc = shingle + gap + shingle  # two indexed positions for the same shingle
    assert len(read_ranges.ShingleIndex(doc).table[shingle]) == 2
    request = "zz " + shingle + " yy"
    result = read_ranges.match_ranges(read_ranges.ShingleIndex(doc), request)
    assert result["ranges"] and result["matched_chars"] > 0
    assert seen and len(seen) == len(set(seen)), seen

