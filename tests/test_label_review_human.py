"""The owner's own label decisions survive every rebuild of the review verdicts.

``data/labels/review/human_reviews.jsonl`` is the source of record for decisions the repository
owner made by hand. A regenerated ``verdicts.jsonl`` must still carry each of them, unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

REVIEW = Path(__file__).resolve().parents[1] / "data" / "labels" / "review"
DECISIONS = {"keep", "use_suggestion", "correct", "unsure"}


def _jsonl(name: str) -> list[dict]:
    with (REVIEW / name).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_human_rows_are_well_formed_and_unique():
    rows = _jsonl("human_reviews.jsonl")
    keys = [(r["catalog"], r["doc_id"], r["field"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        assert r["decision"] in DECISIONS
        assert r["reviewed_at"] and r["source"] == "review_desk"
        assert "value" in r and "label_before_review" in r


def test_verdicts_carry_every_human_decision():
    verdicts = {(r["catalog"], r["doc_id"], r["field"]): r for r in _jsonl("verdicts.jsonl")}
    for h in _jsonl("human_reviews.jsonl"):
        v = verdicts.get((h["catalog"], h["doc_id"], h["field"]))
        assert v is not None, f"verdicts.jsonl lost the label {h['doc_id']} {h['field']}"
        if h["decision"] == "unsure":
            assert v["verdict"] == "needs_human"
            continue
        expected = "human_corrected" if h["value"] != h["label_before_review"] else "human_verified"
        assert v["verdict"] == expected, f"{h['doc_id']} {h['field']}: human decision overwritten"
        assert v["value"] == h["value"], f"{h['doc_id']} {h['field']}: human value overwritten"


def test_no_human_verdict_without_a_human_row():
    human = {(r["catalog"], r["doc_id"], r["field"]) for r in _jsonl("human_reviews.jsonl")}
    for r in _jsonl("verdicts.jsonl"):
        if r["verdict"].startswith("human_"):
            assert (r["catalog"], r["doc_id"], r["field"]) in human
