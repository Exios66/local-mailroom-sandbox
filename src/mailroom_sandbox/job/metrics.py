"""Serving metrics capture + local / Modal / API comparison (DMR-027).

Builds dojo-compatible serving records from run stores and compares offline
(local), remote-GPU (Modal), and API-key (OpenRouter) runs on latency,
throughput, tokens, cost efficiency, and total cost. Reuses
``llm_dojo_scoring.serving`` for price/cost math and pairwise comparisons.

Cost honesty
------------
* **Token-proxy USD** (``estimated_cost_usd``) uses OpenRouter-like
  per-1M prices (dojo table + sandbox champion fallback). Configurable via
  ``SANDBOX_TOKEN_PRICE_IN_PER_M`` / ``SANDBOX_TOKEN_PRICE_OUT_PER_M``.
* **Modal GPU USD** (``estimated_gpu_cost_usd``) is wall/busy GPU-seconds ×
  ``$/hr`` for the locked GPU class (default L4 ≈ $0.80/hr). Configurable via
  ``MODAL_GPU_USD_PER_HOUR`` or ``MODAL_GPU_USD_PER_SEC``. Never fabricate $0
  when tokens/GPU seconds are missing — omit the field and warn loudly.
* **TTFT** is only present when items record ``ttft_ms`` (never inferred).
"""

from __future__ import annotations

import logging
import os
import statistics
from typing import Any, Mapping, Sequence

from llm_dojo_scoring.serving import compare_serving, estimate_cost

_log = logging.getLogger("mailroom_sandbox.job.metrics")

_COST_WARNED = False
_GPU_WARNED = False

MODAL_PROFILES = ("modal-vllm",)
LOCAL_PROFILES = ("ollama", "vllm-local", "vllm-remote", "llamacpp", "lmstudio")
API_PROFILES = ("openrouter",)

# Champion-model prices for locally/Modal-served weights: the OpenRouter list
# price of the matrix champion each HF id maps to, so local-vs-API cost
# comparisons stay like-for-like. The dojo table only knows the OpenRouter
# slugs; without this the flagship default model always costed None (DMR-049).
SANDBOX_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "Qwen/Qwen3-8B": (0.03, 0.13),  # qwen/qwen3.7-flash champion
    "Qwen/Qwen3-8B-AWQ": (0.03, 0.13),
    "Qwen/Qwen3-14B": (0.03, 0.13),
    "Qwen/Qwen3-14B-AWQ": (0.03, 0.13),
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B": (0.05, 0.25),  # deepseek-v4-flash
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B": (0.05, 0.25),
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B": (0.435, 0.87),  # deepseek-v4-pro
}

# Modal GPU $/hr (modal.com/pricing, verified 2026-09-09 — see deploy/README.md).
# Override a single rate with MODAL_GPU_USD_PER_HOUR (applies to whatever GPU
# class the run locked) or MODAL_GPU_USD_PER_SEC for a precise per-second rate.
DEFAULT_GPU_USD_PER_HOUR: dict[str, float] = {
    "L4": 0.80,
    "A10": 1.10,
    "A10G": 1.10,
    "A100": 2.10,
    "A100-40GB": 2.10,
    "A100-80GB": 2.50,
    "L40S": 1.95,
    "H100": 3.95,
    "H200": 4.54,
    "B200": 6.25,
    "T4": 0.59,
}

# ModernBERT ONNX-CPU inference is essentially free vs LLM tokens; document
# the plan's ~$1e-6/doc floor so comparisons stay honest (mailroom-ml plan §1).
MODERNBERT_DEFAULT_COST_PER_DOC_USD = 1e-6


def _env_float(name: str) -> float | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        _log.warning("ignoring non-float env %s=%r", name, raw)
        return None


def gpu_usd_per_hour(gpu: str | None = None) -> float:
    """Resolve Modal GPU $/hr: env override → table → L4 default ($0.80)."""
    per_sec = _env_float("MODAL_GPU_USD_PER_SEC")
    if per_sec is not None:
        return per_sec * 3600.0
    override = _env_float("MODAL_GPU_USD_PER_HOUR")
    if override is not None:
        return override
    key = (gpu or os.environ.get("MODAL_VLLM_GPU") or "L4").split(":")[0]
    if key in DEFAULT_GPU_USD_PER_HOUR:
        return DEFAULT_GPU_USD_PER_HOUR[key]
    _log.warning(
        "unknown GPU class %r — falling back to L4 rate $%.2f/hr; set "
        "MODAL_GPU_USD_PER_HOUR to override",
        key,
        DEFAULT_GPU_USD_PER_HOUR["L4"],
    )
    return DEFAULT_GPU_USD_PER_HOUR["L4"]


