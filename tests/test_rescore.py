"""``sandbox rescore``: re-score a finished run's stored answers against other truth (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailroom_sandbox import rescore as rs


def _row(doc_id: str, doc_class: str, subclass: str = "") -> dict:
    return {"id": doc_id, "doc_text": f"text of {doc_id}", "expected_doc_class": doc_class,
            "expected_subclass": subclass, "expected_fields": {}, "source_revision": "rev-a"}


def _run(tmp_path: Path, *, task: str = "isolated", truth: list[dict] | None = None,
         items: list[dict] | None = None, name: str = "run-a", state: str = "done") -> Path:
    run = tmp_path / "runs" / name
    run.mkdir(parents=True)
    truth = truth if truth is not None else [_row("DOC-1", "contract"), _row("DOC-2", "correspondence")]
    items = items if items is not None else [
        {"item_id": "DOC-1", "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 1.0}},
        {"item_id": "DOC-2", "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 0.0}},
    ]
    lock = {"run_id": name, "task": task, "lock_kind": "spec.lock", "spec_hash": "h1",
            "job": {"task": "sorter" if task == "isolated" else task},
            "spec_core": {"task": task, "dataset": {"repo": "o/r", "config": "ground_truth",
                                                    "revision": "rev-a", "interim_labels": None,
                                                    "near_gold_labels": None}},
            "dataset": {"repo": "o/r", "revision": "rev-a", "revision_resolved": "rev-a", "rows": len(truth),
                        "sha256": "old", "metadata": {"source": "huggingface"}},
            "scoring_hotfixes": {"fixes": [{"id": "SHF-007"}]}}
    (run / "spec.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (run / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in truth), encoding="utf-8")
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    (run / "checkpoint.json").write_text(json.dumps({"state": state}), encoding="utf-8")
    (run / "events.jsonl").write_text(json.dumps({"event": "start", "ts": "2026-11-19T00:00:00Z"}) + "\n",
                                      encoding="utf-8")
    return run


def _truth_file(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "truth.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_a_moved_label_rescores_the_stored_answer_into_a_derived_run(tmp_path):
    run = _run(tmp_path)
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    # The new truth says DOC-2 is a contract: the stored answer "contract" is now right.
    truth = _truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")])
    report = rs.rescore(run, dataset_file=truth, out=tmp_path / "out")

    out = Path(report["out"])
    assert {p.name: p.read_bytes() for p in run.iterdir()} == before  # the source is never written
    items = [json.loads(line) for line in (out / "items.jsonl").read_text().splitlines()]
    assert [i["score"]["match"] for i in items] == [1.0, 1.0]
    assert [i["score_original"]["match"] for i in items] == [1.0, 0.0]
    assert all(i["rescored"] for i in items)
    m = report["digest"]["metrics"]["match"]
    assert (m["before"], m["after"], m["paired_delta"], m["changed"]) == (0.5, 1.0, 0.5, 1)
    assert report["digest"]["truth_changes"]["label_moves"] == {"class correspondence -> contract": 1}

    lock = json.loads((out / "spec.lock.json").read_text())
    assert lock["lock_kind"] == "rescore.lock" and lock["run_id"] == "out"
    assert lock["rescore"]["source_run"] == "run-a" and lock["rescore"]["source_dataset"]["sha256"] == "old"
    assert lock["dataset"]["rows"] == 2 and lock["dataset"]["sha256"] != "old"
    assert [json.loads(line)["id"] for line in (out / "dataset.jsonl").read_text().splitlines()] == ["DOC-1", "DOC-2"]
    assert (out / "events.jsonl").is_file() and (out / "rescore.json").is_file()


def test_a_rescore_of_a_rescore_keeps_the_first_score(tmp_path):
    run = _run(tmp_path)
    first = rs.rescore(run, dataset_file=_truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")]),
                       out=tmp_path / "one")
    second = rs.rescore(first["out"], dataset_file=tmp_path / "truth.jsonl", out=tmp_path / "two")
    items = [json.loads(line) for line in (Path(second["out"]) / "items.jsonl").read_text().splitlines()]
    assert [i["score_original"]["match"] for i in items] == [1.0, 0.0]


def test_errored_items_are_carried_not_scored(tmp_path):
    run = _run(tmp_path, items=[
        {"item_id": "DOC-1", "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 1.0}},
        {"item_id": "DOC-2", "ok": False, "error": "timeout", "pred": None, "score": None},
    ])
    report = rs.rescore(run, dataset_file=_truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")]),
                        out=tmp_path / "out")
    assert (report["digest"]["rescored"], report["digest"]["carried"]) == (1, 1)
    errored = json.loads((Path(report["out"]) / "items.jsonl").read_text().splitlines()[1])
    assert errored["score"] is None and "score_original" not in errored and "rescored" not in errored


def test_a_document_the_new_truth_lacks_stops_the_rescore_unless_allowed(tmp_path):
    run = _run(tmp_path)
    truth = _truth_file(tmp_path, [_row("DOC-1", "contract")])
    with pytest.raises(rs.RescoreError, match="1 of 2 documents are not in the new truth"):
        rs.rescore(run, dataset_file=truth, out=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    report = rs.rescore(run, dataset_file=truth, out=tmp_path / "out", allow_missing=True)
    assert report["missing"] == ["DOC-2"]
    assert [json.loads(line)["item_id"] for line in (Path(report["out"]) / "items.jsonl").read_text().splitlines()] == ["DOC-1"]


def test_dry_run_writes_nothing_and_existing_out_needs_force(tmp_path):
    run = _run(tmp_path)
    truth = _truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")])
    report = rs.rescore(run, dataset_file=truth, out=tmp_path / "out", dry_run=True)
    assert report["dry_run"] and not (tmp_path / "out").exists()
    rs.rescore(run, dataset_file=truth, out=tmp_path / "out")
    with pytest.raises(rs.RescoreError, match="exists; --force replaces it"):
        rs.rescore(run, dataset_file=truth, out=tmp_path / "out")
    rs.rescore(run, dataset_file=truth, out=tmp_path / "out", force=True)


def test_refusals(tmp_path):
    truth = _truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")])
    run = _run(tmp_path)
    with pytest.raises(rs.RescoreError, match="never rewrites its source"):
        rs.rescore(run, dataset_file=truth, out=run)
    with pytest.raises(rs.RescoreError, match="not both"):
        rs.rescore(run, dataset_file=truth, revision="v9.3", out=tmp_path / "x")
    live = _run(tmp_path, name="live", state="running")
    with pytest.raises(rs.RescoreError, match="'running'"):
        rs.rescore(live, dataset_file=truth, out=tmp_path / "y")
    odd = _run(tmp_path, name="odd", task="local_vs_api")
    with pytest.raises(rs.RescoreError, match="no per-document scorer"):
        rs.rescore(odd, dataset_file=truth, out=tmp_path / "z")
    with pytest.raises(rs.RescoreError, match="no items to re-score in the given ids"):
        rs.rescore(run, dataset_file=truth, ids={"DOC-9"}, out=tmp_path / "w")


def test_revision_reads_the_runs_documents_from_that_revisions_full_corpus(tmp_path):
    run = _run(tmp_path)
    seen = {}

    def loader(spec, ids):
        seen.update(revision=spec.revision, split=spec.split, ids=list(ids))
        return [_row("DOC-1", "contract"), _row("DOC-2", "contract")], {"source": "huggingface",
                                                                         "revision": spec.revision}

    report = rs.rescore(run, revision="v9.3", out=tmp_path / "out", truth_loader=loader)
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    # The tag maps to its commit with no Hub call; documents come from the whole corpus, not a draw.
    assert seen == {"revision": FAMILY_HF_REVISION, "split": "all", "ids": ["DOC-1", "DOC-2"]}
    assert report["digest"]["metrics"]["match"]["after"] == 1.0
    assert rs.render(report).splitlines()[0] == "rescore run-a -> out"


def test_ids_restrict_the_rescore(tmp_path):
    run = _run(tmp_path)
    report = rs.rescore(run, dataset_file=_truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")]),
                        ids={"DOC-2"}, out=tmp_path / "out")
    assert report["ids_restricted"] and report["digest"]["items"] == 1


def test_a_report_bundle_is_read_in_place(tmp_path):
    bundle = tmp_path / "bundle" / "i01"
    for sub in ("logs", "traces"):
        (bundle / sub).mkdir(parents=True)
    run = _run(tmp_path)
    (bundle / "logs" / "r.spec-lock.json").write_bytes((run / "spec.lock.json").read_bytes())
    (bundle / "traces" / "r.items.jsonl").write_bytes((run / "items.jsonl").read_bytes())
    files = rs.locate(bundle)
    assert set(files.files) == {"spec.lock.json", "items.jsonl"}
    report = rs.rescore(bundle, dataset_file=_truth_file(tmp_path, [_row("DOC-1", "contract"),
                                                                   _row("DOC-2", "contract")]),
                        out=tmp_path / "out")
    assert report["digest"]["rescored"] == 2
    with pytest.raises(rs.RescoreError, match="no spec.lock.json"):
        rs.locate(tmp_path / "bundle")


def test_the_derived_run_loads_as_a_sorter_arm_on_the_new_truth(tmp_path):
    from mailroom_sandbox import sorter_arms

    run = _run(tmp_path)
    lock = json.loads((run / "spec.lock.json").read_text())
    lock["agent_assignments"] = {"sorter": {"model": "m"}}
    (run / "spec.lock.json").write_text(json.dumps(lock))

    def loader(spec, ids):
        rows = [{**_row("DOC-1", "contract"), "source_revision": "rev-b"},
                {**_row("DOC-2", "contract"), "source_revision": "rev-b"}]
        return rows, {"source": "huggingface", "revision": "rev-b", "revision_resolved": "rev-b"}

    report = rs.rescore(run, revision="rev-b", out=tmp_path / "out", truth_loader=loader)
    arm = sorter_arms.load_arm(report["out"])
    assert arm.revision == "rev-b" and arm.truth["DOC-2"] == ("contract", None)


def test_the_cli_prints_the_digest(tmp_path, capsys):
    from mailroom_sandbox import cli

    run = _run(tmp_path)
    truth = _truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")])
    assert cli.main(["rescore", str(run), "--dataset-file", str(truth), "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "match" in out and "wrote" in out
    assert cli.main(["rescore", str(run), "--dataset-file", str(truth), "--out", str(tmp_path / "out")]) == 2
    assert "exists" in capsys.readouterr().err


def _repo_split(name: str) -> tuple[Path, str]:
    from mailroom_sandbox.paths import repo_root

    split = repo_root() / "config" / "splits" / name
    return split, json.loads((split / "manifest.json").read_text())["dataset"]["revision"]


def _drawn_from(tmp_path: Path, split: str, **kw) -> Path:
    """A run on ``split``'s revision whose lock names that split's dev exclude file."""
    _, rev = _repo_split(split)
    truth = [{**_row("DOC-1", "contract"), "source_revision": rev},
             {**_row("DOC-2", "correspondence"), "source_revision": rev}]
    run = _run(tmp_path, truth=truth, **kw)
    lock = json.loads((run / "spec.lock.json").read_text())
    lock["dataset"].update(revision=rev, revision_resolved=rev,
                           exclude_ids_file=f"config/splits/{split}/dev.exclude.ids")
    lock["agent_assignments"] = {"sorter": {"model": "m"}}
    (run / "spec.lock.json").write_text(json.dumps(lock))
    return run


def _loader_on(split: str):
    _, rev = _repo_split(split)

    def loader(spec, ids):
        rows = [{**_row("DOC-1", "contract"), "source_revision": rev},
                {**_row("DOC-2", "contract"), "source_revision": rev}]
        return [r for r in rows if r["id"] in set(ids)], {"source": "huggingface", "revision": rev,
                                                          "revision_resolved": rev}
    return loader


def test_a_rescore_to_another_revision_drops_the_old_split_and_the_gold_audit_follows(tmp_path):
    """runbook-v1 (v9.1) and runbook-v2 (v9.3) assign sets differently (a v1 dev document can be
    v2 held-out), so a v9.3 rescore must not keep the v1 split file: the audit then resolves the
    split and registry of the new revision, and its set checks are v2's."""
    from mailroom_sandbox import gold_audit as ga
    from mailroom_sandbox.paths import repo_root

    run = _drawn_from(tmp_path, "runbook-v1")
    moved = rs.rescore(run, revision="v9.3", out=tmp_path / "v93", truth_loader=_loader_on("runbook-v2"))
    lock = json.loads((Path(moved["out"]) / "spec.lock.json").read_text())
    assert "exclude_ids_file" not in lock["dataset"]
    assert lock["rescore"]["source_dataset"]["exclude_ids_file"] == "config/splits/runbook-v1/dev.exclude.ids"
    rows = [json.loads(line) for line in (Path(moved["out"]) / "dataset.jsonl").read_text().splitlines()]
    root = repo_root()
    assert ga.resolve_inputs(Path(moved["out"]), rows) == (root / "config/splits/runbook-v2",
                                                           root / "config/extraction/subclass_schemas.json")

    same = rs.rescore(run, out=tmp_path / "same", truth_loader=_loader_on("runbook-v1"))
    lock = json.loads((Path(same["out"]) / "spec.lock.json").read_text())
    assert lock["dataset"]["exclude_ids_file"] == "config/splits/runbook-v1/dev.exclude.ids"
    rows = [json.loads(line) for line in (Path(same["out"]) / "dataset.jsonl").read_text().splitlines()]
    assert ga.resolve_inputs(Path(same["out"]), rows)[0] == root / "config/splits/runbook-v1"


