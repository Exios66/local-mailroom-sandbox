"""The decision reviewer's ``unknown`` on correspondence (slice-gate task 10).

E3 ``DOC-49642fa25902b91e`` ("Here is the revised BPA document", 32 characters) and r3
``DOC-16dfd03aed14e557`` (56 characters) are Enron cover notes whose attachment was stripped. The
reviewer answers ``unknown`` because there is nothing to classify, so the review is an input finding,
not a reviewer or mapping fault: the gate buckets it as ``input:near_empty``. The pinned corpus has
109 correspondence documents under 200 characters, none with gold ``communication_type`` or ``sender``.
"""
from __future__ import annotations

import json

from mailroom_sandbox.job import gate, gate_causes
from mailroom_sandbox.job.gate import Bars

LONG_TEXT = ("From: Ben Rogers\nTo: Deal team\nSubject: section 1\n\n" + "The revised draft of section 1 changes "
             "the payment schedule, the notice period and the governing law clause. " * 4)


def review(doc_text, **pred):
    row = {"id": "d1", "expected_doc_class": "correspondence", "doc_text": doc_text,
           "expected_fields": json.dumps({"communication_type": "email", "sender": "Ben Rogers"})}
    body = {"stage": "review", "doc_type": "correspondence", "extracted_data": {},
            "review_causes": ["classification_arbiter_escalated", "reviewer_ineligible_label",
                              "reviewer_disagreement", "reviewer_low_confidence"],
            "reviewer_doc_type": "unknown", "reviewer_confidence": None, **pred}
    item = {"item_id": "d1", "ok": True, "error": None, "prompt_tokens": 1, "completion_tokens": 1, "pred": body}
    return {"row": row, "item": item, "nodes": []}


def test_reviewer_unknown_on_a_near_empty_cover_note_is_an_input_finding():
    d = review("Here is the revised BPA document")
    assert gate_causes.primary_cause(d, gate.doc_status(d, Bars())) == "input:near_empty"


def test_reviewer_unknown_on_a_real_email_stays_a_classification_cause():
    d = review(LONG_TEXT)
    assert len(LONG_TEXT) >= gate_causes.NEAR_EMPTY_CHARS
    assert gate_causes.primary_cause(d, gate.doc_status(d, Bars())) == "classification:reviewer_unknown"


def test_mechanism_still_beats_near_empty():
    d = review("ok", review_causes=["judge_error"])
    assert gate_causes.primary_cause(d, gate.doc_status(d, Bars())) == "mechanism:judge_error"


def _archived(doc_text, doc_type="correspondence"):
    row = {"id": "d2", "expected_doc_class": "correspondence", "doc_text": doc_text,
           "expected_fields": json.dumps({"communication_type": "memo", "sender": "Ben Rogers"})}
    body = {"stage": "archived", "doc_type": doc_type, "review_causes": [],
            "extracted_data": {"communication_type": "email", "sender": "Someone Else"}}
    item = {"item_id": "d2", "ok": True, "error": None, "prompt_tokens": 1, "completion_tokens": 1, "pred": body}
    return {"row": row, "item": item, "nodes": []}


def test_a_near_empty_wrong_archive_stays_a_pipeline_cause():
    """A confidently wrong archive is a pipeline fault even on a short input (review I2)."""
    d = _archived("Here is the revised BPA document")
    status = gate.doc_status(d, Bars())
    assert status["outcome"] == "wrong_archive"
    assert gate_causes.primary_cause(d, status).startswith("extraction:")


def test_a_near_empty_wrong_class_archive_stays_wrong_class():
    d = _archived("Here is the revised BPA document", doc_type="contract")
    status = gate.doc_status(d, Bars())
    assert status["outcome"] == "wrong_archive"
    assert gate_causes.primary_cause(d, status) == "classification:wrong_class"
