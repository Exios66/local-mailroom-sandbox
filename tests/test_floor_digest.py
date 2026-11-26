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
