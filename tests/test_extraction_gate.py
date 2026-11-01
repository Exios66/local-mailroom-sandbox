"""Extraction quality gate: question set, Decisions request, specialist handoff, calibration."""

from __future__ import annotations

import importlib.util
import json

import pytest

from mailroom_sandbox import decision_backends as db
from mailroom_sandbox.eval import agents
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.preflight import extraction_handoff_map
from mailroom_sandbox.job.spec import run_dir
from mailroom_sandbox.paths import repo_root

CLASSES = ("insurance_claim", "corporate_record", "correspondence", "contract", "merger_agreement")
STEM = "extraction_gate_v1.0.0"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_question_set_covers_all_five_classes():
    """Question set covers all five classes."""
    qset = db.load_question_set(STEM)
    assert qset["kind"] == db.EXTRACTION_GATE
    assert set(qset["fields"]) == set(CLASSES)
    for cls in CLASSES:
        questions = db.gate_questions(qset, cls)
        assert questions["verdict"]["type"] == "choice" and "accept" in questions["verdict"]["criteria"]
        assert all(q["type"] == "noul" for k, q in questions.items() if k != "verdict")
        assert all("{" not in q["instructions"] for q in questions.values() if q["type"] == "noul")


def test_contract_and_merger_ask_entities_and_native_questions():
    """Contract and merger ask entities and native questions."""
    qset = db.load_question_set(STEM)
    assert {"parties", "governing_law", "effective_date", "cuad_clauses"} <= set(qset["fields"]["contract"])
    assert {"parties", "governing_law", "merger_consideration", "maud_clauses"} <= set(qset["fields"]["merger_agreement"])


