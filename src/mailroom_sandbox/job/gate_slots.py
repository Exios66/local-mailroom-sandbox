"""Decision-slot scoring for a gated pipeline run (llm-mailroom ``decision_slots``).

A run with decision slots exports, per document, ``decision_slot_outcomes`` and
``decision_slot_marks`` (``eval/runners.py``, ``DECISION_SLOT_FIELDS``). This module
turns the slice gate's per-document outcomes into the Dojo's per-slot summary (park,
release, capped and unavailable rates beside the pipeline's review and wrong-archive
rates) and a risk-coverage curve of the extraction gate's ``key_field_score`` over the
scorable archives: what share of those archives a further cutoff on that score would send
to review (the curve's ``review_rate``, NOT the run's) and what wrong-archive rate it would
leave. Parked documents are not on the curve: whether archiving them would have been wrong
is not scored. The caller passes the gated classes only, so the summary's pipeline rates
match the gate's pooled block; crashed documents are neither archived nor reviewed.

The scoring lives in llm-dojo-scoring (``analysis.risk_coverage``); a Dojo snapshot
without it gives ``available: False`` and the reason, never an error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_WRONG = {"wrong_archive": True, "correct_archive": False}


def _pred(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    item = doc.get("item") or {}
    pred = item.get("pred") if isinstance(item, Mapping) else None
    return pred if isinstance(pred, Mapping) else {}


def has_decision_slots(docs: Sequence[Mapping[str, Any]]) -> bool:
    """True when any document of the run recorded a decision slot."""
    return any(_pred(d).get("decision_slot_outcomes") or _pred(d).get("decision_slot_marks") for d in docs)


def slot_records(docs: Sequence[Mapping[str, Any]], statuses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One Dojo ``slot_decision_summary`` record per document (``docs`` and ``statuses`` aligned)."""
    records = []
    for doc, status in zip(docs, statuses):
        pred = _pred(doc)
        records.append({
            "final_stage": "archived" if status.get("stage") == "archived" else status.get("stage"),
            "wrong_archive": _WRONG.get(str(status.get("outcome"))),
            "decision_slot_outcomes": pred.get("decision_slot_outcomes") or {},
            "decision_slot_marks": pred.get("decision_slot_marks") or [],
        })
    return records


def gate_score_rows(docs: Sequence[Mapping[str, Any]], statuses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Risk-coverage rows: each archive's gate ``key_field_score`` and whether the gold scores it wrong."""
    rows = []
    for doc, status in zip(docs, statuses):
        if status.get("stage") != "archived":
            continue
        gate = _pred(doc).get("extraction_gate")
        score = gate.get("key_field_score") if isinstance(gate, Mapping) else None
        rows.append({"id": status.get("id"), "score": score, "wrong": _WRONG.get(str(status.get("outcome")))})
    return rows


def decision_slot_report(docs: Sequence[Mapping[str, Any]], statuses: Sequence[Mapping[str, Any]], *,
                         max_wrong_archive_rate: float | None = None) -> dict[str, Any] | None:
    """The run's per-slot summary and gate risk-coverage curve, or ``None`` when no slot ran."""
    if not has_decision_slots(docs):
        return None
    try:
        from llm_dojo_scoring.analysis.risk_coverage import (
            operating_point,
            risk_coverage_curve,
            slot_decision_summary,
        )
    except ImportError:
        return {"available": False,
                "reason": "llm-dojo-scoring has no analysis.risk_coverage; refresh the Dojo vendor snapshot"}
    curve = risk_coverage_curve(gate_score_rows(docs, statuses))
    out: dict[str, Any] = {"available": True, "summary": slot_decision_summary(slot_records(docs, statuses)),
                           "gate_risk_coverage": curve}
    if max_wrong_archive_rate is not None:
        # The slice gate compares the observed rate with its bar; the Wilson point is the stricter read.
        out["gate_operating_point"] = {
            "observed": operating_point(curve, max_wrong_archive_rate=max_wrong_archive_rate, use_upper=False),
            "upper95": operating_point(curve, max_wrong_archive_rate=max_wrong_archive_rate),
        }
    return out
