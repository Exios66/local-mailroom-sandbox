"""Routing calibration: gate inputs recorded, locked per-run thresholds, post-run audit, cost envelope."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mailroom_sandbox.job import node_trace, preflight, routing_audit
from mailroom_sandbox.job.context_plan import plan
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, core_hash, spec_core

# --- gate inputs ----------------------------------------------------------------


def test_extract_nodes_record_the_judge_gate_confidence():
    got = node_trace.decisions_for("extract", {"extraction_confidence": 0.97, "decisions": []})
    assert got == [{"question": "extraction_confidence", "type": "score", "answer": None, "p": 0.97,
                    "expected": None, "options": None, "source": "agent"}]
    assert node_trace.decisions_for("retry_extract", {"extraction_confidence": 0.5})[0]["p"] == 0.5
    assert node_trace.decisions_for("extract", {"extraction_confidence": "n/a"}) == []
    assert node_trace.decisions_for("judge_verify", {"extraction_confidence": 0.9}) == []


# --- run-scoped thresholds ------------------------------------------------------------


def _spec(**kw):
    return RunSpec(run_id="r-conf", task="pipeline", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, **kw)


def test_confidence_block_validates_keys_ranges_and_order():
    ok = _spec(confidence={"arbiter_retry_max": 1,
                           "by_class": {"contract": {"high": 0.95, "judge_band_high": 1.01}}})
    assert ok.confidence["by_class"]["contract"]["high"] == 0.95
    for bad in ({"hgh": 0.9}, {"high": 1.5}, {"low": 0.9, "high": 0.8}, {"retry_max": -1},
                {"judge_max_passes": True}, {"by_class": {"contract": {"low": "x"}}}, {"by_class": []}):
        with pytest.raises(ValidationError):
            _spec(confidence=bad)


def test_confidence_is_hashed_only_when_set():
    plain = _spec()
    assert "confidence" not in spec_core(plain, source_sha256="0" * 64)
    tuned = _spec(confidence={"by_class": {"contract": {"high": 0.95}}})
    assert core_hash(spec_core(tuned, source_sha256="0" * 64)) != core_hash(spec_core(plain, source_sha256="0" * 64))


def _local_pipeline(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    path = tmp_path / "p.jsonl"
    path.write_text(json.dumps({"id": "p0", "filename": "p0.txt", "doc_text": "agreement " * 50,
                                "expected_doc_class": "contract", "expected": "contract"}) + "\n")
    kw.setdefault("run_id", "run-conf")
    return RunSpec(task="pipeline", dataset=DatasetSpec(local_path=f"file://{path}", limit=1),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"}, job={"mock": True}, **kw)


def test_preflight_locks_the_thresholds_and_refuses_unknown_classes(tmp_path, monkeypatch):
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    conf = {"by_class": {"contract": {"high": 0.95, "arbiter_retry_max": 1}}}
    report = preflight.preflight(_local_pipeline(tmp_path, monkeypatch, confidence=conf), offline=True)
    assert report["status"] == "prepared", report
    assert RunStore(run_dir(report["run_id"])).read_lock()["confidence"] == conf

    bad = preflight.preflight(_local_pipeline(tmp_path, monkeypatch, run_id="run-conf-bad",
                                              confidence={"by_class": {"memo": {"high": 0.9}}}), offline=True)
    assert bad["status"] == "failed"
    assert "unknown or retired doc classes ['memo']" in json.dumps(bad["checks"])


def test_activation_applies_run_thresholds_over_vendor_and_overlay(monkeypatch):
    pytest.importorskip("pipeline.config")
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import runtime

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    runtime.activate("modal-vllm", load_env_file=False,
                     confidence={"by_class": {"contract": {"high": 0.95, "arbiter_retry_max": 1}}})
    try:
        th = get_confidence_thresholds("contract")
        assert th["high"] == 0.95 and th["arbiter_retry_max"] == 1
        assert get_confidence_thresholds("merger_agreement")["high"] == 0.98  # untouched class
    finally:
        runtime.activate("modal-vllm", load_env_file=False)
    assert get_confidence_thresholds("contract")["high"] == 0.98


# --- post-run audit -------------------------------------------------------------------


def _node(doc, node, ts, decisions=None):
    return {"doc": doc, "node": node, "status": "done", "ts": ts, "ms": 10, "decisions": decisions or []}


def _verdict(v):
    return [{"question": "extraction_verdict", "type": "score", "answer": v}]


def _store(tmp_path, docs):
    """docs: (id, class, chars, stage, quality, nodes)."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "spec.lock.json").write_text(json.dumps({"run_id": "r-audit", "engine": {"model": "qwen/qwen3.7-flash"}}))
    with open(root / "dataset.jsonl", "w") as ds, open(root / "items.jsonl", "w") as it, open(root / "nodes.jsonl", "w") as nd:
        for doc_id, cls, chars, stage, quality, nodes in docs:
            ds.write(json.dumps({"id": doc_id, "expected_doc_class": cls, "doc_text": "x" * chars}) + "\n")
            it.write(json.dumps({"item_id": doc_id, "pred": {"stage": stage},
                                 "score": {"overall_extraction_score": quality}}) + "\n")
            for n in nodes:
                nd.write(json.dumps(n) + "\n")
    return root


