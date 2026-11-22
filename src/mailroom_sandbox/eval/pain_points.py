"""Pain-point composites for sandbox pipeline runs: the adapter over the Dojo scorer.

Two penalty scores built around a client's stated production costs (profile ``amfam-v1``): the
volume of documents a person has to review, errors, and misarchived documents. Each document
earns 0 (correct and complete) to 4 (sent to a person when the pipeline could have finished it)
penalty points for classification and for entity extraction; lower is better. The ladders, the
definitions and the outputs are in ``docs/pain-point-composites.md``.

The scoring itself lives in the Dojo (``llm_dojo_scoring.pipeline.pain_points``, contract
``docs/contracts/PAIN_POINT_SCORING.md`` there). Until the vendored Dojo pin ships that module, the
sandbox serves a byte-identical copy of it (``eval/_dojo_pain_points.py``) as scoring hotfix
``SHF-014`` (``docs/scoring-hotfixes.md``): fingerprinted, recorded in every run lock, and not
applied when stale (the composites are then left out and ``sandbox run preflight`` fails). Once a
vendor refresh brings the Dojo module, it is used instead and ``SHF-014`` is retired; every output
names its ``source``.

This module maps sandbox rows and pipeline results onto the Dojo's ``PainPointDocument`` and keeps
the run-level block dual reported like every other headline: the headline uses the hotfixed
extraction scores and ``raw_dojo`` the vendored Dojo pin's.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from mailroom_sandbox.eval import _dojo_pain_points as _interim

_log = logging.getLogger("mailroom_sandbox.eval.pain_points")

HOTFIX_ID = "SHF-014"
KEY = "pain_points"


def _load_core() -> tuple[Any, str]:
    """The Dojo module when the vendored pin ships it, else the SHF-014 copy."""
    try:
        from llm_dojo_scoring.pipeline import pain_points as native
    except ImportError:
        return _interim, f"sandbox hotfix {HOTFIX_ID} (copy of llm_dojo_scoring.pipeline.pain_points)"
    return native, "dojo"


_CORE, SOURCE = _load_core()

PainPointDocument = _CORE.PainPointDocument
PenaltyScale = _CORE.PenaltyScale
Outcome = _CORE.Outcome
DEFAULT_SCALE = _CORE.DEFAULT_SCALE
PROFILE = _CORE.PROFILE
CLASSIFICATION = _CORE.CLASSIFICATION
EXTRACTION = _CORE.EXTRACTION
CLASSIFICATION_REASONS = _CORE.CLASSIFICATION_REASONS
EXTRACTION_REASONS = _CORE.EXTRACTION_REASONS
FABRICATION_MAX_FIELD_SCORE = _CORE.FABRICATION_MAX_FIELD_SCORE
field_value_outcomes = _CORE.field_value_outcomes
summarize = _CORE.summarize


class PainPointsUnavailable(RuntimeError):
    """The composites cannot be served: the vendored Dojo lacks them and SHF-014 is not current."""


def available() -> bool:
    """True when the Dojo serves the composites, or the SHF-014 copy is current."""
    if SOURCE == "dojo":
        return True
    from mailroom_sandbox import scoring_hotfixes as sh

    return sh.enabled(HOTFIX_ID)


def core() -> tuple[Any, str]:
    """``(scorer module, source)``; raises :class:`PainPointsUnavailable` when not :func:`available`."""
    if not available():
        raise PainPointsUnavailable(
            f"{HOTFIX_ID} is not current (its copy of the Dojo module changed since it was validated) "
            "and the vendored Dojo has no pipeline.pain_points: re-validate or retire it "
            "(docs/scoring-hotfixes.md)")
    return _CORE, SOURCE


def document(row: Mapping[str, Any], result: Mapping[str, Any], scored: Mapping[str, Any] | None = None, *,
             subclass_ok: bool | None = None, doc_id: str | None = None,
             groups: Mapping[str, str] | None = None) -> Any:
    """One sandbox row and pipeline result as the Dojo's ``PainPointDocument``.

    ``scored`` is the document's scored extraction row (``eval/runners.py``
    ``_score_pipeline_extraction``; None without field truth). A result with an ``error`` failed.
    """
    stage = result.get("stage")
    row_id = row.get("id")
    return PainPointDocument(
        doc_id=doc_id if doc_id is not None else (None if row_id is None else str(row_id)),
        expected_class=row.get("expected_doc_class"),
        predicted_class=result.get("doc_type"),
        stage=None if stage is None else str(stage),
        expected_stage=row.get("expected_stage"),
        failed=bool(result.get("error")),
        subclass_correct=subclass_ok,
        extraction=scored,
        groups=dict(groups or {}),
    )


def classification_outcome(row: Mapping[str, Any], result: Mapping[str, Any], *,
                           subclass_ok: bool | None = None, scale: Any = DEFAULT_SCALE) -> Any:
    """One document's classification penalty; None when the row has no expected class."""
    return _CORE.classification_outcome(document(row, result, subclass_ok=subclass_ok), scale)


