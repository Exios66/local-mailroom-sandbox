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


def test_judge_rejudge_retry_is_a_strict_boolean_run_knob():
    on = _spec(confidence={"judge_rejudge_retry": True, "by_class": {"corporate_record": {"judge_rejudge_retry": False}}})
    assert on.confidence["judge_rejudge_retry"] is True
    assert on.confidence["by_class"]["corporate_record"]["judge_rejudge_retry"] is False
    for bad in ("false", "true", 1, 0, None):
        with pytest.raises(ValidationError, match="judge_rejudge_retry must be true or false"):
            _spec(confidence={"judge_rejudge_retry": bad})
        with pytest.raises(ValidationError, match="judge_rejudge_retry must be true or false"):
            _spec(confidence={"by_class": {"contract": {"judge_rejudge_retry": bad}}})
    # The knob is part of the run's identity: the on and off arms never share a lock.
    off = _spec(confidence={"judge_rejudge_retry": False})
    assert core_hash(spec_core(on, source_sha256="0" * 64)) != core_hash(spec_core(off, source_sha256="0" * 64))


@pytest.mark.parametrize("flag", ["judge_complete_archives", "arbiter_accept_archives", "judge_clears_low_confidence"])
def test_archive_checks_are_strict_boolean_run_knobs(flag):
    """A baseline arm can restore the old route per class; a quoted "false" never switches it on."""
    spec = _spec(confidence={flag: False, "by_class": {"contract": {flag: True}}})
    assert spec.confidence["by_class"]["contract"][flag] is True
    with pytest.raises(ValidationError, match=f"{flag} must be true or false"):
        _spec(confidence={flag: "false"})


def test_activation_applies_judge_rejudge_retry_and_routing_reads_it(monkeypatch):
    pytest.importorskip("pipeline.config")
    from graph import routing
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import runtime

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("MAILROOM_JUDGE_VERIFY", raising=False)
    # A judged first attempt, retried: the case #241 re-judges when the knob is on.
    state = {"doc_type": "corporate_record", "extraction_attempts": 2, "judge_pass_count": 1,
             "extracted_data": {"entity_name": "Cedar Sample Ltd"}}
    runtime.activate("modal-vllm", load_env_file=False)
    assert get_confidence_thresholds("corporate_record").get("judge_rejudge_retry", False) is False
    assert routing.retry_rejudge_due(state) is False  # ships off
    runtime.activate("modal-vllm", load_env_file=False,
                     confidence={"by_class": {"corporate_record": {"judge_rejudge_retry": True}}})
    try:
        assert get_confidence_thresholds("corporate_record")["judge_rejudge_retry"] is True
        assert get_confidence_thresholds("contract").get("judge_rejudge_retry", False) is False
        flag_on = routing.retry_rejudge_due(state)
        other_class = routing.retry_rejudge_due({**state, "doc_type": "contract"})
    finally:
        runtime.activate("modal-vllm", load_env_file=False)
    assert flag_on is True and other_class is False
    assert routing.retry_rejudge_due(state) is False  # restored on the next activation


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
    assert cost["worst_calls"] == {"extract_passes": 4, "judge": 2, "arbiter": 2}
    assert 0 < cost["clean"] < cost["judged"] < cost["worst"]
    assert cost["worst"] == pytest.approx(4 * cost["clean"] + 4 * (cost["judged"] - cost["clean"]), rel=1e-3)


def test_rejudge_cost_uses_the_effective_class_flag_and_pass_cap():
    agent = {"provider": "openrouter", "model": "qwen/qwen3.7-flash", "max_input_chars": 100000}
    tax = {"doc_classes": [{"key": "contract", "specialist": "contracts_specialist"}],
           "agents": {"contracts_specialist": agent, "judge": agent, "arbiter": agent},
           "confidence": {"arbiter_retry_max": 1, "judge_max_passes": 3, "judge_rejudge_retry": False}}
    rows = [{"id": "c", "expected_doc_class": "contract", "doc_text": "x" * 1000}]

    def cost():
        return plan(tax, rows)["classes"]["contract"]["input_cost_usd"]

    off = cost()
    tax["confidence"]["by_class"] = {"contract": {"judge_rejudge_retry": True}}
    on = cost()
    assert on["high_confidence_retry"]["judge_calls"] == 2
    assert off["high_confidence_retry"]["judge_calls"] == 1
    assert on["high_confidence_retry"]["input_usd"] > off["high_confidence_retry"]["input_usd"]
    assert on["worst"] == off["worst"]  # ambiguous retries already consume this upper bound
    tax["confidence"]["keep_best_attempt"] = True
    assert cost() == on  # selection reads stored attempts; it makes no model call
    tax["confidence"]["judge_max_passes"] = 1
    assert cost()["high_confidence_retry"]["judge_calls"] == 1


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


def _audit_store(tmp_path, lock):
    import json as _json

    run = tmp_path / "run"
    run.mkdir()
    (run / "spec.lock.json").write_text(_json.dumps(lock))
    (run / "dataset.jsonl").write_text(_json.dumps({"id": "d1", "expected_doc_class": "corporate_record",
                                                    "expected_fields": "{}"}) + "\n")
    (run / "items.jsonl").write_text(_json.dumps({"item_id": "d1", "pred": {"stage": "archived"}}) + "\n")
    (run / "nodes.jsonl").write_text("")
    return run


def test_routing_audit_reads_the_frozen_thresholds_of_a_run(tmp_path):
    from mailroom_sandbox.job import routing_audit

    frozen = {"high": 0.5, "judge_rejudge_retry": True}
    report = routing_audit.audit(_audit_store(tmp_path, {"run_id": "r", "effective_confidence": frozen}))
    corp = report["classes"]["corporate_record"]["thresholds"]
    assert corp["high"] == 0.5 and corp["judge_rejudge_retry"] is True
    assert report["thresholds_source"] == "locked"


