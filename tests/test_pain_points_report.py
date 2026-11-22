"""``sandbox pain-points``: per-document composites and per-experiment breakdowns of finished runs.

Every run here is a hand-built runtime directory (spec.lock.json, dataset.jsonl, items.jsonl):
no model call, no network. Extraction truth comes from the golden correspondence case, so the
extraction composite runs through the real scorer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailroom_sandbox import cli, pain_points_report as ppr

INPUTS = Path(__file__).parent / "fixtures" / "scoring_golden" / "inputs.json"


@pytest.fixture(scope="module")
def case() -> dict:
    return next(c for c in json.loads(INPUTS.read_text())["cases"] if c["doc_type"] == "correspondence")


def _row(doc_id: str, case: dict, *, stage: str = "archived", fields: bool = True) -> dict:
    row = {"id": doc_id, "expected_doc_class": "correspondence", "expected_stage": stage, "doc_text": "x"}
    if fields:
        row["expected_fields"] = json.dumps(case["expected"])
    return row


def _item(doc_id: str, *, stage: str = "archived", doc_type: str = "correspondence", data: dict | None = None,
          ok: bool = True, error: str | None = None) -> dict:
    pred = {"stage": stage, "doc_type": doc_type, "extracted_data": data or {}}
    return {"item_id": doc_id, "ok": ok, "error": error, "pred": pred}


def _run(root: Path, run_id: str, rows: list[dict], items: list[dict], *, task: str = "pipeline",
         model: str = "m/one", mock: bool = False) -> Path:
    path = root / run_id
    path.mkdir(parents=True)
    lock = {"run_id": run_id, "task": task, "profile": "modal", "engine": {"model": model},
            "prompt": {"default": {"name": "deploy_v1", "version": "3"}}, "job": {"mock": mock}}
    (path / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    lock["dataset"] = {"sha256": hashlib.sha256((path / "dataset.jsonl").read_bytes()).hexdigest(), "rows": len(rows)}
    (path / "spec.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (path / "checkpoint.json").write_text(json.dumps({"run_id": run_id, "state": "done"}), encoding="utf-8")
    (path / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return path


@pytest.fixture()
def two_runs(tmp_path, case):
    exp = case["expected"]
    invented = {k: "zzqq entirely invented value" for k in exp}
    rows = [_row("d1", case), _row("d2", case), _row("d3", case, stage="review"), _row("d4", case, fields=False)]
    base = _run(tmp_path, "run-a", rows, [
        _item("d1", data=exp),                       # correct and complete: 0 / 0
        _item("d2", stage="review", data=exp),       # needless review: 4 / 4
        _item("d3", stage="review"),                 # needed review: 0 / 0
        _item("d4", doc_type="contract"),            # wrong class, no field truth: 3 / excluded
    ])
    cand = _run(tmp_path, "run-b", rows, [
        _item("d1", data=invented),                  # fabricated: 0 / 3
        _item("d2", data=exp),                       # fixed: 0 / 0
        _item("d3", stage="review"),                 # 0 / 0
        _item("d4", ok=False, error="timeout"),      # pipeline failure: 4 / excluded
    ], model="m/two")
    return base, cand


def test_every_document_is_scored(two_runs):
    base, _ = two_runs
    docs, meta = ppr.documents_for_run(base, label="A")
    rep = ppr.report([(str(base), "A")])
    by_id = {d["doc_id"]: d for d in rep["documents"]}
    assert meta["documents"] == 4 and meta["missing_truth"] == []
    assert by_id["d1"]["classification"]["reason"] == "correct" and by_id["d1"]["extraction"]["reason"] == "complete"
    assert by_id["d2"]["classification"]["reason"] == "unnecessary_review"
    assert by_id["d2"]["extraction"]["points"] == 4
    assert by_id["d3"]["classification"]["reason"] == "necessary_review"
    assert by_id["d4"]["classification"]["reason"] == "wrong_doc_type" and by_id["d4"]["extraction"] is None
    assert rep["per_run"]["A"]["classification"]["points"] == 7.0


def test_breakdown_per_experiment_and_paired_comparison(two_runs):
    base, cand = two_runs
    rep = ppr.report([(str(base), "A"), (str(cand), "B")], by=("experiment",), baseline="A", n_boot=200)
    groups = {g["key"]["experiment"]: g for g in rep["breakdown"]["groups"]}
    assert groups["A"]["classification"]["mean"] == pytest.approx(7 / 4)
    assert groups["B"]["classification"]["mean"] == pytest.approx(4 / 4)
    assert groups["B"]["extraction"]["reasons"]["fabricated"] == 1
    assert groups["A"]["classification"]["ci"] is not None
    (cls,) = rep["compare"]["classification"]
    assert cls["candidate"] == "B" and cls["n_paired"] == 4
    assert cls["delta"] == pytest.approx(1.0 - 1.75)  # negative: B earns fewer penalty points
    (ext,) = rep["compare"]["extraction"]
    assert ext["n_paired"] == 3  # d4 has no field truth in either run


def test_breakdown_by_class_and_model(two_runs):
    base, cand = two_runs
    rep = ppr.report([(str(base), "A"), (str(cand), "B")], by=("model", "doc_class"), n_boot=50)
    keys = [g["key"] for g in rep["breakdown"]["groups"]]
    assert {"model": "m/one", "doc_class": "correspondence"} in keys
    assert {"model": "m/two", "doc_class": "correspondence"} in keys


def test_render_names_the_scorer_and_the_tables(two_runs):
    base, cand = two_runs
    text = ppr.render(ppr.report([(str(base), "A"), (str(cand), "B")], baseline="A", n_boot=50))
    assert "## Classification" in text and "## Extraction" in text
    assert "Paired comparison with `A`" in text and "amfam-v1" in text


def test_mock_runs_are_labelled_simulated(tmp_path, case):
    path = _run(tmp_path, "mock-run", [_row("d1", case)], [_item("d1", data=case["expected"])], mock=True)
    rep = ppr.report([(str(path), None)])
    assert rep["simulated"] == ["mock-run"]
    assert "never model evidence" in ppr.render(rep)


def test_non_pipeline_runs_are_refused(tmp_path, case):
    path = _run(tmp_path, "sorter-run", [_row("d1", case)], [_item("d1")], task="sorter")
    with pytest.raises(ppr.PainPointsError, match="pipeline runs only"):
        ppr.documents_for_run(path)


def test_documents_missing_from_truth_are_listed_not_scored(tmp_path, case):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1", data=case["expected"]), _item("d9")])
    docs, meta = ppr.documents_for_run(path)
    assert [d.doc_id for d in docs] == ["d1"] and meta["missing_truth"] == ["d9"]


def test_retried_items_keep_the_last_answer(tmp_path, case):
    path = _run(tmp_path, "r", [_row("d1", case)],
                [_item("d1", stage="review"), _item("d1", data=case["expected"])])
    docs, _ = ppr.documents_for_run(path)
    assert len(docs) == 1 and docs[0].stage == "archived"


def test_duplicate_labels_unknown_keys_and_baselines_are_refused(two_runs):
    base, cand = two_runs
    with pytest.raises(ppr.PainPointsError, match="share the experiment label"):
        ppr.report([(str(base), "A"), (str(cand), "A")])
    with pytest.raises(ppr.PainPointsError, match="--by"):
        ppr.report([(str(base), "A")], by=("colour",))
    with pytest.raises(ppr.PainPointsError, match="--baseline"):
        ppr.report([(str(base), "A")], baseline="Z")


def test_truth_loader_serves_bundles_without_a_dataset_file(tmp_path, case):
    path = _run(tmp_path, "bundle", [_row("d1", case)], [_item("d1", data=case["expected"])])
    (path / "dataset.jsonl").unlink()
    calls = []

    def loader(spec, order):
        calls.append(list(order))
        return [_row("d1", case)], {}

    docs, _ = ppr.documents_for_run(path, truth_loader=loader)
    assert calls == [["d1"]] and docs[0].doc_id == "d1"


def test_parse_run_args():
    assert ppr.parse_run_args(["base=run-a", "run-b"]) == [("run-a", "base"), ("run-b", None)]


def test_cli_prints_markdown_and_writes_documents(two_runs, tmp_path, capsys):
    base, cand = two_runs
    docs_out = tmp_path / "docs.jsonl"
    args = cli.build_parser().parse_args(["pain-points", f"A={base}", f"B={cand}", "--baseline", "A",
                                          "--by", "experiment,doc_class", "--n-boot", "50",
                                          "--documents", str(docs_out)])
    assert args.handler(args) == 0
    assert "Paired comparison" in capsys.readouterr().out
    lines = docs_out.read_text().splitlines()
    assert len(lines) == 8 and json.loads(lines[0])["groups"]["experiment"] == "A"


def test_cli_reports_errors_with_exit_2(tmp_path, capsys):
    args = cli.build_parser().parse_args(["pain-points", str(tmp_path / "nope")])
    assert args.handler(args) == 2
    assert "sandbox pain-points:" in capsys.readouterr().err


def test_line_separators_inside_json_strings_survive(tmp_path, case):
    """Regression (CodeRabbit on #393): U+2028 / U+2029 inside a JSON string are not line breaks."""
    row = {**_row("d1", case), "doc_text": "clause one clause two end"}
    path = tmp_path / "r"
    path.mkdir()
    lock = {"run_id": "r", "task": "pipeline", "engine": {"model": "m"}, "job": {"mock": False}}
    (path / "spec.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (path / "dataset.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    lock["dataset"] = {"sha256": hashlib.sha256((path / "dataset.jsonl").read_bytes()).hexdigest()}
    (path / "spec.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    item = _item("d1", data=case["expected"])
    item["pred"]["note"] = "a b"
    (path / "items.jsonl").write_text(json.dumps(item, ensure_ascii=False) + "\n", encoding="utf-8")
    docs, _ = ppr.documents_for_run(path)
    assert [d.doc_id for d in docs] == ["d1"]


def test_experiment_labels_are_normalised_before_the_uniqueness_check(two_runs):
    """Regression (CodeRabbit on #393): ``A`` and `` A `` are one label; a blank label is refused."""
    base, cand = two_runs
    with pytest.raises(ppr.PainPointsError, match="share the experiment label"):
        ppr.report([(str(base), "A"), (str(cand), " A ")])
    with pytest.raises(ppr.PainPointsError, match="blank"):
        ppr.report([(str(base), "  ")])
    rep = ppr.report([(str(base), " A "), (str(cand), "B")], baseline=" A ", n_boot=50)
    assert rep["compare"]["baseline"] == "A" and [p["label"] for p in rep["runs"]] == ["A", "B"]


@pytest.mark.parametrize("mutation", ["changed", "missing_hash", "duplicate_id"])
def test_locked_truth_integrity_is_required(tmp_path, case, mutation):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    lock = json.loads((path / "spec.lock.json").read_text())
    if mutation == "missing_hash":
        lock["dataset"].pop("sha256")
    elif mutation == "changed":
        (path / "dataset.jsonl").write_text(json.dumps(_row("changed", case)) + "\n")
    else:
        with (path / "dataset.jsonl").open("a") as handle:
            handle.write(json.dumps(_row("d1", case)) + "\n")
        lock["dataset"]["sha256"] = hashlib.sha256((path / "dataset.jsonl").read_bytes()).hexdigest()
    (path / "spec.lock.json").write_text(json.dumps(lock))
    with pytest.raises(ppr.PainPointsError, match="sha256|duplicate"):
        ppr.documents_for_run(path)


@pytest.mark.parametrize("state", ["prepared", "running", "paused", "unknown", None])
def test_unfinished_runs_are_refused(tmp_path, case, state):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    (path / "checkpoint.json").write_text(json.dumps({"run_id": "r", "state": state}))
    with pytest.raises(ppr.PainPointsError, match="finished pipeline run"):
        ppr.documents_for_run(path)


def test_foreign_checkpoint_is_refused(tmp_path, case):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    (path / "checkpoint.json").write_text(json.dumps({"run_id": "other", "state": "done"}))
    with pytest.raises(ppr.PainPointsError, match="locked generation"):
        ppr.documents_for_run(path)


def test_bundle_without_checkpoint_is_explicitly_unverified(tmp_path, case):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    (path / "checkpoint.json").unlink()
    rep = ppr.report([(str(path), None)], n_boot=10)
    assert rep["runs"][0]["state"] == "unverified (no checkpoint)"
    assert "unverified (no checkpoint)" in ppr.render(rep)
    assert rep["runs"][0]["truth"]["sha256"]


def test_explicit_truth_override_keeps_its_own_provenance(tmp_path, case):
    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    (path / "dataset.jsonl").write_text("changed original dataset")
    override = tmp_path / "new-truth.jsonl"
    override.write_text(json.dumps(_row("d1", case)) + "\n")
    rep = ppr.report([(str(path), None)], dataset_file=override, n_boot=10)
    assert rep["runs"][0]["truth"]["sha256"] == hashlib.sha256(override.read_bytes()).hexdigest()


@pytest.mark.parametrize("source", ["explicit_file", "locked_revision"])
def test_reconstructed_truth_refuses_duplicate_source_ids(tmp_path, case, monkeypatch, source):
    from mailroom_sandbox import corpus
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1")])
    rows = [_row("d1", case), _row("d1", case, stage="review")]
    kwargs = {}
    if source == "explicit_file":
        override = tmp_path / "new-truth.jsonl"
        override.write_text("".join(json.dumps(row) + "\n" for row in rows))
        kwargs["dataset_file"] = override
    else:
        (path / "dataset.jsonl").unlink()
        lock_file = path / "spec.lock.json"
        lock = json.loads(lock_file.read_text())
        lock["dataset"]["revision"] = FAMILY_HF_REVISION
        lock_file.write_text(json.dumps(lock))

        def load_pinned(spec):
            assert spec.revision == FAMILY_HF_REVISION
            return rows

        monkeypatch.setattr(corpus, "load_hf_rows", load_pinned)
    with pytest.raises(ValueError, match="duplicate document id"):
        ppr.documents_for_run(path, **kwargs)


def test_rescore_output_and_legacy_source_checkpoints_are_reportable(tmp_path, case):
    from mailroom_sandbox import rescore

    path = _run(tmp_path, "r", [_row("d1", case)], [_item("d1", data=case["expected"])])
    replacement = tmp_path / "truth.jsonl"
    replacement.write_text(json.dumps(_row("d1", case)) + "\n")
    result = rescore.rescore(path, dataset_file=replacement, out=tmp_path / "derived")
    derived = Path(result["out"])
    checkpoint = json.loads((derived / "checkpoint.json").read_text())
    assert checkpoint["run_id"] == "derived"
    assert checkpoint["source_checkpoint"]["run_id"] == "r"
    assert ppr.documents_for_run(derived)[1]["state"] == "done"
    second = rescore.rescore(derived, dataset_file=replacement, out=tmp_path / "second")
    assert ppr.documents_for_run(second["out"])[1]["state"] == "done"
    # Previously written rescore bundles carry the source checkpoint unchanged.
    (derived / "checkpoint.json").write_bytes((path / "checkpoint.json").read_bytes())
    assert ppr.documents_for_run(derived)[1]["state"] == "done"
    (derived / "checkpoint.json").write_text(json.dumps({"run_id": "foreign", "state": "done"}))
    with pytest.raises(ppr.PainPointsError, match="locked generation"):
        ppr.documents_for_run(derived)


@pytest.fixture
def legacy_rescore_chain(tmp_path, case):
    from mailroom_sandbox import rescore

    original = _run(tmp_path, "original", [_row("d1", case)], [_item("d1", data=case["expected"])])
    lock = json.loads((original / "spec.lock.json").read_text())
    lock.update(spec_hash="source-spec", generation_id="source-generation")
    (original / "spec.lock.json").write_text(json.dumps(lock))
    checkpoint = {"run_id": "original", "spec_hash": "source-spec", "generation_id": "source-generation",
                  "state": "done"}
    (original / "checkpoint.json").write_text(json.dumps(checkpoint))
    truth = original / "dataset.jsonl"
    middle = Path(rescore.rescore(original, dataset_file=truth, out=tmp_path / "middle")["out"])
    final = Path(rescore.rescore(middle, dataset_file=truth, out=tmp_path / "elsewhere" / "final")["out"])
    for path in (middle, final):
        # Reproduce the pre-fix producer: every generation copied the original checkpoint verbatim.
        (path / "checkpoint.json").write_text(json.dumps(checkpoint))
    return original, middle, final


def test_multistep_legacy_rescore_follows_verified_recorded_source_paths(legacy_rescore_chain):
    _, _, final = legacy_rescore_chain
    docs, meta = ppr.documents_for_run(final)
    assert [d.doc_id for d in docs] == ["d1"] and meta["state"] == "done"


@pytest.mark.parametrize("problem", ["foreign_checkpoint", "foreign_ancestor", "missing_ancestor", "cycle"])
def test_multistep_legacy_rescore_refuses_unverified_ancestry(legacy_rescore_chain, problem):
    _, middle, final = legacy_rescore_chain
    expected = "locked generation"
    if problem == "foreign_checkpoint":
        path = final / "checkpoint.json"
        checkpoint = json.loads(path.read_text())
        checkpoint["run_id"] = "unrelated-run"
        path.write_text(json.dumps(checkpoint))
    elif problem == "foreign_ancestor":
        path = middle / "spec.lock.json"
        lock = json.loads(path.read_text())
        lock["spec_hash"] = "another-spec"
        path.write_text(json.dumps(lock))
    elif problem == "missing_ancestor":
        (middle / "spec.lock.json").unlink()
        expected = "cannot verify legacy rescore ancestry"
    else:
        path = middle / "spec.lock.json"
        lock = json.loads(path.read_text())
        lock["rescore"]["source_run"] = "final"
        path.write_text(json.dumps(lock))
        report = middle / "rescore.json"
        data = json.loads(report.read_text())
        data.update(source_run="final", source_path=str(final))
        report.write_text(json.dumps(data))
        expected = "cyclic or excessive"
    with pytest.raises(ppr.PainPointsError, match=expected):
        ppr.documents_for_run(final)
