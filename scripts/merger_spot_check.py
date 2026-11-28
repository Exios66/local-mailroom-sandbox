#!/usr/bin/env python3
"""Human spot check of near-gold merger labels: draw a review sheet, then record the agreement.

Usage: python scripts/merger_spot_check.py --labels <jsonl> --seed <int> [--n 5] [--out-dir <dir>]
       python scripts/merger_spot_check.py --labels <jsonl> --record <sheet.csv>

The first form writes a CSV (default: data/runtime/merger_spot_check/) holding every near-gold field
of n seeded documents with its value and evidence; a person marks ``correct`` y or n. The second
records the agreement rate in the label directory's MANIFEST.json (``spot_check``). Under 0.90 it sets
``cite_blocked``: the entity check then says not to cite the near-gold numbers. Recording changes the
MANIFEST, so its digest (the near-gold fingerprint) changes too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mailroom_sandbox.job import merger_entities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", required=True, type=Path, help="the near-gold merger label JSONL file")
    parser.add_argument("--n", type=int, default=5, help="documents to sample (default 5)")
    parser.add_argument("--seed", type=int, help="sample seed (required to draw a sheet)")
    parser.add_argument("--out-dir", type=Path, help="where to write the sheet")
    parser.add_argument("--record", type=Path, help="a marked sheet whose agreement to record")
    args = parser.parse_args(argv)
    try:
        if args.record is not None:
            entry = merger_entities.record_spot_check(args.record, args.labels)
            print(json.dumps(entry, indent=2, sort_keys=True))
            if entry["cite_blocked"]:
                print(f"agreement under {merger_entities.CITE_FLOOR}: do not cite near-gold numbers", file=sys.stderr)
            return 0
        if args.seed is None:
            parser.error("--seed is required to draw a sheet")
        sheet = merger_entities.spot_sample(args.labels, n=args.n, seed=args.seed, out_dir=args.out_dir)
    except merger_entities.EntityCheckError as exc:
        print(f"spot check failed: {exc}", file=sys.stderr)
        return 2
    print(f"review sheet: {sheet} (mark the correct column y or n, then --record it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
