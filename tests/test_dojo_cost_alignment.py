"""The sandbox's pre-priced serving record follows the dojo's repaired usage rules.

A cost written by ``record_from_run`` is authoritative in the dojo, so the sandbox
must apply the same gates the dojo applies when it derives a cost itself:
dojo 0.24.2 (an unobserved request makes the run cost unknown) and DMR-113
(explicit zero usage is observed; an all-zero priced run costs 0.0).
"""

from __future__ import annotations

import pytest
from llm_dojo_scoring.serving import normalize_serving_record

from mailroom_sandbox.job.metrics import record_from_run
from mailroom_sandbox.job.usage_capture import usage_from_openai_response

MODEL = "Qwen/Qwen3-8B"  # priced in the sandbox table


def _record(items, model=MODEL):
    return record_from_run(
        run_id="r", spec_hash="h", task="pipeline", profile="openrouter", model=model,
        prompt_version="v", dataset_fingerprint="f", items=items,
    )


def test_complete_usage_is_priced():
    rec = _record([{"ok": True, "prompt_tokens": 1000, "completion_tokens": 100}] * 2)
    assert rec["estimated_cost_usd"] > 0 and "usage_unobserved_items" not in rec


def test_one_unobserved_ok_item_makes_the_cost_unknown():
    rec = _record([{"ok": True, "prompt_tokens": 1000, "completion_tokens": 100}, {"ok": True}])
    assert "estimated_cost_usd" not in rec and rec["usage_unobserved_items"] == 1
    assert rec["total_tokens"] == 1100  # the tokens that were observed are still reported


def test_failed_items_without_a_response_do_not_block_the_estimate():
    rec = _record([{"ok": True, "prompt_tokens": 1000, "completion_tokens": 100}, {"ok": False, "error": "timeout"}])
    assert rec["estimated_cost_usd"] > 0


def test_one_component_usage_is_observed():
    rec = _record([{"ok": True, "prompt_tokens": 1000}, {"ok": True, "completion_tokens": 50}])
    assert rec["estimated_cost_usd"] > 0


def test_explicit_zero_usage_on_a_priced_model_costs_a_known_zero():
    rec = _record([{"ok": True, "prompt_tokens": 0, "completion_tokens": 0}] * 3)
    assert rec["estimated_cost_usd"] == 0.0 and rec["cost_per_document"] == 0.0


@pytest.mark.parametrize("items", [
    [{"ok": True}, {"ok": True}],  # nothing observed
    [{"ok": True, "prompt_tokens": 0, "completion_tokens": 0}, {"ok": True}],  # zero + unobserved
])
def test_missing_usage_never_becomes_zero(items):
    assert "estimated_cost_usd" not in _record(items)


def test_zero_usage_on_an_unpriced_model_stays_unknown():
    assert "estimated_cost_usd" not in _record([{"ok": True, "prompt_tokens": 0, "completion_tokens": 0}], model="nope/unpriced")


@pytest.mark.parametrize("items", [
    [{"ok": True, "prompt_tokens": 1000, "completion_tokens": 100}] * 2,
    [{"ok": True, "prompt_tokens": 1000, "completion_tokens": 100}, {"ok": True}],
    [{"ok": True, "prompt_tokens": 0, "completion_tokens": 0}],
])
def test_dojo_reads_the_same_cost_the_sandbox_wrote(items):
    rec = _record(items)
    run = normalize_serving_record(rec)
    assert run.estimated_cost_usd == rec.get("estimated_cost_usd")


@pytest.mark.parametrize(("usage", "expected"), [
    ({"prompt_tokens": 0, "completion_tokens": 0}, {"prompt_tokens": 0, "completion_tokens": 0}),
    ({"prompt_tokens": 0, "input_tokens": 7, "completion_tokens": 3}, {"prompt_tokens": 0, "completion_tokens": 3}),
    ({"input_tokens": 7, "output_tokens": 0}, {"prompt_tokens": 7, "completion_tokens": 0}),
    ({}, {}),
])
def test_openai_usage_keeps_an_explicit_zero(usage, expected):
    class _Resp:
        pass

    resp = _Resp()
    resp.usage = usage
    assert usage_from_openai_response(resp) == expected


