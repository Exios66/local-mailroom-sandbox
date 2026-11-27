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

import contextlib
import contextvars
import copy
import functools
import logging
import math
import re
import threading
from typing import Any, Iterable, Iterator, Mapping

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()
#: Process-wide like the governor: agent-task workers do not inherit the lock's ContextVar.
_ACTIVE: dict[str, Any] | None = None
#: The choice ``record_choice`` made for the extraction being set up: (class schema, schema sent,
#: schema the judge reviews against). The last differs from the one sent only under fields_only.
_PENDING: contextvars.ContextVar[tuple[dict, dict, dict, str | None] | None] = contextvars.ContextVar(
    "sandbox_subclass_schema", default=None)
#: Phase 4 field-only retry: the fields a judge-ordered re-extraction asks for (None: every field).
_ONLY: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar("sandbox_fields_only", default=None)
#: Extraction metadata a field-only schema keeps beside the named fields.
_KEEP_META = frozenset({"confidence", "reasoning"})

FALLBACK_SUBCLASSES = frozenset({"", "unknown", "other"})

_LIST_TYPES = frozenset({"list"})


def _is_list_type(kind: str) -> bool:
    base = kind.partition(":")[0]  # the registry spells list types "entity_list:name" and so on
    return base in _LIST_TYPES or base.endswith("_list")


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


def _confident(confidence: Any, low: float | None) -> bool:
    """A finite numeric confidence at or above ``low``; anything else (missing, NaN, text) falls back."""
    if isinstance(confidence, bool):
        return False
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and (low is None or value >= float(low))


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
    if not _confident(confidence, low):
        return base, "fallback:low_confidence"
    return _narrow(base, entry, guide=guide, curated=_curated(doc_class) if guide else frozenset()), "subclass"


def low_band(doc_class: str) -> float | None:
    """The class's ``low`` confidence band from the vendored taxonomy config."""
    from pipeline.config import get_confidence_thresholds

    value = get_confidence_thresholds(doc_class).get("low")
    return None if value is None else float(value)


def activate(lists: Mapping[str, Any] | None = None, *, sha256: str, guide: bool, note: bool = False) -> None:
    """Turn the switch on for this process; refuses a field list that differs from the lock's.

    ``note`` (``job.subclass_field_note``) also appends :func:`field_note` to the system prompt of
    a specialist sent a narrowed subclass schema.

    Without ``lists`` the committed file is read once, and the lists come from the same bytes the
    sha is taken of, so a file replaced between a parse and a hash cannot pass the lock check.
    """
    from mailroom_sandbox import subclass_fields

    global _ACTIVE
    if lists is None:
        lists, actual = subclass_fields.read_field_lists()
    else:
        actual = subclass_fields.field_lists_sha256()
    if sha256 != actual:
        raise RuntimeError(
            f"job.subclass_schemas: the subclass field list changed after the run was locked "
            f"(locked {sha256[:12] or 'nothing'}, now {actual[:12]}); re-run preflight")
    with _LOCK:
        _ACTIVE = {"lists": copy.deepcopy(dict(lists)), "guide": bool(guide), "note": bool(note)}


def deactivate() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None
    _PENDING.set(None)


def active() -> bool:
    return _ACTIVE is not None


def note_active() -> bool:
    return bool(_ACTIVE and _ACTIVE.get("note"))


def field_note(doc_class: str, subclass: str, base: Mapping[str, Any], schema: Mapping[str, Any]) -> str | None:
    """``job.subclass_field_note``: the block appended after a specialist's (frozen) system prompt.

    The promoted prompts are class-level text written before subclass schemas; some name fields
    the subclass schema no longer requests (the MAUD merger prompt sends consideration language to
    ``subject_matter`` or ``keywords``, which every non-fallback merger subclass drops). The strict schema stops
    a dropped field being written, not its content moving into a field that is still requested.
    The note is built from the two schemas only, so it follows the committed field lists. None
    when the field sets are equal (a fallback, or a subclass that drops and adds nothing).
    """
    base_fields = list((base.get("properties") or {}))
    fields = list((schema.get("properties") or {}))
    dropped = [name for name in base_fields if name not in fields]
    added = [name for name in fields if name not in base_fields]
    if not (dropped or added):
        return None
    lines = ["SUBCLASS FIELDS",
             f"This document was sorted as {doc_class} / {subclass}; the response schema lists the fields "
             "to fill for it."]
    if dropped:
        lines.append("Not requested for this subclass: " + ", ".join(f"`{n}`" for n in dropped)
                     + ". Where the instructions above ask for any of these, leave that content out; "
                     "never move it into another field.")
    if added:
        lines.append("Requested for this subclass in addition to the class fields: "
                     + ", ".join(f"`{n}`" for n in added) + " (see each field's description in the schema).")
    return "\n".join(lines)


