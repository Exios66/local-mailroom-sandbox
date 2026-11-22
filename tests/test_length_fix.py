"""#214 length-fix defaults for pipeline chunked specialists (SAND-214).

Contracts r1 lost a chunk window on 5 of 30 documents to a decode that ran to
the output cap (``LengthFinishReasonError`` → ``chunk_call_failed``). r2's
Qwen3 non-thinking sampling plus one length re-sample lost none. A ``task:
pipeline`` run on self-hosted Qwen3 vLLM now defaults that sampling for the
specialists it did not configure; explicit and posture knobs always win.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.job.length_fix import (
    CHUNKED_SPECIALISTS,
    QWEN3_LENGTH_FIX,
    is_qwen3_family,
    self_hosted_vllm,
    with_length_fix_defaults,
)
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec


def _pipeline_spec(**overrides) -> RunSpec:
    base = dict(
        task="pipeline",
        dataset=DatasetSpec(local_path="file:///tmp/x.jsonl"),
        engine={"kind": "modal-vllm", "model": "Qwen/Qwen3-8B-AWQ", "modal": {}},
    )
    base.update(overrides)
    return RunSpec(**base)


def test_default_sampling_matches_the_sand40_posture_values():
    """One table of numbers: the posture rows and the pipeline default agree."""
    from mailroom_sandbox.job.specialist_posture import SAND40_OPTIMIZED_KNOBS

    for key, value in QWEN3_LENGTH_FIX.items():
        assert SAND40_OPTIMIZED_KNOBS[key] == value


def test_default_applies_to_unconfigured_specialists_on_a_qwen3_pipeline():
    knobs = with_length_fix_defaults({}, _pipeline_spec())
    assert set(knobs) == set(CHUNKED_SPECIALISTS)
    assert all(knobs[agent] == QWEN3_LENGTH_FIX for agent in CHUNKED_SPECIALISTS)


def test_explicit_agent_knobs_win_per_agent():
    own = {"contracts_specialist": {"length_retries": 0, "top_p": 0.95}}
    knobs = with_length_fix_defaults(own, _pipeline_spec())
    assert knobs["contracts_specialist"] == own["contracts_specialist"]
    assert knobs["merger_agreement_specialist"] == QWEN3_LENGTH_FIX


def test_run_configured_knobs_are_never_mutated():
    own = {"correspondence_specialist": {"max_input_chars": 12000}}
    knobs = with_length_fix_defaults(own, _pipeline_spec())
    assert own == {"correspondence_specialist": {"max_input_chars": 12000}}
    assert knobs["correspondence_specialist"]["max_input_chars"] == 12000


def test_openrouter_pipeline_never_defaults():
    spec = _pipeline_spec(engine={"kind": "openrouter", "model": "qwen/qwen3.7-flash", "modal": None})
    assert with_length_fix_defaults({}, spec) == {}


def test_non_qwen3_model_never_defaults():
    spec = _pipeline_spec(engine={"kind": "modal-vllm", "model": "meta-llama/llama-4-8b", "modal": {}})
    assert with_length_fix_defaults({}, spec) == {}


def test_specialist_task_never_defaults():
    spec = RunSpec(
        task="contracts_specialist",
        dataset=DatasetSpec(local_path="file:///tmp/x.jsonl"),
        engine={"kind": "modal-vllm", "model": "Qwen/Qwen3-8B-AWQ", "modal": {}},
    )
    assert with_length_fix_defaults({}, spec) == {}


def test_self_hosted_kinds_cover_local_and_remote_vllm():
    for kind in ("vllm-local", "vllm-remote", "modal-vllm"):
        spec = _pipeline_spec(engine={"kind": kind, "model": "Qwen/Qwen3-8B-AWQ", "modal": None})
        assert set(with_length_fix_defaults({}, spec)) == set(CHUNKED_SPECIALISTS), kind


def test_qwen35_counts_as_the_qwen3_family():
    assert is_qwen3_family("Qwen/Qwen3.5-9B")
    assert is_qwen3_family("Qwen/Qwen3-8B-AWQ")
    assert not is_qwen3_family("qwen/qwen2.5-7b")
    assert not is_qwen3_family(None)


def test_self_hosted_vllm_rejects_api_engines():
    spec = _pipeline_spec(engine={"kind": "openrouter", "model": "qwen/qwen3.7-flash", "modal": None})
    assert not self_hosted_vllm(spec)
    assert self_hosted_vllm(_pipeline_spec())


def test_preflight_run_knobs_merge_the_default_into_the_locked_snapshot():
    """The one resolution shared by the context plan and the lock carries the default."""
    from mailroom_sandbox.job.preflight import _run_knobs

    spec = _pipeline_spec(
        agent_knobs={"sorter": {"max_input_chars": 600000}, "intake": {"max_input_chars": 600000}}
    )
    knobs = _run_knobs(spec, None)
    assert knobs["sorter"] == {"max_input_chars": 600000}
    assert knobs["contracts_specialist"] == QWEN3_LENGTH_FIX
    assert knobs["insurance_claims_specialist"] == QWEN3_LENGTH_FIX


def test_preflight_run_knobs_specialist_posture_path_is_untouched():
    """A posture-driven run keeps resolving exactly the posture's own knobs."""
    from mailroom_sandbox.job.preflight import _run_knobs

    spec = RunSpec(
        task="contracts_specialist",
        dataset=DatasetSpec(local_path="file:///tmp/x.jsonl"),
        engine={"kind": "modal-vllm", "model": "Qwen/Qwen3-8B-AWQ", "modal": {}},
    )
    knobs = _run_knobs(spec, "sand214-30-contracts-specialist-awq-1l4-windows-r2")
    assert "presence_penalty" in knobs["contracts_specialist"]
    assert set(knobs) == {"contracts_specialist"}


@pytest.mark.parametrize("agent", sorted(CHUNKED_SPECIALISTS))
def test_every_vendored_chunked_specialist_is_covered(agent):
    """The vendored graph chunks all five specialists; the default covers each."""
    assert agent.endswith("_specialist")
