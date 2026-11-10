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


def test_endpoint_tracer_mirrors_even_with_sink_none(tmp_path):
    from mailroom_sandbox import cli

    tracer = cli._endpoint_tracer("r-endpoint", {"trace": {"sink": "none", "otlp": False}})
    assert tracer is not None
    assert tracer.sandbox_local_path == tmp_path / "traces" / "r-endpoint.spans.jsonl.gz"
    with otel.job_span(tracer, "job.run", run_id="r-endpoint"):
        pass
    otel.flush_tracer(tracer)
    assert len(trace_pack.read_spans(tracer.sandbox_local_path)) == 1
