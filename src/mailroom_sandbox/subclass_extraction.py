"""job.subclass_schemas (phase 3, X1): the predicted subclass picks the extraction schema.

:func:`choose_schema` turns (class, predicted subclass, classification confidence, class
schema) into the JSON schema the specialist is sent, using the committed field lists
(:mod:`mailroom_sandbox.subclass_fields`). It falls back to the class schema itself, the
same object, when the subclass is missing, ``unknown``, ``other`` or not listed, or
when the confidence is missing or below the class's ``low`` band. The sorter reports no
separate subclass confidence, so the class confidence decides.

HF-023 (``vendor_hotfixes``) applies the choice to the vendored extraction call while the
switch is active; see :func:`activate`. A corporate specialist whose ``extract`` another
hotfix wraps (the dedicated corporate composer) keeps that hotfix's schema.
"""

from __future__ import annotations

import contextvars
import copy
import functools
import logging
import threading
from typing import Any, Mapping

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()
#: Process-wide like the governor: agent-task workers do not inherit the lock's ContextVar.
_ACTIVE: dict[str, Any] | None = None
#: The choice ``record_choice`` made for the extraction being set up: (class schema, chosen schema).
_PENDING: contextvars.ContextVar[tuple[dict, dict] | None] = contextvars.ContextVar(
    "sandbox_subclass_schema", default=None)

FALLBACK_SUBCLASSES = frozenset({"", "unknown", "other"})

_LIST_TYPES = frozenset({"list"})


def _is_list_type(kind: str) -> bool:
    return kind in _LIST_TYPES or kind.endswith("_list")


def _added_property(spec: Mapping[str, Any]) -> dict[str, Any]:
    if _is_list_type(str(spec.get("type") or "")):
        return {"type": ["array", "null"], "items": {"type": "string"}}
    return {"type": ["string", "null"]}


def _curated(doc_class: str) -> frozenset[str]:
    """Fields whose description ``job.schema_guide`` already sets (its curated text wins)."""
    from mailroom_sandbox.schema_guide import GUIDE_DESCRIPTIONS

    return frozenset(GUIDE_DESCRIPTIONS.get(doc_class) or ())


def _narrow(base: Mapping[str, Any], entry: Mapping[str, Any], *, guide: bool, curated: frozenset[str] = frozenset()
            ) -> dict[str, Any]:
    schema = copy.deepcopy(dict(base))
    properties: dict[str, Any] = schema.setdefault("properties", {})
    required = list(schema.get("required") or [])
    strict = set(required) >= set(properties)
    dropped = set(entry.get("drop") or ())
    for name in dropped:
        properties.pop(name, None)
    required = [name for name in required if name not in dropped]
    for name, spec in (entry.get("add") or {}).items():
        properties[name] = _added_property(spec)
        if strict and name not in required:
            required.append(name)
    if guide:
        for name, text in (entry.get("guide") or {}).items():
            if name in properties and name not in curated and isinstance(properties[name], dict):
                properties[name]["description"] = text
    schema["required"] = required
    return schema


def choose_schema(
    doc_class: str,
    subclass: str | None,
    confidence: float | None,
    base: dict,
    lists: Mapping[str, Any],
    *,
    low: float | None,
    guide: bool,
) -> tuple[dict, str]:
    """Return ``(schema, reason)``; on fallback ``schema is base``. ``base`` is never mutated."""
    sub = str(subclass or "").strip()
    entry = ((lists.get("classes") or {}).get(doc_class) or {}).get(sub)
    if sub in FALLBACK_SUBCLASSES or entry is None:
        return base, "fallback:unknown"
    if confidence is None or (low is not None and float(confidence) < float(low)):
        return base, "fallback:low_confidence"
    return _narrow(base, entry, guide=guide, curated=_curated(doc_class) if guide else frozenset()), "subclass"


