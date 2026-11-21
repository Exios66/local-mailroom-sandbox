"""Context fit: whole-document budgets follow the agent's model window, not the L4 posture."""
from __future__ import annotations

import pytest

from mailroom_sandbox import context_fit, source_windows
from mailroom_sandbox.overlay import build_merged_taxonomy, load_profile

CONTEXTS = {"qwen/qwen3.7-flash": 1_000_000, "small/api-model": 16_384}


def _taxonomy(provider="openrouter", model="qwen/qwen3.7-flash", **extra):
    agent = {"provider": provider, "model": model, "max_tokens": 4096}
    return {
        "doc_classes": [
            {"key": "merger_agreement", "specialist": "merger_agreement_specialist"},
            {"key": "contract", "specialist": "contracts_specialist"},
        ],
        "agents": {
            "merger_agreement_specialist": {**agent, "max_input_chars": 36008},
            "contracts_specialist": {**agent, "max_input_chars": 18000},
            "judge": {**agent, "max_input_chars": 80000},
            "arbiter": {**agent, "max_input_chars": 100000},
            "sorter": {**agent, "max_input_chars": 12000},
        },
        "chunking": {"enabled": True, "chunk_chars": 90000, "overlap_chars": 8000},
        **extra,
    }


def test_long_context_api_agents_get_their_model_window():
    out = context_fit.apply_context_fit(_taxonomy(), contexts=CONTEXTS)
    expected = int((1_000_000 - 4096 - 8000) * 2.4)
    agents = out["agents"]
    assert agents["merger_agreement_specialist"]["max_input_chars"] == expected
    assert agents["judge"]["max_input_chars"] == expected
    # The vendored sorter windows the whole document at its budget: fitted, it reads one window.
    assert agents["sorter"]["max_input_chars"] == expected
    assert out["context_fit"]["applied"]["sorter"]["before"] == 12000
    assert out["chunking"]["chunk_chars"] == expected  # 418k-char mergers now fit one window
    applied = out["context_fit"]["applied"]
    assert applied["merger_agreement_specialist"] == {
        "model": "qwen/qwen3.7-flash", "context_length": 1_000_000, "before": 36008, "after": expected}
    assert out["context_fit"]["chunk_chars"] == {"before": 90000, "after": expected}


@pytest.mark.parametrize("provider", ["modal-vllm", "vllm", "ollama", "lmstudio"])
def test_local_and_modal_routes_keep_the_l4_posture(provider):
    out = context_fit.apply_context_fit(_taxonomy(provider=provider), contexts=CONTEXTS)
    assert out["agents"]["merger_agreement_specialist"]["max_input_chars"] == 36008
    assert out["chunking"]["chunk_chars"] == 90000
    assert out["context_fit"]["applied"] == {}


def test_unknown_model_or_smaller_window_never_lowers_a_budget():
    unknown = context_fit.apply_context_fit(_taxonomy(model="nobody/knows"), contexts=CONTEXTS)
    small = context_fit.apply_context_fit(_taxonomy(model="small/api-model"), contexts=CONTEXTS)
    for out in (unknown, small):
        assert out["agents"]["merger_agreement_specialist"]["max_input_chars"] == 36008
        assert "merger_agreement_specialist" not in out["context_fit"]["applied"]


