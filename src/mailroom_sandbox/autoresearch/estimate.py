"""Worst-case cost of a candidate round, before it runs.

The champion's measured tokens, per agent, repriced at the candidate's models at their dearest
tier (``metrics.token_price_ceiling``). A round whose estimate exceeds the round cap is skipped
with a ledger row instead of being left to abort mid-way when the run's own cap trips.

Rules:

- each agent's tokens are priced at the candidate's model for it: ``agent_models``, else its
  ``agent_routes`` model, else the engine model;
- a candidate decision reviewer (backend ``decisions``) replaces the champion's reviewer tokens
  with one request per document: the document capped at the question set's ``max_input_chars``
  (0.25 tokens per character) plus the question text, input tokens only; an extraction gate the
  champion lacks adds the same per document;
- a champion run without the per-agent split prices all its tokens at the candidate's dearest
  model (an upper bound);
- tokens are scaled by ``safety`` (default 1.0: the measured tokens, as briefed).

Two figures are reported. ``usd`` prices each agent's tokens at its own model (the oversight tokens at the
candidate's rate). ``runtime_bound_usd`` is what the runtime ``ApiBudget`` (``job/api_budget.py``) will count:
it prices EVERY token of the run at the dearest API model in the candidate's run (``price_bound`` over
``spec_api_models``), so a cheap worker's tokens are charged at the supervisor's price. The round-cap decision
uses the runtime bound, because that is what aborts a run. A decisions reviewer or gate adds its input tokens to
the bound's prompt side, and the champion's own reviewer tokens stay in it (an upper bound).

A model with no price is listed in ``unpriced`` and the estimate is unusable (``usd`` is infinite).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from mailroom_sandbox.autoresearch.levers import QUESTION_TOKENS, TOKENS_PER_CHAR
from mailroom_sandbox.autoresearch.scoring import RunScores


@dataclass
class Estimate:
    usd: float
    basis: str
    detail: dict[str, float] = field(default_factory=dict)
    unpriced: list[str] = field(default_factory=list)
    runtime_bound_usd: float | None = None           # the ApiBudget's view; None for a hand-built estimate
    runtime_bound_detail: dict[str, Any] = field(default_factory=dict)
    measured: bool = True                            # the champion recorded tokens to scale from

    @property
    def cap_usd(self) -> float:
        """The figure the round-cap decision uses: the runtime bound, else ``usd``."""
        return self.usd if self.runtime_bound_usd is None else self.runtime_bound_usd

    def to_dict(self) -> dict[str, Any]:
        def fin(value: float | None) -> float | None:
            return None if value is None or math.isinf(value) else round(value, 4)

        return {"usd": fin(self.usd), "runtime_bound_usd": fin(self.runtime_bound_usd), "basis": self.basis,
                "detail": self.detail, "runtime_bound": self.runtime_bound_detail, "unpriced": self.unpriced,
                "measured": self.measured}


#: Cap of a ``round_cap_auto`` lever by tier while the champion has no token measurement to scale from.
TIER_DEFAULT_CAPS = {1: 1.5, 2: 3.0, 3: 4.0}
CAP_MARGIN = 1.2
CAP_STEP = 0.25


def auto_round_cap(est: Estimate, *, base_cap: float, max_cap: float, tier: int | None = None) -> float:
    """The derived round cap: the runtime bound x 1.2 rounded up to $0.25, within ``[base_cap, max_cap]``.

    Without a champion measurement (or with an unusable estimate) the per-tier default applies
    (tier 1: 1.5, tier 2: 3, tier 3 and above: 4 USD), still clamped to ``max_cap``.
    """
    bound = est.cap_usd
    if est.measured and math.isfinite(bound) and bound > 0:
        cap = math.ceil(bound * CAP_MARGIN / CAP_STEP - 1e-9) * CAP_STEP
    else:
        cap = TIER_DEFAULT_CAPS.get(min(max(int(tier or 1), 1), 3), TIER_DEFAULT_CAPS[3])
    return min(max(cap, base_cap), max_cap)


def round_cap_for(lever: Any, est: Estimate, *, base_cap: float, max_cap: float) -> float:
    """The ``job.api_cost_cap_usd`` of ``lever``'s round: its override, its derived cap, or the study's round cap."""
    if getattr(lever, "round_cap_usd", None) is not None:
        return min(float(lever.round_cap_usd), max_cap)
    if getattr(lever, "round_cap_auto", False):
        return auto_round_cap(est, base_cap=base_cap, max_cap=max_cap, tier=getattr(lever, "tier", None))
    return base_cap


def agent_model(spec: Mapping[str, Any], agent: str) -> str:
    """The model ``agent`` runs on in ``spec`` (a per-agent model, else its route, else the engine)."""
    models = spec.get("agent_models") or {}
    routes = spec.get("agent_routes") or {}
    if models.get(agent):
        return str(models[agent])
    if (routes.get(agent) or {}).get("model"):
        return str(routes[agent]["model"])
    return str((spec.get("engine") or {}).get("model") or "")


def _decision_tokens(champ: RunScores, stem: str | None) -> int:
    from mailroom_sandbox.decision_backends import DECISIONS_MAX_INPUT_CHARS, load_question_set

    cap = DECISIONS_MAX_INPUT_CHARS
    if stem:
        try:
            cap = int(load_question_set(stem).get("max_input_chars") or cap)
        except Exception:  # noqa: BLE001 - an unreadable set is the preflight's finding
            pass
    return sum(int(min(d.doc_chars or cap, cap) * TOKENS_PER_CHAR) + QUESTION_TOKENS for d in champ.docs)


def estimate_round_cost(champ: RunScores, champ_spec: Mapping[str, Any], cand_spec: Mapping[str, Any], *,
                        safety: float = 1.0) -> Estimate:
    """Worst-case USD of running ``cand_spec`` on the champion's draw, from the champion's token counts."""
    from mailroom_sandbox.job.metrics import token_price_ceiling

    detail: dict[str, float] = {}
    unpriced: set[str] = set()

    def price(model: str) -> tuple[float, float] | None:
        found = token_price_ceiling(model) if model and model != "mock" else (0.0, 0.0)
        if found is None:
            unpriced.add(model)
        return found

    cand_rev = cand_spec.get("reviewer") or {}
    usage = champ.agent_usage()
    if usage:
        for agent, slot in usage.items():
            if agent == "sorter_reviewer" and cand_rev.get("backend") == "decisions":
                continue  # replaced by the decisions request below
            p = price(agent_model(cand_spec, agent))
            if p is not None:
                detail[agent] = (slot["prompt_tokens"] * p[0] + slot["completion_tokens"] * p[1]) * safety / 1e6
        basis = "by_agent"
    else:
        models = {agent_model(cand_spec, a) for a in ("sorter", "judge", "arbiter", "boss", "sorter_reviewer")}
        models |= {str((cand_spec.get("engine") or {}).get("model") or "")}
        prices = [p for m in models if m and (p := price(m)) is not None]
        dearest = max((max(p) for p in prices), default=0.0)
        detail["all_tokens"] = sum(d.tokens for d in champ.docs) * dearest * safety / 1e6
        basis = "totals"
    if cand_rev.get("backend") == "decisions":
        p = price(str(cand_rev.get("model") or ""))
        if p is not None:
            detail["reviewer(decisions)"] = _decision_tokens(champ, cand_rev.get("questions")) * p[0] * safety / 1e6
    gate, champ_gate = cand_spec.get("extraction_gate") or {}, champ_spec.get("extraction_gate") or {}
    if gate and gate != champ_gate:
        p = price(str(gate.get("model") or ""))
        if p is not None:
            detail["extraction_gate"] = _decision_tokens(champ, gate.get("questions")) * p[0] * safety / 1e6
    bound, bound_detail = _runtime_bound(champ, usage, cand_spec, champ_spec, safety, unpriced)
    usd = math.inf if unpriced else sum(detail.values())
    measured = bool(usage) or any(d.tokens for d in champ.docs)
    return Estimate(usd=usd, basis=basis, detail={k: round(v, 6) for k, v in detail.items()}, unpriced=sorted(unpriced),
                    runtime_bound_usd=math.inf if unpriced else bound, runtime_bound_detail=bound_detail, measured=measured)


def _api_models(cand_spec: Mapping[str, Any]) -> list[str]:
    """The token-billed models the runtime budget will price: what ``api_budget.api_models(lock)`` finds in the lock.

    ``api_budget.spec_api_models`` resolves the engine, agent models and routes the way preflight does, but it
    leaves the reviewer out. The lock has it (any backend of ``decisions``, ``local``, ``api``, ``jev``), and the
    extraction gate, so both are added here and the bound prices them like the run's own ``ApiBudget`` does.
    """
    from mailroom_sandbox.autoresearch.levers import LeverError, validate_spec
    from mailroom_sandbox.job import api_budget

    try:
        models = set(api_budget.spec_api_models(validate_spec(cand_spec, where="estimate")))
    except LeverError:   # a partial spec (never a real candidate: those validated when the lever was applied)
        shaped = {k: cand_spec.get(k) for k in ("engine", "agent_models", "agent_routes")}
        models = set(api_budget.api_models({k: v for k, v in shaped.items() if v}))
    oversight = {k: cand_spec[k] for k in ("reviewer", "extraction_gate") if cand_spec.get(k)}
    return sorted(models | set(api_budget.api_models(oversight)))


def _runtime_bound(champ: RunScores, usage: Mapping[str, Any], cand_spec: Mapping[str, Any], champ_spec: Mapping[str, Any],
                   safety: float, unpriced: set[str]) -> tuple[float, dict[str, Any]]:
    """The ApiBudget's USD for the champion's tokens on the candidate's run: all of them at the dearest API model."""
    from mailroom_sandbox.job import api_budget

    from mailroom_sandbox.autoresearch.levers import validate_spec

    if validate_spec(cand_spec, where="candidate spec").job.mock:   # the validated value: a quoted "false" is a paid run
        return 0.0, {"models": [], "note": "mock run: no API budget"}
    models = _api_models(cand_spec)
    if usage:
        prompt = sum(int(s["prompt_tokens"]) for s in usage.values())
        completion = sum(int(s["completion_tokens"]) for s in usage.values())
    else:
        prompt, completion = sum(d.tokens for d in champ.docs), 0
    cand_rev, gate = cand_spec.get("reviewer") or {}, cand_spec.get("extraction_gate") or {}
    if cand_rev.get("backend") == "decisions":
        prompt += _decision_tokens(champ, cand_rev.get("questions"))
    if gate and gate != (champ_spec.get("extraction_gate") or {}):
        prompt += _decision_tokens(champ, gate.get("questions"))
    try:
        price_in, price_out = api_budget.price_bound(models)
    except ValueError:
        unpriced.update(api_budget.unpriced(models))
        return math.inf, {"models": models, "prompt_tokens": prompt, "completion_tokens": completion}
    if not usage:   # totals only: no prompt/completion split, so every token at the dearer side
        price_in = price_out = max(price_in, price_out)
    usd = (prompt * price_in + completion * price_out) * safety / 1e6
    return usd, {"models": models, "prompt_tokens": prompt, "completion_tokens": completion,
                 "usd_per_m": [price_in, price_out], "safety": safety}
