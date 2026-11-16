"""``sandbox run gate``: artifacts, exit codes, step-up and threshold sections (offline, deterministic)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.job import gate

LABELS = {"sender": "A. Smith", "recipient": "B. Jones"}


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A checkout-shaped data dir: ``<tmp>/data/{runtime/runs,traces,archive}``, selected via MAILROOM_BASE_DIR."""
    root = tmp_path / "data"
    (root / "runtime" / "runs").mkdir(parents=True)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(root))
    return root


def _run(data: Path, run_id: str, docs, *, trail=True):
    """docs: dicts with id and optional score / stage / error / confidence."""
    run = data / "runtime" / "runs" / run_id
    run.mkdir()
    (run / "spec.lock.json").write_text(json.dumps({"run_id": run_id, "trace": {"sink": "none"}}))
    (data / "traces").mkdir(exist_ok=True)
    spans = gzip.open(data / "traces" / f"{run_id}.spans.jsonl.gz", "wt")
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it, \
            open(run / "nodes.jsonl", "w") as nd:
        for d in docs:
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": "correspondence",
                                 "expected_fields": json.dumps(LABELS)}) + "\n")
            stage = d.get("stage", "archived")
            pred = {"stage": stage, "doc_type": "correspondence", "_score": d.get("score", 0.95),
                    "extraction_confidence": d.get("confidence", 0.95),
                    "review_causes": [], "extracted_data": {}}
            it.write(json.dumps({"item_id": d["id"], "ok": d.get("error") is None, "error": d.get("error"),
                                 "prompt_tokens": 10, "completion_tokens": 5, "pred": pred}) + "\n")
            nd.write(json.dumps({"doc": d["id"], "node": "intake", "status": "running", "ts": 1.0}) + "\n")
            spans.write(json.dumps({"trace_id": f"t-{run_id}", "span_id": f"s-{d['id']}", "name": "job.item",
                                    "attributes": {"item_id": d["id"]}}) + "\n")
            if stage == "archived" and trail:
                (data / "archive" / f"SANDBOX-sandbox_pipeline_{run_id}-{d['id']}" / "correspondence").mkdir(parents=True)
    spans.close()
    return run


def _ok(*ids):
    return [{"id": i} for i in ids]


def test_gate_cli_writes_artifacts_and_exit_code(data, capsys):
    run = _run(data, "slice-a", _ok("a", "b", "c"))
    assert cli.main(["run", "gate", "--run-id", "slice-a"]) == 0
    report = json.loads((run / "gate.json").read_text())
    assert report["verdict"]["pass"] is True
    md = (run / "gate.md").read_text()
    assert md.startswith("PASS")
    assert "slice-a" in md and "correspondence" in md
    assert str(data.parent) not in md  # no absolute checkout/home paths in the Markdown


def test_gate_cli_fail_exit_2(data):
    run = _run(data, "slice-b", _ok("a", "b") + [{"id": "x", "error": "boom"}])
    assert cli.main(["run", "gate", "--run-id", "slice-b"]) == 2
    md = (run / "gate.md").read_text()
    assert md.startswith("FAIL — ")
    assert "crashed document(s)" in md.splitlines()[0]
    assert json.loads((run / "gate.json").read_text())["verdict"]["pass"] is False


def test_gate_cli_fail_buckets_link_archive_and_span(data):
    run = _run(data, "slice-c", _ok("a", "b") + [{"id": "w", "score": 0.5}])
    assert cli.main(["run", "gate", "--run-id", "slice-c"]) == 2
    md = (run / "gate.md").read_text()
    assert "data/archive/SANDBOX-sandbox_pipeline_slice-c-w" in md
    assert "s-w" in md


def test_gate_cli_prev_run_adds_step_up(data):
    _run(data, "prev", _ok("a", "b"))
    run = _run(data, "next", _ok("a", "b", "c", "d"))
    assert cli.main(["run", "gate", "--run-id", "next", "--prev-run-id", "prev"]) == 0
    report = json.loads((run / "gate.json").read_text())
    assert report["step_up"]["new_docs"] == ["c", "d"]
    md = (run / "gate.md").read_text()
    assert "Step-up" in md and "prev" in md


def test_gate_cli_step_up_failure_fails_the_run(data):
    _run(data, "prev", _ok("a"))
    run = _run(data, "next", _ok("a", "b", "c", "d", "e", "f") + [{"id": "g", "score": 0.4}])
    # whole slice: 1 wrong of 7 archives fails already; make sure the verdict names the step-up too
    assert cli.main(["run", "gate", "--run-id", "next", "--prev-run-id", "prev"]) == 2
    assert (run / "gate.md").read_text().startswith("FAIL")


