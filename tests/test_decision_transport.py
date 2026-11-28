"""Decisions retries stop when their caller's wall-clock budget expires."""
from __future__ import annotations

import time

import httpx
import pytest

from mailroom_sandbox import decision_backends as db
from pipeline import limits


@pytest.fixture
def transport(monkeypatch):
    clock = [100.0]
    calls = []
    sleeps = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(time, "time", lambda: clock[0])
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(limits, "get_run_deadline", lambda: None)
    monkeypatch.setattr(limits, "get_call_timeout_seconds", lambda: 120)

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    def post(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(429, text="rate limited", headers={"Retry-After": "7"})

    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(httpx, "post", post)
    return clock, calls, sleeps


def test_expired_run_never_sends_a_decisions_request(monkeypatch, transport):
    _, calls, sleeps = transport
    monkeypatch.setattr(limits, "get_run_deadline", lambda: 99.0)
    with pytest.raises(limits.RunDeadlineExceeded):
        db._post_decision({}, timeout=120, attempts=3)
    assert calls == sleeps == []


def test_retry_checks_run_deadline_and_clamps_http_timeout(monkeypatch, transport):
    _, calls, sleeps = transport
    monkeypatch.setattr(limits, "get_run_deadline", lambda: 103.0)
    with pytest.raises(limits.RunDeadlineExceeded):
        db._post_decision({}, timeout=120, attempts=3)
    assert len(calls) == 1
    assert calls[0]["timeout"] == pytest.approx(3)
    assert sleeps == [3]


def test_request_budget_covers_retries_and_the_backoff(transport):
    _, calls, sleeps = transport
    with pytest.raises(TimeoutError, match="Decisions.*deadline"):
        db._post_decision({}, timeout=2, attempts=3)
    assert len(calls) == 1 and sleeps == [2]


def test_configured_call_allowance_caps_the_transport_budget(monkeypatch, transport):
    _, calls, sleeps = transport
    monkeypatch.setattr(limits, "get_run_deadline", lambda: 1000.0)
    monkeypatch.setattr(limits, "get_call_timeout_seconds", lambda: 2)
    with pytest.raises(TimeoutError, match="Decisions.*deadline"):
        db._post_decision({}, timeout=120, attempts=3)
    assert len(calls) == 1 and calls[0]["timeout"] == 2 and sleeps == [2]


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5])
def test_invalid_attempt_counts_never_send_a_request(transport, attempts):
    _, calls, sleeps = transport
    with pytest.raises(ValueError, match="attempts must be a positive integer"):
        db._post_decision({}, timeout=120, attempts=attempts)
    assert calls == sleeps == []


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_invalid_timeouts_never_send_a_request(transport, timeout):
    _, calls, sleeps = transport
    with pytest.raises(ValueError, match="timeout must be finite and positive"):
        db._post_decision({}, timeout=timeout, attempts=3)
    assert calls == sleeps == []


def test_retry_after_is_honored_without_sleeping_after_the_last_attempt(transport):
    _, calls, sleeps = transport
    with pytest.raises(RuntimeError, match="Decisions API 429"):
        db._post_decision({}, timeout=120, attempts=3)
    assert len(calls) == 3 and sleeps == [7, 7]


@pytest.mark.parametrize(("header", "delay"), [
    ("Thu, 01 Jan 1970 00:01:47 GMT", 7), ("invalid", 1), ("NaN", 1), ("inf", 1), ("-3", 1),
])
def test_retry_after_dates_and_invalid_values(transport, header, delay):
    assert db._decision_retry_delay(httpx.Response(503, headers={"Retry-After": header}), 0) == delay


