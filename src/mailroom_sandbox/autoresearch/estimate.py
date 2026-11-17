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
    usd = math.inf if unpriced else sum(detail.values())
    return Estimate(usd=usd, basis=basis, detail={k: round(v, 6) for k, v in detail.items()}, unpriced=sorted(unpriced))
