"""SAND-026: class-mismatched empty Hub GT must not count as extraction misses."""

from __future__ import annotations

from llm_dojo_scoring.field_scoring import score_extraction

from mailroom_sandbox.eval.extraction_scope import (
    LIVE_SCHEMA_FIELDS,
    applicable_expected_fields,
    is_empty_gt,
    scope_extraction_pair,
    scope_predicted_fields,
)
from mailroom_sandbox.eval.scoring import score_extraction_row


def test_empty_gt_treats_lists_and_blanks_as_absence_not_zero():
    assert is_empty_gt(None)
    assert is_empty_gt("")
    assert is_empty_gt("  ")
    assert is_empty_gt([])
    assert is_empty_gt({})
    assert is_empty_gt([None, "", []])
    assert not is_empty_gt(0)
    assert not is_empty_gt(0.0)
    assert not is_empty_gt("0")
    assert not is_empty_gt("payment_demand")
    assert not is_empty_gt(["breach"])


def test_vendor_score_extraction_skips_empty_list_gt():
    """The dojo bug this seam papered over is fixed upstream (>= v0.16).

    Empty-field contract: correct emptiness is not folded into the overall
    score, so ``denial_reasons: []`` GT is not a scored event at all.
    """
    result = score_extraction(
        "correspondence",
        {"intent": "name", "denial_reasons": "entity_list:free_text"},
        {"intent": "payment_demand"},
        {"intent": "payment_demand", "denial_reasons": []},
    )
    assert "denial_reasons" not in result.field_scores
    assert result.overall_score == 1.0


def test_applicable_expected_drops_foreign_empty_insurance_fields():
    expected = {
        "intent": "payment_demand",
        "subject_matter": "unpaid invoices",
        "keywords": ["breach", "demand", "invoice"],
        "denial_reasons": [],
        "claim_number": None,
        "supporting_documents": [],
        "coverage_determination": "",
        "claimed_amount": None,
        "intent_source": "manual",
        "intent_confidence": "1.0",
        "intent_status": "gt",
    }
    scoped = applicable_expected_fields("correspondence", expected)
    assert scoped["intent"] == "payment_demand"
    assert "denial_reasons" not in scoped
    assert "claim_number" not in scoped
    assert "claimed_amount" not in scoped
    assert "intent_source" not in scoped
    assert "confidence" not in scoped


def test_correspondence_aliases_hub_claimed_amount_to_demand_amount():
    pred, exp = scope_extraction_pair(
        "correspondence",
        {"demand_amount": 218440.0, "intent": "payment_demand"},
        {
            "claimed_amount": 218440.0,
            "intent": "payment_demand",
            "denial_reasons": [],
        },
    )
    assert "claimed_amount" not in exp
    assert "denial_reasons" not in exp
    assert exp["demand_amount"] == 218440.0
    assert pred["demand_amount"] == 218440.0
    assert "claimed_amount" not in pred


def test_scope_predicted_drops_foreign_keys_so_they_are_not_fp():
    scoped = scope_predicted_fields(
        "correspondence",
        {
            "intent": "payment_demand",
            "claim_number": "CLM-1",
            "denial_reasons": ["late notice"],
            "reasoning": {"summary": "trace"},
            "confidence": 0.9,
        },
    )
    assert scoped == {"intent": "payment_demand"}


def test_empty_insurance_gt_does_not_penalize_correspondence_row():
    predicted = {
        "intent": "payment_demand",
        "subject_matter": "unpaid invoices",
        "keywords": ["breach", "demand", "invoice"],
    }
    clean = score_extraction_row("correspondence", predicted, dict(predicted))
    polluted = score_extraction_row(
        "correspondence",
        predicted,
        {
            **predicted,
            "denial_reasons": [],
            "claim_number": None,
            "supporting_documents": [],
            "claimed_amount": None,
            "coverage_determination": "",
            "adjuster": "",
        },
    )
    assert clean["overall_extraction_score"] is not None
    assert polluted["overall_extraction_score"] == clean["overall_extraction_score"]
    assert polluted.get("extraction_f1") == clean.get("extraction_f1")
    assert polluted["overall_extraction_score"] >= 0.99


def test_empty_correspondence_gt_does_not_penalize_insurance_row():
    predicted = {
        "claim_number": "MTR-2025-0117",
        "policy_number": "AU-55210",
        "insured_party": "Devon Okafor",
    }
    clean = score_extraction_row("insurance_claim", predicted, dict(predicted))
    polluted = score_extraction_row(
        "insurance_claim",
        predicted,
        {
            **predicted,
            "sender": None,
            "recipient": "",
            "additional_recipients": [],
            "demand_amount": None,
            "action_items": [],
            "parties": [],
            "cuad_clauses": [],
        },
    )
    assert polluted["overall_extraction_score"] == clean["overall_extraction_score"]
    assert polluted.get("extraction_f1") == clean.get("extraction_f1")
    assert polluted["overall_extraction_score"] >= 0.99


def test_in_schema_empty_denial_reasons_are_not_insurance_misses():
    """Approved claims often carry denial_reasons: [] — that is not an FN."""
    predicted = {
        "claim_number": "MTR-1",
        "coverage_determination": "approved",
    }
    scored = score_extraction_row(
        "insurance_claim",
        predicted,
        {
            "claim_number": "MTR-1",
            "coverage_determination": "approved",
            "denial_reasons": [],
        },
    )
    assert scored["overall_extraction_score"] >= 0.99
    assert scored.get("extraction_f1", 1.0) >= 0.99


