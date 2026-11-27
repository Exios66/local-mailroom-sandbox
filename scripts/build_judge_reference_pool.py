#!/usr/bin/env python3
"""Write config/judge/reference-pool-runbook-v2.jsonl from the near-gold and interim labels.

``--check`` exits 1 when the committed pool is stale. See ``mailroom_sandbox.judge_references``.
"""

from __future__ import annotations

import argparse
import sys

from mailroom_sandbox import judge_references as jr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed pool is stale")
    args = parser.parse_args(argv)
    text = jr.render(jr.build_pool(*jr.read_sources()))
    current = jr.POOL_PATH.read_text(encoding="utf-8") if jr.POOL_PATH.exists() else None
    if args.check:
        if current != text:
            print(f"{jr.POOL_PATH} is stale: run python scripts/build_judge_reference_pool.py", file=sys.stderr)
            return 1
        print(f"{jr.POOL_PATH.name} is current")
        return 0
    jr.POOL_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {jr.POOL_PATH} ({text.count(chr(10))} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
