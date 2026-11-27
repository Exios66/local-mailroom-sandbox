"""Phase 5 part 1 (A): ``confidence.keep_best_attempt`` reaches the vendored #254 attempt selection.

Design: docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, load_run_spec, spec_hash


def _spec(**overrides) -> RunSpec:
    base = dict(run_id="r-kb", task="pipeline", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                engine={"kind": "vllm-local", "modal": None}, job={"mock": True})
    base.update(overrides)
    return RunSpec(**base)


def test_the_flag_is_accepted_globally_and_per_class():
    assert _spec(confidence={"keep_best_attempt": True}).confidence["keep_best_attempt"] is True
    spec = _spec(confidence={"by_class": {"contract": {"keep_best_attempt": True}}})
    assert spec.confidence["by_class"]["contract"]["keep_best_attempt"] is True


def test_a_quoted_flag_is_refused():
    with pytest.raises(ValidationError, match="keep_best_attempt must be true or false"):
        _spec(confidence={"keep_best_attempt": "true"})
    with pytest.raises(ValidationError, match="keep_best_attempt must be true or false"):
        _spec(confidence={"by_class": {"contract": {"keep_best_attempt": 1}}})


def test_the_flag_is_refused_with_the_correcting_judge():
    for confidence in ({"keep_best_attempt": True}, {"by_class": {"contract": {"keep_best_attempt": True}}}):
        with pytest.raises(ValidationError, match="keep_best_attempt.*judge.mode correct"):
            _spec(confidence=confidence, judge={"mode": "correct"})
    assert _spec(confidence={"keep_best_attempt": True}, judge={"mode": "verify"})
    # An explicit false asks for the vendored default, which correct mode already has.
    assert _spec(confidence={"keep_best_attempt": False}, judge={"mode": "correct"})


def test_a_spec_without_the_flag_keeps_its_hash():
    assert spec_hash(load_run_spec("config/runs/p4-s1-verify-gov-off.yaml")) == (
        "7293c6342d502a2d42f2d052a0e985031f7343723baf242c983ba2313c0bb288")  # main at 1dcafd5


def test_the_flag_changes_the_hash():
    assert spec_hash(_spec()) != spec_hash(_spec(confidence={"keep_best_attempt": True}))


def test_the_flag_reaches_the_vendored_switch(monkeypatch):
    pytest.importorskip("pipeline.config")
    from graph.routing import keep_best_attempt_enabled

    from mailroom_sandbox import runtime
    from mailroom_sandbox.job.routing_audit import effective_thresholds

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    explicit = {"by_class": {"contract": {"keep_best_attempt": True}}}
    lock = {"profile": "modal-vllm", "job": {}, "confidence": explicit,
            "effective_confidence": effective_thresholds(explicit)}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert keep_best_attempt_enabled({"doc_type": "contract"}) is True
        assert keep_best_attempt_enabled({"doc_type": "invoice"}) is False
    finally:
        runtime.activate("modal-vllm", load_env_file=False)
    assert keep_best_attempt_enabled({"doc_type": "contract"}) is False


def _audit_store(tmp_path, lock):
    run = tmp_path / "run"
    run.mkdir()
    (run / "spec.lock.json").write_text(json.dumps(lock))
    (run / "dataset.jsonl").write_text(json.dumps({"id": "d1", "expected_doc_class": "contract",
                                                   "expected_fields": "{}"}) + "\n")
    (run / "items.jsonl").write_text(json.dumps({"item_id": "d1", "pred": {"stage": "archived"}}) + "\n")
    (run / "nodes.jsonl").write_text("")
    return run


def test_the_routing_audit_reports_the_flag(tmp_path):
    from mailroom_sandbox.job import routing_audit

    locked = routing_audit.audit(_audit_store(tmp_path, {"run_id": "r", "effective_confidence": {
        "keep_best_attempt": False, "by_class": {"contract": {"keep_best_attempt": True}}}}))
    assert locked["classes"]["contract"]["thresholds"]["keep_best_attempt"] is True
    (tmp_path / "legacy").mkdir()
    legacy = routing_audit.audit(_audit_store(tmp_path / "legacy", {"run_id": "r"}))
    # An older run froze only its overrides: today's default is not its setting.
    assert legacy["classes"]["contract"]["thresholds"]["keep_best_attempt"] is None
