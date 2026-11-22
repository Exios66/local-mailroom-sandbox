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

import difflib
import functools
import hashlib
import importlib
import inspect
import logging
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
    """The completeness judge's answer did not parse: no verdict was reached (HF-002)."""


def _install_judge_parse_error(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def judge_completeness(self: Any, *args: Any, **kwargs: Any) -> dict:
        out = original(self, *args, **kwargs)
        # Upstream turns a parse failure into a real "incomplete 0.0" verdict, which sends the
        # document to the arbiter as if the extraction were judged incomplete and is never counted
        # as a judge error. Raising takes the graph's own hard-failure path: judge_verdict
        # "judge_error", routed to human review and counted by the gate.
        if str(out.get("reasoning") or "") == JUDGE_PARSE_FAILURE and out.get("completeness") == 0.0:
            raise JudgeParseError(JUDGE_PARSE_FAILURE)
        return out

    return judge_completeness


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


def _install_window_confidences(_module: Any, original: Callable[..., Any]) -> Callable[..., Any]:
    """Record each surviving window's confidence and character length. The merged value stays the vendor's minimum."""

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
        return merged

    return merge_chunk_windows


class WholeDocumentTooLong(ValueError):
    """An API-routed specialist got a document longer than its input budget (HF-009)."""


def _api_route(agent_name: str) -> bool:
    """True when ``agent_name`` calls a hosted API, not Modal/vLLM or another self-hosted server."""
    from llm.client import is_free_only_exempt, resolve_agent_model  # type: ignore
    from pipeline.config import get_agent_config  # type: ignore

    resolved = resolve_agent_model(agent_name, get_agent_config(agent_name))
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
        upstream="llm-mailroom: draft issue J-1 in docs/vendor-hotfixes.md (not filed)",
        summary="a completeness-judge parse failure is a judge error (human review, counted), "
                "not an 'incomplete 0.0' verdict",
        install=_install_judge_parse_error,
    ),
    Hotfix(
        id="HF-003",
        module="agents.intake",
        attr="IntakeAgent.intake_run",
        source_sha256="f578ebf0562082c3eab3c64ff49782eed13236a4d3ff413aa74cf099a11ab5b1",
        upstream="llm-mailroom: draft issue J-2 in docs/vendor-hotfixes.md (not filed)",
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
        upstream="llm-mailroom: draft issue J-3 in docs/vendor-hotfixes.md (not filed)",
        summary="every returned call is priced against the run's API cap as it returns, so a "
                "document in flight cannot spend past job.api_cost_cap_usd (job.call_guard)",
        install=_install_call_spend,
    ),
    Hotfix(
        id="HF-005",
        module="pipeline.watcher",
        attr="_DispatchPool.submit",
        source_sha256="be8d41188d093a667196d2c9af16342b0d35a237188660eca75308df0292018c",
        upstream="llm-mailroom: draft issue J-4 in docs/vendor-hotfixes.md (not filed)",
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
                "_window_confidences and _window_lengths; the merged confidence stays the weakest window (#214)",
        install=_install_window_confidences,
    ),
    Hotfix(
        id="HF-009",
        module="graph.build_graph",
        attr="_run_chunked_extraction",
        source_sha256="4582ca088cf6c34869891e093119c6b692d55e633f0b46f54e5a018c3b452a5f",
        upstream="draft J-5 below (not filed)",
        summary="an API-routed specialist reads the whole document in one call and refuses a "
                "document over its budget; only Modal/vLLM and self-hosted routes chunk",
        install=_install_api_whole_document,
    ),
    Hotfix(
        id="HF-010",
        module="agents.intake",
        attr="sliding_windows",
        source_sha256="f826d7f9d88570fbd46a86e6a7dc3c7e5c973661e0caeaf0cdfa20f2fa2788a4",
        upstream="draft J-5 below (not filed)",
        summary="an API-routed sorter or intake refuses a document that needs more than one "
                "window; only Modal/vLLM and self-hosted routes slide windows",
        install=_install_api_single_window,
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
            _STATUS[fix.id] = "applied"
            continue
        if _source_sha(current) != fix.source_sha256:
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
