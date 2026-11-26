"""Per-call API spend cap and per-document call ceiling (rb1 R01 smoke, defect 3).

``job.api_cost_cap_usd`` used to be checked only between documents, priced from finished ones,
so a document already running was unbounded: in the R01 smoke two merger agreements ran for
more than ten minutes and about 140 calls past the check. While a run with an API budget is
armed here:

- every API call's usage is priced as it returns (``after_call``; vendor hotfix HF-004 wraps
  ``pipeline.limits.record_usage``, which every vendored agent calls after each completion);
- no API call starts once the run's spend has reached the cap, or the current document has made
  ``ceiling`` calls (``before_call``; the provider-pin wrappers call it before each OpenRouter
  request). The refusal is a ``RunBudgetExceeded``, so the vendored graph aborts the document
  through its own run-limit path;
- the document scope (``document()``) records the refusal, and the runner turns that document
  into an error row: a document cut short by the guard is never scored as a pipeline outcome.

- every guarded request reserves its worst-case cost before it goes out (``before_call`` with the
  request's size, ``request_tokens``) and is settled when it ends (``settle``): a success releases the
  reservation (``after_call`` then prices the real usage); a failure that may have been billed (a
  timeout, a 5xx, a dropped response) is charged at its reservation; a request the provider rejected
  (HTTP 4xx) or that never connected is released. A request whose estimate would pass the cap, with
  every reservation in flight, is refused before it goes out.

Spend therefore stops at the cap, within the size estimate's error (0.25 tokens per character; the
output cap, or ``DEFAULT_COMPLETION_RESERVE_TOKENS`` when a request sets none).
"""

from __future__ import annotations

import contextlib
import contextvars
import math
import threading
from collections.abc import Iterator, Mapping
from typing import Any

#: Calls one document may make on an armed run: generous for the pipeline's whole-document path
#: (intake, sorter and its retries, reviewer, specialist and re-extraction, judge, arbiter: about
#: a dozen), far below a windowed or looping document (R01 merger documents: 100+).
CALL_CEILING = {"pipeline": 40}
DEFAULT_CALL_CEILING = 16
#: Request sizing: the shared 0.25 tokens-per-character estimate (``decision_backends.DECISIONS_TOKENS_PER_CHAR``).
TOKENS_PER_CHAR = 0.25
#: Output tokens reserved for a request that sets no output cap of its own.
DEFAULT_COMPLETION_RESERVE_TOKENS = 4096

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"budget": None, "ceiling": None}
_DOC: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("sandbox_call_guard_doc", default=None)
_EXC: list[type] = []


def ceiling_for(lock: Mapping[str, Any]) -> int:
    """The per-document call ceiling of a locked run."""
    return CALL_CEILING.get(str(lock.get("task") or ""), DEFAULT_CALL_CEILING)


def arm(budget: Any, ceiling: int | None) -> None:
    """Guard every later API call with ``budget`` (an ``ApiBudget``) and the per-document ceiling."""
    if budget is not None:
        budget.start_live()
    with _LOCK:
        _STATE.update(budget=budget, ceiling=ceiling if budget is not None else None)


def disarm() -> None:
    with _LOCK:
        _STATE.update(budget=None, ceiling=None)


def armed() -> bool:
    return _STATE["budget"] is not None


def current_budget() -> Any:
    """The armed run's ``ApiBudget``, or None."""
    return _STATE["budget"]


def _text_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, Mapping):
        text = content.get("text")
        return len(text) if isinstance(text, str) else _text_chars(content.get("content"))
    if isinstance(content, (list, tuple)):
        return sum(_text_chars(part) for part in content)
    return 0


def request_tokens(messages: Any, max_tokens: Any) -> tuple[int, int]:
    """A request's (prompt, completion) token estimate: its text at ``TOKENS_PER_CHAR``, its output cap."""
    chars = 0
    for message in messages or ():
        chars += _text_chars(message.get("content") if isinstance(message, Mapping)
                             else getattr(message, "content", None))
    prompt = math.ceil(chars * TOKENS_PER_CHAR)
    try:
        completion = int(max_tokens)
    except (TypeError, ValueError):
        completion = 0
    return prompt, completion if completion > 0 else DEFAULT_COMPLETION_RESERVE_TOKENS


@contextlib.contextmanager
def document() -> Iterator[dict[str, Any]]:
    """One document's scope: its call count and, if the guard refused a call, why."""
    state: dict[str, Any] = {"calls": 0, "refused": None}
    token = _DOC.set(state)
    try:
        yield state
    finally:
        _DOC.reset(token)


def _judge_reask_block(judge: str) -> dict[str, int] | None:
    doc = _DOC.get()
    if doc is None:
        return None
    return doc.setdefault("judge_reasks", {}).setdefault(judge, {"asked": 0, "recovered": 0, "parked": 0})


