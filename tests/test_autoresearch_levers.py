"""Autoresearch levers: patching, validation, ordering and the production catalog."""
from __future__ import annotations

import copy

import pytest
import yaml

from mailroom_sandbox.autoresearch import levers as lv
from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
BASE = {
    "schema": "sandbox.run/v1", "run_id": "t", "task": "pipeline", "profile": "ollama",
    "dataset": {"provider": "file", "local_path": "data/fixtures/hf/docclass_mini.jsonl", "limit": 3},
    "engine": {"kind": "vllm-local", "model": "Qwen/Qwen3-8B", "modal": None},
    "reviewer": {"backend": "mock", "model": "mock", "classes": {"contract": 0.5}},
    "job": {"mode": "endpoint", "mock": True},
    "trace": {"sink": "none", "tags": ["t"]},
}


def lever(**kw) -> lv.Lever:
    kw.setdefault("id", "x")
    kw.setdefault("node", "reviewer")
    kw.setdefault("description", "d")
    return lv.Lever(**kw)


def test_patch_sets_nested_and_leaves_the_original_alone():
    spec = copy.deepcopy(BASE)
    out = lv.apply_patch(spec, {"confidence.by_class.contract.judge_band_high": 1.01, "reviewer.classes.contract": 0.4})
    assert out["confidence"]["by_class"]["contract"] == {"judge_band_high": 1.01}
    assert out["reviewer"]["classes"]["contract"] == 0.4
    assert spec == BASE


def test_null_deletes_a_key_and_a_missing_parent_is_a_noop():
    out = lv.apply_patch(BASE, {"reviewer": None, "engine.vllm.nothing.here": None})
    assert "reviewer" not in out
    assert out["engine"] == BASE["engine"]


def test_patch_through_a_scalar_fails():
    with pytest.raises(lv.LeverError, match="not a mapping"):
        lv.apply_patch(BASE, {"profile.sub": 1})


def test_lever_validation_failure_names_the_bad_path():
    bad = lever(patch={"confidence.by_class.contract.judge_band_high": 5})
    with pytest.raises(lv.LeverError, match=r"lever x: .*judge_band_high"):
        lv.apply_lever(BASE, bad)
    unknown = lever(patch={"nonexistent.path": 1})
    with pytest.raises(lv.LeverError, match="nonexistent"):
        lv.apply_lever(BASE, unknown)


@pytest.mark.parametrize("path", ["dataset.limit", "run_id", "task", "job.mock", "job.api_cost_cap_usd", "job.max_wall_seconds", "job.mode"])
def test_levers_cannot_touch_what_the_study_owns(path):
    with pytest.raises(ValueError, match="set by the study"):
        lever(patch={path: 1})


def test_lever_needs_a_patch_or_a_pipeline_source_and_a_group_for_a_tier():
    with pytest.raises(ValueError, match="patch or a pipeline_source"):
        lever()
    with pytest.raises(ValueError, match="needs a group"):
        lever(patch={"reviewer.classes.contract": 0.4}, tier=1)
    with pytest.raises(ValueError, match="conditions are"):
        lever(patch={"reviewer.classes.contract": 0.4}, requires=[{"bogus": 1}])


def test_catalog_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "l.yaml"
    item = {"id": "a", "node": "judge", "description": "d", "patch": {"reviewer.classes.contract": 0.4}}
    p.write_text(yaml.safe_dump({"schema": lv.SCHEMA, "levers": [item, item]}))
    with pytest.raises(lv.LeverError, match="duplicate lever ids"):
        lv.load_levers(p)


def test_env_ready_and_pipeline_source_default():
    src = lever(id="repair", node="insurance_claims_specialist",
                pipeline_source={"env": "AR_TEST_SRC", "commit": "a" * 40})
    assert src.requires_env == "AR_TEST_SRC"
    assert not lv.env_ready(src, {})
    assert not lv.env_ready(src, {"AR_TEST_SRC": "  "})
    assert lv.env_ready(src, {"AR_TEST_SRC": "/x"})
    assert lv.env_ready(lever(patch={"reviewer.classes.contract": 0.4}), {})


