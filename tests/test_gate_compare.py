"""Step-up verdict on the new documents and offline threshold evidence (offline, deterministic)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import gate, gate_compare
from mailroom_sandbox.job.gate import Bars

LABELS = {"entity_name": "Acme Corp", "record_type": "bylaws"}


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


def _run(root, name, docs):
    """docs: dicts with id and optional cls/stage/score/confidence/no_confidence."""
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            cls = d.get("cls", "corporate_record")
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": cls,
                                 "expected_fields": json.dumps(LABELS)}) + "\n")
            pred = {"stage": d.get("stage", "archived"), "doc_type": cls, "_score": d.get("score", 0.95),
                    "review_causes": []}
            if not d.get("no_confidence"):
                pred["extraction_confidence"] = d.get("confidence", 1.0)
            it.write(json.dumps({"item_id": d["id"], "ok": True, "error": None, "prompt_tokens": 10,
                                 "completion_tokens": 5, "pred": pred}) + "\n")
    return run


def _ids(*names):
    return [{"id": n} for n in names]


def test_new_docs_lane_uses_only_new_documents(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", _ids("a", "b", "c", "d"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["new_docs"] == ["c", "d"]
    assert out["new_docs_gate"]["n"] == 2
    assert [d["id"] for d in out["new_docs_gate"]["docs"]] == ["c", "d"]
    assert out["nested"] is True
    assert out["shared_paired"]["shared_docs"] == 2
    assert out["verdict"] == {"pass": True, "reasons": []}


def test_new_docs_gate_failure_fails_the_step_up(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a"))
    nxt = _run(tmp_path, "next", _ids("a") + [{"id": "c", "score": 0.5}, {"id": "d", "score": 0.5}])
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["verdict"]["pass"] is False
    assert any("wrong_archive_rate" in r for r in out["verdict"]["reasons"])
    # the shared document does not count toward the new-documents verdict
    assert out["new_docs_gate"]["pooled"]["wrong_archive_rate"] == 1.0


def test_non_nested_slices_fail(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "gone"))
    nxt = _run(tmp_path, "next", _ids("a", "c"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["nested"] is False
    assert out["new_docs"] == ["c"]
    assert out["verdict"]["pass"] is False
    assert "slices do not nest" in out["verdict"]["reasons"]


def test_no_new_documents_fails(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", _ids("a", "b"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["new_docs"] == [] and out["verdict"]["pass"] is False
    assert "no new documents" in out["verdict"]["reasons"]


def test_only_ids_restricts_rates_buckets_and_n(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "score": 0.5}, {"id": "b"}, {"id": "c", "stage": "review"}])
    full = gate.gate_report(run, Bars(), audit=False)
    sub = gate.gate_report(run, Bars(), audit=False, only_ids={"b", "c"})
    assert full["n"] == 3 and sub["n"] == 2
    assert [d["id"] for d in sub["docs"]] == ["b", "c"]
    assert sub["pooled"]["wrong_archive_rate"] == 0
    assert sub["pooled"]["review_rate"] == 0.5
    assert [d["id"] for b in sub["buckets"].values() for d in b["docs"]] == ["c"]
    assert gate.gate_report(run, Bars(), audit=False, only_ids=None)["n"] == 3


def test_threshold_evidence_counts(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "confidence": 0.95, "score": 0.5},
                               {"id": "b", "confidence": 0.95}, {"id": "c", "confidence": 1.0}])
    out = gate_compare.threshold_evidence(run, Bars())
    assert out["label"] == "upper bound: assumes the judge rejects every caught wrong archive"
    at = out["pooled"]["thresholds"][0.96]
    assert at == {"extra_judged": 2, "wrong_archives_caught_upper_bound": 1, "correct_archives_disturbed": 1}
    assert out["pooled"]["thresholds"][0.90] == {"extra_judged": 0, "wrong_archives_caught_upper_bound": 0,
                                                 "correct_archives_disturbed": 0}
    assert out["pooled"]["thresholds"][1.01]["extra_judged"] == 3  # 1.01 sends every archive to the judge
    assert out["classes"]["corporate_record"]["thresholds"][0.96] == at
    assert out["pooled"]["no_confidence"] == 0 and out["pooled"]["archived"] == 3


def test_threshold_evidence_counts_missing_confidence_separately(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "confidence": 0.95}, {"id": "b", "no_confidence": True, "score": 0.5},
                               {"id": "c", "no_confidence": True}, {"id": "d", "stage": "review"},
                               {"id": "e", "cls": "merger_agreement", "confidence": 0.5}])
    out = gate_compare.threshold_evidence(run, Bars())
    pooled = out["pooled"]
    assert pooled["archived"] == 3 and pooled["no_confidence"] == 2
    assert pooled["no_confidence_by_outcome"] == {"wrong_archive": 1, "correct_archive": 1}
    assert pooled["thresholds"][0.96]["extra_judged"] == 1  # the 2 unconfident docs are not in the counts
    assert "merger_agreement" not in out["classes"]  # reported never, gated only
