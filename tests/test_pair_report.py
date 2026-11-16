"""Paired ladder report: pairing, templated-field lane, CI and counts (offline, no LLM)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import pair_report


def _arm(root, name, docs):
    """docs: (id, class, expected_fields, extracted, stage, nodes)."""
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it, open(run / "nodes.jsonl", "w") as nd:
        for i, (doc, cls, exp, got, stage, nodes) in enumerate(docs):
            ds.write(json.dumps({"id": doc, "expected_doc_class": cls, "expected_fields": json.dumps(exp)}) + "\n")
            it.write(json.dumps({"item_id": doc, "prompt_tokens": 10, "completion_tokens": 5,
                                 "pred": {"stage": stage, "extracted_data": got}, "score": {}}) + "\n")
            for j, node in enumerate(nodes):
                decisions = [{"question": "extraction_verdict", "answer": "partial"}] if node == "judge_verify" else []
                nd.write(json.dumps({"doc": doc, "node": node, "status": "done", "ts": i * 10 + j,
                                     "decisions": decisions}) + "\n")
    return run


def test_without_fields_drops_only_the_named_labels():
    row = {"id": "a", "expected_fields": json.dumps({"keywords": ["EX-3.1"], "intent": "x"})}
    assert pair_report.without_fields(row, ["keywords"])["expected_fields"] == {"intent": "x"}
    assert json.loads(row["expected_fields"])["keywords"] == ["EX-3.1"]  # the original is untouched


def test_paired_report_scores_both_lanes_on_shared_documents(tmp_path, monkeypatch):
    # Score = share of expected fields the prediction matches exactly.
    def fake_score(row, pred):
        exp = pair_report._fields(row)
        got = pred.get("extracted_data") or {}
        return sum(got.get(k) == v for k, v in exp.items()) / len(exp) if exp else None

    monkeypatch.setattr(pair_report, "_score", fake_score)
    exp = {"keywords": "EX-3.1", "subject_matter": "bylaws of X", "intent": "governance_rules"}
    real = {"keywords": "Bylaws", "subject_matter": "Amended bylaws", "intent": "governance_rules"}
    wrong = {**real, "intent": "investor_rights"}
    control = _arm(tmp_path, "c", [("d1", "corporate_record", exp, wrong, "archived", ["extract"]),
                                   ("d2", "corporate_record", exp, wrong, "archived", ["extract"]),
                                   ("only-c", "corporate_record", exp, real, "archived", ["extract"])])
    treatment = _arm(tmp_path, "t", [("d1", "corporate_record", exp, real, "review", ["extract", "judge_verify"]),
                                     ("d2", "corporate_record", exp, wrong, "archived", ["extract", "judge_verify", "retry_extract"])])
    report = pair_report.paired_report(control, treatment)

    assert report["shared_docs"] == 2 and report["only_control"] == ["only-c"]
    corp = report["classes"]["corporate_record"]
    assert corp["dropped_fields"] == ["keywords", "subject_matter"]
    # All fields: the templated labels hold both arms near zero; without them the gain shows in full.
    assert corp["all_fields"]["control"] == pytest.approx(0.0)
    assert corp["all_fields"]["treatment"] == pytest.approx(1 / 6)
    assert corp["without_templated"]["control"] == pytest.approx(0.0)
    assert corp["without_templated"]["treatment"] == pytest.approx(0.5)
    assert corp["without_templated"]["diff"] == pytest.approx(0.5)
    assert corp["treatment_counts"]["review"] == 1 and corp["treatment_counts"]["judge_calls"] == 2
    assert corp["treatment_counts"]["retries"] == 1 and corp["treatment_verdicts"] == {"partial": 2}
    table = pair_report.render_markdown(report)
    assert "without templated" in table and "only-c" in table


def test_classes_without_templated_labels_get_one_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(pair_report, "_score", lambda row, pred: 1.0)
    exp = {"title": "x"}
    a = _arm(tmp_path, "c", [("d1", "contract", exp, exp, "archived", [])])
    b = _arm(tmp_path, "t", [("d1", "contract", exp, exp, "archived", [])])
    contract = pair_report.paired_report(a, b)["classes"]["contract"]
    assert "without_templated" not in contract and contract["all_fields"]["diff"] == 0.0
