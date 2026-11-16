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
  and ``agents/arbiter.py`` (``SOURCE_CHARS``) each send only the start of the
  document, on their own window. Without context fit they ignore
  ``agents.judge.max_input_chars``; on a fitted route the sandbox raises them to
  the fitted budget. On longer documents they flag correct facts from later pages
  as fabrications and order re-extractions.
* **Degenerate inputs.** Near-empty rows (a 56-character "correspondence"
  document) can only end in review or a meaningless score.

The plan is informational: preflight records it and never fails on it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_MAX_CHUNKS = 4
DEFAULT_MIN_CHARS = 200
_DEFAULT_CHUNK_CHARS = 90_000
_DEFAULT_OVERLAP_CHARS = 8_000
_DEFAULT_BUDGET = 90_000
_CHARS_PER_TOKEN = 2.4
_PROMPT_OVERHEAD_TOKENS = 8000

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


def chunk_count(text: str, chunk_chars: int) -> int:
    """How many windows ``SpecialistAgent._split_chunks`` cuts ``text`` into.

    Paragraphs (``\\n\\n``) stay intact and an oversized paragraph is hard-split,
    so a document of large paragraphs can need more windows than ``len / chunk``.
    The overlap tail is prepended to later windows and does not change the count.
    """
    if len(text) <= chunk_chars:
        return 1
    count, current_len = 0, 0
    for para in (p for p in text.split("\n\n") if p.strip()):
        size = len(para)
        while size > chunk_chars:
            count += 1
            size -= chunk_chars
        if current_len and current_len + size + 2 > chunk_chars:
            count += 1
            current_len = 0
        current_len += size + 2
    return count + (1 if current_len else 0)


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


def _coverage(cls: str, agent: str, window: int | None, docs: list[tuple[str, int]], longest: int,
              entry: dict[str, Any], warnings: list[str]) -> None:
    """Record one agent's source coverage; each agent truncates on its own window."""
    if not window:
        return
    entry[f"{agent}_coverage_min"] = round(min(1.0, window / longest), 4) if longest else 1.0
    over = [d for d, n in docs if n > window]
    if over:
        warnings.append(
            f"{cls}: {len(over)}/{len(docs)} document(s) exceed the {agent} source window "
            f"({window} chars); the longest is {100 * window / longest:.0f}% visible, so "
            f"{agent} findings about later content are unverifiable"
        )


