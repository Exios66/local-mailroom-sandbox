"""Experiment-log explorer figures: computed titles, house lint and deterministic output."""
from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from mailroom_sandbox import log_figures as lf  # noqa: E402
from mailroom_sandbox.figure_style import lint_svg  # noqa: E402


def _record(task="sorter", fp="fp1", exact=1.0, n=10, mock=False, model="org/model-a", prompt="v1",
            ts="2026-11-20T00:00:00+00:00", name="run"):
    return {"task": task, "dataset_fingerprint": fp, "scores": {"exact_match": exact}, "n": n, "mock": mock,
            "model": model, "prompt_version": prompt, "timestamp": ts, "experiment_name": name}


def _rows(*records):
    return [lf.flatten_record(r) for r in records]


def test_flatten_record_reads_identity_and_exact_match():
    row = lf.flatten_record({**_record(), "git": {"sha": "0123456789abcdef"}})
    assert row["task"] == "sorter" and row["fingerprint"] == "fp1" and row["n"] == 10
    assert row["exact_match"] == 1.0 and row["git"] == "0123456789"
    assert lf.flatten_record({"scores": {"n": 4, "exact_match": 0.5}})["n"] == 4


def test_cohorts_rank_real_runs_first():
    rows = _rows(_record(fp="a", mock=True), _record(fp="a", mock=True), _record(fp="b"))
    assert [c["fingerprint"] for c in lf.cohorts(rows)] == ["b", "a"]


def test_inventory_title_counts_real_and_mock():
    svg, data = lf.inventory_svg(_rows(_record(), _record(mock=True), _record(task="pipeline", mock=True)))
    assert "1 of 3 logged runs are real; the rest are mock plumbing checks" in svg
    assert {d["label"]: (d["real"], d["mock"]) for d in data} == {"LLM sorter": (1, 1), "Pipeline": (0, 1)}
    assert lint_svg(svg) == []


def test_inventory_all_mock_says_none_measures_quality():
    svg, _ = lf.inventory_svg(_rows(_record(mock=True), _record(mock=True)))
    assert "All 2 logged runs are mock plumbing checks" in svg
    svg, _ = lf.inventory_svg(_rows(_record(mock=True)))
    assert "The only logged run is a mock plumbing check" in svg
    svg, _ = lf.trend_svg(_rows(_record(mock=True)), "sorter", "fp1")
    assert "The only run is mock, so exact match is 100% by construction" in svg


def test_setups_title_names_a_clear_leader():
    rows = _rows(_record(exact=0.95, n=100, model="org/strong"), _record(exact=0.4, n=100, model="org/weak"))
    svg, data = lf.setups_svg(rows, "sorter", "fp1")
    assert "Setup strong · v1 leads at 95% exact match" in svg
    assert [d["setup"] for d in data] == ["weak · v1", "strong · v1"]
    assert data[-1]["correct"] == 95 and data[-1]["low"] > data[0]["high"]
    assert lint_svg(svg) == []


def test_setups_title_refuses_to_rank_overlapping_intervals():
    rows = _rows(_record(exact=1.0, n=2, model="org/a"), _record(exact=0.5, n=2, model="org/b"))
    svg, _ = lf.setups_svg(rows, "sorter", "fp1")
    assert "No setup is clearly ahead: the top 2 intervals overlap" in svg


def test_setups_pools_runs_and_ignores_other_cohorts():
    rows = _rows(_record(exact=1.0, n=4), _record(exact=0.5, n=4), _record(fp="other", exact=0.0, n=50))
    _, data = lf.setups_svg(rows, "sorter", "fp1")
    assert data == [pytest.approx({**data[0], "runs": 2, "correct": 6, "scored": 8, "documents": 4, "rate": 0.75})]


def test_repeat_runs_do_not_narrow_the_interval():
    """Repeat runs re-score the same documents, so the interval stays at one run's n."""
    one = lf.setups_svg(_rows(_record(exact=0.5, n=20)), "sorter", "fp1")[1][0]
    five = lf.setups_svg(_rows(*[_record(exact=0.5, n=20) for _ in range(5)]), "sorter", "fp1")[1][0]
    assert (five["low"], five["high"]) == pytest.approx((one["low"], one["high"]))
    assert five["documents"] == 20 and five["scored"] == 100


def test_setups_mock_only_cohort_is_labelled():
    svg, _ = lf.setups_svg(_rows(_record(mock=True)), "sorter", "fp1")
    assert "Only mock runs here, so every setup scores 100% by construction" in svg
    assert lint_svg(svg) == []


def test_trend_title_detects_a_resolvable_move():
    rows = _rows(_record(exact=0.3, n=100, ts="2026-11-01T00:00:00+00:00"),
                 _record(exact=0.9, n=100, ts="2026-11-02T00:00:00+00:00"))
    svg, data = lf.trend_svg(rows, "sorter", "fp1")
    assert "Exact match moved from 30% to 90% over 2 runs" in svg
    assert [d["run"] for d in data] == [1, 2]
    assert lint_svg(svg) == []


def test_trend_title_flags_tiny_runs_as_unresolvable():
    rows = _rows(_record(n=2, ts="2026-11-01T00:00:00+00:00"), _record(n=2, ts="2026-11-02T00:00:00+00:00"))
    svg, _ = lf.trend_svg(rows, "sorter", "fp1")
    assert "Exact match was 100% on every run; no change is resolvable at n = 2 each" in svg


