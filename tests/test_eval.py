"""Activation, mock LLM, eval runners, experiment log (network-free)."""

from __future__ import annotations

import json
import os

import pytest

from mailroom_sandbox.cli import main
from mailroom_sandbox.datasets import dataset_fingerprint, load_hf_fixtures, load_legalbench_fixtures, load_manifest
from mailroom_sandbox.eval import experiment_log, matrix, runners, scoring
from mailroom_sandbox.mock_llm import fake_client, fake_structured_payload
from mailroom_sandbox.runtime import activate


def test_activate_writes_taxonomy(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    act = activate("ollama", load_env_file=False)
    assert act.profile_name == "ollama"
    assert act.taxonomy_path.is_file()
    text = act.taxonomy_path.read_text(encoding="utf-8")
    assert "qwen3:8b" in text
    assert "provider: ollama" in text


def test_fake_client_classify():
    expect = {"doc_type": "contract", "conf": 0.97}
    client = fake_client(expect)
    resp = client.chat.completions.create(
        messages=[{"role": "user", "content": "Classify this legal document.\njson"}]
    )
    payload = json.loads(resp.choices[0].message.content)
    assert payload["doc_type"] == "contract"
    assert payload["confidence"] == 0.97


def test_fake_payload_ambiguous():
    payload = fake_structured_payload(
        "Classify this legal document",
        {"id": "ambiguous_01", "doc_type": "correspondence"},
    )
    assert payload["confidence"] == 0.40
    assert payload["doc_type"] == "correspondence"


def test_manifest_and_hf_fixtures():
    rows = load_manifest()
    assert len(rows) >= 8
    classes = {r["expected_doc_class"] for r in rows}
    assert "contract" in classes
    assert "correspondence" in classes
    assert dataset_fingerprint(rows)
    hf = load_hf_fixtures()
    assert {r["doc_type"] for r in hf} >= {"contract", "correspondence", "insurance_claim"}
    lb = load_legalbench_fixtures()
    assert all(r["answer"] in {"Yes", "No"} for r in lb)


def test_sorter_eval_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    # experiment log writes under repo reports/; isolate via env used by dojo
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setenv("EXPERIMENT_LOG_PATH", str(log))
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    result = runners.run_sorter_eval(mock=True, dry_run=True)
    assert result["n"] >= 1
    result = runners.run_sorter_eval(mock=True, sample=3, experiment_name="test_sorter")
    assert result["scores"]["exact_match"] == 1.0
    assert log.is_file()


def test_extract_eval_mock(tmp_path, monkeypatch):
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setenv("EXPERIMENT_LOG_PATH", str(log))
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    result = runners.run_extract_eval(mock=True, sample=2)
    assert result["scores"]["n"] >= 1
    assert result["scores"]["overall_extraction_score"] >= 0.0


def test_legalbench_eval_mock(tmp_path, monkeypatch):
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setenv("EXPERIMENT_LOG_PATH", str(log))
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    result = runners.run_legalbench_eval(mock=True)
    assert result["scores"]["exact_match"] == 1.0


def test_matrix_dry_run():
    plan = matrix.run_matrix(
        task="sorter",
        providers=["ollama"],
        models=["qwen3:8b", "llama3.1:8b"],
        prompts=["mailroom-default", "sorter_local_v0"],
        dry_run=True,
    )
    assert plan["n"] == 4
    names = {c["experiment_name"] for c in plan["cells"]}
    assert any("sorter_local_v0" in n for n in names)


def test_cli_help():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_profiles():
    rc = main(["profiles"])
    assert rc == 0


def test_cli_eval_dry_run(capsys):
    rc = main(["eval", "sorter", "--mock", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["task"] == "sorter"


def test_cli_matrix_dry_run(capsys):
    rc = main(
        [
            "matrix",
            "--task",
            "sorter",
            "--providers",
            "ollama",
            "--models",
            "qwen3:8b",
            "--prompts",
            "sorter_local_v0",
            "--dry-run",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n"] == 1


def test_classification_scoring_smoke():
    scores = scoring.score_classification(
        ["contract", "correspondence"],
        ["contract", "correspondence"],
    )
    assert scores["exact_match"] == 1.0


@pytest.mark.local_llm
def test_live_ollama_health():
    if os.environ.get("SANDBOX_LOCAL_LLM", "").strip() not in {"1", "true", "yes"}:
        pytest.skip("SANDBOX_LOCAL_LLM not set")
    from mailroom_sandbox.health import health_check

    result = health_check("ollama")
    assert result["ok"] is True
