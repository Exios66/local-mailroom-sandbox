"""The fake LLM answers each pipeline prompt in that agent's own schema (network-free).

A mock answer outside an agent's schema is not a mock of that agent: the vendored guardrail
turns it into an escalation, so every mock run parks documents a real model would route.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.mock_llm import fake_structured_payload
from mailroom_sandbox.runtime import activate

SORTER = {"doc_type": "corporate_record", "doc_subclass": "bylaws", "confidence": 0.99}


def _prompts(monkeypatch, tmp_path):
    """The classification-arbiter and accuracy-judge user prompts, built by the vendored agents."""
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    activate("ollama", load_env_file=False)
    from agents.arbiter import ClassificationArbiterAgent
    from agents.judge import CompletenessJudge

    seen: list[str] = []

    def capture(self, user_message, *args, **kwargs):
        seen.append(user_message)
        return {}

    monkeypatch.setattr(ClassificationArbiterAgent, "_call_structured", capture)
    monkeypatch.setattr(CompletenessJudge, "_call_structured", capture)
    return seen, ClassificationArbiterAgent, CompletenessJudge


def _carb_prompt(monkeypatch, tmp_path, *, sorter, reviewer):
    seen, carb, _ = _prompts(monkeypatch, tmp_path)
    carb.__new__(carb).arbitrate_classification(
        sorter=sorter, reviewer=reviewer, causes=["reviewer_unavailable"],
        labels=["contract", "corporate_record", "correspondence"], doc_text="Bylaws of Cedar Sample Ltd.")
    return seen[-1]


@pytest.mark.parametrize(("reviewer", "expected"), [
    ({"doc_type": "unknown", "doc_subclass": None, "confidence": 0.0}, "accept_sorter"),
    ({"doc_type": "corporate_record", "doc_subclass": "bylaws", "confidence": 0.4}, "accept_sorter"),
])
def test_classification_arbiter_accepts_the_sorter_when_it_names_the_expected_class(
        monkeypatch, tmp_path, reviewer, expected):
    from agents.arbiter import CLASSIFICATION_DECISIONS

    prompt = _carb_prompt(monkeypatch, tmp_path, sorter=SORTER, reviewer=reviewer)
    payload = fake_structured_payload(prompt, {"doc_type": "corporate_record"})
    assert payload["decision"] == expected and payload["decision"] in CLASSIFICATION_DECISIONS
    assert set(payload) >= {"decision", "confidence", "reasoning"}
    assert payload["confidence"] == 0.99


def test_classification_arbiter_accepts_the_reviewer_when_only_it_is_right(monkeypatch, tmp_path):
    wrong = {"doc_type": "contract", "doc_subclass": "service", "confidence": 0.99}
    right = {"doc_type": "corporate_record", "doc_subclass": "bylaws", "confidence": 0.9}
    prompt = _carb_prompt(monkeypatch, tmp_path, sorter=wrong, reviewer=right)
    assert fake_structured_payload(prompt, {"doc_type": "corporate_record"})["decision"] == "accept_reviewer"


def test_classification_arbiter_parks_when_neither_answer_is_right(monkeypatch, tmp_path):
    wrong = {"doc_type": "contract", "doc_subclass": "service", "confidence": 0.99}
    unknown = {"doc_type": "unknown", "doc_subclass": None, "confidence": 0.0}
    prompt = _carb_prompt(monkeypatch, tmp_path, sorter=wrong, reviewer=unknown)
    assert fake_structured_payload(prompt, {"doc_type": "corporate_record"})["decision"] == "human_review"


def test_a_fixture_can_force_the_classification_arbiters_decision(monkeypatch, tmp_path):
    prompt = _carb_prompt(monkeypatch, tmp_path, sorter=SORTER, reviewer={"doc_type": "unknown"})
    forced = {"doc_type": "corporate_record", "classification_arbiter_decision": "human_review"}
    assert fake_structured_payload(prompt, forced)["decision"] == "human_review"


def test_the_extraction_arbiter_keeps_its_own_vocabulary():
    payload = fake_structured_payload("DOCUMENT TYPE: contract\n\nJUDGE VERDICT: partial\n", {"doc_type": "contract"})
    assert payload["decision"] == "accept_with_caveats" and "fields_to_fix" in payload


def _correctness_prompt(monkeypatch, tmp_path):
    seen, _, judge = _prompts(monkeypatch, tmp_path)
    judge.__new__(judge).judge_extraction_correctness(
        doc_type="contract", extracted={"parties": ["Cedar Sample Ltd"]}, doc_text="Cedar Sample Ltd agreement.")
    return seen[-1]


def test_accuracy_judge_answers_in_its_own_schema(monkeypatch, tmp_path):
    from agents.judge import CORRECTNESS_LABELS

    payload = fake_structured_payload(_correctness_prompt(monkeypatch, tmp_path), {"doc_type": "contract"})
    assert payload["extraction_correctness_label"] == "accurate" and "accurate" in CORRECTNESS_LABELS
    assert 0.95 <= payload["extraction_correctness"] <= 1.0
    assert payload["reasoning"] and "mock_extraction" not in payload


def test_a_fixture_can_set_the_accuracy_verdict(monkeypatch, tmp_path):
    prompt = _correctness_prompt(monkeypatch, tmp_path)
    payload = fake_structured_payload(prompt, {"doc_type": "contract", "correctness_label": "partial",
                                               "correctness_score": 0.6})
    assert payload["extraction_correctness_label"] == "partial" and payload["extraction_correctness"] == 0.6


def _mock_pilot(tmp_path, monkeypatch, rows=None):
    """``(stage by id, expected stage by id, final state by id)`` of a mock pilot (mock routing only)."""
    from mailroom_sandbox.datasets import load_manifest
    from mailroom_sandbox.eval import experiment_log, runners

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setenv("EXPERIMENT_LOG_PATH", str(log))
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    activate(load_env_file=False)
    import graph.build_graph as bg  # vendored; on sys.path once a runtime is active

    states: dict[str, dict] = {}
    original_run, original_once = bg.run_pipeline, runners._run_pipeline_doc_once
    current: dict[str, str] = {}

    def once(row, *args, **kwargs):
        current["id"] = row["id"]
        return original_once(row, *args, **kwargs)

    def run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        states[current["id"]] = dict(result)
        return result

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", once)
    monkeypatch.setattr(bg, "run_pipeline", run)
    rows = load_manifest() if rows is None else rows
    result = runners.run_pipeline_eval(mock=True, rows=rows, experiment_name="test_mock_pilot_routing")
    expected = {row["id"]: row["expected_stage"] for row in rows}
    return {doc["id"]: doc["stage"] for doc in result["docs"]}, expected, states


def _assert_clean_archives(got, states):
    for doc_id, stage in got.items():
        if stage == "archived":
            state = states[doc_id]
            assert state.get("judge_verdict") == "complete", (doc_id, state.get("judge_verdict"))
            assert not state.get("arbiter_decision"), (doc_id, state.get("arbiter_decision"))


def test_mock_contracts_archive_on_a_complete_verdict_without_the_arbiter(tmp_path, monkeypatch):
    """The accuracy judge's mock answer used to read as ``partial``, so every clean contract met the arbiter."""
    from mailroom_sandbox.datasets import load_manifest

    rows = [row for row in load_manifest() if row["expected_doc_class"] == "contract"]
    got, expected, states = _mock_pilot(tmp_path, monkeypatch, rows)
    assert got == expected == {"contract_msa": "archived", "contract_nda": "archived"}
    _assert_clean_archives(got, states)
