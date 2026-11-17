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


def test_blind_routing_is_hashed_only_when_set_and_only_for_pipelines():
    plain, blind = _spec(), _spec(blind_routing=True)
    assert "blind_routing" not in spec_core(plain, source_sha256="0" * 64)["job"]
    assert spec_core(blind, source_sha256="0" * 64)["job"]["blind_routing"] is True
    assert core_hash(spec_core(plain, source_sha256="0" * 64)) != core_hash(spec_core(blind, source_sha256="0" * 64))
    with pytest.raises(ValidationError, match="blind_routing"):
        _spec(task="sorter", blind_routing=True)


def test_only_a_locked_blind_run_activates_blind_routing(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    try:
        with runtime.locked_runtime({"profile": "modal-vllm", "job": {"blind_routing": True}}, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert runtime.blind_routing_active() is True
        runtime.activate("modal-vllm", load_env_file=False)  # an unlocked activation is never blind
        assert runtime.blind_routing_active() is False
        with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert runtime.blind_routing_active() is False
    finally:
        runtime.activate("modal-vllm", load_env_file=False)


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
