#!/usr/bin/env python3
"""Regenerate harness stubs from config/subagents/roster.yaml."""

from __future__ import annotations

import argparse
import sys

from mailroom_sandbox.subagents import sync_harness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", default="cursor", choices=("cursor",))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = sync_harness(args.harness, dry_run=args.dry_run)
    for path in result.written:
        print(path)
    if result.skipped:
        print("skipped:", ", ".join(result.skipped), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
