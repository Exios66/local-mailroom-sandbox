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
    out = deepcopy(taxonomy)
    chunking = out.setdefault("chunking", {})
    cap = int(chunking.get("chunk_chars", _DEFAULT_CHUNK_CHARS))
    record: dict[str, Any] = {**cfg, "applied": {}, "chunk_chars": {"before": cap, "after": cap}}
    out["context_fit"] = record
    if not cfg.get("enabled", True):
        return out
    contexts = api_context_lengths() if contexts is None else contexts
    providers = {str(p) for p in cfg.get("providers") or []}
    specialists = _specialists(out)
    routes = agent_routes or {}
    agents = out.get("agents") or {}
    for name in sorted(_targets(cfg, specialists)):
        agent = agents.get(name)
        if not isinstance(agent, dict):
            continue
        route = routes.get(name)
        provider = str(_route_field(route, "provider") or agent.get("provider") or "")
        model = str(_route_field(route, "model") or agent.get("model") or "")
        context = contexts.get(model)
        if provider not in providers or not context:
            continue
        before = _budget(agent)
        after = fit_chars(context, int(agent.get("max_tokens") or 4096), cfg)
        if after <= before:
            continue
        agent["max_input_chars"] = after
        record["applied"][name] = {"model": model, "context_length": context, "before": before, "after": after}

    fitted = [record["applied"][s]["after"] for s in specialists if s in record["applied"]]
    wide_unfitted = sorted(s for s in specialists if s not in record["applied"] and _budget(agents.get(s) or {}) > cap)
    if fitted and not wide_unfitted:
        chunking["chunk_chars"] = max(cap, *fitted)
        record["chunk_chars"]["after"] = chunking["chunk_chars"]
    elif fitted:
        _log.warning("chunk cap left at %s: unfitted specialists %s have wider budgets", cap, wide_unfitted)
    if record["applied"]:
        _log.info("context-fit budgets: %s", {k: v["after"] for k, v in record["applied"].items()})
    return out


def fitted_budget(taxonomy: Mapping[str, Any], agent: str) -> int | None:
    """``agent``'s final budget when it was context-fitted (None otherwise).

    Reads the agent's current ``max_input_chars`` so a run ``agent_knobs`` value
    applied after fitting is honoured.
    """
    if agent not in ((taxonomy.get("context_fit") or {}).get("applied") or {}):
        return None
    return _budget((taxonomy.get("agents") or {}).get(agent) or {}) or None