def test_live_schema_covers_five_classes_and_not_trace_keys():
    assert set(LIVE_SCHEMA_FIELDS) == {
        "contract",
        "merger_agreement",
        "corporate_record",
        "correspondence",
        "insurance_claim",
    }
    for fields in LIVE_SCHEMA_FIELDS.values():
        assert "reasoning" not in fields
        assert "confidence" not in fields
    assert "demand_amount" in LIVE_SCHEMA_FIELDS["correspondence"]
    assert "claimed_amount" in LIVE_SCHEMA_FIELDS["insurance_claim"]
    assert "claimed_amount" not in LIVE_SCHEMA_FIELDS["correspondence"]
    assert "cuad_clauses" not in LIVE_SCHEMA_FIELDS["merger_agreement"]
    assert "effective_time" in LIVE_SCHEMA_FIELDS["merger_agreement"]


def test_hf_fixture_correspondence_union_key_does_not_tank_score():
    """docclass_mini correspondence row stores dollars as claimed_amount."""
    predicted = {
        "intent": "payment_demand",
        "subject_matter": "unpaid invoices",
        "keywords": ["breach", "demand", "invoice"],
        "demand_amount": 218440.0,
    }
    expected = {
        "intent": "payment_demand",
        "intent_source": "manual",
        "intent_confidence": "1.0",
        "intent_status": "gt",
        "subject_matter": "unpaid invoices",
        "keywords": ["breach", "demand", "invoice"],
        "claimed_amount": 218440.0,
        "sentiment_label": "negative",
        "denial_reasons": [],
    }
    scored = score_extraction_row("correspondence", predicted, expected)
    assert scored["overall_extraction_score"] is not None
    assert scored["overall_extraction_score"] >= 0.99
    assert scored.get("extraction_f1", 1.0) >= 0.99


def test_seam_keys_track_the_vendored_engine_and_the_merger_agent():
    """The seam's field set IS the scoring contract — pin it, don't just comment it.

    Four classes must equal the vendored engine's ``field_types`` exactly. Merger is
    the deliberate exception: ``suite_for_doc_type("merger_agreement")`` returns the
    *contract* suite, whose map still carries CUAD leftovers (``term_length``,
    ``cuad_family``, ``cuad_clauses``, ``contract_value``, ``renewal_terms``) that
    the mailroom merger agent never emits. The seam scores the agent's real keys
    instead, minus the trace-only ``reasoning``/``confidence``.

    A vendored-schema refresh that moves any of these silently changes what every
    SAND-042 cell scores, so it must fail here rather than in a card.
    """
    from langchain_agents.specialist_agents import MERGER_AGREEMENT_SCHEMA
    from llm_dojo_scoring import suite_for_doc_type

    for doc_type in ("correspondence", "insurance_claim", "corporate_record", "contract"):
        engine = set(suite_for_doc_type(doc_type).field_types or {})
        assert set(LIVE_SCHEMA_FIELDS[doc_type]) == engine, doc_type

    agent = set((MERGER_AGREEMENT_SCHEMA.get("properties") or MERGER_AGREEMENT_SCHEMA).keys())
    merger = set(LIVE_SCHEMA_FIELDS["merger_agreement"])
    assert merger == agent - {"reasoning", "confidence"}
    # And the dojo's CUAD leftovers must not creep back into the merger score.
    assert not merger & {"term_length", "cuad_family", "cuad_clauses", "contract_value", "renewal_terms"}


# Fields the vendored schema declares that the sandbox deliberately leaves out of a class.
_DELIBERATELY_UNSCORED = {
    # Dojo 0.28 contract schema v2: these belong to merger_agreement.
    "contract": {"merger_consideration", "maud_clauses"},
    # llm-mailroom #283 emits it, but the Dojo insurance suite (7d69bbd) has no class-level
    # field type for it, and the seam must equal the engine (test above). The Dojo scores it
    # only through its CMS subtype schema. Scoring it here waits on the Dojo.
    "insurance_claim": {"cms_source_table"},
}


def test_live_schema_fields_track_the_vendored_extraction_schemas():
    """A vendor refresh that adds a field (e.g. llm-mailroom #283 cms_source_table) must not be silently unscored."""
    import importlib

    import sys

    from mailroom_sandbox.paths import vendored_mailroom_src

    src = str(vendored_mailroom_src())
    if src not in sys.path:
        sys.path.insert(0, src)
    schemas = importlib.import_module("schemas.documents").EXTRACTION_SCHEMAS
    for doc_class, live in LIVE_SCHEMA_FIELDS.items():
        declared = set(schemas[doc_class].model_fields) - {"reasoning", "confidence"}
        assert declared - _DELIBERATELY_UNSCORED.get(doc_class, set()) == set(live), doc_class



def test_cms_source_table_stays_out_until_the_dojo_suite_scores_it():
    from llm_dojo_scoring import suite_for_doc_type

    assert "cms_source_table" not in set(suite_for_doc_type("insurance_claim").field_types or {})
    pred, exp = scope_extraction_pair("insurance_claim", {"claim_type": "health", "cms_source_table": "pde"},
                                      {"claim_type": "health", "cms_source_table": "pde"})
    assert pred == exp == {"claim_type": "health"}
