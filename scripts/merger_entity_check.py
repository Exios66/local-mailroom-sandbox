#!/usr/bin/env python3
"""Offline merger entity check on a finished pipeline run (no model call, the run is only read).

Usage: python scripts/merger_entity_check.py --run <run_id|run dir> --labels <jsonl> [<jsonl> ...]
       [--baseline <run_id|run dir>] [--out <json>]

Prints a digest: per-field accuracy of the 16 merger entity fields and the consideration, scored
by the suite scorer against interim, near-gold or gold labels, next to MAUD accuracy. It is never
the headline score; near-gold numbers stay unverified until a spot check is recorded
(scripts/merger_spot_check.py). Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mailroom_sandbox.job import merger_entities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="run id (under the runs root) or a run directory")
    parser.add_argument("--labels", required=True, nargs="+", type=Path, help="merger label JSONL file(s)")
    parser.add_argument("--baseline", help="a second finished run to pair with (deltas over shared documents)")
    parser.add_argument("--out", type=Path, help="where to write the full JSON result "
                                                 "(default: data/runtime/entity_checks/<run_id>.merger_entities.json)")
    args = parser.parse_args(argv)
    try:
        from mailroom_sandbox import rescore

        source = rescore.locate(args.run).path
        result = merger_entities.check(source, args.labels, baseline=args.baseline)
        out = merger_entities.write_check(result, args.out or merger_entities.default_output(result["run_id"]),
                                          source=source)
    except (merger_entities.EntityCheckError, RuntimeError) as exc:
        print(f"entity check failed: {exc}", file=sys.stderr)
        return 2
    print(merger_entities.digest(result, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
