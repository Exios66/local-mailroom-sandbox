"""The sandbox serves through Modal vLLM unless the operator opts out."""

from __future__ import annotations

from mailroom_sandbox.cli import build_parser
from mailroom_sandbox.health import _effective_base_url, health_check, missing_modal_endpoint
from mailroom_sandbox.overlay import load_profile
from mailroom_sandbox.providers import DEFAULT_PROFILE, default_profile, modal_gateway_url


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
