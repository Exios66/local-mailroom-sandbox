"""Phase 5 part 1: the offline replay of best-attempt selection (A) and the evidence check (B)."""

from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("graph.attempts")

from mailroom_sandbox.job import attempt_replay as ar  # noqa: E402

DOC = ("MASTER SERVICES AGREEMENT between Acme Corp and Beta LLC. Section 12. This Agreement shall be "
       "governed by the laws of Delaware. Section 14. Either party may terminate this Agreement for "
       "convenience on thirty days written notice.")
REAL = "Governing Law: This Agreement shall be governed by the laws of Delaware"
FAKE = "Non-Compete: The Supplier shall not compete in any territory worldwide"
GT = {"Governing Law": [{"start": 60, "text": "governed by the laws of Delaware"}], "Non-Compete": [],
      "Parties": [{"start": 30, "text": "Acme Corp"}, {"start": 44, "text": "Beta LLC"}]}


def _row(doc_id):
    return {"id": doc_id, "expected_doc_class": "contract", "doc_text": DOC,
            "expected_fields": json.dumps({"cuad_clause_labels": json.dumps(GT)})}


def _attempt(no, extracted, verdict, confidence):
    return {"attempt_no": no, "kind": "extract" if no == 1 else "retry", "extracted_data": extracted,
            "extraction_confidence": confidence, "guardrail": [], "schema_valid": True, "gate_ok": True,
            "judge_verdict": verdict, "judge_score": None, "judge_findings": [], "judge_source_verified": False}


GOOD = {"parties": ["Acme Corp", "Beta LLC"], "cuad_clauses": [REAL]}
WORSE = {"parties": ["Acme Corp", "Beta LLC"], "cuad_clauses": [REAL, FAKE]}


def _pred(history, *, stage="review", **extra):
    latest = history[-1]
    return {"doc_type": "contract", "stage": stage, "extracted_data": dict(latest["extracted_data"]),
            "extraction_confidence": latest["extraction_confidence"], "judge_verdict": latest["judge_verdict"],
            "extraction_attempt_history": history, **extra}


def _store(tmp_path, items):
    run = tmp_path / "r-replay"
    run.mkdir()
    (run / "spec.lock.json").write_text(json.dumps({"run_id": "r-replay", "profile": "modal-vllm",
                                                    "task": "pipeline", "job": {}, "confidence": {}}))
    (run / "dataset.jsonl").write_text("".join(json.dumps(_row(i["item_id"])) + "\n" for i in items))
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
    return run


def _items():
    return [
        # Earlier complete attempt beats the latest partial one: selection restores attempt 1.
        {"item_id": "d1", "ok": True, "pred": _pred([_attempt(1, GOOD, "complete", 0.9),
                                                     _attempt(2, WORSE, "partial", 0.9)])},
        # One attempt: nothing to select. Its FAKE clause is the evidence check's target.
        {"item_id": "d2", "ok": True, "pred": _pred([_attempt(1, WORSE, "partial", 0.9)])},
        {"item_id": "d3", "ok": False, "error": "boom", "pred": None},
        # Aborted with a partial extraction: the gate scores it 0 either way, so it is no evidence.
        {"item_id": "d6", "ok": False, "error": "cost cap", "pred": _pred([_attempt(1, GOOD, "complete", 0.9),
                                                                          _attempt(2, WORSE, "partial", 0.9)],
                                                                         stage="failed")},
        {"item_id": "d4", "ok": True, "pred": _pred([_attempt(1, WORSE, "partial", 0.9)],
                                                    extraction_source="human")},
        # Archived, and the better-ranked earlier attempt is unsure: the archive keeps the latest.
        {"item_id": "d5", "ok": True, "pred": _pred([_attempt(1, GOOD, "complete", 0.05),
                                                     _attempt(2, WORSE, "partial", 0.99)], stage="archived")},
    ]


