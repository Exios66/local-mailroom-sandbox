#!/usr/bin/env python3
"""api-evals CLI — run OpenRouter API eval comparisons.

Comparable to the org-owned eval-environment's ``scripts/run_evals.py`` but
coded for OpenRouter and scoped to this sandbox repo: every task pins a
run-spec YAML under ``api-evals/config/runs/`` that is byte-comparable (same
strata draw, seed, revision, prompt stem) to the sandbox Modal specialist runs.

Usage
-----
    python api-evals/run_api_evals.py list
    python api-evals/run_api_evals.py run   api-contracts-20
    python api-evals/run_api_evals.py run-all --prices 0.03 0.13
    python api-evals/run_api_evals.py report --from-log

``--api-key`` overrides the .env key for one invocation (never logged).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from api_evals import invoke  # noqa: E402
from api_evals.cost import resolve_prices  # noqa: E402
from api_evals.registry import registered, task_by_run_id, tasks  # noqa: E402
from api_evals import report as report_mod  # noqa: E402


def _load_env() -> None:
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / ".env", root / "config" / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def cmd_list(_args: argparse.Namespace) -> int:
    for t in tasks():
        print(f"{t.run_id:32s} {t.task:26s} n={t.n:4d} model={t.model} prompt={t.prompt_stem}")
    return 0


def _resolve_prices(args: argparse.Namespace):
    if args.prices and len(args.prices) == 2:
        return float(args.prices[0]), float(args.prices[1])
    return resolve_prices()


def cmd_run(args: argparse.Namespace) -> int:
    task = task_by_run_id(args.run_id)
    prices = _resolve_prices(args)
    result = invoke.run_task(
        task.yaml_path,
        api_key=args.api_key,
        prices=prices,
        mock=args.mock,
        dry_run=args.dry_run,
        force=args.force,
    )
    if result.get("dry_run"):
        print(json.dumps(
            {
                "run_id": result.get("run_id"),
                "task": result.get("task"),
                "profile": result.get("profile"),
                "model": result.get("model"),
                "n": result.get("n"),
                "dry_run": True,
            },
            indent=2,
        ))
        return 0
    print(json.dumps(
        {
            "run_id": result["run_id"],
            "task": result["task"],
            "n": result["n"],
            "model": result["model"],
            "cost": result["cost"],
            "scores": result.get("scores"),
            "wall_seconds": result.get("wall_seconds"),
            "spec_hash": result.get("spec_hash"),
            "dataset_fingerprint": result.get("dataset_fingerprint"),
            "dry_run": result.get("dry_run", False),
        },
        indent=2,
    ))
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    prices = _resolve_prices(args)
    results = []
    for task in tasks():
        print(f"[api-evals] running {task.run_id} (n={task.n}, model={task.model}) ...", file=sys.stderr)
        result = invoke.run_task(
            task.yaml_path,
            api_key=args.api_key,
            prices=prices,
            mock=args.mock,
            dry_run=args.dry_run,
            force=args.force,
        )
        results.append(result)
        cost = result.get("cost") or {}
        print(
            f"[api-evals] {task.run_id}: total=${cost.get('cost_usd')} "
            f"$/doc={cost.get('cost_per_document')} tokens={cost.get('total_tokens')}",
            file=sys.stderr,
        )
    report = report_mod.build_report(results, model="qwen/qwen3.7-flash", prices=prices)
    paths = report_mod.write_report(report, model=report["model"])
    print(report_mod.render_console(report))
    print(f"[api-evals] report written: {paths['markdown']}", file=sys.stderr)
    print(f"[api-evals] report json:    {paths['json']}", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Rebuild a report from the experiment log (no new API spend)."""
    from mailroom_sandbox.eval import experiment_log

    records = experiment_log.load()
    wanted_run_ids = {t.run_id for t in tasks()}
    results = []
    for rec in records:
        run_id = rec.get("run_id") or ""
        name = rec.get("experiment_name") or ""
        # whole-run records carry the run_id in the experiment_name suffix.
        matched = next((rid for rid in wanted_run_ids if rid in run_id or run_id in rid or f"_{rid}" in name or rid in name), None)
        if not matched:
            continue
        results.append(
            {
                "run_id": matched,
                "task": rec.get("task") or "",
                "n": int(rec.get("n") or 0),
                "model": rec.get("model") or "",
                "scores": rec.get("scores") or {},
                "wall_seconds": rec.get("wall_seconds"),
                "spec_hash": rec.get("spec_hash") or "",
                "dataset_fingerprint": rec.get("dataset_fingerprint") or "",
                "cost": {
                    "n_ok": int(rec.get("n") or 0),
                    "prompt_tokens": rec.get("prompt_tokens"),
                    "completion_tokens": rec.get("completion_tokens"),
                    "total_tokens": (rec.get("prompt_tokens") or 0) + (rec.get("completion_tokens") or 0),
                    "tokens_per_document": None,
                    "cost_usd": rec.get("estimated_cost_usd"),
                    "cost_per_document": rec.get("cost_per_document"),
                    "honest_gaps": [],
                },
            }
        )
    if not results:
        print("no api-evals records found in reports/experiment_log.jsonl — run `run`/`run-all` first",
              file=sys.stderr)
        return 1
    prices = _resolve_prices(args)
    report = report_mod.build_report(results, model="qwen/qwen3.7-flash", prices=prices)
    paths = report_mod.write_report(report, model=report["model"])
    print(report_mod.render_console(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="api-evals: OpenRouter API cost comparisons")
    # Global flags accepted BEFORE the subcommand. Subparser parents reuse the
    # same dests; use argparse.SUPPRESS defaults there so an absent flag does
    # NOT clobber a value already set globally (e.g. `--dry-run run X` stays a
    # dry run — a live double-run would be an unplanned API spend).
    parser.add_argument("--api-key", default=None, help="OpenRouter key (default: .env OPENROUTER_API_KEY)")
    parser.add_argument("--mock", action="store_true", help="dry deterministic (no API spend)")
    parser.add_argument("--dry-run", action="store_true", help="preflight only")
    parser.add_argument("--force", action="store_true", help="force re-lock run specs")
    parser.add_argument("--prices", nargs=2, type=float, metavar=("IN", "OUT"),
                        help="per-1M USD prices override (default: live OpenRouter /models)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-key", default=argparse.SUPPRESS)
    common.add_argument("--mock", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--force", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--prices", nargs=2, type=float, metavar=("IN", "OUT"), default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", parents=[common], help="list registered api-evals tasks")
    p_list.set_defaults(fn=cmd_list)

    p_run = sub.add_parser("run", parents=[common], help="run one task (live OpenRouter)")
    p_run.add_argument("run_id")
    p_run.set_defaults(fn=cmd_run)

    p_all = sub.add_parser("run-all", parents=[common], help="run every registered task")
    p_all.set_defaults(fn=cmd_run_all)

    p_rep = sub.add_parser("report", parents=[common], help="rebuild report from the experiment log")
    p_rep.set_defaults(fn=cmd_report)

    args = parser.parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"error: {exc}", file=sys.stderr)
        if os.environ.get("API_EVALS_DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
