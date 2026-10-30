"""Explicit initials attestation bound to a verified run generation and its endpoints.

This records an operator's review, not cryptographic proof of personal identity.
No credential values are written to the receipt or displayed during review.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from typing import Any

from mailroom_sandbox.job.checkpoint import RunStore, _atomic_write
from mailroom_sandbox.services._exec import ServiceError
from mailroom_sandbox.services._redact import redact_urls

RECEIPT = "spend-authorization.json"
MAX_AGE_S = 24 * 3600
ATTESTATION = "I reviewed all settings and authorize the displayed Modal/OpenRouter spend."


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return redact_urls(value) if isinstance(value, str) else value


def paid(lock: dict, *, probe: bool = False) -> bool:
    job = lock.get("job") or {}
    return job.get("mode") == "modal" or (not job.get("mock", True) and bool(lock.get("agent_routes"))) or (
        (probe or not job.get("mock", True)) and (
            (lock.get("engine") or {}).get("kind") in {"modal-vllm", "openrouter"}
            or lock.get("profile") in {"modal-vllm", "openrouter"}
        )
    )


def review_settings(store: RunStore) -> dict[str, Any]:
    from mailroom_sandbox.job.otel import resolve_sink
    from mailroom_sandbox.overlay import load_profile
    from mailroom_sandbox.providers import endpoints_for, modal_gateway_url

    lock = store.verify_generation()
    profile = load_profile(lock["profile"])
    endpoint = endpoints_for(profile).base_url
    if lock.get("profile") == "modal-vllm":
        endpoint = os.environ.get("VLLM_BASE_URL", "").strip() or modal_gateway_url(profile) or "unresolved (deploy required)"
    trace = lock.get("trace") or {}
    sink = resolve_sink(sink=trace.get("sink", "none"), otlp=trace.get("otlp", True),
                        endpoint=trace.get("endpoint"), environment=trace.get("environment", "pilot"))
    context = {
        "provider_endpoint": endpoint,
        "trace_endpoint": sink.endpoint,
        "modal_workspace": os.environ.get("MODAL_WORKSPACE", "").strip(),
        "modal_profile": os.environ.get("MODAL_PROFILE", ""),
        "modal_environment": os.environ.get("MODAL_ENVIRONMENT", ""),
    }
    if lock.get("agent_routes"):
        from mailroom_sandbox.agent_routes import endpoint
        from mailroom_sandbox.job.spec import AgentRoute
        for name, raw in lock["agent_routes"].items():
            route = AgentRoute.model_validate(raw)
            context[f"agent_endpoint:{name}"] = endpoint(route)
    # Raw URLs are hashed in memory; only redacted context is persisted/displayed.
    fingerprint = hashlib.sha256(json.dumps({"lock": lock, "prompt": store.read_prompt_lock(),
                                            "context": context}, sort_keys=True).encode()).hexdigest()
    return _safe({"run_id": store.run_id, "fingerprint": fingerprint,
            "generation_id": lock.get("generation_id"), "settings": lock.get("spec_core"),
            "agent_knobs": lock.get("agent_knobs", {}), "dataset": lock.get("dataset"),
            "agents": lock.get("agent_assignments", {}),
            "context": {key: redact_urls(value) if isinstance(value, str) else value for key, value in context.items()},
            "budget_note": "Modal cost caps estimate GPU time; CPU/build/scaledown and in-flight calls can add cost. OpenRouter billing is token-based; the GPU-time cap is not an API dollar limit."})


def require_budget(lock: dict) -> None:
    job = lock.get("job") or {}
    cap = job.get("cost_cap_usd")
    wall = job.get("max_wall_seconds")
    if not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap <= 0 or not wall:
        raise ServiceError("paid execution requires finite job.cost_cap_usd and job.max_wall_seconds; review and re-preflight the configuration")


def authorize(store: RunStore, *, initials: str | None = None, probe: bool = False,
              extra: dict | None = None) -> dict | None:
    """Verify a current receipt or display the complete review and require initials."""
    lock = store.verify_generation()
    if not paid(lock, probe=probe):
        return None
    require_budget(lock)
    review = review_settings(store)
    if extra:
        review["workflow"] = extra
        review["fingerprint"] = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
    path = store.dir / RECEIPT
    try:
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict):
            raise ValueError("invalid receipt")
        age = time.time() - float(receipt["signed_at"])
        if receipt.get("schema") == "mailroom.spend-authorization/v1" and receipt.get("fingerprint") == review["fingerprint"] and 0 <= age < MAX_AGE_S and re.fullmatch(r"[A-Z]{2,6}", receipt.get("initials", "")):
            return receipt
    except (OSError, ValueError, TypeError, KeyError):
        pass
    print("Spend review (no paid action has started):", file=sys.stderr)
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    print(ATTESTATION, file=sys.stderr)
    if initials is None:
        if not sys.stdin.isatty():
            raise ServiceError("spend is NOT authorized: review the settings and supply --initials YOUR_INITIALS, or run interactively")
        try:
            initials = input("Sign with your initials (2–6 letters; blank cancels): ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise ServiceError("spend authorization cancelled; no paid action started") from exc
    initials = initials.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,6}", initials):
        raise ServiceError("spend is NOT authorized: initials must contain 2–6 letters")
    receipt = {"schema": "mailroom.spend-authorization/v1", **review, "initials": initials,
               "signed_at": time.time(), "attestation": ATTESTATION}
    _atomic_write(path, json.dumps(receipt, indent=2, sort_keys=True))
    path.chmod(0o600)
    store.append_event("spend_authorized", "info", initials=initials, fingerprint=review["fingerprint"])
    return receipt
