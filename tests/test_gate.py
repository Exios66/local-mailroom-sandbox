"""Production slice gate: bars, per-document outcome, pooled Wilson rates and verdict (offline)."""
from __future__ import annotations

import json
import math

import pytest

from mailroom_sandbox.job import gate
from mailroom_sandbox.job.gate import Bars

TWO = {"document_name": "Master Agreement", "parties": ["A", "B"]}
LABELS = {  # two real labels per class, so a document is scorable
    "contract": TWO,
    "merger_agreement": TWO,
    "corporate_record": {"entity_name": "Acme Corp", "record_type": "bylaws"},
    "correspondence": {"sender": "A. Smith", "recipient": "B. Jones"},
    "insurance_claim": {"claim_number": "C-1", "policy_number": "P-9"},
}


def _run(root, docs, name="slice"):
    """docs: dicts with id, cls, and optional expected/stage/score/causes/error/item/repeat."""
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": d["cls"],
                                 "expected_fields": json.dumps(d.get("expected", LABELS[d["cls"]]))}) + "\n")
            if d.get("item", True) is False:
                continue
            for _ in range(d.get("repeat", 1)):
                pred = {"stage": d.get("stage", "archived"), "extracted_data": {},
                        "review_causes": d.get("causes") or [], "_score": d.get("score", 0.95)}
                it.write(json.dumps({"item_id": d["id"], "ok": d.get("error") is None, "error": d.get("error"),
                                     "prompt_tokens": 10, "completion_tokens": 5, "pred": pred}) + "\n")
    return run


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


def _docs(n, cls="contract", **kw):
    return [{"id": f"{cls}-{i}", "cls": cls, **kw} for i in range(n)]


def test_outcomes_follow_score_and_stage(tmp_path):
    one = {"document_name": "Only One"}
    run = _run(tmp_path, [
        {"id": "ok", "cls": "contract", "score": 0.95},
        {"id": "bad", "cls": "contract", "score": 0.6},
        {"id": "rev", "cls": "contract", "stage": "review"},
        {"id": "few", "cls": "contract", "expected": one},
    ])
    out = {d["id"]: d for d in gate.gate_report(run, Bars())["docs"]}
    assert out["ok"]["outcome"] == "correct_archive" and out["ok"]["score"] == 0.95 and out["ok"]["scorable"]
    assert out["bad"]["outcome"] == "wrong_archive"
    assert out["rev"]["outcome"] == "review" and out["rev"]["stage"] == "review"
    assert out["few"]["outcome"] == "unscorable_archive" and out["few"]["scorable"] is False
    assert out["ok"]["class"] == "contract" and out["ok"]["tokens"] == 15


def test_bar_edge_is_inclusive(tmp_path):
    run = _run(tmp_path, [{"id": "edge", "cls": "contract", "score": 0.90}])
    assert gate.gate_report(run, Bars())["docs"][0]["outcome"] == "correct_archive"


