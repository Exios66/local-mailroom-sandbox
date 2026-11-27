"""Step-up verdict on the new documents and offline threshold evidence (offline, deterministic)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import gate, gate_compare
from mailroom_sandbox.job.gate import Bars

LABELS = {"entity_name": "Acme Corp", "record_type": "bylaws"}


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


def _run(root, name, docs):
    """docs: dicts with id and optional cls/stage/score/confidence/no_confidence."""
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            cls = d.get("cls", "corporate_record")
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": cls,
                                 "expected_fields": json.dumps(d.get("labels", LABELS))}) + "\n")
            pred = {"stage": d.get("stage", "archived"), "doc_type": cls, "_score": d.get("score", 0.95),
                    "review_causes": []}
            if not d.get("no_confidence"):
                pred["extraction_confidence"] = d.get("confidence", 1.0)
            it.write(json.dumps({"item_id": d["id"], "ok": True, "error": None, "prompt_tokens": 10,
                                 "completion_tokens": 5, "pred": pred}) + "\n")
    return run


def _ids(*names):
    return [{"id": n} for n in names]


def test_new_docs_lane_uses_only_new_documents(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", _ids("a", "b", "c", "d"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["new_docs"] == ["c", "d"]
    assert out["new_docs_gate"]["n"] == 2
    assert [d["id"] for d in out["new_docs_gate"]["docs"]] == ["c", "d"]
    assert out["nested"] is True
    assert out["shared_paired"]["shared_docs"] == 2
    assert out["verdict"] == {"pass": True, "reasons": []}


def test_new_docs_gate_failure_fails_the_step_up(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a"))
    nxt = _run(tmp_path, "next", _ids("a") + [{"id": "c", "score": 0.5}, {"id": "d", "score": 0.5}])
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["verdict"]["pass"] is False
    assert any("wrong_archive_rate" in r for r in out["verdict"]["reasons"])
    # the shared document does not count toward the new-documents verdict
    assert out["new_docs_gate"]["pooled"]["wrong_archive_rate"] == 1.0


def test_non_nested_slices_fail(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "gone"))
    nxt = _run(tmp_path, "next", _ids("a", "c"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["nested"] is False
    assert out["new_docs"] == ["c"]
    assert out["verdict"]["pass"] is False
    assert "slices do not nest" in out["verdict"]["reasons"]


def test_no_new_documents_fails(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", _ids("a", "b"))
    out = gate_compare.step_up(prev, nxt, Bars(), audit=False)
    assert out["new_docs"] == [] and out["verdict"]["pass"] is False
    assert "no new documents" in out["verdict"]["reasons"]


def test_only_ids_restricts_rates_buckets_and_n(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "score": 0.5}, {"id": "b"}, {"id": "c", "stage": "review"}])
    full = gate.gate_report(run, Bars(), audit=False)
    sub = gate.gate_report(run, Bars(), audit=False, only_ids={"b", "c"})
    assert full["n"] == 3 and sub["n"] == 2
    assert [d["id"] for d in sub["docs"]] == ["b", "c"]
    assert sub["pooled"]["wrong_archive_rate"] == 0
    assert sub["pooled"]["review_rate"] == 0.5
    assert [d["id"] for b in sub["buckets"].values() for d in b["docs"]] == ["c"]
    assert gate.gate_report(run, Bars(), audit=False, only_ids=None)["n"] == 3


def test_threshold_evidence_counts(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "confidence": 0.95, "score": 0.5},
                               {"id": "b", "confidence": 0.95}, {"id": "c", "confidence": 1.0}])
    out = gate_compare.threshold_evidence(run, Bars())
    assert out["label"] == "upper bound: assumes the judge rejects every caught wrong archive"
    keys = ("extra_judged", "wrong_archives_caught_upper_bound", "correct_archives_disturbed")
    at = out["pooled"]["thresholds"][0.96]
    assert {k: at[k] for k in keys} == {"extra_judged": 2, "wrong_archives_caught_upper_bound": 1,
                                        "correct_archives_disturbed": 1}
    low = out["pooled"]["thresholds"][0.90]
    assert {k: low[k] for k in keys} == dict.fromkeys(keys, 0)
    assert out["pooled"]["thresholds"][1.01]["extra_judged"] == 3  # 1.01 sends every archive to the judge
    assert out["classes"]["corporate_record"]["thresholds"][0.96] == at
    assert out["pooled"]["no_confidence"] == 0 and out["pooled"]["archived"] == 3


def test_threshold_evidence_counts_missing_confidence_separately(tmp_path):
    run = _run(tmp_path, "r", [{"id": "a", "confidence": 0.95}, {"id": "b", "no_confidence": True, "score": 0.5},
                               {"id": "c", "no_confidence": True}, {"id": "d", "stage": "review"},
                               {"id": "e", "cls": "merger_agreement", "confidence": 0.5}])
    out = gate_compare.threshold_evidence(run, Bars())
    pooled = out["pooled"]
    assert pooled["archived"] == 3 and pooled["no_confidence"] == 2
    assert pooled["no_confidence_by_outcome"] == {"wrong_archive": 1, "correct_archive": 1}
    assert pooled["thresholds"][0.96]["extra_judged"] == 1  # the 2 unconfident docs are not in the counts
    assert "merger_agreement" not in out["classes"]  # reported never, gated only


def test_rerun_on_the_same_slice_passes_when_not_worse(tmp_path):
    """A fix re-run on the same documents is a paired comparison, not a step-up (review I1)."""
    prev = _run(tmp_path, "prev", [{"id": "a", "score": 0.5}, {"id": "b"}])
    nxt = _run(tmp_path, "next", _ids("a", "b"))
    out = gate_compare.rerun(prev, nxt, Bars(), audit=False)
    assert out["same_documents"] is True
    assert out["prev_pooled"]["wrong_archive_rate"] == 0.5
    assert out["next_pooled"]["wrong_archive_rate"] == 0.0
    assert out["verdict"] == {"pass": True, "reasons": []}


def test_rerun_fails_when_wrong_archives_or_reviews_rise(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b", "c"))
    nxt = _run(tmp_path, "next", [{"id": "a", "score": 0.5}, {"id": "b", "stage": "review"}, {"id": "c"}])
    out = gate_compare.rerun(prev, nxt, Bars(), audit=False)
    assert out["verdict"]["pass"] is False
    assert any(r.startswith("wrong_archive_rate rose") for r in out["verdict"]["reasons"])
    assert any(r.startswith("review_rate rose") for r in out["verdict"]["reasons"])


def test_rerun_on_different_documents_fails(tmp_path):
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", _ids("a", "c"))
    out = gate_compare.rerun(prev, nxt, Bars(), audit=False)
    assert out["same_documents"] is False
    assert "re-run drew different documents" in out["verdict"]["reasons"]


def test_threshold_evidence_projects_rates(tmp_path):
    """Per candidate threshold, the gate's rates if every caught wrong archive went to review (review I7)."""
    run = _run(tmp_path, "r", [{"id": "a", "confidence": 0.95, "score": 0.5},  # wrong, caught at t > 0.95
                               {"id": "b", "confidence": 0.99, "score": 0.5},  # wrong, caught only at 1.01
                               {"id": "c", "confidence": 0.95},                # correct, disturbed at t > 0.95
                               {"id": "d", "confidence": 1.0},
                               {"id": "e", "stage": "review"}])
    pooled = gate_compare.threshold_evidence(run, Bars())["pooled"]
    assert pooled["baseline"] == {"n": 5, "review_rate": 0.2, "wrong_archive_rate": 0.5}
    at = pooled["thresholds"][0.96]
    assert at["wrong_archive_rate"] == 1 / 3          # 1 wrong left of 3 scorable archives left
    assert at["review_rate"] == 2 / 5                 # the review + the caught wrong archive
    assert at["review_rate_if_disturbed_rejected"] == 3 / 5  # plus the disturbed correct archive
    top = pooled["thresholds"][1.01]
    assert top["wrong_archive_rate"] == 0.0 and top["review_rate"] == 3 / 5


