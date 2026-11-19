"""Campaign report tree (SAND-108): grammar, mapping, iterations, builder, --check and the runner hook."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox import report_campaigns as rc
from mailroom_sandbox.job import preflight, runner
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir
from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
RUN = "rb1-r03-sorter-unit"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Run stores, experiment log and the campaign tree all under tmp."""
    from mailroom_sandbox.eval import experiment_log

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(rc.ROOT_ENV, str(tmp_path / "campaigns"))
    monkeypatch.delenv("SANDBOX_SERVED_LOG", raising=False)
    monkeypatch.delenv("MODAL_BILLED_GPU_SECONDS", raising=False)
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    return {"tmp": tmp_path, "tree": tmp_path / "campaigns", "log": log}


def _store(tmp_path: Path, run_id: str = RUN, rows: int = 4) -> RunStore:
    path = tmp_path / f"{run_id}.src.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(json.dumps({"id": f"d{i}", "filename": f"{i}.txt", "doc_text": f"t{i}",
                                 "expected": "contract" if i % 2 else "insurance_claim",
                                 "expected_subclass": "service" if i % 2 else "auto"}) + "\n")
    spec = RunSpec(run_id=run_id, task="sorter", dataset=DatasetSpec(local_path=f"file://{path}", limit=rows),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"}, job={"mock": True})
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    return RunStore(run_dir(report["run_id"]))


def _finished(env, run_id: str = RUN) -> RunStore:
    store = _store(env["tmp"], run_id)
    assert runner.run_job(store, mock=None)["state"] == "done"
    return store


# ── grammar ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("run_id", ["rb1-r01-smoke-qwen3.7-flash", "rb1-g6b-load-probe", "rb1-r03-sorter-v0-dev"])
def test_run_id_and_artifact_names_round_trip(run_id):
    key = rc.parse_run_id(run_id)
    assert rc.format_run_id(key.campaign, key.row, run_id[len(key.experiment) + 1:]) == run_id
    name = rc.format_artifact(run_id, 3, "report", "md")
    assert name == f"{run_id}-i03.report.md"
    assert rc.parse_artifact(name) == (run_id, 3, "report", "md")
    assert rc.parse_iteration(rc.format_iteration(12)) == 12 and rc.parse_iteration("2") == 2


@pytest.mark.parametrize("bad", ["RB1-r01-x", "rb1-r01", "rb1-r01-x-i02", "rb1--x", "rb1-r01-" + "x" * 60])
def test_grammar_rejects_ids_outside_it(bad):
    with pytest.raises(rc.CampaignError):
        rc.parse_run_id(bad)


def test_artifact_and_iteration_rejections():
    for bad in ("README.md", "rb1-r01-x.report.md", "rb1-r01-x-i1.report.md"):
        with pytest.raises(rc.CampaignError):
            rc.parse_artifact(bad)
    for bad in ("i00", "x01", 0):
        with pytest.raises(rc.CampaignError):
            rc.parse_iteration(bad)


def test_every_committed_campaign_config_matches_the_grammar():
    configs = sorted((ROOT / "config/runs").glob("rb1-*.yaml"))
    assert configs, "expected committed rb1 configs"
    camp = rc.load_campaign("rb1")
    for path in configs:
        run_id = yaml.safe_load(path.read_text(encoding="utf-8"))["run_id"]
        assert run_id == path.stem
        key = rc.parse_run_id(run_id)
        assert key.campaign == "rb1" and camp.experiment(key.row).key == key.experiment
    assert not sorted((ROOT / "config/runs").glob("runbook-r0*.yaml")), "old runbook-* names must be renamed"


# ── mapping ─────────────────────────────────────────────────────────────────
def test_mapping_covers_the_runbook_rows():
    camp = rc.load_campaign("rb1")
    assert camp.name == "runbook-v1" and len(camp.experiments) == 39
    assert camp.experiments[0].row == "r00" and camp.experiments[-1].row == "r90"
    _c, exp, key = rc.experiment_for_run("rb1-r03-sorter-v0-dev")
    assert exp.dirname == "rb1-r03-gold-audit" and key.experiment == "rb1-r03"
    assert rc.experiment_paths("rb1-r02").dir.name == "rb1-r02-scorer-handcheck"
    with pytest.raises(rc.CampaignError):
        rc.experiment_for_run("rb1-r99-nope")
    with pytest.raises(rc.CampaignError):
        rc.load_campaign("zz9")


def test_campaign_paths_api(env):
    paths = rc.campaign_paths("rb1-r20-sorter-arm-a", 2)
    assert paths.root == env["tree"] / "rb1/rb1-r20-sorter-v0-baselines/rb1-r20-sorter-arm-a/i02"
    assert paths.analysis == paths.root / "analysis" and paths.figures == paths.root / "figures"
    assert paths.file("analysis", "mcnemar", "json").name == "rb1-r20-sorter-arm-a-i02.mcnemar.json"
    assert paths.experiment.file("comparison", "csv", "analysis").name == "rb1-r20.comparison.csv"
    assert rc.campaign_paths("rb1-r20-sorter-arm-a").key.iteration == 1  # no store: i01
    with pytest.raises(rc.CampaignError):
        paths.file("nowhere", "x", "json")


# ── iterations ──────────────────────────────────────────────────────────────
def test_iterations_are_archived_generations_then_the_live_store(tmp_path):
    store = tmp_path / RUN
    for name in ("archive-20261102T000000Z-bbbb", "archive-20261101T000000Z-aaaa"):
        (store / name).mkdir(parents=True)
        (store / name / "spec.lock.json").write_text(json.dumps({"run_id": RUN, "spec_hash": name}))
    (store / "archive-20261103T000000Z-empty").mkdir()  # nothing locked there: not an iteration
    (store / "spec.lock.json").write_text(json.dumps({"run_id": RUN, "spec_hash": "live"}))
    (store / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"ts": "2026-11-04T00:00:00+00:00", "event": "start"},
        {"ts": "2026-11-04T01:00:00+00:00", "event": "paused"},
        {"ts": "2026-11-04T02:00:00+00:00", "event": "resume"},
        {"ts": "2026-11-04T03:00:00+00:00", "event": "done"})))
    gens = rc.discover_iterations(store)
    assert [(g.label, g.archived, (g.lock or {})["spec_hash"]) for g in gens] == [
        ("i01", True, "archive-20261101T000000Z-aaaa"), ("i02", True, "archive-20261102T000000Z-bbbb"),
        ("i03", False, "live")]
    assert [x["event"] for x in rc._launches(gens[-1])] == ["start", "resume"]
    assert rc._event_window(gens[-1]) == ("2026-11-04T00:00:00+00:00", "2026-11-04T03:00:00+00:00")
    assert rc.discover_iterations(tmp_path / "missing-run") == []


