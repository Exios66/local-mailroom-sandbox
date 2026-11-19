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


@pytest.mark.parametrize(("cleaned", "kept"), [("short", False), ("A" * 95, True)])
def test_hf003_a_short_single_window_clean_never_replaces_the_document(cleaned, kept):
    def original(self, doc_text, filename=None):
        return {"cleaned": cleaned, "clean_stats": {"n": 1}, "changed": True, "windows": 1}

    guarded = vh._install_intake_clean_guard(None, original)
    prep = guarded(object(), "A" * 100, "doc.txt")
    assert ("cleaned" in prep) is kept and prep["changed"] is kept
    if not kept:
        assert "clean_stats" not in prep and "HF-003" in prep["clean_refused"]
