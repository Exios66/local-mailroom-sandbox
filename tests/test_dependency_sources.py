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


MUTABLE_SOURCES = [
    (component, layer)
    for component in ("dojo", "pipeline")
    for layer in ("vendored", "installed", "env")
]


@pytest.fixture
def mutable_source(request, isolated, tmp_path):
    """Select a small mutable family tree without editing real vendor/install files."""
    import sys
    import types

    component, layer = request.param
    if component == "dojo" and layer == "installed":
        __import__("llm_dojo_scoring")
    root = tmp_path / "selected"
    package = "llm_dojo_scoring" if component == "dojo" else "pipeline"
    (root / package).mkdir(parents=True)
    (root / package / "__init__.py").write_text(
        '__version__ = "0.28.1"\n' if component == "dojo" else ""
    )
    if component == "pipeline":
        for name in (
            "pipeline/config.py",
            "graph/build_graph.py",
            "graph/__init__.py",
            "agents/__init__.py",
            "llm/__init__.py",
            "legalbench/__init__.py",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
    code = root / package / "logic.py"
    code.write_text("VALUE = 1\n")
    (root / package / "schema.json").write_text('{"version": 1}\n')
    module = dojo_source if component == "dojo" else pipeline_source
    state = {"root": root, "component": component, "layer": layer, "code": code, "package": package}
    real_distribution = __import__("importlib.metadata", fromlist=["distribution"]).distribution
    dist = types.SimpleNamespace(
        files=[p.relative_to(root) for p in root.rglob("*") if p.is_file()]
        + [Path("__pycache__/entry.cpython-311.pyc")],
        locate_file=lambda path: state["root"] / path,
    )
    state["distribution"] = dist
    (root / "__pycache__").mkdir()
    (root / "__pycache__/entry.cpython-311.pyc").write_bytes(b"generated")
    isolated.setattr(
        "importlib.metadata.distribution",
        lambda name: (
            dist
            if name == ("llm-dojo-scoring" if component == "dojo" else "mailroom")
            else real_distribution(name)
        ),
    )

    def select(path):
        """Relocate the selected root while preserving its version and commit."""
        state["root"] = path
        if component == "dojo" and layer == "installed":
            isolated.setattr(dojo_source, "_installed_package_dirs", lambda: [path / package])
            isolated.setattr(
                sys.modules["llm_dojo_scoring"], "__file__", str(path / package / "__init__.py")
            )
        isolated.setattr(
            module,
            "_CHOICE",
            replace(
                module.current(),
                source=layer,
                path=None if component == "dojo" and layer == "installed" else str(path),
                version=s.PINS[component]["version"],
                commit=s.PINS[component]["commit"],
                tree_sha256=None,
            ),
        )

    state["select"] = select
    select(root)
    return state


@pytest.mark.parametrize("mutation", ["edit", "add", "delete", "resource", "mode"])
@pytest.mark.parametrize("mutable_source", MUTABLE_SOURCES, indirect=True)
def test_mutable_source_changes_refuse_same_metadata_lock(mutable_source, mutation):
    """File changes must invalidate every mutable layer with fixed version/commit."""
    root, package, code = (mutable_source[key] for key in ("root", "package", "code"))
    frozen = {"dependency_sources": deps.describe()}
    deps.verify_locked(frozen)
    if mutation == "edit":
        code.write_text("VALUE = 2\n")
    elif mutation == "add":
        (root / package / "new_module.py").write_text("VALUE = 3\n")
    elif mutation == "delete":
        code.unlink()
    elif mutation == "resource":
        (root / package / "schema.json").write_text('{"version": 2}\n')
    else:
        code.chmod(code.stat().st_mode ^ 0o100)
    with pytest.raises(s.SnapshotError, match="source drift"):
        deps.verify_locked(frozen)


@pytest.mark.parametrize("mutable_source", MUTABLE_SOURCES, indirect=True)
def test_mutable_source_digest_is_portable_and_ignores_bytecode(mutable_source, tmp_path):
    """Worker relocation and generated import caches must preserve source identity."""
    import shutil

    root, package = mutable_source["root"], mutable_source["package"]
    frozen = {"dependency_sources": deps.describe()}
    assert frozen["dependency_sources"][mutable_source["component"]]["tree_sha256"]
    destination = tmp_path / "worker"
    shutil.copytree(root, destination)
    cache = destination / package / "__pycache__"
    cache.mkdir()
    (cache / "logic.cpython-311.pyc").write_bytes(b"generated")
    mutable_source["select"](destination)
    deps.verify_locked(frozen)
    if mutable_source["layer"] == "installed":
        # Other distributions in the same site-packages must not be fingerprinted.
        (destination / "unrelated_library.py").write_text("irrelevant\n")
        deps.verify_locked(frozen)


@pytest.mark.parametrize("mutable_source", MUTABLE_SOURCES, indirect=True)
def test_mutable_bytes_are_checked_by_preflight_and_execution(
    mutable_source, tmp_path, job_data_dir, monkeypatch
):
    """Both public entry points reject edited source without rewriting the run lock."""
    from test_job_preflight import _run_spec
    from mailroom_sandbox.job import preflight, runner
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    spec = _run_spec(tmp_path, run_id="mutable-source-entrypoints")
    assert preflight.preflight(spec, offline=True)["status"] == "prepared"
    store = RunStore(run_dir(spec.run_id))
    before = store.lock_path.read_bytes()
    mutable_source["code"].write_text("VALUE = 99\n")
    assert preflight.preflight(spec, offline=True)["status"] == "drift_refused"
    monkeypatch.setattr(runner, "_beacon_hook", lambda *a, **kw: (None, lambda *a, **kw: None))
    monkeypatch.setattr(
        "mailroom_sandbox.runtime.activate", lambda *a, **kw: pytest.fail("drift reached execution")
    )
    with store.acquire():
        with pytest.raises(s.SnapshotError, match="source drift"):
            runner.run_job(store)
    assert store.lock_path.read_bytes() == before


@pytest.mark.parametrize(
    "mutable_source", [("dojo", "installed"), ("pipeline", "installed")], indirect=True
)
def test_mutable_fingerprint_requires_source_ownership(mutable_source, isolated):
    """Missing installed metadata/source must fail closed instead of using a null hash."""
    if mutable_source["component"] == "pipeline":
        isolated.setattr(
            "importlib.metadata.distribution",
            lambda *a: type("Distribution", (), {"files": None})(),
        )
    else:
        isolated.setattr(dojo_source, "_installed_package_dirs", lambda: [])
    with pytest.raises(s.SnapshotError, match="manifest|source root"):
        deps.describe()


@pytest.mark.parametrize("mutable_source", MUTABLE_SOURCES, indirect=True)
def test_mutable_source_links_fail_closed(mutable_source, tmp_path):
    """A mutable source cannot hide changed code behind an escaping file link."""
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n")
    code = mutable_source["code"]
    code.unlink()
    code.symlink_to(outside)
    with pytest.raises(s.SnapshotError, match="Symlink"):
        deps.describe()


@pytest.mark.parametrize(
    "mutable_source", [("dojo", "installed"), ("pipeline", "installed")], indirect=True
)
def test_worker_preserves_installed_source_with_explicit_snapshot(
    mutable_source, release_api, isolated, tmp_path
):
    """A fresh worker must reproduce installed provenance even with an off-pin lock."""
    import json
    import os
    import shutil
    import subprocess
    import sys

    component = mutable_source["component"]
    root = mutable_source["root"]
    if component == "pipeline":
        release_api.update(component="pipeline", tag="v0.9.3", assets=False, data=archive())
    item = s.fetch(component, version=release_api["tag"])
    isolated.setenv(f"SANDBOX_{component.upper()}_SNAPSHOT", item["lock_path"])
    module = dojo_source if component == "dojo" else pipeline_source
    isolated.setattr(
        module, "_CHOICE", replace(module.current(), version=item["version"], commit=item["commit"])
    )
    distribution_name = "llm-dojo-scoring" if component == "dojo" else "mailroom"
    info = root / f"{distribution_name.replace('-', '_')}-{item['version']}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {distribution_name}\nVersion: {item['version']}\n"
    )
    (info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": f"https://github.com/Exios66/{s.COMPONENTS[component]}.git",
                "vcs_info": {"vcs": "git", "commit_id": item["commit"]},
            }
        )
    )
    distribution = mutable_source["distribution"]
    distribution.files.extend([p.relative_to(root) for p in info.iterdir()])
    distribution.files.append(Path(info.name) / "RECORD")
    (info / "RECORD").write_text("".join(f"{name},,\n" for name in distribution.files))
    frozen = deps.describe()
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "vendor").symlink_to(
        Path(__file__).resolve().parents[1] / "vendor", target_is_directory=True
    )

    class Image:
        """Copy only adapter-selected files into an offline simulated image root."""

        def __init__(self):
            self.settings = {}

        def add_local_dir(self, source, *, remote_path, **kwargs):
            shutil.copytree(
                source,
                remote_path,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            return self

        def add_local_file(self, source, *, remote_path, **kwargs):
            Path(remote_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, remote_path)
            return self

        def env(self, settings):
            self.settings.update(settings)
            return self

    image = deps.bundle_job_snapshots(Image(), remote_root=str(worker))
    assert f"SANDBOX_INSTALLED_{component.upper()}_ROOT" in image.settings
    assert f"SANDBOX_{component.upper()}_SNAPSHOT" in image.settings
    assert not (
        worker / "data/cache/installed-sources" / component / "unrelated_library.py"
    ).exists()
    environment = {
        **os.environ,
        **image.settings,
        "SANDBOX_ROOT": str(worker),
        "SANDBOX_SKIP_DOTENV": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "LOCKED_DEPENDENCIES": json.dumps({"dependency_sources": frozen}),
    }
    script = "import os,json; import mailroom_sandbox; from mailroom_sandbox.dependency_sources import describe,verify_locked; verify_locked(json.loads(os.environ['LOCKED_DEPENDENCIES'])); print(json.dumps(describe()))"
    result = subprocess.run(
        [sys.executable, "-c", script], env=environment, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[component]["source"] == "installed"
