"""Phase 4 fix checking: a judge fix is applied only when its quote is in the source and supports it."""

from __future__ import annotations

import pytest

from mailroom_sandbox import gold_labels, judge_fixes
from mailroom_sandbox.judge_fixes import apply_fixes, verify_fix

DOC = ("This Services Agreement is made between Acme Holdings Ltd and Birch Logistics LLC. "
       "It is effective as of March 3, 2024.")
REQUESTED = ("parties", "effective_date", "governing_law")


def _fix(field, value, quote):
    return {"field": field, "value": value, "quote": quote}


def test_a_quoted_supported_fix_is_verified():
    check = verify_fix("contract", DOC, _fix("effective_date", "2024-03-03", "effective as of March 3, 2024"),
                       requested=REQUESTED)
    assert check == {"field": "effective_date", "value": "2024-03-03", "quote": "effective as of March 3, 2024",
                     "verified": True, "why": "ok"}
    parties = verify_fix("contract", DOC, _fix("parties", ["Acme Holdings Ltd", "Birch Logistics LLC"],
                                               "between Acme Holdings Ltd and Birch Logistics LLC"),
                         requested=REQUESTED)
    assert parties["verified"] and parties["why"] == "ok"


@pytest.mark.parametrize("blank", [None, "", []])
def test_a_fix_can_never_blank_a_field(blank):
    assert gold_labels.evidence_support("contract", "effective_date", blank, ["x"])[0] is True  # absence passes there
    check = verify_fix("contract", DOC, _fix("effective_date", blank, "effective as of March 3, 2024"),
                       requested=REQUESTED)
    assert (check["verified"], check["why"]) == (False, "blank")


def test_a_quote_not_in_the_document_is_rejected():
    check = verify_fix("contract", DOC, _fix("effective_date", "2024-03-03", "effective as of 3 March 2024 sharp"),
                       requested=REQUESTED)
    assert (check["verified"], check["why"]) == (False, "quote_not_found")
    empty = verify_fix("contract", DOC, _fix("effective_date", "2024-03-03", ""), requested=REQUESTED)
    assert (empty["verified"], empty["why"]) == (False, "quote_not_found")


def test_a_value_the_quote_does_not_support_is_rejected():
    check = verify_fix("contract", DOC, _fix("effective_date", "2025-01-01", "effective as of March 3, 2024"),
                       requested=REQUESTED)
    assert (check["verified"], check["why"]) == (False, "unsupported")


@pytest.mark.parametrize("field", ["_report", "reasoning", "contract_value", "no_such_field"])
def test_a_fix_outside_the_requested_fields_is_rejected(field):
    # Even a name the request lists is refused when the class has no such target field.
    requested = (*REQUESTED, field) if field == "no_such_field" else REQUESTED
    check = verify_fix("contract", DOC, _fix(field, "Acme Holdings Ltd", "Acme Holdings Ltd"), requested=requested)
    assert (check["verified"], check["why"]) == (False, "not_requested"), field


def test_apply_fixes_writes_only_verified_values():
    extracted = {"parties": ["Acme Holdings Ltd"], "effective_date": None, "governing_law": "Delaware", "_report": {}}
    checks = [
        verify_fix("contract", DOC, _fix("effective_date", "2024-03-03", "effective as of March 3, 2024"),
                   requested=REQUESTED),
        verify_fix("contract", DOC, _fix("governing_law", "England", "governed by English law"), requested=REQUESTED),
    ]
    fixed = apply_fixes(extracted, checks)
    assert fixed == {**extracted, "effective_date": "2024-03-03"}
    assert extracted["effective_date"] is None  # the input is not changed


def test_verify_fix_passes_the_subclass_when_evidence_support_takes_it(monkeypatch):
    seen: list[tuple] = []

    def with_subclass(doc_class, name, value, quotes, *, doc_subclass=None):
        seen.append(("with", doc_subclass))
        return True, ""

    def without_subclass(doc_class, name, value, quotes):
        seen.append(("without", None))
        return True, ""

    fix = _fix("effective_date", "2024-03-03", "effective as of March 3, 2024")
    monkeypatch.setattr(judge_fixes.gold_labels, "evidence_support", with_subclass)
    assert verify_fix("contract", DOC, fix, requested=REQUESTED, subclass="Service")["verified"]
    monkeypatch.setattr(judge_fixes.gold_labels, "evidence_support", without_subclass)
    assert verify_fix("contract", DOC, fix, requested=REQUESTED, subclass="Service")["verified"]
    assert seen == [("with", "Service"), ("without", None)]
