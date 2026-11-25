"""Sorter-arm head-to-head (runbook H5): pairing refusals, held-out seal, cost arithmetic, paired
tests, non-inferiority, Holm, frontier, planning helpers and the H5 run configs. Offline."""

from __future__ import annotations

import importlib.util
import json
import random
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox import heldout_seal
from mailroom_sandbox import sorter_arms as sa
from mailroom_sandbox.experiment_stats import holm, macro_f1
from mailroom_sandbox.paths import repo_root

REV = "bc9eab280044befb51e19dda3071d290a8677f42"
QWEN = "qwen/qwen3.7-flash"
LUNA = "openai/gpt-6-luna-decisions"
CLASSES = {"insurance_claim": "property", "correspondence": "email", "contract": "Sponsorship"}
RUNS = repo_root() / "config" / "runs"

_CLI = importlib.util.spec_from_file_location("compare_sorter_arms", repo_root() / "scripts" / "compare_sorter_arms.py")
cli = importlib.util.module_from_spec(_CLI)
_CLI.loader.exec_module(cli)


def _docs(n_dev=30, n_held=6):
    docs = []
    classes = list(CLASSES)
    for i in range(n_dev + n_held):
        cls = classes[i % 3]
        docs.append({"id": f"DOC-{i:03d}", "doc_class": cls, "subclass": CLASSES[cls],
                     "set": "dev" if i < n_dev else "heldout",
                     "hf_split": "test" if i % 5 == 0 else "train", "tuned": False,
                     "unit": f"{cls}/{CLASSES[cls]}", "unit_kind": "subclass"})
    return docs


@pytest.fixture
def split(tmp_path):
    d = tmp_path / "split"
    d.mkdir()
    docs = _docs()
    (d / "assignments.jsonl").write_text("".join(json.dumps(r) + "\n" for r in docs), encoding="utf-8")
    dev = [r["id"] for r in docs if r["set"] == "dev"]
    (d / "dev-look1.ids").write_text("# dev-look1\n" + "\n".join(dev[:12]) + "\n", encoding="utf-8")
    (d / "heldout.ids").write_text("# heldout\n" + "\n".join(r["id"] for r in docs if r["set"] == "heldout") + "\n",
                                   encoding="utf-8")
    return d


def _write_run(root: Path, run_id: str, *, task="isolated", model=QWEN, ids, wrong=(), sub_wrong=(), failed=(),
               mock=False, revision=REV, truth_override=None, tokens=(10_000, 100), conf=0.9, qset=None,
               no_usage=(), abstain=None):
    run = root / run_id
    run.mkdir(parents=True)
    lock = {"run_id": run_id, "task": task, "spec_hash": "h-" + run_id, "job": {"mock": mock},
            "engine": {"kind": "openrouter", "model": model},
            "dataset": {"revision": revision, "revision_resolved": revision, "sha256": "s"}}
    if task == "sorter_reviewer":
        lock["reviewer"] = {"backend": "decisions", "model": model, "questions": "q",
                            "question_set": qset or {"name": "q"}}
    else:
        lock["agent_assignments"] = {"sorter": {"model": model, "provider": "openrouter"}}
    (run / "spec.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    rows, items = [], []
    docs = {d["id"]: d for d in _docs()}
    for doc_id in ids:
        d = docs[doc_id]
        cls, sub = d["doc_class"], d["subclass"]
        if truth_override and doc_id in truth_override:
            cls = truth_override[doc_id]
        rows.append({"id": doc_id, "doc_text": "x y", "expected_doc_class": cls, "expected_subclass": sub,
                     "source_revision": revision})
        pred_cls = "correspondence" if (doc_id in wrong and cls != "correspondence") else (
            "contract" if doc_id in wrong else cls)
        pred = {"doc_type": pred_cls, "doc_subclass": "other" if doc_id in sub_wrong else sub,
                ("doc_type_probability" if task == "sorter_reviewer" else "confidence"): conf}
        if abstain and doc_id in abstain:
            pred.update(abstained=True, route_to_human=True, abstain_reasons=[abstain[doc_id]])
        if task == "sorter_reviewer":
            pred["usage"] = {"input_tokens": tokens[0], "output_tokens": 0, "cost": tokens[0] * 0.1 / 1e6}
        item = {"item_id": doc_id, "ok": doc_id not in failed, "error": "boom" if doc_id in failed else None,
                "pred": {} if doc_id in failed else pred, "latency_ms": 1000.0 + int(doc_id[-3:])}
        if doc_id not in no_usage:
            item.update(prompt_tokens=tokens[0], completion_tokens=tokens[1], llm_calls=1)
        items.append(item)
    (run / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return run


def _dev_ids(n=30):
    return [f"DOC-{i:03d}" for i in range(n)]


def _cmp(tmp_path, split, **kw):
    kw.setdefault("n_boot", 300)
    kw.setdefault("n_perm", 300)
    return sa.compare(["A", "B"], split_dir=split, runs_root=tmp_path / "runs", **kw)


# ---------------------------------------------------------------- refusals


def _draw_from(run: Path, split_name: str) -> None:
    lock = json.loads((run / "spec.lock.json").read_text())
    lock["dataset"]["exclude_ids_file"] = f"config/splits/{split_name}/dev-look1.exclude.ids"
    (run / "spec.lock.json").write_text(json.dumps(lock))


def test_runs_from_two_splits_or_another_split_dir_are_refused(tmp_path, split):
    """A run drawn from runbook-v1 is never read against runbook-v2's sets (or a mix of both)."""
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids())
    _draw_from(tmp_path / "runs" / "A", "runbook-v1")
    _draw_from(tmp_path / "runs" / "B", "runbook-v2")
    with pytest.raises(sa.ArmError, match="different splits"):
        _cmp(tmp_path, split)
    _draw_from(tmp_path / "runs" / "B", "runbook-v1")
    with pytest.raises(sa.ArmError, match="is not the split the runs drew from"):
        _cmp(tmp_path, split)
    arms = [sa.load_arm(r, runs_root=tmp_path / "runs") for r in ("A", "B")]
    assert sa._arms_split_dir(arms).name == "runbook-v1"


def test_unpaired_runs_are_refused(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids()[:-1])
    with pytest.raises(sa.ArmError, match="unpaired"):
        _cmp(tmp_path, split)


def test_a_set_restricts_both_runs_and_needs_full_cover(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())           # all of dev
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids()[:12])  # dev-look1 only
    report = _cmp(tmp_path, split, set_name="dev-look1")
    assert report["n"] == 12
    with pytest.raises(sa.ArmError, match="unpaired"):
        _cmp(tmp_path, split, set_name="dev")


def test_revision_mismatch_is_refused(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids(), revision="ed7576b6")
    with pytest.raises(sa.ArmError, match="revisions differ"):
        _cmp(tmp_path, split)


def test_truth_mismatch_is_refused(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids(),
               truth_override={"DOC-003": "contract"})
    with pytest.raises(sa.ArmError, match="truth differs"):
        _cmp(tmp_path, split)


def test_mock_runs_are_refused_unless_allowed(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids(), mock=True)
    with pytest.raises(sa.ArmError, match="mock"):
        _cmp(tmp_path, split)
    assert _cmp(tmp_path, split, allow_mock=True)["n"] == 30


def test_a_handoff_question_set_is_not_a_standalone_sorter(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids())
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids(), qset={"handoff": True})
    with pytest.raises(sa.ArmError, match="handoff"):
        _cmp(tmp_path, split)


