"""Paired statistics for the runbook keep / transfer / held-out rules (R02)."""

from __future__ import annotations

import math

import pytest

from mailroom_sandbox import experiment_stats as st


def test_mcnemar_exact_matches_binomial():
    # 2 discordant against, 10 for: exact two-sided p = 2 * P(X<=2; 12, .5) = 0.03857
    base = [True] * 2 + [False] * 10 + [True] * 50
    cand = [False] * 2 + [True] * 10 + [True] * 50
    r = st.mcnemar(base, cand)
    assert (r.b, r.c, r.n) == (2, 10, 62)
    assert r.p_value == pytest.approx(0.0385742, abs=1e-6)
    assert r.z == pytest.approx(8 / math.sqrt(12))
    assert r.gain == pytest.approx(8 / 62)


def test_mcnemar_no_discordance_is_null():
    r = st.mcnemar([True, False], [True, False])
    assert r.p_value == 1.0 and r.z == 0.0


def test_mcnemar_rejects_unpaired():
    with pytest.raises(ValueError):
        st.mcnemar([True], [True, False])


def test_holm_step_down():
    adj = st.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})
    assert st.holm([0.5, 0.9]) == {0: 0.5 * 2 if 0.5 * 2 < 1 else 1.0, 1: 1.0}


def test_permutation_detects_shift_and_is_seeded():
    base = [0.5] * 60
    cand = [0.6] * 60
    diff, p = st.paired_permutation(base, cand, n_perm=2000, seed=1)
    assert diff == pytest.approx(0.1)
    assert p < 0.001
    assert st.paired_permutation(base, cand, n_perm=200, seed=1) == st.paired_permutation(base, cand, n_perm=200, seed=1)
    assert st.paired_permutation([0.1, 0.2], [0.1, 0.2]) == (0.0, 1.0)


def test_sequential_keep_rule():
    assert st.keep_at_look(300, 5.0, 0.1, 0.03) == "continue"  # look 1 only screens
    assert st.keep_at_look(600, 2.5, 0.04, 0.03) == "keep"
    assert st.keep_at_look(600, 1.0, 0.01, 0.03) == "drop"  # under half the target
    assert st.keep_at_look(600, 1.0, 0.02, 0.03) == "continue"
    assert st.keep_at_look(900, 2.0, 0.02, 0.03) == "keep"
    assert st.keep_at_look(900, 1.99, 0.02, 0.03) == "drop"
    # a full look that lost docs to failed calls still decides
    assert st.keep_at_look(897, 2.1, 0.02, 0.03, look=3) == "keep"
    assert st.keep_at_look(597, 1.0, 0.01, 0.03, look=2) == "drop"
    with pytest.raises(ValueError):
        st.keep_at_look(900, 2.0, 0.02, 0.03, look=4)


def test_cost_weighted_error():
    confusion = {("contract", "contract"): 8, ("contract", "merger_agreement"): 1, ("claim", "contract"): 1}
    costs = {("contract", "merger_agreement"): 5.0}
    assert st.cost_weighted_error(confusion, costs) == pytest.approx((5.0 + 1.0) / 10)
    assert st.cost_weighted_error({}, costs) == 0.0


def test_null_floors():
    assert st.brier_null_floor([True] * 9 + [False]) == pytest.approx(0.09)
    assert st.brier_null_floor([]) is None
    floor = st.ece_null_floor([0.8] * 200, n_sim=200, seed=2)
    assert 0.0 < floor < 0.1
    assert st.ece_null_floor([0.8] * 200, n_sim=200, seed=2) == floor


def test_dojo_reexports_are_live():
    assert st.clopper_pearson_upper(0, 299) == pytest.approx(0.00997, abs=1e-4)
    assert st.brier_score([(1.0, True), (0.0, False)]) == 0.0
