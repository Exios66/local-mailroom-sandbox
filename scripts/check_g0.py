#!/usr/bin/env python3
"""Evaluation runbook G0 checkpoint: run every Phase 0 gate and print one line each.

G0 closes only when all of these pass (``docs/superpowers/plans/2026-11-18-evaluation-runbook-plan.md``,
Task 5):

* R00: ``sandbox splits audit`` (the frozen split rebuilds from its seed, no leak).
* R00+: ``sandbox schemas build --check`` (the extraction registry matches the committed labels).
* R01: ``scripts/check_r01_smoke.py`` over each smoke config and its served-provider ledger
  (``data/runtime/rb1-r01/served-<stem>.jsonl``, written by the launched smoke run).
* R02: ``scripts/check_scorer_handcheck.py`` (a person confirmed every hand score).
* R03: ``scripts/build_gold_audit_sheet.py --summarize`` on each lineage's adjudicated sheet
  (``data/labels/review/r03-<lineage>-audit.csv``).

A gate whose evidence does not exist yet (no ledger, no sheet) is reported ``missing``, which
fails G0 like a failed gate. Offline: no network, no spend. Nothing is written unless
``--write-digest`` is given: it files the digest as ``rb1-g0.checkpoint-gate.json`` and ``.md``
under ``reports/campaigns/rb1/rb1-g0-checkpoint/`` and refreshes the campaign indexes.
Exit 0 when every gate passes, 1 otherwise.

    HF_HUB_OFFLINE=1 python scripts/check_g0.py [--write-digest]
"""
from __future__ import annotations

import argparse
import subprocess  # nosec B404 - runs this repository's own gate commands only
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = [sys.executable, "-m", "mailroom_sandbox.cli"]
R03_LINEAGES = ("sorter", "correspondence", "insurance", "corporate", "contracts", "merger")


def r01_pairs(root: Path = ROOT) -> list[tuple[Path, Path]]:
    """(config, ledger) for every committed R01 smoke config."""
    configs = sorted((root / "config/runs").glob("rb1-r01-smoke-*.yaml"))
    stem = len("rb1-r01-smoke-")
    return [(c, root / "data/runtime/rb1-r01" / f"served-{c.stem[stem:]}.jsonl") for c in configs]


def gates(root: Path = ROOT) -> list[tuple[str, list[str] | None, str]]:
    """(name, command or None when its evidence is missing, what is missing)."""
    py = [sys.executable]  # not -I: a worktree's gates must import that worktree's src via PYTHONPATH
    out: list[tuple[str, list[str] | None, str]] = [
        ("R00 split audit", [*SANDBOX, "splits", "audit"], ""),
        ("R00 schemas registry", [*SANDBOX, "schemas", "build", "--check"], ""),
    ]
    pairs = r01_pairs(root)
    if not pairs:
        out.append(("R01 smoke", None, "no config/runs/rb1-r01-smoke-*.yaml"))
    for config, ledger in pairs:
        name = f"R01 smoke {config.stem.removeprefix('rb1-r01-smoke-')}"
        if ledger.exists():
            out.append((name, [*py, str(root / "scripts/check_r01_smoke.py"), "--ledger", str(ledger),
                               "--config", str(config)], ""))
        else:
            out.append((name, None, f"ledger {ledger.relative_to(root)} (launch the smoke run)"))
    out.append(("R02 scorer hand-check", [sys.executable, str(root / "scripts/check_scorer_handcheck.py")], ""))
    for lineage in R03_LINEAGES:
        sheet = root / "data/labels/review" / f"r03-{lineage}-audit.csv"
        name = f"R03 gold audit {lineage}"
        if sheet.exists():
            out.append((name, [sys.executable, str(root / "scripts/build_gold_audit_sheet.py"),
                               "--summarize", str(sheet)], ""))
        else:
            out.append((name, None, f"sheet {sheet.relative_to(root)} (v0 pass, then adjudication)"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="print each failing gate's last output lines")
    parser.add_argument("--write-digest", action="store_true",
                        help="file the digest under reports/campaigns/rb1/rb1-g0-checkpoint/")
    args = parser.parse_args(argv)
    failed = 0
    rows: list[dict[str, object]] = []
    for name, cmd, missing in gates():
        if cmd is None:
            print(f"missing  {name}: {missing}")
            failed += 1
            rows.append({"gate": name, "status": "missing", "exit": None, "missing": missing})
            continue
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # nosec B603
        ok = proc.returncode == 0
        failed += not ok
        print(f"{'pass' if ok else 'FAIL'}     {name} (exit {proc.returncode})")
        rows.append({"gate": name, "status": "pass" if ok else "fail", "exit": proc.returncode})
        if not ok and args.verbose:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
            print("\n".join(f"           {line}" for line in tail))
    print(f"G0: {'passed' if not failed else f'not passed ({failed} gate(s) failing or missing)'}")
    if args.write_digest:
        for path in write_digest(rows, failed):
            print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0 if not failed else 1


def write_digest(rows: list[dict[str, object]], failed: int, root: Path | None = None) -> list[Path]:
    """Write ``rb1-g0.checkpoint-gate.{json,md}`` and refresh the rb1 indexes (index refresh is best-effort)."""
    import json

    from mailroom_sandbox import report_campaigns as rc

    exp = rc.experiment_paths("rb1-g0", root=root)
    exp.dir.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "sandbox.g0-digest/v1", "ok": not failed, "failing_or_missing": failed, "gates": rows}
    json_path = exp.file("checkpoint-gate", "json")
    json_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = [f"# G0 checkpoint digest: {'passed' if not failed else 'not passed'}", "",
          "Written by `python scripts/check_g0.py --write-digest`; rerun it to refresh.", "",
          "| gate | status | exit | missing evidence |", "| --- | --- | --- | --- |"]
    md += [f"| {r['gate']} | {r['status']} | {r['exit'] if r['exit'] is not None else '—'} | {r.get('missing') or ''} |"
           for r in rows]
    md_path = exp.file("checkpoint-gate", "md")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    try:
        rc.build_campaign("rb1", root=root)
    except Exception as exc:  # noqa: BLE001 - the digest is written; the index refresh is best-effort
        print(f"warning: campaign index not refreshed: {exc}", file=sys.stderr)
    return [json_path, md_path]


if __name__ == "__main__":
    raise SystemExit(main())
