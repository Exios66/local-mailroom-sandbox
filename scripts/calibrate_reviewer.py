#!/usr/bin/env python3
"""Pick each class's decision-reviewer cutoff from a labelled reviewer run.

Answers are grouped by the class the reviewer predicted, since that class's
cutoff is the one that admits them. The cutoff is the lowest confidence at which
a class's accepted answers reach the target accuracy. Five seeded folds estimate
what that rule delivers: each fold is scored with a cutoff tuned on the other
four, so every answer is test data once. ``meets_target`` is true only when the
interval's lower bound clears the target. A class that never reaches the target
gets no cutoff, so it should not be configured as reviewed.
A run that is not done, or misses any locked document, is refused. Each class also
reports its answers at the top confidence: wrong ones there no cutoff can remove.
"""
from __future__ import annotations

import argparse
import json
import random
import sys

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.sand42_cards import wilson
from mailroom_sandbox.job.spec import run_dir
from mailroom_sandbox.overlay import live_doc_classes
from mailroom_sandbox.paths import repo_root

FOLDS = 5


def _incomplete(store: RunStore) -> str | None:
    """Why the run cannot stand for its whole locked draw, or None when it can."""
    if store.state() != "done":
        return f"run {store.run_id} is {store.state() or 'not started'}, not done"
    expected = {str(row.get("id")) for row in store.dataset_rows()}
    seen = {str(item.get("item_id")) for item in store.load_items()}
    missing = expected - seen
    if not expected or missing:
        return f"run {store.run_id} has no answer for {len(missing)} of {len(expected)} locked documents"
    return None


def _answer(item: dict, classes: set[str]) -> tuple[str, float] | None:
    """The answer's (doc_type, confidence) when it is usable: ok, in the taxonomy, a real confidence."""
    pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
    doc_type, confidence = pred.get("doc_type"), pred.get("confidence")
    if (item.get("ok") and doc_type in classes and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool) and 0.0 <= confidence <= 1.0):
        return str(doc_type), float(confidence)
    return None


def _rows(store: RunStore, classes: set[str] | None = None) -> dict[str, list[tuple[float, bool]]]:
    """Per predicted class: (confidence, correct).

    The decision reviewer applies the cutoff of the class it predicted, so that
    is the class whose evidence an answer is. A failed, unscored or
    out-of-taxonomy answer predicts no class and can clear no cutoff.
    """
    classes = set(live_doc_classes()) if classes is None else classes
    expected = {str(row.get("id")): str(row.get("expected_doc_class")) for row in store.dataset_rows()}
    by_class: dict[str, list[tuple[float, bool]]] = {name: [] for name in sorted(set(expected.values()))}
    for item in store.load_items():
        truth = expected.get(str(item.get("item_id")))
        answer = _answer(item, classes) if truth is not None else None
        if answer is not None:
            by_class.setdefault(answer[0], []).append((answer[1], answer[0] == truth))
    return by_class


def _accepted(rows: list[tuple[float, bool]], cutoff: float) -> tuple[int, int]:
    kept = [correct for confidence, correct in rows if confidence >= cutoff]
    return sum(kept), len(kept)


def _saturation(rows: list[tuple[float, bool]]) -> dict:
    """The answers at the highest confidence, which no cutoff can separate."""
    if not rows:
        return {"top_confidence": None, "top_confidence_documents": 0, "top_confidence_wrong": 0}
    top = max(confidence for confidence, _ in rows)
    right, kept = _accepted(rows, top)
    return {"top_confidence": top, "top_confidence_documents": kept, "top_confidence_wrong": kept - right}


def _cutoff(rows: list[tuple[float, bool]], target: float) -> float | None:
    for cutoff in sorted({confidence for confidence, _ in rows if confidence > 0}):
        right, kept = _accepted(rows, cutoff)
        if kept and right / kept >= target:
            return cutoff
    return None


def _cross_fit(rows: list[tuple[float, bool]], target: float, folds: int = FOLDS) -> tuple[int, int]:
    """(right, accepted) over all folds, each scored with a cutoff tuned on the others."""
    right = kept = 0
    for fold in range(folds):
        held = rows[fold::folds]
        cutoff = _cutoff([row for index, row in enumerate(rows) if index % folds != fold], target)
        if cutoff is not None:
            fold_right, fold_kept = _accepted(held, cutoff)
            right, kept = right + fold_right, kept + fold_kept
    return right, kept


def calibrate(store: RunStore, *, target: float = 0.95, seed: int = 42,
              classes: set[str] | None = None) -> dict:
    """Cutoffs from a finished run; raises ``ValueError`` on a run that misses locked documents."""
    if not 0.0 < target <= 1.0:
        raise ValueError(f"target accuracy must be in (0, 1]; got {target}")
    reason = _incomplete(store)
    if reason:
        raise ValueError(reason)
    results = {}
    for name, rows in sorted(_rows(store, classes).items()):
        rows = sorted(rows)
        random.Random(seed).shuffle(rows)
        cutoff = _cutoff(rows, target)
        result = {"documents": len(rows), "cutoff": cutoff, **_saturation(rows)}
        if cutoff is not None:
            right, kept = _cross_fit(rows, target)
            interval = wilson(right, kept) if kept else None
            result.update({"holdout_documents": len(rows), "holdout_accepted": kept,
                           "holdout_accuracy": right / kept if kept else None,
                           "holdout_accuracy_ci": interval,
                           "holdout_share_accepted": kept / len(rows) if rows else None,
                           "meets_target": bool(interval and interval[0] >= target)})
        results[name] = result
    return {"run_id": store.run_id, "target_accuracy": target, "seed": seed, "classes": results}


def probe(store: RunStore, *, min_valid: int = 9, max_mean_seconds: float = 10.0,
          classes: set[str] | None = None) -> dict:
    """Whether a model is fit to calibrate: a finished run, taxonomy-valid answers, usable speed."""
    classes = set(live_doc_classes()) if classes is None else classes
    items = store.load_items()
    valid = sum(_answer(item, classes) is not None for item in items)
    latency = [float(item["latency_ms"]) / 1000.0 for item in items if item.get("latency_ms") is not None]
    mean_seconds = sum(latency) / len(latency) if latency else None
    incomplete = _incomplete(store)
    passed = (incomplete is None and valid >= min_valid
              and mean_seconds is not None and mean_seconds <= max_mean_seconds)
    return {"run_id": store.run_id, "documents": len(items), "valid_answers": valid,
            "mean_seconds_per_document": mean_seconds, "incomplete": incomplete, "passed": passed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--target", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--probe", action="store_true", help="check the model is fit to calibrate")
    args = parser.parse_args()
    if args.probe:
        verdict = probe(RunStore(run_dir(args.run)))
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["passed"] else 1
    try:
        result = calibrate(RunStore(run_dir(args.run)), target=args.target, seed=args.seed)
    except ValueError as exc:
        print(f"calibrate_reviewer: {exc}", file=sys.stderr)
        return 1
    path = repo_root() / "reports" / "reviewer-calibration" / f"{args.run}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["classes"], indent=2, sort_keys=True))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
