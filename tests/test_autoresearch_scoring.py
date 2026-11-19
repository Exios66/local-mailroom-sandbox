"""Autoresearch scoring: per-document utility, the paired stratified bootstrap, the cost split."""
from __future__ import annotations

import math

import pytest

from mailroom_sandbox.autoresearch import scoring as sc


def doc(i, cls="contract", outcome="correct_archive", utility=1.0, **kw):
    return sc.DocScore(id=i, doc_class=cls, outcome=outcome, utility=utility, **kw)


def run(docs, **kw):
    return sc.RunScores(run_id="r", run_dir="/x", docs=docs, **kw)


W = sc.UtilityWeights()


@pytest.mark.parametrize("status,expected", [
    ({"outcome": "correct_archive", "score": 0.83}, 0.83),
    ({"outcome": "correct_archive", "score": 1.7}, 1.0),
    ({"outcome": "correct_archive", "score": None}, 0.0),
    ({"outcome": "unscorable_archive"}, 0.0),
    ({"outcome": "review"}, -0.25),
    ({"outcome": "wrong_archive"}, -1.0),
    ({"outcome": "crashed"}, -1.0),
    ({"outcome": "correct_archive", "score": 0.9, "judge_error": True}, -1.0),
    ({"outcome": "something_new"}, -1.0),
])
def test_doc_utility_weights(status, expected):
    assert sc.doc_utility(status, W) == expected


def test_weights_are_configurable():
    weights = sc.UtilityWeights(review=-0.5, wrong_archive=-2.0)
    assert sc.doc_utility({"outcome": "review"}, weights) == -0.5
    assert sc.doc_utility({"outcome": "wrong_archive"}, weights) == -2.0
    with pytest.raises(ValueError):
        sc.UtilityWeights(bogus=1)


def test_roles_classify_agents_and_the_arbiter_node_is_not_an_agent():
    assert sc.role_of("judge") == sc.role_of("arbiter") == sc.role_of("boss") == "oversight"
    assert sc.role_of("sorter_reviewer") == "reviewer"
    assert sc.role_of("sorter") == sc.role_of("contracts_specialist") == "worker"
    assert sc.role_of("classification_arbiter") == "other"


def test_paired_delta_is_deterministic_for_a_seed_and_seed_dependent():
    ids = [f"d{i}" for i in range(12)]
    champ = {i: 0.5 for i in ids}
    cand = {i: 0.5 + (0.3 if n % 3 else -0.1) for n, i in enumerate(ids)}
    classes = {i: ("a" if n % 2 else "b") for n, i in enumerate(ids)}
    first = sc.paired_delta(champ, cand, classes, n_boot=400, seed=7)
    again = sc.paired_delta(champ, cand, classes, n_boot=400, seed=7)
    other = sc.paired_delta(champ, cand, classes, n_boot=400, seed=8)
    assert first == again
    assert (first.ci_low, first.ci_high) != (other.ci_low, other.ci_high)
    assert first.mean == pytest.approx(sum(cand[i] - champ[i] for i in ids) / 12)
    assert first.ci_low <= first.mean <= first.ci_high
    assert first.n == 12 and set(first.by_class) == {"a", "b"}


def test_a_uniform_gain_has_a_tight_positive_interval_and_a_tie_straddles_zero():
    ids = [f"d{i}" for i in range(10)]
    classes = {i: "a" for i in ids}
    gain = sc.paired_delta({i: 0.0 for i in ids}, {i: 0.2 for i in ids}, classes, n_boot=200)
    assert gain.ci_low == pytest.approx(0.2) and gain.ci_high == pytest.approx(0.2)
    mixed = {i: (0.5 if n % 2 else -0.5) for n, i in enumerate(ids)}
    tie = sc.paired_delta({i: 0.0 for i in ids}, mixed, classes, n_boot=500)
    assert tie.mean == pytest.approx(0.0) and tie.ci_low < 0 < tie.ci_high


def test_the_bootstrap_resamples_inside_each_class():
    # class a never changes, class b always gains 1.0: every resample keeps both class sizes, so the
    # mean is exactly (4 * 0 + 2 * 1) / 6 in every draw and the interval collapses onto it.
    champ = {f"a{i}": 0.0 for i in range(4)} | {f"b{i}": 0.0 for i in range(2)}
    cand = {f"a{i}": 0.0 for i in range(4)} | {f"b{i}": 1.0 for i in range(2)}
    classes = {k: k[0] for k in champ}
    out = sc.paired_delta(champ, cand, classes, n_boot=300)
    assert out.mean == pytest.approx(1 / 3)
    assert out.ci_low == pytest.approx(1 / 3) and out.ci_high == pytest.approx(1 / 3)
    assert out.by_class["b"]["mean"] == 1.0 and out.by_class["a"]["mean"] == 0.0


