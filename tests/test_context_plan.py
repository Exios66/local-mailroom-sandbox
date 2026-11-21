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
    check = next(c for c in report["checks"] if c["name"] == "expanded_inputs")
    assert check["ok"] is True


def test_a_changed_context_fit_refuses_resume(tmp_path, monkeypatch):
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    spec = _pipeline_spec(tmp_path, monkeypatch)
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    store = RunStore(run_dir(spec.run_id))
    lock = store.read_lock()
    assert lock["context_fit"]["sha256"]
    lock["context_fit"]["sha256"] = "0" * 64
    store.lock_path.write_text(json.dumps(lock))
    again = preflight.preflight(spec, offline=True)
    assert again["status"] == "drift_refused"
    assert "context fit" in again["detail"]


def test_preflight_requires_expanded_inputs_on_openrouter(tmp_path, monkeypatch):
    spec = _pipeline_spec(tmp_path, monkeypatch)
    spec = RunSpec.model_validate({
        **spec.model_dump(),
        "profile": "openrouter",
        "engine": {"kind": "openrouter", "model": "qwen/qwen3.7-flash", "modal": None},
        "job": {**spec.job.model_dump(), "require_expanded_inputs": True},
    })
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    check = next(c for c in report["checks"] if c["name"] == "expanded_inputs")
    assert check["ok"] is True and "judge=" in check["detail"]
    assert report["expanded_inputs"]["gaps"] == []


def test_preflight_fails_when_expanded_inputs_are_required_and_missing(tmp_path, monkeypatch):
    def short(_taxonomy):
        return {"agents": [{"agent": "judge", "expanded": False, "max_input_chars": 80000}],
                "gaps": ["judge: max_input_chars=80000 was not expanded"], "source_windows": {}}

    monkeypatch.setattr("mailroom_sandbox.context_fit.expansion_status", short)
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch), offline=True, require_expanded_inputs=True)
    assert report["status"] == "failed"
    check = next(c for c in report["checks"] if c["name"] == "expanded_inputs")
    assert check["ok"] is False and "judge:" in check["detail"]


def test_chunk_count_keeps_paragraphs_intact():
    text = "\n\n".join("y" * 20_000 for _ in range(5))
    assert context_plan.chunk_count(text, 31_507) == 5  # len/window would say 4
    assert context_plan.chunk_count("x" * 418_669, 31_507) == 14
    assert context_plan.chunk_count("short", 31_507) == 1
    tax = json.loads(json.dumps(TAXONOMY))
    tax["agents"]["merger_agreement_specialist"]["max_input_chars"] = 36008
    rows = [{"id": "p", "expected_doc_class": "merger_agreement", "doc_text": text}]
    cp = context_plan.plan(tax, rows, windows=WINDOWS)
    assert cp["classes"]["merger_agreement"]["max_chunks_per_pass"] == 5
    assert any("~5 chunks per extraction pass" in w for w in cp["warnings"])


def test_arbiter_window_is_checked_on_its_own():
    rows = [{"id": "m", "expected_doc_class": "merger_agreement", "doc_text": "x" * 400_000}]
    cp = context_plan.plan(TAXONOMY, rows, windows={"judge": 500_000, "arbiter": 16_000})
    entry = cp["classes"]["merger_agreement"]
    assert entry["judge_coverage_min"] == 1.0 and entry["arbiter_coverage_min"] == pytest.approx(0.04)
    text = "\n".join(cp["warnings"])
    assert "exceed the arbiter source window" in text and "exceed the judge source window" not in text


def test_isolated_specialist_plan_follows_the_chunk_knob():
    rows = [{"id": "m", "expected_doc_class": "merger_agreement", "doc_text": "x" * 100_000}]
    single = context_plan.plan(TAXONOMY, rows, windows=WINDOWS, task="specialist")
    entry = single["classes"]["merger_agreement"]
    assert entry["chunked"] is False and entry["max_chunks_per_pass"] == 1 and "judge_coverage_min" not in entry
    assert any("no chunk_chars knob (single pass)" in w for w in single["warnings"])
    assert not any("judge" in w for w in single["warnings"])
    knobs = {"merger_agreement_specialist": {"chunk_chars": 30_000, "overlap_chars": 2_000}}
    chunked = context_plan.plan(TAXONOMY, rows, windows=WINDOWS, task="specialist", knobs=knobs)
    entry = chunked["classes"]["merger_agreement"]
    assert entry["chunked"] is True and entry["chunk_chars"] == 30_000 and entry["max_chunks_per_pass"] == 4


