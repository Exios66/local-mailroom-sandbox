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
    _write_run(tmp_path / "runs", "A", ids=ids)
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
    assert "parked 2/29" in sa.render(report)
    # A decision arm with no abstentions still reports its 0% routing rate; the LLM arm does not.
    _write_run(tmp_path / "runs2", "A", ids=ids)
    _write_run(tmp_path / "runs2", "B", task="sorter_reviewer", model=LUNA, ids=ids)
    quiet = sa.render(sa.compare(["A", "B"], split_dir=split, runs_root=tmp_path / "runs2", n_boot=50, n_perm=50))
    assert "B: parked 0/30" in quiet and "A: parked" not in quiet


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
    assert same["noninferiority_macro_f1"]["non_inferior"] and same["noninferiority_unit"]["non_inferior"]
    assert same["noninferiority_macro_f1"]["p_value"] < 0.01
    worse = tmp_path / "w"
    _write_run(worse / "runs", "A", ids=ids)
    _write_run(worse / "runs", "B", task="sorter_reviewer", model=LUNA, ids=ids, wrong=set(ids[:6]))
    tests = sa.compare(["A", "B"], split_dir=split, runs_root=worse / "runs", n_boot=300, n_perm=300)["pairs"]["B"]["tests"]
    assert not tests["noninferiority_macro_f1"]["non_inferior"] and tests["noninferiority_macro_f1"]["p_value"] > 0.5
    assert not tests["noninferiority_unit"]["non_inferior"]


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
        assert spec.dataset.exclude_ids_file == f"config/splits/runbook-v1/{want_set}.exclude.ids"
        assert spec.dataset.limit == (1000 if heldout else 300)
        assert heldout == heldout_seal.is_sealed_draw(spec)
        if heldout:
            assert text.startswith("# SEALED.") and heldout_seal.SEALED_RUN_ID.match(spec.run_id)
        (model, want), = gate.expected_calls(spec).items()
        assert model == spec.reviewer.model and want["paths"] == {"decisions": spec.dataset.limit}
    assert yaml.safe_load((RUNS / H5_CONFIGS[0].name).read_text())["reviewer"]["questions"] == "reviewer_decisions_v4.0.0"


def test_h5_run_ids_start_with_their_experiment_key():
    keys = {path.stem: ("rb1-r70b" if "-r70b-" in path.stem else "rb1-r13b") for path in H5_CONFIGS}
    assert all(stem.startswith(key + "-") for stem, key in keys.items())


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
    assert files == ["analysis/rb1-r13b-sorter-arms.comparison.json", "analysis/rb1-r13b-sorter-arms.digest.txt",
                     "figures/rb1-r13b-sorter-arms.frontier.csv"]
    assert json.loads((base / files[0]).read_text())["experiment_key"] == "rb1-r13b"
    assert (base / files[2]).read_text().splitlines()[0].startswith("run_id,model,class_macro_f1")
    capsys.readouterr()
    assert cli.main([*common, "--experiment-key", "h5", "--write"]) == 2
    assert cli.main([*common, "--write", "--allow-mock"]) == 2
