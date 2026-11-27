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
    return api_budget.ApiBudget(cap, 0.10, 0.25, ["qwen/qwen3.5-9b"])


def test_live_spend_trips_the_cap_before_any_document_finishes():
    budget = _budget(cap=0.05)
    budget.start_live()
    assert budget.exceeded() is None and budget.documents == 0
    budget.add_live(600_000, 1)  # $0.060 at the qwen3.5-9b slug price, one call still running
    assert "api_cost_cap_usd=0.05 reached" in budget.exceeded()


def test_live_spend_counts_from_a_resumed_runs_persisted_spend():
    budget = api_budget.ApiBudget(0.05, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    budget.add_usage({"prompt_tokens": 400_000, "completion_tokens": 1})  # $0.040 persisted
    budget.start_live()
    budget.add_live(200_000, 1)  # +$0.020
    assert budget.exceeded() is not None


def test_hf004_prices_every_vendored_call_and_the_guard_refuses_the_next():
    assert vh.apply_hotfixes()["HF-004"] == "applied"
    from pipeline import limits

    budget = _budget(cap=0.05)
    call_guard.arm(budget, ceiling=40)
    with call_guard.document() as doc:
        limits.reset_run_usage()
        call_guard.before_call()  # under the cap: allowed
        limits.record_usage({"input_tokens": 600_000, "output_tokens": 1}, agent="sorter")
        assert doc["calls"] == 1 and budget.live_usd == pytest.approx(0.060, abs=1e-4)
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
    assert (doc["calls"], doc["refused"]) == (0, None)  # no ceiling count, no refusal
    assert doc["llm_calls"] == 1 and doc["spend_usd"] == 0.0  # the governor still sees the call


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
    budget = _budget(cap=0.10)  # $0.010 per call at the slug price: the 10th call reaches the cap
    call_guard.arm(budget, ceiling=40)
    items = []
    rows = [{"id": "merger", "expected_doc_class": "merger_agreement", "doc_text": "x"}]
    with pytest.raises(RuntimeError) as raised:
        runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, api_budget=budget,
                                  connected=False, row_cb=items.append)
    assert len(calls) == 10  # stopped at the cap, not 140 calls later
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
    call_guard.arm(_budget(cap=0.05), ceiling=40)
    with call_guard.document():
        with pytest.raises(Exception, match="api_cost_cap_usd"):
            db._post_decision({}, timeout=1, attempts=3)
    assert len(calls) == 1


# S2 (phase 1): each request reserves its worst-case cost before it goes out.


def _armed(cap=0.05):
    budget = _budget(cap=cap)  # qwen/qwen3.5-9b: $0.10 per 1M prompt tokens
    call_guard.arm(budget, None)
    return budget


def test_a_call_whose_estimate_passes_the_cap_is_refused_before_it_goes_out():
    budget = _armed(cap=0.05)
    with pytest.raises(Exception, match="next call est"):
        call_guard.before_call(prompt_tokens=600_000, completion_tokens=0)  # about $0.06
    assert budget.reserved_usd == 0.0 and budget.live_total_usd() == 0.0


def test_concurrent_reservations_stop_the_next_call_below_the_cap():
    budget = _armed(cap=0.05)
    first = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)  # about $0.03 held
    assert first == pytest.approx(budget.estimate_call_usd(300_000, 0)) and first > 0
    with pytest.raises(Exception, match="reserved"):
        call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)


def test_a_settled_success_releases_and_after_call_prices_the_real_usage():
    budget = _armed(cap=1.0)
    held = call_guard.before_call(prompt_tokens=100_000, completion_tokens=0)
    call_guard.settle(held, billed=False)
    assert budget.reserved_usd == 0.0 and budget.unreported_usd == 0.0 and budget.settling_usd == 0.0
    call_guard.after_call({"prompt_tokens": 100_000, "completion_tokens": 0})
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(100_000, 0))


def test_a_success_holds_the_cap_until_its_usage_is_priced():
    """The reply is back before record_usage prices it. Dropping the reservation there lets the next
    request through, and the real bill lands after it has already gone out."""
    budget = _armed(cap=0.05)
    held = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)  # about $0.03
    call_guard.settle(held, billed=False, await_price=True)
    assert budget.reserved_usd == 0.0 and budget.settling_usd == pytest.approx(held)
    with pytest.raises(Exception, match="awaiting price"):
        call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
    call_guard.after_call({"prompt_tokens": 1, "completion_tokens": 0})
    assert budget.settling_usd == 0.0
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(1, 0))
    call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)  # the real bill left room


def test_a_rejected_request_frees_the_cap():
    budget = _armed(cap=0.05)
    held = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
    call_guard.settle(held, billed=False)  # HTTP 4xx or never connected: not billed
    assert budget.reserved_usd == 0.0 and budget.settling_usd == 0.0 and budget.unreported_usd == 0.0
    call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)


