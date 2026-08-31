"""Eval runners: sorter / extract / chained / pipeline / legalbench."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
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
from mailroom_sandbox.mock_llm import fake_client, fake_structured_payload
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


def _predict_spec(spec, row: dict[str, Any], *, mock: bool) -> tuple[dict[str, Any], bool]:
    if mock:
        return spec.mock_predict(row), False
    if spec.live_predict is None:
        return spec.mock_predict(row), True
    try:
        return spec.live_predict(row), False
    except Exception:
        return spec.mock_predict(row), True


def run_isolated_eval(
    task: str,
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    prompt_version: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    agent_models: dict[str, str] | None = None,
    connected: bool = False,
) -> dict[str, Any]:
    """Run one live agent / node against fixtures, nested under document-pipeline."""
    from mailroom_sandbox.eval.agents import spec_for

    spec = spec_for(task)
    rows = spec.load_rows()
    if sample:
        rows = rows[: sample]
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
    per_row: list[dict[str, Any]] = []
    offline = 0
    for row in rows:
        seed = str(row.get("id") or row.get("filename") or task)
        with tracing.document_pipeline_trace(
            seed=seed,
            session_id=session,
            input={"filename": row.get("filename") or row.get("id"), "matter_id": f"SANDBOX-{row.get('id')}"},
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
        if fell_back:
            offline += 1
        match = scored.get("match")
        if match is None and "overall_extraction_score" in scored:
            match = scored.get("overall_extraction_score") or 0.0
        if isinstance(match, (int, float)):
            matches.append(float(match))
        per_row.append({"id": row.get("id"), "pred": pred, "score": scored, "offline_fallback": fell_back})
    mean = scoring.mean_or_zero(matches)
    scores = {"exact_match": mean, "n": len(rows), "offline_fallback": offline}
    if per_row and "overall_extraction_score" in (per_row[0].get("score") or {}):
        scores["overall_extraction_score"] = mean
    tracing.emit_langfuse_score("class_correct" if spec.observation == "classify-document" else "stage_completed", mean)
    tracing.flush_traces()
    if ScoreRecord is not None:
        emit(
            ScoreRecord(
                metric="exact_match",
                value=float(mean),
                agent=task,
                run_id=experiment_name,
            )
        )
    record = experiment_log.new_record(
        experiment_name=experiment_name or f"sandbox_{task}",
        task=task,
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model or (activation.assignments[0][2] if activation.assignments else None),
        prompt_version=prompt_version or "mailroom-default",
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=len(rows),
        scores=scores,
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-fixtures", f"agent-{task}"),
        session_id=session,
        trace_ids=tracing.last_trace_ids(),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "record": record, "rows": per_row}


def run_sorter_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    prompt_version: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    agent_models: dict[str, str] | None = None,
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

    activation = activate(profile, model=model, prompt_variant=prompt_version, agent_models=agent_models)
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
    agent_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = [r for r in load_manifest() if parse_expected_fields(r)]
    if sample:
        rows = rows[: sample]
    plan = {"task": "extract", "n": len(rows), "mock": mock, "fingerprint": dataset_fingerprint(rows)}
    if dry_run:
        return plan
    activation = activate(profile, model=model, prompt_variant=prompt_version, agent_models=agent_models)
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
    agent_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = load_legalbench_fixtures()
    if sample:
        rows = rows[: sample]
    plan = {"task": "legalbench", "n": len(rows), "mock": mock}
    if dry_run:
        return plan
    activation = activate(profile, model=model, agent_models=agent_models)
    expected = [str(r.get("answer") or r.get("expected") or "") for r in rows]
    if mock:
        predicted = list(expected)
    else:
        predicted = [_live_legalbench_answer(r, model=model) for r in rows]
    session = tracing.session_id_for("legalbench")
    for row, pred in zip(rows, predicted):
        with tracing.document_pipeline_trace(
            seed=str(row.get("id") or "legalbench"),
            session_id=session,
            input={"filename": row.get("id"), **tracing.public_ground_truth({"expected": row.get("answer")})},
            metadata={"pipeline": "mailroom", "source": "legalbench", "run_id": experiment_name},
            tags=tracing.default_tags("source-legalbench"),
        ):
            with tracing.child_observation("answer-question", as_type="generation"):
                pass
    tracing.flush_traces()
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
) -> dict[str, Any]:
    """Compare local (Ollama/vLLM/…) vs API-key (OpenRouter) serving metrics.

    ``--mock`` uses committed fixture timings (no LLM, no ``OPENROUTER_API_KEY``).
    ``from_log`` partitions ``reports/experiment_log.jsonl`` via dojo
    ``split_local_api`` / ``get_suite("local_vs_api")``.
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
        compared = scoring.compare_from_records(experiment_log.load())
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
    if comparison:
        scoring.emit_local_vs_api_scorecard(
            comparison, run_id=experiment_name or "sandbox_local_vs_api"
        )
    record = experiment_log.new_record(
        experiment_name=experiment_name or "sandbox_local_vs_api",
        task="local_vs_api",
        profile=activation.profile_name,
        provider=os.environ.get("DEFAULT_PROVIDER"),
        model=model,
        prompt_version=prompt_version or "mailroom-default",
        mock=mock,
        dataset_fingerprint=plan["fingerprint"],
        n=scores["n"],
        scores=scores,
        serving_kind="local",
        tracing_backend=tracing.tracing_backend(),
        tags=tracing.default_tags("source-serving", "local-vs-api"),
        local_vs_api=compared,
        serving_markdown=markdown,
        source=source,
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "comparison": compared, "record": record}


