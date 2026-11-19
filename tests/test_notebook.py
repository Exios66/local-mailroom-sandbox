"""Gold-field grounding over the fixture manifest (network-free)."""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox.notebook import (
    ALIAS_FORM,
    NO_EVIDENCE,
    CATEGORICAL,
    DATE_FORM,
    GROUNDED,
    GROUNDED_NORMALIZED,
    NON_TEXT,
    NUMBER_FORM,
    NUMERAL_FORM,
    UNGROUNDED,
    agent_fixture_grounding,
    gold_field_grounding,
    label_overlay_grounding,
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
    sec = next(f for f in findings if (f.row_id, f.field) == ("compliance_10k", "regulatory_body"))
    assert (sec.status, sec.form) == (GROUNDED_NORMALIZED, ALIAS_FORM)


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


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (-500, GROUNDED_NORMALIZED),  # a minus sign is part of the amount
        ("-$75", GROUNDED_NORMALIZED),
        ("−500", GROUNDED_NORMALIZED),  # U+2212 MINUS SIGN
        (500, UNGROUNDED),
        (15, UNGROUNDED),  # the day of an ISO date is not a number in the text
        ("3 years", UNGROUNDED),  # not inside "thirteen (13) years"
        ("13 years", GROUNDED_NORMALIZED),
        ("Delaware", UNGROUNDED),  # not inside "Delawarean"
        (9007199254740993, GROUNDED_NORMALIZED),
        (9007199254740992, UNGROUNDED),  # no float rounding above 2**53
    ],
)
def test_signs_word_edges_and_large_integers(value, status):
    text = (
        "A loss of -500 and a credit of $-75. Dated 2024-01-15. A term of thirteen (13) years "
        "under Delawarean practice; reference 9007199254740993."
    )
    [finding] = gold_field_grounding([{"id": "x", "text": text, "expected_fields": {"f": value}}])
    assert finding.status == status


def test_alias_needs_its_written_form_not_a_longer_word():
    def status(text):
        rows = [{"id": "x", "text": text, "expected_fields": {"regulatory_body": "SEC"}}]
        return gold_field_grounding(rows)[0].status

    assert status("Filed under SECTION 13 of the Act.") == UNGROUNDED
    assert status("Filed with the Securities and Exchange Commission.") == GROUNDED_NORMALIZED
    assert status("Filed with the SEC.") == GROUNDED


# --------------------------------------------------------------------------- agent fixtures


def test_agent_fixture_gold_is_grounded_in_its_text():
    findings = agent_fixture_grounding()
    assert ungrounded(findings) == []
    by_row = {(f.row_id, f.field, f.value): f.status for f in findings}
    # The judge's MSA row once carried the 10-K's parties; it must name the MSA's own.
    assert by_row[("judge/judge_msa", "parties", "ACME Corporation")] == GROUNDED
    assert by_row[("judge/judge_msa", "parties", "Zenith Technologies LLC")] == GROUNDED
    # Intake snippets match through the whitespace the agent must normalize (NBSP).
    assert by_row[("intake/intake_nbsp", "expected", "Hello world")] == GROUNDED


def test_agent_rows_without_source_text_yield_no_findings():
    ids = {f.row_id.split("/", 1)[0] for f in agent_fixture_grounding()}
    # arbiter/boss judge model output with no source document; image/PDF rows are binary.
    assert ids.isdisjoint({"arbiter", "boss", "image_extractor", "pdf_transcriber"})


def test_agent_row_with_missing_catalog_file_is_ungrounded(tmp_path, monkeypatch):
    import mailroom_sandbox.datasets as datasets
    import mailroom_sandbox.paths as paths
    import mailroom_sandbox.prep as prep

    (tmp_path / "agents").mkdir()
    row = {
        "id": "r1",
        "subdir": "contract",
        "filename": "gone.txt",
        "expected_fields": {"parties": ["ACME Corporation"]},
    }
    (tmp_path / "agents" / "judge.jsonl").write_text(json.dumps(row) + "\n")
    for module in (datasets, paths, prep):
        monkeypatch.setattr(module, "fixtures_dir", lambda: tmp_path)
    [finding] = agent_fixture_grounding(["judge"])
    assert (finding.row_id, finding.status) == ("judge/r1", UNGROUNDED)


