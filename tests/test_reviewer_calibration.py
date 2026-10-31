"""Reviewer cutoff calibration from a labelled run (SAND-085)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import load_run_spec

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("calibrate_reviewer", ROOT / "scripts/calibrate_reviewer.py")
calibrate_reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibrate_reviewer)


def _store(tmp_path, items, rows):
    store = RunStore(tmp_path / "run")
    store.dir.mkdir(parents=True, exist_ok=True)
    store.dataset_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    for item in items:
        store.append_item(item)
    return store


def _run(tmp_path, answers, name="contract"):
    rows = [{"id": str(i), "expected_doc_class": name} for i in range(len(answers))]
    items = [{"item_id": str(i), "ok": True, "pred": {"doc_type": label, "confidence": confidence}}
             for i, (label, confidence) in enumerate(answers)]
    return _store(tmp_path, items, rows)


def test_cutoff_is_the_lowest_confidence_reaching_the_target():
    rows = [(0.5, False), (0.7, False), (0.8, True), (0.9, True)]
    assert calibrate_reviewer._cutoff(rows, 0.95) == 0.8


def test_holdout_reports_what_the_cutoff_delivers(tmp_path):
    answers = [("contract", 0.9)] * 20 + [("correspondence", 0.5)] * 20
    result = calibrate_reviewer.calibrate(_run(tmp_path, answers))["classes"]["contract"]
    assert result["cutoff"] == 0.9
    assert result["holdout_accuracy"] == 1.0
    assert 0 < result["holdout_share_accepted"] < 1


def test_class_that_never_reaches_the_target_gets_no_cutoff(tmp_path):
    result = calibrate_reviewer.calibrate(_run(tmp_path, [("correspondence", 0.9)] * 10))
    assert result["classes"]["contract"]["cutoff"] is None


def test_failed_answers_cannot_clear_a_cutoff(tmp_path):
    rows = [{"id": "a", "expected_doc_class": "contract"}]
    store = _store(tmp_path, [{"item_id": "a", "ok": False, "pred": None}], rows)
    assert calibrate_reviewer._rows(store) == {"contract": [(0.0, False)]}


def test_calibration_run_is_capped_and_uses_a_non_qwen_model():
    run = load_run_spec(ROOT / "config/runs/reviewer-calibration-gemma4.yaml")
    assert run.task == "sorter_reviewer" and run.engine.model.startswith("google/gemma-4")
    assert run.job.cost_cap_usd <= 1.0 and run.engine.modal.max_containers == 1
