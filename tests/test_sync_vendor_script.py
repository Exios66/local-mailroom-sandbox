"""``scripts/sync_vendor.py`` stages before replacing tracked snapshots."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_vendor.py"


@pytest.fixture
def sync_vendor(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_vendor_script", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = tmp_path
    module.VENDOR = tmp_path / "vendor"
    return module


def _dest(tmp_path: Path) -> Path:
    dest = tmp_path / "vendor" / "pkg" / "src"
    dest.mkdir(parents=True)
    (dest / "keep.py").write_text("reviewed bytes\n")
    return dest


def test_empty_workspace_source_preserves_snapshot(sync_vendor, tmp_path):
    dest = _dest(tmp_path)
    source = tmp_path / "workspace" / "pkg" / "src"
    source.mkdir(parents=True)
    assert sync_vendor._refresh("pkg", dest, source) == 1
    assert (dest / "keep.py").read_text() == "reviewed bytes\n"


def test_only_excluded_files_preserves_snapshot(sync_vendor, tmp_path):
    dest = _dest(tmp_path)
    source = tmp_path / "workspace" / "pkg" / "src"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "test_x.py").write_text("excluded\n")
    assert sync_vendor._refresh("pkg", dest, source) == 1
    assert (dest / "keep.py").exists()


def test_success_replaces_tree_and_removes_stale_files(sync_vendor, tmp_path):
    dest = _dest(tmp_path)
    source = tmp_path / "workspace" / "pkg" / "src"
    source.mkdir(parents=True)
    (source / "new.py").write_text("new bytes\n")
    (source / "pkg").mkdir()
    (source / "pkg" / "mod.py").write_text("module\n")
    assert sync_vendor._refresh("pkg", dest, source) == 0
    assert (dest / "new.py").read_text() == "new bytes\n"
    assert (dest / "pkg" / "mod.py").exists()
    assert not (dest / "keep.py").exists()
    assert not dest.with_name("src.sync-new").exists()
    assert not dest.with_name("src.sync-old").exists()


def test_failed_copy_leaves_snapshot_and_no_staging(sync_vendor, tmp_path, monkeypatch):
    dest = _dest(tmp_path)
    source = tmp_path / "workspace" / "pkg" / "src"
    source.mkdir(parents=True)
    (source / "new.py").write_text("new bytes\n")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sync_vendor.shutil, "copy2", fail)
    with pytest.raises(OSError, match="disk full"):
        sync_vendor._refresh("pkg", dest, source)
    assert (dest / "keep.py").read_text() == "reviewed bytes\n"
    assert not dest.with_name("src.sync-new").exists()
    assert not dest.with_name("src.sync-old").exists()
