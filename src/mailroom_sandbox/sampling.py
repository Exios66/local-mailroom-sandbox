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

SAND-040 adds the rest of Qwen3's documented non-thinking sampling for those two
agents — ``top_p`` 0.8, ``top_k`` 20 (vLLM extra body) and a ``presence_penalty``
("reduce endless repetitions" in quantized models) — bound onto the agent's chat
model for the call, plus ``length_retries``: a call that ends in
``LengthFinishReasonError`` (a runaway decode at the output cap) is re-sampled up
to that many times. At temperature 0.7 the loops are stochastic (SAND-37/39 hit
different documents on every run), so a fresh draw usually closes the JSON.
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Mapping

_log = logging.getLogger("mailroom_sandbox.sampling")

_OVERRIDES: dict[str, float] = {}
_EXTRA: dict[str, dict[str, Any]] = {}  # agent → {top_p, top_k, presence_penalty, length_retries}
_PATCHED: set[str] = set()
_EXTRA_KEYS = ("top_p", "top_k", "presence_penalty", "length_retries")
# Per-agent count of LengthFinishReasonError calls re-sampled in this process.
LENGTH_RETRIES: dict[str, int] = {}

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


def extra_overrides(agent_knobs: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``{agent: {top_p, top_k, presence_penalty, length_retries}}`` from run-scoped knobs."""
    out: dict[str, dict[str, Any]] = {}
    for agent, knobs in (agent_knobs or {}).items():
        if not isinstance(knobs, Mapping):
            continue
        extra = {k: knobs[k] for k in _EXTRA_KEYS if knobs.get(k) is not None}
        if extra:
            out[str(agent)] = extra
    return out


def _bind_kwargs(extra: Mapping[str, Any]) -> dict[str, Any]:
    """OpenAI-compatible request kwargs; vLLM takes ``top_k`` through the extra body."""
    kw: dict[str, Any] = {}
    if extra.get("top_p") is not None:
        kw["top_p"] = float(extra["top_p"])
    if extra.get("presence_penalty") is not None:
        kw["presence_penalty"] = float(extra["presence_penalty"])
    if extra.get("top_k") is not None:
        kw["extra_body"] = {"top_k": int(extra["top_k"])}
    return kw


def _is_length_finish(exc: BaseException) -> bool:
    return type(exc).__name__ == "LengthFinishReasonError" or "length limit was reached" in str(exc)


def _wrap(original):
    signature = inspect.signature(original)

    @functools.wraps(original)
    def _call_structured(self, *args, **kwargs):
        name = str(getattr(self, "agent_name", ""))
        override = _OVERRIDES.get(name)
        extra = _EXTRA.get(name) or {}
        if override is None and not extra:
            return original(self, *args, **kwargs)
        bound = signature.bind(self, *args, **kwargs)
        if override is not None:
            bound.arguments["temperature"] = override
        bind_kw = _bind_kwargs(extra)
        retries = max(0, int(extra.get("length_retries") or 0))
        own_llm = "llm" in getattr(self, "__dict__", {})
        if bind_kw and callable(getattr(self, "llm", None)):
            base_llm = self.llm
            self.llm = lambda: base_llm().bind(**bind_kw)  # instance attr shadows the method for this call
        try:
            attempt = 0
            while True:
                try:
                    return original(*bound.args, **bound.kwargs)
                except Exception as exc:  # noqa: BLE001 — only the length class is retried
                    if attempt >= retries or not _is_length_finish(exc):
                        raise
                    attempt += 1
                    LENGTH_RETRIES[name] = LENGTH_RETRIES.get(name, 0) + 1
                    _log.warning("%s: runaway decode at the output cap — re-sampling (%d/%d)", name, attempt, retries)
        finally:
            if bind_kw and not own_llm and "llm" in getattr(self, "__dict__", {}):
                del self.llm

    _call_structured.__sandbox_sampling__ = True  # type: ignore[attr-defined]
    return _call_structured


def apply_sampling_overrides(agent_knobs: Mapping[str, Any] | None) -> dict[str, float]:
    """Install the wrapper (once per class) and set this run's overrides.

    Last call wins: an activation without temperature knobs clears earlier
    overrides, so the call-site values stand again. Returns the active map.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(temperature_overrides(agent_knobs))
    _EXTRA.clear()
    _EXTRA.update(extra_overrides(agent_knobs))
    if not _OVERRIDES and not _EXTRA:
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
    _log.info("specialist sampling overrides active: temperature %s · extra %s", _OVERRIDES, _EXTRA)
    return dict(_OVERRIDES)


def active_overrides() -> dict[str, float]:
    """The temperature overrides currently in force in this process."""
    return dict(_OVERRIDES)


def active_extra() -> dict[str, dict[str, Any]]:
    """The top_p / top_k / presence_penalty / length_retries overrides in force."""
    return {k: dict(v) for k, v in _EXTRA.items()}
