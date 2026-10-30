"""SAND-076: live per-node tracking of full-pipeline runs (store → watch frame → browser)."""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.job import node_trace
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.tui.demo import DemoRun
from mailroom_sandbox.watch import LogBuffer, compose_watch_state, pipeline_lines, render_frame


@pytest.mark.parametrize(("node", "out", "expected"), [
    ("classify", {"doc_type": "contract", "classification_confidence": 0.91},
     {"question": "doc_type", "type": "choice", "answer": "contract", "p": 0.91}),
    ("review_classify", {"review_verdict": "reviewer_agrees_high", "classification_confidence": 0.98},
     {"question": "sorter_review", "type": "choice", "answer": "reviewer_agrees_high", "p": 0.98}),
    ("judge_verify", {"judge_verdict": "fail", "judge_score": 0.4},
     {"question": "extraction_verdict", "type": "score", "answer": "fail", "expected": 0.4}),
    ("arbiter", {"arbiter_decision": "retry_extract"}, {"question": "arbiter_route", "answer": "retry_extract"}),
    ("boss_escalation", {"review_decision": "approve"}, {"question": "conflict_ruling", "answer": "approve"}),
])
def test_decision_nodes_map_onto_the_typed_decision_schema(node, out, expected):
    [decision] = node_trace.decisions_for(node, out)
    assert expected.items() <= decision.items()
    assert decision["source"] == "agent" and decision["options"] is None


def test_non_decision_nodes_and_empty_outputs_record_no_decision():
    assert node_trace.decisions_for("intake", {"doc_type": "contract"}) == []
    assert node_trace.decisions_for("classify", {}) == []


@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), "high", None])
def test_out_of_range_probabilities_are_dropped_not_kept(bad):
    [d] = node_trace.decisions_for("classify", {"doc_type": "contract", "classification_confidence": bad})
    assert d["p"] is None


def test_native_decisions_pass_through_validated_and_capped():
    native = [
        {"question": "is_privileged", "type": "noul", "answer": True, "p": 0.83, "source": "decisions"},
        {"question": "doc_type", "type": "choice", "answer": "contract",
         "options": {"contract": 0.7, "correspondence": 0.2, "bogus": 3}},
        {"question": "quality", "type": "score", "expected": 3.4, "options": {"1": 0.1, "5": 0.5}},
        {"question": "ignored", "type": "freeform"},
    ]
    out = node_trace.decisions_for("classify", {"decisions": native, "doc_type": "x"})
    assert [d["type"] for d in out] == ["noul", "choice", "score"]
    assert out[0]["source"] == "decisions" and out[0]["answer"] is True
    assert out[1]["options"] == {"contract": 0.7, "correspondence": 0.2}
    many = [{"question": f"q{i}", "type": "noul", "p": 0.5} for i in range(250)]
    assert len(node_trace.decisions_for("classify", {"decisions": many})) == node_trace.MAX_DECISIONS


def test_summarize_merges_starts_and_ends_and_counts_pauses_as_non_errors():
    recs = [
        {"doc": "a", "node": "intake", "status": "running"}, {"doc": "a", "node": "intake", "status": "done", "ms": 10},
        {"doc": "a", "node": "human_review", "status": "running"},
        {"doc": "a", "node": "human_review", "status": "paused", "ms": 4},
        {"doc": "b", "node": "intake", "status": "running"}, {"doc": "b", "node": "intake", "status": "error", "ms": 30,
                                                               "error": "boom"},
        {"doc": "c", "node": "intake", "status": "running", "agent": None},
    ]
    s = node_trace.summarize(recs, docs=2)
    assert s["current"]["doc"] == "c" and s["current"]["route"][0]["status"] == "running"
    assert [r["doc"] for r in s["recent"]] == ["b", "c"] and s["docs_seen"] == 3
    totals = {t["node"]: t for t in s["nodes"]}
    assert totals["intake"] == {"node": "intake", "visits": 2, "errors": 1, "mean_ms": 20.0}
    assert totals["human_review"]["errors"] == 0
    assert node_trace.summarize([]) is None


def test_store_node_tail_skips_torn_lines(tmp_path):
    store = RunStore(tmp_path / "r")
    store.append_node({"doc": "a", "node": "intake", "status": "running"})
    with open(store.nodes_path, "a", encoding="utf-8") as fh:
        fh.write('{"doc": "a", "node"\n[1, 2]\n')
    store.append_node({"doc": "a", "node": "intake", "status": "done"})
    assert [r["status"] for r in store.nodes()] == ["running", "done"]
    assert RunStore(tmp_path / "empty").nodes() == []


def test_watch_totals_cover_full_stream_while_routes_use_bounded_tail(tmp_path):
    store = RunStore(tmp_path / "r")
    store.append_node({"doc": "old", "node": "intake", "status": "done", "ms": 10, "padding": "x" * 300_000})
    with open(store.nodes_path, "a", encoding="utf-8") as fh:
        fh.write('invalid json\n')
    store.append_node({"doc": "new", "node": "intake", "status": "error", "ms": 30})
    state = compose_watch_state(store=store, app="a", sink=LogBuffer(None), ledger=None, cap_usd=5,
                                times_dir=None, serving_dir=tmp_path, started=0, boot_mark={})
    pipe = state["pipeline"]
    assert pipe["docs_seen"] == 2
    assert pipe["nodes"] == [{"node": "intake", "visits": 2, "errors": 1, "mean_ms": 20.0}]
    assert [route["doc"] for route in pipe["recent"]] == ["new"]


