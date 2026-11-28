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


def test_hf004_prices_a_call_at_the_model_it_names():
    """Phase 4 final review: a dearer judge model on the run does not re-price the pipeline's calls."""
    from mailroom_sandbox.job.metrics import call_cost

    assert vh.apply_hotfixes()["HF-004"] == "applied"
    from pipeline import limits

    budget = api_budget.ApiBudget(10.0, 0.10, 0.25, ["qwen/qwen3.7-flash", "qwen/qwen3.7-plus"])
    call_guard.arm(budget, ceiling=40)
    with call_guard.document():
        limits.reset_run_usage()
        limits.record_usage({"input_tokens": 5_000, "output_tokens": 1_000}, "qwen/qwen3.7-flash", agent="sorter")
        assert budget.live_usd == pytest.approx(call_cost("qwen/qwen3.7-flash", 5_000, 1_000))
        limits.record_usage({"input_tokens": 5_000, "output_tokens": 1_000}, agent="judge")  # unnamed: dearest
        assert budget.live_usd == pytest.approx(call_cost("qwen/qwen3.7-flash", 5_000, 1_000)
                                                + call_cost("qwen/qwen3.7-plus", 5_000, 1_000))


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


# A held success is released by whoever prices it. These pin where that happens, and what a miss costs.


def _held_success(prompt_tokens=300_000):
    held = call_guard.before_call(prompt_tokens=prompt_tokens, completion_tokens=0)
    call_guard.settle(held, billed=False, await_price=True)
    return held


def test_a_price_clears_only_a_hold_of_its_own_model():
    """A concurrent call of another model in the same document, or one that reserved nothing, used to
    clear the oldest hold in the shared queue and briefly reopen that call's gap on the cap."""
    budget = _armed(cap=1.0)
    with call_guard.document():
        held = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
        call_guard.settle(held, billed=False, await_price=True, model="qwen/qwen3.5-9b")
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0}, model="local/other-model")
        assert budget.settling_usd == pytest.approx(held)  # still held: that price was another model's
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0}, model="OpenRouter/Qwen/Qwen3.5-9B")
        assert budget.settling_usd == 0.0
    assert budget.live_total_usd() == pytest.approx(2 * budget.estimate_call_usd(10, 0))


def test_a_price_without_a_model_still_clears_the_oldest_hold():
    budget = _armed(cap=1.0)
    with call_guard.document():
        held = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
        call_guard.settle(held, billed=False, await_price=True, model="qwen/qwen3.5-9b")
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0})
        assert budget.settling_usd == 0.0


def test_a_named_hold_is_priced_by_its_own_reply_only():
    """The Decisions transport prices its own reply by hold id, never a concurrent call's hold."""
    budget = _armed(cap=1.0)
    with call_guard.document():
        other = call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
        call_guard.settle(other, billed=False, await_price=True)  # a LangChain reply priced later
        mine = call_guard.before_call(prompt_tokens=100_000, completion_tokens=0)
        hold = call_guard.settle(mine, billed=False, await_price=True)
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0}, hold=hold)
        assert budget.settling_usd == pytest.approx(other)
        call_guard.after_call({"prompt_tokens": 10, "completion_tokens": 0})
        assert budget.settling_usd == 0.0


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "lots"], ids=["inf", "nan", "text"])
def test_a_held_success_with_unreadable_usage_is_still_priced_and_cleared(bad):
    """after_call takes the hold before it reads the counts, so a count it cannot read must not raise,
    and the billed reply keeps at least its reservation rather than being priced at nothing."""
    budget = _armed(cap=1.0)
    with call_guard.document():
        held = call_guard.before_call(prompt_tokens=1_000, completion_tokens=10)
        call_guard.settle(held, billed=False, await_price=True)
        reserved = budget.settling_usd
        assert reserved > 0
        call_guard.after_call({"prompt_tokens": bad, "completion_tokens": 1})
        assert budget.settling_usd == 0.0 and budget.reserved_usd == 0.0
        assert budget.live_usd == pytest.approx(reserved)


