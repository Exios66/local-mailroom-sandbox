"""R03 gold-label audit sheets: disagreement selection, set refusal, sampling and the gate summary."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox import gold_audit as ga

_SPEC = importlib.util.spec_from_file_location(
    "build_gold_audit_sheet", Path(__file__).resolve().parents[1] / "scripts" / "build_gold_audit_sheet.py")
cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cli)

ASSIGN = {"DOC-d1": "dev", "DOC-d2": "dev", "DOC-d3": "dev", "DOC-p1": "pool",
          "DOC-h1": "heldout", "DOC-c1": "calibration"}
SCHEMAS = {"classes": {
    "correspondence": {"fields": {"sender": {"verdict": "iterate"}, "recipient": {"verdict": "iterate"},
                                  "urgency": {"verdict": "thin"}, "keywords": {"verdict": "iterate"}},
                       "subclasses": {"email": {"fields": {"sender": {"verdict": "thin"},
                                                           "recipient": {"verdict": "iterate"}}}}},
    "insurance_claim": {"fields": {"claim_number": {"verdict": "iterate"}, "cms_source_table": {"verdict": "iterate"}},
                        "subclasses": {}},
    "merger_agreement": {"fields": {"maud_clauses": {"verdict": "iterate"}}, "subclasses": {}},
    "contract": {"fields": {"cuad_clauses": {"verdict": "iterate"}, "cuad_family": {"verdict": "iterate"}},
                 "subclasses": {}},
}}


def _letter(doc_id, *, sender="Jeff Skilling", recipient="Ken Lay", urgency="high", interim=("sender",)):
    return {"id": doc_id, "expected_doc_class": "correspondence", "expected_subclass": "email",
            "doc_text": f"From: {sender}\nTo: {recipient}\nSubject: pipeline capacity",
            "expected_fields": {"sender": sender, "recipient": recipient, "urgency": urgency,
                                "keywords": ["pipeline"]},
            "interim_labels": {"fields": list(interim), "overlay_sha256": "x"}}


def _write_run(tmp_path: Path, name: str, rows: list[dict], preds: dict[str, dict], **item_extra) -> Path:
    run = tmp_path / "runs" / name
    run.mkdir(parents=True)
    (run / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    items = [{"item_id": doc_id, "ok": True, "pred": pred, **item_extra.get(doc_id, {})} for doc_id, pred in preds.items()]
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return run


@pytest.fixture
def env(tmp_path):
    split = tmp_path / "split"
    split.mkdir()
    (split / "assignments.jsonl").write_text(
        "".join(json.dumps({"id": i, "set": s}) + "\n" for i, s in ASSIGN.items()), encoding="utf-8")
    schemas = tmp_path / "schemas.json"
    schemas.write_text(json.dumps(SCHEMAS), encoding="utf-8")
    return {"tmp": tmp_path, "split": split, "schemas": schemas}


def _build(env, run, lineage, **kw):
    return ga.build_sheet(run, lineage, split_dir=env["split"], schemas_path=env["schemas"],
                          seed=kw.pop("seed", 7), **kw)


# --- set refusal -------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["DOC-h1", "DOC-c1", "DOC-zz"])
def test_heldout_calibration_and_unknown_ids_are_refused(env, bad):
    run = _write_run(env["tmp"], "r", [_letter("DOC-d1"), _letter(bad)], {"DOC-d1": {}, bad: {}})
    with pytest.raises(ga.AuditError, match="dev and pool documents only"):
        _build(env, run, "correspondence")


def test_check_sets_names_each_refused_set():
    with pytest.raises(ga.AuditError) as err:
        ga.check_sets(["DOC-d1", "DOC-h1", "DOC-c1"], ASSIGN)
    assert "heldout 1" in str(err.value) and "calibration 1" in str(err.value)
    ga.check_sets(["DOC-d1", "DOC-p1"], ASSIGN)  # dev and pool pass


def test_specialist_lineage_refuses_other_classes(env):
    other = {**_letter("DOC-d2"), "expected_doc_class": "insurance_claim"}
    run = _write_run(env["tmp"], "r", [_letter("DOC-d1"), other], {"DOC-d1": {}, "DOC-d2": {}})
    with pytest.raises(ga.AuditError, match="also holds"):
        _build(env, run, "correspondence")


def test_unknown_lineage_and_missing_files(env, tmp_path):
    with pytest.raises(ga.AuditError, match="unknown lineage"):
        _build(env, tmp_path, "nope")
    with pytest.raises(ga.AuditError, match="missing"):
        _build(env, tmp_path / "absent", "sorter")


# --- sorter -------------------------------------------------------------------------------------

def test_sorter_class_then_subclass_disagreements():
    row = {"id": "x", "expected_doc_class": "contract", "expected_subclass": "License_Agreements"}
    wrong_class = ga.sorter_disagreements(row, {"pred": {"doc_type": "corporate_record"}})
    assert [d["field"] for d in wrong_class] == ["doc_class"]
    assert wrong_class[0]["v0_value"] == "corporate_record" and wrong_class[0]["gold_value"] == "contract"
    # CUAD subtypes compare through the Dojo's normalize_subtype: License_Agreements == license
    assert ga.sorter_disagreements(row, {"pred": {"doc_type": "contract", "contract_subtype": "license"}}) == []
    sub = ga.sorter_disagreements(row, {"pred": {"doc_type": "contract", "contract_subtype": "supply"}})
    assert [(d["field"], d["v0_value"], d["gold_value"]) for d in sub] == [("subclass", "supply", "License_Agreements")]
    letter = {"id": "y", "expected_doc_class": "correspondence", "expected_subclass": "memo"}
    assert ga.sorter_disagreements(letter, {"pred": {"doc_type": "correspondence", "doc_subclass": "Memo"}}) == []
    missing = ga.sorter_disagreements(letter, {"pred": {"doc_type": "correspondence"}})
    assert missing[0]["field"] == "subclass" and missing[0]["v0_value"] == ""


def test_sorter_run_skips_failed_items(env):
    rows = [_letter("DOC-d1"), _letter("DOC-d2"), _letter("DOC-p1")]
    run = _write_run(env["tmp"], "s", rows,
                     {"DOC-d1": {"doc_type": "insurance_claim"}, "DOC-d2": {"doc_type": "correspondence"}},
                     **{"DOC-d2": {"error": "boom"}})
    res = _build(env, run, "sorter")
    assert res.digest["failed_or_missing"] == 2  # DOC-d2 errored, DOC-p1 has no item
    assert [(r["doc_id"], r["field"], r["set"]) for r in res.rows] == [("DOC-d1", "doc_class", "dev")]


# --- specialists --------------------------------------------------------------------------------

def test_specialist_flags_only_iterate_fields_that_disagree(env):
    rows = [_letter("DOC-d1"), _letter("DOC-p1")]
    preds = {"DOC-d1": {"sender": "Andrew Fastow", "recipient": "Ken Lay", "urgency": "low", "keywords": ["x"]},
             "DOC-p1": {"sender": "Jeff Skilling", "recipient": "Ken Lay", "urgency": "high", "keywords": ["pipeline"]}}
    res = _build(env, _write_run(env["tmp"], "c", rows, preds), "correspondence", per_doc=0)
    # urgency is not an iterate field; keywords is templated (left out as the gate leaves it out)
    assert [(r["doc_id"], r["field"]) for r in res.rows] == [("DOC-d1", "sender")]
    row = res.rows[0]
    assert (row["v0_value"], row["gold_value"], row["label_source"]) == ("Andrew Fastow", "Jeff Skilling", "interim")
    assert row["verdict"] == "" and row["note"] == "" and float(row["field_score"]) < 1.0
    assert res.digest["documents_with_disagreement"] == 1


def test_subclass_verdict_level_reads_the_subclass_entry():
    assert ga.iterate_fields(SCHEMAS, "correspondence") == {"sender", "recipient", "keywords"}
    assert ga.iterate_fields(SCHEMAS, "correspondence", "email", "subclass") == {"recipient"}
    # no subclass entry: the class verdicts apply
    assert ga.iterate_fields(SCHEMAS, "correspondence", "memo", "subclass") == {"sender", "recipient", "keywords"}
    with pytest.raises(ga.AuditError, match="no class"):
        ga.iterate_fields(SCHEMAS, "nope")


def test_subclass_derived_fields_are_never_sampled():
    row = {"id": "i", "expected_doc_class": "insurance_claim", "expected_subclass": "property",
           "doc_text": "Claim CLM-1", "expected_fields": {"claim_number": "CLM-1", "cms_source_table": "carrier"}}
    out = ga.specialist_disagreements(row, {"pred": {"claim_number": "CLM-9", "cms_source_table": "inpatient"}},
                                      frozenset({"claim_number", "cms_source_table"}))
    assert [d["field"] for d in out] == ["claim_number"]
    assert out[0]["label_source"] == "hub"


def test_maud_questions_that_disagree():
    labels = {"Type of Consideration": {"answer": "All Cash"},
              "Accuracy of Target \"General\" R&W: Bringdown Timing Answer": {"answer": "At Closing Only"}}
    row = {"id": "m", "expected_doc_class": "merger_agreement", "expected_subclass": "all_cash",
           "expected_fields": {"maud_clause_labels": json.dumps(labels)}}
    pred = {"maud_clauses": ["Type of Consideration: All Cash"]}
    out = ga.specialist_disagreements(row, {"pred": pred}, frozenset({"maud_clauses"}))
    assert [d["field"] for d in out] == ["maud_clauses:Accuracy of Target \"General\" R&W: Bringdown Timing Answer"]
    assert out[0]["v0_value"] == "" and out[0]["gold_value"] == "At Closing Only"


def test_cuad_categories_missed_and_false_match_the_dojo_counts():
    labels = {"Governing Law": [{"text": "laws of the State of Delaware"}], "Non-Compete": [],
              "Exclusivity": [{"text": "exclusive distributor"}]}
    row = {"id": "k", "expected_doc_class": "contract", "expected_subclass": "Distributor",
           "expected_fields": {"cuad_clause_labels": json.dumps(labels)}}
    pred = {"cuad_clauses": ["Non-Compete: shall not compete"], "governing_law": "Delaware", "cuad_family": "x"}
    out = ga.specialist_disagreements(row, {"pred": pred}, frozenset({"cuad_clauses", "cuad_family"}))
    got = {(d["field"], d["v0_value"]) for d in out}
    assert got == {("cuad_clauses:Exclusivity", ""), ("cuad_clauses:Non-Compete", "predicted")}


# --- sampling -----------------------------------------------------------------------------------

def test_sample_is_deterministic_and_caps_rows_per_document():
    cands = [{"doc_id": f"D{i}", "field": f"f{j}"} for i in range(30) for j in range(3)]
    a = ga.sample(cands, n=10, seed=3)
    assert a == ga.sample(list(reversed(cands)), n=10, seed=3)
    assert len(a) == 10 and len({c["doc_id"] for c in a}) == 10
    assert a != ga.sample(cands, n=10, seed=4)
    uncapped = ga.sample(cands, n=90, seed=3, per_doc=0)
    assert len(uncapped) == 90


# --- summary and gate ---------------------------------------------------------------------------

def _sheet(path: Path, verdicts: list[tuple[str, str]], *, meta: bool = True, run_docs: int | None = None) -> Path:
    """A filled sheet plus the builder's meta digest (as if the builder sampled exactly these rows)."""
    rows = [{"doc_id": d, "field": f"f{i}", "label_source": "hub", "verdict": v} for i, (d, v) in enumerate(verdicts)]
    ga.write_sheet(rows, path)
    if meta:
        docs = len({d for d, _ in verdicts})
        path.with_suffix(".meta.json").write_text(json.dumps({
            "sampled": len(rows), "sampled_rows_sha256": ga.rows_digest(rows),
            "documents_with_disagreement": run_docs if run_docs is not None else docs}), encoding="utf-8")
    return path


