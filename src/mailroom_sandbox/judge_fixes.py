"""Phase 4 fix checking: a judge's proposed fix is applied only once the source supports it.

A fix names one field, a value and a quote. It is verified only when the field was one the
judge was asked about (and a target field of the class), the value is not blank (a fix can
never erase a field), the quote is in the document, and the located text supports the value
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
    why: str  # ok | not_requested | blank | quote_not_found | unsupported


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == [] or value == {}


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
    """Check one fix in order: requested, blank, quote located, value supported by the located text."""
    field = str(fix.get("field") or "")
    value = copy.deepcopy(fix.get("value"))
    quote = str(fix.get("quote") or "")

    def check(verified: bool, why: str) -> FixCheck:
        return {"field": field, "value": value, "quote": quote, "verified": verified, "why": why}

    if field not in set(requested) or field.startswith("_") or field not in _target_fields(doc_class):
        return check(False, "not_requested")
    if _blank(value):
        return check(False, "blank")
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