# ── builder ─────────────────────────────────────────────────────────────────
def test_build_produces_the_full_tree(env):
    _finished(env)
    result = rc.build_run(RUN)
    it = env["tree"] / "rb1/rb1-r03-gold-audit" / RUN / "i01"
    assert result["iterations"][0]["iteration"] == "i01"
    for sub in rc.SUBDIRS:
        assert (it / sub).is_dir()
    stem = f"{RUN}-i01"
    for rel in ("README.md", f"{stem}.manifest.json", f"report/{stem}.report.md", f"report/{stem}.report.json",
                f"logs/{stem}.spec-lock.json", f"logs/{stem}.events.jsonl", f"logs/{stem}.served-digest.json",
                f"outputs/{stem}.predictions.csv", f"outputs/{stem}.item-scores.csv",
                f"analysis/{stem}.metrics.json", f"analysis/{stem}.stats.json", f"traces/{stem}.items.jsonl",
                f"traces/{stem}.traces.json", f"docs/{stem}.caveats.md", f"docs/{stem}.prompt-lock.json"):
        assert (it / rel).is_file(), rel
    # every generated file but README/index carries its full key
    for path in env["tree"].rglob("*"):
        if path.is_file() and path.name not in ("README.md", "index.jsonl"):
            assert path.name.startswith(f"{RUN}-i01."), path
            assert rc.parse_artifact(path.name)[0] == RUN
    report = json.loads((it / f"report/{stem}.report.json").read_text())
    assert report["mock"] is True and report["status"] == "done" and report["items"]["total"] == 4
    assert report["headline_source"] == "experiment log" and report["headline"]["accuracy"] == 1.0
    assert "MOCK" in (it / "README.md").read_text()
    rows = [json.loads(line) for line in (env["tree"] / "rb1/index.jsonl").read_text().splitlines()]
    assert [(r["campaign"], r["experiment"], r["run_id"], r["iteration"], r["status"]) for r in rows] == [
        ("rb1", "rb1-r03", RUN, "i01", "done")]
    assert rows[0]["path"] == f"rb1-r03-gold-audit/{RUN}/i01" and rows[0]["spec_hash"] == report["spec_hash"]
    exp_readme = (env["tree"] / "rb1/rb1-r03-gold-audit/README.md").read_text()
    assert f"({RUN}/i01/README.md)" in exp_readme and "rb1-r03-sorter-v0-dev.yaml" in exp_readme
    assert "[rb1-r03-gold-audit](rb1-r03-gold-audit/README.md)" in (env["tree"] / "rb1/README.md").read_text()


