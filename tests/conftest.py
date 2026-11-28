"""Pytest hooks for the sandbox suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mailroom_sandbox.paths import repo_root

# Set before any test, so subprocesses inherit it too: a key in .env can bill real calls.
os.environ["SANDBOX_SKIP_DOTENV"] = "1"
os.environ.pop("OPENROUTER_API_KEY", None)
# A commit hook exports these, and `git init` in a test would then rewrite the real repo's config.
for _name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
    os.environ.pop(_name, None)


@pytest.fixture(autouse=True)
def _sandbox_root(monkeypatch):
    monkeypatch.setenv("SANDBOX_ROOT", str(repo_root()))
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "none")
    monkeypatch.setenv("PHOENIX_TRACING", "disabled")
    # Child interpreters must import this checkout, not whichever one the venv's
    # editable install happens to point at (pytest's `pythonpath` is in-process only).
    src = str(Path(__file__).resolve().parents[1] / "src")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")])))


@pytest.fixture(autouse=True)
def _worker_runtime_taxonomy(monkeypatch):
    """Under xdist, give each worker its own runtime taxonomy file.

    ``runtime.activate`` rewrites ``data/runtime/taxonomy.yaml`` and points the vendored config
    at it, so two workers sharing a container would read each other's profile. The worker's
    file stays under ``data/runtime/`` (gitignored), since callers report it relative to the root.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    from mailroom_sandbox import overlay
    from mailroom_sandbox.paths import runtime_dir

    own = runtime_dir() / f"xdist-{worker}"
    own.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(overlay, "runtime_dir", lambda: own)


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """Fake external CLIs on an isolated ``PATH`` (see ``tests/_fakebin.py``).

    ``PATH`` holds only the shim directory, so a tool a test did not ``add`` is genuinely
    missing and no real ``modal``/``hf``/``docker``/``ssh`` on the host can be reached.
    """
    from _fakebin import FakeBin

    fake = FakeBin(tmp_path / "fakebin")
    fake.isolate_path(monkeypatch)
    return fake


@pytest.fixture
def job_data_dir(monkeypatch, tmp_path):
    """Point run-store writes at tmp (DMR-027 tests)."""
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    return tmp_path


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "local_llm: live test against a local OpenAI-compatible server",
    )


# CI runs `--dist loadfile`: each test file goes to one xdist worker, so process-local unions
# such as test_pipeline_routing_matrix.WALKED stay whole. These files are the exception: their
# tests share no state (function-scoped fixtures, no module globals, arbiter_harness_state
# restores the compiled graph), so the scheduler below hands out their tests one at a time.
# They are the slowest files; on one worker each set the floor for a whole CI container. Add a
# file only after checking that none of its tests reads state another test leaves behind.
PER_TEST_XDIST_FILES = frozenset({
    "tests/test_arbiter_termination.py",
    "tests/test_generation_protocol.py",
    "tests/test_job_generation_residuals.py",
})

try:
    from xdist.scheduler import LoadFileScheduling
except ImportError:  # xdist is a dev dependency; without it there is nothing to schedule
    LoadFileScheduling = None
else:

    class PerTestLoadFileScheduling(LoadFileScheduling):
        """`--dist loadfile`, except that tests in PER_TEST_XDIST_FILES are scheduled singly.

        Only the scope key changes (xdist's documented `_split_scope` override point); node IDs
        are untouched, so this does not depend on how a pytest version stores them.
        """

        def _split_scope(self, nodeid: str) -> str:
            scope = super()._split_scope(nodeid)
            return nodeid if scope in PER_TEST_XDIST_FILES else scope

    def pytest_xdist_make_scheduler(config, log):
        if config.getvalue("dist") != "loadfile":
            return None
        return PerTestLoadFileScheduling(config, log)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SANDBOX_LOCAL_LLM", "").strip() in {"1", "true", "yes"}:
        return
    skip = pytest.mark.skip(reason="SANDBOX_LOCAL_LLM not set")
    for item in items:
        if "local_llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _span_mirror_sdk_present(request, monkeypatch):
    """The dev venv (and CI) lacks the [observability] SDK that a real run's span mirror needs.

    Preflight refuses a paid endpoint run without it, so tests that prepare such runs would all
    fail on the environment. They see the SDK as present; tests of that check opt out with
    ``@pytest.mark.span_mirror_sdk``.
    """
    if request.node.get_closest_marker("span_mirror_sdk") is None:
        from mailroom_sandbox.job import preflight

        monkeypatch.setattr(preflight, "span_mirror_missing", lambda: [])


@pytest.fixture(autouse=True)
def _isolated_run_ledger(tmp_path, monkeypatch):
    """Signed test runs must not append to the tracked reports/run-ledger.md."""
    monkeypatch.setenv("SANDBOX_RUN_LEDGER", str(tmp_path / "_ledger" / "run-ledger.md"))


@pytest.fixture(autouse=True)
def _isolated_beacon_dir(tmp_path, monkeypatch):
    """Runs started in tests publish mailroom beacons — keep them out of ~/.mailroom/jobs."""
    monkeypatch.setenv("MAILROOM_BEACON_DIR", str(tmp_path / "_beacons"))


@pytest.fixture(autouse=True)
def _no_leaked_prompt_selection():
    """Restore both prompt selection and patched pipeline bindings between tests."""
    from mailroom_sandbox import prompt_versions
    from mailroom_sandbox.prompt_registry import deactivate_runtime_overrides

    deactivate_runtime_overrides()
    prompt_versions.clear_active_selection()
    yield
    deactivate_runtime_overrides()
    prompt_versions.clear_active_selection()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item):
    """Join the vendored pipeline's fire-and-forget scan threads before the next test.

    ``pipeline.relations`` starts daemon ``relations-scan`` threads that write to the
    default DB; ``ensure_schema`` logs ``schema_ready`` the first time it sees a URL.
    Left running, that line lands in whichever later test is capturing stdout and
    corrupts its JSON. ``tryfirst`` joins them before fixtures (and env) are undone.
    """
    import threading

    for t in threading.enumerate():
        if t.name == "relations-scan" and t is not threading.current_thread():
            t.join(timeout=10)
