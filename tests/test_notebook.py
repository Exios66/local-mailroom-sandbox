"""Gold-field grounding over the fixture manifest (network-free)."""

from __future__ import annotations

import pytest

from mailroom_sandbox.notebook import (
    CATEGORICAL,
    DATE_FORM,
    GROUNDED,
    GROUNDED_NORMALIZED,
    NON_TEXT,
    NUMBER_FORM,
    NUMERAL_FORM,
    UNGROUNDED,
    gold_field_grounding,
    ungrounded,
)


def test_manifest_extractive_gold_is_grounded_in_fixture_text():
    findings = gold_field_grounding()
    assert findings, "manifest produced no gold values to check"
    assert ungrounded(findings) == []
    by_row = {(f.row_id, f.field, f.value): f.status for f in findings}
    assert by_row[("contract_msa", "parties", "ACME Corporation")] == GROUNDED
    assert by_row[("contract_nda", "parties", "Stellar Advisors LLC")] == GROUNDED
    assert by_row[("merger_agreement", "merger_consideration", "all_cash")] == CATEGORICAL


def test_copied_gold_block_is_reported_ungrounded():
    rows = [
        {
            "id": "msa",
            "text": "Agreement between ACME\n  CORPORATION and ZENITH TECHNOLOGIES LLC.",
            "expected_fields": {
                "parties": ["Acme Corporation", "HarborPoint Holdings, Inc."],
                "communication_type": "internal memo",
                "page_count": 3,
                "signed": True,
                "governing_law": "",
            },
        }
    ]
    status = {(f.field, f.value): f.status for f in gold_field_grounding(rows)}
    assert status == {
        ("parties", "Acme Corporation"): GROUNDED,
        ("parties", "HarborPoint Holdings, Inc."): UNGROUNDED,
        ("communication_type", "internal memo"): CATEGORICAL,
        ("page_count", 3): UNGROUNDED,
        ("signed", True): NON_TEXT,
        ("governing_law", ""): UNGROUNDED,
    }
    assert [f.value for f in ungrounded(gold_field_grounding(rows, categorical=()))] == [
        "HarborPoint Holdings, Inc.",
        "internal memo",
        3,
        "",
    ]


def test_rows_without_gold_yield_no_findings():
    assert (
        gold_field_grounding(
            [{"id": "x", "text": "t"}, {"id": "y", "text": "t", "expected_fields": {}}]
        )
        == []
    )


_CONTRACT = (
    "This Agreement is entered into as of January 15, 2024. Invoices are paid within "
    "thirty (30) days. The total contract value shall not exceed $2,500,000 over a "
    "term of three (3) years. Notice is due on the 1st day of March, 2025 or 4/1/2025. "
    "Coverage of USD 1.2 million; renewal for twenty-four months."
)


@pytest.mark.parametrize(
    ("value", "form"),
    [
        ("2024-01-15", DATE_FORM),
        ("15th day of January 2024", DATE_FORM),
        ("2025-03-01", DATE_FORM),
        ("2025-04-01", DATE_FORM),
        (2500000, NUMBER_FORM),
        (2500000.0, NUMBER_FORM),
        ("2.5M", NUMBER_FORM),
        ("2500000 USD", NUMBER_FORM),
        (1200000, NUMBER_FORM),
        ("3 years", NUMERAL_FORM),
        ("three years", NUMERAL_FORM),
        ("30 days", NUMERAL_FORM),
        ("24 months", NUMERAL_FORM),
    ],
)
def test_canonical_gold_is_grounded_in_its_written_form(value, form):
    rows = [{"id": "c", "text": _CONTRACT, "expected_fields": {"f": value}}]
    [finding] = gold_field_grounding(rows)
    assert (finding.status, finding.form) == (GROUNDED_NORMALIZED, form)


@pytest.mark.parametrize(
    "value",
    [
        "2024-02-01",
        "2024-15-01",
        2600000,
        "$2.6M",
        "4 years",
        "signed on 1/15/2024 by both",
        "2 years",
    ],
)
def test_canonical_gold_not_in_the_text_stays_ungrounded(value):
    rows = [{"id": "c", "text": _CONTRACT, "expected_fields": {"f": value}}]
    [finding] = gold_field_grounding(rows)
    assert (finding.status, finding.form) == (UNGROUNDED, "")


def test_literal_match_wins_over_normalized():
    rows = [
        {"id": "c", "text": _CONTRACT, "expected_fields": {"f": ["January 15, 2024", "$2,500,000"]}}
    ]
    assert {(f.status, f.form) for f in gold_field_grounding(rows)} == {(GROUNDED, "")}