def test_headline_is_never_invented_without_a_matching_log_record(env):
    _finished(env)
    env["log"].write_text("")  # the run's record is gone
    rc.build_run(RUN)
    stem = f"{RUN}-i01"
    it = env["tree"] / "rb1/rb1-r03-gold-audit" / RUN / "i01"
    report = json.loads((it / f"report/{stem}.report.json").read_text())
    assert report["headline"] == {} and report["headline_source"] is None
    assert "Not recorded" in (it / f"report/{stem}.report.md").read_text()
    assert any("No experiment-log record" in c for c in report["caveats"])


def test_build_is_deterministic_and_check_detects_stale(env, capsys):
    from mailroom_sandbox import cli

    _finished(env)
    rc.build_run(RUN)
    it = env["tree"] / "rb1/rb1-r03-gold-audit" / RUN / "i01"
    before = {p: p.read_bytes() for p in env["tree"].rglob("*") if p.is_file()}
    assert rc.build_run(RUN, check=True)["stale"] == []
    rc.build_run(RUN)
    assert {p: p.read_bytes() for p in env["tree"].rglob("*") if p.is_file()} == before
    assert cli.main(["report", "build", "--run", RUN, "--check"]) == 0
    report_md = it / f"report/{RUN}-i01.report.md"
    report_md.write_text("hand edit\n")
    stale = rc.build_run(RUN, check=True)["stale"]
    assert stale == [f"reports/campaigns/rb1/rb1-r03-gold-audit/{RUN}/i01/report/{RUN}-i01.report.md"]
    assert report_md.read_text() == "hand edit\n"  # --check writes nothing
    (it / "docs" / f"{RUN}-i01.r01-gate.json").write_text('{"ok": true}\n')  # gate output: not owned
    capsys.readouterr()
    assert cli.main(["report", "build", "--campaign", "rb1", "--check"]) == 1  # experiment README lists gates
    assert cli.main(["report", "build", "--run", RUN, "--check"]) == 1
    assert "stale:" in capsys.readouterr().out
    assert cli.main(["report", "build", "--run", RUN]) == 0
    assert (it / "docs" / f"{RUN}-i01.r01-gate.json").is_file()  # builder never deletes unowned files
    assert cli.main(["report", "build", "--campaign", "rb1", "--check"]) == 0
    assert "r01-gate.json" in (env["tree"] / "rb1/rb1-r03-gold-audit/README.md").read_text()
    assert cli.main(["report", "build", "--run", "runbook-r03-x"]) == 2
    assert cli.main(["report", "build"]) == 2
    assert cli.main(["report", "build", "--run", RUN, "--campaign", "rb1"]) == 2
    assert cli.main(["report"]) == 0
    assert cli.main(["report", "build", "--run", "rb1-r03-not-there"]) == 2


def test_large_traces_are_referenced_by_sha256_not_copied(env):
    store = _finished(env)
    rc.build_run(RUN, opts=rc.BuildOptions(copy_cap=16))
    it = env["tree"] / "rb1/rb1-r03-gold-audit" / RUN / "i01"
    assert not (it / f"traces/{RUN}-i01.items.jsonl").exists()
    refs = json.loads((it / f"traces/{RUN}-i01.traces.json").read_text())["references"]
    assert refs["items"]["sha256"] == rc.sha256_file(store.items_path)
    assert refs["items"]["path"] == f"data/runtime/runs/{RUN}/items.jsonl"
    assert refs["dataset"]["bytes"] == store.dataset_path.stat().st_size
    large = json.loads((it / f"logs/{RUN}-i01.large-logs.json").read_text())
    assert large["spec-lock"]["sha256"] == rc.sha256_file(store.lock_path)


def test_served_ledger_rows_are_filtered_to_the_generation(env, monkeypatch):
    store = _finished(env)
    lock = store.read_lock()
    ledger = env["tmp"] / "data/runtime/rb1-r03/served-m.jsonl"
    ledger.parent.mkdir(parents=True)
    rows = [{"run_id": RUN, "spec_hash": lock["spec_hash"], "requested_model": "m", "served_model": "m",
             "served_provider": "p", "status": "verified", "mismatch": False},
            {"run_id": RUN, "spec_hash": "other", "requested_model": "m", "status": "verified"},
            {"run_id": "rb1-r03-else", "spec_hash": lock["spec_hash"], "requested_model": "m", "status": "verified"}]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rc.build_run(RUN)
    digest = json.loads((env["tree"] / f"rb1/rb1-r03-gold-audit/{RUN}/i01/logs/{RUN}-i01.served-digest.json").read_text())
    assert digest["rows"] == 1 and digest["mismatch_rows"] == 0
    assert digest["sources"][0]["path"] == "data/runtime/rb1-r03/served-m.jsonl"


