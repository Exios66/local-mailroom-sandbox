"""Pytest hooks for the sandbox suite."""

from __future__ import annotations

import os

import pytest

from mailroom_sandbox.paths import repo_root


@pytest.fixture(autouse=True)
def _sandbox_root(monkeypatch):
    monkeypatch.setenv("SANDBOX_ROOT", str(repo_root()))
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "none")
    monkeypatch.setenv("PHOENIX_TRACING", "disabled")


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


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SANDBOX_LOCAL_LLM", "").strip() in {"1", "true", "yes"}:
        return
    skip = pytest.mark.skip(reason="SANDBOX_LOCAL_LLM not set")
    for item in items:
        if "local_llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _isolated_beacon_dir(tmp_path, monkeypatch):
    """Runs started in tests publish mailroom beacons — keep them out of ~/.mailroom/jobs."""
    monkeypatch.setenv("MAILROOM_BEACON_DIR", str(tmp_path / "_beacons"))


@pytest.fixture(autouse=True)
def _no_leaked_prompt_selection():
    """The active eval-environment prompt selection is process-wide; never leak it across tests."""
    from mailroom_sandbox import prompt_versions

    prompt_versions.clear_active_selection()
    yield
    prompt_versions.clear_active_selection()
