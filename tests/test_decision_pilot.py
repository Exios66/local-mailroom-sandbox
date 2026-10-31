"""Offline Pilot 1: real graph, SQLite, catalog, files and review API; fake models."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import nullcontext
from dataclasses import replace
from functools import wraps
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from mailroom_sandbox.job.spec import ReviewerSpec
from mailroom_sandbox.runtime import activate

ROWS = [json.loads(line) for line in (
    Path(__file__).parents[1] / "data/fixtures/pilot/decision_review.jsonl"
).read_text().splitlines()]
SPEC = ReviewerSpec(backend="mock", model="mock", classes={
    "contract": 0.9, "corporate_record": 0.9, "insurance_claim": 0.9,
})


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    # Never load operator credentials or connect to the operator's catalog.
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    monkeypatch.setenv("MAILROOM_CHECKPOINTER", "sqlite")
    monkeypatch.setattr("httpx.HTTPTransport.handle_request", Mock(
        side_effect=AssertionError("offline pilot attempted an external HTTP request")))
    for flag in ("MAILROOM_RELATIONS", "MAILROOM_RELATIONS_EMBEDDINGS",
                 "MAILROOM_BERT_INTAKE", "MAILROOM_LLM_INTAKE", "MAILROOM_LLM_CACHE"):
        monkeypatch.setenv(flag, "0")
    activate("ollama", load_env_file=False, reviewer=SPEC)
    import graph.build_graph as bg
    from agents.decision_backend import register_decision_backend

    bg.reset_compiled_graph()
    yield tmp_path, monkeypatch
    bg.reset_compiled_graph()
    register_decision_backend(None)
    activate("ollama", load_env_file=False)  # rewrite the reviewer block back to all-llm


def run_pilot_row(row: dict, spec: ReviewerSpec, pilot) -> dict:
    from contextlib import ExitStack

    import graph.build_graph as bg
    from agents.decision_backend import register_decision_backend
    from mailroom_sandbox.decision_backends import mock_backend
    from mailroom_sandbox.mock_llm import fake_client
    from langchain_agents.mock import FakeLangChainLLM
    from pipeline.bins import inbox_dir

    _, monkeypatch = pilot
    activate("ollama", load_env_file=False, reviewer=spec)
    backend = mock_backend({row["doc_text"]: (row["reviewer_type"], row["reviewer_confidence"])})

    def answer(text, types, catalogs):
        picked = backend(text, types, catalogs)
        # The canned backend supplies class/confidence; include a registered
        # subclass just as the typed live adapter does.
        subclasses = catalogs.get(picked.doc_type) or []
        return replace(picked, doc_subclass=subclasses[0] if subclasses else None)

    backend_spy = Mock(side_effect=answer)
    register_decision_backend(None if row["id"] == "unavailable" else backend_spy)
    reviewer = Mock(side_effect=AssertionError("LLM reviewer must not run"))
    monkeypatch.setattr("agents.sorter_reviewer.SorterReviewerAgent", reviewer)
    visited = []
    extraction_inputs = []

    def observe(name, fn):
        @wraps(fn)
        def wrapped(state):
            visited.append(name)
            if name == "extract":
                extraction_inputs.append(dict(state))
            if row["id"] == "no_text" and name in {"classify", "retry_classify"}:
                # Inject a sorter answer to exercise Lane A's blank-text guard;
                # the real sorter otherwise parks blank input before Lane A.
                return {"doc_type": row["sorter_type"], "classification_confidence": 0.93,
                        "classification_attempts": state.get("classification_attempts", 0) + 1,
                        "stage": "classified"}
            return fn(state)
        return wrapped

    for name in ("intake", "classify", "retry_classify", "review_classify", "extract",
                 "retry_extract", "judge_verify", "arbiter", "human_review",
                 "boss_escalation", "compile_report", "catalog_write", "archive"):
        monkeypatch.setattr(bg, name + "_node", observe(name, getattr(bg, name + "_node")))

    # Same model seams as the sandbox mock runner; graph and routing stay real.
    expect = {"doc_type": row["sorter_type"], "conf": 0.93, "expected_fields": {
        "entity_name": "Cedar Sample Ltd", "record_type": "minutes",
        "claim_number": "C-17", "insured_party": "Cedar Sample Ltd",
    }}
    stack = ExitStack()
    for target in ("llm.client.get_llm", "agents.base.get_llm"):
        stack.enter_context(patch(
            target, return_value=(fake_client(expect), "mock-model")))
    fake = FakeLangChainLLM(classification={
        "doc_type": row["sorter_type"], "confidence": 0.93,
        "contract_subtype": "other" if row["sorter_type"] == "contract" else None,
        "doc_subclass": {"contract": "other", "corporate_record": "minutes",
                         "insurance_claim": "carrier"}[row["sorter_type"]],
        "reasoning": "curated reviewer-band sorter output",
    }, extraction={**expect["expected_fields"], "confidence": 0.99})
    stack.enter_context(patch("langchain_agents.base_agent.BaseAgent.llm", lambda self: fake))
    bg.reset_compiled_graph()
    inbox_dir().mkdir(parents=True, exist_ok=True)
    source = inbox_dir() / f"{row['id']}.txt"
    source.write_text(row["doc_text"])
    # Keep mocks through any subsequent CLI/API resume in the same test.
    try:
        result = bg.run_pipeline(source, "DECISION-PILOT")
    except BaseException:
        stack.close()
        raise
    return {**result, "visited": visited, "llm_reviewer": reviewer,
            "backend": backend_spy, "extract_inputs": extraction_inputs, "stack": stack}


@pytest.fixture
def run(pilot):
    results = []

    def run(row):
        result = run_pilot_row(row, SPEC, pilot)
        results.append(result)
        return result

    yield run
    for result in results:
        result["stack"].close()


def catalog(doc_id):
    from storage.catalog import get_document
    from storage.db import ensure_schema

    ensure_schema()
    return asyncio.run(get_document(doc_id))


def assert_archive(result):
    from pipeline.bins import archived_file_path, load_manifest

    manifest = load_manifest(result["doc_id"])
    assert manifest.stage.value == "archived"
    assert archived_file_path(manifest).is_file()
    stored = catalog(result["doc_id"])
    assert stored.stage == "archived"
    assert stored.extracted_data["_report"]
    assert not stored.extracted_data["_report"].get("error")
    assert {"extract", "compile_report", "catalog_write", "archive"} <= set(result["visited"])
    assert result["llm_reviewer"].call_count == 0


def test_clean_accept_reaches_archive_entry(run):
    result = run(ROWS[0])
    assert result["stage"] == "archived"
    assert_archive(result)
    assert result["review_verdict"] == "decision_accepts"
    assert result["backend"].call_count == 1
    assert result["extract_inputs"][0]["review_verdict"] == "decision_accepts"


@pytest.mark.parametrize("row", ROWS[1:], ids=lambda r: r["id"])
def test_each_cause_parks(row, run):
    from pipeline.bins import load_manifest, review_file_path

    result = run(row)
    manifest = load_manifest(result["doc_id"])
    assert result["stage"] == manifest.stage.value == "review"
    assert row["cause"] in manifest.review_causes
    assert manifest.doc_type == row["sorter_type"]
    assert manifest.review_verdict == "decision_escalates"
    assert review_file_path(manifest).is_file()
    assert row["cause"] in catalog(result["doc_id"]).extracted_data["_review"]["review_causes"]
    assert "review_classify" in result["visited"]
    assert not {"extract", "archive"} & set(result["visited"])
    assert result["llm_reviewer"].call_count == 0
    assert result["backend"].call_count == (0 if row["id"] in {"no_text", "unavailable"} else 1)


def connect_review_api(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    from mailroom_sandbox import review_cli

    monkeypatch.setenv("MAILROOM_API_URL", "http://testserver")
    monkeypatch.setenv("MAILROOM_API_TOKEN", "offline-pilot-token")
    # Exercise real endpoints without starting the embedded watcher lifespan.
    monkeypatch.setattr(review_cli, "_client", lambda base, token, timeout: nullcontext(TestClient(
        app, base_url=base, headers={"Authorization": f"Bearer {token}"})))


@pytest.mark.parametrize("restart", [False, True], ids=["same-process", "sqlite-restart"])
def test_approve_with_override_reaches_archive(run, pilot, restart, capsys):
    import graph.build_graph as bg
    from mailroom_sandbox import cli
    from pipeline.bins import load_manifest

    result = run(ROWS[1])
    if restart:
        bg.reset_compiled_graph()
    manifest = load_manifest(result["doc_id"])
    assert bg._thread_is_interrupted(bg.get_compiled_graph(), manifest.checkpoint_thread_id)
    connect_review_api(pilot[1])
    assert cli.main(["review", "list"]) == 0
    assert cli.main(["review", "show", result["doc_id"]]) == 0
    assert cli.main(["review", "resolve", result["doc_id"], "--decision", "approved",
                     "--doc-type", "corporate_record", "--notes", "curated offline override"]) == 0
    assert_archive(result)
    assert result["extract_inputs"][-1]["doc_type"] == "corporate_record"
    assert load_manifest(result["doc_id"]).reviewer_doc_type == "corporate_record"
    assert cli.main(["review", "resolve", result["doc_id"], "--decision", "rejected"]) == 1
    assert "not in review" in capsys.readouterr().err


def test_reject_ends_failed(run, pilot):
    from mailroom_sandbox import cli
    from pipeline.bins import archive_dir, failed_file_path, load_manifest

    result = run(ROWS[1])
    connect_review_api(pilot[1])
    assert cli.main(["review", "resolve", result["doc_id"], "--decision", "rejected"]) == 0
    manifest = load_manifest(result["doc_id"])
    assert manifest.stage.value == catalog(result["doc_id"]).stage == "failed"
    assert failed_file_path(manifest).is_file()
    assert not list(archive_dir().rglob("*.txt"))
    assert "extract" not in result["visited"]
    assert result["llm_reviewer"].call_count == 0


def test_activate_defaults_to_durable_review_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.delenv("MAILROOM_CHECKPOINTER", raising=False)
    activate("ollama", load_env_file=False)
    assert os.environ["MAILROOM_CHECKPOINTER"] == "sqlite"
    monkeypatch.setenv("MAILROOM_CHECKPOINTER", "memory")
    activate("ollama", load_env_file=False)
    assert os.environ["MAILROOM_CHECKPOINTER"] == "memory"
