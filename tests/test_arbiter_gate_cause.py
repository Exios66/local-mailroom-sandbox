"""The gate types a parked extraction by the extraction arbiter, through the real graph (offline).

One document runs the compiled graph with the sandbox harness (``tests/_arbiter_harness.py``); the
review causes the vendored pipeline derives from its final state are fed to the gate's
``primary_cause``. The table of cause combinations lives in ``tests/test_gate_causes.py``.
"""
from __future__ import annotations

import pytest
from _arbiter_harness import Script, activate_profile, run, arbiter_harness_state  # noqa: F401 (fixture)

from mailroom_sandbox import source_windows

pytestmark = pytest.mark.usefixtures("arbiter_harness_state")

JUDGE_PARTIAL = [("partial", "accurate")]


def test_a_parked_extraction_is_charged_to_the_extraction_arbiter_not_to_settled_reviewer_doubt(
        monkeypatch, tmp_path):
    """Mid-band sorter, reviewer doubts it, the classification arbiter accepts, the judge says partial
    and the extraction arbiter parks the document: the gate types that park as ``judge:arbiter_escalated``.
    The reviewer's doubt is still on the review causes but was settled by the classification arbiter."""
    from mailroom_sandbox.job import gate_causes
    from pipeline.reconsideration import collect_review_causes

    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    try:
        out = run(bg, monkeypatch, Script(sorter=None, judge=JUDGE_PARTIAL, arbiter=["human_review"],
                                          carb=("accept_sorter", 0.99), confs=[0.88] * 6))
    finally:
        source_windows.apply_source_windows({})
    assert out["stage"] == "review", out["path"]
    path = out["path"]
    assert path.index("classification_arbiter") < path.index("extract") < path.index("arbiter"), path
    causes = collect_review_causes(out["state"])
    assert {"arbiter_escalated", "reviewer_low_confidence"} <= set(causes), causes
    assert "classification_arbiter_escalated" not in causes, causes
    row = {"expected_doc_class": "corporate_record", "id": "x"}
    pred = {"doc_type": "corporate_record", "stage": "review", "review_causes": causes}
    cause = gate_causes.primary_cause({"row": row, "item": {"pred": pred}},
                                      {"outcome": "review", "class": "corporate_record"})
    assert cause == "judge:arbiter_escalated"