def estimate_gpu_cost_usd(
    gpu_seconds: float,
    *,
    gpu: str | None = None,
) -> float | None:
    """USD for ``gpu_seconds`` of billed/busy time at the configured rate."""
    if gpu_seconds is None or gpu_seconds <= 0:
        return None
    rate = gpu_usd_per_hour(gpu)
    return round(gpu_seconds / 3600.0 * rate, 6)


def _token_price_override() -> tuple[float, float] | None:
    """Optional global token price override (per-1M in/out)."""
    pin = _env_float("SANDBOX_TOKEN_PRICE_IN_PER_M")
    pout = _env_float("SANDBOX_TOKEN_PRICE_OUT_PER_M")
    if pin is None and pout is None:
        return None
    return (pin if pin is not None else 0.0, pout if pout is not None else 0.0)


def _estimate_cost(
    prompt_tokens: int, completion_tokens: int, model: str
) -> float | None:
    """Dojo cost first; fall back to the sandbox champion-price table."""
    override = _token_price_override()
    if override is not None:
        if prompt_tokens + completion_tokens <= 0:
            return None
        per_million_in, per_million_out = override
        return round(
            prompt_tokens * per_million_in / 1_000_000
            + completion_tokens * per_million_out / 1_000_000,
            6,
        )
    try:
        cost = estimate_cost(prompt_tokens, completion_tokens, model)
        if cost is not None:
            return float(cost)
    except Exception as exc:
        global _COST_WARNED
        if not _COST_WARNED:
            _COST_WARNED = True
            _log.warning(
                "dojo estimate_cost raised for model %r — fell back to the "
                "sandbox champion-price table; a broken dojo cost fn would "
                "otherwise look like 'no price known'",
                model,
                exc_info=exc,
            )
    if not model:
        return None
    prices = SANDBOX_MODEL_PRICES.get(model)
    if prices is None:
        for known, price in SANDBOX_MODEL_PRICES.items():
            if model.startswith(known):
                prices = price
                break
    if prices is None or prompt_tokens + completion_tokens <= 0:
        return None
    per_million_in, per_million_out = prices
    return round(
        prompt_tokens * per_million_in / 1_000_000
        + completion_tokens * per_million_out / 1_000_000,
        6,
    )


def bucket_kind(record: Mapping[str, Any]) -> str:
    kind = str(record.get("serving_kind") or "").lower()
    if kind in {"local", "api", "modal"}:
        return kind
    profile = str(record.get("profile") or "")
    if profile in MODAL_PROFILES:
        return "modal"
    if profile in API_PROFILES:
        return "api"
    if profile in LOCAL_PROFILES:
        return "local"
    provider = str(record.get("provider") or "").lower()
    if provider in {"openrouter"}:
        return "api"
    if provider in {"vllm", "ollama", "llamacpp", "lmstudio", "generic"}:
        return "local"
    return "unknown"


def _gpu_seconds_from_items(
    items: Sequence[Mapping[str, Any]],
    *,
    billed_window_seconds: float | None = None,
) -> float | None:
    """GPU-seconds attribution for a run.

    Prefer an explicit billed window (Modal warm interval). Else sum ok-item
    ``latency_ms`` as a busy-time lower bound (overcounts under concurrency —
    still better than silent $0).
    """
    if billed_window_seconds is not None and billed_window_seconds > 0:
        return float(billed_window_seconds)
    env_billed = _env_float("MODAL_BILLED_GPU_SECONDS")
    if env_billed is not None and env_billed > 0:
        return env_billed
    ok_items = [i for i in items if i.get("ok", True) is not False]
    latencies = [
        float(i["latency_ms"])
        for i in ok_items
        if i.get("latency_ms") is not None
    ]
    if not latencies:
        return None
    return sum(latencies) / 1000.0


