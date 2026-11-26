"""Sandbox hotfixes over the vendored pipeline: fingerprint-bound, recorded, preflight-gated."""
from __future__ import annotations

import pytest

from mailroom_sandbox import vendor_hotfixes as vh

pytest.importorskip("langchain_agents.doc_inventories")


def test_every_hotfix_matches_the_vendored_code_it_was_written_against():
    import importlib.util

    status = vh.apply_hotfixes()
    # HF-005 wraps pipeline.watcher, which imports langfuse (the observability extra); without it
    # the watcher is not importable here and the fix is unavailable, never stale.
    optional = {} if importlib.util.find_spec("langfuse") else {"HF-005": "unavailable"}
    assert status and all(s == optional.get(i, "applied") for i, s in status.items()), status
    assert vh.apply_hotfixes() == status  # idempotent: no wrapper stacking
    from langchain_agents import doc_inventories as di

    assert getattr(di.enrich_extraction, "_sandbox_hotfix") == "HF-001"


def test_a_changed_target_is_reported_stale_and_not_wrapped(monkeypatch):
    fix = vh.HOTFIXES[0]
    bogus = vh.Hotfix(id="HF-TEST", module=fix.module, attr=fix.attr, source_sha256="0" * 64,
                      upstream="-", summary="-", install=fix.install)
    assert vh.apply_hotfixes((bogus,)) == {"HF-TEST": "stale"}


@pytest.mark.parametrize(("subclass", "record_type"), [
    ("indenture", "other"), ("board_resolution", "other"), ("officer_certificate", "other"),
    ("subsidiary_list", "other"), ("charter_amendment", "articles_of_incorporation"),
    ("certificate_of_formation", "articles_of_incorporation"), ("bylaws", "bylaws"),
])
def test_every_corporate_subclass_fills_a_null_record_type(subclass, record_type):
    vh.apply_hotfixes()
    from langchain_agents.doc_inventories import enrich_extraction

    out = enrich_extraction({"record_type": None}, doc_type="corporate_record", subtype=subclass)
    assert out["record_type"] == record_type


def test_the_model_record_type_and_other_classes_are_untouched():
    vh.apply_hotfixes()
    from langchain_agents.doc_inventories import enrich_extraction

    out = enrich_extraction({"record_type": "bylaws"}, doc_type="corporate_record", subtype="indenture")
    assert out["record_type"] == "bylaws"
    assert vh.corporate_record_type_for("not-a-subclass") is None
    out = enrich_extraction({"communication_type": None}, doc_type="correspondence", subtype="indenture")
    assert out.get("communication_type") is None


def test_preflight_check_and_lock_identity():
    from mailroom_sandbox.job.preflight import _hotfix_check, _hotfix_identity

    assert _hotfix_check()["ok"] is True
    ident = _hotfix_identity()
    assert ident["module_sha256"] == vh.module_sha256()
    assert [f["id"] for f in ident["fixes"]] == [f.id for f in vh.HOTFIXES]


@pytest.mark.parametrize("status,ok", [({"HF-003": "unavailable"}, False),
                                     ({"HF-005": "unavailable"}, True)])
def test_required_hotfixes_cannot_silently_be_unavailable(monkeypatch, status, ok):
    from mailroom_sandbox.job.preflight import _hotfix_check

    monkeypatch.setattr(vh, "apply_hotfixes", lambda: status)
    assert _hotfix_check()["ok"] is ok


