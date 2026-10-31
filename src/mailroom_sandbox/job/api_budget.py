"""API token spend: which models bill per token, their price bound, and the run ceiling (SAND-089).

The GPU cap (``job.cost_cap_usd``) estimates Modal container time; it says nothing
about OpenRouter, which bills per token. A run that sends any agent to a token-billed
provider therefore needs its own ceiling, ``job.api_cost_cap_usd``, and a known price
for every such model: an unpriced model would make the ceiling unenforceable.

The running total prices every observed token at the highest input and output price
among the run's API models. In a hybrid run that also counts tokens a Modal agent
served, so the estimate errs high: the safe direction for a ceiling.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Iterable, Mapping
from typing import Any

API_PROVIDERS = frozenset({"openrouter"})


def api_models(lock: Mapping[str, Any]) -> list[str]:
    """Token-billed models a locked run (or a lock-shaped spec dump) can call."""
    models: set[str] = set()
    assignments = lock.get("agent_assignments") or {}
    for assignment in assignments.values():
        if str(assignment.get("provider")) in API_PROVIDERS and assignment.get("model"):
            models.add(str(assignment["model"]))
    agent_models = lock.get("agent_models") or {}
    for name, route in (lock.get("agent_routes") or {}).items():
        if (route or {}).get("provider") in API_PROVIDERS:
            models.add(str(agent_models.get(name) or route.get("model") or ""))
    engine = lock.get("engine") or {}
    if engine.get("kind") in API_PROVIDERS and not assignments:
        models.add(str(engine.get("model") or ""))
    return sorted(model for model in models if model)


def spec_api_models(spec: Any) -> list[str]:
    """``api_models`` for an unlocked RunSpec, resolved as preflight would lock it."""
    shaped: dict[str, Any] = {
        "engine": spec.engine.model_dump(),
        "agent_models": dict(spec.agent_models),
        "agent_routes": {name: route.model_dump() for name, route in spec.agent_routes.items()},
    }
    if spec.agent_routes or spec.agent_knobs or spec.agent_models:
        from mailroom_sandbox.agent_routes import describe

        shaped["agent_assignments"] = describe(spec)
    return api_models(shaped)


def unpriced(models: Iterable[str]) -> list[str]:
    from mailroom_sandbox.job.metrics import token_price

    return [model for model in models if token_price(model) is None]


def price_bound(models: Iterable[str]) -> tuple[float, float]:
    """Highest USD per 1M (input, output) tokens across ``models``; raises on an unpriced model."""
    from mailroom_sandbox.job.metrics import token_price

    models = list(models)
    missing = unpriced(models)
    if missing:
        raise ValueError(f"no token price for {', '.join(missing)}")
    prices = [token_price(model) for model in models]
    return (max((p[0] for p in prices), default=0.0), max((p[1] for p in prices), default=0.0))


def budget_errors(lock: Mapping[str, Any]) -> list[str]:
    """Why a paid run that bills API tokens may not start (empty when it may)."""
    models = api_models(lock)
    if not models:
        return []
    errors = []
    missing = unpriced(models)
    if missing:
        errors.append(
            f"no token price for {', '.join(missing)}: the API spend ceiling cannot be enforced. "
            "Add the model to SANDBOX_MODEL_PRICES (src/mailroom_sandbox/job/metrics.py) or set both "
            "SANDBOX_TOKEN_PRICE_IN_PER_M and SANDBOX_TOKEN_PRICE_OUT_PER_M "
            "(a missing side is priced at 0 and its tokens are not counted)"
        )
    cap = (lock.get("job") or {}).get("api_cost_cap_usd")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not math.isfinite(cap) or cap <= 0:
        errors.append(
            f"this run bills API tokens ({', '.join(models)}) and needs a finite job.api_cost_cap_usd; "
            "the GPU cost_cap_usd does not limit token spend"
        )
    return errors


class ApiBudget:
    """Running API token spend against ``job.api_cost_cap_usd``; checked between documents."""

    def __init__(self, cap_usd: float, usd_per_m_in: float, usd_per_m_out: float, models: list[str]):
        self.cap_usd = float(cap_usd)
        self.usd_per_m_in = float(usd_per_m_in)
        self.usd_per_m_out = float(usd_per_m_out)
        self.models = list(models)
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def add(self, prompt_tokens: Any, completion_tokens: Any) -> None:
        prompt = float(prompt_tokens or 0)
        completion = float(completion_tokens or 0)
        with self._lock:
            self.spent_usd += (prompt * self.usd_per_m_in + completion * self.usd_per_m_out) / 1_000_000

    def add_usage(self, usage: Mapping[str, Any] | None) -> None:
        usage = usage or {}
        self.add(usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def exceeded(self) -> str | None:
        if self.spent_usd >= self.cap_usd:
            return (f"api_cost_cap_usd={self.cap_usd} reached (est_api_usd={self.spent_usd:.4f} "
                    f"at ${self.usd_per_m_in}/${self.usd_per_m_out} per 1M tokens) — aborting to protect spend")
        return None

    def check(self, prefix: str = "") -> None:
        reason = self.exceeded()
        if reason:
            raise RuntimeError(prefix + reason)


def budget_for(lock: Mapping[str, Any], items: Iterable[Mapping[str, Any]] = ()) -> ApiBudget | None:
    """The run's API budget, seeded with tokens already spent by persisted items (resume)."""
    job = lock.get("job") or {}
    cap = job.get("api_cost_cap_usd")
    models = api_models(lock)
    if job.get("mock", False) or not models or not isinstance(cap, (int, float)) or cap <= 0:
        return None
    price_in, price_out = price_bound(models)
    budget = ApiBudget(cap, price_in, price_out, models)
    for item in items:
        budget.add_usage(item)
    return budget


def spend_estimate(lock: Mapping[str, Any], items: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Estimated API token spend of persisted items at the run's price bound (None: no priced API model)."""
    models = api_models(lock)
    if not models or unpriced(models):
        return None
    price_in, price_out = price_bound(models)
    budget = ApiBudget(float("inf"), price_in, price_out, models)
    for item in items:
        budget.add_usage(item)
    return {"est_api_usd": round(budget.spent_usd, 6), "usd_per_million_tokens": [price_in, price_out],
            "models": models, "basis": "observed tokens at the highest API model price"}