def test_routing_audit_does_not_backfill_an_unlocked_rejudge_setting(tmp_path):
    """An older run did not freeze its thresholds: today's default is not its setting."""
    from mailroom_sandbox.job import routing_audit

    report = routing_audit.audit(_audit_store(tmp_path, {"run_id": "r"}))
    assert report["classes"]["corporate_record"]["thresholds"]["judge_rejudge_retry"] is None
    assert report["thresholds_source"] == "current_config"
    (tmp_path / "explicit").mkdir()
    explicit = routing_audit.audit(_audit_store(tmp_path / "explicit",
                                                {"run_id": "r", "confidence": {"judge_rejudge_retry": False}}))
    assert explicit["classes"]["corporate_record"]["thresholds"]["judge_rejudge_retry"] is False



def test_a_locked_run_routes_on_its_frozen_block_even_after_the_overlay_moves(monkeypatch):
    """Routing and the audit read the same frozen `effective_confidence` (#303 review).

    The frozen contract `high` is 0.91 while today's vendored+overlay value is 0.98: the
    locked activation must route on 0.91, not on the current files.
    """
    pytest.importorskip("pipeline.config")
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import runtime
    from mailroom_sandbox.job.routing_audit import effective_thresholds

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    current = effective_thresholds()
    assert current["by_class"]["contract"]["high"] == 0.98
    frozen = json.loads(json.dumps(current))
    frozen["by_class"]["contract"]["high"] = 0.91
    lock = {"profile": "modal-vllm", "job": {}, "confidence": {}, "effective_confidence": frozen}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert get_confidence_thresholds("contract")["high"] == 0.91
        assert lock["effective_confidence"]["by_class"]["contract"]["high"] == 0.91  # what the audit reads
    finally:
        runtime.activate("modal-vllm", load_env_file=False)
    assert get_confidence_thresholds("contract")["high"] == 0.98


def test_a_locked_run_ignores_a_class_key_an_overlay_added_after_preflight(monkeypatch):
    """The frozen block replaces the live one, so a key absent from it cannot leak in (#303 review)."""
    pytest.importorskip("pipeline.config")
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import runtime
    from mailroom_sandbox.job.routing_audit import effective_thresholds, thresholds_for

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    frozen = json.loads(json.dumps(effective_thresholds()))
    assert "judge_rejudge_retry" not in (frozen["by_class"].get("contract") or {})
    real_build = runtime.build_merged_taxonomy

    def overlay_added_a_class_key(*args, **kwargs):  # the overlay edited after preflight
        tax = real_build(*args, **kwargs)
        tax["confidence"]["by_class"]["contract"]["judge_rejudge_retry"] = True
        return tax

    monkeypatch.setattr(runtime, "build_merged_taxonomy", overlay_added_a_class_key)
    lock = {"profile": "modal-vllm", "job": {}, "confidence": {}, "effective_confidence": frozen}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        routed = get_confidence_thresholds("contract")
        audited = thresholds_for(lock["effective_confidence"], "contract")
        assert routed.get("judge_rejudge_retry") == audited.get("judge_rejudge_retry")
        assert routed.get("judge_rejudge_retry") is not True
    finally:
        monkeypatch.setattr(runtime, "build_merged_taxonomy", real_build)
        runtime.activate("modal-vllm", load_env_file=False)


def test_frozen_block_matches_unlocked_routing_including_the_component_overlay(monkeypatch):
    """The frozen block carries every layer (components.yaml routing included): a locked run
    routes exactly as an unlocked activation does, and the audit reads the same values."""
    pytest.importorskip("pipeline.config")
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import runtime
    from mailroom_sandbox.components import load_components, routing_overlay
    from mailroom_sandbox.job.routing_audit import effective_thresholds, thresholds_for

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    component = routing_overlay(load_components()).get("confidence") or {}
    frozen = effective_thresholds()
    for key, value in component.items():
        if key != "by_class":
            assert frozen[key] == value  # the component layer is in the frozen block
    classes = ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement")
    runtime.activate("modal-vllm", load_env_file=False)
    unlocked = {cls: get_confidence_thresholds(cls) for cls in classes}
    lock = {"profile": "modal-vllm", "job": {}, "confidence": {}, "effective_confidence": frozen}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        for cls in classes:
            routed = get_confidence_thresholds(cls)
            assert routed == unlocked[cls], cls
            audited = thresholds_for(frozen, cls)
            assert {k: routed.get(k) for k in audited} == audited, cls
    finally:
        runtime.activate("modal-vllm", load_env_file=False)


def test_a_component_change_after_preflight_does_not_move_a_locked_run(monkeypatch):
    pytest.importorskip("pipeline.config")
    from pipeline.config import get_confidence_thresholds

    from mailroom_sandbox import components, runtime
    from mailroom_sandbox.job.routing_audit import effective_thresholds, thresholds_for

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    frozen = effective_thresholds()
    real = components.load_components

    def moved():
        cfg = json.loads(json.dumps(real()))
        cfg.setdefault("routing", {}).setdefault("confidence", {})["low"] = 0.42
        return cfg

    monkeypatch.setattr(components, "load_components", moved)
    lock = {"profile": "modal-vllm", "job": {}, "confidence": {}, "effective_confidence": frozen}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        for cls in ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement"):
            assert get_confidence_thresholds(cls)["low"] == thresholds_for(frozen, cls)["low"] != 0.42, cls
    finally:
        monkeypatch.setattr(components, "load_components", real)
        runtime.activate("modal-vllm", load_env_file=False)