def test_rerun_with_different_labels_on_the_same_documents_fails(tmp_path):
    """Same ids, different gold (interim labels in one run only): not a like-for-like re-run (#311 review)."""
    prev = _run(tmp_path, "prev", _ids("a", "b"))
    nxt = _run(tmp_path, "next", [{"id": "a"}, {"id": "b", "labels": {**LABELS, "jurisdiction": "Nevada"}}])
    out = gate_compare.rerun(prev, nxt, Bars(), audit=False)
    assert out["label_mismatch"] == ["b"]
    assert "re-run labels differ on 1 document(s): b" in out["verdict"]["reasons"]
    assert gate_compare.same_documents(prev, nxt) is True  # still routed as a re-run, which then fails


def test_paired_ci_bounds_are_json_safe(tmp_path):
    """One scored pair gives no interval: null, not NaN, so gate.json stays strict JSON (#311 review)."""
    prev = _run(tmp_path, "prev", _ids("a"))
    nxt = _run(tmp_path, "next", _ids("a"))
    out = gate_compare.rerun(prev, nxt, Bars(), audit=False)
    json.dumps(out, allow_nan=False)


# --- phase 4: judge_compare (the stage 1 and stage 2 success rules) -------------------------------

QWEN = "qwen/qwen3.7-plus"


