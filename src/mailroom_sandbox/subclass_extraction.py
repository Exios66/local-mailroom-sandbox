"""job.subclass_schemas (phase 3, X1): the predicted subclass picks the extraction schema.

:func:`choose_schema` turns (class, predicted subclass, classification confidence, class
schema) into the JSON schema the specialist is sent, using the committed field lists
(:mod:`mailroom_sandbox.subclass_fields`). It falls back to the class schema itself, the
same object, when the subclass is missing, ``unknown``, ``other`` or not listed, or
when the confidence is missing or below the class's ``low`` band. The sorter reports no
separate subclass confidence, so the class confidence decides.

HF-020 (``vendor_hotfixes``) applies the choice to the vendored extraction call while the
switch is active; see :func:`activate`.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

FALLBACK_SUBCLASSES = frozenset({"", "unknown", "other"})

_LIST_TYPES = frozenset({"list"})


def _is_list_type(kind: str) -> bool:
    return kind in _LIST_TYPES or kind.endswith("_list")


def _added_property(spec: Mapping[str, Any]) -> dict[str, Any]:
    if _is_list_type(str(spec.get("type") or "")):
        return {"type": ["array", "null"], "items": {"type": "string"}}
    return {"type": ["string", "null"]}


def _narrow(base: Mapping[str, Any], entry: Mapping[str, Any], *, guide: bool) -> dict[str, Any]:
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
            if name in properties and isinstance(properties[name], dict):
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
    return _narrow(base, entry, guide=guide), "subclass"


def low_band(doc_class: str) -> float | None:
    """The class's ``low`` confidence band from the vendored taxonomy config."""
    from pipeline.config import get_confidence_thresholds

    value = get_confidence_thresholds(doc_class).get("low")
    return None if value is None else float(value)
