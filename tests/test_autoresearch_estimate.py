"""Autoresearch round-cost estimate (the worst case priced at the candidate's dearest tier) and production parity."""
from __future__ import annotations

import math

import pytest
import yaml

from mailroom_sandbox.autoresearch import estimate as est
from mailroom_sandbox.autoresearch import parity
from mailroom_sandbox.autoresearch import scoring as sc
from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.job.spec import LEGACY_FAMILY_HF_REVISIONS

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
    # dataset.interim_labels / dataset.staged_overlay: production replaced the interim and near-gold
    # overlays with the pinned staged v10 overlay (docs/staged-label-overlay.md).
    # dataset.near_gold_labels: production adopted near-gold labels after the v1/v2 studies ran;
    # their frozen bases keep the labels they were scored with.
    # dataset.revision: production moved to Hub tag v9.3; the frozen v1/v2 bases keep the v9.1 pin
    # they were measured on (scores compare only on the same label revision).
    # dataset.task_gt_min_field_labels: production slices also draw contracts with no CUAD map but
    # enough field labels (SHF-016); the frozen v1/v2 bases keep the strict CUAD draw rule.
    allowed_prefix = ("reviewer.", "dataset.strata", "dataset.near_gold_labels", "dataset.interim_labels", "dataset.staged_overlay", "dataset.revision", "dataset.task_gt_min_field_labels", "job.api_cost_cap_usd", "job.max_wall_seconds", "run_id", "trace.tags")
    stray = {p for p in differs if not p.startswith(allowed_prefix)}
    assert not stray, f"undocumented differences from production-slice-0100: {sorted(stray)}"
    # production comparability wins over determinism: no agent_knobs difference, in particular no temperature override
    assert not [p for p in differs if p.startswith("agent_knobs.")]
    assert "temperature" not in yaml.safe_dump(base) and base["agent_knobs"] == parity.load_production()["agent_knobs"]
    assert "reviewer" not in base                       # the chat reviewer baseline: no decisions block
    inherited = dict(parity.compare(base, parity.load_production())["inherited"])
    assert base["dataset"]["revision"] == LEGACY_FAMILY_HF_REVISIONS["v9.1"][0]
    for key in ("dataset.sample_seed", "dataset.draw", "dataset.exclude_ids_file",
                "dataset.require_task_gt", "job.blind_routing", "engine.model", "profile"):
        assert key in inherited, key


def test_the_report_section_lists_commits_and_differences():
    base = yaml.safe_load((repo_root() / "config/autoresearch/mailroom-v1/base.yaml").read_text())
    md = parity.render_parity_md(base, base, dependency_sources={"pipeline": {"source": "vendored", "commit": "c" * 40, "tree_sha256": "d" * 64}})
    assert md.startswith("## Production parity")
    assert "vendored llm-mailroom" in md and "vendored llm-dojo-scoring" in md and "baseline run lock, pipeline" in md
    assert "### Differs from `config/runs/production/slice-0100.yaml`" in md and "`reviewer.backend`" in md
    assert "### Inherited unchanged" in md


# ---- the runtime bound: what the run's own ApiBudget will count --------------------------------------------------------

def _base_and_lever(lever_id="sup-claude-sonnet-5.5"):
    from mailroom_sandbox.autoresearch import levers as lv

    base = yaml.safe_load((repo_root() / "config/autoresearch/mailroom-v1/base.yaml").read_text())
    item = next(i for i in lv.load_levers(repo_root() / "config/autoresearch/levers.yaml").levers if i.id == lever_id)
    return base, item, lv.apply_lever(base, item)


def _champion(n=25):
    per_doc = {"sorter": usage(40_000, 500), "contracts_specialist": usage(60_000, 2_000), "judge": usage(8_000, 600),
               "boss": usage(4_000, 300)}
    docs = [sc.DocScore(id=f"d{i}", doc_class="contract", outcome="correct_archive", utility=1.0, usage_by_agent=per_doc, tokens=114_000)
            for i in range(n)]
    return sc.RunScores(run_id="r", run_dir="/x", docs=docs, split_available=True, price_model="qwen/qwen3.7-flash")


