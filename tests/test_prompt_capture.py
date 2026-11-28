"""job.prompt_capture: every prompt a run sends lands in prompts.jsonl and in the floor digest."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox.job import prompt_capture, read_ranges
from mailroom_sandbox.job.checkpoint import RunStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rows():
    out: list[dict] = []
    prompt_capture.activate(out.append)
    yield out
    prompt_capture.deactivate()


def _digest_module():
    spec = importlib.util.spec_from_file_location("build_floor_digest", ROOT / "reports/dashboard/build_floor_digest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inactive_capture_records_nothing():
    prompt_capture.deactivate()
    prompt_capture.observe_chat({"messages": [{"role": "system", "content": "x"}]}, call_path="langchain")
    assert not prompt_capture.active()


def test_chat_request_records_texts_once_and_one_call_row_each(rows):
    payload = {"model": "qwen/qwen3.7-flash",
               "messages": [{"role": "system", "content": "You are the judge."},
                            {"role": "user", "content": [{"type": "text", "text": "Doc: hello"}]},
                            {"role": "assistant", "content": "ignored"}],
               "response_format": {"type": "json_schema", "json_schema": {"name": "x"}}}
    with read_ranges.document("DOC-1", "hello", sink=lambda rec: None):
        prompt_capture.observe_chat(payload, call_path="langchain")
        prompt_capture.observe_chat(payload, call_path="langchain")
    texts = [r for r in rows if r["kind"] == "text"]
    calls = [r for r in rows if r["kind"] == "call"]
    assert sorted(r["role"] for r in texts) == ["schema", "system", "user"]  # each text once
    assert len(calls) == 2 and calls[0]["doc"] == "DOC-1" and calls[0]["model"] == "qwen/qwen3.7-flash"
    assert [p["role"] for p in calls[0]["parts"]] == ["system", "user", "schema"]
    assert next(r for r in texts if r["role"] == "system")["text"] == "You are the judge."


def test_user_message_keeps_only_its_edges(rows):
    body = "H" * 10 + "D" * 20_000 + "T" * 10
    prompt_capture.observe_chat({"messages": [{"role": "user", "content": body}]}, call_path="langchain")
    user = next(r for r in rows if r["kind"] == "text")
    assert user["chars"] == len(body)
    assert user["text"].startswith("H" * 10) and user["text"].endswith("T" * 10)
    assert "characters omitted (document body)" in user["text"]
    assert len(user["text"]) < 2 * prompt_capture.USER_EDGE_CHARS + 100


def test_decision_request_never_records_the_document(rows):
    body = {"model": "openai/gpt-6-luna-decisions", "questions": {"q1": "Which class?"},
            "state": {"document": "SECRET BODY", "closed_field_handoff": {"class": "contract"}}}
    prompt_capture.observe_decision(body, agent="decisions:classification")
    assert "SECRET BODY" not in json.dumps(rows)
    call = next(r for r in rows if r["kind"] == "call")
    assert call["agent"] == "decisions:classification" and call["call_path"] == "decisions"
    assert [p["role"] for p in call["parts"]] == ["questions", "handoff"]


def test_store_appends_and_a_resume_does_not_rewrite_texts(tmp_path):
    store = RunStore(tmp_path / "run")
    prompt_capture.activate(store.append_prompt)
    try:
        prompt_capture.observe_chat({"messages": [{"role": "system", "content": "S"}]}, call_path="langchain")
        seen = store.prompt_text_hashes()
        prompt_capture.activate(store.append_prompt, seen=seen)  # a resumed run
        prompt_capture.observe_chat({"messages": [{"role": "system", "content": "S"}]}, call_path="langchain")
    finally:
        prompt_capture.deactivate()
    lines = [json.loads(x) for x in store.prompts_path.read_text(encoding="utf-8").splitlines()]
    assert [r["kind"] for r in lines] == ["text", "call", "call"]


def test_floor_digest_groups_prompts_by_node(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"kind": "text", "sha256": "a" * 64, "role": "system", "chars": 4, "text": "SYS1"},
        {"kind": "text", "sha256": "b" * 64, "role": "user", "chars": 9, "text": "U1"},
        {"kind": "text", "sha256": "c" * 64, "role": "user", "chars": 9, "text": "U2"},
        {"kind": "call", "doc": "D1", "node": "judge_verify", "agent": "completeness_judge",
         "parts": [{"role": "system", "sha256": "a" * 64, "chars": 4}, {"role": "user", "sha256": "b" * 64, "chars": 9}]},
        {"kind": "call", "doc": "D2", "node": "judge_verify", "agent": "completeness_judge",
         "parts": [{"role": "system", "sha256": "a" * 64, "chars": 4}, {"role": "user", "sha256": "c" * 64, "chars": 9}]},
    ]
    (run / "prompts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    record = _digest_module().prompt_record(run)
    node = record["node_prompts"]["judge_verify"]
    assert [(p["role"], p["calls"]) for p in node] == [("system", 2), ("user", 1)]  # one user sample per agent
    # a user message carries the document: listed by hash and length, its text left in the run store
    assert set(record["prompt_texts"]) == {"a" * 64}
    assert node[1]["in_run_store"] is True and "in_run_store" not in node[0]
    assert "U1" not in json.dumps(record) and "U2" not in json.dumps(record)
    assert _digest_module().prompt_record(tmp_path / "missing") == {"node_prompts": {}, "prompt_texts": {}}
