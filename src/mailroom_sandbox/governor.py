"""Phase 2 loop governor: one budget per document, counted across every pipeline node.

Switched on by ``job.governor`` (saved in the run lock, activated by ``runtime.activate``). Off,
nothing here changes a routing decision or a result field. Design:
``docs/superpowers/specs/2026-11-26-correcting-judge-design.md``, "The loop governor".
"""

from __future__ import annotations

import threading
from collections.abc import Collection, Mapping
from typing import Any

from mailroom_sandbox.job.spec import GovernorSpec

_LOCK = threading.Lock()
_ACTIVE: GovernorSpec | None = None


def activate(spec: GovernorSpec | Mapping[str, Any] | None) -> None:
    """Set the process-wide governor (``None`` turns it off)."""
    global _ACTIVE
    resolved = None if spec is None else (spec if isinstance(spec, GovernorSpec) else GovernorSpec(**spec))
    with _LOCK:
        _ACTIVE = resolved


def active() -> GovernorSpec | None:
    return _ACTIVE


def call_budget(doc_type: str | None) -> int:
    """The model-call budget for one document of ``doc_type`` (the governor must be on)."""
    spec = _ACTIVE or GovernorSpec()
    return int(spec.calls_by_class.get(str(doc_type or ""), spec.calls))


#: Destinations that add a round: a retry, an arbiter call, a boss entry.
ROUND_DESTINATIONS = frozenset({"retry_classify", "retry_extract", "arbiter", "boss_escalation"})
_HISTORY_KEY = "extraction_attempt_history"  # graph.attempts.HISTORY_KEY


def _passed_judge(state: Mapping[str, Any]) -> bool:
    """The current extraction passed the judge.

    Phase 2 has no judge fixes yet, so this is a ``complete`` verdict (complete and accurate) that
    describes the latest extraction attempt. ``judge_findings`` is not read: the vendored judge
    stores its free-text reasoning there, even for a passing verdict.
    """
    if state.get("judge_verdict") != "complete":
        return False
    history = [e for e in state.get(_HISTORY_KEY) or [] if isinstance(e, Mapping)]
    return not history or history[-1].get("judge_verdict") == "complete"


def stop_destination(state: Mapping[str, Any], destinations: Collection[str]) -> str:
    """Where a stopped document goes: archive with caveats when it already passed, else a person."""
    return "compile_report" if _passed_judge(state) and "compile_report" in destinations else "human_review"


def _stop_reason(spec: GovernorSpec, scope: Mapping[str, Any], state: Mapping[str, Any], proposed: str) -> str | None:
    counters = scope["governor"]
    if proposed == "boss_escalation" and counters["boss"] >= 1:
        return "boss_repeat"
    if counters["retries"] >= spec.retries:
        return "retry_budget"
    if int(scope.get("llm_calls") or 0) >= call_budget(state.get("doc_type")):
        return "call_budget"
    if spec.spend_usd is not None and float(scope.get("spend_usd") or 0.0) >= spec.spend_usd:
        return "spend_budget"
    return None


def govern(node: str, state: Mapping[str, Any], proposed: str, destinations: Collection[str]) -> str:
    """The route after ``node``: ``proposed``, unless a round would pass the document's budget (HF-018)."""
    from mailroom_sandbox.job import call_guard

    spec, scope = _ACTIVE, call_guard.scope()
    if spec is None or scope is None:
        return proposed
    counters = scope["governor"]
    # L2: a sorter retry cannot beat the sorter's measured ceiling; a second opinion can.
    if (node == "classify" and proposed == "retry_classify" and spec.sorter_ceiling is not None
            and "review_classify" in destinations
            and float(state.get("classification_confidence") or 0.0) >= spec.sorter_ceiling):
        counters["skipped_classify_retries"] += 1
        return "review_classify"
    if proposed not in ROUND_DESTINATIONS or proposed == node:  # not a round, or a transient self-loop
        return proposed
    reason = _stop_reason(spec, scope, state, proposed)
    if reason is None:
        counters["retries"] += 1
        if proposed == "boss_escalation":
            counters["boss"] += 1
        return proposed
    dest = stop_destination(state, destinations)
    if "governor_stop" not in scope:
        scope["governor_stop"] = {
            "reason": reason, "outcome": "archive_with_caveats" if dest == "compile_report" else "human_review",
            "node": node, "proposed": proposed, "calls": int(scope.get("llm_calls") or 0),
            "retries": counters["retries"], "spend_usd": round(float(scope.get("spend_usd") or 0.0), 6)}
    return dest
