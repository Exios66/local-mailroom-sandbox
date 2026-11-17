"""Record a ``sandbox api eval`` report as a run the floor viewer can open.

``sandbox api eval --floor-run`` writes ``<base>/runtime/runs/<id>/`` with the same files a
job run leaves behind (``items.jsonl``, ``nodes.jsonl``, ``dataset.jsonl``,
``checkpoint.json``, ``spec.lock.json``), so ``sandbox floor`` shows the API's documents with
their classes, outcomes, Dojo extraction scores and label tiers.

The API exposes no per-node trace, so ``nodes.jsonl`` is rebuilt from each document's
hash-chained stage audit (``GET /audit/{doc_id}``): one record per audit event that names a
graph node. Nodes that write no audit event (``compile_report``, ``catalog_write``, the
review/arbiter hops without an entry) are absent from those paths, and the run's
``spec.lock.json`` says so (``engine.node_source = "stage-audit"``).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

# Stage-audit event -> the graph node that emits it (llm-mailroom _emit_stage_audit sites,
# plus the archivist's ``archived`` entry). Events not listed here are not node visits.
AUDIT_EVENT_NODE = {
    "ingested": "intake",
    "classified": "classify",
    "extracted": "extract",
    "arbiter_decided": "arbiter",
    "boss_adjudicated": "boss_escalation",
    "routed_to_review": "human_review",
    "archived": "archive",
}
# Dataset-row keys that carry document text: never copied into the run store.
_TEXT_KEYS = frozenset({"doc_text", "text", "content", "raw_text", "document_text"})
_SCORE_KEYS = ("overall_extraction_score", "scoring_method", "extraction_precision",
               "extraction_recall", "extraction_f1", "doc_type")


def _ts(value: Any) -> float | None:
    """ISO-8601 timestamp -> epoch seconds, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _audit_nodes(doc: str, audit: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """``nodes.jsonl`` records for one document from its stage audit, in chain order."""
    entries = (audit or {}).get("entries")
    if not isinstance(entries, list):
        return []
    out = []
    for entry in sorted((e for e in entries if isinstance(e, Mapping)), key=lambda e: e.get("seq") or 0):
        node = AUDIT_EVENT_NODE.get(str(entry.get("event") or ""))
        if node is None:
            continue
        detail = entry.get("detail") if isinstance(entry.get("detail"), Mapping) else {}
        out.append({"doc": doc, "node": node, "status": "done", "ts": entry.get("timestamp"),
                    "agent": entry.get("actor"), "stage": detail.get("stage"), "source": "stage-audit"})
    return out


def _latency_ms(records: Sequence[Mapping[str, Any]]) -> float | None:
    """Milliseconds between the first and last audit entry, or None with fewer than two."""
    times = [t for t in (_ts(r.get("ts")) for r in records) if t is not None]
    return round((max(times) - min(times)) * 1000, 1) if len(times) >= 2 else None


def _dataset_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """The fixture row as the run store keeps it: identity, labels and label provenance, no text."""
    return {k: v for k, v in row.items() if k not in _TEXT_KEYS}


def record_floor_run(
    report: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    base: Path,
    run_id: str,
    audit: Callable[[str], Mapping[str, Any]] | None = None,
) -> Path:
    """Write ``report`` (from :func:`family_api.run_api_eval`) as run ``run_id`` under ``base``.

    ``rows`` are the fixture rows that were uploaded, in order; ``audit`` fetches a
    document's stage audit by API ``doc_id`` (a failing fetch leaves that document without
    a node path). Refuses an existing run directory. Returns the run directory.
    """
    if not run_id or "/" in run_id or "\\" in run_id or run_id in (".", ".."):
        raise ValueError(f"invalid floor run id: {run_id!r}")
    run_dir = Path(base) / "runtime" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"floor run already exists: {run_dir}")

    by_id = {str(r.get("id")): r for r in rows}
    items: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    for doc in report.get("documents") or []:
        item_id = str(doc.get("id"))
        stage = doc.get("stage")
        recs: list[dict[str, Any]] = []
        if audit is not None and doc.get("doc_id"):
            try:
                recs = _audit_nodes(item_id, audit(str(doc["doc_id"])))
            except Exception:  # noqa: BLE001 — a missing audit trail must not lose the result
                recs = []
        nodes.extend(recs)
        extraction = doc.get("extraction") if isinstance(doc.get("extraction"), Mapping) else None
        items.append({
            "item_id": item_id,
            "ok": stage is not None and stage != "failed",
            "error": None if stage is not None else "not finished before the eval timeout",
            "pred": {"stage": stage, "doc_type": doc.get("doc_type"),
                     "classification_confidence": doc.get("classification_confidence"),
                     "extraction_confidence": doc.get("extraction_confidence"),
                     "escalation_reason": doc.get("escalation_reason")},
            "score": {k: extraction[k] for k in _SCORE_KEYS if k in extraction} if extraction else None,
            "latency_ms": _latency_ms(recs),
            "api_doc_id": doc.get("doc_id"),
        })

    dataset = [_dataset_row(by_id[str(d.get("id"))]) for d in report.get("documents") or []
               if str(d.get("id")) in by_id]
    mode = report.get("mode")
    files = {
        "items.jsonl": "".join(json.dumps(i, default=str) + "\n" for i in items),
        "nodes.jsonl": "".join(json.dumps(n, default=str) + "\n" for n in nodes),
        "dataset.jsonl": "".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in dataset),
        "checkpoint.json": json.dumps({
            "state": "complete" if report.get("ok") else "failed",
            "cursor": len(items), "total": int(report.get("n_rows") or len(items))}),
        "spec.lock.json": json.dumps({
            "profile": "api-eval",
            "engine": {"kind": "api-eval-mock" if mode == "mock" else "api-eval", "model": None,
                       "node_source": "stage-audit"},
            "api_eval": {"run_tag": report.get("run_tag"), "api_url": report.get("api_url"),
                         "mode": mode, "error": report.get("error")},
            **({"dataset": report["dataset"]} if report.get("dataset") else {}),
        }, indent=1, default=str),
    }
    # Write beside runs/ and rename into place, so a failed write never leaves a half run that
    # the floor lists and a retry with the same id refuses.
    staging = Path(base) / "runtime" / f".floor-run-{uuid.uuid4().hex[:12]}"
    staging.mkdir(parents=True)
    try:
        for name, text in files.items():
            (staging / name).write_text(text, encoding="utf-8")
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        if run_dir.exists():
            raise FileExistsError(f"floor run already exists: {run_dir}")
        os.rename(staging, run_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return run_dir
