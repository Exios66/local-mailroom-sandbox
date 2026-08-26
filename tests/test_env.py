"""Env template is local-first."""

from mailroom_sandbox.paths import config_dir


def test_env_example_has_no_live_openrouter_key():
    text = (config_dir() / ".env.example").read_text(encoding="utf-8")
    assert "SANDBOX_PROFILE=ollama" in text
    assert "DEFAULT_PROVIDER=ollama" in text
    assert "OBSERVABILITY_PROVIDER=phoenix" in text
    # Cloud key is commented, not a placeholder that would authenticate.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("OPENROUTER_API_KEY="):
            raise AssertionError("OPENROUTER_API_KEY must stay commented in the example")
