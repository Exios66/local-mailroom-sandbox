"""Phase 5 part 2: the merger-read and long-document head-read switches (spec, hash, activation).

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md.
Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 1).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import merger_reads
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, load_run_spec, spec_core, spec_hash

BASELINE_HASH = "7293c6342d502a2d42f2d052a0e985031f7343723baf242c983ba2313c0bb288"  # main at 1dcafd5


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-mr", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


@pytest.fixture(autouse=True)
def _off():
    yield
    merger_reads.activate(None)
    merger_reads.activate_head(False)


def test_a_spec_without_the_switches_keeps_its_hash():
    assert spec_hash(load_run_spec("config/runs/p4-s1-verify-gov-off.yaml")) == BASELINE_HASH
    core = spec_core(_spec())["job"]
    assert "merger" not in core and "long_document_head" not in core


def test_question_groups_require_subclass_fields():
    with pytest.raises(ValidationError, match="job.merger.question_groups requires job.merger.subclass_fields"):
        _spec(merger={"question_groups": True})


def test_gap_retry_requires_subclass_fields():
    with pytest.raises(ValidationError, match="job.merger.gap_retry requires job.merger.subclass_fields"):
        _spec(merger={"gap_retry": True})


@pytest.mark.parametrize("groups", [0, 4])
def test_groups_outside_one_to_three_is_refused(groups):
    with pytest.raises(ValidationError, match="groups"):
        _spec(merger={"subclass_fields": True, "question_groups": True, "groups": groups})


def test_merger_switches_are_pipeline_only():
    with pytest.raises(ValidationError, match="job.merger"):
        _spec(task="sorter", merger={"subclass_fields": True})


def test_long_document_head_is_allowed_on_sorter_and_pipeline_only():
    assert _spec(task="sorter", long_document_head=True).job.long_document_head is True
    assert _spec(long_document_head=True).job.long_document_head is True
    with pytest.raises(ValidationError, match="long_document_head"):
        _spec(task="specialist", long_document_head=True)


def test_a_set_switch_changes_the_hash_and_a_quoted_true_is_refused():
    base = spec_hash(_spec())
    on = _spec(merger={"subclass_fields": True})
    assert spec_core(on)["job"]["merger"]["subclass_fields"] is True
    assert spec_hash(on) != base
    assert spec_hash(_spec(long_document_head=True)) != base
    with pytest.raises(ValidationError):
        _spec(merger={"subclass_fields": "true"})
    with pytest.raises(ValidationError):
        _spec(long_document_head="true")
    with pytest.raises(ValidationError):
        _spec(merger={"subclass_fields": True, "question_groups": True, "groups": "2"})


def _activate(monkeypatch, job):
    from mailroom_sandbox import runtime

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    lock = {"profile": "modal-vllm", "task": "pipeline", "job": job}
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)


def test_activation_reads_the_locked_job(monkeypatch):
    _activate(monkeypatch, {"merger": {"subclass_fields": True, "question_groups": False,
                                       "gap_retry": False, "groups": 3},
                            "long_document_head": True})
    assert merger_reads.on("subclass_fields") and not merger_reads.on("question_groups")
    assert merger_reads.config()["groups"] == 3
    assert merger_reads.head_active()


def test_a_lock_without_the_keys_activates_nothing(monkeypatch):
    _activate(monkeypatch, {"merger": {"subclass_fields": True}, "long_document_head": True})
    _activate(monkeypatch, {})
    assert merger_reads.config() is None and not merger_reads.on("subclass_fields")
    assert not merger_reads.head_active()
