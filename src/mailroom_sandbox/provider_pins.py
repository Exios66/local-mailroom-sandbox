"""Pin OpenRouter providers per model and record what actually served each call (R01).

The vendored chat agents (``agents.base.BaseAgent._call_llm``) send
``retry_chat_completion(client, **kwargs)`` and record only the served model. The
runbook needs two more facts per call: that the request was routed to the pinned
provider(s) without silent fallback, and which provider answered. Like
``llm_timeout`` and ``source_windows``, this module wraps the vendored function at
activation instead of editing ``vendor/`` (drift-guarded):

* ``config/provider_pins.yaml`` maps a model id to ``{order: [...], allow_fallbacks:
  false, canonical_slug: ...}``. A model with a non-empty ``order`` gets
  ``extra_body.provider.order`` / ``allow_fallbacks`` merged into every request
  (an existing ``provider`` block, e.g. ``require_parameters``, is kept).
* Every OpenRouter response's ``model`` and ``provider`` are appended to the
  process ledger and, when ``SANDBOX_SERVED_LOG`` names a file, to that JSONL.
  A served provider outside the pinned order is a ``mismatch``.

Provider names compare case-insensitively. A served model that is neither the
requested id nor its ``canonical_slug`` (dated slug) is also a mismatch. A request
that already names a fallback chain (``extra_body.models``) is recorded but not
pinned, since its route is meant to move: any model in that chain is allowed and its
provider is not compared.

Each entry's ``status`` is ``verified`` only when a non-empty pin and the response's
provider and model were all observed and agree; ``mismatch`` when a difference was
seen; otherwise ``unverified`` (no pin, an unpinned fallback chain, or the response
omitted its provider or model). ``mismatch: false`` alone is not evidence: R01
requires ``status: verified``.

Not covered: the LangChain contract / merger agents (``ChatOpenAI``) and any module
that imported ``retry_chat_completion`` by name before activation (for example the
PDF transcriber). Pin those through their route's ``model_kwargs`` if they join an
R01 smoke run.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

import yaml

from mailroom_sandbox.paths import repo_root

_log = logging.getLogger(__name__)
PINS_PATH = repo_root() / "config" / "provider_pins.yaml"
_LOCK = threading.Lock()
_LEDGER: list[dict[str, Any]] = []
_ORIGINAL: Callable[..., Any] | None = None
_ACTIVE: dict[str, dict[str, Any]] = {}


def load_pins(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = Path(path or PINS_PATH)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = data.get("models") or {}
    out: dict[str, dict[str, Any]] = {}
    for model, pin in models.items():
        pin = dict(pin or {})
        order = [str(p) for p in (pin.get("order") or [])]
        out[str(model)] = {
            "order": order,
            "allow_fallbacks": bool(pin.get("allow_fallbacks", False)),
            "canonical_slug": pin.get("canonical_slug"),
        }
    return out


def _is_openrouter(client: Any) -> bool:
    return "openrouter.ai" in str(getattr(client, "base_url", "") or "")


def pinned_kwargs(model: str, kwargs: dict[str, Any], pins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return kwargs with the model's provider pin merged into ``extra_body.provider``."""
    pin = pins.get(model)
    if not pin or not pin["order"]:
        return kwargs
    extra = dict(kwargs.get("extra_body") or {})
    if extra.get("models"):
        return kwargs  # an explicit fallback chain is meant to move; record only
    provider = dict(extra.get("provider") or {})
    provider["order"] = list(pin["order"])
    provider["allow_fallbacks"] = pin["allow_fallbacks"]
    extra["provider"] = provider
    return {**kwargs, "extra_body": extra}


def served_provider(response: Any) -> str | None:
    value = getattr(response, "provider", None)
    if not value:
        extra = getattr(response, "model_extra", None) or {}
        value = extra.get("provider") if isinstance(extra, dict) else None
    return str(value) if value else None


