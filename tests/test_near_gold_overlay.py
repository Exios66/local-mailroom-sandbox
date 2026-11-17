"""Near-gold scoring overlay: the committed export stays consistent and fills only unlabelled fields."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import gold_labels as gl
from mailroom_sandbox import interim_labels as il
from mailroom_sandbox.job.spec import DatasetSpec

TEXT = "From: Jane Roe\nTo: John Doe\nSent: May 14, 2001\nPlease call me."


def _row(**exp):
    return {"id": "D1", "expected_doc_class": "correspondence", "expected_subclass": "email", "doc_text": TEXT,
            "expected_fields": json.dumps({"sender": "Hub Sender", "gt_presence": json.dumps({"sender": "populated"}), **exp})}


def _lab(value, basis="near_gold:two_pass_agree"):
    return {"value": value, "status": "gap_fill", "basis": basis, "use_as_truth": False}


def _rec(**labels):
    return {"doc_id": "D1", "doc_sha256": il.doc_sha(TEXT), "labels": labels}


def test_committed_overlay_is_consistent():
    assert gl.verify_overlay() == []
    overlay = gl.load_near_gold()
    assert overlay and len(gl.near_gold_fingerprint()) == 64
    for rec in overlay.values():
        for lab in rec["labels"].values():
            assert lab["basis"].startswith("near_gold:") and lab["use_as_truth"] is False


def test_apply_fills_only_unlabelled_fields_and_marks_them():
    row = _row(recipient=None, gt_presence=json.dumps({"sender": "populated", "urgency": "schema_documented_absence"}))
    rec = _rec(sender=_lab("Jane Roe"), recipient=_lab("John Doe"), urgency=_lab("urgent"),
               action_items=_lab([]), demand_amount=_lab(None), other=_lab("x", basis="candidate"))
    out = gl.apply_near_gold(row, {"D1": rec}, overlay_sha="abc")
    exp = json.loads(out["expected_fields"])
    assert exp["sender"] == "Hub Sender"            # Hub label wins
    assert "urgency" not in exp                     # a Hub documented absence wins too
    assert exp["recipient"] == "John Doe" and exp["action_items"] == [] and exp["demand_amount"] is None
    assert "other" not in exp                       # only near_gold labels are applied
    pres = json.loads(exp["gt_presence"])
    assert pres["recipient"] == "populated"
    assert pres["action_items"] == pres["demand_amount"] == "schema_documented_absence"
    assert out["near_gold_labels"] == {"fields": ["action_items", "demand_amount", "recipient"],
                                       "overlay_sha256": "abc", "status": "near_gold"}
    assert json.loads(row["expected_fields"]).get("recipient") is None  # input not mutated


def test_apply_skips_changed_text_and_interim_labels():
    rec = _rec(recipient=_lab("John Doe"))
    changed = {**_row(), "doc_text": TEXT + " amended"}
    assert gl.apply_near_gold(changed, {"D1": rec}, overlay_sha="abc") == changed
    interim = il.apply_overlay(_row(), {"D1": {"doc_id": "D1", "doc_sha256": il.doc_sha(TEXT), "labels": {
        "recipient": {"value": "Interim Doe", "status": "gap_fill", "use_as_truth": True}}}}, overlay_sha="i")
    out = gl.apply_near_gold(interim, {"D1": rec}, overlay_sha="abc")
    assert json.loads(out["expected_fields"])["recipient"] == "Interim Doe" and "near_gold_labels" not in out


def test_verify_overlay_flags_edits(tmp_path):
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"schema": gl.OVERLAY_SCHEMA, "files": {"c.jsonl": "0" * 64}}))
    (tmp_path / "c.jsonl").write_text(json.dumps({"doc_id": "D1", "labels": {}}) + "\n")
    (tmp_path / "stray.jsonl").write_text("")
    problems = gl.verify_overlay(tmp_path)
    assert any("sha256 differs" in p for p in problems) and any("stray.jsonl" in p for p in problems)
    assert "missing" in gl.verify_overlay(tmp_path / "nope")[0]


def test_near_gold_labels_is_hashed_only_when_set():
    assert "near_gold_labels" not in DatasetSpec(repo="r", split="train").request_core()
    on = DatasetSpec(repo="r", split="train", near_gold_labels=True).request_core()
    assert on["near_gold_labels"] == gl.near_gold_fingerprint()


def test_prepare_subset_applies_near_gold_only_when_asked(tmp_path, monkeypatch):
    from mailroom_sandbox.corpus import prepare_subset

    row = _row()
    src = tmp_path / "rows.jsonl"
    src.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(gl, "verify_overlay", lambda root=None: [])
    monkeypatch.setattr(gl, "load_near_gold", lambda root=None: {"D1": _rec(recipient=_lab("John Doe"))})
    monkeypatch.setattr(gl, "near_gold_fingerprint", lambda root=None: "f" * 64)
    off = prepare_subset(DatasetSpec(local_path=str(src)), tmp_path / "off.jsonl")
    assert "near_gold_labels" not in off["metadata"]
    on = prepare_subset(DatasetSpec(local_path=str(src), near_gold_labels=True), tmp_path / "on.jsonl")
    assert on["metadata"]["near_gold_labels"] == {"overlay_sha256": "f" * 64, "status": "near_gold",
                                                  "rows_with_labels": 1, "fields_applied": 1}
    locked = json.loads((tmp_path / "on.jsonl").read_text())
    exp = locked["expected_fields"]
    assert (json.loads(exp) if isinstance(exp, str) else exp)["recipient"] == "John Doe"
    monkeypatch.setattr(gl, "verify_overlay", lambda root=None: ["c.jsonl: sha256 differs"])
    with pytest.raises(ValueError, match="near-gold label overlay is inconsistent"):
        prepare_subset(DatasetSpec(local_path=str(src), near_gold_labels=True), tmp_path / "bad.jsonl")


def test_prepare_subset_refuses_an_overlay_that_changes_while_read(tmp_path, monkeypatch):
    from mailroom_sandbox.corpus import prepare_subset

    src = tmp_path / "rows.jsonl"
    src.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    shas = iter(["a" * 64, "b" * 64])  # an export lands between the two reads
    monkeypatch.setattr(gl, "verify_overlay", lambda root=None: [])
    monkeypatch.setattr(gl, "load_near_gold", lambda root=None: {"D1": _rec(recipient=_lab("John Doe"))})
    monkeypatch.setattr(gl, "near_gold_fingerprint", lambda root=None: next(shas))
    with pytest.raises(ValueError, match="changed while it was read"):
        prepare_subset(DatasetSpec(local_path=str(src), near_gold_labels=True), tmp_path / "x.jsonl")
