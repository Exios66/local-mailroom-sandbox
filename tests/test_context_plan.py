"""Preflight context plan: chunk fan-out, judge/arbiter coverage, degenerate rows."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import context_plan, preflight
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec

TAXONOMY = {
    "doc_classes": [
        {"key": "merger_agreement", "specialist": "merger_agreement_specialist"},
        {"key": "correspondence", "specialist": "correspondence_specialist"},
        {"key": "legacy", "specialist": "legacy_specialist", "status": "retired"},
    ],
    "agents": {
        "merger_agreement_specialist": {"max_input_chars": 36008},
        "correspondence_specialist": {"max_input_chars": 15312},
        "judge": {"max_input_chars": 80000},
    },
    "chunking": {"enabled": True, "chunk_chars": 90000, "overlap_chars": 8000},
}
WINDOWS = {"judge": 16000, "arbiter": 16000}


def _rows():
    return [
        {"id": "m1", "expected_doc_class": "merger_agreement", "doc_text": "x" * 418_669},
        {"id": "m2", "expected_doc_class": "merger_agreement", "doc_text": "x" * 12_000},
        {"id": "c1", "expected_doc_class": "correspondence", "doc_text": "hello " * 200},
        {"id": "c2", "expected_doc_class": "correspondence", "doc_text": "Re: lunch?"},
    ]


def test_window_plan_mirrors_the_vendored_cap():
    # overlap = min(8000, 36008 // 8) = 4501; chunk = min(90000, 36008 - 4501)
    assert context_plan.window_plan(36008, TAXONOMY["chunking"]) == (31507, 4501)
    assert context_plan.window_plan(98000, TAXONOMY["chunking"]) == (90000, 8000)


def test_plan_reports_fan_out_coverage_and_tiny_rows():
    cp = context_plan.plan(TAXONOMY, _rows(), windows=WINDOWS)
    merger = cp["classes"]["merger_agreement"]
    assert merger["max_chunks_per_pass"] == 14 and merger["longest_doc"] == "m1"
    assert merger["judge_coverage_min"] == pytest.approx(16000 / 418_669, abs=1e-4)
    assert cp["classes"]["correspondence"]["max_chunks_per_pass"] == 1
    assert cp["tiny_docs"] == ["c2"]
    text = "\n".join(cp["warnings"])
    assert "~14 chunks per extraction pass" in text
    assert "agent_knobs.merger_agreement_specialist.max_input_chars" in text
    assert "1/2 document(s) exceed the judge source window" in text
    assert "agents.judge.max_input_chars=80000 has no effect" in text
    assert "under 200 chars" in text and "c2" in text
    assert "correspondence: " not in text  # fits every window


def test_widened_budget_clears_the_fan_out_warning():
    widened = json.loads(json.dumps(TAXONOMY))
    widened["agents"]["merger_agreement_specialist"]["max_input_chars"] = 98000
    cp = context_plan.plan(widened, _rows(), windows=WINDOWS)
    assert cp["classes"]["merger_agreement"]["max_chunks_per_pass"] == 5
    assert not any("chunks per extraction pass" in w for w in cp["warnings"])


def test_disabled_chunking_warns_about_truncation():
    off = {**TAXONOMY, "chunking": {"enabled": False}}
    cp = context_plan.plan(off, _rows(), windows=WINDOWS)
    assert any("chunking is disabled" in w for w in cp["warnings"])


def test_source_windows_read_the_vendored_constants():
    windows = context_plan.source_windows()
    assert set(windows) == {"judge", "arbiter"}
    assert all(isinstance(v, int) and v > 0 for v in windows.values()), windows


def test_source_windows_tolerate_a_missing_tree(tmp_path):
    assert context_plan.source_windows(tmp_path) == {"judge": None, "arbiter": None}


def _pipeline_spec(tmp_path, monkeypatch, text_len=50_000, task="pipeline"):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    path = tmp_path / "p.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "p0", "filename": "p0.txt", "doc_text": "agreement " * (text_len // 10),
                             "expected_doc_class": "merger_agreement", "expected": "merger_agreement"}) + "\n")
    return RunSpec(
        run_id=f"run-cp-{task}",
        task=task,
        dataset=DatasetSpec(local_path=f"file://{path}", limit=1),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        job={"mock": True},
    )


def test_preflight_attaches_the_plan_without_failing(tmp_path, monkeypatch):
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch), offline=True)
    assert report["status"] == "prepared", report
    check = next(c for c in report["checks"] if c["name"] == "context_plan")
    assert check["ok"] is True and "judge source window" in check["detail"]
    assert report["context_plan"]["classes"]["merger_agreement"]["docs"] == 1


def test_preflight_survives_a_plan_error(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("no taxonomy")

    monkeypatch.setattr(context_plan, "plan_for_spec", boom)
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch), offline=True)
    assert report["status"] == "prepared", report
    check = next(c for c in report["checks"] if c["name"] == "context_plan")
    assert check["ok"] is True and check["detail"] == "skipped: no taxonomy"


def test_preflight_skips_the_plan_for_sorter_runs(tmp_path, monkeypatch):
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch, task="sorter"), offline=True)
    assert report["status"] == "prepared", report
    assert "context_plan" not in report