def test_transport_failure_cannot_retry_after_the_node_deadline(monkeypatch, transport):
    clock, calls, sleeps = transport

    def post(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 3
        raise httpx.ReadTimeout("no response")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(TimeoutError, match="Decisions.*deadline"):
        db._post_decision({}, timeout=2, attempts=3)
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
def test_permanent_failures_are_never_retried(monkeypatch, transport, status):
    _, calls, sleeps = transport

    def post(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(status, text="permanent failure")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(RuntimeError, match=f"Decisions API {status}"):
        db._post_decision({}, timeout=120, attempts=3)
    assert len(calls) == 1 and sleeps == []


# --- read ranges (Task 4) ----------------------------------------------------

def _read_doc(n=1500, seed=11):
    import random

    rng = random.Random(seed)
    return "\n\n".join(f"Section {i}. " + rng.randbytes(40).hex() for i in range(n // 90 + 1))[:n]


def test_post_decision_records_once_per_request(monkeypatch, transport):
    """A transport that fails twice and then succeeds is still one logical request."""
    from mailroom_sandbox.job import read_ranges

    _, calls, _ = transport
    doc = _read_doc()

    def post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) <= 2:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"answers": {}, "usage": {}})

    monkeypatch.setattr(httpx, "post", post)
    out: list[dict] = []
    body = {"model": "m", "state": {"document": doc, "extraction_handoff": {"doc_type": "contract"}},
            "questions": {"q": {"type": "choice"}}}
    with read_ranges.document("d1", doc, out.append):
        assert db._post_decision(body, timeout=120, attempts=3) == {"answers": {}, "usage": {}}
    assert len(calls) == 3
    assert len(out) == 1
    assert out[0]["agent"] == "decisions:extraction_gate"
    assert out[0]["ranges"] == [[0, len(doc)]]


@pytest.mark.parametrize("state_extra,lane", [
    ({"closed_field_handoff": {"field": "f"}}, "closed_field_resolver"),
    ({"extraction_handoff": {"doc_type": "c"}}, "extraction_gate"),
    ({"sorter_handoff": {"doc_type": "c"}}, "classification"),
    ({}, "classification"),
])
def test_post_decision_lane_comes_from_the_state_shape(monkeypatch, transport, state_extra, lane):
    from mailroom_sandbox.job import read_ranges

    doc = _read_doc()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={}))
    out: list[dict] = []
    with read_ranges.document("d1", doc, out.append):
        db._post_decision({"model": "m", "state": {"document": doc, **state_extra}, "questions": {}},
                          timeout=120, attempts=1)
        db._post_decision({"model": "m", "state": doc, "questions": {}}, timeout=120, attempts=1)
    assert [r["agent"] for r in out] == [f"decisions:{lane}", "decisions:classification"]


def test_unsent_request_is_not_recorded(monkeypatch, transport):
    from mailroom_sandbox.job import read_ranges

    monkeypatch.delenv("OPENROUTER_API_KEY")
    out: list[dict] = []
    with read_ranges.document("d1", "x" * 500, out.append):
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            db._post_decision({"state": "x" * 500, "questions": {}}, timeout=120, attempts=1)
    assert out == []


def test_request_refused_by_the_call_guard_is_not_recorded(monkeypatch, transport):
    """A request the call guard stops before sending leaves no read record."""
    from mailroom_sandbox.job import call_guard, read_ranges

    _, calls, _ = transport
    doc = _read_doc()

    def refuse(*_size):
        raise RuntimeError("call ceiling reached")

    monkeypatch.setattr(call_guard, "before_call", refuse)
    out: list[dict] = []
    with read_ranges.document("d1", doc, out.append):
        with pytest.raises(RuntimeError, match="call ceiling"):
            db._post_decision({"model": "m", "state": {"document": doc}, "questions": {}},
                              timeout=120, attempts=3)
    assert out == [] and calls == []


def test_request_past_the_run_deadline_is_not_recorded(monkeypatch, transport):
    """An expired run deadline stops the request before sending, so nothing is recorded."""
    from mailroom_sandbox.job import read_ranges

    _, calls, _ = transport
    doc = _read_doc()
    monkeypatch.setattr(limits, "get_run_deadline", lambda: 99.0)
    out: list[dict] = []
    with read_ranges.document("d1", doc, out.append):
        with pytest.raises(limits.RunDeadlineExceeded):
            db._post_decision({"model": "m", "state": {"document": doc}, "questions": {}},
                              timeout=120, attempts=3)
    assert out == [] and calls == []


def test_request_sent_once_then_refused_on_retry_is_recorded_once(monkeypatch, transport):
    """The first attempt passed the guard and went out, so it counts, once, even if a retry is refused."""
    from mailroom_sandbox.job import call_guard, read_ranges

    _, calls, _ = transport
    doc = _read_doc()
    real = call_guard.before_call
    seen = []

    def guard(*_size):
        seen.append(1)
        if len(seen) > 1:
            raise RuntimeError("call ceiling reached")
        real()

    monkeypatch.setattr(call_guard, "before_call", guard)
    out: list[dict] = []
    with read_ranges.document("d1", doc, out.append):
        with pytest.raises(RuntimeError, match="call ceiling"):
            db._post_decision({"model": "m", "state": {"document": doc}, "questions": {}}, timeout=120, attempts=3)
    assert len(calls) == 1 and len(out) == 1


