"""SHF-016: an empty-universe CUAD row keeps the suite field headline.

A contract row whose ``cuad_clause_labels`` map names no category scores the suite field basis
(the reviewed interim / near-gold field labels merged at truth prep stand in); the raw side
keeps the Dojo pin's ``None``. Network-free; no LLM calls.
"""
from __future__ import annotations

from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval.scoring import score_extraction_row


def _row(**fields):
    truth = {"agreement_date": "December 1, 2015", "signatories": ["ACME Corp", "Beta LLC"], **fields}
    return dict(truth), dict(truth)


# --- the fix and its fingerprint ----------------------------------------------------------------


def test_shf016_is_registered_current_extraction_scoped_and_pinned():
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-016")
    assert sh.status(refresh=True)["SHF-016"] == "current"
    assert "SHF-016" in sh.EXTRACTION_FIXES
    described = next(f for f in sh.describe()["fixes"] if f["id"] == "SHF-016")
    assert {t["target"] for t in described["targets"]} == {t for t, _ in fix.targets}


def test_shf016_an_empty_cuad_row_keeps_the_suite_headline():
    expected, predicted = _row(cuad_clause_labels="{}")
    out = score_extraction_row("contract", predicted, expected)
    assert out["overall_extraction_score"] is not None
    assert out["cuad_unlabeled"] is True
    assert "SHF-016" in out["scoring_hotfixes"]
    assert "overall_extraction_score" in out["scoring_hotfixes_changed"]
    # the raw side keeps the Dojo pin's None, so the run-level raw means still exclude the row
    assert out["raw_dojo"]["overall_extraction_score"] is None


def test_shf016_a_stale_fix_leaves_the_dojo_pin(monkeypatch):
    expected, predicted = _row(cuad_clause_labels="{}")
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-016")
    stale = sh.ScoringHotfix(fix.id, fix.layer,
                             tuple((t, "0" * 64) for t, _ in fix.targets),
                             fix.upstream, fix.summary)
    monkeypatch.setattr(sh, "HOTFIXES", tuple(stale if f.id == fix.id else f for f in sh.HOTFIXES))
    monkeypatch.setattr(sh, "_STATUS", {})
    out = score_extraction_row("contract", predicted, expected)
    assert out["overall_extraction_score"] is None
    assert "cuad_unlabeled" not in out
    monkeypatch.setattr(sh, "_STATUS", {})


def test_shf016_a_labeled_cuad_row_still_scores_the_cuad_basis():
    expected, predicted = _row(
        cuad_clause_labels='{"Parties": [["ACME Corp"], ["Beta LLC"]], "Agreement Date": [["December 1, 2015"]]}')
    out = score_extraction_row("contract", predicted, expected)
    assert "cuad_unlabeled" not in out
    assert out["scoring_method"].endswith("+cuad")
    # SHF-016 is on for the row (the active extraction set), but moves nothing here
    assert "overall_extraction_score" not in out["scoring_hotfixes_changed"]


def test_shf016_the_merger_maud_replacement_is_untouched():
    truth = {"intent": "material_agreement", "maud_clause_labels": "{}"}
    out = score_extraction_row("merger_agreement", dict(truth), dict(truth))
    assert "cuad_unlabeled" not in out
    assert out["scoring_method"].endswith("+maud")


def test_shf016_a_contract_row_without_a_cuad_key_never_needed_the_fix():
    expected, predicted = _row()
    out = score_extraction_row("contract", predicted, expected)
    assert "cuad_unlabeled" not in out
    assert "overall_extraction_score" not in out["scoring_hotfixes_changed"]