def test_summary_refuses_a_sheet_too_small_trimmed_or_without_its_digest(tmp_path):
    """A one-row sheet, a hand-trimmed sheet or a sheet with no builder digest never passes R03."""
    tiny = ga.summarize(_sheet(tmp_path / "t.csv", [("D1", "model_wrong")], run_docs=250))
    assert tiny["gate"] == "too_small" and "1 audited documents < 100 required" in tiny["size_problems"][0]
    assert ga.summarize(_sheet(tmp_path / "n.csv", [("D1", "model_wrong")], meta=False))["gate"] == "too_small"
    full = _sheet(tmp_path / "f.csv", [(f"D{i}", "model_wrong") for i in range(100)])
    with full.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ga.write_sheet(rows[:99], full)  # trimmed after building
    out = ga.summarize(full)
    assert out["gate"] == "too_small" and any("differ from the builder" in p for p in out["size_problems"])
    small_run = ga.summarize(_sheet(tmp_path / "s.csv", [(f"D{i}", "model_wrong") for i in range(12)], run_docs=12))
    assert small_run["gate"] == "pass"  # a run with only 12 disagreeing documents audits all 12


def test_clopper_pearson_interval_matches_the_beta_quantiles():
    from scipy.stats import beta

    lo, hi = ga.clopper_pearson_interval(7, 100)
    assert lo == pytest.approx(beta.ppf(0.025, 7, 94), abs=1e-9)
    assert hi == pytest.approx(beta.ppf(0.975, 8, 93), abs=1e-9)
    assert ga.clopper_pearson_interval(0, 50)[0] == 0.0
    assert ga.clopper_pearson_interval(50, 50)[1] == 1.0
    with pytest.raises(ga.AuditError):
        ga.clopper_pearson_interval(0, 0)