def test_a_non_sorter_task_is_refused(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids(), task="pipeline")
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids())
    with pytest.raises(sa.ArmError, match="not a sorter arm"):
        _cmp(tmp_path, split)


def test_heldout_ids_need_the_confirmatory_call_on_sealed_runs(tmp_path, split):
    held = [f"DOC-{i:03d}" for i in range(30, 36)]
    _write_run(tmp_path / "runs", "A", ids=held)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=held)
    with pytest.raises(sa.ArmError, match="sealed held-out"):
        _cmp(tmp_path, split)
    with pytest.raises(sa.ArmError, match="held-out --set"):
        _cmp(tmp_path, split, confirmatory=True)
    with pytest.raises(sa.ArmError, match="sealed-convention"):
        _cmp(tmp_path, split, confirmatory=True, set_name="heldout")
    _write_run(tmp_path / "runs", "rb1-r70-sorter-v0-heldout", ids=held)
    _write_run(tmp_path / "runs", "rb1-r70b-decision-sorter-x-heldout", task="sorter_reviewer", model=LUNA, ids=held)
    report = sa.compare(["rb1-r70-sorter-v0-heldout", "rb1-r70b-decision-sorter-x-heldout"], split_dir=split,
                        runs_root=tmp_path / "runs", set_name="heldout", confirmatory=True, n_boot=50, n_perm=50)
    assert report["confirmatory"] and report["n"] == 6
    assert set(report["strata"]["rb1-r70b-decision-sorter-x-heldout"]) == {"never_tuned", "train_untuned"}


def test_exposure_sets(split):
    assert len(sa.set_ids("heldout", split)) == 6
    never = sa.set_ids("heldout-never-tuned", split)
    assert never == {"DOC-030", "DOC-035"} and never | sa.set_ids("heldout-train", split) == sa.set_ids("heldout", split)
    with pytest.raises(sa.ArmError, match="unknown set"):
        sa.set_ids("test", split)


# ---------------------------------------------------------------- cost


def test_item_cost_prices_both_arms_from_the_catalogs():
    small = {"ok": True, "prompt_tokens": 10_000, "completion_tokens": 100, "llm_calls": 1}
    assert sa.item_cost(QWEN, small) == pytest.approx((10_000 * 0.03 + 100 * 0.13) / 1e6)
    long = {"ok": True, "prompt_tokens": 40_000, "completion_tokens": 200, "llm_calls": 1}
    assert sa.item_cost(QWEN, long) == pytest.approx((40_000 * 0.10 + 200 * 0.40) / 1e6)  # >=32k tier
    assert sa.item_cost(LUNA, {"ok": True, "prompt_tokens": 50_000, "completion_tokens": 0}) == pytest.approx(0.005)
    assert sa.item_cost("typesafe/jev-1.14", {"ok": True, "prompt_tokens": 1_000_000}) == pytest.approx(0.042)
    assert sa.item_cost(QWEN, {"ok": False, "error": "x"}) == 0.0      # failed before billing
    assert sa.item_cost(QWEN, {"ok": True}) is None                   # answered without usage: unpriced


def test_cost_totals_per_1k_monthly_and_difference(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids(), tokens=(10_000, 100))
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids(), tokens=(20_000, 0))
    report = _cmp(tmp_path, split, volume=100_000)
    a, b = report["arms"]
    per_a, per_b = (10_000 * 0.03 + 100 * 0.13) / 1e6, 20_000 * 0.1 / 1e6
    assert a["cost"]["total_usd"] == pytest.approx(30 * per_a)
    assert b["cost"]["per_1k_docs_usd"] == pytest.approx(1000 * per_b)
    assert b["cost"]["provider_reported_usd"] == pytest.approx(30 * per_b)
    assert a["cost"]["per_class_correct_usd"] == pytest.approx(30 * per_a / 30)
    cost = report["pairs"]["B"]["cost"]
    assert cost["per_1k_docs"]["estimate"] == pytest.approx(1000 * (per_b - per_a))
    assert cost["monthly"]["difference"]["estimate"] == pytest.approx(100_000 * (per_b - per_a))
    assert cost["monthly"]["a"]["ci95"] == pytest.approx([100_000 * per_a] * 2)  # constant per-doc cost
    assert cost["lower_cost_p_value"] > 0.5  # B is dearer here


def test_unpriced_items_make_cost_unavailable_not_zero(tmp_path, split):
    _write_run(tmp_path / "runs", "A", ids=_dev_ids(), no_usage={"DOC-004"})
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=_dev_ids())
    report = _cmp(tmp_path, split)
    assert report["arms"][0]["cost"]["priced"] is False and report["arms"][0]["cost"]["total_usd"] is None
    assert report["pairs"]["B"]["cost"] is None
    assert "lower_cost" in report["h5"]["verdicts"]["B"]["failed"]


# ---------------------------------------------------------------- scoring and tests


def test_scores_failures_subclass_and_units(tmp_path, split):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, wrong={"DOC-000", "DOC-001"}, sub_wrong={"DOC-002"})
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, failed={"DOC-005"})
    report = _cmp(tmp_path, split)
    a, b = report["arms"]
    assert a["class_accuracy"] == pytest.approx(28 / 30) and b["class_accuracy"] == pytest.approx(29 / 30)
    assert a["unit_accuracy"] == pytest.approx(27 / 30) and a["subclass_accuracy"] == pytest.approx(27 / 30)
    assert b["failed"] == 1 and b["failed_ids"] == ["DOC-005"]
    assert b["calibration"]["n"] == 29 and a["calibration"]["ece_null_floor"] is not None
    assert a["latency_ms"]["p50"] == pytest.approx(1014.0) and a["latency_ms"]["p95"] == pytest.approx(1028.0)
    mc = report["pairs"]["B"]["tests"]["mcnemar_class"]
    assert (mc["b"], mc["c"]) == (1, 2)
    assert report["pairs"]["B"]["differences"]["class_accuracy"]["estimate"] == pytest.approx(1 / 30)


def test_routing_reports_parked_share_and_auto_routed_accuracy(tmp_path, split):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, conf=1.0)
    parked = {"DOC-000": "document_form: unknown", "DOC-001": "subclass_gate: contract",
              "DOC-005": "document_form: unknown"}
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids,
               wrong={"DOC-000", "DOC-003"}, failed={"DOC-005"}, abstain=parked)
    report = _cmp(tmp_path, split)
    a, b = report["arms"]
    assert a["routing"]["abstained"] == 0 and a["routing"]["abstain_rate"] == 0.0
    r = b["routing"]
    # DOC-005 failed, so it is neither parked nor auto-routed.
    assert (r["answered"], r["abstained"], r["auto_routed"]) == (29, 2, 27)
    assert r["auto_class_accuracy"] == pytest.approx(26 / 27)
    assert r["abstained_class_accuracy"] == pytest.approx(1 / 2)
    assert r["abstain_reasons"] == {"document_form": 1, "subclass_gate": 1}
    # Forced-choice accuracy still counts the parked documents.
    assert b["class_accuracy"] == pytest.approx(27 / 30)
    assert "to a person 2/29" in sa.render(report)
    # Every arm reports its routing line, a measured 0% included.
    _write_run(tmp_path / "runs2", "A", ids=ids, conf=1.0)
    _write_run(tmp_path / "runs2", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    quiet = sa.render(sa.compare(["A", "B"], split_dir=split, runs_root=tmp_path / "runs2", n_boot=50, n_perm=50))
    assert "B: to a person 0/30" in quiet and "A: to a person 0/30" in quiet


def test_llm_arm_routes_by_its_class_band(tmp_path, split):
    # The LLM sorter's answer goes to a person under its class's `high` band (the pipeline rule the
    # run report counts): 0.9 is under every class's band (correspondence is 0.95), 1.0 is over all of them.
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, conf=0.9)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    a = _cmp(tmp_path, split)["arms"][0]["routing"]
    assert (a["answered"], a["abstained"], a["auto_routed"]) == (30, 30, 0)
    assert set(a["abstain_reasons"]) == {"below_high_band"} and a["abstain_reasons"]["below_high_band"] == 30


