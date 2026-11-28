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


def _stored(i: int) -> dict:
    """A persisted item, as items.jsonl holds it: the earlier attempt's answer and its billed tokens."""
    pred = {"id": str(i), "doc_type": _cls(i), "stage": "archived", "extracted_data": {}}
    return {"item_id": str(i), "pred": pred, "latency_ms": 12.0, "prompt_tokens": 100, "completion_tokens": 5}


def test_a_replayed_document_is_scored_without_a_model_call(monkeypatch):
    state = _install(monkeypatch, delay=0.01)
    items: list[dict] = []
    replay = {"0": _stored(0), "2": _stored(2)}
    result = runners.run_pipeline_eval(profile="ollama", rows=_rows(4), mock=False, connected=False,
                                       row_cb=items.append, concurrency=2, replay=replay)
    assert sorted(state["started"]) == ["1", "3"]
    assert result["scores"]["class_correct"] == 1.0 and len(result["docs"]) == 4
    replayed = {item["id"]: item for item in items if item.get("replayed")}
    assert sorted(replayed) == ["0", "2"]
    assert all(item["prompt_tokens"] == 100 for item in replayed.values())


def test_replayed_documents_are_not_added_to_the_api_budget(monkeypatch):
    _install(monkeypatch, delay=0.0)

    class Budget:
        def __init__(self):
            self.added: list[dict] = []
            self.checks = 0

        def add_usage(self, usage):
            self.added.append(dict(usage or {}))

        def check(self, prefix="", in_flight=0):
            self.checks += 1

    budget = Budget()
    runners.run_pipeline_eval(profile="ollama", rows=_rows(4), mock=False, connected=False,
                              api_budget=budget, replay={"0": _stored(0), "2": _stored(2)})
    assert len(budget.added) == 2  # documents 1 and 3 only: replayed spend is already in the seeded budget
    assert budget.checks == 2  # no cap check before a document that makes no call


def test_a_run_that_is_all_replay_makes_no_model_call(monkeypatch):
    state = _install(monkeypatch, delay=0.0)
    full = runners.run_pipeline_eval(profile="ollama", rows=_rows(4), mock=False, connected=False)
    state["started"].clear()
    replayed = runners.run_pipeline_eval(profile="ollama", rows=_rows(4), mock=False, connected=False,
                                         concurrency=3, replay={str(i): _stored(i) for i in range(4)})
    assert state["started"] == []
    assert replayed["scores"]["class_correct"] == full["scores"]["class_correct"] == 1.0
    assert replayed["scores"]["stage_correct"] == full["scores"]["stage_correct"]


def test_an_item_without_a_dict_pred_is_run_again(monkeypatch):
    state = _install(monkeypatch, delay=0.0)
    runners.run_pipeline_eval(profile="ollama", rows=_rows(2), mock=False, connected=False,
                              replay={"0": {"item_id": "0", "pred": None}})
    assert sorted(state["started"]) == ["0", "1"]


def test_a_persisted_error_row_runs_again_instead_of_replaying_its_failure(monkeypatch):
    """Final review: a resume after an outage must recover the documents that failed, not replay the failure."""
    state = _install(monkeypatch, delay=0.0)
    failed = {**_stored(0), "error": "ReadTimeout: no response"}
    parse_failed = {**_stored(1), "score": {"parse_error": True}}  # a real billed answer: replayed
    runners.run_pipeline_eval(profile="ollama", rows=_rows(2), mock=False, connected=False,
                              replay={"0": failed, "1": parse_failed})
    assert state["started"] == ["0"]


# job.max_retries / job.fail_fast for task: pipeline (the launch review found both ignored).


class _Budget:
    """An API budget stand-in: records what was added; ``over`` makes every cap check refuse."""

    def __init__(self, over: bool = False):
        self.added: list[dict] = []
        self.over = over

    def check(self, *_a, **_k):
        return None

    def exceeded(self, *_a, **_k):
        return "cap reached" if self.over else None

    def add_usage(self, usage):
        self.added.append(dict(usage))


def _flaky(monkeypatch, failures: dict[str, int], exc_type=RuntimeError):
    """Each listed document raises (after a billed call) that many times, then answers."""
    monkeypatch.setattr(runners, "_RETRY_PAUSE_SECONDS", 0)
    started: list[str] = []
    lock = threading.Lock()

    def fake_doc(row, **_kw):
        with lock:
            started.append(row["id"])
            left = failures.get(row["id"], 0)
            if left:
                failures[row["id"]] = left - 1
        if left:
            raise exc_type(f"lost {row['id']}")
        return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {}}

    def fake_usage():
        return {"prompt_tokens": 100, "completion_tokens": 10, "llm_calls": 1}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    from mailroom_sandbox.job import usage_capture

    monkeypatch.setattr(usage_capture, "usage_from_pipeline", fake_usage)
    return started


