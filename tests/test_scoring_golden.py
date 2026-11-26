"""Golden end-to-end scoring: a synthetic offline pipeline run through the real whole-run entrypoint.

``runner._run_whole_run`` drives ``run_pipeline_eval`` exactly as ``sandbox run start`` does, with
only the graph call (``_run_pipeline_doc``) and the token accumulator stubbed. Four documents are
built so every headline has a hand-computable value and every scoring hotfix that touches them
moves a number the record names:

========  ===============================  ===============================  ===========================
doc       truth (class / subclass)         prediction                       fields
========  ===============================  ===============================  ===========================
d0        insurance_claim / auto           insurance_claim / auto           claim id punctuation (SHF-004)
d1        contract / service               contract / license               EUR vs USD amount (SHF-003)
d2        contract / service               insurance_claim / auto (wrong)   amount missed
d3        correspondence / (no truth)      correspondence                   documented-absent recipient
                                                                            stated (SHF-001)
========  ===============================  ===============================  ===========================

Network-free, no LLM.
"""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import experiment_stats as st
from mailroom_sandbox.job import metrics, preflight, runner
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec

ABSENT = "schema_documented_absence"

DOCS = [
    ("d0", "insurance_claim", "auto", {"claim_number": "CLM-12345"},
     "insurance_claim", "auto", {"claim_number": "CLM12345"}),
    ("d1", "contract", "service", {"contract_value": "$1,000.00"},
     "contract", "license", {"contract_value": "EUR 1,000"}),
    ("d2", "contract", "service", {"contract_value": "$500.00"},
     "insurance_claim", "auto", {}),
    ("d3", "correspondence", None,
     {"sender": "Jane Doe", "recipient": None, "gt_presence": json.dumps({"recipient": ABSENT})},
     "correspondence", None, {"sender": "Jane Doe", "recipient": "Bob"}),
]
USAGE = {"d0": (1000, 100, 2), "d1": (2000, 200, 3), "d2": (500, 50, 1), "d3": (1500, 150, 4)}