def test_summary_gate_pass_fail_and_per_document_rate(tmp_path):
    passing = _sheet(tmp_path / "p.csv", [(f"D{i}", "gold_wrong" if i < 15 else "model_wrong") for i in range(100)])
    out = ga.summarize(passing)
    assert out["gate"] == "pass" and out["per_document"]["rate"] == 0.15
    assert out["upper_bound_within_threshold"] is False  # the point rate gates; the bound is reported
    failing = _sheet(tmp_path / "f.csv", [(f"D{i}", "gold_wrong" if i < 16 else "ambiguous") for i in range(100)])
    assert ga.summarize(failing)["gate"] == "fail"
    # one document with two rows counts once, gold-wrong if either row is
    doc = ga.summarize(_sheet(tmp_path / "d.csv", [("D1", "gold_wrong"), ("D1", "model_wrong"), ("D2", "model_wrong")]))
    assert doc["per_document"]["gold_wrong"] == 1 and doc["per_document"]["n"] == 2
    assert doc["per_row"]["n"] == 3 and doc["verdicts"] == {"model_wrong": 2, "gold_wrong": 1, "ambiguous": 0}


def test_summary_incomplete_and_bad_verdicts(tmp_path):
    out = ga.summarize(_sheet(tmp_path / "i.csv", [("D1", "gold_wrong"), ("D2", "")]))
    assert out["gate"] == "incomplete" and out["blank"] == 1
    assert ga.summarize(_sheet(tmp_path / "e.csv", [("D1", "")]))["gate"] == "incomplete"
    with pytest.raises(ga.AuditError, match="unknown verdicts"):
        ga.summarize(_sheet(tmp_path / "b.csv", [("D1", "label_wrong")]))
    (tmp_path / "cols.csv").write_text("doc_id,verdict\nD1,gold_wrong\n", encoding="utf-8")
    with pytest.raises(ga.AuditError, match="missing columns"):
        ga.summarize(tmp_path / "cols.csv")


