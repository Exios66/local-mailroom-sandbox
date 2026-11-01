#!/usr/bin/env python3
"""Extraction quality gate: build the baseline sample, then calibrate the gate against the dojo.

The gate (``task: extraction_gate``, question set ``config/decisions/extraction_gate_v*.yaml``) is
the Decisions model ``openai/gpt-6-luna-decisions`` reading a document with the specialist's real
extraction of it. Its truth is the dojo score of that extraction against the row's
``expected_fields`` (the same scorer every specialist run uses).

``inputs`` writes the baseline documents, mailroom-dataset ground_truth rows taken from a locked
run's ``dataset.jsonl``, stratified by subclass within each of the five classes (seed 42):
one file per class for the specialist runs (``data/runtime/handoff/gate-<split>-<class>.jsonl``)
and their union for the gate run (``gate-<split>.jsonl``). A class's rows must carry its ground
truth (CUAD / MAUD labels for contract / merger, populated fields otherwise).

``calibrate`` reads a finished gate run: per class and overall, how well ``accept_probability``
separates good extractions (dojo score >= --good) from bad ones (AUROC), the accept cutoff that
keeps precision >= --precision, and per-field support against per-field truth.

    python scripts/extraction_gate.py --split train inputs --dataset-run reviewer-calibration-luna-decisions-v3.1.0-train
    sandbox run start --config config/runs/extraction-gate-specialist-<class>-qwen.yaml --initials XX   # x5
    sandbox run start --config config/runs/extraction-gate-luna-v1.0.0-baseline.yaml --initials XX
    python scripts/extraction_gate.py calibrate --run extraction-gate-luna-v1.0.0-baseline
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import repo_root

CLASSES = ("insurance_claim", "corporate_record", "correspondence", "contract", "merger_agreement")
# Baseline size per class: small enough to afford, large enough for a per-class AUROC.
BASELINE = {"insurance_claim": 60, "corporate_record": 40, "correspondence": 60, "contract": 40, "merger_agreement": 20}
# Contract and merger documents run to hundreds of thousands of characters; the baseline caps the
# length so a handful of outliers cannot take the budget (the cap is reported with the sample).
MAX_CHARS = {"contract": 120_000, "merger_agreement": 400_000}


def _lines(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="\n") as handle:
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


def _expected(row: dict) -> dict:
    raw = row.get("expected_fields") or {}
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def has_truth(row: dict) -> bool:
    """Whether the row carries ground truth the dojo scores an extraction of its class against."""
    exp = _expected(row)
    cls = row.get("expected_doc_class")
    if cls == "contract":
        return exp.get("cuad_clause_labels") not in (None, "", "{}", {})
    if cls == "merger_agreement":
        return exp.get("maud_clause_labels") not in (None, "", "{}", {})
    try:
        presence = json.loads(exp.get("gt_presence") or "{}")
    except (TypeError, ValueError):
        presence = {}
    return any(v == "populated" for v in presence.values())


def stratified(rows: list[dict], count: int, seed: int) -> list[dict]:
    """``count`` rows spread evenly over subclasses (round-robin over seeded shuffles)."""
    rng = random.Random(seed)
    by_sub: dict[str, list[dict]] = collections.defaultdict(list)
    for row in sorted(rows, key=lambda r: r["id"]):
        by_sub[str(row.get("expected_subclass") or "")].append(row)
    for bucket in by_sub.values():
        rng.shuffle(bucket)
    picked: list[dict] = []
    order = sorted(by_sub)
    while len(picked) < count and any(by_sub.values()):
        for sub in order:
            if by_sub[sub] and len(picked) < count:
                picked.append(by_sub[sub].pop())
    return sorted(picked, key=lambda r: r["id"])


def cmd_inputs(args: argparse.Namespace) -> int:
    root = repo_root()
    rows: dict[str, dict] = {}
    for rid in args.dataset_run:
        for row in _lines(root / "data" / "runtime" / "runs" / rid / "dataset.jsonl"):
            if row.get("split", args.split) == args.split:
                rows.setdefault(row["id"], row)
    out_dir = root / "data" / "runtime" / "handoff"
    out_dir.mkdir(parents=True, exist_ok=True)
    union: list[dict] = []
    summary: dict[str, Any] = {}
    for cls in CLASSES:
        pool = [r for r in rows.values() if r.get("expected_doc_class") == cls and has_truth(r)
                and len(r.get("doc_text") or "") <= MAX_CHARS.get(cls, 10**9)]
        picked = stratified(pool, BASELINE[cls], args.seed)
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in picked)
        path = out_dir / f"gate-{args.split}-{cls}.jsonl"
        path.write_text(text, encoding="utf-8")
        union.extend(picked)
        summary[cls] = {"file": str(path.relative_to(root)), "documents": len(picked), "pool": len(pool),
                        "max_chars": MAX_CHARS.get(cls), "doc_chars": sum(len(r["doc_text"]) for r in picked),
                        "by_subclass": dict(collections.Counter(r.get("expected_subclass") for r in picked)),
                        "sha256": hashlib.sha256(text.encode()).hexdigest()}
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in sorted(union, key=lambda r: r["id"]))
    path = out_dir / f"gate-{args.split}.jsonl"
    path.write_text(text, encoding="utf-8")
    summary["all"] = {"file": str(path.relative_to(root)), "documents": len(union),
                      "doc_chars": sum(len(r["doc_text"]) for r in union), "sha256": hashlib.sha256(text.encode()).hexdigest()}
    print(json.dumps(summary, indent=2))
    return 0


# ---------------------------------------------------------------------------- calibration

def auroc(scores: list[float], labels: list[bool]) -> float | None:
    """Probability a random good extraction outranks a random bad one (ties count half)."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation of the gate's accept probability with the dojo score."""
    if len(xs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(cov / var, 4) if var else None


def cutoff_for_precision(scores: list[float], labels: list[bool], precision: float) -> dict[str, Any]:
    """Lowest accept cutoff whose accepted set keeps the target precision (most coverage)."""
    best: dict[str, Any] = {"cutoff": None, "precision": None, "accept_rate": 0.0, "recall": 0.0}
    n_good = sum(labels)
    for cut in sorted(set(scores)):
        acc = [y for s, y in zip(scores, labels) if s >= cut]
        if acc and sum(acc) / len(acc) >= precision:
            return {"cutoff": round(cut, 4), "precision": round(sum(acc) / len(acc), 4),
                    "accept_rate": round(len(acc) / len(labels), 4),
                    "recall": round(sum(acc) / n_good, 4) if n_good else None}
    return best


def _field_truth(doc_type: str, row: dict, fields: dict, good: float) -> dict[str, bool]:
    """Per-field correctness of the extraction, from the dojo scorers."""
    exp = _expected(row)
    out: dict[str, bool] = {}
    try:
        if doc_type == "contract":
            from llm_dojo_scoring.sandbox_scoring import FIELD_CATEGORY, _empty, _value_ok, gt_categories

            spans = gt_categories(exp.get("cuad_clause_labels"))
            for field, cat in FIELD_CATEGORY.items():
                if cat in spans:
                    value = fields.get(field)
                    out[field] = (_value_ok(field, value, spans[cat]) if field in ("document_name", "parties", "governing_law")
                                  else not _empty(value)) if spans[cat] else _empty(value)
            from mailroom_sandbox.eval.cuad_scoring import score_cuad

            out["cuad_clauses"] = float(score_cuad(fields, exp["cuad_clause_labels"]).get("cuad_presence_f1") or 0) >= good
            return out
        if doc_type == "merger_agreement":
            from mailroom_sandbox.eval.maud_scoring import score_maud

            out["maud_clauses"] = float(score_maud(fields, exp["maud_clause_labels"]).get("maud_accuracy") or 0) >= good
            sub = row.get("expected_subclass")
            if sub and sub != "other":
                out["merger_consideration"] = fields.get("merger_consideration") == sub
            return out
        from mailroom_sandbox.datasets import parse_expected_fields
        from mailroom_sandbox.eval.scoring import suite_for_doc_type

        suite = suite_for_doc_type(doc_type)
        kwargs = {"doc_subclass": row.get("expected_subclass")} if doc_type == "corporate_record" and row.get("expected_subclass") else {}
        result = suite.score(parse_expected_fields(row) or exp, fields, doc_text=row.get("doc_text"), detailed=True, **kwargs)
        extraction = result["extraction"] if isinstance(result, dict) else result
        unlabeled = set((result.get("unlabeled_fields") or []) if isinstance(result, dict) else [])
        for field, score in (getattr(extraction, "field_scores", None) or {}).items():
            if field not in unlabeled:
                out[field] = float(getattr(score, "score", score)) >= good
    except Exception as exc:  # noqa: BLE001 - a scorer gap leaves that row's fields unscored, reported
        out["_error"] = False
        print(f"field truth {doc_type} {row.get('id')}: {type(exc).__name__}: {exc}")
    return out


def calibrate(items: list[dict], rows: dict[str, dict], handoff: dict[str, dict], *, good: float, precision: float) -> dict:
    per: dict[str, dict[str, list]] = collections.defaultdict(lambda: {"p": [], "y": [], "score": [], "verdict": []})
    fields: dict[tuple[str, str], dict[str, list]] = collections.defaultdict(lambda: {"p": [], "y": []})
    skipped = collections.Counter()
    for item in items:
        pred, score = item.get("pred") or {}, item.get("score") or {}
        p, s = pred.get("accept_probability"), score.get("extraction_score")
        doc_id = str(item.get("item_id"))
        if not item.get("ok") or not isinstance(p, (int, float)) or not isinstance(s, (int, float)):
            skipped["no_answer_or_score"] += 1
            continue
        cls = score.get("doc_type") or pred.get("doc_type")
        for key in (cls, "all"):
            per[key]["p"].append(float(p))
            per[key]["y"].append(float(s) >= good)
            per[key]["score"].append(float(s))
            per[key]["verdict"].append(pred.get("verdict"))
        truth = _field_truth(cls, rows[doc_id], (handoff.get(doc_id) or {}).get("fields") or {}, good) if doc_id in rows else {}
        for field, ok in truth.items():
            prob = (pred.get("field_support") or {}).get(field)
            if not field.startswith("_") and isinstance(prob, (int, float)):
                fields[(cls, field)]["p"].append(float(prob))
                fields[(cls, field)]["y"].append(ok)
    report: dict[str, Any] = {"good_threshold": good, "target_precision": precision, "skipped": dict(skipped), "classes": {}}
    for cls, d in sorted(per.items()):
        n = len(d["y"])
        median = sorted(d["score"])[n // 2]
        report["classes"][cls] = {
            "n": n, "good_rate": round(sum(d["y"]) / n, 4), "mean_extraction_score": round(sum(d["score"]) / n, 4),
            "accept_auroc": auroc(d["p"], d["y"]),
            # Within-class view: a class whose scores sit far below --good (correspondence free text)
            # still shows whether the gate ranks its better extractions above its worse ones.
            "median_score": round(median, 4),
            "accept_auroc_above_median": auroc(d["p"], [s > median for s in d["score"]]),
            "spearman_accept_vs_score": spearman(d["p"], d["score"]),
            "verdicts": dict(collections.Counter(d["verdict"])),
            "accept_verdict_precision": (round(sum(y for y, v in zip(d["y"], d["verdict"]) if v == "accept")
                                               / max(1, sum(v == "accept" for v in d["verdict"])), 4)),
            "cutoff": cutoff_for_precision(d["p"], d["y"], precision),
        }
    report["fields"] = {f"{cls}.{field}": {"n": len(d["y"]), "truth_rate": round(sum(d["y"]) / len(d["y"]), 4),
                                           "support_auroc": auroc(d["p"], d["y"])}
                        for (cls, field), d in sorted(fields.items())}
    return report


def cmd_calibrate(args: argparse.Namespace) -> int:
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    store = RunStore(run_dir(args.run))
    lock = store.read_lock() or {}
    if lock.get("task") != "extraction_gate":
        print(f"extraction_gate: {args.run} is not an extraction_gate run")
        return 1
    if (lock.get("job") or {}).get("mock", True):
        print(f"extraction_gate: {args.run} is a mock run; nothing to calibrate")
        return 1
    rows = {r["id"]: r for r in store.dataset_rows()}
    handoff = (lock.get("reviewer") or {}).get("handoff") or {}
    report = {"run_id": args.run, "question_set": (lock.get("reviewer") or {}).get("questions"),
              "questions_sha256": (lock.get("reviewer") or {}).get("questions_sha256"),
              **calibrate(store.load_items(), rows, handoff, good=args.good, precision=args.precision)}
    out = repo_root() / "reports" / "extraction-gate" / f"{args.run}.calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["classes"], indent=2, sort_keys=True))
    print(f"wrote {out.relative_to(repo_root())}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", default="train")
    parser.add_argument("--seed", type=int, default=42)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_in = sub.add_parser("inputs", help="write the baseline documents")
    p_in.add_argument("--dataset-run", action="append", required=True)
    p_ca = sub.add_parser("calibrate", help="score a finished gate run against the dojo")
    p_ca.add_argument("--run", required=True)
    p_ca.add_argument("--good", type=float, default=0.8, help="dojo score at or above which an extraction is good")
    p_ca.add_argument("--precision", type=float, default=0.9, help="target precision of the accepted set")
    args = parser.parse_args()
    return cmd_inputs(args) if args.cmd == "inputs" else cmd_calibrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
