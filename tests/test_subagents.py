"""Central subagent roster + harness sync (network-free)."""

from __future__ import annotations

from mailroom_sandbox.subagents import load_roster, sync_harness
from mailroom_sandbox.subagents.parse_opencode import parse_opencode_markdown
from mailroom_sandbox.subagents.roster import get_subagent


def test_roster_entries_have_opencode_prompts():
    for entry in load_roster():
        path = entry.opencode_path()
        assert path.is_file(), f"missing OpenCode prompt for {entry.id}: {path}"
        doc = parse_opencode_markdown(path.read_text(encoding="utf-8"))
        assert doc.description or entry.cursor_invoke_hint


def test_meta_subagents_present():
    assert get_subagent("harness-doctor") is not None
    assert get_subagent("adversarial-reviewer") is not None


def test_sync_cursor_writes_agents(tmp_path):
    # Copy minimal tree: roster + one opencode agent
    (tmp_path / "config" / "subagents").mkdir(parents=True)
    import shutil

    from mailroom_sandbox.paths import repo_root

    shutil.copy(repo_root() / "config" / "subagents" / "roster.yaml", tmp_path / "config" / "subagents" / "roster.yaml")
    for entry in load_roster():
        dest_dir = tmp_path / ".opencode" / "agents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(entry.opencode_path(), dest_dir / f"{entry.id}.md")

    result = sync_harness("cursor", root=tmp_path)
    assert result.written
    sample = get_subagent("harness-doctor")
    assert sample is not None
    cursor_file = sample.cursor_path(tmp_path)
    assert cursor_file.is_file()
    text = cursor_file.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: harness-doctor" in text
    assert "Harness Doctor" in text
