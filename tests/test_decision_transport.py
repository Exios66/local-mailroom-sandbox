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
