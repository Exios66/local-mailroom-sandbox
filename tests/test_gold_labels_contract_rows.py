"""Every empty-CUAD contract row has a near-gold label for a scored contract field.

A contract row whose ``cuad_clause_labels`` map names no category (91 rows at the pinned corpus
revision) scores only when a reviewed field label stands in for the missing CUAD universe
(SHF-016, ``docs/scoring-hotfixes.md``). This pins that each of those 91 documents keeps a
near-gold overlay record with at least one populated label on a field the contract scorer
counts, so a rebuild or export that drops one is caught here and not as a silent unscored row.
Network-free: it reads the committed overlay and the committed id list only.
"""
from __future__ import annotations

from pathlib import Path

from mailroom_sandbox import gold_labels as gl
from mailroom_sandbox.eval.extraction_scope import applicable_expected_fields

IDS = Path(__file__).parent / "fixtures" / "empty_cuad_contract_ids.txt"


def _ids() -> list[str]:
    return [line.strip() for line in IDS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scored_near_gold_fields(rec: dict) -> list[str]:
    """Near-gold labels whose value the contract scorer counts as an extraction event."""
    out = []
    for field, lab in (rec.get("labels") or {}).items():
        if not str(lab.get("basis") or "").startswith("near_gold:"):
            continue
        if applicable_expected_fields("contract", {field: lab.get("value")}):
            out.append(field)
    return out


def test_the_id_list_is_the_91_empty_cuad_contract_rows():
    ids = _ids()
    assert len(ids) == 91 and len(set(ids)) == 91
    assert all(i.startswith("DOC-") for i in ids)


def test_each_empty_cuad_contract_row_has_a_near_gold_label_on_a_scored_field():
    overlay = gl.load_near_gold()
    missing = [i for i in _ids() if i not in overlay]
    assert not missing, f"{len(missing)} empty-CUAD contract rows have no near-gold record: {missing[:5]}"
    wrong_class = [i for i in _ids() if overlay[i].get("doc_class") != "contract"]
    assert not wrong_class, wrong_class[:5]
    unscored = [i for i in _ids() if not _scored_near_gold_fields(overlay[i])]
    assert not unscored, f"{len(unscored)} rows label no scored contract field: {unscored[:5]}"
