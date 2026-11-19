"""Stress harness: deterministic offline scenarios over the mailroom's load seams.

A larger experiment fails through seams that small mock runs never reach: a queue that
grows without bound, a document that loops past its call ceiling, a budget that drains
while documents are in flight, a wave of misclassifications that archives wrong documents.
This module simulates those conditions **against the real seams** — admission through
``backpressure.saturated``, per-call accounting and ceilings through ``job/call_guard.py``,
the ceiling's budget through a real ``ApiBudget`` — and injects failure modes into the
outcomes so the metric surfaces (``eval/human_review.py``, ``eval/archive_correctness.py``,
``failure_report``) can be read under load.

Everything here is deterministic (seeded), offline and mock: the reports are instrument
readings of the harness's behavior, never model evidence (``docs/critical-regressions.md``
row 8). The built-in scenarios (``default_scenarios``) are the preventative sweep: run
them before a campaign to confirm the invariants a paid run depends on still hold.
"""

from __future__ import annotations

import contextlib
import os
import random
from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from mailroom_sandbox.backpressure import saturated
from mailroom_sandbox.eval import archive_correctness as ac
from mailroom_sandbox.job import api_budget, call_guard

#: The live document classes a scenario draws from, in a fixed order (deterministic).
CLASSES: tuple[str, ...] = ("contract", "merger_agreement", "corporate_record",
                            "correspondence", "insurance_claim")

_QUEUE_ENV = "MAILROOM_MAX_QUEUE_DEPTH_DISPATCH"


class FailureMix(BaseModel):
    """Per-document failure injection rates, each in ``[0, 1]`` (a seeded draw)."""

    model_config = ConfigDict(extra="forbid")

    #: Archived under another class than expected (reason ``wrong_class_archive``).
    wrong_class_rate: float = 0.0
    #: Archived with a parse error (reason ``parse_error_archive``).
    parse_error_rate: float = 0.0
    #: Finishes in stage ``review`` (a human-review document).
    review_rate: float = 0.0
    #: Raises mid-flight (an error row that never reached a stage).
    crash_rate: float = 0.0
    #: Keeps calling until the per-document ceiling refuses it (a looping document).
    loop_rate: float = 0.0
    #: API calls every non-crashing, non-looping document makes before its outcome.
    calls_per_doc: int = 1

    @field_validator("wrong_class_rate", "parse_error_rate", "review_rate", "crash_rate", "loop_rate")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("failure rates must be within [0, 1]")
        return value

    @field_validator("calls_per_doc")
    @classmethod
    def _positive_calls(cls, value: int) -> int:
        if value < 1:
            raise ValueError("calls_per_doc must be >= 1")
        return value


