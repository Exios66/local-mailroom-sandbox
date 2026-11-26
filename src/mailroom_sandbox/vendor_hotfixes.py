"""Sandbox hotfixes over the vendored llm-mailroom snapshot, until upstream catches up.

``vendor/`` stays byte-identical to its pin (``tests/test_vendor_drift.py``), so a fix the
experiments need before the owning repo ships it is installed here, at activation, as a
wrapper around one vendored function. Each hotfix is bound to the exact source of the
function it wraps:

- the target's ``inspect.getsource`` sha256 must equal ``source_sha256``. After a vendor
  refresh changes the function, the hotfix is not applied and its status is ``stale``:
  ``sandbox run preflight`` fails until the hotfix is re-validated against the new code or
  retired because upstream shipped the fix.
- every run lock records the hotfix set (``dependency_sources.describe()["hotfixes"]``): ids,
  target fingerprints and the sha256 of this module, so results name the code that scored them.

Add a hotfix only for pipeline behavior an experiment depends on, with a test, an upstream
issue or PR in ``upstream`` and the CHANGELOG entry. Scoring corrections do not go here: they
live in ``scoring_hotfixes.py``, dual reported beside the Dojo pin's raw values. See
``docs/vendor-hotfixes.md`` and ``docs/scoring-hotfixes.md``.

``attr`` may name a method (``Class.method``); the wrapper then replaces it on the class.
"""

from __future__ import annotations

import copy
import difflib
import functools
import hashlib
import importlib
import inspect
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

_log = logging.getLogger("mailroom_sandbox.vendor_hotfixes")

_MARK = "_sandbox_hotfix"


@dataclass(frozen=True)
class Hotfix:
    id: str
    module: str
    attr: str
    source_sha256: str  # sha256 of inspect.getsource(<vendored target>) the fix was written against
    upstream: str
    summary: str
    install: Callable[[Any, Callable[..., Any]], Callable[..., Any]]
    # Other functions whose behavior the fix relies on: (attr, sha256), the attr in the same
    # module, or "other.module:attr" in another one. Any mismatch makes the whole fix stale,
    # like a change to the target itself.
    also: tuple[tuple[str, str], ...] = ()
    # Re-run on an already-applied fix, for side effects a test or a reload can undo (route rules).
    refresh: Callable[[Any], None] | None = None


def corporate_record_type_for(subclass: Any) -> str | None:
    """The Hub ``record_type`` a corporate-record subclass implies (Dojo ``corporate_record_schema``).

    The sorter catalog has eleven corporate subclasses, the Hub ``record_type`` inventory five;
    Dojo maps each subclass onto one (indenture, board_resolution, officer_certificate and
    subsidiary_list are ``other``; charter_amendment and certificate_of_formation are
    ``articles_of_incorporation``). Unknown tokens map to nothing.
    """
    from langchain_agents.doc_inventories import sorter_subclass_catalog  # type: ignore
    from llm_dojo_scoring.schemas import corporate_record_schema as crs

    token = str(subclass or "").strip().lower()
    if token not in sorter_subclass_catalog("corporate_record"):
        return None
    return crs.subclass_schema(token).record_type or None


