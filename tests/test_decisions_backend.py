"""Decisions-API reviewer backend and the guard that keeps a chat model out of the decision role."""

from __future__ import annotations

import pytest

from mailroom_sandbox import decision_backends as db
from mailroom_sandbox.job.spec import ReviewerSpec

DECISIONS = "openai/gpt-6-luna-decisions"


def test_decisions_model_detection():
    assert db.is_decisions_model(DECISIONS)
    assert not db.is_decisions_model("openai/gpt-6-luna")
    assert not db.is_decisions_model(None)


def test_chat_model_cannot_be_the_decision_reviewer_by_default():
    with pytest.raises(ValueError, match="allow_chat_model"):
        ReviewerSpec(backend="api", model="openai/gpt-6-luna", classes={"contract": 0.9})
    ReviewerSpec(backend="api", model="openai/gpt-6-luna", classes={"contract": 0.9}, allow_chat_model=True)


def test_decisions_model_needs_decisions_backend_and_questions():
    with pytest.raises(ValueError, match="backend decisions"):
        ReviewerSpec(backend="api", model=DECISIONS, classes={}, allow_chat_model=True)
    with pytest.raises(ValueError, match="Decisions-API model"):
        ReviewerSpec(backend="decisions", model="openai/gpt-6-luna", questions="reviewer_decisions_v1")
    with pytest.raises(ValueError, match="questions"):
        ReviewerSpec(backend="decisions", model=DECISIONS)
    spec = ReviewerSpec(backend="decisions", model=DECISIONS, questions="reviewer_decisions_v1")
    assert spec.classes == {}
    # Old reviewer blocks dump (and hash) exactly as before.
    assert ReviewerSpec(backend="jev", model="jev-1.13.0", classes={"contract": 0.9}).model_dump() == {
        "backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.9}}


def test_empty_classes_only_on_a_calibration_run():
    from mailroom_sandbox.job.spec import RunSpec

    reviewer = {"backend": "decisions", "model": DECISIONS, "questions": "reviewer_decisions_v1"}
    RunSpec(task="sorter_reviewer", reviewer=reviewer)
    with pytest.raises(ValueError, match="at least one class"):
        RunSpec(task="pipeline", reviewer=reviewer)


def test_question_set_builds_doc_type_and_subclass_questions():
    qset = db.load_question_set("reviewer_decisions_v1")
    questions = db.decision_questions(qset)
    assert set(questions["doc_type"]["criteria"]) == {
        "contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim", "unknown"}
    assert {q for q in questions if q.startswith("subclass__")} == {
        "subclass__contract", "subclass__merger_agreement", "subclass__corporate_record",
        "subclass__correspondence", "subclass__insurance_claim"}
    assert all(q["type"] == "choice" for q in questions.values())


def test_decide_reads_probabilities_and_records_usage(monkeypatch):
    calls = {}

    class Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"model": DECISIONS + "-20261006",
                    "answers": {"doc_type": {"type": "choice", "choice": "merger_agreement",
                                             "probabilities": {"merger_agreement": 0.97, "contract": 0.03}},
                                "subclass__merger_agreement": {"type": "choice", "choice": "all_cash",
                                                               "probabilities": {"all_cash": 0.8, "other": 0.2}},
                                "subclass__contract": {"type": "choice", "choice": "supply"}},
                    "usage": {"input_tokens": 1000, "output_tokens": 0, "cost": 0.0001}}

    def post(url, json, timeout, headers):
        calls.update(url=url, body=json)
        return Resp()

    recorded = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr("httpx.post", post)
    monkeypatch.setattr(db, "_record_usage", lambda model, usage: recorded.append(usage))
    out = db.decide("x" * 50, model=DECISIONS, questions={"doc_type": {}}, max_input_chars=10)
    assert calls["url"] == db.DECISIONS_URL and calls["body"]["state"] == "x" * 10
    assert out["doc_type"] == "merger_agreement" and out["confidence"] == 0.97
    assert out["doc_subclass"] == "all_cash" and out["contract_subtype"] is None
    assert out["subclass_confidence"] == 0.8
    assert recorded and recorded[0]["input_tokens"] == 1000


def test_decide_refuses_a_chat_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    with pytest.raises(ValueError):
        db.decide("x", model="openai/gpt-6-luna", questions={})


def test_live_reviewer_uses_the_activated_decisions_reviewer_from_a_worker_thread(monkeypatch):
    """Agent-task workers do not inherit the run lock's ContextVar; the reviewer must still be found."""
    import threading

    from mailroom_sandbox import runtime
    from mailroom_sandbox.eval import agents

    qset = db.load_question_set("reviewer_decisions_v1")
    monkeypatch.setattr(runtime, "_ACTIVE_REVIEWER", {"backend": "decisions", "model": DECISIONS, "question_set": qset})
    seen = {}

    def fake_decide(text, *, model, questions, max_input_chars, qset=None):
        seen.update(model=model, n=len(questions), cap=max_input_chars)
        return {"doc_type": "contract", "confidence": 0.9}

    monkeypatch.setattr(db, "decide", fake_decide)
    out = {}
    worker = threading.Thread(target=lambda: out.update(agents._live_reviewer({"doc_text": "AGREEMENT"})))
    worker.start()
    worker.join()
    assert out["doc_type"] == "contract"
    assert seen == {"model": DECISIONS, "n": 6, "cap": 120000}


def test_zero_output_tokens_are_still_recorded():
    """A Decisions call has no output tokens; the run's usage must still count its input."""
    from mailroom_sandbox import runtime

    runtime.activate("openrouter")
    from pipeline.limits import reset_run_usage, usage_summary

    reset_run_usage()
    db._record_usage(DECISIONS, {"input_tokens": 1234, "output_tokens": 0})
    summary = usage_summary()
    assert summary["prompt_tokens"] == 1234 and summary["calls"] == 1


def test_marker_subclass_takes_the_first_marker_in_order():
    block = db.load_question_set("reviewer_decisions_v2")["subclass"]["correspondence"]
    answers = {"marker__correspondence__notice": {"noul": 0.9}, "marker__correspondence__demand": {"noul": 0.7},
               "marker__correspondence__letter": {"noul": 0.2}}
    key, conf, _ = db.marker_subclass(block, answers, "correspondence")
    assert (key, conf) == ("demand", 0.7)   # demand precedes notice in the corpus order
    key, conf, _ = db.marker_subclass(block, {"marker__correspondence__letter": {"noul": 0.1}}, "correspondence")
    assert key == "email" and abs(conf - 0.9) < 1e-9


def test_v2_asks_marker_questions_for_correspondence():
    questions = db.decision_questions(db.load_question_set("reviewer_decisions_v2"))
    assert "subclass__correspondence" not in questions
    assert questions["marker__correspondence__memo"]["type"] == "noul"
    assert "subclass__contract" in questions