def test_campaign_hotfix_check_requires_the_watcher_only_when_requested(monkeypatch):
    import importlib.util

    from mailroom_sandbox.paths import repo_root

    spec = importlib.util.spec_from_file_location("check_hotfixes", repo_root() / "scripts/check_hotfixes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(vh, "apply_hotfixes", lambda: {"HF-001": "applied", "HF-005": "unavailable"})
    assert mod.check()["ok"]
    assert not mod.check(require_watcher=True)["ok"]


@pytest.mark.parametrize("class_name", ["ContractsSpecialist", "CorporateRecordsSpecialist",
                                       "CorrespondenceSpecialist", "MergerAgreementSpecialist"])
@pytest.mark.parametrize("confidence", [0, 0.0, 0.4, None])
def test_hf006_explicit_confidence_survives_extraction(monkeypatch, class_name, confidence):
    from langchain_agents import specialist_agents as sa

    vh.apply_hotfixes()
    agent = object.__new__(getattr(sa, class_name))
    monkeypatch.setattr(agent, "truncate_input", lambda text: text)
    monkeypatch.setattr(agent, "_call_structured", lambda *a, **kw: {"confidence": confidence})
    monkeypatch.setattr(agent, "_evidence_confidence", lambda result: 0.9)
    assert agent.extract("source")["confidence"] == (0.9 if confidence is None else confidence)


def test_hf006_a_zero_confidence_chunk_cannot_be_hidden(monkeypatch):
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist

    vh.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent._last_usage = None
    monkeypatch.setattr(agent, "_split_chunks", lambda *a: ["first", "last"])
    replies = iter([{"entity_name": "First", "confidence": 0.9},
                    {"entity_name": "Last", "confidence": 0.0}])
    monkeypatch.setattr(agent, "_call_structured", lambda *a, **kw: next(replies))
    monkeypatch.setattr(agent, "_evidence_confidence", lambda result: 0.9)
    assert agent.extract_chunked("first last")["confidence"] == 0.0


_CLAUSES = [f"Section {i}. The Borrower shall deliver notice {i} to the Agent within ten days."
            for i in range(1, 41)]
_SOURCE = "\n".join(_CLAUSES)
# A 12-word clause dropped and padded back: length stays over 90%, content does not.
_DROPPED = "\n".join(_CLAUSES[:20] + _CLAUSES[21:]) + " " * len(_CLAUSES[20])


@pytest.mark.parametrize(("cleaned", "kept"), [
    ("short", False),                                                  # length
    (_DROPPED, False),                                                 # near-threshold partial reply
    (_SOURCE.replace("\n", "\n\n"), True),                             # layout repair
    (_SOURCE.replace("notice 7", "notlce 7").replace("ten days", "ten  days"), True),  # OCR repair
])
def test_hf003_a_single_window_clean_replaces_the_document_only_when_it_keeps_it(cleaned, kept):
    def original(self, doc_text, filename=None):
        return {"cleaned": cleaned, "clean_stats": {"n": 1}, "changed": True, "windows": 1}

    assert len(_DROPPED) >= vh.INTAKE_CLEAN_MIN_SHARE * len(_SOURCE)
    guarded = vh._install_intake_clean_guard(None, original)
    prep = guarded(object(), _SOURCE, "doc.txt")
    assert ("cleaned" in prep) is kept and prep["changed"] is kept
    if not kept:
        assert "clean_stats" not in prep and "HF-003" in prep["clean_refused"]


def test_hf003_the_vendored_intake_keeps_the_source_over_a_partial_reply(monkeypatch):
    """Downstream: the real IntakeAgent.intake_run, one window, a reply that drops one clause."""
    assert vh.apply_hotfixes()["HF-003"] == "applied"
    from agents.intake import IntakeAgent

    agent = object.__new__(IntakeAgent)
    monkeypatch.setattr(agent, "_configured_max_input_chars", lambda: 10 * len(_SOURCE), raising=False)
    monkeypatch.setattr(agent, "_call_one", lambda window, name: {"cleaned_text": _DROPPED.strip()},
                        raising=False)
    prep = IntakeAgent.intake_run(agent, _SOURCE, "merger.txt")
    assert prep["windows"] == 1 and "cleaned" not in prep and "HF-003" in prep["clean_refused"]

    monkeypatch.setattr(agent, "_call_one", lambda window, name: {"cleaned_text": _SOURCE + "\n"},
                        raising=False)
    assert "clean_refused" not in IntakeAgent.intake_run(agent, _SOURCE + "  ", "merger.txt")


def test_hf007_confidence_at_or_above_the_band_still_reaches_the_judge(monkeypatch):
    from graph import routing

    assert vh.apply_hotfixes()["HF-007"] == "applied"
    monkeypatch.setattr(routing, "_thresholds_for", lambda state: {"low": 0.70, "judge_band_high": 0.85})
    assert routing.judge_gate({"extraction_confidence": 0.99}) is True
    assert routing.judge_gate({"extraction_confidence": 0.80}) is True
    assert routing.judge_gate({"extraction_confidence": 0.69}) is False
    assert routing.judge_gate({"extraction_confidence": None}) is False
    monkeypatch.setenv("MAILROOM_JUDGE_HIGH_BAND", "off")
    assert routing.judge_gate({"extraction_confidence": 0.99}) is False
    assert routing.judge_gate({"extraction_confidence": 0.80}) is True
    monkeypatch.setenv("MAILROOM_JUDGE_VERIFY", "off")
    monkeypatch.delenv("MAILROOM_JUDGE_HIGH_BAND", raising=False)
    assert routing.judge_gate({"extraction_confidence": 0.99}) is False


def test_hf008_records_each_window_and_keeps_the_weakest_confidence():
    assert vh.apply_hotfixes()["HF-008"] == "applied"
    from langchain_agents.specialist_agents import merge_chunk_windows
    windows = [({"entity_name": "First", "confidence": 0.99}, "first"),
               ({"entity_name": "Second", "confidence": 0.2}, "second")]
    merged = merge_chunk_windows(windows, agent_name="corporate_records_specialist")
    assert merged["confidence"] == 0.2
    assert merged["_window_confidences"] == [0.99, 0.2]
    assert merged["_window_lengths"] == [5, 6]
    assert merged["entity_name"] == "First"
    # Only asserted content counts; the per-window self-report is not compared.
    assert merged["_window_agreement"] == {"agreement": 0.0, "fields": 1, "conflicts": 1}


def test_hf008_cross_window_agreement_agrees_on_shared_content():
    # Two windows that read the same fields and disagree on none score 1.0; a
    # key only one window asserts is skipped, not scored as a conflict.
    windows = [({"entity_name": "Acme  Corp", "clause": ["a", "b"], "confidence": 0.9}, "x"),
               ({"entity_name": "acme corp", "clause": ["a", "b"], "confidence": 0.8,
                 "filing_number": "123"}, "y")]
    got = vh.cross_window_agreement(windows)
    assert got == {"agreement": 1.0, "fields": 2, "conflicts": 0}


def test_hf008_cross_window_agreement_scores_list_jaccard_and_none_pairs():
    windows = [({"clause": ["a", "b"], "date": "2026-01-01", "amount": 1000, "confidence": 0.9}, "x"),
               ({"clause": ["b", "c"], "date": "2026-01-02", "amount": 1000.0, "confidence": 0.8}, "y")]
    got = vh.cross_window_agreement(windows)
    # clause 1/3 (shared b, union a/b/c), date 0.0, amount 1.0 (1000 == 1000.0 numerically).
    assert got["fields"] == 3 and got["conflicts"] == 2
    assert got["agreement"] == round((1 / 3 + 0.0 + 1.0) / 3, 4)


def test_hf008_cross_window_agreement_never_scores_a_normalize_fill():
    # normalize_extraction fills EVERY schema key, so a field one window never
    # saw arrives as None/[] rather than missing. A value is never scored
    # against a fill, and two fills are not scored as agreement either
    # (Bugbot #402: unique-window fields are not conflicts).
    windows = [({"entity_name": "Acme", "keywords": [], "filing_number": None,
                 "reasoning": {"summary": "w1", "entries": []}, "confidence": 0.9}, "x"),
               ({"entity_name": "Acme", "keywords": [], "filing_number": None,
                 "reasoning": {"summary": "w2", "entries": []}, "confidence": 0.9}, "y"),
               ({"entity_name": "Acme", "keywords": ["sub"], "filing_number": None,
                 "reasoning": {"summary": "w3", "entries": []}, "confidence": 0.9}, "z")]
    got = vh.cross_window_agreement(windows)
    # filing_number: all fills -> nothing comparable. keywords: only one window
    # asserts -> no comparable pair. reasoning: the trace is excluded.
    assert got == {"agreement": 1.0, "fields": 1, "conflicts": 0}


def test_hf008_cross_window_agreement_excludes_the_reasoning_trace():
    # Contracts and merger emit a per-field reasoning trace on every window;
    # per-chunk summaries and quotes almost never match, so scoring it would
    # pull agreement down on exactly the classes this signal must rank
    # (Bugbot #402).
    windows = [({"entity_name": "A", "reasoning": {"summary": "scan one", "entries": []},
                 "confidence": 0.9}, "x"),
               ({"entity_name": "A", "reasoning": {"summary": "scan two", "entries": []},
                 "confidence": 0.9}, "y")]
    got = vh.cross_window_agreement(windows)
    assert got == {"agreement": 1.0, "fields": 1, "conflicts": 0}


def test_hf008_cross_window_agreement_conflicting_pairs_still_score():
    windows = [({"entity_name": "Acme", "filing_number": "123", "confidence": 0.9}, "x"),
               ({"entity_name": "Beta", "filing_number": None, "confidence": 0.9}, "y"),
               ({"entity_name": "Acme", "filing_number": "456", "confidence": 0.9}, "z")]
    got = vh.cross_window_agreement(windows)
    # entity_name: Acme/Beta 0.0, Acme/Acme 1.0, Beta/Acme 0.0 -> 1/3.
    # filing_number: only w1 and w3 assert -> 0.0. No fill ever scores.
    assert got["fields"] == 2 and got["conflicts"] == 2
    assert got["agreement"] == round((1 / 3 + 0.0) / 2, 4)


def test_hf008_cross_window_agreement_compares_fields_two_of_three_windows_assert():
    # Per-key presence, not the all-window key intersection: `name` is asserted
    # by two windows and missing from the third, so it scores as the conflict it
    # is instead of vanishing (CodeRabbit, #402).
    windows = [({"name": "A"}, "x"), ({"name": "B"}, "y"), ({"date": "2026-01-01"}, "z")]
    got = vh.cross_window_agreement(windows)
    assert got == {"agreement": 0.0, "fields": 1, "conflicts": 1}


def test_hf008_cross_window_agreement_is_none_without_comparable_content():
    assert vh.cross_window_agreement([({"confidence": 0.9}, "x")]) == {
        "agreement": None, "fields": 0, "conflicts": 0}
    assert vh.cross_window_agreement([({"entity_name": "A"}, "x"), ({"filing_number": "1"}, "y")]) == {
        "agreement": None, "fields": 0, "conflicts": 0}
    assert vh.cross_window_agreement([("not a dict", "x"), ({"entity_name": "A"}, "y")]) == {
        "agreement": None, "fields": 0, "conflicts": 0}
    # Two normalize fills of the same field are "not seen", not agreement.
    assert vh.cross_window_agreement([({"filing_number": None}, "x"),
                                      ({"filing_number": None}, "y")]) == {
        "agreement": None, "fields": 0, "conflicts": 0}


class _FakeSpecialist:
    agent_name = "contracts_specialist"
    calls: list[str] = []

    def __init__(self, handoff_context=None):
        self.handoff_context = handoff_context

    def _configured_max_input_chars(self):
        return 100

    def extract(self, doc_text, pages=None, handoff_context=None):
        self.calls.append(f"extract:{len(doc_text)}")
        return {"confidence": 0.9}

    def extract_chunked(self, doc_text, **kwargs):
        self.calls.append(f"chunked:{len(doc_text)}")
        return {"confidence": 0.5}


def test_hf009_api_route_reads_the_whole_document_in_one_call(monkeypatch):
    assert vh.apply_hotfixes()["HF-009"] == "applied"
    import graph.build_graph as bg

    monkeypatch.setattr(vh, "_api_route", lambda agent_name: True)
    _FakeSpecialist.calls = []
    assert bg._run_chunked_extraction(_FakeSpecialist, "x" * 100, None, None) == {"confidence": 0.9}
    assert _FakeSpecialist.calls == ["extract:100"]
    with pytest.raises(vh.WholeDocumentTooLong, match="contracts_specialist.*101.*100.*Modal"):
        bg._run_chunked_extraction(_FakeSpecialist, "x" * 101, None, None)
    assert _FakeSpecialist.calls == ["extract:100"]


def test_hf009_local_serving_keeps_the_vendored_chunking(monkeypatch):
    assert vh.apply_hotfixes()["HF-009"] == "applied"
    import graph.build_graph as bg

    monkeypatch.setattr(vh, "_api_route", lambda agent_name: False)
    _FakeSpecialist.calls = []
    bg._run_chunked_extraction(_FakeSpecialist, "x" * 5000, None, None)
    assert _FakeSpecialist.calls == ["chunked:5000"]


def test_hf009_treats_openrouter_as_api_and_vllm_as_local(monkeypatch):
    from types import SimpleNamespace

    import llm.client as client

    def resolved(provider, gpu=False):
        return SimpleNamespace(provider=SimpleNamespace(name=provider), served_by_vllm=provider == "vllm" or gpu)

    for provider, gpu, api in (("openrouter", False, True), ("vllm", False, False),
                               ("ollama", False, False), ("gateway", True, False)):
        monkeypatch.setattr(client, "resolve_agent_model", lambda *a, p=provider, g=gpu: resolved(p, g))
        assert vh._api_route("contracts_specialist") is api, provider


def test_hf009_an_unresolvable_route_keeps_the_vendored_path(monkeypatch):
    # A --mock run has no OpenRouter key: resolution raises before any client exists. The
    # route check must not turn that into a parse failure ahead of the stubbed extract.
    import graph.build_graph as bg
    import llm.client as client

    assert vh.apply_hotfixes()["HF-009"] == "applied"

    def no_key(*a, **kw):
        raise ValueError("OPENROUTER_API_KEY is missing or the mock-key placeholder")

    monkeypatch.setattr(client, "resolve_agent_model", no_key)
    assert vh._api_route("contracts_specialist") is False
    _FakeSpecialist.calls = []
    bg._run_chunked_extraction(_FakeSpecialist, "x" * 5000, None, None)
    assert _FakeSpecialist.calls == ["chunked:5000"]


class _FakeReader:
    agent_name = "sorter"

    def read(self, text, budget):
        import agents.intake as intake

        return intake.sliding_windows(text, budget, 10)


def test_hf010_api_reader_never_slides_windows(monkeypatch):
    assert vh.apply_hotfixes()["HF-010"] == "applied"
    seen: list[str] = []
    monkeypatch.setattr(vh, "_api_route", lambda agent_name: seen.append(agent_name) or True)
    assert len(_FakeReader().read("x" * 100, 100)) == 1
    with pytest.raises(vh.WholeDocumentTooLong, match="sorter.*101.*100.*Modal"):
        _FakeReader().read("x" * 101, 100)
    assert seen == ["sorter"]


def test_hf010_local_reader_and_plain_calls_keep_windows(monkeypatch):
    assert vh.apply_hotfixes()["HF-010"] == "applied"
    import agents.intake as intake

    monkeypatch.setattr(vh, "_api_route", lambda agent_name: False)
    assert len(_FakeReader().read("x" * 500, 100)) > 1
    monkeypatch.setattr(vh, "_api_route", lambda agent_name: True)
    assert len(intake.sliding_windows("x" * 500, 100, 10)) > 1


# --- HF-011 / HF-012: bounded judge, arbiter and transient loops ------------------------------

_VENDORED_BUDGETS = {"low": 0.88, "judge_band_high": 0.95, "retry_max": 2, "arbiter_retry_max": 2,
                     "judge_max_passes": 3}
_SANDBOX_BUDGETS = {**_VENDORED_BUDGETS, "retry_max": 1, "arbiter_retry_max": 1, "judge_max_passes": 2,
                    "transient_retry_max": 1, "judge_exhausted_to_arbiter": True}


def _walk(monkeypatch, thresholds, *, confidence, arbiter_says, start="extract", **state):
    """Drive the real route specs with scripted nodes; return (terminal, calls per node, path).

    Nodes: every extraction reports ``confidence``; the judge (when ``judge_should_run``) says
    ``partial``; the arbiter answers ``arbiter_says``. Schema and coverage checks pass.
    """
    from graph import route_spec, routing

    monkeypatch.setattr(routing, "_thresholds_for", lambda _state: dict(thresholds))
    monkeypatch.setattr(routing, "validate_extraction", lambda *_a, **_k: {"schema_valid": True})
    specs = {spec.node: spec for spec in route_spec.ROUTE_SPECS}
    s = {"doc_id": "DOC-1", "doc_type": "correspondence", "extracted_data": {"sender": "A", "recipient": "B"},
         "extraction_confidence": confidence, "extraction_attempts": 1, "judge_pass_count": 0,
         "arbiter_retry_count": 0, **state}
    calls = {"extract": 1, "retry_extract": 0, "judge_verify": 0, "arbiter": 0}
    node, path = start, [start]
    for _ in range(40):
        nxt = route_spec.decide_route(specs[node], s)
        path.append(nxt)
        if nxt in ("compile_report", "human_review"):
            return nxt, calls, path
        calls[nxt] += 1
        if nxt == "retry_extract":
            s["extraction_attempts"] += 1
        elif nxt == "judge_verify":
            if routing.judge_should_run(s):
                s.update(judge_verdict="partial", judge_score=0.8, judge_pass_count=s["judge_pass_count"] + 1)
            else:
                s["judge_verdict"] = "skipped"
        elif nxt == "arbiter":
            s["arbiter_decision"] = arbiter_says
            if arbiter_says == "retry_extraction":
                s["arbiter_retry_count"] += 1
        node = nxt
    raise AssertionError(f"no terminal route: {path}")


def test_hf011_the_screenshot_loop_is_bounded_without_an_extra_park(monkeypatch):
    """An unsure extraction the arbiter keeps sending back: 5 extractions before, 3 now."""
    assert vh.apply_hotfixes()["HF-011"] == "applied"
    before = _walk(monkeypatch, _VENDORED_BUDGETS, confidence=0.6, arbiter_says="retry_extraction")
    assert before[0] == "human_review"
    assert before[1] == {"extract": 1, "retry_extract": 4, "judge_verify": 3, "arbiter": 2}, before[2]
    after = _walk(monkeypatch, _SANDBOX_BUDGETS, confidence=0.6, arbiter_says="retry_extraction")
    assert after[0] == "human_review"
    # The unsure extraction is not sent to the arbiter after the last pass: accepting it would
    # still park it, so that call would be wasted.
    assert after[1] == {"extract": 1, "retry_extract": 2, "judge_verify": 2, "arbiter": 1}, after[2]


def test_hf011_a_sound_partial_extraction_gets_a_final_ruling_instead_of_a_park(monkeypatch):
    assert vh.apply_hotfixes()["HF-011"] == "applied"
    before = _walk(monkeypatch, _VENDORED_BUDGETS, confidence=0.9, arbiter_says="retry_extraction")
    assert before[0] == "human_review"
    assert before[1] == {"extract": 1, "retry_extract": 2, "judge_verify": 3, "arbiter": 2}, before[2]
    accepted = _walk(monkeypatch, _SANDBOX_BUDGETS, confidence=0.9, arbiter_says="accept_with_caveats")
    assert accepted[0] == "compile_report"
    assert accepted[1] == {"extract": 1, "retry_extract": 0, "judge_verify": 1, "arbiter": 1}
    # An arbiter that keeps asking for a retry gets one, then rules finally on the last pass:
    # a retry it orders there could not be judged, so it goes to a person.
    retried = _walk(monkeypatch, _SANDBOX_BUDGETS, confidence=0.9, arbiter_says="retry_extraction")
    assert retried[0] == "human_review"
    assert retried[1] == {"extract": 1, "retry_extract": 1, "judge_verify": 2, "arbiter": 2}, retried[2]
    assert retried[2][-2:] == ["arbiter", "human_review"]


def test_hf011_is_inert_without_the_flag_and_keeps_incomplete_and_conflict_parks(monkeypatch):
    from graph import route_spec, routing

    assert vh.apply_hotfixes()["HF-011"] == "applied"
    specs = {spec.node: spec for spec in route_spec.ROUTE_SPECS}
    last = {"doc_type": "correspondence", "extraction_confidence": 0.9, "judge_pass_count": 2,
            "judge_verdict": "partial", "extracted_data": {"sender": "A"}}
    monkeypatch.setattr(routing, "_thresholds_for", lambda _s: {**_SANDBOX_BUDGETS, "judge_exhausted_to_arbiter": False})
    assert route_spec.decide_route(specs["judge_verify"], last) == "human_review"
    assert route_spec.decide_route(specs["arbiter"], {**last, "arbiter_decision": "retry_extraction",
                                                      "arbiter_retry_count": 1}) == "retry_extract"
    monkeypatch.setattr(routing, "_thresholds_for", lambda _s: dict(_SANDBOX_BUDGETS))
    assert route_spec.decide_route(specs["judge_verify"], last) == "arbiter"
    assert route_spec.decide_route(specs["judge_verify"], {**last, "judge_verdict": "incomplete"}) == "human_review"
    assert route_spec.decide_route(specs["judge_verify"], {**last, "judge_pass_count": 1}) == "arbiter"  # budget left
    conflict = {**last, "conflict_detected": True, "conflict_details": ["two parties"], "boss_conflict_fingerprint": None}
    assert route_spec.decide_route(specs["judge_verify"], conflict) == "human_review"
    # The refused retry still parks with a cause (route rules must never park a clean document).
    from pipeline.reconsideration import collect_review_causes

    causes = collect_review_causes({**last, "arbiter_decision": "retry_extraction", "arbiter_retry_count": 1,
                                    "extraction_attempts": 2})
    assert "judge_partial" in causes, causes


def test_hf011_rules_survive_a_registry_clear_and_never_stack(monkeypatch):
    from graph import route_spec

    vh.apply_hotfixes()
    route_spec.clear_route_rules()
    vh.apply_hotfixes()
    vh.apply_hotfixes()
    for node in ("judge_verify", "arbiter"):
        names = [r.name for r in route_spec.route_rules(node)]
        assert len([n for n in names if n.startswith(vh.JUDGE_EXHAUSTED_RULES)]) == 1, names
        assert names[0].startswith(vh.JUDGE_EXHAUSTED_RULES)


def test_hf011_is_stale_when_after_arbiter_changes():
    fix = next(f for f in vh.HOTFIXES if f.id == "HF-011")
    bogus = vh.Hotfix(id="HF-TEST-ALSO", module=fix.module, attr=fix.attr, source_sha256=fix.source_sha256,
                      upstream="-", summary="-", install=fix.install, also=(("after_arbiter", "0" * 64),))
    assert vh.apply_hotfixes((bogus,)) == {"HF-TEST-ALSO": "stale"}


def test_hf015_is_stale_when_the_arbiter_node_changes():
    """HF-015 reads the graph state from ``arbiter_node``'s frame, so a change to it is drift."""
    import graph.build_graph as build_graph

    fix = next(f for f in vh.HOTFIXES if f.id == "HF-015")
    assert dict(fix.also) == {"graph.build_graph:arbiter_node": vh._source_sha(build_graph.arbiter_node)}
    bogus = vh.Hotfix(id="HF-TEST-NODE", module=fix.module, attr=fix.attr, source_sha256=fix.source_sha256,
                      upstream="-", summary="-", install=fix.install,
                      also=(("graph.build_graph:arbiter_node", "0" * 64),))
    assert vh.apply_hotfixes((bogus,)) == {"HF-TEST-NODE": "stale"}
    gone = vh.Hotfix(id="HF-TEST-GONE", module=fix.module, attr=fix.attr, source_sha256=fix.source_sha256,
                     upstream="-", summary="-", install=fix.install,
                     also=(("graph.build_graph:no_such_node", "0" * 64),))
    assert vh.apply_hotfixes((gone,)) == {"HF-TEST-GONE": "stale"}


def test_hf012_transient_budget_follows_the_threshold(monkeypatch):
    from graph import routing

    assert vh.apply_hotfixes()["HF-012"] == "applied"
    monkeypatch.setattr(routing, "_thresholds_for", lambda _s: {})
    # Unset: the vendored two node-level re-runs.
    assert [routing._transient_decision({"transient_retries_judge_verify": n}, retry_target="judge_verify")
            for n in (1, 2, 3)] == ["retry", "retry", "human_review"]
    monkeypatch.setattr(routing, "_thresholds_for", lambda _s: {"transient_retry_max": 1})
    assert [routing._transient_decision({"transient_retries_extract": n}, retry_target="extract")
            for n in (1, 2)] == ["retry", "human_review"]
    monkeypatch.setattr(routing, "_thresholds_for", lambda _s: {"transient_retry_max": 0})
    assert routing._transient_decision({"transient_retries_arbiter": 1}, retry_target="arbiter") == "human_review"
    for bad in (True, -1, "1"):
        monkeypatch.setattr(routing, "_thresholds_for", lambda _s, b=bad: {"transient_retry_max": b})
        assert routing._transient_decision({"transient_retries_x": 2}, retry_target="x") == "retry"


def test_hf011_refresh_never_drops_a_registered_rule(monkeypatch):
    """apply_hotfixes runs on every activation; a concurrent route decision must never find
    the HF-011 rules missing, so a refresh leaves registered rules in place."""
    from graph import route_spec

    vh.apply_hotfixes()
    before = {node: route_spec.route_rules(node)[0] for node in ("judge_verify", "arbiter")}
    monkeypatch.setattr(route_spec, "remove_route_rule",
                        lambda *a, **k: pytest.fail("a refresh removed a live HF-011 rule"))
    vh.apply_hotfixes()
    for node, rule in before.items():
        assert route_spec.route_rules(node)[0] is rule


# --- HF-013: an accuracy-judge parse failure is a judge error -------------------------------------

def _bare_judge(answer):
    from agents.judge import CompletenessJudge

    judge = CompletenessJudge.__new__(CompletenessJudge)
    judge._call_structured = lambda *a, **k: answer
    return judge


def test_hf013_an_accuracy_judge_parse_failure_is_a_judge_error():
    assert vh.apply_hotfixes()["HF-013"] == "applied"
    with pytest.raises(vh.JudgeParseError):
        _bare_judge({"_raw": "garbage", "_parse_error": True}).judge_extraction_correctness("contract", {"parties": ["A"]}, "t")
    # an answer that parsed, however poor, is still a verdict
    real = _bare_judge({"extraction_correctness": 0.0, "extraction_correctness_label": "inaccurate", "reasoning": "r"})
    assert real.judge_extraction_correctness("contract", {"parties": ["A"]}, "t")["extraction_correctness_label"] == "inaccurate"


def test_hf013_the_judge_node_parks_a_correctness_parse_failure_as_judge_error(monkeypatch):
    """Not an ``incomplete`` verdict that spends an arbiter call, a retry and a second judge pass."""
    vh.apply_hotfixes()
    import graph.build_graph as bg
    from agents.judge import CompletenessJudge

    def call(self, user_message, *a, **k):
        if user_message.startswith("Evaluate extraction completeness"):
            return {"completeness": 0.97, "completeness_label": "complete", "reasoning": "ok"}
        return {"_raw": "garbage", "_parse_error": True}

    monkeypatch.setattr(CompletenessJudge, "_call_structured", call)
    monkeypatch.setattr(CompletenessJudge, "__init__", lambda self: None)
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    out = bg.judge_verify_node({"doc_id": "d", "doc_type": "contract", "doc_text": "Cedar Sample Ltd agreement.",
                                "extracted_data": {"parties": ["Cedar Sample Ltd"]}, "extraction_confidence": 0.99})
    assert out["judge_verdict"] == "judge_error" and "JudgeParseError" in out["escalation_reason"]
    assert "judge_pass_count" not in out


def test_a_fresh_run_lock_records_every_hotfix_including_hf013(tmp_path, monkeypatch):
    import json

    from mailroom_sandbox.job import preflight
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    data = tmp_path / "f.jsonl"
    data.write_text(json.dumps({"id": "d0", "filename": "0.txt", "doc_text": "t", "expected": "contract",
                                "expected_subclass": "service"}) + "\n")
    spec = RunSpec(run_id="hf-lock-r1", task="sorter", dataset=DatasetSpec(local_path=f"file://{data}", limit=1),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"}, job={"mock": True})
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    lock = RunStore(run_dir(report["run_id"])).read_lock()
    assert lock["vendor_hotfixes"] == vh.describe()
    fixes = {f["id"]: f for f in lock["vendor_hotfixes"]["fixes"]}
    assert fixes["HF-013"]["target"] == "agents.judge.CompletenessJudge.judge_extraction_correctness"
    assert fixes["HF-013"]["source_sha256"] == vh._source_sha(
        __import__("agents.judge", fromlist=["CompletenessJudge"]).CompletenessJudge.judge_extraction_correctness)
    # HF-014: the route rule's target and its frozen switch (a legacy lock without it stays inert)
    assert fixes["HF-014"]["target"] == "graph.routing.after_arbiter"
    assert fixes["HF-014"]["source_sha256"] == vh._source_sha(__import__("graph.routing", fromlist=["x"]).after_arbiter)
    assert lock["effective_confidence"]["arbiter_full_source"] is True
    assert "arbiter_full_source_min_confidence" not in lock["effective_confidence"]  # unset: class ``low``
    # HF-015: the arbiter's request wrapper
    assert fixes["HF-015"]["target"] == "agents.arbiter.ArbiterAgent.arbitrate"
    assert fixes["HF-015"]["source_sha256"] == vh._source_sha(
        __import__("agents.arbiter", fromlist=["ArbiterAgent"]).ArbiterAgent.arbitrate)


# --- HF-002 / HF-013: a judge answer that did not parse is asked once more --------------------------

PARSE = {"_raw": "garbage", "_parse_error": True}
COMPLETE = {"completeness": 0.97, "completeness_label": "complete", "reasoning": "ok"}
ACCURATE = {"extraction_correctness": 0.97, "extraction_correctness_label": "accurate", "reasoning": "ok"}
LOW_COMPLETENESS = {"completeness": 0.0, "completeness_label": "incomplete", "reasoning": "nothing captured"}
LOW_CORRECTNESS = {"extraction_correctness": 0.0, "extraction_correctness_label": "inaccurate", "reasoning": "r"}
#: (method name, a parsed verdict, a parsed verdict of the lowest score, the verdict field)
JUDGES = {"completeness": ("judge_completeness", COMPLETE, LOW_COMPLETENESS, "completeness"),
          "correctness": ("judge_extraction_correctness", ACCURATE, LOW_CORRECTNESS, "extraction_correctness")}


class _Answers:
    """A scripted ``_call_structured``: answers in order (an exception instance is raised), and records the calls."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, user_message, *args, **kwargs):
        self.calls.append((user_message, args, kwargs))
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _scripted_judge(*answers):
    from agents.judge import CompletenessJudge

    judge = CompletenessJudge.__new__(CompletenessJudge)
    judge._call_structured = _Answers(*answers)
    return judge


def _ask(judge, which):
    return getattr(judge, JUDGES[which][0])("contract", {"parties": ["A"]}, "Cedar Sample Ltd agreement.")


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_judge_parse_failure_is_asked_once_more_and_a_parsed_answer_is_the_verdict(which):
    assert vh.apply_hotfixes()["HF-002"] == vh.apply_hotfixes()["HF-013"] == "applied"
    _, good, _, field = JUDGES[which]
    judge = _scripted_judge(PARSE, good)
    out = _ask(judge, which)
    assert out[field] == good[field] and out["reasoning"] == "ok"
    assert len(judge._call_structured.calls) == 2
    first, second = judge._call_structured.calls
    assert first == second  # the same request: prompt, schema, temperature and system prompt


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_two_judge_parse_failures_are_a_judge_error_after_exactly_two_calls(which):
    vh.apply_hotfixes()
    judge = _scripted_judge(PARSE, PARSE, COMPLETE if which == "completeness" else ACCURATE)
    with pytest.raises(vh.JudgeParseError):
        _ask(judge, which)
    assert len(judge._call_structured.calls) == 2  # never a third


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_parsed_low_answer_is_a_verdict_and_is_never_asked_again(which):
    vh.apply_hotfixes()
    _, good, low, field = JUDGES[which]
    judge = _scripted_judge(low, good)
    assert _ask(judge, which)[field] == 0.0
    assert len(judge._call_structured.calls) == 1


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_transport_error_is_not_asked_again_here(which):
    vh.apply_hotfixes()
    judge = _scripted_judge(ConnectionError("provider blip"), PARSE, PARSE)
    with pytest.raises(ConnectionError):
        _ask(judge, which)
    assert len(judge._call_structured.calls) == 1  # HF-012 bounds transient errors at node level


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_re_ask_calls_the_vendored_method_again_and_is_recorded_on_the_scope(which):
    """The wrapper calls ``_call_structured`` twice; guard and usage on the real path are held by the live-path tests."""
    from mailroom_sandbox.job import call_guard

    vh.apply_hotfixes()
    _, good, _, _ = JUDGES[which]
    judge = _scripted_judge(PARSE, good)
    with call_guard.document() as scope:
        _ask(judge, which)
    assert len(judge._call_structured.calls) == 2
    assert scope["judge_reasks"] == {which: {"asked": 1, "recovered": 1, "parked": 0}}


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_re_ask_whose_answer_does_not_parse_is_parked_not_errored(which):
    """``parked`` is a second parse failure; a re-ask that raised is neither recovered nor parked (it errored)."""
    from mailroom_sandbox.job import call_guard

    vh.apply_hotfixes()
    with call_guard.document() as scope:
        with pytest.raises(vh.JudgeParseError):
            _ask(_scripted_judge(PARSE, PARSE), which)
    assert scope["judge_reasks"] == {which: {"asked": 1, "recovered": 0, "parked": 1}}


def test_a_re_ask_is_recorded_on_the_document_scope_with_counts_only():
    from mailroom_sandbox.job import call_guard

    vh.apply_hotfixes()
    with call_guard.document() as scope:
        _ask(_scripted_judge(PARSE, COMPLETE), "completeness")
        with pytest.raises(vh.JudgeParseError):
            _ask(_scripted_judge(PARSE, PARSE), "correctness")
        _ask(_scripted_judge(COMPLETE), "completeness")  # parsed first time: not recorded
    assert scope["judge_reasks"] == {"completeness": {"asked": 1, "recovered": 1, "parked": 0},
                                     "correctness": {"asked": 1, "recovered": 0, "parked": 1}}
    with call_guard.document() as quiet:
        _ask(_scripted_judge(ACCURATE), "correctness")
    assert "judge_reasks" not in quiet
    _ask(_scripted_judge(PARSE, COMPLETE), "completeness")  # outside a document scope: no error, no record


@pytest.mark.parametrize("which", sorted(JUDGES))
@pytest.mark.parametrize("failure", [ConnectionError("provider blip"), RuntimeError("per-document ceiling 1")],
                         ids=["transport_error", "guard_refusal"])
def test_a_re_ask_that_raises_still_counts_as_asked_and_the_error_propagates_unchanged(which, failure):
    """The second call was made (and may be billed) even when it raises, so it is ``asked``, never ``recovered``."""
    from mailroom_sandbox.job import call_guard

    vh.apply_hotfixes()
    judge = _scripted_judge(PARSE, failure)
    with call_guard.document() as scope:
        with pytest.raises(type(failure)) as caught:
            _ask(judge, which)
    assert caught.value is failure  # not wrapped, not replaced by JudgeParseError
    assert len(judge._call_structured.calls) == 2
    assert scope["judge_reasks"] == {which: {"asked": 1, "recovered": 0, "parked": 0}}  # errored, not parked


class _FakeOpenRouter:
    """The client boundary only: an OpenRouter-URL client whose ``create`` returns scripted message contents."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, *contents):
        import types

        self.contents, self.requests = list(contents), []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        import types

        self.requests.append(kwargs)
        content = self.contents[min(len(self.requests), len(self.contents)) - 1]
        return types.SimpleNamespace(
            model=kwargs["model"], usage=types.SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])


def _live_path_judge(client):
    from agents.judge import CompletenessJudge

    judge = CompletenessJudge.__new__(CompletenessJudge)
    judge.client, judge.model, judge.agent_name = client, "test/model", "judge"
    return judge


def _run_live_path(which, contents, *, ceiling=40):
    """Run one judge method through the real ``_call_llm``, ``retry_chat_completion``, pins and HF-004 usage capture."""
    import json

    from mailroom_sandbox import provider_pins
    from mailroom_sandbox.job import api_budget, call_guard
    from pipeline import limits

    assert vh.apply_hotfixes()["HF-004"] == "applied"
    provider_pins.apply_provider_pins({})
    budget = api_budget.ApiBudget(100.0, 1.0, 1.0, ["test/model"])
    call_guard.arm(budget, ceiling)
    client = _FakeOpenRouter(*[c if isinstance(c, str) else json.dumps(c) for c in contents])
    outcome = None
    try:
        limits.reset_run_usage()
        with call_guard.document() as scope:
            try:
                outcome = _ask(_live_path_judge(client), which)
            except Exception as exc:  # noqa: BLE001 - the test inspects what propagated
                outcome = exc
        usage = limits.usage_summary()
    finally:
        call_guard.disarm()
    return client, budget, scope, usage, outcome


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_re_ask_through_the_real_call_path_passes_the_guard_and_is_priced_once_per_response(which):
    """Both HTTP calls go through the call guard; usage is captured once per response, never twice."""
    _, good, _, field = JUDGES[which]
    _, single_budget, single_scope, _, _ = _run_live_path(which, [good])
    client, budget, scope, usage, outcome = _run_live_path(which, ["not json", good])
    assert outcome[field] == good[field]
    assert len(client.requests) == 2  # the re-ask is a second HTTP call, with the same request
    assert client.requests[0] == client.requests[1]
    assert single_scope["calls"] == 1 and scope["calls"] == 2  # guard saw each call once
    assert usage["calls"] == 2 and usage["by_agent"]["judge"]["calls"] == 2
    assert (usage["prompt_tokens"], usage["completion_tokens"]) == (2000, 200)
    assert budget.live_usd == pytest.approx(2 * single_budget.live_usd) and budget.live_usd > 0
    assert scope["judge_reasks"] == {which: {"asked": 1, "recovered": 1, "parked": 0}}


@pytest.mark.parametrize("which", sorted(JUDGES))
def test_a_re_ask_the_guard_refuses_is_asked_not_recovered_and_makes_no_second_request(which):
    """A per-document ceiling of one lets the first call through and refuses the re-ask before it is sent."""
    from pipeline import limits

    _, good, _, _ = JUDGES[which]
    client, _, scope, usage, outcome = _run_live_path(which, ["not json", good], ceiling=1)
    assert isinstance(outcome, limits.RunBudgetExceeded) and "per-document ceiling 1" in str(outcome)
    assert len(client.requests) == 1 and usage["calls"] == 1  # the refused call never reached the client
    assert scope["refused"] and scope["calls"] == 1
    assert scope["judge_reasks"] == {which: {"asked": 1, "recovered": 0, "parked": 0}}  # errored, not parked


def _judge_node(monkeypatch, completeness, correctness):
    vh.apply_hotfixes()
    import graph.build_graph as bg
    from agents.judge import CompletenessJudge

    asks = {"c": 0, "a": 0}

    def call(self, user_message, *a, **k):
        which = "c" if user_message.startswith("Evaluate extraction completeness") else "a"
        asks[which] += 1
        answers = completeness if which == "c" else correctness
        return answers[min(asks[which], len(answers)) - 1]

    monkeypatch.setattr(CompletenessJudge, "_call_structured", call)
    monkeypatch.setattr(CompletenessJudge, "__init__", lambda self: None)
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    state = {"doc_id": "d", "doc_type": "contract", "doc_text": "Cedar Sample Ltd agreement.",
             "extracted_data": {"parties": ["Cedar Sample Ltd"]}, "extraction_confidence": 0.99}
    return bg.judge_verify_node(state), asks


def test_the_judge_node_keeps_a_document_whose_second_answer_parses(monkeypatch):
    out, asks = _judge_node(monkeypatch, [PARSE, COMPLETE], [PARSE, ACCURATE])
    assert out["judge_verdict"] == "complete" and out["judge_pass_count"] == 1
    assert "escalation_reason" not in out and asks == {"c": 2, "a": 2}


def test_the_judge_node_parks_a_document_whose_second_answer_does_not_parse(monkeypatch):
    out, asks = _judge_node(monkeypatch, [COMPLETE], [PARSE, PARSE])
    assert out["judge_verdict"] == "judge_error" and "JudgeParseError" in out["escalation_reason"]
    assert asks == {"c": 1, "a": 2}


def test_the_re_ask_reaches_the_run_item_through_the_document_scope(monkeypatch):
    from mailroom_sandbox.eval import runners

    def once(row, **kwargs):
        _judge_node(monkeypatch, [PARSE, COMPLETE], [ACCURATE])
        return {"id": row["id"], "stage": "archived"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", once)
    item = runners._run_pipeline_doc({"id": "d0"}, mock=False)
    assert item["judge_reasks"] == {"completeness": {"asked": 1, "recovered": 1, "parked": 0}}
    monkeypatch.setattr(runners, "_run_pipeline_doc_once", lambda row, **kw: {"id": row["id"], "stage": "archived"})
    assert "judge_reasks" not in runners._run_pipeline_doc({"id": "d1"}, mock=False)  # present only when it happened


def test_a_document_the_pipeline_returned_as_failed_still_carries_its_re_ask_counts(monkeypatch):
    """A returned failure becomes an error item (``_record``) whose pred keeps ``judge_reasks``; a raised one has no item."""
    from mailroom_sandbox.eval import runners

    def once(row, **kwargs):
        _judge_node(monkeypatch, [PARSE, COMPLETE], [ACCURATE])
        return {"id": row["id"], "stage": "failed", "escalation_reason": "run limit"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", once)
    result = runners._run_pipeline_doc({"id": "d0"}, mock=False)
    assert result["stage"] == "failed"
    assert result["judge_reasks"] == {"completeness": {"asked": 1, "recovered": 1, "parked": 0}}