def test_runtime_reports_wall_time_throughput_and_concurrency(tmp_path, split):
    ids = _dev_ids(10)
    for run_id, task, model, lat_s in (("A", "isolated", QWEN, 10.0), ("B", "sorter_reviewer", LUNA, 1.0)):
        run = _write_run(tmp_path / "runs", run_id, task=task, model=model, ids=ids)
        lock = json.loads((run / "spec.lock.json").read_text())
        lock["job"]["concurrency"] = 5
        (run / "spec.lock.json").write_text(json.dumps(lock))
        items = [json.loads(line) for line in (run / "items.jsonl").read_text().splitlines()]
        for k, item in enumerate(items):  # two waves of 5 parallel calls, each lat_s long
            item["latency_ms"] = lat_s * 1000
            item["ts"] = f"2026-11-19T08:00:{int(lat_s * (1 + k // 5)):02d}.000+00:00"
        (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
        (run / "events.jsonl").write_text(
            json.dumps({"event": "start", "ts": "2026-11-19T07:59:59.000+00:00"}) + "\n"
            + json.dumps({"event": "done", "ts": f"2026-11-19T08:00:{int(2 * lat_s) + 1:02d}.000+00:00"}) + "\n")
    report = sa.compare(["A", "B"], split_dir=split, runs_root=tmp_path / "runs", set_name=None, n_boot=50, n_perm=50)
    a, b = (arm["runtime"] for arm in report["arms"])
    assert a["concurrency"] == b["concurrency"] == 5
    assert a["active_seconds"] == pytest.approx(20.0) and b["active_seconds"] == pytest.approx(2.0)
    assert a["run_wall_seconds"] == pytest.approx(22.0) and b["run_wall_seconds"] == pytest.approx(4.0)
    assert a["latency_sum_seconds"] == pytest.approx(100.0) and a["docs_per_minute_per_worker"] == pytest.approx(6.0)
    assert b["docs_per_minute"] == pytest.approx(300.0) and b["hours_per_100k_docs"] == pytest.approx(100_000 / 300 / 60)
    text = sa.render(report)
    assert "runtime (compared documents)" in text and "10.0x" in text


def test_fast_macro_f1_matches_experiment_stats():
    rng = random.Random(1)
    labels = ["a", "b", "c", "d"]
    truth = [rng.choice(labels) for _ in range(300)]
    pred = [t if rng.random() < 0.7 else rng.choice(labels + [sa.FAILED]) for t in truth]
    assert sa.fast_macro_f1(truth, pred, sorted(set(truth))) == pytest.approx(macro_f1(truth, pred))


def test_noninferiority_decides_on_constructed_examples(tmp_path, split):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, tokens=(1_000, 0))
    same = _cmp(tmp_path, split)["pairs"]["B"]["tests"]
    # 30 agreeing documents cannot rule out a 2-point loss: the bootstrap alone said p ~ 0.003 here.
    for key in ("noninferiority_macro_f1", "noninferiority_unit"):
        assert not same[key]["non_inferior"] and same[key]["bootstrap"]["p_value"] < 0.01
        assert same[key]["exact"]["losses"] == 0 and same[key]["lower95_one_sided"] < -0.09
    worse = tmp_path / "w"
    _write_run(worse / "runs", "A", ids=ids)
    _write_run(worse / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, wrong=set(ids[:6]))
    tests = sa.compare(["A", "B"], split_dir=split, runs_root=worse / "runs", n_boot=300, n_perm=300)["pairs"]["B"]["tests"]
    assert not tests["noninferiority_macro_f1"]["non_inferior"] and tests["noninferiority_macro_f1"]["p_value"] > 0.5
    assert not tests["noninferiority_unit"]["non_inferior"]


def test_exact_noninferiority_floor_scales_with_n():
    # No discordant documents: each rate is bounded at alpha/2, so 20 docs give -(1 - 0.025^(1/20)),
    # about -17 points, and cannot show a 4-point margin; 900 docs can show 2 points.
    small = sa.exact_noninferiority([True] * 20, [True] * 20, 0.04)
    assert small["lower95_one_sided"] == pytest.approx(-(1 - 0.025 ** (1 / 20)), abs=1e-6)
    # p inverts the bound: the smallest alpha with 1 - (alpha/2)^(1/20) < 0.04.
    assert small["p_value"] == pytest.approx(2 * 0.96 ** 20, abs=1e-6) and small["p_value"] > 0.05
    big = sa.exact_noninferiority([True] * 900, [True] * 900, 0.02)
    assert big["p_value"] < 1e-6 and big["lower95_one_sided"] > -0.005
    # Losses outweighing gains are never non-inferior at a 2-point margin.
    a = [True] * 900
    b = [False] * 40 + [True] * 860
    worse = sa.exact_noninferiority(a, b, 0.02)
    assert worse["losses"] == 40 and worse["p_value"] > 0.5
    # Gains offset losses: 10 losses and 10 gains in 900 is a zero difference, non-inferior at 2 points.
    a2 = [True] * 10 + [False] * 10 + [True] * 880
    b2 = [False] * 10 + [True] * 10 + [True] * 880
    even = sa.exact_noninferiority(a2, b2, 0.02)
    assert (even["gains"], even["losses"]) == (10, 10) and even["p_value"] < 0.01
    assert even["lower95_one_sided"] > -0.02


def test_exact_bound_counts_the_sampling_error_in_gains():
    # 3 gains and no losses in 50: taking 3/50 as fixed would put the bound above 0; bounding the
    # gain rate too keeps it well below, so a few lucky gains cannot carry non-inferiority.
    a = [False] * 3 + [True] * 47
    b = [True] * 50
    r = sa.exact_noninferiority(a, b, 0.02)
    assert (r["gains"], r["losses"]) == (3, 0)
    assert 3 / 50 - sa._cp_upper(0, 50) > 0 > r["lower95_one_sided"]
    assert r["lower95_one_sided"] == pytest.approx(sa._cp_lower(3, 50, 0.025) - sa._cp_upper(0, 50, 0.025))
    assert r["p_value"] > 0.05
    # The p-value and the bound agree: non-inferior at the 5% level exactly when the bound clears -margin.
    for gains, losses, n, margin in ((5, 2, 400, 0.02), (0, 0, 300, 0.02), (12, 9, 900, 0.02), (1, 4, 120, 0.04)):
        a = [False] * gains + [True] * losses + [True] * (n - gains - losses)
        b = [True] * gains + [False] * losses + [True] * (n - gains - losses)
        r = sa.exact_noninferiority(a, b, margin)
        assert (r["p_value"] < 0.05) == (r["lower95_one_sided"] > -margin)


