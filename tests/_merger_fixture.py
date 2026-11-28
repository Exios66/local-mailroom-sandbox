"""Shared merger-agreement fixture for the phase 5 part 2 tests (HF-030): text, answers, a call recorder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mailroom_sandbox import merger_tables

merger_tables._ensure_dojo()

from llm_dojo_scoring.schemas.maud_schema import maud_question, maud_questions  # noqa: E402

BODY = "The parties agree as follows in every respect material to this provision. " * 8
ALL_ON = {"subclass_fields": True, "question_groups": True, "gap_retry": True, "groups": 3}
HANDOFF = "SORTER CLASSIFICATION: merger_agreement / all_cash"

SECTIONS = {
    "definitions": ("\nARTICLE I\nSection 1.1 Definitions. " + BODY
                    + "“Company Material Adverse Effect” means any effect materially adverse to the business. " + BODY
                    + "“Knowledge” means the actual knowledge of the officers listed. " + BODY
                    + "“Superior Proposal” means a bona fide written proposal on better terms. " + BODY
                    + "“Intervening Event” means a material event unknown on the date hereof. " + BODY
                    + "“Acquisition Proposal” means any proposal for fifteen percent or more. " + BODY),
    "consideration": "\nSection 2.1 Conversion of Shares. Each share converts into $45.00 in cash. " + BODY,
    "conduct": "\nSection 5.1 Conduct of Business. The Company shall operate in the ordinary course. " + BODY,
    "no_solicitation": "\nSection 6.2 No Solicitation. The Company shall not solicit any proposal. " + BODY,
    "recommendation": "\nSection 6.3 Change of Recommendation. The Board shall not change its recommendation. " + BODY,
    "meeting": "\nSection 6.4 Stockholders Meeting. The Company shall hold the meeting. " + BODY,
    "efforts": "\nSection 6.5 Efforts. Each party shall use reasonable best efforts. " + BODY,
    "conditions": ("\nSection 7.1 Conditions to Each Party's Obligations. No injunction shall be in effect. " + BODY
                   + "\nSection 7.2 Conditions to Obligations of Parent. The representations shall be true. " + BODY),
    "termination": "\nSection 8.1 Termination. Either party may terminate after the Outside Date. " + BODY,
    "fee": "\nSection 8.3 Termination Fee. The Company shall pay the Termination Fee. " + BODY,
    "remedies": "\nSection 9.8 Specific Performance. The parties are entitled to specific performance. " + BODY,
    "law": "\nSection 9.9 Governing Law. This Agreement is governed by the laws of Delaware. " + BODY,
}
PREAMBLE = ("AGREEMENT AND PLAN OF MERGER, dated as of May 1, 2020, by and among Parent Inc., Merger Sub Inc. "
            "and Target Corp.\n")


def doc(*leave_out: str) -> str:
    return PREAMBLE + "".join(text for key, text in SECTIONS.items() if key not in leave_out)


FIXTURE = doc()


def _ok(question: str, index: int = 0) -> str:
    return f"{question}: {maud_question(question).valid_classes[index]}"


def main_answer(**over: Any) -> dict:
    out = {"document_name": "Agreement and Plan of Merger", "parties": ["Parent Inc.", "Target Corp."],
           "acquirer": "Parent Inc.", "target": "Target Corp.", "governing_law": None,
           "outside_date": "2021-05-01", "per_share_cash_amount": "$45.00", "merger_consideration": "all_cash",
           "maud_clauses": [_ok(q.name, 0) for q in maud_questions()], "confidence": 0.8}
    out.update(over)
    return out


@dataclass
class Call:
    message: str
    schema: dict

    @property
    def props(self) -> set[str]:
        return set(self.schema.get("properties") or {})

    @property
    def is_group(self) -> bool:
        return self.props == {"maud_clauses"}

    @property
    def is_main(self) -> bool:
        return "document_name" in self.props and "maud_clauses" in self.props and len(self.props) > 8

    def questions(self) -> list[str]:
        items = ((self.schema.get("properties") or {}).get("maud_clauses") or {}).get("items") or {}
        names = [q.name for q in maud_questions()]
        if "enum" in items:
            return [n for n in names if any(str(x).startswith(f"{n}: ") for x in items["enum"])]
        return [n for n in names if f"] {n}  (" in self.message]


def default_respond(call: Call) -> dict:
    if call.is_main:
        return main_answer()
    out: dict[str, Any] = {}
    for name in call.props:
        if name == "maud_clauses":
            out[name] = [_ok(q, 1) for q in call.questions()]
        elif name not in ("confidence", "reasoning"):
            out[name] = f"retried {name}"
    return out
