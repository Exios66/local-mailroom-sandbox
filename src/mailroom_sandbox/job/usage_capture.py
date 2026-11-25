"""Per-item token / TTFT capture helpers for the job runner.

Pulls OpenAI-compatible ``usage`` from the vendored pipeline's run accumulator
(``pipeline.limits.usage_summary``) after a live graph invoke, or from a raw
chat-completions response. TTFT is never inferred from e2e — only persisted
when an explicit first-token timestamp is supplied.
"""

from __future__ import annotations

import contextvars
import logging
import math
from typing import Any, Mapping

_log = logging.getLogger("mailroom_sandbox.job.usage_capture")

# Per-call provider details (cost, cache split) beside the vendored token accumulator.
# Reset with the accumulator so one row cannot inherit another's charges.
_CALLS: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "sandbox_provider_calls", default=None
)
# LangChain's usage_metadata has token counts and no provider cost. The raw OpenRouter
# response, seen earlier on the same thread, leaves its usage.cost here for the next note.
_PENDING_COST: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "sandbox_pending_provider_cost", default=None
)


def reset_usage() -> None:
    """Start a fresh per-item usage accumulator for the current thread.

    ``pipeline.limits._run_usage`` is a ``ContextVar`` whose default is one
    shared list; with a thread pool and no reset, every row's tokens accumulate
    across the whole run (SAND-018: 20 docs reported 346k prompt tokens). Reset
    before each row so ``usage_from_pipeline`` returns that row's real counts.
    """
    try:
        from pipeline.limits import reset_run_usage
    except Exception as exc:  # noqa: BLE001 — mock / no vendor
        _log.debug("pipeline.limits unavailable for usage reset: %s", exc)
    else:
        try:
            reset_run_usage()
        except Exception as exc:  # noqa: BLE001
            _log.warning("reset_run_usage() raised — per-item tokens may accumulate: %s", exc)
    _CALLS.set([])
    _PENDING_COST.set(None)


