#!/usr/bin/env python3
"""Replay the R02 hand-check sheet through the run scorers and compare with the hand scores.

    HF_HUB_OFFLINE=1 python scripts/check_scorer_handcheck.py [--sheet-dir reports/campaigns/rb1/rb1-r02-scorer-handcheck]

Reads ``rb1-r02.sheet.csv``, ``rb1-r02.cases.jsonl`` and ``rb1-r02.provenance.json`` written by
``scripts/build_scorer_handcheck.py``, reloads the truth rows (HF cache at the recorded revision
with both overlays, or ``--rows FILE``) and refuses a document whose text or labels moved since
the sheet was built. Each case is scored by the code real runs use: the sorter row scorer, the
split's unit lookup, the Dojo extraction suite (per-field scores, CUAD presence F1, MAUD accuracy)
and the production gate's per-document outcome; the pooled rows by the Dojo sorter suite and the
gate's rate helpers. Prints a digest, then the statistics layer on the same documents
(``mailroom_sandbox.experiment_stats``) as a sanity read.

Exit codes: 0 the gate passes (every row scored by a person's initials, all match); 1 a filled
hand score disagrees with the scorer, or the sheet and the scorer list different checks; 2 rows
are blank; 3 every filled row matches but some are only ``agent-draft``; 4 the truth drifted;
5 all confirmed and matching, but the sheet holds fewer than ``--min-docs`` (20) documents.
Nothing is written unless ``--json OUT`` is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from mailroom_sandbox import scorer_handcheck as hc
from mailroom_sandbox.paths import repo_root

DEFAULT_DIR = Path("reports/campaigns/rb1/rb1-r02-scorer-handcheck")
DEFAULT_SPLIT = Path("config/splits/runbook-v1")
MAX_LISTED = 20


def _load_build_module():
    import importlib.util

    path = repo_root() / "scripts" / "build_scorer_handcheck.py"
    spec = importlib.util.spec_from_file_location("build_scorer_handcheck", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _short(value: Any, n: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= n else text[: n - 1] + "…"


def stats_digest(records: list[dict[str, Any]], rows: dict[str, dict[str, Any]],
                 per_doc: dict[str, dict[str, Any]], stats: dict[str, Any]) -> list[str]:
    """The statistics layer on the hand-check documents (a sanity read, not a gate)."""
    from mailroom_sandbox import experiment_stats as st

    truth = [str(rows[r["doc_id"]]["expected_doc_class"]) for r in records]
    pred = [str(r["prediction"]["doc_type"]) for r in records]
    correct = [t == p for t, p in zip(truth, pred)]
    unit_ok = [bool(per_doc[r["doc_id"]]["subclass_unit"]) for r in records]
    conf = [float(r["prediction"].get("confidence") or 0.0) for r in records]
    n, errors = len(records), sum(1 for c in correct if not c)
    cls = stats["_classification"]
    per_class = (cls.get("task") or {}).get("per_class") or {}
    confusion = Counter(zip(truth, pred))
    pairs = list(zip(conf, correct))
    mc = st.mcnemar(correct, unit_ok)
    doc_scores = [per_doc[r["doc_id"]]["doc_score"] for r in records]
    finite = [float(s) for s in doc_scores if isinstance(s, (int, float))]
    diff, perm_p = st.paired_permutation([1.0] * len(finite), finite, n_perm=2000, seed=0) if finite else (None, None)
    lines = [
        f"n {n}  class accuracy {cls.get('accuracy')}  errors {errors}  "
        f"Clopper-Pearson 95% upper on class error {st.clopper_pearson_upper(errors, n)}",
        f"macro-F1: Dojo sorter suite {cls.get('f1_macro')}  experiment_stats.macro_f1 "
        f"{round(st.macro_f1(truth, pred), 4)}",
        "per-class F1 (Dojo): " + ", ".join(f"{c} {v.get('f1')}" for c, v in sorted(per_class.items())),
        f"unit accuracy {stats['stat:unit_accuracy']}",
        f"cost-weighted error, unit costs (no committed cost matrix) {st.cost_weighted_error(confusion, {})}",
        f"Brier {st.brier_score(pairs)} (null floor {st.brier_null_floor(correct)})  "
        f"ECE {st.expected_calibration_error(pairs)} (null floor {st.ece_null_floor(conf, n_sim=500, seed=0)})  "
        f"AUROC {st.auroc(conf, correct)}",
        f"McNemar class-correct vs unit-correct (sanity) b={mc.b} c={mc.c} p={round(mc.p_value, 4)}  "
        f"sign-flip permutation doc score vs 1.0: mean diff {None if diff is None else round(diff, 4)} p={perm_p}",
        f"Holm over those two: {({k: round(v, 4) for k, v in st.holm({'mcnemar': mc.p_value, 'perm': perm_p or 1.0}).items()})}",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet-dir", type=Path, default=None)
    ap.add_argument("--split-dir", type=Path, default=None)
    ap.add_argument("--rows", type=Path, default=None, help="prepared dev rows (JSONL) instead of the HF cache")
    ap.add_argument("--json", type=Path, default=None, help="write every row with its scorer value here")
    ap.add_argument("--min-docs", type=int, default=20, help="documents the gate needs (R02: 20)")
    args = ap.parse_args(argv)
    root = repo_root()
    sheet_dir = args.sheet_dir or root / DEFAULT_DIR
    split_dir = args.split_dir or root / DEFAULT_SPLIT

    from mailroom_sandbox.experiment_splits import load_unit_table
    from mailroom_sandbox.job.gate import load_bars

    sheet = hc.read_sheet(sheet_dir / hc.SHEET_FILE)
    records = hc.read_jsonl(sheet_dir / hc.CASES_FILE)
    prov = json.loads((sheet_dir / hc.PROVENANCE_FILE).read_text(encoding="utf-8"))
    truth_rows, _ = _load_build_module().load_truth(split_dir, args.rows)
    rows = {str(r["id"]): r for r in truth_rows}

    drift = []
    for rec in records:
        row = rows.get(rec["doc_id"])
        if row is None:
            drift.append(f"{rec['doc_id']}: not in the dev truth rows")
        elif row.get("content_sha256") != rec["content_sha256"]:
            drift.append(f"{rec['doc_id']}: document text changed (content_sha256)")
        elif hc.canonical_sha(hc.expected_fields(row)) != rec["expected_fields_sha256"]:
            drift.append(f"{rec['doc_id']}: truth labels changed since the sheet was built")
    if drift:
        print("TRUTH DRIFT: rebuild the sheet (and re-score it) before checking", file=sys.stderr)
        for line in drift[:MAX_LISTED]:
            print("  " + line, file=sys.stderr)
        return 4

    table = load_unit_table(split_dir)
    bars = load_bars()
    per_doc = {rec["doc_id"]: hc.score_case(rec, rows[rec["doc_id"]], table, bars) for rec in records}
    values: dict[tuple[str, str], Any] = {}
    for doc_id, scored in per_doc.items():
        for check, value in scored.items():
            if not check.startswith("_"):
                values[(doc_id, check)] = value
    stats = hc.stat_values(records, rows, per_doc, bars)
    for check in hc.STAT_CHECKS:
        values[("*", check)] = stats[check]
    cmp = hc.compare(sheet, values)

    labels = prov.get("labels") or {}
    print(f"R02 hand-check  documents {len(records)}  rows {len(sheet)}  "
          f"labels named {str(labels.get('runbook_named_commit'))[:8]} (checkout {str(labels.get('checkout_head'))[:8]})  "
          f"Dojo pin {str((prov.get('scorer') or {}).get('dojo_vendor_pin'))[:12]}  "
          f"dataset {str((prov.get('dataset') or {}).get('revision'))[:12]}")
    filled = len(sheet) - len(cmp.blank)
    print(f"filled {filled}  blank {len(cmp.blank)}  agent-draft {len(cmp.draft)}  person-confirmed {len(cmp.confirmed)}  "
          f"matches {filled - len(cmp.mismatched)}  mismatches {len(cmp.mismatched)}  "
          f"unscored rows {len(cmp.missing_checks)}  unlisted scorer checks {len(cmp.unlisted)}")
    by_check = Counter(r["check"].split(":", 1)[0] for r in cmp.mismatched)
    if cmp.mismatched:
        print("mismatches by check: " + ", ".join(f"{k} {v}" for k, v in sorted(by_check.items())))
        for r in cmp.mismatched[:MAX_LISTED]:
            print(f"  {r['row_id']} {r['doc_id']} {r['check']:<28} {r['perturbation']:<18} "
                  f"hand {r['hand_score']!r} ({r['hand_scored_by']})  scorer {_short(r['scorer_value'], 30)}")
    for doc_id, check in cmp.unlisted[:MAX_LISTED]:
        print(f"  unlisted: {doc_id} {check} = {_short(values[(doc_id, check)], 30)}")
    for row_id in cmp.missing_checks[:MAX_LISTED]:
        print(f"  unscored: {row_id}")
    if cmp.blank:
        print("blank rows (need a person): " + ", ".join(cmp.blank[:MAX_LISTED]) + (" …" if len(cmp.blank) > MAX_LISTED else ""))
    print("statistics layer on these documents (sanity, not the gate):")
    for line in stats_digest(records, rows, per_doc, stats):
        print("  " + line)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"rows": cmp.rows, "unlisted": cmp.unlisted, "exit_code": cmp.exit_code},
                                        indent=1, default=str) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    verdict = {
        0: "R02 GATE PASSES: every row scored by a person and reproduced by the scorers",
        1: "R02 gate NOT passed: scorer and hand scores disagree (or the check lists differ)",
        2: "R02 gate NOT passed: blank hand scores remain",
        3: "R02 gate NOT passed: hand scores match but are agent-draft; a person must confirm each row",
    }[cmp.exit_code]
    code = cmp.exit_code
    if code == 0 and len(records) < args.min_docs:
        verdict, code = (f"R02 gate NOT passed: the sheet holds {len(records)} documents, the gate needs "
                         f"{args.min_docs}"), 5
    print(verdict)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
