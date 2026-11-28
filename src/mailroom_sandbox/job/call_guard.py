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
  request's size, ``request_tokens``) and is settled when it ends (``settle``): a success keeps that
  hold (``await_price``) until ``after_call`` prices the real usage, so another request cannot pass
  in the gap; a failure that may have been billed (a timeout, a 5xx, a dropped response) is charged
  at its reservation in that same step; a request the provider rejected (HTTP 4xx) or that never
  connected is released. A request whose estimate would pass the cap, with every reservation and
  unpriced success still held, is refused before it goes out. A held success waits in its document's
  queue (``price_holds``), which every thread running in a copy of the document's context shares, so
  it is priced wherever the agent records the usage; one nothing prices is released when the document
  ends. Outside a document only a transport that prices on its own thread holds a success.

Spend therefore stops at the cap, within the size estimate's error (0.25 tokens per character; the
output cap, or ``DEFAULT_COMPLETION_RESERVE_TOKENS`` when a request sets none).
"""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import logging
import math
import threading
from collections import deque
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



class GuardStop(RuntimeError):
    """A document the guard stopped (the run's API cap or the document's call ceiling).

    Running it again would be refused again or spend another ceiling of calls, so it is never retried.
    """


_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"budget": None, "ceiling": None}
_DOC: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("sandbox_call_guard_doc", default=None)
_EXC: list[type] = []
#: Success reservations waiting for ``after_call``, as ``(budget.hold_token, usd, model_key, hold_id)``.
#: A price takes the oldest hold of its own model (``_model_key``), so a concurrent call of another
#: model, or one that reserved nothing, never clears this call's hold. Inside a scope
#: (``document()`` or ``price_holds()``) the queue is the scope's own and every thread that copies the
#: scope's context shares it: a LangChain structured call settles on a ``RunnableParallel`` worker thread
#: and the agent prices it on its own thread. Outside a scope it is per thread (``_PENDING``).
_Hold = tuple[int, float, "str | None", int]
_HOLDS: contextvars.ContextVar[deque[_Hold] | None] = contextvars.ContextVar(
    "sandbox_call_guard_holds", default=None)
_PENDING = threading.local()
_HOLD_LOCK = threading.Lock()
_HOLD_IDS = itertools.count(1)
_log = logging.getLogger("mailroom_sandbox.call_guard")


def ceiling_for(lock: Mapping[str, Any]) -> int:
    """The per-document call ceiling of a locked run."""
    return CALL_CEILING.get(str(lock.get("task") or ""), DEFAULT_CALL_CEILING)


def arm(budget: Any, ceiling: int | None) -> None:
    """Guard every later API call with ``budget`` (an ``ApiBudget``) and the per-document ceiling."""
    queue = getattr(_PENDING, "prices", None)
    if queue is not None:
        _release_unpriced(queue, "re-armed")  # a new run does not price the previous run's replies
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
    """One document's scope: its call count and, if the guard refused a call, why.

    ``calls`` counts guarded calls while a budget is armed (the hard ceiling reads it).
    ``llm_calls`` counts every call, armed or not; ``spend_usd`` is its priced spend, which needs an armed
    budget (unarmed, nothing prices a call). ``governor`` holds the loop governor's round counters
    (phase 2, ``mailroom_sandbox.governor``). It is also a ``price_holds`` scope.
    """
    state: dict[str, Any] = {"calls": 0, "refused": None, "llm_calls": 0, "spend_usd": 0.0,
                             "governor": {"retries": 0, "boss": 0, "skipped_classify_retries": 0}}
    token = _DOC.set(state)
    try:
        with price_holds():
            yield state
    finally:
        _DOC.reset(token)


@contextlib.contextmanager
def price_holds() -> Iterator[None]:
    """A scope whose successes may be priced on any thread that runs in a copy of its context.

    A success settled with ``await_price`` inside it stays on the cap until ``after_call`` prices it,
    from this thread or another one (LangChain runs a structured call's request on a worker thread).
    A hold nothing priced by the time the scope ends is released, so a missed ``after_call`` costs at
    most this scope's lifetime and never the rest of the run.
    """
    queue: deque[_Hold] = deque()
    token = _HOLDS.set(queue)
    try:
        yield
    finally:
        _HOLDS.reset(token)
        _release_unpriced(queue, "scope ended")


def scoped_holds() -> bool:
    """Whether a success settled here can be priced from another thread (inside ``price_holds``)."""
    return _HOLDS.get() is not None


def _release_unpriced(queue: deque[_Hold], why: str) -> None:
    """Drop every hold in ``queue``; the armed budget's own leave its ``settling_usd``."""
    with _HOLD_LOCK:
        held = list(queue)
        queue.clear()
    budget = _STATE["budget"]
    if budget is None:
        return
    mine = [hold[1] for hold in held if hold[0] == budget.hold_token]
    if mine:
        budget.release_settling(sum(mine))
        _log.warning("call guard: %d success hold(s) never priced (%s); released $%.6f",
                     len(mine), why, sum(mine))


def scope() -> dict[str, Any] | None:
    """The current document's scope (``None`` outside :func:`document`)."""
    return _DOC.get()


def note_failed_attempt() -> None:
    """Count an HTTP attempt that returned no usage (L1): it counts toward the ceiling and the governor."""
    doc = _DOC.get()
    if doc is not None:
        doc["calls"] += 1
        doc["llm_calls"] += 1


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


def _refusal() -> str | None:
    budget, ceiling = _STATE["budget"], _STATE["ceiling"]
    if budget is None:
        return None
    reason = budget.exceeded()
    if reason:
        return f"call refused: {reason}"
    return _ceiling_refusal(ceiling)


def _ceiling_refusal(ceiling: int | None) -> str | None:
    doc = _DOC.get()
    if doc is not None and ceiling is not None and doc["calls"] >= ceiling:
        return f"call refused: this document made {doc['calls']} calls (per-document ceiling {ceiling})"
    return None


def before_call(prompt_tokens: int = 0, completion_tokens: int = 0, model: str | None = None) -> float:
    """Raise before an API call that would pass the run's cap or the document's call ceiling.

    A sized request (``request_tokens``) reserves its estimated cost, which this returns; the caller
    passes it to ``settle`` when the request ends. Unarmed, or with no size, nothing is reserved (0.0).
    """
    budget, ceiling = _STATE["budget"], _STATE["ceiling"]
    estimate = (budget.estimate_call_usd(prompt_tokens, completion_tokens, model)
                if budget is not None and (prompt_tokens or completion_tokens) else 0.0)
    if not estimate:
        reason = _refusal()
    else:  # check and reserve as one step, so concurrent requests cannot overshoot together
        reason = _ceiling_refusal(ceiling)
        if reason is None:
            cap = budget.try_reserve(estimate)
            reason = f"call refused: {cap}" if cap else None
    if reason:
        doc = _DOC.get()
        if doc is not None and not doc["refused"]:
            doc["refused"] = reason
        raise budget_error(reason)
    return estimate if budget is not None else 0.0


def _model_key(model: Any) -> str | None:
    """A model name as both sides of a hold spell it: trimmed, lower case, no ``openrouter/`` prefix."""
    text = str(model or "").strip().lower()
    return text.removeprefix("openrouter/") or None


def _thread_queue() -> deque[_Hold]:
    queue = getattr(_PENDING, "prices", None)
    if queue is None:
        queue = deque()
        _PENDING.prices = queue
    return queue


def _hold(budget: Any, usd: float, model: Any = None) -> int:
    """Queue one success's reservation for ``after_call`` (it already moved to ``settling_usd``); its id."""
    queue = _HOLDS.get()
    if queue is None:
        queue = _thread_queue()
        # Outside a scope, only a caller that prices on this same thread holds (the chat-completions
        # and Decisions transports), and it prices one reply before the next request on this thread
        # settles. A hold still queued here was missed: release it, so misses never pile up.
        _release_unpriced(queue, "next success on this thread")
    hold_id = next(_HOLD_IDS)
    with _HOLD_LOCK:
        queue.append((budget.hold_token, usd, _model_key(model), hold_id))
    return hold_id


def _take_pending(budget: Any, model: Any = None, hold: int | None = None) -> float:
    """The success reservation a price clears in this scope or thread (0 when none).

    ``hold`` names one exactly (a transport that prices its own reply). Otherwise it is the oldest
    hold of the priced call's model; a hold or a price with no model matches any. A price whose model
    no hold shares clears nothing: that call reserved nothing, and another call's hold stays on the cap.
    """
    queue = _HOLDS.get()
    if queue is None:
        queue = getattr(_PENDING, "prices", None)
    if not queue:
        return 0.0
    key, want = budget.hold_token, _model_key(model)
    with _HOLD_LOCK:
        while queue and queue[0][0] != key:
            queue.popleft()  # a previous run's: its budget is gone
        for entry in queue:
            if entry[0] != key:
                continue
            if hold is not None:
                if entry[3] != hold:
                    continue
            elif want is not None and entry[2] is not None and entry[2] != want:
                continue
            queue.remove(entry)
            return entry[1]
    return 0.0


def settle(reserved_usd: float, *, billed: bool, await_price: bool = False, model: Any = None) -> int | None:
    """End a request's reservation.

    ``billed`` charges it, in the same step that drops it (a failure the provider may have billed).
    ``await_price`` keeps a success's worst-case cost against the cap until ``after_call`` prices the
    usage recorded for it: on any thread inside a ``price_holds`` scope (every ``document()`` is one),
    on this thread outside one. Neither flag releases a rejection (HTTP 4xx, never connected).
    ``model`` is the requested model: only a price of that model clears the hold. Returns the hold's id
    (for ``after_call(hold=...)``), or None when nothing is held.
    """
    budget = _STATE["budget"]
    if budget is None or not reserved_usd:
        return None
    if billed:
        budget.settle_billed(reserved_usd)
        doc = _DOC.get()
        if doc is not None:
            doc["spend_usd"] += float(reserved_usd)
        return None
    if await_price:
        budget.release_to_settling(reserved_usd)
        return _hold(budget, float(reserved_usd), model)
    budget.release_unbilled(reserved_usd)
    return None


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
    except (TypeError, ValueError, OverflowError):  # inf overflows; after_call has already taken the hold
        return 0


def after_call(usage: Any, model: str | None = None, *, hold: int | None = None, count: bool = True) -> None:
    """Price one returned call (OpenAI ``usage`` object or LangChain usage dict) and count it.

    ``model`` is the requested model, priced on its own; unnamed, the run's dearest model is. It also
    picks the hold this price clears; ``hold`` (an id ``settle`` returned) names it exactly.
    ``count`` False prices the call without counting it toward the ceiling or the governor: a reply the
    pipeline never sees (a discarded length re-sample), so routing stays the same armed or not.
    """
    budget = _STATE["budget"]
    doc = _DOC.get()
    if doc is not None and count:
        doc["llm_calls"] += 1  # the governor counts every call, armed or not
    if budget is None:
        return
    if isinstance(usage, Mapping):
        prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
        completion = usage.get("output_tokens", usage.get("completion_tokens"))
    else:
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
    pending = _take_pending(budget, model, hold)
    if pending:
        cost = budget.price_settling(pending, budget.estimate_call_usd(_count(prompt), _count(completion), model))
    else:
        cost = budget.add_live(_count(prompt), _count(completion), model)
    if doc is not None:
        if count:
            doc["calls"] += 1
        doc["spend_usd"] += float(cost or 0.0)
