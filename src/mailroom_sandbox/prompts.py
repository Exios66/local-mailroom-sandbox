"""Prompt-variant overlay for local-model experiments."""

from __future__ import annotations

from pathlib import Path

from mailroom_sandbox.paths import prompts_dir


def list_variants() -> list[str]:
    return sorted(p.stem for p in prompts_dir().glob("*.txt"))


def load_variant(name: str) -> str:
    path = prompts_dir() / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Unknown prompt variant {name!r}. Have: {list_variants()}")
    return path.read_text(encoding="utf-8")


def patch_managed_prompt(variant: str) -> bool:
    """Monkeypatch mailroom ``llm.prompts.get_managed_prompt`` when importable.

    Sorter variants replace the sorter template; other names are returned as-is
    for the matching agent (prefix before ``_local`` / first token).
    """
    text = load_variant(variant)
    try:
        import llm.prompts as prompts  # type: ignore
    except Exception:
        return False

    original = prompts.get_managed_prompt

    def wrapped(agent_name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        stem = variant
        target = stem.split("_local")[0].split("_v")[0]
        if agent_name == target or agent_name.replace("-", "_") == target:
            return text
        if target == "sorter" and agent_name in {"sorter", "sorter_reviewer"}:
            return text
        return original(agent_name, *args, **kwargs)

    prompts.get_managed_prompt = wrapped  # type: ignore[assignment]
    return True


def variant_path(name: str) -> Path:
    return prompts_dir() / f"{name}.txt"
