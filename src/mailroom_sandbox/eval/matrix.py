"""Provider × model × prompt experiment matrix."""

from __future__ import annotations

from typing import Any

from mailroom_sandbox.eval import experiment_log, runners
from mailroom_sandbox.overlay import load_profile, map_model, serving_family


def cell_name(task: str, provider: str, model: str, prompt: str) -> str:
    slug = model.split("/")[-1].replace(":", "-")
    prompt_slug = prompt.replace("/", "-")
    return f"matrix_{task}_{provider}_{slug}_{prompt_slug}"


def plan_matrix(
    *,
    task: str,
    providers: list[str],
    models: list[str],
    prompts: list[str],
    sample: int = 10,
    seed: int = 42,
) -> list[dict[str, Any]]:
    cells = []
    for provider in providers:
        profile = load_profile(provider) if provider in _profile_aliases(provider) else None
        family = serving_family(profile) if profile else provider
        for model in models:
            mapped = map_model(model, family) if "/" in model else model
            for prompt in prompts:
                cells.append(
                    {
                        "task": task,
                        "provider": provider,
                        "model": mapped,
                        "prompt": prompt,
                        "sample": sample,
                        "seed": seed,
                        "experiment_name": cell_name(task, provider, mapped, prompt),
                    }
                )
    return cells


def _profile_aliases(name: str) -> set[str]:
    from mailroom_sandbox.overlay import list_profiles

    return set(list_profiles()) | {name}


def run_matrix(
    *,
    task: str = "sorter",
    providers: list[str],
    models: list[str],
    prompts: list[str],
    sample: int = 10,
    seed: int = 42,
    mock: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    cells = plan_matrix(
        task=task,
        providers=providers,
        models=models,
        prompts=prompts,
        sample=sample,
        seed=seed,
    )
    if dry_run:
        return {"task": task, "cells": cells, "n": len(cells)}

    runner = {
        "sorter": runners.run_sorter_eval,
        "extract": runners.run_extract_eval,
        "chained": runners.run_chained_eval,
        "pipeline": runners.run_pipeline_eval,
        "legalbench": runners.run_legalbench_eval,
    }.get(task)
    if runner is None:
        raise ValueError(f"Unknown matrix task {task!r}")

    results = []
    for cell in cells:
        kwargs: dict[str, Any] = {
            "mock": mock,
            "sample": sample,
            "experiment_name": cell["experiment_name"],
            "profile": cell["provider"],
            "model": cell["model"],
        }
        if task != "legalbench":
            kwargs["prompt_version"] = cell["prompt"]
        results.append(runner(**kwargs))
    return {"task": task, "cells": cells, "results": results, "log": str(experiment_log.jsonl_path())}