def _ladder() -> lv.Catalog:
    t1 = [lever(id=f"t1{i}", patch={"reviewer.classes.contract": 0.1 * i}, tier=1, group="g") for i in (1, 2)]
    t2 = lever(id="t2", patch={"reviewer.classes.contract": 0.9}, tier=2, group="g",
               requires=[{"kept": {"group": "g", "tier": 1}}, {"all_reverted_positive": {"group": "g", "tier": 1}}])
    t3 = lever(id="t3", patch={"reviewer.classes.contract": 0.95}, tier=3, group="g",
               requires=[{"kept": {"group": "g", "tier": 2}, "budget_multiple": 3}])
    return lv.Catalog(levers=[*t1, t2, t3])


def row(lever_id, decision, mean=0.0):
    return {"lever": lever_id, "decision": decision, "delta": {"mean": mean}}


def test_tier_two_needs_a_tier_one_keep_or_all_reverted_with_positive_mean():
    cat = _ladder()
    t2 = next(item for item in cat.levers if item.id == "t2")
    met = lambda rows: lv.requirement_met(t2, cat.levers, rows)  # noqa: E731
    assert not met([])
    assert not met([row("t11", "revert", 0.1)])                                  # t12 untried
    assert met([row("t11", "keep", 0.1)])                                        # a keep opens it
    assert met([row("t11", "revert", 0.02), row("t12", "revert", 0.01)])         # all reverted, positive
    assert not met([row("t11", "revert", 0.02), row("t12", "revert", -0.01)])    # one negative
    assert not met([row("t11", "revert", 0.02), row("t12", "error")])            # an error is not a revert


def test_tier_three_needs_a_tier_two_keep_and_three_round_caps_of_budget():
    cat = _ladder()
    t3 = next(item for item in cat.levers if item.id == "t3")
    kept = [row("t2", "keep", 0.1)]
    assert not lv.requirement_met(t3, cat.levers, [row("t2", "revert", 0.1)], budget_remaining_usd=99, round_cap_usd=1)
    assert not lv.requirement_met(t3, cat.levers, kept, budget_remaining_usd=2.9, round_cap_usd=1)
    assert lv.requirement_met(t3, cat.levers, kept, budget_remaining_usd=3.0, round_cap_usd=1)
    assert not lv.requirement_met(t3, cat.levers, kept)   # budget unknown: closed


def test_placements_derive_only_after_the_winner_is_kept_and_restore_the_base_routing():
    sup = lever(id="sup-x", node=["judge", "boss"], group="sup", tier=1,
                patch={"agent_routes.judge": {"provider": "openrouter", "model": "m"},
                       "agent_routes.boss": {"provider": "openrouter", "model": "m"}})
    cat = lv.Catalog(levers=[sup], placements=[lv.Placement(group="sup", roles=["judge", "boss"], keep_on=[["judge"], ["boss"]])])
    base = {"agent_routes": {"judge": {"provider": "openrouter", "model": "base"}}}
    assert lv.derive_placements(cat, base, []) == []
    assert lv.derive_placements(cat, base, [row("sup-x", "revert", 0.1)]) == []
    derived = {item.id: item for item in lv.derive_placements(cat, base, [row("sup-x", "keep", 0.1)])}
    assert set(derived) == {"sup-x@judge", "sup-x@boss"}
    only_judge = derived["sup-x@judge"]
    assert only_judge.goal == "cost"
    assert only_judge.patch == {"agent_routes.boss": None}                 # boss had no base route: deleted
    assert derived["sup-x@boss"].patch == {"agent_routes.judge": {"provider": "openrouter", "model": "base"}}
    assert only_judge.requires == [{"kept_lever": "sup-x"}]


def test_placement_must_be_a_proper_subset():
    with pytest.raises(ValueError, match="proper, non-empty subset"):
        lv.Placement(group="g", roles=["a", "b"], keep_on=[["a", "b"]])


def test_slug_makes_a_valid_run_id_fragment():
    assert lv.slug("sup-x@judge+boss") == "sup-x-judge-boss"
    assert lv.slug("@@@") == "lever"


def test_validate_catalog_reports_noop_and_unknown_requires():
    noop = lever(id="noop", patch={"reviewer.classes.contract": 0.5})
    ghost = lever(id="ghost", patch={"reviewer.classes.contract": 0.4}, requires=[{"kept_lever": "missing"}])
    problems = lv.validate_catalog(lv.Catalog(levers=[noop, ghost]), BASE)
    assert any("noop: the patch changes nothing" in p for p in problems)
    assert any("unknown lever 'missing'" in p for p in problems)


