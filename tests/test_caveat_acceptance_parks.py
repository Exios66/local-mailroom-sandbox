"""HF-034: with ``confidence.caveat_acceptance_parks`` on a class, an arbiter acceptance parks.

Network-free: the real compiled graph with the judge and arbiter nodes real and their model calls
scripted (``_arbiter_harness``), on the OpenRouter route the live smokes ran.
"""
from __future__ import annotations

import pytest
from _arbiter_harness import Script, activate_profile, run, arbiter_harness_state  # noqa: F401 (fixture)

from mailroom_sandbox import source_windows
from mailroom_sandbox import vendor_hotfixes as vh

pytestmark = pytest.mark.usefixtures("arbiter_harness_state")

IN_BAND = [0.88] * 6  # at or above corporate_record ``low`` (0.86): the vendored route archives an acceptance
UNSURE = [0.5] * 6


@pytest.fixture
def openrouter(monkeypatch, tmp_path):
    yield activate_profile(monkeypatch, tmp_path, "openrouter")
    source_windows.apply_source_windows({})


def _with(monkeypatch, **keys):
    import graph.routing as routing

    original = routing._thresholds_for  # the keys a run's ``confidence`` block would carry
    monkeypatch.setattr(routing, "_thresholds_for", lambda state: {**original(state), **keys})


def _accept(confs=IN_BAND, **extra) -> Script:
    return Script(confs=confs, judge=[("complete", "partial")] * 3, arbiter=["accept_with_caveats"] * 3, **extra)


def test_the_hotfix_is_applied_with_hf014():
    status = vh.apply_hotfixes()
    assert status["HF-034"] == "applied" and status["HF-014"] == "applied"
    from graph import route_spec

    names = [rule.name for rule in route_spec.route_rules("arbiter")]
    assert names.index(vh.CAVEAT_PARK_RULE) > names.index(vh.FULL_SOURCE_RULE)


def test_without_the_key_an_in_band_acceptance_still_archives(openrouter, monkeypatch):
    out = run(openrouter, monkeypatch, _accept())
    assert out["stage"] == "archived", out["path"]


def test_the_key_parks_an_in_band_acceptance(openrouter, monkeypatch):
    _with(monkeypatch, **{vh.CAVEAT_PARK_KEY: True})
    out = run(openrouter, monkeypatch, _accept())
    assert out["stage"] == "review", out["path"]
    assert out["path"][-2:] == ["arbiter", "human_review"]
    assert vh.arbiter_caveats(out["state"]) is None  # a parked acceptance is not a caveat archive


def test_false_leaves_the_route_unchanged(openrouter, monkeypatch):
    _with(monkeypatch, **{vh.CAVEAT_PARK_KEY: False})
    assert run(openrouter, monkeypatch, _accept())["stage"] == "archived"


def test_the_key_overrides_a_lowered_hf014_floor(openrouter, monkeypatch):
    """HF-014 turns an unsure acceptance into an archive at a lowered floor; HF-034 keeps it parked."""
    _with(monkeypatch, **{vh.FULL_SOURCE_FLOOR_KEY: 0.5})
    assert run(openrouter, monkeypatch, _accept(confs=UNSURE))["stage"] == "archived"
    _with(monkeypatch, **{vh.FULL_SOURCE_FLOOR_KEY: 0.5, vh.CAVEAT_PARK_KEY: True})
    assert run(openrouter, monkeypatch, _accept(confs=UNSURE))["stage"] == "review"


def test_hf011_skips_the_arbiter_on_a_last_partial_pass(openrouter, monkeypatch):
    """The last pass's acceptance would park, so no arbiter call is spent on it."""
    script = Script(confs=IN_BAND, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
    before = run(openrouter, monkeypatch, script)
    assert before["stage"] == "archived" and before["arbiter"] == 2, before["path"]
    _with(monkeypatch, **{vh.CAVEAT_PARK_KEY: True})
    after = run(openrouter, monkeypatch, script)
    assert after["stage"] == "review" and after["arbiter"] == 1
    assert after["path"][-2:] == ["judge_verify", "human_review"]


def test_a_retry_ruling_keeps_its_route(openrouter, monkeypatch):
    _with(monkeypatch, **{vh.CAVEAT_PARK_KEY: True})
    script = Script(confs=IN_BAND, judge=[("partial", "accurate"), ("complete", "accurate")],
                    arbiter=["retry_extraction"])
    out = run(openrouter, monkeypatch, script)
    assert out["stage"] == "archived" and out["arbiter"] == 1, out["path"]


@pytest.mark.parametrize(("value", "ok"), [(True, True), (False, True), ("true", False), (1, False)])
def test_the_key_is_a_boolean_flag_in_a_run_spec(value, ok):
    from mailroom_sandbox.job import spec

    block = {vh.CAVEAT_PARK_KEY: value}
    if ok:
        spec._check_thresholds("confidence", block)
    else:
        with pytest.raises(ValueError, match=vh.CAVEAT_PARK_KEY):
            spec._check_thresholds("confidence", block)