class Scenario(BaseModel):
    """One simulated load condition (``extra="forbid"``, like every spec section)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    documents: int
    seed: int = 0
    #: Maximum depth of the simulated dispatch queue (0 = unbounded; intake holds the rest).
    dispatch_limit: int = 0
    #: Per-document call ceiling handed to the real call guard.
    call_ceiling: int = 16
    #: The simulated run's API ceiling: a positive cap is required so the budget is real.
    api_cap_usd: float = 100.0
    #: Prompt tokens every simulated call bills (output tokens are 0).
    tokens_per_call: int = 1_000
    failure: FailureMix = FailureMix()

    @field_validator("documents", "dispatch_limit", "call_ceiling")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("document counts, queue limits and call ceilings must be >= 0")
        return value

    @field_validator("documents")
    @classmethod
    def _some_documents(cls, value: int) -> int:
        if value < 1:
            raise ValueError("a scenario needs at least one document")
        return value

    @field_validator("api_cap_usd")
    @classmethod
    def _positive_cap(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("api_cap_usd must be positive: a scenario without a real budget tests nothing")
        return value


def default_scenarios() -> list[Scenario]:
    """The preventative sweep: one scenario per seam, plus a mixed-chaos soak."""
    return [
        Scenario(name="queue-flood", documents=50, dispatch_limit=16),
        Scenario(name="looper-against-call-ceiling", documents=6, call_ceiling=4,
                 failure=FailureMix(loop_rate=1.0, calls_per_doc=2)),
        Scenario(name="budget-drain", documents=12, api_cap_usd=0.02, tokens_per_call=100_000,
                 failure=FailureMix(calls_per_doc=5)),
        Scenario(name="misclassification-wave", documents=8,
                 failure=FailureMix(wrong_class_rate=1.0)),
        Scenario(name="unsure-wave", documents=8, failure=FailureMix(review_rate=1.0)),
        Scenario(name="parse-error-flood", documents=8, failure=FailureMix(parse_error_rate=1.0)),
        Scenario(name="mixed-chaos", documents=24, seed=7,
                 failure=FailureMix(wrong_class_rate=0.25, parse_error_rate=0.2,
                                    review_rate=0.3, crash_rate=0.1, loop_rate=0.15,
                                    calls_per_doc=3)),
    ]


def _admit(documents: int, dispatch_limit: int) -> tuple[int, int]:
    """Admission through the real ``saturated`` seam: (admitted, held). Nothing is dropped."""
    if dispatch_limit <= 0:
        return documents, 0
    with _dispatch_limit_env(dispatch_limit):
        admitted = 0
        while admitted < documents and not saturated(("dispatch",), depths={"dispatch": admitted}):
            admitted += 1
    return admitted, documents - admitted


@contextlib.contextmanager
def _dispatch_limit_env(value: int) -> Iterator[None]:
    had = os.environ.get(_QUEUE_ENV)
    os.environ[_QUEUE_ENV] = str(value)
    try:
        yield
    finally:
        if had is None:
            os.environ.pop(_QUEUE_ENV, None)
        else:
            os.environ[_QUEUE_ENV] = had


def run_scenario(spec: Scenario) -> dict[str, Any]:
    """Run one scenario against the real seams and return its report with invariant checks."""
    rng = random.Random(spec.seed)
    admitted, held = _admit(spec.documents, spec.dispatch_limit)
    budget = api_budget.ApiBudget(spec.api_cap_usd, 0.005, 0.005, ["mock/scenario-model"])
    rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    error_rows = 0
    calls = 0
    injected_failures = 0  # crash, loop or refused-by-guard documents that must all be error rows
    doc_calls: list[int] = []
    call_guard.arm(budget, spec.call_ceiling)
    try:
        for index in range(admitted):
            cls = CLASSES[index % len(CLASSES)]
            # Rows and results stay pairwise aligned for every admitted document: the
            # incorrect-archive metric is silent for a result whose row is missing.
            rows.append({"expected_doc_class": cls, "expected_stage": "archived"})
            crashed = rng.random() < spec.failure.crash_rate
            looping = not crashed and rng.random() < spec.failure.loop_rate
            reviewing = not crashed and not looping and rng.random() < spec.failure.review_rate
            wrong = (not crashed and not looping and not reviewing
                     and rng.random() < spec.failure.wrong_class_rate)
            parse_error = (not crashed and not looping and not reviewing
                           and rng.random() < spec.failure.parse_error_rate)
            with call_guard.document() as doc:
                if crashed:
                    results.append({"stage": "failed", "doc_type": cls, "error": "simulated crash"})
                    error_rows += 1
                    injected_failures += 1
                    continue
                if looping:
                    # Keep calling until the guard refuses: a document cut short by the
                    # ceiling becomes an error row, never a scored outcome.
                    refused = None
                    for _ in range(spec.failure.calls_per_doc * spec.call_ceiling):
                        try:
                            call_guard.before_call()
                        except Exception as exc:  # noqa: BLE001 - the refusal is the outcome
                            refused = str(exc)
                            break
                        call_guard.after_call({"input_tokens": spec.tokens_per_call, "output_tokens": 0})
                        calls += 1
                    results.append({"stage": "failed", "doc_type": cls,
                                    "error": refused or "simulated loop"})
                    error_rows += 1
                    injected_failures += 1
                    doc_calls.append(doc["calls"])
                    continue
                try:
                    for _ in range(spec.failure.calls_per_doc):
                        call_guard.before_call()
                        call_guard.after_call({"input_tokens": spec.tokens_per_call, "output_tokens": 0})
                        calls += 1
                except Exception as exc:  # noqa: BLE001 - the refusal is the outcome
                    # A drained budget refuses the document's first call too: it becomes
                    # an error row, exactly like a looping document cut by the ceiling.
                    results.append({"stage": "failed", "doc_type": cls, "error": str(exc)})
                    error_rows += 1
                    injected_failures += 1
                    doc_calls.append(doc["calls"])
                    continue
                doc_calls.append(doc["calls"])
                results.append({
                    "stage": "review" if reviewing else "archived",
                    "doc_type": (next(c for c in CLASSES if c != cls) if wrong else cls),
                    "parse_error": parse_error,
                })
        archive = ac.for_pipeline(rows, results, extraction_rows=[None] * len(results))
        review_count = sum(1 for r in results if r.get("stage") == "review")
        finished = sum(1 for r in results if r.get("stage") == "archived")
        failure = ac.failure_report(
            {"doc_class": rows[i]["expected_doc_class"], "outcome": _outcome(results[i]),
             "cause": _cause(results[i])}
            for i in range(len(results))
        )
    finally:
        call_guard.disarm()

    invariants = _invariants(spec, admitted, held, error_rows, injected_failures,
                             doc_calls, budget, archive, failure, results)
    return {
        "scenario": spec.name,
        "documents": spec.documents,
        "admitted": admitted,
        "held": held,
        "error_rows": error_rows,
        "calls": calls,
        "spend_usd": round(budget.live_total_usd(), 6),
        "outcomes": {"archived": finished, "review": review_count, "failed": error_rows},
        "review_rate": round(review_count / spec.documents, 6) if spec.documents else None,
        **archive,
        "failure_report": failure,
        "invariants": invariants,
        "invariants_ok": all(item["ok"] for item in invariants),
    }


def _outcome(result: Mapping[str, Any]) -> str:
    stage = result.get("stage")
    if stage == "failed":
        return "crashed"
    if stage == "review":
        return "review"
    return "correct_archive"


def _cause(result: Mapping[str, Any]) -> str:
    if result.get("stage") == "failed":
        return "simulated_crash" if result.get("error") == "simulated crash" else "call_ceiling"
    if result.get("stage") == "review":
        return "sorter_low_confidence"
    if result.get("parse_error"):
        return "parse_error"
    return ""


def _invariants(spec: Scenario, admitted: int, held: int, error_rows: int, injected_failures: int,
                doc_calls: list[int], budget: Any, archive: dict[str, Any],
                failure: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The checks a paid experiment depends on; every one must hold for the run to count.

    The two checks that guard seam behavior compare an observed value against a bound
    computed independently of the seam under test (admission against a spec-derived
    bound; the call ceiling against every document's tracked count). The others are
    consistency tripwires over values the harness itself records, so a report bug
    cannot hide a broken run even where it cannot re-derive the seam.
    """
    # The guard refuses a call when the projected spend has reached the cap, so the true
    # bound is "within one call of the cap" (plus float noise in the cumulative sum),
    # not strict <=. A spend over that bound means the refusal did not fire.
    one_call_usd = spec.tokens_per_call / 1e6 * 0.005
    # Admission bound recomputed from the spec alone: a `saturated` seam that never fires
    # would admit everything (violating this), not just pass an arithmetic identity.
    expected_admitted = min(spec.documents, spec.dispatch_limit) if spec.dispatch_limit > 0 else spec.documents
    return [
        {"name": "nothing_dropped",
         "ok": (admitted, held) == (expected_admitted, spec.documents - expected_admitted),
         "detail": (f"admitted {admitted} + held {held} against the spec bound "
                    f"{expected_admitted} admitted / {spec.documents - expected_admitted} held")},
        {"name": "spend_within_one_call_of_cap",
         "ok": budget.live_total_usd() <= spec.api_cap_usd + one_call_usd,
         "detail": (f"spend {budget.live_total_usd():.6f} <= cap {spec.api_cap_usd} "
                    f"+ one call ({one_call_usd:.6f})")},
        {"name": "per_document_call_ceiling_respected",
         "ok": not doc_calls or max(doc_calls) <= spec.call_ceiling,
         "detail": (f"max calls by one document {max(doc_calls, default=0)} <= ceiling "
                    f"{spec.call_ceiling}")},
        {"name": "injected_failures_are_error_rows",
         "ok": error_rows == injected_failures,
         "detail": f"{injected_failures} injected failure documents -> {error_rows} error rows"},
        {"name": "scored_documents_carry_no_error",
         "ok": all(not r.get("error") for r in results if r.get("stage") != "failed"),
         "detail": "no finished document in a stage other than failed carries an error"},
        {"name": "metrics_reported",
         "ok": ac.KEY in archive and "n" in failure,
         "detail": "incorrect-archive and failure-taxonomy surfaces present"},
    ]
