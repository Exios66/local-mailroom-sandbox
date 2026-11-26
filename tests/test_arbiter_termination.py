"""Every judge/arbiter path ends at archive or human review within a fixed node-visit bound.

Network-free property test over the real compiled graph (``_arbiter_harness``): judge verdicts
(including parse failures and a transient blip) x arbiter decisions (including blips) x
extraction confidence, on the OpenRouter overlay settings (context-fitted windows, HF-011 to
HF-015 active) and on Modal/vLLM (16k excerpts). Decision-lane transport failures run the
Decisions HTTP retry loop for real (#413: three attempts, none once the run deadline has
passed), and an oversize document meets the API-route refusals (HF-009/HF-010). A matter
conflict meets each Boss answer, and a mid-band sorter each classification-arbiter ruling.

Extraction confidence: ``sure`` (above ``judge_band_high``), ``mid`` (in the judge band, at or above
the class ``low``), ``unsure`` (below ``low``; HF-014's default floor parks its acceptance) and
``unsure_floor`` (the same, with the run's floor lowered to 0.5 so HF-014 archives it).

The budgets are the overlay's: ``retry_max`` 1, ``arbiter_retry_max`` 1, ``judge_max_passes`` 2,
``transient_retry_max`` 1. The per-lane bounds asserted below follow from them.
"""
from __future__ import annotations

import itertools

import pytest
from _arbiter_harness import LONG, SHORT, VISIT_BOUND, Script, activate_profile, run, arbiter_harness_state  # noqa: F401 (fixture)

from mailroom_sandbox import source_windows
from mailroom_sandbox import vendor_hotfixes as vh

pytestmark = pytest.mark.usefixtures("arbiter_harness_state")

JUDGE = {"complete": [("complete", "accurate")], "partial": [("partial", "accurate")],
         "incomplete": [("incomplete", "accurate")], "parse_c": ["parse_c"], "parse_a": ["parse_a"],
         "parse_c_once": ["parse_c_once"], "parse_a_once": ["parse_a_once"],
         "blip_partial": ["blip", ("partial", "accurate")]}
ARBITER = {"accept": ["accept_with_caveats"], "retry_accept": ["retry_extraction", "accept_with_caveats"],
           "retry": ["retry_extraction"], "blip": ["blip"]}
#: name -> (confidence per extraction, the run's HF-014 floor or None for the class ``low``)
CONF = {"sure": ([0.95] * 6, None), "mid": ([0.88] * 6, None), "unsure": ([0.5] * 6, None),
        "unsure_floor": ([0.5] * 6, 0.5)}
# OpenRouter: the whole product. Modal/vLLM: the unsure cases, where HF-014 would act if it leaked.
CASES = ([("openrouter", *c) for c in itertools.product(JUDGE, ARBITER, CONF)]
         + [("modal-vllm", j, a, c) for j, a, c in itertools.product(
             ("partial", "incomplete", "blip_partial", "parse_a", "parse_a_once"), ARBITER,
             ("unsure", "unsure_floor"))])
BOSS = ("approve", "reject", "blip")
CONFLICT_CASES = ([("openrouter", *c) for c in itertools.product(
                      ("complete", "partial", "incomplete"), ("accept", "retry_accept"),
                      ("sure", "unsure", "unsure_floor"), BOSS)]
                  + [("modal-vllm", "partial", a, "unsure_floor", b)
                     for a, b in itertools.product(("accept", "retry_accept"), BOSS)])
#: classification arbiter: (decision, confidence); ``low`` accepts the sorter without conviction
CARB = {"accept_sorter": ("accept_sorter", 0.99), "accept_reviewer": ("accept_reviewer", 0.99),
        "human_review": ("human_review", 0.1), "low": ("accept_sorter", 0.1)}
CARB_CASES = [(p, *c) for p in ("openrouter", "modal-vllm")
              for c in itertools.product((("complete", "accept", "sure"), ("partial", "accept", "unsure_floor")), CARB)]
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
    # HF-002 / HF-013: a parse failure is re-asked once, so a judge method makes at most two model
    # calls per pass (``judge_c`` / ``judge_a`` count first asks, the ``*_reasks`` keys the re-asks)
    assert out["judge_c_reasks"] <= out["judge_c"] and out["judge_a_reasks"] <= out["judge_a"], out["path"]
    assert out["judge_c"] + out["judge_c_reasks"] <= 2 * out["judge_c"], out["path"]
    assert out["arbiter"] <= 2 and out["carb"] <= 1, out["path"]
    state = out["state"]
    if out["stage"] == "archived":
        # A judge that never answered never archives (HF-002 / HF-013) ...
        assert state.get("judge_verdict") != "judge_error", out["path"]
        # ... and neither does a matter conflict without the Boss's approval of that conflict
        if state.get("conflict_detected"):
            assert state.get("review_decision") == "approved", out["path"]


def _script(conf: str, **kw) -> Script:
    confs, floor = CONF[conf]
    return Script(confs=confs, floor=floor, **kw)


def _assert_marker(out: dict, profile: str, conf: str, marker: dict | None) -> None:
    state = out["state"]
    if out["stage"] == "archived" and state.get("arbiter_decision") == "accept_with_caveats":
        assert marker is not None
        # HF-014 archives an unsure acceptance only where the arbiter read the whole source and the
        # run lowered the floor below the confidence; at the default floor it changes no route
        assert marker["hf014"] == (conf == "unsure_floor" and profile == "openrouter"), out["path"]
        assert conf != "unsure", out["path"]


