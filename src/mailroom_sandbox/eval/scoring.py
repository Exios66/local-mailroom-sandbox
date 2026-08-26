"""Deterministic scoring via llm-dojo-scoring + local JSONL score sink."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_dojo_scoring import (
    LocalManifestSink,
    ScoreRecord,
    accuracy,
    bootstrap_ci,
    exact_match,
    score_extraction,
    score_task,
)

from mailroom_sandbox.paths import reports_dir


def scores_path() -> Path:
    dest = reports_dir() / "scores" / "scores.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def emit(record: ScoreRecord, path: Path | None = None) -> None:
    LocalManifestSink(path or scores_path()).emit(record)


def score_classification(expected: list[str], predicted: list[str]) -> dict[str, Any]:
    acc = accuracy(expected, predicted)
    matches = [exact_match(p, e) for p, e in zip(predicted, expected)]
    ci = bootstrap_ci(matches) if matches else {}
    task = score_task("doc_class", expected=expected, predicted=predicted)
    return {
        "exact_match": acc,
        "exact_match_ci": ci,
        "n": len(expected),
        "task": task if isinstance(task, dict) else {"result": task},
    }


def score_extraction_row(
    doc_type: str,
    predicted: dict,
    expected: dict,
    doc_text: str | None = None,
) -> dict[str, Any]:
    try:
        from llm_dojo_scoring import suite_for_doc_type

        suite = suite_for_doc_type(doc_type)
        field_types = getattr(suite, "field_types", None) or {}
    except Exception:
        field_types = {}
    result = score_extraction(
        doc_type,
        field_types,
        predicted or {},
        expected or {},
        doc_text=doc_text,
    )
    overall = getattr(result, "overall_score", None)
    if overall is None and isinstance(result, dict):
        overall = result.get("overall_score")
    payload = {"overall_extraction_score": overall, "doc_type": doc_type}
    if hasattr(result, "__dict__"):
        payload["fields"] = {
            k: v for k, v in vars(result).items() if k != "field_scores" and not k.startswith("_")
        }
    return payload


def score_legalbench(expected: list[str], predicted: list[str]) -> dict[str, Any]:
    result = score_task("legalbench", expected=expected, predicted=predicted)
    if not isinstance(result, dict):
        result = {"result": result}
    result.setdefault("exact_match", accuracy(expected, predicted))
    return result


def score_stage(expected: list[str], predicted: list[str]) -> dict[str, Any]:
    acc = accuracy(expected, predicted)
    matches = [exact_match(p, e) for p, e in zip(predicted, expected)]
    return {
        "stage_correct": acc,
        "stage_correct_ci": bootstrap_ci(matches) if matches else {},
        "n": len(expected),
    }


def mean_or_zero(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