def test_only_documents_in_both_runs_count_and_no_overlap_is_nan():
    out = sc.paired_delta({"a": 0.0, "b": 0.0}, {"b": 1.0, "c": 1.0}, {"a": "x", "b": "x", "c": "x"}, n_boot=50)
    assert out.n == 1 and out.mean == 1.0
    empty = sc.paired_delta({"a": 0.0}, {"z": 1.0}, {}, n_boot=50)
    assert empty.n == 0 and math.isnan(empty.mean)


def test_paired_delta_argument_checks():
    with pytest.raises(ValueError, match="ci"):
        sc.paired_delta({"a": 0}, {"a": 1}, {}, ci=1.0)
    with pytest.raises(ValueError, match="n_boot"):
        sc.paired_delta({"a": 0}, {"a": 1}, {}, n_boot=0)


def test_run_scores_summaries_and_roundtrip():
    docs = [doc("a", utility=1.0), doc("b", "correspondence", "wrong_archive", -1.0),
            doc("c", "correspondence", "review", -0.25), doc("d", outcome="unscorable_archive", utility=0.0)]
    scores = run(docs)
    assert scores.n == 4 and scores.mean_utility == pytest.approx(-0.0625)
    assert scores.mean_by_class() == {"contract": 0.5, "correspondence": -0.625}
    assert scores.wrong_archives == 1 and scores.count("review") == 1
    assert sc.RunScores.from_dict(scores.to_dict()) == scores
    with pytest.raises(ValueError, match="schema"):
        sc.RunScores.from_dict({"schema": "other"})


def test_cost_split_by_role_and_the_oversight_share():
    docs = [doc("a", cost_usd=0.03, cost_by_role={"worker": 0.02, "oversight": 0.01},
                usage_by_agent={"judge": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 2, "models": ["m"]}}),
            doc("b", cost_usd=0.03, cost_by_role={"worker": 0.02, "oversight": 0.005, "reviewer": 0.005},
                usage_by_agent={"judge": {"calls": 2, "prompt_tokens": 5, "completion_tokens": 1, "models": ["n"]}})]
    scores = run(docs, split_available=True)
    assert scores.cost_by_role() == pytest.approx({"worker": 0.04, "oversight": 0.015, "reviewer": 0.005})
    assert scores.oversight_cost_share == pytest.approx(0.375)
    assert scores.cost_per_doc == pytest.approx(0.03)
    assert scores.agent_usage()["judge"] == {"calls": 3, "prompt_tokens": 15, "completion_tokens": 3, "models": ["m", "n"]}
    m = scores.metrics()
    assert m["cost_split"] == "by_agent" and m["oversight_cost_share"] == 0.375
    assert m["cost_by_role"]["worker"] == 0.04


def test_totals_only_runs_have_no_oversight_share():
    scores = run([doc("a", cost_usd=0.02, cost_by_role={"unsplit": 0.02})], split_available=False)
    assert scores.oversight_cost_share is None
    assert scores.metrics()["cost_split"] == "totals_only"


def test_usd_per_utility_point():
    champ = run([doc("a", cost_usd=0.010), doc("b", cost_usd=0.010)])
    cand = run([doc("a", cost_usd=0.014), doc("b", cost_usd=0.014)])
    # +0.004 USD per document for +0.08 utility = 0.0005 USD per 0.01 point
    assert sc.usd_per_utility_point(champ, cand, 0.08) == pytest.approx(0.0005)
    assert sc.usd_per_utility_point(champ, cand, 0.0) is None
    assert sc.usd_per_utility_point(champ, cand, -0.1) is None
    cheaper = run([doc("a", cost_usd=0.006), doc("b", cost_usd=0.006)])
    assert sc.usd_per_utility_point(champ, cheaper, 0.04) < 0     # better and cheaper


def test_usage_by_agent_is_read_from_the_pipeline_accumulator(monkeypatch):
    import sys
    import types

    from mailroom_sandbox.job import usage_capture

    fake = types.ModuleType("pipeline.limits")
    fake.usage_summary = lambda: {"by_agent": {"judge": {"calls": 2, "prompt_tokens": "30", "completion_tokens": 4, "models": ["m"]},
                                               "sorter": {"calls": 1, "prompt_tokens": 7}}}
    monkeypatch.setitem(sys.modules, "pipeline.limits", fake)
    assert usage_capture.usage_by_agent_from_pipeline() == {
        "judge": {"calls": 2, "prompt_tokens": 30, "completion_tokens": 4, "models": ["m"]},
        "sorter": {"calls": 1, "prompt_tokens": 7, "completion_tokens": 0, "models": []}}
    fake.usage_summary = lambda: (_ for _ in ()).throw(RuntimeError("no accumulator"))
    assert usage_capture.usage_by_agent_from_pipeline() == {}


