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
    "sand214-30-contracts-specialist-awq-1l4-windows-r2": "contract",
    "sand214-30-contracts-specialist-awq-1l4-windows-c28k": "contract",
    "sand214-30-contracts-specialist-awq-1l4-windows-c16k": "contract",
}
SUITE = ["sand214-30-contracts-specialist-awq-1l4-windows", "sand214-30-merger-specialist-awq-1l4-windows"]


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
    assert ids == SUITE  # contracts first: the cheaper leg fails first
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


def test_contracts_r2_pairs_with_r1_and_carries_the_length_fix():
    r1, r2 = _spec(SUITE[0]), _spec("sand214-30-contracts-specialist-awq-1l4-windows-r2")
    # Same documents: everything that decides the draw is identical.
    for key in ("revision", "exclude_ids_file", "strata", "sample_seed", "limit", "require_task_gt",
                "interim_labels", "near_gold_labels"):
        assert getattr(r1.dataset, key) == getattr(r2.dataset, key), key
    assert r1.prompt == r2.prompt and deploy_env.spec_env(r1) == deploy_env.spec_env(r2)
    knobs = posture.agent_knobs_for_run(r2.run_id)["contracts_specialist"]
    assert knobs["length_retries"] == 1 and knobs["presence_penalty"] == 1.0
    assert knobs["top_p"] == 0.8 and knobs["top_k"] == 20 and knobs["max_tokens"] == 8192
    assert {k: v for k, v in knobs.items() if k not in posture.SAND214_LENGTH_FIX} == r1.agent_knobs[
        "contracts_specialist"]
    assert r2.job.longest_first and not benchmark_check.chunked_window_warnings(r2)


@pytest.mark.parametrize(("arm", "chunk"), [("c28k", 28000), ("c16k", 16000)])
def test_a_window_length_arm_pairs_with_r2_and_moves_only_the_window(arm, chunk):
    r2 = _spec("sand214-30-contracts-specialist-awq-1l4-windows-r2")
    spec = _spec(f"sand214-30-contracts-specialist-awq-1l4-windows-{arm}")
    for key in ("revision", "exclude_ids_file", "strata", "sample_seed", "limit", "require_task_gt",
                "interim_labels", "near_gold_labels"):
        assert getattr(r2.dataset, key) == getattr(spec.dataset, key), key
    assert r2.prompt == spec.prompt and deploy_env.spec_env(r2) == deploy_env.spec_env(spec)
    base = posture.agent_knobs_for_run(r2.run_id)["contracts_specialist"]
    knobs = posture.agent_knobs_for_run(spec.run_id)["contracts_specialist"]
    assert {k for k in knobs if knobs[k] != base.get(k)} == {"chunk_chars", "overlap_chars"}
    assert knobs["chunk_chars"] == chunk
    # Same overlap share as r2 (6,000 / 43,000), within a percentage point.
    assert abs(knobs["overlap_chars"] / chunk - base["overlap_chars"] / base["chunk_chars"]) < 0.01
    assert spec.job.longest_first and not benchmark_check.chunked_window_warnings(spec)


def test_window_length_suite_serves_both_arms_from_one_deploy():
    suite = load_suite("sand214-window-length")
    specs = [load_run_spec(p) for p in suite.configs]
    assert [s.run_id.rsplit("-", 1)[1] for s in specs] == ["c28k", "c16k"]
    assert deploy_env.spec_env(specs[0]) == deploy_env.spec_env(specs[1])


def test_threshold_calibration_runs_production_on_the_calibration_split_and_judges_every_class():
    spec = load_run_spec(repo_root() / "config/runs/sand214-pipeline-150-calibration-judge-all.yaml")
    prod = load_run_spec(repo_root() / "config/runs/production/slice-0100.yaml")
    excluded = {s.strip() for s in spec.dataset.exclude_ids_path().read_text().splitlines()
                if s.strip() and not s.startswith("#")}
    rows = [json.loads(line) for line in
            (repo_root() / "config/splits/runbook-v2/assignments.jsonl").read_text().splitlines()]
    assert excluded == {r["id"] for r in rows if r["set"] != "calibration"}
    counts = {b["doc_class"]: b["count"] for b in spec.dataset.strata["buckets"]}
    assert counts == dict.fromkeys(("contract", "corporate_record", "correspondence", "insurance_claim",
                                    "merger_agreement"), 30)
    by_class = spec.confidence["by_class"]
    assert set(by_class) == set(counts) and all(b["judge_band_high"] == 1.01 for b in by_class.values())
    assert all("low" not in b for b in by_class.values())  # low also gates the sorter
    # Routing and serving still match the adopted production configuration.
    assert (spec.prompt, spec.engine, spec.agent_routes, spec.agent_knobs, spec.reviewer) == (
        prod.prompt, prod.engine, prod.agent_routes, prod.agent_knobs, prod.reviewer)
    # Calibration truth is frozen even when new production preparations advance.
    assert spec.dataset.staged_overlay == "9.3.1-rc.9"
    assert spec.job.blind_routing
    assert spec.job.api_cost_cap_usd and spec.job.max_wall_seconds