def test_a_success_never_priced_is_released_when_its_document_ends(caplog):
    """A path that settles with await_price and never reaches after_call holds the cap for the rest of
    its document only. The next document prices its own replies as usual."""
    budget = _armed(cap=0.05)
    with call_guard.document():
        held = _held_success()
        assert budget.settling_usd == pytest.approx(held)
        with pytest.raises(Exception, match="awaiting price"):  # fails closed while the document runs
            call_guard.before_call(prompt_tokens=300_000, completion_tokens=0)
    assert budget.settling_usd == 0.0 and budget.reserved_usd == 0.0 and budget.live_total_usd() == 0.0
    assert "never priced" in caplog.text
    with call_guard.document() as scope:
        _held_success()
        call_guard.after_call({"prompt_tokens": 1_000, "completion_tokens": 0})
        assert budget.settling_usd == 0.0  # priced by its own after_call, before the document ends
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(1_000, 0))
    assert scope["spend_usd"] == pytest.approx(budget.estimate_call_usd(1_000, 0))


def test_outside_a_document_a_missed_price_is_released_by_the_next_success_on_that_thread(caplog):
    """No scope: the hold is this thread's, and a same-thread transport prices one reply before its next
    request settles. A miss is therefore bounded at one hold per thread."""
    budget = _armed(cap=1.0)
    first = _held_success()
    assert budget.settling_usd == pytest.approx(first)
    second = _held_success(prompt_tokens=200_000)  # the first was never priced
    assert budget.settling_usd == pytest.approx(second)
    assert "never priced" in caplog.text
    call_guard.after_call({"prompt_tokens": 1_000, "completion_tokens": 0})
    assert budget.settling_usd == 0.0
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(1_000, 0))


def test_a_new_arm_drops_the_previous_runs_holds():
    old = _armed(cap=1.0)
    _held_success()
    new = _armed(cap=1.0)
    assert old.settling_usd == 0.0
    call_guard.after_call({"prompt_tokens": 1_000, "completion_tokens": 0})  # nothing of the old run's
    assert new.settling_usd == 0.0
    assert new.live_total_usd() == pytest.approx(new.estimate_call_usd(1_000, 0))


