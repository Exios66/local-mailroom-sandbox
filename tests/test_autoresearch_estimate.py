"""Autoresearch round-cost estimate (the worst case priced at the candidate's dearest tier) and production parity."""
from __future__ import annotations

import math

import pytest
import yaml

from mailroom_sandbox.autoresearch import estimate as est
from mailroom_sandbox.autoresearch import parity
from mailroom_sandbox.autoresearch import scoring as sc
from mailroom_sandbox.paths import repo_root

SPEC = {"engine": {"model": "qwen/qwen3.7-flash"},
        "agent_routes": {"judge": {"provider": "openrouter", "model": "qwen/qwen3.7-flash"}}}


def usage(prompt, completion=0, model="qwen/qwen3.7-flash"):
    return {"calls": 1, "prompt_tokens": prompt, "completion_tokens": completion, "models": [model]}


def run_with(usage_by_agent, tokens=0):
    docs = [sc.DocScore(id="d", doc_class="contract", outcome="correct_archive", utility=1.0, tokens=tokens,
                        usage_by_agent=usage_by_agent)]
    return sc.RunScores(run_id="r", run_dir="/x", docs=docs, split_available=bool(usage_by_agent), price_model="qwen/qwen3.7-flash")


def sup(model):
    return {**SPEC, "agent_routes": {r: {"provider": "openrouter", "model": model} for r in ("judge", "arbiter", "boss")}}


def test_agent_model_follows_routes_then_agent_models_then_the_engine():
    spec = {**SPEC, "agent_models": {"sorter": "deepseek/deepseek-v4.1-flash-1017"}}
    assert est.agent_model(spec, "judge") == "qwen/qwen3.7-flash"
    assert est.agent_model(spec, "sorter") == "deepseek/deepseek-v4.1-flash-1017"
    assert est.agent_model(spec, "intake") == "qwen/qwen3.7-flash"
    assert est.agent_model(sup("qwen/qwen4-max"), "arbiter") == "qwen/qwen4-max"


def test_the_champions_judge_tokens_are_repriced_at_the_supervisor_models_price():
    champ = run_with({"sorter": usage(1_000_000), "judge": usage(1_000_000, 100_000)})
    cheap = est.estimate_round_cost(champ, SPEC, SPEC)
    dear = est.estimate_round_cost(champ, SPEC, sup("anthropic/claude-sonnet-5.5"))
    assert dear.basis == "by_agent" and not dear.unpriced
    assert dear.usd > cheap.usd * 5
    # only the oversight agents move: the sorter line is identical
    assert dear.detail["sorter"] == cheap.detail["sorter"]
    assert dear.detail["judge"] > cheap.detail["judge"]


def test_a_model_with_no_price_gives_infinity_and_names_the_model():
    champ = run_with({"judge": usage(1000)})
    out = est.estimate_round_cost(champ, SPEC, sup("nobody/unpriced-model-9"))
    assert math.isinf(out.usd) and "nobody/unpriced-model-9" in out.unpriced


def test_without_a_per_agent_split_every_token_is_priced_at_the_dearest_model():
    champ = run_with({}, tokens=2_000_000)
    base = est.estimate_round_cost(champ, SPEC, SPEC)
    dear = est.estimate_round_cost(champ, SPEC, sup("anthropic/claude-sonnet-5.5"))
    assert base.basis == dear.basis == "totals"
    assert dear.usd > base.usd


def test_a_decisions_reviewer_is_priced_input_only_and_capped_by_the_question_set():
    champ = run_with({"sorter": usage(1000)})
    spec = {**SPEC, "reviewer": {"backend": "decisions", "model": "typesafe/jev-1.14", "questions": "reviewer_decisions_v2", "classes": {"contract": 0.5}}}
    out = est.estimate_round_cost(champ, SPEC, spec, safety=1.0)
    assert "reviewer(decisions)" in out.detail and out.detail["reviewer(decisions)"] > 0
    assert out.detail["reviewer(decisions)"] < 0.05          # one document at ~34k tokens and 0.042 USD per 1M


def test_safety_scales_the_estimate():
    champ = run_with({"judge": usage(1_000_000)})
    one = est.estimate_round_cost(champ, SPEC, SPEC, safety=1.0)
    two = est.estimate_round_cost(champ, SPEC, SPEC, safety=2.0)
    assert two.usd == pytest.approx(2 * one.usd)


# ---- parity ------------------------------------------------------------------------------------------------

def test_flatten_and_compare():
    assert parity.flatten({"a": {"b": 1}, "c": [1, 2]}) == {"a.b": 1, "c": [1, 2]}
    out = parity.compare({"a": {"b": 1, "x": 3}}, {"a": {"b": 1, "x": 4}, "y": 1})
    assert ("a.b", 1) in out["inherited"]
    assert ("a.x", 3, 4) in out["differs"] and ("y", "<unset>", 1) in out["differs"]


def test_vendored_commits_are_forty_hex():
    commits = parity.vendored_commits()
    assert set(commits) == {"llm-mailroom", "llm-dojo-scoring"}
    for sha in commits.values():
        assert sha and len(sha) == 40


def test_production_base_differs_from_slice_0100_only_where_documented():
    root = repo_root() / "config"
    base = yaml.safe_load((root / "autoresearch/mailroom-v1/base.yaml").read_text())
    differs = {p for p, *_ in parity.compare(base, parity.load_production())["differs"]}
    allowed_prefix = ("agent_knobs.", "reviewer.", "dataset.strata", "job.api_cost_cap_usd", "job.max_wall_seconds",
                      "run_id", "trace.tags")
    stray = {p for p in differs if not p.startswith(allowed_prefix)}
    assert not stray, f"undocumented differences from production-slice-0100: {sorted(stray)}"
    assert all(p.endswith("temperature") or p.endswith("max_input_chars") for p in differs if p.startswith("agent_knobs."))
    assert "reviewer" not in base                       # the chat reviewer baseline: no decisions block
    inherited = dict(parity.compare(base, parity.load_production())["inherited"])
    for key in ("dataset.revision", "dataset.sample_seed", "dataset.draw", "dataset.exclude_ids_file", "dataset.interim_labels",
                "dataset.require_task_gt", "job.blind_routing", "engine.model", "profile"):
        assert key in inherited, key


def test_the_report_section_lists_commits_and_differences():
    base = yaml.safe_load((repo_root() / "config/autoresearch/mailroom-v1/base.yaml").read_text())
    md = parity.render_parity_md(base, base, dependency_sources={"pipeline": {"source": "vendored", "commit": "c" * 40, "tree_sha256": "d" * 64}})
    assert md.startswith("## Production parity")
    assert "vendored llm-mailroom" in md and "vendored llm-dojo-scoring" in md and "baseline run lock, pipeline" in md
    assert "### Differs from `config/runs/production/slice-0100.yaml`" in md and "`reviewer.backend`" in md
    assert "### Inherited unchanged" in md