def test_a_document_that_raises_runs_again_and_keeps_the_usage_its_failed_attempt_billed(monkeypatch):
    started = _flaky(monkeypatch, {"1": 1})
    items: list[dict] = []
    out = runners.run_pipeline_eval(profile="ollama", rows=_rows(3), mock=False, connected=False,
                                    row_cb=items.append, max_retries=1)
    assert sorted(started) == ["0", "1", "1", "2"]
    by_id = {item["id"]: item for item in items}
    assert not by_id["1"]["error"] and by_id["1"]["prompt_tokens"] == 200  # the failed attempt and the answer
    assert by_id["0"]["prompt_tokens"] == 100
    assert not any(doc.get("error") for doc in out["docs"])


def test_without_retries_a_failure_still_stops_a_direct_call(monkeypatch):
    started = _flaky(monkeypatch, {"0": 1})
    with pytest.raises(RuntimeError, match="lost 0"):
        runners.run_pipeline_eval(profile="ollama", rows=_rows(3), mock=False, connected=False)
    assert started == ["0"]


def test_a_guard_refusal_is_never_retried(monkeypatch):
    from mailroom_sandbox.job.call_guard import GuardStop

    started = _flaky(monkeypatch, {"0": 5}, exc_type=GuardStop)
    with pytest.raises(GuardStop):
        runners.run_pipeline_eval(profile="ollama", rows=_rows(2), mock=False, connected=False, max_retries=3)
    assert started == ["0"]


def test_no_retry_starts_once_the_api_cap_is_reached(monkeypatch):
    started = _flaky(monkeypatch, {"0": 5})
    with pytest.raises(RuntimeError, match="lost 0"):
        runners.run_pipeline_eval(profile="ollama", rows=_rows(2), mock=False, connected=False, max_retries=3,
                                  api_budget=_Budget(over=True))
    assert started == ["0"]


def test_without_fail_fast_a_failed_document_is_an_error_row_and_the_run_goes_on(monkeypatch):
    started = _flaky(monkeypatch, {"0": 9})
    items: list[dict] = []
    budget = _Budget()
    out = runners.run_pipeline_eval(profile="ollama", rows=_rows(6), mock=False, connected=False, concurrency=2,
                                    row_cb=items.append, max_retries=2, fail_fast=False, record_failures=True,
                                    api_budget=budget)
    assert started.count("0") == 3 and {"1", "2", "3", "4", "5"} <= set(started)
    failed = next(item for item in items if item["id"] == "0")
    assert failed["error"] == "RuntimeError: lost 0" and failed["pred"]["attempts"] == 3
    assert failed["prompt_tokens"] == 300  # every attempt billed a call
    assert sum(u.get("prompt_tokens", 0) for u in budget.added) == 300 + 5 * 100
    assert out["docs"][0]["error"] and out["docs"][0]["stage"] == "failed"


def test_with_fail_fast_every_failed_document_is_recorded_once_with_its_usage(monkeypatch):
    """Two documents failing together: each is an error row with its own usage (the resume budget
    used to see only the first one's), the exception no longer carries usage, and the run stops."""
    _flaky(monkeypatch, {"0": 9, "1": 9})
    items: list[dict] = []
    budget = _Budget()
    with pytest.raises(RuntimeError, match="lost") as caught:
        runners.run_pipeline_eval(profile="ollama", rows=_rows(8), mock=False, connected=False, concurrency=2,
                                  row_cb=items.append, fail_fast=True, record_failures=True, api_budget=budget)
    errors = {item["id"]: item["prompt_tokens"] for item in items if item["error"]}
    assert errors == {"0": 100, "1": 100}
    assert getattr(caught.value, "sandbox_failed_usage", None) is None  # the rows carry it: no double count
    assert sum(u.get("prompt_tokens", 0) for u in budget.added) == 100 * len(items)
    assert len(items) < 8


def _served(model: str, calls: int = 1) -> list[dict]:
    return [{"requested_model": model, "served_model": model, "served_provider": "P", "status": "pinned",
             "call_path": "retry_chat_completion", "calls": calls}]


def test_an_error_row_and_a_retried_answer_keep_the_served_calls_of_failed_attempts(monkeypatch):
    """Bugbot: the served model of a failed document's billed calls was lost with its exception."""
    monkeypatch.setattr(runners, "_RETRY_PAUSE_SECONDS", 0)
    left = {"0": 9, "1": 1}

    def fake_doc(row, **_kw):
        if left.get(row["id"]):
            left[row["id"]] -= 1
            exc = RuntimeError(f"lost {row['id']}")
            exc.sandbox_served_calls = _served("m")
            raise exc
        return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {},
                "served_calls": _served("m")}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    items: list[dict] = []
    runners.run_pipeline_eval(profile="ollama", rows=_rows(3), mock=False, connected=False, row_cb=items.append,
                              max_retries=1, fail_fast=False, record_failures=True)
    by_id = {item["id"]: item["pred"] for item in items}
    assert by_id["0"]["served_calls"] == _served("m", 2)  # both failed attempts
    assert by_id["1"]["served_calls"] == _served("m", 2)  # the failed attempt and the answer
    assert by_id["2"]["served_calls"] == _served("m", 1)


