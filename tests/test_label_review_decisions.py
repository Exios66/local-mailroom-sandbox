"""The review decisions in ``data/labels/review/decisions.jsonl`` are ready for the gold build.

``scripts/gold_labels.py build --review data/labels/review/decisions.jsonl`` applies them to the
gold catalogs. The build refuses a decision that matches no catalog record, a second decision for
a record that already has one, and a correction that fails the gate on the document text. These
checks run on the committed catalogs, without the Hub text, so a broken decisions file fails here
and not halfway through a build. The gate itself runs again in the build.
"""

from __future__ import annotations

import json
from pathlib import Path

from mailroom_sandbox import gold_labels as gl

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "data" / "labels" / "review"
GOLD = ROOT / "data" / "labels" / "gold"
CATALOGS = ("correspondence", "corporate_record")
VERDICTS = {"accept", "reject", "correct"}


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _catalog() -> dict[tuple[str, str], dict]:
    return {(r["doc_id"], r["field"]): r for name in CATALOGS for r in _jsonl(GOLD / f"{name}.jsonl")}


def _decisions() -> list[dict]:
    return _jsonl(REVIEW / "decisions.jsonl")


def test_decisions_are_well_formed_and_unique():
    rows = _decisions()
    keys = [(d["doc_id"], d["field"]) for d in rows]
    assert len(keys) == len(set(keys)), "two decisions for one label: the build refuses this"
    for d in rows:
        assert d["verdict"] in VERDICTS, d
        assert gl.reviewer_problem(d.get("reviewer")) is None, d
        assert d.get("note"), d
        if d["verdict"] == "correct":
            entry = d["entry"]
            assert "value" in entry, d
            assert entry.get("evidence") or entry.get("absent") or entry.get("basis"), d
        else:
            assert "entry" not in d, d


def test_every_decision_matches_an_unreviewed_catalog_record():
    catalog = _catalog()
    for d in _decisions():
        rec = catalog.get((d["doc_id"], d["field"]))
        assert rec is not None, f"no catalog record for {d['doc_id']}.{d['field']}"
        assert not rec.get("review"), f"{d['doc_id']}.{d['field']} already has a review decision"
        if d["verdict"] == "accept":
            assert rec["status"] != "near_gold", f"{d['doc_id']}.{d['field']}: accept changes nothing"
            # the build refuses an accept that does not name the current value exactly
            assert "value" in d and d["value"] == rec.get("value"), f"{d['doc_id']}.{d['field']}: stale accept"


def test_applied_decisions_leave_valid_near_gold_records():
    catalog = _catalog()
    for d in _decisions():
        rec = catalog[(d["doc_id"], d["field"])]
        if d["verdict"] == "correct":
            e = d["entry"]
            decision = {"verdict": "correct", "reviewer": d["reviewer"], "note": d["note"], "value": e["value"],
                        "evidence": e.get("evidence"), "absent_reason": e.get("absent") or e.get("basis")}
        else:
            decision = {k: v for k, v in d.items() if k not in ("doc_id", "field", "value")}
        out = gl.apply_review(rec, decision)
        if out["status"] == "near_gold":
            assert gl._near_gold_problem(out) is None, (d["doc_id"], d["field"], gl._near_gold_problem(out))


def test_decisions_keep_the_owner_decisions():
    catalog = _catalog()
    decisions = {(d["doc_id"], d["field"]): d for d in _decisions()}
    for h in _jsonl(REVIEW / "human_reviews.jsonl"):
        if h["catalog"] not in CATALOGS or h["decision"] == "unsure":
            continue
        key = (h["doc_id"], h["field"])
        d = decisions.get(key)
        rec = catalog[key]
        if d is None:
            assert rec["status"] == "near_gold" and rec["value"] == h["value"], key
            continue
        assert d["verdict"] != "reject", f"{key}: an owner decision is never rejected"
        value = d["entry"]["value"] if d["verdict"] == "correct" else rec["value"]
        assert value == h["value"], f"{key}: decision differs from the owner's value"


def test_held_labels_are_accounted_for():
    decisions = {(d["doc_id"], d["field"]): d for d in _decisions()}
    held = _jsonl(REVIEW / "decisions_held.jsonl")
    keys = [(h["doc_id"], h["field"]) for h in held]
    assert len(keys) == len(set(keys))
    for h in held:
        key = (h["doc_id"], h["field"])
        assert h["kind"] == "held" and h["why"], key
        assert key not in decisions, f"{key} is both held and decided"
