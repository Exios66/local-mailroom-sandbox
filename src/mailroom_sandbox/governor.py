"""Phase 2 loop governor: one budget per document, counted across every pipeline node.

Switched on by ``job.governor`` (saved in the run lock, activated by ``runtime.activate``). Off,
nothing here changes a routing decision or a result field. Design:
``docs/superpowers/specs/2026-11-26-correcting-judge-design.md``, "The loop governor".
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from mailroom_sandbox.job.spec import GovernorSpec

_LOCK = threading.Lock()
_ACTIVE: GovernorSpec | None = None


def activate(spec: GovernorSpec | Mapping[str, Any] | None) -> None:
    """Set the process-wide governor (``None`` turns it off)."""
    global _ACTIVE
    resolved = None if spec is None else (spec if isinstance(spec, GovernorSpec) else GovernorSpec(**spec))
    with _LOCK:
        _ACTIVE = resolved


def active() -> GovernorSpec | None:
    return _ACTIVE


def call_budget(doc_type: str | None) -> int:
    """The model-call budget for one document of ``doc_type`` (the governor must be on)."""
    spec = _ACTIVE or GovernorSpec()
    return int(spec.calls_by_class.get(str(doc_type or ""), spec.calls))
