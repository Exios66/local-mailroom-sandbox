#!/usr/bin/env python3
"""Check campaign hotfix fingerprints and installation without models, network or spend."""
from __future__ import annotations

import argparse
import json


def check(*, require_watcher: bool = False) -> dict:
    from mailroom_sandbox import scoring_hotfixes, vendor_hotfixes
    from mailroom_sandbox.job.preflight import _hotfix_check, _scoring_hotfix_check

    checks = [_hotfix_check(), _scoring_hotfix_check()]
    pipeline = vendor_hotfixes.apply_hotfixes()
    if require_watcher and pipeline.get("HF-005") != "applied":
        checks.append({"name": "watcher_hotfix", "ok": False,
                       "detail": "HF-005 must be applied for watcher execution; install the observability extra"})
    return {"schema": "sandbox.hotfix-check/v1", "ok": all(c["ok"] for c in checks),
            "checks": checks, "pipeline": pipeline, "scoring": scoring_hotfixes.status(refresh=True),
            "identity": {"vendor_hotfixes": vendor_hotfixes.describe(),
                         "scoring_hotfixes": scoring_hotfixes.describe()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-watcher", action="store_true")
    args = parser.parse_args(argv)
    report = check(require_watcher=args.require_watcher)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for c in report["checks"]:
            print(f"{'PASS' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