def record_from_run(
    *,
    run_id: str,
    spec_hash: str,
    task: str,
    profile: str,
    model: str,
    prompt_version: str,
    dataset_fingerprint: str,
    items: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Any] | None = None,
    gpu: str | None = None,
    billed_window_seconds: float | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    """Aggregate per-item captures into one dojo-compatible serving record."""
    kind = bucket_kind({"serving_kind": "", "profile": profile, "provider": _provider_for(profile)})
    # hub#56: TTFT aggregation must treat failures like the latency
    # aggregation — failed/retried items carry inflated TTFT from backoff
    # sleeps, so average TTFT over the SAME ok_items as e2e latency (the two
    # must never disagree about which items are representative). Token sums
    # stay over ALL items (cost is real even for failures).
    ok_items = [i for i in items if i.get("ok", True) is not False]
    latencies = [float(i.get("latency_ms", 0)) for i in ok_items if i.get("latency_ms") is not None]
    prompt_tokens = sum(int(i.get("prompt_tokens") or 0) for i in items)
    completion_tokens = sum(int(i.get("completion_tokens") or 0) for i in items)
    total_tokens = prompt_tokens + completion_tokens
    ttfts = [float(i.get("ttft_ms", 0)) for i in ok_items if i.get("ttft_ms") is not None]
    n = len(items)
    n_ok = len(ok_items)
    rec: dict[str, Any] = {
        "serving_kind": kind,
        "provider": _provider_for(profile),
        "profile": profile,
        "model": model,
        "prompt_version": prompt_version or "mailroom-default",
        "task": task,
        "dataset_fingerprint": dataset_fingerprint,
        "n": n,
        "run_id": run_id,
        "spec_hash": spec_hash,
    }
    if gpu:
        rec["gpu"] = gpu
    if latencies:
        rec["e2e_latency_seconds"] = statistics.mean(latencies) / 1000.0
    if ttfts:
        rec["ttft_seconds"] = statistics.mean(ttfts) / 1000.0
    if prompt_tokens:
        rec["prompt_tokens"] = prompt_tokens
    if completion_tokens:
        rec["completion_tokens"] = completion_tokens
    if total_tokens:
        rec["total_tokens"] = total_tokens
    if scores:
        rec["scores"] = dict(scores)

    # Token-proxy cost (OpenRouter-like). Absent when tokens or prices missing —
    # never write estimated_cost_usd=0 as a stand-in for "unknown".
    try:
        cost = _estimate_cost(prompt_tokens, completion_tokens, model)
        if cost is not None:
            rec["estimated_cost_usd"] = float(cost)
            if n_ok > 0:
                rec["cost_per_document"] = round(float(cost) / n_ok, 8)
        elif not mock and n_ok > 0 and total_tokens <= 0:
            _log.warning(
                "run %r (%s/%s): %d ok items but 0 tokens recorded — "
                "estimated_cost_usd ABSENT (not $0); ensure the OpenAI-"
                "compatible server returns usage.prompt_tokens",
                run_id,
                kind,
                profile,
                n_ok,
            )
        elif not mock and total_tokens > 0 and cost is None:
            _log.warning(
                "run %r: tokens recorded but no price for model %r — "
                "estimated_cost_usd ABSENT; set SANDBOX_TOKEN_PRICE_IN_PER_M / "
                "OUT_PER_M or extend SANDBOX_MODEL_PRICES",
                run_id,
                model,
            )
    except Exception as exc:
        _log.warning(
            "cost estimation for run %r failed outright (inner function "
            "covered) — estimated_cost_usd will be ABSENT from the record: %s",
            run_id,
            exc,
        )

    # Modal GPU-hour cost (orthogonal to token proxy). Local Ollama and API
    # buckets skip this; Modal / vLLM-remote may attribute busy GPU seconds.
    if kind == "modal" or (kind == "local" and profile in {"vllm-local", "vllm-remote"}):
        gpu_seconds = _gpu_seconds_from_items(
            items, billed_window_seconds=billed_window_seconds
        )
        if gpu_seconds is not None:
            rec["gpu_seconds"] = round(gpu_seconds, 3)
            gpu_cost = estimate_gpu_cost_usd(gpu_seconds, gpu=gpu)
            if gpu_cost is not None:
                rec["estimated_gpu_cost_usd"] = gpu_cost
                if n_ok > 0:
                    rec["gpu_cost_per_document"] = round(gpu_cost / n_ok, 8)
            else:
                global _GPU_WARNED
                if not _GPU_WARNED:
                    _GPU_WARNED = True
                    _log.warning(
                        "gpu_seconds=%s but GPU rate resolved to no cost — "
                        "estimated_gpu_cost_usd ABSENT",
                        gpu_seconds,
                    )
        elif kind == "modal" and not mock and n_ok > 0:
            _log.warning(
                "modal run %r has no latency_ms / billed window — "
                "estimated_gpu_cost_usd ABSENT (not $0); set "
                "MODAL_BILLED_GPU_SECONDS or ensure items record latency_ms",
                run_id,
            )

    return {k: v for k, v in rec.items() if v is not None}