@pytest.mark.parametrize("by_agent", [
    {"judge": {"calls": "many", "prompt_tokens": 3}},        # a non-numeric count
    {"judge": "not-a-slot"},                                 # a slot that is not a mapping
    {"judge": {"calls": 1, "models": 7}},                    # models that cannot be iterated
])
def test_a_malformed_usage_slot_is_soft_and_logged_not_raised(monkeypatch, caplog, by_agent):
    import sys
    import types

    from mailroom_sandbox.job import usage_capture

    fake = types.ModuleType("pipeline.limits")
    fake.usage_summary = lambda: {"by_agent": by_agent}
    monkeypatch.setitem(sys.modules, "pipeline.limits", fake)
    with caplog.at_level("WARNING", logger="mailroom_sandbox.job.usage_capture"):
        assert usage_capture.usage_by_agent_from_pipeline() == {}      # a billed document is never failed by telemetry
    assert any("per-agent usage capture failed" in r.getMessage() for r in caplog.records)


# ---- an unpriced recorded model is reported, never repriced at the engine model --------------------------------

def test_agent_cost_prices_a_recorded_model_and_the_engine_only_for_a_slot_with_no_model():
    slot = {"calls": 1, "prompt_tokens": 1_000_000, "completion_tokens": 0, "models": ["qwen/qwen3.7-flash"]}
    usd, model = sc.agent_cost(slot, "anthropic/claude-sonnet-5.5")
    assert model == "qwen/qwen3.7-flash" and usd == pytest.approx(0.2)           # its own model, not the fallback
    usd, model = sc.agent_cost({**slot, "models": []}, "qwen/qwen3.7-flash")      # no recorded model: the engine model
    assert model == "qwen/qwen3.7-flash" and usd == pytest.approx(0.2)
    assert sc.agent_cost({**slot, "models": ["mock"]}, "qwen/qwen3.7-flash") == (0.0, "mock")


def test_agent_cost_leaves_an_unpriced_recorded_model_unpriced_even_with_a_priced_engine_model():
    slot = {"calls": 1, "prompt_tokens": 1000, "completion_tokens": 100, "models": ["nobody/unpriced-model-9"]}
    assert sc.agent_cost(slot, "qwen/qwen3.7-flash") == (None, "nobody/unpriced-model-9")     # was: priced at the engine model
    assert sc.unpriced_models(slot) == ["nobody/unpriced-model-9"]
    mixed = {**slot, "models": ["qwen/qwen3.7-flash", "nobody/unpriced-model-9"]}
    assert sc.unpriced_models(mixed) == ["nobody/unpriced-model-9"] and sc.agent_cost(mixed, None)[1] == "qwen/qwen3.7-flash"
    assert sc.unpriced_models({"models": ["mock", "qwen/qwen3.7-flash"]}) == []


def test_score_run_lists_the_unpriced_recorded_model_and_charges_nothing_for_it(tmp_path, monkeypatch):
    import json

    from mailroom_sandbox.job import gate

    report = {"docs": [{"id": "a", "class": "contract", "outcome": "correct_archive", "score": 1.0, "tokens": 5}]}
    monkeypatch.setattr(gate, "gate_report", lambda *a, **k: report)
    monkeypatch.setattr(gate, "load_bars", lambda *a, **k: None)
    (tmp_path / "items.jsonl").write_text(json.dumps({"item_id": "a", "usage_by_agent": {
        "judge": {"calls": 1, "prompt_tokens": 1000, "completion_tokens": 100, "models": ["nobody/unpriced-model-9"]},
        "sorter": {"calls": 1, "prompt_tokens": 1_000_000, "completion_tokens": 0, "models": ["qwen/qwen3.7-flash"]}}}) + "\n")
    (tmp_path / "dataset.jsonl").write_text(json.dumps({"id": "a"}) + "\n")
    scores = sc.score_run(tmp_path, price_model="qwen/qwen3.7-flash")
    assert scores.unpriced == ["nobody/unpriced-model-9"]
    assert scores.docs[0].cost_by_role == {"worker": pytest.approx(0.2)}          # no oversight cost invented from the engine price
