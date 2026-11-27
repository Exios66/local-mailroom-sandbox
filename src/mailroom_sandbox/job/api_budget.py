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

import itertools
import math
import threading
from collections.abc import Iterable, Mapping
from typing import Any

API_PROVIDERS = frozenset({"openrouter"})


def task_agents(lock: Mapping[str, Any]) -> set[str] | None:
    """The agents a run's task calls, or None when it may call any (pipeline and the like).

    A single-agent task calls only that agent, so the profile's other assignments (for
    example the openrouter judge on deepseek) never set the price of a Qwen sorter run.
    """
    task = str(lock.get("task") or "")
    if task == "isolated":
        # The isolated runner always runs the sorter spec, whatever job.task says (job/runner.py).
        return {"sorter"}
    if task == "sorter" or task.endswith("_specialist"):
        return {task}
    return None


def api_models(lock: Mapping[str, Any]) -> list[str]:
    """Token-billed models a locked run (or a lock-shaped spec dump) can call."""
    models: set[str] = set()
    assignments = lock.get("agent_assignments") or {}
    used = task_agents(lock)
    for name, assignment in assignments.items():
        if used is not None and name not in used:
            continue
        if str(assignment.get("provider")) in API_PROVIDERS and assignment.get("model"):
            models.add(str(assignment["model"]))
    agent_models = lock.get("agent_models") or {}
    for name, route in (lock.get("agent_routes") or {}).items():
        if (route or {}).get("provider") in API_PROVIDERS:
            models.add(str(agent_models.get(name) or route.get("model") or ""))
    engine = lock.get("engine") or {}
    if engine.get("kind") in API_PROVIDERS and not assignments:
        models.add(str(engine.get("model") or ""))
    # Reviewer model (e.g. openai/gpt-6-luna-decisions) bills tokens too.
    reviewer = lock.get("reviewer") or {}
    rev_model = reviewer.get("model")
    if rev_model and str(reviewer.get("backend", "")) in ("decisions", "local", "api", "jev"):
        models.add(str(rev_model))
    # The pipeline extraction gate bills the Decisions API whatever the engine is.
    gate = lock.get("extraction_gate") or {}
    if gate.get("model"):
        models.add(str(gate["model"]))
    # So does the decision_slots closed-field resolver.
    resolver = (lock.get("decision_slots") or {}).get("resolver") or {}
    if resolver.get("model"):
        models.add(str(resolver["model"]))
    # And the phase 4 correcting judge, in correct mode (verify mode runs the pipeline's judge model).
    from mailroom_sandbox.correcting_judge import judge_models

    models.update(judge_models(lock.get("judge")))
    return sorted(model for model in models if model)


def spec_api_models(spec: Any) -> list[str]:
    """``api_models`` for an unlocked RunSpec, resolved as preflight would lock it."""
    shaped: dict[str, Any] = {
        "task": spec.task,  # the lock carries it, and task_agents drops agents a single-agent task never calls
        "engine": spec.engine.model_dump(),
        "agent_models": dict(spec.agent_models),
        "agent_routes": {name: route.model_dump() for name, route in spec.agent_routes.items()},
    }
    if getattr(spec, "extraction_gate", None) is not None:
        shaped["extraction_gate"] = {"model": spec.extraction_gate.model}
    slots = getattr(spec, "decision_slots", None)
    if slots is not None and slots.resolver is not None:
        shaped["decision_slots"] = {"resolver": {"model": slots.resolver.model}}
    if getattr(spec, "judge", None) is not None:
        shaped["judge"] = spec.judge.model_dump()
    if spec.agent_routes or spec.agent_knobs or spec.agent_models:
        from mailroom_sandbox.agent_routes import describe

        shaped["agent_assignments"] = describe(spec)
    return api_models(shaped)


def unpriced(models: Iterable[str]) -> list[str]:
    from mailroom_sandbox.job.metrics import token_price

    return [model for model in models if token_price(model) is None]


def price_bound(models: Iterable[str]) -> tuple[float, float]:
    """Highest USD per 1M (input, output) tokens across ``models`` and their price tiers.

    Raises on an unpriced model.
    """
    from mailroom_sandbox.job.metrics import token_price_ceiling

    models = list(models)
    missing = unpriced(models)
    if missing:
        raise ValueError(f"no token price for {', '.join(missing)}")
    prices = [token_price_ceiling(model) for model in models]
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


_HOLD = itertools.count()