def test_gate_cli_same_slice_rerun_is_a_paired_check(data):
    """Re-running the fixed slice and pairing it with the earlier run passes when not worse (review I1)."""
    _run(data, "first", _ok("a", "b", "c"))
    run = _run(data, "rerun", _ok("a", "b", "c"))
    assert cli.main(["run", "gate", "--run-id", "rerun", "--prev-run-id", "first"]) == 0
    report = json.loads((run / "gate.json").read_text())
    assert "step_up" not in report and report["rerun"]["same_documents"] is True
    assert "Re-run" in (run / "gate.md").read_text()


def test_gate_cli_missing_run(data, capsys):
    assert cli.main(["run", "gate", "--run-id", "nope"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "failed" and "nope" in out["detail"]


def test_gate_cli_missing_prev_run(data, capsys):
    _run(data, "only", _ok("a"))
    assert cli.main(["run", "gate", "--run-id", "only", "--prev-run-id", "ghost"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_gate_cli_json_prints_report(data, capsys):
    _run(data, "slice-j", _ok("a", "b"))
    assert cli.main(["run", "gate", "--run-id", "slice-j", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"] == "slice-j" and out["verdict"]["pass"] is True


def test_gate_cli_flags_work_before_or_after_subcommand(data):
    run = _run(data, "slice-f", _ok("a", "b"))
    assert cli.main(["run", "--profile", "local", "gate", "--run-id", "slice-f"]) == 0
    assert cli.main(["run", "gate", "--run-id", "slice-f", "--profile", "local"]) == 0
    assert (run / "gate.json").is_file()


def test_gate_cli_thresholds_adds_labelled_table(data):
    run = _run(data, "slice-t", _ok("a", "b") + [{"id": "lo", "score": 0.5, "confidence": 0.5}])
    assert cli.main(["run", "gate", "--run-id", "slice-t", "--thresholds", "--json"]) == 2
    report = json.loads((run / "gate.json").read_text())
    assert "thresholds" in report and report["thresholds"]["pooled"]["archived"] == 3
    md = (run / "gate.md").read_text()
    assert "upper bound" in md and "0.90" in md


def test_gate_cli_custom_bars(data, tmp_path):
    run = _run(data, "slice-k", _ok("a", "b") + [{"id": "w", "score": 0.5}])
    bars = tmp_path / "bars.yaml"
    bars.write_text("wrong_archive_max: 0.5\n")
    assert cli.main(["run", "gate", "--run-id", "slice-k", "--bars", str(bars)]) == 0
    assert (run / "gate.json").is_file()


def test_gate_cli_preflight_only_run_is_an_error_not_a_fail(data, capsys):
    """A run that was preflighted but never started has no items: exit 1, not 100 crashes (review M2)."""
    run = _run(data, "preflighted", _ok("a", "b"))
    (run / "items.jsonl").unlink()
    assert cli.main(["run", "gate", "--run-id", "preflighted"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "failed" and "never started" in out["detail"]
    assert not (run / "gate.json").exists()


def test_gate_cli_bad_bars_file_is_a_failed_status(data, tmp_path, capsys):
    _run(data, "slice-bars", _ok("a"))
    bad = tmp_path / "bars.yaml"
    bad.write_text("quality: 0.9\nnot_a_bar: 1\n")
    assert cli.main(["run", "gate", "--run-id", "slice-bars", "--bars", str(bad)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "failed" and "gate error" in out["detail"]


def test_gate_cli_scorer_failure_is_a_failed_status(data, monkeypatch, capsys):
    _run(data, "slice-score", _ok("a"))
    def boom(row, pred):
        raise RuntimeError("scorer exploded")
    monkeypatch.setattr(gate, "_score", boom)
    assert cli.main(["run", "gate", "--run-id", "slice-score"]) == 1
    assert "scorer exploded" in json.loads(capsys.readouterr().out)["detail"]


def test_gate_md_has_a_per_document_table(data):
    """Every document gets a row: outcome, score, cause and its links (review I7)."""
    run = _run(data, "slice-docs", _ok("a") + [{"id": "w", "score": 0.5}, {"id": "r", "stage": "review"}])
    cli.main(["run", "gate", "--run-id", "slice-docs"])
    md = (run / "gate.md").read_text()
    assert "## Documents" in md
    section = md.split("## Documents", 1)[1]
    for doc_id in ("a", "w", "r"):
        assert f"| {doc_id} |" in section
    assert "correct_archive" in section and "wrong_archive" in section and "review" in section
    assert "`s-w`" in section and "data/archive/SANDBOX-sandbox_pipeline_slice-docs-a" in section