def test_the_runtime_bound_prices_every_token_at_the_dearest_api_model_of_the_candidate():
    from mailroom_sandbox.job import api_budget

    base, _, cand = _base_and_lever()
    champ = _champion()
    plain, dear = est.estimate_round_cost(champ, base, base), est.estimate_round_cost(champ, base, cand)
    prompt = sum(s["prompt_tokens"] for s in champ.agent_usage().values())
    completion = sum(s["completion_tokens"] for s in champ.agent_usage().values())
    price_in, price_out = api_budget.price_bound(["anthropic/claude-sonnet-5.5", "qwen/qwen3.7-flash"])
    assert dear.runtime_bound_usd == pytest.approx((prompt * price_in + completion * price_out) / 1e6, abs=1e-3)
    assert dear.runtime_bound_detail["models"] == ["anthropic/claude-sonnet-5.5", "qwen/qwen3.7-flash"]
    # both figures are reported; the per-agent one prices only the oversight tokens dearly, the bound prices the workers' too
    assert dear.runtime_bound_usd > 2 * dear.usd and dear.cap_usd == dear.runtime_bound_usd
    assert plain.runtime_bound_usd == pytest.approx(plain.usd, rel=0.02)         # one model: the two views agree
    assert dear.to_dict()["runtime_bound_usd"] == round(dear.runtime_bound_usd, 4) and dear.to_dict()["usd"] == round(dear.usd, 4)


def test_the_runtime_bound_is_at_least_what_the_api_budget_counts_for_the_same_tokens():
    from mailroom_sandbox.autoresearch import levers as lv
    from mailroom_sandbox.job import api_budget

    base, _, cand = _base_and_lever()
    champ = _champion()
    models = api_budget.spec_api_models(lv.validate_spec(cand))
    budget = api_budget.ApiBudget(10.0, *api_budget.price_bound(models), models)
    for doc in champ.docs:
        usage_all = {"prompt_tokens": sum(s["prompt_tokens"] for s in doc.usage_by_agent.values()),
                     "completion_tokens": sum(s["completion_tokens"] for s in doc.usage_by_agent.values()), "llm_calls": 4}
        budget.add_usage(usage_all)
    assert est.estimate_round_cost(champ, base, cand).runtime_bound_usd >= budget.spent_usd - 1e-9


def test_the_bound_scales_with_safety_adds_decisions_input_and_is_zero_for_a_mock_run():
    base, _, cand = _base_and_lever()
    champ = _champion()
    one, two = est.estimate_round_cost(champ, base, cand), est.estimate_round_cost(champ, base, cand, safety=2.0)
    assert two.runtime_bound_usd == pytest.approx(2 * one.runtime_bound_usd) and two.usd == pytest.approx(2 * one.usd)
    gate = {**base, "extraction_gate": {"model": "openai/gpt-6-luna-decisions", "questions": "extraction_gate_v1.3.0"}}
    with_gate = est.estimate_round_cost(champ, base, gate)
    assert with_gate.runtime_bound_detail["prompt_tokens"] > est.estimate_round_cost(champ, base, base).runtime_bound_detail["prompt_tokens"]
    mock = {**cand, "job": {**cand["job"], "mock": True}}
    assert est.estimate_round_cost(champ, base, mock).runtime_bound_usd == 0.0
    quoted = {**cand, "job": {**cand["job"], "mock": "false"}}                  # a quoted "false" is a paid run, not a mock
    assert est.estimate_round_cost(champ, base, quoted).runtime_bound_usd == pytest.approx(one.runtime_bound_usd)


def test_an_unpriced_candidate_model_makes_the_bound_infinite_too():
    out = est.estimate_round_cost(run_with({"judge": usage(1000)}), SPEC, sup("nobody/unpriced-model-9"))
    assert math.isinf(out.runtime_bound_usd) and math.isinf(out.cap_usd) and out.to_dict()["runtime_bound_usd"] is None


