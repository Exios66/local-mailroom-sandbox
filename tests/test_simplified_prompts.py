"""SAND-026 simplified specialist prompts — live schema, no vendor overwrite."""

from __future__ import annotations

from pathlib import Path

import pytest

from mailroom_sandbox.prompts import list_variants, load_variant

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "config" / "prompts"

# Live registered fields from vendored specialist_agents / schemas.documents
# (offline copy so this test does not need the [pipeline] extra).
SIMPLIFIED_FIELDS: dict[str, tuple[str, ...]] = {
    "contracts_specialist_v33_simplified": (
        "reasoning",
        "document_name",
        "parties",
        "effective_date",
        "term_length",
        "governing_law",
        "contract_value",
        "renewal_terms",
        "cuad_family",
        "merger_consideration",
        "cuad_clauses",
        "maud_clauses",
        "confidence",
    ),
    "merger_agreement_specialist_simplified": (
        "reasoning",
        "document_name",
        "parties",
        "effective_date",
        "effective_time",
        "governing_law",
        "merger_consideration",
        "maud_clauses",
        "intent",
        "subject_matter",
        "keywords",
        "confidence",
    ),
    "corporate_records_specialist_simplified": (
        "entity_name",
        "record_type",
        "effective_date",
        "signatories",
        "jurisdiction",
        "filing_number",
        "intent",
        "subject_matter",
        "keywords",
    ),
    "correspondence_specialist_simplified": (
        "sender",
        "recipient",
        "additional_recipients",
        "communication_type",
        "communication_date",
        "demand_amount",
        "action_items",
        "urgency",
        "intent",
        "subject_matter",
        "keywords",
        "confidence",
    ),
    "insurance_claims_specialist_simplified": (
        "claim_number",
        "policy_number",
        "insurer",
        "insured_party",
        "claim_type",
        "date_of_loss",
        "date_filed",
        "claimed_amount",
        "adjuster",
        "damages_description",
        "coverage_determination",
        "denial_reasons",
        "supporting_documents",
        "intent",
        "subject_matter",
        "keywords",
        "claim_checklist",
        "confidence",
    ),
}

VENDOR_COUNTERPART = {
    "contracts_specialist_v33_simplified": "contracts_specialist_v33",
    "merger_agreement_specialist_simplified": "merger_agreement_specialist_production",
    "corporate_records_specialist_simplified": "corporate_records_specialist_production",
    "correspondence_specialist_simplified": "correspondence_specialist_production",
    "insurance_claims_specialist_simplified": "insurance_claims_specialist_production",
}

RETIRED = {
    "contracts_specialist_v33_simplified": ("key_obligations", "termination_clauses"),
    "corporate_records_specialist_simplified": ("key_provisions",),
    "correspondence_specialist_simplified": ("key_points", "referenced_communications"),
}


def test_simplified_stems_are_local_variants():
    variants = set(list_variants())
    for stem in SIMPLIFIED_FIELDS:
        assert stem in variants
        assert (PROMPTS / f"{stem}.txt").is_file()


@pytest.mark.parametrize("stem,fields", list(SIMPLIFIED_FIELDS.items()))
def test_simplified_prompt_names_every_live_schema_field(stem, fields):
    text = load_variant(stem)
    missing = [field for field in fields if field not in text]
    assert missing == [], f"{stem} missing live schema fields: {missing}"
    assert "PRODUCTION DOCTRINE" not in text
    assert "do not invent" in text.lower()
    assert "null" in text and "[]" in text
    assert "0.0" in text or "$0" in text or "Numeric zero" in text


@pytest.mark.parametrize("stem,retired", list(RETIRED.items()))
def test_simplified_prompt_does_not_register_retired_fields(stem, retired):
    text = load_variant(stem)
    lower = text.lower()
    assert "do not emit" in lower or "not emit" in lower or "retired" in lower
    for field in retired:
        assert field in text


def test_correspondence_simplified_uses_hub_intent_tokens():
    text = load_variant("correspondence_specialist_simplified")
    for token in (
        "payment_demand",
        "notice",
        "analysis",
        "request",
        "update",
        "meeting_invite",
        "press_communication",
        "email",
        "attorney_demand",
        "press_release",
    ):
        assert token in text
    assert "demand_payment" not in text


def test_contracts_simplified_is_pared_cuad_not_obligation_dump():
    text = load_variant("contracts_specialist_v33_simplified")
    vendor = load_variant("contracts_specialist_v33")
    assert len(text) < len(vendor) / 2
    assert "cuad_clauses" in text
    assert "Document Name" in text and "Third Party Beneficiary" in text
    assert "key_obligations" in text and "Do NOT emit" in text


def test_extract_local_v0_states_empty_and_zero_rules():
    text = load_variant("extract_local_v0")
    lower = text.lower()
    assert "json" in lower
    assert "null" in lower
    assert "[]" in text
    assert "invent" in lower


def test_simplified_prompts_shorter_than_vendor_mirrors():
    for simplified, vendor in VENDOR_COUNTERPART.items():
        s = load_variant(simplified)
        v = load_variant(vendor)
        assert len(s) < len(v), (simplified, len(s), len(v))
    contracts_s = load_variant("contracts_specialist_v33_simplified")
    assert len(contracts_s) < 12_000
