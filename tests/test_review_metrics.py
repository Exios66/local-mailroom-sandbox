"""Review/incorrect-archive metric alignment: the eval-side first-class metric.

The production gate (``job/gate.py``) owns ``wrong_archive`` semantics and stays
authoritative; these tests pin the per-run score surface that pipeline and isolated
runs report beside ``routed_to_human_review`` (``eval/human_review.py``), so the
autoresearch loop and failure debugging can guide on both numbers per class.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.eval import archive_correctness as ac


def _row(doc_class: str, stage: str = "archived", **extra) -> dict:
    return {"expected_doc_class": doc_class, "expected_stage": stage, **extra}


def _result(stage: str = "archived", doc_type: str | None = None, **extra) -> dict:
    return {"stage": stage, "doc_type": doc_type, **extra}


class TestArchiveFlag:
    def test_correct_archive_is_not_flagged(self):
        reasons = ac.archive_reasons(_row("contract"), _result(doc_type="contract"))
        assert reasons == []

    def test_wrong_class_archive(self):
        reasons = ac.archive_reasons(_row("contract"), _result(doc_type="corporate_record"))
        assert reasons == ["wrong_class_archive"]

    def test_stage_should_review(self):
        reasons = ac.archive_reasons(_row("contract", stage="review"), _result(doc_type="contract"))
        assert reasons == ["stage_should_review"]

    def test_incomplete_extraction_archive(self):
        scored = {"overall_extraction_score": 0.5}
        reasons = ac.archive_reasons(_row("contract"), _result(doc_type="contract"), scored=scored)
        assert reasons == ["incomplete_extraction_archive"]

    def test_extraction_at_the_quality_bar_is_complete(self):
        scored = {"overall_extraction_score": 0.90}
        reasons = ac.archive_reasons(_row("contract"), _result(doc_type="contract"), scored=scored)
        assert reasons == []

    def test_parse_error_archive(self):
        reasons = ac.archive_reasons(_row("contract"), _result(doc_type="contract"), parse_error=True)
        assert reasons == ["parse_error_archive"]

    def test_multiple_reasons_keep_gate_precedence(self):
        # Wrong class dominates: the gate counts it as wrong_archive regardless of score.
        reasons = ac.archive_reasons(
            _row("contract", stage="review"),
            _result(doc_type="corporate_record", parse_error=True),
            scored={"overall_extraction_score": 0.5},
        )
        assert reasons == ["wrong_class_archive", "stage_should_review", "incomplete_extraction_archive", "parse_error_archive"]

    def test_non_archived_stages_are_never_flagged(self):
        for stage in ("review", "failed", "unknown", None):
            reasons = ac.archive_reasons(_row("contract"), _result(stage=stage, doc_type="contract"), parse_error=True)
            assert reasons == []

    def test_no_ground_truth_row_cannot_be_called_wrong(self):
        # Without an expected class the metric stays silent: no blind labels (row 1).
        assert ac.archive_reasons(_row(""), _result(doc_type="unknown")) == []

    def test_class_comparison_matches_the_gate_case_insensitively(self):
        # The gate lowercases both sides (job/gate.py is_wrong_class); so must the metric.
        assert ac.archive_reasons(_row("Contract"), _result(doc_type="contract")) == []
        assert ac.archive_reasons(_row("contract"), _result(doc_type="Contract")) == []

    def test_row_result_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            ac.for_pipeline([_row("contract"), _row("contract")], [_result(doc_type="contract")])
        with pytest.raises(ValueError):
            ac.for_pipeline(
                [_row("contract")], [_result(doc_type="contract")],
                extraction_rows=[{"overall_extraction_score": 1.0}, {"overall_extraction_score": 1.0}],
            )


class TestSummarize:
    def test_counts_rate_and_reasons(self):
        rows = [_row("contract"), _row("contract"), _row("insurance_claim")]
        results = [
            _result(doc_type="contract"),
            _result(doc_type="corporate_record"),
            _result(doc_type="insurance_claim", parse_error=True),
        ]
        out = ac.summarize(((ac.archive_reasons(r, s), r.get("expected_doc_class")) for r, s in zip(rows, results)), "pipeline")
        assert out["incorrect_archives"] == 2
        assert out["incorrect_archives_rate"] == pytest.approx(2 / 3, abs=1e-6)
        assert out["incorrect_archives_basis"] == "pipeline"
        assert out["incorrect_archives_by_class"]["contract"]["incorrect"] == 1
        assert out["incorrect_archives_by_class"]["contract"]["n"] == 2
        assert out["incorrect_archives_reasons"] == {
            "wrong_class_archive": 1,
            "parse_error_archive": 1,
        }

    def test_empty_run_reports_none_rate(self):
        out = ac.summarize((([] for _ in ()), ), "pipeline") if False else ac.summarize((), "pipeline")
        assert out["incorrect_archives"] == 0
        assert out["incorrect_archives_rate"] is None
        assert out["incorrect_archives_by_class"] == {}
        assert out["incorrect_archives_reasons"] == {}


class TestForPipeline:
    def test_end_to_end_with_extraction_rows(self):
        rows = [
            _row("contract"),
            _row("corporate_record"),
            _row("contract", stage="review"),
        ]
        results = [
            _result(doc_type="contract"),
            _result(doc_type="contract"),  # archived under the wrong class
            _result(doc_type="contract"),  # archived although it should have been reviewed
        ]
        scored = [None, {"overall_extraction_score": 0.95}, None]
        out = ac.for_pipeline(rows, results, extraction_rows=scored)
        assert out["incorrect_archives"] == 2
        assert out["incorrect_archives_by_class"]["corporate_record"]["incorrect"] == 1
        assert out["incorrect_archives_by_class"]["contract"]["incorrect"] == 1
        assert out["incorrect_archives_basis"] == "pipeline"

    def test_results_without_rows_are_silent(self):
        # A pipeline result alone never claims an archive is wrong without its row.
        out = ac.for_pipeline([{}], [_result(doc_type="contract")])
        assert out["incorrect_archives"] == 0


class TestFailureReport:
    """The debugging aggregation over per-document gate statuses (autoresearch DocScore shape)."""

    def test_counts_outcomes_causes_and_crash_nodes(self):
        statuses = [
            {"doc_class": "contract", "outcome": "wrong_archive", "cause": "wrong_class"},
            {"doc_class": "contract", "outcome": "wrong_archive", "cause": "wrong_class"},
            {"doc_class": "contract", "outcome": "review", "cause": "sorter_low_confidence"},
            {"doc_class": "merger_agreement", "outcome": "crashed", "cause": "intake"},
            {"doc_class": "merger_agreement", "outcome": "correct_archive"},
        ]
        out = ac.failure_report(statuses)
        assert out["outcomes"] == {
            "correct_archive": 1, "wrong_archive": 2, "review": 1, "crashed": 1,
            "unscorable_archive": 0, "judge_error": 0,
        }
        assert out["causes"]["wrong_class"] == 2
        assert out["causes_by_class"]["contract"] == {"wrong_class": 2, "sorter_low_confidence": 1}
        assert out["n"] == 5

    def test_empty_report(self):
        out = ac.failure_report(())
        assert out["n"] == 0
        assert out["outcomes"] == {}
        assert out["causes"] == {}
        assert out["causes_by_class"] == {}


class TestGateAlignment:
    def test_quality_bar_matches_the_production_gate(self):
        # The gate (job/gate.py) owns wrong-archive semantics; the eval metric borrows
        # its bar. If the gate default changes, this pin forces the eval side to follow.
        from mailroom_sandbox.job.gate import Bars

        assert ac.DEFAULT_QUALITY_BAR == Bars.quality

