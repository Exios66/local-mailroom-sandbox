"""Pain-point composites (eval/pain_points.py): classification and extraction penalty points.

The ladder is the client's: a needless human review is the worst outcome on both composites
(4 points), a correct and complete document earns none, a wrong subclass under the right class
costs less than a wrong class, and some correct entities cost less than under a third, which
costs less than a fully fabricated extraction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailroom_sandbox.eval import pain_points as pp
from mailroom_sandbox.eval import runners, scoring

INPUTS = Path(__file__).parent / "fixtures" / "scoring_golden" / "inputs.json"


def _row(doc_class: str | None = "contract", stage: str = "archived", **extra) -> dict:
    return {"expected_doc_class": doc_class, "expected_stage": stage, **extra}


def _result(stage: str = "archived", doc_type: str | None = "contract", **extra) -> dict:
    return {"stage": stage, "doc_type": doc_type, **extra}


def _scored(tp=None, fn=None, fp=0, wrong=0, partial=0, **extra) -> dict:
    out = {"tp": tp, "fn": fn, "fp": fp, "n_value_wrong": wrong, "n_value_partial": partial,
           "scoring_method": "suite", **extra}
    return {k: v for k, v in out.items() if v is not None}


def _cls(row, result, **kw):
    return pp.classification_outcome(row, result, **kw)


def _ext(row, result, scored, **kw):
    return pp.extraction_outcome(row, result, scored, **kw)


class TestClassificationLadder:
    def test_correct_and_complete_costs_nothing(self):
        out = _cls(_row(), _result(), subclass_ok=True)
        assert (out.points, out.reasons) == (0.0, ("correct",))

    def test_unnecessary_review_is_the_worst_outcome(self):
        out = _cls(_row(), _result(stage="review"))
        assert (out.points, out.reason) == (4.0, "unnecessary_review")
        assert out.points == pp.DEFAULT_SCALE.max_points

    def test_necessary_review_costs_nothing(self):
        out = _cls(_row(stage="review"), _result(stage="review", doc_type="other"))
        assert (out.points, out.reason) == (0.0, "necessary_review")

    def test_wrong_subtype_costs_less_than_wrong_doc_type(self):
        subtype = _cls(_row(), _result(), subclass_ok=False)
        doc_type = _cls(_row(), _result(doc_type="corporate_record"), subclass_ok=False)
        assert (subtype.points, subtype.reason) == (1.0, "wrong_subtype")
        assert (doc_type.points, doc_type.reasons) == (3.0, ("wrong_doc_type",))
        assert 0 < subtype.points < doc_type.points < _cls(_row(), _result(stage="review")).points

    def test_missed_review_is_a_misarchive_below_a_wrong_class(self):
        out = _cls(_row(stage="review"), _result())
        assert (out.points, out.reason) == (2.0, "missed_review")

    def test_worst_reason_wins_and_every_reason_is_kept(self):
        out = _cls(_row(stage="review"), _result(doc_type="corporate_record"))
        assert (out.points, out.reasons) == (3.0, ("wrong_doc_type", "missed_review"))

    def test_class_comparison_is_case_insensitive(self):
        assert _cls(_row("Contract"), _result(doc_type=" contract ")).points == 0.0

    def test_archive_without_a_class_is_a_wrong_class(self):
        assert _cls(_row(), _result(doc_type=None)).reason == "wrong_doc_type"

    @pytest.mark.parametrize("result", [
        _result(error="boom"), _result(stage="failed"), _result(stage=None), _result(stage="extract"),
    ])
    def test_errors_and_unfinished_documents_are_pipeline_failures(self, result):
        out = _cls(_row(), result)
        assert (out.points, out.reason) == (4.0, "pipeline_failure")

    def test_unlabelled_row_is_never_scored(self):
        assert _cls(_row(None), _result()) is None
        assert _cls(_row(" "), _result()) is None

    def test_missing_expected_stage_defaults_to_archived(self):
        row = {"expected_doc_class": "contract"}
        assert _cls(row, _result(stage="review")).reason == "unnecessary_review"


class TestExtractionLadder:
    def test_complete_extraction_costs_nothing(self):
        out = _ext(_row(), _result(), _scored(tp=5, fn=0))
        assert (out.points, out.reason) == (0.0, "complete")

    def test_some_valid_entities_are_partial(self):
        assert _ext(_row(), _result(), _scored(tp=2, fn=1)).reason == "partial"
        # Exactly a third reported correctly is not under a third.
        assert _ext(_row(), _result(), _scored(tp=1, fn=2)).reason == "partial"

    def test_under_a_third_is_low_recall(self):
        out = _ext(_row(), _result(), _scored(tp=1, fn=3))
        assert (out.points, out.reason) == (2.0, "low_recall")

    def test_extraction_that_stated_nothing_is_low_recall(self):
        assert _ext(_row(), _result(), _scored(tp=0, fn=4)).reason == "low_recall"

    def test_fully_fabricated_extraction(self):
        wrong_values = _ext(_row(), _result(), _scored(tp=0, fn=4, wrong=4))
        invented_fields = _ext(_row(), _result(), _scored(tp=0, fn=4, fp=2))
        assert (wrong_values.points, wrong_values.reason) == (3.0, "fabricated")
        assert invented_fields.reason == "fabricated"

    def test_near_misses_are_not_fabrication(self):
        out = _ext(_row(), _result(), _scored(tp=0, fn=4, wrong=2, partial=2))
        assert out.reason == "low_recall"

    def test_one_correct_entity_is_not_fully_fabricated(self):
        out = _ext(_row(), _result(), _scored(tp=1, fn=9, wrong=9))
        assert out.reason == "low_recall"

    def test_invented_values_beside_a_full_recall_are_not_complete(self):
        assert _ext(_row(), _result(), _scored(tp=4, fn=0, fp=1)).reason == "partial"

    def test_only_empty_truth(self):
        assert _ext(_row(), _result(), _scored(tp=0, fn=0)).reason == "complete"
        assert _ext(_row(), _result(), _scored(tp=0, fn=0, fp=1)).reason == "fabricated"

    def test_ladder_order_matches_the_client(self):
        points = {
            "unnecessary_review": _ext(_row(), _result(stage="review"), _scored(tp=5, fn=0)).points,
            "fabricated": _ext(_row(), _result(), _scored(tp=0, fn=3, wrong=3)).points,
            "low_recall": _ext(_row(), _result(), _scored(tp=0, fn=3)).points,
            "partial": _ext(_row(), _result(), _scored(tp=2, fn=1)).points,
            "complete": _ext(_row(), _result(), _scored(tp=3, fn=0)).points,
        }
        assert list(points.values()) == sorted(points.values(), reverse=True)
        assert len(set(points.values())) == len(points)
        assert points["complete"] == 0.0

    def test_review_outcomes_override_the_extraction(self):
        assert _ext(_row(), _result(stage="review"), _scored(tp=5, fn=0)).reason == "unnecessary_review"
        assert _ext(_row(stage="review"), _result(stage="review"), _scored(tp=0, fn=5)).reason == "necessary_review"
        assert _ext(_row(), _result(error="boom"), _scored(tp=5, fn=0)).reason == "pipeline_failure"

    def test_rows_without_field_truth_or_class_are_not_scored(self):
        assert _ext(_row(), _result(), None) is None
        assert _ext(_row(None), _result(), _scored(tp=1, fn=0)) is None

    def test_scorer_without_any_figure_is_left_out(self):
        assert _ext(_row(), _result(), {"scoring_method": "suite"}) is None

    @pytest.mark.parametrize("method", ["suite+maud", "suite+cuad"])
    def test_clause_label_rows_use_the_headline_share(self, method):
        # Clause-label rows carry suite event counts that never meet their truth: ignore them.
        base = {"tp": 0, "fn": 9, "n_value_wrong": 9, "scoring_method": method}
        assert _ext(_row(), _result(), {**base, "overall_extraction_score": 1.0}).reason == "complete"
        assert _ext(_row(), _result(), {**base, "overall_extraction_score": 0.5}).reason == "partial"
        assert _ext(_row(), _result(), {**base, "overall_extraction_score": 0.1}).reason == "low_recall"

    def test_rows_without_event_counts_use_the_headline_share(self):
        assert _ext(_row(), _result(), {"overall_extraction_score": 0.2}).reason == "low_recall"


class TestPenaltyScale:
    def test_default_scale_is_profile_amfam_v1(self):
        scale = pp.PenaltyScale()
        assert (scale.unnecessary_review, scale.wrong_doc_type, scale.missed_review, scale.wrong_subtype) == (4, 3, 2, 1)
        assert (scale.fabricated, scale.low_recall, scale.partial) == (3, 2, 1)
        assert scale.low_recall_below == pytest.approx(1 / 3)
        assert pp.PROFILE == "amfam-v1"

    @pytest.mark.parametrize("override", [
        {"fabricated": 4.0},  # must stay under a needless review
        {"wrong_subtype": 3.0},  # must stay under a wrong class
        {"low_recall": 0.5},  # must stay over partial
        {"missed_review": 3.0},  # must stay under a wrong class
        {"pipeline_failure": 5.0},
        {"low_recall_below": 1.0},
    ])
    def test_scale_refuses_an_order_the_client_did_not_ask_for(self, override):
        with pytest.raises(ValueError):
            pp.PenaltyScale(**override)

    def test_custom_scale_flows_through(self):
        scale = pp.PenaltyScale(unnecessary_review=10.0, pipeline_failure=10.0)
        assert _cls(_row(), _result(stage="review"), scale=scale).points == 10.0


class TestRunSummary:
    def test_summary_counts_means_score_reasons_and_classes(self):
        out = pp.summarize([
            (pp.Outcome(4.0, ("unnecessary_review",)), "contract"),
            (pp.Outcome(0.0, ("correct",)), "contract"),
            (pp.Outcome(1.0, ("wrong_subtype",)), "corporate_record"),
            (None, "contract"),
        ], pp.CLASSIFICATION_REASONS)
        assert (out["n"], out["excluded"], out["points"]) == (3, 1, 5.0)
        assert out["mean"] == pytest.approx(5 / 3, abs=1e-6)
        assert out["score"] == pytest.approx(1 - (5 / 3) / 4, abs=1e-6)
        assert list(out["reasons"]) == list(pp.CLASSIFICATION_REASONS)
        assert out["reasons"]["unnecessary_review"] == 1 and out["reasons"]["missed_review"] == 0
        assert out["by_class"]["contract"] == {"n": 2, "points": 4.0, "mean": 2.0}

    def test_empty_run_has_no_mean(self):
        out = pp.summarize([], pp.EXTRACTION_REASONS)
        assert (out["n"], out["mean"], out["score"]) == (0, None, None)

    def test_for_pipeline_reports_both_composites_dual(self):
        rows = [_row(), _row(), _row("contract", stage="review"), _row(None)]
        results = [_result(), _result(stage="review"), _result(stage="review"), _result()]
        scored = [_scored(tp=3, fn=0), None, _scored(tp=0, fn=3), None]
        out = pp.for_pipeline(rows, results, scored)
        block = out["pain_points"]
        assert block["profile"] == "amfam-v1" and block["scale"]["unnecessary_review"] == 4.0
        cls = block["classification"]
        assert (cls["n"], cls["excluded"], cls["points"]) == (3, 1, 4.0)
        assert cls["reasons"]["unnecessary_review"] == 1 and cls["reasons"]["necessary_review"] == 1
        ext = block["extraction"]
        assert (ext["n"], ext["excluded"], ext["points"]) == (2, 2, 0.0)
        assert out["pain_points_classification_mean"] == cls["mean"]
        assert out["pain_points_extraction_mean"] == ext["mean"] == 0.0
        assert set(block["raw_dojo"]) == {"classification", "extraction"}
        assert block["scoring_hotfixes_changed"] == []

    def test_raw_side_reads_the_raw_dojo_counts(self):
        # A hotfix moved this row's event counts: the headline is complete, the raw side is not.
        scored = {**_scored(tp=3, fn=0), "raw_dojo": {"tp": 1, "fn": 2, "fp": 0}, "scoring_hotfixes": ["SHF-002"]}
        block = pp.for_pipeline([_row()], [_result()], [scored])["pain_points"]
        assert block["extraction"]["reasons"]["complete"] == 1
        assert block["raw_dojo"]["extraction"]["reasons"]["partial"] == 1
        assert block["scoring_hotfixes_changed"] == ["extraction"]
        assert "SHF-002" in block["scoring_hotfixes"]

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            pp.for_pipeline([_row(), _row()], [_result()])
        with pytest.raises(ValueError):
            pp.for_pipeline([_row()], [_result()], [None, None])

    def test_item_points_persist_per_document(self):
        out = pp.item_points(_row(), _result(stage="review"), _scored(tp=3, fn=0))
        assert out == {"pain_points_classification_points": 4.0,
                       "pain_points_classification_reason": "unnecessary_review",
                       "pain_points_extraction_points": 4.0,
                       "pain_points_extraction_reason": "unnecessary_review"}
        assert pp.item_points(_row(None), _result(), None) == {}


class TestThroughTheScorer:
    """The extraction ladder on real Dojo scores of a golden correspondence case."""

    @pytest.fixture()
    def case(self):
        return next(c for c in json.loads(INPUTS.read_text())["cases"] if c["doc_type"] == "correspondence")

    def _reason(self, case, predicted):
        scored = scoring.score_extraction_row(case["doc_type"], predicted, case["expected"])
        return _ext(_row(case["doc_type"]), _result(doc_type=case["doc_type"]), scored).reason, scored

    def test_exact_copy_is_complete(self, case):
        reason, scored = self._reason(case, case["expected"])
        assert reason == "complete" and scored["n_value_wrong"] == 0

    def test_blank_extraction_is_low_recall(self, case):
        reason, scored = self._reason(case, {})
        assert reason == "low_recall" and scored["n_value_wrong"] == 0 and scored["tp"] == 0

    def test_invented_values_are_fabricated(self, case):
        invented = {k: "zzqq entirely invented value" for k in case["expected"]}
        reason, scored = self._reason(case, invented)
        assert reason == "fabricated" and scored["n_value_wrong"] > 0
        assert scored["raw_dojo"]["n_value_wrong"] == scored["n_value_wrong"]

    def test_half_right_is_partial(self, case):
        keys = [k for k, v in case["expected"].items() if v not in (None, "", [])]
        half = {k: case["expected"][k] for k in keys[: len(keys) // 2 + 1]}
        reason, _ = self._reason(case, half)
        assert reason == "partial"


def _detailed_cases():
    """Golden cases scored on the detailed suite path (a subclass, or a corporate record)."""
    cases = json.loads(INPUTS.read_text())["cases"]
    picked: dict[tuple[str, bool], dict] = {}
    for case in cases:
        if case["doc_type"] in ("contract", "merger_agreement"):
            continue  # clause-label truth on live rows; the share path is tested separately
        subclass = bool(case.get("doc_subclass") or case.get("expected_subclass"))
        if subclass or case["doc_type"] == "corporate_record":
            picked.setdefault((case["doc_type"], subclass), case)
    return [pytest.param(c, id=f"{k[0]}-subclass={k[1]}") for k, c in sorted(picked.items())]


@pytest.mark.parametrize("case", _detailed_cases())
def test_detailed_rows_can_be_fabricated(case):
    """Regression (Bugbot on #393): the detailed suite path returns no tp / fn, and the composite
    fell back to the soft headline share, so a fully invented extraction was never fabricated."""
    expected = case["expected"]
    kwargs = {"doc_subclass": case.get("doc_subclass"), "expected_subclass": case.get("expected_subclass")}
    stated = [k for k, v in expected.items() if v not in (None, "", [], {})]

    def reason(predicted):
        scored = scoring.score_extraction_row(case["doc_type"], predicted, expected, **kwargs)
        return _ext(_row(case["doc_type"]), _result(doc_type=case["doc_type"]), scored).reason

    assert reason(dict(expected)) == "complete"
    assert reason({k: "zzqq entirely invented value" for k in stated}) == "fabricated"
    assert reason({}) == "low_recall"


def test_per_field_counts_stand_in_for_missing_event_counts():
    scored = {"n_targeted": 4, "n_value_correct": 0, "n_value_wrong": 4, "scoring_method": "suite",
              "overall_extraction_score": 0.4}
    assert _ext(_row(), _result(), scored).reason == "fabricated"
    assert _ext(_row(), _result(), {**scored, "n_value_correct": 2, "n_value_wrong": 0}).reason == "partial"
    # Without fp, documented-absence hallucinations count as values invented on empty truth.
    hallucinated = {"n_targeted": 2, "n_value_correct": 2, "n_hallucinated": 1, "scoring_method": "suite"}
    assert _ext(_row(), _result(), hallucinated).reason == "partial"
    # Dojo event counts win when both are present.
    both = {"tp": 3, "fn": 0, "fp": 0, "n_targeted": 3, "n_value_correct": 0, "scoring_method": "suite"}
    assert _ext(_row(), _result(), both).reason == "complete"


@pytest.mark.parametrize("placeholder", ["n/a", "N/A", "null", "none", "nan", "[]", "{}", "n.a."])
def test_placeholder_predictions_are_blank_not_wrong(placeholder):
    """Regression (CodeAnt on #393): the Dojo scores these placeholders as blank, so a field
    "filled" with one is a plain miss, never an invented value that could make an extraction
    fabricated."""
    out = scoring._field_value_outcomes({"a": "x", "b": "y"}, {"a": placeholder, "b": placeholder},
                                        {"a": 0.0, "b": 0.0})
    assert out == {"n_targeted": 2, "n_value_correct": 0, "n_value_wrong": 0, "n_value_partial": 0}
    scored = {"n_targeted": 2, "n_value_correct": 0, "scoring_method": "suite", **out}
    assert _ext(_row(), _result(), scored).reason == "low_recall"


def test_field_value_outcomes_split_wrong_from_near_misses():
    out = scoring._field_value_outcomes(
        {"a": "x", "b": "y", "c": "z", "d": "w", "e": ""},
        {"a": "x", "b": "nope", "c": "close", "d": "", "e": "invented"},
        {"a": 1.0, "b": 0.1, "c": 0.8, "d": 0.0, "e": 0.0},
    )
    # a correct, b wrong, c near miss, d blank (a plain miss), e empty truth (an fp, not counted here).
    assert out == {"n_targeted": 4, "n_value_correct": 1, "n_value_wrong": 1, "n_value_partial": 1}
    assert scoring._field_value_outcomes({"a": "x"}, {"a": "y"}, None) == {}


def test_pipeline_run_reports_pain_points(monkeypatch):
    rows = [{"id": "0", "expected_doc_class": "contract", "doc_text": "x"},
            {"id": "1", "expected_doc_class": "correspondence", "doc_text": "x"}]

    def fake_doc(row, **_kw):
        stage = "review" if row["id"] == "1" else "archived"
        return {"id": row["id"], "doc_type": row["expected_doc_class"], "stage": stage, "extracted_data": {}}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    items: list[dict] = []
    result = runners.run_pipeline_eval(profile="ollama", rows=rows, mock=False, connected=False, row_cb=items.append)
    scores = result["scores"]
    assert scores["pain_points"]["classification"]["reasons"]["unnecessary_review"] == 1
    assert scores["pain_points_classification_mean"] == 2.0
    # Not connected: no document has scored field truth, so the extraction composite is silent.
    assert scores["pain_points"]["extraction"]["n"] == 0 and scores["pain_points_extraction_mean"] is None
    by_id = {item["id"]: item["score"] for item in items}
    assert by_id["0"]["pain_points_classification_points"] == 0.0
    assert by_id["1"]["pain_points_classification_reason"] == "unnecessary_review"
