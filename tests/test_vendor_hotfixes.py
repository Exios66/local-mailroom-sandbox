"""Sandbox hotfixes over the vendored pipeline: fingerprint-bound, recorded, preflight-gated."""
from __future__ import annotations

import pytest

from mailroom_sandbox import vendor_hotfixes as vh

pytest.importorskip("langchain_agents.doc_inventories")


def test_every_hotfix_matches_the_vendored_code_it_was_written_against():
    status = vh.apply_hotfixes()
    assert status and all(s == "applied" for s in status.values()), status
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
