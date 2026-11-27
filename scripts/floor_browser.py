#!/usr/bin/env python3
"""Serve the floor viewer for browser debugging from committed run logs.

The default source is the bundled replay sample under
``data/fixtures/floor/replay``. Numbers in that sample are simulated.
``--replay-run`` plays a finished recorded run, including one produced
earlier by a billed job. This process never starts a model, Modal, or a
billed run.

    python scripts/floor_browser.py
    python scripts/floor_browser.py --dry-run
    python scripts/floor_browser.py --replay-run data/runtime/runs/my-run --replay-speed 20
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH_BASE = Path("data") / "runtime" / "floor-browser"
FIXTURE = Path("data") / "fixtures" / "floor" / "replay"


def _port(text: str) -> int:
    """Accept 0–65535. Zero asks the server for an ephemeral port."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if value < 0 or value > 65535:
        raise argparse.ArgumentTypeError("port must be 0-65535")
    return value


def _positive_float(text: str) -> float:
    """Accept a finite number greater than zero."""
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("expected a finite number greater than zero")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="floor-browser",
        description=(
            "Serve the pipeline floor viewer against the committed replay sample "
            "or a finished recorded run. Does not start billed work."
        ),
    )
    parser.add_argument("--base", default=None, help=f"scratch run store (default {SCRATCH_BASE})")
    parser.add_argument("--port", type=_port, default=None, help="loopback port (default 8769; 0 = ephemeral)")
    parser.add_argument("--interval", type=_positive_float, default=5.0, help="digest check interval in seconds")
    parser.add_argument("--replay-speed", type=_positive_float, default=None, help="timeline multiplier")
    parser.add_argument(
        "--replay-run",
        default=None,
        metavar="PATH",
        help="finished run directory to replay (instead of the committed sample)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan and do not bind a port")
    parser.add_argument("--list", action="store_true", help="print the committed fixture and scratch base")
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--real", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--submit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--initials", default=None, help=argparse.SUPPRESS)
    return parser


@dataclass(frozen=True)
class Plan:
    """One offline floor-browser invocation."""

    refused: str | None
    dry_run: bool
    list_only: bool
    source: str
    fixture: Path
    base: Path
    port: int
    interval: float
    replay: bool
    replay_run: str | None
    replay_speed: float | None
    debug_url: str | None
    fixture_ok: bool


def _floor_app():
    """Import the floor app from this checkout."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from mailroom_sandbox.tui import floor_app

    return floor_app


def _display(path: Path) -> str:
    """A repo-relative path when the target lives in this checkout."""
    resolved = path if path.is_absolute() else ROOT / path
    try:
        return str(resolved.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def build_plan(argv: list[str] | None = None) -> Plan:
    """Parse ``argv`` into an offline serve plan. Billed flags set ``refused``."""
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    floor_app = _floor_app()
    refused = None
    if args.live or args.real or args.submit or args.initials is not None:
        refused = (
            "floor-browser: refusing billed work. Record a run with "
            "`sandbox run preflight` and `sandbox run start --initials XX`, "
            "then pass --replay-run <run-dir>. This script only serves logs."
        )
    fixture = ROOT / FIXTURE
    base = Path(args.base).expanduser() if args.base else ROOT / SCRATCH_BASE
    port = floor_app.DEFAULT_PORT if args.port is None else args.port
    replay = args.replay_run is None
    debug_url = None
    if replay and port != 0:
        debug_url = floor_app.floor_url(port, floor_app.REPLAY_RUN_ID, debug=True)
    return Plan(
        refused=refused,
        dry_run=args.dry_run,
        list_only=args.list,
        source="committed replay fixture" if replay else "recorded run",
        fixture=fixture,
        base=base,
        port=port,
        interval=args.interval,
        replay=replay,
        replay_run=args.replay_run,
        replay_speed=args.replay_speed,
        debug_url=debug_url,
        fixture_ok=fixture.is_dir(),
    )


def format_plan(plan: Plan) -> str:
    """Stable text for ``--dry-run`` and the stderr banner."""
    speed = "default" if plan.replay_speed is None else f"{plan.replay_speed:g}"
    debug = plan.debug_url or "printed by the server (debug=1)"
    lines = [
        f"source: {plan.source}",
        f"fixture: {_display(plan.fixture)}",
        f"base: {_display(plan.base)}",
        f"port: {plan.port}",
        f"interval: {plan.interval:g}",
        f"replay: {'yes' if plan.replay else 'no'}",
        f"replay_run: {plan.replay_run or '-'}",
        f"replay_speed: {speed}",
        f"debug_url: {debug}",
        "spend: not started",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Print a plan, or serve the floor until interrupted. Never starts a billed run."""
    plan = build_plan(argv)
    if plan.refused:
        print(plan.refused, file=sys.stderr)
        return 2
    if plan.list_only:
        state = "present" if plan.fixture_ok else "missing"
        print(f"committed fixture ({state}): {_display(plan.fixture)}")
        print(f"scratch base: {_display(plan.base)}")
        print("recorded runs: pass --replay-run PATH (a finished run directory)")
        print("spend: not started")
        return 0
    if plan.replay and not plan.fixture_ok:
        print(f"floor-browser: committed fixture missing: {plan.fixture}", file=sys.stderr)
        return 1
    if plan.dry_run:
        print(format_plan(plan), end="")
        return 0
    plan.base.mkdir(parents=True, exist_ok=True)
    note = (
        "floor-browser: simulated sample is not model evidence"
        if plan.replay
        else "floor-browser: recorded replay is a viewing copy, not a new job"
    )
    print(format_plan(plan), end="", file=sys.stderr)
    print(note, file=sys.stderr)
    return _floor_app().serve_floor(
        base=plan.base,
        port=plan.port,
        interval=plan.interval,
        replay=plan.replay,
        replay_run=plan.replay_run,
        replay_speed=plan.replay_speed,
        debug=True,
    )


def _prefer_venv() -> None:
    """Re-exec through the checkout venv when this process is not already in it.

    ``.venv/bin/python`` is a symlink to the base interpreter. Resolving that
    link and executing the result drops ``pyvenv.cfg``, so packages installed
    only in the venv are missing. Compare ``sys.prefix`` with the venv
    directory and re-exec the unresolved venv path.
    """
    venv_dir = ROOT / ".venv"
    venv_py = venv_dir / "bin" / "python"
    if not venv_py.is_file():
        return
    try:
        if Path(sys.prefix).resolve() == venv_dir.resolve():
            return
    except OSError:
        return
    os.execv(venv_py, [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])  # nosec B606 - re-exec this script through the checkout venv, no shell


if __name__ == "__main__":
    _prefer_venv()
    raise SystemExit(main())
