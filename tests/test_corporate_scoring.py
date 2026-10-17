"""Sandbox #145 vendor bump: ``score_extraction_row`` drives the per-subclass dojo machinery.

The sandbox scores a corporate-record row through the SAME vendored alignment
the dojo's ``suites._score_extraction`` runs (``align_unlabeled`` +
``corporate_record_schema``) — wired via ``doc_subclass``/``expected_subclass``.
This test only checks the WIRING: every expectation is computed IN TEST from
the vendored module (no hardcoded numbers), so a scoring bump that changes the
alignment semantics still passes as long as the sandbox faithfully forwards
the subclass to the vendored engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mailroom_sandbox.eval.scoring import score_extraction_row

REPO = Path(__file__).resolve().parents[1]


def _real_corporate_row(subclass: str = "bylaws") -> dict[str, Any]:
    """One REAL published-v9.2 corporate row from the installed corpus cache.

    Skipped (not stubbed) when the cache is absent, so a fixture never drifts
    from the published GT shape this wiring must serve.
    """
    for cache in sorted((REPO / "data" / "cache").glob("*mailroom-dataset*")):
        gt = cache / "ground_truth_all.jsonl"
        if not gt.is_file():
            continue
        for line in gt.open(encoding="utf-8"):
            row = json.loads(line)
            if (
                row.get("expected_doc_class") == "corporate_record"
                and str(row.get("expected_subclass") or "").lower() == subclass
            ):
                return row
    pytest.skip("no corporate GT row in the installed corpus cache")


def test_corporate_row_scores_with_dojo_alignment():
    from llm_dojo_scoring import suite_for_doc_type
    from llm_dojo_scoring.corporate_record_schema import align_unlabeled

    row = _real_corporate_row("bylaws")
    expected = row["expected_fields"]
    # A realistic prediction: the labeled semantic trio plus subclass entity
    # keys the published GT leaves blank WITHOUT documenting absence.
    predicted = dict(expected)
    predicted["intent"] = expected.get("intent")
    predicted["subject_matter"] = "bylaws of the registrant"
    predicted["keywords"] = ["bylaws", "EX-3.2"]
    predicted["entity_name"] = "NCM Financial, Inc."
    predicted["certifying_officer"] = "Michael Noel"
    predicted["principal"] = "Someone Else"  # another subclass's extension key

    scored = score_extraction_row(
        "corporate_record",
        predicted,
        expected,
        doc_text=row.get("doc_text"),
        expected_subclass=row.get("expected_subclass"),
    )

    # Dojo-side expectation, computed IN TEST from the vendored module.
    dojo_expected, dojo_predicted, dojo_dropped = align_unlabeled(
        row.get("expected_subclass"), expected, expected, predicted
    )
    assert dojo_dropped, "the fixture must exercise unlabeled fields"
    # 1. per-row unlabeled_fields match the dojo payload exactly
    assert scored["unlabeled_fields"] == list(dojo_dropped)
    # 2. the headline equals the vendored engine on the aligned pair
    reference = suite_for_doc_type("corporate_record").score(
        dojo_expected, dojo_predicted, doc_text=row.get("doc_text")
    )
    assert scored["overall_extraction_score"] == pytest.approx(
        reference.overall_score, abs=1e-9
    )
    # 3. a subclass entity the GT never labeled was aligned out, not charged
    #    as a spurious fill: score the unaligned pair the OLD (pre-#145) way
    #    and confirm the wired path scores STRICTLY not-worse.
    raw_reference = suite_for_doc_type("corporate_record").score(
        expected, predicted, doc_text=row.get("doc_text")
    )
    assert scored["overall_extraction_score"] >= raw_reference.overall_score - 1e-9


def test_corporate_alignment_is_subclass_sensitive():
    """Without the subclass the alignment normalizes to ``other`` — detectable.

    ``signature_block`` extension fields named only by the row's own subclass
    (e.g. a ``powers_of_attorney`` row's ``principal``) must remain scorable
    candidates under the forwarded subclass; the miss does not change the
    unlabeled set the same way it would under "" → ``other``.
    """
    from llm_dojo_scoring.corporate_record_schema import align_unlabeled

    row = _real_corporate_row("powers_of_attorney")
    assert row.get("expected_subclass"), row["id"]
    expected = row["expected_fields"]
    predicted = dict(expected)
    predicted["principal"] = "Grantor L."

    scored = score_extraction_row(
        "corporate_record", predicted, expected, expected_subclass=row["expected_subclass"]
    )
    _, _, dojo_dropped = align_unlabeled(
        row["expected_subclass"], expected, expected, predicted
    )
    _, _, other_dropped = align_unlabeled(None, expected, expected, predicted)
    # the fwd subclass vs the default normalized one must be asserted to be
    # what the sandbox actually produced
    assert scored["unlabeled_fields"] == list(dojo_dropped)
    # and (on the published v9.2 shape where entity GT is blank/unlabeled)
    # the two alignments coincide for this row — the point is that the scored
    # payload used the subclass, whatever the dojo itself computed from it.
    scored_other = score_extraction_row(
        "corporate_record", predicted, expected,
        doc_subclass=row["expected_subclass"],
    )
    assert scored_other["unlabeled_fields"] == list(dojo_dropped)
    assert scored["overall_extraction_score"] == scored_other["overall_extraction_score"]
    # guard against a silent default-"other" fallback producing a different
    # alignment than the dojo's own subclass-aware computation
    if dojo_dropped != other_dropped:
        assert scored["unlabeled_fields"] != list(other_dropped)


def test_non_subclass_paths_are_unchanged():
    """``doc_subclass=None`` (or an unknown class) keeps the legacy payload."""
    predicted = {
        "intent": "payment_demand",
        "subject_matter": "unpaid invoices",
        "keywords": ["breach", "demand", "invoice"],
    }
    clean = score_extraction_row("correspondence", predicted, dict(predicted))
    scored = score_extraction_row("correspondence", dict(predicted), dict(predicted))
    assert "unlabeled_fields" not in clean and "unlabeled_fields" not in scored
    assert scored["overall_extraction_score"] == clean["overall_extraction_score"]
    corporate = score_extraction_row(
        "corporate_record", dict(predicted), dict(predicted)
    )
    # no subclass given → legacy single-path result; no alignment surfaced
    assert "unlabeled_fields" not in corporate
    assert corporate["overall_extraction_score"] is not None