def test_a_success_settled_on_a_worker_thread_is_priced_on_the_documents_thread():
    """LangChain's with_structured_output runs the model in a RunnableParallel: the request (and its
    settle) runs on a worker thread in a copy of the caller's context, and the agent prices the reply on
    its own thread. The document's queue is shared by both."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    budget = _armed(cap=1.0)
    with call_guard.document(), ThreadPoolExecutor(1) as pool:
        held = pool.submit(contextvars.copy_context().run, _held_success).result()
        assert budget.settling_usd == pytest.approx(held)
        call_guard.after_call({"prompt_tokens": 1_000, "completion_tokens": 0})
        assert budget.settling_usd == 0.0
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(1_000, 0))


def test_the_runners_chat_specialist_rows_share_holds_across_threads():
    from mailroom_sandbox.eval import runners

    with runners.isolated_call_scope("contracts_specialist", mock=False) as scope:
        assert call_guard.scoped_holds() and scope == {"calls": 0, "refused": None}
    assert not call_guard.scoped_holds()
    with runners.isolated_call_scope("contracts_specialist", mock=True):
        assert not call_guard.scoped_holds()


@pytest.mark.parametrize("hop", [False, True], ids=["same-thread", "worker-thread"])
def test_concurrent_documents_settle_and_price_back_to_zero(hop, caplog):
    """run_pipeline_eval runs up to job.concurrency documents on a thread pool. However the settles and
    prices of N documents interleave, every hold is priced once: nothing is left awaiting a price and
    the live spend is exactly the sum of the priced costs."""
    import contextvars
    import threading
    from concurrent.futures import ThreadPoolExecutor

    budget = _armed(cap=1_000.0)
    workers, calls = 10, 20
    priced, lock, start = [], threading.Lock(), threading.Barrier(workers)

    def document(n):
        start.wait()
        with call_guard.document(), ThreadPoolExecutor(1) as hop_pool:
            for i in range(calls):
                if hop:
                    hop_pool.submit(contextvars.copy_context().run, _held_success, 50_000 + i).result()
                else:
                    _held_success(50_000 + i)
                usage = {"prompt_tokens": 1_000 * (n + 1) + i, "completion_tokens": 10 * i}
                call_guard.after_call(usage)
                with lock:
                    priced.append(budget.estimate_call_usd(usage["prompt_tokens"], usage["completion_tokens"]))

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(document, range(workers)))
    assert len(priced) == workers * calls
    assert budget.settling_usd == pytest.approx(0.0, abs=1e-12) and budget.reserved_usd == pytest.approx(0.0, abs=1e-12)
    assert budget.live_total_usd() == pytest.approx(sum(priced))
    assert "never priced" not in caplog.text  # each was priced, none released at a document's end


def test_a_length_resample_prices_the_reply_it_discards(monkeypatch):
    """sampling's length re-sample drops a reply no caller records. It was billed and its success is
    held, so it is priced there; otherwise every re-sample would leave a hold behind."""
    import types

    import llm.retry as retry_mod

    from mailroom_sandbox import sampling

    def reply(finish, prompt, completion):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason=finish)],
                                     usage=types.SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion))

    replies = [reply("length", 40_000, 4_000), reply("stop", 5_000, 100)]

    def guarded(client, **kwargs):  # one attempt, settled as _AttemptGuardedCompletions settles a success
        held = call_guard.before_call(prompt_tokens=50_000, completion_tokens=4_096)
        call_guard.settle(held, billed=False, await_price=True)
        return replies.pop(0)

    monkeypatch.setattr(retry_mod, "retry_chat_completion", guarded)
    sampling._install_retry_patch()
    budget = _armed(cap=1.0)
    token = sampling._REQUEST.set({"agent": "probe", "extra": {"length_retries": 1}})
    try:
        with call_guard.document() as scope:
            response = retry_mod.retry_chat_completion(None, model="qwen/qwen3.5-9b", messages=[])
            assert budget.settling_usd == pytest.approx(budget.estimate_call_usd(50_000, 4_096))  # the kept one
            call_guard.after_call(response.usage)  # what the caller's record_usage does
            assert budget.settling_usd == 0.0
    finally:
        sampling._REQUEST.reset(token)
    assert budget.live_total_usd() == pytest.approx(budget.estimate_call_usd(40_000, 4_000)
                                                    + budget.estimate_call_usd(5_000, 100))
    # Priced only: the discarded reply never reaches the pipeline, so the ceiling and the governor's call
    # budget count the kept reply alone, as on an unarmed run (routing must not depend on the cap).
    assert scope["calls"] == 1 and scope["llm_calls"] == 1
    assert scope["spend_usd"] == pytest.approx(budget.live_total_usd())


def test_concurrent_threads_outside_a_document_price_their_own_holds():
    from concurrent.futures import ThreadPoolExecutor

    budget = _armed(cap=1_000.0)
    priced = []

    def worker(n):
        out = []
        for i in range(20):
            _held_success(10_000 + i)
            call_guard.after_call({"prompt_tokens": 500 * (n + 1), "completion_tokens": i})
            out.append(budget.estimate_call_usd(500 * (n + 1), i))
        return out

    with ThreadPoolExecutor(10) as pool:
        for out in pool.map(worker, range(10)):
            priced.extend(out)
    assert budget.settling_usd == pytest.approx(0.0, abs=1e-12)
    assert budget.live_total_usd() == pytest.approx(sum(priced))


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
