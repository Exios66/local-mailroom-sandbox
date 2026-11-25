"""Size whole-document agents' input budgets to their model's real context window.

The overlay's specialist ``max_input_chars`` values fit the 16k-token L4 window
that Modal vLLM serves. The vendored graph caps each extraction chunk at that
budget (``graph/build_graph.py:_run_chunked_extraction``), so the same budgets
make a 1M-context OpenRouter model (``qwen/qwen3.7-flash``) chunk a 400k-char
merger agreement into ~14 windows per pass.

The sorter, sorter_reviewer and intake are fitted the same way: the vendored sorter and
intake slide windows over the whole document at their budget, so an unfitted 12k budget
reads a 380k-char merger agreement in ~100 calls.

For agents routed to a long-context API provider, this raises the budget to what
the model's ``context_length`` (``config/api_prices.yaml``) actually holds:
``(context_length - max_tokens - reserve_tokens) * chars_per_token``. A document
that fits is then extracted in one call. Modal, vLLM, Ollama and other local
routes keep the overlay posture unchanged, and so does any model without a
known context length. Budgets are only ever raised. Explicit run
``agent_knobs`` are applied afterwards and still win.

When every specialist that could exceed the global ``chunking.chunk_chars`` cap
is context-fitted, the cap rises to the largest fitted budget, so chunking only
happens when a document is longer than the model can take. Each agent's own
budget still bounds its windows.

The judge and arbiter source windows are vendored literals; see
:mod:`mailroom_sandbox.source_windows`. They follow the fitted ``judge`` /
``arbiter`` budgets recorded under ``context_fit.applied``.
"""
from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from functools import lru_cache
from typing import Any, Mapping

import yaml

_log = logging.getLogger("mailroom_sandbox.context_fit")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    # Measured on dense SEC filings (SAND-018); a low ratio under-fills, never overflows.
    "chars_per_token": 2.4,
    # Prompt template, schema, handoff and extraction JSON beside the document.
    "reserve_tokens": 8000,
    "providers": ["openrouter"],
    # Agents that must read the whole document; "specialists" expands to every
    # live doc-class specialist. The vendored sorter and intake slide windows over
    # the WHOLE document at their budget (agents/sorter.py, agents/intake.py), so a
    # 12k/25k budget turns a 380k-char merger into ~100 calls on a 1M-context model:
    # they are fitted too, and read a document that fits in one call.
    "agents": ["specialists", "judge", "arbiter", "sorter", "sorter_reviewer", "intake"],
}
_DEFAULT_CHUNK_CHARS = 90_000


