"""SAND-037 — run-scoped temperature reaches the vendored specialist calls."""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from mailroom_sandbox import sampling


@pytest.fixture(autouse=True)
def _reset():
    sampling._OVERRIDES.clear()
    yield
    sampling._OVERRIDES.clear()


def _capture_with_signature_of(original):
    """A stand-in with the vendored signature that returns its bound temperature."""
    signature = inspect.signature(original)

    def capture(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return bound.arguments["temperature"]

    capture.__signature__ = signature
    return capture


def test_temperature_overrides_only_names_agents_with_a_temperature():
    knobs = {
        "merger_agreement_specialist": {"max_tokens": 8192, "temperature": 0.7},
        "correspondence_specialist": {"max_tokens": 8192},
        "bad": "not-a-mapping",
    }
    assert sampling.temperature_overrides(knobs) == {"merger_agreement_specialist": 0.7}
    assert sampling.temperature_overrides(None) == {}


@pytest.mark.parametrize(
    ("module_name", "call"),
    [
        # agents/*_specialist.py: self._call_structured(msg, json_schema=..., temperature=0.1, pages=...)
        ("agents.base", lambda fn, obj: fn(obj, "doc", json_schema={}, temperature=0.1, pages=None)),
        # agents.base positional form: (msg, schema, temperature)
        ("agents.base", lambda fn, obj: fn(obj, "doc", {}, 0.1)),
        # langchain_agents/specialist_agents.py: same keyword call site, temperature after system_prompt
        ("langchain_agents.base_agent", lambda fn, obj: fn(obj, "doc", json_schema={}, temperature=0.1, pages=None)),
    ],
)
def test_wrapper_replaces_call_site_temperature_for_named_agents(module_name, call):
    module = pytest.importorskip(module_name)
    original = module.BaseAgent.__dict__["_call_structured"]
    if getattr(original, "__sandbox_sampling__", False):
        original = original.__wrapped__
    wrapped = sampling._wrap(_capture_with_signature_of(original))

    sampling._OVERRIDES.update({"merger_agreement_specialist": 0.7})
    merger = types.SimpleNamespace(agent_name="merger_agreement_specialist")
    other = types.SimpleNamespace(agent_name="correspondence_specialist")
    assert call(wrapped, merger) == 0.7
    assert call(wrapped, other) == 0.1


def test_apply_installs_once_and_clears_on_reactivation(monkeypatch):
    calls = []

    class Agent:
        agent_name = "contracts_specialist"

        def _call_structured(self, user_message, json_schema, system_prompt=None, temperature=None):
            calls.append(temperature)
            return {}

    fake = types.ModuleType("fake_agents_base")
    fake.BaseAgent = Agent
    monkeypatch.setitem(sys.modules, "fake_agents_base", fake)
    monkeypatch.setattr(sampling, "_TARGETS", (("fake_agents_base", "BaseAgent"),))
    monkeypatch.setattr(sampling, "_PATCHED", set())

    active = sampling.apply_sampling_overrides({"contracts_specialist": {"temperature": 0.7}})
    assert active == {"contracts_specialist": 0.7}
    first = Agent.__dict__["_call_structured"]
    sampling.apply_sampling_overrides({"contracts_specialist": {"temperature": 0.7}})
    assert Agent.__dict__["_call_structured"] is first  # wrapped once

    Agent()._call_structured("doc", {}, temperature=0.1)
    assert calls == [0.7]

    # An activation without temperature knobs restores the call-site value.
    assert sampling.apply_sampling_overrides({"contracts_specialist": {"max_tokens": 8192}}) == {}
    Agent()._call_structured("doc", {}, temperature=0.1)
    assert calls == [0.7, 0.1]


def test_grid_posture_knobs_flow_into_overrides():
    from mailroom_sandbox.job.specialist_posture import agent_knobs_for_run

    merger = agent_knobs_for_run("grid-20-merger-specialist-awq-1l4-rerun")
    contracts = agent_knobs_for_run("grid-50-contracts-specialist-awq-2l4-rerun")
    corr = agent_knobs_for_run("grid-50-correspondence-specialist-awq-1l4")
    assert sampling.temperature_overrides(merger) == {"merger_agreement_specialist": 0.7}
    assert sampling.temperature_overrides(contracts) == {"contracts_specialist": 0.7}
    assert sampling.temperature_overrides(corr) == {}
    assert merger["merger_agreement_specialist"]["max_tokens"] == 8192


def test_reactivation_without_explicit_knobs_keeps_the_run_override(monkeypatch):
    """Eval runners re-call activate(profile) mid-run; the env-carried knobs must survive."""
    import json

    from mailroom_sandbox.job.specialist_posture import agent_knobs_for_run
    from mailroom_sandbox.runtime import activate

    knobs = agent_knobs_for_run("grid-20-merger-specialist-awq-1l4-rerun")
    monkeypatch.setenv("SANDBOX_AGENT_KNOBS", json.dumps(knobs))
    activate("ollama", load_env_file=False)
    assert sampling.active_overrides() == {"merger_agreement_specialist": 0.7}
