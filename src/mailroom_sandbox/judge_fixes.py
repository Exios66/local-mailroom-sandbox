"""Phase 4 fix checking: a judge's proposed fix is applied only once the source supports it.

A fix names one field, a value and a quote. It is verified only when the field was one the
judge was asked about (and a target field of the class), the value is not blank once normalized
the way the scorer normalizes it (a fix can never erase a field), the value has the type the
pipeline's extraction model declares for the field, the quote is in the document, and the located text supports the value
under the gate's value rules (``gold_labels.evidence_support``). Nothing here calls a model.
"""

from __future__ import annotations

import copy
import functools
import inspect
from typing import Any, Collection, Mapping, TypedDict

from mailroom_sandbox import gold_labels


class FixCheck(TypedDict):
    field: str
    value: Any
    quote: str
    verified: bool
    why: str  # ok | not_requested | blank | wrong_type | quote_not_found | unsupported


def _blank(value: Any, ftype: str = "") -> bool:
    """Blank as written, or once the scorer's normalization drops whitespace-only items."""
    if value is None or (isinstance(value, str) and not value.strip()) or value == [] or value == {}:
        return True
    return gold_labels._is_empty(gold_labels._normalize(value, ftype))


def _type_ok(doc_class: str, field: str, value: Any) -> bool:
    """Whether ``value`` validates as the pipeline extraction model's type for ``field``."""
    from pydantic import TypeAdapter, ValidationError

    try:
        info = gold_labels._schema_bits(doc_class)[4].model_fields.get(field)
    except Exception:  # noqa: BLE001 — no model, no type to hold the fix to
        return True
    if info is None:
        return True
    try:
        TypeAdapter(info.annotation).validate_python(value)
    except ValidationError:
        return False
    return True


@functools.lru_cache(maxsize=8)
def _takes_subclass(fn: Any) -> bool:
    try:
        return "doc_subclass" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _target_fields(doc_class: str) -> frozenset[str]:
    try:
        return frozenset(gold_labels._schema_bits(doc_class)[0])
    except Exception:  # noqa: BLE001 — an unknown class has no target fields
        return frozenset()


def verify_fix(doc_class: str, doc_text: str, fix: Mapping[str, Any], *, requested: Collection[str],
               subclass: str | None = None) -> FixCheck:
    """Check one fix in order: requested, blank, type, quote located, value supported by the located text."""
    field = str(fix.get("field") or "")
    value = copy.deepcopy(fix.get("value"))
    quote = str(fix.get("quote") or "")

    def check(verified: bool, why: str) -> FixCheck:
        return {"field": field, "value": value, "quote": quote, "verified": verified, "why": why}

    if field not in set(requested) or field.startswith("_") or field not in _target_fields(doc_class):
        return check(False, "not_requested")
    ftype = str(gold_labels._schema_bits(doc_class)[0].get(field) or "")
    if _blank(value, ftype):
        return check(False, "blank")
    if not _type_ok(doc_class, field, value):
        return check(False, "wrong_type")
    span = gold_labels.locate(quote, doc_text) if quote.strip() else None
    if span is None:
        return check(False, "quote_not_found")
    support = gold_labels.evidence_support
    kwargs = {"doc_subclass": subclass} if _takes_subclass(support) else {}  # ruling 14 (#439)
    supported, _reason = support(doc_class, field, value, [span["text"]], **kwargs)
    return check(True, "ok") if supported else check(False, "unsupported")


def apply_fixes(extracted: Mapping[str, Any], checks: list[FixCheck]) -> dict[str, Any]:
    """``extracted`` with every verified fix written; every other key is kept as it was."""
    fixed = copy.deepcopy(dict(extracted or {}))
    for item in checks:
        if item.get("verified"):
            fixed[item["field"]] = copy.deepcopy(item["value"])
    return fixed
