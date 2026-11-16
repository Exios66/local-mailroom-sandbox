"""Opt-in OTel integration for the local span mirror (requires opentelemetry-sdk)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("opentelemetry.sdk")

from mailroom_sandbox.job import otel, preflight, runner, trace_pack
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))


def _prepped_store(tmp_path, rows=4, run_id="run-t1", job=None):
    path = tmp_path / "f.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(json.dumps({"id": f"d{i}", "filename": f"{i}.txt", "doc_text": f"t{i}", "expected": "contract"}) + "\n")
    spec = RunSpec(
        run_id=run_id,
        task="sorter",
        dataset=DatasetSpec(local_path=f"file://{path}", limit=rows),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        job=job or {"mock": True},
    )
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    return RunStore(run_dir(report["run_id"]))


def _traced_run(tmp_path, rows=6, concurrency=3):
    store = _prepped_store(tmp_path, rows=rows, job={"mock": True, "concurrency": concurrency})
    mirror = tmp_path / "traces" / f"{store.run_id}.spans.jsonl.gz"
    tracer = otel.configure_tracing(otel.resolve_sink(sink="none", run_id=store.run_id), local_path=mirror)
    assert tracer is not None
    with otel.job_span(tracer, "job.run", run_id=store.run_id):
        summary = runner.run_job(store, mock=None, tracer=tracer)
    otel.flush_tracer(tracer)
    return store, mirror, summary


def test_local_mirror_nests_item_spans_under_run(tmp_path):
    store, mirror, summary = _traced_run(tmp_path)
    assert summary["state"] == "done"
    spans = trace_pack.read_spans(mirror)
    roots = [s for s in spans if s["name"] == "job.run"]
    items = [s for s in spans if s["name"] == "job.item"]
    assert len(roots) == 1 and len(items) == 6
    # Items run on worker threads yet still hang off the run span.
    assert {s["parent_span_id"] for s in items} == {roots[0]["span_id"]}
    assert {s["trace_id"] for s in spans} == {roots[0]["trace_id"]}
    assert all(s["attributes"]["job.ok"] is True for s in items)
    assert roots[0]["resource"]["sandbox.run_id"] == store.run_id


def test_whole_run_pipeline_mirrors_item_and_node_spans(tmp_path):
    """A whole-run task (pipeline) gets one job.item per document plus job.node children."""
    path = tmp_path / "p.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(2):
            fh.write(json.dumps({"id": f"p{i}", "filename": f"p{i}.txt", "doc_text": f"agreement {i}",
                                 "expected_doc_class": "contract", "expected": "contract"}) + "\n")
    spec = RunSpec(
        run_id="run-pipe-spans",
        task="pipeline",
        dataset=DatasetSpec(local_path=f"file://{path}", limit=2),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        job={"mock": True},
    )
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    store = RunStore(run_dir(report["run_id"]))
    mirror = tmp_path / "traces" / f"{store.run_id}.spans.jsonl.gz"
    tracer = otel.configure_tracing(otel.resolve_sink(sink="none", run_id=store.run_id), local_path=mirror)
    with otel.job_span(tracer, "job.run", run_id=store.run_id):
        summary = runner.run_job(store, mock=None, tracer=tracer)
    otel.flush_tracer(tracer)
    assert summary["state"] == "done", summary

    spans = trace_pack.read_spans(mirror)
    root = next(s for s in spans if s["name"] == "job.run")
    items = [s for s in spans if s["name"] == "job.item"]
    assert sorted(s["attributes"]["item_id"] for s in items) == ["p0", "p1"]
    assert {s["parent_span_id"] for s in items} == {root["span_id"]}
    assert all(s["end_time_unix_nano"] > s["start_time_unix_nano"] for s in items)
    nodes = [s for s in spans if s["name"] == "job.node"]
    finished = [n for n in store.nodes() if n.get("status") == "done"]
    assert nodes, "pipeline documents report graph nodes; each finished node becomes a span"
    assert len(nodes) == len(finished)
    assert {n["attributes"]["node"] for n in nodes} == {n["node"] for n in finished}
    item_ids = {s["span_id"]: s["attributes"]["item_id"] for s in items}
    assert all(n["parent_span_id"] in item_ids for n in nodes)
    assert all(n["attributes"]["item_id"] == item_ids[n["parent_span_id"]] for n in nodes)
    assert {s["trace_id"] for s in spans} == {root["trace_id"]}


def _span_recorder(tmp_path):
    mirror = tmp_path / "traces" / "r-spans.spans.jsonl.gz"
    tracer = otel.configure_tracing(otel.resolve_sink(sink="none", run_id="r-spans"), local_path=mirror)
    return tracer, mirror, runner._WholeRunSpans(tracer, None, task="pipeline")


def test_whole_run_spans_keep_failed_nodes_as_error_spans(tmp_path):
    tracer, mirror, spans = _span_recorder(tmp_path)
    spans.node({"doc": "d1", "node": "intake", "status": "done", "ts": 100.0, "ms": 50})
    spans.node({"doc": "d1", "node": "extract", "status": "error", "ts": 101.0, "ms": 200})
    spans.node({"doc": "d1", "node": "extract", "status": "running", "ts": 100.8})
    spans.item({"id": "d1", "latency_ms": 1500, "pred": {"stage": "failed"}, "error": "pipeline failed"})
    otel.flush_tracer(tracer)
    nodes = {s["attributes"]["node"]: s for s in trace_pack.read_spans(mirror) if s["name"] == "job.node"}
    assert set(nodes) == {"intake", "extract"}
    assert nodes["extract"]["status_code"] == "ERROR" and nodes["intake"]["status_code"] != "ERROR"


def test_whole_run_spans_flush_documents_that_raised(tmp_path):
    """A document that raised has no item row; its buffered nodes still become a failed job.item."""
    tracer, mirror, spans = _span_recorder(tmp_path)
    spans.node({"doc": "d2", "node": "intake", "status": "done", "ts": 200.0, "ms": 40})
    spans.node({"doc": "d2", "node": "classify", "status": "error", "ts": 201.0, "ms": 900})
    spans.flush_unfinished("RuntimeError: boom")
    otel.flush_tracer(tracer)
    got = trace_pack.read_spans(mirror)
    item = next(s for s in got if s["name"] == "job.item")
    assert item["attributes"]["item_id"] == "d2" and item["attributes"]["job.ok"] is False
    assert item["attributes"]["job.error"] == "RuntimeError: boom" and item["status_code"] == "ERROR"
    assert item["end_time_unix_nano"] == int(201.0 * 1e9)
    assert len([s for s in got if s["name"] == "job.node"]) == 2


def test_endpoint_tracer_mirrors_even_with_sink_none(tmp_path):
    from mailroom_sandbox import cli

    tracer = cli._endpoint_tracer("r-endpoint", {"trace": {"sink": "none", "otlp": False}})
    assert tracer is not None
    assert tracer.sandbox_local_path == tmp_path / "traces" / "r-endpoint.spans.jsonl.gz"
    with otel.job_span(tracer, "job.run", run_id="r-endpoint"):
        pass
    otel.flush_tracer(tracer)
    assert len(trace_pack.read_spans(tracer.sandbox_local_path)) == 1
