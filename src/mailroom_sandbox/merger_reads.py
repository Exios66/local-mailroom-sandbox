"""Phase 5 part 2: the process-wide merger-read and long-document head-read switches.

Set from the locked run spec at every runtime activation (``runtime.activate``), so a run's
choice never leaks into the next one; an unlocked eval leaves both off.

* ``job.merger`` (:func:`config`, :func:`on`): subclass-valid merger fields, MAUD question-group
  reads from located sections, and one targeted gap retry (HF-030, HF-031).
* ``job.long_document_head`` (:func:`head_active`): the sorter and intake read only the opening of
  a very long document on an API route (HF-032, HF-033).

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Head reads apply to documents longer than this many characters.
HEAD_THRESHOLD = 150_000
#: The sorter reads the first ``SORTER_HEAD`` and the last ``SORTER_TAIL`` characters.
SORTER_HEAD = 120_000
SORTER_TAIL = 8_000
#: Intake reads the first ``INTAKE_HEAD`` characters (its section map feeds only trace counts).
INTAKE_HEAD = 40_000

_SWITCHES = ("subclass_fields", "question_groups", "gap_retry")
_CONFIG: dict[str, Any] | None = None
_HEAD = False


def activate(cfg: Mapping[str, Any] | None) -> None:
    """Set the merger switches from a locked ``job.merger`` block (``None``: all off)."""
    global _CONFIG
    if not isinstance(cfg, Mapping) or not any(cfg.get(name) is True for name in _SWITCHES):
        _CONFIG = None
        return
    groups = cfg.get("groups", 3)
    _CONFIG = {**{name: cfg.get(name) is True for name in _SWITCHES},
               "groups": int(groups) if isinstance(groups, int) and 1 <= groups <= 3 else 3}


def config() -> dict[str, Any] | None:
    return None if _CONFIG is None else dict(_CONFIG)


def on(name: str) -> bool:
    return bool(_CONFIG and _CONFIG.get(name) is True)


def activate_head(enabled: bool) -> None:
    global _HEAD
    _HEAD = enabled is True


def head_active() -> bool:
    return _HEAD


def head_text(text: str, head: int, tail: int = 0) -> str:
    """The first ``head`` and last ``tail`` characters of ``text``, with a marker for the omitted middle."""
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    marker = f"\n\n[… {omitted} characters of the document omitted …]\n\n"
    return text[:head] + marker + (text[-tail:] if tail else "")
