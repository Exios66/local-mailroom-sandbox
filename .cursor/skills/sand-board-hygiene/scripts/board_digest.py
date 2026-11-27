#!/usr/bin/env python3
"""Digest non-terminal SAND rows from governance/TASKS.md (offline)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TASKS = ROOT / "governance" / "TASKS.md"

ROW_RE = re.compile(
    r"^\|\s*(SAND-\d+(?:-\d+)?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
NEXT_RE = re.compile(r"\*\*Next ID:\s*`?(SAND-\d{3})`?\*\*")
PR_OR_ISSUE_RE = re.compile(r"#\d+")
TERMINAL = frozenset({"done", "cancelled"})


def _status_token(cell: str) -> str:
    cell = cell.strip()
    m = re.search(r"\*\*([^*]+)\*\*", cell)
    raw = (m.group(1) if m else cell).strip().lower().replace(" ", "_")
    return raw


def parse_board(text: str) -> dict:
    next_m = NEXT_RE.search(text)
    next_id = next_m.group(1) if next_m else None
    rows: list[dict] = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        card_id, title, owner, status_cell, notes = m.groups()
        status = _status_token(status_cell)
        rows.append(
            {
                "id": card_id,
                "title": title.strip(),
                "owner": owner.strip(),
                "status": status,
                "status_cell": status_cell.strip(),
                "notes": notes.strip(),
                "has_pr_or_issue_ref": bool(PR_OR_ISSUE_RE.search(notes)),
                "notes_empty": notes.strip() in {"", "—", "-"},
            }
        )
    primary = []
    for row in rows:
        m = re.match(r"SAND-(\d{3})$", row["id"])
        if m:
            primary.append(int(m.group(1)))
    open_rows = [r for r in rows if r["status"] not in TERMINAL]
    by_lane: dict[str, list[dict]] = {}
    for row in open_rows:
        by_lane.setdefault(row["status"], []).append(row)

    stale_hints = []
    for row in open_rows:
        hints = []
        if row["notes_empty"]:
            hints.append("empty_notes")
        if row["status"] in {"in_progress", "review", "needs_attention"} and not row[
            "has_pr_or_issue_ref"
        ]:
            hints.append("missing_pr_or_issue_ref")
        if hints:
            stale_hints.append({"id": row["id"], "status": row["status"], "hints": hints})

    return {
        "tasks_path": str(TASKS),
        "next_id": next_id,
        "max_primary": max(primary) if primary else None,
        "row_count": len(rows),
        "open_count": len(open_rows),
        "by_lane": {k: [{"id": r["id"], "title": r["title"], "owner": r["owner"]} for r in v]
                    for k, v in sorted(by_lane.items())},
        "lane_counts": {k: len(v) for k, v in sorted(by_lane.items())},
        "stale_hints": stale_hints,
    }


def render_text(digest: dict) -> str:
    lines = [
        f"Board digest — {digest['tasks_path']}",
        f"Next ID: {digest['next_id']}  max primary: SAND-{digest['max_primary']:03d}"
        if digest["max_primary"] is not None
        else f"Next ID: {digest['next_id']}",
        f"Rows: {digest['row_count']}  open/non-terminal: {digest['open_count']}",
        "Lane counts: "
        + (
            ", ".join(f"{k}={v}" for k, v in digest["lane_counts"].items())
            or "(none)"
        ),
        "",
    ]
    for lane, cards in digest["by_lane"].items():
        lines.append(f"## {lane} ({len(cards)})")
        for card in cards:
            lines.append(f"- {card['id']}: {card['title']} [{card['owner']}]")
        lines.append("")
    if digest["stale_hints"]:
        lines.append("## stale hints")
        for hint in digest["stale_hints"]:
            lines.append(
                f"- {hint['id']} ({hint['status']}): {', '.join(hint['hints'])}"
            )
    else:
        lines.append("## stale hints")
        lines.append("- (none)")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        type=Path,
        default=TASKS,
        help="Path to TASKS.md (default: repo governance/TASKS.md)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)
    path = args.tasks
    if not path.is_file():
        print(f"error: missing {path}", file=sys.stderr)
        return 2
    digest = parse_board(path.read_text(encoding="utf-8"))
    digest["tasks_path"] = str(path)
    if args.json:
        json.dump(digest, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
