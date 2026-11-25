"""On a full-source route the extraction arbiter's acceptance counts (HF-014).

Network-free: the real compiled graph with the judge and arbiter nodes real and their model
calls scripted (``_arbiter_harness``). OpenRouter is activated as a run would be, so context fit
widens the arbiter's source window; Modal/vLLM keeps the vendored 16k excerpt and today's routes.
"""
from __future__ import annotations

import pytest
from _arbiter_harness import DATA, LONG, SHORT, Script, activate_profile, run

from mailroom_sandbox import source_windows
from mailroom_sandbox import vendor_hotfixes as vh

UNSURE = [0.5] * 6  # below the class ``low`` band on every attempt: acceptance used to park


@pytest.fixture
def profile_graph(monkeypatch, tmp_path):
    def make(profile: str):
        return activate_profile(monkeypatch, tmp_path, profile)

    yield make
    source_windows.apply_source_windows({})


def _unsure_accept(doc: str = SHORT, **extra) -> Script:
    return Script(doc=doc, confs=UNSURE, judge=[("complete", "partial")] * 3,
                  arbiter=["accept_with_caveats"] * 3, **extra)


# --- HF-014: an acceptance from a whole-source reading archives ------------------------------------

@pytest.mark.parametrize("doc", [SHORT, LONG], ids=["short", "long"])
def test_openrouter_full_source_acceptance_archives(doc, profile_graph, monkeypatch):
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


def test_hf011_asks_the_arbiter_when_its_acceptance_now_archives(profile_graph, monkeypatch):
    """A partial last pass on an unsure extraction: HF-011 used to skip the arbiter (acceptance parked)."""
    script = Script(confs=UNSURE, judge=[("partial", "accurate")] * 3,
                    arbiter=["retry_extraction", "accept_with_caveats"])
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