@contextlib.contextmanager
def fields_only(names: Iterable[str]) -> Iterator[None]:
    """Phase 4 (HF-027): the extraction set up inside asks only for ``names`` (plus metadata)."""
    token = _ONLY.set(frozenset(str(n) for n in names))
    try:
        yield
    finally:
        _ONLY.reset(token)


def _restrict(schema: Mapping[str, Any], names: frozenset[str]) -> dict[str, Any]:
    out = copy.deepcopy(dict(schema))
    keep = names | _KEEP_META
    out["properties"] = {k: v for k, v in (out.get("properties") or {}).items() if k in keep}
    if "required" in out:
        out["required"] = [k for k in out.get("required") or () if k in out["properties"]]
    return out


def record_choice(state: Mapping[str, Any]) -> None:
    """HF-023: pick the schema for the extraction ``extract_node`` is about to run."""
    cfg, only = _ACTIVE, _ONLY.get()
    if cfg is None and only is None:
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
    schema, note = base, None
    if cfg is not None:
        schema, reason = choose_schema(doc_class, subclass, state.get("classification_confidence"), base,
                                       cfg["lists"], low=low_band(doc_class), guide=cfg["guide"])
        _log.info("subclass schema for %s: %s/%s -> %s", state.get("doc_id"), doc_class, subclass, reason)
        if cfg.get("note") and schema is not base:
            note = field_note(doc_class, str(subclass or "").strip(), base, schema)
    if only is not None:
        # The judge still reviews the whole (merged) extraction against the subclass schema.
        _PENDING.set((base, _restrict(schema, only), schema, note))
        return
    _PENDING.set(None if schema is base else (base, schema, schema, note))


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
    _record_review(None)
    if choice is None:
        return
    base, schema, review, note = choice
    cls = type(agent)
    if _composed_elsewhere(cls):
        _log.info("subclass schema for %s left to %s on %s.extract", getattr(agent, "doc_id", None) or "extraction",
                  getattr(cls.extract, _hotfix_mark(), None), cls.__name__)
        return
    _record_review(None if review is base else base, review)
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
    if note:
        _append_note(agent, note)


def _append_note(agent: Any, note: str) -> None:
    """``job.subclass_field_note``: this instance's default system prompt ends with ``note``.

    The note is added to the method the vendored call falls back to when the caller passes no
    ``system_prompt`` (no specialist passes one): ``augmented_system_prompt()`` for LangChain
    specialists (prompt, skills, tools, memory), ``system_prompt()`` for the legacy ``agents`` family
    (which appends its skill text later, in ``_call_llm``). The call's arguments are left alone, because
    the floor-read observer measures a caller-passed ``system_prompt`` as request text. The promoted
    prompt stays the head; only this one document's specialist instance is changed.
    """
    name = "augmented_system_prompt" if callable(getattr(type(agent), "augmented_system_prompt", None)) \
        else "system_prompt"
    default = getattr(agent, name)

    @functools.wraps(default)
    def with_note(*args: Any, **kwargs: Any) -> str:
        return f"{default(*args, **kwargs)}\n\n{note}"

    setattr(agent, name, with_note)


# --- HF-024: the judge and the arbiter see the fields the extraction was asked for ----------

_REVIEW_KEY = "subclass_schema"
_FIELD_LINE = re.compile(r"^  - ([A-Za-z0-9_]+):")


def _record_review(base: Mapping[str, Any] | None, schema: Mapping[str, Any] | None = None) -> None:
    """Keep the document's dropped and added fields in its call-guard scope (cleared on fallback)."""
    from mailroom_sandbox.job import call_guard

    scope = call_guard.scope()
    if scope is None:
        return
    if base is None or schema is None:
        scope.pop(_REVIEW_KEY, None)
        return
    before, after = dict(base.get("properties") or {}), dict(schema.get("properties") or {})
    scope[_REVIEW_KEY] = {"drop": sorted(set(before) - set(after)),
                          "add": {name: after[name] for name in sorted(set(after) - set(before))}}


def _review() -> Mapping[str, Any] | None:
    from mailroom_sandbox.job import call_guard

    scope = call_guard.scope()
    return None if scope is None else scope.get(_REVIEW_KEY)


def review_fields(fields: dict) -> dict:
    """HF-024: an extraction as the judge, arbiter and retry summary see it, without dropped fields."""
    review = _review()
    if not review:
        return fields
    dropped = set(review.get("drop") or ())
    return {k: v for k, v in fields.items() if k not in dropped}


def review_field_list(text: str) -> str:
    """HF-024: the judge's expected-field list without dropped fields, with added ones."""
    review = _review()
    if not review or not isinstance(text, str):
        return text
    dropped = set(review.get("drop") or ())
    lines = [line for line in text.split("\n")
             if not ((m := _FIELD_LINE.match(line)) and m.group(1) in dropped)]
    for name, spec in (review.get("add") or {}).items():
        kind = spec.get("type") if isinstance(spec, Mapping) else None
        lines.append(f"  - {name}: {'list' if kind == ['array', 'null'] else 'str'} | None")
    return "\n".join(lines)
