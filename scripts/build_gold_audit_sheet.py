#!/usr/bin/env python3
"""Build or summarize an R03 gold-label audit sheet (evaluation runbook, Task 4; no model call).

Build: read one finished v0 run (``dataset.jsonl`` truth with the overlays, ``items.jsonl``
predictions), keep its v0-vs-gold disagreements and write a deterministic sample of them as a CSV
with empty ``verdict`` (model_wrong / gold_wrong / ambiguous) and ``note`` columns, plus a
``<sheet>.meta.json`` digest. Only dev and pool documents are audited: a run holding held-out or
calibration ids is refused. An existing sheet is never overwritten without ``--force``.

    python scripts/build_gold_audit_sheet.py --run rb1-r03-correspondence-v0-dev \\
        --lineage correspondence --n 100 --seed 20261118

Summarize: the gold-wrong rate per audited document and per row with two-sided Clopper-Pearson 95%
intervals, and the R03 gate (gold wrong on at most 15% of audited documents). Exit 0 pass,
1 fail, 3 incomplete (blank verdicts), 2 on an error.

    python scripts/build_gold_audit_sheet.py --summarize data/labels/review/r03-correspondence-audit.csv

Logic: ``mailroom_sandbox.gold_audit``. Procedure: ``data/labels/review/README.md`` (R03 gold audit).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mailroom_sandbox import gold_audit
from mailroom_sandbox.paths import repo_root


def _run_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_dir():
        return path
    from mailroom_sandbox.job.spec import run_dir

    return run_dir(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summarize", metavar="SHEET", help="summarize a filled sheet instead of building one")
    parser.add_argument("--threshold", type=float, default=gold_audit.GATE_MAX_GOLD_WRONG,
                        help="gate: highest gold-wrong share of audited documents (default 0.15)")
    parser.add_argument("--run", help="finished v0 run: a run id under data/runtime/runs or a run directory")
    parser.add_argument("--lineage", choices=sorted(gold_audit.LINEAGES))
    parser.add_argument("--n", type=int, default=100, help="disagreements to sample (default 100)")
    parser.add_argument("--seed", type=int, help="sample seed (required to build)")
    parser.add_argument("--per-doc", type=int, default=1,
                        help="most rows per document (default 1, so rows = audited documents; 0 = no cap)")
    parser.add_argument("--mismatch-below", type=float, default=1.0,
                        help="a field disagrees when its Dojo field score is below this (default 1.0)")
    parser.add_argument("--verdict-level", choices=("class", "subclass"), default="class",
                        help="read the iterate verdict per class (default) or per gold subclass")
    parser.add_argument("--split", default="config/splits/runbook-v1")
    parser.add_argument("--schemas", default="config/extraction/subclass_schemas-runbook-v1.json",
                        help="field registry graded on the run's revision (default: the frozen runbook-v1 one)")
    parser.add_argument("--out", help="sheet path (default data/labels/review/r03-<lineage>-audit.csv)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing sheet (loses its verdicts)")
    args = parser.parse_args(argv)
    root = repo_root()
    try:
        if args.summarize:
            result = gold_audit.summarize(Path(args.summarize), threshold=args.threshold)
            print(json.dumps(result, indent=2))
            return {"pass": 0, "fail": 1, "too_small": 1}.get(result["gate"], 3)
        if not (args.run and args.lineage and args.seed is not None):
            parser.error("building a sheet needs --run, --lineage and --seed")
        if args.n < 1:
            parser.error("--n must be >= 1")
        out = Path(args.out) if args.out else root / "data" / "labels" / "review" / f"r03-{args.lineage}-audit.csv"
        if out.exists() and not args.force:
            print(f"error: {out} exists (adjudicated verdicts would be lost); pass --force to rebuild",
                  file=sys.stderr)
            return 2
        result = gold_audit.build_sheet(
            _run_path(args.run), args.lineage, split_dir=root / args.split, schemas_path=root / args.schemas,
            n=args.n, seed=args.seed, per_doc=args.per_doc, mismatch_below=args.mismatch_below,
            verdict_level=args.verdict_level)
        gold_audit.write_sheet(result.rows, out)
        meta = {**result.digest, "sheet": str(out), "split": args.split, "schemas": args.schemas}
        out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(meta, indent=2, sort_keys=True))
        if result.digest.get("sampled", 0) < args.n:
            print(f"note: only {result.digest.get('sampled', 0)} disagreements available (asked {args.n})",
                  file=sys.stderr)
        return 0
    except gold_audit.AuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
