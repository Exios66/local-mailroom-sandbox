"""Incorrect archives: one metric, reported beside the review metric by pipeline runs.

The production gate (``job/gate.py``) owns the ``wrong_archive`` outcome — an archive is
wrong when it landed under another class than expected, or its extraction score is under
the quality bar. This module does not replace it: it carries the same semantics to the
per-run score surface that pipeline runs report (next to ``eval/human_review.py``), so a
run card, the autoresearch loop and failure debugging can read both cost-of-operation
numbers per class without re-deriving them:

- ``incorrect_archives`` / ``incorrect_archives_rate`` / ``incorrect_archives_by_class``
  with an ``incorrect_archives_basis`` that names what was checked, and
- ``incorrect_archives_reasons`` — the reason counts behind the headline.

A document is only flagged when it **finished archived** (stage ``archived``); a document
that went to review, crashed or failed can be many things, but it was never wrongly
archived. Without an expected class on the row the metric stays silent: no blind labels
(``docs/critical-regressions.md`` row 1). Reasons, in gate precedence order:

- ``wrong_class_archive``: archived under another class than the row's expected class.
- ``stage_should_review``: archived although the row's expected stage is ``review``.
- ``incomplete_extraction_archive``: archived with a per-document extraction score under
  the gate's quality bar (0.90 by default; only checked when the row has field ground
  truth, i.e. a scored row exists).
- ``parse_error_archive``: archived with a parse error on the result.

``failure_report`` is the debugging aggregation for scale: one summary over the run's
per-document gate statuses (the autoresearch ``DocScore`` shape) that counts outcomes,
causes and cause-by-class, so the recurring failure patterns behind a plateau are visible
without opening every run.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

KEY = "incorrect_archives"

#: The gate's quality bar (``job/gate.py``): an archive scoring below it is wrong.
DEFAULT_QUALITY_BAR = 0.90

_OUTCOMES = ("correct_archive", "wrong_archive", "review", "unscorable_archive", "crashed", "judge_error")


def archive_reasons(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    scored: Mapping[str, Any] | None = None,
    parse_error: bool | None = None,
    quality: float = DEFAULT_QUALITY_BAR,
) -> list[str]:
    """Every reason this finished document is an incorrect archive, in gate precedence order."""
    expected = str(row.get("expected_doc_class") or "").strip()
    stage = str(result.get("stage") or "")
    if not expected or stage != "archived":
        return []
    reasons: list[str] = []
    doc_type = result.get("doc_type")
    if doc_type and doc_type != expected:
        reasons.append("wrong_class_archive")
    if str(row.get("expected_stage") or "archived") == "review":
        reasons.append("stage_should_review")
    if scored is not None:
        score = scored.get("overall_extraction_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and float(score) < quality:
            reasons.append("incomplete_extraction_archive")
    if parse_error is None:
        parse_error = bool(result.get("parse_error"))
    if parse_error:
        reasons.append("parse_error_archive")
    return reasons


def summarize(pairs: Iterable[tuple[Sequence[str], str | None]], basis: str) -> dict[str, Any]:
    """``(reasons, class)`` pairs -> count, rate, per-class table, reason counts and basis."""
    total: Counter[str] = Counter()
    incorrect: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for pair in pairs:
        doc_reasons, cls = pair
        name = str(cls or "unknown")
        total[name] += 1
        if doc_reasons:
            incorrect[name] += 1
            reasons.update(doc_reasons)
    n = sum(total.values())
    count = sum(incorrect.values())
    return {
        KEY: count,
        f"{KEY}_rate": round(count / n, 6) if n else None,
        f"{KEY}_by_class": {
            name: {
                "incorrect": incorrect[name],
                "n": total[name],
                "rate": round(incorrect[name] / total[name], 6),
            }
            for name in sorted(total)
        },
        f"{KEY}_reasons": dict(sorted(reasons.items())),
        f"{KEY}_basis": basis,
    }


def for_pipeline(
    rows: Iterable[Mapping[str, Any]],
    results: Iterable[Mapping[str, Any]],
    extraction_rows: Iterable[Mapping[str, Any] | None] | None = None,
    quality: float = DEFAULT_QUALITY_BAR,
) -> dict[str, Any]:
    """The metric for a pipeline run over its rows and finished documents.

    ``extraction_rows`` are the per-document scored rows (``eval/runners.py``'s
    ``_score_pipeline_extraction`` output); a row without field ground truth is ``None``
    and its completeness is never judged. Rows and results must line up pairwise — the
    metric is silent for a result whose row is missing rather than guess.
    """
    pairs = (
        (archive_reasons(row, result, scored=scored, quality=quality), row.get("expected_doc_class"))
        for row, result, scored in _zip_strict(rows, results, extraction_rows)
    )
    return summarize(pairs, "pipeline")


def _zip_strict(rows, results, extraction_rows):
    """Pair rows/results/extraction_rows one-to-one; a missing row silences, never shifts."""
    extraction_rows = iter(extraction_rows) if extraction_rows is not None else None
    for row, result in zip(rows, results):
        scored = next(extraction_rows, None) if extraction_rows is not None else None
        yield row, result, scored


def failure_report(statuses: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-document gate statuses for failure debugging at scale.

    Each status is the per-document gate outcome (autoresearch ``DocScore`` fields:
    ``doc_class``, ``outcome``, ``cause``, optionally ``crash_node``). The report counts
    outcomes, causes and cause-by-class so the patterns behind a plateau — the same cause
    recurring on one class, or crashes concentrating on one node — are visible in one
    table. Deterministic and offline; it reads what a finished run already recorded.
    """
    statuses = list(statuses)
    outcomes: Counter[str] = Counter({name: 0 for name in _OUTCOMES} if statuses else {})
    causes: Counter[str] = Counter()
    causes_by_class: dict[str, Counter[str]] = {}
    crashes_by_node: Counter[str] = Counter()
    for status in statuses:
        cls = str(status.get("doc_class") or "unknown")
        outcome = str(status.get("outcome") or "unknown")
        outcomes[outcome] += 1
        cause = str(status.get("cause") or "")
        if cause:
            causes[cause] += 1
            causes_by_class.setdefault(cls, Counter())[cause] += 1
        node = status.get("crash_node")
        if outcome == "crashed" and node:
            crashes_by_node[str(node)] += 1
    return {
        "n": len(statuses),
        "outcomes": dict(sorted(outcomes.items())),
        "causes": dict(sorted(causes.items())),
        "causes_by_class": {cls: dict(sorted(ctr.items())) for cls, ctr in sorted(causes_by_class.items())},
        "crashes_by_node": dict(sorted(crashes_by_node.items())),
    }
