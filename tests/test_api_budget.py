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
    # Canonical slug qwen/qwen3.5-9b-20260310, checked 2026-11-25.
    assert token_price("qwen/qwen3.5-9b") == (0.10, 0.25)


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
    assert spend.require_budget(_lock()) is None  # no cost_cap_usd: nothing warms a GPU


def test_a_gpu_run_still_needs_the_gpu_cap():
    lock = _lock(engine={"kind": "modal-vllm", "model": "Qwen/Qwen3.5-9B"},
                 agent_routes={"judge": {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash"}})
    with pytest.raises(ServiceError, match="cost_cap_usd"):
        spend.require_budget(lock)
    lock["job"]["cost_cap_usd"] = 1.0
    spend.require_budget(lock)


def test_the_budget_prices_at_the_highest_api_price_and_seeds_from_persisted_items():
    lock = _lock(agent_routes={"judge": {"provider": "openrouter", "model": "qwen/qwen3.5-27b"}},
                 job={"mock": False, "api_cost_cap_usd": 0.008})
    budget = api_budget.budget_for(lock, [{"prompt_tokens": 10_000, "completion_tokens": 1_000}])
    # The refreshed canonical-slug sheet (config/api_prices.yaml): 0.26/2.6 per 1M.
    assert (budget.usd_per_m_in, budget.usd_per_m_out) == (0.26, 2.6)
    assert budget.spent_usd == pytest.approx(0.0052)
    assert budget.exceeded() is None
    budget.add(10_000, 1_000)
    assert "api_cost_cap_usd=0.008 reached" in budget.exceeded()
    assert api_budget.budget_for({**lock, "job": {"mock": True, "api_cost_cap_usd": 0.005}}) is None


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
    budget = api_budget.ApiBudget(0.05, 0.10, 0.25, ["qwen/qwen3.5-9b"])  # one doc costs $0.060
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
    assert api["calls_per_document"] == 4 and api["usd_per_million_tokens"] == [0.10, 0.25]
    # 20 docs × 4 calls × (4000 × $0.10 + 1000 × $0.25)/1M × 1.5 margin = $0.078 → $0.10
    assert advice["api_cost_cap_usd"] == 0.10
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
    assert "api_cost_cap_usd=0.05 is below the recommended 0.1" in warnings


def test_an_isolated_document_that_fails_after_a_paid_call_still_counts_its_tokens(monkeypatch):
    from mailroom_sandbox.eval import runners

    def predict(spec, row, *, mock):
        from pipeline import limits

        limits.record_usage({"input_tokens": 600_000, "output_tokens": 1}, agent="judge")
        raise RuntimeError("scoring blew up after the call")

    monkeypatch.setattr(runners, "_predict_spec", predict)
    budget = api_budget.ApiBudget(0.05, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    rows = [{"id": str(i), "doc_text": "x", "expected": "contract"} for i in range(3)]
    with pytest.raises(RuntimeError, match="api_cost_cap_usd=0.05 reached"):
        runners.run_isolated_eval("judge", profile="ollama", rows=rows, mock=False, api_budget=budget, concurrency=1)
    assert budget.spent_usd == pytest.approx(0.060, abs=1e-3)


def test_reports_estimate_api_spend_apart_from_gpu_cost():
    from mailroom_sandbox.job.spend import bills_gpu

    lock = _lock()
    assert not bills_gpu(lock)  # the report drops its GPU cost
    estimate = api_budget.spend_estimate(lock, [{"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}])
    assert estimate["est_api_usd"] == pytest.approx(0.35) and estimate["models"] == ["qwen/qwen3.5-9b"]
    assert api_budget.spend_estimate({"engine": {"kind": "modal-vllm", "model": "m"}}, []) is None


def test_a_pipeline_document_that_raises_after_a_paid_call_reports_its_usage(monkeypatch):
    from mailroom_sandbox.eval import runners

    def fake_doc(row, **_):
        from pipeline import limits

        limits.reset_run_usage()
        limits.record_usage({"input_tokens": 300_000, "output_tokens": 1}, agent="sorter")
        raise RuntimeError("graph raised after the call")

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    budget = api_budget.ApiBudget(1.0, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    rows = [{"id": "d0", "expected_doc_class": "contract", "doc_text": "x"}]
    with pytest.raises(RuntimeError) as raised:
        runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, api_budget=budget)
    assert raised.value.sandbox_failed_usage["item_id"] == "d0"
    assert raised.value.sandbox_failed_usage["prompt_tokens"] == 300_000
    assert budget.spent_usd == pytest.approx(0.030, abs=1e-4)


def test_a_document_the_pipeline_aborted_fails_alone(monkeypatch):
    from mailroom_sandbox.eval import runners

    rows = [{"id": name, "expected_doc_class": "contract", "text": "x"} for name in ("dead", "live")]
    results = {"dead": {"stage": "failed", "escalation_reason": "run aborted [run_budget]"},
               "live": {"stage": "archived", "doc_type": "contract"}}
    monkeypatch.setattr(runners, "_run_pipeline_doc", lambda row, **_: results[row["id"]])
    items = []
    runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, connected=False, row_cb=items.append)
    assert [bool(item["error"]) for item in items] == [True, False]


def test_a_run_with_no_classified_document_still_refuses_to_score(monkeypatch):
    from mailroom_sandbox.eval import runners

    rows = [{"id": "dead", "expected_doc_class": "contract", "text": "x"}]
    monkeypatch.setattr(runners, "_run_pipeline_doc",
                        lambda row, **_: {"stage": "failed", "escalation_reason": "run aborted"})
    with pytest.raises(RuntimeError, match="no doc_type"):
        runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, connected=False)


def test_a_modal_route_on_an_api_engine_counts_its_replicas_and_overhead():
    spec = _spec(agent_routes={"judge": {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-27B",
                                         "modal": {"app": "sandbox-vllm-judge", "gpu": "L4", "max_containers": 1,
                                                   "scaledown_seconds": 60}}},
                 job={"mock": False, "concurrency": 16})
    basis = budget_advice.recommend(spec)["basis"]
    assert basis["effective_concurrency"] == 4
    assert basis["cold_start_and_scaledown_seconds"] == 180


def test_reported_api_spend_includes_documents_that_failed_after_a_paid_call(tmp_path):
    from mailroom_sandbox.job.checkpoint import RunStore

    store = RunStore(tmp_path / "run")
    store.append_item({"item_id": "1", "ok": True, "usage": {"prompt_tokens": 10}})
    store.append_event(api_budget.FAILED_USAGE_EVENT, "warning", item_id="2", prompt_tokens=20)
    records = api_budget.usage_records(store)
    assert [record["item_id"] for record in records] == ["1", "2"]


def test_a_run_without_a_billed_gpu_reports_no_gpu_metrics():
    from mailroom_sandbox.experiments import _clear_gpu_metrics

    metrics = {"cost": {"usd_per_1k_ok": 1}, "goodput": {"documents_per_minute_per_gpu": 2}}
    card = {"cost": {"x": 1}, "conditions": {"gpu": "L4", "replicas": 1, "model": "m"}}
    _clear_gpu_metrics(metrics, card)
    assert metrics == {"cost": {}, "goodput": {}}
    assert card["conditions"]["gpu"] is None and card["conditions"]["replicas"] is None
    assert card["conditions"]["model"] == "m"


def test_in_flight_documents_count_against_the_cap():
    """Concurrent starts: each unfinished document is counted at the mean finished-document cost."""
    budget = api_budget.ApiBudget(1.0, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    budget.spent_usd, budget.documents = 0.6, 3          # $0.20 per finished document
    assert budget.exceeded() is None
    assert budget.exceeded(in_flight=1) is None          # 0.80
    assert "2 in flight" in budget.exceeded(in_flight=2)  # 1.00 reaches the cap
    with pytest.raises(RuntimeError, match="in flight"):
        budget.check("stop: ", in_flight=2)


def test_price_bound_uses_the_dearest_tier():
    """The signed ceiling prices Qwen 3.7 Flash at its 256k+ tier, not the base tier."""
    from mailroom_sandbox.job.metrics import token_price_ceiling

    assert token_price("qwen/qwen3.7-flash") == (0.03, 0.13)
    assert token_price_ceiling("qwen/qwen3.7-flash") == (0.20, 0.80)
    assert api_budget.price_bound(["qwen/qwen3.7-flash", "qwen/qwen3.5-9b"]) == (0.20, 0.80)


def test_isolated_runs_price_the_sorter_whatever_job_task_says():
    """The isolated runner always runs the sorter; job.task must not drop its model from the cap check."""
    lock = {"task": "isolated", "job": {"task": "judge", "mock": False},
            "agent_assignments": {"sorter": {"provider": "openrouter", "model": "qwen/qwen3.5-9b"}}}
    assert api_budget.api_models(lock) == ["qwen/qwen3.5-9b"]
    assert any("api_cost_cap_usd" in e for e in api_budget.budget_errors(lock))


@pytest.mark.parametrize("task", ["isolated", "correspondence_specialist"])
def test_spec_api_models_drops_profile_agents_a_single_agent_task_never_calls(task):
    """The advice and autoresearch price a spec as its lock would: the profile's judge is not a sorter run's model.

    With agent_knobs set, the spec carries every profile assignment (the openrouter judge on
    deepseek among them). The lock records the task, so ``api_models(lock)`` drops the judge;
    the spec-level resolution must too, or the advice prices a Qwen run at deepseek's dearer
    short-prompt rate.
    """
    agent = "sorter" if task == "isolated" else task
    spec = _spec(task=task, agent_knobs={agent: {"max_tokens": 2000}},
                 engine={"kind": "openrouter", "model": "qwen/qwen3.7-flash", "modal": None})
    from mailroom_sandbox.agent_routes import describe

    assert "deepseek/deepseek-v4-flash" in {a.get("model") for a in describe(spec).values()}
    assert api_budget.spec_api_models(spec) == ["qwen/qwen3.7-flash"]


def _live_budget(cap=0.05):
    budget = api_budget.ApiBudget(cap, 0.10, 0.25, ["qwen/qwen3.5-9b"])
    budget.start_live()
    return budget


def test_a_reservation_counts_against_the_cap_until_released():
    budget = _live_budget()
    budget.reserve(0.06)
    assert "reserved" in (budget.exceeded() or "")
    budget.release(0.06)
    assert budget.exceeded() is None and budget.reserved_usd == 0.0


def test_extra_usd_refuses_a_call_that_would_pass_the_cap():
    budget = _live_budget()
    budget.reserve(0.03)
    assert budget.exceeded(extra_usd=0.01) is None
    assert budget.exceeded(extra_usd=0.03) is not None  # 0.03 reserved + 0.03 more passes 0.05


def test_estimate_call_usd_prices_one_call_at_the_models_tier():
    budget = _live_budget()
    assert budget.estimate_call_usd(600_000, 0) == pytest.approx(budget._cost(600_000, 0, 1))
    assert budget.estimate_call_usd(600_000, 0) > 0


def test_an_unreported_charge_is_spend_and_survives_a_resume(tmp_path):
    from mailroom_sandbox.job.checkpoint import RunStore

    budget = _live_budget(cap=1.0)
    budget.charge_unreported(0.05)
    assert budget.unreported_usd == pytest.approx(0.05)
    assert budget.live_total_usd() == pytest.approx(0.05)
    store = RunStore(tmp_path / "run")
    store.append_event(api_budget.UNREPORTED_CHARGE_EVENT, "warning", kind="unreported_charge",
                       unreported_usd=0.05)
    resumed = api_budget.budget_for(_lock(), api_budget.usage_records(store))
    assert resumed.spent_usd == pytest.approx(0.05) and resumed.documents == 0


def test_release_never_goes_below_zero():
    budget = _live_budget()
    budget.release(0.01)
    assert budget.reserved_usd == 0.0
