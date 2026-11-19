"""The review decisions in ``data/labels/review/`` are applied to the gold catalogs.

``scripts/gold_labels.py review --review data/labels/review/decisions.jsonl
data/labels/review/decisions_supersede.jsonl`` applied them in place: each decision settled one
catalog record, and each superseding line replaced the earlier review it names. These checks run
on the committed catalogs, without the Hub text, so a decision that is not applied (or a catalog
edited after it) fails here. The gate itself ran in the review command.
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


def _supersedes() -> list[dict]:
    return _jsonl(REVIEW / "decisions_supersede.jsonl")


def test_every_decision_is_applied_to_its_catalog_record():
    catalog = _catalog()
    superseding = {(d["doc_id"], d["field"]) for d in _supersedes()}
    for d in _decisions():
        key = (d["doc_id"], d["field"])
        rec = catalog.get(key)
        assert rec is not None, f"no catalog record for {d['doc_id']}.{d['field']}"
        if key in superseding:
            continue
        review = rec.get("review") or {}
        assert rec["status"] == "near_gold", key
        assert review.get("verdict") == d["verdict"] and review.get("note") == d["note"], f"{key}: decision not applied"
        if d["verdict"] == "accept":
            assert d["value"] == rec.get("value"), f"{key}: stale accept"
        else:
            assert review["original"] is not None and rec["value_source"]["kind"] == "review_correction", key
            assert rec["value"] == d["entry"]["value"], f"{key}: correction not applied"


def test_superseding_reviews_replace_the_review_they_name():
    catalog = _catalog()
    rows = _supersedes()
    keys = [(d["doc_id"], d["field"]) for d in rows]
    assert len(keys) == len(set(keys))
    for d in rows:
        assert d["verdict"] in ("accept", "correct") and gl.reviewer_problem(d.get("reviewer")) is None, d
        rec = catalog[(d["doc_id"], d["field"])]
        review = rec["review"]
        assert review["note"] == d["note"] and review["verdict"] == d["verdict"], d["doc_id"]
        earlier = review["supersedes"]
        assert {"verdict": earlier["verdict"], "value": earlier["value"]} == d["supersedes"], d["doc_id"]
        if d["verdict"] == "correct":
            assert rec["value"] == d["entry"]["value"], d["doc_id"]


def test_decided_records_are_valid_near_gold():
    catalog = _catalog()
    for d in _decisions() + _supersedes():
        rec = catalog[(d["doc_id"], d["field"])]
        assert rec["status"] == "near_gold" and gl._near_gold_problem(rec) is None, (d["doc_id"], d["field"])


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
    decisions = {(d["doc_id"], d["field"]) for d in _decisions() + _supersedes()}
    held = _jsonl(REVIEW / "decisions_held.jsonl")
    keys = [(h["doc_id"], h["field"]) for h in held]
    assert len(keys) == len(set(keys))
    for h in held:
        key = (h["doc_id"], h["field"])
        assert h["kind"] == "held" and h["why"], key
        assert key not in decisions, f"{key} is both held and decided"


def test_consensus_votes_decide_every_delegated_label():
    """Three judges per label; the majority value is applied, a three-way split stays open."""
    catalog = _catalog()
    verdicts = {(v["doc_id"], v["field"]): v for v in _jsonl(REVIEW / "verdicts.jsonl")}
    held = {(h["doc_id"], h["field"]) for h in _jsonl(REVIEW / "decisions_held.jsonl")}
    interim = {(r["doc_id"], r["field"]): r for r in _jsonl(REVIEW / "interim_reviews.jsonl")}
    rows = _jsonl(REVIEW / "consensus_votes.jsonl")
    keys = [(r["doc_id"], r["field"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        key = (r["doc_id"], r["field"])
        assert set(r["votes"]) == {"claude_main", "judge_1", "judge_2"} and r["decided_by"], key
        assert r["agreement"] in ("unanimous", "2-1", "split"), key
        if r["agreement"] == "split":
            assert r["outcome"] == "needs_human" and r["chosen_value"] is None, key
            assert key in held or verdicts[key]["verdict"] == "needs_human", key
            continue
        if key in catalog:
            assert catalog[key]["value"] == r["chosen_value"], f"{key}: the majority value is not in the catalog"
        elif key in interim:
            assert interim[key]["value"] == r["chosen_value"], f"{key}: the majority value is not reviewed"
        else:  # a disputed gate label the vote rejected: the Hub value stands
            assert verdicts[key]["source"] == "interim" and verdicts[key]["value"] == r["chosen_value"], key


def test_every_policy_group_is_decided():
    groups = json.loads((REVIEW / "policy_questions.json").read_text(encoding="utf-8"))
    used = {v["policy_group"] for v in _jsonl(REVIEW / "verdicts.jsonl") if v.get("policy_group")}
    assert used <= set(groups)
    for name, q in groups.items():
        assert q.get("decision") and q.get("decided_by"), name
        c = q["consensus"]
        assert c["unanimous"] + c["two_to_one"] + c["split"] == c["labels"], name
