"""Widen the vendored judge/arbiter source excerpts for long-context routes.

``agents/judge.py`` (``JUDGE_SOURCE_CHARS``, also bound as the ``_truncate``
default) and ``agents/arbiter.py`` (``SOURCE_CHARS`` and
``CLASSIFICATION_SOURCE_CHARS``) hardcode a 16k-char excerpt and ignore
``agents.<name>.max_input_chars``. The vendor files are drift-guarded, so the
sandbox cannot edit them. On a 400k-char merger agreement the judge then sees 4%
of the text and flags facts from later pages as fabrications. The classification
arbiter sends every longer document to a person without a model call.

When ``judge`` / ``arbiter`` were context-fitted (:mod:`mailroom_sandbox.context_fit`),
this sets those literals to the fitted budget. It only ever raises them. On every
other activation it restores the vendored values, so a Modal run in the same
process never inherits a widened window. This is a stopgap until llm-mailroom
exposes the windows as config (upstream v0.30/v0.31 handoff).
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Mapping

_log = logging.getLogger("mailroom_sandbox.source_windows")

# agent → [(module, attribute)] the vendored code reads at call time.
TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "judge": (("agents.judge", "JUDGE_SOURCE_CHARS"),),
    "arbiter": (("agents.arbiter", "SOURCE_CHARS"), ("agents.arbiter", "CLASSIFICATION_SOURCE_CHARS")),
}
_ORIGINAL: dict[str, int] = {}


def windows_for(taxonomy: Mapping[str, Any]) -> dict[str, int]:
    """Agent → widened source window, for agents whose budget was context-fitted."""
    from mailroom_sandbox.context_fit import fitted_budget

    return {agent: budget for agent in TARGETS if (budget := fitted_budget(taxonomy, agent))}


def _set_judge_truncate_default(module: Any, value: int) -> None:
    judge_cls = getattr(module, "CompletenessJudge", None)
    raw = vars(judge_cls).get("_truncate") if judge_cls is not None else None
    func = getattr(raw, "__func__", raw)
    if func is not None and func.__defaults__ and len(func.__defaults__) == 1:
        func.__defaults__ = (int(value),)


def apply_source_windows(windows: Mapping[str, int] | None) -> dict[str, int]:
    """Set every target to ``max(vendored, windows[agent])``; restore the rest.

    Returns ``"module.attr" → effective value``. Empty when the vendored agents
    cannot be imported (pipeline extra missing).
    """
    windows = windows or {}
    effective: dict[str, int] = {}
    for agent, targets in TARGETS.items():
        for module_name, attr in targets:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 — optional (pipeline extra)
                _log.debug("%s unavailable — source window left alone: %s", module_name, exc)
                continue
            key = f"{module_name}.{attr}"
            if not hasattr(module, attr):
                _log.warning("%s missing — vendor drift; source window not applied", key)
                continue
            original = _ORIGINAL.setdefault(key, int(getattr(module, attr)))
            value = max(original, int(windows.get(agent) or 0))
            setattr(module, attr, value)
            if attr == "JUDGE_SOURCE_CHARS":
                _set_judge_truncate_default(module, value)
            effective[key] = value
    widened = {k: v for k, v in effective.items() if v != _ORIGINAL.get(k)}
    if widened:
        _log.info("judge/arbiter source windows widened: %s", widened)
    return effective


def unavailable_targets() -> list[str]:
    """``module.attr`` keys whose vendored window cannot be widened.

    Empty when the pipeline extra is installed and the attributes are present.
    Activation still continues if this is non-empty; preflight does not, once a
    judge or arbiter was context-fitted.
    """
    missing: list[str] = []
    for targets in TARGETS.values():
        for module_name, attr in targets:
            key = f"{module_name}.{attr}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 — optional extra
                _log.debug("%s unavailable: %s", module_name, exc)
                missing.append(key)
                continue
            if not hasattr(module, attr):
                missing.append(key)
    return missing


def vendored_windows() -> dict[str, int]:
    """The vendored values captured before any override (empty until first apply)."""
    return dict(_ORIGINAL)
