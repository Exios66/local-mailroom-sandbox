"""Phase 2 loop governor: the job.governor switch, budgets, stop outcomes and loop fixes L2, L4, L5."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import governor, runtime
from mailroom_sandbox.job.spec import DatasetSpec, GovernorSpec, RunSpec, spec_core


@pytest.fixture(autouse=True)
def _governor_off():
    governor.activate(None)
    yield
    governor.activate(None)


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-gov", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_governor_true_means_the_spec_defaults():
    spec = _spec(governor=True).job.governor
    assert spec == GovernorSpec()
    assert (spec.retries, spec.calls, spec.spend_usd) == (2, 30, None)
    assert spec.calls_by_class == {"merger_agreement": 36}
    assert (spec.sorter_ceiling, spec.near_empty_chars, spec.link_duplicates) == (None, 64, True)
    assert spec.near_duplicate_jaccard == 0.9
    assert _spec(governor=False).job.governor is None


def test_governor_is_hashed_only_when_set():
    assert "governor" not in spec_core(_spec(), source_sha256="0" * 64)["job"]
    assert spec_core(_spec(governor={"retries": 1}), source_sha256="0" * 64)["job"]["governor"]["retries"] == 1


@pytest.mark.parametrize("bad", [{"calls": 40}, {"calls_by_class": {"merger_agreement": 40}}, {"retries": -1},
                                 {"sorter_ceiling": 1.5}, {"spend_usd": 0}])
def test_governor_refuses_a_budget_outside_its_range(bad):
    with pytest.raises(ValidationError):
        _spec(governor=bad)


def test_governor_is_refused_outside_pipeline():
    with pytest.raises(ValidationError, match="governor"):
        _spec(task="correspondence_specialist", governor=True)


def test_the_lock_activates_the_governor(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {"governor": {"retries": 1}}}, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert governor.active().retries == 1
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):  # a lock from before phase 2
        runtime.activate("modal-vllm", load_env_file=False)
    assert governor.active() is None


def test_merger_call_budget_is_36():
    governor.activate(GovernorSpec())
    assert governor.call_budget("merger_agreement") == 36
    assert governor.call_budget("contract") == 30
    assert governor.call_budget(None) == 30


def test_the_runner_merges_governor_stop_into_the_result(monkeypatch):
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.job import call_guard

    stop = {"reason": "retry_budget", "outcome": "human_review", "node": "arbiter", "proposed": "retry_extract",
            "calls": 9, "retries": 2, "spend_usd": 0.0}

    def fake(row, **_):
        call_guard.scope()["governor_stop"] = dict(stop)
        call_guard.scope()["duplicate_of"] = {"doc_id": "d0", "kind": "exact", "similarity": 1.0}
        call_guard.scope()["governor"]["skipped_classify_retries"] = 1
        return {"id": row["id"], "stage": "review"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", fake)
    result = runners._run_pipeline_doc({"id": "d1"})
    assert result["governor_stop"] == stop
    assert result["duplicate_of"]["kind"] == "exact"
    assert result["governor_skips"] == {"classify_retry": 1}


def test_the_runner_adds_no_governor_fields_when_nothing_happened(monkeypatch):
    from mailroom_sandbox.eval import runners

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", lambda row, **_: {"id": row["id"], "stage": "archived"})
    assert runners._run_pipeline_doc({"id": "d1"}) == {"id": "d1", "stage": "archived"}
