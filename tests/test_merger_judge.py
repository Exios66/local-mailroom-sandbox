"""Phase 5 part 2: the merger judge off (judge_max_passes 0) and the per-question correct-mode MAUD retry.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 5); design part 4.
"""

from __future__ import annotations

import pytest
from _arbiter_harness import Script, activate_profile, arbiter_harness_state, run  # noqa: F401 (fixture)
from _merger_fixture import ALL_ON, FIXTURE, HANDOFF, Call, _ok, default_respond, main_answer

from mailroom_sandbox import (correcting_judge, merger_extract, merger_reads, source_windows, subclass_extraction,
                              subclass_fields, vendor_hotfixes)
from mailroom_sandbox.job import routing_audit

ZERO_JUDGE = {"judge_max_passes": 0, "arbiter_retry_max": 0}


@pytest.fixture
def zero_judge_graph(monkeypatch, tmp_path, arbiter_harness_state):  # noqa: F811
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    import graph.routing as routing

    original = routing._thresholds_for
    monkeypatch.setattr(routing, "_thresholds_for", lambda state: {**original(state), **ZERO_JUDGE})
    yield bg
    source_windows.apply_source_windows({})


MERGER = {k: v for k, v in main_answer(governing_law="Delaware").items() if k != "confidence"}


def _merger_script(confs: list[float]) -> Script:
    return Script(confs=confs, judge=[("partial", "accurate")] * 3, doc_type="merger_agreement",
                  doc_subclass="all_cash", data=dict(MERGER))


@pytest.fixture
def groups_on():
    merger_reads.activate(ALL_ON)
    yield
    merger_reads.activate(None)


@pytest.mark.parametrize("confs", [[0.93], [0.30] * 4], ids=["in-band", "low-after-retries"])  # merger band: 0.90..0.97
def test_judge_max_passes_zero_skips_the_merger_judge_and_archives_or_reviews_without_crashing(
        zero_judge_graph, monkeypatch, groups_on, confs):
    out = run(zero_judge_graph, monkeypatch, _merger_script(confs))
    assert "judge_verify" not in out["path"] and "arbiter" not in out["path"]
    assert out["judge_c"] == 0 and out["judge_a"] == 0 and out["arbiter"] == 0
    assert out["stage"] == ("archived" if confs == [0.93] else "review")


@pytest.mark.parametrize("confs", [[0.93], [0.30] * 4], ids=["in-band", "low-after-retries"])
def test_the_vendored_routing_alone_still_judges_a_merger_at_zero_passes(zero_judge_graph, monkeypatch, confs):
    """Why the route rule exists: without question_groups the vendored routers ignore judge_max_passes 0."""
    out = run(zero_judge_graph, monkeypatch, _merger_script(confs))
    assert "judge_verify" in out["path"]


def test_another_class_keeps_its_judge_under_the_merger_rule(zero_judge_graph, monkeypatch, groups_on):
    out = run(zero_judge_graph, monkeypatch, Script(confs=[0.30] * 4, judge=[("partial", "accurate")] * 3))
    assert "judge_verify" in out["path"]


def test_the_routing_audit_reports_the_merger_judge_off():
    block = routing_audit.effective_thresholds({"by_class": {"merger_agreement": dict(ZERO_JUDGE)}})
    merger = routing_audit.thresholds_for(block, "merger_agreement")
    assert merger["judge_max_passes"] == 0 and merger["arbiter_retry_max"] == 0
    assert routing_audit.thresholds_for(block, "contract").get("judge_max_passes") != 0


# --- the per-question correct-mode retry ---------------------------------------------------------

PREVIOUS = main_answer(governing_law="Delaware")