def extraction_outcome(row: Mapping[str, Any], result: Mapping[str, Any], scored: Mapping[str, Any] | None, *,
                       scale: Any = DEFAULT_SCALE) -> Any:
    """One document's extraction penalty; None without an expected class or field truth."""
    return _CORE.extraction_outcome(document(row, result, scored), scale)


def _composites(rows, results, extraction_rows, subclass, scale) -> dict[str, Any]:
    docs = [document(row, result, scored, subclass_ok=sub)
            for row, result, scored, sub in zip(rows, results, extraction_rows, subclass)]
    run = _CORE.score_run(docs, scale)
    return {CLASSIFICATION: run[CLASSIFICATION], EXTRACTION: run[EXTRACTION]}


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
    scale: Any = DEFAULT_SCALE,
) -> dict[str, Any]:
    """Both composites for a pipeline run, dual reported, under ``pain_points``.

    Also returns the Dojo's registry-named flat headlines (``pain_points_{classification,extraction}_mean``,
    lower is better, and ``..._score``, 0-1, higher is better) so a run card or comparison can read
    them without opening the block. Rows, results and
    scored rows must line up one to one; a length mismatch raises. Empty (and logged) when the
    composites are not :func:`available`.
    """
    from mailroom_sandbox import scoring_hotfixes as sh

    rows, results = list(rows), list(results)
    extraction_rows = list(extraction_rows) if extraction_rows is not None else [None] * len(rows)
    if not len(rows) == len(results) == len(extraction_rows):
        raise ValueError(
            f"pain points need one result and one scored row per row: {len(rows)} rows, "
            f"{len(results)} results, {len(extraction_rows)} scored rows")
    if not available():
        _log.warning("pain-point composites left out: %s is not current (docs/scoring-hotfixes.md)", HOTFIX_ID)
        return {}
    fixed = _composites(rows, results, extraction_rows, subclass_flags(rows, results, 1), scale)
    raw = _composites(rows, results, sh.raw_rows(extraction_rows), subclass_flags(rows, results, 0), scale)
    used = sorted({i for r in extraction_rows if r for i in r.get("scoring_hotfixes") or []}
                  | ({"SHF-012"} if sh.enabled("SHF-012") else set())
                  | ({HOTFIX_ID} if SOURCE != "dojo" else set()))
    block = {
        "profile": scale.profile,
        "scale": asdict(scale),
        "source": SOURCE,
        **fixed,
        "raw_dojo": raw,
        "scoring_hotfixes": used,
        "scoring_hotfixes_changed": sorted(k for k in (CLASSIFICATION, EXTRACTION) if raw[k] != fixed[k]),
    }
    # The Dojo's registry-named run headlines: pain_points_{classification,extraction}_{mean,score}.
    return {KEY: block, **_CORE.headline_scores(fixed)}


def item_points(row: Mapping[str, Any], result: Mapping[str, Any], scored: Mapping[str, Any] | None,
                *, subclass_ok: bool | None = None, scale: Any = DEFAULT_SCALE) -> dict[str, Any]:
    """The per-document points a pipeline item persists (absent when the document is not scored)."""
    if not available():
        return {}
    doc = document(row, result, scored, subclass_ok=subclass_ok)
    out: dict[str, Any] = {}
    cls = _CORE.classification_outcome(doc, scale)
    if cls is not None:
        out[f"{KEY}_classification_points"] = cls.points
        out[f"{KEY}_classification_reason"] = cls.reason
    ext = _CORE.extraction_outcome(doc, scale)
    if ext is not None:
        out[f"{KEY}_extraction_points"] = ext.points
        out[f"{KEY}_extraction_reason"] = ext.reason
    return out


__all__ = [
    "CLASSIFICATION_REASONS", "DEFAULT_SCALE", "EXTRACTION_REASONS", "HOTFIX_ID", "KEY", "Outcome", "PROFILE",
    "PainPointDocument", "PainPointsUnavailable", "PenaltyScale", "SOURCE", "available", "classification_outcome",
    "core", "document", "extraction_outcome", "field_value_outcomes", "for_pipeline", "item_points",
    "subclass_flags", "summarize",
]
