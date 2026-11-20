"""Pain-point composites: two penalty scores built around a client's stated operating costs.

A client's document-intelligence team said what hurts most in production: the volume of
documents a person has to review, errors, and misarchived documents. The composites turn a
pipeline run into two numbers on that scale, one for classification and one for entity
extraction. Each document earns **penalty points** from 0 (correct and complete) to 4 (sent
to a person when the pipeline could have finished it); lower is better. Profile
``amfam-v1`` (the American Family Insurance pain points) sets the default scale below.

Classification (``pain_points_classification``), worst reason wins:

====  =====================  ==============================================================
 pts  reason                 when
====  =====================  ==============================================================
  4   unnecessary_review     routed to review although the row's expected stage is archived
  4   pipeline_failure       the document errored or ended in no final stage
  3   wrong_doc_type         archived under another class (a misarchive)
  2   missed_review          archived although the row's expected stage is review
  1   wrong_subtype          archived under the right class with the wrong subclass
  0   necessary_review       routed to review, and the expected stage is review
  0   correct                archived under the right class (and subclass, when labelled)
====  =====================  ==============================================================

Entity extraction (``pain_points_extraction``), over documents with field ground truth:

====  =====================  ==============================================================
 pts  reason                 when
====  =====================  ==============================================================
  4   unnecessary_review     as above: the extraction never had to reach a person
  4   pipeline_failure       as above
  3   fabricated             values were stated but none is supported by the truth (no
                             exact field, no near miss, at least one wrong or invented one)
  2   low_recall             under a third of the targeted entities reported correctly,
                             including an extraction that stated nothing
  1   partial                some targeted entities right, but not all, or extra values
                             were stated on fields the truth leaves empty
  0   necessary_review       as above: a person had to see it anyway
  0   complete               every targeted entity right and nothing invented
====  =====================  ==============================================================

Definitions, so a number can be traced back:

- *Targeted entities* are the expected fields with a value (the Dojo's ``tp + fn`` events);
  *reported correctly* is a field the Dojo scores 1.0 (``tp``). The share is ``tp / (tp + fn)``.
- *Invented values* are the Dojo's false positives (``fp``: a value on a field the truth
  leaves empty, including a documented absence under SHF-001, or an unmatched list item) plus
  ``n_value_wrong`` (a value stated on a targeted field that scores under
  ``scoring.FABRICATION_MAX_FIELD_SCORE``). A value between that bar and 1.0 is a near miss
  (``n_value_partial``): wrong, but not invented.
- Contract (CUAD) and merger (MAUD) rows are scored on clause labels, not fields, so their
  share is the row's ``overall_extraction_score`` and they are never called fabricated.
- *Unnecessary review* uses the row's ``expected_stage`` (default ``archived``) as the truth
  that the pipeline could have finished the document. A run without expected stages cannot
  separate needed from needless reviews, so every review counts as needless; read the
  ``necessary_review`` count before comparing such runs.

Rows without an expected class are left out of both composites, and rows without field
truth out of the extraction composite (``*_excluded``): a missing label is never scored as
correct (``docs/critical-regressions.md`` row 1). Each composite reports its scored ``n``,
the total and mean points, a 0-1 ``score`` (``1 - mean / max points``, higher is better),
the count per reason and a per-class table. Both composites are dual reported like every
other headline (``docs/scoring-hotfixes.md``): the headline uses the hotfixed scores and
``raw_dojo`` the vendored Dojo pin's. See ``docs/pain-point-composites.md``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

PROFILE = "amfam-v1"
KEY = "pain_points"
CLASSIFICATION = "classification"
EXTRACTION = "extraction"

CLASSIFICATION_REASONS = (
    "unnecessary_review", "pipeline_failure", "wrong_doc_type", "missed_review", "wrong_subtype",
    "necessary_review", "correct",
)
EXTRACTION_REASONS = (
    "unnecessary_review", "pipeline_failure", "fabricated", "low_recall", "partial",
    "necessary_review", "complete",
)

_FINAL_STAGES = ("archived", "review")


@dataclass(frozen=True)
class PenaltyScale:
    """Points per reason. The defaults are profile ``amfam-v1``; the order is enforced."""

    unnecessary_review: float = 4.0
    pipeline_failure: float = 4.0
    wrong_doc_type: float = 3.0
    missed_review: float = 2.0
    wrong_subtype: float = 1.0
    fabricated: float = 3.0
    low_recall: float = 2.0
    partial: float = 1.0
    #: Under this share of targeted entities reported correctly, an extraction is ``low_recall``.
    low_recall_below: float = 1 / 3

    def __post_init__(self) -> None:
        def strictly_falling(*names: str) -> None:
            values = [getattr(self, n) for n in names]
            if any(a <= b for a, b in zip(values, values[1:])):
                raise ValueError(f"penalty scale must fall strictly along {' > '.join(names)}: {values}")

        # The client's ordering: a needless review is the worst outcome on both composites.
        strictly_falling("unnecessary_review", "wrong_doc_type", "wrong_subtype")
        strictly_falling("unnecessary_review", "fabricated", "low_recall", "partial")
        if not self.wrong_doc_type > self.missed_review > 0 or self.wrong_subtype <= 0:
            raise ValueError("penalty scale: wrong_doc_type > missed_review > 0 and wrong_subtype > 0")
        if not 0 < self.pipeline_failure <= self.unnecessary_review:
            raise ValueError("penalty scale: 0 < pipeline_failure <= unnecessary_review")
        if not 0 < self.low_recall_below < 1:
            raise ValueError("penalty scale: low_recall_below must lie in (0, 1)")

    @property
    def max_points(self) -> float:
        return max(self.unnecessary_review, self.pipeline_failure)


DEFAULT_SCALE = PenaltyScale()


@dataclass(frozen=True)
class Outcome:
    """One document's penalty: its points and every reason that applied, worst first."""

    points: float
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        return self.reasons[0]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _routing(row: Mapping[str, Any], result: Mapping[str, Any], scale: PenaltyScale) -> Outcome | None:
    """The outcome shared by both composites for a document that did not archive, else None."""
    stage = str(result.get("stage") or "")
    if result.get("error") or stage not in _FINAL_STAGES:
        return Outcome(scale.pipeline_failure, ("pipeline_failure",))
    if stage == "review":
        if str(row.get("expected_stage") or "archived") == "review":
            return Outcome(0.0, ("necessary_review",))
        return Outcome(scale.unnecessary_review, ("unnecessary_review",))
    return None