def test_runtime_throughput_counts_only_answered_documents():
    from types import SimpleNamespace as NS
    arm = NS(concurrency=1, run_wall_seconds=12.0)
    ok = [NS(started_ts=float(k), finished_ts=float(k + 1), latency_ms=1000.0, failed=False) for k in range(10)]
    failed = [NS(started_ts=None, finished_ts=None, latency_ms=None, failed=True) for _ in range(10)]
    rt = sa._runtime(arm, ok + failed)
    # 10 answered documents over 10 active seconds and 10 latency seconds; the failures add neither.
    assert rt["active_seconds"] == pytest.approx(10.0)
    assert rt["docs_per_minute"] == pytest.approx(60.0) and rt["docs_per_minute_per_worker"] == pytest.approx(60.0)
    assert rt["hours_per_100k_docs"] == pytest.approx(100_000 / 60 / 60)


def test_runtime_charges_failed_attempt_time_and_prefers_the_execution_window():
    from types import SimpleNamespace as NS
    arm = NS(concurrency=1, run_wall_seconds=None)
    # one 1-second answer, then a 60-second attempt that failed: 1 document delivered in 61 seconds.
    ok = NS(started_ts=0.0, finished_ts=1.0, latency_ms=1000.0, failed=False)
    timeout = NS(started_ts=1.0, finished_ts=61.0, latency_ms=60_000.0, failed=True)
    rt = sa._runtime(arm, [ok, timeout])
    assert rt["active_seconds"] == pytest.approx(61.0) and rt["latency_sum_seconds"] == pytest.approx(61.0)
    assert (rt["answered"], rt["failed"]) == (1, 1)
    assert rt["docs_per_minute"] == pytest.approx(60 / 61) and rt["timing_basis"] == "execution"
    # Persisted at 30 s, long after a 1-second answer: the window, not ts - latency, places the request.
    late = NS(started_ts=0.0, finished_ts=1.0, latency_ms=1000.0, failed=False)
    assert sa._runtime(arm, [late])["active_seconds"] == pytest.approx(1.0)
    legacy = NS(started_ts=None, finished_ts=30.0, latency_ms=1000.0, failed=False)
    assert sa._runtime(arm, [legacy])["timing_basis"] == "estimate"


def test_macro_noninferiority_needs_per_class_support():
    # 5 classes and a 2-point margin: each class needs ln(0.05)/ln(0.9) -> 29 documents.
    support = sa.macro_class_support(["a"] * 40 + ["b"] * 40 + ["c"] * 40 + ["d"] * 40 + ["e"] * 1, 0.02)
    assert support["min_docs_per_class"] == 29 and support["underpowered"] == {"e": 1}
    # merger_agreement is exempt (owner decision): its shortfall is reported but does not block.
    mergers = sa.macro_class_support(["a"] * 40 + ["b"] * 40 + ["c"] * 40 + ["d"] * 40 + ["merger_agreement"] * 20, 0.02)
    assert mergers["underpowered"] == {} and mergers["exempt_underpowered"] == {"merger_agreement": 20}


def test_a_minority_class_both_arms_get_right_cannot_carry_macro_noninferiority(tmp_path, split):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    report = sa.compare(["A", "B"], split_dir=split, runs_root=tmp_path / "runs", set_name=None, n_boot=50, n_perm=50)
    ni = report["pairs"]["B"]["tests"]["noninferiority_macro_f1"]
    assert ni["class_support"]["underpowered"] and ni["non_inferior"] is False and ni["p_value"] == 1.0
    assert "classes under" in sa.render(report)


def test_no_scored_units_leaves_unit_noninferiority_unavailable():
    outs = [sa.Outcome(doc_id=f"D{i}", truth_class="contract", pred_class="contract", class_ok=True,
                       sub_scored=False, sub_ok=False, unit_scored=False, unit_ok=False, failed=False,
                       confidence=0.9, latency_ms=1.0, cost_usd=0.0, reported_cost_usd=None, tokens=(1, 1))
            for i in range(30)]
    result = sa.compare_pair(outs, outs, labels=["contract"], n_boot=20, n_perm=20)
    unit = result["tests"]["noninferiority_unit"]
    assert result["unit_n"] == 0 and unit["non_inferior"] is False and unit["unavailable"]
    assert result["tests"]["noninferiority_macro_f1"]["lower95_one_sided"] is not None


def test_compare_is_deterministic(tmp_path, split):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, wrong={"DOC-003"})
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, wrong={"DOC-007", "DOC-008"})
    assert _cmp(tmp_path, split) == _cmp(tmp_path, split)


def test_h5_family_is_holm_adjusted_and_needs_all_three():
    def pair(ni_f1, ni_unit, cost):
        tests = {"noninferiority_macro_f1": {"p_value": ni_f1}, "noninferiority_unit": {"p_value": ni_unit},
                 "paired_macro_f1_permutation": {"p_value": 0.5}, "mcnemar_class": {"p_value": 0.2},
                 "mcnemar_unit": {"p_value": 0.3}}
        return {"tests": tests, "cost": {"lower_cost_p_value": cost}}

    family = sa.h5_family({"luna": pair(0.001, 0.004, 0.0005), "jev": pair(0.001, 0.03, 0.0005)})
    assert family["holm"] == holm(family["raw"])
    assert family["holm"]["jev:noninferiority_unit"] == pytest.approx(0.03)      # largest raw p, rank 6: 1 x p
    assert family["holm"]["luna:noninferiority_unit"] == pytest.approx(0.008)    # rank 5: 2 x 0.004
    assert family["verdicts"]["luna"] == {"supported": True, "failed": []}
    assert family["verdicts"]["jev"]["supported"] is True
    strict = sa.h5_family({"luna": pair(0.001, 0.004, 0.0005), "jev": pair(0.001, 0.06, 0.0005)})
    assert strict["verdicts"]["jev"] == {"supported": False, "failed": ["noninferiority_unit"]}
    assert set(strict["secondary_holm"]) == {f"{b}:{k}" for b in ("luna", "jev")
                                             for k in ("paired_macro_f1_permutation", "mcnemar_class", "mcnemar_unit")}


def test_frontier_marks_dominated_runs(tmp_path, split):
    ids = _dev_ids()
    root = tmp_path / "runs"
    _write_run(root, "A", ids=ids, tokens=(10_000, 100))
    _write_run(root, "B1", task="sorter_reviewer", model=LUNA, ids=ids, tokens=(2_000, 0))           # cheaper, same
    _write_run(root, "B2", task="sorter_reviewer", model=LUNA, ids=ids, tokens=(50_000, 0), wrong={"DOC-001"})
    report = sa.compare(["A", "B1", "B2"], split_dir=split, runs_root=root, n_boot=50, n_perm=50)
    rows = {r["run_id"]: r for r in report["frontier"]}
    assert rows["B1"]["dominated_by"] is None
    assert rows["A"]["dominated_by"] == "B1" and rows["B2"]["dominated_by"] is not None
    assert "cost-quality frontier" in sa.render(report)


# ---------------------------------------------------------------- planning


def test_noninferiority_sample_size_and_power():
    n = sa.noninferiority_n(0.06, 0.02)
    assert n == 928
    assert sa.noninferiority_power(n, margin=0.02, discordance=0.06) == pytest.approx(0.80, abs=0.005)
    assert sa.noninferiority_power(1000, margin=0.04, discordance=0.25) > 0.8
    with pytest.raises(ValueError):
        sa.noninferiority_n(0.06, 0.0)


