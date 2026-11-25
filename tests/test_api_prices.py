"""Tiered API pricing: config/api_prices.yaml, call_price/call_cost, task_agents, budget tiers."""
from __future__ import annotations

import sys

import pytest
import yaml

from mailroom_sandbox.job import metrics
from mailroom_sandbox.job.api_budget import task_agents
from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
sys.path.insert(0, str(ROOT / "scripts"))
import refresh_api_prices  # noqa: E402


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    for env in ("SANDBOX_TOKEN_PRICE", "SANDBOX_TOKEN_PRICE_USD_PER_1M", "OPENROUTER_TOKEN_PRICE"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(metrics, "_token_price_override", lambda: None)


def _prices() -> dict:
    return yaml.safe_load((ROOT / "config" / "api_prices.yaml").read_text(encoding="utf-8"))


def test_qwen37_flash_full_sheet_is_listed():
    row = _prices()["models"]["qwen/qwen3.7-flash"]
    assert row["context_length"] == 1_000_000 and row["max_completion_tokens"] == 65536
    assert [t["min_prompt_tokens"] for t in row["tiers"]] == [0, 32000, 256000]
    assert {"prompt", "completion", "cache_read", "cache_write"} <= set(row["tiers"][0])


def test_profile_api_models_all_priced():
    profile = yaml.safe_load((ROOT / "config" / "profiles" / "openrouter.yaml").read_text(encoding="utf-8"))
    assert "qwen/qwen3.7-flash" in profile["api_models"]
    for model in profile["api_models"]:
        assert metrics.price_sheet(model), model


def test_file_sheets_match_builtin_fallback():
    file_sheets = {k: [{f: t[f] for f in ("min_prompt_tokens", "prompt", "completion")} for t in v["tiers"]]
                   for k, v in _prices()["models"].items()}
    for model, sheet in metrics.API_PRICE_SHEETS.items():
        assert file_sheets[model] == [{f: t[f] for f in ("min_prompt_tokens", "prompt", "completion")} for t in sheet]


@pytest.mark.parametrize("tokens,price", [(0, (0.03, 0.13)), (31_999, (0.03, 0.13)), (32_000, (0.10, 0.40)),
                                          (255_999, (0.10, 0.40)), (256_000, (0.20, 0.80))])
def test_call_price_tiers(tokens, price):
    assert metrics.call_price("qwen/qwen3.7-flash", tokens) == pytest.approx(price)


def test_decisions_id_not_priced_as_chat_model():
    assert metrics.call_price("openai/gpt-6-luna-decisions-20261006", 300_000) == (0.10, 0.0)
    assert metrics.call_price("openai/gpt-6-luna-20261006", 300_000) == (0.20, 0.75)


def test_provider_cost_is_kept_only_when_every_call_reports_one():
    from mailroom_sandbox.job import usage_capture as uc

    uc.reset_usage()
    uc.note_provider_call({
        "prompt_tokens": 1000, "completion_tokens": 10, "cost": 0.01,
        "prompt_tokens_details": {"cached_tokens": 800, "cache_write_tokens": 50},
    })
    assert uc.provider_calls()[0]["cached"] == 800 and uc.provider_calls()[0]["cache_write"] == 50
    assert uc._reported_cost(uc.provider_calls()) == pytest.approx(0.01)
    uc.note_provider_call({"prompt_tokens": 10, "completion_tokens": 1})
    assert uc._reported_cost(uc.provider_calls()) is None
    uc.note_provider_call({"prompt_tokens": 1.5, "completion_tokens": 1, "cost": 1})
    assert len(uc.provider_calls()) == 2  # a non-integer count is not a recorded call
    uc.reset_usage()
    assert uc.provider_calls() == []
    uc.note_pending_provider_cost(0.02)
    uc.note_provider_call({"prompt_tokens": 100, "completion_tokens": 4})
    assert uc.provider_calls()[-1]["cost"] == pytest.approx(0.02)
    uc.note_provider_call({"prompt_tokens": 10, "completion_tokens": 1})
    assert uc.provider_calls()[-1]["cost"] is None  # the held cost is consumed by the matching call
    uc.reset_usage()
    uc.note_pending_provider_cost(0.02)
    uc.note_provider_call({"prompt_tokens": 1.5, "completion_tokens": 1})  # rejected: not a whole number
    uc.note_provider_call({"prompt_tokens": 10, "completion_tokens": 1})
    assert uc.provider_calls()[-1]["cost"] is None  # a rejected call does not leave its cost for the next one
    uc.reset_usage()
    uc.note_provider_call({
        "input_tokens": 1000, "output_tokens": 10,
        "input_token_details": {"cache_read": 800, "cache_creation": 50},
    })
    assert uc.provider_calls()[-1]["cached"] == 800 and uc.provider_calls()[-1]["cache_write"] == 50


def test_call_cost_bills_cached_prompt_tokens_at_the_cache_rate():
    """Cached tokens sit inside the prompt total and are not billed again at the prompt rate."""
    model = "deepseek/deepseek-v4.1-flash-1017"
    full = metrics.call_cost(model, 1_000, 100)
    cached = metrics.call_cost(model, 1_000, 100, cached_tokens=800)
    assert full == pytest.approx((1_000 * 0.30 + 100 * 1.20) / 1e6)
    assert cached == pytest.approx((200 * 0.30 + 800 * 0.006 + 100 * 1.20) / 1e6)
    assert cached < full
    item_cost, approx = metrics.item_calls_cost(model, {"call_usage": [[1_000, 100, 800, 0]]})
    assert item_cost == pytest.approx(cached) and approx is False


def test_call_cost_prices_each_call_at_its_tier():
    one_long = metrics.call_cost("qwen/qwen3.7-flash", 100_000, 1_000)
    ten_short = metrics.call_cost("qwen/qwen3.7-flash", 100_000, 1_000, calls=10)
    assert one_long == pytest.approx((100_000 * 0.10 + 1_000 * 0.40) / 1e6)
    assert ten_short == pytest.approx((100_000 * 0.03 + 1_000 * 0.13) / 1e6)


def test_missing_file_falls_back_to_builtin(monkeypatch):
    monkeypatch.setattr(metrics, "_FILE_SHEETS", {})
    assert metrics.call_price("qwen/qwen3.7-flash", 40_000) == pytest.approx((0.10, 0.40))


@pytest.mark.parametrize("lock,expected", [
    ({"task": "isolated", "job": {}}, {"sorter"}),
    # The isolated runner always runs the sorter spec, so job.task cannot hide its model.
    ({"task": "isolated", "job": {"task": "judge"}}, {"sorter"}),
    ({"task": "contract_specialist"}, {"contract_specialist"}),
    ({"task": "pipeline"}, None),
])
def test_task_agents(lock, expected):
    assert task_agents(lock) == expected


def test_refresh_sheet_from_catalog_and_drift():
    entry = {"id": "x/m", "context_length": 1000, "top_provider": {"max_completion_tokens": 10},
             "pricing": {"prompt": "0.00000003", "completion": "0.00000013",
                         "overrides": [{"min_prompt_tokens": 32000, "prompt": "0.0000001", "completion": "0.0000004"}]}}
    row = refresh_api_prices.sheet_from_catalog(entry)
    assert row["tiers"] == [{"min_prompt_tokens": 0, "prompt": 0.03, "completion": 0.13},
                            {"min_prompt_tokens": 32000, "prompt": 0.1, "completion": 0.4}]
    doc = {"models": {"x/m": row, "y/decisions": {"endpoint": "/d", "tiers": []}}}
    same, changed = refresh_api_prices.refresh(doc, {"x/m": entry}, today="2026-11-02")
    assert changed == [] and same == doc
    entry["pricing"]["prompt"] = "0.00000005"
    _, changed = refresh_api_prices.refresh(doc, {"x/m": entry}, today="2026-11-02")
    assert changed == ["x/m"]


def test_time_of_day_windows_are_not_prompt_tiers():
    """OpenRouter time windows (utc_days / utc_start) fold into the base tier at their highest price."""
    entry = {"id": "x/w", "context_length": 1000, "top_provider": {},
             "pricing": {"prompt": "0.0000003", "completion": "0.0000012", "input_cache_read": "0.000000006",
                         "overrides": [
                             {"utc_days": ["saturday"], "prompt": "0.00000015", "completion": "0.0000006"},
                             {"utc_days": ["monday"], "utc_start": 100, "utc_end": 400, "prompt": "0.0000004"},
                             {"min_prompt_tokens": 64000, "prompt": "0.0000006", "completion": "0.0000024"}]}}
    row = refresh_api_prices.sheet_from_catalog(entry)
    assert row["tiers"] == [{"min_prompt_tokens": 0, "prompt": 0.4, "completion": 1.2, "cache_read": 0.006},
                            {"min_prompt_tokens": 64000, "prompt": 0.6, "completion": 2.4}]
    assert row["time_windows"] == 2
    entry["pricing"]["overrides"] = entry["pricing"]["overrides"][2:]
    out, _ = refresh_api_prices.refresh({"models": {"x/w": row}}, {"x/w": entry}, today="2026-11-18")
    assert "time_windows" not in out["models"]["x/w"]


def test_refresh_prices_an_alias_at_its_canonical_slug_row():
    """When the dated slug is its own catalog row, that row's price wins over the alias."""
    alias = {"id": "org/model", "canonical_slug": "org/model-20261101", "context_length": 1000,
             "top_provider": {}, "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}}
    slug = {"id": "org/model-20261101", "canonical_slug": "org/model-20261101", "context_length": 2000,
            "top_provider": {"max_completion_tokens": 50},
            "pricing": {"prompt": "0.0000003", "completion": "0.0000004"}}
    catalog = {alias["id"]: alias, slug["id"]: slug}
    new, changed = refresh_api_prices.refresh({"models": {"org/model": {}}}, catalog, today="2026-11-25")
    row = new["models"]["org/model"]
    assert changed == ["org/model"]
    assert row["canonical_slug"] == "org/model-20261101"
    assert row["context_length"] == 2000 and row["max_completion_tokens"] == 50
    assert row["tiers"] == [{"min_prompt_tokens": 0, "prompt": 0.3, "completion": 0.4}]
    # A slug with no separate row keeps the alias row that declares it.
    lone = {"id": "org/only", "canonical_slug": "org/only-20260101", "context_length": 8,
            "top_provider": {}, "pricing": {"prompt": "0.0000005", "completion": "0.0000006"}}
    new, _ = refresh_api_prices.refresh({"models": {"org/only": {}}}, {"org/only": lone}, today="2026-11-25")
    assert new["models"]["org/only"]["tiers"][0]["prompt"] == 0.5
    assert new["models"]["org/only"]["canonical_slug"] == "org/only-20260101"


@pytest.mark.parametrize("model,prompt", [("typesafe/jev-1.14", 0.042), ("liquid/d1.2", 0.02), ("upstage/solar-decide", 0.05),
                                          ("google/gemini-decision-1", 0.1), ("perplexity/pplx-decider-v1.2", 0.02)])
def test_decision_models_price_from_the_catalog_input_only(model, prompt):
    assert metrics.call_price(model, 100_000) == pytest.approx((prompt, 0.0))
    assert metrics.call_cost(model, 1_000_000, 0) == pytest.approx(prompt)
    assert metrics.token_price_ceiling(model) == pytest.approx((prompt, 0.0))


def test_unknown_decision_sibling_is_not_priced_by_prefix():
    # liquid/d1.2 is a catalog id; a future liquid/d1.9 must stay unpriced.
    assert metrics.price_sheet("liquid/d1.9") is None


def test_a_variant_of_a_decisions_model_never_falls_to_a_chat_models_prefix_price(monkeypatch):
    from mailroom_sandbox import decision_backends as db

    chat = [{"min_prompt_tokens": 0, "prompt": 9.0, "completion": 9.0}]
    monkeypatch.setattr(metrics, "api_price_sheets", lambda: {"vendor/chat": chat})
    monkeypatch.setattr(db, "decision_catalog", lambda: {"vendor/chat-decider": {"prompt": 0.3}})
    assert metrics.price_sheet("vendor/chat-decider") == [{"min_prompt_tokens": 0, "prompt": 0.3, "completion": 0.0}]
    assert metrics.price_sheet("vendor/chat-decider:nitro") is None      # not the chat model's 9.0 USD, and not guessed
    assert metrics.price_sheet("vendor/chat-other:nitro") == chat        # an ordinary chat id keeps its prefix rule


def test_a_decisions_variant_is_refused_by_every_public_price_function_not_just_price_sheet(monkeypatch):
    """price_sheet refused the variant, but call_price / token_price_ceiling then reached token_price's
    prefix fallback and priced it at a chat model's rate."""
    from mailroom_sandbox import decision_backends as db

    monkeypatch.setattr(metrics, "api_price_sheets", lambda: {})
    monkeypatch.setattr(metrics, "SANDBOX_MODEL_PRICES", {"vendor/chat": (9.0, 9.0)})
    monkeypatch.setattr(db, "decision_catalog", lambda: {"vendor/chat-decider": {"prompt": 0.3}})
    variant = "vendor/chat-decider:nitro"
    assert metrics.token_price(variant) is None
    assert metrics.token_price_ceiling(variant) is None
    assert metrics.call_price(variant, 1000) is None
    assert metrics.call_cost(variant, 1000, 10) is None
    assert metrics.token_price("vendor/chat-other:nitro") == (9.0, 9.0)       # chat variants keep their prefix price
    assert metrics.token_price_ceiling("vendor/chat-decider") == pytest.approx((0.3, 0.0))   # the pinned base is priced
    monkeypatch.setattr(metrics, "SANDBOX_MODEL_PRICES", {"vendor/chat": (9.0, 9.0), variant: (0.5, 0.0)})
    assert metrics.token_price_ceiling(variant) == (0.5, 0.0)                 # an explicit row for the variant stands


@pytest.mark.parametrize("model", ["typesafe/jev-1.14:nitro", "perplexity/pplx-decider-v1.2:floor"])
def test_a_shipped_decisions_variant_has_no_price_so_a_paid_run_refuses_it(model):
    assert metrics.price_sheet(model) is None
    assert metrics.price_sheet(model.split(":")[0])                      # while its pinned base is priced


# ── the three candidate ledgers: core OpenRouter sheet, decisions catalog, Modal matrix ──


def test_every_models_yaml_openrouter_id_is_priced_or_a_decisions_model():
    """All experimental OpenRouter candidates the model catalog names carry a
    verified price: the core ``config/api_prices.yaml`` sheet for chat ids, the
    decisions catalog for Decisions ids — never an unpriced candidate."""
    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    decisions = set((yaml.safe_load((ROOT / "config" / "decision_models.yaml").read_text(encoding="utf-8"))
                     .get("models") or {}))
    chat: set[str] = set(models.get("openrouter_preference") or [])

    def _collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "openrouter" and isinstance(item, str):
                    chat.add(item)
                else:
                    _collect(item)
        elif isinstance(value, list):
            for item in value:
                _collect(item)

    _collect(models.get("map") or {})
    _collect(models.get("critical_tier") or {})
    assert chat, "models.yaml names no OpenRouter candidates"
    for model in sorted(chat):
        assert metrics.token_price(model) or model in decisions, model


def test_every_modal_models_row_carries_a_serve_posture():
    """The Modal experimental ledger (``config/models.yaml`` ``modal_models:``)
    stays deployable: every candidate row names its GPU, quantization, context
    cap and tensor-parallel size, so a new candidate cannot land half-specified."""
    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    rows = models.get("modal_models") or {}
    assert "Qwen/Qwen3.5-9B" in rows and "Qwen/Qwen3.5-35B-A3B" in rows and "Qwen/Qwen3.5-27B" in rows
    for model, row in rows.items():
        assert isinstance(row, dict), model
        for key in ("gpu", "quantization", "max_model_len", "tp_size"):
            assert key in row and row[key] is not None, f"{model}: missing {key}"
        assert row["gpu"], model
        assert int(row["tp_size"]) >= 1 and int(row["max_model_len"]) > 0, model
        assert "notes" in row, model


def test_the_granite_twin_pair_is_priced_on_both_legs():
    """A first-party twin pair (SAND-027) must be priced on BOTH legs: the
    OpenRouter chat id in the core sheet, the Modal FP8 serve form in the matrix."""
    assert metrics.price_sheet("ibm-granite/granite-4.2-8b")
    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert "ibm-granite/granite-4.2-8b-fp8" in (models.get("modal_models") or {})


def test_api_evals_cost_falls_back_to_the_core_ledger_not_its_own_pin(monkeypatch):
    """The api-evals harness must not carry a second, drift-prone price pin: its
    offline fallback is the CORE ledger row the sandbox bills with (network-free:
    the live refresh is stubbed off)."""
    api_evals_root = ROOT / "api-evals"
    monkeypatch.syspath_prepend(str(api_evals_root))
    import importlib

    cost = importlib.import_module("api_evals.cost")
    monkeypatch.setattr(cost, "live_prices", lambda model, timeout=15.0: None)
    assert cost.core_ledger_prices("qwen/qwen3.7-flash") == (0.03, 0.13)  # the core ledger's base tier
    # A Decisions id is priced input-only by the same ledger (no output charge):
    assert cost.core_ledger_prices("openai/gpt-6-luna-decisions") == (0.10, 0.0)
    assert cost.core_ledger_prices("vendor/unknown-model") is None  # the honest gap
    assert cost.resolve_prices("qwen/qwen3.7-flash") == (0.03, 0.13)
    assert cost.resolve_prices("vendor/unknown-model") is None
