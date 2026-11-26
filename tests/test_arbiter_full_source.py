"""On a full-source route the extraction arbiter's acceptance counts at or above a confidence floor (HF-014) and its last ruling is final (HF-015).

Network-free: the real compiled graph with the judge and arbiter nodes real and their model
calls scripted (``_arbiter_harness``). OpenRouter is activated as a run would be, so context fit
widens the arbiter's source window; Modal/vLLM keeps the vendored 16k excerpt and today's routes.
"""
from __future__ import annotations

import pytest
from _arbiter_harness import DATA, LONG, SHORT, Script, activate_profile, run, arbiter_harness_state  # noqa: F401 (fixture)

from mailroom_sandbox import source_windows
from mailroom_sandbox import vendor_hotfixes as vh

pytestmark = pytest.mark.usefixtures("arbiter_harness_state")

UNSURE = [0.5] * 6  # below the class ``low`` band (corporate_record 0.86) on every attempt
IN_BAND = [0.88] * 6  # at or above ``low``, below ``judge_band_high``: judged, then caveated


@pytest.fixture
def profile_graph(monkeypatch, tmp_path):
    def make(profile: str):
        return activate_profile(monkeypatch, tmp_path, profile)

    yield make
    source_windows.apply_source_windows({})


def _unsure_accept(doc: str = SHORT, *, floor: float | None = 0.5, confs=UNSURE, **extra) -> Script:
    """An acceptance of an unsure extraction; ``floor`` is the run's HF-014 floor (None: class ``low``)."""
    return Script(doc=doc, confs=confs, judge=[("complete", "partial")] * 3,
                  arbiter=["accept_with_caveats"] * 3, floor=floor, **extra)


# --- HF-014: an acceptance from a whole-source reading archives at or above the floor --------------

@pytest.mark.parametrize("doc", [SHORT, LONG], ids=["short", "long"])
def test_openrouter_acceptance_below_the_default_floor_parks(doc, profile_graph, monkeypatch):
    """Unset, the floor is the class ``low``: a 0.5 extraction parks after the acceptance, as before."""
    out = run(profile_graph("openrouter"), monkeypatch, _unsure_accept(doc, floor=None))
    assert out["stage"] == "review", out["path"]
    assert out["path"][-2:] == ["arbiter", "human_review"] and out["arbiter"] == 1
    assert not vh.full_source_accepts(__import__("graph.routing", fromlist=["x"]), out["state"])


def test_openrouter_acceptance_at_the_default_floor_archives_with_the_marker(profile_graph, monkeypatch):
    out = run(profile_graph("openrouter"), monkeypatch, _unsure_accept(floor=None, confs=IN_BAND))
    assert out["stage"] == "archived", out["path"]
    assert out["path"][-4:] == ["arbiter", "compile_report", "catalog_write", "archive"]
    # The vendored route already archives at ``low``: caveated and whole-source, but not HF-014's.
    assert vh.arbiter_caveats(out["state"]) == {"decision": "accept_with_caveats", "reasoning": "harness",
                                                "judge_verdict": "partial", "whole_source": True,
                                                "hf014": False}


@pytest.mark.parametrize(("floor", "stage"), [(0.5, "archived"), (0.6, "review")])
def test_the_override_moves_the_floor(floor, stage, profile_graph, monkeypatch):
    out = run(profile_graph("openrouter"), monkeypatch, _unsure_accept(floor=floor))
    assert out["stage"] == stage, out["path"]
    marker = vh.arbiter_caveats(out["state"])
    assert (marker or {}).get("hf014", False) is (stage == "archived")


@pytest.mark.parametrize("confidence", [None, float("nan"), True, "0.9", 0.49])
def test_a_missing_or_unusable_confidence_never_reaches_the_floor(confidence):
    class Routing:
        @staticmethod
        def _thresholds_for(_state):
            return {"low": 0.86, vh.FULL_SOURCE_FLOOR_KEY: 0.5}

    assert not vh.confidence_floor_met(Routing, {"extraction_confidence": confidence})
    assert vh.confidence_floor_met(Routing, {"extraction_confidence": 0.5})


def test_the_floor_falls_back_to_the_class_low_band():
    class Routing:
        thresholds: dict = {"low": 0.9}

        @classmethod
        def _thresholds_for(cls, _state):
            return cls.thresholds

    assert vh.full_source_floor(Routing, {}) == 0.9
    Routing.thresholds = {}
    assert vh.full_source_floor(Routing, {}) == 0.70  # the vendored ``_extraction_still_unsure`` default


