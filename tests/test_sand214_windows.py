"""#214 window merge-rule calibration: two runs, one warm fleet, calibration split only.

Network-free. A drift here silently changes what the AUROC is fitted on: a draw that
reaches dev or held-out documents breaks the held-out seal, a second serving block
pays a second cold boot, and a knob that differs from the posture row is not the
SAND-042 cell the throughput claim rests on.
"""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import benchmark_check, deploy_env
from mailroom_sandbox.job import specialist_posture as posture
from mailroom_sandbox.job.spec import load_run_spec
from mailroom_sandbox.job.suite import load_suite
from mailroom_sandbox.paths import repo_root

RUNS = {
    "sand214-30-contracts-specialist-awq-1l4-windows": "contract",
    "sand214-30-merger-specialist-awq-1l4-windows": "merger_agreement",
}


def _spec(run_id: str):
    return load_run_spec(repo_root() / "config" / "runs" / f"{run_id}.yaml")


@pytest.mark.parametrize("run_id", sorted(RUNS))
def test_config_matches_its_posture_row(run_id):
    spec, row = _spec(run_id), posture.SPECIALIST_POSTURE[run_id]
    assert spec.task == row["task"] == row["agent"]
    assert spec.job.concurrency == row["concurrency"] == 16
    assert float(spec.job.cost_cap_usd) == float(row["cost_cap_usd"])
    assert int(spec.job.max_wall_seconds) == int(row["max_wall_seconds"])
    assert spec.prompt["agents"][row["agent"]]["file"] == row["prompt_file"]
    # A spec's agent_knobs replace the posture's (preflight: spec knobs or posture knobs), so
    # either the spec has none or they are exactly the posture's.
    knobs = posture.agent_knobs_for_run(run_id)
    assert not spec.agent_knobs or spec.agent_knobs == knobs
    assert spec.engine.modal.min_containers == 0  # scale-to-zero between and after legs
    assert spec.dataset.interim_labels and spec.dataset.near_gold_labels
    assert spec.dataset.require_task_gt and spec.dataset.limit == 30


def test_merger_dispatches_its_longest_agreements_first():
    # The contracts leg was locked and started before longest_first existed; its config keeps
    # the locked spec_hash. The merger leg (6-10 windows per agreement) dispatches LPT-first.
    assert _spec("sand214-30-merger-specialist-awq-1l4-windows").job.longest_first


def test_merger_runs_the_stem_that_lists_the_maud_answers():
    assert posture.SPECIALIST_POSTURE["sand214-30-merger-specialist-awq-1l4-windows"][
        "prompt_file"] == "merger_agreement_specialist_maud_v2"


@pytest.mark.parametrize("run_id", sorted(RUNS))
def test_the_draw_never_reaches_dev_or_heldout(run_id):
    doc_class = RUNS[run_id]
    text = _spec(run_id).dataset.exclude_ids_path().read_text(encoding="utf-8")
    excluded = {s.strip() for s in text.splitlines() if s.strip() and not s.startswith("#")}
    rows = [json.loads(line) for line in
            (repo_root() / "config/splits/runbook-v2/assignments.jsonl").read_text().splitlines()]
    outside = {r["id"] for r in rows if r["doc_class"] == doc_class and r["set"] != "calibration"}
    assert outside and outside <= excluded
    assert len({r["id"] for r in rows if r["doc_class"] == doc_class} - excluded) >= 30


def test_suite_serves_both_runs_from_one_deploy():
    suite = load_suite("sand214-windows")
    ids = [load_run_spec(p).run_id for p in suite.configs]
    assert ids == sorted(RUNS)  # contracts first: the cheaper leg fails first
    envs = [deploy_env.spec_env(load_run_spec(p)) for p in suite.configs]
    assert envs[0] == envs[1]


@pytest.mark.parametrize("run_id", sorted(RUNS))
def test_benchmark_check_passes_on_the_study_profile(monkeypatch, run_id):
    monkeypatch.setattr(benchmark_check, "active_modal_profile_name", lambda: "exios66")
    monkeypatch.setattr(benchmark_check, "_modal_cli_ok", lambda: {"ok": True, "version": "stub"})
    report = benchmark_check.check_benchmark_posture(
        spec=_spec(run_id), require_hermes=False, expected_modal_profile="exios66")
    assert report["ok"], report["errors"]


def test_preflight_names_a_chunked_agent_that_would_drop_a_capped_window():
    # The contracts leg ran without length_retries and lost 3 windows to chunk_call_failed;
    # merger re-samples once and runs the Qwen3 anti-repetition sampling, so it is clean.
    warned = benchmark_check.chunked_window_warnings(_spec("sand214-30-contracts-specialist-awq-1l4-windows"))
    assert len(warned) == 1 and "contracts_specialist" in warned[0] and "length_retries" in warned[0]
    assert not benchmark_check.chunked_window_warnings(_spec("sand214-30-merger-specialist-awq-1l4-windows"))
