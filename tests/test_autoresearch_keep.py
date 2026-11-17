"""Autoresearch keep rule."""
from __future__ import annotations

import math

from mailroom_sandbox.autoresearch import keep
from mailroom_sandbox.autoresearch import scoring as sc


def delta(mean=0.1, low=0.05, high=0.15, n=10, by_class=None):
    return sc.PairedDelta(n=n, mean=mean, ci_low=low, ci_high=high, ci=0.9, n_boot=100, seed=0,
                          by_class=by_class or {"contract": {"n": 5.0, "mean": mean}, "correspondence": {"n": 5.0, "mean": mean}})


def scores(wrong=0, cost=0.01, n=10):
    docs = [sc.DocScore(id=f"d{i}", doc_class="contract", outcome="wrong_archive" if i < wrong else "correct_archive",
                        utility=-1.0 if i < wrong else 1.0, cost_usd=cost) for i in range(n)]
    return sc.RunScores(run_id="r", run_dir="/x", docs=docs)


def decide(champ=None, cand=None, d=None, **kw):
    return keep.decide_keep(champ or scores(), cand or scores(), d or delta(), **kw)


def test_keeps_a_real_gain():
    ok, why = decide()
    assert ok and any("gain is real" in r for r in why)


def test_reverts_when_the_interval_includes_zero():
    ok, why = decide(d=delta(mean=0.04, low=0.0, high=0.08))
    assert not ok and any("not established" in r for r in why)
    ok, _ = decide(d=delta(mean=0.04, low=-0.02, high=0.1))
    assert not ok


def test_noise_floor_raises_the_bar_and_a_negative_floor_does_not_lower_it():
    assert decide(d=delta(low=0.03), noise_floor=0.02)[0]
    ok, why = decide(d=delta(low=0.03), noise_floor=0.05)
    assert not ok and any("<= 0.05" in r for r in why)
    assert not decide(d=delta(mean=0.0, low=-0.01, high=0.01), noise_floor=-1.0)[0]


def test_a_guarded_class_dropping_more_than_005_reverts_even_with_a_pooled_gain():
    by_class = {"contract": {"n": 5.0, "mean": 0.3}, "correspondence": {"n": 5.0, "mean": -0.06}}
    ok, why = decide(d=delta(by_class=by_class))
    assert not ok and any("class drop: correspondence -0.060" in r for r in why)
    by_class["correspondence"]["mean"] = -0.05
    assert decide(d=delta(by_class=by_class))[0]                    # exactly the limit passes


def test_guard_classes_restricts_the_class_check():
    by_class = {"contract": {"n": 5.0, "mean": 0.3}, "merger_agreement": {"n": 1.0, "mean": -0.9}}
    assert not decide(d=delta(by_class=by_class))[0]
    assert decide(d=delta(by_class=by_class), guard_classes=["contract"])[0]


def test_more_wrong_archives_reverts():
    ok, why = decide(champ=scores(wrong=1), cand=scores(wrong=2))
    assert not ok and any("wrong archives rose: 2 > champion 1" in r for r in why)
    assert decide(champ=scores(wrong=1), cand=scores(wrong=1))[0]
    assert decide(champ=scores(wrong=2), cand=scores(wrong=0))[0]


def test_cost_over_125x_needs_a_gain_of_005():
    ok, why = decide(cand=scores(cost=0.02), d=delta(mean=0.04, low=0.01))
    assert not ok and any("over 1.25 x" in r for r in why)
    ok, why = decide(cand=scores(cost=0.02), d=delta(mean=0.05, low=0.01))
    assert ok and any("paid for by gain" in r for r in why)
    assert decide(cand=scores(cost=0.0125), d=delta(mean=0.04, low=0.01))[0]      # exactly 1.25x passes


def test_a_champion_with_no_priced_usage_skips_the_cost_rule():
    ok, why = decide(champ=scores(cost=0.0), cand=scores(cost=5.0))
    assert ok and any("cost rule not applied" in r for r in why)


def test_no_common_documents_never_keeps():
    ok, why = decide(d=sc.PairedDelta(0, math.nan, math.nan, math.nan, 0.9, 10, 0, {}))
    assert not ok and "different draw" in why[0]


def test_cost_goal_accepts_a_cheaper_equal_candidate_and_rejects_a_worse_or_dearer_one():
    cheap = scores(cost=0.008)
    ok, why = decide(cand=cheap, d=delta(mean=0.0, low=-0.01, high=0.01), goal="cost")
    assert ok and any("saves cost" in r for r in why)
    ok, why = decide(cand=cheap, d=delta(mean=-0.05, low=-0.08, high=-0.02), goal="cost")
    assert not ok and any("worse" in r for r in why)
    ok, why = decide(cand=scores(cost=0.0095), d=delta(mean=0.0, low=-0.01, high=0.01), goal="cost")
    assert not ok and any("no saving" in r for r in why)
    ok, why = decide(champ=scores(cost=0.0), cand=cheap, d=delta(mean=0.0, low=-0.01, high=0.01), goal="cost")
    assert not ok and any("recorded no priced usage" in r for r in why)
