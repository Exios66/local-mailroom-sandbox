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


@pytest.mark.parametrize("path", ["dataset.limit", "run_id", "task", "job.mock", "job.api_cost_cap_usd", "job.max_wall_seconds", "job.mode",
                                  "job", "trace", "trace.tags", "trace.sink", "job.mock.x", "job.api_cost_cap_usd.x"])
def test_levers_cannot_touch_what_the_study_owns(path):
    # ``job`` (a prefix of the forbidden job.* paths) would replace the caps wholesale; ``trace`` carries the study's tags
    with pytest.raises(ValueError, match="set by the study"):
        lever(patch={path: 1})


@pytest.mark.parametrize("path", ["job.max_retries", "job.concurrency", "reviewer.classes.contract", "confidence.judge_max_passes"])
def test_levers_may_still_patch_the_rest_of_the_job_block(path):
    assert lever(patch={path: 1}).patch == {path: 1}


@pytest.mark.parametrize("value", [0.0, 0.49, 10.01, float("nan"), float("inf"), -1.0])
def test_a_levers_estimate_safety_is_finite_and_between_half_and_ten(value):
    with pytest.raises(ValueError):
        lever(patch={"reviewer.classes.contract": 0.4}, estimate_safety=value)


@pytest.mark.parametrize("value", [0.5, 1.0, 2.0, 10.0])
def test_a_levers_estimate_safety_in_range_is_accepted(value):
    assert lever(patch={"reviewer.classes.contract": 0.4}, estimate_safety=value).estimate_safety == value


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
    # absolute: the winner's own route on the role it keeps, the base route (here none: deleted) on the one it restores
    assert only_judge.patch == {"agent_routes.judge": {"provider": "openrouter", "model": "m"}, "agent_routes.boss": None}
    assert derived["sup-x@boss"].patch == {"agent_routes.boss": {"provider": "openrouter", "model": "m"},
                                           "agent_routes.judge": {"provider": "openrouter", "model": "base"}}
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


# ---- placements stay correct after later keeps and after a later tier supersedes the winner -------------------

ROLES = ["judge", "arbiter", "boss"]


def route(model):
    return {"provider": "openrouter", "model": model}


def sup(lever_id, model, tier=1, **kw):
    return lever(id=lever_id, node=ROLES, group="sup", tier=tier, patch={f"agent_routes.{r}": route(model) for r in ROLES}, **kw)


def placement_catalog(*levers):
    return lv.Catalog(levers=list(levers), placements=[lv.Placement(
        group="sup", roles=ROLES, keep_on=[["judge"], ["arbiter"], ["boss"], ["judge", "arbiter"]])])


def kept(lever_id, **before):
    return {"lever": lever_id, "decision": "keep", "delta": {"mean": 0.1}, "patch_before": before}


def champion_after(spec, *levers):
    for item in levers:
        spec = lv.apply_patch(spec, item.patch)
    return spec


def models(spec):
    return {r: (spec.get("agent_routes", {}).get(r) or {}).get("model") for r in ROLES}


def test_placement_patches_are_absolute_so_they_survive_a_kept_placement():
    """Winner kept, then placement A kept, then placement B: B must still put the winner on ITS roles."""
    cat = placement_catalog(sup("w", "strong"))
    base = {"agent_routes": {"judge": route("base"), "boss": route("base")}}
    rows = [kept("w", **{"agent_routes.judge": route("base"), "agent_routes.arbiter": None, "agent_routes.boss": route("base")})]
    champ = champion_after(base, cat.levers[0])
    assert models(champ) == {"judge": "strong", "arbiter": "strong", "boss": "strong"}
    derived = {item.id: item for item in lv.derive_placements(cat, base, rows)}
    a = derived["w@judge"]
    champ_a = lv.apply_patch(champ, a.patch)
    assert models(champ_a) == {"judge": "strong", "arbiter": None, "boss": "base"}          # arbiter had no route before w
    rows.append({"lever": a.id, "decision": "keep", "delta": {"mean": 0.0}})
    # the derivation reads the winner's row, not the champion: the same placements come back unchanged
    again = {item.id: item for item in lv.derive_placements(cat, base, rows)}
    assert {k: v.patch for k, v in again.items()} == {k: v.patch for k, v in derived.items()}
    champ_b = lv.apply_patch(champ_a, again["w@arbiter"].patch)
    assert models(champ_b) == {"judge": "base", "arbiter": "strong", "boss": "base"}        # judge went back, arbiter is the winner
    champ_c = lv.apply_patch(champ_b, again["w@judge+arbiter"].patch)
    assert models(champ_c) == {"judge": "strong", "arbiter": "strong", "boss": "base"}


