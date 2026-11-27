"""SHF-015: stale Hub labels (the Dojo label policy) are not scored as truth on the headline.

Each test scores a prepared row through the run's own scorer (``runners._score_pipeline_extraction``,
which every pipeline, rescore, pair report and gate path shares) and asserts both sides: the raw
Dojo-pin pass still scores the stale label, the hotfixed headline does not, and an overlay keeps a
heuristic intent. A value the policy still calls metadata or a record-title template is dropped
even when the overlay lists the field. Network-free; no LLM calls.
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


def test_shf015_an_overlay_does_not_keep_keywords_the_policy_still_calls_metadata():
    """The staged overlay lists keywords after stripping a mailbox path, and the value is still a topic tag.

    Production slice 0100, 28 of 30 correspondence rows. Content keywords must not be scored against that tag.
    """
    fields = {"sender": "Ann Lee", "recipient": "Bo Chu", "keywords": ["energy_market", "email"],
              "intent": "analysis", "intent_source": "llm_zero_shot"}
    row = _row(fields, staged_overlay={"version": "9.3.1-rc.9", "fields": ["keywords", "sender", "recipient"],
                                       "overrides": {"keywords": {"hub_presence": "populated"}}})
    scored = runners._score_pipeline_extraction(
        row, {"extracted_data": {"sender": "Ann Lee", "recipient": "Bo Chu",
                                 "keywords": ["v/x", "forward spreads"], "intent": "analysis"}})
    assert scored["stale_hub_labels"]["keywords"] == "keywords_metadata"
    assert scored["overall_extraction_score"] == 1.0
    assert scored["raw_dojo"]["overall_extraction_score"] < 1.0


def test_shf015_an_overlay_keeps_content_keywords():
    fields = {"sender": "Ann Lee", "keywords": ["Mary", "Canada reports", "Enron"],
              "intent": "analysis", "intent_source": "llm_zero_shot"}
    row = _row(fields, staged_overlay={"version": "9.3.1-rc.9", "fields": ["keywords"]})
    scored = runners._score_pipeline_extraction(
        row, {"extracted_data": {"sender": "Ann Lee", "keywords": ["gas desk"], "intent": "analysis"}})
    assert "keywords" not in scored.get("stale_hub_labels", {})
    assert scored["overall_extraction_score"] < 1.0


def test_shf015_a_corporate_record_title_is_not_truth():
    """All 14 corporate rows on production slice 0100 are ``<label> of <entity>`` plus those two keywords."""
    fields = {"entity_name": "ARTES MEDICAL INC", "record_type": "articles_of_incorporation",
              "subject_matter": "Charter amendment of ARTES MEDICAL INC.",
              "keywords": ["Charter amendment", "ARTES MEDICAL INC"], "intent": "entity_formation",
              "intent_source": "heuristic"}
    row = {**_row(fields), "expected_doc_class": "corporate_record",
           "doc_text": "Certificate of Amendment of Artes Medical, Inc."}
    scored = runners._score_pipeline_extraction(
        row, {"doc_type": "corporate_record", "extracted_data": {
            "entity_name": "ARTES MEDICAL INC", "record_type": "articles_of_incorporation",
            "subject_matter": "Amends the certificate of incorporation to authorize two classes of stock.",
            "keywords": ["preferred stock", "reverse split"], "intent": "entity_formation"}})
    assert scored["stale_hub_labels"]["subject_matter"] == "subject_matter_record_title"
    assert scored["stale_hub_labels"]["keywords"] == "keywords_record_title"
    assert scored["overall_extraction_score"] == 1.0


def test_shf015_a_corporate_summary_is_not_a_record_title():
    fields = {"entity_name": "ARTES MEDICAL INC",
              "subject_matter": "Amends the certificate to authorize two classes of stock.",
              "keywords": ["preferred stock", "reverse split"]}
    row = {**_row(fields), "expected_doc_class": "corporate_record"}
    scored = runners._score_pipeline_extraction(
        row, {"doc_type": "corporate_record", "extracted_data": {
            "entity_name": "ARTES MEDICAL INC",
            "subject_matter": "A joinder agreement for a different company.",
            "keywords": ["Valley Rents"]}})
    assert "subject_matter" not in scored.get("stale_hub_labels", {})
    assert "keywords" not in scored.get("stale_hub_labels", {})
    assert scored["overall_extraction_score"] < 1.0


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


@pytest.mark.parametrize("policy_result", [None, [], ["intent"], "intent", 0])
def test_a_policy_result_that_is_not_a_mapping_means_no_stale_labels(monkeypatch, policy_result):
    from llm_dojo_scoring.schemas import label_policy

    monkeypatch.setattr(label_policy, "stale_hub_labels", lambda doc_type, expected: policy_result)
    expected = {"sender": "Ann Lee", "intent": "payment_demand", "intent_source": "heuristic"}
    out, dropped = sh.drop_stale_hub_truth("correspondence", expected, ())
    assert out == expected and dropped == {}


def test_overlay_fields_reads_a_string_as_one_field_name_and_ignores_junk():
    assert sh.overlay_fields({"interim_labels": {"fields": "intent"}}) == {"intent"}
    assert sh.overlay_fields({"near_gold_labels": json.dumps({"fields": "subject_matter"})}) == {"subject_matter"}
    assert sh.overlay_fields({"interim_labels": {"fields": ["intent", "sender"]},
                              "staged_overlay": {"fields": ("keywords",)}}) == {"intent", "sender", "keywords"}
    assert sh.overlay_fields({"interim_labels": {"fields": 7}}) == frozenset()
    assert sh.overlay_fields({"interim_labels": {"fields": None}}) == frozenset()
    assert sh.overlay_fields(None) == frozenset()


# --- the scored n beside the pipeline run's extraction headline (critical regression 1) ---------

_PAIR = {"sender": "Ann Lee", "recipient": "Bo Chu"}
_ANSWER = {"doc_type": "correspondence", "stage": "archived", "extracted_data": dict(_PAIR)}


def _stale_only_row(doc_id="DOC-S"):
    """Every scored label is a heuristic intent: SHF-015 leaves nothing to score (headline None, raw 0.0)."""
    return {**_row({"intent": "payment_demand", "intent_source": "heuristic"}), "id": doc_id}


def _pipeline_run_scores(spec):
    """``runners._pipeline_extraction_scores`` over ``(row, answer, class_ok)`` triples, as a run calls it."""
    rows = [None if r is None else runners._score_pipeline_extraction(r, a) for r, a, _ in spec]
    return runners._pipeline_extraction_scores(rows, [ok for _, _, ok in spec])


def test_the_pipeline_headline_reports_how_many_documents_each_mean_averaged():
    """A stale-only row leaves the headline mean (no score) but is still averaged on the raw side, and a
    misrouted row leaves the correct-class mean: each count says so beside its mean."""
    stale_answer = {**_ANSWER, "extracted_data": {"intent": "complaint"}}
    out = _pipeline_run_scores([
        (_row(_PAIR), _ANSWER, True),
        (_stale_only_row(), stale_answer, True),
        (_row(_PAIR), _ANSWER, False),  # routed to the wrong class
        (None, _ANSWER, True),  # parked: nothing was extracted
    ])
    assert out["extraction_overall"] == 1.0  # the stale-only row is not a 0
    assert out["extraction_overall_n_scored"] == 2
    assert out["extraction_overall_correct_class_n_scored"] == 1
    assert out["raw_dojo"]["extraction_overall_n_scored"] == 3  # a stale label still scores on the raw side
    assert out["raw_dojo"]["extraction_overall_correct_class_n_scored"] == 2
    assert {"extraction_overall_n_scored", "extraction_overall_correct_class_n_scored"} <= set(
        out["scoring_hotfixes_changed"])


def test_the_pipeline_headline_count_is_zero_not_none_when_no_document_has_a_score():
    out = _pipeline_run_scores([(_stale_only_row("DOC-S1"), {**_ANSWER, "extracted_data": {"intent": "x"}}, True)])
    assert out["extraction_overall"] is None and out["extraction_overall_correct_class"] is None
    assert out["extraction_overall_n_scored"] == 0 == out["extraction_overall_correct_class_n_scored"]
    assert out["raw_dojo"]["extraction_overall_n_scored"] == 1


def test_a_clean_run_reports_equal_counts_on_both_sides():
    out = _pipeline_run_scores([(_row(_PAIR), _ANSWER, True), (_row(_PAIR), _ANSWER, False)])
    assert out["extraction_overall_n_scored"] == 2 == out["raw_dojo"]["extraction_overall_n_scored"]
    assert out["extraction_overall_correct_class_n_scored"] == 1
    assert "extraction_overall_n_scored" not in out["scoring_hotfixes_changed"]


def test_a_rescore_reports_the_scored_n_beside_each_mean():
    """A rescored run's ``scores.json`` carries ``n`` beside each per-item mean: the stale-only item has no
    ``overall_extraction_score``, so the mean is over 1 of the 2 scored items. Its ``raw_dojo`` means are the
    plain means (SHF-005 off), so they read the same ``n``; the item keeps its own raw stale-label score."""
    from mailroom_sandbox import rescore

    score = rescore.scorer_for({"task": "pipeline"})
    stale_item = score(_stale_only_row(), {**_ANSWER, "extracted_data": {"intent": "complaint"}})
    items = [{"item_id": "DOC-1", "ok": True, "score": score(_row(_PAIR), _ANSWER)},
             {"item_id": "DOC-S", "ok": True, "score": stale_item}]
    truth = {"DOC-1": {"expected_doc_class": "correspondence"}, "DOC-S": {"expected_doc_class": "correspondence"}}
    out = rescore.run_scores(items, truth)
    key = "overall_extraction_score"
    assert out["scored"] == 2
    assert out["means"][key] == {"n": 1, "mean": 1.0}
    assert out["raw_dojo"]["means"][key]["n"] == 1
    assert stale_item["raw_dojo"][key] == 0.0 and stale_item.get(key) is None