def _record(model: str, response: Any, pins: dict[str, dict[str, Any]], *,
            fallback_models: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """Ledger entry for one response, checked against the route the request actually used."""
    pin = pins.get(model) or {}
    provider = served_provider(response)
    served_model = getattr(response, "model", None)
    served = served_model if isinstance(served_model, str) and served_model else None
    order = [] if fallback_models else list(pin.get("order") or [])  # a fallback chain is not pinned
    provider_off = bool(order) and provider is not None and provider.casefold() not in {
        p.casefold() for p in order
    }
    allowed = {model.casefold()} | {str(m).casefold() for m in fallback_models}
    for m in (model, *fallback_models):
        slug = (pins.get(str(m)) or {}).get("canonical_slug")
        if slug:
            allowed.add(str(slug).casefold())
    model_off = bool(pin or fallback_models) and served is not None and served.casefold() not in allowed
    verified = bool(order) and provider is not None and served is not None and not (provider_off or model_off)
    status = "mismatch" if provider_off or model_off else "verified" if verified else "unverified"
    entry = {
        "requested_model": model,
        "served_model": served,
        "served_provider": provider,
        "pinned_order": order,
        "fallback_models": list(fallback_models),
        "provider_mismatch": provider_off,
        "model_mismatch": model_off,
        "mismatch": provider_off or model_off,
        "status": status,
    }
    with _LOCK:
        _LEDGER.append(entry)
        log = os.environ.get("SANDBOX_SERVED_LOG")
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
    if entry["mismatch"]:
        _log.warning("pin mismatch for %s: served %s by %s (pin %s)", model, served, provider, order)
    return entry


def ledger() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_LEDGER)


def reset_ledger() -> None:
    with _LOCK:
        _LEDGER.clear()


def summarize(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per requested model: calls, served models, served providers, and mismatch / verified / unverified counts."""
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        s = out.setdefault(e["requested_model"], {"calls": 0, "served_models": {}, "providers": {}, "mismatches": 0,
                                                  "verified": 0, "unverified": 0})
        s["calls"] += 1
        s["served_models"][str(e["served_model"])] = s["served_models"].get(str(e["served_model"]), 0) + 1
        s["providers"][str(e["served_provider"])] = s["providers"].get(str(e["served_provider"]), 0) + 1
        s["mismatches"] += int(e["mismatch"])
        status = e.get("status") or ("mismatch" if e["mismatch"] else "unverified")
        if status in ("verified", "unverified"):
            s[status] += 1
    return out


def apply_provider_pins(pins: dict[str, dict[str, Any]] | None = None) -> int:
    """Wrap the vendored ``retry_chat_completion``; returns the number of pinned models.

    Idempotent: re-activation swaps the pin table, never stacks wrappers.
    """
    global _ORIGINAL, _ACTIVE
    import agents.base as base
    import llm.retry as retry

    _ACTIVE = load_pins() if pins is None else pins
    if _ORIGINAL is None:
        _ORIGINAL = retry.retry_chat_completion

    original = _ORIGINAL

    def pinned_retry_chat_completion(client, **kwargs):
        model = str(kwargs.get("model") or "")
        openrouter = _is_openrouter(client)
        fallback = [str(m) for m in ((kwargs.get("extra_body") or {}).get("models") or [])]
        pins = _ACTIVE  # one snapshot per call: a re-activation mid-call cannot change the pin it is checked against
        if openrouter:
            kwargs = pinned_kwargs(model, kwargs, pins)
        response = original(client, **kwargs)
        if openrouter:
            try:
                _record(model, response, pins, fallback_models=fallback)
            except Exception as exc:  # noqa: BLE001 — recording never fails a call
                _log.warning("served-provider record failed: %s", exc)
        return response

    pinned_retry_chat_completion.__wrapped__ = original  # type: ignore[attr-defined]
    retry.retry_chat_completion = pinned_retry_chat_completion
    base.retry_chat_completion = pinned_retry_chat_completion
    return sum(1 for p in _ACTIVE.values() if p["order"])


def restore() -> None:
    """Put the vendored function back (tests)."""
    global _ORIGINAL
    if _ORIGINAL is None:
        return
    import agents.base as base
    import llm.retry as retry

    retry.retry_chat_completion = _ORIGINAL
    base.retry_chat_completion = _ORIGINAL
    _ORIGINAL = None