# --- CLI ----------------------------------------------------------------------------------------

def test_cli_builds_refuses_overwrite_and_summarizes(env, capsys):
    run = _write_run(env["tmp"], "cli", [_letter("DOC-d1")], {"DOC-d1": {"sender": "Andrew Fastow", "recipient": "Ken Lay"}})
    out = env["tmp"] / "sheet.csv"
    args = ["--run", str(run), "--lineage", "correspondence", "--seed", "1", "--out", str(out),
            "--split", str(env["split"]), "--schemas", str(env["schemas"])]
    assert cli.main(args) == 0
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == ga.COLUMNS and rows[0]["field"] == "sender"
    meta = json.loads(out.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["sampled"] == 1 and meta["seed"] == 1
    assert cli.main(args) == 2  # never overwrite adjudication work silently
    assert "exists" in capsys.readouterr().err
    assert cli.main(["--summarize", str(out)]) == 3  # blank verdict
    rows[0]["verdict"] = "model_wrong"
    ga.write_sheet(rows, out)
    assert cli.main(["--summarize", str(out)]) == 0
    bad = _write_run(env["tmp"], "cli-bad", [_letter("DOC-h1")], {"DOC-h1": {}})
    assert cli.main(["--run", str(bad), "--lineage", "correspondence", "--seed", "1", "--out", str(env["tmp"] / "x.csv"),
                     "--split", str(env["split"]), "--schemas", str(env["schemas"])]) == 2
    assert not (env["tmp"] / "x.csv").exists()


# --- registry revision --------------------------------------------------------------------------

@pytest.mark.parametrize("level", ["class", "subclass"])
def test_a_registry_graded_on_another_revision_is_refused(env, level):
    """Both verdict levels read the registry, so the opt-in subclass level is guarded too."""
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION, LEGACY_FAMILY_HF_REVISIONS

    v91_tag, v91_data = LEGACY_FAMILY_HF_REVISIONS["v9.1"]
    rows = [{**_letter("DOC-d1"), "source_revision": v91_data}]   # the parquet parent maps to its tag
    # recipient is iterate at both levels (email sender is thin at subclass level)
    run = _write_run(env["tmp"], "rev", rows, {"DOC-d1": {"sender": "Jeff Skilling", "recipient": "Andrew Fastow"}})
    env["schemas"].write_text(json.dumps({**SCHEMAS, "inputs": {"dataset_revision": v91_tag}}), encoding="utf-8")
    assert _build(env, run, "correspondence", verdict_level=level).digest["sampled"] == 1
    env["schemas"].write_text(json.dumps({**SCHEMAS, "inputs": {"dataset_revision": FAMILY_HF_REVISION}}),
                              encoding="utf-8")
    with pytest.raises(ga.AuditError, match="grades dataset revision"):
        _build(env, run, "correspondence", verdict_level=level)


def test_the_frozen_runbook_v1_registry_matches_its_split():
    from mailroom_sandbox import subclass_schemas as ss
    from mailroom_sandbox.paths import repo_root

    root = repo_root()
    reg = json.loads((root / "config/extraction/subclass_schemas-runbook-v1.json").read_text(encoding="utf-8"))
    split = root / "config/splits/runbook-v1"
    manifest = json.loads((split / "manifest.json").read_text(encoding="utf-8"))
    assert reg["schema"] == ss.SCHEMA and reg["problems"] == []
    assert reg["inputs"]["dataset_revision"] == manifest["dataset"]["revision"]
    assert reg["inputs"]["split_assignments_sha256"] == ss._read_sets(split)[1]


@pytest.mark.parametrize("split_name, registry", [("runbook-v1", "subclass_schemas-runbook-v1.json"),
                                                  ("runbook-v2", "subclass_schemas.json")])
def test_a_run_gets_the_split_and_registry_of_its_revision(tmp_path, split_name, registry):
    """Default --split / --schemas: v9.1 runs audit against runbook-v1 and its registry, v9.3 runs
    against runbook-v2 and the current one, from the lock's exclude file or the rows' revision."""
    from mailroom_sandbox.paths import repo_root

    root = repo_root()
    rev = json.loads((root / "config/splits" / split_name / "manifest.json").read_text())["dataset"]["revision"]
    run = tmp_path / "run"
    run.mkdir()
    rows = [{"id": "DOC-1", "source_revision": rev}]
    assert ga.resolve_inputs(run, rows) == (root / "config/splits" / split_name, root / "config/extraction" / registry)
    (run / "spec.lock.json").write_text(json.dumps({"dataset": {
        "exclude_ids_file": f"config/splits/{split_name}/dev.exclude.ids"}}))
    assert ga.resolve_inputs(run, [{"id": "DOC-1"}])[0] == root / "config/splits" / split_name
    assert ga.resolve_inputs(run, rows, schemas_path=tmp_path / "x.json")[1] == tmp_path / "x.json"


def test_a_run_on_an_unknown_revision_names_the_missing_registry(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(ga.AuditError, match="committed splits are drawn on revision"):
        ga.resolve_inputs(run, [{"id": "DOC-1", "source_revision": "c" * 40}])
    with pytest.raises(ga.AuditError, match="several revisions"):
        ga.resolve_inputs(run, [{"source_revision": "c" * 40}, {"source_revision": "d" * 40}])
    from mailroom_sandbox.paths import repo_root

    v2 = repo_root() / "config/splits/runbook-v2"
    with pytest.raises(ga.AuditError, match="0 committed field registries"):
        ga.resolve_inputs(run, [{"source_revision": "c" * 40}], split_dir=v2)


def test_a_registry_built_from_a_tag_name_matches_the_run_that_drew_its_commit():
    from mailroom_sandbox.job.spec import FAMILY_HF_DATA_REVISION, FAMILY_HF_REVISION, FAMILY_HF_TAG

    rows = [{"source_revision": FAMILY_HF_DATA_REVISION}]
    ga.check_schemas_revision(rows, {"inputs": {"dataset_revision": FAMILY_HF_TAG}}, Path("r.json"))
    ga.check_schemas_revision([{"source_revision": "bc9eab280044befb51e19dda3071d290a8677f42"}],
                              {"inputs": {"dataset_revision": "v9.1"}}, Path("r.json"))
    assert ga._tag_commit(FAMILY_HF_TAG) == FAMILY_HF_REVISION
    with pytest.raises(ga.AuditError):
        ga.check_schemas_revision(rows, {"inputs": {"dataset_revision": "v9.1"}}, Path("r.json"))
