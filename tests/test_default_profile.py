"""The sandbox serves through Modal vLLM unless the operator opts out."""

from __future__ import annotations

import os

import pytest

from mailroom_sandbox.cli import build_parser
from mailroom_sandbox.health import _effective_base_url, health_check, missing_modal_endpoint
from mailroom_sandbox.overlay import load_profile
from mailroom_sandbox.providers import DEFAULT_PROFILE, default_profile, modal_gateway_url


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """A developer's real `.env` must not change what the defaults resolve to."""
    monkeypatch.setattr("mailroom_sandbox.paths.dotenv_files", lambda: [])


def test_default_profile_constant_is_modal_vllm():
    assert DEFAULT_PROFILE == "modal-vllm"
    assert load_profile(DEFAULT_PROFILE)["provider"] == "vllm"


def test_default_profile_honors_env_opt_out(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROFILE", raising=False)
    assert default_profile() == "modal-vllm"

    monkeypatch.setenv("SANDBOX_PROFILE", "ollama")
    assert default_profile() == "ollama"


def test_cli_parser_uses_the_default_profile(monkeypatch):
    monkeypatch.delenv("SANDBOX_PROFILE", raising=False)
    parser = build_parser()
    assert parser.parse_args(["health"]).profile == "modal-vllm"
    assert parser.parse_args(["health", "--profile", "ollama"]).profile == "ollama"


def test_modal_profile_has_no_silent_localhost_health_probe(monkeypatch):
    """Unset VLLM_BASE_URL must not be reported as a healthy local server."""
    monkeypatch.delenv("VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("MODAL_WORKSPACE", raising=False)
    assert _effective_base_url(load_profile("modal-vllm")) is None
    assert missing_modal_endpoint(load_profile("modal-vllm")) is True

    result = health_check("modal-vllm")
    assert result["ok"] is False
    assert "VLLM_BASE_URL" in result["models"]["detail"]
    assert "localhost" not in result["models"]["url"]

    monkeypatch.setenv("MODAL_WORKSPACE", "exios66")
    assert (
        _effective_base_url(load_profile("modal-vllm"))
        == "https://exios66--sandbox-vllm-serve.modal.run/v1"
    )
    assert missing_modal_endpoint(load_profile("modal-vllm")) is False
    assert modal_gateway_url(load_profile("ollama")) is None


def test_dotenv_profile_opt_out_survives_the_default_flip(monkeypatch, tmp_path):
    """A pre-existing `.env` saying SANDBOX_PROFILE=ollama must keep winning.

    The CLI resolves its default before any `.env` is loaded, so `default_profile()`
    reads the file itself (real env still wins; `os.environ` is left untouched).
    """
    env_file = tmp_path / ".env"
    env_file.write_text("SANDBOX_PROFILE=ollama   # offline opt-out\n", encoding="utf-8")
    monkeypatch.setattr("mailroom_sandbox.paths.dotenv_files", lambda: [env_file])
    monkeypatch.delenv("SANDBOX_PROFILE", raising=False)

    assert default_profile() == "ollama"
    assert build_parser().parse_args(["health"]).profile == "ollama"
    assert "SANDBOX_PROFILE" not in os.environ

    monkeypatch.setenv("SANDBOX_PROFILE", "vllm-local")
    assert default_profile() == "vllm-local"
    assert build_parser().parse_args(["health", "--profile", "ollama"]).profile == "ollama"


def test_dotenv_without_a_profile_falls_back_to_modal(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OBSERVABILITY_PROVIDER=langfuse\nSANDBOX_PROFILE=\n", encoding="utf-8")
    monkeypatch.setattr("mailroom_sandbox.paths.dotenv_files", lambda: [env_file])
    monkeypatch.delenv("SANDBOX_PROFILE", raising=False)
    assert default_profile() == "modal-vllm"


def _isolated_environ(monkeypatch):
    """Let `apply_profile_env` mutate a private copy of the environment."""
    env = {k: v for k, v in os.environ.items() if k not in {"VLLM_BASE_URL", "MODAL_WORKSPACE"}}
    monkeypatch.setattr(os, "environ", env)
    return env


def test_modal_activation_never_seeds_the_localhost_fallback(monkeypatch):
    """An unset Modal URL must stay unset so the pipeline's live-or-loud warning fires."""
    from mailroom_sandbox.runtime import apply_profile_env

    env = _isolated_environ(monkeypatch)
    apply_profile_env(load_profile("modal-vllm"))
    assert "VLLM_BASE_URL" not in env
    assert env["DEFAULT_PROVIDER"] == "vllm"


def test_modal_activation_prefers_exported_url_then_workspace_gateway(monkeypatch):
    from mailroom_sandbox.runtime import apply_profile_env

    env = _isolated_environ(monkeypatch)
    env["MODAL_WORKSPACE"] = "ws1"
    apply_profile_env(load_profile("modal-vllm"))
    assert env["VLLM_BASE_URL"] == "https://ws1--sandbox-vllm-serve.modal.run/v1"

    env = _isolated_environ(monkeypatch)
    env.update(MODAL_WORKSPACE="ws1", VLLM_BASE_URL="https://exported.example/v1")
    apply_profile_env(load_profile("modal-vllm"))
    assert env["VLLM_BASE_URL"] == "https://exported.example/v1"


def test_other_profiles_still_seed_their_static_base_url(monkeypatch):
    from mailroom_sandbox.providers import endpoints_for
    from mailroom_sandbox.runtime import apply_profile_env

    env = _isolated_environ(monkeypatch)
    profile = load_profile("vllm-local")
    apply_profile_env(profile)
    assert env["VLLM_BASE_URL"] == endpoints_for(profile).base_url