class ApiBudget:
    """Running API token spend against ``job.api_cost_cap_usd``.

    Checked between documents (finished-document usage) and, once live tracking starts, before
    every API call (``job.call_guard``): ``add_live`` prices each call as it returns, so a long
    document in flight is bounded too (rb1 R01: two merger documents ran ~140 calls past the
    between-document check).
    """

    def __init__(self, cap_usd: float, usd_per_m_in: float, usd_per_m_out: float, models: list[str]):
        self.cap_usd = float(cap_usd)
        self.usd_per_m_in = float(usd_per_m_in)
        self.usd_per_m_out = float(usd_per_m_out)
        self.models = list(models)
        self.spent_usd = 0.0
        self.documents = 0
        self.live_usd = 0.0  # per-call spend since start_live()
        self.reserved_usd = 0.0  # worst-case cost of requests sent but not yet settled (call_guard)
        self.settling_usd = 0.0  # a success's reservation, held until after_call prices the real usage
        self.unreported_usd = 0.0  # failed requests that may have been billed, charged at their reservation
        self._live_base: float | None = None  # spent_usd when live tracking started
        self._lock = threading.Lock()
        self._reserve_lock = threading.Lock()  # serialises check-and-reserve (try_reserve)
        self.hold_token = next(_HOLD)  # identifies this budget's unpriced successes; never reused

    def _cost(self, prompt_tokens: Any, completion_tokens: Any, calls: Any = 1, model: str | None = None) -> float:
        """Price the tokens at the named model's tier for the average call size.

        Unnamed or unpriced, every run model is priced and the dearest wins, so a call is never
        under-counted (a judge model on the run must not re-price every pipeline call, though).
        """
        from mailroom_sandbox.job.metrics import call_cost

        prompt = float(prompt_tokens or 0)
        completion = float(completion_tokens or 0)
        if model:
            own = call_cost(str(model), prompt, completion, calls=int(calls or 1))
            if own is not None:
                return own
        costs = [call_cost(m, prompt, completion, calls=int(calls or 1)) for m in self.models]
        known = [c for c in costs if c is not None]
        return max(known) if known else (prompt * self.usd_per_m_in + completion * self.usd_per_m_out) / 1_000_000

    def add(self, prompt_tokens: Any, completion_tokens: Any, calls: Any = 1) -> None:
        cost = self._cost(prompt_tokens, completion_tokens, calls)
        with self._lock:
            self.spent_usd += cost

    def start_live(self) -> None:
        """Begin per-call tracking from the spend persisted so far (a resume's items included)."""
        with self._lock:
            self._live_base = self.spent_usd
            self.live_usd = 0.0

    def add_live(self, prompt_tokens: Any, completion_tokens: Any, model: str | None = None) -> float:
        """Add one API call's usage as it returns (documents still in flight included); returns its cost."""
        cost = self._cost(prompt_tokens, completion_tokens, 1, model)
        with self._lock:
            self.live_usd += cost
        return cost

    def live_total_usd(self) -> float:
        """Spend observed call by call since ``start_live`` on top of the spend before it (0 when off)."""
        with self._lock:
            return 0.0 if self._live_base is None else self._live_base + self.live_usd

    def estimate_call_usd(self, prompt_tokens: float, completion_tokens: float, model: str | None = None) -> float:
        """The cost of one call of this size at ``model``'s tier, else the dearest model's (``call_guard``)."""
        return self._cost(prompt_tokens, completion_tokens, 1, model)

    def _usage_cost(self, usage: Mapping[str, Any]) -> float:
        """A finished document's cost: each ``usage_by_agent`` slot at its own model, the rest at the dearest."""
        prompt, completion = float(usage.get("prompt_tokens") or 0), float(usage.get("completion_tokens") or 0)
        calls = int(usage.get("llm_calls") or 1)
        slots = usage.get("usage_by_agent")
        if not isinstance(slots, Mapping) or not slots:
            return self._cost(prompt, completion, calls)
        total, p_left, c_left, n_left = 0.0, prompt, completion, calls
        for slot in slots.values():
            if not isinstance(slot, Mapping) or not slot.get("calls"):
                continue
            models = slot.get("models") or []
            sp, sc, sn = float(slot.get("prompt_tokens") or 0), float(slot.get("completion_tokens") or 0), int(slot["calls"])
            total += self._cost(sp, sc, sn, models[0] if len(models) == 1 else None)
            p_left, c_left, n_left = p_left - sp, c_left - sc, n_left - sn
        if p_left > 0 or c_left > 0:  # tokens no slot attributes: never left unpriced
            total += self._cost(max(p_left, 0.0), max(c_left, 0.0), max(n_left, 1))
        return total

    def reserve(self, usd: float) -> None:
        """Hold ``usd`` against the cap while a request is in flight."""
        with self._lock:
            self.reserved_usd += max(0.0, float(usd))

    def try_reserve(self, usd: float) -> str | None:
        """Check the cap with ``usd`` more and reserve it, as one step: why it is refused, or None.

        Concurrent requests cannot all pass the check before any of them reserves.
        """
        with self._reserve_lock:
            reason = self.exceeded(extra_usd=usd)
            if reason is None:
                self.reserve(usd)
            return reason

    def release(self, usd: float) -> None:
        """Drop a settled request's reservation (never below zero)."""
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - max(0.0, float(usd)))

    def release_to_settling(self, usd: float) -> None:
        """Move a finished success's reservation onto ``settling_usd`` until its usage is priced.

        The cap still counts it. Releasing first and pricing later lets another request pass in the gap.
        """
        usd = max(0.0, float(usd))
        with self._reserve_lock:
            with self._lock:
                self.reserved_usd = max(0.0, self.reserved_usd - usd)
                self.settling_usd += usd

    def price_settling(self, reserved_usd: float, cost: float) -> float:
        """Replace one success's held reservation with the priced cost of its usage. Returns that cost."""
        reserved_usd = max(0.0, float(reserved_usd))
        cost = max(0.0, float(cost))
        with self._reserve_lock:
            with self._lock:
                self.settling_usd = max(0.0, self.settling_usd - reserved_usd)
                self.live_usd += cost
        return cost

    def settle_billed(self, usd: float) -> None:
        """Drop a reservation and charge it, as one step (a failure the provider may have billed)."""
        usd = max(0.0, float(usd))
        with self._reserve_lock:
            with self._lock:
                self.reserved_usd = max(0.0, self.reserved_usd - usd)
                self.live_usd += usd
                self.unreported_usd += usd

    def release_unbilled(self, usd: float) -> None:
        """Drop a reservation the provider did not bill (HTTP 4xx, or the request never connected)."""
        usd = max(0.0, float(usd))
        with self._reserve_lock:
            with self._lock:
                self.reserved_usd = max(0.0, self.reserved_usd - usd)

    def charge_unreported(self, usd: float) -> None:
        """Charge a request that failed without usage but may have been billed (its reservation)."""
        usd = max(0.0, float(usd))
        with self._lock:
            self.live_usd += usd
            self.unreported_usd += usd

    def add_usage(self, usage: Mapping[str, Any] | None) -> None:
        """Add one finished (or failed) document's token usage, or a persisted unreported charge."""
        usage = usage or {}
        if usage.get("kind") == "unreported_charge":  # UNREPORTED_CHARGE_EVENT: spend, not a document
            with self._lock:
                self.spent_usd += max(0.0, float(usage.get("unreported_usd") or 0.0))
            return
        cost = self._usage_cost(usage)
        with self._lock:
            self.spent_usd += cost
            self.documents += 1

    def projected_usd(self, in_flight: int = 0) -> float:
        """Spend so far plus ``in_flight`` unfinished documents at the mean cost per finished document."""
        with self._lock:
            mean = self.spent_usd / self.documents if self.documents else 0.0
            return self.spent_usd + max(0, int(in_flight)) * mean

    def exceeded(self, in_flight: int = 0, extra_usd: float = 0.0) -> str | None:
        """Why no further document may start, or None.

        ``in_flight`` documents have started but not finished: their spend is not in the total yet,
        so concurrent runs count each at the mean finished-document cost. Requests in flight hold their
        reservation (``reserved_usd``), a success not yet priced holds ``settling_usd``, and ``extra_usd``
        is the next request's own estimate.
        """
        # Per-call spend bounds documents still running; the projection covers the rest.
        with self._lock:
            reserved = self.reserved_usd
            settling = self.settling_usd
        projected = max(self.projected_usd(in_flight),
                        self.live_total_usd() + reserved + settling + max(0.0, extra_usd))
        if projected >= self.cap_usd:
            pending = f", {in_flight} in flight" if in_flight else ""
            if reserved:
                pending += f", ${reserved:.4f} reserved"
            if settling:
                pending += f", ${settling:.4f} awaiting price"
            if extra_usd:
                pending += f", next call est ${extra_usd:.4f}"
            return (f"api_cost_cap_usd={self.cap_usd} reached (est_api_usd={projected:.4f}{pending} "
                    f"at ${self.usd_per_m_in}/${self.usd_per_m_out} per 1M tokens) — aborting to protect spend")
        return None

    def check(self, prefix: str = "", in_flight: int = 0) -> None:
        """Raise when the cap is reached, counting ``in_flight`` documents (see ``exceeded``)."""
        reason = self.exceeded(in_flight)
        if reason:
            raise RuntimeError(prefix + reason)


FAILED_USAGE_EVENT = "api_usage_of_failed_document"
#: A resume re-ran (and re-billed) a document an earlier attempt had already persisted as an item.
RERUN_USAGE_EVENT = "api_usage_of_rerun_document"
#: Requests that failed without usage but may have been billed (call_guard), charged at their reservation.
UNREPORTED_CHARGE_EVENT = "api_unreported_charge"


def usage_records(store: Any) -> list[dict[str, Any]]:
    """Every persisted item, plus each paid call without an item row: a document that raised, a resumed
    re-run, an unreported charge."""
    extra = [event.get("detail") or {} for event in store.events()
             if event.get("event") in (FAILED_USAGE_EVENT, RERUN_USAGE_EVENT, UNREPORTED_CHARGE_EVENT)]
    return [*store.load_items(), *extra]


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
            "models": models, "basis": "observed tokens at each call's price tier, the highest API model price"}