@pytest.fixture
def judged_retry(monkeypatch):
    from agents.merger_agreement_specialist import MergerAgreementSpecialist

    vendor_hotfixes.apply_hotfixes()
    subclass_extraction.activate(sha256=subclass_fields.field_lists_sha256(), guide=False)

    def go(ruling: dict, *, cfg: dict = ALL_ON, previous: dict = PREVIOUS):
        calls: list[Call] = []

        def fake(self, user_message, json_schema=None, **_kw):
            calls.append(Call(user_message, json_schema))
            return default_respond(calls[-1])

        monkeypatch.setattr(MergerAgreementSpecialist, "_call_structured", fake)
        monkeypatch.setattr(correcting_judge, "last_ruling", lambda: ruling)
        merger_reads.activate(cfg)
        names = frozenset(ruling["retry_fields"])
        token = vendor_hotfixes._FIELD_RETRY.set((dict(previous), names))
        try:
            with subclass_extraction.fields_only(names):
                subclass_extraction.record_choice({"doc_id": "d1", "doc_type": "merger_agreement",
                                                   "doc_subclass": "all_cash", "classification_confidence": 0.95})
                agent = MergerAgreementSpecialist(handoff_context=HANDOFF)
                subclass_extraction.bind_choice(agent)
                result = agent.extract(FIXTURE)
        finally:
            vendor_hotfixes._FIELD_RETRY.reset(token)
        return result, calls

    yield go
    merger_reads.activate(None)
    subclass_extraction.deactivate()


def _ruling(*fields: str, reason: str = "", fixes: list | None = None) -> dict:
    return {"pass": 1, "mode": "correct", "ruling": "retry_fields", "retry_fields": list(fields), "reason": reason,
            "fixes": fixes or [], "wrong_fields": list(fields)}


def test_a_correct_mode_retry_naming_one_maud_question_replaces_only_that_line(judged_retry):
    result, calls = judged_retry(_ruling("maud_clauses", reason="The No-Shop answer misreads Section 6.2."))
    assert len(calls) == 1 and calls[0].is_group and calls[0].questions() == ["No-Shop"]
    assert FIXTURE not in calls[0].message and "shall not solicit" in calls[0].message
    expected = [_ok("No-Shop", 1) if line.startswith("No-Shop:") else line for line in PREVIOUS["maud_clauses"]]
    assert sorted(result["maud_clauses"]) == sorted(expected)
    assert result["_merger_reads"]["question_retry"]["questions"] == ["No-Shop"]


def test_a_fix_naming_a_question_targets_it():
    ruling = _ruling("maud_clauses", fixes=[{"field": "maud_clauses", "value": [_ok("MAE Definition", 2)],
                                             "verified": False}])
    assert merger_extract.ruling_questions(ruling) == ("MAE Definition",)


def test_a_retry_with_other_fields_reads_them_and_still_asks_maud_from_sections(judged_retry):
    result, calls = judged_retry(_ruling("governing_law", "maud_clauses", reason="No-Shop is wrong"))
    assert len(calls) == 2 and not calls[0].is_group and calls[1].is_group
    assert calls[1].questions() == ["No-Shop"]
    assert _ok("MAE Definition", 0) in result["maud_clauses"]          # the whole-document re-read's list is not kept
    assert _ok("No-Shop", 1) in result["maud_clauses"]


def test_a_retry_naming_no_question_re_asks_every_question_from_sections(judged_retry):
    _, calls = judged_retry(_ruling("maud_clauses", reason="several deal points look wrong"))
    asked = {q for c in calls for q in c.questions()}
    assert all(c.is_group for c in calls) and all(FIXTURE not in c.message for c in calls)
    assert {"No-Shop", "MAE Definition", "Ordinary course covenant"} <= asked


def test_the_per_question_retry_is_inert_without_question_groups(judged_retry):
    result, calls = judged_retry(_ruling("maud_clauses", reason="No-Shop is wrong"), cfg={"subclass_fields": True})
    assert len(calls) == 1 and not calls[0].is_group and "maud_clauses" in calls[0].props
    assert "_merger_reads" not in result
