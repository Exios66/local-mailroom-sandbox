"""Phase 5 part 1 (B): HF-029, the evidence check for list items from a one-call read.

Design: docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import evidence_check as ec
from mailroom_sandbox import vendor_hotfixes as vh
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, spec_core, spec_hash

pytest.importorskip("langchain_agents.specialist_agents")

DOC = ("MASTER SERVICES AGREEMENT between Acme Corp and Beta LLC. Section 12. This Agreement shall be "
       "governed by the laws of Delaware. Section 14. Either party may terminate this Agreement for "
       "convenience on thirty days written notice.")
REAL = "Governing Law: This Agreement shall be governed by the laws of Delaware"
REAL2 = "Termination For Convenience: Either party may terminate this Agreement for convenience"
FAKE = "Non-Compete: The Supplier shall not compete in any territory worldwide"


@pytest.fixture
def check_on():
    ec.activate(True)
    yield
    ec.activate(False)


def test_an_unevidenced_item_is_dropped_and_recorded():
    out = ec.filter_one_read({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, DOC)
    assert out["cuad_clauses"] == [REAL]
    assert out["_evidence_dropped"] == {"cuad_clauses": [FAKE]}
    assert out["parties"] == ["Acme"]


def test_only_category_span_fields_are_checked():
    # cuad_clauses and claim_checklist items are "<Category>: <quoted span>". Action items and denial
    # reasons are summaries the prompts ask for, so a whole-item quote test drops true ones.
    assert ec.fields() == ("cuad_clauses", "claim_checklist")
    summaries = {"action_items": ["Return signed lease amendment by March 3, 2026"],
                 "denial_reasons": ["Flood damage excluded under Section 4(b)"], "parties": ["Acme"]}
    assert ec.filter_one_read(summaries, DOC) == summaries
    out = ec.filter_one_read({"claim_checklist": [f"Termination: {REAL2.split(': ', 1)[1]}", FAKE],
                              "parties": ["Acme"]}, DOC)
    assert out["claim_checklist"] == [f"Termination: {REAL2.split(': ', 1)[1]}"]


def test_a_short_unverifiable_item_is_kept():
    out = ec.filter_one_read({"cuad_clauses": ["Governing Law: Delaware", FAKE], "parties": ["Acme"]}, DOC)
    assert out["cuad_clauses"] == ["Governing Law: Delaware"]


def test_a_reasoning_quote_evidences_an_item():
    paraphrase = "Governing Law: the contract is governed by the laws of Delaware"
    result = {"cuad_clauses": [paraphrase], "parties": ["Acme"],
              "reasoning": {"entries": [{"field": "cuad_clauses", "evidence": "Either party may terminate"}]}}
    # The quote is in the document, but quote and item do not contain each other: dropped.
    assert ec.filter_one_read(result, DOC)["cuad_clauses"] == []
    result["reasoning"]["entries"][0]["evidence"] = "governed by the laws of Delaware"
    result["cuad_clauses"] = ["Governing Law: governed by the laws of Delaware (Section 12)"]
    assert ec.filter_one_read(result, DOC)["cuad_clauses"] == result["cuad_clauses"]


def test_label_lists_are_never_filtered():
    result = {"maud_clauses": [FAKE], "parties": ["Nobody In This Document Ltd"], "keywords": [FAKE]}
    assert ec.filter_one_read(result, DOC) == result


def test_a_chunked_read_is_left_to_the_merge_policy():
    result = {"cuad_clauses": [FAKE], "parties": ["Acme"], "_n_chunks": 3, "_failed_chunks": 0}
    assert ec.filter_one_read(result, DOC) is result


def test_a_parse_error_or_missing_text_is_left_alone():
    broken = {"_parse_error": True, "cuad_clauses": [FAKE]}
    assert ec.filter_one_read(broken, DOC) is broken
    plain = {"cuad_clauses": [FAKE], "parties": ["Acme"]}
    assert ec.filter_one_read(plain, None) is plain and ec.filter_one_read(plain, "") is plain
    assert ec.filter_one_read(None, DOC) is None and ec.filter_one_read([FAKE], DOC) == [FAKE]


def test_non_string_items_are_kept():
    items = [{"clause": FAKE}, 7, None, FAKE]
    out = ec.filter_one_read({"cuad_clauses": items, "parties": ["Acme"]}, DOC)
    assert out["cuad_clauses"] == [{"clause": FAKE}, 7, None]


@pytest.mark.parametrize("reasoning", [None, [], "x", {"entries": "x"}, {"entries": [1, None, "e"]},
                                       {"entries": [{"field": None, "evidence": None}]}])
def test_malformed_reasoning_never_raises(reasoning):
    out = ec.filter_one_read({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"], "reasoning": reasoning}, DOC)
    assert out["cuad_clauses"] == [REAL]


def test_a_filter_that_would_empty_the_extraction_is_skipped():
    out = ec.filter_one_read({"cuad_clauses": [FAKE]}, DOC)
    assert out["cuad_clauses"] == [FAKE] and out["_evidence_skipped"] == "would_empty"
    assert "_evidence_dropped" not in out


def test_the_emptiness_check_counts_fields_the_retry_keeps():
    # A field-only retry returns only the named fields; the rest come from the previous extraction.
    out = ec.filter_one_read({"cuad_clauses": [FAKE]}, DOC, keeps={"parties": ["Acme"]})
    assert out["cuad_clauses"] == [] and out["_evidence_dropped"] == {"cuad_clauses": [FAKE]}


def test_the_filter_is_idempotent():
    once = ec.filter_one_read({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, DOC)
    assert ec.filter_one_read(once, DOC) == once


def test_the_input_is_never_mutated():
    result = {"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}
    ec.filter_one_read(result, DOC)
    assert result == {"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}


# --- HF-029 on the vendored graph -------------------------------------------------------------


def _wrap_depth(fn):
    depth = 0
    while hasattr(fn, "__wrapped__"):
        fn, depth = fn.__wrapped__, depth + 1
    return depth


def _state():
    return {"doc_type": "contract", "doc_text": DOC, "doc_id": "d1"}


def test_hf029_is_registered_with_a_pinned_source():
    import graph.build_graph as bg

    fix = next(f for f in vh.HOTFIXES if f.id == "HF-029")
    assert [f.id for f in vh.HOTFIXES].count("HF-029") == 1
    assert (fix.module, fix.attr) == ("graph.build_graph", "_enrich_contract_result")
    assert [f.id for f in vh.HOTFIXES].index("HF-029") > [f.id for f in vh.HOTFIXES].index("HF-027")
    status = vh.apply_hotfixes()
    assert status["HF-029"] == "applied" and status["HF-027"] == "applied"
    assert fix.source_sha256 == vh._source_sha(bg._enrich_contract_result)
    for name in ("extract_node", "retry_extract_node"):
        assert dict(fix.also)[name] == vh._source_sha(getattr(bg, name)), name
    depth = _wrap_depth(bg._enrich_contract_result)
    vh.apply_hotfixes()
    assert _wrap_depth(bg._enrich_contract_result) == depth  # neither HF-027 nor HF-029 is doubled
    assert getattr(bg._enrich_contract_result, "_sandbox_hotfix", None) == "HF-029"


def test_a_filter_error_passes_the_read_through(check_on, monkeypatch):
    import graph.build_graph as bg

    vh.apply_hotfixes()

    def boom(*_a, **_k):
        raise RuntimeError("filter bug")

    monkeypatch.setattr(ec, "filter_one_read", boom)
    out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, _state())
    assert out["cuad_clauses"] == [REAL, FAKE] and not out.get("_parse_error")


def test_off_changes_nothing():
    import graph.build_graph as bg

    vh.apply_hotfixes()
    ec.activate(False)
    out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, _state())
    assert out["cuad_clauses"] == [REAL, FAKE] and "_evidence_dropped" not in out


def test_on_filters_a_one_call_read(check_on):
    import graph.build_graph as bg

    vh.apply_hotfixes()
    out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, _state())
    assert out["cuad_clauses"] == [REAL] and out["_evidence_dropped"] == {"cuad_clauses": [FAKE]}


def test_a_field_retry_with_the_check_filters_the_fresh_fields(check_on):
    import graph.build_graph as bg

    vh.apply_hotfixes()
    token = vh._FIELD_RETRY.set(({"cuad_clauses": [REAL2], "parties": ["Acme"]}, frozenset({"cuad_clauses"})))
    try:
        out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE]}, _state())
        assert out["cuad_clauses"] == [REAL] and out["parties"] == ["Acme"]
        assert out["_evidence_dropped"] == {"cuad_clauses": [FAKE]}
        # Every fresh item unevidenced: the previous extraction's other fields keep it non-empty.
        out = bg._enrich_contract_result({"cuad_clauses": [FAKE]}, _state())
        assert out["cuad_clauses"] == [] and out["parties"] == ["Acme"] and "_evidence_skipped" not in out
    finally:
        vh._FIELD_RETRY.reset(token)


# --- spec, lock --------------------------------------------------------------------------------


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-ev", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_the_check_flag_is_hashed_only_when_set():
    assert "evidence_check" not in spec_core(_spec())["job"]
    assert spec_core(_spec(evidence_check=True))["job"]["evidence_check"] is True
    assert spec_hash(_spec()) != spec_hash(_spec(evidence_check=True))
    with pytest.raises(ValidationError):
        _spec(evidence_check="true")


def test_the_check_requires_a_pipeline_task():
    with pytest.raises(ValidationError, match="evidence_check"):
        _spec(task="sorter", evidence_check=True)


def test_the_lock_activates_the_check(monkeypatch):
    from mailroom_sandbox import runtime

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    lock = {"profile": "modal-vllm", "task": "pipeline", "job": {"evidence_check": True}}
    try:
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert ec.active()
        lock["job"].pop("evidence_check")
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert not ec.active()
    finally:
        ec.activate(False)


def test_the_confirming_arm_differs_from_its_baseline_only_in_the_check():
    import yaml

    def core(name):
        spec = RunSpec.model_validate(yaml.safe_load(open(f"config/runs/{name}.yaml", encoding="utf-8")))
        out = spec_core(spec)
        out.pop("trace", None)  # tags only
        return out

    on, off = core("p5-s1-evidence-on"), core("p4-s1-verify-gov-off")
    assert on["job"].pop("evidence_check") is True
    assert "evidence_check" not in off["job"]
    assert on == off


def test_a_field_retry_keeps_the_earlier_drop_record_for_carried_fields(check_on):
    import graph.build_graph as bg

    vh.apply_hotfixes()
    previous = {"cuad_clauses": [REAL2], "claim_checklist": [f"Termination: {REAL2.split(': ', 1)[1]}"],
                "parties": ["Acme"], "_evidence_dropped": {"claim_checklist": [FAKE], "cuad_clauses": ["old"]}}
    token = vh._FIELD_RETRY.set((previous, frozenset({"cuad_clauses"})))
    try:
        # The carried checklist keeps its record; the re-read cuad_clauses get the fresh one.
        out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE]}, _state())
        assert out["_evidence_dropped"] == {"claim_checklist": [FAKE], "cuad_clauses": [FAKE]}
        out = bg._enrich_contract_result({"cuad_clauses": [REAL]}, _state())
        assert out["_evidence_dropped"] == {"claim_checklist": [FAKE]}
    finally:
        vh._FIELD_RETRY.reset(token)


def _layers(fn):
    marks = []
    while fn is not None:
        mark = getattr(fn, "__dict__", {}).get("_sandbox_hotfix")
        if mark:
            marks.append(mark)
        fn = getattr(fn, "__wrapped__", None)
    return marks


def test_a_reapply_after_the_retry_node_is_put_back_wraps_each_layer_once():
    import graph.build_graph as bg

    vh.apply_hotfixes()
    before = _layers(bg._enrich_contract_result)
    assert before.count("HF-027") == 1 and before.count("HF-029") == 1
    node = bg.retry_extract_node
    bg.retry_extract_node = node.__wrapped__  # a reload or a test put the node under HF-027 back
    try:
        vh.apply_hotfixes()
        assert _layers(bg._enrich_contract_result) == before
        assert _layers(bg.retry_extract_node).count("HF-027") == 1
    finally:
        bg.retry_extract_node = node


def test_a_read_with_page_images_is_left_alone(check_on):
    # The specialist also saw the page images; a clause read from them has no quote in doc_text.
    import graph.build_graph as bg

    vh.apply_hotfixes()
    out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]},
                                     {**_state(), "doc_pages": ["iVBORw0KGgo="]})
    assert out["cuad_clauses"] == [REAL, FAKE] and out["_evidence_skipped"] == "pages"
    assert "_evidence_dropped" not in out
    out = bg._enrich_contract_result({"cuad_clauses": [REAL, FAKE], "parties": ["Acme"]}, {**_state(), "doc_pages": []})
    assert out["cuad_clauses"] == [REAL]


def test_hf029_is_stale_when_the_vendored_evidence_test_moves(monkeypatch):
    import graph.build_graph as bg
    import langchain_agents.specialist_agents as sa

    monkeypatch.setattr(sa, "_DEFAULT_EVIDENCE_FIELDS", ("action_items",))
    with pytest.raises(vh.HotfixDrift, match="evidence fields"):
        vh._install_evidence_check(bg, bg._enrich_contract_result)
    monkeypatch.setattr(sa, "_DEFAULT_EVIDENCE_FIELDS", ("cuad_clauses", "claim_checklist"))
    monkeypatch.setattr(sa, "_MIN_SPAN_CHARS", 4)
    with pytest.raises(vh.HotfixDrift, match="_MIN_SPAN_CHARS"):
        vh._install_evidence_check(bg, bg._enrich_contract_result)


def test_preflight_refuses_keep_best_from_an_overlay_with_correct_mode(monkeypatch):
    from mailroom_sandbox.job import preflight, routing_audit

    spec = RunSpec(run_id="r-kb", task="pipeline", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True}, judge={"mode": "correct"})
    monkeypatch.setattr(routing_audit, "effective_thresholds",
                        lambda c=None: {"by_class": {"contract": {"keep_best_attempt": True}}})
    assert any("keep_best_attempt" in e for e in preflight._keep_best_errors(spec))
    monkeypatch.setattr(routing_audit, "effective_thresholds", lambda c=None: {"keep_best_attempt": False})
    assert preflight._keep_best_errors(spec) == []
