"""R02 scorer hand-check: selection, perturbation drafts, sheet round trip and both scripts.

Network-free: small hand-made rows stand in for the HF cache (``--rows``), with their own split
directory and saved sorter pass.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox import experiment_splits as es
from mailroom_sandbox import scorer_handcheck as hc
from mailroom_sandbox.job.gate import load_bars
from mailroom_sandbox.paths import repo_root


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row(doc_id: str, cls: str, sub: str, fields: dict, text: str = "") -> dict:
    text = text or f"{cls} {sub} document {doc_id}"
    return {"id": doc_id, "filename": f"{doc_id}.txt", "doc_text": text, "content_sha256": _sha(text),
            "expected_doc_class": cls, "expected_subclass": sub, "expected_fields": fields}


def _insurance(doc_id: str, sub: str = "auto", n: int = 1) -> dict:
    fields = {
        "claim_number": f"CLM-00007{n}", "policy_number": f"POL-665746014{n}", "insurer": "BDR Mutual Insurance Company",
        "insured_party": "JONES, CHRISTOPHER", "claim_type": sub, "date_of_loss": "2024-11-21",
        "date_filed": "2024-11-24", "claimed_amount": "25784.32436488675", "coverage_determination": "pending",
        "intent": "coverage_determination", "denial_reasons": "[]",
        "supporting_documents": '["repair estimate", "police report"]',
    }
    presence = {k: "populated" for k in fields}
    presence["denial_reasons"] = "schema_documented_absence"  # a stated absence: answered empty, not scored
    return _row(doc_id, "insurance_claim", sub, {**fields, "gt_presence": json.dumps(presence)})


ROWS = [
    _row("DOC-c1", "contract", "License_Agreements", {"cuad_clause_labels": json.dumps({
        "Parties": [{"text": "Acme Corp"}], "Governing Law": [{"text": "the laws of the State of Delaware"}],
        "Audit Rights": [{"text": "Licensor may audit the books"}], "Non-Compete": []})}),
    _row("DOC-r1", "corporate_record", "bylaws", {
        "entity_name": "NCM FINANCIAL, INC.", "record_type": "bylaws", "effective_date": "2013-06-09",
        "intent": "governance_rules", "signatories": "['Michael Noel']"}),
    _row("DOC-m1", "correspondence", "email", {
        "sender": "Enterprise Storage Team", "recipient": "Jane Doe", "communication_type": "email",
        "communication_date": "2001-05-04", "intent": "notice"}),
    _insurance("DOC-i1"),
    _row("DOC-g1", "merger_agreement", "all_cash", {"maud_clause_labels": json.dumps({
        "Accuracy of Target R&W Closing Condition": {"answer": "General R&Ws"},
        "Agreement provides for matching rights in connection with COR": {"answer": "2 business days or less"},
        "Type of Consideration": {"answer": "All Cash"}})}),
]
SORTER = {  # the saved v0 answers: one class error, one unit error, the rest right
    "DOC-c1": ("contract", "license", 0.95), "DOC-r1": ("corporate_record", "bylaws", 0.9),
    "DOC-m1": ("unknown", "", 0.4), "DOC-i1": ("insurance_claim", "property", 0.8),
    "DOC-g1": ("merger_agreement", "all_cash", 0.99),
}
UNITS = [("contract", "License_Agreements", "contract/License_Agreements"),
         ("corporate_record", "bylaws", "corporate_record/family:governance_instruments"),
         ("corporate_record", "other", "corporate_record/family:governance_instruments"),
         ("correspondence", "email", "correspondence/email"),
         ("insurance_claim", "auto", "insurance_claim/auto"),
         ("insurance_claim", "property", "insurance_claim/property"),
         ("merger_agreement", "all_cash", "merger_agreement/all_cash")]


def _setup(tmp_path: Path, rows: list[dict], sorter: dict) -> dict[str, Path]:
    split = tmp_path / "split"
    split.mkdir()
    (split / "manifest.json").write_text(json.dumps({"dataset": {"revision": "f" * 40}}))
    (split / "dev.ids").write_text("# dev\n" + "".join(r["id"] + "\n" for r in rows))
    (split / "assignments.jsonl").write_text("".join(
        json.dumps({"id": f"A{i}", "doc_class": c, "subclass": s, "unit": u}) + "\n" for i, (c, s, u) in enumerate(UNITS)))
    handoff = tmp_path / "pass"
    handoff.mkdir()
    (handoff / "manifest.json").write_text(json.dumps({"model": "fixture/model", "dataset_revision": "e" * 40}))
    (handoff / "train.jsonl").write_text("".join(json.dumps({
        "id": r["id"], "content_sha256": r["content_sha256"], "sorter_doc_type": sorter[r["id"]][0],
        "sorter_doc_subclass": sorter[r["id"]][1], "sorter_confidence": sorter[r["id"]][2]}) + "\n" for r in rows))
    (handoff / "train.targets.jsonl").write_text("")
    rows_file = tmp_path / "rows.jsonl"
    rows_file.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"split": split, "pass": handoff, "rows": rows_file, "out": tmp_path / "out"}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _replay(cases, table, bars):
    """Scorer values keyed like the sheet, from case records (the check script's path)."""
    records = [hc.case_record(c) for c in cases]
    rows = {c.doc_id: c.row for c in cases}
    per_doc = {r["doc_id"]: hc.score_case(r, rows[r["doc_id"]], table, bars) for r in records}
    values = {(d, k): v for d, s in per_doc.items() for k, v in s.items() if not k.startswith("_")}
    stats = hc.stat_values(records, rows, per_doc, bars)
    values.update({("*", k): stats[k] for k in hc.STAT_CHECKS})
    return values


# ---------------------------------------------------------------- units


def test_unit_table_normalises_spellings_and_scores_at_the_unit():
    table = es.unit_table({"doc_class": c, "subclass": s, "unit": u} for c, s, u in UNITS)
    assert es.unit_of("contract", "license", table) == "contract/License_Agreements"
    assert es.unit_correct("corporate_record", "bylaws", "corporate_record", "other", table)  # same family
    assert not es.unit_correct("insurance_claim", "auto", "insurance_claim", "property", table)
    assert not es.unit_correct("contract", "License_Agreements", "correspondence", "license", table)
    assert not es.unit_correct("insurance_claim", "auto", "insurance_claim", "made_up", table)


def test_unit_table_refuses_one_token_in_two_units():
    with pytest.raises(es.SplitError):
        es.unit_table([{"doc_class": "contract", "subclass": "License_Agreements", "unit": "a"},
                       {"doc_class": "contract", "subclass": "license", "unit": "b"}])


# ---------------------------------------------------------------- perturbations


@pytest.mark.parametrize("ftype,value,profile,expect", [
    ("date", "2024-11-21", "normalised", ("November 21, 2024", "date_reformat", 1.0)),
    ("date", "2024-11-21", "mismatch", ("2025-11-21", "date_year_shift", 0.33)),
    ("money", "25784.32436488675", "normalised", ("$25,784.32", "money_format", 1.0)),
    ("money", 10, "mismatch", (11.0, "money_off_by_one", 0.0)),
    ("id", "CLM-1", "normalised", ("  clm-1 ", "id_case_ws", 1.0)),
    ("id", "CLM-1", "missing", (None, "missing", 0.0)),
    ("name", "Jane  Doe", "normalised", ("  JANE  DOE ", "name_case_ws", 1.0)),
    ("entity_list:name", ["a", "b", "c", "d"], "mismatch", (["a", "b"], "list_drop_half", None)),
    ("entity_list", [], "missing", ([], hc.EXPECTED_EMPTY, 1.0)),
])
def test_perturb_value_rules(ftype, value, profile, expect):
    assert hc.perturb_value(ftype, value, profile) == expect


def test_wrong_intent_is_another_vocabulary_label_not_a_decorated_one():
    # intent folds free text onto a label it contains: "zz_notice" would still score as notice.
    pred, kind, draft = hc.perturb_value("label", "notice", "mismatch", doc_class="correspondence", field="intent")
    assert kind == "label_changed" and draft == 0.0 and "notice" not in pred


def test_as_list_reads_json_and_python_literals():
    assert hc.as_list('["a", "b"]') == ["a", "b"]
    assert hc.as_list("['Michael Noel']") == ["Michael Noel"]
    assert hc.as_list("plain") is None


# ---------------------------------------------------------------- end to end on the module


def test_every_profile_draft_is_reproduced_by_the_run_scorers(tmp_path):
    rows = [_insurance(f"DOC-i{n}", sub, n) for n, sub in enumerate(("auto", "property", "auto", "property"))]
    sorter = {"DOC-i0": ("insurance_claim", "property", 0.6), "DOC-i1": ("insurance_claim", "property", 0.9),
              "DOC-i2": ("insurance_claim", "auto", 0.8), "DOC-i3": ("insurance_claim", "property", 0.7)}
    paths = _setup(tmp_path, rows, sorter)
    table = es.load_unit_table(paths["split"])
    bars = load_bars()
    cases = [hc.perturb(c) for c in hc.select_docs(rows, hc.load_sorter_pass(paths["pass"]), table,
                                                    classes=("insurance_claim",))]
    assert [c.profile for c in cases] == list(hc.PROFILES)
    assert {c.role for c in cases} == {"v0_unit_error", "v0_correct"}
    sheet = hc.sheet_rows(cases, table, draft=True, gated=bars.gated)
    cmp = hc.compare(sheet, _replay(cases, table, bars))
    assert not cmp.mismatched and not cmp.unlisted and not cmp.missing_checks, cmp.mismatched
    assert cmp.draft and not cmp.confirmed and cmp.exit_code in (2, 3)
    kinds = {r["perturbation"] for r in sheet}
    assert {"date_reformat", "date_year_shift", "money_format", "money_off_by_one", "id_case_ws", "id_changed",
            "label_changed", "missing"} <= kinds
    assert cases[0].fields["denial_reasons"] == []  # a stated absence is answered empty, never listed


def test_select_refuses_a_pass_that_read_other_text(tmp_path):
    paths = _setup(tmp_path, ROWS, SORTER)
    saved = hc.load_sorter_pass(paths["pass"])
    saved["DOC-i1"]["content_sha256"] = "0" * 64
    with pytest.raises(hc.HandcheckError, match="different text"):
        hc.select_docs(ROWS, saved, es.load_unit_table(paths["split"]), per_class=1)


def test_compare_exit_codes():
    sheet = [{"row_id": "R1", "doc_id": "d", "check": "class", "hand_score": "1", "hand_scored_by": "TT"},
             {"row_id": "R2", "doc_id": "d", "check": "field:x", "hand_score": "0.33", "hand_scored_by": hc.DRAFT}]
    values = {("d", "class"): 1.0, ("d", "field:x"): 0.33}
    assert hc.compare(sheet, values).exit_code == 3
    sheet[1]["hand_scored_by"] = "TT"
    assert hc.compare(sheet, values).exit_code == 0
    assert hc.compare(sheet, {**values, ("d", "field:y"): 1.0}).exit_code == 1  # unlisted scorer check
    sheet[1]["hand_score"] = "1"
    assert hc.compare(sheet, values).exit_code == 1
    sheet[1]["hand_score"] = ""
    assert hc.compare(sheet, values).exit_code == 2


# ---------------------------------------------------------------- scripts


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_build_and_check_scripts_round_trip(tmp_path, capsys):
    paths = _setup(tmp_path, ROWS, SORTER)
    build, check = _script("build_scorer_handcheck"), _script("check_scorer_handcheck")
    common = ["--split-dir", str(paths["split"]), "--rows", str(paths["rows"])]
    assert build.main([*common, "--sorter-pass", str(paths["pass"]), "--out", str(paths["out"]), "--per-class", "1"]) == 0
    sheet_path = paths["out"] / hc.SHEET_FILE
    sheet = _read(sheet_path)
    assert all(r["hand_score"] == "" and r["hand_scored_by"] == "" for r in sheet)  # blank without --draft
    prov = json.loads((paths["out"] / hc.PROVENANCE_FILE).read_text())
    assert prov["labels"]["runbook_named_commit"] == hc.LABELS_COMMIT
    assert prov["scorer"]["dojo_vendor_pin"] and prov["dataset"]["revision"] == "f" * 40
    assert not Path(prov["dataset"]["path"]).is_absolute()
    check_args = [*common, "--sheet-dir", str(paths["out"]), "--min-docs", "5"]
    assert check.main(check_args) == 2  # nothing scored yet

    assert build.main([*common, "--sorter-pass", str(paths["pass"]), "--out", str(paths["out"]),
                       "--per-class", "1", "--draft"]) == 0
    sheet = _read(sheet_path)
    capsys.readouterr()
    assert check.main(check_args) == 3  # every draft matches, nobody confirmed
    out = capsys.readouterr().out
    assert "mismatches 0" in out and "agent-draft" in out and "NOT passed" in out
    assert "macro-F1: Dojo sorter suite" in out and "Clopper-Pearson" in out

    for r in sheet:  # a person (fixture initials) confirms every row, filling the blanks from the scorer
        r["hand_scored_by"] = "TT"
    values = {(r["row_id"]): r for r in sheet}
    blank = [r for r in values.values() if not r["hand_score"]]
    assert not blank, "the fixture rows are all settled by the documented rules"
    _write(sheet_path, sheet)
    assert check.main(check_args) == 0
    assert check.main([*common, "--sheet-dir", str(paths["out"])]) == 5  # 5 documents, the gate needs 20

    flipped = [dict(r) for r in sheet]
    target = next(r for r in flipped if r["check"] == "class")
    target["hand_score"] = "0" if target["hand_score"] == "1" else "1"
    _write(sheet_path, flipped)
    assert check.main(check_args) == 1
    # a person's scores are never overwritten by a rebuild without --force
    assert build.main([*common, "--sorter-pass", str(paths["pass"]), "--out", str(paths["out"]), "--per-class", "1"]) == 2

    drifted = [dict(r) for r in ROWS]
    drifted[3] = {**drifted[3], "expected_fields": {**drifted[3]["expected_fields"], "insurer": "Other Mutual"}}
    paths["rows"].write_text("".join(json.dumps(r) + "\n" for r in drifted))
    assert check.main(check_args) == 4


def test_cms_row_lists_the_documented_absent_field_its_truth_names():
    fields = {**_insurance("DOC-x", "inpatient")["expected_fields"], "cms_source_table": "inpatient",
              "claim_type": "health", "adjuster": ""}  # a CMS row: health product line, table from the subclass
    truth = hc.scored_truth("insurance_claim", fields, "inpatient")
    assert truth["denial_reasons"][1] == []  # documented absent on a CMS row: scored, answered empty
    assert "adjuster" not in truth  # blank in the truth, so the suite leaves it out
    assert "denial_reasons" not in hc.scored_truth("insurance_claim", _insurance("DOC-y")["expected_fields"])


def test_field_scores_are_opt_in_on_the_row_scorer():
    from mailroom_sandbox.eval.scoring import score_extraction_row

    expected = {"claim_number": "CLM-1", "insurer": "BDR Mutual"}
    plain = score_extraction_row("insurance_claim", dict(expected), dict(expected))
    assert "field_scores" not in plain
    scored = score_extraction_row("insurance_claim", {"claim_number": "clm-1"}, dict(expected), field_scores=True)
    assert scored["field_scores"]["claim_number"] == 1.0
