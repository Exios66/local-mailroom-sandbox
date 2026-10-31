"""SAND-089: priced API models, the API token spend ceiling, and design-informed budget advice."""
from __future__ import annotations

import pytest

from mailroom_sandbox.job import api_budget, budget_advice, spend
from mailroom_sandbox.job.metrics import token_price
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec
from mailroom_sandbox.services._exec import ServiceError


def _lock(**overrides):
    lock = {"engine": {"kind": "openrouter", "model": "qwen/qwen3.5-9b"},
            "job": {"mock": False, "mode": "endpoint", "max_wall_seconds": 1800, "api_cost_cap_usd": 0.25}}
    lock.update(overrides)
    return lock


@pytest.fixture(autouse=True)
def _no_price_override(monkeypatch):
    monkeypatch.delenv("SANDBOX_TOKEN_PRICE_IN_PER_M", raising=False)
    monkeypatch.delenv("SANDBOX_TOKEN_PRICE_OUT_PER_M", raising=False)


def test_the_openrouter_default_model_has_a_price():
    assert token_price("qwen/qwen3.5-9b") == (0.17, 0.25)


def test_api_models_come_from_the_engine_routes_and_assignments():
    assert api_budget.api_models(_lock()) == ["qwen/qwen3.5-9b"]
    hybrid = {"engine": {"kind": "modal-vllm", "model": "Qwen/Qwen3.5-9B"},
              "agent_routes": {"judge": {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash"}}}
    assert api_budget.api_models(hybrid) == ["deepseek/deepseek-v4-flash"]
    assert api_budget.api_models({"engine": {"kind": "modal-vllm", "model": "Qwen/Qwen3.5-9B"}}) == []


def test_a_paid_run_with_an_unpriced_api_model_is_refused():
    with pytest.raises(ServiceError, match="no token price for vendor/unpriced"):
        spend.require_budget(_lock(engine={"kind": "openrouter", "model": "vendor/unpriced"}))


def test_a_paid_api_run_needs_its_own_ceiling():
    with pytest.raises(ServiceError, match="api_cost_cap_usd"):
        spend.require_budget(_lock(job={"mock": False, "max_wall_seconds": 1800, "cost_cap_usd": 1.0}))


def test_an_api_only_run_is_bounded_by_the_api_ceiling_not_the_gpu_cap():
    spend.require_budget(_lock())  # no cost_cap_usd: nothing warms a GPU


def test_a_gpu_run_still_needs_the_gpu_cap():
    lock = _lock(engine={"kind": "modal-vllm", "model": "Qwen/Qwen3.5-9B"},
                 agent_routes={"judge": {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash"}})
    with pytest.raises(ServiceError, match="cost_cap_usd"):
        spend.require_budget(lock)
    lock["job"]["cost_cap_usd"] = 1.0
    spend.require_budget(lock)


def test_the_budget_prices_at_the_highest_api_price_and_seeds_from_persisted_items():
    lock = _lock(agent_routes={"judge": {"provider": "openrouter", "model": "qwen/qwen3.5-27b"}},
                 job={"mock": False, "api_cost_cap_usd": 0.01})
    budget = api_budget.budget_for(lock, [{"prompt_tokens": 10_000, "completion_tokens": 1_000}])
    assert (budget.usd_per_m_in, budget.usd_per_m_out) == (0.26, 2.60)
    assert budget.spent_usd == pytest.approx(0.0052)
    assert budget.exceeded() is None
    budget.add(10_000, 1_000)
    assert "api_cost_cap_usd=0.01 reached" in budget.exceeded()
    assert api_budget.budget_for({**lock, "job": {"mock": True, "api_cost_cap_usd": 0.01}}) is None


def test_the_pipeline_stops_before_the_next_document_once_api_spend_reaches_the_cap(monkeypatch):
    from mailroom_sandbox.eval import runners

    calls = []

    def fake_doc(row, **_):
        from pipeline import limits  # a live activation can reload the pipeline package

        calls.append(row["id"])
        limits.reset_run_usage()
        # record_usage drops a zero output count (``0 or completion_tokens`` is None), so use 1.
        limits.record_usage({"input_tokens": 600_000, "output_tokens": 1}, agent="sorter")
        return {"id": row["id"], "doc_type": "contract", "stage": "archived", "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    budget = api_budget.ApiBudget(0.10, 0.17, 0.25, ["qwen/qwen3.5-9b"])  # one doc costs $0.102
    rows = [{"id": str(i), "expected_doc_class": "contract", "doc_text": "x"} for i in range(3)]
    with pytest.raises(RuntimeError, match="API spend cap reached before next document"):
        runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, api_budget=budget)
    assert calls == ["0"]


def _spec(**overrides) -> RunSpec:
    base = dict(task="pipeline", profile="openrouter",
                dataset=DatasetSpec(repo="example/corpus", revision="a" * 40, limit=20),
                engine={"kind": "openrouter", "model": "qwen/qwen3.5-9b", "modal": None},
                job={"mock": False, "concurrency": 4})
    base.update(overrides)
    return RunSpec(**base)


def test_an_api_run_gets_an_api_ceiling_and_no_gpu_cap():
    advice = budget_advice.recommend(_spec())
    assert advice["gpu_cost_cap_usd"] is None
    api = advice["basis"]["api"]
    assert api["calls_per_document"] == 4 and api["usd_per_million_tokens"] == [0.17, 0.25]
    # 20 docs × 4 calls × (4000 × $0.17 + 1000 × $0.25)/1M × 1.5 margin = $0.1116 → $0.15
    assert advice["api_cost_cap_usd"] == 0.15
    assert advice["max_wall_seconds"] == 3000  # 20 × 400 s / 4 × 1.5


def test_a_modal_run_gets_a_gpu_cap_priced_on_its_fleet():
    spec = _spec(profile="modal-vllm", engine={"kind": "modal-vllm", "model": "Qwen/Qwen3.5-9B",
                                               "modal": {"gpu": "L4", "max_containers": 2, "scaledown_seconds": 120}},
                 job={"mock": False, "concurrency": 16})
    advice = budget_advice.recommend(spec)
    assert advice["api_cost_cap_usd"] is None
    assert advice["basis"]["effective_concurrency"] == 8  # 4 in flight per replica
    # 20 × 400 / 8 × 1.5 + 120 cold + 120 scaledown = 1740 s; 2 × L4 at $0.80/h
    assert advice["max_wall_seconds"] == 1740 and advice["gpu_cost_cap_usd"] == 0.80


def test_compare_warns_when_a_ceiling_is_below_its_recommendation():
    spec = _spec(job={"mock": False, "concurrency": 4, "max_wall_seconds": 600, "api_cost_cap_usd": 0.05})
    warnings = " ".join(budget_advice.compare(spec))
    assert "max_wall_seconds=600 is below the recommended 3000" in warnings
    assert "api_cost_cap_usd=0.05 is below the recommended 0.15" in warnings


def test_an_isolated_document_that_fails_after_a_paid_call_still_counts_its_tokens(monkeypatch):
    from mailroom_sandbox.eval import runners

    def predict(spec, row, *, mock):
        from pipeline import limits

        limits.record_usage({"input_tokens": 600_000, "output_tokens": 1}, agent="judge")
        raise RuntimeError("scoring blew up after the call")

    monkeypatch.setattr(runners, "_predict_spec", predict)
    budget = api_budget.ApiBudget(0.10, 0.17, 0.25, ["qwen/qwen3.5-9b"])
    rows = [{"id": str(i), "doc_text": "x", "expected": "contract"} for i in range(3)]
    with pytest.raises(RuntimeError, match="api_cost_cap_usd=0.1 reached"):
        runners.run_isolated_eval("judge", profile="ollama", rows=rows, mock=False, api_budget=budget, concurrency=1)
    assert budget.spent_usd == pytest.approx(0.102, abs=1e-3)


def test_reports_estimate_api_spend_apart_from_gpu_cost():
    from mailroom_sandbox.job.spend import bills_gpu

    lock = _lock()
    assert not bills_gpu(lock)  # the report drops its GPU cost
    estimate = api_budget.spend_estimate(lock, [{"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}])
    assert estimate["est_api_usd"] == pytest.approx(0.42) and estimate["models"] == ["qwen/qwen3.5-9b"]
    assert api_budget.spend_estimate({"engine": {"kind": "modal-vllm", "model": "m"}}, []) is None
