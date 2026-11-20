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


def test_a_decisions_call_is_charged_once_when_hf004_wraps_record_usage(monkeypatch):
    """One Decisions HTTP response is one live charge and one ceiling slot.

    ``_post_decision`` prices the returned call, and HF-004 prices ``record_usage``.
    Feeding both the same response charged Luna and Jev runs twice, so a cap set
    for the real estimate aborted near the halfway document.
    """
    from mailroom_sandbox import decision_backends as db
    from pipeline import limits

    assert vh.apply_hotfixes()["HF-004"] == "applied"

    class Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "openai/gpt-6-luna-decisions",
                "answers": {"doc_type": {"choice": "contract", "probabilities": {"contract": 0.91}}},
                "usage": {"input_tokens": 1_000_000, "output_tokens": 0, "cost": 0.10},
            }

    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("httpx.post", lambda *a, **k: Resp())
    monkeypatch.setattr(db, "_record_served", lambda *a, **k: None)
    budget = api_budget.ApiBudget(1.0, 0.10, 0.0, ["openai/gpt-6-luna-decisions"])
    call_guard.arm(budget, ceiling=2)
    limits.reset_run_usage()
    with call_guard.document() as doc:
        db.decide("a short contract", model="openai/gpt-6-luna-decisions",
                  questions={"doc_type": {"type": "choice", "criteria": {"contract": "a contract"}}})
        assert doc["calls"] == 1
        assert budget.live_usd == pytest.approx(0.10, abs=1e-6)
        summary = limits.usage_summary()
        assert summary["calls"] == 1
        assert summary["prompt_tokens"] == 1_000_000
        call_guard.before_call()  # ceiling 2: the next document call may still start
    assert doc["refused"] is None


def test_decision_tasks_take_the_per_document_ceiling_and_chunked_specialists_do_not():
    """Isolated decision smokes are one request per document, so the R01 ceiling applies.

    A chunked specialist can legitimately pass that count. Mock rows stay unscoped.
    """
    from mailroom_sandbox.eval.runners import isolated_call_scope

    call_guard.arm(_budget(cap=1_000), ceiling=1)
    for task in ("sorter_reviewer", "extraction_gate"):
        with isolated_call_scope(task, mock=False) as scope:
            call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0})
            assert scope["calls"] == 1
            with pytest.raises(Exception, match="per-document ceiling"):
                call_guard.before_call()
    with isolated_call_scope("specialist", mock=False) as scope:
        call_guard.before_call()
        assert scope["calls"] == 0
    with isolated_call_scope("sorter_reviewer", mock=True) as scope:
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0})
        assert scope["calls"] == 0


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
