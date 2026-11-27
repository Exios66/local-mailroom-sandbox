"""SHF-017 contact equivalence and SHF-018 subclass-schema scoring.

A mailbox whose local-part tokens equal the labeled name is that contact. A field the subclass
schema drops, and an insurance list item the claim does not contain, is not a miss and not a
false positive. The raw side keeps the class-schema score, and every omitted field is named.
Network-free; no LLM calls.
"""
from __future__ import annotations

from mailroom_sandbox.eval.scoring import score_extraction_row


def _row(doc_type, predicted, expected, **kwargs):
    return score_extraction_row(doc_type, predicted, expected, field_scores=True, **kwargs)


def test_shf017_an_email_local_part_matches_the_labeled_name():
    from llm_dojo_scoring.scoring import field_scoring as fs

    from mailroom_sandbox import scoring_hotfixes as sh

    row = _row("correspondence", {"sender": "John.Arnold@enron.com"}, {"sender": "John Arnold"},
               expected_subclass="email")
    # The Dojo calls this exact by containment (the name's tokens sit inside the address).
    # SHF-002 then scores the extra domain tokens as a partial 0.5. SHF-017 puts it back to 1.0.
    assert row["raw_dojo"]["field_scores"]["sender"] == 1.0
    assert row["field_scores"]["sender"] == 1.0
    assert "SHF-017" in row["scoring_hotfixes"]
    with sh.hotfixed(["SHF-002"]):
        assert fs.score_name_field("John.Arnold@enron.com", "John Arnold") == 0.5


def test_shf017_a_display_name_beside_the_same_mailbox_matches():
    row = _row("correspondence",
               {"sender": "John Arnold <John.Arnold@enron.com>"},
               {"sender": "John Arnold"}, expected_subclass="email")
    assert row["field_scores"]["sender"] == 1.0


def test_shf017_a_different_person_stays_a_miss():
    row = _row("correspondence", {"sender": "John.Arnold@enron.com"}, {"sender": "Jane Doe"},
               expected_subclass="email")
    assert row["field_scores"]["sender"] < 1.0


def test_shf017_a_shared_token_stays_partial():
    bare = _row("correspondence", {"sender": "John"}, {"sender": "John Arnold"}, expected_subclass="email")
    initial = _row("correspondence", {"sender": "j.arnold@enron.com"}, {"sender": "John Arnold"},
                   expected_subclass="email")
    assert bare["field_scores"]["sender"] < 1.0
    assert initial["field_scores"]["sender"] < 1.0


def test_shf017_a_recipient_list_item_matches_by_mailbox():
    row = _row("correspondence",
               {"additional_recipients": ["John.Arnold@enron.com"]},
               {"additional_recipients": ["John Arnold"]}, expected_subclass="email")
    assert row["field_scores"]["additional_recipients"] == 1.0


def test_shf017_an_exchange_path_matches_the_written_name():
    row = _row("correspondence",
               {"additional_recipients": ["Randy Rice/OTS/Enron@ENRON"]},
               {"additional_recipients": ["Randy Rice"]}, expected_subclass="email")
    assert row["field_scores"]["additional_recipients"] == 1.0


def test_shf017_a_display_name_is_not_replaced_by_a_different_local_part():
    row = _row("correspondence",
               {"sender": "John Arnold <jane.doe@enron.com>"},
               {"sender": "Jane Doe"}, expected_subclass="email")
    assert row["field_scores"]["sender"] < 1.0


def test_shf017_two_mailboxes_with_the_same_local_part_match():
    row = _row("correspondence", {"sender": "john.arnold@enron.com"}, {"sender": "John.Arnold@enron.com"},
               expected_subclass="email")
    assert row["field_scores"]["sender"] == 1.0


def test_shf018_a_populated_field_the_subclass_drops_is_not_a_miss():
    row = _row("corporate_record",
               {"entity_name": "Acme Holdings Inc."},
               {"entity_name": "Acme Holdings Inc.", "filing_number": "0001234567"},
               expected_subclass="bylaws")
    assert "filing_number" not in row["field_scores"]
    assert row["subclass_unscored"]["filing_number"] == "not_in_subclass_schema"
    assert row["overall_extraction_score"] == 1.0
    assert row["raw_dojo"]["field_scores"]["filing_number"] < 1.0
    assert "SHF-018" in row["scoring_hotfixes"]


def test_shf018_a_stated_value_on_a_dropped_field_is_not_a_false_positive():
    row = _row("insurance_claim",
               {"claim_number": "1", "adjuster": "Pat Lee"},
               {"claim_number": "1"},
               doc_text="claim 1", expected_subclass="property")
    assert row["subclass_unscored"]["adjuster"] == "not_in_subclass_schema"
    assert "adjuster" not in row["field_scores"]
    assert row["overall_extraction_score"] == 1.0


def test_shf018_a_fallback_subclass_keeps_the_class_schema():
    row = _row("insurance_claim",
               {"claim_number": "1"},
               {"claim_number": "1", "adjuster": "Pat Lee"},
               doc_text="claim 1 adjuster Pat Lee", expected_subclass="health")
    assert "adjuster" in row["field_scores"]
    assert "subclass_unscored" not in row or "adjuster" not in row.get("subclass_unscored", {})


def test_shf018_insurance_documents_absent_from_the_claim_are_not_scored():
    text = "First notice of loss. Claim 262605551. Groundwater seepage through the basement."
    row = _row("insurance_claim",
               {"claim_number": "262605551", "supporting_documents": ["contractor invoice"]},
               {"claim_number": "262605551",
                "supporting_documents": ["invoice", "online claim form", "photo evidence"]},
               doc_text=text, expected_subclass="property")
    assert row["subclass_unscored"]["supporting_documents"] == "not_present_on_claim"
    assert "supporting_documents" not in row["field_scores"]
    assert row["field_scores"]["claim_number"] == 1.0
    assert row["overall_extraction_score"] == 1.0
    assert row["raw_dojo"]["field_scores"]["supporting_documents"] < 1.0


