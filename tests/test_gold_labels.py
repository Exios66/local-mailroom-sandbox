"""Gold-label gate, agreement and catalog (``mailroom_sandbox.gold_labels``)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import gold_labels as gl

EMAIL = """Message-ID: <1@x>
Date: Mon, 14 May 2001 09:02:00 -0700 (PDT)
From: Jane Roe
To: John Doe
Subject: unpaid invoice

John,
Please remit $18,530.00 by May 31, 2001 or we will refer the matter to counsel.
Jane Roe
VP Finance, Acme Corp
"""


def sub(fields, doc_id="DOC-1"):
    return {"doc_id": doc_id, "labeler": {"model": "test", "role": "label"}, "fields": fields}


def test_locate_is_whitespace_and_case_tolerant():
    span = gl.locate("please  REMIT $18,530.00", EMAIL)
    assert span is not None
    assert EMAIL[span["start"]:span["end"]] == span["text"]
    assert span["text"].startswith("Please remit")
    assert gl.locate("not in the text", EMAIL) is None


def test_valid_correspondence_labels_pass_every_gate():
    res = gl.validate_submission(sub({
        "sender": {"value": "Jane Roe, VP Finance, Acme Corp", "evidence": ["Jane Roe\nVP Finance, Acme Corp"]},
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-14", "evidence": ["Mon, 14 May 2001"]},
        "demand_amount": {"value": "$18,530.00", "evidence": ["Please remit $18,530.00"]},
        "urgency": {"value": "time-sensitive", "evidence": ["by May 31, 2001"]},
        "action_items": {"value": ["Remit $18,530.00 by May 31, 2001"], "evidence": ["Please remit $18,530.00 by May 31, 2001"]},
        "additional_recipients": {"value": [], "absent": "no cc line"},
    }), EMAIL, "correspondence")
    assert res.payload_valid, res.payload_error
    assert all(fr.ok for fr in res.fields.values()), {k: v.reason for k, v in res.fields.items()}
    assert res.fields["demand_amount"].value == 18530.0
    assert res.fields["additional_recipients"].presence == "schema_documented_absence"
    assert res.fields["recipient"].evidence[0]["text"] == "To: John Doe"


@pytest.mark.parametrize("entry, reason", [
    ({"value": "John Doe", "evidence": ["To: Jim Doe"]}, "evidence not found"),
    ({"value": "Somebody Else", "evidence": ["To: John Doe"]}, "not supported"),
    ({"value": None}, "absent reason"),
    ({"value": "John Doe"}, "no evidence"),
])
def test_recipient_rejections(entry, reason):
    res = gl.validate_submission(sub({"recipient": entry}), EMAIL, "correspondence")
    assert not res.fields["recipient"].ok
    assert reason in res.fields["recipient"].reason


def test_closed_label_out_of_vocabulary_is_rejected_not_mapped():
    res = gl.validate_submission(sub({"urgency": {"value": "high", "evidence": ["by May 31"]}}), EMAIL, "correspondence")
    assert not res.fields["urgency"].ok
    assert res.fields["urgency"].reason.startswith("out_of_vocabulary")


def test_urgency_is_never_empty_but_routine_may_rest_on_a_basis():
    empty = gl.validate_submission(sub({"urgency": {"value": None, "absent": "none"}}), EMAIL, "correspondence")
    assert not empty.fields["urgency"].ok
    routine = gl.validate_submission(sub({"urgency": {"value": "routine", "basis": "no deadline"}}), EMAIL, "correspondence")
    assert routine.fields["urgency"].ok


def test_date_must_be_iso_and_match_its_evidence():
    bad_fmt = gl.validate_submission(sub({"communication_date": {"value": "05/14/2001", "evidence": ["14 May 2001"]}}),
                                     EMAIL, "correspondence")
    assert "ISO" in bad_fmt.fields["communication_date"].reason
    wrong = gl.validate_submission(sub({"communication_date": {"value": "2001-05-31", "evidence": ["Mon, 14 May 2001"]}}),
                                   EMAIL, "correspondence")
    assert not wrong.fields["communication_date"].ok


def test_action_items_cap():
    items = ["Please remit"] * 4
    res = gl.validate_submission(sub({"action_items": {"value": items, "evidence": ["Please remit"]}}), EMAIL, "correspondence")
    assert "at most 3" in res.fields["action_items"].reason


def test_non_target_field_is_rejected():
    res = gl.validate_submission(sub({"intent": {"value": "payment_demand", "evidence": ["remit"]}}), EMAIL, "correspondence")
    assert res.fields["intent"].reason == "not a target field"


CONTRACT = """SERVICES AGREEMENT dated as of June 21, 1999 between Alpha Inc. ("Supplier") and Beta LLC ("Customer").
Customer shall pay Supplier a fee of $250,000 within thirty days of invoice.
IN WITNESS WHEREOF  By: /s/ Mary Major, President  By: /s/ Sam Minor, CEO
"""


def test_contract_value_stays_a_currency_phrase_for_the_pipeline_schema():
    res = gl.validate_submission(sub({"contract_value": {"value": "$250,000", "evidence": ["a fee of $250,000"]}}),
                                 CONTRACT, "contract")
    assert res.payload_valid, res.payload_error
    assert res.fields["contract_value"].ok
    assert res.fields["contract_value"].value == "$250,000"


def test_party_roles_need_a_known_role():
    ok = gl.validate_submission(sub({"party_roles": {
        "value": ["Alpha Inc.: supplier", "Beta LLC: customer"],
        "evidence": ['Alpha Inc. ("Supplier") and Beta LLC ("Customer")']}}), CONTRACT, "contract")
    assert ok.fields["party_roles"].ok, ok.fields["party_roles"].reason
    bad = gl.validate_submission(sub({"party_roles": {
        "value": ["Alpha Inc.: vendor"], "evidence": ['Alpha Inc. ("Supplier")']}}), CONTRACT, "contract")
    assert "known role" in bad.fields["party_roles"].reason


def test_values_agree_is_type_aware():
    assert gl.values_agree(["Mary Major", "Sam Minor"], ["Sam Minor", "Mary Major"], "entity_list:name")
    assert gl.values_agree("Jane Roe", "Jane Roe, VP Finance", "name")
    assert not gl.values_agree("Jane Roe", "John Doe", "name")
    assert gl.values_agree(None, [], "entity_list")
    assert not gl.values_agree("2001-05-14", "2001-05-15", "date")
    assert gl.values_agree(18530.0, 18530.0, "money")


def test_reconcile_and_review():
    label = gl.validate_submission(sub({
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-14", "evidence": ["14 May 2001"]},
    }), EMAIL, "correspondence")
    check = gl.validate_submission(sub({
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-31", "evidence": ["May 31, 2001"]},
    }), EMAIL, "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence", "filename": "f", "content_sha256": "abc"}
    records, rejects = gl.reconcile(doc, EMAIL, label, check, {"model": "a"}, {"model": "b"}, {"dataset_revision": "r"})
    by_field = {r["field"]: r for r in records}
    assert by_field["recipient"]["status"] == "near_gold" and not by_field["recipient"]["use_as_truth"]
    assert by_field["communication_date"]["status"] == "disputed"
    assert not by_field["communication_date"]["use_as_truth"]
    assert rejects == []
    settled = gl.apply_review(by_field["communication_date"], {"verdict": "accept", "reviewer": {"model": "opus"}})
    assert settled["status"] == "near_gold" and not settled["use_as_truth"]
    dropped = gl.apply_review(by_field["recipient"], {"verdict": "reject", "reviewer": {"model": "opus"}})
    assert dropped["status"] == "rejected" and not dropped["use_as_truth"]


def test_gate_rejects_go_to_supplementary():
    label = gl.validate_submission(sub({"recipient": {"value": "Nobody", "evidence": ["To: John Doe"]}}),
                                   EMAIL, "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence"}
    records, rejects = gl.reconcile(doc, EMAIL, label, None, {"model": "a"}, None, {})
    assert records == [] and rejects[0]["field"] == "recipient"


def test_work_queue_skips_fields_the_hub_labels():
    rows = [{
        "document_id": "DOC-9", "filename": "f", "expected": "corporate_record", "expected_subclass": "bylaws",
        "content_sha256": "x",
        "gt_fields": json.dumps({"entity_name": "Acme Inc.",
                                 "gt_presence": json.dumps({"signatories": "not_applicable"})}),
    }, {"document_id": "DOC-8", "filename": "g", "expected": "merger_agreement", "gt_fields": "{}"}]
    queue = gl.work_queue(rows)
    assert [q["doc_id"] for q in queue] == ["DOC-9"]
    assert queue[0]["fields"] == ["effective_date", "jurisdiction"]


def test_cuad_dates_need_exactly_one_calendar_date():
    labels = {"Agreement Date": [{"start": 0, "text": "the 21st day of June, 1999"}],
              "Expiration Date": [{"start": 9, "text": "five years after the Effective Date"}]}
    row = {"document_id": "DOC-7", "expected": "contract",
           "gt_fields": json.dumps({"cuad_clause_labels": labels})}
    out = gl.cuad_date_submission(row)
    assert out["fields"] == {"agreement_date": {"value": "1999-06-21", "evidence": ["the 21st day of June, 1999"]}}
    assert gl.parse_dates("June 1, 2000 and 6/2/2000") == {"2000-06-01", "2000-06-02"}


def test_catalog_round_trip_and_tamper_detection(tmp_path):
    rec = {"doc_id": "D", "field": "recipient", "status": "near_gold", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}]}
    sha = gl.write_jsonl(tmp_path / "correspondence.jsonl", [rec])
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"schema": gl.SCHEMA, "files": {"correspondence.jsonl": sha}}))
    assert gl.verify_catalog(tmp_path) == []
    (tmp_path / "correspondence.jsonl").write_text(json.dumps({**rec, "use_as_truth": True}) + "\n")
    problems = gl.verify_catalog(tmp_path)
    assert any("sha256" in p for p in problems)
    assert any("use_as_truth" in p for p in problems)


def test_free_text_lists_agree_on_paraphrase_but_not_on_count():
    a = ["Update the Excel worksheet by 5 p.m. on Thursday to reflect payments"]
    b = ["Update the worksheet by 5 p.m. Thursday to reflect any payments received"]
    assert gl.values_agree(a, b, "entity_list")
    assert not gl.values_agree(a, a + ["Call me"], "entity_list")
    assert not gl.values_agree(["Call the bank"], ["Sign the lease"], "entity_list")


def test_overlay_exports_near_gold_and_candidates_never_truth():
    base = {"doc_class": "correspondence", "subclass": "email", "content_sha256": "ab" * 32,
            "presence": "populated", "evidence": [], "labeler": {"model": "s"}}
    recs = [
        {**base, "doc_id": "D1", "field": "recipient", "value": "John Doe", "status": "near_gold"},
        {**base, "doc_id": "D1", "field": "sender", "value": "Jane", "status": "near_gold",
         "review": {"verdict": "correct"}},
        {**base, "doc_id": "D1", "field": "urgency", "value": "routine", "status": "candidate"},
        {**base, "doc_id": "D2", "field": "recipient", "value": "X", "status": "disputed"},
        {**base, "doc_id": "D3", "field": "recipient", "value": "Y", "status": "rejected"},
    ]
    out = gl.overlay_records(recs, gate_run="gold-labels-x")
    assert [o["doc_id"] for o in out] == ["D1"]
    labels = out[0]["labels"]
    assert out[0]["doc_sha256"] == "ab" * 8 and out[0]["source"]["gate_run"] == "gold-labels-x"
    assert labels["recipient"]["basis"] == "near_gold:two_pass_agree"
    assert labels["sender"]["basis"] == "near_gold:opus_reviewed_correct"
    assert labels["urgency"]["basis"] == "candidate:single_pass"
    assert all(v["status"] == "gap_fill" and v["use_as_truth"] is False for v in labels.values())


def test_near_empty_documents_are_tagged():
    res = gl.validate_submission(sub({"recipient": {"value": "John Doe", "evidence": ["To: John Doe"]}}),
                                 "To: John Doe\nsee attached", "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence"}
    records, _ = gl.reconcile(doc, "To: John Doe\nsee attached", res, None, {"model": "a"}, None, {})
    assert records[0]["near_empty"] is True


def test_review_correction_keeps_the_basis_of_a_default_label():
    rec = {"doc_id": "D", "field": "urgency", "value": "urgent", "status": "disputed", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}], "absent_reason": None}
    out = gl.apply_review(rec, {"verdict": "correct", "value": "routine", "evidence": [], "presence": "populated",
                                "absent_reason": "standing weekly invitation", "reviewer": {"model": "opus"}})
    assert out["absent_reason"] == "standing weekly invitation" and out["evidence"] == []
    assert "absent_reason" not in out["review"]


def test_day_first_numeric_dates_only_when_unambiguous():
    assert gl._date_supported("2001-03-27", "Sent: 27/03/2001 18:38")
    assert not gl._date_supported("2000-11-02", "Sent: 02/11/2000 12:38")
    assert gl._date_supported("2000-02-11", "Sent: 02/11/2000 12:38")