def _install_record_type_from_subclass(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def enrich_extraction(extracted: dict | None = None, *, doc_type: str | None = None,
                          extract_class: str | None = None, subtype: str | None = None) -> dict:
        out = original(extracted, doc_type=doc_type, extract_class=extract_class, subtype=subtype)
        # Upstream backfills a null record_type from the subclass only when the subclass is one
        # of the five Hub tokens; the other six corporate subclasses left it null.
        if str(doc_type or "") == "corporate_record" and subtype and not out.get("record_type"):
            token = corporate_record_type_for(subtype)
            if token:
                out["record_type"] = token
        return out

    return enrich_extraction


#: The reasoning the vendored CompletenessJudge returns when its structured output failed to parse.
JUDGE_PARSE_FAILURE = "judge output failed to parse"


class JudgeParseError(RuntimeError):
    """A judge's answer did not parse: no verdict was reached (HF-002 completeness, HF-013 accuracy)."""


def _is_completeness_parse_failure(out: Mapping[str, Any]) -> bool:
    return str(out.get("reasoning") or "") == JUDGE_PARSE_FAILURE and out.get("completeness") == 0.0


def _is_correctness_parse_failure(out: Mapping[str, Any]) -> bool:
    return (str(out.get("reasoning") or "") == JUDGE_PARSE_FAILURE and out.get("extraction_correctness") == 0.0
            and out.get("extraction_correctness_label") == "inaccurate")


def _ask_once_more(judge: str, original: Callable[..., Any], failed: Callable[[Mapping[str, Any]], bool],
                   self: Any, args: tuple, kwargs: dict) -> dict:
    """One judge call, re-asked once when its answer did not parse; raises when the re-ask fails too.

    Only the vendored parse-failure sentinel triggers the re-ask: a transport or provider error
    raises out of ``original`` untouched (HF-012 bounds those at node level), and an answer that
    parsed, however low, is a verdict. The re-ask is the same vendored method with the same
    arguments, so it passes the API call guard, the provider pins, usage capture and the spend caps
    like any call. It is made at most once per call, so a pass holds at most two calls per judge
    method. ``note_judge_reask`` records whether it recovered (counts only, never document text).
    """
    out = original(self, *args, **kwargs)
    if not failed(out):
        return out
    out = original(self, *args, **kwargs)
    from mailroom_sandbox.job import call_guard

    call_guard.note_judge_reask(judge, recovered=not failed(out))
    if failed(out):
        raise JudgeParseError(JUDGE_PARSE_FAILURE)
    return out


def _install_judge_parse_error(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def judge_completeness(self: Any, *args: Any, **kwargs: Any) -> dict:
        # Upstream turns a parse failure into a real "incomplete 0.0" verdict, which sends the
        # document to the arbiter as if the extraction were judged incomplete and is never counted
        # as a judge error. A single unparseable answer is asked once more; when the second one
        # fails too, raising takes the graph's own hard-failure path: judge_verdict "judge_error",
        # routed to human review and counted by the gate.
        return _ask_once_more("completeness", original, _is_completeness_parse_failure, self, args, kwargs)

    return judge_completeness


def _install_judge_correctness_parse_error(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def judge_extraction_correctness(self: Any, *args: Any, **kwargs: Any) -> dict:
        # HF-002's gap: the accuracy judge runs after a "complete" completeness verdict, and its
        # parse failure becomes "inaccurate 0.0", which judge_verify turns into an "incomplete"
        # verdict that spends an arbiter call and a re-extraction. No verdict was reached, so it is
        # asked once more and, failing again, takes the same judge_error path as a completeness
        # parse failure (HF-002).
        return _ask_once_more("correctness", original, _is_correctness_parse_failure, self, args, kwargs)

    return judge_extraction_correctness


#: The least share of the source a single-window intake ``cleaned_text`` must keep to replace it.
INTAKE_CLEAN_MIN_SHARE = 0.9
#: Content check: the source and cleaned words are aligned in order; the longest run of source
#: words with no counterpart and the share of such words are bounded.
INTAKE_CLEAN_MAX_LOST_RUN = 8
INTAKE_CLEAN_MAX_LOST_SHARE = 0.05

_WORD = re.compile(r"\w+")


def lost_words(source: str, cleaned: str) -> tuple[int, float]:
    """``(longest run, share)`` of source words the cleaned text does not keep, in order.

    Words are case-folded and aligned with :class:`difflib.SequenceMatcher` (its autojunk
    heuristic keeps a 400k-character document to milliseconds). An OCR or hyphenation repair
    loses a word or two; a dropped clause loses every word in it, in one run, even when the same
    wording recurs elsewhere in the document (a set of n-grams would miss that).
    """
    src = [w.casefold() for w in _WORD.findall(source or "")]
    dst = [w.casefold() for w in _WORD.findall(cleaned or "")]
    if not src:
        return 0, 0.0
    longest = matched = prev = 0
    for block in difflib.SequenceMatcher(None, src, dst).get_matching_blocks():
        longest = max(longest, block.a - prev)
        prev = block.a + block.size
        matched += block.size
    return longest, (len(src) - matched) / len(src)


def _intake_clean_refusal(doc_text: str, cleaned: str) -> str | None:
    """Why a single-window ``cleaned`` may not replace ``doc_text`` (None when it may)."""
    if len(cleaned) < INTAKE_CLEAN_MIN_SHARE * len(doc_text or ""):
        return f"cleaned_text kept {len(cleaned)} of {len(doc_text or '')} characters (HF-003)"
    run, share = lost_words(doc_text, cleaned)
    if run >= INTAKE_CLEAN_MAX_LOST_RUN or share > INTAKE_CLEAN_MAX_LOST_SHARE:
        return f"cleaned_text lost {share:.1%} of the source words, {run} in a row (HF-003)"
    return None


def _install_intake_clean_guard(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def intake_run(self: Any, doc_text: str, filename: str | None = None) -> dict:
        prep = original(self, doc_text, filename)
        cleaned = prep.get("cleaned") if isinstance(prep, dict) else None
        # Upstream accepts any non-empty cleaned_text from a single-window read, and the graph
        # then replaces the whole document with it. Context fit sends a long document in one
        # window while the output allowance stays ~2k tokens, so a short or partial reply would
        # replace a merger with a fragment. The source stands unless the cleaned text keeps its
        # length and its words: a dropped clause is refused even when the length survives.
        refusal = _intake_clean_refusal(doc_text, cleaned) if cleaned else None
        if refusal:
            for key in ("cleaned", "clean_stats"):
                prep.pop(key, None)
            prep["changed"] = False
            prep["clean_refused"] = refusal
        return prep

    return intake_run


def _install_call_spend(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def record_usage(usage: Any, model: str | None = None, agent: str | None = None,
                     served_model: str | None = None) -> None:
        original(usage, model, agent=agent, served_model=served_model)
        # Upstream records usage per document for reporting only; the run's API cap was checked
        # between documents, so one long document could spend without bound. Each returned call
        # is priced against the run's cap here (job.call_guard; no-op unless a budget is armed).
        if usage is not None:
            from mailroom_sandbox.job import call_guard
            from mailroom_sandbox.job.usage_capture import note_provider_call

            # The vendored accumulator keeps token counts only. The provider's own
            # ``usage.cost`` and cache split are what an accurate bill is priced from.
            note_provider_call(usage)
            call_guard.after_call(usage)

    return record_usage


#: Seconds between "holding" log lines from the watcher's backpressure gate (HF-005).
DISPATCH_HOLD_LOG_SECONDS = 30.0


def _install_dispatch_backpressure(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    last_log = [0.0]

    @functools.wraps(original)
    def submit(self: Any, name: str, fn: Any, path: Any) -> bool:
        # Upstream queues every inbox file the 1-second rescan sees, with no bound on the
        # in-memory dispatch queue or on processing/. Over a limit the file is not queued: it
        # stays in inbox/ and the next rescan offers it again, so intake slows and nothing is
        # dropped. submit's False ("not queued") is the return its callers already ignore.
        import time

        from mailroom_sandbox import backpressure

        full = backpressure.saturated(("dispatch", "processing", "review"),
                                      depths={"dispatch": self.queued_count()})
        if full:
            now = time.monotonic()
            if now - last_log[0] >= DISPATCH_HOLD_LOG_SECONDS:
                last_log[0] = now
                _log.warning("HF-005 backpressure: %s stays in the inbox while %s",
                             name, ", ".join(map(str, full)))
            return False
        return original(self, name, fn, path)

    return submit


def _install_explicit_zero_confidence(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def confidence_missing(self: Any, result: dict) -> bool:
        value = result.get("confidence")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
            return False
        return original(self, result)

    return confidence_missing


_SWITCH_OFF = ("off", "false", "0", "no")


def _install_judge_above_band(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """High self-reported confidence no longer skips the judge (#215, llm-mailroom#278).

    ``MAILROOM_JUDGE_VERIFY=off`` still disables the lane. ``MAILROOM_JUDGE_HIGH_BAND=off``
    restores the vendored band (low <= confidence < judge_band_high).
    """

    @functools.wraps(original)
    def judge_gate(state: Mapping[str, Any]) -> bool:
        import os

        if os.environ.get("MAILROOM_JUDGE_VERIFY", "on").lower() in _SWITCH_OFF:
            return False
        if os.environ.get("MAILROOM_JUDGE_HIGH_BAND", "on").lower() in _SWITCH_OFF:
            return original(state)
        confidence = state.get("extraction_confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return False
        low = float(module._thresholds_for(state).get("low", 0.70))
        return float(confidence) >= low

    return judge_gate


def _agreement_norm(value: Any) -> str:
    """Comparable form of one extracted value: numbers by value, text folded, structure sorted.

    Mirrors the tolerance of the vendored chunk dedupe (whitespace collapse +
    casefold) so a window that re-quotes a value with different spacing or case
    still agrees with itself across the overlap.
    """
    if value is None:
        return "\u2205"  # ∅ — a stated null agrees with another stated null, not with a value
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, (int, float)):
        return f"num:{float(value)!r}"
    if isinstance(value, str):
        return " ".join(str(value).split()).casefold()
    if isinstance(value, dict):
        return "{" + ";".join(
            f"{_agreement_norm(k)}={_agreement_norm(v)}" for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ";".join(sorted(_agreement_norm(item) for item in value)) + "]"
    return " ".join(str(value).split()).casefold()


def _pair_agreement(a: Any, b: Any) -> float:
    """One pair's agreement: exact on the comparable form, Jaccard on list-shaped values."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and not isinstance(a, str) and not isinstance(b, str):
        sa = {_agreement_norm(item) for item in a}
        sb = {_agreement_norm(item) for item in b}
        union = sa | sb
        return 1.0 if not union else len(sa & sb) / len(union)
    return 1.0 if _agreement_norm(a) == _agreement_norm(b) else 0.0


def _asserts(value: Any) -> bool:
    """True when a window actually asserts content for a field.

    Every surviving window passes the vendored ``normalize_extraction``, which
    fills EVERY schema key — ``None`` for nullable scalars, ``[]`` for arrays —
    so a field one window never saw is not missing, it is a fill. A fill is
    "not seen here", not a conflicting assertion: only a pair where both
    windows assert content is comparable (Bugbot, #402).
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def cross_window_agreement(windows: list[tuple[dict, str | None]]) -> dict[str, Any]:
    """Self-consistency across a document's chunk windows (SAND-214).

    For every field key two or more windows assert, compare the asserted values
    pairwise (Jaccard for lists, exact on the comparable form otherwise) and
    average. Two normalization facts shape this (Bugbot, #402):

    - ``normalize_extraction`` fills every schema key, so ``None``/``[]``/``{}``
      mean "not seen in this window". A pair counts only when BOTH windows
      assert content; a value is never scored against a window's fill, and
      two fills are not scored as agreement either.
    - ``reasoning`` (the per-field trace contracts and merger emit on every
      window) and the per-window ``confidence`` describe the scan or the
      self-report, not asserted content; both are excluded, as are underscore
      bookkeeping keys.

    Returns ``{"agreement": float | None, "fields": int, "conflicts": int}`` —
    ``agreement`` averages only the keys with at least one comparable pair and
    is None when none exist (fewer than two windows, or no shared asserted
    content). Self-consistency over shared content is the measure the #214
    runs left untested: the specialist's single self-reported confidence does
    not predict quality (AUROC 0.36-0.47), while agreement between independent
    reads of overlapping text is a model-behavior signal the merge wrapper
    already has in hand.
    """
    results = [result for result, _text in windows if isinstance(result, dict)]
    if len(results) < 2:
        return {"agreement": None, "fields": 0, "conflicts": 0}
    # Per-key presence, not the all-window key intersection: a field asserted by
    # two of three windows is comparable even when a third window lacks the key
    # entirely (CodeRabbit, #402). With normalize fills every window carries
    # every key, so `_asserts` decides comparability either way.
    candidate = set()
    for result in results:
        candidate |= {k for k in result
                      if not str(k).startswith("_") and k not in ("confidence", "reasoning")}
    # Underscore keys are merge bookkeeping; `confidence` is the per-window
    # self-report and `reasoning` the per-field trace this measure replaces —
    # none is asserted content.
    if not candidate:
        return {"agreement": None, "fields": 0, "conflicts": 0}
    scores: list[float] = []
    conflicts = 0
    for key in sorted(candidate):
        values = [result[key] for result in results if key in result]
        pairwise = [_pair_agreement(a, b) for i, a in enumerate(values) for b in values[i + 1:]
                    if _asserts(a) and _asserts(b)]
        if not pairwise:
            continue  # no window pair both asserted this field: nothing comparable
        mean = sum(pairwise) / len(pairwise)
        scores.append(mean)
        if mean < 1.0:
            conflicts += 1
    if not scores:
        return {"agreement": None, "fields": 0, "conflicts": 0}
    return {"agreement": round(sum(scores) / len(scores), 4),
            "fields": len(scores), "conflicts": conflicts}


def _install_window_confidences(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """Record each surviving window's confidence and character length. The merged value stays the vendor's minimum.

    Also records the cross-window agreement the #214 runs did not measure
    (``_window_agreement`` + compared/conflicting field counts): the
    specialist's self-reported confidence does not predict quality, so the
    routing audit needs a behavior-based signal to test against judged
    outcomes.
    """

    @functools.wraps(original)
    def merge_chunk_windows(windows: list[tuple[dict, str | None]], *, agent_name: str) -> dict | None:
        merged = original(windows, agent_name=agent_name)
        if not isinstance(merged, dict):
            return merged
        recorded: list[float | None] = []
        lengths: list[int | None] = []
        for result, text in windows:
            value = result.get("confidence") if isinstance(result, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                recorded.append(None)
            else:
                recorded.append(float(value))
            lengths.append(len(text) if isinstance(text, str) else None)
        merged["_window_confidences"] = recorded
        merged["_window_lengths"] = lengths
        merged["_window_agreement"] = cross_window_agreement(windows)
        return merged

    return merge_chunk_windows


class WholeDocumentTooLong(ValueError):
    """An API-routed specialist got a document longer than its input budget (HF-009)."""


def _api_route(agent_name: str) -> bool:
    """True when ``agent_name`` calls a hosted API, not Modal/vLLM or another self-hosted server.

    A route that cannot be resolved (no or a mock OpenRouter key, an unknown provider or tier)
    is not treated as an API route: the vendored path runs and resolves its client lazily, so a
    ``--mock`` run that stubs the call still extracts, and a real call there fails the same way
    it would have without this fix. Nothing is chunked against a hosted API this way, because no
    client for it can exist.
    """
    from llm.client import is_free_only_exempt, resolve_agent_model  # type: ignore
    from pipeline.config import get_agent_config  # type: ignore

    try:
        resolved = resolve_agent_model(agent_name, get_agent_config(agent_name))
    except (KeyError, ValueError):
        return False
    return not (resolved.served_by_vllm or is_free_only_exempt(resolved.provider.name))


def _install_api_whole_document(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """On an API route a specialist reads the whole document in one call; chunking stays local.

    Context fit widens API readers' budgets to the model's context, but the vendored graph
    still windows any document longer than that budget. On OpenRouter that multiplies calls
    per document, so it is refused: the document fails with :class:`WholeDocumentTooLong`
    (the extract node's parse-failure path, then review) instead of being chunked or
    truncated. Modal, vLLM and other self-hosted routes keep the vendored chunking.
    """

    @functools.wraps(original)
    def _run_chunked_extraction(agent_fn, doc_text, pages, handoff_context):
        name = str(getattr(agent_fn, "agent_name", "") or "")
        if not name or not _api_route(name):
            return original(agent_fn, doc_text, pages, handoff_context)
        agent = module._instantiate_specialist(agent_fn, handoff_context)
        budget = module._specialist_input_budget(agent)
        if len(doc_text or "") > budget:
            raise WholeDocumentTooLong(
                f"{name}: {len(doc_text)} chars exceed the {budget}-char input budget on an API "
                "route, which never chunks; route this class to Modal/vLLM to window it")
        try:
            return agent.extract(doc_text, pages=pages, handoff_context=handoff_context)
        except TypeError:
            return agent.extract(doc_text, pages=pages)

    return _run_chunked_extraction


def _calling_reader() -> str:
    """``agent_name`` of the agent method that called ``sliding_windows`` (sorter or intake), else ``""``."""
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        reader = caller.f_locals.get("self") if caller else None
        return str(getattr(reader, "agent_name", "") or "")
    finally:
        del frame


def _install_api_single_window(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """On an API route the sorter and intake read the whole document in one window.

    Both readers slide windows through ``agents.intake.sliding_windows`` when a document is
    longer than their budget. When the calling agent is API-routed and the text needs more
    than one window, the read fails with :class:`WholeDocumentTooLong` instead. Intake fails
    soft (the deterministic clerk output stays); the sorter's failure takes the graph's error
    path. Calls from no agent, or from a Modal/vLLM or self-hosted route, keep the windows.
    """

    @functools.wraps(original)
    def sliding_windows(text: str, budget: int, overlap_chars: int) -> list[tuple[str, int]]:
        windows = original(text, budget, overlap_chars)
        if len(windows) <= 1:
            return windows
        name = _calling_reader()
        if name and _api_route(name):
            raise WholeDocumentTooLong(
                f"{name}: {len(text)} chars exceed the {budget}-char input budget on an API "
                "route, which never slides windows; route this reader to Modal/vLLM to window it")
        return windows

    return sliding_windows


#: Route-rule name prefix of HF-011 (``graph.route_spec`` registry).
JUDGE_EXHAUSTED_RULES = "HF-011:"


def _judge_passes_spent(routing: Any, state: Mapping[str, Any]) -> bool:
    passes = int(state.get("judge_pass_count") or 0)
    return passes >= routing._judge_max_passes(routing._thresholds_for(state))


def _exhausted_to_arbiter_enabled(routing: Any, state: Mapping[str, Any]) -> bool:
    return routing._thresholds_for(state).get("judge_exhausted_to_arbiter") is True


def judge_exhausted_rule(routing: Any) -> Callable[[Mapping[str, Any], str], str | None]:
    """``judge_verify``: a ``partial`` verdict on the last judge pass asks the arbiter, not a person.

    The vendored ``after_judge`` parks a ``partial`` verdict once ``judge_max_passes`` is spent
    without consulting the arbiter, the fallback that exists to accept a materially sound
    extraction with caveats. Only that park is redirected: an ``incomplete`` verdict, a judge
    error, a transient error, or a pass budget not yet spent keep the router's answer, and so
    does an extraction ``after_arbiter`` would park even on acceptance (still unsure, or an
    unadjudicated conflict, unless HF-014 lets a whole-source acceptance archive): asking the
    arbiter there would spend a call for the same park.
    """

    def decide(state: Mapping[str, Any], proposed: str) -> str | None:
        if proposed != "human_review" or state.get("transient_error"):
            return None
        if state.get("judge_verdict") != "partial" or not _exhausted_to_arbiter_enabled(routing, state):
            return None
        if not _judge_passes_spent(routing, state):
            return None
        # after_arbiter parks these whatever the arbiter says, so its call would be wasted
        # (HF-014 keeps an acceptance from a whole-source reading out of that park).
        if acceptance_parks(routing, state):
            return None
        return "arbiter"

    return decide


def arbiter_final_rule(routing: Any) -> Callable[[Mapping[str, Any], str], str | None]:
    """``arbiter``: no re-extraction once the judge passes are spent.

    A retry there could not be judged again, so the arbiter's ruling on the last pass is
    final: it accepts with caveats (``after_arbiter`` still parks an unsure extraction or an
    unadjudicated conflict) or the document goes to a person. The park carries the
    ``retries_exhausted`` cause the judge's last ``partial`` verdict already earned.
    """

    def decide(state: Mapping[str, Any], proposed: str) -> str | None:
        if proposed != "retry_extract" or not _exhausted_to_arbiter_enabled(routing, state):
            return None
        return "human_review" if _judge_passes_spent(routing, state) else None

    return decide


def _register_judge_exhausted_rules(module: Any) -> None:
    """(Re)register the HF-011 rules first on their nodes; idempotent.

    ``apply_hotfixes`` runs on every runtime activation, possibly while another thread is
    routing a document. A rule already registered first for this ``module`` is left in
    place, so a concurrent route decision never sees it missing. Only a registry clear
    (the rule is absent: added, nothing removed) or a reloaded routing module (the rule
    points at the old one: swapped) changes the registry.
    """
    from graph import route_spec

    rules = (("judge_verify", "judge_exhausted_to_arbiter", judge_exhausted_rule),
             ("arbiter", "arbiter_final_after_last_pass", arbiter_final_rule))
    for node, name, build in rules:
        full = JUDGE_EXHAUSTED_RULES + name
        current = route_spec.route_rules(node)
        mine = next((r for r in current if r.name == full), None)
        if mine is not None and current[0] is mine and getattr(mine.decide, "_hf011_module", None) is module:
            continue
        decide = build(module)
        decide._hf011_module = module  # type: ignore[attr-defined]
        if mine is not None:
            route_spec.remove_route_rule(node, full)
        route_spec.add_route_rule(node, route_spec.RouteRule(full, decide), position="first")


def _install_judge_exhausted_to_arbiter(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """Register the HF-011 route rules; the router itself is unchanged.

    ``graph.route_spec`` binds the routers at import, so a wrapper could not change the
    graph; its rule registry is the sanctioned hook. The rules are placed first so a
    decision-point rule cannot follow a retry the pass budget no longer covers. Both are
    off unless the class's ``confidence.judge_exhausted_to_arbiter`` is ``true``, so a run
    locked without the key routes exactly as the vendored graph does.
    """
    _register_judge_exhausted_rules(module)

    @functools.wraps(original)
    def after_judge(state: dict) -> Any:
        return original(state)

    return after_judge


def _transient_budget(thresholds: Mapping[str, Any]) -> int | None:
    raw = thresholds.get("transient_retry_max")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


def _install_transient_budget(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """Each node's transient self-loop follows ``confidence.transient_retry_max`` when set.

    ``retry_chat_completion`` already retries a transient provider error up to its own
    ``max_attempts`` (5) inside one node call, so the vendored two node-level re-runs on
    top of that repeat whole extractions or judge passes. With the key set, a node re-runs
    at most that many times (0: straight to review); without it, the vendored budget
    (``_TRANSIENT_MAX_RETRIES``) stands. The counters and the ``transient_exhausted`` review
    cause are unchanged.
    """

    @functools.wraps(original)
    def _transient_decision(state: dict, *, retry_target: str) -> Any:
        budget = _transient_budget(module._thresholds_for(state))
        if budget is None:
            return original(state, retry_target=retry_target)
        retries = state.get(f"transient_retries_{retry_target}", 0)
        if retries <= budget:
            module.logger.warning("transient_retry", retry_target=retry_target, retries=retries,
                                  budget=budget, error=state.get("error_message"))
            return "retry"
        module.logger.warning("transient_retries_exhausted", retry_target=retry_target, retries=retries,
                              budget=budget, doc_id=state.get("doc_id"))
        return "human_review"

    return _transient_decision


#: Run ``confidence`` key that turns on HF-014 and HF-015 (overlay default ``true``). Both stay inert
#: unless context fit widened the arbiter's source window, so Modal/vLLM and local routes are unchanged.
FULL_SOURCE_KEY = "arbiter_full_source"
#: Run ``confidence`` key: the extraction confidence an HF-014 acceptance needs. Unset (the
#: overlay default) it is the class's own ``low`` band, read the way routing reads it.
FULL_SOURCE_FLOOR_KEY = "arbiter_full_source_min_confidence"
#: Route-rule name of HF-014 (``graph.route_spec`` registry, ``arbiter`` node).
FULL_SOURCE_RULE = "HF-014:arbiter_full_source_accepts"
#: The note HF-015 adds to the arbiter's request when no re-extraction budget is left.
RETRY_CLOSED_NOTE = ("RE-EXTRACTION IS NOT AVAILABLE: no re-extraction budget is left, so this ruling is "
                     "final. Decide accept_with_caveats or human_review; retry_extraction cannot be chosen.")


def arbiter_source_window() -> tuple[int | None, bool]:
    """``(the extraction arbiter's source window, whether context fit widened it)``.

    The window is ``agents.arbiter.SOURCE_CHARS`` as the arbiter reads it at call time
    (:mod:`mailroom_sandbox.source_windows` raises it on a fitted route and restores the vendored
    value on every other activation). ``(None, False)`` when the vendored agent is not importable.
    """
    from mailroom_sandbox.source_windows import vendored_windows

    try:
        arbiter = importlib.import_module("agents.arbiter")
    except Exception:  # noqa: BLE001 — optional (pipeline extra)
        return None, False
    window = int(arbiter.SOURCE_CHARS)
    vendored = vendored_windows().get("agents.arbiter.SOURCE_CHARS")
    return window, vendored is not None and window > vendored


def _full_source_route(routing: Any, state: Mapping[str, Any]) -> bool:
    if routing._thresholds_for(state).get(FULL_SOURCE_KEY) is not True:
        return False
    return arbiter_source_window()[1]


def _full_source_rule_registered() -> bool:
    from graph import route_spec

    return any(rule.name == FULL_SOURCE_RULE for rule in route_spec.route_rules("arbiter"))


def arbiter_read_whole_source(routing: Any, state: Mapping[str, Any]) -> bool:
    """HF-014: whether an ``accept_with_caveats`` on ``state`` rests on the whole source.

    True on a context-fitted route (``confidence.arbiter_full_source`` on and the arbiter window
    widened) when the arbiter read every character of the document (``doc_text`` no longer than
    its window), no chunked window was lost and no matter conflict is unadjudicated.
    """
    if not _full_source_route(routing, state):
        return False
    window, _ = arbiter_source_window()
    text = state.get("doc_text")
    if window is None or not isinstance(text, str) or len(text) > window:
        return False
    return not routing._chunks_lost(state) and not routing._unadjudicated_conflict(state)


def full_source_floor(routing: Any, state: Mapping[str, Any]) -> float:
    """HF-014's confidence floor for ``state``'s class: ``confidence.arbiter_full_source_min_confidence``,
    else the class's ``low`` band (by-class overrides included, vendored default 0.70)."""
    thresholds = routing._thresholds_for(state)
    raw = thresholds.get(FULL_SOURCE_FLOOR_KEY)
    return float(raw if raw is not None else thresholds.get("low", 0.70))


def confidence_floor_met(routing: Any, state: Mapping[str, Any]) -> bool:
    """Whether the extraction confidence reaches HF-014's floor (missing or non-finite: it does not)."""
    confidence = state.get("extraction_confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
        return False
    return confidence >= full_source_floor(routing, state)


def full_source_accepts(routing: Any, state: Mapping[str, Any]) -> bool:
    """HF-014: an ``accept_with_caveats`` on ``state`` archives (whole source read, floor reached)."""
    return arbiter_read_whole_source(routing, state) and confidence_floor_met(routing, state)


def acceptance_parks(routing: Any, state: Mapping[str, Any]) -> bool:
    """Whether ``after_arbiter`` (with HF-014 when it is registered) parks an ``accept_with_caveats``."""
    if not (routing._extraction_still_unsure(state) or routing._unadjudicated_conflict(state)):
        return False
    return not (_full_source_rule_registered() and full_source_accepts(routing, state))


def full_source_accept_rule(routing: Any) -> Callable[[Mapping[str, Any], str], str | None]:
    """``arbiter``: an acceptance from a whole-source reading goes to the report, not to a person.

    The vendored ``after_arbiter`` parks ``accept_with_caveats`` while the extraction is still
    unsure (confidence under the class ``low`` band and no source-verified judge verdict). On a
    16k-excerpt route that park guards against an arbiter that never saw most of the document.
    Where the arbiter read all of it, its acceptance is the ruling the judge/arbiter lane exists
    for, so the document archives with its caveats on record (``arbiter_decision`` and
    ``arbiter_reasoning`` in the manifest and the matter report; ``arbiter_caveats`` on the
    sandbox item). The extraction confidence must still reach a floor
    (``confidence.arbiter_full_source_min_confidence``, else the class ``low`` band): below it,
    or with none recorded, the document parks as before. Lost chunks and an unadjudicated
    conflict still park. The judge verdict is not gated.
    """

    def decide(state: Mapping[str, Any], proposed: str) -> str | None:
        if proposed != "human_review" or state.get("transient_error"):
            return None
        if state.get("arbiter_decision") != "accept_with_caveats":
            return None
        return "compile_report" if full_source_accepts(routing, state) else None

    return decide


def _register_full_source_rule(module: Any) -> None:
    """(Re)register the HF-014 rule right after the HF-011 rules on ``arbiter``; idempotent.

    HF-011 keeps its rules first. This rule acts on a different proposal (``human_review``, not
    ``retry_extract``), so the order between them never changes a route; keeping it fixed avoids
    re-registering on every activation.
    """
    from graph import route_spec

    current = route_spec.route_rules("arbiter")
    position = sum(1 for rule in current if rule.name.startswith(JUDGE_EXHAUSTED_RULES))
    mine = next((rule for rule in current if rule.name == FULL_SOURCE_RULE), None)
    if (mine is not None and current.index(mine) == position
            and getattr(mine.decide, "_hf014_module", None) is module):
        return
    decide = full_source_accept_rule(module)
    decide._hf014_module = module  # type: ignore[attr-defined]
    if mine is not None:
        route_spec.remove_route_rule("arbiter", FULL_SOURCE_RULE)
        position = sum(1 for rule in route_spec.route_rules("arbiter")
                       if rule.name.startswith(JUDGE_EXHAUSTED_RULES))
    route_spec.add_route_rule("arbiter", route_spec.RouteRule(FULL_SOURCE_RULE, decide), position=position)


def arbiter_caveats(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The visible caveat marker of an archived ``accept_with_caveats`` document, else None.

    ``{"decision", "reasoning", "judge_verdict", "whole_source", "hf014"}``: ``whole_source`` is
    whether the arbiter read the whole document (HF-014's condition) and ``hf014`` whether the
    vendored ``after_arbiter`` would have parked it (extraction still unsure), so HF-014 alone
    archived it. Every caveat-accepted archive gets the marker, whichever route archived it, so
    reports, the floor digest and the gate can count and separate them from clean archives.
    """
    if state.get("stage") != "archived" or state.get("arbiter_decision") != "accept_with_caveats":
        return None
    try:
        routing = importlib.import_module("graph.routing")
        whole = arbiter_read_whole_source(routing, state)
        unsure = bool(routing._extraction_still_unsure(state)) and confidence_floor_met(routing, state)
    except Exception:  # noqa: BLE001 — the marker never fails a record
        whole, unsure = False, False
    return {"decision": "accept_with_caveats",
            "reasoning": str(state.get("arbiter_reasoning") or "")[:500] or None,
            "judge_verdict": state.get("judge_verdict"),
            "whole_source": whole, "hf014": whole and unsure}


def _install_full_source_accept(module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """Register the HF-014 route rule; the router itself is unchanged (see HF-011)."""
    _register_full_source_rule(module)

    @functools.wraps(original)
    def after_arbiter(state: dict) -> Any:
        return original(state)

    return after_arbiter


def retry_closed(routing: Any, state: Mapping[str, Any]) -> bool:
    """HF-015: on a full-source route, whether the arbiter has no re-extraction left to order.

    Closed when HF-011's last judge pass is spent (a retry could not be judged again), or when
    ``arbiter_retry_count`` has reached ``arbiter_retry_max`` (``after_arbiter`` would refuse it).
    """
    if not _full_source_route(routing, state):
        return False
    thresholds = routing._thresholds_for(state)
    if thresholds.get("judge_exhausted_to_arbiter") is True and _judge_passes_spent(routing, state):
        return True
    raw = thresholds.get("arbiter_retry_max")
    retry_max = int(raw) if raw is not None else 2
    return int(state.get("arbiter_retry_count") or 0) >= retry_max


def _arbiter_node_state() -> Mapping[str, Any] | None:
    """The graph state of the ``arbiter_node`` call that invoked the wrapped ``arbitrate``, else None."""
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        if caller is None or caller.f_code.co_name != "arbiter_node":
            return None
        state = caller.f_locals.get("state")
        return state if isinstance(state, Mapping) else None
    finally:
        del frame


def _without_retry(schema: Any) -> Any:
    """``schema`` with ``retry_extraction`` dropped from its ``decision`` enum (a copy)."""
    if not isinstance(schema, Mapping):
        return schema
    out = copy.deepcopy(dict(schema))
    decision = (out.get("properties") or {}).get("decision")
    if isinstance(decision, dict) and isinstance(decision.get("enum"), list):
        decision["enum"] = [d for d in decision["enum"] if d != "retry_extraction"]
    return out


def _install_final_ruling(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """With no re-extraction budget left, the arbiter is asked for a final ruling.

    The vendored arbiter is always offered ``retry_extraction``; HF-011 and ``after_arbiter``
    then turn a retry they cannot grant into a park, under the arbiter's "ordered re-extraction"
    reason. On a full-source route this request drops ``retry_extraction`` from the decision
    enum and says why, so the model chooses between accepting with caveats and a person. An
    answer that still names a retry (a provider that does not enforce the schema) becomes
    ``human_review`` with its own reason. Every other call, and every Modal/vLLM or local call,
    is the vendored request.
    """

    @functools.wraps(original)
    def arbitrate(self: Any, *args: Any, **kwargs: Any) -> dict:
        state = _arbiter_node_state()
        try:
            routing = importlib.import_module("graph.routing")
        except Exception:  # noqa: BLE001 — optional (pipeline extra)
            routing = None
        if state is None or routing is None or not retry_closed(routing, state):
            return original(self, *args, **kwargs)
        had_own = "_call_structured" in vars(self)
        own = vars(self).get("_call_structured")
        call = self._call_structured

        def final_call(user_message: str, schema: Any = None, *a: Any, **k: Any) -> dict:
            return call(f"{user_message}\n\n{RETRY_CLOSED_NOTE}", _without_retry(schema), *a, **k)

        self._call_structured = final_call
        try:
            result = original(self, *args, **kwargs)
        finally:
            if had_own:
                self._call_structured = own
            else:
                del self._call_structured
        if isinstance(result, dict) and result.get("decision") == "retry_extraction":
            result = {**result, "decision": "human_review",
                      "reasoning": "arbiter asked for a re-extraction with no budget left; escalated "
                                   f"({str(result.get('reasoning') or '')[:200]})"}
        return result

    return arbitrate


HOTFIXES: tuple[Hotfix, ...] = (
    Hotfix(
        id="HF-001",
        module="langchain_agents.doc_inventories",
        attr="enrich_extraction",
        source_sha256="a9986cab125fc26e76d36de77ccd4a18d0537f5fa93f6ce146e9389186d20a90",
        upstream="Exios66/llm-mailroom#313",
        summary="corporate_record: a null record_type is filled from every corporate subclass "
                "through Dojo's subclass -> record_type map, not only the five Hub tokens",
        install=_install_record_type_from_subclass,
    ),
    Hotfix(
        id="HF-002",
        module="agents.judge",
        attr="CompletenessJudge.judge_completeness",
        source_sha256="880f296bc037e17376a34cf8964568bcf7a35ede7a0d1648d990b434ade5fbb9",
        upstream="Exios66/llm-mailroom#315",
        summary="a completeness-judge parse failure is asked once more; a second failure is a judge "
                "error (human review, counted), not an 'incomplete 0.0' verdict",
        install=_install_judge_parse_error,
    ),
    Hotfix(
        id="HF-003",
        module="agents.intake",
        attr="IntakeAgent.intake_run",
        source_sha256="f578ebf0562082c3eab3c64ff49782eed13236a4d3ff413aa74cf099a11ab5b1",
        upstream="Exios66/llm-mailroom#316",
        summary="a single-window intake cleaned_text replaces the document only when it keeps "
                "90% of its length and its words (no dropped run of 8+ words, under 5% lost); "
                "context fit reads long documents in one window",
        install=_install_intake_clean_guard,
    ),
    Hotfix(
        id="HF-004",
        module="pipeline.limits",
        attr="record_usage",
        source_sha256="f150e39413a1b6501feddcd6eed7f79414e5c44754e6c0f10486b0a7e344ed8b",
        upstream="Exios66/llm-mailroom#317",
        summary="every returned call is priced against the run's API cap as it returns, so a "
                "document in flight cannot spend past job.api_cost_cap_usd (job.call_guard)",
        install=_install_call_spend,
    ),
    Hotfix(
        id="HF-005",
        module="pipeline.watcher",
        attr="_DispatchPool.submit",
        source_sha256="be8d41188d093a667196d2c9af16342b0d35a237188660eca75308df0292018c",
        upstream="Exios66/llm-mailroom#318",
        summary="the watcher queues an inbox file only while dispatch, processing (and review, "
                "when limited) are below MAILROOM_MAX_QUEUE_DEPTH_<STAGE>; a held file stays in "
                "the inbox for the next rescan, never dropped (mailroom_sandbox.backpressure)",
        install=_install_dispatch_backpressure,
    ),
    Hotfix(
        id="HF-006",
        module="langchain_agents.specialist_agents",
        attr="_SpecialistBase._confidence_missing",
        source_sha256="dc2dacb46b6cfd3e7ccd3fd4bd4dff611ba1c91356f86c91567a57086078858c",
        upstream="https://github.com/Exios66/llm-mailroom/issues/279",
        summary="an explicit numeric confidence of zero remains zero on single and chunked "
                "extractions instead of being replaced by field-presence confidence",
        install=_install_explicit_zero_confidence,
    ),
    Hotfix(
        id="HF-007",
        module="graph.routing",
        attr="judge_gate",
        source_sha256="2ad6b396fa388c9ed478139a9460b3cf6a3e9b5b85b67a0f64670b81e8797e4b",
        upstream="https://github.com/Exios66/llm-mailroom/issues/278",
        summary="extraction confidence at or above judge_band_high still reaches the judge; "
                "MAILROOM_JUDGE_HIGH_BAND=off restores the vendored band (#215)",
        install=_install_judge_above_band,
    ),
    Hotfix(
        id="HF-008",
        module="langchain_agents.specialist_agents",
        attr="merge_chunk_windows",
        source_sha256="016b350d7e462b8e032fb17cbeb2a5c0b62825ff583bc09cd7045fe56fc14234",
        upstream="https://github.com/Exios66/llm-mailroom/issues/255",
        summary="a chunked merge records each surviving window's confidence and length under "
                "_window_confidences and _window_lengths, plus the cross-window agreement under "
                "_window_agreement; the merged confidence stays the weakest window (#214)",
        install=_install_window_confidences,
    ),
    Hotfix(
        id="HF-009",
        module="graph.build_graph",
        attr="_run_chunked_extraction",
        source_sha256="4582ca088cf6c34869891e093119c6b692d55e633f0b46f54e5a018c3b452a5f",
        upstream="Exios66/llm-mailroom#319 (budgets: #321)",
        summary="an API-routed specialist reads the whole document in one call and refuses a "
                "document over its budget; only Modal/vLLM and self-hosted routes chunk",
        install=_install_api_whole_document,
    ),
    Hotfix(
        id="HF-010",
        module="agents.intake",
        attr="sliding_windows",
        source_sha256="f826d7f9d88570fbd46a86e6a7dc3c7e5c973661e0caeaf0cdfa20f2fa2788a4",
        upstream="Exios66/llm-mailroom#319 (budgets: #321)",
        summary="an API-routed sorter or intake refuses a document that needs more than one "
                "window; only Modal/vLLM and self-hosted routes slide windows",
        install=_install_api_single_window,
    ),
    Hotfix(
        id="HF-011",
        module="graph.routing",
        attr="after_judge",
        source_sha256="f56bf75e06bfef996de395dc06cc1dfe8b23c8cdd681451b0e2f0c1f333f0a66",
        upstream="Exios66/llm-mailroom#320",
        summary="with confidence.judge_exhausted_to_arbiter, a partial verdict on the last judge "
                "pass goes to the arbiter (accept with caveats or a person) instead of straight to "
                "review, and the arbiter cannot order a retry the pass budget no longer covers",
        install=_install_judge_exhausted_to_arbiter,
        refresh=_register_judge_exhausted_rules,
        also=(("after_arbiter", "6cf2a63495a3c87a755f03b6fb59b424514f2ad7898882c79e192252aca94529"),),
    ),
    Hotfix(
        id="HF-012",
        module="graph.routing",
        attr="_transient_decision",
        source_sha256="506a662ea96308180e4c402a8276720698d4bacea01a5762e860eb3b101ca5f2",
        upstream="Exios66/llm-mailroom#320",
        summary="confidence.transient_retry_max, when set, bounds each node's transient self-loop "
                "(retry_chat_completion already retries inside the call); unset keeps the vendored 2",
        install=_install_transient_budget,
    ),
    Hotfix(
        id="HF-013",
        module="agents.judge",
        attr="CompletenessJudge.judge_extraction_correctness",
        source_sha256="dd2b8dae82df4c789b9636c694dd35ca1bd16212dbdd14788530d41aad0b4634",
        upstream="to file (Exios66/llm-mailroom)",
        summary="an accuracy-judge parse failure is asked once more; a second failure is a judge "
                "error (human review, counted), not an 'inaccurate 0.0' answer that reads as an "
                "incomplete verdict",
        install=_install_judge_correctness_parse_error,
    ),
    Hotfix(
        id="HF-014",
        module="graph.routing",
        attr="after_arbiter",
        source_sha256="6cf2a63495a3c87a755f03b6fb59b424514f2ad7898882c79e192252aca94529",
        upstream="to file (Exios66/llm-mailroom)",
        summary="with confidence.arbiter_full_source on a context-fitted route, an arbiter "
                "accept_with_caveats from a whole-source reading archives with its caveats when the "
                "extraction confidence reaches confidence.arbiter_full_source_min_confidence (unset: the "
                "class low, so no route changes); below it, lost chunks and conflicts still park",
        install=_install_full_source_accept,
        refresh=_register_full_source_rule,
        also=(("_extraction_still_unsure", "21700548d1be504e6bd7ce93164d6630fc25e05a86a82df8585d1b8bd3d5bd67"),
              ("_unadjudicated_conflict", "7084a3d97357b5ec6848b7847c95e3eabbbacfe7b474c8baf6270d5c2f24d1ce"),
              ("_chunks_lost", "85eca48ae57b740f0d5fbd6118eea1682778bc774c14a274cf7d32b704109b2a")),
    ),
    Hotfix(
        id="HF-015",
        module="agents.arbiter",
        attr="ArbiterAgent.arbitrate",
        source_sha256="c6c7b3ac5c4aa19ae58c84527901658c3caa41f5788da3010ef046295445e6d4",
        upstream="to file (Exios66/llm-mailroom)",
        summary="with confidence.arbiter_full_source on a context-fitted route, an arbiter with no "
                "re-extraction budget left is not offered retry_extraction: its ruling is final",
        install=_install_final_ruling,
        # The wrapper reads the graph state from this caller's frame (_arbiter_node_state).
        also=(("graph.build_graph:arbiter_node", "16755ef96c46505540bb921ce6a7b5eddc3c10819b300743868b92fdc51afc6f"),),
    ),
)

_STATUS: dict[str, str] = {}


def _source_sha(obj: Any) -> str:
    return hashlib.sha256(inspect.getsource(inspect.unwrap(obj)).encode("utf-8")).hexdigest()


def module_sha256() -> str:
    """sha256 of this module: the hotfix code identity a run lock records."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def apply_hotfixes(hotfixes: tuple[Hotfix, ...] = HOTFIXES) -> dict[str, str]:
    """Install every hotfix whose target still matches (idempotent); ``{id: status}``.

    Status is ``applied``, ``stale`` (the vendored target changed, so the fix was not
    installed) or ``unavailable`` (the vendored module cannot be imported here).
    """
    for fix in hotfixes:
        try:
            module = importlib.import_module(fix.module)
        except Exception as exc:  # noqa: BLE001 — optional (pipeline extra)
            _log.debug("%s: %s unavailable: %s", fix.id, fix.module, exc)
            _STATUS[fix.id] = "unavailable"
            continue
        owner_path, _, name = fix.attr.rpartition(".")
        owner: Any = module
        for part in owner_path.split(".") if owner_path else ():
            owner = getattr(owner, part)
        current = getattr(owner, name)
        if getattr(current, _MARK, None) == fix.id:
            if fix.refresh is not None:
                fix.refresh(module)
            _STATUS[fix.id] = "applied"
            continue
        drifted = [attr for attr, sha in fix.also if _also_sha(module, attr) != sha]
        if _source_sha(current) != fix.source_sha256 or drifted:
            _log.warning("%s not applied: vendored %s.%s changed since the hotfix was written "
                         "(re-validate it or retire it)", fix.id, fix.module, fix.attr)
            _STATUS[fix.id] = "stale"
            continue
        wrapped = fix.install(module, current)
        setattr(wrapped, _MARK, fix.id)
        setattr(owner, name, wrapped)
        _STATUS[fix.id] = "applied"
        _log.info("%s applied: %s", fix.id, fix.summary)
    return {fix.id: _STATUS[fix.id] for fix in hotfixes}


def _also_sha(module: Any, attr: str) -> str | None:
    """The source sha of the function an ``also`` entry names (``attr`` of ``module``, or
    ``other.module:attr``); ``None`` when it is gone, which counts as drift."""
    try:
        if ":" in attr:
            other, _, attr = attr.partition(":")
            module = importlib.import_module(other)
        owner: Any = module
        for part in attr.split("."):
            owner = getattr(owner, part)
        return _source_sha(owner)
    except Exception:  # noqa: BLE001 — a missing helper is drift, never a crash
        return None


def describe() -> dict[str, Any]:
    """Portable hotfix identity for run locks: module sha and each fix's target fingerprint."""
    return {
        "module_sha256": module_sha256(),
        "fixes": [{"id": f.id, "target": f"{f.module}.{f.attr}", "source_sha256": f.source_sha256}
                  for f in HOTFIXES],
    }


def stale() -> list[str]:
    """Hotfixes whose vendored target no longer matches (after :func:`apply_hotfixes`)."""
    status = apply_hotfixes()
    return [i for i, s in status.items() if s == "stale"]
