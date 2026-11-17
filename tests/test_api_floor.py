"""``api_floor``: an API eval report recorded as a floor run (no network, no pipeline)."""

from __future__ import annotations

import json

import pytest

from mailroom_sandbox import api_floor

AUDIT = {"entries": [
    {"seq": 3, "event": "extracted", "actor": "contract", "timestamp": "2026-01-01T00:00:01.500+00:00",
     "detail": {"stage": "extracted"}},
    {"seq": 1, "event": "ingested", "actor": "pipeline", "timestamp": "2026-01-01T00:00:00+00:00", "detail": {}},
    {"seq": 2, "event": "classified", "actor": "sorter", "timestamp": "2026-01-01T00:00:01+00:00"},
    {"seq": 4, "event": "relations_linked", "actor": "pipeline", "timestamp": "2026-01-01T00:00:02+00:00"},
    {"seq": 5, "event": "archived", "actor": "archivist", "timestamp": "2026-01-01T00:00:02+00:00"},
]}


def _report(**extra):
    return {"run_tag": "apieval-x", "mode": "mock", "ok": True, "n_rows": 3, "documents": [
        {"id": "a", "doc_id": "u1", "stage": "archived", "doc_type": "letter",
         "extraction": {"overall_extraction_score": 0.75, "scoring_method": "suite", "fields": {"big": 1}}},
        {"id": "b", "doc_id": "u2", "stage": "review", "doc_type": "letter", "escalation_reason": "low conf"},
        {"id": "c", "stage": None},
    ], **extra}


ROWS = [{"id": "a", "expected_doc_class": "letter", "doc_text": "secret body", "expected_fields": {"x": 1},
         "near_gold_labels": {"fields": ["y"], "status": "near_gold"}},
        {"id": "b", "expected_doc_class": "letter", "text": "t"}, {"id": "c", "expected_doc_class": "memo"}]


def test_audit_entries_become_ordered_node_visits():
    recs = api_floor._audit_nodes("a", AUDIT)
    assert [r["node"] for r in recs] == ["intake", "classify", "extract", "archive"]  # seq order, unknown event dropped
    assert recs[1]["agent"] == "sorter" and all(r["source"] == "stage-audit" for r in recs)
    assert api_floor._latency_ms(recs) == 2000.0
    assert api_floor._audit_nodes("a", None) == [] and api_floor._audit_nodes("a", {"entries": "x"}) == []


def test_record_writes_the_run_store_files(tmp_path):
    calls = []

    def audit(doc_id):
        calls.append(doc_id)
        if doc_id == "u2":
            raise RuntimeError("audit down")  # a missing trail must not lose the result
        return AUDIT

    run = api_floor.record_floor_run(_report(), ROWS, base=tmp_path, run_id="r1", audit=audit)
    assert run == tmp_path / "runtime" / "runs" / "r1" and calls == ["u1", "u2"]
    items = [json.loads(x) for x in (run / "items.jsonl").read_text().splitlines()]
    assert [i["ok"] for i in items] == [True, True, False] and items[2]["error"]
    assert items[0]["score"] == {"overall_extraction_score": 0.75, "scoring_method": "suite"}
    assert items[1]["pred"]["escalation_reason"] == "low conf" and items[1]["latency_ms"] is None
    nodes = [json.loads(x) for x in (run / "nodes.jsonl").read_text().splitlines()]
    assert {n["doc"] for n in nodes} == {"a"}
    ds = (run / "dataset.jsonl").read_text()
    assert "secret body" not in ds and '"text"' not in ds and "near_gold_labels" in ds
    lock = json.loads((run / "spec.lock.json").read_text())
    assert lock["engine"]["kind"] == "api-eval-mock" and lock["engine"]["node_source"] == "stage-audit"
    assert json.loads((run / "checkpoint.json").read_text()) == {"state": "complete", "cursor": 3, "total": 3}


def test_record_refuses_existing_or_unsafe_ids(tmp_path):
    api_floor.record_floor_run(_report(ok=False), ROWS, base=tmp_path, run_id="r1")
    assert json.loads((tmp_path / "runtime/runs/r1/checkpoint.json").read_text())["state"] == "failed"
    with pytest.raises(FileExistsError):
        api_floor.record_floor_run(_report(), ROWS, base=tmp_path, run_id="r1")
    assert not [p for p in (tmp_path / "runtime").iterdir() if p.name.startswith(".floor-run-")], "no staging left"
    for bad in ("", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            api_floor.record_floor_run(_report(), ROWS, base=tmp_path, run_id=bad)


def test_a_failed_write_leaves_no_half_run(tmp_path, monkeypatch):
    """A write failure removes the staging dir, so the floor lists nothing and a retry can reuse the id."""
    real = api_floor.Path.write_text

    def flaky(self, text, *a, **k):
        if self.name == "checkpoint.json":
            raise OSError("disk full")
        return real(self, text, *a, **k)

    monkeypatch.setattr(api_floor.Path, "write_text", flaky)
    with pytest.raises(OSError):
        api_floor.record_floor_run(_report(), ROWS, base=tmp_path, run_id="r1")
    monkeypatch.undo()
    assert not (tmp_path / "runtime" / "runs" / "r1").exists()
    assert [p.name for p in (tmp_path / "runtime").iterdir()] == []
    assert api_floor.record_floor_run(_report(), ROWS, base=tmp_path, run_id="r1").is_dir()
