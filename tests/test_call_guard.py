"""rb1 R01 smoke defect 3: the API cap bounds documents in flight, call by call (job.call_guard)."""
from __future__ import annotations

import pytest

from mailroom_sandbox import vendor_hotfixes as vh
from mailroom_sandbox.job import api_budget, call_guard

pytest.importorskip("pipeline.limits")


@pytest.fixture(autouse=True)
def _disarmed():
    call_guard.disarm()
    yield
    call_guard.disarm()


def _budget(cap=0.10):
    return api_budget.ApiBudget(cap, 0.17, 0.25, ["qwen/qwen3.5-9b"])


def test_live_spend_trips_the_cap_before_any_document_finishes():
    budget = _budget()
    budget.start_live()
    assert budget.exceeded() is None and budget.documents == 0
    budget.add_live(600_000, 1)  # $0.102 on one call of a document still running
    assert "api_cost_cap_usd=0.1 reached" in budget.exceeded()


def test_live_spend_counts_from_a_resumed_runs_persisted_spend():
    budget = api_budget.ApiBudget(0.10, 0.17, 0.25, ["qwen/qwen3.5-9b"])
    budget.add_usage({"prompt_tokens": 400_000, "completion_tokens": 1})  # $0.068 persisted
    budget.start_live()
    budget.add_live(200_000, 1)  # +$0.034
    assert budget.exceeded() is not None


def test_hf004_prices_every_vendored_call_and_the_guard_refuses_the_next():
    assert vh.apply_hotfixes()["HF-004"] == "applied"
    from pipeline import limits

    budget = _budget()
    call_guard.arm(budget, ceiling=40)
    with call_guard.document() as doc:
        limits.reset_run_usage()
        call_guard.before_call()  # under the cap: allowed
        limits.record_usage({"input_tokens": 600_000, "output_tokens": 1}, agent="sorter")
        assert doc["calls"] == 1 and budget.live_usd == pytest.approx(0.102, abs=1e-4)
        with pytest.raises(limits.RunBudgetExceeded, match="call refused: api_cost_cap_usd"):
            call_guard.before_call()
    assert doc["refused"].startswith("call refused")


def test_the_per_document_ceiling_refuses_a_runaway_document_only():
    call_guard.arm(_budget(cap=1_000.0), ceiling=3)
    with call_guard.document() as runaway:
        for _ in range(3):
            call_guard.before_call()
            call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 1})
        with pytest.raises(Exception, match="per-document ceiling 3"):
            call_guard.before_call()
    with call_guard.document() as fresh:
        call_guard.before_call()  # the next document starts from zero
    assert runaway["refused"] and not fresh["refused"]


def test_an_unarmed_process_is_untouched():
    with call_guard.document() as doc:
        call_guard.before_call()
        call_guard.after_call({"prompt_tokens": 10**9, "completion_tokens": 10**9})
    assert doc == {"calls": 0, "refused": None}


def test_a_document_the_guard_cut_short_is_an_error_row_not_a_score(monkeypatch):
    """The R01 merger case: one long document, no finished document, the cap reached mid-run."""
    from mailroom_sandbox.eval import runners

    vh.apply_hotfixes()
    from pipeline import limits

    calls = []

    def long_merger(row, **_):
        limits.reset_run_usage()
        for _ in range(140):  # the i01 merger documents made 100+ calls each
            try:
                call_guard.before_call()
            except limits.RunBudgetExceeded:
                # The graph aborts through its run-limit path, or a slot fails soft and the
                # document finishes with what it had: either way a result comes back.
                break
            calls.append(row["id"])
            limits.record_usage({"input_tokens": 100_000, "output_tokens": 1}, agent="sorter")
        return {"id": row["id"], "doc_type": "merger_agreement", "stage": "archived", "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", long_merger)
    budget = _budget(cap=0.10)  # $0.017 per call: the 6th call reaches the cap
    call_guard.arm(budget, ceiling=40)
    items = []
    rows = [{"id": "merger", "expected_doc_class": "merger_agreement", "doc_text": "x"}]
    with pytest.raises(RuntimeError) as raised:
        runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, api_budget=budget,
                                  connected=False, row_cb=items.append)
    assert len(calls) == 6  # stopped at the cap, not 140 calls later
    assert "API call guard" in str(raised.value) or "api_cost_cap_usd" in str(raised.value)
    assert not [i for i in items if not i.get("error")]  # nothing scored as a pipeline outcome


def test_decisions_transport_obeys_the_run_guard_before_each_attempt(monkeypatch):
    from mailroom_sandbox import decision_backends as db

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1))
    budget = _budget()
    call_guard.arm(budget, ceiling=1)
    with call_guard.document():
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0})
        with pytest.raises(Exception, match="per-document ceiling"):
            db._post_decision({}, timeout=1, attempts=3)
    assert calls == []


def test_decisions_rechecks_budget_before_retry(monkeypatch):
    import httpx
    from mailroom_sandbox import decision_backends as db

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    calls = []

    def first_attempt(*args, **kwargs):
        calls.append(1)
        # A different in-flight request reaches the shared cap while this one fails.
        call_guard.after_call({"prompt_tokens": 600_000, "completion_tokens": 1})
        raise httpx.ConnectError("temporary")

    monkeypatch.setattr("httpx.post", first_attempt)
    call_guard.arm(_budget(), ceiling=40)
    with call_guard.document():
        with pytest.raises(Exception, match="api_cost_cap_usd"):
            db._post_decision({}, timeout=1, attempts=3)
    assert len(calls) == 1