@pytest.mark.parametrize("bound, tier, measured, expected", [
    (2.3, 2, True, 3.0),         # 2.76 -> 3.00
    (0.5, 1, True, 1.0),         # 0.6 -> 0.75, never below the study's round cap
    (1.0, 1, True, 1.25),        # 1.2 -> 1.25
    (1.04, 1, True, 1.25),       # 1.248 -> 1.25
    (9.0, 3, True, 4.0),         # clamped to max_round_cap_usd
    (0.0, 1, False, 1.5), (0.0, 2, False, 3.0), (0.0, 3, False, 4.0), (0.0, None, False, 1.5),   # no champion measurement: tier default
])
def test_auto_round_cap(bound, tier, measured, expected):
    got = est.auto_round_cap(est.Estimate(usd=0.0, basis="t", runtime_bound_usd=bound, measured=measured), base_cap=1.0, max_cap=4.0, tier=tier)
    assert got == expected


def test_round_cap_for_uses_the_override_the_derived_cap_or_the_study_cap():
    from mailroom_sandbox.autoresearch import levers as lv

    e = est.Estimate(usd=0.1, basis="t", runtime_bound_usd=2.3)
    mk = lambda **kw: lv.Lever(id="x", node="judge", description="d", patch={"confidence.judge_max_passes": 2}, **kw)  # noqa: E731
    assert est.round_cap_for(mk(), e, base_cap=1.0, max_cap=4.0) == 1.0
    assert est.round_cap_for(mk(round_cap_usd=2.0), e, base_cap=1.0, max_cap=4.0) == 2.0
    assert est.round_cap_for(mk(round_cap_usd=7.0), e, base_cap=1.0, max_cap=4.0) == 4.0
    assert est.round_cap_for(mk(round_cap_auto=True, tier=2, group="g"), e, base_cap=1.0, max_cap=4.0) == 3.0


def test_the_runtime_bound_prices_the_reviewer_and_gate_models_like_the_run_lock_does():
    from mailroom_sandbox.job import api_budget

    cheap = "qwen/qwen3.5-9b"                       # slug price, cheaper on input than the reviewer
    plain = {"engine": {"kind": "openrouter", "model": cheap}, "job": {"mock": False}}
    dear_reviewer = {**plain, "reviewer": {"backend": "decisions", "model": "cloudflare/clef",
                                           "questions": "reviewer_decisions_v2", "classes": {"contract": 0.5}}}
    assert est._api_models(plain) == [cheap]
    models = est._api_models(dear_reviewer)
    assert models == ["cloudflare/clef", cheap]
    lock_shaped = {"engine": plain["engine"], "reviewer": dear_reviewer["reviewer"]}
    assert models == api_budget.api_models(lock_shaped)           # what the run's own ApiBudget will price
    for backend in ("local", "api", "jev"):                       # the other lock backends count too; mock does not
        assert "cloudflare/clef" in est._api_models({**plain, "reviewer": {**dear_reviewer["reviewer"], "backend": backend}}), backend
    assert est._api_models({**plain, "reviewer": {**dear_reviewer["reviewer"], "backend": "mock"}}) == [cheap]
    gated = {**plain, "extraction_gate": {"model": "cloudflare/clef", "questions": "extraction_gate_v1.3.0"}}
    assert est._api_models(gated) == ["cloudflare/clef", cheap]

    champ = run_with({"sorter": usage(1_000_000, 0, cheap)})
    base_bound = est.estimate_round_cost(champ, plain, plain).runtime_bound_usd
    out = est.estimate_round_cost(champ, plain, dear_reviewer)
    assert out.runtime_bound_detail["models"] == ["cloudflare/clef", cheap]
    price_in, _ = api_budget.price_bound(models)
    assert price_in == 0.192 > api_budget.price_bound([cheap])[0]  # the reviewer is the dearest input price
    assert out.runtime_bound_usd > base_bound
    assert out.runtime_bound_usd == pytest.approx((out.runtime_bound_detail["prompt_tokens"] * price_in) / 1e6, rel=0.01)