def plan(
    taxonomy: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    windows: Mapping[str, int | None] | None = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    min_chars: int = DEFAULT_MIN_CHARS,
    task: str = "pipeline",
    knobs: Mapping[str, Any] | None = None,
    models: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-class chunk, source-coverage and input-cost plan for ``rows`` under ``taxonomy``.

    ``models`` overrides an agent's taxonomy model for pricing (agent routes).

    ``task="pipeline"`` follows the graph: chunking per ``taxonomy["chunking"]``
    and judge/arbiter source windows. Any other task is an isolated specialist
    eval (``eval/agents.py:_live_specialist``): one ``extract`` call truncated at
    the budget unless the run gives that specialist a ``chunk_chars`` knob, and no
    judge or arbiter call.
    """
    windows = dict(source_windows() if windows is None else windows)
    pipeline = task == "pipeline"
    chunking = taxonomy.get("chunking") or {}
    cap = int(chunking.get("chunk_chars", _DEFAULT_CHUNK_CHARS))
    specialists = _specialists(taxonomy)
    knobs = knobs or {}
    texts: dict[str, list[tuple[str, str]]] = defaultdict(list)
    tiny: list[str] = []
    for row in rows:
        text = str(row.get("doc_text") or "")
        doc_id = str(row.get("id") or row.get("item_id") or "?")
        texts[str(row.get("expected_doc_class") or "unknown")].append((doc_id, text))
        if len(text.strip()) < min_chars:
            tiny.append(doc_id)

    classes: dict[str, Any] = {}
    warnings: list[str] = []
    for cls in sorted(texts):
        docs = [(d, len(t)) for d, t in texts[cls]]
        longest_id, longest = max(docs, key=lambda d: d[1])
        entry: dict[str, Any] = {"docs": len(docs), "max_chars": longest, "longest_doc": longest_id}
        specialist = specialists.get(cls)
        if specialist:
            budget = _budget(taxonomy, specialist)
            knob = knobs.get(specialist) or {}
            if pipeline:
                chunked = bool(chunking.get("enabled", True))
                chunk_chars, _ = window_plan(budget, chunking)
                knob_hint, window_cap = f"agent_knobs.{specialist}.max_input_chars", cap
            else:
                chunked = bool(knob.get("chunk_chars"))
                # _live_specialist falls back to 8,000 overlap on a missing *or zero* knob.
                spec_chunking = {"chunk_chars": knob.get("chunk_chars"),
                                 "overlap_chars": knob.get("overlap_chars") or _DEFAULT_OVERLAP_CHARS}
                chunk_chars, _ = window_plan(budget, spec_chunking) if chunked else (budget, 0)
                knob_hint = f"agent_knobs.{specialist}.max_input_chars or chunk_chars"
                window_cap = int(knob["chunk_chars"]) if chunked else budget
            # A shorter document of large paragraphs can need more windows than the longest.
            counts = [(chunk_count(t, chunk_chars), d, len(t)) for d, t in texts[cls]] if chunked else [(1, longest_id, longest)]
            per_pass, fan_doc, fan_chars = max(counts, key=lambda c: (c[0], c[2]))
            entry.update(specialist=specialist, input_budget=budget, chunked=chunked,
                         chunk_chars=chunk_chars if chunked else None, max_chunks_per_pass=per_pass,
                         max_chunks_doc=fan_doc)
            if pipeline:
                entry["input_cost_usd"] = _cost_envelope(
                    taxonomy, cls, specialist, longest, per_pass, window_plan(budget, chunking),
                    windows.get("judge"), windows.get("arbiter"), models or {})
            if not chunked and longest > budget:
                why = "chunking is disabled" if pipeline else "no chunk_chars knob (single pass)"
                warnings.append(f"{cls}: {why} and {specialist} max_input_chars={budget} "
                                f"truncates the longest document ({longest} chars)")
            elif per_pass > max_chunks and chunk_chars < window_cap:  # at the cap, a wider budget changes nothing
                warnings.append(
                    f"{cls}: document {fan_doc} ({fan_chars} chars) splits into ~{per_pass} chunks per "
                    f"extraction pass at {specialist} max_input_chars={budget}; on a long-context engine "
                    f"widen {knob_hint} (the window caps at chunk_chars={window_cap})"
                )
        if pipeline:
            _coverage(cls, "judge", windows.get("judge"), docs, longest, entry, warnings)
            _coverage(cls, "arbiter", windows.get("arbiter"), docs, longest, entry, warnings)
        classes[cls] = entry

    judge_w = windows.get("judge")
    configured = _budget(taxonomy, "judge") if "judge" in (taxonomy.get("agents") or {}) else None
    if pipeline and judge_w and configured and configured > judge_w:
        warnings.append(
            f"agents.judge.max_input_chars={configured} has no effect: the vendored judge sends at most "
            f"JUDGE_SOURCE_CHARS={judge_w} chars of source (context fit widens it only on a fitted route)"
        )
    if tiny:
        shown = ", ".join(tiny[:5]) + (" …" if len(tiny) > 5 else "")
        warnings.append(f"{len(tiny)} document(s) under {min_chars} chars of text: {shown}")
    fit = taxonomy.get("context_fit") or {}
    return {
        "task": task,
        "source_windows": windows if pipeline else {},
        "context_fit": {"applied": fit.get("applied") or {}, "chunk_chars": fit.get("chunk_chars")},
        "classes": classes,
        "tiny_docs": tiny,
        "warnings": warnings,
    }


# Providers billed per token; GPU-hour serving (Modal/vLLM) has no per-call price.
_TOKEN_BILLED = {"openrouter", "api"}


def _model(taxonomy: Mapping[str, Any], agent: str, models: Mapping[str, Any]) -> str | None:
    """The token-priced model behind ``agent``; None for GPU-hour or local serving."""
    cfg = (taxonomy.get("agents") or {}).get(agent) or {}
    override = models.get(agent)
    provider, model = cfg.get("provider"), cfg.get("model")
    if isinstance(override, Mapping):
        provider, model = override.get("provider") or provider, override.get("model") or model
    elif override:
        model = override
    return str(model) if model and str(provider or "") in _TOKEN_BILLED else None


def _calls_cost(model: str | None, calls: int, chars: int) -> float | None:
    from mailroom_sandbox.job.metrics import call_cost

    if calls <= 0:
        return 0.0
    tokens = chars / _CHARS_PER_TOKEN + _PROMPT_OVERHEAD_TOKENS
    return call_cost(model, calls * tokens, 0, calls=calls)


def _cost_envelope(taxonomy: Mapping[str, Any], cls: str, specialist: str, longest: int, per_pass: int,
                   window: tuple[int, int], judge_w: int | None, arbiter_w: int | None,
                   models: Mapping[str, Any]) -> dict[str, Any] | None:
    """Input cost of the class's longest document: clean path vs the full escalation loop.

    ``clean`` is one extraction pass with the judge skipped. ``judged`` adds one
    passing judge call. ``worst`` is every pass the thresholds allow:
    ``1 + arbiter_retry_max`` extractions, ``judge_max_passes`` judge calls and up
    to ``arbiter_retry_max + 1`` arbiter calls. Prompt sizes use 2.4 chars/token
    plus 8k tokens of prompt, so these are upper bounds. Tiered API prices apply
    per call. None when an agent is not token-billed (Modal/vLLM GPU-hour serving)
    or its model has no API price.
    """
    conf = taxonomy.get("confidence") or {}
    th = {**{k: v for k, v in conf.items() if k != "by_class"}, **((conf.get("by_class") or {}).get(cls) or {})}
    retries = int(th.get("arbiter_retry_max", 2))
    judge_passes = int(th.get("judge_max_passes", 1 + retries))
    chunk_chars, overlap = window
    chunk_in = min(longest, chunk_chars + (overlap if per_pass > 1 else 0))
    extract = _calls_cost(_model(taxonomy, specialist, models), per_pass, chunk_in)
    judge = _calls_cost(_model(taxonomy, "judge", models), 1, min(longest, judge_w or longest))
    arbiter = _calls_cost(_model(taxonomy, "arbiter", models), 1, min(longest, arbiter_w or longest))
    if None in (extract, judge, arbiter):
        return None
    worst = (1 + retries) * extract + judge_passes * judge + min(judge_passes, retries + 1) * arbiter
    return {"clean": round(extract, 5), "judged": round(extract + judge, 5), "worst": round(worst, 5),
            "worst_calls": {"extract_passes": 1 + retries, "judge": judge_passes,
                            "arbiter": min(judge_passes, retries + 1)}}


def plan_for_spec(spec: Any, rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """The plan under the taxonomy this run would activate (overlay + run ``agent_knobs``).

    ``knobs`` should be the snapshot preflight locks (``resolve_agent_knobs`` with the
    posture and ``SANDBOX_AGENT_KNOBS`` fallbacks); it defaults to resolving the same way.
    """
    from mailroom_sandbox.overlay import build_merged_taxonomy, load_profile

    knobs = kwargs.pop("knobs", None)
    if knobs is None:
        knobs = effective_knobs(spec)
    taxonomy = build_merged_taxonomy(
        load_profile(spec.profile),
        model_override=spec.engine.model,
        agent_models=spec.agent_models,
        agent_knobs=knobs,
        agent_routes=spec.agent_routes,
        extra_overlay={"confidence": spec.confidence} if getattr(spec, "confidence", None) else None,
    )
    if "models" not in kwargs:
        models: dict[str, Any] = {name: {"provider": route.provider, "model": route.model}
                                  for name, route in (spec.agent_routes or {}).items()}
        for name, model in (spec.agent_models or {}).items():
            models[name] = {**models.get(name, {}), "model": model}
        kwargs["models"] = models
    if "windows" not in kwargs:
        kwargs["windows"] = effective_windows(taxonomy)
    kwargs.setdefault("task", "pipeline" if spec.task == "pipeline" else "specialist")
    return plan(taxonomy, rows, knobs=knobs, **kwargs)


def effective_knobs(spec: Any) -> dict[str, Any]:
    """The run ``agent_knobs`` preflight writes into the lock."""
    from mailroom_sandbox.job.specialist_posture import agent_knobs_for_run
    from mailroom_sandbox.runtime import resolve_agent_knobs

    return resolve_agent_knobs(spec.agent_knobs or agent_knobs_for_run(spec.run_id))


def effective_windows(taxonomy: Mapping[str, Any], vendored: Mapping[str, int | None] | None = None) -> dict[str, int | None]:
    """Judge/arbiter windows this run would use: vendored, raised by context-fit."""
    from mailroom_sandbox.source_windows import windows_for

    out = dict(source_windows() if vendored is None else vendored)
    for agent, widened in windows_for(taxonomy).items():
        out[agent] = max(int(out.get(agent) or 0), widened)
    return out
