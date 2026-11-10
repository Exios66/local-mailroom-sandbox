"""Frozen source identity, fallback and worker-image integration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mailroom_sandbox import dependency_sources as deps, dojo_source, pipeline_source
from mailroom_sandbox import snapshots as s
from test_snapshots import COMMIT, TAG, archive, release_api  # noqa: F401


@pytest.fixture
def isolated(monkeypatch):
    import sys

    path = sys.path[:]
    family = ("llm_dojo_scoring", "pipeline", "graph", "agents", "llm", "legalbench")
    modules = {k: v for k, v in sys.modules.items() if k.split(".")[0] in family}
    old_dojo, old_pipeline = dojo_source.current(), pipeline_source.current()
    monkeypatch.setattr(dojo_source, "_CHOICE", old_dojo)
    monkeypatch.setattr(pipeline_source, "_CHOICE", old_pipeline)
    monkeypatch.delenv("DOJO_SRC", raising=False)
    monkeypatch.delenv("MAILROOM_SRC", raising=False)
    monkeypatch.delenv("SANDBOX_DOJO_SOURCE", raising=False)
    yield monkeypatch
    sys.path[:] = path
    for name in list(sys.modules):
        if name.split(".")[0] in family:
            del sys.modules[name]
    sys.modules.update(modules)
    dojo_source._CHOICE, pipeline_source._CHOICE = old_dojo, old_pipeline


def test_off_pin_installed_uses_selected_cache_then_vendor(release_api, isolated):
    result = s.fetch("dojo", version=TAG)
    isolated.setenv("SANDBOX_DOJO_SNAPSHOT", result["lock_path"])
    isolated.setattr(dojo_source, "installed", lambda: {"version": "0.0.1", "commit": "b" * 40})
    choice = dojo_source.choose()
    assert choice.source == "cached" and choice.commit == COMMIT
    from mailroom_sandbox.runtime import resolve_dojo_src

    assert resolve_dojo_src() == Path(result["path"])
    isolated.delenv("SANDBOX_DOJO_SNAPSHOT")
    assert dojo_source.choose().source == "vendored"


def test_broken_cached_import_falls_back(release_api, isolated):
    release_api["data"] = __import__("test_snapshots").wheel(
        {"llm_dojo_scoring/__init__.py": "raise RuntimeError('broken')"}
    )
    result = s.fetch("dojo", version=TAG)
    isolated.setenv("SANDBOX_DOJO_SNAPSHOT", result["lock_path"])
    isolated.setattr(dojo_source, "installed", lambda: None)
    choice = dojo_source.choose()
    assert choice.source == "vendored" and "cached import rejected" in choice.reason


def test_all_missing_layers_have_diagnostic(release_api, isolated):
    isolated.setattr(dojo_source, "installed", lambda: None)
    isolated.setattr(dojo_source, "vendored_dojo_src", lambda: None)
    choice = dojo_source.choose()
    assert choice.source == "none"
    for text in ("DOJO_SRC", "not installed", "cache", "vendored"):
        assert text in choice.reason
    isolated.setattr(pipeline_source, "installed", lambda: None)
    isolated.setattr(pipeline_source, "vendored_mailroom_src", lambda: None)
    choice = pipeline_source.choose()
    assert choice.source == "none"
    for text in ("MAILROOM_SRC", "installed", "cache", "vendored"):
        assert text in choice.reason


def test_pipeline_cached_and_explicit_source_precedence(release_api, isolated, tmp_path):
    release_api.update(component="pipeline", tag="v0.9.3", assets=False, data=archive())
    result = s.fetch("pipeline", version="v0.9.3")
    isolated.setenv("SANDBOX_PIPELINE_SNAPSHOT", result["lock_path"])
    isolated.setattr(pipeline_source, "installed", lambda: None)
    isolated.setattr(pipeline_source, "vendored_mailroom_src", lambda: None)
    choice = pipeline_source.choose()
    assert choice.source == "cached" and choice.commit == COMMIT
    from mailroom_sandbox.runtime import resolve_mailroom_src

    assert resolve_mailroom_src() == Path(result["path"])
    isolated.setenv("MAILROOM_SRC", str(Path(result["path"]).parent))
    # Explicit roots may be the source directory itself.
    isolated.setenv("MAILROOM_SRC", result["path"])
    assert pipeline_source.choose().source == "env"


def test_matching_installed_pipeline_is_selected(isolated, tmp_path):
    import sys
    import types

    root = tmp_path / "site"
    s._extract(archive(), tmp_path, wheel=False)
    root = tmp_path / "root/src"
    isolated.setattr(
        pipeline_source, "installed", lambda: {**s.PINS["pipeline"], "path": str(root)}
    )
    isolated.setitem(
        sys.modules, "pipeline", types.SimpleNamespace(__file__=str(root / "pipeline/__init__.py"))
    )
    assert pipeline_source.choose().source == "installed"


def test_run_lock_refuses_source_drift_and_corruption(release_api, isolated):
    result = s.fetch("dojo", version=TAG)
    isolated.setenv("SANDBOX_DOJO_SNAPSHOT", result["lock_path"])
    isolated.setattr(dojo_source, "installed", lambda: None)
    dojo_source.choose()
    frozen = {"dependency_sources": deps.describe()}
    deps.verify_locked(frozen)
    original = dojo_source.current()
    isolated.setattr(dojo_source, "_CHOICE", replace(original, commit="c" * 40))
    with pytest.raises(s.SnapshotError, match="source drift"):
        deps.verify_locked(frozen)
    isolated.setattr(dojo_source, "_CHOICE", original)
    (Path(result["path"]) / "llm_dojo_scoring/__init__.py").write_text("tampered")
    with pytest.raises(s.SnapshotError, match="inventory"):
        deps.verify_locked(frozen)
    deps.verify_locked({})  # old locks remain readable


def test_worker_bundles_only_selected_entry_without_download(release_api, isolated):
    result = s.fetch("dojo", version=TAG)
    isolated.setenv("SANDBOX_DOJO_SNAPSHOT", result["lock_path"])
    isolated.setattr(dojo_source, "installed", lambda: None)
    dojo_source.choose()

    class Image:
        def __init__(self):
            self.directories, self.settings = [], {}

        def add_local_dir(self, path, **kwargs):
            self.directories.append((path, kwargs))
            return self

        def env(self, settings):
            self.settings.update(settings)
            return self

    image = deps.bundle_job_snapshots(Image())
    assert len(image.directories) == 1
    assert image.directories[0][0] == Path(result["lock_path"]).parent
    assert image.settings["SANDBOX_DOJO_SNAPSHOT"].startswith("/root/data/cache/snapshots/dojo/")
    assert image.settings["SANDBOX_DOJO_SNAPSHOT"].endswith("/snapshot.lock.json")


def test_pin_identity_survives_worker_without_vendor_metadata(isolated, tmp_path):
    root = tmp_path / "src/llm_dojo_scoring"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text('__version__ = "0.28.1"')
    isolated.setattr(dojo_source, "vendored_dojo_src", lambda: root.parent)
    assert dojo_source.pinned() == s.PINS["dojo"]


def test_preflight_records_identity_and_refuses_changed_source(tmp_path, job_data_dir, monkeypatch):
    from test_job_preflight import _run_spec
    from mailroom_sandbox.job import preflight
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    spec = _run_spec(tmp_path, run_id="pf-dependency-sources")
    first = preflight.preflight(spec, offline=True)
    assert first["status"] == "prepared"
    store = RunStore(run_dir(spec.run_id))
    frozen = store.read_lock()["dependency_sources"]
    assert frozen["dojo"]["commit"] == s.PINS["dojo"]["commit"]
    assert frozen["pipeline"]["source"] == "vendored"
    before = store.lock_path.read_bytes()
    monkeypatch.setattr(
        deps, "describe", lambda: {**frozen, "dojo": {**frozen["dojo"], "commit": "f" * 40}}
    )
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "drift_refused" and "Dependency source drift" in report["detail"]
    assert store.lock_path.read_bytes() == before


def test_missing_source_raises_aggregated_diagnostic(release_api, isolated):
    isolated.setattr(dojo_source, "installed", lambda: None)
    isolated.setattr(dojo_source, "vendored_dojo_src", lambda: None)
    dojo_source.choose()
    with pytest.raises(ModuleNotFoundError, match="DOJO_SRC.*not installed.*cache.*vendored"):
        dojo_source.import_root()


def test_status_displays_frozen_dependency_sources(tmp_path, job_data_dir, capsys):
    import json
    from test_job_preflight import _run_spec
    from mailroom_sandbox.cli import main
    from mailroom_sandbox.job.preflight import preflight

    spec = _run_spec(tmp_path, run_id="status-dependency-sources")
    assert preflight(spec, offline=True)["status"] == "prepared"
    assert main(["run", "status", "--run-id", spec.run_id]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dependency_sources"]["dojo"]["commit"] == s.PINS["dojo"]["commit"]
    assert payload["dependency_sources"]["pipeline"]["source"] == "vendored"


def test_cache_validation_import_is_readonly(release_api, isolated):
    result = s.fetch("dojo", version=TAG)
    isolated.setenv("SANDBOX_DOJO_SNAPSHOT", result["lock_path"])
    isolated.setattr(dojo_source, "installed", lambda: None)
    source = Path(result["path"])
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert dojo_source.choose().source == "cached"
    assert not list(source.rglob("__pycache__"))
    assert {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    } == before
    isolated.setattr(
        dojo_source, "_import_ok", lambda: pytest.fail("verify_import=False imported the cache")
    )
    assert dojo_source.choose(verify_import=False).source == "cached"
