"""SHF-015: stale Hub labels (the Dojo label policy) are not scored as truth on the headline.

Each test scores a prepared row through the run's own scorer (``runners._score_pipeline_extraction``,
which every pipeline, rescore, pair report and gate path shares) and asserts both sides: the raw
Dojo-pin pass still scores the stale label, the hotfixed headline does not, and a label an overlay
supplied is never dropped. Network-free; no LLM calls.
"""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval import runners
from mailroom_sandbox.eval.scoring import score_extraction_row

TEMPLATED = "Correspondence concerning general_business: Re: Enron"
METADATA_KEYWORDS = json.dumps(["general_business", "email", "allen-p", "_sent_mail", "2000-10-24T12:16:00+00:00"])


def _row(fields, **markers):
    presence = {k: "populated" for k in fields if k not in ("intent_source",)}
    return {"id": "DOC-1", "expected_doc_class": "correspondence", "doc_text": "From: A\nTo: B\nPlease pay now.",
            "expected_fields": json.dumps({**fields, "gt_presence": json.dumps(presence)}), **markers}


HEURISTIC = {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "payment_demand", "intent_source": "heuristic"}


def test_shf015_a_heuristic_intent_is_not_scored_on_the_headline():
    scored = runners._score_pipeline_extraction(
        _row(HEURISTIC), {"extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}})
    assert scored["raw_dojo"]["overall_extraction_score"] < 1.0  # the raw pass scores the heuristic copy
    assert scored["overall_extraction_score"] == 1.0
    assert scored["stale_hub_labels"] == {"intent": "intent_heuristic"}
    assert "SHF-015" in scored["scoring_hotfixes"] and "overall_extraction_score" in scored["scoring_hotfixes_changed"]


def test_shf015_a_dropped_label_is_dropped_from_the_prediction_too():
    # A field with no truth is no scoring event either way: never a false positive or a miss.
    scored = score_extraction_row("correspondence", {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "x"},
                                  {k: v for k, v in HEURISTIC.items()}, overlay_fields=())
    assert scored["n_targeted"] == scored["raw_dojo"]["n_targeted"] - 1
    assert scored.get("fp") in (None, 0)


@pytest.mark.parametrize("marker", [
    {"interim_labels": {"fields": ["intent"], "overlay_sha256": "x"}},
    {"near_gold_labels": {"fields": ["intent"], "overlay_sha256": "y", "status": "near_gold"}},
    {"staged_overlay": {"version": "1", "fields": ["intent"], "overrides": {}}},
    {"interim_labels": json.dumps({"fields": ["intent"], "overlay_sha256": "x"})},  # a parquet shard's marker
])
def test_shf015_never_drops_an_overlay_supplied_label(marker):
    # An interim correction replaces the Hub intent but leaves intent_source "heuristic" on the row.
    row = _row({**HEURISTIC, "intent": "complaint"}, **marker)
    wrong = runners._score_pipeline_extraction(
        row, {"extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "payment_demand"}})
    assert "stale_hub_labels" not in wrong
    assert wrong["overall_extraction_score"] == wrong["raw_dojo"]["overall_extraction_score"] < 1.0


def test_shf015_a_stale_staged_overlay_marker_supplies_nothing():
    row = _row(HEURISTIC, staged_overlay={"version": "1", "fields": [], "overrides": {}, "stale": True})
    scored = runners._score_pipeline_extraction(
        row, {"extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}})
    assert scored["stale_hub_labels"] == {"intent": "intent_heuristic"} and scored["overall_extraction_score"] == 1.0


def test_shf015_templated_correspondence_subject_and_keywords_are_not_truth():
    fields = {"sender": "Ann Lee", "subject_matter": TEMPLATED, "keywords": METADATA_KEYWORDS,
              "intent": "meeting_invite", "intent_source": "llm_zero_shot"}
    answer = {"sender": "Ann Lee", "subject_matter": "Phillip Allen asks to move the gas desk meeting",
              "keywords": ["gas desk", "meeting"], "intent": "meeting_invite"}
    scored = runners._score_pipeline_extraction(_row(fields), {"extracted_data": answer})
    assert scored["stale_hub_labels"] == {"keywords": "keywords_metadata", "subject_matter": "subject_matter_templated"}
    assert scored["raw_dojo"]["overall_extraction_score"] < scored["overall_extraction_score"] == 1.0


def test_shf015_an_llm_intent_is_still_truth():
    fields = {**HEURISTIC, "intent_source": "llm_zero_shot"}
    scored = runners._score_pipeline_extraction(
        _row(fields), {"extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}})
    assert "stale_hub_labels" not in scored
    assert scored["overall_extraction_score"] == scored["raw_dojo"]["overall_extraction_score"] < 1.0


def test_shf015_stays_off_when_the_caller_gives_no_provenance():
    scored = score_extraction_row("correspondence", {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "x"},
                                  dict(HEURISTIC))
    assert "SHF-015" not in scored["scoring_hotfixes"] and "stale_hub_labels" not in scored


def test_shf015_a_dropped_label_becomes_unlabelled_not_a_documented_absence():
    expected = {**HEURISTIC, "gt_presence": json.dumps({"intent": "populated", "sender": "populated"})}
    out, dropped = sh.drop_stale_hub_truth("correspondence", expected, ())
    assert dropped == {"intent": "intent_heuristic"} and "intent" not in out
    assert json.loads(out["gt_presence"])["intent"] == "pending_annotation"
    assert sh.documented_absent_fields("correspondence", out) == []  # SHF-001 never restores it
    assert json.loads(expected["gt_presence"])["intent"] == "populated"  # the input is never mutated


def test_a_pipeline_item_keeps_its_raw_side_and_names_its_fixes():
    row = _row(HEURISTIC)
    result = {"doc_type": "correspondence", "stage": "archived",
              "extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}}
    scored = runners._score_pipeline_extraction(row, result)
    item = runners.pipeline_item_score(row, result, scored)
    assert item["overall_extraction_score"] == 1.0
    assert item["raw_dojo"]["overall_extraction_score"] == scored["raw_dojo"]["overall_extraction_score"] < 1.0
    assert "SHF-015" in item["scoring_hotfixes"]
    plain = runners.pipeline_item_score(row, result, None)
    assert "raw_dojo" not in plain and plain["scoring_hotfixes"] == []


def test_a_pipeline_item_records_the_stale_labels_it_dropped():
    """The item record in items.jsonl names each dropped field and why; a clean row carries no key."""
    result = {"doc_type": "correspondence", "stage": "archived",
              "extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}}
    stale_row = _row(HEURISTIC)
    stale = runners.pipeline_item_score(stale_row, result, runners._score_pipeline_extraction(stale_row, result))
    assert stale["stale_hub_labels"] == {"intent": "intent_heuristic"}
    clean_row = _row({**HEURISTIC, "intent_source": "llm_zero_shot"})
    clean = runners.pipeline_item_score(clean_row, result, runners._score_pipeline_extraction(clean_row, result))
    assert "stale_hub_labels" not in clean
    assert "stale_hub_labels" not in runners.pipeline_item_score(stale_row, result, None)


def test_a_rescored_item_carries_the_stale_labels_too():
    from mailroom_sandbox import rescore

    row = _row(HEURISTIC)
    pred = {"doc_type": "correspondence", "stage": "archived",
            "extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu", "intent": "complaint"}}
    item = rescore.scorer_for({"task": "pipeline"})(row, pred)
    assert item["stale_hub_labels"] == {"intent": "intent_heuristic"}
