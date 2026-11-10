"""Read-only sync previews, scope defaults, and content-based drift detection."""
import shutil
from pathlib import Path

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.subagents import doctor, load_roster
from mailroom_sandbox.subagents.sync import sync_harness


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    for rel in ('config/subagents/family-roster.yaml', 'config/subagents/roster.yaml',
                'config/subagents/AGENT_FRAMEWORK.md'):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(repo_root() / rel, dest)
    for entry in load_roster():
        dest = entry.opencode_path(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(entry.opencode_path(), dest)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(doctor.shutil, 'which', lambda name: None)
    return root


def test_previews_and_checks_do_not_create_destinations(checkout):
    home = Path.home()
    before = sorted(str(p) for p in checkout.rglob('*'))
    for flag in ({'dry_run': True}, {'check': True}):
        blocks = sync_harness('all', root=checkout, **flag)
        assert blocks[-1].written
        assert not (home / '.config').exists()
        assert before == sorted(str(p) for p in checkout.rglob('*'))


def test_project_default_and_check_status_do_not_touch_global(checkout, capsys):
    assert cli.main(['subagents', 'sync', '--root', str(checkout)]) == 0
    capsys.readouterr()
    assert not (Path.home() / '.config').exists()
    assert cli.main(['subagents', 'sync', '--root', str(checkout), '--check']) == 0
    entry = load_roster(checkout)[0]
    path = entry.cursor_path(checkout)
    path.write_text(path.read_text() + '\nstale\n')
    before = path.read_bytes()
    assert cli.main(['subagents', 'sync', '--root', str(checkout), '--check']) == 1
    assert path.read_bytes() == before


def test_doctor_detects_content_and_framework_drift_with_markers_present(checkout):
    sync_harness('project', root=checkout)
    entry = load_roster(checkout)[0]
    path = entry.cursor_path(checkout)
    path.write_text(path.read_text() + '\nstale body\n')
    framework = checkout / 'config/subagents/AGENT_FRAMEWORK.md'
    framework.write_text(framework.read_text().replace('Startup ritual', 'Updated startup ritual'))
    report = doctor.run_doctor(root=checkout, include_global=False)
    codes = {f.code for f in report.findings}
    assert 'cursor.content_drift' in codes and 'agent.framework_drift' in codes
    assert 'cursor.stub_stale' not in codes


def test_framework_refresh_preserves_persona_and_stays_project_only(checkout, capsys):
    entry = load_roster(checkout)[0]
    path = entry.opencode_path(checkout)
    prefix = path.read_text().split('## Agent framework (v2)')[0]
    assert cli.main(['subagents', 'doctor', '--root', str(checkout), '--refresh-framework']) == 0
    assert path.read_text().startswith(prefix)
    assert not (Path.home() / '.config').exists()
    capsys.readouterr()


def test_sync_check_and_dry_run_conflict_is_usage_error(checkout, capsys):
    assert cli.main(['subagents', 'sync', '--root', str(checkout), '--check', '--dry-run']) == 2
    assert 'Choose' in capsys.readouterr().err
