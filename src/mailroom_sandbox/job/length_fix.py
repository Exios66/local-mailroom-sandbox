"""Default Qwen3 length-fix sampling for a pipeline's chunked specialists (#214).

The #214 window runs (SAND-214, 2026-11-21) showed the failure mode: on
Qwen3-8B-AWQ a chunk window's decode can run to the output cap and vLLM raises
``LengthFinishReasonError``, which the vendored chunked pass records as
``chunk_call_failed`` and drops from the deterministic merge. Contracts r1 lost
a window on 5 of 30 documents (those scored 0.467 against 0.616 overall, and the
window-rule audit had to exclude them). Contracts r2 adds the Qwen3
non-thinking sampling (temperature 0.7, top_p 0.8, top_k 20, presence_penalty
1.0) plus one re-sample on a length-capped window and lost none, gaining +0.036
mean on the same documents (reports/SAND-214/2026-11-21/README.md).

A ``task: pipeline`` run that serves its specialists on a self-hosted vLLM
engine gets the same sampling as the default for the five specialist agents,
because the vendored graph chunks long documents for every one of them
(``graph/build_graph.py:_run_chunked_extraction``). A run that sets its own
knobs for an agent (``agent_knobs``, or a posture row through
``agent_knobs_for_run``) keeps them: the default fills only agents the run
configure nothing for, and an explicit ``length_retries`` (0 included) is the
documented opt-out. Temperature is deliberately not defaulted — the call-site
literal stands unless the run sets one.

OpenRouter engines never chunk (HF-009/HF-010), so an API run needs none of
this. The knobs freeze into the lock at preflight (``_run_knobs``), so the
locked run executes exactly what preflight disclosed.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

# The Qwen3 non-thinking sampling plus one length re-sample (SAND40_OPTIMIZED_KNOBS
# values; a unit test pins the two tables to the same numbers, so a posture edit
# and this default cannot drift apart silently).
QWEN3_LENGTH_FIX: dict[str, Any] = {
    "top_p": 0.8,
    "top_k": 20,
    "presence_penalty": 1.0,
    "length_retries": 1,
}

# Every specialist the vendored graph may send through the chunked pass.
CHUNKED_SPECIALISTS: frozenset[str] = frozenset({
    "contracts_specialist",
    "merger_agreement_specialist",
    "corporate_records_specialist",
    "correspondence_specialist",
    "insurance_claims_specialist",
})

# Model families with the runaway-decode failure mode (#214 r1). Matched as a
# prefix on the engine model id.
_QWEN3_PREFIX = "qwen/qwen3"


def is_qwen3_family(model: str | None) -> bool:
    """True for the Qwen3 model family (Qwen3, Qwen3-8B-AWQ, Qwen3.5, ...)."""
    return bool(model) and str(model).lower().startswith(_QWEN3_PREFIX)


def self_hosted_vllm(spec: Any) -> bool:
    """True when the run's specialists serve on a vLLM endpoint we deploy."""
    engine = getattr(spec, "engine", None)
    return engine is not None and engine.kind in ("vllm-local", "vllm-remote", "modal-vllm")


def with_length_fix_defaults(knobs: Mapping[str, Mapping[str, Any]] | None, spec: Any) -> dict[str, dict[str, Any]]:
    """Merge the default sampling into unconfigured specialist agents.

    Applies to a ``task: pipeline`` run on a self-hosted vLLM Qwen3 engine. An
    agent the run (or a posture row) already configured keeps its own knobs,
    including an explicit ``length_retries: 0`` opt-out. Returns a deep copy, so
    the caller's snapshot and the lock stay independent.
    """
    out: dict[str, dict[str, Any]] = copy.deepcopy(dict(knobs or {}))
    if getattr(spec, "task", None) != "pipeline":
        return out
    if not self_hosted_vllm(spec):
        return out
    if not is_qwen3_family(getattr(getattr(spec, "engine", None), "model", None)):
        return out
    for agent in sorted(CHUNKED_SPECIALISTS):
        if agent not in out or not out[agent]:
            out[agent] = dict(QWEN3_LENGTH_FIX)
    return out