# ---- the committed catalogs ------------------------------------------------------------------------

@pytest.mark.parametrize("study", ["mailroom-v1", "mock-smoke"])
def test_committed_catalogs_fit_their_base_specs(study):
    root = ROOT / "config" / "autoresearch"
    levers_path = root / ("levers.yaml" if study == "mailroom-v1" else "mock-smoke/levers.yaml")
    base = yaml.safe_load((root / study / "base.yaml").read_text())
    assert lv.validate_catalog(lv.load_levers(levers_path), base) == []


def test_production_catalog_reviewers_are_all_true_decisions_models():
    from mailroom_sandbox.decision_backends import decision_model

    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    reviewers = [item for item in cat.levers if item.group == "reviewer"]
    assert len(reviewers) == 10
    for item in reviewers:
        block = item.patch["reviewer"]
        assert block["backend"] == "decisions"                        # never jev, api or a chat backend
        assert decision_model(block["model"]) is not None, block["model"]
        assert not block["model"].startswith("~") and not block["model"].endswith("-latest")
        assert not block["model"].endswith(":free")
        assert block["classes"] == cat.levers[0].patch["reviewer"]["classes"]    # v2 cutoffs everywhere
    assert "typesafe/jev-router" not in yaml.safe_dump(cat.model_dump())


def test_production_supervisor_tiers_and_order():
    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    sup = [item for item in cat.levers if item.group == "supervisor"]
    by_tier = {t: [item.patch["agent_routes.judge"]["model"] for item in sup if item.tier == t] for t in (1, 2, 3)}
    assert by_tier == {
        1: ["openai/gpt-6-luna", "qwen/qwen3.7-plus", "minimax/minimax-m3", "z-ai/glm-5.3-flashx-legal"],
        2: ["deepseek/deepseek-v4-pro", "mistralai/mistral-large-4-0", "google/gemini-3.8-flash", "qwen/qwen4-max"],
        3: ["anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol", "google/gemini-4-carbon"],
    }
    for item in sup:
        assert set(item.patch) == {"agent_routes.judge", "agent_routes.arbiter", "agent_routes.boss"}
        assert all(r["provider"] == "openrouter" for r in item.patch.values())
    assert all(not item.requires for item in sup if item.tier == 1)
    assert all(item.requires for item in sup if item.tier in (2, 3))
    assert cat.placements and cat.placements[0].roles == ["judge", "arbiter", "boss"]


def test_every_api_model_in_the_production_catalog_is_priced_and_in_the_profile():
    from mailroom_sandbox.job.metrics import token_price_ceiling

    profile = yaml.safe_load((ROOT / "config/profiles/openrouter.yaml").read_text())
    listed = set(profile.get("api_models") or [])
    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    chat_models = set()
    for item in cat.levers:
        for path, value in item.patch.items():
            if path.startswith("agent_routes.") and isinstance(value, dict):
                chat_models.add(value["model"])
            if path.startswith("agent_models."):
                chat_models.add(value)
    assert chat_models
    for model in sorted(chat_models):
        assert token_price_ceiling(model) is not None, f"{model} has no price"
        assert model in listed, f"{model} missing from profiles/openrouter.yaml api_models"


def test_repair_283_is_a_contained_pipeline_source_lever():
    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    item = next(i for i in cat.levers if i.id == "repair-283")
    assert item.pipeline_source.env == "AUTORESEARCH_PR283_SRC"
    assert item.pipeline_source.commit == "090991b34c0e4e56658a1c38f98c9d9fc414b0d4"
    assert item.requires_env == "AUTORESEARCH_PR283_SRC" and not item.patch
    assert not lv.env_ready(item, {})


def test_a_skipped_tier_one_lever_does_not_block_the_ladder():
    cat = _ladder()
    t2 = next(item for item in cat.levers if item.id == "t2")
    rows = [row("t11", "revert", 0.02), {"lever": "t12", "decision": "skipped"}]
    assert lv.requirement_met(t2, cat.levers, rows)
