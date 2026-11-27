"""The ``judge:`` section (phase 4): today's judge plus a record, or a judge that rules on fixes.

``mode: verify`` keeps the vendored judge and records its verdict; ``mode: correct`` lets the
judge propose a fix per weak field, which the pipeline accepts only once a deterministic check
verifies it (spec ``docs/design/specs/2026-11-26-correcting-judge-design.md``, "The correcting
judge"). The section is process-wide like the governor, because agent-task workers do not inherit
the lock's ContextVar. A lock without the key leaves the judge off: today's judge, no record.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

_LOCK = threading.Lock()
_ACTIVE: dict[str, Any] | None = None

#: The split assignments that say which set every labeled document belongs to.
ASSIGNMENTS = Path(__file__).resolve().parents[2] / "config" / "splits" / "runbook-v2" / "assignments.jsonl"
#: Sets a train-pool reference may not be drawn beside: the pool is their examples (spec "References").
_REFUSED_SETS = ("calibration", "pool")


def _sha256(path: str | Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def activate(spec: Mapping[str, Any] | None, *, pool_sha256: str | None) -> None:
    """Turn the judge on for this process (``None`` turns it off).

    Refuses a reference pool whose bytes differ from the ones the run was locked with.
    """
    global _ACTIVE
    if not spec:
        deactivate()
        return
    pool = spec.get("reference_pool")
    if pool and spec.get("references") == "train_pool":
        actual = _sha256(pool)
        if actual is None or actual != pool_sha256:
            raise RuntimeError(
                f"judge: the reference pool {pool} changed after the run was locked "
                f"(locked {str(pool_sha256 or 'nothing')[:12]}, now {str(actual or 'missing')[:12]}); "
                "re-run preflight")
    with _LOCK:
        _ACTIVE = copy.deepcopy(dict(spec))


def deactivate() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None


def active() -> Mapping[str, Any] | None:
    return _ACTIVE


def judge_model(doc_type: str) -> str:
    """The correct-mode judge model for a document class: its override, else the default."""
    from mailroom_sandbox.job.spec import JUDGE_MODEL

    cfg = _ACTIVE or {}
    return str((cfg.get("models_by_class") or {}).get(doc_type) or cfg.get("model") or JUDGE_MODEL)


def judge_models(judge: Mapping[str, Any] | None) -> list[str]:
    """Token-billed models a ``judge:`` section (spec or lock dump) adds: correct mode only."""
    if not judge or judge.get("mode") != "correct":
        return []
    models = {str(judge.get("model") or ""), *map(str, (judge.get("models_by_class") or {}).values())}
    return sorted(model for model in models if model)


def _assigned_sets(path: Path = ASSIGNMENTS) -> dict[str, str]:
    sets: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                sets[str(row["id"])] = str(row.get("set") or "")
    return sets


def reference_set_errors(spec: Any, row_ids: Iterable[Any], *, sets: Mapping[str, str] | None = None) -> list[str]:
    """Refuse train-pool references on a draw holding calibration or pool documents."""
    judge = getattr(spec, "judge", None)
    if judge is None or judge.references != "train_pool":
        return []
    sets = _assigned_sets() if sets is None else sets
    hits: dict[str, list[str]] = {}
    for row_id in row_ids:
        name = sets.get(str(row_id))
        if name in _REFUSED_SETS:
            hits.setdefault(name, []).append(str(row_id))
    if not hits:
        return []
    found = ", ".join(f"{len(ids)} {name} ({', '.join(sorted(ids)[:3])})" for name, ids in sorted(hits.items()))
    return [f"judge.references: train_pool draws its examples from the pool, so the draw may hold no "
            f"calibration or pool documents; it holds {sum(map(len, hits.values()))}: {found}"]
