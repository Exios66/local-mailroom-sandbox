"""Every judge/arbiter path ends at archive or human review within a fixed node-visit bound.

Network-free property test over the real compiled graph (``_arbiter_harness``): judge verdicts
(including parse failures and a transient blip) x arbiter decisions (including blips) x
extraction confidence, on the OpenRouter overlay settings (context-fitted windows, HF-011 to
HF-015 active) and on Modal/vLLM (16k excerpts). Decision-lane transport failures run the
Decisions HTTP retry loop for real (#413: three attempts, none once the run deadline has
passed), and an oversize document meets the API-route refusals (HF-009/HF-010).

The budgets are the overlay's: ``retry_max`` 1, ``arbiter_retry_max`` 1, ``judge_max_passes`` 2,
``transient_retry_max`` 1. The per-lane bounds asserted below follow from them.
"""
from __future__ import annotations

import itertools

import pytest
from _arbiter_harness import LONG, SHORT, VISIT_BOUND, Script, activate_profile, run

from mailroom_sandbox import source_windows
from mailroom_sandbox import vendor_hotfixes as vh

JUDGE = {"complete": [("complete", "accurate")], "partial": [("partial", "accurate")],
         "incomplete": [("incomplete", "accurate")], "parse_c": ["parse_c"], "parse_a": ["parse_a"],
         "blip_partial": ["blip", ("partial", "accurate")]}
ARBITER = {"accept": ["accept_with_caveats"], "retry_accept": ["retry_extraction", "accept_with_caveats"],
           "retry": ["retry_extraction"], "blip": ["blip"]}
CONF = {"sure": [0.95] * 6, "unsure": [0.5] * 6}
# OpenRouter: the whole product. Modal/vLLM: the unsure cases, where HF-014 would act if it leaked.
CASES = ([("openrouter", *c) for c in itertools.product(JUDGE, ARBITER, CONF)]
         + [("modal-vllm", j, a, "unsure") for j, a in itertools.product(
             ("partial", "incomplete", "blip_partial", "parse_a"), ARBITER)])
SPECIAL = {"decisions_down": {"sorter": None, "decisions_down": True, "carb": ("accept_sorter", 0.99)},
           "decisions_down_deadline": {"sorter": None, "decisions_down": True, "deadline_passed": True,
                                       "carb": ("accept_sorter", 0.99)},
           "oversize_sorter": {"classify_raises": vh.WholeDocumentTooLong("harness: too long")},
           "oversize_specialist": {"extract_raises": vh.WholeDocumentTooLong("harness: too long")}}
#: Tighter than ``VISIT_BOUND``: the longest path any case takes is 13 visits.
MAX_VISITS = 14


def _assert_terminates(out: dict) -> None:
    assert out["visits"] <= min(MAX_VISITS, VISIT_BOUND), out["path"]
    assert out["path"][-1] in ("archive", "human_review"), out["path"]
    assert out["stage"] in ("archived", "review"), (out["stage"], out["path"])
    if out["stage"] == "archived":
        assert out["path"][-3:] == ["compile_report", "catalog_write", "archive"], out["path"]
    # per-lane budgets: 1 extraction + 1 confidence retry + 1 arbiter retry; 2 judge passes + 1
    # transient re-run; 1 arbiter retry ruling + its final ruling; one classification ruling
    assert out["extract_calls"] <= 3 and out["judge_passes"] <= 3, out["path"]
    assert out["arbiter"] <= 2 and out["carb"] <= 1, out["path"]


@pytest.mark.parametrize(("profile", "judge", "arbiter", "conf"), CASES)
def test_every_judge_and_arbiter_path_terminates(profile, judge, arbiter, conf, monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        out = run(bg, monkeypatch, Script(confs=CONF[conf], judge=JUDGE[judge], arbiter=ARBITER[arbiter]))
        marker = vh.arbiter_caveats(out["state"])  # as the runner records it: windows still active
    finally:
        source_windows.apply_source_windows({})
    _assert_terminates(out)
    state = out["state"]
    if judge.startswith("parse"):  # HF-002 / HF-013: a judge that never answered is never archived
        assert out["stage"] == "review" and state.get("judge_verdict") == "judge_error"
    if out["stage"] == "archived" and state.get("arbiter_decision") == "accept_with_caveats":
        assert marker is not None
        # HF-014 archives an unsure acceptance only where the arbiter read the whole source
        assert marker["hf014"] == (conf == "unsure") and (profile == "openrouter" or conf == "sure")
    if profile == "modal-vllm":  # HF-015 never touches a Modal/vLLM request
        assert not any(vh.RETRY_CLOSED_NOTE in p for p in out["arbiter_prompts"])
    else:
        # HF-015: a ruling with no re-extraction budget left is never offered a retry
        for prompt, schema in zip(out["arbiter_prompts"], out["arbiter_schemas"]):
            offered = "retry_extraction" in schema["properties"]["decision"]["enum"]
            assert offered != prompt.endswith(vh.RETRY_CLOSED_NOTE)


@pytest.mark.parametrize("profile", ["openrouter", "modal-vllm"])
@pytest.mark.parametrize("case", sorted(SPECIAL))
def test_transport_failures_and_oversize_documents_terminate(case, profile, monkeypatch, tmp_path):
    script = SPECIAL[case]
    bg = activate_profile(monkeypatch, tmp_path, profile, reviewer=script.get("decisions_down", False))
    try:
        out = run(bg, monkeypatch, Script(doc=LONG if profile == "openrouter" else SHORT, **script))
    finally:
        source_windows.apply_source_windows({})
    _assert_terminates(out)
    if case.startswith("decisions_down"):
        # #413: the Decisions transport tries three times, and not at all past the run deadline;
        # the parked decision review then gets the classification arbiter's one ruling
        assert out["decisions_posts"] == (0 if script.get("deadline_passed") else 3)
        assert "classification_arbiter" in out["path"] and out["stage"] == "archived"
    else:  # HF-009 / HF-010 refuse it on an API route (scripted on both): one park, no judge or arbiter call
        assert out["stage"] == "review" and out["arbiter"] == 0 and out["judge_passes"] == 0