@pytest.mark.parametrize(("value", "ok"), [(0.5, True), (0, True), (1, True), (1.01, False), (-0.1, False),
                                           (True, False), ("0.5", False)])
def test_the_floor_is_a_unit_threshold_in_a_run_spec(value, ok):
    from mailroom_sandbox.job import spec

    block = {vh.FULL_SOURCE_FLOOR_KEY: value}
    if ok:
        spec._check_thresholds("confidence", block)
    else:
        with pytest.raises(ValueError, match=vh.FULL_SOURCE_FLOOR_KEY):
            spec._check_thresholds("confidence", block)


@pytest.mark.parametrize("doc", [SHORT, LONG], ids=["short", "long"])
def test_openrouter_full_source_acceptance_archives_at_a_lowered_floor(doc, profile_graph, monkeypatch):
    out = run(profile_graph("openrouter"), monkeypatch, _unsure_accept(doc))
    assert out["stage"] == "archived", out["path"]
    assert out["path"][-4:] == ["arbiter", "compile_report", "catalog_write", "archive"]
    assert out["arbiter"] == 1 and out["state"]["arbiter_decision"] == "accept_with_caveats"
    assert vh.arbiter_read_whole_source(__import__("graph.routing", fromlist=["x"]), out["state"])


@pytest.mark.parametrize("doc", [SHORT, LONG], ids=["short", "long"])
def test_modal_keeps_parking_an_unsure_acceptance(doc, profile_graph, monkeypatch):
    out = run(profile_graph("modal-vllm"), monkeypatch, _unsure_accept(doc))
    assert out["stage"] == "review" and out["path"][-2:] == ["arbiter", "human_review"]
    assert out["arbiter"] == 1


def test_a_document_longer_than_the_arbiter_window_still_parks(profile_graph, monkeypatch):
    bg = profile_graph("openrouter")
    source_windows.apply_source_windows({"arbiter": 20_000})  # widened, but shorter than LONG
    out = run(bg, monkeypatch, _unsure_accept(LONG))
    assert out["stage"] == "review" and out["path"][-1] == "human_review"


@pytest.mark.parametrize("extra", [
    {"extracted_data": {**DATA, "_failed_chunks": [1]}},
    {"conflict_detected": True, "conflict_details": {"field": "entity_name"}},
], ids=["chunks_lost", "unadjudicated_conflict"])
def test_lost_chunks_or_an_unadjudicated_conflict_never_archive(extra, profile_graph, monkeypatch):
    out = run(profile_graph("openrouter"), monkeypatch, _unsure_accept(extract_extra=extra))
    assert out["stage"] != "archived" and "compile_report" not in out["path"], out["path"]
    assert out["path"][-1] == "human_review"


def test_the_flag_turns_the_rule_off(profile_graph, monkeypatch):
    bg = profile_graph("openrouter")
    import graph.routing as routing

    original = routing._thresholds_for
    monkeypatch.setattr(routing, "_thresholds_for",
                        lambda state: {**original(state), vh.FULL_SOURCE_KEY: False})
    out = run(bg, monkeypatch, _unsure_accept())
    assert out["stage"] == "review"