def note_pending_provider_cost(cost: Any) -> None:
    """Hold one raw response's ``usage.cost`` until the matching ``note_provider_call``."""
    _PENDING_COST.set(_finite(cost))


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _token_count(value: Any) -> int | None:
    """Same acceptance rule as ``pipeline.limits._token_count``: a non-negative whole number."""
    number = _finite(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _first(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        value = _get(obj, name)
        if value is not None:
            return value
    return None


def note_provider_call(usage: Any) -> None:
    """Remember one returned call's provider cost and cache split for this row.

    Called beside ``pipeline.limits.record_usage``. A call that record_usage would drop
    (missing or non-integer counts) is not noted, so the two lists stay aligned. ``cost``
    stays absent when the provider did not report one; a reported 0 is kept.

    OpenRouter reports the cache split as ``prompt_tokens_details.cached_tokens`` and
    ``cache_write_tokens``, both already inside the prompt total. LangChain's
    ``usage_metadata`` copies those into ``input_token_details.cache_read`` and
    ``cache_creation`` with the same meaning, so list-price fallback can bill the
    cached subset at the cache rate. A rejected count drops the call and the held
    provider cost together: the next cost-less call must not inherit this one.
    """
    if usage is None:
        return
    prompt = _token_count(_first(usage, ("prompt_tokens", "input_tokens")))
    completion = _token_count(_first(usage, ("completion_tokens", "output_tokens")))
    if prompt is None or completion is None:
        _PENDING_COST.set(None)
        return
    details = _first(usage, (
        "prompt_tokens_details", "input_tokens_details", "input_token_details")) or {}
    cached = _token_count(_first(details, ("cached_tokens", "cache_read")))
    if cached is None:
        cached = _token_count(_first(usage, ("cached_tokens", "cache_read"))) or 0
    written = _token_count(_first(details, ("cache_write_tokens", "cache_creation")))
    if written is None:
        written = _token_count(_first(usage, ("cache_write_tokens", "cache_creation"))) or 0
    calls = _CALLS.get()
    if calls is None:
        calls = []
        _CALLS.set(calls)
    cost = _finite(_first(usage, ("cost",)))
    if cost is None:
        cost = _PENDING_COST.get()
    _PENDING_COST.set(None)
    calls.append({
        "prompt": prompt,
        "completion": completion,
        "cached": cached,
        "cache_write": written,
        "cost": cost,
    })


def provider_calls() -> list[dict[str, Any]]:
    """This row's noted calls (empty before ``reset_usage`` or when none were noted)."""
    return list(_CALLS.get() or [])


def _reported_cost(notes: list[dict[str, Any]]) -> float | None:
    """Sum of provider ``usage.cost`` when every noted call reported one; otherwise unknown."""
    if not notes or any(note.get("cost") is None for note in notes):
        return None
    return round(sum(float(note["cost"]) for note in notes), 8)


def usage_from_pipeline() -> dict[str, int]:
    """Read the current thread's pipeline usage accumulator (post-invoke)."""
    try:
        from pipeline.limits import usage_summary
    except Exception as exc:  # noqa: BLE001 — soft: mock / no vendor
        _log.debug("pipeline.limits unavailable for usage capture: %s", exc)
        return {}
    try:
        summary = usage_summary() or {}
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "usage_summary() raised — item will lack prompt/completion tokens "
            "(estimated_cost_usd will be absent): %s",
            exc,
        )
        return {}
    prompt = int(summary.get("prompt_tokens") or 0)
    completion = int(summary.get("completion_tokens") or 0)
    calls = int(summary.get("calls") or 0)
    out: dict[str, int] = {}
    if prompt:
        out["prompt_tokens"] = prompt
    if completion:
        out["completion_tokens"] = completion
    if calls:
        out["llm_calls"] = calls
    notes = provider_calls()
    if notes and calls == len(notes):
        out["cached_tokens"] = sum(int(note["cached"]) for note in notes)
        out["cache_write_tokens"] = sum(int(note["cache_write"]) for note in notes)
        reported = _reported_cost(notes)
        if reported is not None:
            out["reported_cost_usd"] = reported
    return out


def call_usage_from_pipeline() -> list[list[int]]:
    """The current thread's calls as ``[[prompt_tokens, completion_tokens], ...]``, in call order.

    The item totals hide how a document's prompt tokens split across calls, and a tiered price
    sheet (cheaper below a prompt-size threshold) needs each call's own size. Empty when the
    vendored accumulator is unavailable.

    HF-004's ``record_usage`` wrapper keeps that accumulator as the two token counts and notes
    provider cost and cache beside it. A row gains ``cached`` and ``cache_write`` only when a
    noted call actually recorded a cache split. A note of zeros is not a split, so a call the
    provider reported as prompt and completion stays two numbers.
    """
    try:
        from pipeline import limits
    except Exception as exc:  # noqa: BLE001 — mock / no vendor
        _log.debug("pipeline.limits unavailable for per-call usage capture: %s", exc)
        return []
    try:
        calls = limits._run_usage.get()  # noqa: SLF001 — the accumulator usage_summary() reads
        notes = provider_calls()
        rows: list[list[int]] = []
        aligned = len(notes) == len(calls)
        # Widen every row together so a mixed document does not change width mid-list.
        widen = aligned and any(int(note["cached"]) or int(note["cache_write"]) for note in notes)
        for index, call in enumerate(calls):
            row = [int(call["prompt_tokens"]), int(call["completion_tokens"])]
            if widen:
                row.extend([int(notes[index]["cached"]), int(notes[index]["cache_write"])])
            rows.append(row)
        return rows
    except Exception as exc:  # noqa: BLE001 — soft: the totals are still recorded
        _log.warning("per-call usage capture failed (%s): item will be priced from totals", exc)
        return []


def usage_from_openai_response(resp: Any) -> dict[str, int]:
    """Extract prompt/completion tokens from an OpenAI SDK response object."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        # First present key wins: an explicit 0 is observed usage, not a fallthrough.
        prompt = next((usage[k] for k in ("prompt_tokens", "input_tokens") if usage.get(k) is not None), None)
        completion = next((usage[k] for k in ("completion_tokens", "output_tokens") if usage.get(k) is not None), None)
    else:
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
    out: dict[str, int] = {}
    try:
        if prompt is not None:
            out["prompt_tokens"] = int(prompt)
        if completion is not None:
            out["completion_tokens"] = int(completion)
    except (TypeError, ValueError):
        return {}
    return out


def usage_by_agent_from_pipeline() -> dict[str, dict[str, Any]]:
    """The current thread's usage split by agent, ``{agent: {calls, prompt_tokens, completion_tokens, models}}``.

    The vendored accumulator already keeps this split (``usage_summary()["by_agent"]``);
    ``usage_from_pipeline`` collapses it to totals. Persisted per item as ``usage_by_agent`` so a
    run's cost can be split by role (autoresearch). Empty when unavailable.
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        from pipeline.limits import usage_summary

        by_agent = (usage_summary() or {}).get("by_agent") or {}
        for agent, slot in by_agent.items():
            out[str(agent)] = {"calls": int(slot.get("calls") or 0),
                               "prompt_tokens": int(slot.get("prompt_tokens") or 0),
                               "completion_tokens": int(slot.get("completion_tokens") or 0),
                               "models": [str(m) for m in slot.get("models") or []]}
    except ImportError as exc:  # mock / no vendor
        _log.debug("pipeline.limits unavailable for per-agent usage capture: %s", exc)
        return {}
    except Exception as exc:  # noqa: BLE001 - soft, like usage_from_pipeline: a malformed slot must not fail a billed document
        _log.warning("per-agent usage capture failed (%s) — item will lack usage_by_agent (no role cost split): %s",
                     type(exc).__name__, exc)
        return {}
    return out


def merge_item_metrics(
    *,
    latency_ms: float | None = None,
    usage: Mapping[str, Any] | None = None,
    ttft_ms: float | None = None,
) -> dict[str, Any]:
    """Build the per-item metrics block persisted to ``items.jsonl``."""
    out: dict[str, Any] = {}
    if latency_ms is not None:
        out["latency_ms"] = float(latency_ms)
    if ttft_ms is not None:
        out["ttft_ms"] = float(ttft_ms)
    if usage:
        for key in ("prompt_tokens", "completion_tokens", "llm_calls", "cached_tokens", "cache_write_tokens"):
            val = usage.get(key)
            if val is not None:
                try:
                    out[key] = int(val)
                except (TypeError, ValueError):
                    continue
        reported = usage.get("reported_cost_usd")
        if isinstance(reported, (int, float)) and not isinstance(reported, bool) and math.isfinite(reported):
            out["reported_cost_usd"] = float(reported)
    return out