def test_audit_flags_a_judge_that_never_passes_and_retries_without_yield(tmp_path):
    def looped(doc):
        return [_node(doc, "classify", 1, [{"question": "doc_type", "answer": "contract", "p": 0.95}]),
                _node(doc, "retry_classify", 2, [{"question": "doc_type", "answer": "contract", "p": 0.95}]),
                _node(doc, "extract", 3), _node(doc, "judge_verify", 4, _verdict("partial")),
                _node(doc, "arbiter", 5, [{"question": "arbiter_route", "answer": "retry_extraction"}]),
                _node(doc, "retry_extract", 6), _node(doc, "judge_verify", 7, _verdict("partial")),
                _node(doc, "arbiter", 8, [{"question": "arbiter_route", "answer": "retry_extraction"}]),
                _node(doc, "retry_extract", 9), _node(doc, "judge_verify", 10, _verdict("partial"))]
    root = _store(tmp_path, [(f"c{i}", "contract", 30_000, "review", 0.85, looped(f"c{i}")) for i in range(3)])
    report = routing_audit.audit(root)
    c = report["classes"]["contract"]
    assert c["fires"] == {"retry_classify": 3, "judge_verify": 9, "arbiter": 6, "retry_extract": 6}
    assert c["retry_yield"] == {"retries_rejudged": 6, "verdict_improved": 0}
    assert c["retry_classify_yield"] == {"retries": 3, "changed": 0}
    text = "\n".join(report["findings"])
    assert "the judge passed 0/9 calls" in text
    assert "6 arbiter-ordered retries improved no judge verdict" in text
    assert "confidence.by_class.contract.high <= 0.95" in text
    assert c["escalation_input_cost"]["at_full_document_usd"] > c["escalation_input_cost"]["at_vendored_16k_usd"] > 0
    assert any("no extraction_confidence was recorded" in n for n in report["notes"])


def test_audit_flags_a_skipped_judge_on_low_quality_documents(tmp_path):
    root = _store(tmp_path, [(f"r{i}", "corporate_record", 5_000, "archived", 0.3,
                              [_node(f"r{i}", "extract", 1)]) for i in range(2)])
    text = "\n".join(routing_audit.audit(root)["findings"])
    assert "no document was judged, yet mean quality is 0.3" in text


def test_judge_band_suggestion_needs_recorded_confidence_and_enough_documents():
    def doc(conf, quality):
        return {"extraction_confidence": [conf], "quality": quality}

    few = routing_audit.suggest_judge_band_high([doc(0.9, 0.9)] * 3)
    assert few["suggestion"] is None and "need 5" in few["basis"]
    sample = [doc(0.80, 0.4), doc(0.85, 0.6), doc(0.90, 0.75), doc(0.93, 0.8), doc(0.97, 0.9), doc(0.99, 0.95)]
    got = routing_audit.suggest_judge_band_high(sample, target=0.7)
    assert got["suggestion"] == 0.9 and got["would_judge"] == 2 and got["of"] == 6
    flat = routing_audit.suggest_judge_band_high([doc(0.99, 0.2)] * 5)
    assert flat["suggestion"] is None and "does not separate quality" in flat["basis"]


# --- cost envelope --------------------------------------------------------------------


def test_cost_envelope_follows_the_retry_thresholds():
    agent = {"provider": "openrouter", "model": "qwen/qwen3.7-flash", "max_input_chars": 2_000_000}
    tax = {"doc_classes": [{"key": "merger_agreement", "specialist": "merger_agreement_specialist"}],
           "agents": {"merger_agreement_specialist": agent, "judge": agent, "arbiter": agent},
           "chunking": {"chunk_chars": 2_000_000},
           "confidence": {"arbiter_retry_max": 2, "judge_max_passes": 3,
                          "by_class": {"merger_agreement": {"arbiter_retry_max": 1, "judge_max_passes": 2}}}}
    rows = [{"id": "m", "expected_doc_class": "merger_agreement", "doc_text": "x" * 400_000}]
    cost = plan(tax, rows, windows={"judge": 2_000_000, "arbiter": 2_000_000})["classes"]["merger_agreement"]["input_cost_usd"]
    assert cost["worst_calls"] == {"extract_passes": 2, "judge": 2, "arbiter": 2}
    assert 0 < cost["clean"] < cost["judged"] < cost["worst"]
    assert cost["worst"] == pytest.approx(2 * cost["clean"] + 4 * (cost["judged"] - cost["clean"]), rel=1e-3)


def test_unpriced_models_have_no_cost_envelope():
    agent = {"provider": "modal-vllm", "model": "Qwen/Qwen3.5-9B", "max_input_chars": 36008}
    tax = {"doc_classes": [{"key": "contract", "specialist": "contracts_specialist"}],
           "agents": {"contracts_specialist": agent, "judge": agent, "arbiter": agent}}
    rows = [{"id": "c", "expected_doc_class": "contract", "doc_text": "x" * 10_000}]
    assert plan(tax, rows, windows={"judge": 16000, "arbiter": 16000})["classes"]["contract"]["input_cost_usd"] is None


# --- run isolation ------------------------------------------------------------------


def test_matter_ids_are_scoped_to_the_run():
    """A rerun must not see the previous run's archive as the same matter (Boss conflict)."""
    from mailroom_sandbox.eval.runners import sandbox_matter_id

    row = {"id": "DOC-a52b3ad21666d339"}
    first, rerun = sandbox_matter_id(row, "pipeline-qwen-flash-25"), sandbox_matter_id(row, "pipeline-qwen-flash-25-fit")
    assert first != rerun and first.endswith(row["id"]) and rerun.startswith("SANDBOX-pipeline-qwen-flash-25-fit-")
    assert sandbox_matter_id(row, None) == "SANDBOX-adhoc-DOC-a52b3ad21666d339"