def test_simulated_macro_f1_se_is_seeded_and_shrinks_with_n():
    small = sa.simulate_macro_f1_se({"a": 60, "b": 60, "c": 30}, 0.95, 0.97, 0.06, n_sim=80)
    big = sa.simulate_macro_f1_se({"a": 600, "b": 600, "c": 300}, 0.95, 0.97, 0.06, n_sim=80)
    assert small == sa.simulate_macro_f1_se({"a": 60, "b": 60, "c": 30}, 0.95, 0.97, 0.06, n_sim=80)
    assert 0 < big < small
    with pytest.raises(ValueError):
        sa.simulate_macro_f1_se({"a": 10}, 0.9, 0.99, 0.01)


# ---------------------------------------------------------------- CLI


def test_cli_digest_json_and_refusal(tmp_path, split, capsys):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    common = ["--runs-root", str(tmp_path / "runs"), "--split-dir", str(split), "--n-boot", "50", "--n-perm", "50"]
    assert cli.main(["--a", "A", "--b", "B", *common, "--volume-docs-per-month", "1000",
                     "--out", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "H5 confirmatory family" in out and "docs/month" in out
    assert json.loads((tmp_path / "r.json").read_text())["schema"] == "mailroom.sorter_arms/v1"
    _write_run(tmp_path / "runs", "C", task="sorter_reviewer", model=LUNA, ids=ids[:5])
    assert cli.main(["--a", "A", "--b", "C", *common]) == 2
    assert "unpaired" in capsys.readouterr().err


def test_cli_writes_comparison_figures_coloured_by_system(tmp_path, split, capsys):
    from mailroom_sandbox import figure_style as fs

    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, wrong=ids[:2])
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    common = ["--runs-root", str(tmp_path / "runs"), "--split-dir", str(split), "--n-boot", "50", "--n-perm", "50"]
    figs = tmp_path / "figs"
    assert cli.main(["--a", "A", "--b", "B", *common, "--figures", str(figs)]) == 0
    capsys.readouterr()
    names = sorted(p.name for p in figs.glob("*.svg"))
    assert names == [f"rb1-r13b-sorter-arms.{n}.svg" for n in ("cost-quality", "latency", "pricing", "quality", "routing")]
    assert fs.lint_paths(figs.glob("*.svg")) == {}
    lat = (figs / "rb1-r13b-sorter-arms.latency.svg").read_text()
    assert fs.DECISION in lat and fs.LLM in lat  # colour follows the system, both present
    cost = (figs / "rb1-r13b-sorter-arms.cost-quality.svg").read_text()
    assert "no billed cost: LLM sorter" in cost  # the LLM arm has no billed cost
    assert "Cost is not yet comparable" in cost and "more per 1,000" not in cost  # no direction from a small sample
    pricing = (figs / "rb1-r13b-sorter-arms.pricing.svg").read_text()
    assert "LLM sorter calls" in pricing  # each call's prompt size, from the run items



def test_a_clean_billed_sample_still_needs_list_and_billed_costs_to_agree():
    def arm(rid, listed, billed):
        return {"run_id": rid, "n": 1000, "cost": {"per_1k_docs_usd": listed, "provider_reported_docs": 1000,
                                                    "provider_reported_usd": billed}}
    report = {"n": 1000, "arms": [arm("A", 2.0, 2.5), arm("B", 2.3, 2.6)]}
    assert sa.cost_not_comparable(report, ["A", "B"]) == []  # both say B costs more
    report["arms"][1] = arm("B", 2.3, 2.2)  # list price says more, the bill says less
    assert sa.cost_not_comparable(report, ["A", "B"]) == ["list-price and billed costs disagree on direction for A and B"]


def test_a_reversed_ranking_between_any_two_arms_blocks_a_cost_comparison():
    def arm(rid, listed, billed):
        return {"run_id": rid, "n": 1000, "cost": {"per_1k_docs_usd": listed, "provider_reported_docs": 1000,
                                                    "provider_reported_usd": billed}}
    # B and C each agree with A, but list price ranks B above C and the bill ranks C above B
    report = {"n": 1000, "arms": [arm("A", 1.0, 1.0), arm("B", 2.2, 2.0), arm("C", 2.1, 2.3)]}
    assert sa.cost_not_comparable(report, ["A", "B", "C"]) == [
        "list-price and billed costs disagree on direction for B and C"]


def test_h5_lower_cost_leg_is_undecided_until_costs_are_a_comparison():
    def report(n, billed):
        arms = [{"run_id": r, "n": n, "cost": {"per_1k_docs_usd": c, "provider_reported_docs": n if billed else 0,
                                                "provider_reported_usd": c * n / 1000 if billed else None}}
                for r, c in (("A", 3.0), ("B", 2.0))]
        return {"reference": "A", "n": n, "arms": arms,
                "h5": {"alpha": 0.05, "holm": {}, "raw": {}, "verdicts": {"B": {"supported": True, "failed": []}}}}
    small = report(20, billed=False)
    sa.gate_h5_cost(small)
    v = small["h5"]["verdicts"]["B"]
    assert v["supported"] is False and v["undecided"] is True and v["cost_not_comparable"]
    text = "\n".join(sa._render_h5(small))
    assert "B: undecided" in text and "SUPPORTED" not in text
    clean = report(1000, billed=True)
    sa.gate_h5_cost(clean)
    assert clean["h5"]["verdicts"]["B"] == {"supported": True, "failed": [], "cost_not_comparable": [],
                                            "undecided": False}
    assert "B: SUPPORTED" in "\n".join(sa._render_h5(clean))


def test_every_arm_gates_the_h5_cost_leg_and_saved_reports_are_regated():
    def arm(rid, listed, billed):
        return {"run_id": rid, "n": 1000, "cost": {"per_1k_docs_usd": listed, "provider_reported_docs": 1000 if billed else 0,
                                                    "provider_reported_usd": listed if billed else None}}
    report = {"reference": "A", "n": 1000, "arms": [arm("A", 3.0, True), arm("B", 2.0, True), arm("C", 2.5, False)],
              "h5": {"alpha": 0.05, "holm": {}, "raw": {}, "verdicts": {"B": {"supported": True, "failed": []}}}}
    saved = json.loads(json.dumps(report))  # a report saved before the gate: no undecided field
    text = "\n".join(sa._render_h5(saved))
    assert "B: undecided" in text and "no billed cost for: C" in text
    sa.gate_h5_cost(report)  # C is unbilled, so B's cost leg is not a comparison either
    assert report["h5"]["verdicts"]["B"]["undecided"] is True
    report["arms"][2]["cost"]["per_1k_docs_usd"] = None
    assert "no list-price cost for: C" in sa.cost_not_comparable(report, ["A", "B", "C"])


def test_digest_needs_explicit_complete_timing_for_a_speed_up():
    report = {"reference": "A", "arms": [{"run_id": "A", "runtime": {"active_seconds": 10.0, "interleaved_docs": 0,
                                                                      "timing_complete": True}},
                                         {"run_id": "B", "runtime": {"active_seconds": 5.0, "interleaved_docs": 0}}]}
    text = "\n".join(sa._render_runtime(report))  # B saved without timing_complete
    assert "2.0x" not in text and "isolation unknown for B" in text


def test_runtime_isolation_is_unknown_when_timing_is_incomplete():
    from types import SimpleNamespace as NS

    items = {f"D{k}": {"started_at_ns": int((100 + k) * 1e9), "finished_at_ns": int((100.5 + k) * 1e9)} for k in range(4)}
    arm = NS(items=items, concurrency=1, run_wall_seconds=4.0)

    def row(k, end=True):
        return NS(doc_id=f"D{k}", started_ts=100.0 + k, finished_ts=100.5 + k if end else None,
                  latency_ms=500.0, failed=False)

    cut = sa._runtime(arm, [row(0), row(1, end=False)])  # a compared request with no end time
    assert cut["timing_complete"] is False and cut["interleaved_docs"] is None
    items["D3"] = {"latency_ms": 500.0}  # another item that cannot be placed
    other = sa._runtime(arm, [row(0), row(1)])
    assert other["timing_complete"] is True and other["interleaved_docs"] is None
    report = {"reference": "A", "arms": [{"run_id": "A", "runtime": {"active_seconds": 4.0, "interleaved_docs": 0,
                                                                      "timing_complete": True}},
                                         {"run_id": "B", "runtime": {"active_seconds": 2.0, **other}}]}
    report["arms"][1]["runtime"]["active_seconds"] = 2.0
    text = "\n".join(sa._render_runtime(report))
    assert "2.0x" not in text and "no speed-up: timing is incomplete or its isolation unknown for B" in text


def test_digest_gives_no_speed_up_when_other_documents_share_the_window():
    rt = {"active_seconds": 10.0, "run_wall_seconds": 30.0, "interleaved_docs": 0, "timing_complete": True}
    report = {"reference": "A", "arms": [{"run_id": "A", "runtime": dict(rt)},
                                         {"run_id": "B", "runtime": dict(rt, active_seconds=5.0)}]}
    assert "2.0x" in "\n".join(sa._render_runtime(report))
    report["arms"][1]["runtime"]["interleaved_docs"] = 4
    text = "\n".join(sa._render_runtime(report))
    assert "2.0x" not in text and "no speed-up: other documents of the run ran inside the active window of B" in text


def test_runtime_counts_other_documents_inside_the_compared_window():
    from types import SimpleNamespace as NS

    # six documents, one second apart; the comparison takes D0, D2, D4
    items = {f"D{k}": {"started_at_ns": int((100 + k) * 1e9), "finished_at_ns": int((100.5 + k) * 1e9)} for k in range(6)}
    arm = NS(items=items, concurrency=1, run_wall_seconds=6.0)

    def rows(keys):
        return [NS(doc_id=f"D{k}", started_ts=100.0 + k, finished_ts=100.5 + k, latency_ms=500.0, failed=False)
                for k in keys]

    assert sa._runtime(arm, rows([0, 2, 4]))["interleaved_docs"] == 2  # D1 and D3 ran inside 100..104.5
    assert sa._runtime(arm, rows([0, 1, 2]))["interleaved_docs"] == 0  # a contiguous block is its own window


def test_pricing_ticks_are_per_call_prompt_sizes():
    assert cli.call_prompt_sizes({"prompt_tokens": 90_000, "llm_calls": 3}) == [30_000.0] * 3
    assert cli.call_prompt_sizes({"prompt_tokens": 40_000, "llm_calls": 1}) == [40_000.0]
    assert cli.call_prompt_sizes({"prompt_tokens": 40_000}) == [40_000.0]
    assert cli.call_prompt_sizes({"prompt_tokens": 9, "call_usage": [[300_000, 5], [2_000, 1]]}) == [300_000.0, 2_000.0]
    assert cli.call_prompt_sizes({"prompt_tokens": None}) == [] and cli.call_prompt_sizes({}) == []


def test_cli_figures_from_mock_runs_are_labelled_simulated(tmp_path, split, capsys):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, mock=True)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, mock=True)
    common = ["--runs-root", str(tmp_path / "runs"), "--split-dir", str(split), "--n-boot", "50", "--n-perm", "50"]
    figs = tmp_path / "figs"
    assert cli.main(["--a", "A", "--b", "B", *common, "--allow-mock", "--figures", str(figs)]) == 0
    capsys.readouterr()
    svgs = list(figs.glob("*.svg"))
    assert svgs and all("SIMULATED" in p.read_text() for p in svgs)


