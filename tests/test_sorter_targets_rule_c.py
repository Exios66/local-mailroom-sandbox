"""Rule C in the sorter answer key: a bylaw amendment is bylaws, never board_resolution.

The v9.3 labels file board-adopted bylaw amendments under board_resolution, and the Decisions
reviewer (question sets up to 3.1.0) agrees with them, so rule 3 (title and reviewer must agree)
can never move them. Rule C is a deterministic corpus rule (mailroom-dataset v10 rule C, user
decision 2026-11-07): the document's own title decides, with no reviewer vote.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


psh = _load("patch_sorter_handoff")
csp = _load("compare_sorter_prompt")


@pytest.mark.parametrize("text", [
    "EX-3.(II) 2 bylawamend.htm\nAMENDMENT TO BYLAWS OF PARKER ENERGY TECHNOLOGY, INC.\nThe following",
    "**EXHIBIT 3.2**\n**AMENDMENT**\n**TO THE BYLAWS OF**\n**NATIONAL HEALTH REALTY, INC.**\nOn March 22",
    "**Exhibit 3.2**\n**FIRST AMENDMENT TO THE BY-LAWS**\n**OF**\n**MONARCH ENERGY HOLDING, INC.**",
    "EX-3.01\nAMENDMENT TO SECOND AMENDED BYLAWS\nAMENDMENT TO SECOND AMENDED AND RESTATED BYLAWS",
    "EX-3.1 2 v387920_ex3-1.htm EXHIBIT 3.1 \n**Exhibit 3.1**\n\nEXHIBIT A\n\n(to Unanimous Consent\n\n"
    "of the Board of Directors\n\ndated August 26, 2014)\n\nAmendment to Bylaws of Rancher Energy Corp.\n",
    "**EXHIBIT 3.2.3**\n**SECOND AMENDMENT TO BYLAWS**\n**OF**",
])
def test_a_title_naming_an_amendment_to_the_bylaws_is_rule_c(text):
    assert psh.bylaw_amendment_title(text)


@pytest.mark.parametrize("text", [
    "BYLAWS OF ACME CORP\nARTICLE I",
    "AMENDED AND RESTATED BYLAWS OF ACME CORP",
    "CERTIFICATE OF AMENDMENT OF THE CERTIFICATE OF INCORPORATION OF ACME CORP",
    "UNANIMOUS WRITTEN CONSENT OF THE BOARD OF DIRECTORS\nRESOLVED, that the Corporation's officers",
    "CERTIFICATE OF DESIGNATION\nof Series A Preferred Stock\nas amended",
])
def test_other_titles_are_not_rule_c(text):
    assert not psh.bylaw_amendment_title(text)


def test_rule_c_corrects_a_board_resolution_label_without_the_reviewer():
    sub, state, evidence = psh.rule_c("corporate_record", "board_resolution", "AMENDMENT TO BYLAWS OF X\n")
    assert (sub, state) == ("bylaws", "corrected")
    assert evidence[0].startswith(psh.RULE_C_EVIDENCE)


def test_rule_c_confirms_a_bylaws_label():
    sub, state, evidence = psh.rule_c("corporate_record", "bylaws", "FIRST AMENDMENT TO BYLAWS\n")
    assert (sub, state) == ("bylaws", "label")
    assert psh.label_confirmed(evidence)


@pytest.mark.parametrize("cls, sub, text", [
    ("corporate_record", "board_resolution", "RESOLVED, that the bylaws are amended"),
    ("correspondence", "email", "AMENDMENT TO BYLAWS OF X"),
])
def test_rule_c_leaves_other_rows_alone(cls, sub, text):
    assert psh.rule_c(cls, sub, text) is None


def test_prime_keeps_a_rule_c_target_the_published_label_and_old_reviewer_contradict():
    """The v9.3 label and a reviewer on the old convention both say board_resolution."""
    target = {"filename": "amend.htm", "target_status": "corrected",
              "target_evidence": [f"{psh.RULE_C_EVIDENCE}: x"], "use_for_class": True, "use_for_subclass": True,
              "target_doc_class": "corporate_record", "target_subclass": "bylaws",
              "sorter_class_correct": True, "sorter_doc_type": "corporate_record",
              "reviewer_evidence": {"doc_type": "corporate_record", "doc_subclass": "board_resolution", "p": 1.0}}
    current = {"amend.htm": {"class": "corporate_record", "subclass": "board_resolution", "source": "s"}}
    kept, dropped = csp.prime_targets({"d": target}, current, {"d": "AMENDMENT TO BYLAWS OF X\n"})
    assert set(kept) == {"d"} and dropped == {}


def test_prime_still_drops_a_rule_c_target_whose_reviewer_disputes_the_class():
    target = {"filename": "amend.htm", "target_status": "corrected",
              "target_evidence": [f"{psh.RULE_C_EVIDENCE}: x"], "use_for_class": True, "use_for_subclass": True,
              "target_doc_class": "corporate_record", "target_subclass": "bylaws",
              "sorter_class_correct": True, "sorter_doc_type": "corporate_record",
              "reviewer_evidence": {"doc_type": "contract", "doc_subclass": "other", "p": 1.0}}
    current = {"amend.htm": {"class": "corporate_record", "subclass": "board_resolution", "source": "s"}}
    kept, dropped = csp.prime_targets({"d": target}, current, {"d": "AMENDMENT TO BYLAWS OF X\n"})
    assert not kept and dropped == {"the reviewer disputes the label": 1}


def _row(doc_id, sub, sorter_sub, *, status="label"):
    return {"id": doc_id, "filename": f"{doc_id}.htm", "label_doc_class": "corporate_record", "label_subclass": sub,
            "target_doc_class": "corporate_record", "target_subclass": sub, "target_status": status,
            "target_evidence": [], "use_for_class": True, "use_for_subclass": True,
            "sorter_doc_type": "corporate_record", "sorter_doc_subclass": sorter_sub, "sorter_confidence": 0.9,
            "sorter_class_correct": True, "sorter_subclass_correct": sorter_sub == sub, "reviewer_evidence": None}


def test_apply_rule_c_regrades_only_bylaw_amendments():
    rows = [_row("amend", "board_resolution", "bylaws"), _row("consent", "board_resolution", "board_resolution"),
            _row("done", "bylaws", "bylaws"), _row("disputed", "board_resolution", "bylaws", status="disputed")]
    texts = {"amend": "AMENDMENT TO BYLAWS OF X\n", "consent": "UNANIMOUS WRITTEN CONSENT\nRESOLVED, that\n",
             "done": "FIRST AMENDMENT TO BYLAWS\n", "disputed": "AMENDMENT TO BYLAWS OF Y\n"}
    out, corrections = psh.apply_rule_c(rows, texts)
    by = {r["id"]: r for r in out}
    assert (by["amend"]["target_subclass"], by["amend"]["target_status"]) == ("bylaws", "corrected")
    assert by["amend"]["sorter_subclass_correct"] is True
    assert by["amend"]["target_evidence"][-1].startswith(psh.RULE_C_EVIDENCE)
    assert by["consent"] == rows[1]
    assert by["done"]["target_status"] == "label" and psh.label_confirmed(by["done"]["target_evidence"])
    assert by["disputed"] == rows[3]  # rule C runs only where the full build would (status label)
    assert [c["id"] for c in corrections] == ["amend"]


def test_apply_rule_c_needs_every_row_text():
    with pytest.raises(SystemExit):
        psh.apply_rule_c([_row("amend", "board_resolution", "bylaws")], {})
