"""``scripts/floor_browser.py`` serves the floor from committed logs and refuses spend."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def floor_browser():
    """Load the project script without installing it as a package."""
    path = REPO / "scripts" / "floor_browser.py"
    spec = importlib.util.spec_from_file_location("floor_browser_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_uses_the_committed_fixture(floor_browser, capsys):
    """The default plan replays the committed sample into the scratch base, in debug mode."""
    assert floor_browser.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "source: committed replay fixture" in out
    assert "data/fixtures/floor/replay" in out
    assert "data/runtime/floor-browser" in out
    assert "replay-mailroom-sample" in out
    assert "debug=1" in out
    assert "spend: not started" in out
    assert "replay: yes" in out


def test_recorded_run_dry_run_does_not_reset_the_sample(floor_browser, capsys):
    """``--replay-run`` points at a finished directory and leaves the sample id out of the plan."""
    assert floor_browser.main(["--dry-run", "--replay-run", "data/runtime/runs/example"]) == 0
    out = capsys.readouterr().out
    assert "source: recorded run" in out
    assert "data/runtime/runs/example" in out
    assert "replay: no" in out
    assert "replay-mailroom-sample" not in out
    assert "printed by the server (debug=1)" in out
    assert "spend: not started" in out


@pytest.mark.parametrize("argv", [
    ["--live"],
    ["--real"],
    ["--submit"],
    ["--initials", "AB"],
    ["--dry-run", "--live"],
])
def test_billed_flags_are_refused(floor_browser, capsys, argv):
    """Spend gates are refused before a port is bound, including on a dry run."""
    assert floor_browser.main(argv) == 2
    assert "billed" in capsys.readouterr().err


def test_list_names_the_fixture_without_serving(floor_browser, capsys):
    """``--list`` reports the committed sample and does not claim a billed run will start."""
    assert floor_browser.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "data/fixtures/floor/replay" in out
    assert "present" in out
    assert "spend: not started" in out


def test_bad_speed_is_a_usage_error(floor_browser):
    """A non-positive replay speed exits 2 before any serve plan is built."""
    with pytest.raises(SystemExit) as exc:
        floor_browser.main(["--replay-speed", "0"])
    assert exc.value.code == 2


def test_serve_passes_debug_and_the_requested_base(floor_browser, monkeypatch, tmp_path):
    """A real invocation asks ``serve_floor`` for debug mode and does not enable a recorded replay."""
    seen = {}

    def serve(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(floor_browser._floor_app(), "serve_floor", serve)
    base = tmp_path / "scratch"
    assert floor_browser.main(["--base", str(base), "--port", "0", "--replay-speed", "4"]) == 0
    assert seen["debug"] is True
    assert seen["replay"] is True
    assert seen["replay_run"] is None
    assert seen["replay_speed"] == 4
    assert seen["port"] == 0
    assert seen["base"] == base
    assert base.is_dir()


def test_prefer_venv_reexecs_the_unresolved_venv_path(floor_browser, tmp_path, monkeypatch):
    """A symlink to the base interpreter must be executed as the venv path."""
    venv = tmp_path / ".venv"
    link = venv / "bin" / "python"
    link.parent.mkdir(parents=True)
    real = tmp_path / "base-python"
    real.write_text("", encoding="utf-8")
    link.symlink_to(real)
    monkeypatch.setattr(floor_browser, "ROOT", tmp_path)
    monkeypatch.setattr(floor_browser.sys, "prefix", str(tmp_path / "other"))
    monkeypatch.setattr(floor_browser.sys, "argv", ["scripts/floor_browser.py", "--dry-run"])
    seen = {}

    def fake_execv(path, argv):
        seen["path"] = path
        seen["argv"] = argv
        raise SystemExit(0)

    monkeypatch.setattr(floor_browser.os, "execv", fake_execv)
    with pytest.raises(SystemExit):
        floor_browser._prefer_venv()
    assert seen["path"] == link
    assert seen["argv"][0] == str(link)
    assert seen["argv"][1].endswith("floor_browser.py")


def test_prefer_venv_stays_when_the_prefix_is_the_venv(floor_browser, tmp_path, monkeypatch):
    """An already-active checkout venv is not replaced."""
    venv = tmp_path / ".venv"
    link = venv / "bin" / "python"
    link.parent.mkdir(parents=True)
    real = tmp_path / "base-python"
    real.write_text("", encoding="utf-8")
    link.symlink_to(real)
    monkeypatch.setattr(floor_browser, "ROOT", tmp_path)
    monkeypatch.setattr(floor_browser.sys, "prefix", str(venv))
    monkeypatch.setattr(floor_browser.os, "execv", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("re-exec")))
    floor_browser._prefer_venv()


def test_serve_pins_the_script_checkout(floor_browser, monkeypatch, tmp_path):
    """The server uses the same checkout the plan just checked."""
    seen = {}

    def serve(**kwargs):
        seen["root"] = floor_browser.os.environ.get("SANDBOX_ROOT")
        return 0

    monkeypatch.setattr(floor_browser._floor_app(), "serve_floor", serve)
    assert floor_browser.main(["--base", str(tmp_path / "scratch"), "--port", "0"]) == 0
    assert Path(seen["root"]) == floor_browser.ROOT


def test_unwritable_base_is_a_normal_error(floor_browser, tmp_path, capsys):
    """A base that cannot be created exits 1 with a message, not a traceback."""
    parent = tmp_path / "not-a-directory"
    parent.write_text("x", encoding="utf-8")
    assert floor_browser.main(["--base", str(parent / "child"), "--port", "0"]) == 1
    assert "cannot create base" in capsys.readouterr().err


def test_launch_config_points_at_the_script():
    """The project launch config starts this script on the floor port."""
    config = json.loads((REPO / ".claude" / "launch.json").read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in config["configurations"]}
    debug = by_name["mailroom-floor-debug"]
    assert debug["runtimeExecutable"] == "scripts/floor_browser.py"
    assert debug["port"] == 8769
    assert by_name["mailroom-floor"]["runtimeExecutable"] == ".venv/bin/sandbox"
