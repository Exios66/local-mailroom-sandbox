"""Project Cursor skills are present and discoverable."""

from __future__ import annotations

import re

from mailroom_sandbox.paths import repo_root

REQUIRED = (
    "sandbox-tool-router",
    "docs-audit-tool-router",
    "sand-board-lifecycle",
    "sand-board-hygiene",
    "langfuse",
    "braintrust",
    "apache-phoenix",
    "ollama",
    "openrouter",
    "modal",
    "huggingface",
    "near-gold-labels",
)

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def test_cursor_skills_exist_with_frontmatter():
    root = repo_root() / ".cursor" / "skills"
    assert root.is_dir()
    for name in REQUIRED:
        path = root / name / "SKILL.md"
        assert path.is_file(), f"missing skill {path}"
        text = path.read_text(encoding="utf-8")
        match = _FRONTMATTER.match(text)
        assert match, f"{path} missing YAML frontmatter"
        meta = match.group(1)
        assert f"name: {name}" in meta
        assert "description:" in meta
        assert len(meta.strip()) > 40


def test_sand_board_hygiene_digest_script():
    """Offline digest must parse the live board and stay import-free of network."""
    import json
    import subprocess
    import sys

    script = repo_root() / ".cursor" / "skills" / "sand-board-hygiene" / "scripts" / "board_digest.py"
    assert script.is_file()
    proc = subprocess.run(
        [sys.executable, str(script), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["next_id"].startswith("SAND-")
    assert payload["open_count"] >= 1
    assert "by_lane" in payload


def test_near_gold_labels_skill_is_one_source_with_live_commands():
    """The Claude Code wrapper points at the canonical skill; every script the skill names exists."""
    root = repo_root()
    wrapper = (root / ".claude" / "skills" / "near-gold-labels" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: near-gold-labels" in wrapper
    assert ".cursor/skills/near-gold-labels/SKILL.md" in wrapper
    skill = (root / ".cursor" / "skills" / "near-gold-labels" / "SKILL.md").read_text(encoding="utf-8")
    for rel in sorted(set(re.findall(r"(?:scripts|reports/datasets/[\w.-]+)/[\w.-]+\.py", skill))):
        assert (root / rel).is_file(), f"skill names missing script {rel}"
    for doc in ("docs/gold-labels/NEAR_GOLD_PLAYBOOK.md", "docs/gold-labels/PASS_BRIEF_TEMPLATE.md"):
        assert doc in skill and (root / doc).is_file()
