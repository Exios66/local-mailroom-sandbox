"""Phase 5 part 2: the pure logic of the merger reads (HF-030): group prompts, schemas, combine, targets.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 4).
"""

from __future__ import annotations

from mailroom_sandbox import merger_extract, merger_sections, merger_tables

merger_tables._ensure_dojo()

from llm_dojo_scoring.schemas.maud_schema import maud_question  # noqa: E402


def _ok(question: str, index: int = 0) -> str:
    return f"{question}: {maud_question(question).valid_classes[index]}"


def test_the_owning_group_answer_wins_and_the_main_answer_fills_a_gap():
    main = {"maud_clauses": [_ok("No-Shop", 0), _ok("Ordinary course covenant", 0), _ok("MAE Definition", 0)]}
    clauses, invalid = merger_extract.combine(main, {"1": [_ok("No-Shop", 1)], "3": []}, 3)
    assert _ok("No-Shop", 1) in clauses and _ok("No-Shop", 0) not in clauses      # the owner wins
    assert _ok("Ordinary course covenant", 0) in clauses                          # owner silent: main stands
    assert _ok("MAE Definition", 0) in clauses and invalid == []                  # main-owned untouched


def test_a_line_for_a_question_the_group_does_not_own_is_ignored():
    main = {"maud_clauses": [_ok("MAE Definition", 0), _ok("Ordinary course covenant", 0)]}
    clauses, _ = merger_extract.combine(
        main, {"1": [_ok("MAE Definition", 1), _ok("Ordinary course covenant", 1)]}, 3)
    assert _ok("MAE Definition", 0) in clauses and _ok("MAE Definition", 1) not in clauses
    assert _ok("Ordinary course covenant", 0) in clauses and _ok("Ordinary course covenant", 1) not in clauses


def test_a_free_text_answer_is_invalid_and_becomes_a_target():
    main = {"maud_clauses": ["No-Shop: the company may not solicit anything"]}
    clauses, invalid = merger_extract.combine(main, {"1": ["No-Shop: also not an allowed answer"]}, 3)
    assert invalid == ["No-Shop"]
    assert clauses == ["No-Shop: the company may not solicit anything"]   # nothing valid: the main line stays
    targets = merger_extract.gap_targets({"maud_clauses": clauses}, "all_cash", "all_cash", invalid)
    assert "No-Shop" in targets.questions


def test_a_multi_label_question_keeps_every_valid_line_of_its_owner():
    q = "Tail Period & Acquisition Proposal Details"
    clauses, _ = merger_extract.combine({"maud_clauses": [_ok(q, 0)]}, {"1": [_ok(q, 1), _ok(q, 2)]}, 3)
    assert [c for c in clauses if c.startswith(q)] == [_ok(q, 1), _ok(q, 2)]


def test_the_group_block_comes_after_the_excerpts():
    ex = merger_sections.Excerpt("no_solicitation", "Section 6.2 No Solicitation", 0, 10,
                                 "The Company shall not solicit.", False)
    msg = merger_extract.group_message("SORTER: merger_agreement / all_cash", [ex], "all_cash", ["No-Shop"])
    assert msg.startswith("SORTER: merger_agreement / all_cash")                  # the main read's opening
    assert msg.index("Section 6.2 No Solicitation") < msg.index("The Company shall not solicit.")
    assert msg.index("The Company shall not solicit.") < msg.index("MAUD QUESTIONS")
    assert "relevant sections" in msg


def test_the_group_schema_has_only_maud_clauses_with_an_enum_of_valid_lines():
    s = merger_extract.group_schema(["No-Shop"], enum=True)
    assert set(s["properties"]) == {"maud_clauses"}
    assert all(x.startswith("No-Shop: ") for x in s["properties"]["maud_clauses"]["items"]["enum"])
    assert "enum" not in merger_extract.group_schema(["No-Shop"], enum=False)["properties"]["maud_clauses"]["items"]


def test_gap_targets_take_invalid_answers_unanswered_near_universal_and_empty_required_fields():
    extracted = {"document_name": "Agreement and Plan of Merger", "parties": ["A", "B"], "acquirer": "A",
                 "target": "B", "governing_law": None, "outside_date": "", "per_share_cash_amount": "$45.00",
                 "maud_clauses": [_ok("No-Shop", 0)]}
    t = merger_extract.gap_targets(extracted, "all_cash", "all_cash", ["Breach of No Shop"])
    assert set(t.fields) == {"governing_law", "outside_date"}
    assert "Breach of No Shop" in t.questions and "MAE Definition" in t.questions
    assert "No-Shop" not in t.questions                                      # answered validly
    assert "Specific Performance" not in t.questions                         # not near-universal


def test_a_subclass_disagreement_targets_the_dropped_amount():
    t = merger_extract.gap_targets({"merger_consideration": "all_stock", "exchange_ratio": None}, "all_cash", "all_cash", [])
    assert "exchange_ratio" in t.fields


def test_an_agreeing_or_unreadable_consideration_asks_no_dropped_field():
    for token in ("all_cash", "All Cash", None, "something else"):
        t = merger_extract.gap_targets({"merger_consideration": token}, "all_cash", "all_cash", [])
        assert "exchange_ratio" not in t.fields, token


def test_a_fallback_schema_asks_both_amounts_and_drops_nothing():
    t = merger_extract.gap_targets({"merger_consideration": "all_stock"}, None, "all_cash", [])
    assert {"per_share_cash_amount", "exchange_ratio"} <= set(t.fields)
