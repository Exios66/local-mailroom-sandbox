"""Pain-point composites for sandbox pipeline runs: the adapter over the Dojo scorer.

Two penalty scores built around a client's stated production costs (profile ``amfam-v1``): the
volume of documents a person has to review, errors, and misarchived documents. Each document
earns 0 (correct and complete) to 4 (sent to a person when the pipeline could have finished it)
penalty points for classification and for entity extraction; lower is better. The ladders, the
definitions and the outputs are in ``docs/pain-point-composites.md``.

The scoring itself lives in the Dojo (``llm_dojo_scoring.pipeline.pain_points``, contract
``docs/contracts/PAIN_POINT_SCORING.md`` there), served by the vendored pin. Scoring hotfix
``SHF-014`` served a byte-identical copy of it until the pin shipped the module; it is retired.

This module maps sandbox rows and pipeline results onto the Dojo's ``PainPointDocument`` and keeps
the run-level block dual reported like every other headline: the headline uses the hotfixed
extraction scores and ``raw_dojo`` the vendored Dojo pin's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from llm_dojo_scoring.pipeline import pain_points as _CORE

KEY = "pain_points"
#: Where the scorer comes from; every run-level block records it.
SOURCE = "dojo"

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


def core() -> tuple[Any, str]:
    """``(scorer module, source)``: the vendored Dojo's ``pipeline.pain_points``."""
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
    "CLASSIFICATION_REASONS", "DEFAULT_SCALE", "EXTRACTION_REASONS", "KEY", "Outcome", "PROFILE",
    "PainPointDocument", "PenaltyScale", "SOURCE", "classification_outcome",
    "core", "document", "extraction_outcome", "field_value_outcomes", "for_pipeline", "item_points",
    "subclass_flags", "summarize",
]
