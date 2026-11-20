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
    assert merged["entity_name"] == "First"
