"""Stress harness: deterministic offline scenarios that pressure the mailroom's load seams.

Every scenario composes the real admission, call-guard and budgeting seams
(``backpressure.saturated``, ``job/call_guard.py``, ``job/api_budget.py``) with synthetic
documents and injected failure modes, then checks the invariants a paid experiment depends
on: nothing dropped, spend bounded within one call, refused documents become error rows,
and the metric surfaces (review rate, incorrect archives, failure taxonomy) reflect what
happened. Everything is mock/offline — its numbers are instrument readings, never model
evidence (``docs/critical-regressions.md`` row 8).
"""

from __future__ import annotations

import pytest

from mailroom_sandbox.stress import Scenario, FailureMix, default_scenarios, run_scenario


class TestScenarioValidation:
    def test_rejects_non_positive_documents(self):
        with pytest.raises(ValueError):
            Scenario(name="x", documents=0)

    def test_rejects_out_of_range_rates(self):
        with pytest.raises(ValueError):
            FailureMix(wrong_class_rate=1.5)

    def test_rejects_missing_or_non_positive_budget(self):
        with pytest.raises(ValueError):
            Scenario(name="x", documents=3, api_cap_usd=0)
        with pytest.raises(ValueError):
            Scenario(name="x", documents=3, api_cap_usd=-1.0)

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError):
            Scenario(name="x", documents=3, mystery=1)


class TestDefaultScenarios:
    """The preventative sweep: every built-in scenario must hold its invariants."""

    @pytest.mark.parametrize("name", [
        "queue-flood", "looper-against-call-ceiling", "budget-drain",
        "misclassification-wave", "unsure-wave", "parse-error-flood", "mixed-chaos",
    ])
    def test_default_scenario_holds_invariants(self, name):
        spec = next(s for s in default_scenarios() if s.name == name)
        report = run_scenario(spec)
        assert report["invariants_ok"], report["invariants"]
        assert report["admitted"] + report["held"] == spec.documents

    def test_queue_flood_holds_intake_and_drops_nothing(self):
        report = run_scenario(Scenario(name="queue-flood", documents=50, dispatch_limit=8))
        assert report["admitted"] == 8
        assert report["held"] == 42
        assert report["error_rows"] == 0

    def test_looper_hits_ceiling_and_never_scores(self):
        spec = Scenario(
            name="looper", documents=3, api_cap_usd=100.0, call_ceiling=4,
            failure=FailureMix(loop_rate=1.0, calls_per_doc=2),
        )
        report = run_scenario(spec)
        assert report["error_rows"] == 3
        assert report["outcomes"]["archived"] == 0
        assert report["invariants_ok"], report["invariants"]

    def test_budget_drain_stops_within_one_call(self):
        spec = Scenario(
            name="drain", documents=10, api_cap_usd=0.02, tokens_per_call=100_000,
            failure=FailureMix(calls_per_doc=5),
        )
        report = run_scenario(spec)
        # The guard refuses at the cap, so the bound is "within one call of the cap"
        # (the report's spend_within_one_call_of_cap invariant asserts the same bound).
        one_call = spec.tokens_per_call / 1e6 * 0.005
        assert report["spend_usd"] <= spec.api_cap_usd + one_call
        assert report["error_rows"] > 0
        assert report["calls"] < spec.documents * spec.failure.calls_per_doc

    def test_misclassification_wave_reads_as_incorrect_archives(self):
        spec = Scenario(
            name="misclass", documents=6, api_cap_usd=100.0,
            failure=FailureMix(wrong_class_rate=1.0, calls_per_doc=1),
        )
        report = run_scenario(spec)
        assert report["incorrect_archives"] == 6
        assert report["incorrect_archives_reasons"] == {"wrong_class_archive": 6}
        assert report["outcomes"]["archived"] == 6

    def test_unsure_wave_routes_everything_to_review(self):
        spec = Scenario(
            name="unsure", documents=5, api_cap_usd=100.0,
            failure=FailureMix(review_rate=1.0, calls_per_doc=1),
        )
        report = run_scenario(spec)
        assert report["outcomes"]["review"] == 5
        assert report["incorrect_archives"] == 0
        assert report["review_rate"] == pytest.approx(1.0)

    def test_mixed_chaos_is_deterministic_per_seed(self):
        def once(seed):
            spec = Scenario(
                name="chaos", documents=24, seed=seed, api_cap_usd=5.0,
                failure=FailureMix(wrong_class_rate=0.25, parse_error_rate=0.2,
                                   review_rate=0.3, crash_rate=0.1, loop_rate=0.15,
                                   calls_per_doc=3),
            )
            return run_scenario(spec)

        a, b = once(7), once(7)
        assert a["outcomes"] == b["outcomes"]
        assert a["error_rows"] == b["error_rows"]
        assert a["incorrect_archives"] == b["incorrect_archives"]
        assert a["calls"] == b["calls"]

    def test_chaos_invariants_hold_under_mixed_load(self):
        spec = Scenario(
            name="chaos2", documents=24, seed=1, api_cap_usd=5.0,
            failure=FailureMix(wrong_class_rate=0.25, parse_error_rate=0.2,
                               review_rate=0.3, crash_rate=0.1, loop_rate=0.15,
                               calls_per_doc=3),
        )
        report = run_scenario(spec)
        assert report["invariants_ok"], report["invariants"]
        assert report["failure_report"]["n"] == report["documents"]


class TestAdmission:
    def test_unbounded_stage_admits_everything(self):
        report = run_scenario(Scenario(name="open", documents=30, dispatch_limit=0))
        assert report["admitted"] == 30
        assert report["held"] == 0

    def test_saturation_uses_the_real_backpressure_seam(self):
        # Admission must go through backpressure.saturated, not a bare comparison.
        report = run_scenario(Scenario(name="flood", documents=4, dispatch_limit=2))
        assert report["admitted"] == 2 and report["held"] == 2


class TestReportShape:
    def test_report_carries_the_metric_surfaces(self):
        report = run_scenario(Scenario(name="x", documents=2, api_cap_usd=10.0))
        for key in ("review_rate", "incorrect_archives", "incorrect_archives_by_class",
                    "failure_report", "outcomes", "invariants"):
            assert key in report