# ---------------------------------------------------------------- held-out seal and configs


class _Dataset:
    def __init__(self, path):
        self.path = path

    def exclude_ids_path(self):
        return self.path


class _Spec:
    def __init__(self, path):
        self.dataset = _Dataset(path)


def test_seal_refuses_a_heldout_draw_without_run_id_and_unseal(tmp_path, monkeypatch):
    sealed = _Spec(tmp_path / "runbook-v1" / "heldout.exclude.ids")
    monkeypatch.delenv(heldout_seal.UNSEAL_ENV, raising=False)
    assert len(heldout_seal.seal_errors(sealed, "my-heldout-run")) == 2
    assert len(heldout_seal.seal_errors(sealed, "rb1-r70b-x")) == 1
    monkeypatch.setenv(heldout_seal.UNSEAL_ENV, "rb1-r70b-other")
    assert len(heldout_seal.seal_errors(sealed, "rb1-r70b-x")) == 1   # unsealed for another run only
    monkeypatch.setenv(heldout_seal.UNSEAL_ENV, "rb1-r70b-x")
    assert heldout_seal.seal_errors(sealed, "rb1-r70b-x") == []
    assert heldout_seal.seal_errors(_Spec(tmp_path / "dev.exclude.ids"), "anything") == []
    assert heldout_seal.seal_errors(_Spec(None), "anything") == []


def test_leak_check_catches_heldout_rows_in_another_draw(tmp_path):
    d = tmp_path / "runbook-v1"
    d.mkdir()
    (d / "heldout.ids").write_text("# h\nDOC-h1\nDOC-h2\n", encoding="utf-8")
    spec = _Spec(d / "dev.exclude.ids")
    assert heldout_seal.leak_errors(spec, ["DOC-d1", "DOC-d2"]) == []
    errs = heldout_seal.leak_errors(spec, ["DOC-d1", "DOC-h2"])
    assert len(errs) == 1 and "DOC-h2" in errs[0]
    assert heldout_seal.leak_errors(_Spec(d / "heldout.exclude.ids"), ["DOC-h1"]) == []


def test_preflight_refuses_the_sealed_template_before_preparing(monkeypatch, job_data_dir):
    from mailroom_sandbox.job import preflight
    from mailroom_sandbox.job.spec import load_run_spec, run_dir

    monkeypatch.delenv(heldout_seal.UNSEAL_ENV, raising=False)
    path = RUNS / "rb1-r70b-decision-sorter-luna-heldout.yaml"
    spec = load_run_spec(path)
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "failed" and report["checks"][-1]["name"] == "heldout_seal"
    assert not (run_dir(spec.run_id) / "dataset.jsonl").exists()


H5_CONFIGS = sorted(RUNS.glob("rb1-r13b-decision-sorter-*.yaml")) + sorted(RUNS.glob("rb1-r70b-decision-sorter-*.yaml"))


