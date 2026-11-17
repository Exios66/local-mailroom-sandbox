"""SAND-104 (#312): a run records and checks the checkout its code was imported from."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mailroom_sandbox.job import preflight
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import DatasetSpec, JobSpec, RunSpec, run_dir

REPO = Path(__file__).resolve().parents[1]


def _spec(tmp_path, run_id="pkg-1") -> RunSpec:
    path = tmp_path / "f.jsonl"
    path.write_text(json.dumps({"id": "d0", "filename": "0.txt", "doc_text": "t0", "expected": "contract",
                                "expected_subclass": "service"}) + "\n", encoding="utf-8")
    return RunSpec(run_id=run_id, task="sorter", dataset=DatasetSpec(local_path=f"file://{path}", limit=1),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"})


def _check(report):
    return next(c for c in report["checks"] if c["name"] == "checkout")


def test_package_checkout_is_the_checkout_this_code_was_imported_from():
    found = preflight.package_checkout()
    assert Path(found["path"]) == REPO
    assert found["commit"] is None or len(found["commit"]) == 40


def test_the_lock_records_the_imported_package_checkout(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr(preflight, "package_checkout", lambda: {"path": "/src/checkout", "commit": "a" * 40})
    monkeypatch.setattr(preflight, "_cwd_checkout", lambda: Path("/src/checkout"))
    spec = _spec(tmp_path)
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    assert _check(report)["ok"] is True
    lock = RunStore(run_dir(spec.run_id)).read_lock()
    assert lock["package"] == {"path": "/src/checkout", "commit": "a" * 40}


def test_preflight_fails_when_the_code_comes_from_another_checkout(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.delenv("SANDBOX_ALLOW_FOREIGN_CHECKOUT", raising=False)
    monkeypatch.setattr(preflight, "package_checkout", lambda: {"path": "/src/main", "commit": "b" * 40})
    monkeypatch.setattr(preflight, "_cwd_checkout", lambda: Path("/src/worktree"))
    spec = _spec(tmp_path, run_id="pkg-2")
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "failed"
    check = _check(report)
    assert check["ok"] is False
    assert "/src/main" in check["detail"] and "/src/worktree" in check["detail"] and "PYTHONPATH" in check["detail"]
    assert RunStore(run_dir(spec.run_id)).read_lock() is None  # nothing was locked


def test_a_named_override_accepts_a_foreign_checkout(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setenv("SANDBOX_ALLOW_FOREIGN_CHECKOUT", "1")
    monkeypatch.setattr(preflight, "package_checkout", lambda: {"path": "/src/main", "commit": "b" * 40})
    monkeypatch.setattr(preflight, "_cwd_checkout", lambda: Path("/src/worktree"))
    report = preflight.preflight(_spec(tmp_path, run_id="pkg-3"), offline=True)
    assert report["status"] == "prepared", report
    assert "SANDBOX_ALLOW_FOREIGN_CHECKOUT" in _check(report)["detail"]


def test_a_cwd_outside_any_git_checkout_is_not_a_mismatch(tmp_path, job_data_dir, monkeypatch):
    monkeypatch.setattr(preflight, "_cwd_checkout", lambda: None)
    report = preflight.preflight(_spec(tmp_path, run_id="pkg-4"), offline=True)
    assert report["status"] == "prepared", report
    assert _check(report)["ok"] is True


@pytest.mark.parametrize("model, kwargs", [
    (DatasetSpec, {"local_path": "file:///x.jsonl", "exclude_ids_fle": "typo.txt"}),
    (JobSpec, {"max_wall_second": 60}),
])
def test_an_unknown_spec_key_fails_validation(model, kwargs):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model(**kwargs)


def test_an_unknown_top_level_run_key_fails_validation():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RunSpec(run_id="r", task="sorter", datset={"local_path": "file:///x.jsonl"})
