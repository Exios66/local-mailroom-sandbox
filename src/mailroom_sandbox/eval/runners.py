"""Eval runners: sorter / extract / chained / pipeline / specialist."""

from __future__ import annotations

import logging
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence
from unittest.mock import patch

from mailroom_sandbox.datasets import (
    dataset_fingerprint,
    fixture_file,
    load_manifest,
    parse_expected_fields,
)
from mailroom_sandbox import scoring_hotfixes
from mailroom_sandbox.eval import experiment_log, scoring, tracing
from mailroom_sandbox.eval.prompt_provenance import (
    resolve_logged_prompt_version,
    stamp_prompt_provenance,
)
from mailroom_sandbox.eval.scoring import emit, validate_dataset_revision
from mailroom_sandbox.mock_llm import fake_client, fake_structured_payload
from mailroom_sandbox.runtime import activate, resolve_mailroom_src

_log = logging.getLogger("mailroom_sandbox.eval.runners")

try:
    from llm_dojo_scoring.emitter import ScoreRecord
except Exception as exc:  # pragma: no cover
    _log.warning(
        "llm_dojo_scoring.emitter.ScoreRecord unavailable — every eval-run score "
        "emission is SKIPPED (runs still record locally, but the dojo sink "
        "never sees them). Defect in the vendored dojo snapshot.",
        exc_info=exc,
    )
    ScoreRecord = None  # type: ignore



def sandbox_matter_id(row: Mapping[str, Any], run_id: str | None) -> str:
    """Catalog matter for one sandbox row, scoped to its run.

    The catalog (``mailroom.db``) outlives runs, and the graph's conflict check
    compares an extraction with every *archived* record of the same matter. A
    row-only id made a rerun of the same dataset compare each document with the
    previous run's copy of itself, so most documents took a Boss ruling instead
    of the judge (pipeline-qwen-flash-25-fit: 14/25). Scoping to the run keeps
    one run's archive out of another's routing.
    """
    scope = str(run_id or "adhoc")
    return f"SANDBOX-{scope}-{row.get('id')}"

def _estimated_gpu_usd(
    wall: float, *, gpu: str | None, replicas: int, gpu_fleet: list[tuple[str, int]] | None
) -> float:
    """Warm-GPU $ for a spend cap: the whole routed fleet when known, else the base engine."""
    from mailroom_sandbox.job.metrics import estimate_gpu_cost_usd, fleet_gpu_cost_usd

    if gpu_fleet:
        return fleet_gpu_cost_usd(wall, gpu_fleet)
    return float(estimate_gpu_cost_usd(wall, gpu=gpu or "L4", replicas=replicas) or 0.0)


_GPU_PROFILES = ("modal-vllm", "vllm-local", "vllm-remote")


def _cap_gpu(gpu: str | None, gpu_fleet: list[tuple[str, int]] | None, profile: str | None) -> str | None:
    """The GPU class a ``cost_cap_usd`` guard bills, or None when no GPU serves the run.

    An explicit engine GPU or a routed fleet bills; a GPU serving profile without either claims
    the default L4. An API-only run (OpenRouter) bills no GPU, so its wall clock never trips the
    GPU cap (rb1 R01: an OpenRouter smoke died on an L4 estimate); job.api_cost_cap_usd bounds it.
    """
    if gpu or gpu_fleet:
        return gpu or "L4"
    if not profile:  # activate(None) serves the default profile (modal-vllm unless configured)
        from mailroom_sandbox.providers import default_profile

        profile = default_profile()
    return "L4" if profile in _GPU_PROFILES else None


# ``classification_arbiter_decision`` lets the gate's cause typing tell reviewer doubt the classification
# arbiter settled (it accepted a class) from doubt it left standing; None when that arbiter did not run.
REVIEW_OUTCOME_FIELDS = ("review_causes", "review_verdict", "escalation_reason",
                        "reviewer_doc_type", "reviewer_confidence", "classification_arbiter_decision")
# llm-mailroom decision_slots records (graph/decision_slots.py), exported per document so the
# Dojo's analysis.risk_coverage.slot_decision_summary can score each slot.
DECISION_SLOT_FIELDS = ("decision_slot_outcomes", "decision_slot_marks", "closed_field_resolutions", "judge_source")


def _arbiter_caveats(result: dict[str, Any]) -> dict[str, Any] | None:
    from mailroom_sandbox.vendor_hotfixes import arbiter_caveats

    return arbiter_caveats(result)


def _expect_from_row(row: dict[str, Any]) -> dict[str, Any]:
    doc_type = row.get("expected_doc_class") or row.get("doc_type") or "contract"
    conf = 0.40 if row.get("id") == "ambiguous_01" else 0.99  # above every class high threshold
    expect = {
        "id": row.get("id"),
        "doc_type": doc_type,
        "expected_doc_class": doc_type,
        "conf": conf,
        "expected_subclass": row.get("expected_subclass"),
        "expected_fields": parse_expected_fields(row) if "expected_fields" in row else row.get("expected_fields"),
    }
    # A pipeline mock row can force the classification arbiter's decision the same way a
    # hand-built expect dict can: without it the mock silently uses the class-matching fallback.
    decision = row.get("classification_arbiter_decision")
    if decision:
        expect["classification_arbiter_decision"] = decision
    return expect


def _classify_mock(row: dict[str, Any]) -> str:
    return str(row.get("expected_doc_class") or row.get("doc_type") or "unknown")


def isolated_call_scope(task: str, *, mock: bool):
    """Per-document call ceiling for a one-request Decisions task.

    Pipeline documents already enter ``call_guard.document`` (the R01 ceiling).
    An isolated chat specialist can legitimately exceed the default ceiling
    while it chunks a long document, so only ``sorter_reviewer`` and
    ``extraction_gate`` take the scope. Mock rows do not.
    """
    from contextlib import nullcontext

    if mock or task not in ("sorter_reviewer", "extraction_gate"):
        return nullcontext({"calls": 0, "refused": None})
    from mailroom_sandbox.job import call_guard

    return call_guard.document()


#: Usage keys a persisted item carries: kept on a replayed row for reporting, never billed again.
REPLAY_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "llm_calls", "call_usage", "usage_by_agent",
                     "cached_tokens", "cache_write_tokens", "reported_cost_usd")


def replayable(item: Mapping[str, Any] | None) -> bool:
    """True when a persisted item holds an answer a resumed run can replay: its ``pred`` is a dict and it
    did not fail. A failed row (a timeout, a 5xx, a guard refusal) runs again, so a resume can recover it;
    an answer that failed to parse is a real billed answer and is replayed."""
    return isinstance(item, Mapping) and isinstance(item.get("pred"), Mapping) and not item.get("error")


def _replay_usage(item: Mapping[str, Any]) -> dict[str, Any]:
    return {k: item[k] for k in REPLAY_USAGE_KEYS if item.get(k) is not None}


def _replay_window(item: Mapping[str, Any]) -> tuple[int, int] | None:
    start, end = item.get("started_at_ns"), item.get("finished_at_ns")
    return (start, end) if isinstance(start, int) and isinstance(end, int) else None


def _run_rows_bounded(
    rows: list[Any],
    *,
    workers: int,
    run_one,
    on_result,
    guard,
    order: list[int] | None = None,
    skip: Collection[int] = (),
) -> None:
    """Execute ``run_one(i, row)`` with at most ``workers`` in flight.

    ``order`` is the submission order of row indices (default: drawn order). It only
    changes when each row starts; results are still recorded by their drawn index.

    Guards *before every new submission*: a tripped wall/cost cap must stop
    starting work immediately. An eager submit-all pool would keep burning GPU
    on already-queued rows after the cap fired, so a concurrent run could
    silently overshoot its budget (SAND-018 cost-guard accuracy). The guard is
    called as ``guard(in_flight)`` with the number of rows started but not yet
    recorded, whose spend is not in any running total yet.
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    skipped = set(skip)
    wanted = [i for i in range(len(rows)) if i not in skipped]
    queue = wanted if order is None else list(order)
    if sorted(queue) != wanted:
        raise ValueError("order must be a permutation of the row indices that are not skipped")
    n = len(queue)
    if workers <= 1:
        for index in queue:
            guard(0)
            on_result(index, run_one(index, rows[index]))
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: dict[Any, int] = {}
        nxt = 0
        try:
            while nxt < n or futures:
                guard(len(futures))
                while nxt < n and len(futures) < workers:
                    if futures:
                        guard(len(futures))
                    futures[pool.submit(run_one, queue[nxt], rows[queue[nxt]])] = queue[nxt]
                    nxt += 1
                if not futures:
                    break
                done, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                for fut in done:
                    index = futures.pop(fut)
                    on_result(index, fut.result())
        except Exception:
            for fut in futures:
                fut.cancel()
            raise


def _predict_spec(spec, row: dict[str, Any], *, mock: bool) -> tuple[dict[str, Any], bool]:
    """Predict one row; ``fell_back`` is True only when NO live fn exists.

    Live-or-loud (DMR-044): a live-configured eval never degrades to the mock
    predictor on error — the exception propagates and the caller records it as
    an item error instead of silently scoring a mock prediction.
    """
    if mock:
        return spec.mock_predict(row), False
    if spec.live_predict is None:
        return spec.mock_predict(row), True
    return spec.live_predict(row), False


def _row_value(entry: Mapping[str, Any], *, raw: bool = False) -> float | None:
    """A row's scored value as the pre-hotfix aggregate read it (``match``, else the extraction score).

    ``raw`` reads the row's ``raw_dojo`` values over the hotfixed ones (the raw headline side).
    """
    scored = entry.get("score") or {}
    if raw and isinstance(scored.get("raw_dojo"), Mapping):
        scored = {**scored, **scored["raw_dojo"]}
    match = scored.get("match")
    if match is None and "overall_extraction_score" in scored:
        match = scored.get("overall_extraction_score") or 0.0
    return float(match) if isinstance(match, (int, float)) and not isinstance(match, bool) else None


def _isolated_headline(per_row: Sequence[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Run headline of an isolated eval, dual reported (``docs/scoring-hotfixes.md``).

    Raw (the pre-hotfix aggregate): the mean over rows that produced a value; an errored row
    leaves the denominator and a row without truth averages in as 0.
    SHF-005: an errored row scores 0. SHF-006: a row without truth (no ``match`` and no
    extraction score) is left out and counted under ``n_no_truth``. Abstentions are counted.
    """
    from mailroom_sandbox import scoring_hotfixes as sh

    entries = [e for e in per_row if e is not None]
    raw_values = [v for v in (_row_value(e, raw=True) for e in entries) if v is not None]
    raw_mean = scoring.mean_or_zero(raw_values)
    on = sh.current_ids()
    values: list[float] = []
    no_truth = abstain = 0
    for e in entries:
        scored = e.get("score") or {}
        if (scored.get("raw_dojo") or {}).get("abstain") or scored.get("abstain"):
            abstain += 1
        if e.get("error") and "SHF-005" in on:
            values.append(0.0)
            continue
        if e.get("error"):
            continue
        if "SHF-006" in on:
            value = scored.get("match")
            if value is None:
                value = scored.get("overall_extraction_score")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                no_truth += 1
                continue
            values.append(float(value))
        else:
            value = _row_value(e)
            if value is not None:
                values.append(value)
    # Provenance: the aggregation fixes plus every fix that moved a contributing row's score.
    used = sorted((on & {"SHF-005", "SHF-006"})
                  | {i for e in entries for i in ((e.get("score") or {}).get("scoring_hotfixes") or [])})
    raw_part = {"exact_match": raw_mean, "n_scored": len(raw_values)}
    fixed_part = {"exact_match": scoring.mean_or_zero(values) if values else (None if "SHF-006" in on else 0.0),
                  "n_scored": len(values), "n_no_truth": no_truth, "abstain": abstain}
    return sh.merge_dual(raw_part, fixed_part, used)