def test_shf018_a_matched_supporting_document_keeps_its_credit():
    """The label's wording need not be a substring of the claim when the prediction states it."""
    text = "Medicare summary notice. Claim 8875."
    value = ["provider NPI 8521399254", "HCPCS detail (1 codes)"]
    row = _row("insurance_claim",
               {"claim_number": "8875", "supporting_documents": list(value)},
               {"claim_number": "8875", "supporting_documents": list(value)},
               doc_text=text, expected_subclass="carrier")
    assert "supporting_documents" not in row.get("subclass_unscored", {})
    assert row["field_scores"]["supporting_documents"] == 1.0


def test_shf018_a_supporting_document_named_in_the_claim_still_counts():
    text = "Automobile claims decision letter. A repair estimate is attached."
    row = _row("insurance_claim",
               {"claim_number": "650", "supporting_documents": []},
               {"claim_number": "650", "supporting_documents": ["repair estimate"]},
               doc_text=text, expected_subclass="auto")
    assert row["field_scores"]["supporting_documents"] == 0.0
    assert "supporting_documents" not in row.get("subclass_unscored", {})


def test_shf018_keyword_tokens_absent_from_the_claim_leave_the_gold():
    text = "property fire claim 268371333 first notice of loss"
    row = _row("insurance_claim",
               {"keywords": ["fire", "first notice of loss", "268371333"]},
               {"keywords": ["Fire", "first notice of loss", "Outbuilding", "268371333"]},
               doc_text=text, expected_subclass="property")
    assert row["subclass_unscored"]["keywords"] == "items_not_in_claim"
    assert row["field_scores"]["keywords"] == 1.0


def test_shf018_without_the_claim_text_the_gold_list_stays():
    row = _row("insurance_claim",
               {"supporting_documents": []},
               {"supporting_documents": ["invoice", "online claim form"]},
               expected_subclass="property")
    assert "supporting_documents" in row["field_scores"]
    assert row["field_scores"]["supporting_documents"] == 0.0


def test_shf018_a_short_label_inside_a_longer_word_is_not_in_the_claim():
    embedded = _row("insurance_claim",
                    {"supporting_documents": []},
                    {"supporting_documents": ["form"]},
                    doc_text="information about the claim", expected_subclass="property")
    assert embedded["subclass_unscored"]["supporting_documents"] == "not_present_on_claim"
    assert "supporting_documents" not in embedded["field_scores"]
    stated = _row("insurance_claim",
                  {"supporting_documents": []},
                  {"supporting_documents": ["invoice"]},
                  doc_text="a contractor invoice is attached", expected_subclass="property")
    assert stated["field_scores"]["supporting_documents"] == 0.0
    assert "supporting_documents" not in stated.get("subclass_unscored", {})


def test_shf018_an_equivalent_contact_on_a_dropped_field_keeps_its_credit():
    row = _row("corporate_record",
               {"entity_name": "Acme Holdings Inc.", "signatories": ["Randy Rice/OTS/Enron@ENRON"]},
               {"entity_name": "Acme Holdings Inc.", "signatories": ["Randy Rice"]},
               expected_subclass="subsidiary_list")
    assert "signatories" not in row.get("subclass_unscored", {})
    assert row["field_scores"]["signatories"] == 1.0
    assert row["overall_extraction_score"] == 1.0


def test_shf018_a_different_person_on_a_dropped_field_is_not_a_miss():
    row = _row("corporate_record",
               {"entity_name": "Acme Holdings Inc.", "signatories": ["Jane Doe"]},
               {"entity_name": "Acme Holdings Inc.", "signatories": ["Randy Rice"]},
               expected_subclass="subsidiary_list")
    assert row["subclass_unscored"]["signatories"] == "not_in_subclass_schema"
    assert "signatories" not in row["field_scores"]
    assert row["overall_extraction_score"] == 1.0


def test_shf018_a_dropped_field_leaves_the_hallucination_rate():
    import json

    expected = {
        "claim_number": "1",
        "adjuster": None,
        "denial_reasons": None,
        "gt_presence": json.dumps({
            "adjuster": "schema_documented_absence",
            "denial_reasons": "schema_documented_absence",
        }),
    }
    row = _row("insurance_claim",
               {"claim_number": "1", "adjuster": "Pat Lee", "denial_reasons": None},
               expected, doc_text="claim 1", expected_subclass="property")
    assert row["subclass_unscored"]["adjuster"] == "not_in_subclass_schema"
    assert "adjuster" not in row["hallucinated_fields"]
    assert row["n_documented_absent"] == 1
    assert row["n_hallucinated"] == 0
    assert row["hallucination_rate"] == 0.0


def test_shf018_the_gate_returns_no_scores_when_every_labelled_field_was_dropped():
    from mailroom_sandbox.job import gate_causes

    row = {"expected_doc_class": "corporate_record", "expected_subclass": "bylaws",
           "expected_fields": {"filing_number": "0001234567"}}
    assert gate_causes._field_scores(row, {"extracted_data": {}}) == {}


def test_shf018_correspondence_keeps_its_class_schema():
    row = _row("correspondence", {"sender": "John Arnold", "intent": "request"},
               {"sender": "John Arnold", "intent": "request"}, expected_subclass="email")
    assert row["field_scores"]["sender"] == 1.0
    assert row["field_scores"]["intent"] == 1.0
    assert "subclass_unscored" not in row
