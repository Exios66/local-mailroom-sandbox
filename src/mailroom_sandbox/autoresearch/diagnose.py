"""The weakness table: lost utility charged to a (document class, node).

Lost utility of a document is ``1 - utility`` (0 to 2: a wrong archive at -1 loses 2). Each lost
point is charged to ONE node by the rules below, applied in order to the gate's per-document
outcome and its primary cause (``job/gate_causes.py``):

1. ``unscorable_archive``: no loss. There is no gold to score against, so no lever can recover it;
   the count is reported per class.
2. ``crashed``: the node the document last started and never finished (``nodes.jsonl``), else ``pipeline``.
3. ``judge_error`` (flag or cause): ``judge``. ``mechanism:transient``: the crash node, else ``pipeline``.
4. Causes no lever can act on are charged to a non-actionable node: ``input:near_empty`` to ``input``,
   ``label_suspect`` to ``label``, ``mechanism:scorer_error`` to ``scoring``, ``mechanism:unmapped:*`` to ``pipeline``.
5. ``classification:wrong_class``: ``reviewer`` when the reviewer named the same wrong class the document
   was archived under (it confirmed the error), else ``sorter``.
6. ``classification:reviewer_unknown`` / ``reviewer_disagreement``: ``reviewer``;
   ``classification:arbiter_escalated``: ``arbiter``.
7. ``judge:arbiter_escalated`` (the extraction arbiter sent the document to a person): ``arbiter``;
   ``judge:*`` (a partial verdict with retries spent, a rejected extraction): ``judge``.
8. ``extraction:*`` (missing field, wrong value, out of enum, date format, CUAD/MAUD misses) and a correct
   archive scored under 1.0: the class's specialist (``contracts_specialist`` ...).
9. Anything else: ``pipeline`` (non-actionable).

A node is *actionable* when a lever could change it; the proposer only follows actionable rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from mailroom_sandbox.autoresearch.scoring import DocScore, RunScores

SPECIALIST = {
    "contract": "contracts_specialist",
    "merger_agreement": "merger_agreement_specialist",
    "corporate_record": "corporate_records_specialist",
    "correspondence": "correspondence_specialist",
    "insurance_claim": "insurance_claims_specialist",
}
#: Graph node (and agent) a crash is charged to.
_NODE_AGENT = {"intake": "intake", "classify": "sorter", "retry_classify": "sorter", "review_classify": "reviewer",
               "judge_verify": "judge", "arbiter": "arbiter", "classification_arbiter": "arbiter",
               "boss_escalation": "boss"}
NON_ACTIONABLE = frozenset({"input", "label", "scoring", "pipeline", "unattributed"})


@dataclass
class WeaknessRow:
    doc_class: str
    node: str
    lost: float = 0.0
    docs: int = 0
    causes: dict[str, int] = field(default_factory=dict)

    @property
    def actionable(self) -> bool:
        return self.node not in NON_ACTIONABLE

    def to_dict(self) -> dict:
        return {"class": self.doc_class, "node": self.node, "lost": round(self.lost, 4), "docs": self.docs,
                "causes": dict(sorted(self.causes.items())), "actionable": self.actionable}


def _crash_node(doc: DocScore) -> str:
    if not doc.crash_node:
        return "pipeline"
    node, _, agent = doc.crash_node.partition("|")
    if node in ("extract", "retry_extract"):
        return agent or SPECIALIST.get(doc.doc_class, "pipeline")
    return _NODE_AGENT.get(node, "pipeline")


def attribute(doc: DocScore) -> tuple[str, str] | None:
    """``(node, cause label)`` that ``doc``'s lost utility is charged to, or None when it lost nothing chargeable."""
    if doc.outcome == "unscorable_archive":
        return None
    cause = doc.cause
    if doc.outcome == "crashed":
        return _crash_node(doc), cause or "mechanism:crashed"
    if doc.judge_error or cause == "mechanism:judge_error":
        return "judge", "mechanism:judge_error"
    if cause == "mechanism:transient":
        return _crash_node(doc), cause
    if cause == "input:near_empty":
        return "input", cause
    if cause == "label_suspect":
        return "label", cause
    if cause == "mechanism:scorer_error":
        return "scoring", cause
    if cause.startswith("mechanism:"):
        return "pipeline", cause
    if cause == "classification:wrong_class":
        confirmed = bool(doc.reviewer_doc_type) and doc.reviewer_doc_type == doc.archived_class
        return ("reviewer" if confirmed else "sorter"), cause
    if cause in ("classification:reviewer_unknown", "classification:reviewer_disagreement"):
        return "reviewer", cause
    if cause in ("classification:arbiter_escalated", "judge:arbiter_escalated"):
        return "arbiter", cause
    if cause.startswith("judge:"):
        return "judge", cause
    if cause.startswith("extraction:"):
        return SPECIALIST.get(doc.doc_class, "pipeline"), cause
    if doc.outcome == "correct_archive":
        return SPECIALIST.get(doc.doc_class, "pipeline"), "extraction:partial"
    return "pipeline", cause or f"outcome:{doc.outcome}"


