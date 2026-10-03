"""Resolve report grouping from a run ID or its locked experiment metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SAND_TOKEN = re.compile(r"(?:^|[^A-Za-z0-9])SAND[-_]?0*(\d+)(?!\d)", re.IGNORECASE)
_SWEEP_FIELDS = ("experiment", "experiment_id", "sweep", "sweep_id", "runbook", "runbook_id", "config", "config_path")


def experiment_prefix(run_id: str | None, metadata: Mapping[str, Any] | None = None) -> str | None:
    """Return ``SAND-NN`` only when the run is associated with a named sweep."""
    candidates = [str(run_id or "")]
    if isinstance(metadata, Mapping):
        candidates.extend(str(metadata.get(key) or "") for key in _SWEEP_FIELDS)

    for candidate in candidates:
        match = _SAND_TOKEN.search(candidate)
        if match:
            return f"SAND-{int(match.group(1))}"

    if any(re.match(r"^grid(?:[-_]|$)", candidate.strip(), re.IGNORECASE) for candidate in candidates):
        return "SAND-37"
    return None