def test_a_gold_audit_sheet_builds_from_a_rescored_run(tmp_path):
    from mailroom_sandbox import gold_audit as ga

    split, _ = _repo_split("runbook-v2")
    dev = sorted(json.loads(line)["id"] for line in (split / "assignments.jsonl").read_text().splitlines()
                 if json.loads(line)["set"] == "dev")[:2]
    rev = _repo_split("runbook-v2")[1]
    truth = [{**_row(dev[0], "contract"), "source_revision": rev},
             {**_row(dev[1], "correspondence"), "source_revision": rev}]
    run = _run(tmp_path, truth=truth, items=[
        {"item_id": dev[0], "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 1.0}},
        {"item_id": dev[1], "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 0.0}}])
    out = rs.rescore(run, dataset_file=_truth_file(tmp_path, truth), out=tmp_path / "out")["out"]
    sheet = ga.build_sheet(Path(out), "sorter", seed=1)
    assert sheet.digest["documents"] == 2 and [r["doc_id"] for r in sheet.rows] == [dev[1]]


def test_an_original_run_pairs_with_a_rescore_only_on_the_same_revision(tmp_path):
    """Original vs. its own rescore pairs while the revision and labels are the same (a scorer-drift
    check); moved labels or another revision are other truth and are refused; two arms rescored to
    the same revision pair."""
    from mailroom_sandbox import sorter_arms

    a = _drawn_from(tmp_path, "runbook-v1", name="arm-a")
    b = _drawn_from(tmp_path, "runbook-v1", name="arm-b")
    original = [json.loads(line) for line in (a / "dataset.jsonl").read_text().splitlines()]
    meta = {k: json.loads((a / "spec.lock.json").read_text())["dataset"][k] for k in ("revision", "revision_resolved")}
    drift = rs.rescore(a, out=tmp_path / "a-drift", truth_loader=lambda spec, ids: (original, meta))["out"]
    assert sorter_arms.pair([sorter_arms.load_arm(a), sorter_arms.load_arm(drift)]) == ["DOC-1", "DOC-2"]
    moved = rs.rescore(a, out=tmp_path / "a-moved", truth_loader=_loader_on("runbook-v1"))["out"]
    with pytest.raises(sorter_arms.ArmError, match="the truth differs between runs"):
        sorter_arms.pair([sorter_arms.load_arm(a), sorter_arms.load_arm(moved)])

    a93 = rs.rescore(a, revision="v9.3", out=tmp_path / "a93", truth_loader=_loader_on("runbook-v2"))["out"]
    b93 = rs.rescore(b, revision="v9.3", out=tmp_path / "b93", truth_loader=_loader_on("runbook-v2"))["out"]
    with pytest.raises(sorter_arms.ArmError, match="dataset revisions differ"):
        sorter_arms.pair([sorter_arms.load_arm(a), sorter_arms.load_arm(a93)])
    arms = [sorter_arms.load_arm(a93), sorter_arms.load_arm(b93)]
    assert sorter_arms.pair(arms) == ["DOC-1", "DOC-2"]
    assert all(arm.split_dir is None for arm in arms)  # resolved from v9.3, not the v1 file


def test_the_derived_run_carries_run_level_scores(tmp_path):
    run = _run(tmp_path, items=[
        {"item_id": "DOC-1", "ok": True, "pred": {"doc_type": "contract"}, "score": {"match": 1.0}},
        {"item_id": "DOC-2", "ok": False, "error": "timeout", "pred": None, "score": None}])
    report = rs.rescore(run, dataset_file=_truth_file(tmp_path, [_row("DOC-1", "contract"), _row("DOC-2", "contract")]),
                        out=tmp_path / "out")
    scores = json.loads((Path(report["out"]) / "scores.json").read_text())
    assert scores == report["scores"]
    assert (scores["items"], scores["scored"], scores["unscored"]) == (2, 1, 1)
    assert scores["means"]["match"] == {"n": 1, "mean": 1.0}
    assert scores["by_class"]["contract"]["match"]["n"] == 1
