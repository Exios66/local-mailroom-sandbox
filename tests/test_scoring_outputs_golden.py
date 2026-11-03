"""Frozen sandbox scoring outputs (S0): parity baseline for the dojo refresh.

For every case in ``fixtures/scoring_golden/inputs.json`` (the dojo D1 inputs,
copied verbatim) three output kinds are recorded in ``outputs.json``:

- ``score_row``: ``score_extraction_row(doc_type, predicted, expected,
  doc_text=, doc_subclass=, expected_subclass=)``.
- ``scores_jsonl``: the line ``emit(ScoreRecord(...))`` writes through
  ``LocalManifestSink`` for that row (agent ``extraction``, metric
  ``overall_extraction_score``, value taken from the score row, or ``None``).
- ``serving_record``: ``serving_parity.to_dojo_serving_record`` applied to a
  minimal, fixed run record (model ``golden-model``, 1200 ms latency, 100/50
  tokens, ``n=1``) carrying the row's numeric scores under ``scores``.

Normalised for determinism: ``ScoreRecord.timestamp`` is fixed to ``0.0``,
``run_id`` is ``golden-run``, ``doc_id`` is the case id; NaN becomes ``"NaN"``;
sets are sorted; all keys are sorted. A case that raises is recorded as
``{"error": "<ExceptionType>"}``.

Dojo settings are process-wide and cached; other tests mutate them (taxonomy
wiring, ``configure``), which shifted ``ambiguous_fields``. The test therefore
drops the settings cache before and after, so cases always run on the dojo
defaults (the sandbox's ``src`` never wires a taxonomy, so that is what it
runs with).

Regenerate after an intentional behaviour change with
``SCORING_GOLDEN_WRITE=1 pytest tests/test_scoring_outputs_golden.py``.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from pathlib import Path
from typing import Any

import pytest

from llm_dojo_scoring import ScoreRecord
from llm_dojo_scoring.config import clear_settings_cache
from mailroom_sandbox.eval.scoring import emit, score_extraction_row
from mailroom_sandbox.eval.serving_parity import to_dojo_serving_record

FIXTURES = Path(__file__).parent / "fixtures" / "scoring_golden"
INPUTS = FIXTURES / "inputs.json"
OUTPUTS = FIXTURES / "outputs.json"
KINDS = ("score_row", "scores_jsonl", "serving_record")


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value) if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _numeric(row: Any) -> dict[str, float]:
    if not isinstance(row, dict):
        return {}
    return {
        k: v for k, v in sorted(row.items())
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    }


def _capture_case(case: dict, tmp_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        row = score_extraction_row(
            case["doc_type"],
            case["predicted"],
            case["expected"],
            doc_text=case.get("doc_text"),
            doc_subclass=case.get("doc_subclass"),
            expected_subclass=case.get("expected_subclass"),
        )
    except Exception as exc:
        err = {"error": type(exc).__name__}
        return {kind: dict(err) for kind in KINDS}
    out["score_row"] = _jsonable(row)

    value = row.get("overall_extraction_score") if isinstance(row, dict) else None
    sink = tmp_path / f"{case['case_id']}.jsonl"
    try:
        emit(
            ScoreRecord(
                agent="extraction",
                metric="overall_extraction_score",
                value=value if isinstance(value, (int, float)) else None,
                doc_id=case["case_id"],
                run_id="golden-run",
                metadata={"doc_type": case["doc_type"]},
                timestamp=0.0,
            ),
            sink,
        )
        lines = sink.read_text().splitlines()
        out["scores_jsonl"] = [json.loads(line) for line in lines]
    except Exception as exc:
        out["scores_jsonl"] = {"error": type(exc).__name__}

    try:
        out["serving_record"] = _jsonable(
            to_dojo_serving_record(
                {
                    "run_id": "golden-run",
                    "model": "golden-model",
                    "task": "extract",
                    "n": 1,
                    "latency_ms": 1200,
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                    "scores": _numeric(row),
                }
            )
        )
    except Exception as exc:
        out["serving_record"] = {"error": type(exc).__name__}
    return out


def _capture_all(tmp_path: Path) -> dict[str, Any]:
    cases = json.loads(INPUTS.read_text())["cases"]
    return {c["case_id"]: _capture_case(c, tmp_path) for c in cases}


def _dump(data: Any) -> str:
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


@pytest.fixture
def default_dojo_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_scoring_outputs_match_goldens(tmp_path, default_dojo_settings):
    actual = _capture_all(tmp_path)
    if os.environ.get("SCORING_GOLDEN_WRITE") == "1":
        OUTPUTS.write_text(_dump(actual))
        pytest.skip(f"regenerated {OUTPUTS.name} ({len(actual)} cases)")
    expected = json.loads(OUTPUTS.read_text())
    assert set(actual) == set(expected)
    # Round-trip through JSON so tuples/ints compare like the stored file.
    actual = json.loads(_dump(actual))
    bad = [
        f"{cid}:{kind}"
        for cid in sorted(expected)
        for kind in KINDS
        if actual[cid].get(kind) != expected[cid].get(kind)
    ]
    assert not bad, f"golden drift in {len(bad)} outputs, first: {bad[:10]}"
