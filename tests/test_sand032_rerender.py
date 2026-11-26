"""scripts/sand032/rerender.py re-lays only the SAND-032 figures it owns."""

from __future__ import annotations

import importlib.util
import sys

from mailroom_sandbox.paths import repo_root

_SCRIPT = repo_root() / "scripts" / "sand032" / "rerender.py"


def _load():
    spec = importlib.util.spec_from_file_location("sand032_rerender", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fig_dirs_are_the_sand032_class_and_serving_figures():
    """Other generators' figure folders (decisions, dashboard, SAND42…) are not its to re-lay."""
    rerender = _load()
    root = repo_root() / "reports"
    got = {p.relative_to(root).as_posix() for p in rerender.FIG_DIRS}
    want = {p.relative_to(root).as_posix() for p in root.glob("SAND-32/*/figures") if p.is_dir()}
    want.add("serving/figures")
    assert got == want


def test_check_passes_on_the_committed_figures(monkeypatch):
    rerender = _load()
    monkeypatch.setattr(sys, "argv", ["rerender.py", "--check"])
    assert rerender.main() == 0