def test_hf011_still_skips_the_arbiter_below_the_default_floor(profile_graph, monkeypatch):
    script = Script(confs=UNSURE, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
    out = run(profile_graph("openrouter"), monkeypatch, script)
    assert out["stage"] == "review" and out["arbiter"] == 1 and out["path"][-2:] == ["judge_verify", "human_review"]


def test_hf011_asks_the_arbiter_when_its_acceptance_now_archives(profile_graph, monkeypatch):
    """A partial last pass under a lowered floor: HF-011 used to skip the arbiter (acceptance parked)."""
    script = Script(confs=UNSURE, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"], floor=0.5)
    out = run(profile_graph("openrouter"), monkeypatch, script)
    assert out["stage"] == "archived", out["path"]
    assert out["arbiter"] == 2 and out["judge_passes"] == 2


def test_modal_hf011_still_skips_the_arbiter_for_an_unsure_last_pass(profile_graph, monkeypatch):
    script = Script(confs=UNSURE, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
    out = run(profile_graph("modal-vllm"), monkeypatch, script)
    assert out["stage"] == "review" and out["arbiter"] == 1 and out["path"][-2:] == ["judge_verify", "human_review"]


def test_a_caveat_archive_carries_the_marker_onto_the_run_item(profile_graph, monkeypatch):
    bg = profile_graph("openrouter")
    out = run(bg, monkeypatch, _unsure_accept())
    marker = vh.arbiter_caveats(out["state"])
    assert marker == {"decision": "accept_with_caveats", "reasoning": "harness", "judge_verdict": "partial",
                      "whole_source": True, "hf014": True}
    from mailroom_sandbox.eval import runners

    monkeypatch.setattr(bg, "run_pipeline", lambda *a, **k: out["state"])
    item = runners._run_pipeline_doc_once({"id": "d0", "filename": "d0.txt", "doc_text": SHORT,
                                           "expected_doc_class": "corporate_record"}, mock=False)
    assert item["stage"] == "archived" and item["arbiter_caveats"] == marker


def test_a_sure_acceptance_is_marked_but_not_as_hf014(profile_graph, monkeypatch):
    """The vendored route already archived a confident acceptance; it is still caveated, not HF-014's."""
    out = run(profile_graph("modal-vllm"), monkeypatch,
              Script(confs=[0.95] * 4, judge=[("partial", "accurate")], arbiter=["accept_with_caveats"]))
    assert out["stage"] == "archived"
    assert vh.arbiter_caveats(out["state"]) == {"decision": "accept_with_caveats", "reasoning": "harness",
                                                "judge_verdict": "partial", "whole_source": False, "hf014": False}


def test_no_marker_without_a_caveat_acceptance(profile_graph, monkeypatch):
    out = run(profile_graph("openrouter"), monkeypatch, Script())
    assert out["stage"] == "archived" and vh.arbiter_caveats(out["state"]) is None


# --- HF-015: no re-extraction budget left, so the arbiter cannot choose one ------------------------

def _decisions(schema) -> list[str]:
    return list(schema["properties"]["decision"]["enum"])


def test_the_last_ruling_offers_no_retry_on_openrouter(profile_graph, monkeypatch):
    script = Script(confs=[0.95] * 4, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
    out = run(profile_graph("openrouter"), monkeypatch, script)
    first, last = out["arbiter_schemas"]
    assert "retry_extraction" in _decisions(first) and vh.RETRY_CLOSED_NOTE not in out["arbiter_prompts"][0]
    assert _decisions(last) == ["accept_with_caveats", "human_review"]
    assert out["arbiter_prompts"][1].endswith(vh.RETRY_CLOSED_NOTE)
    assert out["stage"] == "archived"


def test_a_retry_answer_without_budget_becomes_a_clean_escalation(profile_graph, monkeypatch):
    """A provider that ignores the enum still cannot re-extract, and the park says why."""
    script = Script(confs=[0.95] * 4, judge=[("partial", "accurate")] * 3, arbiter=["retry_extraction"] * 3)
    out = run(profile_graph("openrouter"), monkeypatch, script)
    assert out["stage"] == "review" and out["arbiter"] == 2 and out["extract_calls"] == 2
    assert out["state"]["arbiter_decision"] == "human_review"
    assert "ordered re-extraction" not in str(out["state"].get("escalation_reason"))


def test_the_retry_count_alone_closes_the_retry(profile_graph, monkeypatch):
    """Judge passes left, but arbiter_retry_max spent: the arbiter still cannot order another retry."""
    bg = profile_graph("openrouter")
    import graph.routing as routing

    original = routing._thresholds_for
    monkeypatch.setattr(routing, "_thresholds_for", lambda state: {**original(state), "judge_max_passes": 3})
    script = Script(confs=[0.95] * 4, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
    out = run(bg, monkeypatch, script)
    assert _decisions(out["arbiter_schemas"][1]) == ["accept_with_caveats", "human_review"]
    assert out["stage"] == "archived"


def test_modal_arbiter_prompts_are_unchanged(profile_graph, monkeypatch):
    script = Script(confs=[0.95] * 4, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "retry_extraction"])
    out = run(profile_graph("modal-vllm"), monkeypatch, script)
    assert all("retry_extraction" in _decisions(s) for s in out["arbiter_schemas"])
    assert not any(vh.RETRY_CLOSED_NOTE in p for p in out["arbiter_prompts"])
    assert out["stage"] == "review"