def test_pooled_rates_and_pass(tmp_path):
    docs = _docs(39) + [{"id": "r", "cls": "contract", "stage": "review"}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["n"] == 40 and report["run_id"] == "slice"
    assert report["pooled"]["review_rate"] == pytest.approx(0.025)
    assert report["pooled"]["wrong_archive_rate"] == 0
    assert report["verdict"] == {"pass": True, "reasons": []}
    assert report["bars"]["quality"] == 0.90 and report["bars"]["gated"][0] == "contract"
    cls = report["classes"]["contract"]
    assert cls["n"] == 40 and cls["gated"] is True and cls["tokens_per_doc"] == 15
    assert cls["correct_archive_rate"] == pytest.approx(39 / 40)


def test_wilson_upper_bounds(tmp_path):
    docs = _docs(39) + [{"id": "r", "cls": "contract", "stage": "review"}]
    pooled = gate.gate_report(_run(tmp_path, docs), Bars())["pooled"]
    z, k, n = 1.96, 1, 40
    p = k / n
    expected = (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
    assert pooled["review_upper95"] == pytest.approx(expected)
    assert 0.0 < pooled["wrong_archive_upper95"] < 0.1  # 0 of 39 still has a non-zero upper bound


def test_wrong_archive_bar_fails(tmp_path):
    docs = _docs(29) + [{"id": "w", "cls": "contract", "score": 0.5}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["verdict"]["pass"] is False
    assert "wrong_archive_rate 0.033 > 0.02" in report["verdict"]["reasons"]


def test_review_bar_fails(tmp_path):
    docs = _docs(18) + [{"id": f"r{i}", "cls": "contract", "stage": "review"} for i in range(2)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["verdict"]["pass"] is False
    assert "review_rate 0.100 > 0.05" in report["verdict"]["reasons"]


def test_mergers_are_reported_not_gated(tmp_path):
    docs = _docs(40) + [{"id": f"m{i}", "cls": "merger_agreement", "score": 0.2} for i in range(5)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    merger = report["classes"]["merger_agreement"]
    assert merger["gated"] is False and merger["wrong_archive_rate"] == 1.0 and merger["n"] == 5
    assert report["pooled"]["wrong_archive_rate"] == 0 and report["pooled"]["review_rate"] == 0
    assert report["verdict"]["pass"] is True


def test_per_class_bar_applies_from_500(tmp_path):
    # contract: 2 wrong of 40 (0.05); two other gated classes are clean. Pooled 2/120 = 0.017.
    docs = (_docs(38) + [{"id": f"w{i}", "cls": "contract", "score": 0.5} for i in range(2)]
            + _docs(40, "corporate_record") + _docs(40, "correspondence"))
    run = _run(tmp_path, docs)
    below = gate.gate_report(run, Bars())
    assert below["n"] == 120 and below["classes"]["contract"]["wrong_archive_rate"] == pytest.approx(0.05)
    assert below["pooled"]["wrong_archive_rate"] == pytest.approx(2 / 120)
    assert below["verdict"]["pass"] is True  # pooled rate decides below slice 500

    above = gate.gate_report(run, Bars(per_class_from_n=100))
    assert above["verdict"]["pass"] is False
    assert any("contract" in r and "wrong_archive_rate" in r for r in above["verdict"]["reasons"])


def test_missing_items_are_crashes_and_fail(tmp_path):
    docs = _docs(39) + [{"id": "lost", "cls": "contract", "item": False}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    lost = next(d for d in report["docs"] if d["id"] == "lost")
    assert lost["stage"] == "crashed" and lost["outcome"] == "crashed" and lost["score"] is None
    assert report["pooled"]["crashes"] == 1
    assert report["verdict"]["pass"] is False and any("crash" in r for r in report["verdict"]["reasons"])


def test_errored_items_are_crashes(tmp_path):
    docs = _docs(39) + [{"id": "boom", "cls": "contract", "error": "RuntimeError: x"}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["crashes"] == 1 and report["verdict"]["pass"] is False


def test_duplicate_items_keep_latest(tmp_path):
    run = tmp_path / "dup"
    run.mkdir()
    (run / "dataset.jsonl").write_text(json.dumps(
        {"id": "d1", "expected_doc_class": "contract", "expected_fields": json.dumps(TWO)}) + "\n")
    first = {"item_id": "d1", "ok": True, "error": None, "pred": {"stage": "review", "_score": None}}
    last = {"item_id": "d1", "ok": True, "error": None, "pred": {"stage": "archived", "_score": 0.97}}
    (run / "items.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n")
    report = gate.gate_report(run, Bars())
    assert report["n"] == 1 and report["docs"][0]["outcome"] == "correct_archive"
    assert report["pooled"]["review_rate"] == 0


def test_judge_error_fails(tmp_path):
    docs = _docs(39) + [{"id": "j", "cls": "contract", "stage": "review", "causes": ["judge_error"]}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["judge_errors"] == 1
    assert report["verdict"]["pass"] is False and any("judge_error" in r for r in report["verdict"]["reasons"])


def test_no_gated_documents_fails(tmp_path):
    report = gate.gate_report(_run(tmp_path, _docs(5, "merger_agreement")), Bars())
    assert report["pooled"]["review_rate"] is None and report["pooled"]["wrong_archive_rate"] is None
    assert report["pooled"]["review_upper95"] is None
    assert report["verdict"] == {"pass": False, "reasons": ["no gated documents"]}


def test_labelled_count_scopes_and_drops_templated():
    corp = {"expected_doc_class": "corporate_record", "expected_fields": json.dumps({
        "entity_name": "Acme", "record_type": "bylaws", "keywords": ["EX-3.1"],
        "subject_matter": "bylaws of Acme", "filing_number": "", "signatories": [],
        "gt_presence": {"entity_name": "present"}, "clause_count": "7"})}
    assert gate.labelled_count(corp, "corporate_record") == 2  # templated, blank, metadata and foreign keys are not labels
    claim = {"expected_fields": json.dumps({"claim_number": "C1", "denial_reasons": [], "document_name": "x"})}
    assert gate.labelled_count(claim, "insurance_claim") == 1
    assert gate.labelled_count({"expected_fields": ""}, "contract") == 0
    evidence = {"expected_fields": json.dumps({"document_name": "x", "label_evidence": "CUAD-annotated clauses: ..."})}
    assert gate.labelled_count(evidence, "contract") == 1  # evidence columns are not scored, so not labels


def test_load_bars_defaults_to_the_committed_config(tmp_path):
    bars = gate.load_bars()
    assert bars == Bars()
    custom = tmp_path / "b.yaml"
    custom.write_text("quality: 0.8\ngated: [contract]\n")
    loaded = gate.load_bars(custom)
    assert loaded.quality == 0.8 and loaded.gated == ("contract",) and loaded.review_max == 0.05
    custom.write_text("qualty: 0.8\n")
    with pytest.raises(ValueError, match="qualty"):
        gate.load_bars(custom)
