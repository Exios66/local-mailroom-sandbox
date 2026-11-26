"""The gate types a parked extraction by the lane that parked it, through the real graph (offline).

One document runs the compiled graph with the sandbox harness (``tests/_arbiter_harness.py``). The
run item is built by the sandbox's own runner (``_run_pipeline_doc_once``), so it carries what a real
run records: the review causes and the classification arbiter's decision. That item is fed to the gate's
``primary_cause``. The table of cause combinations lives in ``tests/test_gate_causes.py``.
"""
from __future__ import annotations

import pytest
from _arbiter_harness import Script, activate_profile, arbiter_harness_state, run  # noqa: F401 (fixture)

pytestmark = pytest.mark.usefixtures("arbiter_harness_state")

JUDGE_PARTIAL = [("partial", "accurate")]
#: the reviewer's doubt as each cause leaves it: (reviewer causes, reviewer doc type)
REVIEWER = {"low_confidence": (["reviewer_low_confidence"], "corporate_record"),
            "disagreement": (["reviewer_disagreement"], "contract"),
            "unavailable": (["reviewer_unavailable"], "corporate_record"),
            "unknown_type": ([], "unknown")}


def _cause_of(bg, monkeypatch, out: dict) -> tuple[str, dict]:
    """The gate's primary cause of ``out``'s document, from the item the sandbox runner builds for it."""
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.job import gate_causes

    monkeypatch.setattr(bg, "run_pipeline", lambda *a, **k: out["state"])
    item = runners._run_pipeline_doc_once({"id": "d0", "filename": "d0.txt", "doc_text": "x",
                                           "expected_doc_class": "corporate_record"}, mock=False)
    row = {"expected_doc_class": "corporate_record", "id": "d0"}
    cause = gate_causes.primary_cause({"row": row, "item": {"pred": item}},
                                      {"outcome": "review", "class": "corporate_record"})
    return cause, item


@pytest.mark.parametrize("reviewer", sorted(REVIEWER))
def test_a_parked_extraction_is_charged_to_the_extraction_arbiter_not_to_settled_reviewer_doubt(
        reviewer, monkeypatch, tmp_path):
    """Mid-band sorter, the reviewer doubts it (four ways), the classification arbiter accepts, the judge
    says partial and the extraction arbiter parks the document: the gate types that park as
    ``judge:arbiter_escalated`` whichever reviewer cause is left on the item, because every one of them
    routes to the classification arbiter and extraction ran only after it accepted."""
    causes, doc_type = REVIEWER[reviewer]
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    out = run(bg, monkeypatch, Script(sorter=None, judge=JUDGE_PARTIAL, arbiter=["human_review"],
                                      carb=("accept_sorter", 0.99), confs=[0.88] * 6,
                                      reviewer_causes=causes, reviewer_doc_type=doc_type))
    assert out["stage"] == "review", out["path"]
    path = out["path"]
    assert path.index("classification_arbiter") < path.index("extract") < path.index("arbiter"), path
    cause, item = _cause_of(bg, monkeypatch, out)
    assert "arbiter_escalated" in item["review_causes"], item["review_causes"]
    assert "classification_arbiter_escalated" not in item["review_causes"], item["review_causes"]
    assert item["classification_arbiter_decision"] == "accept_sorter"
    assert cause == "judge:arbiter_escalated"


@pytest.mark.parametrize("reviewer", sorted(REVIEWER))
@pytest.mark.parametrize("verdict", ["incomplete", "partial"])
def test_a_judge_park_without_an_arbiter_call_is_charged_to_the_judge_not_to_settled_reviewer_doubt(
        reviewer, verdict, monkeypatch, tmp_path):
    """The classification arbiter accepted, the judge never reached ``complete`` and no extraction arbiter
    ruled (an incomplete verdict on the last pass, or a partial one the arbiter's retry could not fix):
    the park is a judge-lane outcome, not the reviewer's doubt."""
    causes, doc_type = REVIEWER[reviewer]
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    judge = [(verdict, "accurate")]
    out = run(bg, monkeypatch, Script(sorter=None, judge=judge, arbiter=["retry_extraction"],
                                      carb=("accept_sorter", 0.99), confs=[0.88] * 6,
                                      reviewer_causes=causes, reviewer_doc_type=doc_type))
    assert out["stage"] == "review", out["path"]
    cause, item = _cause_of(bg, monkeypatch, out)
    assert item["classification_arbiter_decision"] == "accept_sorter"
    assert cause.startswith("judge:"), (cause, item["review_causes"])


def test_the_decision_is_none_when_the_classification_arbiter_did_not_run(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    out = run(bg, monkeypatch, Script(judge=JUDGE_PARTIAL, arbiter=["human_review"], confs=[0.88] * 6))
    assert out["carb"] == 0 and "classification_arbiter" not in out["path"]
    _, item = _cause_of(bg, monkeypatch, out)
    assert item["classification_arbiter_decision"] is None
