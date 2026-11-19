"""Gold-field grounding over the fixture manifest (network-free)."""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox.notebook import (
    ALIAS_FORM,
    NO_EVIDENCE,
    CATEGORICAL,
    DATE_FORM,
    IN_VOCABULARY,
    INTERIM,
    INTERIM_CORRECTION,
    NEAR_GOLD,
    NEAR_GOLD_SHF010,
    GROUNDED,
    GROUNDED_NORMALIZED,
    HUB,
    NON_TEXT,
    NUMBER_FORM,
    NUMERAL_FORM,
    UNGROUNDED,
    agent_fixture_grounding,
    gold_field_grounding,
    label_overlay_grounding,
    merged_truth,
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


def test_agent_row_with_empty_catalog_file_is_ungrounded(tmp_path, monkeypatch):
    import mailroom_sandbox.datasets as datasets
    import mailroom_sandbox.paths as paths
    import mailroom_sandbox.prep as prep

    (tmp_path / "agents").mkdir()
    (tmp_path / "contract").mkdir()
    (tmp_path / "contract" / "blank.txt").write_text("   \n")
    rows = [
        {
            "id": "r1",
            "subdir": "contract",
            "filename": "blank.txt",
            "expected_fields": {"parties": ["ACME Corporation"]},
        },
        {"id": "r2", "expected_fields": {"parties": ["ACME Corporation"]}},  # no source text
    ]
    (tmp_path / "agents" / "judge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for module in (datasets, paths, prep):
        monkeypatch.setattr(module, "fixtures_dir", lambda: tmp_path)
    [finding] = agent_fixture_grounding(["judge"])
    assert (finding.row_id, finding.status) == ("judge/r1", UNGROUNDED)


# --------------------------------------------------------------------------- label overlays


def test_scoring_overlays_are_supported_by_their_evidence():
    findings = label_overlay_grounding()
    assert [f for f in findings if f.status == UNGROUNDED] == []
    checked = [f for f in findings if f.status == GROUNDED]
    assert {f.overlay for f in checked} == {"gold-overlay", "interim"}
    assert len(checked) > 6000
    # The reviewed header fill whose Exchange display name fuses the surname with the org
    # ("Michael GrimesCORPENRON") passes the review file's own header rule.
    grimes = next(
        f
        for f in findings
        if (f.overlay, f.doc_id, f.field) == ("interim", "DOC-2ccf94f14bd5f040", "recipient")
    )
    assert (grimes.status, grimes.basis) == (GROUNDED, "original_header")
    # Only gate fills and CUAD corrections, which need their Hub document, stay unchecked here.
    unchecked = {f.basis for f in findings if f.status == NO_EVIDENCE}
    assert unchecked <= {"gate_accepted_grounded", "cuad_party_spans", "cuad_agreement_date"}


def _overlay(tmp_path, labels, doc_class="contract", overlay="gold-overlay", rows=None, **record):
    (tmp_path / overlay).mkdir(parents=True)
    record = {"doc_class": doc_class, "doc_id": "DOC-1", **record, "labels": labels}
    (tmp_path / overlay / f"{doc_class}.jsonl").write_text(json.dumps(record) + "\n")
    found = label_overlay_grounding([overlay], root=tmp_path, rows=rows)
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


def test_overlay_rechecks_derived_labels_from_the_subclass(tmp_path):
    def derived(field, value, sub, basis="hub_subclass", doc_class="corporate_record"):
        label = {"value": value, "status": "derived", "basis": basis}
        where = tmp_path / f"{field}-{value}"
        return _overlay(where, {field: label}, doc_class, "interim", doc_subclass=sub)[field][0]

    assert derived("record_type", "other", "indenture") == GROUNDED  # Dojo enum mapping
    assert derived("record_type", "indenture", "indenture") == UNGROUNDED
    assert (
        derived("cms_source_table", "carrier", "carrier", "cms_subclass", "insurance_claim")
        == GROUNDED
    )
    assert (
        derived("cms_source_table", "dme", "carrier", "cms_subclass", "insurance_claim")
        == UNGROUNDED
    )


def test_overlay_checks_reviewed_labels_by_the_review_rule(tmp_path):
    fused = {
        "file": "kean-s/sent_items/1.",
        "header": "X-To: Michael GrimesCORPENRON <Michael GrimesCORPENRON/ENRON@EUEnronXGate>",
        "source": "cmu_enron_maildir",
    }
    review = {"reviewer": {"role": "review"}, "note": "n", "file": "f"}
    status = _overlay(
        tmp_path,
        {
            "recipient": {
                "value": "Michael Grimes",
                "basis": "original_header",
                "evidence": [fused],
                "status": "gap_fill",
                "review": review,
            },
            "sender": {
                "value": "Jeff Dasovich",
                "basis": "original_header",
                "evidence": [fused],
                "status": "gap_fill",
                "review": review,
            },
            "intent": {
                "value": "request",
                "basis": "review_read_message",
                "evidence": [],
                "status": "correction",
                "review": review,
            },
        },
        "correspondence",
        "interim",
    )
    assert status["recipient"] == (GROUNDED, "")
    assert status["sender"][0] == UNGROUNDED  # an X-To line does not state the sender
    assert status["intent"] == (IN_VOCABULARY, "")  # a reviewed intent quotes nothing


def test_reviewed_intent_is_held_to_the_vocabulary_rule_only(tmp_path):
    review = {"reviewer": {"role": "review"}, "note": "n", "file": "f"}
    status = _overlay(
        tmp_path,
        {
            "intent": {
                "value": "request",
                "basis": "review_read_message",
                "evidence": ["Please"],  # an optional quote under the gate's token minimum
                "status": "correction",
                "review": review,
            },
        },
        "correspondence",
        "interim",
    )
    assert status["intent"] == (IN_VOCABULARY, "")


def test_overlay_closed_labels_disputed_and_support(tmp_path):
    status = _overlay(
        tmp_path,
        {
            "urgency": {"value": "routine", "status": "gap_fill", "evidence": []},
            "intent": {"value": "not-a-label", "status": "gap_fill"},
            "sender": {"value": "Ann Roe", "status": "disputed"},
            "recipient": {"value": "Bo Li", "status": "gap_fill", "support": 0.5},
        },
        "correspondence",
        "interim",
    )
    assert status["urgency"] == (IN_VOCABULARY, "")
    assert status["intent"][0] == UNGROUNDED
    assert "sender" not in status  # disputed labels are never truth
    assert status["recipient"][0] == UNGROUNDED and "admission threshold" in status["recipient"][1]


def test_overlay_checks_unquoted_labels_against_the_hub_row(tmp_path):
    from mailroom_sandbox.interim_labels import doc_sha

    text = "This Agreement, made this 27t h day of March, 2017, is between Alpha Inc. and Beta LLC."
    cuad = {
        "cuad_clause_labels": json.dumps(
            {"Agreement Date": [{"start": 25, "text": "27t h day of March, 2017"}]}
        )
    }
    row = {"id": "DOC-1", "doc_text": text, "expected_fields": cuad}
    labels = {
        "parties": {
            "value": ["Alpha Inc.", "Beta LLC"],
            "status": "gap_fill",
            "basis": "gate_accepted_grounded",
            "support": 1.0,
        },
        "governing_law": {
            "value": "Delaware",
            "status": "gap_fill",
            "basis": "gate_accepted_grounded",
            "support": 1.0,
        },
        "effective_date": {
            "value": "2017-03-27",
            "status": "correction",
            "basis": "cuad_agreement_date",
            "support": 1.0,
        },
    }
    status = _overlay(
        tmp_path / "a", labels, "contract", "interim", {"DOC-1": row}, doc_sha256=doc_sha(text)
    )
    assert status["parties"] == (GROUNDED, "")
    assert status["governing_law"] == (UNGROUNDED, "value not in the document")
    assert status["effective_date"] == (GROUNDED, "")  # CUAD's span, not the OCR-broken text
    stale = _overlay(
        tmp_path / "b", labels, "contract", "interim", {"DOC-1": row}, doc_sha256="0" * 16
    )
    assert stale["parties"] == (NO_EVIDENCE, "document text changed since the label was read")
    weak = {"recipient": {"value": "Alpha Inc.", "status": "gap_fill", "support": 0.5}}
    low = _overlay(
        tmp_path / "d", weak, "contract", "interim", {"DOC-1": row}, doc_sha256=doc_sha(text)
    )
    assert low["recipient"][0] == UNGROUNDED  # in the text, but under the admission threshold
    assert "admission threshold" in low["recipient"][1]
    assert _overlay(tmp_path / "c", labels, "contract", "interim")["parties"] == (NO_EVIDENCE, "")


# --------------------------------------------------------------------------- merged truth


def _merge_fixture():
    from mailroom_sandbox.interim_labels import doc_sha

    text = "From the desk of the sender. Please review the attached draft by Friday."
    row = {
        "id": "DOC-1",
        "expected_doc_class": "correspondence",
        "doc_text": text,
        "expected_fields": {"sender": "Hub Sender", "intent": "notice"},
    }

    def lab(value, status="gap_fill", basis="gate_accepted_grounded"):
        return {"value": value, "status": status, "basis": basis, "use_as_truth": True}

    interim = {
        "DOC-1": {
            "doc_sha256": doc_sha(text),
            "labels": {
                "sender": lab("Interim Sender"),  # the Hub labels it: a gap fill never applies
                "intent": lab("request", "correction", "review_read_message"),
                "recipient": lab("Gate Recipient"),  # near-gold disagrees: SHF-010
                "action_items": lab(["review the draft"]),  # near-gold agrees
                "communication_date": lab("2001-07-06", basis="original_header"),
            },
        }
    }

    def near(value):
        return {"value": value, "status": "gap_fill", "basis": "near_gold:two_pass_agree"}

    near_gold = {
        "DOC-1": {
            "doc_sha256": doc_sha(text),
            "labels": {
                "sender": near("Near Sender"),
                "recipient": near("Near Recipient"),
                "action_items": near(["review the draft"]),
                "communication_date": near(None),  # the text lost the header
                "urgency": near("routine"),
            },
        }
    }
    return row, interim, near_gold


def test_merged_truth_names_each_fields_source_and_overlap():
    row, interim, near_gold = _merge_fixture()
    merge = merged_truth([row], interim=interim, near_gold=near_gold)
    source = {f.field: (f.source, f.value) for f in merge.fields}
    assert source == {
        "sender": (HUB, "Hub Sender"),
        "intent": (INTERIM_CORRECTION, "request"),
        "recipient": (NEAR_GOLD_SHF010, "Near Recipient"),
        "action_items": (INTERIM, ["review the draft"]),
        "communication_date": (INTERIM, "2001-07-06"),
        "urgency": (NEAR_GOLD, "routine"),
    }
    assert merge.violations == []
    assert merge.overlaps == {
        ("gate_accepted_grounded", "differ", HUB): 1,  # sender: the Hub label stands
        ("gate_accepted_grounded", "agree", INTERIM): 1,
        ("gate_accepted_grounded", "differ", NEAR_GOLD): 1,
        ("original_header", "differ", INTERIM): 1,
    }
    assert merge.breakdown() == {
        "correspondence": {
            HUB: 1,
            INTERIM_CORRECTION: 1,
            NEAR_GOLD_SHF010: 1,
            INTERIM: 2,
            NEAR_GOLD: 1,
        }
    }


def test_merged_truth_resolves_a_raw_hub_row_by_document_id():
    row, interim, near_gold = _merge_fixture()
    raw = {k: v for k, v in row.items() if k != "id"} | {"document_id": row["id"]}
    prepared = merged_truth([row], interim=interim, near_gold=near_gold)
    merge = merged_truth([raw], interim=interim, near_gold=near_gold)
    assert merge.fields == prepared.fields
    assert {f.field: f.source for f in merge.fields}["urgency"] == NEAR_GOLD


def test_merged_truth_reports_an_overlay_replacing_a_hub_label(monkeypatch):
    import mailroom_sandbox.interim_labels as il

    row, interim, near_gold = _merge_fixture()

    def leaky(row, overlay, *, overlay_sha):  # a gap fill that wrongly wins over the Hub
        out = dict(row, expected_fields={**row["expected_fields"], "sender": "Interim Sender"})
        out["interim_labels"] = {"fields": ["sender"], "overlay_sha256": overlay_sha}
        return out

    del near_gold["DOC-1"]["labels"]["sender"]
    monkeypatch.setattr(il, "apply_overlay", leaky)
    merge = merged_truth([row], interim=interim, near_gold=near_gold)
    assert merge.violations == ["DOC-1.sender: an interim gap_fill replaced the Hub label"]


def test_merged_truth_leaves_rows_whose_text_changed():
    row, interim, near_gold = _merge_fixture()
    row = dict(row, doc_text=row["doc_text"] + " (edited)")
    merge = merged_truth([row], interim=interim, near_gold=near_gold)
    assert {(f.field, f.source) for f in merge.fields} == {("sender", HUB), ("intent", HUB)}
    assert merge.violations == []


def test_merged_truth_lists_unsettled_hub_conflicts_and_keeps_the_hub_value():
    row, interim, near_gold = _merge_fixture()
    interim["DOC-1"]["labels"]["sender"] = {
        "value": "the sender",
        "status": "disputed",
        "basis": "gate_vs_hub",
        "support": 0.97,
        "use_as_truth": False,
    }
    merge = merged_truth([row], interim=interim, near_gold=near_gold)
    assert {f.field: f.source for f in merge.fields}["sender"] == HUB
    [conflict] = merge.hub_conflicts
    assert (conflict.field, conflict.hub_value, conflict.overlay_value, conflict.support) == (
        "sender",
        "Hub Sender",
        "the sender",
        0.97,
    )
    # The gate's value is in the text and the Hub's is not: evidence for a review, not a verdict.
    assert (conflict.hub_grounded, conflict.overlay_grounded) == (False, True)
