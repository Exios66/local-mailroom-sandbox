#!/usr/bin/env python3
"""Write config/extraction/merger_tables.json from the Dojo merger definitions and the calibration labels.

``--check`` exits 1 when the committed file is stale. Without the cached dataset the committed
near-universal block is kept (and said so); every other table is always rebuilt. See
``mailroom_sandbox.merger_tables``.
"""

from __future__ import annotations

import argparse
import json
import sys

from mailroom_sandbox import merger_tables as mt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed file is stale")
    args = parser.parse_args(argv)
    current = mt.TABLES_PATH.read_text(encoding="utf-8") if mt.TABLES_PATH.exists() else None
    tables, rebuilt = mt.build(json.loads(current) if current else None)
    if not rebuilt:
        print("dataset not cached: the committed near-universal block is kept", file=sys.stderr)
    text = mt.render(tables)
    if args.check:
        if current != text:
            print(f"{mt.TABLES_PATH} is stale: run python scripts/build_merger_tables.py", file=sys.stderr)
            return 1
        print(f"{mt.TABLES_PATH.name} is current")
        return 0
    mt.TABLES_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {mt.TABLES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
