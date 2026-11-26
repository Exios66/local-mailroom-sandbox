"""The floor digest's deterministic selftest runs as part of the suite."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from mailroom_sandbox.tui import floor_app

SELFTEST = Path(__file__).resolve().parents[1] / "reports" / "dashboard" / "selftest_floor_digest.py"


def test_floor_digest_selftest_passes():
    """``selftest_floor_digest.py`` builds its fixtures and every check passes."""
    res = subprocess.run([sys.executable, str(SELFTEST)], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS" in res.stdout.splitlines()[-1], res.stdout


# ── debug.reads: numbers only, never document text ──────────────────────────────

WORKING = (
    "ALPHA AGREEMENT between Orion Holdings and Vega Capital dated March 3 2021. "
    "The borrower shall repay the principal sum of 4,500,000 dollars on or before "
    "the maturity date and in the manner described in schedule two attached hereto. "
    "Governing law is the law of the State of Delaware without regard to conflicts."
)


def _reads_run(root: Path, *, reads: list[dict] | None, text: str = WORKING) -> Path:
    """One run dir with a dataset row, an item, working text and (optionally) reads.jsonl."""
    run = root / "runtime" / "runs" / "run-r"
    (run / "doc_texts").mkdir(parents=True)
    (run / "items.jsonl").write_text(json.dumps({"item_id": "d1", "ok": True, "stage": "archived"}) + "\n")
    (run / "nodes.jsonl").write_text("")
    (run / "dataset.jsonl").write_text(json.dumps({"id": "d1", "doc_text": text, "expected_doc_class": "contract"}) + "\n")
    name = hashlib.sha1(b"d1").hexdigest()[:16] + ".txt"
    (run / "doc_texts" / name).write_text(text, encoding="utf-8")
    (run / "doc_texts" / "index.jsonl").write_text(json.dumps({"doc": "d1", "file": name}) + "\n")
    if reads is not None:
        (run / "reads.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reads) + "{torn\n")
    return run


def _read(call: int, agent: str, ranges, matched: int = 100, request: int = 120, **extra) -> dict:
    return {"doc": "d1", "call": call, "agent": agent, "node": "classify", "ts": 1.0 + call, "basis": "working",
            "ranges": ranges, "request_chars": request, "matched_chars": matched, "doc_chars": len(WORKING), **extra}


def _doc_row(run: dict) -> dict:
    return next(r for r in run["docs"] if r["id"] == "d1")


def test_digest_attaches_reads_without_text(tmp_path):
    """debug.reads carries ranges and counts only; no 40-character slice of the text reaches the digest."""
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[
        _read(1, "sorter", [[0, 60], [100, 140]]),
        _read(2, "sorter_reviewer", [[50, 90]], matched=40, request=45),
        _read(3, "sorter", [[130, 200]], matched=70, request=80, skipped="size"),
    ])
    run, _ = builder.build_run("run-r", run_dir, set())
    reads = _doc_row(run)["debug"]["reads"]
    assert [c["agent"] for c in reads["calls"]] == ["sorter", "sorter_reviewer", "sorter"]
    assert reads["calls"][0] == {"agent": "sorter", "node": "classify", "basis": "working",
                                 "ranges": [[0, 60], [100, 140]], "matched": 100, "request": 120}
    assert reads["calls"][2]["skipped"] == "size"
    assert reads["union"] == {"sorter": [[0, 60], [100, 200]], "sorter_reviewer": [[50, 90]]}
    assert reads["doc_chars"] == len(WORKING)
    digest = {"generated_utc": "x", "classes": [], "graph_reference": {}, "runs": [run]}
    out = tmp_path / "out"
    json_path, js_path = builder.write_outputs(digest, out)
    # the viewer's export embeds this same digest object, so the on-disk twins stand for it
    for blob in (json_path.read_text(encoding="utf-8"), js_path.read_text(encoding="utf-8"), json.dumps(digest)):
        leaked = [i for i in range(len(WORKING) - 40) if WORKING[i:i + 41] in blob]
        assert not leaked, f"working text leaked at offsets {leaked[:3]}"


def test_digest_omits_reads_when_not_recorded(tmp_path):
    """A run without reads.jsonl has no debug.reads key; the viewer says 'not recorded'."""
    builder = floor_app.load_builder()
    run, _ = builder.build_run("run-r", _reads_run(tmp_path, reads=None), set())
    assert "reads" not in _doc_row(run)["debug"]


def test_digest_dedupes_resumed_call_sequences(tmp_path):
    """A resumed document re-appends call=1..n; only its last sequence is kept."""
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[
        _read(1, "sorter", [[0, 10]]), _read(2, "specialist", [[0, 20]]), _read(3, "judge", [[0, 30]]),
        _read(1, "sorter", [[5, 50]]), _read(2, "specialist", [[60, 80]]),
    ])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert [(c["agent"], c["ranges"]) for c in reads["calls"]] == [("sorter", [[5, 50]]), ("specialist", [[60, 80]])]
    assert set(reads["union"]) == {"sorter", "specialist"}


def test_dedupe_resets_on_call_one_only(tmp_path):
    """Records of one attempt written out of order (concurrent calls) are not mistaken for a resume."""
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[
        _read(1, "sorter", [[0, 10]]), _read(3, "judge", [[0, 30]]), _read(2, "specialist", [[0, 20]]),
    ])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert [c["agent"] for c in reads["calls"]] == ["sorter", "judge", "specialist"]
    # a later attempt starts at call 1 again and supersedes all of it
    other = tmp_path / "other"
    run_dir = _reads_run(other, reads=[
        _read(1, "sorter", [[0, 10]]), _read(3, "judge", [[0, 30]]), _read(2, "specialist", [[0, 20]]),
        _read(1, "sorter", [[7, 9]]),
    ])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert [(c["agent"], c["ranges"]) for c in reads["calls"]] == [("sorter", [[7, 9]])]


def _tag(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def test_text_pairing_matches_when_the_stored_text_is_the_one_the_agents_saw(tmp_path):
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[_read(1, "sorter", [[0, 60]], text_hash=_tag(WORKING))])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert reads["text_pairing"] == "match"
    assert reads["calls"][0]["ranges"] == [[0, 60]]
    # the digest-side content tag is emitted so the viewer can pair the served text with the
    # ranges (a rewrite the digest has not rebuilt yet still refetches); not a secret
    assert reads["text_hash"] == _tag(WORKING)
    assert WORKING not in json.dumps(reads), "no text reaches the digest"


def test_digest_carries_unplaced_pieces_and_approximate_ranges(tmp_path):
    """A partly measured or capped call keeps its evidence about the coverage it cannot claim."""
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[
        _read(1, "sorter", [[0, 60]], unplaced_pieces=2),
        _read(2, "sorter", [[0, 60]], ranges_approx=True),
        _read(3, "sorter", [[0, 60]]),
    ])
    calls = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]["calls"]
    assert calls[0]["unplaced"] == 2 and "approx" not in calls[0]
    assert calls[1]["approx"] is True and "unplaced" not in calls[1]
    assert "unplaced" not in calls[2] and "approx" not in calls[2]


def test_text_pairing_flags_equal_length_different_text(tmp_path):
    """A later attempt rewrote the text to the same length: the length check cannot see it, the hash does."""
    builder = floor_app.load_builder()
    other = WORKING.replace("Orion", "Ozone")
    assert len(other) == len(WORKING) and other != WORKING
    run_dir = _reads_run(tmp_path, reads=[_read(1, "sorter", [[0, 60]], text_hash=_tag(other))])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert reads["text_pairing"] == "different"
    assert reads["doc_chars"] == len(WORKING)
    # the emitted hash is the STORED file's tag, not the records': a rewrite that outran its
    # records must not trip the viewer's served-text cache check
    assert reads["text_hash"] == _tag(WORKING)


def test_text_pairing_missing_text_and_old_stores(tmp_path):
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[_read(1, "sorter", [[0, 60]], text_hash=_tag(WORKING))])
    for f in (run_dir / "doc_texts").glob("*.txt"):
        f.unlink()
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert reads["text_pairing"] == "missing"
    # records without a hash (a store from before pairing) keep the length check alone: no verdict at all
    old = tmp_path / "old"
    run_dir = _reads_run(old, reads=[_read(1, "sorter", [[0, 60]])], text=WORKING.replace("Orion", "Ozone"))
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert "text_pairing" not in reads and reads["calls"][0]["ranges"] == [[0, 60]]
    # the stored file's own tag is still emitted for the viewer's served-text pairing
    assert reads["text_hash"] == _tag(WORKING.replace("Orion", "Ozone"))


def _many_docs_run(root: Path, n: int) -> Path:
    """A run with ``n`` documents, each with a stored text, a hashed read record and a torn tail."""
    run = root / "runtime" / "runs" / "run-many"
    (run / "doc_texts").mkdir(parents=True)
    lines = []
    for i in range(n):
        doc = f"doc{i}"
        text = f"{WORKING} number {i}"
        name = hashlib.sha1(doc.encode()).hexdigest()[:16] + ".txt"
        (run / "doc_texts" / name).write_text(text, encoding="utf-8")
        lines.append({**_read(1, "sorter", [[0, 10 + i]], text_hash=_tag(text)), "doc": doc})
        lines.append({**_read(2, "judge", [[5, 20 + i]], text_hash=_tag(text)), "doc": doc})
    (run / "reads.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines) + "{torn\n")
    return run


def test_reads_are_built_only_for_the_kept_documents(tmp_path, monkeypatch):
    """The digest keeps at most DOC_ROW_CAP rows: other documents are neither merged nor hashed."""
    builder = floor_app.load_builder()
    run_dir = _many_docs_run(tmp_path, 6)
    everyone = builder.read_ranges_by_doc(run_dir)
    assert set(everyone) == {f"doc{i}" for i in range(6)}

    hashed: list[int] = []
    real = builder._text_hash
    monkeypatch.setattr(builder, "_text_hash", lambda data: hashed.append(1) or real(data))
    kept = builder.read_ranges_by_doc(run_dir, {"doc1", "doc4", "not-in-the-file"})
    assert set(kept) == {"doc1", "doc4"} and len(hashed) == 2
    assert kept == {d: everyone[d] for d in ("doc1", "doc4")}  # identical output for a kept document
    assert builder.read_ranges_by_doc(run_dir, set()) == {}  # nothing kept: nothing built
    assert builder.read_ranges_by_doc(tmp_path, {"doc1"}) is None  # no reads.jsonl stays "not recorded"


def test_build_run_asks_only_for_the_kept_rows(tmp_path, monkeypatch):
    builder = floor_app.load_builder()
    seen: list = []
    real = builder.read_ranges_by_doc

    def spy(path, docs=None):
        seen.append(docs)
        return real(path, docs)

    monkeypatch.setattr(builder, "read_ranges_by_doc", spy)
    run_dir = _reads_run(tmp_path, reads=[_read(1, "sorter", [[0, 60]], text_hash=_tag(WORKING)),
                                          {**_read(1, "sorter", [[0, 9]]), "doc": "other-doc"}])
    run, _ = builder.build_run("run-r", run_dir, set())
    assert seen == [{row["id"] for row in run["docs"]}]
    assert _doc_row(run)["debug"]["reads"]["text_pairing"] == "match"


def test_digest_and_recorder_hash_the_same_way():
    from mailroom_sandbox.job import read_ranges

    builder = floor_app.load_builder()
    for text in ("", "plain", "a\r\nb\rc", "caf\u00e9 \u2028"):
        assert builder._text_hash(text.encode("utf-8")) == read_ranges.text_hash(text)


def test_doc_chars_comes_from_working_basis_calls_only(tmp_path):
    """A raw-basis call indexes the raw text; its length must not stand for the working text."""
    builder = floor_app.load_builder()
    raw = _read(1, "intake", [[0, 5]], basis="raw", doc_chars=30)
    working = _read(2, "sorter", [[0, 5]], doc_chars=17)
    run_dir = _reads_run(tmp_path, reads=[raw, working])
    assert _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]["doc_chars"] == 17
    # the final working call of the kept sequence wins when working calls disagree
    other = tmp_path / "other"
    run_dir = _reads_run(other, reads=[raw, _read(2, "sorter", [[0, 5]], doc_chars=17), _read(3, "judge", [[0, 5]], doc_chars=19)])
    assert _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]["doc_chars"] == 19


def test_doc_chars_is_null_without_a_working_basis_call(tmp_path):
    """Only raw calls: the working length is unknown, so null (never the raw length)."""
    builder = floor_app.load_builder()
    run_dir = _reads_run(tmp_path, reads=[_read(1, "intake", [[0, 5]], basis="raw", doc_chars=30)])
    reads = _doc_row(builder.build_run("run-r", run_dir, set())[0])["debug"]["reads"]
    assert reads["doc_chars"] is None