def _judge_run(root, name, docs):
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": "corporate_record",
                                 "expected_fields": json.dumps(LABELS)}) + "\n")
            pred = {"stage": d.get("stage", "archived"), "doc_type": "corporate_record", "review_causes": [],
                    "extraction_confidence": 1.0, "_score": d.get("score", 0.95),
                    "judge_rulings": [{"pass": 1, "mode": d.get("mode", "correct"), "ruling": "accept", "score": 0.9,
                                       "reason": "", "fixes": [], "retry_fields": [], "wrong_fields": [],
                                       "model": QWEN}] * d.get("rulings", 1)}
            usage = {"judge": {"calls": d.get("judge_calls", 1), "prompt_tokens": 1, "completion_tokens": 1,
                               "models": [QWEN]},
                     "arbiter": {"calls": d.get("arbiter_calls", 0), "prompt_tokens": 0, "completion_tokens": 0,
                                 "models": []}}
            it.write(json.dumps({"item_id": d["id"], "ok": not d.get("crash"), "error": d.get("error", "x") if d.get("crash") else None,
                                 "prompt_tokens": 1, "completion_tokens": 1, "llm_calls": 3, "usage_by_agent": usage,
                                 "reported_cost_usd": d.get("cost", 0.01), "pred": pred}) + "\n")
    return run


def _docs(n, **over):
    return [{"id": f"d{i}", **over} for i in range(n)]


def _rule(out, name):
    return next(c for c in out["checks"] if c["rule"] == name)


def test_judge_compare_applies_every_success_rule(tmp_path):
    base = _judge_run(tmp_path, "base", _docs(30, judge_calls=2, arbiter_calls=2, mode="verify", cost=0.02))
    good = _judge_run(tmp_path, "good", _docs(30, judge_calls=1, cost=0.01))
    out = gate_compare.judge_compare(base, good, Bars(), stage=2)
    assert out["verdict"]["pass"] is True, out
    for name in ("judge_calls_cut", "judge_cost_by_class", "score_margin", "wrong_archives", "ceiling_crashes"):
        assert _rule(out, name)["pass"] is True, name
    assert _rule(out, "judge_calls_cut")["baseline"] == pytest.approx(4.0)
    bad = _judge_run(tmp_path, "bad", _docs(28, judge_calls=3, arbiter_calls=1, cost=0.05, score=0.5)
                     + [{"id": "d28", "crash": True}, {"id": "d29", "crash": True}])
    out = gate_compare.judge_compare(base, bad, Bars(), stage=2)
    assert out["verdict"]["pass"] is False
    for name in ("judge_calls_cut", "judge_cost_by_class", "score_margin", "wrong_archives", "ceiling_crashes"):
        assert _rule(out, name)["pass"] is False, name
    lower = _rule(out, "score_margin")
    assert lower["ci_low"] < -2.0 and "delta" in lower
    stage1 = gate_compare.judge_compare(base, bad, Bars(), stage=1)
    assert _rule(stage1, "score_margin")["gating"] is False  # reported, not gating, in the pilot
    assert stage1["verdict"]["reasons"] and not any("score_margin" in r for r in stage1["verdict"]["reasons"])


def test_judge_compare_counts_only_the_call_ceiling_as_a_ceiling_crash(tmp_path):
    base = _judge_run(tmp_path, "base", _docs(3, mode="verify"))
    capped = _judge_run(tmp_path, "capped", _docs(2) + [
        {"id": "d2", "crash": True, "error": "call refused: api_cost_cap_usd=44.4 reached ($44.40 spent)"}])
    assert _rule(gate_compare.judge_compare(base, capped, Bars()), "ceiling_crashes")["ceiling"] == 0
    ceiling = _judge_run(tmp_path, "ceiling", _docs(2) + [
        {"id": "d2", "crash": True, "error": "call refused: this document made 40 calls (per-document ceiling 40)"}])
    assert _rule(gate_compare.judge_compare(base, ceiling, Bars()), "ceiling_crashes")["ceiling"] == 1


def test_judge_compare_prices_both_arms_on_the_same_documents(tmp_path, monkeypatch):
    from mailroom_sandbox.job import gate

    base = _judge_run(tmp_path, "base", _docs(2, mode="verify", cost=0.02))
    new = _judge_run(tmp_path, "new", _docs(2, cost=0.01))
    real = gate.doc_cost
    # d0's cost is unknown in the baseline: only d1 (0.02 vs 0.01) may be compared, not d0's 0.01 too.
    monkeypatch.setattr(gate, "doc_cost", lambda item: None if item.get("item_id") == "d0"
                        and item.get("reported_cost_usd") == 0.02 else real(item))
    classes = _rule(gate_compare.judge_compare(base, new, Bars()), "judge_cost_by_class")["classes"]
    assert all(v["paired_documents"] == 1 for v in classes.values()), classes


def test_judge_compare_refuses_runs_with_different_documents(tmp_path):
    base = _judge_run(tmp_path, "base", _docs(3, mode="verify"))
    other = _judge_run(tmp_path, "other", [{"id": "z"}])
    with pytest.raises(ValueError, match="same documents"):
        gate_compare.judge_compare(base, other, Bars())