def test_h5_configs_are_handoff_free_capped_and_counted_by_the_r01_gate():
    from mailroom_sandbox.decision_backends import load_question_set
    from mailroom_sandbox.job.spec import load_run_spec

    gate_spec = importlib.util.spec_from_file_location("check_r01_smoke", repo_root() / "scripts" / "check_r01_smoke.py")
    gate = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate)
    assert len(H5_CONFIGS) == 3
    sorter = load_run_spec(next(p for p in (RUNS / "rb1-r03-sorter-v0-dev.yaml", RUNS / "runbook-r03-sorter-v0-dev.yaml") if p.is_file()))
    for path in H5_CONFIGS:
        spec = load_run_spec(path)
        text = path.read_text()
        assert spec.run_id == path.stem and spec.task == "sorter_reviewer"
        assert spec.reviewer.backend == "decisions" and spec.engine.model == spec.reviewer.model
        assert not load_question_set(spec.reviewer.questions).get("handoff")
        assert spec.dataset.revision == sorter.dataset.revision and spec.dataset.interim_labels and spec.dataset.near_gold_labels
        assert spec.job.max_wall_seconds and spec.job.api_cost_cap_usd and not spec.job.mock
        assert "--initials <XX>" in text and "compare_sorter_arms.py" in text
        heldout = "r70b" in path.stem
        want_set = "heldout" if heldout else "dev-look1"
        assert spec.dataset.exclude_ids_file == f"config/splits/runbook-v2/{want_set}.exclude.ids"
        assert spec.dataset.limit == (1000 if heldout else 300)
        assert heldout == heldout_seal.is_sealed_draw(spec)
        if heldout:
            assert text.startswith("# SEALED.") and heldout_seal.SEALED_RUN_ID.match(spec.run_id)
        (model, want), = gate.expected_calls(spec).items()
        assert model == spec.reviewer.model and want["paths"] == {"decisions": spec.dataset.limit}
    questions = {yaml.safe_load(path.read_text())["reviewer"]["questions"] for path in H5_CONFIGS}
    assert questions == {"reviewer_decisions_v4.1.0"}


def test_h5_run_ids_start_with_their_experiment_key():
    keys = {path.stem: ("rb1-r70b" if "-r70b-" in path.stem else "rb1-r13b") for path in H5_CONFIGS}
    assert all(stem.startswith(key + "-") for stem, key in keys.items())


def test_class_error_rates_are_one_vs_rest():
    truth = ["a", "a", "b", "b"]
    pred = ["a", "b", "b", "a"]
    rates = sa.class_error_rates(truth, pred, ["a", "b"])
    assert rates["class_fpr"] == {"a": 0.5, "b": 0.5}
    assert rates["class_fnr"] == {"a": 0.5, "b": 0.5}
    assert rates["class_macro_fpr"] == 0.5 and rates["class_macro_fnr"] == 0.5
    perfect = sa.class_error_rates(truth, truth, ["a", "b"])
    assert perfect["class_macro_fpr"] == 0.0 and perfect["class_macro_fnr"] == 0.0
    # One truth class has no negatives, so its FPR is unmeasurable and must not pull the macro to 0.
    single = sa.class_error_rates(["a", "a"], ["a", "b"], ["a"])
    assert single["class_fpr"] == {"a": None}
    assert single["class_fnr"] == {"a": 0.5}
    assert single["class_macro_fpr"] is None and single["class_macro_fnr"] == 0.5


def test_paired_500_arms_share_one_draw_and_leave_the_classify_window_open():
    from mailroom_sandbox.context_fit import decision_document_chars
    from mailroom_sandbox.job.spec import load_run_spec

    llm = load_run_spec(RUNS / "sorter-vs-decision-500-llm-deepseek-v4.1-flash.yaml")
    dec = load_run_spec(RUNS / "sorter-vs-decision-500-decision-luna.yaml")
    assert llm.task == "isolated" and llm.engine.model == "deepseek/deepseek-v4.1-flash-1017"
    assert dec.task == "sorter_reviewer" and dec.engine.model == "openai/gpt-6-luna-decisions"
    assert dec.reviewer.model == dec.engine.model
    assert dec.reviewer.questions == "reviewer_decisions_v4.1.0"
    assert dec.reviewer.max_input_chars == decision_document_chars(1_050_000)
    assert llm.dataset == dec.dataset
    assert sum(bucket["count"] for bucket in llm.dataset.strata["buckets"]) == 500
    assert llm.dataset.sample_seed == 3302 and llm.dataset.draw == "ranked"
    assert llm.job.require_expanded_inputs is True
    assert "max_input_chars" not in (llm.agent_knobs.get("sorter") or {})
    assert llm.job.api_cost_cap_usd and dec.job.api_cost_cap_usd
    assert "--initials <XX>" in (RUNS / f"{llm.run_id}.yaml").read_text()


def test_paired_smoke_is_one_document_per_class_inside_the_500():
    from mailroom_sandbox.context_fit import decision_document_chars
    from mailroom_sandbox.job.spec import load_run_spec

    full = load_run_spec(RUNS / "sorter-vs-decision-500-llm-deepseek-v4.1-flash.yaml")
    full_dec = load_run_spec(RUNS / "sorter-vs-decision-500-decision-luna.yaml")
    llm = load_run_spec(RUNS / "sorter-vs-decision-smoke-llm-deepseek-v4.1-flash.yaml")
    dec = load_run_spec(RUNS / "sorter-vs-decision-smoke-decision-luna.yaml")
    assert llm.task == "isolated" and llm.engine.model == full.engine.model
    assert dec.task == "sorter_reviewer" and dec.engine.model == full_dec.engine.model
    assert dec.reviewer.backend == "decisions"
    assert dec.reviewer.questions == full_dec.reviewer.questions == "reviewer_decisions_v4.1.0"
    assert dec.reviewer.max_input_chars == full_dec.reviewer.max_input_chars == decision_document_chars(1_050_000)
    assert llm.dataset == dec.dataset
    assert llm.dataset.sample_seed == full.dataset.sample_seed == 3302
    assert llm.dataset.draw == full.dataset.draw == "ranked"
    assert llm.dataset.revision == full.dataset.revision
    assert llm.dataset.staged_overlay == full.dataset.staged_overlay
    assert llm.dataset.exclude_ids_file == full.dataset.exclude_ids_file
    assert llm.dataset.require_task_gt is True
    smoke = {b["doc_class"]: b["count"] for b in llm.dataset.strata["buckets"]}
    paired = {b["doc_class"]: b["count"] for b in full.dataset.strata["buckets"]}
    assert smoke == {name: 1 for name in paired}
    assert all(smoke[name] <= paired[name] for name in paired)
    assert llm.job.require_expanded_inputs is True
    assert "max_input_chars" not in (llm.agent_knobs.get("sorter") or {})
    assert llm.job.api_cost_cap_usd <= 3 and dec.job.api_cost_cap_usd <= 2
    assert not llm.job.mock and not dec.job.mock
    assert "--initials <XX>" in (RUNS / f"{llm.run_id}.yaml").read_text()


def test_qwen_smoke_uses_the_same_five_documents_as_the_decision_arm():
    from mailroom_sandbox.job.spec import load_run_spec

    qwen = load_run_spec(RUNS / "sorter-vs-decision-smoke-llm-qwen3.7-flash.yaml")
    dec = load_run_spec(RUNS / "sorter-vs-decision-smoke-decision-luna.yaml")
    assert qwen.task == "isolated" and qwen.engine.model == "qwen/qwen3.7-flash"
    assert qwen.dataset == dec.dataset
    assert qwen.job.require_expanded_inputs is True
    assert qwen.trace.sink == "none"
    assert "max_input_chars" not in (qwen.agent_knobs.get("sorter") or {})
    assert qwen.job.api_cost_cap_usd <= 1 and not qwen.job.mock
    assert "--initials <XX>" in (RUNS / f"{qwen.run_id}.yaml").read_text()


