"""Phase 5 part 2: the deterministic merger section locator.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 3).
"""

from __future__ import annotations

import json

import pytest

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


# --- final review: contents lines and over-broad titles (a wrong excerpt is worse than a miss) ---------

_FILL = "The parties shall act in good faith under this provision at all times. " * 10 + "\n\n"


def test_a_contents_line_before_an_article_heading_is_not_taken_for_the_body_section():
    toc = ("TABLE OF CONTENTS Section 1.8 Closing 7 Section 1.9 Further Action 8 ARTICLE II. REPRESENTATIONS 8 "
           + " ".join(f"Section 2.{i} Item {i} {9 + i}" for i in range(1, 30)) + "\n")
    body = "ARTICLE I\nSection 1.9 Further Action. " + _FILL + "Section 1.10 Other Matters. " + _FILL
    doc = "AGREEMENT AND PLAN OF MERGER\n" + toc + body
    found = merger_sections.locate(doc)["efforts"]
    assert found.start >= len(doc) - len(body) and "ARTICLE" not in found.heading


def test_a_later_cross_reference_with_the_same_number_does_not_displace_the_body_section():
    # Calibration shape: "Section 2.7 Effect on Capital Stock." in the body, then "… Section 2.7. Any income
    # from investment of the Exchange Fund will be payable …" much later (longer to the next anchor).
    body = "Section 2.7 Effect on Capital Stock. " + _FILL * 2
    later = "as set out in Section 2.7. Any income from investment of the Exchange Fund will be payable to Parent. " + _FILL * 6
    doc = body + "Section 2.8 Exchange Procedures. " + _FILL + later + "Section 2.9 Other. " + _FILL
    assert merger_sections.locate(doc)["consideration"].heading == "Section 2.7 Effect on Capital Stock"


def test_a_specific_title_beats_an_earlier_general_one_for_the_same_key():
    doc = ("Section 8.2 Effect of Termination. " + _FILL + "Section 8.3 Termination Fees. " + _FILL
           + "Section 8.4 Other. " + _FILL)
    assert merger_sections.locate(doc)["termination_fee"].heading == "Section 8.3 Termination Fees"
    only = "Section 8.2 Effect of Termination. " + _FILL + "Section 8.4 Other. " + _FILL
    assert merger_sections.locate(only)["termination_fee"].heading == "Section 8.2 Effect of Termination"


def test_governmental_filings_representations_are_not_the_efforts_covenant_but_filings_other_actions_is():
    doc = ("Section 4.04 Governmental Filings; No Violations. " + _FILL
           + "Section 6.04 Cooperation; Regulatory Efforts; Status. " + _FILL)
    assert merger_sections.locate(doc)["efforts"].heading.startswith("Section 6.04")
    wlrk = "Section 5.6 Filings; Other Actions; Notification. " + _FILL + "Section 5.7 Other. " + _FILL
    assert merger_sections.locate(wlrk)["efforts"].heading.startswith("Section 5.6")


def test_sec_filings_and_required_filings_representations_are_not_the_efforts_covenant():
    doc = ("Section 3.4 SEC Filings; Financial Statements. " + _FILL
           + "Section 3.5 No Conflict; Required Filings and Consents. " + _FILL
           + "Section 6.5 Regulatory Efforts. " + _FILL)
    excerpts, _ = merger_sections.question_excerpts(doc, ["General Antitrust Efforts Standard"])
    assert [e.heading for e in excerpts] == ["Section 6.5 Regulatory Efforts"]


def test_a_brokers_or_expenses_section_is_not_the_termination_fee_section():
    doc = ("Section 3.20 Brokers; Expenses. " + _FILL + "Section 9.5 Fees and Expenses. " + _FILL
           + "Section 8.3 Termination Fees. " + _FILL)
    assert merger_sections.locate(doc)["termination_fee"].heading == "Section 8.3 Termination Fees"


def test_conditions_to_the_companys_obligations_are_not_the_parent_conditions():
    doc = ("Section 7.2 Conditions to Obligations of the Company. " + _FILL
           + "Section 7.3 Conditions to Obligations of Parent and Merger Sub. " + _FILL)
    assert merger_sections.locate(doc)["conditions_parent"].heading.startswith("Section 7.3")


def test_the_offline_check_lists_each_keys_headings_for_review_and_counts_contents_lines():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_merger_sections", "scripts/check_merger_sections.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    doc = ("Section 6.4 Regulatory Efforts. " + _FILL + "Section 8.3 Termination Fees. " + _FILL
           + "Section 9.8 Governing Law. " + _FILL)
    result = mod.check([("d1", doc), ("d2", doc)])
    assert result["headings"]["efforts"] == {"Section 6.4 Regulatory Efforts": 2}
    assert result["contents_like_headings"] == 0


@pytest.mark.parametrize(("key", "title"), [
    ("efforts", "SEC Filings; Financial Statements"),
    ("efforts", "No Conflict; Required Filings and Consents"),
    ("efforts", "Governmental Filings; No Violations"),
    ("termination_fee", "Brokers; Expenses"),
    ("termination_fee", "Fees and Expenses"),
    ("conditions_parent", "Conditions to Obligations of the Company"),
])
def test_a_document_with_only_the_wrong_section_is_a_miss_not_a_wrong_excerpt(key, title):
    doc = f"Section 3.4 {title}. " + _FILL + "Section 3.5 Other Matters. " + _FILL
    assert key not in merger_sections.locate(doc)