@lru_cache(maxsize=1)
def _price_sheet_contexts() -> dict[str, int]:
    from mailroom_sandbox.paths import config_dir

    try:
        doc = yaml.safe_load((config_dir() / "api_prices.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        _log.warning("config/api_prices.yaml unreadable — no context-fit: %s", exc)
        return {}
    out: dict[str, int] = {}
    for model, row in (doc.get("models") or {}).items():
        try:
            length = int((row or {}).get("context_length") or 0)
        except (TypeError, ValueError):
            continue
        if length > 0:
            out[str(model)] = length
    return out


def api_context_lengths() -> dict[str, int]:
    """Model id → context window (tokens) from the API price sheet."""
    return dict(_price_sheet_contexts())


def fit_chars(context_tokens: int, max_tokens: int, cfg: Mapping[str, Any]) -> int:
    room = int(context_tokens) - int(max_tokens) - int(cfg["reserve_tokens"])
    return max(0, int(room * float(cfg["chars_per_token"])))


#: Tokens held back from a Decisions classify call for the question payload (document text is the rest).
DECISION_QUESTION_RESERVE_TOKENS = 80_000


def decision_document_chars(context_tokens: int, *, question_reserve_tokens: int = DECISION_QUESTION_RESERVE_TOKENS,
                            chars_per_token: float | None = None) -> int:
    """Characters of document text that fit beside the questions in a Decisions classify call.

    The model's context is about a million tokens. The question payload is not part of
    ``max_input_chars`` (that cap slices the document only), so this reserve keeps the
    document plus the questions inside the window at the dense-filing chars/token ratio.
    """
    ratio = float(DEFAULTS["chars_per_token"] if chars_per_token is None else chars_per_token)
    room = int(context_tokens) - int(question_reserve_tokens)
    return max(0, int(room * ratio))


def _route_field(route: Any, key: str) -> Any:
    if route is None:
        return None
    if isinstance(route, Mapping):
        return route.get(key)
    return getattr(route, key, None)


def _specialists(taxonomy: Mapping[str, Any]) -> set[str]:
    return {
        str(c["specialist"])
        for c in taxonomy.get("doc_classes") or []
        if isinstance(c, Mapping) and c.get("specialist") and c.get("status") != "retired"
    }


def _targets(cfg: Mapping[str, Any], specialists: set[str]) -> set[str]:
    names: set[str] = set()
    for name in cfg.get("agents") or []:
        names |= specialists if name == "specialists" else {str(name)}
    return names


def _budget(agent: Mapping[str, Any]) -> int:
    try:
        return int(agent.get("max_input_chars") or 0)
    except (TypeError, ValueError):
        return 0


def _routes_checked(cfg: Mapping[str, Any], taxonomy: Mapping[str, Any], routes: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Provider and model each reader would use. An explicit route wins over the profile."""
    agents = taxonomy.get("agents") or {}
    checked: dict[str, dict[str, str]] = {}
    for name in sorted(_targets(cfg, _specialists(taxonomy))):
        agent = agents.get(name)
        if not isinstance(agent, dict):
            continue
        route = routes.get(name)
        checked[name] = {
            "provider": str(_route_field(route, "provider") or agent.get("provider") or ""),
            "model": str(_route_field(route, "model") or agent.get("model") or ""),
        }
    return checked


def apply_context_fit(
    taxonomy: dict,
    *,
    agent_routes: Mapping[str, Any] | None = None,
    contexts: Mapping[str, int] | None = None,
) -> dict:
    """Return a copy of ``taxonomy`` with long-context agents' budgets fitted.

    Records what changed under ``taxonomy["context_fit"]["applied"]`` (agent →
    model, context_length, before, after) and the chunk cap under ``chunk_chars``.
    """
    cfg = {**DEFAULTS, **(taxonomy.get("context_fit") or {})}
    cfg.pop("applied", None)
    cfg.pop("checked", None)
    out = deepcopy(taxonomy)
    chunking = out.setdefault("chunking", {})
    cap = int(chunking.get("chunk_chars", _DEFAULT_CHUNK_CHARS))
    record: dict[str, Any] = {**cfg, "applied": {}, "checked": {}, "chunk_chars": {"before": cap, "after": cap}}
    out["context_fit"] = record
    # Record routes even when fitting is off, so preflight still sees an OpenRouter
    # override on a local profile and can reject a short reader.
    record["checked"] = _routes_checked(cfg, out, agent_routes or {})
    if not cfg.get("enabled", True):
        return out
    contexts = api_context_lengths() if contexts is None else contexts
    providers = {str(p) for p in cfg.get("providers") or []}
    specialists = _specialists(out)
    agents = out.get("agents") or {}
    for name, choice in record["checked"].items():
        agent = agents[name]
        provider = choice["provider"]
        model = choice["model"]
        context = contexts.get(model)
        if provider not in providers or not context:
            continue
        before = _budget(agent)
        after = fit_chars(context, int(agent.get("max_tokens") or 4096), cfg)
        if after <= before:
            continue
        agent["max_input_chars"] = after
        record["applied"][name] = {"model": model, "context_length": context, "before": before, "after": after}
    _raise_chunk_cap(chunking, record, specialists, agents, cap)
    if record["applied"]:
        _log.info("context-fit budgets: %s", {k: v["after"] for k, v in record["applied"].items()})
    return out


def _raise_chunk_cap(chunking: dict, record: dict, specialists: set[str], agents: Mapping[str, Any], cap: int) -> None:
    """Raise the chunk cap only when every wide specialist was fitted."""
    applied = record["applied"]
    fitted = [applied[name]["after"] for name in specialists if name in applied]
    wide = sorted(name for name in specialists if name not in applied and _budget(agents.get(name) or {}) > cap)
    if not fitted:
        return
    if wide:
        _log.warning("chunk cap left at %s: unfitted specialists %s have wider budgets", cap, wide)
        return
    chunking["chunk_chars"] = max(cap, *fitted)
    record["chunk_chars"]["after"] = chunking["chunk_chars"]


# Vendored judge/arbiter excerpts. A fitted route must swap these on; a budget
# that is already wide does not, because the literals ignore max_input_chars.
_VENDORED_SOURCE_CHARS = 16_000
_SOURCE_AGENTS = ("judge", "arbiter")


def _checked_route(taxonomy: Mapping[str, Any], name: str, agent: Mapping[str, Any]) -> tuple[str, str]:
    choice = ((taxonomy.get("context_fit") or {}).get("checked") or {}).get(name) or {}
    provider = str(choice.get("provider") or agent.get("provider") or "")
    model = str(choice.get("model") or agent.get("model") or "")
    return provider, model


def _fitted_room(agent: Mapping[str, Any], model: str, on_route: bool, contexts: Mapping[str, int], cfg: Mapping[str, Any]) -> tuple[int | None, int | None]:
    context = contexts.get(model) if on_route else None
    room = fit_chars(context, int(agent.get("max_tokens") or 4096), cfg) if context else None
    return context, room


def _above_pre_fit(budget: int, before: int | None, in_applied: bool) -> bool:
    return in_applied and before is not None and budget > before


def _covers_fitted_room(name: str, budget: int, room: int | None, in_applied: bool) -> bool:
    covers = room is not None and budget >= room
    window_ok = name not in _SOURCE_AGENTS or in_applied
    return covers and window_ok


def _window_not_swapped(name: str, room: int | None, in_applied: bool) -> bool:
    return name in _SOURCE_AGENTS and room is not None and room > _VENDORED_SOURCE_CHARS and not in_applied


def _expansion_gap(name: str, model: str, budget: int, context: int | None, room: int | None, before: int | None, *, on_route: bool, in_applied: bool) -> tuple[bool | None, str | None]:
    """Whether one reader is expanded, and the gap text when a long-context route is still short."""
    if not on_route:
        return None, None
    if not context:
        return False, (
            f"{name}: model {model} has no context_length in config/api_prices.yaml, "
            f"so its input length stays {budget}"
        )
    if _above_pre_fit(budget, before, in_applied):
        return True, None
    if _covers_fitted_room(name, budget, room, in_applied):
        return True, None
    if _window_not_swapped(name, room, in_applied):
        return False, (
            f"{name}: source window stays at {_VENDORED_SOURCE_CHARS} chars; "
            "the expanded length was not swapped on"
        )
    return False, f"{name}: max_input_chars={budget} was not expanded (fitted room {room})"


def _reader_status(taxonomy: Mapping[str, Any], name: str, agent: Mapping[str, Any], providers: set[str], contexts: Mapping[str, int], applied: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    provider, model = _checked_route(taxonomy, name, agent)
    budget = _budget(agent)
    context, room = _fitted_room(agent, model, provider in providers, contexts, cfg)
    before = int(applied[name]["before"]) if name in applied else None
    expanded, gap = _expansion_gap(
        name, model, budget, context, room, before, on_route=provider in providers, in_applied=name in applied,
    )
    return {
        "agent": name,
        "provider": provider,
        "model": model,
        "max_input_chars": budget,
        "context_length": context,
        "before": before,
        "expanded": expanded,
    }, gap


def _missing_window_attrs(agent: str, missing: set[str]) -> list[str]:
    from mailroom_sandbox.source_windows import TARGETS

    return [
        f"{module}.{attr}"
        for module, attr in TARGETS.get(agent, ())
        if f"{module}.{attr}" in missing
    ]


def _record_source_windows(rows: list[dict[str, Any]], gaps: list[str], windows: Mapping[str, int], missing: set[str]) -> None:
    for row in rows:
        if row["agent"] in windows:
            row["source_window"] = windows[row["agent"]]
        if not row["expanded"] or row["agent"] not in _SOURCE_AGENTS:
            continue
        absent = _missing_window_attrs(row["agent"], missing)
        if not absent:
            continue
        row["expanded"] = False
        gaps.append(
            f"{row['agent']}: source window cannot be swapped on ({', '.join(absent)}); "
            "the vendored 16k excerpt would stand"
        )


def expansion_status(taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    """Whether each context-fit reader is on its expanded input length.

    ``expanded`` is true when the live budget is above the pre-fit budget, or
    already covers the model's fitted room. It is null when the agent's provider
    is outside ``context_fit.providers`` (Modal and local routes keep the short
    budget on purpose). ``gaps`` names every long-context reader still short,
    including a judge or arbiter whose source window was not swapped on.
    """
    cfg = {**DEFAULTS, **(taxonomy.get("context_fit") or {})}
    cfg.pop("applied", None)
    applied = (taxonomy.get("context_fit") or {}).get("applied") or {}
    providers = {str(item) for item in cfg.get("providers") or []}
    agents = taxonomy.get("agents") or {}
    contexts = api_context_lengths()
    rows: list[dict[str, Any]] = []
    gaps: list[str] = []
    for name in sorted(_targets(cfg, _specialists(taxonomy))):
        agent = agents.get(name)
        if not isinstance(agent, dict):
            continue
        row, gap = _reader_status(taxonomy, name, agent, providers, contexts, applied, cfg)
        rows.append(row)
        if gap:
            gaps.append(gap)
    from mailroom_sandbox.source_windows import unavailable_targets, windows_for

    windows = windows_for(taxonomy)
    _record_source_windows(rows, gaps, windows, set(unavailable_targets()))
    return {"agents": rows, "gaps": gaps, "source_windows": windows}


def _chunking_stamp(taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    """The chunking switch and overlap the vendored extractor reads.

    Missing values use the same defaults as ``_run_chunked_extraction``
    (enabled, 8000). The window size is already in ``chunk_chars``.
    """
    chunking = taxonomy.get("chunking") or {}
    try:
        overlap = int(chunking.get("overlap_chars", 8_000))
    except (TypeError, ValueError):
        overlap = 8_000
    return {"enabled": bool(chunking.get("enabled", True)), "overlap_chars": overlap}


def identity(taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    """Stable digest of the fitted budgets a lock freezes.

    A later price-sheet or overlay edit changes the digest, including turning
    chunking off or changing its overlap. Locks written before this stamp have
    no key and still resume.
    """
    fit = taxonomy.get("context_fit") or {}
    applied = {
        name: {
            "model": row.get("model"),
            "context_length": row.get("context_length"),
            "after": row.get("after"),
        }
        for name, row in sorted((fit.get("applied") or {}).items())
    }
    body = {
        "applied": applied,
        "chunk_chars": (fit.get("chunk_chars") or {}).get("after"),
        "chunking": _chunking_stamp(taxonomy),
    }
    return {
        "sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        **body,
    }


def fitted_budget(taxonomy: Mapping[str, Any], agent: str) -> int | None:
    """``agent``'s final budget when it was context-fitted (None otherwise).

    Reads the agent's current ``max_input_chars`` so a run ``agent_knobs`` value
    applied after fitting is honoured.
    """
    if agent not in ((taxonomy.get("context_fit") or {}).get("applied") or {}):
        return None
    return _budget((taxonomy.get("agents") or {}).get(agent) or {}) or None