def test_a_later_tier_supersedes_the_winner_and_restores_to_the_tier_before_it():
    t1, t2 = sup("w1", "tier1-model"), sup("w2", "tier2-model", tier=2, requires=[{"kept_lever": "w1"}])
    cat = placement_catalog(t1, t2)
    base = {"agent_routes": {"judge": route("base"), "boss": route("base")}}
    before_w1 = {"agent_routes.judge": route("base"), "agent_routes.arbiter": None, "agent_routes.boss": route("base")}
    rows = [kept("w1", **before_w1)]
    assert {i.id for i in lv.derive_placements(cat, base, rows)} == {f"w1@{s}" for s in ("judge", "arbiter", "boss", "judge+arbiter")}
    before_w2 = {f"agent_routes.{r}": route("tier1-model") for r in ROLES}               # the champion after w1
    rows.append(kept("w2", **before_w2))
    derived = {item.id: item for item in lv.derive_placements(cat, base, rows)}
    assert not any(i.startswith("w1@") for i in derived)                                   # w1 is superseded: it would put tier 1 back
    assert set(derived) == {f"w2@{s}" for s in ("judge", "arbiter", "boss", "judge+arbiter")}
    champ = champion_after(champion_after(base, t1), t2)
    only_boss = lv.apply_patch(champ, derived["w2@boss"].patch)
    assert models(only_boss) == {"judge": "tier1-model", "arbiter": "tier1-model", "boss": "tier2-model"}   # restored to w1, not base


def test_a_later_lever_patching_a_child_or_parent_path_also_supersedes_the_winner():
    t1 = sup("w1", "tier1-model")
    child = lever(id="w2", node=["judge"], group="sup", tier=2, patch={"agent_routes.judge.model": "tier2-model"})
    parent = lever(id="w3", node=["judge"], group="sup", tier=2, patch={"agent_routes": {"judge": route("tier3-model")}})
    for later in (child, parent):
        rows = [kept("w1"), kept(later.id)]
        assert not any(i.id.startswith("w1@") for i in lv.derive_placements(placement_catalog(t1, later), {}, rows))
    assert lv._paths_overlap("agent_routes.judge", "agent_routes.judge.model")
    assert not lv._paths_overlap("agent_routes.judge", "agent_routes.judge_v2")


def test_a_reverted_later_tier_does_not_supersede_the_winner():
    t1, t2 = sup("w1", "tier1-model"), sup("w2", "tier2-model", tier=2)
    cat = placement_catalog(t1, t2)
    rows = [kept("w1"), {"lever": "w2", "decision": "revert", "delta": {"mean": 0.0}}]
    assert any(i.id.startswith("w1@") for i in lv.derive_placements(cat, {}, rows))


def test_a_row_without_patch_before_falls_back_to_the_base_spec():
    cat = placement_catalog(sup("w", "strong"))
    base = {"agent_routes": {"boss": route("base")}}
    derived = {i.id: i for i in lv.derive_placements(cat, base, [{"lever": "w", "decision": "keep", "delta": {"mean": 0.1}}])}
    assert derived["w@judge"].patch["agent_routes.boss"] == route("base") and derived["w@judge"].patch["agent_routes.arbiter"] is None


def test_placements_inherit_the_winners_round_cap_policy():
    cat = placement_catalog(sup("w", "strong", round_cap_auto=True))
    assert all(i.round_cap_auto for i in lv.derive_placements(cat, {}, [kept("w")]))


# ---- aborted_cap counts as decided, never as a revert ---------------------------------------------------------

def test_an_aborted_cap_tier_one_lever_does_not_block_tier_two():
    cat = _ladder()
    t2 = next(item for item in cat.levers if item.id == "t2")
    met = lambda rows: lv.requirement_met(t2, cat.levers, rows)  # noqa: E731
    assert met([row("t11", "revert", 0.02), {"lever": "t12", "decision": "aborted_cap"}])        # decided = revert or aborted_cap
    assert not met([row("t11", "revert", -0.02), {"lever": "t12", "decision": "aborted_cap"}])   # a revert still needs a positive mean
    assert not met([row("t11", "revert", 0.02)])                                                  # t12 undecided


