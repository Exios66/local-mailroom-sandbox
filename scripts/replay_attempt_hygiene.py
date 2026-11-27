#!/usr/bin/env python3
"""Offline replay of Phase 5 part 1 on a finished pipeline run (no model call, the run is only read).

Usage: python scripts/replay_attempt_hygiene.py --run <run_id|run dir> [--out <json>]

Prints a digest: A (``confidence.keep_best_attempt``) latest versus selected quality per class, and
B (``job.evidence_check``) quality, dropped items and CUAD false/missed clauses before and after,
plus the design's adoption bars. The numbers are an offline estimate, never a model result.
Design: docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mailroom_sandbox.job import attempt_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="run id (under the runs root) or a run directory")
    parser.add_argument("--out", type=Path, help="where to write the full JSON result "
                                                 "(default: data/runtime/replays/<run_id>.attempt_replay.json)")
    args = parser.parse_args(argv)
    try:
        from mailroom_sandbox import rescore

        source = rescore.locate(args.run).path
        result = attempt_replay.replay(source)
        out = attempt_replay.write_replay(result, args.out or attempt_replay.default_output(result["run_id"]),
                                          source=source)
    except (attempt_replay.ReplayError, RuntimeError) as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 2
    print(attempt_replay.digest(result, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