def _merge_subclass_headline(scores: dict[str, Any], sub: Mapping[str, Any]) -> None:
    """Fold SHF-013's dual subclass scores into an isolated run headline (raw side under ``raw_dojo``)."""
    if not sub:
        return
    scores.update({k: v for k, v in sub.items()
                   if k not in ("raw_dojo", "scoring_hotfixes", "scoring_hotfixes_changed")})
    scores.setdefault("raw_dojo", {}).update(sub.get("raw_dojo") or {})
    scores["scoring_hotfixes"] = sorted({*scores.get("scoring_hotfixes", []), *sub.get("scoring_hotfixes", [])})
    scores["scoring_hotfixes_changed"] = sorted({*scores.get("scoring_hotfixes_changed", []),
                                                 *sub.get("scoring_hotfixes_changed", [])})


def _logged_prompt(prompt_version: str | None, *, task: str) -> tuple[str, str | None]:
    return resolve_logged_prompt_version(prompt_version, task=task)


def run_isolated_eval(
    task: str,
    *,
    mock: bool = True,
    sample: int | None = None,
    sample_seed: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    prompt_version: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    agent_models: dict[str, str] | None = None,
    connected: bool = False,
    rows: list[dict[str, Any]] | None = None,
    cold_boot_seconds: float | None = None,
    concurrency: int = 1,
    max_wall_seconds: float | None = None,
    cost_cap_usd: float | None = None,
    api_budget: Any = None,
    gpu: str | None = None,
    progress_cb: Any = None,
    replicas: int = 1,
    gpu_fleet: list[tuple[str, int]] | None = None,
    row_cb: Any = None,
    score_metadata: dict[str, Any] | None = None,
    longest_first: bool = False,
    replay: Mapping[Any, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one live agent / node against fixtures, nested under document-pipeline.

    ``replay`` maps a row id to the item an earlier attempt of this run persisted: a replayable row
    keeps its stored answer and score (scorer and truth are locked) with no model call and no new spend.

    ``longest_first`` (``job.longest_first``) starts the longest ``doc_text`` first, so a
    many-window document does not decode alone at the end; rows keep their drawn index.

    ``rows`` (DMR-056): when the caller passes the locked live dataset rows
    (the ``sandbox run`` whole-run path), score THOSE rows; otherwise fall
    back to the agent's committed fixture rows.
    """
    from mailroom_sandbox.eval.agents import spec_for

    import statistics
    import time

    from mailroom_sandbox.job.usage_capture import (
        call_usage_from_pipeline,
        merge_item_metrics,
        reset_usage,
        usage_from_pipeline,
    )

    spec = spec_for(task)
    if prompt_version is None:
        # No --prompt: the agent's lineage frontrunner (the same default a locked run
        # gets), never a silent regression to the pre-condensed stem. An explicit
        # --prompt-version selection owns the surface instead; agents outside the
        # condensed lineages keep their eval-environment parity stem.
        from mailroom_sandbox import prompt_versions as pv

        if not pv.active_selection():
            from mailroom_sandbox.prompt_lineage import default_stem_for

            prompt_version = default_stem_for(task)
    rows = spec.load_rows() if rows is None else rows
    if sample is not None:
        if sample <= 0:
            raise ValueError("sample must be positive")
        rows = _seeded_sample(rows, sample, sample_seed) if sample_seed is not None else rows[:sample]
    plan = {
        "task": task,
        "n": len(rows),
        "mock": mock,
        "prompt_version": prompt_version,
        "profile": profile,
        "model": model,
        "observation": spec.observation,
        "observation_type": tracing.observation_type_for(spec.observation),
        "fingerprint": dataset_fingerprint(rows) if rows else "",
        "connected": False,
    }
    if dry_run:
        return plan

    os.environ["SANDBOX_RUN_MODE"] = "mock" if mock else "local"
    activation = activate(
        profile, model=model, prompt_variant=prompt_version, agent_models=agent_models
    )
    session = tracing.session_id_for(task)
    matches: list[float] = []
    per_row: list[dict[str, Any] | None] = [None] * len(rows)
    offline = 0
    errors = 0

    def _run_one(index: int, row: dict[str, Any]) -> dict[str, Any]:
        seed = str(row.get("id") or row.get("filename") or task)
        started = time.perf_counter()
        # Epoch window around this row's own execution, so a job.item span built from it
        # excludes the wait before the main thread records the row.
        started_ns = time.time_ns()
        error: str | None = None
        pred: dict[str, Any] = {}
        scored: dict[str, Any] = {}
        fell_back = False
        usage: dict[str, Any] = {}
        with isolated_call_scope(task, mock=mock) as scope:
            try:
                # SAND-018: reset the thread's usage accumulator so this row's tokens
                # are its own — without it, pooled rows sum into one inflated total.
                reset_usage()
                with tracing.document_pipeline_trace(
                    seed=seed,
                    session_id=session,
                    input={"filename": row.get("filename") or row.get("id"), "matter_id": sandbox_matter_id(row, experiment_name)},
                    metadata={"pipeline": "mailroom", "source": "sandbox-fixtures", "run_id": experiment_name, "attempt": 1},
                    tags=tracing.default_tags("source-fixtures", f"agent-{task}"),
                ):
                    with tracing.child_observation(
                        spec.observation,
                        as_type=tracing.observation_type_for(spec.observation),
                        input=tracing.public_ground_truth(row),
                    ):
                        pred, fell_back = _predict_spec(spec, row, mock=mock)
                    scored = spec.score_one(row, pred)
                # SAND-018: per-item token capture — the isolated path used to drop
                # usage entirely, so a specialist run had no tokens/latency to report.
                usage = usage_from_pipeline()
            except Exception as exc:  # noqa: BLE001 — recorded as an item error, never a silent mock
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                # SAND-089: a call made before the failure was still billed; keep its tokens.
                usage = usage_from_pipeline()
            if scope.get("refused") and not error:
                error = (f"document stopped by the API call guard ({scope['calls']} calls): "
                         f"{scope['refused']}")[:300]
            calls = call_usage_from_pipeline()
            entry: dict[str, Any] = {
                "id": row.get("id"),
                "pred": pred,
                "score": scored,
                "offline_fallback": fell_back,
                "error": error,
                "started_at_ns": started_ns,
                "finished_at_ns": time.time_ns(),
            }
            if calls:
                entry["call_usage"] = calls
            entry.update(
                merge_item_metrics(
                    latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
                    usage=usage,
                )
            )
            return entry

    def _absorb(entry: dict[str, Any]) -> None:
        nonlocal offline, errors
        if entry.get("offline_fallback"):
            offline += 1
        if entry.get("error"):
            errors += 1
        scored = entry.get("score") or {}
        match = scored.get("match")
        if match is None and "overall_extraction_score" in scored:
            match = scored.get("overall_extraction_score") or 0.0
        if isinstance(match, (int, float)):
            matches.append(float(match))

    budget_started = time.perf_counter()

    def _guard(in_flight: int = 0) -> None:
        """Wall/cost abort so a whole-run task cannot silently overrun its caps.

        The per-item loop already enforces these; isolated agent tasks had no
        guard at all (SAND-018: a 20-doc run overspent its $0.55 cap).
        ``in_flight`` rows are started but unbilled; the API check counts them.
        """
        wall = time.perf_counter() - budget_started
        if max_wall_seconds is not None and wall >= float(max_wall_seconds):
            raise RuntimeError(
                f"isolated eval aborted: max_wall_seconds={max_wall_seconds} "
                f"exceeded (wall={wall:.1f}s) — protecting spend"
            )
        if cost_cap_usd is not None and _cap_gpu(gpu, gpu_fleet, profile):
            est = _estimated_gpu_usd(wall, gpu=_cap_gpu(gpu, gpu_fleet, profile), replicas=replicas,
                                     gpu_fleet=gpu_fleet)
            if est >= float(cost_cap_usd):
                raise RuntimeError(
                    f"isolated eval aborted: cost_cap_usd={cost_cap_usd} exceeded "
                    f"(est_gpu_usd={est:.4f} at wall={wall:.1f}s) — protecting spend"
                )
        if api_budget is not None and not mock:
            # SAND-089: token spend on API-billed agents, priced at the run's highest API price.
            api_budget.check("isolated eval aborted: ", in_flight=in_flight)

    workers = max(1, min(int(concurrency), len(rows) or 1))

    def _record(index: int, entry: dict[str, Any]) -> None:
        per_row[index] = entry
        _absorb(entry)
        if api_budget is not None and not entry.get("replayed"):  # a replayed row's spend seeds the budget
            api_budget.add_usage(entry)
        # SAND-032: stream each finished row to the caller (main thread) so a
        # later cap abort / raise cannot drop rows whose GPU time was paid.
        if row_cb is not None:
            try:
                row_cb(entry)
            except Exception as exc:  # noqa: BLE001 — persistence must never break a run
                _log.warning("row_cb raised — per-doc evidence may be incomplete: %s", exc)
        # SAND-018: the isolated path used to be silent until the end — no
        # running checkpoint, no events — so a live run looked stalled.
        if progress_cb is not None:
            done = sum(1 for e in per_row if e is not None)
            try:
                progress_cb(done, len(rows), done - errors, errors)
            except Exception as exc:  # noqa: BLE001 — progress must never break a run
                _log.warning("progress_cb raised — live progress may stall: %s", exc)

    replayed: set[int] = set()
    for index, row in enumerate(rows):
        stored = (replay or {}).get((row or {}).get("id"))
        if replayable(stored):
            entry = {"id": row.get("id"), "pred": dict(stored["pred"]), "score": dict(stored.get("score") or {}),
                     "error": stored.get("error"), "offline_fallback": False, "replayed": True,
                     "latency_ms": stored.get("latency_ms"), **_replay_usage(stored)}
            window = _replay_window(stored)
            if window:
                entry["started_at_ns"], entry["finished_at_ns"] = window
            _record(index, entry)
            replayed.add(index)
    order = (sorted((i for i in range(len(rows)) if i not in replayed),
                    key=lambda i: -len(str((rows[i] or {}).get("doc_text") or "")))
             if longest_first else None)
    _run_rows_bounded(rows, workers=workers, run_one=_run_one, on_result=_record, guard=_guard, order=order,
                      skip=replayed)

    if rows and errors == len(rows):
        last_error = next((e for e in reversed(per_row) if e and e.get("error")), None)
        raise RuntimeError(
            f"live eval {task!r}: all {len(rows)} row(s) failed — the live path was not "
            f"exercised (last error: {(last_error or {}).get('error')})"
        )
    headline = _isolated_headline(per_row)
    mean = headline["exact_match"]
    scores = {"exact_match": mean, "n": len(rows), "offline_fallback": offline, "error_count": errors}
    scores.update({k: v for k, v in headline.items() if k != "exact_match"})
    # hub#56: decide overall_extraction_score presence from ANY row, not just
    # per_row[0] — the old check silently dropped the aggregate when the first
    # row lacked the key but later rows carried it.
    if any("overall_extraction_score" in (r.get("score") or {}) for r in per_row if r):
        scores["overall_extraction_score"] = mean
        scores["raw_dojo"]["overall_extraction_score"] = scores["raw_dojo"]["exact_match"]
        from mailroom_sandbox import scoring_hotfixes as sh

        fixed_rows = [(r or {}).get("score") for r in per_row]
        extraction = sh.aggregate_extraction(fixed_rows)
        raw_extraction = sh.aggregate_extraction(sh.raw_rows(fixed_rows))
        scores.update(extraction)
        scores["raw_dojo"].update({k: raw_extraction.get(k) for k in extraction})
        scores["scoring_hotfixes_changed"] = sorted({*scores.get("scoring_hotfixes_changed", []),
                                                     *sh.changed_keys(raw_extraction, extraction, extraction)})
    if task in scoring.SORTER_SUBCLASS_TASKS:
        _merge_subclass_headline(scores, scoring.sorter_subclass_scores(list(zip(rows, per_row))))
    schema_rows = [
        r.get("score") or {}
        for r in per_row
        if r and "parse_error" in (r.get("score") or {})
    ]
    if schema_rows:
        scores.update(scoring.aggregate_schema_adherence(schema_rows))
    from mailroom_sandbox.eval import human_review

    routed = human_review.for_isolated(task, [(e or {}).get("pred") for e in per_row if e and e.get("ok", True) and not e.get("error")])
    if routed is not None:
        scores.update(routed)
    if mean is not None:  # no truth anywhere: no score, not a zero (SHF-006)
        tracing.emit_langfuse_score("class_correct" if spec.observation == "classify-document" else "stage_completed", float(mean))
    tracing.flush_traces()
    if ScoreRecord is not None and mean is not None:  # no truth anywhere: nothing to emit (SHF-006)
        emit(
            ScoreRecord(
                metric="exact_match",
                value=float(mean),
                agent=task,
                run_id=experiment_name,
                metadata=dict(score_metadata or {}),
            )
        )
    completed = [e for e in per_row if e is not None]
    latencies = [float(e["latency_ms"]) for e in completed if e.get("latency_ms") is not None]
    prompt_tokens = sum(int(e.get("prompt_tokens") or 0) for e in completed)
    completion_tokens = sum(int(e.get("completion_tokens") or 0) for e in completed)
    wall_seconds = round(time.perf_counter() - budget_started, 3)
    logged_prompt, prompt_sha = _logged_prompt(prompt_version, task=task)
    record = experiment_log.new_record(
        experiment_name=experiment_name or f"sandbox_{task}",
        task=task,
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model or (activation.assignments[0][2] if activation.assignments else None),
        prompt_version=logged_prompt,
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures", f"agent-{task}"),
        session_id=session,
        trace_ids=tracing.last_trace_ids(),
    )
    if prompt_sha:
        record["prompt_sha256"] = prompt_sha
    stamp_prompt_provenance(record, logged_prompt, prompt_sha)
    # SAND-018: per-item serving metrics used to be absent on the isolated path.
    if latencies:
        record["e2e_latency_seconds"] = round(statistics.mean(latencies) / 1000.0, 6)
        record["latency_p50_seconds"] = round(statistics.median(latencies) / 1000.0, 6)
        record["latency_max_seconds"] = round(max(latencies) / 1000.0, 6)
        from mailroom_sandbox.job.metrics import p95

        record["latency_p95_seconds"] = round(p95(latencies) / 1000.0, 6)
    if prompt_tokens:
        record["prompt_tokens"] = prompt_tokens
    if completion_tokens:
        record["completion_tokens"] = completion_tokens
    if prompt_tokens or completion_tokens:
        record["total_tokens"] = prompt_tokens + completion_tokens
    record["wall_seconds"] = wall_seconds
    if int(concurrency) > 1:
        record["concurrency"] = int(concurrency)
    # SAND-018: carry the measured engine cold boot into the record so it lands
    # in reports/experiment_log.jsonl (the whole-run path appends its own copy).
    if cold_boot_seconds is not None:
        record["cold_boot_seconds"] = float(cold_boot_seconds)
    # SAND-018 cost accuracy: bill GPU-seconds over the whole warm interval
    # (cold boot + run wall), not just the per-call busy time — the reported
    # cost must match what Modal charges. Skipped for mock (no GPU spend).
    # #266: a run that never sat on a GPU (openrouter routes, a live ollama
    # isolated run) must not be billed a default class — record GPU cost only
    # for a declared fleet, an explicit engine GPU from the caller, or a
    # serving profile whose engine runs on GPUs (the `sandbox eval` CLI path
    # passes neither: its modal-vllm/vllm endpoint claims the default L4 class).
    if gpu is None and gpu_fleet is None and profile in ("modal-vllm", "vllm-local", "vllm-remote"):
        gpu = "L4"
    if not mock and (gpu_fleet or gpu):
        from mailroom_sandbox.job.metrics import estimate_gpu_cost_usd

        billed_seconds = wall_seconds + (
            float(cold_boot_seconds) if cold_boot_seconds is not None else 0.0
        )
        # Price the record like the cost cap: every warm route app when routed.
        gpu_cost = (
            _estimated_gpu_usd(billed_seconds, gpu=gpu, replicas=replicas, gpu_fleet=gpu_fleet)
            if gpu_fleet
            else estimate_gpu_cost_usd(billed_seconds, gpu=gpu, replicas=replicas)
        )
        record["replicas"] = max(1, int(replicas))
        if gpu_cost is not None:
            record["gpu_seconds"] = round(billed_seconds, 3)
            record["estimated_gpu_cost_usd"] = gpu_cost
            if len(completed) > 0:
                record["gpu_cost_per_document"] = round(gpu_cost / len(completed), 8)
    experiment_log.append(record)
    return {
        **plan,
        "scores": scores,
        "record": record,
        "rows": completed,
        "wall_seconds": wall_seconds,
    }


def run_sorter_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    sample_seed: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    prompt_version: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    agent_models: dict[str, str] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = load_manifest() if rows is None else rows
    if sample is not None:
        if sample <= 0:
            raise ValueError("sample must be positive")
        rows = _seeded_sample(rows, sample, sample_seed) if sample_seed is not None else rows[:sample]
    plan = {
        "task": "sorter",
        "n": len(rows),
        "mock": mock,
        "prompt_version": prompt_version,
        "profile": profile,
        "model": model,
        "fingerprint": dataset_fingerprint(rows),
    }
    if dry_run:
        return plan

    activation = activate(profile, model=model, prompt_variant=prompt_version, agent_models=agent_models)
    if prompt_version is None:
        # Unlocked eval: unnamed lineage agents run their frontrunner, not the vendored
        # prompt. A no-op under a locked run policy (the lock applied its own surface).
        from mailroom_sandbox.prompt_lineage import apply_eval_defaults

        apply_eval_defaults("sorter")
    predicted: list[str] = []
    expected: list[str] = []
    for row in rows:
        expected.append(row["expected_doc_class"])
        if mock:
            predicted.append(_classify_mock(row))
        else:
            result = _run_pipeline_doc(row, mock=False)
            doc_type = result.get("doc_type")
            if not doc_type:
                raise RuntimeError(
                    f"live pipeline returned no doc_type for row "
                    f"{row.get('id') or row.get('filename') or '?'} — refusing to "
                    f"score a dead live path as 'unknown' (ok=True would lie)"
                )
            predicted.append(doc_type)

    scores = scoring.score_classification(expected, predicted)
    if ScoreRecord is not None:
        emit(
            ScoreRecord(
                metric="exact_match",
                value=float(scores["exact_match"] or 0),
                agent="sorter",
                run_id=experiment_name,
            )
        )
        f1 = scores.get("f1_macro")
        if isinstance(f1, (int, float)):
            emit(
                ScoreRecord(
                    metric="f1_macro",
                    value=float(f1),
                    agent="sorter",
                    run_id=experiment_name,
                )
            )
    logged_prompt, prompt_sha = _logged_prompt(prompt_version, task="sorter")
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_sorter",
        task="sorter",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model or (activation.assignments[0][2] if activation.assignments else None),
        prompt_version=logged_prompt,
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures"),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "record": record}


def _extract_run_headline(scored_rows: Sequence[Mapping[str, Any]], n: int) -> dict[str, Any]:
    """Run headline of ``run_extract_eval``, dual reported (``docs/scoring-hotfixes.md``).

    ``overall_extraction_score`` is the mean row score over rows that produced one (0.0 when none),
    on the hotfixed rows and, under ``raw_dojo``, on each row's raw Dojo-pin value; the fixes that
    were on for any row are named, with the headline basis. ``n`` counts the rows and ``n_scored``
    the rows the mean averaged (a row whose every scored label SHF-015 dropped has no score), on
    both sides: the scored n belongs beside every metric (critical regression 1).
    """
    def scored(rows: Sequence[Mapping[str, Any] | None]) -> dict[str, Any]:
        vals = [float(r["overall_extraction_score"]) for r in rows
                if r and isinstance(r.get("overall_extraction_score"), (int, float))]
        return {"overall_extraction_score": sum(vals) / len(vals) if vals else 0.0, "n_scored": len(vals)}

    used = sorted({i for r in scored_rows for i in r.get("scoring_hotfixes") or []})
    dual = scoring_hotfixes.merge_dual(scored(scoring_hotfixes.raw_rows(scored_rows)), scored(scored_rows), used,
                                       keys=("overall_extraction_score", "n_scored"))
    return {**dual, "n": n, "headline_basis": scoring_hotfixes.headline_basis()}


def run_extract_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    sample_seed: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    agent_models: dict[str, str] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [r for r in (load_manifest() if rows is None else rows) if parse_expected_fields(r)]
    if sample is not None:
        if sample <= 0:
            raise ValueError("sample must be positive")
        rows = _seeded_sample(rows, sample, sample_seed) if sample_seed is not None else rows[:sample]
    plan = {"task": "extract", "n": len(rows), "mock": mock, "fingerprint": dataset_fingerprint(rows)}
    if dry_run:
        return plan
    activation = activate(profile, model=model, prompt_variant=prompt_version, agent_models=agent_models)
    if prompt_version is None:
        # Unlocked eval: unnamed lineage agents run their frontrunner, not the vendored
        # prompt. A no-op under a locked run policy (the lock applied its own surface).
        from mailroom_sandbox.prompt_lineage import apply_eval_defaults

        apply_eval_defaults("extract")
    schema_rows: list[dict[str, Any]] = []
    for row in rows:
        expected_fields = parse_expected_fields(row) or {}
        if mock:
            predicted_fields = dict(expected_fields)
        else:
            predicted_fields = _run_pipeline_doc(row, mock=False).get("extracted_data") or {}
        scored = scoring.score_extraction_row(
            row["expected_doc_class"],
            predicted_fields,
            expected_fields,
            # DMR-056: live corpus rows carry doc_text inline (no fixture file).
            doc_text=row.get("doc_text")
            or (fixture_file(row).read_text(encoding="utf-8") if fixture_file(row).is_file() else None),
            # Per-subclass scoring (sandbox #145): the row's GT subclass drives
            # the vendored corporate-record alignment (see scoring.py).
            expected_subclass=row.get("expected_subclass"),
            # SHF-010: the interim truth near-gold replaced is scored as raw, and the fix named.
            truth_overrides=row.get("truth_overrides"),
            overlay_fields=scoring_hotfixes.overlay_fields(row),
        )
        schema_rows.append(scored)
    scores = _extract_run_headline(schema_rows, len(rows))
    if schema_rows:
        scores.update(scoring.aggregate_schema_adherence(schema_rows))
    logged_prompt, prompt_sha = _logged_prompt(prompt_version, task="extract")
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_extract",
        task="extract",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=logged_prompt,
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures"),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores}


def run_chained_eval(**kwargs: Any) -> dict[str, Any]:
    if kwargs.get("dry_run"):
        return {"task": "chained", "dry_run": True, "sorter": run_sorter_eval(**kwargs)}
    sorter = run_sorter_eval(**kwargs)
    extract_kwargs = {k: v for k, v in kwargs.items() if k != "experiment_name"}
    extract = run_extract_eval(**extract_kwargs)
    sorter_exact = sorter.get("scores", {}).get("exact_match")
    extract_overall = extract.get("scores", {}).get("overall_extraction_score")
    if sorter_exact is None or extract_overall is None:
        raise RuntimeError(
            "chained eval: composite score cannot be derived — sorter "
            f"exact_match={sorter_exact!r}, extractor overall={extract_overall!r}; "
            "a 0-sentinel composite would silently hide the failed half"
        )
    composite = 0.25 * float(sorter_exact) + 0.75 * float(extract_overall)
    scores = {
        "sorter_exact": sorter_exact,
        "extractor_overall": extract_overall,
        "chained_composite": composite,
    }
    return {"task": "chained", "scores": scores, "sorter": sorter, "extract": extract}


def _seeded_sample(rows: list[dict[str, Any]], sample: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic seeded sample over a canonical sort (never first-N)."""
    import random

    ordered = sorted(rows, key=lambda r: str(r.get("id") or r.get("filename") or ""))
    if sample >= len(ordered):
        return ordered
    return random.Random(seed).sample(ordered, k=sample)


def run_local_vs_api_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    agent_models: dict[str, str] | None = None,
    from_log: bool = False,
    connected: bool = False,
    score_metadata: dict[str, Any] | None = None,
    group: str | int | None = None,
    dataset_revision: str | None = None,
) -> dict[str, Any]:
    """Compare local (Ollama/vLLM/…) vs API-key (OpenRouter) serving metrics.

    ``--mock`` uses committed fixture timings (no LLM, no ``OPENROUTER_API_KEY``).
    ``from_log`` partitions ``reports/experiment_log.jsonl`` by full identity
    (model / prompt / task / dataset) and compares every comparable local-vs-API
    group separately — the dojo refuses a leg that pools different identities
    (``identity_mixed``). With several groups the headline ``scores`` need one
    group: pass ``group`` (1-based index or unique label substring; CLI
    ``--group``); otherwise they stay empty and every group's scorecard is still
    emitted under ``<name>.g<n>``.

    Scorecards fail loudly: a group that cannot be emitted with honest
    provenance (no ``dataset_revision`` on its records, an incomparable leg)
    RAISES :class:`~mailroom_sandbox.eval.scoring.ScorecardEmissionError` and
    nothing is written or logged. ``dataset_revision`` (CLI
    ``--dataset-revision``) supplies the real 40-hex Hub sha the scored rows
    came from when the records carry none; it can fill a gap, never override a
    revision a record already has.
    """
    del sample, connected, agent_models  # unused; kept for eval kwargs parity
    from mailroom_sandbox.datasets import load_serving_fixtures

    headlines = scoring.serving_headlines()
    plan = {
        "task": "local_vs_api",
        "suite": "local_vs_api",
        "mock": mock,
        "from_log": from_log,
        "headlines": headlines,
        "requires_api_key": False,
        "fingerprint": "fixture-serving-v0",
    }
    if dry_run:
        return plan

    activation = activate(profile, model=model, prompt_variant=prompt_version)
    if from_log:
        compared = scoring.compare_from_records(experiment_log.load(), group=group)
        source = "experiment_log"
        local_rec = None
        api_rec = None
    else:
        fixtures = load_serving_fixtures()
        local_rec = fixtures.get("local") or {}
        api_rec = fixtures.get("api") or {}
        if mock:
            # Fixture path: never call OpenRouter even if a key is in the env.
            os.environ.setdefault("SANDBOX_RUN_MODE", "mock")
        compared = scoring.compare_local_vs_api(local_rec, api_rec)
        source = "fixtures"
        compared = {
            "local_n": 1,
            "api_n": 1,
            "unknown_n": 0,
            "pairs": [compared],
            "groups": [
                {
                    "group": 1,
                    "label": "fixtures",
                    "comparison": compared,
                    "incomparable_reason": compared.get("incomparable_reason"),
                }
            ],
            "unpaired": [],
            "selected_group": 1,
            "comparison": compared,
            "headlines": headlines,
            "table": compared.get("table") or [],
            "scorecard": compared.get("scorecard"),
            "cost": compared.get("cost"),
            "markdown": compared.get("markdown"),
        }

    comparison = compared.get("comparison") or {}
    metrics = comparison.get("metrics") or {}
    ttft = (metrics.get("ttft_seconds") or {}) if isinstance(metrics, dict) else {}
    scorecard = compared.get("scorecard") or comparison.get("scorecard") or {}
    cost = compared.get("cost") or comparison.get("cost") or {}
    table = compared.get("table") or comparison.get("table") or []
    markdown = compared.get("markdown") or comparison.get("markdown")
    scores = {
        "ttft_seconds_local": ttft.get("local"),
        "ttft_seconds_api": ttft.get("api"),
        "ttft_delta_local_minus_api": ttft.get("delta_local_minus_api"),
        "tokens_per_second_local": (metrics.get("tokens_per_second") or {}).get("local"),
        "tokens_per_second_api": (metrics.get("tokens_per_second") or {}).get("api"),
        "gpu_utilization_api": (metrics.get("gpu_utilization") or {}).get("api"),
        "quality": comparison.get("quality"),
        "honest_gaps": comparison.get("honest_gaps") or [],
        "missing": scorecard.get("missing") or [],
        "cost_local": (cost.get("local") or {}).get("estimated_cost_usd") if isinstance(cost, dict) else None,
        "cost_api": (cost.get("api") or {}).get("estimated_cost_usd") if isinstance(cost, dict) else None,
        "table_n": len(table),
        "local_n": compared.get("local_n"),
        "api_n": compared.get("api_n"),
        "n": (compared.get("local_n") or 0) + (compared.get("api_n") or 0),
    }
    provenance = None
    if dataset_revision:
        rev = validate_dataset_revision(dataset_revision)
        provenance = {"local": {"dataset_revision": rev}, "api": {"dataset_revision": rev}}
    scorecards = scoring.emit_group_scorecards(
        compared,
        run_id=experiment_name or "sandbox_local_vs_api",
        metadata=score_metadata,
        provenance=provenance,
    )
    scores["scorecards_emitted"] = len(scorecards)
    scores["groups_n"] = len(compared.get("groups") or [])
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_local_vs_api",
        task="local_vs_api",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=_logged_prompt(prompt_version, task="local_vs_api")[0],
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=scores["n"],
        scores=scores,
        serving_kind="local",
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-serving", "local-vs-api"),
        local_vs_api=compared,
        scorecards=scorecards,
        serving_markdown=markdown,
        source=source,
    )
    experiment_log.append(record)
    return {
        **plan,
        "scores": scores,
        "comparison": compared,
        "scorecards": scorecards,
        "record": record,
    }