@pytest.fixture
def activated(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    from mailroom_sandbox import runtime

    yield
    runtime.activate("modal-vllm", load_env_file=False)


def test_a_stored_pipeline_answer_keeps_the_attempt_history():
    """The item a pipeline document becomes carries every key the vendored selection reads.

    Goes through the real item builder (``eval.runners._pipeline_item``) and the real persistence
    (``job.runner._persist_isolated_items``), so a key the builder drops fails here.
    """
    from mailroom_sandbox.eval import runners as eval_runners
    from mailroom_sandbox.job import runner

    history = [_attempt(1, GOOD, "complete", 0.9), _attempt(2, WORSE, "partial", 0.9)]
    state = {**_pred(history), "conflict_detected": False, "extraction_source": "pipeline",
             "judge_source_verified": False, "selected_attempt": 2,
             "selected_attempt_reason": "keep_best_attempt_off", "doc_text": DOC}
    item = eval_runners._pipeline_item(_row("d1"), state, {}, None)

    class Store:
        items: list = []

        def append_item(self, entry):
            self.items.append(json.loads(json.dumps(entry)))

    store = Store()
    runner._persist_isolated_items(store, [{"id": "d1", "pred": item, "score": {}}], seen=set())
    pred = store.items[0]["pred"]
    assert pred["extraction_attempt_history"] == history
    for key in ("conflict_detected", "extraction_source", "judge_source_verified", "judge_verdict",
                "selected_attempt", "selected_attempt_reason"):
        assert pred[key] == state[key], key
    assert "doc_text" not in pred  # the document text stays out of items.jsonl


def test_an_item_without_attempt_keys_keeps_its_old_shape():
    from mailroom_sandbox.eval import runners as eval_runners

    item = eval_runners._pipeline_item(_row("d1"), {"stage": "review"}, {}, None)
    assert not {"extraction_attempt_history", "conflict_detected", "selected_attempt"} & set(item)


def test_selection_restores_the_better_judged_attempt(tmp_path, activated):
    out = ar.replay(_store(tmp_path, _items()))
    docs = {d["id"]: d for d in out["documents"]}
    assert docs["d1"]["selection_reason"] == "better_judged_earlier_attempt" and docs["d1"]["selection_changed"]
    assert docs["d1"]["selected_quality"] > docs["d1"]["latest_quality"]
    assert docs["d2"]["selection_reason"] == "only_attempt" and not docs["d2"]["selection_changed"]
    assert out["selection"]["overall"]["changed"] == 1


def test_an_archived_unsure_earlier_attempt_is_not_selected(tmp_path, activated):
    docs = {d["id"]: d for d in ar.replay(_store(tmp_path, _items()))["documents"]}
    assert docs["d5"]["selection_reason"] == "earlier_attempt_requires_review"
    assert not docs["d5"]["selection_changed"]


def test_the_filter_counts_dropped_items_and_cuad_errors(tmp_path, activated):
    out = ar.replay(_store(tmp_path, _items()))
    contract = out["evidence"]["by_class"]["contract"]
    assert contract["dropped"] == {"cuad_clauses": 4}  # d1, d2, d4 and d5 each carry the FAKE clause
    assert contract["cuad_fp_before"] == 4 and contract["cuad_fp_after"] == 0
    assert contract["cuad_fn_after"] == contract["cuad_fn_before"]
    assert contract["after"] >= contract["before"]


def test_skips_are_counted_and_scored_n_reported(tmp_path, activated):
    out = ar.replay(_store(tmp_path, _items()))
    assert out["counts"]["items"] == 6 and out["counts"]["skipped"] == {"failed": 1, "no_pred": 1}
    assert out["counts"]["human_source"] == 1  # scored on its latest extraction; never re-selected
    assert out["counts"]["scored_n"] == 4
    assert out["selection"]["overall"]["scored_n"] == out["evidence"]["overall"]["scored_n"] == 4


def test_the_bars_follow_the_design():
    up = {"overall": {"scored_n": 20, "latest": 0.5, "selected": 0.6},
          "by_class": {"contract": {"scored_n": 12, "latest": 0.5, "selected": 0.6},
                       "invoice": {"scored_n": 4, "latest": 0.9, "selected": 0.8}}}  # n < 10: not a veto
    assert ar.selection_meets(up) is True
    down = json.loads(json.dumps(up))
    down["by_class"]["contract"].update(scored_n=10, selected=0.49)
    assert ar.selection_meets(down) is False
    flat = json.loads(json.dumps(up))
    flat["overall"]["selected"] = 0.5
    assert ar.selection_meets(flat) is False
    ev = {"by_class": {"contract": {"scored_n": 100, "cuad_fp_before": 40, "cuad_fp_after": 30,
                                    "cuad_fn_before": 50, "cuad_fn_after": 52}}}
    assert ar.evidence_meets_confirming_arm(ev) is True        # -25% false, +2 missed per 100
    ev["by_class"]["contract"]["cuad_fn_after"] = 53
    assert ar.evidence_meets_confirming_arm(ev) is False
    ev["by_class"]["contract"].update(cuad_fn_after=50, cuad_fp_after=31)
    assert ar.evidence_meets_confirming_arm(ev) is False
    assert ar.evidence_meets_confirming_arm({"by_class": {}}) is False  # no contracts: nothing shown
    # A class whose filtered quality falls (n >= 10) vetoes the arm, whatever CUAD shows.
    good = {"by_class": {"contract": {"scored_n": 100, "before": 0.5, "after": 0.5, "cuad_fp_before": 40,
                                      "cuad_fp_after": 30, "cuad_fn_before": 50, "cuad_fn_after": 50},
                         "insurance_claim": {"scored_n": 10, "before": 0.8, "after": 0.79}}}
    assert ar.evidence_meets_confirming_arm(good) is False
    good["by_class"]["insurance_claim"]["scored_n"] = 9
    assert ar.evidence_meets_confirming_arm(good) is True


def test_the_replay_is_labelled_an_estimate_and_writes_its_file(tmp_path, activated):
    out = ar.replay(_store(tmp_path, _items()))
    assert out["label"] == "offline replay (estimate)" and out["run_id"] == "r-replay"
    path = ar.write_replay(out, tmp_path / "out" / "replay.json")
    assert json.loads(path.read_text())["label"] == "offline replay (estimate)"
    text = ar.digest(out, path)
    assert "offline replay (estimate)" in text and "scored_n 4" in text and str(path) in text


def test_a_correct_mode_run_is_refused(tmp_path):
    run = _store(tmp_path, _items())
    lock = json.loads((run / "spec.lock.json").read_text())
    (run / "spec.lock.json").write_text(json.dumps({**lock, "judge": {"mode": "correct"}}))
    with pytest.raises(ar.ReplayError, match="judge.mode correct"):
        ar.replay(run, activate=False)
    (run / "spec.lock.json").write_text(json.dumps({**lock, "judge": {"mode": "verify"}}))
    assert ar.replay(run, activate=False)["counts"]["scored_n"] == 4


def test_the_replay_never_writes_the_source_run(tmp_path, activated):
    run = _store(tmp_path, _items())

    def snapshot():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.iterdir())}

    before = snapshot()
    ar.replay(run)
    assert snapshot() == before


def test_the_default_output_sits_outside_the_run(tmp_path):
    path = ar.default_output("r-replay", runs_root=tmp_path / "runs")
    assert path == tmp_path / "replays" / "r-replay.attempt_replay.json"