def test_h5_smoke20_arms_draw_the_same_documents_and_are_capped():
    from mailroom_sandbox.job.spec import load_run_spec

    llm = load_run_spec(RUNS / "rb1-r13b-smoke20-llm-sorter-qwen3.7-flash.yaml")
    dec = load_run_spec(RUNS / "rb1-r13b-smoke20-decision-sorter-luna.yaml")
    assert llm.task == "isolated" and dec.task == "sorter_reviewer"
    assert dec.reviewer.backend == "decisions" and dec.reviewer.questions == "reviewer_decisions_v4.0.0"
    assert llm.dataset == dec.dataset and llm.dataset.limit == 20
    assert llm.dataset.exclude_ids_file == "config/splits/runbook-v1/dev-look1.exclude.ids"
    for spec in (llm, dec):
        assert spec.run_id.startswith("rb1-r13b-smoke20-") and not spec.job.mock
        assert spec.job.api_cost_cap_usd <= 0.15 and spec.job.max_wall_seconds
        assert "--initials <XX>" in (RUNS / f"{spec.run_id}.yaml").read_text()


def test_cli_write_names_every_output_from_the_experiment_key(tmp_path, split, capsys):
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids)
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    common = ["--a", "A", "--b", "B", "--runs-root", str(tmp_path / "runs"), "--split-dir", str(split),
              "--n-boot", "50", "--n-perm", "50", "--reports-root", str(tmp_path / "repo")]
    assert cli.main([*common, "--experiment-key", "rb1-r13b", "--write"]) == 0
    base = tmp_path / "repo" / "reports" / "campaigns" / "rb1" / "rb1-r13b-sorter-vs-decision"
    files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
    assert files == sorted(["analysis/rb1-r13b-sorter-arms.comparison.json", "analysis/rb1-r13b-sorter-arms.digest.txt",
                            "figures/rb1-r13b-sorter-arms.frontier.csv",
                            *[f"figures/rb1-r13b-sorter-arms.{n}.svg"
                              for n in ("cost-quality", "latency", "pricing", "quality", "routing")]])
    assert json.loads((base / files[0]).read_text())["experiment_key"] == "rb1-r13b"
    assert (base / "figures/rb1-r13b-sorter-arms.frontier.csv").read_text().splitlines()[0].startswith(
        "run_id,model,class_macro_f1")
    capsys.readouterr()
    assert cli.main([*common, "--experiment-key", "h5", "--write"]) == 2
    assert cli.main([*common, "--write", "--allow-mock"]) == 2


def test_reviewed_subclass_corrections_score_subclass_and_unit_on_the_corrected_truth(tmp_path, split, monkeypatch):
    """SHF-013: a reviewed correction replaces the Hub subclass; the Hub-truth figures stay beside it."""
    from mailroom_sandbox import scoring_hotfixes as sh

    with (split / "assignments.jsonl").open("a", encoding="utf-8") as fh:  # give the corrected value a unit
        fh.write(json.dumps({"id": "DOC-900", "doc_class": "correspondence", "subclass": "other", "set": "pool",
                             "hf_split": "train", "tuned": False, "unit": "correspondence/other",
                             "unit_kind": "subclass"}) + "\n")
    monkeypatch.setattr(sh, "subclass_corrections", lambda: {"DOC-004": {
        "doc_id": "DOC-004", "doc_class": "correspondence", "hub_subclass": "email", "subclass": "other",
        "verdict": "correct"}})
    ids = _dev_ids()
    _write_run(tmp_path / "runs", "A", ids=ids, sub_wrong={"DOC-004"})  # answers "other" on DOC-004
    _write_run(tmp_path / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    report = _cmp(tmp_path, split)
    a, b = report["arms"]
    assert a["subclass_corrections_applied"] == b["subclass_corrections_applied"] == 1
    assert a["subclass_accuracy"] == a["unit_accuracy"] == 1.0
    assert a["hub_truth"]["subclass_accuracy"] == a["hub_truth"]["unit_accuracy"] == pytest.approx(29 / 30)
    assert b["subclass_accuracy"] == b["unit_accuracy"] == pytest.approx(29 / 30)
    assert b["hub_truth"]["subclass_accuracy"] == b["hub_truth"]["unit_accuracy"] == 1.0
    assert "1 reviewed subclass correction(s) applied (SHF-013)" in sa.render(report)

    monkeypatch.setattr(sh, "enabled", lambda fix_id: fix_id != "SHF-013")  # fix off: the Hub truth only
    report = _cmp(tmp_path, split)
    a, b = report["arms"]
    assert a["subclass_corrections_applied"] == 0 and a["subclass_accuracy"] == pytest.approx(29 / 30)
    assert b["unit_accuracy"] == 1.0 and "SHF-013" not in sa.render(report)


def test_class_support_alone_vetoes_macro_noninferiority():
    # 801 agreeing documents clear the exact and bootstrap floors; only the one-document class blocks.
    classes = ["contract"] * 200 + ["corporate_record"] * 200 + ["correspondence"] * 200 + ["insurance_claim"] * 200
    outs = [sa.Outcome(doc_id=f"D{i}", truth_class=c, pred_class=c, class_ok=True, sub_scored=False, sub_ok=False,
                       unit_scored=False, unit_ok=False, failed=False, confidence=0.9, latency_ms=1.0, cost_usd=0.0,
                       reported_cost_usd=None, tokens=(1, 1))
            for i, c in enumerate(classes + ["unknown"])]
    ni = sa.compare_pair(outs, outs, labels=sorted(set(classes) | {"unknown"}), n_boot=50, n_perm=20)[
        "tests"]["noninferiority_macro_f1"]
    assert ni["exact"]["p_value"] < sa.ALPHA and ni["bootstrap"]["p_value"] < sa.ALPHA
    assert ni["exact"]["lower95_one_sided"] > -sa.MARGIN_MACRO_F1
    assert ni["class_support"]["underpowered"] == {"unknown": 1}
    assert ni["non_inferior"] is False and ni["p_value"] == 1.0


def test_cost_is_not_called_a_comparison_below_a_clean_billed_sample():
    def report(n, billed):
        return {"n": n, "arms": [{"run_id": "A", "n": n, "cost": {"per_1k_docs_usd": 2.0, "provider_reported_docs": 0}},
                                 {"run_id": "B", "n": n, "cost": {"per_1k_docs_usd": 2.0,
                                                                  "provider_reported_docs": n if billed else 0,
                                                                  "provider_reported_usd": 2.0 if billed else None}}]}

    why = sa.cost_not_comparable(report(20, False), ["A", "B"])
    assert why == ["n = 20, under 1,000 paired documents", "no billed cost for: A, B"]
    assert sa.cost_not_comparable(report(1000, True), ["B"]) == []
    assert sa.cost_not_comparable(report(1000, True), ["A", "B"]) == ["no billed cost for: A"]
    # billing on some documents is not a billed total: the per-1k figure stays list price × tokens
    partial = report(1000, True)
    partial["arms"][1]["cost"]["provider_reported_docs"] = 999
    assert sa.billed_per_1k(partial["arms"][1]) is None
    assert sa.billed_per_1k(report(1000, True)["arms"][1]) == 2.0