def _worst(found: list[tuple[float, str]], clean: str) -> Outcome:
    if not found:
        return Outcome(0.0, (clean,))
    found.sort(key=lambda item: -item[0])
    return Outcome(found[0][0], tuple(reason for _, reason in found))


def classification_outcome(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    subclass_ok: bool | None = None,
    scale: PenaltyScale = DEFAULT_SCALE,
) -> Outcome | None:
    """One document's classification penalty; None when the row has no expected class.

    ``subclass_ok`` is the document's subclass correctness (``scoring.subclass_correct``), None
    when the row has no subclass truth. An archive without a class name is a wrong class here:
    the document is filed nowhere a person would look for it.
    """
    expected = _label(row.get("expected_doc_class"))
    if not expected:
        return None
    routed = _routing(row, result, scale)
    if routed is not None:
        return routed
    found: list[tuple[float, str]] = []
    if _label(result.get("doc_type")) != expected:
        found.append((scale.wrong_doc_type, "wrong_doc_type"))
    if str(row.get("expected_stage") or "archived") == "review":
        found.append((scale.missed_review, "missed_review"))
    if subclass_ok is False and not any(r == "wrong_doc_type" for _, r in found):
        found.append((scale.wrong_subtype, "wrong_subtype"))
    return _worst(found, "correct")


def extraction_outcome(
    row: Mapping[str, Any],
    result: Mapping[str, Any],
    scored: Mapping[str, Any] | None,
    *,
    scale: PenaltyScale = DEFAULT_SCALE,
) -> Outcome | None:
    """One document's extraction penalty; None without an expected class or field truth.

    ``scored`` is the document's scored extraction row (``eval/runners.py``
    ``_score_pipeline_extraction``; None when the row has no field truth). A row the scorer
    gave no usable figure is left out too, never scored as complete.
    """
    if scored is None or not _label(row.get("expected_doc_class")):
        return None
    routed = _routing(row, result, scale)
    if routed is not None:
        return routed
    tp, fn, fp = (_num(scored.get(k)) for k in ("tp", "fn", "fp"))
    clause_labels = "+maud" in str(scored.get("scoring_method") or "") or "+cuad" in str(
        scored.get("scoring_method") or "")
    if clause_labels or tp is None or fn is None:
        share = _num(scored.get("overall_extraction_score"))
        if share is None:
            return None
        if share >= 1.0:
            return Outcome(0.0, ("complete",))
        if share < scale.low_recall_below:
            return Outcome(scale.low_recall, ("low_recall",))
        return Outcome(scale.partial, ("partial",))
    invented = (fp or 0.0) + (_num(scored.get("n_value_wrong")) or 0.0)
    near_miss = _num(scored.get("n_value_partial")) or 0.0
    targeted = tp + fn
    if targeted <= 0:
        # The truth holds only empty fields: anything stated was invented.
        return Outcome(scale.fabricated, ("fabricated",)) if invented > 0 else Outcome(0.0, ("complete",))
    share = tp / targeted
    if tp == 0 and near_miss == 0 and invented > 0:
        return Outcome(scale.fabricated, ("fabricated",))
    if share < scale.low_recall_below:
        return Outcome(scale.low_recall, ("low_recall",))
    if share < 1.0 or invented > 0:
        return Outcome(scale.partial, ("partial",))
    return Outcome(0.0, ("complete",))


