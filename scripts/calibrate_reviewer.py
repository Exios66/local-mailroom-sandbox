#!/usr/bin/env python3
"""Pick each class's decision-reviewer cutoff from a labelled reviewer run.

Each class is split in half by a seeded shuffle. The cutoff is the lowest
confidence at which the tuning half's accepted answers reach the target
accuracy; the other half reports what that cutoff delivers. A class that never
reaches the target gets no cutoff, so it should not be configured as reviewed.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.sand42_cards import wilson
from mailroom_sandbox.job.spec import run_dir
from mailroom_sandbox.paths import repo_root


def _rows(store: RunStore) -> dict[str, list[tuple[float, bool]]]:
    """Per expected class: (confidence, correct). A failed or unscored answer counts as (0, wrong)."""
    expected = {str(row.get("id")): str(row.get("expected_doc_class")) for row in store.dataset_rows()}
    by_class: dict[str, list[tuple[float, bool]]] = {}
    for item in store.load_items():
        name = expected.get(str(item.get("item_id")))
        if name is None:
            continue
        pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
        confidence = pred.get("confidence")
        usable = item.get("ok") and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        by_class.setdefault(name, []).append(
            (float(confidence), pred.get("doc_type") == name) if usable else (0.0, False))
    return by_class


def _accepted(rows: list[tuple[float, bool]], cutoff: float) -> tuple[int, int]:
    kept = [correct for confidence, correct in rows if confidence >= cutoff]
    return sum(kept), len(kept)


def _cutoff(rows: list[tuple[float, bool]], target: float) -> float | None:
    for cutoff in sorted({confidence for confidence, _ in rows if confidence > 0}):
        right, kept = _accepted(rows, cutoff)
        if kept and right / kept >= target:
            return cutoff
    return None


def calibrate(store: RunStore, *, target: float = 0.95, seed: int = 42) -> dict:
    classes = {}
    for name, rows in sorted(_rows(store).items()):
        rows = sorted(rows)
        random.Random(seed).shuffle(rows)
        middle = len(rows) // 2
        tune, holdout = rows[:middle], rows[middle:]
        cutoff = _cutoff(tune, target)
        result = {"documents": len(rows), "cutoff": cutoff}
        if cutoff is not None:
            right, kept = _accepted(holdout, cutoff)
            result.update({"holdout_documents": len(holdout), "holdout_accepted": kept,
                           "holdout_accuracy": right / kept if kept else None,
                           "holdout_accuracy_ci": wilson(right, kept) if kept else None,
                           "holdout_share_accepted": kept / len(holdout) if holdout else None})
        classes[name] = result
    return {"run_id": store.run_id, "target_accuracy": target, "seed": seed, "classes": classes}


def probe(store: RunStore, *, min_valid: int = 9, max_mean_seconds: float = 10.0) -> dict:
    """Whether a model is fit to calibrate: valid answers, real confidences, usable speed."""
    items = store.load_items()
    valid = 0
    for item in items:
        pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
        confidence = pred.get("confidence")
        if (item.get("ok") and pred.get("doc_type") and not isinstance(confidence, bool)
                and isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0):
            valid += 1
    latency = [float(item["latency_ms"]) / 1000.0 for item in items if item.get("latency_ms") is not None]
    mean_seconds = sum(latency) / len(latency) if latency else None
    passed = valid >= min_valid and mean_seconds is not None and mean_seconds <= max_mean_seconds
    return {"run_id": store.run_id, "documents": len(items), "valid_answers": valid,
            "mean_seconds_per_document": mean_seconds, "passed": passed}


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
    result = calibrate(RunStore(run_dir(args.run)), target=args.target, seed=args.seed)
    path = repo_root() / "reports" / "reviewer-calibration" / f"{args.run}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["classes"], indent=2, sort_keys=True))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
