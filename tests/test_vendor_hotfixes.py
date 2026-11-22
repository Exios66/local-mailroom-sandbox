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