def _store(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text("".join(json.dumps({"id": d, "filename": f"{d}.txt", "doc_text": f"text {d}", "expected": cls,
                                        "expected_subclass": sub}) + "\n"
                            for d, cls, sub, *_ in DOCS))
    spec = RunSpec(run_id="run-golden", task="sorter", dataset=DatasetSpec(local_path=f"file://{path}", limit=4),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"},
                   job={"mock": True, "concurrency": 1})
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    store = RunStore(run_dir(report["run_id"]))
    lock = store.read_lock()
    assert "scoring_hotfixes" in lock and lock["scoring_hotfixes"]["fixes"]
    store.lock_path.write_text(json.dumps({**lock, "task": "pipeline", "profile": "ollama"}))
    truth = {d: (cls, sub, fields) for d, cls, sub, fields, *_ in DOCS}
    rows = [{**row, "expected_doc_class": truth[row["id"]][0], "expected_subclass": truth[row["id"]][1],
             "expected_fields": json.dumps(truth[row["id"]][2])} for row in store.dataset_rows()]
    store.dataset_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return store


@pytest.fixture
def golden(tmp_path, monkeypatch, job_data_dir):
    from mailroom_sandbox.eval import experiment_log
    from mailroom_sandbox.eval import runners as eval_runners
    from mailroom_sandbox.job import dated_reports, grid_cards, usage_capture

    preds = {d: (cls, sub, fields) for d, _c, _s, _f, cls, sub, fields in DOCS}
    current: dict[str, str] = {}

    def fake_doc(row, **_):
        current["id"] = row["id"]
        cls, sub, fields = preds[row["id"]]
        return {"id": row["id"], "doc_type": cls, "doc_subclass": sub, "stage": "archived",
                "extracted_data": dict(fields), "error": None}

    def fake_usage():
        p, c, n = USAGE[current["id"]]
        return {"prompt_tokens": p, "completion_tokens": c, "llm_calls": n}

    monkeypatch.setattr(eval_runners, "_run_pipeline_doc", fake_doc)
    monkeypatch.setattr(usage_capture, "usage_from_pipeline", fake_usage)
    monkeypatch.setattr(usage_capture, "usage_by_agent_from_pipeline", lambda: {})
    monkeypatch.setattr(experiment_log, "append", lambda record, path=None: None)
    monkeypatch.setattr(dated_reports, "maybe_write_run_reports", lambda *a, **k: None)
    monkeypatch.setattr(grid_cards, "maybe_write_card", lambda *a, **k: None)
    store = _store(tmp_path)
    summary = runner._run_whole_run(store, "pipeline", mock=True, model=None, profile="ollama")
    assert summary["state"] == "done", summary
    return store, summary["scores"]


def test_golden_class_and_subclass(golden):
    _store, scores = golden
    assert scores["exact_match"] == 0.75
    # macro over truth classes: insurance_claim 2/3, contract 2/3, correspondence 1
    assert scores["f1_macro"] == pytest.approx(7 / 9, abs=1e-4)
    # joint class/subclass, d3 has no subclass truth; d2's subclass cannot be right in the wrong class
    assert scores["subclass_accuracy"] == pytest.approx(1 / 3, abs=1e-4)
    assert scores["subclass_n"] == 3 and scores["subclass_n_no_truth"] == 1
    assert scores["subclass_accuracy_given_class"] == 0.5
    # insurance_claim/auto: 1 tp, 1 fp (d2) -> 2/3; contract/service: 0
    assert scores["subclass_f1_macro"] == pytest.approx(1 / 3, abs=1e-4)


def test_golden_field_f1_and_hallucination_are_dual_reported(golden):
    _store, scores = golden
    raw = scores["raw_dojo"]
    # per-document field F1: d0 id punctuation, d1 currency, d2 miss, d3 documented-absent recipient
    assert raw["extraction_f1_mean"] == pytest.approx((0.0 + 1.0 + 0.0 + 1.0) / 4, abs=1e-3)
    assert scores["extraction_f1_mean"] == pytest.approx((1.0 + 0.0 + 0.0 + 2 / 3) / 4, abs=1e-3)
    assert scores["extraction_f1_n"] == raw["extraction_f1_n"] == 4
    # the Dojo's insurance/contract suites return no event counts: no micro F1 over 1 of 4 rows
    assert scores["extraction_f1_micro"] is None and raw["extraction_f1_micro"] is None
    assert scores["extraction_f1_micro_reason"] == "event counts on 1 of 4 scored rows"
    assert (raw["extraction_tp"], raw["extraction_fp"], raw["extraction_fn"]) == (1, 0, 0)
    assert (scores["extraction_tp"], scores["extraction_fp"], scores["extraction_fn"]) == (1, 1, 0)
    assert raw["hallucination_rate"] is None
    assert scores["hallucination_rate"] == 1.0 and scores["n_documented_absent"] == 1
    assert scores["extraction_overall"] == pytest.approx(0.5) and raw["extraction_overall"] == pytest.approx(0.5)
    assert scores["extraction_overall_correct_class"] == pytest.approx(2 / 3, abs=1e-4)
    # the scored n beside each mean: all four documents have a score; three were routed to their class
    assert (scores["extraction_overall_n_scored"], raw["extraction_overall_n_scored"]) == (4, 4)
    assert (scores["extraction_overall_correct_class_n_scored"],
            raw["extraction_overall_correct_class_n_scored"]) == (3, 3)
    # active on the rows (SHF-015 is on, it finds no stale Hub label here; SHF-016 is on, the
    # rows here have no empty-universe CUAD map)
    assert set(scores["scoring_hotfixes"]) == {"SHF-001", "SHF-002", "SHF-003", "SHF-004", "SHF-015", "SHF-016"}
    for key in ("extraction_fp", "hallucination_rate", "extraction_f1_mean"):
        assert key in scores["scoring_hotfixes_changed"]
    assert scores["headline_basis"]["headline"] == "hotfixed"


def test_golden_cost_counts_every_call_and_failed_items(golden, monkeypatch):
    store, scores = golden
    items = store.load_items()
    assert [i["llm_calls"] for i in items] == [2, 3, 1, 4]
    assert sum(i["prompt_tokens"] for i in items) == 5000
    monkeypatch.setenv("SANDBOX_TOKEN_PRICE_IN_PER_M", "1.0")
    monkeypatch.setenv("SANDBOX_TOKEN_PRICE_OUT_PER_M", "4.0")
    rec = metrics.record_from_run(run_id=store.run_id, spec_hash="x", task="pipeline", profile="ollama",
                                  model="golden-model", prompt_version="v", dataset_fingerprint="f",
                                  items=items, scores=scores)
    assert rec["estimated_cost_usd"] == pytest.approx((5000 * 1.0 + 500 * 4.0) / 1e6)
    assert rec["cost_per_document"] == pytest.approx(0.007 / 4)
    confusion = {("insurance_claim", "insurance_claim"): 1, ("contract", "contract"): 1,
                 ("contract", "insurance_claim"): 1, ("correspondence", "correspondence"): 1}
    assert st.cost_weighted_error(confusion, {("contract", "insurance_claim"): 3.0}) == 0.75


def test_golden_windowed_run_bills_every_window_and_intake_and_scores_the_vote(tmp_path, monkeypatch, job_data_dir):
    """A windowed document (intake + N sorter windows + specialist) is billed for every call.

    The calls go through ``pipeline.limits.record_usage`` exactly as ``agents.base`` records each
    completion; the scored class is the sorter's window vote (``_merge_sorter_reads``), not the
    first window's read.
    """
    pytest.importorskip("agents.sorter")
    from agents.sorter import _merge_sorter_reads
    from pipeline import limits

    from mailroom_sandbox.eval import experiment_log
    from mailroom_sandbox.eval import runners as eval_runners
    from mailroom_sandbox.job import dated_reports, grid_cards

    windows = {"d0": ["contract", "insurance_claim", "insurance_claim"], "d1": ["contract"] * 5,
               "d2": ["unknown", "insurance_claim", "contract", "insurance_claim"], "d3": ["correspondence"]}

    def fake_doc(row, **_):
        limits.record_usage({"prompt_tokens": 300, "completion_tokens": 30}, "m", agent="intake")
        reads = [{"doc_type": cls, "confidence": 0.8, "reasoning": "r"} for cls in windows[row["id"]]]
        for _ in reads:
            limits.record_usage({"prompt_tokens": 1000, "completion_tokens": 20}, "m", agent="sorter")
        merged = _merge_sorter_reads(reads)
        limits.record_usage({"prompt_tokens": 800, "completion_tokens": 200}, "m", agent="specialist")
        return {"id": row["id"], "doc_type": merged["doc_type"], "stage": "archived", "extracted_data": {},
                "error": None}

    monkeypatch.setattr(eval_runners, "_run_pipeline_doc", fake_doc)
    monkeypatch.setattr(experiment_log, "append", lambda record, path=None: None)
    monkeypatch.setattr(dated_reports, "maybe_write_run_reports", lambda *a, **k: None)
    monkeypatch.setattr(grid_cards, "maybe_write_card", lambda *a, **k: None)
    store = _store(tmp_path)
    summary = runner._run_whole_run(store, "pipeline", mock=True, model=None, profile="ollama")
    assert summary["state"] == "done", summary
    items = {i["item_id"]: i for i in store.load_items()}
    for doc, reads in windows.items():
        assert items[doc]["llm_calls"] == len(reads) + 2
        assert items[doc]["prompt_tokens"] == 300 + 1000 * len(reads) + 800
        assert items[doc]["usage_by_agent"]["sorter"]["calls"] == len(reads)
        assert items[doc]["usage_by_agent"]["intake"]["calls"] == 1
    assert sum(i["llm_calls"] for i in items.values()) == 13 + 8
    # d0 votes insurance_claim 2:1 although its first window said contract; d2 likewise
    assert [items[d]["pred"]["doc_type"] for d in ("d0", "d1", "d2", "d3")] == [
        "insurance_claim", "contract", "insurance_claim", "correspondence"]
    assert summary["scores"]["exact_match"] == 0.75
    monkeypatch.setenv("SANDBOX_TOKEN_PRICE_IN_PER_M", "1.0")
    monkeypatch.setenv("SANDBOX_TOKEN_PRICE_OUT_PER_M", "1.0")
    rec = metrics.record_from_run(run_id=store.run_id, spec_hash="x", task="pipeline", profile="ollama",
                                  model="golden-model", prompt_version="v", dataset_fingerprint="f",
                                  items=list(items.values()), scores=summary["scores"])
    prompt = sum(300 + 1000 * len(r) + 800 for r in windows.values())
    completion = sum(30 + 20 * len(r) + 200 for r in windows.values())
    assert rec["estimated_cost_usd"] == pytest.approx((prompt + completion) / 1e6)


def test_a_fresh_lock_and_its_outputs_carry_the_current_hotfix_set(golden):
    """A new run locks the current module_sha256 and every fix with its targets (SHF-015 and the
    extended SHF-005/006/007/013 paths included), runs on it, and names the fixes in its outputs. A
    lock from before a hotfix change is refused by the executing process (re-lock with --force)."""
    from mailroom_sandbox import scoring_hotfixes as sh
    from mailroom_sandbox.job.preflight import _hotfix_drift_detail

    store, scores = golden
    lock = store.read_lock()["scoring_hotfixes"]
    assert lock == sh.describe() and lock["module_sha256"] == sh.module_sha256()
    targets = {f["id"]: {t["target"] for t in f["targets"]} for f in lock["fixes"]}
    assert "mailroom_sandbox.job.gate:labelled_count" in targets["SHF-015"]
    assert "mailroom_sandbox.rescore:run_scores" in targets["SHF-005"]
    assert {"SHF-006", "SHF-007"} <= {i for i, t in targets.items() if "mailroom_sandbox.job.runner:_scored_pairs" in t}
    assert "mailroom_sandbox.eval.scoring:score_subclass" in targets["SHF-013"]
    assert set(targets) <= sh.current_ids() | set(sh.stale())
    runner.verify_locked_hotfixes(store.read_lock())  # the locked set is the one in effect
    assert "SHF-015" in scores["scoring_hotfixes"] and scores["headline_basis"] == sh.headline_basis()
    assert all("scoring_hotfixes" in item["score"] for item in store.load_items())

    older = {**lock, "module_sha256": "0" * 64, "fixes": [f for f in lock["fixes"] if f["id"] != "SHF-015"]}
    with pytest.raises(RuntimeError, match="re-lock with --force"):
        runner.verify_locked_hotfixes({**store.read_lock(), "scoring_hotfixes": older})
    assert "use --force to re-lock" in _hotfix_drift_detail({"scoring_hotfixes": older}, store)