def test_route_decides_the_provider_and_model():
    routes = {"judge": {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-9B"}}
    out = context_fit.apply_context_fit(_taxonomy(), agent_routes=routes, contexts=CONTEXTS)
    assert out["agents"]["judge"]["max_input_chars"] == 80000
    assert "judge" not in out["context_fit"]["applied"]


def test_chunk_cap_holds_while_an_unfitted_specialist_is_wider():
    tax = _taxonomy()
    tax["agents"]["contracts_specialist"].update(provider="modal-vllm", max_input_chars=120000)
    out = context_fit.apply_context_fit(tax, contexts=CONTEXTS)
    assert "merger_agreement_specialist" in out["context_fit"]["applied"]
    assert out["chunking"]["chunk_chars"] == 90000


def test_disabled_fit_changes_nothing():
    out = context_fit.apply_context_fit(_taxonomy(context_fit={"enabled": False}), contexts=CONTEXTS)
    assert out["agents"]["merger_agreement_specialist"]["max_input_chars"] == 36008
    assert out["context_fit"]["applied"] == {}


def test_price_sheet_lists_the_flash_context():
    assert context_fit.api_context_lengths()["qwen/qwen3.7-flash"] >= 1_000_000


def test_merged_taxonomy_fits_openrouter_but_not_modal():
    fitted = build_merged_taxonomy(load_profile("openrouter"), model_override="qwen/qwen3.7-flash")
    modal = build_merged_taxonomy(load_profile("modal-vllm"))
    assert fitted["agents"]["merger_agreement_specialist"]["max_input_chars"] > 1_000_000
    assert modal["agents"]["merger_agreement_specialist"]["max_input_chars"] == 36008
    assert modal["chunking"]["chunk_chars"] == 90000


def test_run_knobs_still_win_after_fitting():
    tax = build_merged_taxonomy(load_profile("openrouter"), model_override="qwen/qwen3.7-flash",
                                agent_knobs={"merger_agreement_specialist": {"max_input_chars": 98000},
                                             "judge": {"max_input_chars": 200000}})
    assert tax["agents"]["merger_agreement_specialist"]["max_input_chars"] == 98000
    assert context_fit.fitted_budget(tax, "judge") == 200000
    assert source_windows.windows_for(tax)["judge"] == 200000


def test_run_max_tokens_is_reserved_by_the_fit():
    base = build_merged_taxonomy(load_profile("openrouter"), model_override="qwen/qwen3.7-flash")
    wide = build_merged_taxonomy(load_profile("openrouter"), model_override="qwen/qwen3.7-flash",
                                 agent_knobs={"judge": {"max_tokens": 65536}})
    cfg = {**context_fit.DEFAULTS, **(base.get("context_fit") or {})}
    context = base["context_fit"]["applied"]["judge"]["context_length"]
    assert wide["agents"]["judge"]["max_tokens"] == 65536
    assert wide["agents"]["judge"]["max_input_chars"] == context_fit.fit_chars(context, 65536, cfg)
    assert wide["agents"]["judge"]["max_input_chars"] < base["agents"]["judge"]["max_input_chars"]


# --- judge/arbiter source windows (vendored literals) ----------------------------------

@pytest.fixture
def judge_mod():
    return pytest.importorskip("agents.judge")


@pytest.fixture
def arbiter_mod():
    return pytest.importorskip("agents.arbiter")


@pytest.fixture
def restore_windows(judge_mod, arbiter_mod):
    yield
    source_windows.apply_source_windows({})


def test_vendored_window_symbols_keep_their_shape(judge_mod, arbiter_mod):
    """Drift guard: a vendor refresh that renames these must fail here, not silently."""
    assert isinstance(judge_mod.JUDGE_SOURCE_CHARS, int)
    assert isinstance(arbiter_mod.SOURCE_CHARS, int)
    assert isinstance(arbiter_mod.CLASSIFICATION_SOURCE_CHARS, int)
    func = vars(judge_mod.CompletenessJudge)["_truncate"].__func__
    assert len(func.__defaults__) == 1


def test_widened_windows_reach_the_judge_and_arbiter(restore_windows, judge_mod, arbiter_mod):
    source_windows.apply_source_windows({"judge": 500_000, "arbiter": 400_000})
    assert judge_mod.JUDGE_SOURCE_CHARS == 500_000
    assert arbiter_mod.SOURCE_CHARS == 400_000 and arbiter_mod.CLASSIFICATION_SOURCE_CHARS == 400_000
    doc = "x" * 420_000
    assert judge_mod.CompletenessJudge._truncate(doc) == doc  # the whole merger agreement


def test_other_activations_restore_the_vendored_windows(restore_windows, judge_mod):
    source_windows.apply_source_windows({"judge": 500_000})
    vendored = source_windows.vendored_windows()
    source_windows.apply_source_windows({})
    assert judge_mod.JUDGE_SOURCE_CHARS == vendored["agents.judge.JUDGE_SOURCE_CHARS"]
    assert len(judge_mod.CompletenessJudge._truncate("y" * 100_000)) < 100_000


def test_windows_only_ever_rise(restore_windows, judge_mod):
    source_windows.apply_source_windows({"judge": 10})
    assert judge_mod.JUDGE_SOURCE_CHARS == source_windows.vendored_windows()["agents.judge.JUDGE_SOURCE_CHARS"]


def test_activation_widens_for_openrouter_and_restores_for_modal(monkeypatch, judge_mod, arbiter_mod):
    """End to end: runtime.activate installs the fitted windows and budgets per profile."""
    from mailroom_sandbox import runtime
    from pipeline.config import get_agent_config

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    try:
        runtime.activate("openrouter", model="qwen/qwen3.7-flash", load_env_file=False)
        assert judge_mod.JUDGE_SOURCE_CHARS > 1_000_000
        assert arbiter_mod.CLASSIFICATION_SOURCE_CHARS > 1_000_000
        assert get_agent_config("merger_agreement_specialist")["max_input_chars"] > 1_000_000
        runtime.activate("modal-vllm", load_env_file=False)
        vendored = source_windows.vendored_windows()
        assert judge_mod.JUDGE_SOURCE_CHARS == vendored["agents.judge.JUDGE_SOURCE_CHARS"]
        assert arbiter_mod.SOURCE_CHARS == vendored["agents.arbiter.SOURCE_CHARS"]
        assert get_agent_config("merger_agreement_specialist")["max_input_chars"] == 36008
    finally:
        source_windows.apply_source_windows({})


def test_expansion_status_swaps_openrouter_readers_and_leaves_modal():
    fitted = context_fit.expansion_status(
        build_merged_taxonomy(load_profile("openrouter"), model_override="qwen/qwen3.7-flash")
    )
    assert fitted["gaps"] == []
    by_name = {row["agent"]: row for row in fitted["agents"]}
    assert by_name["judge"]["expanded"] is True
    assert by_name["judge"]["source_window"] > 16_000
    assert by_name["arbiter"]["source_window"] > 16_000
    assert by_name["sorter"]["expanded"] is True and by_name["intake"]["expanded"] is True
    modal = context_fit.expansion_status(build_merged_taxonomy(load_profile("modal-vllm")))
    assert modal["gaps"] == []
    assert all(row["expanded"] is None for row in modal["agents"])


def test_expansion_status_flags_a_model_without_a_context_length():
    status = context_fit.expansion_status(
        build_merged_taxonomy(load_profile("openrouter"), model_override="nobody/knows")
    )
    assert any("nobody/knows" in gap for gap in status["gaps"])


def test_expansion_status_flags_a_knob_that_restores_the_short_budget():
    tax = build_merged_taxonomy(
        load_profile("openrouter"),
        model_override="qwen/qwen3.7-flash",
        agent_knobs={"judge": {"max_input_chars": 80000}},
    )
    status = context_fit.expansion_status(tax)
    assert any(gap.startswith("judge:") for gap in status["gaps"])
    kept = context_fit.expansion_status(build_merged_taxonomy(
        load_profile("openrouter"),
        model_override="qwen/qwen3.7-flash",
        agent_knobs={"judge": {"max_input_chars": 200000}},
    ))
    judge = next(row for row in kept["agents"] if row["agent"] == "judge")
    assert judge["expanded"] is True and judge["source_window"] == 200000


def test_the_overlay_fits_every_whole_document_reader():
    """API routes read each document in one call per reader (rb1 R01: ~100 sorter windows per merger)."""
    import yaml

    from mailroom_sandbox.paths import config_dir

    listed = set(yaml.safe_load((config_dir() / "taxonomy.overlay.yaml").read_text())["context_fit"]["agents"])
    assert {"specialists", "judge", "arbiter", "sorter", "sorter_reviewer", "intake"} <= listed
    assert set(context_fit.DEFAULTS["agents"]) == listed
