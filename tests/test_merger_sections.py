"""Phase 5 part 2: the deterministic merger section locator.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 3).
"""

from __future__ import annotations

import json

from mailroom_sandbox import merger_sections, merger_tables

BODY = "The parties agree as follows in every respect material to this provision. " * 8  # > 400 chars

TOC = ("TABLE OF CONTENTS  Section 1.1 Definitions. 2  Section 6.2 No Solicitation. 40  "
       "Section 8.1 Termination. 60  Section 9.8 Specific Performance. 70  ")
FIXTURE = (
    "AGREEMENT AND PLAN OF MERGER, dated as of May 1, 2020, by and among Parent Inc., Merger Sub Inc. "
    "and Target Corp.\n" + TOC + "\nARTICLE I\nSection 1.1 Definitions. " + BODY
    + "“Company Material Adverse Effect” means any effect that is materially adverse to the business. "
    + BODY + "“Knowledge” means the actual knowledge of the officers listed. " + BODY
    + "\nARTICLE II\nSection 2.4 Conversion of Shares. Each share converts into $45.00 in cash. " + BODY
    + "\nARTICLE VI\nSection 6.2 No Solicitation. The Company shall not, directly or indirectly, solicit. " + BODY
    + "\nSection 6.3 Stockholders Meeting. " + BODY
    + "\nARTICLE VIII\nSection 8.1 Termination. This Agreement may be terminated before the Outside Date. " + BODY
    + "\nSection 8.3 Termination Fee. The Company shall pay the Termination Fee. " + BODY
    + "\nARTICLE IX\nSection 9.8 Specific Performance. The parties are entitled to specific performance. " + BODY
    + "\nSection 9.9 Governing Law. This Agreement is governed by the laws of Delaware. " + BODY
)


def test_the_body_section_is_found_not_the_table_of_contents():
    ex = merger_sections.locate(FIXTURE)["no_solicitation"]
    assert ex.start > FIXTURE.index("ARTICLE I\n")
    assert "shall not, directly or indirectly" in ex.text
    assert "Stockholders Meeting" not in ex.text   # ends at the next section


def test_a_defined_term_paragraph_runs_to_the_next_defined_term():
    ex = merger_sections.locate(FIXTURE)["def_mae"]
    assert ex.text.startswith("“Company Material Adverse Effect” means")
    assert "“Knowledge” means" not in ex.text


def test_an_excerpt_over_the_cap_is_cut_at_a_paragraph_and_marked():
    long_body = ("A paragraph of the conduct covenant that the Company must observe until closing.\n\n" * 600)
    text = "Section 5.1 Conduct of Business. " + long_body + "Section 5.2 Access. " + BODY
    ex = merger_sections.locate(text)["conduct"]
    assert ex.cut and len(ex.text) <= merger_sections.EXCERPT_CAP
    assert ex.text.rstrip().endswith("closing.") or "[excerpt cut" in ex.text


def test_a_question_with_no_section_is_reported_missed():
    excerpts, missed = merger_sections.question_excerpts("no headings here at all", ["No-Shop"])
    assert excerpts == [] and missed == ["No-Shop"]


def test_two_questions_sharing_a_section_send_it_once():
    excerpts, missed = merger_sections.question_excerpts(FIXTURE, ["No-Shop", "Breach of No Shop"])
    keys = [e.key for e in excerpts]
    assert len(set(keys)) == len(keys) and "no_solicitation" in keys and missed == []


def test_entity_excerpts_read_the_preamble_and_named_sections():
    excerpts, missed = merger_sections.entity_excerpts(FIXTURE, ["acquirer", "governing_law", "outside_date"])
    keys = {e.key for e in excerpts}
    assert keys == {"preamble", "governing_law", "termination"} and missed == []
    assert next(e for e in excerpts if e.key == "preamble").text.startswith("AGREEMENT AND PLAN OF MERGER")


def test_a_cross_reference_is_not_a_heading():
    text = "Section 4.1 Organization. As described in Section 6.2 of the Company Disclosure Letter. " + BODY
    assert "no_solicitation" not in merger_sections.locate(text)


def test_a_parenthetical_definition_is_found_from_its_sentence():
    text = (BODY + "If the Board determines that a material event has occurred after the date hereof "
            "(each such event, an “Intervening Event”), the Board may change its recommendation. " + BODY)
    ex = merger_sections.locate(text)["def_intervening"]
    assert ex.text.startswith("If the Board determines") and "“Intervening Event”" in ex.text


def test_a_definition_with_words_between_the_term_and_means_is_found():
    for phrase in ("“Knowledge” of the Company, with respect to any matter in question, means the actual knowledge",
                   "“Knowledge” or any similar phrase means the actual knowledge",
                   "“knowledge of the Company” means the actual knowledge"):
        assert "def_knowledge" in merger_sections.locate(BODY + phrase + ". " + BODY), phrase


def test_conditions_and_conduct_title_variants_are_found():
    for title, key in (("Conditions to Obligations of WSFS", "conditions_parent"),
                       ("Conduct of Company Business Pending the Merger", "conduct"),
                       ("Operation of the Company and Company Subsidiaries", "conduct"),
                       ("Business Conduct", "conduct"),
                       ("Conduct of the Company", "conduct"),
                       ("Interim Operations", "conduct"),
                       ("Negative Covenants of Bryn Mawr", "conduct"),
                       ("Covenants of Company", "conduct")):
        text = f"Section 6.1 {title}. " + BODY + "Section 6.2 Access. " + BODY
        assert key in merger_sections.locate(text), title


def test_the_accuracy_condition_falls_back_to_a_single_conditions_section():
    text = "Section 7.1 Conditions to Closing. " + BODY + "Section 7.2 Frustration. " + BODY
    excerpts, missed = merger_sections.question_excerpts(text, ["Accuracy of Target R&W Closing Condition"])
    assert missed == [] and excerpts[0].key == "conditions_each"


def test_every_maud_question_has_a_rule():
    rules = json.loads(merger_sections.RULES_PATH.read_text(encoding="utf-8"))
    merger_tables._ensure_dojo()
    from llm_dojo_scoring.schemas.maud_schema import maud_questions

    assert {q.name for q in maud_questions()} == set(rules["questions"])
    used = {key for keys in rules["questions"].values() for key in keys}
    assert used <= set(rules["sections"])
    assert set(merger_tables.load()["entity_sections"].values()) <= set(rules["sections"]) | {"preamble"}
