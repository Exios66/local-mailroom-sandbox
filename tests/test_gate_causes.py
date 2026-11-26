"""Cause buckets of the production slice gate: one primary cause per review, wrong archive and crash."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import gate, gate_causes
from mailroom_sandbox.job.gate import Bars

CATEGORIES = ("Agreement Date", "Anti-Assignment", "Governing Law", "Parties", "Document Name")


def cuad(gold=2):
    spans = {c: ([{"start": 3, "text": c.lower()}] if i < gold else []) for i, c in enumerate(CATEGORIES)}
    return {"cuad_clause_labels": spans, "label_evidence": "CUAD-annotated clauses: ..."}


def maud(gold=2):
    return {"maud_clause_labels": {f"Q{i}": ({"answer": "yes", "category": "x"} if i < gold else {})
                                   for i in range(4)}}


CORP = {"entity_name": "Acme Corp", "record_type": "other", "intent": "governance_rules",
        "intent_source": "heuristic"}
DOC_TEXT = ("Bylaws of Acme Corp. These bylaws set out the investor rights of the holders. "
            "Article I covers the board, its meetings, quorum and officers; Article II covers the annual "
            "meeting and the record date; Article III covers amendment by the board.")  # >= NEAR_EMPTY_CHARS


def doc(cls="corporate_record", expected=None, pred=None, doc_text=DOC_TEXT, item=True, **item_kw):
    """A load_arm-style document: dataset row, latest item and node list."""
    row = {"id": "d1", "expected_doc_class": cls, "doc_text": doc_text,
           "expected_fields": json.dumps(expected if expected is not None else CORP)}
    body = {"stage": "archived", "doc_type": cls, "extracted_data": {}, "review_causes": None}
    body.update(pred or {})
    it = {"item_id": "d1", "ok": True, "error": None, "prompt_tokens": 1, "completion_tokens": 1, "pred": body}
    it.update(item_kw)
    return {"row": row, "item": it if item else None, "nodes": []}


def review(causes, cls="corporate_record", **pred):
    return doc(cls, pred={"stage": "review", "review_causes": causes, **pred})


def cause_of(d, bars=None):
    return gate_causes.primary_cause(d, gate.doc_status(d, bars or Bars()))


@pytest.fixture
def fake_score(monkeypatch):
    """Archived documents score whatever their ``_score`` says (the run fixtures carry no real extraction)."""
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


@pytest.fixture(autouse=True)
def no_audit(monkeypatch):
    """Run dirs here are loose and carry no trail; the audit has its own tests (``tests/test_gate_audit.py``)."""
    real = gate.gate_report
    monkeypatch.setattr(gate, "gate_report", lambda run_dir, bars, **kw: real(run_dir, bars, **{"audit": False, **kw}))


# --- the brief's cases -------------------------------------------------------------------------


def test_precedence_mechanism_beats_judge():
    assert cause_of(review(["judge_error", "judge_partial"])) == "mechanism:judge_error"


def test_reviewer_unknown():
    d = review(["reviewer_ineligible_label", "reviewer_disagreement"], reviewer_doc_type="unknown")
    assert cause_of(d) == "classification:reviewer_unknown"


def test_wrong_class_archive(fake_score):
    d = doc("contract", cuad(), pred={"doc_type": "correspondence", "_score": 0.97})
    status = gate.doc_status(d, Bars())
    assert status["outcome"] == "wrong_archive" and status["scorable"] is True
    assert status["cause"] == "classification:wrong_class"
    assert gate_causes.primary_cause(d, status) == "classification:wrong_class"


def test_partial_exhausted():
    assert cause_of(review(["judge_partial", "retries_exhausted"])) == "judge:partial_exhausted"


def test_extraction_out_of_enum():
    d = doc(pred={"extracted_data": {"entity_name": "Acme Corp", "record_type": "indenture",
                                     "intent": "governance_rules"}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "out_of_enum"


def test_label_suspect():
    # The heuristic intent label disagrees with a prediction the document text states outright.
    d = doc(pred={"extracted_data": {"entity_name": "Acme Corp", "record_type": "other",
                                     "intent": "investor_rights"}, "_score": 0.5})
    row, pred = d["row"], d["item"]["pred"]
    assert gate_causes.label_suspect(row, pred, "intent") is True
    assert gate_causes.lowest_field(row, pred)[0] == "intent"
    assert gate_causes.primary_cause(d, {"outcome": "wrong_archive", "class": "corporate_record",
                                         "judge_error": False}) == "label_suspect"


def test_label_suspect_needs_heuristic_label_and_verbatim_text():
    pred = {"extracted_data": {"entity_name": "Acme Corp", "record_type": "other", "intent": "investor_rights"}}
    manual = doc(expected={**CORP, "intent_source": "manual"}, pred=pred)
    assert gate_causes.label_suspect(manual["row"], manual["item"]["pred"], "intent") is False
    elsewhere = doc(pred=pred, doc_text="Nothing relevant here.")
    assert gate_causes.label_suspect(elsewhere["row"], elsewhere["item"]["pred"], "intent") is False
    other_field = doc(pred=pred)
    assert gate_causes.label_suspect(other_field["row"], other_field["item"]["pred"], "entity_name") is False


def test_buckets_sorted_with_unlinked_audit_fields_when_audit_is_off(tmp_path, fake_score):
    run = tmp_path / "slice"
    run.mkdir()
    docs = [
        ("a", "contract", {"stage": "review", "review_causes": ["judge_error"]}),
        ("b", "correspondence", {"stage": "review", "review_causes": ["classification_arbiter_escalated"]}),
        ("c", "correspondence", {"stage": "review", "review_causes": ["classification_arbiter_escalated"]}),
        ("d", "insurance_claim", {"stage": "review", "review_causes": ["classification_arbiter_escalated"]}),
        ("e", "contract", {"stage": "review", "review_causes": ["judge_error"]}),
        ("f", "contract", {"stage": "archived", "_score": 0.95}),
    ]
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for doc_id, cls, pred in docs:
            ds.write(json.dumps({"id": doc_id, "expected_doc_class": cls,
                                 "expected_fields": json.dumps(cuad() if cls == "contract" else
                                                               {"sender": "A", "recipient": "B", "claim_number": "C",
                                                                "policy_number": "P"})}) + "\n")
            it.write(json.dumps({"item_id": doc_id, "ok": True, "error": None,
                                 "pred": {"doc_type": cls, "extracted_data": {}, **pred}}) + "\n")
    buckets = gate.gate_report(run, Bars())["buckets"]
    assert list(buckets) == ["classification:arbiter_escalated", "mechanism:judge_error"]
    assert [b["count"] for b in buckets.values()] == [3, 2]
    assert [d["id"] for d in buckets["classification:arbiter_escalated"]["docs"]] == ["b", "c", "d"]
    for bucket in buckets.values():
        assert all(set(d) == {"id", "archive", "trace_id", "span_id"} and d["archive"] is None
                   and d["trace_id"] is None and d["span_id"] is None
                   for d in bucket["docs"])
    report = gate.gate_report(run, Bars())
    assert {d["id"]: d["cause"] for d in report["docs"] if "cause" in d}["a"] == "mechanism:judge_error"
    assert "cause" not in next(d for d in report["docs"] if d["id"] == "f")  # a correct archive has no cause


ACCEPT_SORTER = {"classification_arbiter_decision": "accept_sorter"}
ACCEPT_REVIEWER = {"classification_arbiter_decision": "accept_reviewer"}


# --- precedence and mapping --------------------------------------------------------------------


@pytest.mark.parametrize("causes, extra, expected", [
    (["judge_error"], {}, "mechanism:judge_error"),
    (["transient_exhausted"], {}, "mechanism:transient"),
    (["classification_arbiter_escalated"], {}, "classification:arbiter_escalated"),
    # the extraction arbiter's escalation is a judge-lane outcome, not a classification one
    (["arbiter_escalated"], {}, "judge:arbiter_escalated"),
    (["judge_partial", "retries_exhausted", "arbiter_escalated"], {}, "judge:arbiter_escalated"),
    (["judge_incomplete", "arbiter_escalated"], {}, "judge:arbiter_escalated"),
    (["arbiter_escalated", "classification_arbiter_escalated"], {}, "classification:arbiter_escalated"),
    (["reviewer_disagreement"], {}, "classification:reviewer_disagreement"),
    (["reviewer_ineligible_label"], {}, "classification:reviewer_unknown"),
    (["reviewer_low_confidence"], {}, "classification:reviewer_unknown"),
    (["class_miss"], {}, "classification:wrong_class"),
    (["judge_partial"], {}, "judge:judge_rejected"),
    (["judge_miss"], {}, "judge:judge_rejected"),
    (["judge_incomplete"], {}, "judge:judge_rejected"),
    # one reviewer or arbiter cause plus the leftovers the pipeline always adds beside it
    (["classification_arbiter_escalated", "reviewer_ineligible_label", "reviewer_disagreement",
      "reviewer_low_confidence"], {}, "classification:reviewer_disagreement"),
    (["judge_partial", "classification_arbiter_escalated"], {}, "classification:arbiter_escalated"),
    # Reviewer doubt the classification arbiter resolved (it accepted a class, so extraction ran) is
    # stale once the extraction arbiter has parked the document: the park is a judge-lane outcome.
    (["judge_partial", "arbiter_escalated", "reviewer_low_confidence"], {}, "judge:arbiter_escalated"),
    (["reviewer_low_confidence", "judge_partial", "arbiter_escalated"], {}, "judge:arbiter_escalated"),
    (["reviewer_ineligible_label", "arbiter_escalated"], {}, "judge:arbiter_escalated"),
    (["reviewer_ineligible_label", "reviewer_low_confidence", "arbiter_escalated"], {},
     "judge:arbiter_escalated"),
    # ... while an unresolved doubt or any classification-lane cause still outranks it
    (["reviewer_low_confidence", "arbiter_escalated", "classification_arbiter_escalated"], {},
     "classification:arbiter_escalated"),
    (["reviewer_low_confidence", "arbiter_escalated", "reviewer_disagreement"], {},
     "classification:reviewer_disagreement"),
    (["reviewer_unavailable", "arbiter_escalated"], {}, "classification:reviewer_unknown"),
    (["unknown_class", "reviewer_low_confidence", "arbiter_escalated"], {}, "classification:reviewer_unknown"),
    (["reviewer_low_confidence", "judge_partial"], {}, "classification:reviewer_unknown"),
    # The item records that the classification arbiter accepted a class: every reviewer cause is settled,
    # so the judge lane decides first, whichever reviewer cause was left on the item ...
    (["reviewer_disagreement", "judge_partial", "arbiter_escalated"], ACCEPT_SORTER, "judge:arbiter_escalated"),
    (["reviewer_unavailable", "arbiter_escalated"], ACCEPT_SORTER, "judge:arbiter_escalated"),
    (["unknown_class", "reviewer_low_confidence", "arbiter_escalated"], ACCEPT_REVIEWER, "judge:arbiter_escalated"),
    (["arbiter_escalated"], {**ACCEPT_SORTER, "reviewer_doc_type": "unknown"}, "judge:arbiter_escalated"),
    (["reviewer_disagreement", "judge_partial", "retries_exhausted"], ACCEPT_SORTER, "judge:partial_exhausted"),
    (["reviewer_unavailable", "judge_incomplete"], ACCEPT_REVIEWER, "judge:judge_rejected"),
    (["reviewer_low_confidence", "judge_incomplete"], ACCEPT_SORTER, "judge:judge_rejected"),
    # ... a reviewer cause names the park only when nothing in the judge lane does ...
    (["reviewer_disagreement"], ACCEPT_SORTER, "classification:reviewer_disagreement"),
    (["reviewer_unavailable"], ACCEPT_SORTER, "classification:reviewer_unknown"),
    (["reviewer_low_confidence"], ACCEPT_SORTER, "classification:reviewer_unknown"),
    # ... a wrong class is not settled by it ...
    (["class_miss", "reviewer_disagreement", "arbiter_escalated"], ACCEPT_SORTER, "classification:wrong_class"),
    # ... and an answer that is not an acceptance (or no answer) leaves the reviewer causes in force.
    (["reviewer_disagreement", "arbiter_escalated"], {"classification_arbiter_decision": "human_review"},
     "classification:reviewer_disagreement"),
    (["reviewer_unavailable", "judge_partial", "retries_exhausted"], {"classification_arbiter_decision": None},
     "classification:reviewer_unknown"),
])
def test_review_cause_mapping(causes, extra, expected):
    assert cause_of(review(causes, **extra)) == expected


@pytest.mark.parametrize("reviewer_tokens, extra", [
    (["reviewer_disagreement"], {}), (["reviewer_unavailable"], {}), (["reviewer_low_confidence"], {}),
    ([], {"reviewer_doc_type": "unknown"}),
])
@pytest.mark.parametrize("decision", [ACCEPT_SORTER, ACCEPT_REVIEWER])
def test_a_settled_reviewer_cause_ranks_below_an_extraction_miss(reviewer_tokens, extra, decision):
    """Once the classification arbiter accepted a class, an extraction miss names the park, not the reviewer."""
    alone = cause_of(review(["extraction_miss"], **decision))
    assert alone.startswith(("extraction:", "label_suspect")), alone
    assert cause_of(review([*reviewer_tokens, "extraction_miss"], **decision, **extra)) == alone
    # without the recorded acceptance the reviewer cause keeps its precedence over the extraction lane
    assert cause_of(review([*reviewer_tokens, "extraction_miss"], **extra)).startswith("classification:")


def test_reviewer_doc_type_unknown_without_a_cause_token():
    assert cause_of(review(["reviewer_disagreement"], reviewer_doc_type="unknown")) \
        == "classification:reviewer_unknown"


def test_wrong_class_beats_everything_but_mechanism():
    d = review(["reviewer_disagreement", "judge_partial"], doc_type="correspondence")
    assert cause_of(d) == "classification:wrong_class"
    d = review(["judge_error"], doc_type="correspondence")
    assert cause_of(d) == "mechanism:judge_error"


def test_unknown_review_cause_is_never_silently_bucketed():
    assert cause_of(review(["flux_capacitor"])) == "mechanism:unmapped:flux_capacitor"
    assert cause_of(review(["retries_exhausted"])) == "mechanism:unmapped:retries_exhausted"
    assert cause_of(review([])) == "mechanism:unmapped:none"
    # a known cause wins over a stray unknown one
    assert cause_of(review(["flux_capacitor", "judge_miss"])) == "judge:judge_rejected"


def test_crashed_and_transient_mechanisms():
    missing = doc(item=False)
    assert cause_of(missing) == "mechanism:crashed"
    boom = doc(error="RuntimeError: boom")
    boom["item"]["ok"] = False
    assert cause_of(boom) == "mechanism:crashed"
    flaky = doc(error="TransientError: provider 503 after retries")
    flaky["item"]["ok"] = False
    assert cause_of(flaky) == "mechanism:transient"


def test_status_carries_cause_only_for_non_passing_outcomes(fake_score):
    ok = gate.doc_status(doc("contract", cuad(), pred={"_score": 0.95}), Bars())
    assert "cause" not in ok and ok["outcome"] == "correct_archive"
    few = gate.doc_status(doc("contract", cuad(0), pred={"_score": 0.95}), Bars())
    assert "cause" not in few and few["outcome"] == "unscorable_archive"
    rev = gate.doc_status(review(["judge_miss"]), Bars())
    assert rev["cause"] == "judge:judge_rejected"
    crashed = gate.doc_status(doc(item=False), Bars())
    assert crashed["cause"] == "mechanism:crashed"


def test_wrong_class_missing_doc_type_is_not_flagged(fake_score):
    d = doc("contract", cuad(), pred={"_score": 0.95})
    del d["item"]["pred"]["doc_type"]
    assert gate.doc_status(d, Bars())["outcome"] == "correct_archive"
    same = doc("contract", cuad(), pred={"doc_type": " Contract ", "_score": 0.95})
    assert gate.doc_status(same, Bars())["outcome"] == "correct_archive"


# --- extraction types --------------------------------------------------------------------------


def extraction_type(expected, extracted, cls="corporate_record"):
    d = doc(cls, expected, pred={"extracted_data": extracted})
    return gate_causes.extraction_miss(d["row"], d["item"]["pred"])


def test_extraction_missing_field():
    assert extraction_type(CORP, {"entity_name": "Acme Corp", "record_type": "other", "intent": None}) \
        == "missing_field"
    assert extraction_type(CORP, {"entity_name": "", "record_type": "other", "intent": "governance_rules"}) \
        == "missing_field"


def test_extraction_wrong_value():
    assert extraction_type(CORP, {"entity_name": "Zenith Holdings", "record_type": "other",
                                  "intent": "governance_rules"}) == "wrong_value"


def test_extraction_out_of_enum_intent():
    assert extraction_type(CORP, {"entity_name": "Acme Corp", "record_type": "other", "intent": "made_up"}) \
        == "out_of_enum"
    # an in-vocabulary but wrong intent is a wrong value, not an enum miss
    assert extraction_type(CORP, {"entity_name": "Acme Corp", "record_type": "other", "intent": "investor_rights"}) \
        == "wrong_value"


def test_extraction_date_format():
    expected = {"sender": "A. Smith", "recipient": "B. Jones", "communication_date": "2001-06-04"}
    got = {"sender": "A. Smith", "recipient": "B. Jones", "communication_date": "June 4th"}
    assert extraction_type(expected, got, "correspondence") == "date_format"
    wrong_iso = {**got, "communication_date": "2002-07-09"}
    assert extraction_type(expected, wrong_iso, "correspondence") == "wrong_value"


def test_field_without_enum_metadata_is_never_out_of_enum():
    expected = {"sender": "A. Smith", "recipient": "B. Jones"}
    got = {"sender": "Someone Else", "recipient": "B. Jones"}
    assert extraction_type(expected, got, "correspondence") == "wrong_value"


# --- contracts and mergers: scored on one label field -------------------------------------------


def test_contract_cuad_missed_when_gold_categories_are_not_predicted():
    # gold: Agreement Date and Anti-Assignment; only the first is found
    d = doc("contract", cuad(2), pred={"extracted_data": {"cuad_clauses": ["Agreement Date: May 1"]}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "cuad_missed"


def test_contract_cuad_tie_counts_as_missed():
    d = doc("contract", cuad(2), pred={"extracted_data": {"cuad_clauses": ["Agreement Date: x", "Parties: A"]}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "cuad_missed"  # 1 fn, 1 fp


def test_contract_cuad_false_when_extra_categories_are_predicted():
    d = doc("contract", cuad(1), pred={"extracted_data": {
        "cuad_clauses": ["Agreement Date: x", "Anti-Assignment: y"], "parties": ["A"], "governing_law": "NY"}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "cuad_false"  # 0 fn, 3 fp


def test_contract_labels_given_as_json_text():
    expected = {**cuad(2), "cuad_clause_labels": json.dumps(cuad(2)["cuad_clause_labels"])}
    d = doc("contract", expected, pred={"extracted_data": {}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "cuad_missed"


def test_merger_is_maud_wrong():
    d = doc("merger_agreement", maud(), pred={"extracted_data": {}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "maud_wrong"


def test_contract_wrong_archive_cause_and_never_label_suspect(fake_score):
    d = doc("contract", cuad(2), pred={"extracted_data": {"cuad_clauses": ["Agreement Date: May 1"]},
                                       "_score": 0.4})
    status = gate.doc_status(d, Bars())
    assert status["outcome"] == "wrong_archive" and status["cause"] == "extraction:cuad_missed"
    assert gate_causes.label_suspect(d["row"], d["item"]["pred"], "cuad_clause_labels") is False
    m = doc("merger_agreement", maud(), pred={"_score": 0.2})
    assert gate.doc_status(m, Bars())["cause"] == "extraction:maud_wrong"


def test_extraction_miss_without_any_labelled_field_falls_back_to_wrong_value():
    d = doc("insurance_claim", {"claim_number": "", "policy_number": None}, pred={"extracted_data": {}})
    assert gate_causes.extraction_miss(d["row"], d["item"]["pred"]) == "wrong_value"


# --- scorer failures and label_suspect hardening (review fix round 1) ---------------------------


def test_scorer_exception_is_its_own_cause_not_wrong_value(monkeypatch):
    import mailroom_sandbox.eval.scoring as scoring

    def boom(doc_class):
        raise RuntimeError("dojo api changed")

    monkeypatch.setattr(scoring, "suite_for_doc_type", boom)
    d = doc(pred={"extracted_data": {"entity_name": "Zenith", "record_type": "other", "intent": "investor_rights"}})
    with pytest.raises(gate_causes.ScorerError):
        gate_causes.extraction_miss(d["row"], d["item"]["pred"])
    status = {"outcome": "wrong_archive", "class": "corporate_record", "judge_error": False}
    assert gate_causes.primary_cause(d, status) == "mechanism:scorer_error"


def test_scorer_without_field_scores_is_a_scorer_error(monkeypatch):
    import mailroom_sandbox.eval.scoring as scoring

    class Hollow:
        field_types: dict = {}

        def score(self, *args, **kwargs):
            return {"extraction": object()}

    monkeypatch.setattr(scoring, "suite_for_doc_type", lambda doc_class: Hollow())
    d = doc(pred={"extracted_data": {"entity_name": "Zenith", "record_type": "other", "intent": "governance_rules"}})
    status = {"outcome": "wrong_archive", "class": "corporate_record", "judge_error": False}
    assert gate_causes.primary_cause(d, status) == "mechanism:scorer_error"


def test_label_suspect_never_fires_for_other_or_partial_words():
    expected = {**CORP, "intent": "governance_rules"}
    other = doc(expected=expected, doc_text="Another mother of all bylaws.",
                pred={"extracted_data": {"intent": "other"}})
    assert gate_causes.label_suspect(other["row"], other["item"]["pred"], "intent") is False
    partial = doc(expected=expected, doc_text="The investor rightsholders agreed.",
                  pred={"extracted_data": {"intent": "investor_rights"}})
    assert gate_causes.label_suspect(partial["row"], partial["item"]["pred"], "intent") is False
    off_vocab = doc(expected=expected, doc_text="It covers made up things.",
                    pred={"extracted_data": {"intent": "made_up"}})
    assert gate_causes.label_suspect(off_vocab["row"], off_vocab["item"]["pred"], "intent") is False
    underscored = doc(expected=expected, doc_text="Grants investor_rights to holders.",
                      pred={"extracted_data": {"intent": "investor_rights"}})
    assert gate_causes.label_suspect(underscored["row"], underscored["item"]["pred"], "intent") is True


# --- reviewed overlay labels are not heuristic labels (label_suspect provenance) -----------------
# The overlays replace a heuristic intent with a reviewed one but leave ``intent_source`` on the row as
# ``heuristic``; the marker each overlay writes is what says the label was reviewed.

_SUSPECT_PRED = {"extracted_data": {"entity_name": "Acme Corp", "record_type": "other",
                                    "intent": "investor_rights"}, "_score": 0.5}
_OVERLAY_MARKERS = {
    "interim": ("interim_labels", {"fields": ["intent"], "overlay_sha256": "0" * 64}),
    "near_gold": ("near_gold_labels", {"fields": ["intent"], "overlay_sha256": "0" * 64, "status": "near_gold"}),
    "staged": ("staged_overlay", {"version": "9.3.1-rc.9", "manifest_sha256": "0" * 64,
                                  "fields": ["intent"], "overrides": {}}),
}


def _suspect_doc(**row_extra):
    d = doc(pred=_SUSPECT_PRED)
    d["row"].update(row_extra)
    return d


def test_unmarked_heuristic_intent_is_still_label_suspect():
    d = _suspect_doc()
    assert gate_causes.label_suspect(d["row"], d["item"]["pred"], "intent") is True


@pytest.mark.parametrize("kind", sorted(_OVERLAY_MARKERS))
def test_overlay_supplied_intent_is_not_label_suspect(kind):
    key, marker = _OVERLAY_MARKERS[kind]
    d = _suspect_doc(**{key: marker})
    row, pred = d["row"], d["item"]["pred"]
    assert row["expected_fields"] and json.loads(row["expected_fields"])["intent_source"] == "heuristic"
    assert gate_causes.label_suspect(row, pred, "intent") is False
    status = {"outcome": "wrong_archive", "class": "corporate_record", "judge_error": False}
    assert gate_causes.primary_cause(d, status) == "extraction:wrong_value"


def test_the_real_interim_overlay_marker_clears_label_suspect():
    # The marker comes from the production writer, not a hand-built dict, so a change to its shape shows here.
    from mailroom_sandbox import interim_labels as il

    d = _suspect_doc()
    row = d["row"]
    overlay = {"d1": {"doc_sha256": il.row_doc_sha(row),
                      "labels": {"intent": {"use_as_truth": True, "status": "correction", "value": "update"}}}}
    reviewed = il.apply_overlay(row, overlay, overlay_sha="0" * 64)
    assert reviewed["interim_labels"]["fields"] == ["intent"]
    assert json.loads(reviewed["expected_fields"])["intent_source"] == "heuristic"
    assert gate_causes.label_suspect(row, d["item"]["pred"], "intent") is True
    assert gate_causes.label_suspect(reviewed, d["item"]["pred"], "intent") is False


def test_overlay_that_did_not_supply_intent_leaves_label_suspect():
    # An overlay filled another field; the intent label is still the heuristic one.
    key, marker = _OVERLAY_MARKERS["interim"]
    d = _suspect_doc(**{key: {**marker, "fields": ["entity_name"]}})
    assert gate_causes.label_suspect(d["row"], d["item"]["pred"], "intent") is True


def test_stale_staged_overlay_applied_nothing_and_leaves_label_suspect():
    stale = {"version": "9.3.1-rc.9", "manifest_sha256": "0" * 64, "fields": [], "overrides": {}, "stale": True}
    d = _suspect_doc(staged_overlay=stale)
    assert gate_causes.label_suspect(d["row"], d["item"]["pred"], "intent") is True


def test_every_non_passing_outcome_has_exactly_one_cause(fake_score):
    statuses = [
        gate.doc_status(doc("contract", cuad(), pred={"_score": 0.95}), Bars()),            # correct
        gate.doc_status(doc("contract", cuad(2), pred={"_score": 0.40}), Bars()),           # wrong
        gate.doc_status(doc("contract", cuad(0), pred={"_score": 0.95}), Bars()),           # unscorable
        gate.doc_status(review(["judge_partial", "retries_exhausted"]), Bars()),            # review
        gate.doc_status(doc(item=False), Bars()),                                           # crashed
    ]
    outcomes = [s["outcome"] for s in statuses]
    assert outcomes == ["correct_archive", "wrong_archive", "unscorable_archive", "review", "crashed"]
    for s in statuses:
        if s["outcome"] in ("review", "wrong_archive", "crashed"):
            assert isinstance(s["cause"], str) and s["cause"]
        else:
            assert "cause" not in s
