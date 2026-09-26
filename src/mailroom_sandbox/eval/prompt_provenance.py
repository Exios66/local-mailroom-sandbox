"""Experiment-log prompt labels (issue #39 / DMR-053)."""

from __future__ import annotations

from typing import Any


def _agent_ref(prompt_lock: dict[str, Any] | None, task: str) -> dict[str, Any] | None:
    if not prompt_lock:
        return None
    agents = prompt_lock.get("agents") or {}
    ref = agents.get(task)
    return ref if isinstance(ref, dict) else None


def _local_stem(ref: dict[str, Any]) -> str | None:
    if ref.get("source") != "local":
        return None
    stem = str(ref.get("file") or ref.get("stem") or "").strip()
    return stem or None


def _bound_prompt_for_task(task: str) -> str | None:
    try:
        from llm.prompts import _bound_prompt_versions

        versions = _bound_prompt_versions()
        if task in versions:
            return str(versions[task])
    except Exception:
        return None
    return None


def resolve_logged_prompt_version(
    prompt_version: str | None,
    *,
    task: str,
    prompt_lock: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Label (+ optional sha256) written to experiment / serving records."""
    if prompt_version:
        ref = _agent_ref(prompt_lock, task)
        sha = str(ref["sha256"]) if ref and ref.get("sha256") else None
        return prompt_version, sha
    ref = _agent_ref(prompt_lock, task)
    if ref:
        stem = _local_stem(ref)
        if stem:
            sha = str(ref["sha256"]) if ref.get("sha256") else None
            return stem, sha
    default = (prompt_lock or {}).get("default") or {}
    if isinstance(default, dict):
        stem = _local_stem(default)
        if stem:
            sha = str(default["sha256"]) if default.get("sha256") else None
            return stem, sha
        if default.get("source"):
            return str(default["source"]), None
    bound = _bound_prompt_for_task(task)
    if bound:
        return bound, None
    return "mailroom-default", None


def stamp_prompt_provenance(record: dict[str, Any], label: str, sha256: str | None) -> None:
    record["prompt_version"] = label
    if sha256:
        record["prompt_sha256"] = sha256
