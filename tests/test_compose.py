"""Compose file / CLI argv construction (no docker required)."""

from __future__ import annotations

import yaml

from mailroom_sandbox.compose import VALID_PROFILES, compose_argv, compose_file, default_profiles_for
from mailroom_sandbox.paths import deploy_dir


def test_compose_file_parses():
    data = yaml.safe_load(compose_file().read_text(encoding="utf-8"))
    services = data["services"]
    for name in (
        "phoenix",
        "ollama",
        "vllm",
        "llamacpp",
        "langfuse-web",
        "langfuse-worker",
        "minio",
        "redis",
        "jupyter",
    ):
        assert name in services
    assert "phoenix" in services["phoenix"]["profiles"]
    assert "ollama" in services["ollama"]["profiles"]
    assert "jupyter" in services["jupyter"]["profiles"]
    assert services["jupyter"]["build"]["dockerfile"] == "deploy/Dockerfile"
    assert services["jupyter"]["image"] == "mailroom-sandbox:offline"
    assert "langfuse" in services["langfuse-web"]["profiles"]
    assert services["langfuse-web"]["image"].endswith(":3")
    assert services["langfuse-worker"]["image"].endswith("langfuse-worker:3")
    # Default ollama has no GPU reservation (CPU-capable smoke).
    assert "deploy" not in services["ollama"]
    # Healthchecks must not pass credentials as CLI flags (secret scanners).
    raw = compose_file().read_text(encoding="utf-8")
    assert "--password" not in raw
    assert "LANGFUSE_INIT_PROJECT_PUBLIC_KEY" in raw


def test_compose_argv_profiles():
    cmd = compose_argv(["phoenix", "ollama"], "up", "-d")
    assert cmd[1:3] == ["compose", "-f"]
    assert str(compose_file()) in cmd
    assert cmd.count("--profile") == 2
    assert "phoenix" in cmd and "ollama" in cmd
    assert cmd[-2:] == ["up", "-d"]


def test_default_profiles_ollama():
    names = default_profiles_for("ollama")
    assert names == ["langfuse", "ollama"]
    assert set(names) <= set(VALID_PROFILES)


def test_modal_vllm_app_is_sandbox_scoped():
    text = (deploy_dir() / "modal_vllm.py").read_text(encoding="utf-8")
    assert 'APP_NAME = "sandbox-vllm"' in text
    assert "build_vllm_command" in text
    assert "MODAL_VLLM_MODEL" in text
    assert "sandbox-hf-cache" in text