def test_plan_uses_the_target_rows_and_runs_on_an_existing_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    path = tmp_path / "t.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i, cls in enumerate(("contract", "merger_agreement")):
            fh.write(json.dumps({"id": f"t{i}", "filename": f"t{i}.txt", "doc_text": "word " * 5_000,
                                 "expected_doc_class": cls, "expected": cls}) + "\n")
    spec = RunSpec(run_id="run-cp-target", task="pipeline", target="contract",
                   dataset=DatasetSpec(local_path=f"file://{path}", limit=2),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"}, job={"mock": True})
    first = preflight.preflight(spec, offline=True)
    assert first["status"] == "prepared", first
    assert set(first["context_plan"]["classes"]) == {"contract"}
    again = preflight.preflight(spec, offline=True)
    assert again["context_plan"]["classes"] == first["context_plan"]["classes"]


def test_preflight_plans_whole_run_specialist_tasks(tmp_path, monkeypatch):
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch, task="specialist"), offline=True)
    assert report["status"] == "prepared", report
    assert report["context_plan"]["task"] == "specialist"


def test_isolated_specialist_zero_overlap_falls_back_like_the_evaluator():
    from mailroom_sandbox.eval.agents import chunk_window

    rows = [{"id": "m", "expected_doc_class": "merger_agreement", "doc_text": "x" * 100_000}]
    knobs = {"merger_agreement_specialist": {"chunk_chars": 90_000, "overlap_chars": 0}}
    entry = context_plan.plan(TAXONOMY, rows, windows=WINDOWS, task="specialist", knobs=knobs)["classes"]["merger_agreement"]
    window, _ = chunk_window(36008, 90_000, 8_000)  # _live_specialist: `overlap_chars or 8_000`
    assert entry["chunk_chars"] == window == 31_507 and entry["max_chunks_per_pass"] == 4


def test_fan_out_warning_names_the_document_with_the_most_chunks():
    tax = json.loads(json.dumps(TAXONOMY))
    rows = [{"id": "long", "expected_doc_class": "merger_agreement", "doc_text": "x" * 150_000},
            {"id": "paras", "expected_doc_class": "merger_agreement",
             "doc_text": "\n\n".join("y" * 16_000 for _ in range(8))}]
    entry = context_plan.plan(tax, rows, windows=WINDOWS)["classes"]["merger_agreement"]
    assert entry["longest_doc"] == "long" and entry["max_chunks_doc"] == "paras"
    assert entry["max_chunks_per_pass"] == 8
    cp = context_plan.plan(tax, rows, windows=WINDOWS)
    assert any("document paras (128014 chars) splits into ~8 chunks" in w for w in cp["warnings"])


def test_plan_and_lock_resolve_knobs_from_the_same_run_id(tmp_path, monkeypatch):
    from mailroom_sandbox.job import specialist_posture
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    seen = []

    def posture(run_id):
        seen.append(run_id)
        return {"merger_agreement_specialist": {"max_input_chars": 98_000}} if run_id == "cli-id" else None

    monkeypatch.setattr(specialist_posture, "agent_knobs_for_run", posture)
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch), run_id="cli-id", offline=True)
    assert report["status"] == "prepared", report
    assert set(seen) == {"cli-id"}
    assert report["context_plan"]["classes"]["merger_agreement"]["input_budget"] == 98_000
    lock = RunStore(run_dir("cli-id")).read_lock()
    assert lock["agent_knobs"]["merger_agreement_specialist"]["max_input_chars"] == 98_000


def test_plan_and_lock_share_one_knob_snapshot(tmp_path, monkeypatch):
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    calls = []
    real = preflight._run_knobs

    def once(spec, run_id):
        calls.append(run_id)
        return real(spec, run_id)

    monkeypatch.setattr(preflight, "_run_knobs", once)
    monkeypatch.setenv("SANDBOX_AGENT_KNOBS", json.dumps({"merger_agreement_specialist": {"max_input_chars": 98_000}}))
    report = preflight.preflight(_pipeline_spec(tmp_path, monkeypatch, task="merger_agreement_specialist"), offline=True)
    assert report["status"] == "prepared", report
    assert len(calls) == 1
    lock = RunStore(run_dir(report["run_id"])).read_lock()
    assert report["context_plan"]["classes"]["merger_agreement"]["input_budget"] \
        == lock["agent_knobs"]["merger_agreement_specialist"]["max_input_chars"] == 98_000
