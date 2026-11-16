"""Audit-trail check for the production slice gate: every decision links to its trace and archive.

Offline and read-only. A finished run leaves three records and the gate requires all of them:

- the span mirror ``data/traces/<run_id>.spans.jsonl.gz`` (one JSON span per line; the document is
  ``attributes.item_id`` and the trace is the span's top-level ``trace_id``), written whatever the
  trace sink, so a ``trace.sink: none`` run still has one. ``spec.lock.json`` names only the run id
  and the sink, never this path, so the path is fixed by that convention;
- ``nodes.jsonl`` in the run dir (one record per node transition, the document under ``doc``);
- the hash archive ``data/archive/SANDBOX-sandbox_pipeline_<run_id>-<doc_id>/<class>/``, written for
  archived documents only (a review or a crash has no archive directory).

``audit_trail`` returns ``trace_ids`` and ``archives`` (``None`` where a document has none), the
``missing_spans`` / ``missing_nodes`` / ``missing_archive`` document ids, ``reasons`` (failing verdict
reasons, one line per kind) and ``ok``. A missing span mirror is one reason, not one per document.
The mirror is streamed line by line, never loaded whole.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

_ARCHIVE_PREFIX = "SANDBOX-sandbox_pipeline_"


def archive_path_for(run_id: str, doc_id: str, archive_dir: Path) -> Path:
    """The hash-archive directory of one document of a run."""
    return Path(archive_dir) / f"{_ARCHIVE_PREFIX}{run_id}-{doc_id}"


def default_dirs(run_dir: Path) -> tuple[Path, Path] | None:
    """``(traces_dir, archive_dir)`` of the checkout owning ``run_dir`` (``<data>/runtime/runs/<run_id>``).

    ``None`` when the run dir is not in that layout, so nothing can be located by guess.
    """
    run_dir = Path(run_dir).resolve()
    runs = run_dir.parent
    if runs.name != "runs" or runs.parent.name != "runtime":
        return None
    data = runs.parent.parent
    return data / "traces", data / "archive"


def _run_id(run_dir: Path) -> str:
    try:
        lock = json.loads((run_dir / "spec.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return run_dir.name
    return str(lock.get("run_id") or run_dir.name) if isinstance(lock, dict) else run_dir.name


def _stream_jsonl(path: Path, opener: Any):
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _trace_ids(spans_path: Path, wanted: set[str]) -> dict[str, str]:
    """``{doc_id: trace_id}`` for the wanted documents, streaming the span mirror."""
    found: dict[str, str] = {}
    for span in _stream_jsonl(spans_path, gzip.open):
        attrs = span.get("attributes") if isinstance(span, dict) else None
        doc_id = str((attrs or {}).get("item_id") or "")
        trace_id = span.get("trace_id") if isinstance(span, dict) else None
        if doc_id in wanted and trace_id and doc_id not in found:
            found[doc_id] = str(trace_id)
            if len(found) == len(wanted):
                break
    return found


def _node_docs(run_dir: Path) -> set[str]:
    path = run_dir / "nodes.jsonl"
    if not path.is_file():
        return set()
    return {str(n.get("doc")) for n in _stream_jsonl(path, open) if isinstance(n, dict) and n.get("doc")}


def _has_archive(path: Path) -> bool:
    return path.is_dir() and any(child.is_dir() for child in path.iterdir())


def audit_trail(run_dir: Path, doc_ids: list[str], archived: set[str], *,
                traces_dir: Path, archive_dir: Path) -> dict[str, Any]:
    """Link every document of a run to its trace id, node log and (when archived) archive directory."""
    run_dir = Path(run_dir)
    run_id = _run_id(run_dir)
    spans_path = Path(traces_dir) / f"{run_id}.spans.jsonl.gz"
    mirror = spans_path.is_file()
    traces = _trace_ids(spans_path, set(doc_ids)) if mirror else {}
    with_nodes = _node_docs(run_dir)
    archives: dict[str, str | None] = {}
    for doc_id in doc_ids:
        path = archive_path_for(run_id, doc_id, archive_dir)
        archives[doc_id] = str(path) if _has_archive(path) else None
    missing_spans = [d for d in doc_ids if d not in traces] if mirror else []
    missing_nodes = [d for d in doc_ids if d not in with_nodes]
    missing_archive = [d for d in doc_ids if d in archived and archives[d] is None]
    reasons = [] if mirror else [f"no span mirror at data/traces/{run_id}.spans.jsonl.gz"]
    for label, missing in (("spans", missing_spans), ("nodes", missing_nodes), ("archive", missing_archive)):
        if missing:
            reasons.append(f"missing {label}: {len(missing)}")
    return {"trace_ids": {d: traces.get(d) for d in doc_ids}, "archives": archives,
            "missing_spans": missing_spans, "missing_nodes": missing_nodes, "missing_archive": missing_archive,
            "span_mirror": mirror, "reasons": reasons, "ok": not reasons}
