"""Spend caps price every Modal app a routed run keeps warm, not only the base engine.

A Modal pipeline experiment routes the judge (and optionally the specialists)
to their own apps. Pricing only the base L4 lets an L40S judge run past the cap.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.job import metrics

L4 = 0.80
L40S = 1.95

ROUTED_LOCK = {
    "engine": {"model": "Qwen/Qwen3.5-9B", "modal": {"app": "sandbox-vllm-s-9b", "gpu": "L4", "max_containers": 1}},
    "agent_routes": {
        "judge": {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-27B",
                  "modal": {"app": "sandbox-vllm-s-27b", "gpu": "L40S", "max_containers": 1}},
        "contracts_specialist": {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-35B-A3B",
                                 "modal": {"app": "sandbox-vllm-s-35b-a3b", "gpu": "L4:2", "max_containers": 1}},
        # Same app as above: one deployment, billed once.
        "correspondence_specialist": {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-35B-A3B",
                                      "modal": {"app": "sandbox-vllm-s-35b-a3b", "gpu": "L4:2", "max_containers": 1}},
        "sorter": {"provider": "openrouter", "model": "qwen/qwen3.5-9b"},
    },
}


@pytest.fixture(autouse=True)
def _table_rates(monkeypatch):
    monkeypatch.delenv("MODAL_GPU_USD_PER_HOUR", raising=False)
    monkeypatch.delenv("MODAL_GPU_USD_PER_SEC", raising=False)


def test_fleet_lists_each_distinct_modal_app_with_its_billed_gpus():
    assert metrics.lock_gpu_fleet(ROUTED_LOCK) == [("L4", 1), ("L40S", 1), ("L4", 2)]


def test_fleet_without_routes_is_the_base_engine_alone():
    lock = {"engine": {"modal": {"gpu": "L4", "max_containers": 2}}}
    assert metrics.lock_gpu_fleet(lock) == [("L4", 2)]
    assert metrics.lock_gpu_fleet({}) == [("L4", 1)]


def test_fleet_cost_sums_every_app():
    hour = metrics.fleet_gpu_cost_usd(3600, metrics.lock_gpu_fleet(ROUTED_LOCK))
    assert hour == pytest.approx(L4 + L40S + 2 * L4)
    assert metrics.fleet_gpu_cost_usd(0, [("L4", 1)]) == 0.0


def test_run_cap_estimate_includes_route_apps(tmp_path):
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.runner import _estimate_run_gpu_usd

    store = RunStore(tmp_path / "r")
    store.write_lock(ROUTED_LOCK)
    assert _estimate_run_gpu_usd(store, 3600) == pytest.approx(L4 + L40S + 2 * L4)


def test_pipeline_job_passes_the_fleet_to_the_cap(tmp_path, monkeypatch):
    from mailroom_sandbox.eval import runners as eval_runners
    from mailroom_sandbox.job import runner
    from mailroom_sandbox.job.checkpoint import RunStore

    store = RunStore(tmp_path / "r")
    store.write_lock({**ROUTED_LOCK, "task": "pipeline", "profile": "modal-vllm", "prompt": {},
                      "job": {"cost_cap_usd": 1.0}})
    seen = {}

    def fake_pipeline(**kwargs):
        seen.update(kwargs)
        return {"task": "pipeline", "rows": [], "scores": {}}

    monkeypatch.setattr(eval_runners, "run_pipeline_eval", fake_pipeline)
    runner._run_whole_run(store, "pipeline", mock=False, model=None, profile="modal-vllm")
    # The lock is stored with sorted keys; fleet order carries no meaning.
    assert sorted(seen["gpu_fleet"]) == [("L4", 1), ("L4", 2), ("L40S", 1)]


def test_cap_guard_trips_on_the_fleet_not_the_base_gpu():
    from mailroom_sandbox.eval.runners import _estimated_gpu_usd

    # $1 cap: 30 min on the base L4 alone is $0.40, the routed fleet is $2.18.
    assert _estimated_gpu_usd(1800, gpu="L4", replicas=1, gpu_fleet=None) < 1.0
    assert _estimated_gpu_usd(1800, gpu="L4", replicas=1, gpu_fleet=metrics.lock_gpu_fleet(ROUTED_LOCK)) >= 1.0