# ---- the reviewer is a Decisions-API model or the omitted chat reviewer ---------------------------------------------

PAID = {**BASE, "job": {"mode": "endpoint", "mock": False, "max_wall_seconds": 600, "api_cost_cap_usd": 1}}
PAID.pop("reviewer")
DECISIONS = {"backend": "decisions", "model": "openai/gpt-6-luna-decisions", "questions": "reviewer_decisions_v2",
             "classes": {"contract": 0.78}}


def test_the_chat_reviewer_baseline_and_a_decisions_reviewer_are_allowed_in_a_paid_study():
    assert lv.reviewer_errors(PAID) == []                                       # no reviewer block: the chat sorter_reviewer
    assert lv.reviewer_errors({**PAID, "reviewer": DECISIONS}) == []


@pytest.mark.parametrize("block, needle", [
    ({"backend": "api", "model": "openai/gpt-4o", "allow_chat_model": True, "classes": {"contract": 0.5}}, "allow_chat_model"),
    ({"backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.5}}, "backend 'jev'"),
    ({"backend": "local", "model": "Qwen/Qwen3-8B", "classes": {"contract": 0.5}}, "backend 'local'"),
    ({"backend": "mock", "model": "mock", "classes": {"contract": 0.5}}, "backend 'mock'"),
])
def test_a_paid_study_refuses_a_non_decisions_reviewer(block, needle):
    errors = lv.reviewer_errors({**PAID, "reviewer": block})
    assert any(needle in e for e in errors), errors
    # the same spec in a mock study is untouched
    assert lv.reviewer_errors({**PAID, "job": {**PAID["job"], "mock": True}, "reviewer": block}) == []


def test_a_decisions_reviewer_that_is_not_a_catalog_model_is_refused_with_the_spec_error():
    errors = lv.reviewer_errors({**PAID, "reviewer": {**DECISIONS, "model": "typesafe/jev-router"}})
    assert any("Decisions-API model" in e for e in errors), errors      # the validated spec itself refuses it


@pytest.mark.parametrize("block", [
    {"backend": "api", "model": "openai/gpt-4o", "allow_chat_model": True, "classes": {"contract": 0.5}},
    {"backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.5}},
    {"backend": "local", "model": "Qwen/Qwen3-8B", "classes": {"contract": 0.5}},
])
def test_validate_catalog_refuses_such_a_reviewer_lever_on_a_paid_base(block):
    bad = lever(id="bad-rev", patch={"reviewer": block})
    problems = lv.validate_catalog(lv.Catalog(levers=[bad]), PAID)
    assert any("bad-rev" in p for p in problems), problems


def test_validate_catalog_refuses_a_paid_base_with_a_non_decisions_reviewer():
    base = {**PAID, "reviewer": {"backend": "mock", "model": "mock", "classes": {"contract": 0.5}}}
    ok = lever(id="ok", patch={"reviewer": DECISIONS})
    assert any(p.startswith("base spec:") for p in lv.validate_catalog(lv.Catalog(levers=[ok]), base))
    assert lv.validate_catalog(lv.Catalog(levers=[ok]), PAID) == []


def test_a_lever_may_not_set_both_round_cap_fields():
    with pytest.raises(ValueError, match="not both"):
        lever(patch={"reviewer.classes.contract": 0.4}, round_cap_usd=2.0, round_cap_auto=True)


# ---- the production catalog after the window rework --------------------------------------------------------------

def test_the_five_window_levers_that_lowered_the_baseline_window_are_gone():
    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    windows = {i.id: i for i in cat.levers if any("max_input_chars" in p for p in i.patch)}
    assert set(windows) == {"merger-agreement-window-400k"}
    only = windows["merger-agreement-window-400k"]
    assert only.patch == {"agent_knobs.merger_agreement_specialist.max_input_chars": 400000}
    assert "Narrower window" in only.description and "chunking long mergers" in only.description


def test_every_supervisor_lever_derives_its_round_cap_and_call_adding_levers_scale_the_estimate():
    cat = lv.load_levers(ROOT / "config/autoresearch/levers.yaml")
    sups = [i for i in cat.levers if i.group == "supervisor"]
    assert sups and all(i.round_cap_auto for i in sups)
    calls = {"judge-all-merger-agreement", "judge-all-contract", "judge-all-correspondence", "judge-all-insurance-claim", "judge-all-corporate-record",
             "judge-rejudge-retry", "judge-max-passes-2"}
    assert {i.id for i in cat.levers if i.estimate_safety} == calls | {i.id for i in sups}
    assert all(i.estimate_safety == 2.0 for i in cat.levers if i.id in calls)
    # a reasoning or verbose supervisor emits more completion tokens than the champion's measured ones
    assert all(i.estimate_safety == 1.5 for i in sups)


def test_placements_inherit_the_winners_estimate_safety():
    cat = placement_catalog(sup("w", "strong", round_cap_auto=True, estimate_safety=1.5))
    derived = lv.derive_placements(cat, {}, [kept("w")])
    assert derived and all(i.estimate_safety == 1.5 for i in derived)


# ---- the tier ladder: decided levers, one positive revert, retryable errors ------------------------------------------

def _t2():
    cat = _ladder()
    t2 = next(item for item in cat.levers if item.id == "t2")
    return cat, lambda rows: lv.requirement_met(t2, cat.levers, rows)


def test_a_tier_whose_levers_were_all_aborted_stays_closed():
    _, met = _t2()
    aborted = lambda i: {"lever": i, "decision": "aborted_cap"}  # noqa: E731
    assert not met([aborted("t11"), aborted("t12")])         # aborts alone never open a dearer tier
    assert not met([aborted("t11"), {"lever": "t12", "decision": "skipped"}])   # nor aborts plus skips


def test_one_positive_revert_with_the_rest_aborted_or_skipped_opens_the_next_tier():
    _, met = _t2()
    assert met([row("t11", "revert", 0.02), {"lever": "t12", "decision": "aborted_cap"}])
    assert met([row("t11", "revert", 0.02), {"lever": "t12", "decision": "skipped"}])
    assert not met([row("t11", "revert", 0.02)])                                          # t12 still undecided
    assert not met([row("t11", "revert", 0.02), {"lever": "t12", "decision": "aborted_cap"},
                    row("t12", "revert", -0.01)])                                          # the latest row of t12 is a negative revert


def test_an_error_is_retryable_once_then_decided_without_a_verdict():
    _, met = _t2()
    err = lambda i: {"lever": i, "decision": "error"}  # noqa: E731
    assert lv.settled([err("t12")]) == set()                                  # one error: proposed again
    assert lv.settled([err("t12"), err("t12")]) == {"t12"}                    # two: settled
    assert not met([row("t11", "revert", 0.02), err("t12")])                   # retryable: the tier waits
    assert met([row("t11", "revert", 0.02), err("t12"), err("t12")])           # decided without a verdict
    assert met([row("t11", "revert", 0.02), err("t12"), row("t12", "revert", 0.01)])   # the retry succeeded
    assert not met([row("t11", "revert", 0.02), err("t12"), row("t12", "revert", -0.01)])
    assert not met([err("t11"), err("t11"), err("t12"), err("t12")])           # no positive revert at all: closed
    assert lv.settled([err("t12"), {"lever": "t12", "decision": "skipped"}]) == {"t12"}
    assert met([row("t11", "revert", 0.02), err("t12"), {"lever": "t12", "decision": "skipped"}])


# ---- review: condition shapes, group matching, placements, variants, validated mock ---------------------------

@pytest.mark.parametrize("requires", [
    [{"kept": {"grp": "g"}}], [{"kept": "g"}], [{"kept": {"group": "g", "tier": "1"}}], [{"kept": {"group": "g", "tier": True}}],
    [{"all_reverted_positive": {"tier": 1}}], [{"all_reverted_positive": ["g"]}],
    [{"kept_lever": 3}], [{"kept_lever": ""}],
    [{"budget_multiple": "abc"}], [{"budget_multiple": True}], [{"budget_multiple": 0}], [{"budget_multiple": float("nan")}],
])
def test_a_requires_condition_of_the_wrong_shape_fails_at_load(requires):
    with pytest.raises(ValueError, match="requires condition"):
        lever(patch={"reviewer.classes.contract": 0.4}, requires=requires)


@pytest.mark.parametrize("requires", [
    [{"kept": {"group": "g"}}], [{"kept": {"group": "g", "tier": 2}, "budget_multiple": 2.5}],
    [{"all_reverted_positive": {"group": "g", "tier": 1}}], [{"kept_lever": "other"}], [{"budget_multiple": 3}],
])
def test_a_well_shaped_requires_condition_loads(requires):
    assert lever(patch={"reviewer.classes.contract": 0.4}, requires=requires).requires == requires


def test_a_requires_group_without_a_tier_matches_any_tier_of_that_group():
    tiered = lever(id="t", patch={"reviewer.classes.contract": 0.4}, group="g", tier=2)
    needs_any = lever(id="n", patch={"reviewer.classes.contract": 0.3}, requires=[{"kept": {"group": "g"}}])
    needs_t1 = lever(id="m", patch={"reviewer.classes.contract": 0.2}, requires=[{"kept": {"group": "g", "tier": 1}}])
    problems = lv.validate_catalog(lv.Catalog(levers=[tiered, needs_any, needs_t1]), BASE)
    assert not any("lever n:" in p for p in problems), problems            # no tier: any tier of g
    assert any("lever m:" in p and "empty group/tier" in p for p in problems)   # an exact tier that nothing has


def _placement_cat(path="agent_routes.{role}", group="sup", keep_on=None, patch=None):
    winner = lever(id="w", node=["judge", "boss"], group=group if group else None, patch=patch or {
        "agent_routes.judge": {"provider": "openrouter", "model": "m"}, "agent_routes.boss": {"provider": "openrouter", "model": "m"}})
    place = lv.Placement(group="sup", roles=["judge", "boss"], keep_on=keep_on or [["judge"]], path=path)
    return lv.Catalog(levers=[winner], placements=[place])


def test_a_sound_placement_passes_the_catalog_check():
    assert lv.validate_catalog(_placement_cat(), BASE) == []


def test_a_placement_path_with_a_stray_brace_is_a_catalog_problem_not_a_late_keyerror():
    problems = lv.validate_catalog(_placement_cat(path="agent_routes.{rol}"), BASE)
    assert any("placement 0" in p and "does not derive a valid lever" in p for p in problems), problems


@pytest.mark.parametrize("path", ["agent_routes.{role.missing}", "agent_routes.{0}", "agent_routes.{role!x}"])
def test_any_placement_format_error_is_a_catalog_problem_not_a_crash(path):
    problems = lv.validate_catalog(_placement_cat(path=path), BASE)
    assert any("placement 0" in p and "does not derive a valid lever" in p for p in problems), problems


def test_a_placement_under_a_forbidden_root_is_a_catalog_problem():
    problems = lv.validate_catalog(_placement_cat(path="trace.{role}"), BASE)
    assert any("placement 0" in p and "set by the study" in p for p in problems), problems


def test_a_placement_whose_group_matches_no_lever_is_a_catalog_problem():
    cat = _placement_cat(group="other")
    assert any("no lever has this group" in p for p in lv.validate_catalog(cat, BASE))


def test_a_derived_placement_that_is_not_a_valid_run_spec_is_a_catalog_problem():
    bad = {"agent_routes.judge": {"provider": "openrouter", "model": "m"}, "agent_routes.boss": {"provider": "no-such-provider", "model": "m"}}
    problems = lv.validate_catalog(_placement_cat(patch=bad, keep_on=[["boss"]]), BASE)
    assert any(p.startswith("placement 0") for p in problems), problems


def test_a_quoted_false_mock_is_a_paid_spec_for_the_reviewer_guard():
    block = {"backend": "api", "model": "openai/gpt-4o", "allow_chat_model": True, "classes": {"contract": 0.5}}
    quoted = {**PAID, "job": {**PAID["job"], "mock": "false"}, "reviewer": block}
    errors = lv.reviewer_errors(quoted)
    assert any("allow_chat_model" in e for e in errors), errors            # raw truthiness would have skipped every check
    assert lv.reviewer_errors({**quoted, "job": {**quoted["job"], "mock": "true"}}) == []


def test_an_invalid_spec_is_returned_as_a_problem_not_skipped():
    assert lv.reviewer_errors({**PAID, "task": "no-such-task"})


def test_the_context_check_resolves_a_variant_reviewer_to_its_base_window(monkeypatch):
    from mailroom_sandbox import decision_backends as db

    monkeypatch.setattr(db, "decision_model", lambda m: {"context_length": 1000} if m == "vendor/dec" else None)
    monkeypatch.setattr(db, "load_question_set", lambda stem: {"max_input_chars": 100_000})
    block = {"model": "vendor/dec:nitro", "questions": "q", "backend": "decisions"}
    assert any("over its 1,000-token context" in e for e in lv.context_errors({"reviewer": block}))
    assert any("over its 1,000-token context" in e for e in lv.context_errors({"reviewer": {**block, "model": "vendor/dec"}}))
    assert lv.context_errors({"reviewer": {**block, "model": "vendor/other:nitro"}}) == []


def test_the_context_check_prices_an_omitted_input_cap_at_what_execution_falls_back_to(monkeypatch):
    """A question set with no max_input_chars was sized at 0 chars; execution sends up to
    DECISIONS_MAX_INPUT_CHARS, so a small-window model was never flagged."""
    from mailroom_sandbox import decision_backends as db

    monkeypatch.setattr(db, "decision_model", lambda m: {"context_length": 100_000} if m == "vendor/dec" else None)
    block = {"model": "vendor/dec", "questions": "q", "backend": "decisions"}
    monkeypatch.setattr(db, "load_question_set", lambda stem: {})
    errors = lv.context_errors({"reviewer": block})
    assert len(errors) == 1 and f"max_input_chars {db.DECISIONS_MAX_INPUT_CHARS:,}" in errors[0], errors
    monkeypatch.setattr(db, "load_question_set", lambda stem: {"max_input_chars": 40_000})      # an explicit smaller cap stands
    assert lv.context_errors({"reviewer": block}) == []
    gate = {"model": "vendor/dec", "questions": "q"}
    monkeypatch.setattr(db, "load_question_set", lambda stem: {"max_input_chars": 40_000, "max_input_chars_by_class": {"contract": 900_000}})
    assert any("max_input_chars 900,000" in e for e in lv.context_errors({"extraction_gate": gate}))      # a class may cap higher
    assert lv.context_errors({"reviewer": block}) == []                                                # the reviewer has no per-class cap


def test_the_context_check_reserves_the_questions_execution_sends(monkeypatch):
    """A set whose questions outgrow the default 4,000-token reserve needs that much more room,
    as at execution (decision_backends.decision_input_cap); otherwise the cap is silently cut."""
    from mailroom_sandbox import decision_backends as db

    qset = db.load_question_set("reviewer_decisions_v4.2.0")
    sent = db.lane_question_chars("reviewer", qset)
    reserve = int(sent * db.DECISIONS_TOKENS_PER_CHAR) + 1000
    assert reserve > db.DECISIONS_QUESTION_TOKENS
    cap = int(qset["max_input_chars"])
    edge = int(cap * db.DECISIONS_TOKENS_PER_CHAR) + db.DECISIONS_QUESTION_TOKENS + 100  # fits the old reserve only
    monkeypatch.setattr(db, "decision_model", lambda m: {"context_length": edge} if m == "vendor/dec" else None)
    block = {"model": "vendor/dec", "questions": "reviewer_decisions_v4.2.0", "backend": "decisions"}
    errors = lv.context_errors({"reviewer": block})
    assert len(errors) == 1 and f"~{int(cap * db.DECISIONS_TOKENS_PER_CHAR) + reserve:,} tokens" in errors[0], errors


def test_the_context_check_reads_a_reviewer_input_override(monkeypatch):
    """A spec's ``reviewer.max_input_chars`` raises the set's cap (never lowers it), as at execution,
    so a raise past the model's window is caught before the lever runs."""
    from mailroom_sandbox import decision_backends as db

    qset = db.load_question_set("reviewer_decisions_v4.2.0")
    cap = int(qset["max_input_chars"])
    window = int(cap * db.DECISIONS_TOKENS_PER_CHAR) + 50_000  # holds the set's own cap
    monkeypatch.setattr(db, "decision_model", lambda m: {"context_length": window} if m == "vendor/dec" else None)
    block = {"model": "vendor/dec", "questions": "reviewer_decisions_v4.2.0", "backend": "decisions"}
    assert lv.context_errors({"reviewer": block}) == []
    assert lv.context_errors({"reviewer": {**block, "max_input_chars": cap // 2}}) == []
    (error,) = lv.context_errors({"reviewer": {**block, "max_input_chars": cap * 2}})
    assert f"max_input_chars {cap * 2:,}" in error
