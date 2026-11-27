#!/usr/bin/env python3
"""Write config/extraction/subclass_extraction_fields.json from the label registry.

``--check`` exits 1 when the committed file is stale. See ``mailroom_sandbox.subclass_fields``.
"""

from __future__ import annotations

import argparse
import json
import sys

from mailroom_sandbox import subclass_fields as sf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the committed file is stale")
    args = parser.parse_args(argv)
    registry = json.loads(sf.REGISTRY_PATH.read_text(encoding="utf-8"))
    text = sf.render(sf.build_field_lists(registry))
    current = sf.FIELDS_PATH.read_text(encoding="utf-8") if sf.FIELDS_PATH.exists() else None
    if args.check:
        if current != text:
            print(f"{sf.FIELDS_PATH} is stale: run python scripts/build_subclass_fields.py", file=sys.stderr)
            return 1
        print(f"{sf.FIELDS_PATH.name} is current")
        return 0
    sf.FIELDS_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {sf.FIELDS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