def run_pipeline_eval(
    *,
    mock: bool = True,
    sample: int | None = None,
    dry_run: bool = False,
    experiment_name: str | None = None,
    profile: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    agent_models: dict[str, str] | None = None,
    connected: bool = True,
) -> dict[str, Any]:
    rows = load_manifest()
    if sample:
        rows = rows[: sample]
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
    session = tracing.session_id_for("pipeline")
    results = []
    for row in rows:
        results.append(_run_pipeline_doc(row, mock=mock, session_id=session, experiment_name=experiment_name))
    expected = [r["expected_doc_class"] for r in rows]
    predicted = [r.get("doc_type") or "unknown" for r in results]
    class_scores = scoring.score_classification(expected, predicted)
    stage_expected = [str(r.get("expected_stage") or "archived") for r in rows]
    stage_predicted = [str(r.get("stage") or "unknown") for r in results]
    stage_scores = scoring.score_stage(stage_expected, stage_predicted)
    extract_vals: list[float] = []
    if connected:
        for row, result in zip(rows, results):
            expected_fields = parse_expected_fields(row) or {}
            if not expected_fields:
                continue
            scored = scoring.score_extraction_row(
                row["expected_doc_class"],
                result.get("extracted_data") or {},
                expected_fields,
                doc_text=fixture_file(row).read_text(encoding="utf-8") if fixture_file(row).is_file() else None,
            )
            value = scored.get("overall_extraction_score")
            if isinstance(value, (int, float)):
                extract_vals.append(float(value))
    routing_expected = ["review" if s == "review" else "continue" for s in stage_expected]
    routing_predicted = ["review" if s == "review" else "continue" for s in stage_predicted]
    routing = scoring.score_classification(routing_expected, routing_predicted)
    scores = {
        **class_scores,
        "class_correct": class_scores.get("exact_match"),
        "stage_correct": stage_scores.get("stage_correct"),
        "extraction_overall": scoring.mean_or_zero(extract_vals) if extract_vals else None,
        "routing_accuracy": routing.get("exact_match"),
        "connected": connected,
    }
    tracing.emit_langfuse_score("class_correct", float(scores["class_correct"] or 0))
    tracing.emit_langfuse_score("stage_correct", float(scores["stage_correct"] or 0))
    if scores["extraction_overall"] is not None:
        tracing.emit_langfuse_score("extraction_overall_score", float(scores["extraction_overall"]))
    tracing.flush_traces()
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
        session_id=session,
        trace_ids=tracing.last_trace_ids(),
    )
    experiment_log.append(record)
    return {**plan, "scores": scores, "docs": results}


def _langchain_mock_patches(expect: dict[str, Any]) -> list:
    """Mock patches for mailroom v0.6.0's vendored LangChain agents.

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
    except Exception:
        return []

    class _SandboxFakeLLM(FakeLangChainLLM):
        def _run(self, messages):
            self.calls += 1
            text = user_text_from_messages(messages)
            parsed = fake_structured_payload(text, expect)
            return self._make_message(parsed)

    fake = _SandboxFakeLLM()
    return [patch.object(lc_base.BaseAgent, "llm", new=lambda self: fake)]


def _run_pipeline_doc(
    row: dict[str, Any],
    *,
    mock: bool,
    session_id: str | None = None,
    experiment_name: str | None = None,
) -> dict[str, Any]:
    """Run one fixture through mailroom ``run_pipeline`` when available."""
    src = resolve_mailroom_src()
    path = fixture_file(row)
    expect = _expect_from_row(row)
    public_gt = tracing.public_ground_truth(row)
    fallback = {
        "id": row.get("id"),
        "doc_type": _classify_mock(row) if mock else None,
        "stage": row.get("expected_stage"),
        "extracted_data": parse_expected_fields(row) if mock else None,
        "offline_fallback": True,
    }
    try:
        from graph.build_graph import run_pipeline  # type: ignore
        from pipeline.bins import inbox_dir  # type: ignore
    except Exception:
        with tracing.document_pipeline_trace(
            seed=str(row.get("id") or path.name),
            session_id=session_id or tracing.session_id_for("pipeline"),
            input={"filename": path.name, "matter_id": f"SANDBOX-{row.get('id')}", **public_gt},
            metadata={"pipeline": "mailroom", "source": "sandbox-fixtures", "run_id": experiment_name, "attempt": 1},
            tags=tracing.default_tags("source-fixtures"),
        ):
            with tracing.child_observation("pipeline-result", as_type="generation", input=public_gt):
                pass
        return fallback

    import shutil

    inbox = inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    queued = inbox / path.name
    shutil.copyfile(path, queued)
    matter_id = f"SANDBOX-{row.get('id')}"
    # Mailroom strips expected_fields before the trace; keep it for in-graph scoring.
    gt = {**public_gt, "expected_doc_class": row["expected_doc_class"]}
    fields = parse_expected_fields(row)
    if fields:
        gt["expected_fields"] = fields

    def _mock_get_llm(agent_name: str):
        return fake_client(expect), "mock-model"

    kwargs = {
        "source": "sandbox-fixtures",
        "ground_truth": gt,
        "session_id": session_id or matter_id,
    }
    if mock:
        with ExitStack() as stack:
            stack.enter_context(
                patch("llm.client.get_llm", side_effect=_mock_get_llm)
            )
            stack.enter_context(
                patch("agents.base.get_llm", side_effect=_mock_get_llm)
            )
            for lc_patch in _langchain_mock_patches(expect):
                stack.enter_context(lc_patch)
            result = run_pipeline(queued, matter_id, **kwargs)
    else:
        result = run_pipeline(queued, matter_id, **kwargs)
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
