"""Phase 5 part 2: HF-030 merger reads on the vendored merger specialist, with a scripted structured call.

The extraction is set up the way ``extract_node`` does it (HF-023: ``record_choice`` then
``bind_choice``), and every ``_call_structured`` is recorded with its user message and schema.
Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 4).
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from mailroom_sandbox import merger_reads, merger_tables, subclass_extraction, subclass_fields, vendor_hotfixes

merger_tables._ensure_dojo()

from agents.merger_agreement_specialist import MergerAgreementSpecialist  # noqa: E402
from _merger_fixture import ALL_ON, FIXTURE, HANDOFF, Call, _ok, default_respond, doc, main_answer  # noqa: E402
from llm_dojo_scoring.schemas.maud_schema import maud_questions  # noqa: E402

@pytest.fixture
def merger(monkeypatch):
    vendor_hotfixes.apply_hotfixes()
    subclass_extraction.activate(sha256=subclass_fields.field_lists_sha256(), guide=False)

    def run(text: str = FIXTURE, *, cfg: dict | None = ALL_ON, respond: Callable[[Call], Any] = default_respond,
            subclass: str = "all_cash", confidence: float = 0.95, chunked: dict | None = None):
        calls: list[Call] = []

        def fake(self, user_message, json_schema=None, **_kw):
            call = Call(user_message, json_schema)
            calls.append(call)
            out = respond(call)
            if isinstance(out, Exception):
                raise out
            return out

        monkeypatch.setattr(MergerAgreementSpecialist, "_call_structured", fake)
        merger_reads.activate(cfg)
        subclass_extraction.record_choice({"doc_id": "d1", "doc_type": "merger_agreement", "doc_subclass": subclass,
                                           "classification_confidence": confidence})
        agent = MergerAgreementSpecialist(handoff_context=HANDOFF)
        subclass_extraction.bind_choice(agent)
        if chunked:
            result = agent.extract_chunked(text, **chunked)
        else:
            result = agent.extract(text)
        return result, calls

    yield run
    merger_reads.activate(None)
    subclass_extraction.deactivate()


def test_off_by_default_the_specialist_makes_one_call(merger):
    result, calls = merger(cfg=None)
    assert len(calls) == 1 and calls[0].is_main
    assert "exchange_ratio" in calls[0].props                     # no merger drop without the switch
    assert "_merger_reads" not in result


def test_subclass_fields_drop_the_other_amount_on_a_confident_subclass(merger):
    _, calls = merger(cfg={"subclass_fields": True})
    assert len(calls) == 1
    assert "exchange_ratio" not in calls[0].props and "per_share_cash_amount" in calls[0].props


def test_three_group_calls_follow_the_main_read_and_send_only_excerpts(merger):
    result, calls = merger()
    assert len(calls) == 4 + 1                       # main, 3 groups, 1 gap retry
    assert calls[0].is_main and all(c.is_group for c in calls[1:4])
    assert all(FIXTURE not in c.message for c in calls[1:])   # never the whole document again
    assert all(c.message.startswith(HANDOFF) for c in calls[1:])
    marks = result["_merger_reads"]
    assert marks["group_calls"] == 3 and marks["group_chars"] > 0 and marks["retry_chars"] > 0
    assert _ok("No-Shop", 1) in result["maud_clauses"] and _ok("No-Shop", 0) not in result["maud_clauses"]
    assert _ok("MAE Definition", 0) in result["maud_clauses"]          # main-owned


def test_a_locator_miss_keeps_the_main_answer_and_never_reads_the_whole_document(merger):
    text = doc("conduct")
    result, calls = merger(text)
    assert {"Ordinary course covenant", "Negative interim operating covenant"} <= set(result["_maud_section_missed"])
    assert _ok("Ordinary course covenant", 0) in result["maud_clauses"]
    assert all(text not in c.message for c in calls[1:])
    assert all("Ordinary course covenant" not in c.questions() for c in calls[1:])


def test_a_group_with_no_located_question_makes_no_call(merger):
    text = doc("conduct", "efforts", "conditions")
    _, calls = merger(text, cfg={**ALL_ON, "gap_retry": False})
    asked = {q for c in calls if c.is_group for q in c.questions()}
    assert len([c for c in calls if c.is_group]) == 2
    assert not asked & set(merger_tables.group_questions(3)["3"])


def test_an_enum_rejection_falls_back_to_the_plain_list(merger):
    def respond(call: Call):
        items = ((call.schema.get("properties") or {}).get("maud_clauses") or {}).get("items") or {}
        if call.is_group and "enum" in items:
            return ValueError("400 Bad Request: response_format enum is not supported")
        if call.is_group:
            return {"maud_clauses": [_ok(q, 1) for q in call.questions()] + ["No-Shop: not an allowed answer"]}
        return default_respond(call)

    result, calls = merger(cfg={**ALL_ON, "gap_retry": False}, respond=respond)
    groups = [c for c in calls if c.is_group]
    assert len(groups) == 6                                     # each group: the enum call, then the plain one
    assert _ok("No-Shop", 1) in result["maud_clauses"]
    assert "No-Shop: not an allowed answer" not in result["maud_clauses"]
    assert not result.get("_maud_group_failed")


def test_a_failed_group_read_leaves_the_main_answers_and_is_recorded(merger):
    def respond(call: Call):
        if call.is_group and "No-Shop" in call.questions():
            return {"_parse_error": True, "_raw": "not json"}
        return default_respond(call)

    result, _ = merger(cfg={**ALL_ON, "gap_retry": False}, respond=respond)
    assert result["_maud_group_failed"] == ["1"]
    assert _ok("No-Shop", 0) in result["maud_clauses"]
    assert _ok("Ordinary course covenant", 1) in result["maud_clauses"]        # group 3 still applied


def test_a_transport_error_in_a_group_read_never_fails_the_document(merger):
    def respond(call: Call):
        if call.is_group and "No-Shop" in call.questions():
            return TimeoutError("read timed out")
        return default_respond(call)

    result, _ = merger(cfg={**ALL_ON, "gap_retry": False}, respond=respond)
    assert result["_maud_group_failed"] == ["1"] and result["document_name"] == "Agreement and Plan of Merger"


def test_group_reads_never_change_an_entity_field(merger):
    def respond(call: Call):
        if call.is_group:
            return {"maud_clauses": [_ok(q, 1) for q in call.questions()], "document_name": "WRONG",
                    "acquirer": "WRONG"}
        return default_respond(call)

    result, _ = merger(cfg={**ALL_ON, "gap_retry": False}, respond=respond)
    assert result["document_name"] == "Agreement and Plan of Merger" and result["acquirer"] == "Parent Inc."


def test_the_gap_retry_asks_only_its_targets_from_sections(merger):
    def respond(call: Call):
        if call.is_main:
            return main_answer(maud_clauses=[_ok(q.name, 0) for q in maud_questions() if q.name != "Knowledge Definition"]
                               + ["MAE Definition: free text"])
        return default_respond(call)

    result, calls = merger(respond=respond)
    retry = calls[-1]
    assert not retry.is_group and not retry.is_main
    assert retry.props - {"confidence", "reasoning"} == {"governing_law", "maud_clauses"}
    assert set(retry.questions()) == {"Knowledge Definition"}            # MAE kept its valid main answer
    assert "governed by the laws of Delaware" in retry.message and FIXTURE not in retry.message
    assert result["governing_law"] == "retried governing_law"
    assert _ok("Knowledge Definition", 1) in result["maud_clauses"]
    assert result["_merger_reads"]["targets"]["fields"] == ["governing_law"]


def test_a_retry_never_overwrites_a_filled_field_or_a_valid_answer(merger):
    def respond(call: Call):
        if call.is_main or call.is_group:
            return default_respond(call)
        out = default_respond(call)
        out["acquirer"] = "WRONG"
        out["maud_clauses"] = out.get("maud_clauses", []) + [_ok("No-Shop", 2)]
        return out

    result, _ = merger(respond=respond)
    assert result["acquirer"] == "Parent Inc."
    assert _ok("No-Shop", 2) not in result["maud_clauses"] and _ok("No-Shop", 1) in result["maud_clauses"]


def test_without_gap_retry_a_subclass_disagreement_asks_the_dropped_field_alone(merger):
    def respond(call: Call):
        if call.is_main:
            return main_answer(merger_consideration="all_stock")
        return default_respond(call)

    result, calls = merger(cfg={"subclass_fields": True}, respond=respond)
    assert len(calls) == 2
    assert calls[1].props - {"confidence", "reasoning"} == {"exchange_ratio"}
    assert "Each share converts into" in calls[1].message and FIXTURE not in calls[1].message
    assert result["exchange_ratio"] == "retried exchange_ratio"


def test_a_target_whose_section_is_missing_is_recorded_not_read(merger):
    text = doc("law")
    result, calls = merger(text)
    assert all(text not in c.message for c in calls[1:])
    assert "governing_law" in result["_merger_reads"]["targets"]["unlocated"]
    assert result["governing_law"] is None


def test_a_chunked_read_is_left_alone(merger):
    result, calls = merger(chunked={"chunk_chars": 2_000, "overlap_chars": 100})
    assert len(calls) > 1 and all(c.is_main for c in calls)
    assert "_merger_reads" not in result


def test_an_other_or_low_confidence_subclass_drops_nothing_and_still_runs_groups(merger):
    for kwargs in ({"subclass": "other"}, {"confidence": 0.05}):
        _, calls = merger(cfg={**ALL_ON, "gap_retry": False}, **kwargs)
        assert {"exchange_ratio", "per_share_cash_amount"} <= calls[0].props, kwargs
        assert len([c for c in calls if c.is_group]) == 3, kwargs


def test_a_document_that_is_not_a_merger_is_untouched(monkeypatch):
    from langchain_agents.specialist_agents import ContractsSpecialist

    vendor_hotfixes.apply_hotfixes()
    calls = []
    monkeypatch.setattr(ContractsSpecialist, "_call_structured",
                        lambda self, msg, json_schema=None, **kw: calls.append(msg) or {"confidence": 0.7})
    merger_reads.activate(ALL_ON)
    try:
        result = ContractsSpecialist().extract(FIXTURE)
    finally:
        merger_reads.activate(None)
    assert len(calls) == 1 and "_merger_reads" not in result


def test_a_field_only_retry_is_passed_through(merger):
    with subclass_extraction.fields_only(["governing_law"]):
        result, calls = merger()
    assert len(calls) == 1 and "_merger_reads" not in result


def test_the_graph_extraction_step_reaches_the_merger_reads_once(monkeypatch):
    from graph import build_graph

    vendor_hotfixes.apply_hotfixes()
    subclass_extraction.activate(sha256=subclass_fields.field_lists_sha256(), guide=False)
    calls: list[Call] = []

    def fake(self, user_message, json_schema=None, **_kw):
        calls.append(Call(user_message, json_schema))
        return default_respond(calls[-1])

    monkeypatch.setattr(MergerAgreementSpecialist, "_call_structured", fake)
    merger_reads.activate(ALL_ON)
    try:
        state = {"doc_id": "d1", "doc_type": "merger_agreement", "doc_subclass": "all_cash",
                 "classification_confidence": 0.95}
        build_graph._build_handoff_context(state)       # HF-023 records the choice here
        result = build_graph._run_chunked_extraction(MergerAgreementSpecialist, FIXTURE, None, HANDOFF)
    finally:
        merger_reads.activate(None)
        subclass_extraction.deactivate()
    assert [c.is_main for c in calls].count(True) == 1           # the graph's TypeError probe re-ran nothing
    assert len(calls) == 5 and result["_merger_reads"]["group_calls"] == 3


def test_hf030_is_registered_with_a_pinned_source():
    fix = next(f for f in vendor_hotfixes.HOTFIXES if f.id == "HF-030")
    assert (fix.module, fix.attr) == ("agents.merger_agreement_specialist", "MergerAgreementSpecialist.extract")
    assert vendor_hotfixes.apply_hotfixes()["HF-030"] == "applied"
    assert getattr(MergerAgreementSpecialist.extract, "_sandbox_hotfix", None) == "HF-030"
    from langchain_agents.specialist_agents import ContractsSpecialist, _SpecialistBase

    assert getattr(_SpecialistBase.extract, "_sandbox_hotfix", None) is None    # only the merger class
    assert ContractsSpecialist.extract is _SpecialistBase.extract