def test_tiered_model_prices_each_item_at_its_own_tier():
    # qwen3.7-flash: $0.03/$0.13 per 1M below 32k prompt tokens, $0.10/$0.40 from 32k.
    items = [{"ok": True, "prompt_tokens": 3_700, "completion_tokens": 90, "llm_calls": 1}] * 16 + [
        {"ok": True, "prompt_tokens": 80_000, "completion_tokens": 130, "llm_calls": 1}] * 4
    rec = _record(items, model="qwen/qwen3.7-flash")
    small = 16 * (3_700 * 0.03 + 90 * 0.13) / 1e6
    large = 4 * (80_000 * 0.10 + 130 * 0.40) / 1e6
    assert rec["estimated_cost_usd"] == pytest.approx(small + large, abs=1e-6)
    flat = (16 * 3_700 + 4 * 80_000) * 0.03 / 1e6  # the old run-total pricing: every call in the cheap tier
    assert rec["estimated_cost_usd"] > 2 * flat


def test_multi_call_items_that_may_straddle_a_tier_are_flagged():
    # Items record call totals only: a 3-call item with 60k prompt tokens may have one call over the
    # 32k threshold, so it is priced at its average call's tier and counted as approximate.
    rec = _record([{"ok": True, "prompt_tokens": 60_000, "completion_tokens": 300, "llm_calls": 3},
                   {"ok": True, "prompt_tokens": 9_000, "completion_tokens": 300, "llm_calls": 3},
                   {"ok": True, "prompt_tokens": 80_000, "completion_tokens": 100, "llm_calls": 1}],
                  model="qwen/qwen3.7-flash")
    assert rec["cost_tier_approximate_items"] == 1
    assert "cost_tier_approximate_items" not in _record(
        [{"ok": True, "prompt_tokens": 80_000, "completion_tokens": 100, "llm_calls": 1}], model="qwen/qwen3.7-flash")


def test_per_call_usage_prices_each_call_at_its_own_tier():
    # Two calls of 10k and 50k prompt tokens: the 50k call is in the upper tier even though the average is not.
    rec = _record([{"ok": True, "prompt_tokens": 60_000, "completion_tokens": 20, "llm_calls": 2,
                    "call_usage": [[10_000, 10], [50_000, 10]]}], model="qwen/qwen3.7-flash")
    expected = (10_000 * 0.03 + 10 * 0.13 + 50_000 * 0.10 + 10 * 0.40) / 1e6
    assert rec["estimated_cost_usd"] == pytest.approx(expected, abs=1e-6)
    assert "cost_tier_approximate_items" not in rec


def test_pipeline_per_call_usage_survives_persistence_into_the_serving_cost(monkeypatch, tmp_path):
    # Through run_pipeline_eval: the document's two calls are recorded in the vendored accumulator,
    # captured per call, persisted by the job runner, then priced call by call in the serving record.
    from pipeline.limits import record_usage

    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.runner import _persist_isolated_items

    def fake_doc(row, **_):
        record_usage({"prompt_tokens": 10_000, "completion_tokens": 10}, model="qwen/qwen3.7-flash", agent="sorter")
        record_usage({"prompt_tokens": 50_000, "completion_tokens": 10}, model="qwen/qwen3.7-flash", agent="specialist")
        return {"stage": "archived", "doc_type": "contract"}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    # A non-mock eval appends to reports/experiment_log.jsonl; keep this synthetic record out of it.
    logged = []
    monkeypatch.setattr(runners.experiment_log, "append", lambda record, path=None: logged.append(record) or path)
    rows = []
    runners.run_pipeline_eval(profile="ollama", rows=[{"id": "a", "expected_doc_class": "contract", "text": "x"}],
                              mock=False, connected=False, row_cb=rows.append)
    assert rows[0]["call_usage"] == [[10_000, 10], [50_000, 10]] and rows[0]["llm_calls"] == 2
    assert len(logged) == 1
    store = RunStore(tmp_path / "r")
    _persist_isolated_items(store, rows)
    items = store.load_items()
    assert items[0]["call_usage"] == [[10_000, 10], [50_000, 10]]
    rec = _record(items, model="qwen/qwen3.7-flash")
    assert rec["estimated_cost_usd"] == pytest.approx((10_000 * 0.03 + 10 * 0.13 + 50_000 * 0.10 + 10 * 0.40) / 1e6, abs=1e-6)
    assert "cost_tier_approximate_items" not in rec