def test_a_document_that_raises_carries_the_served_calls_its_scope_counted(monkeypatch):
    from mailroom_sandbox import provider_pins
    from mailroom_sandbox.job.call_guard import GuardStop

    entry = {"requested_model": "m", "served_model": "m", "served_provider": "P", "status": "pinned",
             "call_path": "retry_chat_completion"}

    def raising(row, **_kw):
        provider_pins._note_on_document(entry)
        raise RuntimeError("boom")

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", raising)
    with pytest.raises(RuntimeError, match="boom") as caught:
        runners._run_pipeline_doc({"id": "d0"})
    assert caught.value.sandbox_served_calls == _served("m")

    def refused(row, **_kw):
        from mailroom_sandbox.job import call_guard

        provider_pins._note_on_document(entry)
        call_guard.scope()["refused"] = "cap"
        return {"id": "d0"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", refused)
    with pytest.raises(GuardStop) as stopped:
        runners._run_pipeline_doc({"id": "d0"})
    assert stopped.value.sandbox_served_calls == _served("m")


def _billing(monkeypatch, failures: dict[str, int], *, failed_calls: bool = True):
    """Like _flaky, with per-call and per-agent usage; ``failed_calls`` False: failed attempts report no calls."""
    monkeypatch.setattr(runners, "_RETRY_PAUSE_SECONDS", 0)
    from mailroom_sandbox.job import usage_capture

    state = {"failing": False}

    def fake_doc(row, **_kw):
        left = failures.get(row["id"], 0)
        state["failing"] = bool(left)
        if left:
            failures[row["id"]] = left - 1
            raise RuntimeError(f"lost {row['id']}")
        return {"id": row["id"], "doc_type": _cls(int(row["id"])), "stage": "archived", "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    monkeypatch.setattr(usage_capture, "usage_from_pipeline",
                        lambda: {"prompt_tokens": 100, "completion_tokens": 10, "llm_calls": 1})
    monkeypatch.setattr(usage_capture, "call_usage_from_pipeline",
                        lambda: [] if state["failing"] and not failed_calls else [[100, 10]])
    monkeypatch.setattr(usage_capture, "usage_by_agent_from_pipeline", lambda: {
        "sorter": {"calls": 1, "prompt_tokens": 100, "completion_tokens": 10, "models": ["m"]}})


def test_a_retried_answer_prices_the_calls_of_its_failed_attempts(monkeypatch):
    """CodeAnt: call_usage (priced call by call) kept only the last attempt's calls while the totals
    counted every attempt, so the failed attempts' calls were never priced."""
    _billing(monkeypatch, {"0": 1})
    items: list[dict] = []
    runners.run_pipeline_eval(profile="ollama", rows=_rows(1), mock=False, connected=False, row_cb=items.append,
                              max_retries=1)
    assert items[0]["prompt_tokens"] == 200 and items[0]["call_usage"] == [[100, 10], [100, 10]]
    assert items[0]["usage_by_agent"]["sorter"] == {"calls": 2, "prompt_tokens": 200, "completion_tokens": 20,
                                                    "models": ["m"]}


def test_an_error_row_prices_the_calls_of_every_attempt(monkeypatch):
    _billing(monkeypatch, {"0": 9})
    items: list[dict] = []
    budget = _Budget()
    runners.run_pipeline_eval(profile="ollama", rows=_rows(2), mock=False, connected=False, row_cb=items.append,
                              max_retries=1, fail_fast=False, record_failures=True, api_budget=budget)
    failed = next(item for item in items if item["id"] == "0")
    assert failed["error"] and failed["call_usage"] == [[100, 10], [100, 10]]
    billed = next(u for u in budget.added if u.get("prompt_tokens") == 200)
    assert billed["call_usage"] == [[100, 10], [100, 10]]


def test_without_every_attempts_calls_a_retried_answer_is_priced_on_its_totals(monkeypatch):
    """A failed attempt that billed tokens but reported no calls: a partial call list would underprice."""
    _billing(monkeypatch, {"0": 1}, failed_calls=False)
    items: list[dict] = []
    runners.run_pipeline_eval(profile="ollama", rows=_rows(1), mock=False, connected=False, row_cb=items.append,
                              max_retries=1)
    assert items[0]["prompt_tokens"] == 200 and "call_usage" not in items[0]


def test_no_retry_starts_when_the_pause_reaches_the_wall_cap(monkeypatch):
    """CodeAnt: the wall cap was checked before the pause, so a pause that crossed it still retried."""
    started = _flaky(monkeypatch, {"0": 5})
    monkeypatch.setattr(runners, "_RETRY_PAUSE_SECONDS", 0.3)
    with pytest.raises(RuntimeError, match="lost 0"):
        runners.run_pipeline_eval(profile="ollama", rows=_rows(1), mock=False, connected=False, max_retries=3,
                                  max_wall_seconds=0.15)
    assert started == ["0"]