# --------------------------------------------------------------------------- label overlays

#: Labels whose evidence does not support them and that are kept on purpose, keyed with the
#: value (JSON text for lists) so a changed value is not excused. Each needs the reason and
#: the owner who decides it; a new unsupported label fails the test below.
KNOWN_UNSUPPORTED = {
    # Reviewed original_header fill: the Exchange display name glues the org suffix to the
    # surname ("Michael GrimesCORPENRON"), so "grimes" is not a token of the quoted header.
    # The value is right; changing it is a review-file decision (data/labels/interim/README.md).
    ("interim", "DOC-2ccf94f14bd5f040", "recipient", "Michael Grimes"),
}


def test_scoring_overlays_are_supported_by_their_evidence():
    findings = label_overlay_grounding()
    unsupported = {
        (f.overlay, f.doc_id, f.field, f.value if isinstance(f.value, str) else json.dumps(f.value))
        for f in findings
        if f.status == UNGROUNDED
    }
    assert unsupported == KNOWN_UNSUPPORTED
    checked = [f for f in findings if f.status == GROUNDED]
    assert {f.overlay for f in checked} == {"gold-overlay", "interim"}
    assert len(checked) > 1000


def _overlay(tmp_path, labels, doc_class="contract"):
    (tmp_path / "gold-overlay").mkdir(parents=True)
    record = {"doc_class": doc_class, "doc_id": "DOC-1", "labels": labels}
    (tmp_path / "gold-overlay" / f"{doc_class}.jsonl").write_text(json.dumps(record) + "\n")
    found = label_overlay_grounding(["gold-overlay"], root=tmp_path)
    return {f.field: (f.status, f.reason) for f in found}


def test_overlay_label_is_checked_against_each_evidence_shape(tmp_path):
    span = {"text": "made on this 1st day of December, 2015 by and between"}
    status = _overlay(
        tmp_path,
        {
            "agreement_date": {"value": "2015-12-01", "evidence": [span]},
            "effective_date": {"value": "2016-01-01", "evidence": [span]},
            "document_name": {"value": "Supply Agreement", "evidence": ["THIS SUPPLY AGREEMENT"]},
            "governing_law": {"value": "Delaware", "evidence": []},
            "contract_value": {"value": None, "evidence": []},
        },
    )
    assert status["agreement_date"] == (GROUNDED, "")
    assert status["effective_date"][0] == UNGROUNDED
    assert status["document_name"] == (GROUNDED, "")
    assert status["governing_law"] == (NO_EVIDENCE, "")
    assert "contract_value" not in status  # empty values are not reported


def test_overlay_header_evidence_and_vocabulary(tmp_path):
    header = {"header": "X-From: Schmidt, Ann M", "source": "cmu_enron_maildir"}
    status = _overlay(
        tmp_path,
        {
            "sender": {"value": "Ann M Schmidt", "evidence": [header]},
            "recipient": {"value": "Jeff Dasovich", "evidence": [header]},
            "intent": {"value": "not-a-label", "evidence": ["please review the attached draft"]},
        },
        doc_class="correspondence",
    )
    assert status["sender"] == (GROUNDED, "")
    assert status["recipient"][0] == UNGROUNDED
    assert status["intent"][0] == UNGROUNDED and status["intent"][1].startswith("out_of_vocabulary")


def test_overlay_applies_the_gates_per_field_rules(tmp_path):
    def roles(quote):
        return _overlay(
            tmp_path / str(len(quote)),
            {
                "party_roles": {"value": ["Alpha Inc.: supplier"], "evidence": [quote]},
            },
        )["party_roles"]

    assert roles("Alpha Inc. (the Supplier)") == (GROUNDED, "")
    status, reason = roles("Alpha Inc.")
    assert status == UNGROUNDED and "not stated in the evidence" in reason
