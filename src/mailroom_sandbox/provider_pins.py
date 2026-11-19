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

The vendored LangChain agents (``langchain_agents.base_agent``: the sorter and the
contracts / merger specialists) build their own ``ChatOpenAI`` and never reach
``retry_chat_completion``. Activation also swaps ``base_agent.ChatOpenAI`` for a subclass
that merges the same pin into each request payload's ``extra_body.provider`` (after any
``bind(extra_body=...)``, so a reasoning-effort bind keeps the pin) and records each
chat-completions response into the same ledger with the same status rules
(``call_path: langchain``). Like ``llm_timeout`` it subclasses whatever class is installed,
and re-activation never stacks a second pin subclass.

Decisions-API calls (``decision_backends.decide`` / ``decide_extraction``) are recorded with
``call_path: decisions``. OpenRouter takes no provider order there; the pin is the dated
``canonical_slug`` in ``config/decision_models.yaml``, so a row is ``verified`` when the
served model equals the requested id or that slug, ``mismatch`` when it differs, and
``unverified`` when the response omits it or the catalog has no slug.

Not covered: any module that imported ``retry_chat_completion`` by name before
activation (for example the PDF transcriber), and LangChain requests sent through the
Responses API or streamed (the vendored agents do neither). A smoke run that relies on
those paths leaves rows missing, and the R01 gate (``scripts/check_r01_smoke.py``) fails
on missing rows.
"""

from __future__ import annotations

import contextvars
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
# LangChain path: the ChatOpenAI class installed before the pin subclass, and the
# (model, pins, fallback chain) of the request in flight in this thread / task.
_LC_ORIGINAL: type | None = None
_LC_PENDING: contextvars.ContextVar[tuple[str, dict[str, dict[str, Any]], list[str]] | None] = (
    contextvars.ContextVar("provider_pins_lc_pending", default=None))
CALL_PATHS = ("retry_chat_completion", "langchain", "decisions")


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


def _field(response: Any, name: str) -> Any:
    """``name`` from an SDK response object (attribute or pydantic extra) or a plain dict."""
    if isinstance(response, dict):
        return response.get(name)
    value = getattr(response, name, None)
    if not value:
        extra = getattr(response, "model_extra", None) or {}
        value = extra.get(name) if isinstance(extra, dict) else None
    return value


def _provider_key(name: str) -> str:
    """A provider name or tag reduced to letters and digits: ``Z.AI`` and ``z-ai`` both give ``zai``."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def provider_in_order(provider: str, order: list[str] | tuple[str, ...]) -> bool:
    """True when a served provider is one the pin allows.

    OpenRouter names the served provider by display name (``DeepInfra``, ``Z.AI``) while a pin
    holds endpoint tags (``deepinfra/bf16``, ``z-ai/fp8``), so a tag matches on its provider part,
    the text before the first ``/``. The quantization part of a tag is not reported by the
    response and cannot be checked here.
    """
    served = _provider_key(provider)
    return any(served in {_provider_key(p), _provider_key(str(p).split("/", 1)[0])} for p in order)


def served_provider(response: Any) -> str | None:
    value = _field(response, "provider")
    return str(value) if value else None


def _append(entry: dict[str, Any]) -> None:
    with _LOCK:
        _LEDGER.append(entry)
        log = os.environ.get("SANDBOX_SERVED_LOG")
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _record(model: str, response: Any, pins: dict[str, dict[str, Any]], *,
            fallback_models: list[str] | tuple[str, ...] = (),
            call_path: str = "retry_chat_completion") -> dict[str, Any]:
    """Ledger entry for one response, checked against the route the request actually used."""
    pin = pins.get(model) or {}
    provider = served_provider(response)
    served_model = _field(response, "model")
    served = served_model if isinstance(served_model, str) and served_model else None
    order = [] if fallback_models else list(pin.get("order") or [])  # a fallback chain is not pinned
    provider_off = bool(order) and provider is not None and not provider_in_order(provider, order)
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
        "call_path": call_path,
    }
    _append(entry)
    if entry["mismatch"]:
        _log.warning("pin mismatch for %s: served %s by %s (pin %s)", model, served, provider, order)
    return entry


