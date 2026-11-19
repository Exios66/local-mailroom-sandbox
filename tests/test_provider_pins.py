"""Provider pins + served-provider ledger (R01). Fake vendored modules; no network."""

from __future__ import annotations

import json
import sys
import types

import pytest

from mailroom_sandbox import provider_pins as pp


class _Resp:
    def __init__(self, model, provider):
        self.model = model
        self.model_extra = {"provider": provider}


class _Client:
    def __init__(self, base_url):
        self.base_url = base_url


@pytest.fixture
def vendored(monkeypatch):
    seen = []

    def original(client, **kwargs):
        seen.append(kwargs)
        return _Resp(kwargs["model"], "Served-Co")

    llm = types.ModuleType("llm")
    retry = types.ModuleType("llm.retry")
    retry.retry_chat_completion = original
    llm.retry = retry
    agents = types.ModuleType("agents")
    base = types.ModuleType("agents.base")
    base.retry_chat_completion = original
    agents.base = base
    for name, mod in (("llm", llm), ("llm.retry", retry), ("agents", agents), ("agents.base", base)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(pp, "_ORIGINAL", None)
    pp.reset_ledger()
    yield seen, base
    pp.restore()
    pp.reset_ledger()


PINS = {"qwen/qwen3.7-flash": {"order": ["Alibaba"], "allow_fallbacks": False,
                              "canonical_slug": None, "reasoning_effort": None},
        "deepseek/x": {"order": [], "allow_fallbacks": False, "canonical_slug": None, "reasoning_effort": None}}


def test_pin_merges_into_extra_body_and_keeps_existing_provider_keys(vendored):
    seen, base = vendored
    assert pp.apply_provider_pins(PINS) == 1
    client = _Client("https://openrouter.ai/api/v1")
    base.retry_chat_completion(client, model="qwen/qwen3.7-flash",
                               extra_body={"provider": {"require_parameters": True}, "reasoning": {"effort": "low"}})
    sent = seen[-1]["extra_body"]
    assert sent["provider"] == {"require_parameters": True, "order": ["Alibaba"], "allow_fallbacks": False}
    assert sent["reasoning"] == {"effort": "low"}
    entry = pp.ledger()[-1]
    assert entry["served_provider"] == "Served-Co" and entry["mismatch"] is True


def test_unpinned_model_is_recorded_not_routed(vendored, tmp_path, monkeypatch):
    seen, base = vendored
    log = tmp_path / "served.jsonl"
    monkeypatch.setenv("SANDBOX_SERVED_LOG", str(log))
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="deepseek/x")
    assert "extra_body" not in seen[-1]
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["requested_model"] == "deepseek/x" and row["mismatch"] is False
    assert pp.summarize(pp.ledger())["deepseek/x"]["providers"] == {"Served-Co": 1}


def test_non_openrouter_calls_pass_through(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://example.modal.run/v1"), model="qwen/qwen3.7-flash")
    assert "extra_body" not in seen[-1]
    assert pp.ledger() == []


def test_reapply_does_not_stack_wrappers(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    pp.apply_provider_pins(PINS)
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash")
    assert len(seen) == 1 and len(pp.ledger()) == 1


def test_committed_pin_file_parses():
    pins = pp.load_pins()
    assert "qwen/qwen3.7-flash" in pins
    assert all(p["allow_fallbacks"] is False for p in pins.values())


def test_provider_compare_ignores_case_and_flags_a_substituted_model(vendored, monkeypatch):
    seen, base = vendored
    pins = {"z/glm": {"order": ["served-co"], "allow_fallbacks": False, "canonical_slug": "z/glm-20261102"}}
    pp.apply_provider_pins(pins)
    client = _Client("https://openrouter.ai/api/v1")
    base.retry_chat_completion(client, model="z/glm")  # served model == requested
    first = pp.ledger()[-1]
    assert first["provider_mismatch"] is False and first["mismatch"] is False

    def dated(client, **kwargs):
        seen.append(kwargs)
        return _Resp("z/glm-20261102", "Served-Co")

    monkeypatch.setattr(pp, "_ORIGINAL", dated)
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="z/glm")
    assert pp.ledger()[-1]["mismatch"] is False  # the canonical dated slug is allowed

    def other(client, **kwargs):
        return _Resp("z/glm-lite", "Served-Co")

    monkeypatch.setattr(pp, "_ORIGINAL", other)
    pp.apply_provider_pins(pins)
    base.retry_chat_completion(client, model="z/glm")
    last = pp.ledger()[-1]
    assert last["model_mismatch"] is True and last["mismatch"] is True


def test_explicit_fallback_chain_is_recorded_not_pinned(vendored):
    seen, base = vendored
    pp.apply_provider_pins(PINS)
    body = {"models": ["qwen/qwen3.7-flash", "deepseek/x"]}
    base.retry_chat_completion(_Client("https://openrouter.ai/api/v1"), model="qwen/qwen3.7-flash", extra_body=body)
    assert "provider" not in seen[-1]["extra_body"]
    assert len(pp.ledger()) == 1