def summarize(
    outcomes: Iterable[tuple[Outcome | None, str | None]],
    reasons: Sequence[str],
    scale: PenaltyScale = DEFAULT_SCALE,
) -> dict[str, Any]:
    """``(outcome, class)`` pairs -> n, excluded, points, mean, 0-1 score, reasons and classes."""
    points: Counter[str] = Counter()
    count: Counter[str] = Counter()
    tiers: Counter[str] = Counter({name: 0 for name in reasons})
    excluded = 0
    for outcome, cls in outcomes:
        if outcome is None:
            excluded += 1
            continue
        name = _label(cls) or "unknown"
        count[name] += 1
        points[name] += outcome.points
        tiers[outcome.reason] += 1
    n = sum(count.values())
    total = sum(points.values())
    mean = total / n if n else None
    return {
        "n": n,
        "excluded": excluded,
        "points": round(total, 6),
        "mean": round(mean, 6) if mean is not None else None,
        "score": round(1 - mean / scale.max_points, 6) if mean is not None else None,
        "reasons": dict(tiers),
        "by_class": {
            name: {"n": count[name], "points": round(points[name], 6),
                   "mean": round(points[name] / count[name], 6)}
            for name in sorted(count)
        },
    }


def _composites(rows, results, extraction_rows, subclass, scale) -> dict[str, Any]:
    classification = []
    extraction = []
    for row, result, scored, sub in zip(rows, results, extraction_rows, subclass):
        cls = row.get("expected_doc_class")
        classification.append((classification_outcome(row, result, subclass_ok=sub, scale=scale), cls))
        extraction.append((extraction_outcome(row, result, scored, scale=scale), cls))
    return {CLASSIFICATION: summarize(classification, CLASSIFICATION_REASONS, scale),
            EXTRACTION: summarize(extraction, EXTRACTION_REASONS, scale)}


def subclass_flags(rows: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]],
                   side: int) -> list[bool | None]:
    """Each document's subclass correctness, ``side`` 0 = raw Dojo pin, 1 = hotfixed (SHF-012)."""
    from mailroom_sandbox.eval import scoring

    flags: list[bool | None] = []
    for row, result in zip(rows, results):
        pair = scoring.subclass_correct(row.get("expected_doc_class"), row.get("expected_subclass"),
                                        result.get("doc_type"), scoring.predicted_subclass(result))
        flags.append(None if pair is None else bool(pair[side]))
    return flags


def for_pipeline(
    rows: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    extraction_rows: Sequence[Mapping[str, Any] | None] | None = None,
    *,
    scale: PenaltyScale = DEFAULT_SCALE,
) -> dict[str, Any]:
    """Both composites for a pipeline run, dual reported, under ``pain_points``.

    Also returns flat ``pain_points_classification_mean`` / ``pain_points_extraction_mean`` so
    a run card or comparison can read the headline without opening the block. Rows, results and
    scored rows must line up one to one; a length mismatch raises.
    """
    from mailroom_sandbox import scoring_hotfixes as sh

    rows, results = list(rows), list(results)
    extraction_rows = list(extraction_rows) if extraction_rows is not None else [None] * len(rows)
    if not len(rows) == len(results) == len(extraction_rows):
        raise ValueError(
            f"pain points need one result and one scored row per row: {len(rows)} rows, "
            f"{len(results)} results, {len(extraction_rows)} scored rows")
    fixed = _composites(rows, results, extraction_rows, subclass_flags(rows, results, 1), scale)
    raw = _composites(rows, results, sh.raw_rows(extraction_rows), subclass_flags(rows, results, 0), scale)
    used = sorted({i for r in extraction_rows if r for i in r.get("scoring_hotfixes") or []}
                  | ({"SHF-012"} if sh.enabled("SHF-012") else set()))
    block = {
        "profile": PROFILE,
        "scale": asdict(scale),
        **fixed,
        "raw_dojo": raw,
        "scoring_hotfixes": used,
        "scoring_hotfixes_changed": sorted(k for k in (CLASSIFICATION, EXTRACTION) if raw[k] != fixed[k]),
    }
    return {
        KEY: block,
        f"{KEY}_classification_mean": fixed[CLASSIFICATION]["mean"],
        f"{KEY}_extraction_mean": fixed[EXTRACTION]["mean"],
    }


def item_points(row: Mapping[str, Any], result: Mapping[str, Any], scored: Mapping[str, Any] | None,
                *, subclass_ok: bool | None = None, scale: PenaltyScale = DEFAULT_SCALE) -> dict[str, Any]:
    """The per-document points a pipeline item persists (absent when the document is not scored)."""
    out: dict[str, Any] = {}
    cls = classification_outcome(row, result, subclass_ok=subclass_ok, scale=scale)
    if cls is not None:
        out[f"{KEY}_classification_points"] = cls.points
        out[f"{KEY}_classification_reason"] = cls.reason
    ext = extraction_outcome(row, result, scored, scale=scale)
    if ext is not None:
        out[f"{KEY}_extraction_points"] = ext.points
        out[f"{KEY}_extraction_reason"] = ext.reason
    return out


__all__ = [
    "CLASSIFICATION_REASONS", "DEFAULT_SCALE", "EXTRACTION_REASONS", "KEY", "Outcome", "PROFILE",
    "PenaltyScale", "classification_outcome", "extraction_outcome", "for_pipeline", "item_points",
    "subclass_flags", "summarize",
]