def note_judge_reask(judge: str) -> None:
    """Record, in the current document's scope, that the HF-002/HF-013 wrapper is re-asking a judge.

    ``judge`` is ``completeness`` or ``correctness``; the scope gains
    ``judge_reasks = {judge: {"asked": n, "recovered": m, "parked": p}}`` (counts only, never
    document text), which the runner copies onto the document's pipeline result. Called before the
    second call is made, so a re-ask that raises (transport error, guard refusal) still counts as
    asked. Each ask ends as exactly one of recovered (the answer parsed), parked (the answer did not
    parse either) or neither (the call raised: the gate reports ``asked - recovered - parked`` as
    ``errored``). A re-ask outside a document scope is not counted (a no-op). It does not depend on
    the run being armed: the re-ask is visible on every run.
    """
    block = _judge_reask_block(judge)
    if block is not None:
        block["asked"] += 1


def note_judge_parked(judge: str) -> None:
    """Record that the re-ask of ``judge`` returned an answer that did not parse either (no-op outside a document scope)."""
    block = _judge_reask_block(judge)
    if block is not None:
        block["parked"] += 1


def note_judge_recovered(judge: str) -> None:
    """Record that the re-ask of ``judge`` returned an answer that parsed (no-op outside a document scope)."""
    block = _judge_reask_block(judge)
    if block is not None:
        block["recovered"] += 1


def budget_error(reason: str) -> Exception:
    """A ``RunBudgetExceeded`` (the vendored run-limit error) carrying ``reason``."""
    if not _EXC:
        try:
            from pipeline.limits import RunBudgetExceeded as base  # type: ignore
        except Exception:  # noqa: BLE001 — no vendored pipeline (mock / scoring-only)
            base = RuntimeError

        class CallBudgetExceeded(base):  # type: ignore[misc,valid-type]
            def __init__(self, why: str):
                Exception.__init__(self, why)
                self.used, self.cap, self.reason = None, None, why

        _EXC.append(CallBudgetExceeded)
    return _EXC[0](reason)


def _refusal(estimate_usd: float = 0.0) -> str | None:
    budget, ceiling = _STATE["budget"], _STATE["ceiling"]
    if budget is None:
        return None
    reason = budget.exceeded(extra_usd=estimate_usd)
    if reason:
        return f"call refused: {reason}"
    doc = _DOC.get()
    if doc is not None and ceiling is not None and doc["calls"] >= ceiling:
        return f"call refused: this document made {doc['calls']} calls (per-document ceiling {ceiling})"
    return None


def before_call(prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
    """Raise before an API call that would pass the run's cap or the document's call ceiling.

    A sized request (``request_tokens``) reserves its estimated cost, which this returns; the caller
    passes it to ``settle`` when the request ends. Unarmed, or with no size, nothing is reserved (0.0).
    """
    budget = _STATE["budget"]
    estimate = (budget.estimate_call_usd(prompt_tokens, completion_tokens)
                if budget is not None and (prompt_tokens or completion_tokens) else 0.0)
    reason = _refusal(estimate)
    if reason:
        doc = _DOC.get()
        if doc is not None and not doc["refused"]:
            doc["refused"] = reason
        raise budget_error(reason)
    if budget is not None and estimate:
        budget.reserve(estimate)
    return estimate if budget is not None else 0.0


def settle(reserved_usd: float, *, billed: bool) -> None:
    """End a request's reservation; ``billed`` charges it (a failure the provider may have billed)."""
    budget = _STATE["budget"]
    if budget is None or not reserved_usd:
        return
    budget.release(reserved_usd)
    if billed:
        budget.charge_unreported(reserved_usd)


def _status_code(exc: BaseException) -> int | None:
    for source in (exc, getattr(exc, "response", None)):
        code = getattr(source, "status_code", None)
        if isinstance(code, int) and not isinstance(code, bool):
            return code
    return None


def billed_failure(exc: BaseException) -> bool:
    """Whether a failed request may have been billed: not when the provider rejected it (HTTP 4xx) or it
    never connected; yes for a timeout, a 5xx, a dropped response or anything unknown."""
    try:
        import httpx

        never_sent: tuple[type, ...] = (httpx.ConnectError, httpx.ConnectTimeout)
    except Exception:  # noqa: BLE001 — httpx is a dependency; stay conservative without it
        never_sent = ()
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = _status_code(current)
        if code is not None:
            return code >= 500
        if never_sent and isinstance(current, never_sent):
            return False
        current = current.__cause__ or current.__context__
    return True


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def after_call(usage: Any) -> None:
    """Price one returned call (OpenAI ``usage`` object or LangChain usage dict) and count it."""
    budget = _STATE["budget"]
    if budget is None:
        return
    if isinstance(usage, Mapping):
        prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
        completion = usage.get("output_tokens", usage.get("completion_tokens"))
    else:
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
    budget.add_live(_count(prompt), _count(completion))
    doc = _DOC.get()
    if doc is not None:
        doc["calls"] += 1
