"""Render harness-specific agent stubs from the central roster."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.subagents.parse_opencode import parse_opencode_markdown
from mailroom_sandbox.subagents.roster import SubagentEntry, harness_config, load_roster


@dataclass
class SyncResult:
    written: list[Path]
    skipped: list[str]


def _cursor_description(entry: SubagentEntry, doc_description: str) -> str:
    parts: list[str] = []
    if entry.cursor_invoke_hint:
        parts.append(entry.cursor_invoke_hint.strip())
    if doc_description and doc_description not in (parts[0] if parts else ""):
        # Keep Cursor description within reasonable size; prefer roster hint.
        if not parts:
            flat = " ".join(doc_description.split())
            if len(flat) > 1200:
                flat = flat[:1197] + "..."
            parts.append(flat)
    if not parts:
        parts.append(f"Subagent {entry.title}.")
    return " ".join(parts)


def render_cursor_agent(entry: SubagentEntry, root: Path | None = None) -> str:
    base = root or repo_root()
    src = entry.opencode_path(base)
    text = src.read_text(encoding="utf-8")
    doc = parse_opencode_markdown(text)
    description = _cursor_description(entry, doc.description)
    header = {
        "name": entry.id,
        "description": description,
    }
    yaml_block = yaml.safe_dump(header, sort_keys=False, allow_unicode=True).strip()
    harness_note = (
        f"> **Harness note:** Canonical OpenCode prompt lives at "
        f"`.opencode/agents/{entry.id}.md`. Edit there, then run "
        f"`sandbox subagents sync --harness cursor`.\n\n"
    )
    return f"---\n{yaml_block}\n---\n\n{harness_note}{doc.body}"


def sync_harness(harness: str, *, root: Path | None = None, dry_run: bool = False) -> SyncResult:
    base = root or repo_root()
    cfg = harness_config(harness, base)
    agents_dir = base / cfg["agents_dir"]
    written: list[Path] = []
    skipped: list[str] = []

    if harness != "cursor":
        raise NotImplementedError(f"sync for harness {harness!r} is not implemented yet")

    agents_dir.mkdir(parents=True, exist_ok=True)
    for entry in load_roster(base):
        if "cursor" not in entry.harnesses:
            skipped.append(entry.id)
            continue
        if not entry.opencode_path(base).is_file():
            skipped.append(entry.id)
            continue
        content = render_cursor_agent(entry, base)
        dest = entry.cursor_path(base)
        if dry_run:
            written.append(dest)
            continue
        dest.write_text(content, encoding="utf-8")
        written.append(dest)
    return SyncResult(written=written, skipped=skipped)
