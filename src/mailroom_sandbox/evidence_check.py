"""Phase 5 part 1 (B): drop list items a one-call read cannot quote from its document (HF-029).

On the OpenRouter route every document is read in one call, so the vendored ``evidence`` chunk
merge (``chunking.merge.policy``) never runs and nothing checks list items against the text. With
``job.evidence_check: true``, :func:`filter_one_read` applies the vendored single-window evidence
test (``langchain_agents.specialist_agents._item_support``) to the vendored evidence fields, with
the whole document as the window:

* an item is dropped only when the test returns ``False`` (it has a checkable quote and none of it,
  nor a reasoning quote for its field, is in the document); evidenced and unverifiable items stay;
* only string items are checked: ``str()`` of a dict would yield "fragments" that drop it wrongly;
* a chunked read (``_n_chunks``), a parse error or a missing document text is left alone;
* dropped items are recorded under ``_evidence_dropped`` (merged with an earlier record);
* a filter that would leave the extraction with no substantive content (the vendored guard's
  ``_has_substantive_content``) is not applied and is marked ``_evidence_skipped: "would_empty"``,
  so the check never turns a read into a failed one and never adds a retry call. ``keeps`` names
  the fields a field-only retry (HF-027) carries over from the previous extraction.

Design: docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_ACTIVE = False


def activate(enabled: bool) -> None:
    """Set the process-wide switch (every runtime activation sets it, so a run's choice never leaks)."""
    global _ACTIVE
    _ACTIVE = bool(enabled)


def active() -> bool:
    return _ACTIVE


def fields() -> tuple[str, ...]:
    """The vendored evidence fields (``_DEFAULT_EVIDENCE_FIELDS``): free text a model quotes."""
    from langchain_agents.specialist_agents import _DEFAULT_EVIDENCE_FIELDS

    return tuple(_DEFAULT_EVIDENCE_FIELDS)


def _entries(result: Mapping[str, Any]) -> list[dict]:
    reasoning = result.get("reasoning")
    entries = reasoning.get("entries") if isinstance(reasoning, Mapping) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def filter_one_read(result: Any, doc_text: str | None, *, keeps: Mapping[str, Any] | None = None) -> Any:
    """``result`` with its unevidenced list items dropped (a new dict), or ``result`` itself unchanged."""
    if not isinstance(result, Mapping) or "_n_chunks" in result or result.get("_parse_error"):
        return result
    if not isinstance(doc_text, str) or not doc_text.strip():
        return result
    from langchain_agents.specialist_agents import _fold, _item_support
    from pipeline.guards import _has_substantive_content

    text_norm, entries = _fold(doc_text), _entries(result)
    out, dropped = dict(result), {}
    for field in fields():
        items = result.get(field)
        if not isinstance(items, list):
            continue
        kept = [i for i in items if not isinstance(i, str) or _item_support(i, field, entries, text_norm) is not False]
        if len(kept) < len(items):
            out[field] = kept
            dropped[field] = [i for i in items if i not in kept]
    if not dropped:
        return result
    if _has_substantive_content(dict(result)) and not _has_substantive_content({**dict(keeps or {}), **out}):
        return {**dict(result), "_evidence_skipped": "would_empty"}
    earlier = result.get("_evidence_dropped")
    record = {k: list(v) for k, v in earlier.items()} if isinstance(earlier, Mapping) else {}
    for field, items in dropped.items():
        record[field] = record.get(field, []) + items
    out["_evidence_dropped"] = record
    return out