def test_empty_route_tail_still_renders_aggregate_totals(tmp_path):
    store = RunStore(tmp_path / "r")
    store.append_node({"doc": "large", "node": "intake", "status": "done", "ms": 10, "padding": "x" * 300_000})
    pipe = node_trace.summarize(store.iter_nodes(), recent_records=store.nodes())
    assert pipe["current"] is None and pipe["recent"] == []
    assert "1 docs" in pipeline_lines(pipe)[0]


def test_node_helpers_and_watch_import_without_langchain():
    import subprocess
    import sys

    code = '''
import importlib.abc
import sys
class BlockLangchain(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "langchain_core" or fullname.startswith("langchain_core."):
            raise ModuleNotFoundError("blocked langchain_core")
sys.meta_path.insert(0, BlockLangchain())
from mailroom_sandbox.job import node_trace
from mailroom_sandbox import watch
assert node_trace.summarize([{"doc": "a", "node": "intake", "status": "done", "ms": 1}])["docs_seen"] == 1
try:
    with node_trace.track_nodes("a", lambda rec: None):
        pass
except RuntimeError as exc:
    assert "langchain_core" in str(exc)
else:
    raise AssertionError("tracking should require the hook")
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def _pipeline_run(tmp_path, capsys):
    config = tmp_path / "run.yaml"
    run_id = f"nodes-{tmp_path.name[-8:]}"
    config.write_text(
        f"schema: sandbox.run/v1\nrun_id: {run_id}\ntask: pipeline\nprofile: ollama\n"
        "dataset: {provider: file, local_path: data/fixtures/hf/docclass_mini.jsonl, limit: 2, sample_seed: 1}\n"
        "engine: {kind: vllm-local, model: qwen3:8b, modal: null}\njob: {mode: endpoint, mock: true, concurrency: 1}\n"
        "trace: {sink: none}\n")
    assert cli.main(["run", "start", "--config", str(config), "--mock"]) == 0
    out = capsys.readouterr().out
    return run_id, json.loads(out[out.index("{"):])


@pytest.fixture
def runs(job_data_dir, monkeypatch):
    from mailroom_sandbox.eval import experiment_log

    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: job_data_dir / "log.jsonl")
    monkeypatch.setattr(experiment_log, "md_path", lambda: job_data_dir / "log.md")
    return job_data_dir


def test_a_mock_pipeline_run_records_every_graph_node_it_enters(runs, capsys):
    from mailroom_sandbox.job.checkpoint import store_for

    run_id, out = _pipeline_run(runs, capsys)
    store = store_for(run_id)
    recs = store.nodes()
    docs = {r["doc"] for r in recs}
    assert len(docs) == out["total"] == 2
    for doc in docs:
        nodes = [r["node"] for r in recs if r["doc"] == doc and r["status"] == "running"]
        assert nodes[:2] == ["intake", "classify"]  # graph order, one record per node entered
    classify = next(r for r in recs if r["node"] == "classify" and r["status"] == "done")
    assert classify["agent"] == "sorter" and classify["model"]  # the routed model rides along
    assert classify["decisions"][0]["type"] == "choice"
    assert not any(r["status"] == "running" and r.get("decisions") for r in recs)

    state = compose_watch_state(store=store, app="a", sink=LogBuffer(None), ledger=None, cap_usd=5.0,
                                times_dir=None, serving_dir=runs, started=0, boot_mark={})
    assert state["pipeline"]["docs_seen"] == 2
    json.dumps(state)  # the frame stays SSE-serializable


def test_terminal_frame_shows_the_pipeline_floor(tmp_path):
    demo = DemoRun(tmp_path, n_docs=4, pipeline=True)
    sink = LogBuffer(None)
    for tick in range(10):  # through the first three documents
        demo.step(sink, tick=tick)
    store, app = demo.resolve()
    state = compose_watch_state(store=store, app=app, sink=sink, ledger=demo.ledger, cap_usd=5.0,
                                times_dir=demo.times_dir, serving_dir=demo.serving_dir, started=0, boot_mark={})
    assert state["layout"]["task"] == "pipeline"
    pipe = state["pipeline"]
    assert pipe["current"]["route"] == [{"node": "intake", "status": "running", "agent": None, "model": None}]
    prev = pipe["recent"][-2]["route"]
    assert [h["node"] for h in prev][:4] == ["intake", "classify", "extract", "judge_verify"]
    frame = render_frame(snapshot=state["snapshot"], app=app, log_lines=[], spend=state["spend"],
                         layout=state["layout"], pipeline=pipe)
    assert "PIPELINE FLOOR" in frame and "now · DOC-demo-00-003: intake…" in frame
    assert "previous · DOC-demo-00-002: intake✓ → classify✓" in frame
    lines = pipeline_lines(pipe)
    assert any("doc_type [choice] insurance_claim · p=0.89" in line for line in lines)
    assert any("(sorter · Qwen/Qwen3-8B-AWQ)" in line for line in lines)


def test_specialist_runs_have_no_floor(tmp_path):
    demo = DemoRun(tmp_path, n_docs=2)
    for tick in range(9):
        demo.step(LogBuffer(None), tick=tick)
    store, app = demo.resolve()
    state = compose_watch_state(store=store, app=app, sink=LogBuffer(None), ledger=demo.ledger, cap_usd=5.0,
                                times_dir=demo.times_dir, serving_dir=demo.serving_dir, started=0, boot_mark={})
    assert state["pipeline"] is None
    assert "PIPELINE FLOOR" not in render_frame(snapshot=state["snapshot"], app=app, log_lines=[],
                                                spend=state["spend"], pipeline=state["pipeline"])


def test_dev_pipeline_flag_parses():
    assert cli.build_parser().parse_args(["dev", "--pipeline", "--no-browser"]).pipeline is True