def lost_utility(doc: DocScore) -> float:
    return max(0.0, 1.0 - doc.utility)


def weakness_table(scores: RunScores) -> list[WeaknessRow]:
    """Rows by (class, node), biggest lost utility first (ties by class, node)."""
    rows: dict[tuple[str, str], WeaknessRow] = {}
    for doc in scores.docs:
        target = attribute(doc)
        lost = lost_utility(doc)
        if target is None or lost <= 0:
            continue
        node, cause = target
        row = rows.setdefault((doc.doc_class, node), WeaknessRow(doc.doc_class, node))
        row.lost += lost
        row.docs += 1
        row.causes[cause] = row.causes.get(cause, 0) + 1
    return sorted(rows.values(), key=lambda r: (-r.lost, r.doc_class, r.node))


def node_totals(rows: Iterable[WeaknessRow]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        totals[row.node] = totals.get(row.node, 0.0) + row.lost
    return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))


def render_weakness_md(scores: RunScores, rows: list[WeaknessRow] | None = None) -> str:
    """``weakness.md``: the table for one run, with the rules it was built by."""
    rows = weakness_table(scores) if rows is None else rows
    total = sum(r.lost for r in rows) or 1.0
    unscorable: dict[str, int] = {}
    for doc in scores.docs:
        if doc.outcome == "unscorable_archive":
            unscorable[doc.doc_class] = unscorable.get(doc.doc_class, 0) + 1
    lines = [f"# Weakness table: {scores.run_id}", "",
             f"{scores.n} documents, mean utility {scores.mean_utility:.3f}. Lost utility is `1 - utility` per document, "
             "charged to one node (rules: `autoresearch/diagnose.py`).", "",
             "| class | node | lost | docs | share | actionable | causes |", "|:---|:---|---:|---:|---:|:---|:---|"]
    for r in rows:
        causes = ", ".join(f"{k} x{v}" for k, v in sorted(r.causes.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"| {r.doc_class} | {r.node} | {r.lost:.2f} | {r.docs} | {r.lost / total:.0%} | "
                     f"{'yes' if r.actionable else 'no'} | {causes} |")
    if not rows:
        lines.append("| (none) | | 0.00 | 0 | | | no lost utility |")
    lines += ["", "## By node", "", "| node | lost |", "|:---|---:|"]
    lines += [f"| {node} | {lost:.2f} |" for node, lost in node_totals(rows).items()] or ["| (none) | 0.00 |"]
    if unscorable:
        lines += ["", "Unscorable archives (no loss charged, no gold): "
                  + ", ".join(f"{k} {v}" for k, v in sorted(unscorable.items()))]
    return "\n".join(lines) + "\n"