def run_sorter_vs_modernbert_eval(
    *,
    sample: int | None = None,
    mock: bool = True,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    agent_models: dict[str, str] | None = None,
    from_log: bool = False,
    connected: bool = False,
    sorter_record: dict[str, Any] | None = None,
    modernbert_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare LLM sorter vs trained ModernBERT on accuracy + cost/latency.

    ``--mock`` uses committed fixtures (no mailroom-ml import, no GPU).
    Live (``mock=False``) loads ModernBERT from the local mailroom-ml feeder
    (``MAILROOM_ML_SRC`` / ``MODERNBERT_MODEL_PATH``) via ``eval_modernbert.py``
    and pairs it with fixtures' sorter side unless ``sorter_record`` /
    ``from_log`` supplies a measured sorter record.
    """
    del connected, agent_models  # parity with other eval kwargs
    mb_sample = 50 if sample is None else int(sample)
    from mailroom_sandbox.datasets import load_sorter_vs_modernbert_fixtures
    from mailroom_sandbox.job.metrics import compare_sorter_vs_modernbert

    plan = {
        "task": "sorter_vs_modernbert",
        "suite": "sorter_vs_modernbert",
        "mock": mock,
        "from_log": from_log,
        "fingerprint": "fixture-sorter-vs-modernbert-v0",
        "requires_api_key": False,
        "requires_mailroom_ml": not mock,
    }
    if dry_run:
        return plan

    activation = activate(profile, model=model, prompt_variant=prompt_version)
    source = "fixtures"
    if sorter_record is not None and modernbert_record is not None:
        left, right = sorter_record, modernbert_record
        source = "records"
    elif from_log:
        left, right = _sorter_modernbert_from_log(experiment_log.load())
        source = "experiment_log"
        if left is None or right is None:
            raise RuntimeError(
                "experiment_log has no comparable sorter + modernbert records "
                "(need one with classifier/serving_kind llm_sorter|sorter and "
                "one with modernbert); use --mock fixtures or pass records"
            )
    elif mock:
        fixtures = load_sorter_vs_modernbert_fixtures()
        left = fixtures.get("sorter") or {}
        right = fixtures.get("modernbert") or {}
        if not left or not right:
            raise RuntimeError(
                "sorter_vs_modernbert fixtures missing both sides — "
                "expected data/fixtures/serving/sorter_vs_modernbert.json"
            )
        os.environ.setdefault("SANDBOX_RUN_MODE", "mock")
    else:
        # Live ModernBERT via mailroom-ml feeder; sorter from fixture or log.
        from mailroom_sandbox.modernbert import (
            feeder_status,
            run_modernbert_eval,
            serving_record_from_eval,
        )

        status = feeder_status()
        if not status.get("ok"):
            raise RuntimeError(
                "ModernBERT feeder incomplete — "
                f"{status.get('hint')} (status={status})"
            )
        report = run_modernbert_eval(sample=mb_sample, seed=42)
        right = serving_record_from_eval(report)
        left = sorter_record
        if left is None:
            left, _ = _sorter_modernbert_from_log(experiment_log.load())
        if left is None:
            fixtures = load_sorter_vs_modernbert_fixtures()
            left = fixtures.get("sorter") or {}
            source = "modernbert-live+sorter-fixture"
            _log.warning(
                "no measured sorter record in experiment_log — pairing live "
                "ModernBERT with fixture sorter side (accuracy delta is not "
                "apples-to-apples until a live sorter run exists)"
            )
        else:
            source = "modernbert-live+sorter-log"
        plan["fingerprint"] = right.get("dataset_fingerprint") or plan["fingerprint"]
        plan["modernbert_checkpoint"] = right.get("checkpoint")

    compared = compare_sorter_vs_modernbert(left, right)
    quality = compared.get("quality") or {}
    cost = compared.get("cost") or {}
    latency = compared.get("latency") or {}
    scores = {
        "accuracy_sorter": (quality.get("accuracy") or {}).get("sorter"),
        "accuracy_modernbert": (quality.get("accuracy") or {}).get("modernbert"),
        "f1_macro_sorter": (quality.get("f1_macro") or {}).get("sorter"),
        "f1_macro_modernbert": (quality.get("f1_macro") or {}).get("modernbert"),
        "e2e_sorter": latency.get("sorter_e2e_s"),
        "e2e_modernbert": latency.get("modernbert_e2e_s"),
        "cost_per_doc_sorter": cost.get("sorter_cost_per_document"),
        "cost_per_doc_modernbert": cost.get("modernbert_cost_per_document"),
        "honest_gaps": compared.get("honest_gaps") or [],
        "n": int(left.get("n") or 0) + int(right.get("n") or 0),
    }
    logged_prompt, prompt_sha = _logged_prompt(prompt_version, task="sorter_vs_modernbert")
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_sorter_vs_modernbert",
        task="sorter_vs_modernbert",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=logged_prompt,
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=scores["n"],
        scores=scores,
        serving_kind="local",
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-serving", "sorter-vs-modernbert"),
        sorter_vs_modernbert=compared,
        serving_markdown=compared.get("markdown"),
        source=source,
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "comparison": compared, "record": record}


def _sorter_modernbert_from_log(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick the latest sorter + modernbert rows from an experiment log."""
    sorter: dict[str, Any] | None = None
    modernbert: dict[str, Any] | None = None
    for rec in records:
        kind = str(rec.get("classifier") or rec.get("serving_kind") or "").lower()
        task = str(rec.get("task") or "").lower()
        if kind in {"modernbert", "bert_intake", "onnx-cpu"} or "modernbert" in kind:
            modernbert = rec
        elif task == "sorter" or kind in {"llm_sorter", "modal", "local", "api"}:
            if task in {"sorter", ""} or rec.get("scores"):
                sorter = rec
    return sorter, modernbert


def _score_pipeline_extraction(row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """Score one connected-pipeline document's extraction; None when the row has no field GT."""
    expected_fields = parse_expected_fields(row) or {}
    if not expected_fields:
        return None
    return scoring.score_extraction_row(
        row["expected_doc_class"],
        result.get("extracted_data") or {},
        expected_fields,
        # DMR-056: live corpus rows carry doc_text inline; fixture rows
        # read from disk (subdir guard — live rows have no subdir key).
        doc_text=row.get("doc_text")
        or (
            fixture_file(row).read_text(encoding="utf-8")
            if "subdir" in row and fixture_file(row).is_file()
            else None
        ),
        # Per-subclass scoring (sandbox #145): the row's GT subclass
        # drives the vendored corporate-record alignment.
        expected_subclass=row.get("expected_subclass"),
        truth_overrides=row.get("truth_overrides"),
        # SHF-015: the overlay markers say which labels are reviewed, never dropped as stale Hub labels.
        overlay_fields=scoring_hotfixes.overlay_fields(row),
    )


def pipeline_item_score(row: Mapping[str, Any], result: Mapping[str, Any],
                        scored: Mapping[str, Any] | None) -> dict[str, Any]:
    """The per-document ``score`` a pipeline run persists in ``items.jsonl``.

    ``scored`` is ``_score_pipeline_extraction(row, result)`` (None when the row has no field
    truth or the run was not connected). ``sandbox rescore`` calls this too, so a re-scored item
    has exactly the keys and meaning of one scored during the run.
    """
    stage = str(result.get("stage") or "unknown")
    score: dict[str, Any] = {"match": float(result.get("doc_type") == row.get("expected_doc_class")),
                             "class_correct": float(result.get("doc_type") == row.get("expected_doc_class")),
                             "stage_correct": float(stage == str(row.get("expected_stage") or "archived"))}
    # The same scorer output the run-level aggregate uses, so a report can read it per document.
    score.update({k: v for k, v in (scored or {}).items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool)})
    # SHF-012: the document's subclass outcome, hotfixed and raw (docs/scoring-hotfixes.md).
    # SHF-013: a reviewed subclass correction replaces the Hub subclass on the hotfixed side.
    sub = scoring.subclass_correct(row.get("expected_doc_class"), row.get("expected_subclass"),
                                   result.get("doc_type"), scoring.predicted_subclass(result),
                                   doc_id=row.get("id"))
    fixes = set((scored or {}).get("scoring_hotfixes") or [])
    if sub is not None:
        score["subclass_correct"], score["raw_dojo_subclass_correct"] = sub[1], sub[0]
        if sub[0] != sub[1]:
            fixes.add("SHF-012")
        if scoring.corrected_subclass_truth(row.get("id"), row.get("expected_doc_class"),
                                            row.get("expected_subclass")) is not None:
            score["subclass_corrected"] = True
            fixes.add("SHF-013")
    # Per-document dual provenance (docs/scoring-hotfixes.md): the raw Dojo-pin extraction values
    # and the fixes that moved this document's scores, so a report can show both sides per item.
    # SHF-015: the Hub labels dropped as stale, by field and reason, so items.jsonl says which
    # fields the headline did not score (absent when none were dropped).
    stale = (scored or {}).get("stale_hub_labels")
    if stale:
        score["stale_hub_labels"] = dict(stale)
    raw_side = {k: v for k, v in ((scored or {}).get("raw_dojo") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if raw_side:
        score["raw_dojo"] = raw_side
    score["scoring_hotfixes"] = sorted(fixes)
    # The pain-point penalty points of this document (eval/pain_points.py), headline side.
    from mailroom_sandbox.eval import pain_points

    score.update(pain_points.item_points(row, result, scored, subclass_ok=None if sub is None else bool(sub[1])))
    # Keep the parse facts: whole-run jobs fail when every answer is unparseable.
    score.update({k: scored[k] for k in ("parse_error", "schema_valid") if k in (scored or {})})
    return score


def _pipeline_extraction_scores(extraction_rows: Sequence[Mapping[str, Any] | None],
                                class_ok: Sequence[bool]) -> dict[str, Any]:
    """Run-level extraction headline of a pipeline run, dual reported (``docs/scoring-hotfixes.md``).

    ``extraction_overall`` is the mean per-document Dojo extraction score; ``extraction_f1_micro`` /
    ``extraction_f1_mean`` the field F1 over events and per document; ``hallucination_rate`` the
    share of documented-absent fields a value was stated on (SHF-001).
    ``extraction_overall_correct_class`` restricts the mean to documents the sorter routed to
    their true class, so a misrouted document's partial credit is never read as specialist quality.
    ``extraction_overall_n_scored`` and ``extraction_overall_correct_class_n_scored`` are the number
    of documents each mean averages (0 when the mean is None), on the raw side too: a document with
    no score (parked, or every scored label dropped by SHF-015) is not a 0 in the mean, so the count
    is what shows the denominator (critical regression 1, ``docs/critical-regressions.md``).
    """
    from mailroom_sandbox import scoring_hotfixes as sh

    def scored(rows: Sequence[Mapping[str, Any] | None], mask: Sequence[bool] | None = None) -> list[float]:
        return [float(r["overall_extraction_score"]) for i, r in enumerate(rows)
                if r and isinstance(r.get("overall_extraction_score"), (int, float))
                and (mask is None or mask[i])]

    def overall(rows: Sequence[Mapping[str, Any] | None], mask: Sequence[bool] | None = None) -> dict[str, Any]:
        vals = scored(rows, mask)
        suffix = "" if mask is None else "_correct_class"
        return {f"extraction_overall{suffix}": scoring.mean_or_zero(vals) if vals else None,
                f"extraction_overall{suffix}_n_scored": len(vals)}

    raw = sh.raw_rows(extraction_rows)
    fixed_part = {**overall(extraction_rows), **overall(extraction_rows, class_ok),
                  **sh.aggregate_extraction(extraction_rows)}
    raw_part = {**overall(raw), **overall(raw, class_ok), **sh.aggregate_extraction(raw)}
    used = sorted({i for r in extraction_rows if r for i in r.get("scoring_hotfixes") or []})
    keys = tuple(dict.fromkeys([*fixed_part, *raw_part]))
    return sh.merge_dual(raw_part, fixed_part, used, keys=keys)


def run_pipeline_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    sample_seed: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    agent_models: dict[str, str] | None = None,
    connected: bool = True,
    rows: list[dict[str, Any]] | None = None,
    row_cb=None,
    progress_cb=None,
    node_cb=None,
    read_cb=None,
    text_cb=None,
    max_wall_seconds: int | None = None,
    cost_cap_usd: float | None = None,
    api_budget: Any = None,
    gpu: str | None = None,
    replicas: int = 1,
    gpu_fleet: list[tuple[str, int]] | None = None,
    concurrency: int = 1,
    replay: Mapping[Any, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    # ``replay`` maps a row id to the item an earlier attempt of this run persisted. A replayable
    # document is scored from that stored answer with no model call and no new spend (a resume).
    # DMR-056: rows=None keeps the fixture manifest default; the sandbox job
    # whole-run path passes the LOCKED live dataset rows instead.
    # ``concurrency`` (the job's ``job.concurrency``) runs that many documents at once.
    from mailroom_sandbox.job import usage_capture

    rows = load_manifest() if rows is None else rows
    if sample is not None:
        if sample <= 0:
            raise ValueError("sample must be positive")
        rows = _seeded_sample(rows, sample, sample_seed) if sample_seed is not None else rows[:sample]
    plan = {
        "task": "pipeline",
        "n": len(rows),
        "mock": mock,
        "fingerprint": dataset_fingerprint(rows),
        "connected": connected,
    }
    if dry_run:
        return plan
    os.environ["SANDBOX_RUN_MODE"] = "mock" if mock else "local"
    activation = activate(
        profile, model=model, prompt_variant=prompt_version, agent_models=agent_models
    )
    if prompt_version is None:
        # Unlocked eval: unnamed lineage agents run their frontrunner, not the vendored
        # prompt. A no-op under a locked run policy (the lock applied its own surface).
        from mailroom_sandbox.prompt_lineage import apply_eval_defaults

        apply_eval_defaults("pipeline")
    session = tracing.session_id_for("pipeline")
    import threading
    import time
    started = time.monotonic()
    # Mock documents patch ``get_llm`` process-wide (unittest.mock), so two at once would
    # answer from each other's fake client; only live runs fan out.
    workers = 1 if mock else max(1, min(int(concurrency or 1), len(rows) or 1))
    if node_cb is not None and workers > 1:
        # Concurrent documents report nodes from worker threads; keep each record's write whole.
        node_lock, raw_node_cb = threading.Lock(), node_cb

        def node_cb(record: dict[str, Any]) -> None:  # noqa: F811 — locked wrapper of the caller's sink
            with node_lock:
                raw_node_cb(record)

    if read_cb is not None and workers > 1:
        # Same for read-range records and the working-text writer.
        read_lock, raw_read_cb, raw_text_cb = threading.Lock(), read_cb, text_cb

        def read_cb(record: dict[str, Any]) -> None:  # noqa: F811 — locked wrapper of the caller's sink
            with read_lock:
                raw_read_cb(record)

        if raw_text_cb is not None:
            def text_cb(doc: str, text: str) -> None:  # noqa: F811 — locked wrapper of the caller's sink
                with read_lock:
                    raw_text_cb(doc, text)

    def _check_caps(in_flight: int = 0) -> None:
        """Refuse to START another document once a wall, GPU or API cap is reached.

        ``in_flight`` documents are running but not yet billed into the total; the API check
        counts each at the mean finished-document cost so concurrent starts cannot overshoot.
        """
        if mock:
            return
        elapsed = time.monotonic() - started
        if max_wall_seconds is not None and elapsed >= max_wall_seconds:
            raise RuntimeError("pipeline wall-time cap exceeded before next document")
        cap_gpu = _cap_gpu(gpu, gpu_fleet, profile)
        if cost_cap_usd is not None and cap_gpu:
            if _estimated_gpu_usd(elapsed, gpu=cap_gpu, replicas=replicas, gpu_fleet=gpu_fleet) >= cost_cap_usd:
                raise RuntimeError("pipeline estimated GPU cost cap exceeded before next document")
        if api_budget is not None:
            api_budget.check("pipeline API spend cap reached before next document: ", in_flight=in_flight)

    def _process(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float, tuple[int, int]]:
        """Run one document: (result, token usage, latency ms, (start, end) epoch ns). Safe on a worker thread.

        The epoch window is taken around the document's own execution, so a span built from it
        does not include the wait before the main thread scores and reports the document.

        Usage is per thread (``pipeline.limits`` keeps a ContextVar that ``reset_usage`` replaces)
        and node tracking is per thread (a ContextVar tracker), so documents never share either.
        """
        before = time.monotonic()
        started_ns = time.time_ns()
        read_stats: dict[str, Any] | None = None
        with ExitStack() as nodes:
            if read_cb is not None:
                # Read recording is independent of node tracking: a caller may supply read_cb
                # alone, and records without a node are attributed to no graph node.
                from mailroom_sandbox.job import read_ranges

                read_stats = {}
                nodes.enter_context(
                    read_ranges.document(str(row.get("id")), row.get("doc_text"), read_cb, text_cb)
                )
            if node_cb is not None:
                # SAND-076: report each graph node as it starts and ends.
                from mailroom_sandbox.job.node_trace import track_nodes

                models = {agent: model for agent, _provider, model in activation.assignments}
                models.update(activation.agent_models)
                from mailroom_sandbox.runtime import active_reviewer

                reviewer = active_reviewer() or {}
                if reviewer.get("backend") in {"decisions", "jev"} and reviewer.get("model"):
                    # The review node is answered by the decision backend, not the sorter_reviewer chat route.
                    models["sorter_reviewer"] = reviewer["model"]
                nodes.enter_context(track_nodes(str(row.get("id")), node_cb, models=models))
            usage_capture.reset_usage()
            try:
                result = _run_pipeline_doc(row, mock=mock, session_id=session, experiment_name=experiment_name)
            except Exception as exc:
                # SAND-089: calls made before the failure were billed; hand them to the job runner,
                # which records them for a resumed run's budget (counted in _count_failed).
                failed_usage = usage_capture.usage_from_pipeline()
                if failed_usage:
                    try:
                        exc.sandbox_failed_usage = {"item_id": row.get("id"), **failed_usage}
                    except (AttributeError, TypeError):
                        pass
                raise
            if read_stats is not None:
                read_stats = read_ranges.stats()  # still inside the document scope
        latency_ms = (time.monotonic() - before) * 1000
        usage = usage_capture.usage_from_pipeline()
        calls = usage_capture.call_usage_from_pipeline()
        if calls:
            usage = {**usage, "call_usage": calls}  # per-call tokens: a tiered price applies to each call
        by_agent = usage_capture.usage_by_agent_from_pipeline()
        if by_agent:
            usage = {**usage, "usage_by_agent": by_agent}  # per-agent split, persisted for role-level cost
        if read_stats is not None:
            usage = {**usage, "reads": read_stats}  # persisted by the job runner as the item's ``reads``
        return result, usage, latency_ms, (started_ns, time.time_ns())

    def _count_failed(exc: BaseException) -> None:
        """Count a failed document's billed calls against the API budget (main thread)."""
        if api_budget is not None:
            failed = getattr(exc, "sandbox_failed_usage", None) or {}
            api_budget.add_usage({k: v for k, v in failed.items() if k != "item_id"})

    by_index: dict[int, dict[str, Any]] = {}
    scored_by_index: dict[int, dict[str, Any] | None] = {}

    def _record(index: int, result: dict[str, Any], doc_usage: dict[str, Any], latency_ms: float,
                window: tuple[int, int] | None = None, replayed: bool = False) -> None:
        """Account, score and report one finished document (main thread only).

        A ``replayed`` document was billed by an earlier attempt, whose spend already seeds the
        budget: it is not added again (that would also lower the mean finished-document cost).
        """
        row = rows[index]
        if api_budget is not None and not replayed:
            api_budget.add_usage(doc_usage)
        if result.get("stage") == "failed" and not result.get("error"):
            # A run the pipeline aborted is a failed document, not a finished one.
            result = {**result, "error": result.get("escalation_reason") or "pipeline failed"}
        by_index[index] = result
        scored = _score_pipeline_extraction(row, result) if connected else None
        scored_by_index[index] = scored
        if row_cb:
            score = pipeline_item_score(row, result, scored)
            timing = {"started_at_ns": window[0], "finished_at_ns": window[1]} if window else {}
            row_cb({"id": row.get("id"), "pred": result, "error": result.get("error"), "score": score,
                    "latency_ms": latency_ms, **timing, **doc_usage, **({"replayed": True} if replayed else {})})
        if progress_cb:
            errors = sum(bool(item.get("error")) for item in by_index.values())
            progress_cb(len(by_index), len(rows), len(by_index) - errors, errors)

    for index, row in enumerate(rows):
        stored = (replay or {}).get(row.get("id"))
        if replayable(stored):
            _record(index, dict(stored["pred"]), _replay_usage(stored), float(stored.get("latency_ms") or 0.0),
                    _replay_window(stored), replayed=True)
    pending = [index for index in range(len(rows)) if index not in by_index]
    if workers == 1:
        for index in pending:
            row = rows[index]
            _check_caps()
            try:
                outcome = _process(row)
            except Exception as exc:
                _count_failed(exc)
                raise
            _record(index, *outcome)
    else:
        # job.concurrency documents in flight at once. Caps are checked before each new document
        # starts; after the first failure no new document starts, the in-flight ones finish and
        # are recorded (they were billed), then the first error is raised.
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        queue = iter(pending)
        first_error: BaseException | None = None
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pipeline-doc") as pool:
            futures: dict[Any, int] = {}

            def _fill() -> None:
                while len(futures) < workers:
                    index = next(queue, None)
                    if index is None:
                        return
                    _check_caps(in_flight=len(futures))
                    futures[pool.submit(_process, rows[index])] = index

            try:
                _fill()
            except Exception as exc:  # noqa: BLE001 — a cap reached before the first wave
                first_error = exc
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    index = futures.pop(future)
                    try:
                        outcome = future.result()
                    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised below
                        _count_failed(exc)
                        first_error = first_error or exc
                        continue
                    _record(index, *outcome)
                if first_error is None:
                    try:
                        _fill()
                    except Exception as exc:  # noqa: BLE001 — a cap reached mid-run
                        first_error = exc
        if first_error is not None:
            raise first_error
    results = [by_index[index] for index in range(len(rows))]
    extraction_rows: list[dict[str, Any] | None] = [scored_by_index[index] for index in range(len(rows))]
    expected = [r["expected_doc_class"] for r in rows]
    predicted: list[str] = []
    for row, result in zip(rows, results):
        doc_type = result.get("doc_type")
        if not mock and not doc_type and not result.get("error"):
            raise RuntimeError(
                f"live pipeline returned no doc_type for row "
                f"{row.get('id') or row.get('filename') or '?'} — refusing to "
                f"score a dead live path as 'unknown'"
            )
        predicted.append(doc_type or "unknown")
    if not mock and results and not any(r.get("doc_type") for r in results):
        raise RuntimeError("live pipeline returned no doc_type for any row — refusing to score a dead live path")
    class_scores = scoring.score_classification(expected, predicted)
    stage_expected = [str(r.get("expected_stage") or "archived") for r in rows]
    stage_predicted = [str(r.get("stage") or "unknown") for r in results]
    stage_scores = scoring.score_stage(stage_expected, stage_predicted)
    schema_rows: list[dict[str, Any]] = [scored for scored in extraction_rows if scored is not None]
    extraction = _pipeline_extraction_scores(extraction_rows, [e == p for e, p in zip(expected, predicted)])
    subclass_scores = scoring.score_subclass(
        expected, [r.get("expected_subclass") for r in rows], predicted,
        [scoring.predicted_subclass(r) for r in results], doc_ids=[r.get("id") for r in rows])
    routing_expected = ["review" if s == "review" else "continue" for s in stage_expected]
    routing_predicted = ["review" if s == "review" else "continue" for s in stage_predicted]
    routing = scoring.score_classification(routing_expected, routing_predicted)
    scores = {
        **class_scores,
        "class_correct": class_scores.get("exact_match"),
        "stage_correct": stage_scores.get("stage_correct"),
        "extraction_overall": extraction["extraction_overall"],
        "routing_accuracy": routing.get("exact_match"),
        "connected": connected,
        **{k: v for k, v in extraction.items() if k != "extraction_overall"},
        **subclass_scores,
    }
    from mailroom_sandbox import scoring_hotfixes as _sh

    scores["headline_basis"] = _sh.headline_basis()
    from mailroom_sandbox.eval import human_review

    scores.update(human_review.for_pipeline(results))
    # The incorrect-archive metric beside the review metric (eval/archive_correctness.py):
    # per-class wrong/incomplete archives with reasons, gate semantics (quality bar 0.90).
    from mailroom_sandbox.eval import archive_correctness

    scores.update(archive_correctness.for_pipeline(rows, results, extraction_rows=extraction_rows))
    # The client pain-point composites (eval/pain_points.py): penalty points per document for
    # classification and extraction, a needless human review the worst outcome on both.
    from mailroom_sandbox.eval import pain_points

    scores.update(pain_points.for_pipeline(rows, results, extraction_rows))
    if schema_rows:
        scores.update(scoring.aggregate_schema_adherence(schema_rows))
    tracing.emit_langfuse_score("class_correct", float(scores["class_correct"] or 0))
    tracing.emit_langfuse_score("stage_correct", float(scores["stage_correct"] or 0))
    if scores["extraction_overall"] is not None:
        tracing.emit_langfuse_score("extraction_overall_score", float(scores["extraction_overall"]))
    tracing.flush_traces()
    logged_prompt, prompt_sha = _logged_prompt(prompt_version, task="pipeline")
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_pipeline",
        task="pipeline",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=logged_prompt,
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        docs=results,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures"),
        session_id=session,
        trace_ids=tracing.last_trace_ids(),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "docs": results}


def _langchain_mock_patches(expect: dict[str, Any]) -> list:
    """Mock patches for mailroom's vendored LangChain agents.

    The vendored agents build their own ``ChatOpenAI`` and bypass
    ``llm.client.get_llm``, so — mirroring mailroom's own test suite — the
    ``langchain_agents.base_agent.BaseAgent.llm`` property must be patched
    with the canned ``FakeLangChainLLM`` shipped alongside. The sandbox
    keeps its marker-driven payload table by overriding ``_run`` to answer
    through ``fake_structured_payload``. Returns [] when mailroom v0.5.x
    (no langchain_agents) is resolved instead.
    """
    try:
        import langchain_agents.base_agent as lc_base
        from langchain_agents.mock import FakeLangChainLLM, user_text_from_messages
    except Exception as exc:
        _log.warning(
            "langchain_agents mock surface unavailable — a --mock run against the "
            "vendored langchain stack may proceed WITHOUT its LLM patches (the "
            "agent would attempt a real provider call)",
            exc_info=exc,
        )
        return []

    class _SandboxFakeLLM(FakeLangChainLLM):
        def _run(self, messages):
            self.calls += 1
            text = user_text_from_messages(messages)
            parsed = fake_structured_payload(text, expect)
            return self._make_message(parsed)

    fake = _SandboxFakeLLM()
    return [patch.object(lc_base.BaseAgent, "llm", new=lambda self: fake)]


_TEXT_SUFFIXES = (".txt", ".md", ".json", ".csv", ".eml", ".html", ".htm")


def _doc_source_name(row: dict[str, Any]) -> str:
    """Filename for a row's document in the inbox (fixture or prepared row)."""
    filename = str(row.get("filename") or "").strip()
    if filename:
        return Path(filename).name
    ident = str(row.get("id") or "doc").strip() or "doc"
    return f"{ident}.txt"


def _wait_for_inbox_room(target: Path, name: str) -> None:
    """Backpressure: hold a write into the pipeline's own inbox while that inbox is full.

    A full inbox means a watcher sharing this base dir is behind; the document waits here until
    it drains (``mailroom_sandbox.backpressure``). A write anywhere else, such as the API eval's
    staging directory, is not held. The wait is bounded by ``backpressure.intake_timeout()``, so a
    stalled inbox cannot hold a run past its ``job.max_wall_seconds``, which is checked only
    between documents. Past it the document raises ``BackpressureTimeout`` like any document
    error: a job run records an error row for it and goes on (rerun on resume), and a direct
    ``run_pipeline_eval`` call stops after its in-flight documents, as it does on any failure.
    """
    try:
        from pipeline.bins import inbox_dir  # type: ignore

        is_inbox = target.resolve() == inbox_dir().resolve()
    except Exception:  # noqa: BLE001 — no vendored pipeline: no shared inbox to protect
        return
    if is_inbox:
        from mailroom_sandbox import backpressure

        backpressure.wait_for_capacity(("inbox",), timeout=backpressure.intake_timeout(),
                                       what=f"pipeline intake of {name}")


def _materialize_row(row: dict[str, Any], inbox: Path) -> Path:
    """Place the row's document in the inbox and return the queued path.

    Fixture rows resolve to their file on disk (copied in); prepared corpus
    rows carry ``doc_text`` inline and are written as a text document. A row
    with neither raises — a live run never scores a missing document.
    """
    import shutil

    queued = inbox / _doc_source_name(row)
    _wait_for_inbox_room(inbox, queued.name)
    doc_text = row.get("doc_text") or row.get("text")
    if doc_text:
        if queued.suffix.lower() not in _TEXT_SUFFIXES:
            queued = queued.with_suffix(".txt")
        queued.write_text(str(doc_text), encoding="utf-8")
        return queued
    source = fixture_file(row)  # KeyError when subdir/filename are absent — live-or-loud
    shutil.copyfile(source, queued)
    return queued


def _run_pipeline_doc(row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """:func:`_run_pipeline_doc_once` inside one document scope of the API call guard.

    When the guard refused a call (the run's API cap or the document's call ceiling), the graph
    aborted the document through its run-limit path; that abort is not a pipeline outcome, so the
    document raises and becomes an error row instead of a scored one (rb1 R01 smoke).
    """
    from mailroom_sandbox.job import call_guard

    with call_guard.document() as scope:
        result = _run_pipeline_doc_once(row, **kwargs)
    if scope["refused"]:
        raise RuntimeError(f"document stopped by the API call guard ({scope['calls']} calls): {scope['refused']}")
    if scope.get("judge_reasks"):
        # HF-002 / HF-013: a judge answer that did not parse was asked once more. Present only on a
        # document where that happened: {judge: {"asked": n, "recovered": m, "parked": p}}, counts only.
        result = {**result, "judge_reasks": scope["judge_reasks"]}
    # Phase 2 governor marks, present only when they happened (critical regression 22: a routing
    # change that moves a document between review and the archive carries a mark).
    for key in ("governor_stop", "duplicate_of"):
        if scope.get(key):
            result = {**result, key: scope[key]}
    skipped = int(scope["governor"]["skipped_classify_retries"])
    if skipped:
        result = {**result, "governor_skips": {"classify_retry": skipped}}
    return result


def _gate_fired_without_prep(result: Mapping[str, Any]) -> bool:
    """Whether the vendored intake gate would have fired for this state, read from its flags (no text kept)."""
    try:
        from agents.intake import llm_intake_enabled, should_llm_intake  # type: ignore

        return bool(llm_intake_enabled() and should_llm_intake(str(result.get("doc_text") or ""),
                                                               {"messy": bool(result.get("intake_messy"))}))
    except Exception:  # noqa: BLE001 — a summary never fails a document
        return False


def intake_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """What the intake node did for one document, with no document text (the item record's ``intake``).

    Built from the graph state's ``intake_prep``. ``gate_fired`` is True when a prep is present, or when
    the gate (``should_llm_intake`` on the state's ``intake_messy`` flag and text length) would have
    fired although the call raised and the node left no prep; that case is ``read_failed`` too.
    ``read_failed`` means it ran and yielded no triage, so no
    prior reached the sorter. ``prior_sent`` is whether the intake prior block is non-empty (the
    ModernBERT prior, a separate channel, is not counted). ``clean_refused`` is HF-003's or HF-016's refusal. ``windows`` is None when the prep's count is malformed.
    """
    prep = result.get("intake_prep")
    if not isinstance(prep, Mapping) and _gate_fired_without_prep(result):
        # intake_node catches a failed call (a timeout, HF-010's WholeDocumentTooLong) and leaves no prep.
        return {"gate_fired": True, "windows": 0, "triage_class": None, "triage_confidence": None,
                "prior_sent": False, "clean_refused": False, "read_failed": True}
    if not isinstance(prep, Mapping):
        return {"gate_fired": False, "windows": 0, "triage_class": None, "triage_confidence": None,
                "prior_sent": False, "clean_refused": False, "read_failed": False}
    triage = prep.get("triage") if isinstance(prep.get("triage"), Mapping) else {}
    confidence = triage.get("confidence")
    try:
        from agents.intake import format_intake_prior  # type: ignore

        prior_sent = bool(format_intake_prior(dict(prep)))
    except Exception:  # noqa: BLE001 — a summary never fails a document
        prior_sent = bool(triage)
    try:
        windows: int | None = int(prep.get("windows") or 0)
    except (TypeError, ValueError, OverflowError):  # a summary never fails a document
        windows = None
    return {
        "gate_fired": True,
        "windows": windows,
        "triage_class": (str(triage["primary_doc_class"]) if triage.get("primary_doc_class") else None),
        "triage_confidence": (float(confidence) if isinstance(confidence, (int, float))
                              and not isinstance(confidence, bool) else None),
        "prior_sent": prior_sent,
        "clean_refused": bool(prep.get("clean_refused")),
        "read_failed": not triage,
    }


def _run_pipeline_doc_once(
    row: dict[str, Any],
    *,
    mock: bool,
    session_id: str | None = None,
    experiment_name: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one row through mailroom ``run_pipeline`` when available.

    Rows may be fixture rows (file on disk) or prepared corpus rows
    (``doc_text`` inline — the DMR-027 job path); both are materialized into
    the inbox before the run. When the mailroom import fails a LIVE run
    raises (live-or-loud, DMR-044) instead of returning a mock-shaped
    fallback; mock runs keep the deterministic fallback. ``run_id`` rides
    into ``run_pipeline`` so the catalog provenance is not NULL for
    sandbox-driven runs (DMR-052).

    Return classification, stage, extraction, and ``offline_fallback`` fields;
    successful pipeline calls also include confidence and source-path fields.
    Import failures raise RuntimeError in live mode. Document-materialization
    and pipeline errors propagate in both modes; mock fallback applies only
    to import failures.
    """
    src = resolve_mailroom_src()
    name = _doc_source_name(row)
    expect = _expect_from_row(row)
    public_gt = tracing.public_ground_truth(row)
    fallback = {
        "id": row.get("id"),
        "doc_type": _classify_mock(row) if mock else None,
        "stage": row.get("expected_stage"),
        "extracted_data": parse_expected_fields(row) if mock else None,
        "offline_fallback": True,
        "intake": intake_summary({}),
    }
    try:
        from graph.build_graph import run_pipeline  # type: ignore
        from pipeline.bins import inbox_dir  # type: ignore
    except Exception as exc:
        if not mock:
            raise RuntimeError(
                "mailroom pipeline is not importable (vendored llm-mailroom missing) — "
                "a live run would silently mock; run `sandbox fetch-deps` or use --mock"
            ) from exc
        with tracing.document_pipeline_trace(
            seed=str(row.get("id") or name),
            session_id=session_id or tracing.session_id_for("pipeline"),
            input={"filename": name, "matter_id": sandbox_matter_id(row, run_id or experiment_name), **public_gt},
            metadata={"pipeline": "mailroom", "source": "sandbox-fixtures", "run_id": experiment_name, "attempt": 1},
            tags=tracing.default_tags("source-fixtures"),
        ):
            with tracing.child_observation("pipeline-result", as_type="generation", input=public_gt):
                # Mock fallback: record the span without a second model call.
                pass
        return fallback

    inbox = inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    queued = _materialize_row(row, inbox)
    matter_id = sandbox_matter_id(row, run_id or experiment_name)
    # Labels for an oracle-routing run only (job.blind_routing: false); a blind run passes none.
    gt = {**public_gt, "expected_doc_class": str(row.get("expected_doc_class") or "")}
    fields = parse_expected_fields(row)
    if fields:
        gt["expected_fields"] = fields

    def _mock_get_llm(agent_name: str):
        return fake_client(expect), "mock-model"

    from pipeline.config import oracle_routing_override  # type: ignore

    from mailroom_sandbox.runtime import blind_routing_active

    blind = blind_routing_active()
    kwargs = {
        "source": "sandbox-fixtures",
        # job.blind_routing: no labels in the graph's state, as in production (llm-mailroom
        # #207). The caller scores the result against the full row either way.
        "ground_truth": None if blind else gt,
        "session_id": session_id or matter_id,
        "run_id": run_id or experiment_name,
    }
    with ExitStack() as stack:
        # Since llm-mailroom #264 (vendored at 63f6841) routing ignores ground_truth unless oracle
        # routing is on. Runs are blind by default (labels never enter the graph, so it neither
        # routes on them nor scores itself against them mid-run) and force oracle routing off,
        # whatever MAILROOM_ORACLE_ROUTING says. Only a locked mock spec with
        # job.blind_routing: false routes on the labels (preflight refuses it for a live run).
        stack.enter_context(oracle_routing_override(not blind))
        if mock:
            stack.enter_context(
                patch("llm.client.get_llm", side_effect=_mock_get_llm)
            )
            stack.enter_context(
                patch("agents.base.get_llm", side_effect=_mock_get_llm)
            )
            for lc_patch in _langchain_mock_patches(expect):
                stack.enter_context(lc_patch)
        result = run_pipeline(queued, matter_id, **kwargs)
    # A parked run returns the state from before the review interrupt; the manifest holds the outcome.
    outcome = dict(result)
    if result.get("stage") == "review" and result.get("doc_id"):
        from pipeline.bins import load_manifest  # type: ignore

        manifest = load_manifest(result["doc_id"]).model_dump(mode="json")
        outcome.update({key: manifest.get(key) for key in REVIEW_OUTCOME_FIELDS if manifest.get(key) is not None})
    return {
        "id": row.get("id"),
        "doc_type": result.get("doc_type"),
        "stage": result.get("stage"),
        "extracted_data": result.get("extracted_data"),
        "classification_confidence": result.get("classification_confidence"),
        # The judge gate's input: routing calibration needs it beside the score.
        "extraction_confidence": result.get("extraction_confidence"),
        **{key: outcome.get(key) for key in REVIEW_OUTCOME_FIELDS},
        # SHF-012: the final subclass (the sorter's, or the reviewer's when it overrode the class) is
        # recorded on every item, so pipeline runs can score subclass; the reviewer's own answer too.
        "doc_subclass": result.get("doc_subclass"),
        "contract_subtype": result.get("contract_subtype"),
        "reviewer_doc_subclass": outcome.get("reviewer_doc_subclass"),
        "reviewer_contract_subtype": outcome.get("reviewer_contract_subtype"),
        # Present only when a pipeline extraction gate is registered (advisory).
        **({"extraction_gate": result.get("extraction_gate")}
           if result.get("extraction_gate") is not None else {}),
        # Present only when a decision slot ran (llm-mailroom decision_slots, scored per slot).
        **{key: result.get(key) for key in DECISION_SLOT_FIELDS if result.get(key) is not None},
        # Present only on an archive the extraction arbiter accepted with caveats (HF-014 marker):
        # reports, the gate and the floor digest separate these from clean archives.
        **({"arbiter_caveats": caveats} if (caveats := _arbiter_caveats(result)) else {}),
        # What intake did (gate, windows, triage class, whether a prior reached the sorter): no text.
        "intake": intake_summary(result),
        "error": result.get("error") or result.get("errors"),
        # The agent exception the graph failed soft on (the run-level engine guard reads it).
        "error_message": result.get("error_message"),
        "offline_fallback": False,
        "mailroom_src": str(src) if src else None,
    }
