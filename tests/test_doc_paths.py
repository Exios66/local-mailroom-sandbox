"""Relative markdown links keep pointing at the post-reorganization tree."""

from __future__ import annotations

import re
from pathlib import Path

from mailroom_sandbox.job.runbooks import catalog_path, generated_dir
from mailroom_sandbox.paths import repo_root

_LINK = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)]+)\)")
_IMAGE = re.compile(r"!\[(?:[^\]]*)\]\(([^)]+)\)")
_FENCE = re.compile(r"```.*?```", re.DOTALL)

_SKIP_PREFIXES = (
    "vendor/",
    "CHANGELOG.md",
    "docs/releases/",
    "governance/TASKS.md",
    "governance/archive/",
)

_SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def _iter_markdown() -> list[Path]:
    root = repo_root()
    files: list[Path] = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(_SKIP_PREFIXES) or "/." in f"/{rel}":
            continue
        if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        files.append(path)
    return files


def _targets(text: str) -> list[str]:
    stripped = _FENCE.sub("", text)
    found: list[str] = []
    for pattern in (_LINK, _IMAGE):
        for match in pattern.finditer(stripped):
            target = match.group(1).strip()
            if not target or target.startswith(_SKIP_SCHEMES) or target.startswith("#"):
                continue
            found.append(target.split("#", 1)[0].strip())
    return found


def test_relative_markdown_links_resolve():
    root = repo_root()
    missing: list[str] = []
    for path in _iter_markdown():
        for target in _targets(path.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                rel = path.relative_to(root).as_posix()
                missing.append(f"{rel} -> {target}")
    assert missing == [], "broken relative markdown links:\n" + "\n".join(missing)


def test_generated_runbook_catalog_links_resolve():
    catalog = catalog_path().resolve()
    link_re = re.compile(r"\[`config/runbooks/catalog.yaml`\]\(([^)]+)\)")
    broken: list[str] = []
    for path in generated_dir().rglob("*.md"):
        for match in link_re.finditer(path.read_text(encoding="utf-8")):
            target = (path.parent / match.group(1)).resolve()
            if target != catalog:
                rel = path.relative_to(repo_root()).as_posix()
                broken.append(f"{rel} -> {match.group(1)}")
    assert broken == [], "generated catalog links do not resolve:\n" + "\n".join(broken)
