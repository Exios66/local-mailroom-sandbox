"""Eval runners: sorter / extract / chained / pipeline / legalbench."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mailroom_sandbox.datasets import (
    dataset_fingerprint,
    fixture_file,
    load_hf_fixtures,
    load_legalbench_fixtures,
    load_manifest,
    parse_expected_fields,
)
from mailroom_sandbox.eval import experiment_log, scoring, tracing
from mailroom_sandbox.eval.scoring import emit
from mailroom_sandbox.mock_llm import fake_client
from mailroom_sandbox.runtime import activate, resolve_mailroom_src

try:
    from llm_dojo_scoring.emitter import ScoreRecord
except Exception:  # pragma: no cover
    ScoreRecord = None  # type: ignore


def _expect_from_row(row: dict[str, Any]) -> dict[str, Any]:
    doc_type = row.get("expected_doc_class") or row.get("doc_type") or "contract"
    conf = 0.40 if row.get("id") == "ambiguous_01" else 0.97
    return {
        "id": row.get("id"),
        "doc_type": doc_type,
        "expected_doc_class": doc_type,
        "conf": conf,
        "expected_fields": parse_expected_fields(row) if "expected_fields" in row else row.get("expected_fields"),
        "legalbench_answer": row.get("answer"),
    }


def _classify_mock(row: dict[str, Any]) -> str:
    return str(row.get("expected_doc_class") or row.get("doc_type") or "unknown")


def run_sorter_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    prompt_version: str | None = None,
    profile: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    rows = load_manifest()
    if sample:
        rows = rows[: sample]
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

    activation = activate(profile, model=model, prompt_variant=prompt_version)
    predicted: list[str] = []
    expected: list[str] = []
    for row in rows:
        expected.append(row["expected_doc_class"])
        if mock:
            predicted.append(_classify_mock(row))
        else:
            predicted.append(_run_pipeline_doc(row, mock=False).get("doc_type") or "unknown")

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
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_sorter",
        task="sorter",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model or (activation.assignments[0][2] if activation.assignments else None),
        prompt_version=prompt_version or "mailroom-default",
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures"),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "record": record}


def run_extract_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    rows = [r for r in load_manifest() if parse_expected_fields(r)]
    if sample:
        rows = rows[: sample]
    plan = {"task": "extract", "n": len(rows), "mock": mock, "fingerprint": dataset_fingerprint(rows)}
    if dry_run:
        return plan
    activation = activate(profile, model=model, prompt_variant=prompt_version)
    overall: list[float] = []
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
            doc_text=fixture_file(row).read_text(encoding="utf-8"),
        )
        value = scored.get("overall_extraction_score")
        if isinstance(value, (int, float)):
            overall.append(float(value))
    mean = sum(overall) / len(overall) if overall else 0.0
    scores = {"overall_extraction_score": mean, "n": len(rows)}
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_extract",
        task="extract",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=prompt_version or "mailroom-default",
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
    composite = 0.25 * float(sorter.get("scores", {}).get("exact_match") or 0) + 0.75 * float(
        extract.get("scores", {}).get("overall_extraction_score") or 0
    )
    scores = {
        "sorter_exact": sorter.get("scores", {}).get("exact_match"),
        "extractor_overall": extract.get("scores", {}).get("overall_extraction_score"),
        "chained_composite": composite,
    }
    return {"task": "chained", "scores": scores, "sorter": sorter, "extract": extract}


def run_legalbench_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    rows = load_legalbench_fixtures()
    if sample:
        rows = rows[: sample]
    plan = {"task": "legalbench", "n": len(rows), "mock": mock}
    if dry_run:
        return plan
    activation = activate(profile, model=model)
    expected = [str(r.get("answer") or r.get("expected") or "") for r in rows]
    if mock:
        predicted = list(expected)
    else:
        predicted = [_live_legalbench_answer(r, model=model) for r in rows]
    scores = scoring.score_legalbench(expected, predicted)
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_legalbench",
        task="legalbench",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        mock=mock,
        n=len(rows),
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-legalbench"),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores}


def run_pipeline_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    rows = load_manifest()
    if sample:
        rows = rows[: sample]
    plan = {"task": "pipeline", "n": len(rows), "mock": mock, "fingerprint": dataset_fingerprint(rows)}
    if dry_run:
        return plan
    activation = activate(profile, model=model, prompt_variant=prompt_version)
    results = []
    for row in rows:
        results.append(_run_pipeline_doc(row, mock=mock))
    expected = [r["expected_doc_class"] for r in rows]
    predicted = [r.get("doc_type") or "unknown" for r in results]
    scores = scoring.score_classification(expected, predicted)
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_pipeline",
        task="pipeline",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=prompt_version or "mailroom-default",
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        docs=results,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures"),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "docs": results}


def _run_pipeline_doc(row: dict[str, Any], *, mock: bool) -> dict[str, Any]:
    """Run one fixture through mailroom ``run_pipeline`` when available."""
    src = resolve_mailroom_src()
    path = fixture_file(row)
    expect = _expect_from_row(row)
    try:
        from graph.build_graph import run_pipeline  # type: ignore
        from pipeline.bins import inbox_dir  # type: ignore
        from llm.client import get_llm as real_get_llm  # type: ignore
    except Exception:
        return {
            "id": row.get("id"),
            "doc_type": _classify_mock(row) if mock else None,
            "stage": row.get("expected_stage"),
            "extracted_data": parse_expected_fields(row) if mock else None,
            "offline_fallback": True,
        }

    import shutil

    inbox = inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    queued = inbox / path.name
    shutil.copyfile(path, queued)
    matter_id = f"SANDBOX-{row.get('id')}"
    gt = {
        "expected_doc_class": row["expected_doc_class"],
        "expected_stage": row.get("expected_stage"),
    }
    fields = parse_expected_fields(row)
    if fields:
        gt["expected_fields"] = fields

    def _mock_get_llm(agent_name: str):
        return fake_client(expect), "mock-model"

    if mock:
        with patch("llm.client.get_llm", side_effect=_mock_get_llm), patch(
            "agents.base.get_llm", side_effect=_mock_get_llm
        ):
            result = run_pipeline(queued, matter_id, source="sandbox-fixtures", ground_truth=gt)
    else:
        result = run_pipeline(queued, matter_id, source="sandbox-fixtures", ground_truth=gt)
    return {
        "id": row.get("id"),
        "doc_type": result.get("doc_type"),
        "stage": result.get("stage"),
        "extracted_data": result.get("extracted_data"),
        "classification_confidence": result.get("classification_confidence"),
        "offline_fallback": False,
        "mailroom_src": str(src) if src else None,
    }


def _live_legalbench_answer(row: dict[str, Any], *, model: str | None) -> str:
    try:
        from openai import OpenAI
    except Exception:
        return str(row.get("answer") or "")
    base = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("VLLM_BASE_URL") or "http://localhost:11434/v1"
    client = OpenAI(base_url=base, api_key=os.environ.get("VLLM_API_KEY") or "not-needed")
    prompt = (
        f"Answer Yes or No only. json required.\nQuestion: {row.get('question')}\n"
        f"Passage: {row.get('text') or row.get('passage')}\n"
    )
    resp = client.chat.completions.create(
        model=model or os.environ.get("SANDBOX_MODEL") or "qwen3:8b",
        messages=[
            {"role": "system", "content": "Return json {\"answer\": \"Yes\" or \"No\"}."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=32,
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        return str(json.loads(raw).get("answer") or raw).strip()
    except json.JSONDecodeError:
        return raw.strip()


def hf_rows_as_manifest() -> list[dict[str, str]]:
    rows = []
    for item in load_hf_fixtures():
        rows.append(
            {
                "id": str(item.get("id") or item.get("filename") or item.get("doc_type")),
                "subdir": "hf",
                "filename": str(item.get("filename") or f"{item.get('doc_type')}.txt"),
                "expected_doc_class": str(item.get("doc_type") or item.get("expected_hf_class") or "unknown"),
                "expected_stage": "archived",
                "text": str(item.get("text") or ""),
            }
        )
    return rows