def test_gate_set_needs_an_accept_option(tmp_path, monkeypatch):
    """Gate set needs an accept option."""
    (tmp_path / "bad.yaml").write_text("kind: extraction_gate\nverdict: {criteria: {a: x, b: y}}\n"
                                       "fields: {contract: {parties: p}}\nfield_instructions: '{field}'\n")
    monkeypatch.setattr(db, "decisions_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="accept"):
        db.load_question_set("bad")


def test_handoff_drops_private_keys():
    """Handoff drops private keys."""
    out = db.extraction_handoff("contract", {"parties": ["A"], "_raw": "x", "_parse_error": False})
    assert out == {"doc_type": "contract", "fields": {"parties": ["A"]}}
    assert db.extraction_handoff("contract", None)["available"] is False


def test_decide_extraction_parses_answers(monkeypatch):
    """Decide extraction parses answers."""
    seen = {}

    def fake_post(body, *, timeout, attempts):
        seen.update(body)
        return {"model": "openai/gpt-6-luna-decisions", "usage": {"input_tokens": 900, "output_tokens": 0},
                "answers": {"verdict": {"choice": "retry_extraction",
                                        "probabilities": {"accept": 0.2, "retry_extraction": 0.7, "human_review": 0.1}},
                            "field__parties": {"noul": 0.3}, "field__governing_law": {"noul": 0.9}}}

    monkeypatch.setattr(db, "_post_decision", fake_post)
    qset = db.load_question_set(STEM)
    long_doc = "x" * 300_000
    out = db.decide_extraction(long_doc, {"doc_type": "merger_agreement", "fields": {"parties": []}},
                               model="openai/gpt-6-luna-decisions", qset=qset)
    assert out["verdict"] == "retry_extraction" and out["accept_probability"] == 0.2
    assert out["human_review_probability"] == 0.1
    assert out["field_support"] == {"parties": 0.3, "governing_law": 0.9}
    assert out["truncated"] and out["input_chars"] == qset["max_input_chars_by_class"]["merger_agreement"]
    assert set(seen["state"]) == {"document", "extraction_handoff"}
    assert "field__maud_clauses" in seen["questions"]


def test_decide_extraction_refuses_chat_model():
    """Decide extraction refuses chat model."""
    with pytest.raises(ValueError):
        db.decide_extraction("doc", {"doc_type": "contract"}, model="openai/gpt-6-luna", qset=db.load_question_set(STEM))


def _specialist_run(run_id, *, task="contracts_specialist", mock=False, state="done", items=()):
    store = RunStore(run_dir(run_id))
    store.dir.mkdir(parents=True, exist_ok=True)
    store.write_lock({"run_id": run_id, "task": task, "spec_hash": "a" * 64, "job": {"mock": mock}})
    for item in items:
        store.append_item(item)
    store.write_checkpoint(state=state, cursor=len(items), total=len(items))
    return store


def test_handoff_map_from_real_specialist_runs(job_data_dir):
    """Handoff map from real specialist runs."""
    _specialist_run("spec-a", items=[{"item_id": "D1", "ok": True, "pred": {"parties": ["A"]}},
                                     {"item_id": "D2", "ok": False, "pred": None},
                                     {"item_id": "D3", "ok": True, "pred": {"_parse_error": True}}])
    _specialist_run("spec-b", task="correspondence_specialist",
                    items=[{"item_id": "D4", "ok": True, "pred": {"intent": "inform"}}])
    out = extraction_handoff_map(["spec-a", "spec-b"])
    assert out == {"D1": {"doc_type": "contract", "fields": {"parties": ["A"]}},
                   "D4": {"doc_type": "correspondence", "fields": {"intent": "inform"}}}


@pytest.mark.parametrize("kwargs, match", [({"mock": True}, "mock"), ({"state": "failed"}, "finished"),
                                           ({"task": "sorter"}, "not a specialist")])
def test_handoff_map_refuses_mock_unfinished_and_non_specialist(job_data_dir, kwargs, match):
    """Handoff map refuses mock unfinished and non specialist."""
    _specialist_run("spec-x", items=[{"item_id": "D1", "ok": True, "pred": {"parties": ["A"]}}], **kwargs)
    with pytest.raises(ValueError, match=match):
        extraction_handoff_map("spec-x")


def test_gate_is_a_registered_task():
    """Gate is a registered task."""
    from mailroom_sandbox.job.spec import known_tasks

    assert "extraction_gate" in agents.SPECS and "extraction_gate" in known_tasks()


def test_score_pairs_the_answer_with_the_dojo_score(monkeypatch):
    """Score pairs the answer with the dojo score."""
    monkeypatch.setattr(agents, "_locked_reviewer", lambda: {"handoff": {"D1": {"doc_type": "correspondence",
                                                                                   "fields": {"intent": "inform"}}}})
    monkeypatch.setattr(agents, "_score_extract", lambda row, pred: {"overall_extraction_score": 0.75, "scoring_method": "suite"})
    out = agents._score_extraction_gate({"id": "D1"}, {"accept_probability": 0.6, "verdict": "accept"})
    assert out == {"accept_probability": 0.6, "verdict": "accept", "extraction_score": 0.75,
                   "scoring_method": "suite", "doc_type": "correspondence"}


def test_calibration_metrics():
    """Calibration metrics."""
    gate = _script("extraction_gate")
    assert gate.auroc([0.9, 0.8, 0.2], [True, True, False]) == 1.0
    assert gate.auroc([0.5, 0.5], [True, False]) == 0.5
    assert gate.auroc([0.5], [True]) is None
    cut = gate.cutoff_for_precision([0.9, 0.8, 0.7, 0.1], [True, True, False, False], 0.9)
    assert cut["cutoff"] == 0.8 and cut["precision"] == 1.0 and cut["recall"] == 1.0


def test_baseline_sampling_is_stratified_and_needs_truth():
    """Baseline sampling is stratified and needs truth."""
    gate = _script("extraction_gate")
    rows = [{"id": f"D{i}", "expected_doc_class": "correspondence", "expected_subclass": sub,
             "expected_fields": {"gt_presence": json.dumps({"intent": "populated"})}}
            for i, sub in enumerate(["email"] * 10 + ["memo"] * 2)]
    picked = gate.stratified(rows, 4, seed=42)
    assert sorted(r["expected_subclass"] for r in picked) == ["email", "email", "memo", "memo"]
    assert gate.has_truth(rows[0])
    assert not gate.has_truth({"expected_doc_class": "contract", "expected_fields": {"cuad_clause_labels": "{}"}})


def test_spend_estimator_prices_condensed_below_v15():
    """Spend estimator prices condensed below v15."""
    est = _script("estimate_spend")
    base = {"run_id": "x", "task": "isolated", "engine": {"model": "qwen/qwen3.7-flash"}, "job": {}}
    assert est._sorter_prompt_chars({**base, "prompt": {"agents": {"sorter": {"file": "sorter_condensed_v1"}}}}) \
        < est._sorter_prompt_chars(base)


def _row(doc_id, cls, sub, n, text=None):
    return {"id": doc_id, "expected_doc_class": cls, "expected_subclass": sub,
            "doc_text": text or (doc_id + " ") * max(1, n // (len(doc_id) + 1))}


def test_short_first_covers_every_subclass_and_leans_short():
    """Round-2 sampler covers every subclass and draws its shorter half first."""
    eg = _script("extraction_gate")
    rows = [_row(f"{s}{i:02d}", "insurance_claim", s, 100 * (i + 1)) for s in ("a", "b", "c") for i in range(20)]
    picked = eg.short_first(rows, 15, 42)
    assert {r["expected_subclass"] for r in picked} == {"a", "b", "c"}
    median = sorted(len(r["doc_text"]) for r in rows)[len(rows) // 2]
    assert all(len(r["doc_text"]) <= median for r in picked)
    assert picked == eg.short_first(rows, 15, 42)


def test_text_key_folds_whitespace_and_case():
    """Text key folds whitespace and case."""
    eg = _script("extraction_gate")
    assert eg.text_key("Hello  World\n") == eg.text_key("hello world")
    assert eg.text_key("hello world") != eg.text_key("hello there")


def test_round2_rules():
    """Round-2 rules: mergers exclude other, contracts and mergers sampled representatively."""
    eg = _script("extraction_gate")
    assert "other" in eg.EXCLUDE_SUBCLASSES["merger_agreement"]
    assert eg.REPRESENTATIVE == {"contract", "merger_agreement"}
    assert set(eg.ROUND2) == set(eg.CLASSES)
    assert eg.ROUND2["merger_agreement"] < eg.ROUND2["contract"] < eg.ROUND2["corporate_record"] < eg.ROUND2["insurance_claim"]


def test_round2_inputs_never_repeat_collected_documents():
    """Round-2 inputs share no id or text with the baseline inputs."""
    eg = _script("extraction_gate")
    handoff = repo_root() / "data" / "runtime" / "handoff"
    r2, base = handoff / "gate-train-r2.jsonl", handoff / "gate-train.jsonl"
    if not (r2.is_file() and base.is_file()):
        pytest.skip("round-2 inputs not built in this checkout")
    new, old = eg._lines(r2), eg._lines(base)
    assert not {r["id"] for r in new} & {r["id"] for r in old}
    assert not {eg.text_key(r["doc_text"]) for r in new} & {eg.text_key(r["doc_text"]) for r in old}
    assert len({eg.text_key(r["doc_text"]) for r in new}) == len(new)


def test_round_files_match_the_tag_exactly(tmp_path):
    """Round r2's files never include r20's."""
    eg = _script("extraction_gate")
    handoff = tmp_path / "data" / "runtime" / "handoff"
    handoff.mkdir(parents=True)
    for name in ("gate-train-r2.jsonl", "gate-train-r2-contract.jsonl", "gate-train-r20.jsonl",
                 "gate-train-r20-contract.jsonl", "gate-train.jsonl"):
        (handoff / name).write_text("")
    assert [p.name for p in eg.round_files(tmp_path, "train", "r2")] == [
        "gate-train-r2-contract.jsonl", "gate-train-r2.jsonl"]


def test_expand_refuses_to_rebuild_a_round_and_keeps_its_files(tmp_path, monkeypatch, capsys):
    """An existing round is not deleted or rebuilt without --overwrite; a bad --count deletes nothing."""
    import argparse

    eg = _script("extraction_gate")
    monkeypatch.setattr(eg, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(eg, "run_dir", lambda rid: tmp_path / "runs" / rid)
    handoff = tmp_path / "data" / "runtime" / "handoff"
    handoff.mkdir(parents=True)
    kept = handoff / "gate-train-r2.jsonl"
    kept.write_text('{"id": "a"}\n')
    args = argparse.Namespace(dataset_run=[], split="train", tag="r2", count=[], allow_no_history=True,
                              short_share=0.5, seed=1, overwrite=False)
    assert eg.cmd_expand(args) == 1 and "already has 1 input file" in capsys.readouterr().out
    assert kept.is_file()
    args.overwrite, args.count = True, ["contract=many"]
    assert eg.cmd_expand(args) == 1 and kept.is_file()


def test_calibration_reports_field_truth_errors(monkeypatch):
    """A scorer failure is counted per class in skipped, not only printed."""
    eg = _script("extraction_gate")
    monkeypatch.setattr(eg, "_field_truth", lambda *a, **k: ({}, "ImportError: gone"))
    items = [{"item_id": "d1", "ok": True, "pred": {"accept_probability": 0.9, "doc_type": "contract"},
              "score": {"extraction_score": 0.9, "doc_type": "contract"}}]
    report = eg.calibrate(items, {"d1": {"id": "d1"}}, {}, good=0.8, precision=0.9)
    assert report["skipped"] == {"field_truth_error:contract": 1}
