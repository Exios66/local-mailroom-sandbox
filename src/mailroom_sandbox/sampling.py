"""Honor a run-scoped ``temperature`` knob for the specialist extraction calls.

Every vendored specialist passes ``temperature=0.1`` as a literal at its
``_call_structured`` call site (``agents/*_specialist.py`` and
``langchain_agents/specialist_agents.py``, drift-guarded — the sandbox must not
edit them). A ``temperature`` in the agent config therefore never reaches the
request. This wraps both base ``_call_structured`` implementations so an agent
named in a run-scoped override (``SANDBOX_AGENT_KNOBS``) is sampled at that
temperature; every other agent keeps its call-site value.

SAND-037: the contracts and merger specialists decode under the JSON-schema
grammar (``with_structured_output(method="json_schema")``). At 0.1 they looped
until every completion cap they were given (4096, 8192, 16384) while their
longest successful outputs were ≈ 1.7k–4.1k tokens, and job retries replayed
the same loop. The grid runs those two agents at 0.7.
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Mapping

_log = logging.getLogger("mailroom_sandbox.sampling")

_OVERRIDES: dict[str, float] = {}
_PATCHED: set[str] = set()

# (module, class) of every vendored ``_call_structured`` implementation.
_TARGETS: tuple[tuple[str, str], ...] = (
    ("agents.base", "BaseAgent"),
    ("langchain_agents.base_agent", "BaseAgent"),
)


def temperature_overrides(agent_knobs: Mapping[str, Any] | None) -> dict[str, float]:
    """``{agent: temperature}`` for every agent whose run-scoped knobs set one."""
    out: dict[str, float] = {}
    for agent, knobs in (agent_knobs or {}).items():
        if isinstance(knobs, Mapping) and knobs.get("temperature") is not None:
            out[str(agent)] = float(knobs["temperature"])
    return out


def _wrap(original):
    signature = inspect.signature(original)

    @functools.wraps(original)
    def _call_structured(self, *args, **kwargs):
        override = _OVERRIDES.get(str(getattr(self, "agent_name", "")))
        if override is None:
            return original(self, *args, **kwargs)
        bound = signature.bind(self, *args, **kwargs)
        bound.arguments["temperature"] = override
        return original(*bound.args, **bound.kwargs)

    _call_structured.__sandbox_sampling__ = True  # type: ignore[attr-defined]
    return _call_structured


def apply_sampling_overrides(agent_knobs: Mapping[str, Any] | None) -> dict[str, float]:
    """Install the wrapper (once per class) and set this run's overrides.

    Last call wins: an activation without temperature knobs clears earlier
    overrides, so the call-site values stand again. Returns the active map.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(temperature_overrides(agent_knobs))
    if not _OVERRIDES:
        return {}
    for module_name, class_name in _TARGETS:
        key = f"{module_name}.{class_name}"
        if key in _PATCHED:
            continue
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
        except Exception as exc:  # noqa: BLE001 — optional (pipeline extra)
            _log.debug("%s unavailable — temperature override skipped: %s", key, exc)
            continue
        original = cls.__dict__.get("_call_structured")
        if original is None or getattr(original, "__sandbox_sampling__", False):
            _PATCHED.add(key)
            continue
        if "temperature" not in inspect.signature(original).parameters:
            _log.warning("%s._call_structured has no temperature parameter — not patched", key)
            continue
        cls._call_structured = _wrap(original)
        _PATCHED.add(key)
    _log.info("specialist temperature overrides active: %s", _OVERRIDES)
    return dict(_OVERRIDES)


def active_overrides() -> dict[str, float]:
    """The temperature overrides currently in force in this process."""
    return dict(_OVERRIDES)