@pytest.mark.parametrize(("profile", "judge", "arbiter", "conf"), CASES)
def test_every_judge_and_arbiter_path_terminates(profile, judge, arbiter, conf, monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        out = run(bg, monkeypatch, _script(conf, judge=JUDGE[judge], arbiter=ARBITER[arbiter]))
        marker = vh.arbiter_caveats(out["state"])  # as the runner records it: windows still active
    finally:
        source_windows.apply_source_windows({})
    _assert_terminates(out)
    state = out["state"]
    if judge in ("parse_c", "parse_a"):  # HF-002 / HF-013: a judge that never answered is never archived
        assert out["stage"] == "review" and state.get("judge_verdict") == "judge_error"
        assert out[f"judge_{judge[-1]}_reasks"] == 1, out["path"]  # asked once more, then parked
    elif judge.endswith("_once"):  # the re-ask parsed: a verdict like any other, and exactly one re-ask
        assert state.get("judge_verdict") != "judge_error", out["path"]
        assert out[f"judge_{judge[-6]}_reasks"] == 1, out["path"]
    else:
        assert out["judge_c_reasks"] == out["judge_a_reasks"] == 0, out["path"]
    _assert_marker(out, profile, conf, marker)
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


@pytest.mark.parametrize(("profile", "judge", "arbiter", "conf", "boss"), CONFLICT_CASES)
def test_a_matter_conflict_archives_only_with_the_boss_approval(profile, judge, arbiter, conf, boss,
                                                                monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        out = run(bg, monkeypatch, _script(conf, judge=JUDGE[judge], arbiter=ARBITER[arbiter],
                                           conflict=True, boss=boss))
        marker = vh.arbiter_caveats(out["state"])
    finally:
        source_windows.apply_source_windows({})
    _assert_terminates(out)  # includes: archived => the Boss approved this conflict
    _assert_marker(out, profile, conf, marker)
    if boss != "approve":
        assert out["stage"] == "review", out["path"]


@pytest.mark.parametrize(("profile", "lane", "carb"), [(p, lane, c) for p, lane, c in CARB_CASES])
def test_a_mid_band_sorter_meets_every_classification_ruling(profile, lane, carb, monkeypatch, tmp_path):
    judge, arbiter, conf = lane
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        out = run(bg, monkeypatch, _script(conf, sorter=None, judge=JUDGE[judge], arbiter=ARBITER[arbiter],
                                           carb=CARB[carb]))
        marker = vh.arbiter_caveats(out["state"])
    finally:
        source_windows.apply_source_windows({})
    _assert_terminates(out)
    _assert_marker(out, profile, conf, marker)
    assert out["carb"] == 1 and "classification_arbiter" in out["path"], out["path"]
    if carb in ("human_review", "low"):  # no confident classification ruling, no archive
        assert out["stage"] == "review", out["path"]


@pytest.mark.parametrize("profile", ["openrouter", "modal-vllm"])
@pytest.mark.parametrize("failing", ["c", "a"])
def test_a_judge_parse_failure_followed_by_a_parsed_answer_continues_as_if_it_parsed_first(
        failing, profile, monkeypatch, tmp_path):
    """HF-002 / HF-013: one unparseable answer no longer parks a document the judge would have passed."""
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        control = run(bg, monkeypatch, Script(judge=[("complete", "accurate")]))
        control_path = list(control["path"])  # a second run re-wraps the nodes and keeps appending to this list
        once = run(bg, monkeypatch, Script(judge=[f"parse_{failing}_once"]))
    finally:
        source_windows.apply_source_windows({})
    assert control["stage"] == "archived" and control["judge_c_reasks"] == control["judge_a_reasks"] == 0
    assert once["stage"] == "archived" and once["path"] == control_path
    assert once["state"]["judge_verdict"] == control["state"]["judge_verdict"] == "complete"
    assert once[f"judge_{failing}_reasks"] == 1 and once[f"judge_{'a' if failing == 'c' else 'c'}_reasks"] == 0
    assert once["judge_passes"] == control["judge_passes"] == 1  # a re-ask is not a pass
    assert once["arbiter"] == 0 and once["extract_calls"] == control["extract_calls"] == 1


@pytest.mark.parametrize("profile", ["openrouter", "modal-vllm"])
@pytest.mark.parametrize("failing", ["c", "a"])
def test_two_judge_parse_failures_park_as_judge_error_with_two_calls_for_that_judge(
        failing, profile, monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, profile)
    try:
        out = run(bg, monkeypatch, Script(judge=[f"parse_{failing}"], arbiter=["accept_with_caveats"]))
    finally:
        source_windows.apply_source_windows({})
    assert out["stage"] == "review" and out["state"]["judge_verdict"] == "judge_error", out["path"]
    assert out["path"][-2:] == ["judge_verify", "human_review"] and out["arbiter"] == 0, out["path"]
    assert out[f"judge_{failing}"] + out[f"judge_{failing}_reasks"] == 2  # never a third call
    assert out["judge_passes"] == 1 and "judge_error" in out["state"].get("review_causes", ["judge_error"])
