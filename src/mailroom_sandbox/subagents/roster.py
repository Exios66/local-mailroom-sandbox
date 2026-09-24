"""Load and query config/subagents/roster.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mailroom_sandbox.paths import repo_root


@dataclass(frozen=True)
class SubagentEntry:
    id: str
    title: str
    description: str
    tags: tuple[str, ...] = ()
    harnesses: tuple[str, ...] = ("cursor", "opencode")
    family_source: str | None = None
    cursor_invoke_hint: str | None = None
    opencode_mode: str | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def opencode_path(self, root: Path | None = None) -> Path:
        base = root or repo_root()
        return base / ".opencode" / "agents" / f"{self.id}.md"

    def cursor_path(self, root: Path | None = None) -> Path:
        base = root or repo_root()
        return base / ".cursor" / "agents" / f"{self.id}.md"


def roster_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "config" / "subagents" / "roster.yaml"


def load_roster(root: Path | None = None) -> list[SubagentEntry]:
    path = roster_path(root)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries: list[SubagentEntry] = []
    for row in data.get("subagents") or []:
        cursor = row.get("cursor") or {}
        opencode = row.get("opencode") or {}
        entries.append(
            SubagentEntry(
                id=row["id"],
                title=row.get("title") or row["id"],
                description=row.get("description") or "",
                tags=tuple(row.get("tags") or ()),
                harnesses=tuple(row.get("harnesses") or ("cursor", "opencode")),
                family_source=row.get("family_source"),
                cursor_invoke_hint=cursor.get("invoke_hint"),
                opencode_mode=opencode.get("mode"),
                raw=row,
            )
        )
    return entries


def get_subagent(subagent_id: str, root: Path | None = None) -> SubagentEntry | None:
    for entry in load_roster(root):
        if entry.id == subagent_id:
            return entry
    return None


def harness_config(harness: str, root: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load(roster_path(root).read_text(encoding="utf-8"))
    harnesses = data.get("harnesses") or {}
    if harness not in harnesses:
        raise KeyError(f"unknown harness {harness!r}; known: {sorted(harnesses)}")
    return harnesses[harness]
