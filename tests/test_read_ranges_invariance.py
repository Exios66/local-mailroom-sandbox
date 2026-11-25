"""Recording read ranges never changes a run (``job.trace_reads`` on versus off)."""
from __future__ import annotations

import json
import time

import pytest

from mailroom_sandbox.job import preflight, runner
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir

pytestmark = pytest.mark.usefixtures("job_data_dir")

# Wall-clock keys only: they differ between any two runs. No content key is dropped.
# ``started_at_ns`` / ``finished_at_ns`` are the item rows' monotonic-epoch stamps (the brief's
# ``started_ns`` / ``ended_ns``); both spellings are wall-clock.
_VOLATILE = {"ts", "ms", "latency_ms", "started_ns", "ended_ns", "started_at_ns", "finished_at_ns"}
_ITEM_ONLY = {"reads"}  # the item's recorded read statistics: the feature's own output


def _long_text(n: int = 150_000) -> str:
    """Deterministic paragraphs, so the splitter has boundaries and windowing fires."""
    para = "The parties agree to the merger terms set out in section {i} of this agreement. " * 6
    out, i = [], 0
    while sum(len(p) + 2 for p in out) < n:
        out.append(para.format(i=i))
        i += 1
    return "\n\n".join(out)[:n]


def _rows():
    rows = [
        {"id": "d0", "filename": "d0.txt", "doc_text": "Claim number 123 for an auto accident on 2024-01-01.",
         "expected": "insurance_claim", "expected_subclass": "auto"},
        {"id": "d1", "filename": "d1.txt", "doc_text": "This service agreement is made between Acme and Beta.",
         "expected": "contract", "expected_subclass": "service"},
        {"id": "d2", "filename": "d2.txt", "doc_text": "Auto claim, policy 99, collision damage reported.",
         "expected": "insurance_claim", "expected_subclass": "auto"},
        {"id": "dlong", "filename": "dlong.txt", "doc_text": _long_text(),
         "expected": "merger_agreement"},
    ]
    return rows


def _store(tmp_path, monkeypatch, label, trace_reads):
    """Prepare the same run id under its own base dir, so ids and paths match across arms."""
    base = tmp_path / label
    base.mkdir()
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(base))
    run_id = "run-reads-inv"
    path = base / "rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in _rows()), encoding="utf-8")
    spec = RunSpec(
        run_id=run_id,
        task="pipeline",
        dataset=DatasetSpec(local_path=f"file://{path}", limit=len(_rows())),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        job={"mock": True, "trace_reads": trace_reads},
    )
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    return RunStore(run_dir(report["run_id"]))


def _clean(rows, drop):
    return [{k: v for k, v in r.items() if k not in drop} for r in rows]


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_recording_on_and_off_give_identical_results(tmp_path, monkeypatch):
    t0 = time.monotonic()
    on = _store(tmp_path, monkeypatch, "on", True)
    assert runner.run_job(on, mock=None)["state"] == "done"
    off = _store(tmp_path, monkeypatch, "off", False)
    assert runner.run_job(off, mock=None)["state"] == "done"
    print(f"invariance wall seconds: {time.monotonic() - t0:.1f}")

    items_on, items_off = on.load_items(), off.load_items()
    assert len(items_on) == len(items_off) == 4
    key = lambda r: str(r.get("item_id"))  # noqa: E731
    assert (_clean(sorted(items_on, key=key), _VOLATILE | _ITEM_ONLY)
            == _clean(sorted(items_off, key=key), _VOLATILE))

    nodes_on, nodes_off = _jsonl(on.nodes_path), _jsonl(off.nodes_path)
    assert nodes_on, "the real graph must have written node records"
    sk = lambda r: json.dumps(r, sort_keys=True)  # noqa: E731
    assert (sorted(map(sk, _clean(nodes_on, _VOLATILE))) == sorted(map(sk, _clean(nodes_off, _VOLATILE))))

    # Only the on-run records ranges and working text.
    reads = _jsonl(on.reads_path)
    assert {r.get("doc") for r in reads} >= {"d0", "d1", "d2", "dlong"}
    assert (on.dir / "doc_texts").is_dir()
    assert not off.reads_path.exists()
    assert not (off.dir / "doc_texts").exists()
    assert all("reads" not in i for i in items_off)

    # The long row really was windowed. The sorter slides windows of its configured input cap (read
    # the way the agent reads it); each window is one ``classify`` request, so one agent has many
    # calls with distinct ranges, none holds the whole text, and together they span far more than
    # one window.
    from pipeline.config import get_agent_config  # type: ignore

    cap = int(get_agent_config("sorter")["max_input_chars"])
    sorter = [r for r in reads if r.get("doc") == "dlong" and r.get("agent") == "sorter"
              and r.get("node") == "classify"]
    # The working text is the intake node's cleaned text, so its length is read from the records.
    (doc_chars,) = {r["doc_chars"] for r in sorter}
    assert doc_chars > 100_000
    assert len(sorter) >= -(-doc_chars // cap), (len(sorter), cap)  # at least one call per cap-sized slice
    assert len({r["call"] for r in sorter}) == len(sorter)
    assert len({json.dumps(r["ranges"]) for r in sorter}) == len(sorter), "windows must read distinct ranges"
    assert all(r["matched_chars"] <= cap for r in sorter), "no request was the whole text"
    merged, end = 0, -1
    for lo, hi in sorted(rg for r in sorter for rg in r["ranges"]):
        merged += max(0, hi - max(lo, end))
        end = max(end, hi)
    assert merged > cap, (merged, cap)

    # No document text anywhere in the on-run's persisted records.
    probe = _long_text()[60_000:60_060]
    assert len(probe) >= 40
    for path in (on.items_path, on.nodes_path, on.reads_path):
        assert probe not in path.read_text(encoding="utf-8"), path.name


def test_a_raising_matcher_leaves_the_document_unchanged(tmp_path, monkeypatch):
    from mailroom_sandbox.job import read_ranges

    def boom(*_a, **_k):
        raise RuntimeError("matcher exploded")

    off = _store(tmp_path, monkeypatch, "off", False)
    assert runner.run_job(off, mock=None)["state"] == "done"
    monkeypatch.setattr(read_ranges, "match_ranges", boom)
    on = _store(tmp_path, monkeypatch, "boom", True)
    assert runner.run_job(on, mock=None)["state"] == "done"
    # The matcher really raised (and was counted), and nothing was recorded.
    assert all(i["reads"]["read_errors"] > 0 for i in on.load_items()), on.load_items()[0].get("reads")
    assert not (_jsonl(on.reads_path) if on.reads_path.exists() else [])
    key = lambda r: str(r.get("item_id"))  # noqa: E731
    assert (_clean(sorted(on.load_items(), key=key), _VOLATILE | _ITEM_ONLY)
            == _clean(sorted(off.load_items(), key=key), _VOLATILE))