def record_decision(model: str, data: Any, canonical_slug: str | None) -> dict[str, Any]:
    """Ledger entry for one Decisions-API response (``call_path: decisions``).

    The pin is the dated ``canonical_slug``: ``verified`` needs one, and a served model equal
    to the requested id (with or without its ``:variant``) or the slug. A different served
    model is a ``mismatch``. The served provider is recorded when named, never compared.
    """
    served_model = _field(data, "model")
    served = served_model if isinstance(served_model, str) and served_model else None
    allowed = {str(model).casefold(), str(model).split(":", 1)[0].casefold()}
    if canonical_slug:
        allowed.add(str(canonical_slug).casefold())
    model_off = served is not None and served.casefold() not in allowed
    verified = bool(canonical_slug) and served is not None and not model_off
    entry = {
        "requested_model": model,
        "served_model": served,
        "served_provider": served_provider(data),
        "pinned_order": [],
        "canonical_slug": canonical_slug,
        "fallback_models": [],
        "provider_mismatch": False,
        "model_mismatch": model_off,
        "mismatch": model_off,
        "status": "mismatch" if model_off else "verified" if verified else "unverified",
        "call_path": "decisions",
    }
    _append(entry)
    if model_off:
        _log.warning("decision model mismatch for %s: served %s (pin %s)", model, served, canonical_slug)
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
    apply_langchain_pins()
    return sum(1 for p in _ACTIVE.values() if p["order"])


def pinned_chat_openai(parent: type) -> type:
    """A ``ChatOpenAI`` subclass of ``parent`` that pins and records OpenRouter requests.

    The pin is merged into the final request payload, so it holds for the client's own
    ``extra_body`` and for one bound per call. The pin table is read per request, so a
    re-activation swaps pins without rebuilding agents' clients.
    """

    class PinnedChatOpenAI(parent):  # type: ignore[misc, valid-type]
        _sandbox_provider_pins = True

        def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            if "openrouter.ai" not in str(getattr(self, "openai_api_base", "") or ""):
                _LC_PENDING.set(None)
                return payload
            model = str(payload.get("model") or getattr(self, "model_name", "") or "")
            pins = _ACTIVE  # one snapshot per request, as on the retry_chat_completion path
            fallback = [str(m) for m in ((payload.get("extra_body") or {}).get("models") or [])]
            _LC_PENDING.set((model, pins, fallback))
            return pinned_kwargs(model, payload, pins)

        def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> Any:
            pending = _LC_PENDING.get()
            _LC_PENDING.set(None)
            if pending is not None:
                model, pins, fallback = pending
                try:
                    _record(model, response, pins, fallback_models=fallback, call_path="langchain")
                except Exception as exc:  # noqa: BLE001 — recording never fails a call
                    _log.warning("served-provider record failed: %s", exc)
            return super()._create_chat_result(response, generation_info)

    PinnedChatOpenAI.__name__ = "ChatOpenAI"
    PinnedChatOpenAI.__qualname__ = "ChatOpenAI"
    return PinnedChatOpenAI


def apply_langchain_pins() -> bool:
    """Install the pin subclass as ``langchain_agents.base_agent.ChatOpenAI`` (idempotent).

    False when the vendored LangChain agents are unavailable (pipeline extra missing). A
    client an agent built before activation keeps its class.
    """
    global _LC_ORIGINAL
    try:
        from langchain_agents import base_agent  # type: ignore
    except Exception as exc:  # noqa: BLE001 — optional (pipeline extra)
        _log.debug("langchain_agents.base_agent unavailable — LangChain pins skipped: %s", exc)
        return False
    current = getattr(base_agent, "ChatOpenAI", None)
    if not isinstance(current, type):
        return False  # missing, or a test double that is not a class: nothing to subclass
    if getattr(current, "_sandbox_provider_pins", False):
        return True  # already pinned, possibly under a later llm_timeout subclass
    _LC_ORIGINAL = current
    base_agent.ChatOpenAI = pinned_chat_openai(current)
    return True


def langchain_pins_active() -> bool:
    """True when the vendored LangChain agents build pinned clients in this process."""
    try:
        from langchain_agents import base_agent  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    return bool(getattr(getattr(base_agent, "ChatOpenAI", None), "_sandbox_provider_pins", False))


def restore() -> None:
    """Put the vendored function and ``ChatOpenAI`` class back (tests)."""
    global _ORIGINAL, _LC_ORIGINAL
    if _LC_ORIGINAL is not None:
        try:
            from langchain_agents import base_agent  # type: ignore

            base_agent.ChatOpenAI = _LC_ORIGINAL
        except Exception:  # noqa: BLE001
            pass
        _LC_ORIGINAL = None
    if _ORIGINAL is None:
        return
    import agents.base as base
    import llm.retry as retry

    retry.retry_chat_completion = _ORIGINAL
    base.retry_chat_completion = _ORIGINAL
    _ORIGINAL = None
