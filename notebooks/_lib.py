"""Shared bootstrap for sandbox notebooks.

Kernel-cwd-proof: walk up from cwd (or this file) until ``pyproject.toml`` +
``reports/`` exist. Isolate eval/score writers under ``reports/notebooks/``
so headless runs do not append to the operator experiment log.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    seeds = []
    if start is not None:
        seeds.append(start)
    seeds.append(Path.cwd())
    seeds.append(Path(__file__).resolve().parent)
    seen: set[Path] = set()
    for seed in seeds:
        for cand in [seed, *seed.parents]:
            resolved = cand.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "pyproject.toml").is_file() and (resolved / "reports").is_dir():
                return resolved
    raise RuntimeError("repo root not found (need pyproject.toml + reports/)")


def bootstrap(start: Path | None = None) -> Path:
    """Put ``src/`` on sys.path, set SANDBOX_ROOT, disable live tracing."""
    root = find_repo_root(start)
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    os.environ.setdefault("SANDBOX_ROOT", str(root))
    os.environ["OBSERVABILITY_PROVIDER"] = "none"
    os.environ["PHOENIX_TRACING"] = "disabled"
    return root


def isolate_outputs(root: Path | None = None) -> Path:
    """Redirect experiment log + score JSONL to reports/notebooks/."""
    root = root or find_repo_root()
    dest = root / "reports" / "notebooks"
    dest.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MAILROOM_BASE_DIR", str(dest / "mailroom_data"))
    log = dest / "experiment_log.jsonl"
    scores = dest / "scores.jsonl"

    from mailroom_sandbox.eval import experiment_log, scoring

    experiment_log.jsonl_path = lambda: log  # type: ignore[method-assign]
    experiment_log.md_path = lambda: dest / "experiment_log.md"  # type: ignore[method-assign]
    scoring.scores_path = lambda: scores  # type: ignore[method-assign]
    return dest
