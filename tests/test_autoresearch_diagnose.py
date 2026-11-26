"""Autoresearch diagnosis: lost utility charged to node x class."""
from __future__ import annotations

import pytest

from mailroom_sandbox.autoresearch import diagnose as dg
from mailroom_sandbox.autoresearch import scoring as sc


def doc(i="d", cls="correspondence", outcome="wrong_archive", utility=-1.0, cause="", **kw):
    return sc.DocScore(id=i, doc_class=cls, outcome=outcome, utility=utility, cause=cause, **kw)


def test_specialist_map_matches_the_eval_harness():
    from mailroom_sandbox.eval.agents import SPECIALIST_CLASS

    assert dg.SPECIALIST == {cls: agent for agent, cls in SPECIALIST_CLASS.items()}


@pytest.mark.parametrize("d,expected", [
    (doc(outcome="unscorable_archive", utility=0.0), None),
    (doc(outcome="crashed", utility=-1.0, crash_node="judge_verify|judge"), ("judge", "mechanism:crashed")),
    (doc(outcome="crashed", utility=-1.0, crash_node="extract|insurance_claims_specialist", cls="insurance_claim"),
     ("insurance_claims_specialist", "mechanism:crashed")),
    (doc(outcome="crashed", utility=-1.0, crash_node="extract|", cls="contract"), ("contracts_specialist", "mechanism:crashed")),
    (doc(outcome="crashed", utility=-1.0), ("pipeline", "mechanism:crashed")),
    (doc(judge_error=True), ("judge", "mechanism:judge_error")),
    (doc(cause="mechanism:judge_error"), ("judge", "mechanism:judge_error")),
    (doc(cause="mechanism:transient", outcome="crashed", crash_node="classify|sorter"), ("sorter", "mechanism:transient")),
    (doc(cause="input:near_empty"), ("input", "input:near_empty")),
    (doc(cause="label_suspect"), ("label", "label_suspect")),
    (doc(cause="mechanism:scorer_error"), ("scoring", "mechanism:scorer_error")),
    (doc(cause="mechanism:unmapped:thing"), ("pipeline", "mechanism:unmapped:thing")),
    (doc(cause="classification:wrong_class", archived_class="contract", reviewer_doc_type="contract"), ("reviewer", "classification:wrong_class")),
    (doc(cause="classification:wrong_class", archived_class="contract", reviewer_doc_type="correspondence"), ("sorter", "classification:wrong_class")),
    (doc(cause="classification:wrong_class"), ("sorter", "classification:wrong_class")),
    (doc(cause="classification:reviewer_unknown", outcome="review", utility=-0.25), ("reviewer", "classification:reviewer_unknown")),
    (doc(cause="classification:reviewer_disagreement", outcome="review", utility=-0.25), ("reviewer", "classification:reviewer_disagreement")),
    (doc(cause="classification:arbiter_escalated", outcome="review", utility=-0.25), ("arbiter", "classification:arbiter_escalated")),
    (doc(cause="judge:arbiter_escalated", outcome="review", utility=-0.25), ("arbiter", "judge:arbiter_escalated")),
    (doc(cause="judge:rejected", outcome="review", utility=-0.25), ("judge", "judge:rejected")),
    (doc(cause="extraction:missing_field", cls="insurance_claim", outcome="correct_archive", utility=0.6),
     ("insurance_claims_specialist", "extraction:missing_field")),
    (doc(cls="merger_agreement", outcome="correct_archive", utility=0.8), ("merger_agreement_specialist", "extraction:partial")),
    (doc(cause="", outcome="review", utility=-0.25), ("pipeline", "outcome:review")),
])
def test_attribution_rules(d, expected):
    assert dg.attribute(d) == expected


def test_lost_utility_is_one_minus_utility():
    assert dg.lost_utility(doc(utility=-1.0)) == 2.0
    assert dg.lost_utility(doc(utility=0.25, outcome="correct_archive")) == 0.75
    assert dg.lost_utility(doc(utility=1.0, outcome="correct_archive")) == 0.0


def test_weakness_table_orders_by_lost_utility_and_marks_actionable_rows():
    docs = [
        doc("a", "correspondence", cause="classification:reviewer_unknown", outcome="review", utility=-0.25),   # reviewer 1.25
        doc("b", "correspondence", cause="classification:reviewer_unknown", outcome="review", utility=-0.25),   # reviewer 1.25 (same row)
        doc("c", "insurance_claim", cause="extraction:wrong_value", outcome="correct_archive", utility=0.5),    # insurance 0.5
        doc("d", "contract", cause="input:near_empty"),                                                         # input 2.0, non-actionable
        doc("e", "contract", outcome="correct_archive", utility=1.0),                                           # lost nothing
        doc("f", "merger_agreement", outcome="unscorable_archive", utility=0.0),                                # no charge
    ]
    rows = dg.weakness_table(sc.RunScores(run_id="r", run_dir="/x", docs=docs))
    assert [(r.doc_class, r.node, r.docs) for r in rows] == [
        ("correspondence", "reviewer", 2), ("contract", "input", 1), ("insurance_claim", "insurance_claims_specialist", 1)]
    assert [r.lost for r in rows] == [2.5, 2.0, 0.5]
    assert [r.actionable for r in rows] == [True, False, True]
    assert rows[0].causes == {"classification:reviewer_unknown": 2}
    assert dg.node_totals(rows) == {"reviewer": 2.5, "input": 2.0, "insurance_claims_specialist": 0.5}


def test_weakness_markdown_names_the_rules_and_the_unscorable_count():
    docs = [doc("a", "correspondence", cause="classification:reviewer_unknown", outcome="review", utility=-0.25),
            doc("f", "merger_agreement", outcome="unscorable_archive", utility=0.0)]
    md = dg.render_weakness_md(sc.RunScores(run_id="run-1", run_dir="/x", docs=docs))
    assert "# Weakness table: run-1" in md and "| correspondence | reviewer |" in md
    assert "Unscorable archives" in md and "merger_agreement 1" in md
