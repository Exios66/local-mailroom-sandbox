"""A decision model is swappable: each request reads at most the chosen model's own context.

Luna Decisions (1.05M tokens) is the frontrunner and keeps every question set's cap. Jev 1.14,
Gemini Decision and the other OpenRouter Decisions models in ``SUPPORTED_DECISION_MODELS`` can
replace it on the same lane; a smaller window cuts the document to what the model accepts
(reported as ``truncated``) instead of an oversize request the provider refuses.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from mailroom_sandbox import decision_backends as db
from mailroom_sandbox.job import preflight

LUNA = "openai/gpt-6-luna-decisions"
JEV = "typesafe/jev-1.14"
SMALL = "liquid/d1.2"  # 65,536-token context


def _window(context: int) -> int:
    return int((context - db.DECISIONS_QUESTION_TOKENS) / db.DECISIONS_TOKENS_PER_CHAR)


def test_every_supported_decisions_model_has_a_catalog_window_and_price():
    for model in db.SUPPORTED_DECISION_MODELS["decisions"]:
        row = db.decision_model(model)
        assert row and row["context_length"] > 0 and row.get("prompt") is not None, model
        assert db.decision_window_chars(model) == _window(row["context_length"])


def test_luna_keeps_the_question_set_cap_and_jev_gets_its_own_window():
    assert db.decision_input_cap(LUNA, 1_000_000) == 1_000_000
    assert db.decision_input_cap(LUNA, None) == db.DECISIONS_MAX_INPUT_CHARS  # 4.18M-char window
    jev = _window(262_144)
    assert db.decision_input_cap(JEV, None) == jev < db.DECISIONS_MAX_INPUT_CHARS
    assert db.decision_input_cap(JEV, 1_000_000) == 1_000_000 < jev  # the whole-document sets still fit
    assert db.decision_input_cap(f"{JEV}:nitro", None) == jev  # a variant has its base's window
    assert db.decision_input_cap(SMALL, 1_000_000) == _window(65_536)


def test_a_large_question_payload_takes_room_from_the_document():
    big = 40_000  # characters of questions and handoff, ~10k tokens: more than the default reserve
    expected = int((262_144 - (int(big * db.DECISIONS_TOKENS_PER_CHAR) + 1000)) / db.DECISIONS_TOKENS_PER_CHAR)
    assert db.decision_input_cap(JEV, None, question_chars=big) == expected < _window(262_144)


def test_a_model_without_a_catalog_window_keeps_the_set_cap(monkeypatch):
    monkeypatch.setattr(db, "decision_model", lambda model: {"prompt": 0.1} if model else None)
    assert db.decision_window_chars(JEV) is None
    assert db.decision_input_cap(JEV, 123) == 123


@pytest.mark.parametrize("model", ["~typesafe/jev-latest", "typesafe/jev-router", "openai/gpt-6-luna"])
def test_an_alias_or_chat_model_is_refused_before_any_request(monkeypatch, model):
    monkeypatch.setattr(db, "_post_decision", lambda *a, **k: pytest.fail("no request may be sent"))
    with pytest.raises(ValueError, match="not a Decisions-API model"):
        db.decide("doc", model=model, questions={"doc_type": {"type": "choice", "criteria": {"a": "", "b": ""}}})


def _capture(monkeypatch):
    seen: dict = {}

    def fake_post(body, *, timeout, attempts):
        seen.update(body)
        return {"model": body["model"], "usage": {},
                "answers": {"doc_type": {"type": "choice", "choice": "contract", "probabilities": {"contract": 0.9}},
                            "verdict": {"choice": "accept", "probabilities": {"accept": 0.9}}}}

    monkeypatch.setattr(db, "_post_decision", fake_post)
    monkeypatch.setattr(db, "_record_usage", lambda *a, **k: None)
    monkeypatch.setattr(db, "_record_served", lambda *a, **k: None, raising=False)
    return seen


def _document(state):
    return state["document"] if isinstance(state, dict) else state


def test_decide_sends_jev_no_more_than_its_window(monkeypatch):
    seen = _capture(monkeypatch)
    questions = {"doc_type": {"type": "choice", "criteria": {"contract": "", "other": ""}}}
    doc = "x" * 1_500_000
    db.decide(doc, model=JEV, questions=questions)
    assert len(_document(seen["state"])) == db.decision_input_cap(JEV, None, question_chars=len(
        __import__("json").dumps(questions))) < len(doc)
    db.decide(doc, model=LUNA, questions=questions)
    assert len(_document(seen["state"])) == len(doc)  # Luna's window holds the whole document


def test_the_extraction_gate_cuts_a_small_window_model(monkeypatch):
    seen = _capture(monkeypatch)
    qset = db.load_question_set("extraction_gate_v1.3.0")
    handoff = {"doc_type": "contract", "fields": {"parties": []}}
    out = db.decide_extraction("x" * 600_000, handoff, model=SMALL, qset=qset)
    assert out["truncated"] and out["input_chars"] <= _window(65_536)
    assert len(seen["state"]["document"]) == out["input_chars"]
    full = db.decide_extraction("x" * 600_000, handoff, model=LUNA, qset=qset)
    assert not full["truncated"] and full["input_chars"] == 600_000


def _spec(model, stem="reviewer_decisions_v4.0.0"):
    return SimpleNamespace(reviewer=SimpleNamespace(backend="decisions", model=model, questions=stem),
                           extraction_gate=None, decision_slots=None)


def test_preflight_records_each_decision_lane_window():
    report = {"checks": []}
    preflight._record_decision_windows(report, _spec(JEV))
    (row,) = report["decision_windows"]
    assert row["model"] == JEV and row["context_length"] == 262_144
    assert row["window_chars"] == row["max_input_chars"] == 1_000_000
    assert report["checks"][-1] == {"name": "decision_windows", "ok": True,
                                    "detail": f"reviewer={JEV} (1000000 chars)"}
    small = {"checks": []}
    preflight._record_decision_windows(small, _spec(SMALL))
    assert "cut to" in small["checks"][-1]["detail"] and small["checks"][-1]["ok"] is True
    none = {"checks": []}
    preflight._record_decision_windows(none, SimpleNamespace(reviewer=None, extraction_gate=None,
                                                             decision_slots=None))
    assert none == {"checks": []}


def test_the_autoresearch_context_check_sizes_requests_like_execution():
    from mailroom_sandbox.autoresearch import levers

    assert levers.TOKENS_PER_CHAR == db.DECISIONS_TOKENS_PER_CHAR
    assert levers.QUESTION_TOKENS == db.DECISIONS_QUESTION_TOKENS