def test_trend_orders_runs_by_utc_time_not_text():
    rows = _rows(_record(exact=0.9, n=100, ts="2026-11-01T08:00:00+05:00", name="early"),
                 _record(exact=0.3, n=100, ts="2026-11-01T04:00:00+00:00", name="late"))
    _, data = lf.trend_svg(rows, "sorter", "fp1")
    assert [d["experiment"] for d in data] == ["early", "late"]


def test_trend_follows_one_setup_and_names_the_rest():
    rows = _rows(*[_record(model="org/a", ts=f"2026-11-0{i}T00:00:00+00:00") for i in (1, 2)],
                 _record(model="org/b", exact=0.0, n=100, ts="2026-11-03T00:00:00+00:00"))
    svg, data = lf.trend_svg(rows, "sorter", "fp1")
    assert {d["setup"] for d in data} == {"a · v1"} and len(data) == 2
    assert "1 other setup not shown" in svg and lint_svg(svg) == []
    _, data = lf.trend_svg(rows, "sorter", "fp1", setup=lf.setup_key(rows[-1]))
    assert [d["rate"] for d in data] == [0.0]


def test_setups_keep_one_model_on_two_serving_paths_apart():
    rows = _rows({**_record(exact=1.0, n=10), "provider": "modal", "profile": "modal_vllm"},
                 {**_record(exact=0.0, n=10), "provider": "openrouter", "profile": "api"})
    svg, data = lf.setups_svg(rows, "sorter", "fp1")
    assert sorted(d["setup"] for d in data) == ["org/model-a · v1 (modal/modal vllm)",
                                               "org/model-a · v1 (openrouter/api)"]
    assert lf.cohorts(rows)[0]["setups"] == 2 and lint_svg(svg) == []


def test_partial_credit_scores_get_no_binomial_interval():
    rows = _rows(_record(exact=0.37, n=10, model="org/a"), _record(exact=0.9, n=10, model="org/b"))
    svg, data = lf.setups_svg(rows, "sorter", "fp1")
    partial, whole = sorted(data, key=lambda d: d["model"])
    assert partial["low"] is None and partial["correct"] is None and whole["correct"] == 9
    assert "partial credit has no interval" in svg and "Mean score" in svg and lint_svg(svg) == []
    svg, data = lf.trend_svg(rows[:1], "sorter", "fp1")
    assert data[0]["partial"] and data[0]["low"] is None and lint_svg(svg) == []


def test_trend_prefers_real_runs_over_mock():
    rows = _rows(_record(mock=True, exact=1.0), _record(exact=0.5, n=4))
    _, data = lf.trend_svg(rows, "sorter", "fp1")
    assert [d["rate"] for d in data] == [0.5]


@pytest.mark.parametrize("build", ["inventory", "setups", "trend"])
def test_figures_are_deterministic_and_handle_empty_input(build):
    rows = _rows(_record(), _record(exact=0.5, n=4, ts="2026-11-21T00:00:00+00:00"))
    fn = {"inventory": lambda r: lf.inventory_svg(r), "setups": lambda r: lf.setups_svg(r, "sorter", "fp1"),
          "trend": lambda r: lf.trend_svg(r, "sorter", "fp1")}[build]
    assert fn(rows)[0] == fn(rows)[0]
    svg, data = fn([])
    assert data == [] and lint_svg(svg) == []


def test_scored_n_prefers_n_scored_then_interval_then_scores_n():
    base = _record(n=3)
    assert lf.scored_n(base) == 3
    assert lf.scored_n({**base, "scores": {"exact_match": 1.0, "n": 2}}) == 2
    assert lf.scored_n({**base, "scores": {"exact_match": 1.0, "n": 3, "exact_match_ci": {"n": 2}}}) == 2
    assert lf.scored_n({**base, "scores": {"exact_match": 1.0, "n": 3, "n_scored": 1}}) == 1


def test_intervals_use_the_scored_documents_not_the_run_rows():
    """SHF-006 leaves rows without truth out of exact_match; counts must use n_scored."""
    record = {**_record(n=10), "scores": {"exact_match": 0.5, "n": 10, "n_scored": 4}}
    _, setups = lf.setups_svg(_rows(record), "sorter", "fp1")
    _, trend = lf.trend_svg(_rows(record), "sorter", "fp1")
    for row in (setups[0], trend[0]):
        assert (row["correct"], row["documents"]) == (2, 4)
        assert row["low"] <= row["rate"] <= row["high"]


def test_setups_keep_models_with_one_short_name_apart():
    rows = _rows(_record(model="org-a/model", exact=1.0, n=10), _record(model="org-b/model", exact=0.0, n=10))
    svg, data = lf.setups_svg(rows, "sorter", "fp1")
    assert sorted(d["setup"] for d in data) == ["org-a/model · v1", "org-b/model · v1"]
    assert [d["documents"] for d in data] == [10, 10]
    assert lf.cohorts(rows)[0]["setups"] == 2
    assert lint_svg(svg) == []


@pytest.mark.parametrize("build", ["setups", "trend"])
def test_long_cohort_subtitles_stay_within_the_house_limit(build):
    rows = _rows(_record(task="correspondence_specialist", fp="abcdef1234567890", mock=True))
    fn = lf.setups_svg if build == "setups" else lf.trend_svg
    svg, _ = fn(rows, "correspondence_specialist", "abcdef1234567890")
    assert lint_svg(svg) == []