def test_builder_never_writes_into_the_run_store(env):
    store = _finished(env)
    with open(store.items_path, "a", encoding="utf-8") as fh:
        fh.write('{"torn": ')  # a torn tail RunStore.load_items would truncate
    snapshot = {p: p.read_bytes() for p in store.dir.rglob("*") if p.is_file()}
    rc.build_run(RUN)
    assert {p: p.read_bytes() for p in store.dir.rglob("*") if p.is_file()} == snapshot


# ── runner hook ─────────────────────────────────────────────────────────────
def test_runner_hook_failure_never_fails_or_alters_the_run(env, monkeypatch, caplog):
    calls = []

    def boom(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("report disk full")

    monkeypatch.setattr(rc, "_skip_lock", lambda lock: False)  # file even this mock run
    monkeypatch.setattr(rc, "build_run", boom)
    store = _store(env["tmp"])
    with caplog.at_level("WARNING", logger="mailroom_sandbox.report_campaigns"):
        summary = runner.run_job(store, mock=None)
    assert summary["state"] == "done" and summary["ok"] == 4 and summary["scores"]["exact_match"] == 1.0
    assert calls == [(RUN,)] and "campaign report build failed" in caplog.text
    assert store.read_checkpoint()["state"] == "done"


def test_runner_hook_builds_real_runs_and_skips_others(env, monkeypatch):
    monkeypatch.setattr(rc, "_skip_lock", lambda lock: False)
    store = _finished(env)
    assert (env["tree"] / f"rb1/rb1-r03-gold-audit/{RUN}/i01/README.md").is_file()
    monkeypatch.setenv(rc.DISABLE_ENV, "0")
    assert rc.maybe_build_campaign_reports(store) is None
    monkeypatch.delenv(rc.DISABLE_ENV)
    outside = _store(env["tmp"], "plain-run")
    assert rc.maybe_build_campaign_reports(outside) is None
    monkeypatch.undo()


def test_mock_runs_are_skipped_by_the_hook(env):
    store = _finished(env)
    assert rc.maybe_build_campaign_reports(store) is None
    assert not (env["tree"] / "rb1").exists()


# ── committed tree ──────────────────────────────────────────────────────────
def test_committed_campaign_indexes_are_fresh(monkeypatch):
    monkeypatch.delenv(rc.ROOT_ENV, raising=False)
    assert rc.build_campaign("rb1", check=True)["stale"] == []


def test_r02_handcheck_lives_in_the_campaign_tree():
    exp = ROOT / "reports/campaigns/rb1/rb1-r02-scorer-handcheck"
    for name in ("rb1-r02.sheet.csv", "rb1-r02.cases.jsonl", "rb1-r02.provenance.json"):
        assert (exp / name).is_file()
    assert not (ROOT / "reports/runbook").exists()


def test_g0_digest_files_under_the_checkpoint_folder(env):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_g0", ROOT / "scripts/check_g0.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    paths = mod.write_digest([{"gate": "R00 split audit", "status": "pass", "exit": 0}], 0, root=env["tree"])
    assert [p.name for p in paths] == ["rb1-g0.checkpoint-gate.json", "rb1-g0.checkpoint-gate.md"]
    assert json.loads(paths[0].read_text())["ok"] is True
    readme = (env["tree"] / "rb1/rb1-g0-checkpoint/README.md").read_text()
    assert "gate passed" in readme and "rb1-g0.checkpoint-gate.json" in readme


def test_r01_gate_writes_into_the_run_docs(env):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_r01_smoke", ROOT / "scripts/check_r01_smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ledger = env["tmp"] / "served.jsonl"
    ledger.write_text("")
    out = mod.write_docs({"ok": False, "models": {}}, {"rb1-r01-smoke-m"}, ledgers=[ledger],
                         configs=[Path("config/runs/rb1-r01-smoke-m.yaml")], root=env["tree"])
    assert out == [env["tree"] / "rb1/rb1-r01-provider-pin-smoke/rb1-r01-smoke-m/i01/docs/rb1-r01-smoke-m-i01.r01-gate.json"]
    assert json.loads(out[0].read_text())["ok"] is False
    shutil.rmtree(env["tree"])
