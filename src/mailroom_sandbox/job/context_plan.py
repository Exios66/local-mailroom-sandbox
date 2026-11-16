"""Preflight context plan: how a run's input budgets meet its prepared documents.

Offline and model-free. It shows the run's input-budget risks before any spend:

* **Chunk fan-out.** The vendored graph splits a long document into windows of
  ``min(chunking.chunk_chars, max_input_chars - overlap)`` characters
  (``graph/build_graph.py:_run_chunked_extraction``). It makes one specialist
  call per window on every extraction pass. The overlay budgets fit a 16k-token
  L4 window, so they also apply to a long-context API run unless the run widens
  ``agent_knobs``. In pipeline-qwen-flash-25, each ~400k-character merger
  agreement split into ~14 windows per pass, three passes per document.
* **Judge and arbiter source coverage.** ``agents/judge.py`` (``JUDGE_SOURCE_CHARS``)
  and ``agents/arbiter.py`` (``SOURCE_CHARS``) send only the start of the document.
  They ignore ``agents.judge.max_input_chars``. On longer documents they flag
  correct facts from later pages as fabrications and order re-extractions.
* **Degenerate inputs.** Near-empty rows (a 56-character "correspondence"
  document) can only end in review or a meaningless score.

The plan is informational: preflight records it and never fails on it.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_MAX_CHUNKS = 4
DEFAULT_MIN_CHARS = 200
_DEFAULT_CHUNK_CHARS = 90_000
_DEFAULT_OVERLAP_CHARS = 8_000
_DEFAULT_BUDGET = 90_000

# Vendored constants the plan reads from source; importing the agents would pull
# the pipeline's LLM client stack into an offline preflight.
_SOURCE_WINDOWS = {
    "judge": ("agents/judge.py", "JUDGE_SOURCE_CHARS"),
    "arbiter": ("agents/arbiter.py", "SOURCE_CHARS"),
}


def source_windows(src_root: Path | None = None) -> dict[str, int | None]:
    """The judge/arbiter source windows (chars) as the vendored code defines them."""
    if src_root is None:
        from mailroom_sandbox.overlay import mailroom_taxonomy_path

        src_root = mailroom_taxonomy_path().parents[1]
    out: dict[str, int | None] = {}
    for agent, (rel, name) in _SOURCE_WINDOWS.items():
        value = None
        try:
            text = (src_root / rel).read_text(encoding="utf-8")
            match = re.search(rf"^{name}\s*=\s*([\d_]+)\s*$", text, re.MULTILINE)
            value = int(match.group(1).replace("_", "")) if match else None
        except OSError:
            value = None
        out[agent] = value
    return out


def window_plan(budget: int, chunking: Mapping[str, Any] | None) -> tuple[int, int]:
    """``(chunk_chars, overlap_chars)`` exactly as ``_run_chunked_extraction`` caps them."""
    cfg = chunking or {}
    chunk_chars = int(cfg.get("chunk_chars", _DEFAULT_CHUNK_CHARS))
    overlap = int(cfg.get("overlap_chars", _DEFAULT_OVERLAP_CHARS))
    overlap = min(overlap, max(0, budget // 8))
    return min(chunk_chars, max(1_000, budget - overlap)), overlap


def _specialists(taxonomy: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(c["key"]): str(c["specialist"])
        for c in taxonomy.get("doc_classes") or []
        if isinstance(c, Mapping) and c.get("key") and c.get("specialist") and c.get("status") != "retired"
    }


def _budget(taxonomy: Mapping[str, Any], agent: str) -> int:
    cfg = (taxonomy.get("agents") or {}).get(agent) or {}
    try:
        return int(cfg.get("max_input_chars") or _DEFAULT_BUDGET)
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET


def plan(
    taxonomy: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    windows: Mapping[str, int | None] | None = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> dict[str, Any]:
    """Per-class chunk and source-coverage plan for ``rows`` under ``taxonomy``."""
    windows = dict(source_windows() if windows is None else windows)
    chunking = taxonomy.get("chunking") or {}
    chunked = bool(chunking.get("enabled", True))
    cap = int(chunking.get("chunk_chars", _DEFAULT_CHUNK_CHARS))
    specialists = _specialists(taxonomy)
    lengths: dict[str, list[tuple[str, int]]] = defaultdict(list)
    tiny: list[str] = []
    for row in rows:
        text = str(row.get("doc_text") or "")
        doc_id = str(row.get("id") or row.get("item_id") or "?")
        lengths[str(row.get("expected_doc_class") or "unknown")].append((doc_id, len(text)))
        if len(text.strip()) < min_chars:
            tiny.append(doc_id)

    judge_w, arbiter_w = windows.get("judge"), windows.get("arbiter")
    classes: dict[str, Any] = {}
    warnings: list[str] = []
    for cls in sorted(lengths):
        docs = lengths[cls]
        longest_id, longest = max(docs, key=lambda d: d[1])
        entry: dict[str, Any] = {"docs": len(docs), "max_chars": longest, "longest_doc": longest_id}
        specialist = specialists.get(cls)
        if specialist:
            budget = _budget(taxonomy, specialist)
            chunk_chars, _ = window_plan(budget, chunking)
            per_pass = math.ceil(longest / chunk_chars) if chunked and longest > chunk_chars else 1
            entry.update(specialist=specialist, input_budget=budget, chunk_chars=chunk_chars,
                         max_chunks_per_pass=per_pass)
            if not chunked and longest > budget:
                warnings.append(f"{cls}: chunking is disabled and {specialist} max_input_chars={budget} "
                                f"truncates the longest document ({longest} chars)")
            elif per_pass > max_chunks and chunk_chars < cap:  # at the cap, a wider budget changes nothing
                warnings.append(
                    f"{cls}: longest document ({longest} chars) splits into ~{per_pass} chunks per "
                    f"extraction pass at {specialist} max_input_chars={budget}; on a long-context engine "
                    f"widen agent_knobs.{specialist}.max_input_chars (the window caps at "
                    f"chunking.chunk_chars={cap})"
                )
        if judge_w:
            entry["judge_coverage_min"] = round(min(1.0, judge_w / longest), 4) if longest else 1.0
        over = [d for d, n in docs if judge_w and n > judge_w]
        if over:
            pct = 100 * judge_w / longest
            warnings.append(
                f"{cls}: {len(over)}/{len(docs)} document(s) exceed the judge source window "
                f"({judge_w} chars; arbiter {arbiter_w}); the longest is {pct:.0f}% visible, so "
                "judge/arbiter findings about later content are unverifiable"
            )
        classes[cls] = entry

    configured = _budget(taxonomy, "judge") if "judge" in (taxonomy.get("agents") or {}) else None
    if judge_w and configured and configured > judge_w:
        warnings.append(
            f"agents.judge.max_input_chars={configured} has no effect: the vendored judge sends at most "
            f"JUDGE_SOURCE_CHARS={judge_w} chars of source (upstream fix)"
        )
    if tiny:
        shown = ", ".join(tiny[:5]) + (" …" if len(tiny) > 5 else "")
        warnings.append(f"{len(tiny)} document(s) under {min_chars} chars of text: {shown}")
    fit = taxonomy.get("context_fit") or {}
    return {
        "source_windows": windows,
        "context_fit": {"applied": fit.get("applied") or {}, "chunk_chars": fit.get("chunk_chars")},
        "classes": classes,
        "tiny_docs": tiny,
        "warnings": warnings,
    }


def plan_for_spec(spec: Any, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """The plan under the taxonomy this run would activate (overlay + run ``agent_knobs``)."""
    from mailroom_sandbox.overlay import build_merged_taxonomy, load_profile

    taxonomy = build_merged_taxonomy(
        load_profile(spec.profile),
        model_override=spec.engine.model,
        agent_models=spec.agent_models,
        agent_knobs=spec.agent_knobs,
        agent_routes=spec.agent_routes,
    )
    if "windows" not in kwargs:
        kwargs["windows"] = effective_windows(taxonomy)
    return plan(taxonomy, rows, **kwargs)


def effective_windows(taxonomy: Mapping[str, Any], vendored: Mapping[str, int | None] | None = None) -> dict[str, int | None]:
    """Judge/arbiter windows this run would use: vendored, raised by context-fit."""
    from mailroom_sandbox.source_windows import windows_for

    out = dict(source_windows() if vendored is None else vendored)
    for agent, widened in windows_for(taxonomy).items():
        out[agent] = max(int(out.get(agent) or 0), widened)
    return out