def test_masked_digits_leave_a_gap_not_an_error(monkeypatch, transport):
    from mailroom_sandbox.job import read_ranges

    doc = _read_doc(1400)
    mid = len(doc) // 2
    doc = doc[:mid] + " 4111 1111 1111 1111 " + doc[mid:]
    masked = db.mask_card_numbers(doc)
    assert masked != doc and len(masked) == len(doc)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={}))
    out: list[dict] = []
    with read_ranges.document("d1", doc, out.append):
        db._post_decision({"model": "m", "state": {"document": masked}, "questions": {}},
                          timeout=120, attempts=1)
        stats = read_ranges.stats()
    assert len(out) == 1 and len(out[0]["ranges"]) == 2
    assert stats["read_errors"] == 0


# S2 (phase 1): each Decisions attempt reserves its cost and settles it.


@pytest.fixture
def armed_budget():
    from mailroom_sandbox.job import api_budget, call_guard

    budget = api_budget.ApiBudget(1.0, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    call_guard.arm(budget, None)
    yield budget
    call_guard.disarm()


def test_a_decisions_attempt_reserves_and_settles(monkeypatch, transport, armed_budget):
    _, calls, _ = transport
    held = []
    responses = [httpx.Response(200, json={"usage": {"prompt_tokens": 10, "completion_tokens": 1}}),
                 httpx.Response(400, text="bad request")]

    def post(*args, **kwargs):
        calls.append(kwargs)
        held.append(armed_budget.reserved_usd)
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", post)
    body = {"model": "m", "messages": [{"role": "user", "content": "x" * 4000}]}
    db._post_decision(body, timeout=120, attempts=1)
    assert held[0] > 0 and armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd == 0.0
    with pytest.raises(RuntimeError, match="Decisions API 400"):
        db._post_decision(body, timeout=120, attempts=1)
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd == 0.0  # rejected, not billed


def test_a_decisions_timeout_is_charged_at_its_reservation(monkeypatch, transport, armed_budget):
    def post(*args, **kwargs):
        raise httpx.ReadTimeout("no response")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(httpx.ReadTimeout):
        db._post_decision({"model": "m", "messages": [{"content": "x" * 4000}]}, timeout=120, attempts=1)
    assert armed_budget.reserved_usd == 0.0 and armed_budget.unreported_usd > 0


# --- L1: a failed Decisions attempt still counts toward the document's budget ---------------

def test_each_failed_decisions_attempt_counts_toward_the_document(monkeypatch, transport):
    from mailroom_sandbox.job import call_guard

    _, calls, _ = transport  # every attempt answers 429
    with call_guard.document() as doc:
        with pytest.raises(RuntimeError, match="Decisions API 429"):
            db._post_decision({}, timeout=120, attempts=3)
    assert len(calls) == 3 and doc["llm_calls"] == 3


def test_a_decisions_transport_failure_counts_toward_the_document(monkeypatch, transport):
    from mailroom_sandbox.job import call_guard

    def post(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", post)
    with call_guard.document() as doc:
        with pytest.raises(httpx.ConnectError):
            db._post_decision({}, timeout=120, attempts=2)
    assert doc["llm_calls"] == 2


def test_a_decisions_200_is_priced_with_nothing_left_awaiting_a_price(monkeypatch, transport, armed_budget):
    from mailroom_sandbox.job import call_guard

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        200, json={"usage": {"prompt_tokens": 10, "completion_tokens": 1}}))
    with call_guard.document():
        db._post_decision({"model": "m", "messages": [{"content": "x" * 4000}]}, timeout=120, attempts=1)
        assert armed_budget.settling_usd == 0.0 and armed_budget.reserved_usd == 0.0
    assert armed_budget.live_total_usd() == pytest.approx(armed_budget.estimate_call_usd(10, 1))


@pytest.mark.parametrize("response", [httpx.Response(200, text="not json"), httpx.Response(200, json=["a list"])],
                         ids=["not-json", "not-an-object"])
def test_a_decisions_200_whose_body_cannot_be_read_is_charged_not_held(monkeypatch, transport, armed_budget,
                                                                       response):
    """The reply came back, so it may have been billed, but there is no usage to price it from: it is
    charged at its reservation in the step that drops it, and nothing waits for a price."""
    from mailroom_sandbox.job import call_guard

    monkeypatch.setattr(httpx, "post", lambda *a, **k: response)
    with call_guard.document() as doc:
        with pytest.raises(Exception):
            db._post_decision({"model": "m", "messages": [{"content": "x" * 4000}]}, timeout=120, attempts=1)
        assert armed_budget.settling_usd == 0.0 and armed_budget.reserved_usd == 0.0
    assert armed_budget.unreported_usd > 0 and doc["llm_calls"] == 1
