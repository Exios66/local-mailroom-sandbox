#!/usr/bin/env python3
"""Render Modal specialist performance SVGs into reports/dashboard/figures/modal-performance/."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "reports" / "dashboard"
sys.path.insert(0, str(ROOT / "scripts" / "sand032"))
sys.path.insert(0, str(DASH))

import viz  # noqa: E402
import modal_performance as mp  # noqa: E402

OUT = DASH / "figures" / "modal-performance"
DATA = DASH / "hub_data.json"
DOC = DASH / "MODAL-PERFORMANCE-VISUALS.md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if outputs are stale")
    args = ap.parse_args()
    D = json.loads(DATA.read_text())
    figs = mp.render(D, viz)
    stale = []
    OUT.mkdir(parents=True, exist_ok=True)
    for rel, body in figs.items():
        dest = DASH / rel
        if not dest.is_file() or dest.read_text() != body:
            stale.append(rel)
            if not args.check:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(body)
    md = mp.report_md(sorted(figs))
    if not DOC.is_file() or DOC.read_text() != md:
        stale.append(str(DOC.relative_to(DASH)))
        if not args.check:
            DOC.write_text(md)
    for s in stale:
        print(("stale: " if args.check else "wrote: ") + s)
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
