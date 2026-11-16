#!/usr/bin/env python3
"""Paired control/treatment report for two finished ladder runs (offline re-score, no LLM).

Usage: python scripts/ladder_pair_report.py <control_run_id> <treatment_run_id> [--runs-dir DIR] [--json]
Scores every class on all labelled fields and, for corporate_record / correspondence, again
without the templated keywords / subject_matter labels (llm-dojo-scoring #164, #94).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("control")
    ap.add_argument("treatment")
    ap.add_argument("--runs-dir", type=Path, default=None, help="default: the sandbox run store")
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of markdown")
    args = ap.parse_args()

    from mailroom_sandbox import runtime
    from mailroom_sandbox.job.pair_report import paired_report, render_markdown
    from mailroom_sandbox.job.spec import run_dir

    runtime.activate("ollama", load_env_file=False)  # puts the vendored Dojo on the import path; no model call
    base = args.runs_dir
    control = base / args.control if base else run_dir(args.control)
    treatment = base / args.treatment if base else run_dir(args.treatment)
    report = paired_report(control, treatment)
    print(json.dumps(report, indent=2, default=str) if args.json else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
