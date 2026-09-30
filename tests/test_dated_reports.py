"""Dated specialist report tree (local-date / specialist / cell stem)."""

from __future__ import annotations

from datetime import datetime

from mailroom_sandbox.job import dated_reports
from mailroom_sandbox.job.checkpoint import RunStore


def _specialist_store(tmp_path, *, mock: bool = False) -> RunStore:
    store = RunStore(tmp_path / "grid-20-merger-specialist-awq-1l4")
    store.write_lock(
        {
            "run_id": store.run_id,
            "task": "merger_agreement_specialist",
            "profile": "modal-vllm",
            "spec_hash": "abc",
            "engine": {
                "model": "Qwen/Qwen3-8B-AWQ",
                "modal": {"gpu": "L4", "max_containers": 1, "min_containers": 1},
            },
            "job": {"mock": mock, "concurrency": 8, "mode": "endpoint"},
            "dataset": {"limit": 20},
            "prompt": {"default": {"source": "local", "file": "merger_agreement_specialist_simplified"}},
        }
    )
    store.append_item(
        {
            "item_id": "DOC-1",
            "index": 0,
            "ok": True,
            "latency_ms": 110000.0,
            "prompt_tokens": 10000,
            "completion_tokens": 900,
            "ts": "2026-09-30T04:54:59.000+00:00",
            "score": {"overall_extraction_score": 0.04, "schema_valid": True},
        }
    )
    return store


def test_cell_stem_encodes_n_shape_concurrency(tmp_path):
    store = _specialist_store(tmp_path)
    folder, stem = dated_reports.cell_stem(store)
    assert folder == "merger_agreement"
    assert stem == "RUN-20-MERGER-AWQ-1L4-C8"


def test_cell_stem_retry_suffix_does_not_clobber(tmp_path):
    store = RunStore(tmp_path / "grid-20-merger-specialist-awq-1l4-retry")
    store.write_lock(
        {
            "run_id": store.run_id,
            "task": "merger_agreement_specialist",
            "engine": {
                "model": "Qwen/Qwen3-8B-AWQ",
                "modal": {"gpu": "L4", "max_containers": 1},
            },
            "job": {"concurrency": 8},
            "dataset": {"limit": 20},
        }
    )
    folder, stem = dated_reports.cell_stem(store)
    assert folder == "merger_agreement"
    assert stem == "RUN-20-MERGER-AWQ-1L4-C8-RETRY"


def test_write_run_reports_lands_under_local_date(tmp_path):
    store = _specialist_store(tmp_path)
    now = datetime(2026, 9, 29, 23, 58)
    paths = dated_reports.write_run_reports(store, repo=tmp_path, now=now, wall_seconds=200.0)
    assert paths["report"].name == "RUN-20-MERGER-AWQ-1L4-C8-REPORT.md"
    assert paths["serving_md"].name == "RUN-20-MERGER-AWQ-1L4-C8-SERVING.md"
    assert paths["serving_json"].name == "RUN-20-MERGER-AWQ-1L4-C8.serving.json"
    assert paths["dir"] == tmp_path / "reports" / "2026-09-29" / "merger_agreement"
    text = paths["report"].read_text(encoding="utf-8")
    assert "grid-20-merger-specialist-awq-1l4" in text
    assert "Qwen/Qwen3-8B-AWQ" in text
    serving = paths["serving_md"].read_text(encoding="utf-8")
    assert "gpu_cost_per_document" in serving
    assert (tmp_path / "reports" / "serving" / f"{store.run_id}.serving.json").is_file()


def test_mock_jobs_do_not_write_dated_tree(tmp_path):
    store = _specialist_store(tmp_path, mock=True)
    assert dated_reports.write_run_reports(store, repo=tmp_path) == {}