def _provider_for(profile: str) -> str:
    if profile in MODAL_PROFILES:
        return "vllm"
    if profile in API_PROFILES:
        return "openrouter"
    if profile in {"ollama"}:
        return "ollama"
    if profile in {"llamacpp", "lmstudio"}:
        return "generic"
    return "vllm"


def bucket_records(records: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {"local": [], "modal": [], "api": [], "unknown": []}
    for rec in records:
        buckets.setdefault(bucket_kind(rec), []).append(dict(rec))
    return buckets


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def aggregate_bucket(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mean latency/throughput/cost + totals for one bucket."""
    n = len(records)
    lat = [float(r["e2e_latency_seconds"]) for r in records if r.get("e2e_latency_seconds")]
    ttft = [float(r["ttft_seconds"]) for r in records if r.get("ttft_seconds")]
    prom = sum(int(r.get("prompt_tokens") or 0) for r in records)
    comp = sum(int(r.get("completion_tokens") or 0) for r in records)
    cost = [float(r["estimated_cost_usd"]) for r in records if r.get("estimated_cost_usd") is not None]
    gpu_cost = [
        float(r["estimated_gpu_cost_usd"])
        for r in records
        if r.get("estimated_gpu_cost_usd") is not None
    ]
    cpd = [float(r["cost_per_document"]) for r in records if r.get("cost_per_document") is not None]
    gcpd = [
        float(r["gpu_cost_per_document"])
        for r in records
        if r.get("gpu_cost_per_document") is not None
    ]
    dur = sum(lat) if lat else None
    return {
        "n": n,
        "mean_ttft_s": _mean(ttft),
        "mean_e2e_s": _mean(lat),
        "total_tokens": prom + comp,
        "tokens_per_s": round((prom + comp) / dur, 2) if dur else None,
        "estimated_cost_usd": round(sum(cost), 6) if cost else None,
        "estimated_gpu_cost_usd": round(sum(gpu_cost), 6) if gpu_cost else None,
        "mean_cost_per_document": _mean(cpd),
        "mean_gpu_cost_per_document": _mean(gcpd),
    }


def _pct(base: float | None, other: float | None) -> float | None:
    if base in (None, 0) or other is None:
        return None
    return round((other - base) / base * 100.0, 1)


def compare(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Three-way local / Modal / API comparison with pairwise dojo deltas."""
    buckets = bucket_records(records)
    summary = {kind: aggregate_bucket(rows) for kind, rows in buckets.items() if rows}
    api = summary.get("api")

    def delta_vs_api(metric: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        base = api.get(metric) if api else None
        for kind in ("local", "modal"):
            agg = summary.get(kind)
            if agg:
                out[kind] = _pct(base, agg.get(metric))
        return out

    deltas = {
        "mean_e2e_s": delta_vs_api("mean_e2e_s"),
        "mean_ttft_s": delta_vs_api("mean_ttft_s"),
        "tokens_per_s": delta_vs_api("tokens_per_s"),
        "estimated_cost_usd": delta_vs_api("estimated_cost_usd"),
        "estimated_gpu_cost_usd": delta_vs_api("estimated_gpu_cost_usd"),
        "mean_cost_per_document": delta_vs_api("mean_cost_per_document"),
    }

    pairs: dict[str, Any] = {}
    if buckets.get("local") and buckets.get("api"):
        pairs["local_vs_api"] = compare_serving(buckets["local"], buckets["api"])
    if buckets.get("modal") and buckets.get("api"):
        pairs["modal_vs_api"] = compare_serving(buckets["modal"], buckets["api"])
    if buckets.get("local") and buckets.get("modal"):
        pairs["local_vs_modal"] = compare_serving(buckets["local"], buckets["modal"])

    cost_total = {
        kind: (agg.get("estimated_cost_usd") if agg else None)
        for kind, agg in summary.items()
    }
    gpu_cost_total = {
        kind: (agg.get("estimated_gpu_cost_usd") if agg else None)
        for kind, agg in summary.items()
    }
    markdown = _markdown(summary, deltas, pairs)
    return {
        "buckets": summary,
        "deltas_vs_api": deltas,
        "total_cost_usd": cost_total,
        "total_gpu_cost_usd": gpu_cost_total,
        "pairwise": pairs,
        "markdown": markdown,
    }


def _score_quality(rec: Mapping[str, Any]) -> dict[str, float | None]:
    scores = rec.get("scores") if isinstance(rec.get("scores"), Mapping) else {}
    out: dict[str, float | None] = {}
    for key in ("accuracy", "exact_match", "f1_macro", "doc_type_accuracy", "subclass_accuracy"):
        val = scores.get(key) if scores else rec.get(key)
        if val is not None:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                continue
    return out


def compare_sorter_vs_modernbert(
    sorter: Mapping[str, Any],
    modernbert: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare LLM sorter vs trained ModernBERT on accuracy + cost/latency.

    Both sides should carry comparable fields (``n``, ``e2e_latency_seconds``,
    quality scores, and either ``cost_per_document`` / ``estimated_cost_usd``
    or ModernBERT's CPU inference floor). Does not load the mailroom-ml
    package — callers supply already-scored records (job run / eval fixture).
    """
    s_q = _score_quality(sorter)
    m_q = _score_quality(modernbert)
    s_n = int(sorter.get("n") or 0)
    m_n = int(modernbert.get("n") or 0)
    s_lat = _as_float(sorter.get("e2e_latency_seconds"))
    m_lat = _as_float(modernbert.get("e2e_latency_seconds"))
    s_cpd = _as_float(sorter.get("cost_per_document"))
    if s_cpd is None and sorter.get("estimated_cost_usd") is not None and s_n:
        s_cpd = float(sorter["estimated_cost_usd"]) / s_n
    # Prefer GPU cost-per-doc for Modal sorter when token proxy is absent.
    if s_cpd is None:
        s_cpd = _as_float(sorter.get("gpu_cost_per_document"))
    m_cpd = _as_float(modernbert.get("cost_per_document"))
    if m_cpd is None and modernbert.get("estimated_cost_usd") is not None and m_n:
        m_cpd = float(modernbert["estimated_cost_usd"]) / m_n
    if m_cpd is None:
        m_cpd = MODERNBERT_DEFAULT_COST_PER_DOC_USD
        modernbert_cost_note = (
            f"modernbert cost_per_document defaulted to "
            f"{MODERNBERT_DEFAULT_COST_PER_DOC_USD} (ONNX-CPU floor from "
            f"mailroom-ml plan); override on the record to use a measured rate"
        )
    else:
        modernbert_cost_note = None

    def _delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round(a - b, 6)

    def _pct_delta(base: float | None, other: float | None) -> float | None:
        return _pct(base, other)

    accuracy_keys = sorted(set(s_q) | set(m_q))
    quality = {
        key: {
            "sorter": s_q.get(key),
            "modernbert": m_q.get(key),
            "delta_sorter_minus_modernbert": _delta(s_q.get(key), m_q.get(key)),
        }
        for key in accuracy_keys
    }
    latency = {
        "sorter_e2e_s": s_lat,
        "modernbert_e2e_s": m_lat,
        "delta_sorter_minus_modernbert": _delta(s_lat, m_lat),
        "pct_sorter_vs_modernbert": _pct_delta(m_lat, s_lat),
    }
    cost = {
        "sorter_cost_per_document": s_cpd,
        "modernbert_cost_per_document": m_cpd,
        "delta_sorter_minus_modernbert": _delta(s_cpd, m_cpd),
        "sorter_estimated_cost_usd": _as_float(sorter.get("estimated_cost_usd")),
        "sorter_estimated_gpu_cost_usd": _as_float(sorter.get("estimated_gpu_cost_usd")),
        "modernbert_estimated_cost_usd": _as_float(modernbert.get("estimated_cost_usd")),
    }
    honest_gaps: list[str] = []
    if s_cpd is None:
        honest_gaps.append(
            "sorter cost_per_document unknown (no tokens/GPU attribution on record)"
        )
    if not s_q and not m_q:
        honest_gaps.append("no quality scores on either side")
    if modernbert_cost_note:
        honest_gaps.append(modernbert_cost_note)

    markdown = _sorter_vs_modernbert_md(
        quality, latency, cost, sorter=sorter, modernbert=modernbert, gaps=honest_gaps
    )
    return {
        "agent": "sorter_vs_modernbert",
        "sorter": {
            "model": sorter.get("model"),
            "serving_kind": sorter.get("serving_kind") or bucket_kind(sorter),
            "profile": sorter.get("profile"),
            "n": s_n,
            "classifier": "llm_sorter",
        },
        "modernbert": {
            "model": modernbert.get("model")
            or "Lucius-Morningstar/mailroom-modernbert-classifier",
            "serving_kind": modernbert.get("serving_kind") or "modernbert",
            "n": m_n,
            "classifier": "modernbert",
        },
        "quality": quality,
        "latency": latency,
        "cost": cost,
        "honest_gaps": honest_gaps,
        "markdown": markdown,
    }


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sorter_vs_modernbert_md(
    quality: Mapping[str, Any],
    latency: Mapping[str, Any],
    cost: Mapping[str, Any],
    *,
    sorter: Mapping[str, Any],
    modernbert: Mapping[str, Any],
    gaps: Sequence[str],
) -> str:
    lines = [
        "## Sorter vs ModernBERT (classification)",
        "",
        f"| side | model | n | e2e (s) | $/doc |",
        "| --- | --- | --- | --- | --- |",
        (
            f"| sorter | {sorter.get('model') or '-'} | {sorter.get('n') or '-'} | "
            f"{latency.get('sorter_e2e_s') or '-'} | "
            f"{cost.get('sorter_cost_per_document') or '-'} |"
        ),
        (
            f"| modernbert | {modernbert.get('model') or 'mailroom-modernbert-classifier'} | "
            f"{modernbert.get('n') or '-'} | {latency.get('modernbert_e2e_s') or '-'} | "
            f"{cost.get('modernbert_cost_per_document') or '-'} |"
        ),
        "",
        "### Quality",
        "| metric | sorter | modernbert | Δ (sorter − modernbert) |",
        "| --- | --- | --- | --- |",
    ]
    for key, row in quality.items():
        lines.append(
            f"| {key} | {row.get('sorter') if row.get('sorter') is not None else '-'} | "
            f"{row.get('modernbert') if row.get('modernbert') is not None else '-'} | "
            f"{row.get('delta_sorter_minus_modernbert') if row.get('delta_sorter_minus_modernbert') is not None else '-'} |"
        )
    if gaps:
        lines += ["", "### Honest gaps"]
        for g in gaps:
            lines.append(f"- {g}")
    return "\n".join(lines)


def _markdown(summary: dict[str, Any], deltas: dict[str, Any], pairs: dict[str, Any]) -> str:
    lines = ["## Serving metrics (local vs Modal vs API)", ""]
    header = (
        "| bucket | n | mean e2e (s) | mean ttft (s) | tok/s | total tokens | "
        "est. token $ | est. GPU $ | $/doc (token) |"
    )
    lines += [header, "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for kind in ("local", "modal", "api"):
        agg = summary.get(kind)
        if not agg:
            continue
        lines.append(
            f"| {kind} | {agg['n']} | {agg['mean_e2e_s'] or '-'} | "
            f"{agg['mean_ttft_s'] or '-'} | {agg['tokens_per_s'] or '-'} | "
            f"{agg['total_tokens'] or '-'} | {agg['estimated_cost_usd'] or '-'} | "
            f"{agg.get('estimated_gpu_cost_usd') or '-'} | "
            f"{agg.get('mean_cost_per_document') or '-'} |"
        )
    lines.append("")
    lines.append("### Delta vs API (%)")
    lines.append("| metric | local | modal |")
    lines.append("| --- | --- | --- |")
    for metric, d in deltas.items():
        lines.append(f"| {metric} | {d.get('local') or '-'} | {d.get('modal') or '-'} |")
    for name, pair in pairs.items():
        md = pair.get("markdown") if isinstance(pair, dict) else None
        if md:
            lines += ["", f"### Pairwise: {name}", str(md)]
    return "\n".join(lines)
