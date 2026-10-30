"""The shared guard around external CLIs: missing binary, failure, timeout, argv-only.

Every `sandbox modal|vllm|hf` command and `sandbox doctor` goes through this module, so
the failure modes are pinned once here with fake binaries instead of per command.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.services._exec import (
    ServiceError,
    ToolFailed,
    ToolMissing,
    ToolTimeout,
    require_tool,
    run_tool,
)


def test_require_tool_returns_the_resolved_path(fake_bin):
    shim = fake_bin.add("modal")
    assert require_tool("modal") == str(shim)


def test_require_tool_names_the_tool_and_the_install_hint_when_missing(fake_bin):
    with pytest.raises(ToolMissing) as exc:
        require_tool("modal", hint="pip install -e '.[deploy]'")
    message = str(exc.value)
    assert "modal" in message and "pip install -e '.[deploy]'" in message
    assert isinstance(exc.value, ServiceError)


def test_run_tool_captures_stdout_and_records_the_argv(fake_bin):
    fake_bin.add("hf", stdout="user: alice\n")
    result = run_tool(["hf", "auth", "whoami"])
    assert result.stdout == "user: alice\n" and result.returncode == 0
    assert fake_bin.calls("hf") == [["auth", "whoami"]]


def test_run_tool_raises_tool_failed_with_rc_and_stderr(fake_bin):
    fake_bin.add("modal", stderr="not authenticated\n", rc=3)
    with pytest.raises(ToolFailed) as exc:
        run_tool(["modal", "app", "list"])
    assert exc.value.returncode == 3
    assert "not authenticated" in str(exc.value)
    assert "modal app list" in str(exc.value)


def test_run_tool_check_false_returns_the_failure_instead_of_raising(fake_bin):
    fake_bin.add("modal", stderr="no such app\n", rc=1)
    result = run_tool(["modal", "app", "stop", "x"], check=False)
    assert result.returncode == 1 and "no such app" in result.stderr


def test_run_tool_times_out_with_a_service_error(fake_bin):
    fake_bin.add("vllm", sleep=5)
    with pytest.raises(ToolTimeout) as exc:
        run_tool(["vllm", "--version"], timeout=0.3)
    assert "vllm --version" in str(exc.value) and "0.3" in str(exc.value)


def test_run_tool_on_a_missing_binary_raises_tool_missing_not_filenotfound(fake_bin):
    with pytest.raises(ToolMissing):
        run_tool(["ollama", "list"], hint="install Ollama")


def test_run_tool_never_goes_through_a_shell(fake_bin):
    """Arguments with shell metacharacters reach the tool verbatim."""
    fake_bin.add("hf")
    run_tool(["hf", "download", "a; rm -rf /", "$(whoami)"])
    assert fake_bin.calls("hf") == [["download", "a; rm -rf /", "$(whoami)"]]
