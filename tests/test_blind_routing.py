"""job.blind_routing: dataset labels stay out of the graph's state (llm-mailroom #207)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import runtime
from mailroom_sandbox.eval import runners
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, core_hash, spec_core


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-blind", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def _core(spec):
    return spec_core(spec, source_sha256="0" * 64)


def test_pipeline_specs_are_blind_by_default_and_hash_it():
    plain, blind, oracle = _spec(), _spec(blind_routing=True), _spec(blind_routing=False)
    assert plain.job.blind_routing is True  # unset resolves to blind for task: pipeline
    assert _core(plain)["job"]["blind_routing"] is True
    assert core_hash(_core(plain)) == core_hash(_core(blind))
    assert "blind_routing" not in _core(oracle)["job"]  # false is the pre-fix oracle posture
    assert core_hash(_core(plain)) != core_hash(_core(oracle))
    sorter = _spec(task="sorter")
    assert sorter.job.blind_routing is False and "blind_routing" not in _core(sorter)["job"]
    with pytest.raises(ValidationError, match="blind_routing"):
        _spec(task="sorter", blind_routing=True)


def test_only_a_locked_oracle_run_turns_blind_routing_off(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    try:
        with runtime.locked_runtime({"profile": "modal-vllm", "job": {"blind_routing": False}}, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert runtime.blind_routing_active() is False
        runtime.activate("modal-vllm", load_env_file=False)  # an unlocked activation is blind
        assert runtime.blind_routing_active() is True
        with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert runtime.blind_routing_active() is True
    finally:
        runtime.activate("modal-vllm", load_env_file=False)


def test_preflight_refuses_a_live_oracle_routing_run(tmp_path):
    from mailroom_sandbox.job import preflight

    data = tmp_path / "d.jsonl"
    data.write_text('{"id": "a", "filename": "a.txt", "doc_text": "x", "expected_doc_class": "contract"}\n')
    spec = RunSpec(run_id="r-oracle", task="pipeline", dataset=DatasetSpec(local_path=f"file://{data}"),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"},
                   job={"mock": False, "blind_routing": False, "max_wall_seconds": 60})
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "failed"
    assert any(c["name"] == "blind_routing" and not c["ok"] for c in report["checks"]), report


@pytest.mark.parametrize("blind", [False, True])
def test_the_graph_gets_labels_only_when_routing_is_not_blind(monkeypatch, tmp_path, blind):
    pytest.importorskip("graph.build_graph")
    import graph.build_graph as build_graph

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    seen = {}

    from pipeline.config import oracle_routing_enabled

    def fake_run_pipeline(path, matter_id, **kwargs):
        seen.update(kwargs, oracle=oracle_routing_enabled())
        return {"doc_type": "contract", "stage": "archived", "extracted_data": {"title": "x"}}

    monkeypatch.setattr(build_graph, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(runtime, "blind_routing_active", lambda: blind)
    # A blind run forces oracle routing off even when the environment asks for it (llm-mailroom #264).
    monkeypatch.setenv("MAILROOM_ORACLE_ROUTING", "1" if blind else "0")
    row = {"id": "b0", "filename": "b0.txt", "doc_text": "agreement " * 20, "expected_doc_class": "contract",
           "expected_fields": {"title": "x"}}
    out = runners._run_pipeline_doc(row, mock=True)
    assert out["doc_type"] == "contract"
    if blind:
        assert seen["ground_truth"] is None
        assert seen["oracle"] is False
    else:
        assert seen["ground_truth"]["expected_doc_class"] == "contract"
        assert seen["ground_truth"]["expected_fields"] == {"title": "x"}
        assert seen["oracle"] is True  # routing may read the labels it is given, as before #264
