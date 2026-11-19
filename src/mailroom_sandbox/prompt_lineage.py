"""Experiment-lineage prompt frontrunners: the default prompt for every agent that has one.

The sandbox improves prompts in its own lineages (``config/prompts/sorter_condensed_lineage.yaml``
and ``config/prompts/specialist_condensed_lineage.yaml``). An experiment starts from each agent's
current frontrunner, never from the vendored llm-mailroom prompt it is meant to improve on. So a
run spec whose ``prompt`` section does not name an agent gets that agent's frontrunner as an
explicit ``{source: local, file: <stem>}`` entry. The entry is part of the spec hash and the run
lock, so a lock always states the prompt text that ran.

An explicit per-agent entry always wins, including ``{source: code-default}`` for a deliberate
vendored baseline arm, and so does a ``prompt.versions`` selection for that agent.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

SORTER_LINEAGE = "sorter_condensed_lineage.yaml"
SPECIALIST_LINEAGE = "specialist_condensed_lineage.yaml"


def _prompts_dir() -> Path:
    """The configured prompts dir; the code checkout's own when that has no lineage files.

    A relocated config root (tests, a scratch tree) without lineage files still resolves the
    checkout's frontrunners, never the vendored prompts; a missing lineage anywhere raises.
    """
    from mailroom_sandbox.paths import config_dir

    configured = config_dir() / "prompts"
    if (configured / SORTER_LINEAGE).is_file():
        return configured
    return Path(__file__).resolve().parents[2] / "config" / "prompts"


@lru_cache(maxsize=1)
def _frontrunners_cached(prompts_dir: str) -> tuple[tuple[str, str], ...]:
    root = Path(prompts_dir)
    out: dict[str, str] = {}
    sorter = yaml.safe_load((root / SORTER_LINEAGE).read_text(encoding="utf-8")) or {}
    if sorter.get("frontrunner"):
        out[str(sorter.get("agent") or "sorter")] = str(sorter["frontrunner"])
    specialists = yaml.safe_load((root / SPECIALIST_LINEAGE).read_text(encoding="utf-8")) or {}
    for agent, row in (specialists.get("agents") or {}).items():
        if isinstance(row, Mapping) and row.get("frontrunner"):
            out[str(agent)] = str(row["frontrunner"])
    for agent, stem in out.items():
        if not (root / f"{stem}.txt").is_file():
            raise FileNotFoundError(f"lineage frontrunner for {agent} has no prompt file: config/prompts/{stem}.txt")
    return tuple(sorted(out.items()))


def frontrunners() -> dict[str, str]:
    """Agent name -> frontrunner prompt stem (``config/prompts/<stem>.txt``)."""
    return dict(_frontrunners_cached(str(_prompts_dir())))


def _agents_for(task: str | None, fronts: Mapping[str, str]) -> set[str]:
    """Lineage agents a task executes: its own agent for an isolated-agent task, else all."""
    if task:
        # Imported here: prompt_registry imports job.spec, which imports this module.
        # agent_prompt_names() guards its own vendored import.
        from mailroom_sandbox.prompt_registry import agent_prompt_names

        if task in set(agent_prompt_names()):
            return {task} & set(fronts)
    return set(fronts)


def with_lineage_defaults(prompt: Mapping[str, Any], task: str | None = None) -> dict[str, Any]:
    """Return ``prompt`` with every unnamed lineage agent ``task`` runs pinned to its frontrunner."""
    out = dict(prompt)
    agents = dict(out.get("agents") or {})
    selected = set(out.get("versions") or {})
    fronts = frontrunners()
    for agent in sorted(_agents_for(task, fronts)):
        stem = fronts[agent]
        if agent not in agents and agent not in selected:
            agents[agent] = {"source": "local", "file": stem}
    if agents:
        out["agents"] = dict(sorted(agents.items()))
    return out


def default_stem_for(task: str) -> str | None:
    """The prompt stem an unlocked isolated-agent eval runs for ``task`` without ``--prompt``.

    The lineage frontrunner when the agent has one (the same default a locked run spec
    gets), else the eval-environment frozen stem it was re-frozen to — for the agents
    whose parity stem is the deliberate default (contracts / merger keep theirs; there is
    no condensed lineage for the other positions yet). None when neither exists.
    """
    fronts = frontrunners()
    if task in fronts:
        return fronts[task]
    from mailroom_sandbox.eval_environment_lineage import default_prompt_variant

    return default_prompt_variant(task)


def apply_eval_defaults(task: str | None) -> bool:
    """Pin an unlocked eval run's unnamed lineage agents to their frontrunners, in place.

    The locked ``sandbox run`` path resolves its prompt surface at preflight and applies
    the lock inside :func:`mailroom_sandbox.runtime.activate`; this helper is for the
    direct eval paths (``sandbox eval pipeline`` / ``sorter`` / ``extract`` and the
    runners they call), which otherwise keep vendored code-default prompts — a silent
    regression to the pre-condensed stems. It is a no-op when a locked run policy is
    active (the lock owns the surface) or an explicit ``--prompt-version`` selection is
    set, and returns True only when lineage texts were applied.
    """
    from mailroom_sandbox import prompt_versions as pv
    from mailroom_sandbox.runtime import locked_policy

    if pv.active_selection():
        return False
    if locked_policy() is not None:
        return False
    if not frontrunners():
        return False
    from mailroom_sandbox.prompt_registry import apply_locked_prompts, prompt_lock_block

    apply_locked_prompts(prompt_lock_block(with_lineage_defaults({}, task)))
    return True
