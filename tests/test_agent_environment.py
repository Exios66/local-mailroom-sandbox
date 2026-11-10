"""Environment isolation and hook diagnostics use temporary offline checkouts."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.subagents import environment


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                    "commit", "--allow-empty", "-qm", "initial"], check=True)
    package = tmp_path / "src/mailroom_sandbox/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("")
    monkeypatch.setattr(environment.mailroom_sandbox, "__file__", str(package))
    return tmp_path


def test_preflight_reports_actual_identity_without_mutation(checkout):
    before = sorted(str(p) for p in checkout.rglob("*"))
    head = environment.git_value(checkout, "rev-parse", "HEAD")
    report = environment.environment_report(checkout, head)
    assert report["ok"] and report["checkout"]["dirty"]
    assert report["python"]["package"].startswith(str(checkout))
    assert before == sorted(str(p) for p in checkout.rglob("*"))


def test_wrong_import_and_expected_head_fail_without_fixing(checkout, monkeypatch):
    monkeypatch.setattr(environment.mailroom_sandbox, "__file__", "/foreign/worktree/src/mailroom_sandbox/__init__.py")
    report = environment.environment_report(checkout, "0" * 40)
    assert not report["ok"]
    assert {f["code"] for f in report["findings"]} >= {"runtime.foreign_import", "checkout.head_mismatch"}


def test_missing_or_escaping_hooks_and_invalid_config_are_reported(checkout):
    path = checkout / ".claude/settings.json"
    path.parent.mkdir()
    for command in ['python "$CLAUDE_PROJECT_DIR/missing.py"', 'python "$CLAUDE_PROJECT_DIR/../outside.py"']:
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": command}]}]}}))
        assert environment.hook_findings(checkout)[0]["code"] == "hook.target_missing"
    path.write_text('{"hooks": null}')
    assert environment.hook_findings(checkout)[0]["code"] == "hook.config_invalid"


def test_non_repo_fails_and_cli_does_not_load_dotenv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("mailroom_sandbox.runtime.load_env_file", lambda: pytest.fail("must not load dotenv"))
    assert cli.main(["subagents", "preflight", "--root", str(tmp_path), "--json"]) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]


def test_git_timeout_is_a_finding(checkout, monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("git", 5)
    monkeypatch.setattr(environment.subprocess, "run", timeout)
    assert not environment.environment_report(checkout)["ok"]


def test_git_reads_ignore_inherited_repository_selectors(checkout, tmp_path, monkeypatch):
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git/index"))
    assert Path(environment.git_value(checkout, "rev-parse", "--show-toplevel")).resolve() == checkout.resolve()
    report = environment.environment_report(checkout)
    assert report["ok"] and report["checkout"]["git_root"] == str(checkout)


@pytest.fixture
def guard():
    path = Path(__file__).resolve().parents[1] / ".claude/hooks/guard_resources.py"
    spec = importlib.util.spec_from_file_location("guard_resources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", [
    "pytest", "pytest tests/test_one.py tests", "python -m pytest tests -q", "pytest tests/test_one.py --cov",
    "pytest tests/test_one.py -n auto", "pytest tests/test_one.py -n2",
    "pytest tests/test_one.py --numprocesses=4", "python scripts/smoke_campaign.py",
    "pytest --ignore=unused.py", "pytest --ignore tests/test_skip.py",
    "pytest --doctest-glob tests/test_one.py",
    "pytest --deselect tests/test_skip.py", "pytest --pyargs package",
])
def test_resource_hook_catches_expensive_direct_commands(guard, command):
    assert guard.violation(command)


@pytest.mark.parametrize("command", [
    "pytest -q tests/test_one.py -n 0 --no-cov", "python -m pytest tests/test_one.py::test_x -n1",
    "pytest --ignore tests/test_skip.py tests/test_one.py",
    "pytest --doctest-glob tests/test_one.py tests/test_one.py",
    "pytest -k 'not slow' tests/test_one.py",
    "ruff check src tests", "python scripts/check_cli_surface.py --check",
])
def test_resource_hook_preserves_focused_checks(guard, command):
    assert guard.violation(command) is None