class _Status(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize("exc, billed", [
    (lambda: __import__("httpx").ReadTimeout("read timed out"), True),
    (lambda: _Status(500), True),
    (lambda: _Status(400), False),
    (lambda: __import__("httpx").ConnectError("refused"), False),
])
def test_a_timeout_is_charged_and_a_4xx_is_released(exc, billed):
    budget = _armed(cap=1.0)
    error = exc()
    assert call_guard.billed_failure(error) is billed
    held = call_guard.before_call(prompt_tokens=100_000, completion_tokens=0)
    call_guard.settle(held, billed=call_guard.billed_failure(error))
    assert budget.reserved_usd == 0.0
    assert budget.unreported_usd == (pytest.approx(held) if billed else 0.0)


def test_a_connect_error_wrapped_by_the_sdk_is_not_charged():
    import httpx

    wrapped = RuntimeError("Connection error.")
    wrapped.__cause__ = httpx.ConnectError("refused")
    assert call_guard.billed_failure(wrapped) is False


def test_request_tokens_counts_text_parts_and_defaults_the_output_cap():
    messages = [{"role": "system", "content": "x" * 400},
                {"role": "user", "content": [{"type": "text", "text": "y" * 400}, {"type": "image_url"}]}]
    assert call_guard.request_tokens(messages, None) == (200, call_guard.DEFAULT_COMPLETION_RESERVE_TOKENS)
    assert call_guard.request_tokens(messages, 512) == (200, 512)
    assert call_guard.request_tokens(None, 0) == (0, call_guard.DEFAULT_COMPLETION_RESERVE_TOKENS)


def test_an_unarmed_guard_reserves_nothing():
    assert call_guard.before_call(prompt_tokens=10**9, completion_tokens=10**9) == 0.0
    call_guard.settle(0.0, billed=True)  # a no-op


def test_the_runner_persists_unreported_charges_when_it_disarms(tmp_path):
    from mailroom_sandbox.job import runner
    from mailroom_sandbox.job.checkpoint import RunStore

    budget = _armed(cap=1.0)
    budget.charge_unreported(0.02)
    store = RunStore(tmp_path / "r")
    runner._persist_unreported_charges(store)
    events = [e for e in store.events() if e.get("event") == api_budget.UNREPORTED_CHARGE_EVENT]
    assert len(events) == 1
    assert api_budget.usage_records(store)[-1]["unreported_usd"] == pytest.approx(0.02)
    call_guard.disarm()
    runner._persist_unreported_charges(store)  # unarmed: nothing more is written
    assert len([e for e in store.events() if e.get("event") == api_budget.UNREPORTED_CHARGE_EVENT]) == 1


def test_concurrent_requests_cannot_all_pass_the_check_before_any_reserves(monkeypatch):
    """Final review: check-then-reserve must be atomic, or concurrent requests overshoot the cap together."""
    import threading
    import time

    budget = _armed(cap=0.05)
    real_reserve = budget.reserve

    def slow_reserve(usd):  # widen the window between the check and the reservation
        time.sleep(0.01)
        real_reserve(usd)

    monkeypatch.setattr(budget, "reserve", slow_reserve)
    admitted, refused, start = [], [], threading.Barrier(8)
    refusal = type(call_guard.budget_error("probe"))

    def request():
        start.wait()
        try:
            admitted.append(call_guard.before_call(prompt_tokens=300_000, completion_tokens=0))  # ~$0.03 each
        except refusal as exc:
            refused.append(str(exc))

    threads = [threading.Thread(target=request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(admitted) == 1 and len(refused) == 7


def test_unarmed_calls_still_count_for_the_governor():
    with call_guard.document() as scope:
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 1})
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 1})
    assert scope["llm_calls"] == 2 and scope["calls"] == 0
    assert scope["governor"] == {"retries": 0, "boss": 0, "skipped_classify_retries": 0}


def test_armed_calls_add_their_price_to_document_spend():
    budget = _armed(cap=1.0)
    with call_guard.document() as scope:
        call_guard.after_call({"prompt_tokens": 100_000, "completion_tokens": 0})
    assert scope["spend_usd"] == pytest.approx(budget.estimate_call_usd(100_000, 0))


def test_a_billed_failure_adds_its_charge_to_document_spend():
    _armed(cap=1.0)
    with call_guard.document() as scope:
        held = call_guard.before_call(prompt_tokens=100_000, completion_tokens=0)
        call_guard.settle(held, billed=True)
    assert scope["spend_usd"] == pytest.approx(held) and held > 0


def test_note_failed_attempt_counts_toward_the_ceiling():
    _armed(cap=1.0)
    with call_guard.document() as scope:
        call_guard.note_failed_attempt()
        assert call_guard.scope() is scope
    assert (scope["calls"], scope["llm_calls"]) == (1, 1)
    assert call_guard.scope() is None


def test_two_threads_keep_separate_governor_counters():
    import threading

    seen = {}
    barrier = threading.Barrier(2)

    def work(name, n):
        with call_guard.document():
            for _ in range(n):
                call_guard.scope()["governor"]["retries"] += 1
            barrier.wait()
            seen[name] = call_guard.scope()["governor"]["retries"]

    threads = [threading.Thread(target=work, args=(name, n)) for name, n in (("a", 1), ("b", 3))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"a": 1, "b": 3}
