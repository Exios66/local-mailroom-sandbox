"""task: pipeline honours job.concurrency: documents run in parallel, results stay in input order."""
from __future__ import annotations

import threading
import time

import pytest

from mailroom_sandbox.eval import runners


def _cls(i: int) -> str:
    return "contract" if i % 2 == 0 else "correspondence"


def _rows(n: int) -> list[dict]:
    return [{"id": str(i), "expected_doc_class": _cls(i), "doc_text": "x"} for i in range(n)]


def _install(monkeypatch, *, delay: float = 0.05, fail_on: str | None = None):
    state = {"active": 0, "peak": 0, "started": []}
    lock = threading.Lock()

    def fake_doc(row, **_kw):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["started"].append(row["id"])
        try:
            # Reverse the finishing order so a result list built on completion would be out of order.
            time.sleep(delay * (10 - int(row["id"])) / 10)
            if row["id"] == fail_on:
                raise ValueError(f"boom {row['id']}")
            return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {}}
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    return state


def test_documents_run_concurrently_and_results_keep_input_order(monkeypatch):
    state = _install(monkeypatch)
    items: list[dict] = []
    result = runners.run_pipeline_eval(profile="ollama", rows=_rows(8), mock=False, connected=False,
                                       row_cb=items.append, concurrency=4)
    assert state["peak"] == 4
    assert sorted(item["id"] for item in items) == [str(i) for i in range(8)]
    assert all(item["score"]["class_correct"] == 1.0 for item in items)
    # Documents finish in reverse order; scoring pairs rows with results by position, so a
    # completion-ordered result list would score every alternating class wrong.
    assert result["scores"]["class_correct"] == 1.0


def test_default_concurrency_is_serial(monkeypatch):
    state = _install(monkeypatch, delay=0.01)
    runners.run_pipeline_eval(profile="ollama", rows=_rows(4), mock=False, connected=False)
    assert state["peak"] == 1


def test_a_failure_stops_new_documents_and_records_the_in_flight_ones(monkeypatch):
    state = _install(monkeypatch, fail_on="0")
    items: list[dict] = []
    with pytest.raises(ValueError, match="boom 0"):
        runners.run_pipeline_eval(profile="ollama", rows=_rows(8), mock=False, connected=False,
                                  row_cb=items.append, concurrency=2)
    # Document 0 is slowest, so 1 finishes first and its replacement starts before 0 fails;
    # once 0 fails nothing new starts, and every started document other than 0 is recorded.
    recorded = {item["id"] for item in items}
    assert "0" not in recorded
    assert recorded == set(state["started"]) - {"0"}
    assert len(state["started"]) < 8


def test_the_job_runner_passes_job_concurrency_to_the_pipeline(monkeypatch):
    import inspect

    from mailroom_sandbox.job import runner

    source = inspect.getsource(runner._run_whole_run)
    call = source[source.index("eval_runners.run_pipeline_eval("):]
    call = call[:call.index(")\n")]
    assert "concurrency=concurrency" in call


def test_read_sinks_are_wired_per_document_and_reported_as_item_reads(monkeypatch):
    from mailroom_sandbox.job import read_ranges

    def fake_doc(row, **_kw):
        read_ranges.record("sorter", "Document text:\n" + row["doc_text"], node="classify")
        return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    reads, items = [], []
    rows = [{"id": str(i), "expected_doc_class": _cls(i), "doc_text": "t" * 80} for i in range(6)]
    runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, connected=False, row_cb=items.append,
                              node_cb=lambda rec: None, read_cb=reads.append, text_cb=lambda d, t: None,
                              concurrency=3)
    assert sorted(r["doc"] for r in reads) == sorted(str(i) for i in range(6))
    assert all(r["call"] == 1 and r["node"] == "classify" for r in reads)
    assert all(item["reads"]["read_calls"] == 1 and item["reads"]["read_errors"] == 0 for item in items)
    # no read sink: nothing recorded and no ``reads`` key
    items.clear()
    runners.run_pipeline_eval(profile="ollama", rows=rows[:2], mock=False, connected=False, row_cb=items.append,
                              node_cb=lambda rec: None)
    assert all("reads" not in item for item in items)


def test_read_recording_works_without_node_tracking(monkeypatch):
    """A caller may supply read_cb alone: records land and the item still reports ``reads``."""
    from mailroom_sandbox.job import read_ranges

    def fake_doc(row, **_kw):
        read_ranges.record("sorter", "Document text:\n" + row["doc_text"], node="classify")
        return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    reads, items = [], []
    rows = [{"id": str(i), "expected_doc_class": _cls(i), "doc_text": "t" * 80} for i in range(4)]
    runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, connected=False, row_cb=items.append,
                              read_cb=reads.append, text_cb=lambda d, t: None, concurrency=2)
    assert sorted(r["doc"] for r in reads) == sorted(str(i) for i in range(4))
    assert all(item["reads"]["read_calls"] == 1 for item in items)