def low_band(doc_class: str) -> float | None:
    """The class's ``low`` confidence band from the vendored taxonomy config."""
    from pipeline.config import get_confidence_thresholds

    value = get_confidence_thresholds(doc_class).get("low")
    return None if value is None else float(value)


def activate(lists: Mapping[str, Any], *, sha256: str, guide: bool) -> None:
    """Turn the switch on for this process; refuses a field list that differs from the lock's."""
    from mailroom_sandbox.subclass_fields import field_lists_sha256

    global _ACTIVE
    actual = field_lists_sha256()
    if sha256 != actual:
        raise RuntimeError(
            f"job.subclass_schemas: the subclass field list changed after the run was locked "
            f"(locked {sha256[:12] or 'nothing'}, now {actual[:12]}); re-run preflight")
    with _LOCK:
        _ACTIVE = {"lists": copy.deepcopy(dict(lists)), "guide": bool(guide)}


def deactivate() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None
    _PENDING.set(None)


def active() -> bool:
    return _ACTIVE is not None


def record_choice(state: Mapping[str, Any]) -> None:
    """HF-023: pick the schema for the extraction ``extract_node`` is about to run."""
    cfg = _ACTIVE
    if cfg is None:
        _PENDING.set(None)
        return
    from langchain_agents.specialist_agents import SPECIALIST_SCHEMAS
    from pipeline.config import resolve_extract_class

    doc_type = str(state.get("doc_type") or "")
    doc_class = resolve_extract_class(doc_type) or doc_type
    base = SPECIALIST_SCHEMAS.get(doc_class)
    if base is None:
        _PENDING.set(None)
        return
    subclass = state.get("contract_subtype") if doc_class == "contract" else state.get("doc_subclass")
    schema, reason = choose_schema(doc_class, subclass, state.get("classification_confidence"), base,
                                   cfg["lists"], low=low_band(doc_class), guide=cfg["guide"])
    _log.info("subclass schema for %s: %s/%s -> %s", state.get("doc_id"), doc_class, subclass, reason)
    _PENDING.set(None if schema is base else (base, schema))


#: Specialists whose ``extract`` a corporate-schema hotfix may wrap (PR #425 composes its own
#: corporate request schema there); when one does, that hotfix owns the schema.
_COMPOSED_BY_OWN_HOTFIX = frozenset({"CorporateRecordsSpecialist"})


def _hotfix_mark() -> str:
    from mailroom_sandbox.vendor_hotfixes import _MARK

    return _MARK


def _composed_elsewhere(cls: type) -> bool:
    return cls.__name__ in _COMPOSED_BY_OWN_HOTFIX and bool(getattr(getattr(cls, "extract", None), _hotfix_mark(), None))


def bind_choice(agent: Any) -> None:
    """HF-023: give the extraction's specialist instance the recorded schema (consumed once).

    The instance-level ``_call_structured`` swaps ``json_schema`` only when it is the class
    schema object, then calls the class method (read-range observer, sampling, vendored call),
    so the swap holds for every chunk window of this agent and never reaches another agent.
    """
    choice = _PENDING.get()
    _PENDING.set(None)
    if choice is None:
        return
    base, schema = choice
    cls = type(agent)
    if _composed_elsewhere(cls):
        _log.info("subclass schema for %s left to %s on %s.extract", getattr(agent, "doc_id", None) or "extraction",
                  getattr(cls.extract, _hotfix_mark(), None), cls.__name__)
        return
    if getattr(agent, "schema", None) is base:
        # LangChain specialists also normalize and score evidence confidence on self.schema:
        # with the class schema there, every dropped field would count as "not found".
        agent.schema = schema

    @functools.wraps(cls._call_structured)
    def _call_structured(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("json_schema") is base:
            kwargs["json_schema"] = schema
        elif len(args) >= 2 and args[1] is base:  # (user_message, json_schema, ...)
            args = (args[0], schema, *args[2:])
        return cls._call_structured(agent, *args, **kwargs)  # resolved per call: observer, sampling

    agent._call_structured = _call_structured
