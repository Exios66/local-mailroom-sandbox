"""Pipeline runs report the sand42 metric contract (SAND-085)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox.job import grid_cards, sand42_cards
from mailroom_sandbox.job.checkpoint import RunStore


def _store(tmp_path, items, rows):
    store = RunStore(tmp_path / "run")
    store.dir.mkdir(parents=True, exist_ok=True)
    store.lock_path.write_text(json.dumps({
        "run_id": "exp-pipeline", "task": "pipeline", "generation_id": "g1",
        "job": {"concurrency": 1}, "dataset": {"limit": len(items)},
        "prompt": {"agents": {"sorter": {"file": "sorter.txt"}, "judge": {"file": "judge.txt"}}},
        "engine": {"model": "m", "modal": {"gpu": "L4", "max_containers": 1}},
    }))
    store.dataset_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    for item in items:
        store.append_item(item)
    return store


def _item(item_id, stage, *, cls=1.0, causes=None, adherence=1.0, latency=1000.0):
    return {"item_id": item_id, "ok": True, "latency_ms": latency, "prompt_tokens": 100, "completion_tokens": 20,
            "pred": {"id": item_id, "stage": stage, "doc_type": "contract", "review_causes": causes},
            "score": {"class_correct": cls, "stage_correct": float(stage == "archived"),
                      "overall_extraction_score": 0.8, "schema_adherence": adherence}}


def _sample(tmp_path):
    rows = [{"id": "a", "expected_doc_class": "contract", "expected_stage": "archived"},
            {"id": "b", "expected_doc_class": "contract", "expected_stage": "archived"},
            {"id": "c", "expected_doc_class": "merger_agreement", "expected_stage": "archived"},
            {"id": "d", "expected_doc_class": "correspondence", "expected_stage": "archived"}]
    items = [_item("a", "archived"), _item("b", "review", causes=["reviewer_disagreement"], adherence=0.5),
             _item("c", "review", cls=0.0, causes=["reviewer_disagreement", "class_miss"]),
             _item("d", "archived", latency=120000.0)]
    return _store(tmp_path, items, rows)


def test_card_carries_pipeline_routing_outcomes(tmp_path):
    card = grid_cards.collect_card(_sample(tmp_path), wall_seconds=60.0)
    block = card["pipeline"]
    assert block["stages"] == {"archived": 2, "review": 2}
    assert block["review_rate"] == 0.5
    assert block["class_correct"] == 0.75
    assert block["stage_correct"] == 0.5
    assert block["review_causes"] == {"reviewer_disagreement": 2, "class_miss": 1}
    assert block["by_class"]["contract"]["documents"] == 2
    assert block["by_class"]["contract"]["review_rate"] == 0.5


def test_card_counts_parked_documents_with_no_cause_token(tmp_path):
    rows = [{"id": "a", "expected_doc_class": "contract"}]
    card = grid_cards.collect_card(_store(tmp_path, [_item("a", "review")], rows), wall_seconds=60.0)
    assert card["pipeline"]["review_causes"] == {"no_cause_recorded": 1}


def test_card_shows_which_classes_had_a_reviewer(tmp_path):
    store = _sample(tmp_path)
    lock = json.loads(store.lock_path.read_text())
    lock["reviewer"] = {"backend": "local", "model": "Org/Second", "classes": {"correspondence": 0.8}}
    store.lock_path.write_text(json.dumps(lock))
    by_class = grid_cards.collect_card(store, wall_seconds=60.0)["pipeline"]["by_class"]
    assert by_class["correspondence"]["reviewer"] == "local:Org/Second"
    assert by_class["correspondence"]["reviewer_cutoff"] == 0.8
    assert by_class["contract"]["reviewer"] is None


def test_card_names_no_single_prompt_for_a_multi_agent_run(tmp_path):
    card = grid_cards.collect_card(_sample(tmp_path), wall_seconds=60.0)
    assert card["conditions"]["prompt"] == "2 agent prompts"
    assert card["quality"]["schema_valid_rate"] == 0.75


def test_pipeline_goodput_uses_each_class_slo(tmp_path):
    card = grid_cards.collect_card(_sample(tmp_path), wall_seconds=60.0)
    summary = sand42_cards._summary("exp-pipeline", card, "pipeline")
    assert summary["pipeline"]["review_rate"] == 0.5
    goodput = summary["goodput"]
    assert goodput["documents_per_minute_per_gpu"] == 4.0
    assert goodput["slo_by_class"]["correspondence"] == {"slo_seconds": 60.0, "meets_slo": False}
    assert goodput["slo_by_class"]["contract"]["meets_slo"] is True
    assert goodput["meets_slo"] is False
    assert goodput["goodput_documents_per_minute_per_gpu"] == 0.0


def test_a_known_slo_miss_beats_a_class_without_a_measurement():
    card = {"conditions": {"replicas": 1}, "time": {"wall_seconds": 60.0}, "quality": {"documents": 4},
            "pipeline": {"by_class": {"correspondence": {"latency_p95": 999.0},
                                      "contract": {"latency_p95": None}}}}
    goodput = sand42_cards._pipeline_goodput(card)
    assert goodput["slo_by_class"]["contract"]["meets_slo"] is None
    assert goodput["meets_slo"] is False and goodput["goodput_documents_per_minute_per_gpu"] == 0.0


def test_pipeline_rows_report_each_documents_own_tokens_and_review_cause(monkeypatch):
    from mailroom_sandbox.eval import runners
    from pipeline import limits

    def fake_doc(row, **_):
        limits.reset_run_usage()  # as _execute_run does on entry
        limits.record_usage({"input_tokens": 100, "output_tokens": 10}, agent="sorter")
        return {"id": row["id"], "doc_type": "contract", "stage": "review", "extracted_data": {},
                "review_causes": ["reviewer_disagreement"], "review_verdict": "decision_escalates"}

    monkeypatch.setattr(runners, "_run_pipeline_doc", fake_doc)
    rows = [{"id": str(i), "expected_doc_class": "contract", "doc_text": "x"} for i in range(2)]
    seen = []
    runners.run_pipeline_eval(profile="ollama", rows=rows, mock=True, row_cb=seen.append)
    assert [(r["prompt_tokens"], r["completion_tokens"], r["llm_calls"]) for r in seen] == [(100, 10, 1)] * 2
    assert seen[0]["pred"]["review_causes"] == ["reviewer_disagreement"]


def test_pipeline_doc_result_keeps_the_review_outcome(tmp_path, monkeypatch):
    import graph.build_graph as bg
    from mailroom_sandbox.eval import runners

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    outcome = {"doc_type": "contract", "stage": "review", "review_causes": ["reviewer_low_confidence"],
               "review_verdict": "decision_escalates", "escalation_reason": "reviewer unsure",
               "reviewer_doc_type": "contract", "reviewer_confidence": 0.4}
    monkeypatch.setattr(bg, "run_pipeline", lambda *a, **k: outcome)
    row = {"id": "a", "doc_text": "text", "expected_doc_class": "contract"}
    result = runners._run_pipeline_doc(row, mock=False)
    assert {key: result[key] for key in outcome} == outcome


def test_low_confidence_park_is_attributed(tmp_path, monkeypatch):
    import graph.build_graph as bg
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.runtime import activate

    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "none")
    activate("ollama", load_env_file=False)
    bg.reset_compiled_graph()
    row = {"id": "memo", "doc_text": "Internal memo about the office move.", "expected_doc_class": "correspondence"}
    try:
        result = runners._run_pipeline_doc(row, mock=True)
    finally:
        bg.reset_compiled_graph()
    # llm-mailroom 90e374b compares the sorter against its class low band again,
    # so a low-confidence park names its cause; since #202 a park after the
    # confidence retry budget also names retries_exhausted.
    assert result["review_causes"] == ["sorter_low_confidence", "retries_exhausted"]


def test_parked_document_reports_the_cause_the_manifest_holds(tmp_path, monkeypatch):
    """A parked run returns pre-interrupt state; the real graph proves the cause still arrives."""
    import graph.build_graph as bg
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.runtime import activate

    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "none")
    activate("ollama", load_env_file=False)
    bg.reset_compiled_graph()
    row = next(row for row in runners.load_manifest() if row["id"] == "corporate_bylaws")
    try:
        result = runners._run_pipeline_doc(row, mock=True)
    finally:
        bg.reset_compiled_graph()
    assert result["stage"] == "review"
    # Blind by default: the graph has no labels, so it cannot call an extraction_miss (that cause
    # compared the extraction with the ground truth mid-run); it parks on its own low confidence.
    assert result["review_causes"] == ["sorter_low_confidence", "retries_exhausted"]


def test_a_failed_document_counts_against_quality_and_pairing():
    arm = {"documents": [{"item_id": "a", "ok": True, "score": 1.0},
                         {"item_id": "b", "ok": False, "score": None}]}
    other = {"documents": [{"item_id": "a", "ok": True, "score": 1.0},
                           {"item_id": "b", "ok": True, "score": 1.0}]}
    quality = sand42_cards._summary("r", arm, "specialist")["quality"]
    assert (quality["mean"], quality["scored_documents"], quality["attempted_documents"]) == (0.5, 1, 2)
    assert sand42_cards.paired_delta(arm, other)["delta_mean"] == 0.5


def test_a_failed_document_scores_zero_even_with_a_partial_score():
    card = {"documents": [{"item_id": "a", "ok": True, "score": 1.0},
                          {"item_id": "b", "ok": False, "score": 0.8},
                          {"item_id": "c", "ok": True, "score": None}]}
    quality = sand42_cards._summary("r", card, "specialist")["quality"]
    assert (quality["mean"], quality["scored_documents"], quality["attempted_documents"],
            quality["unscored_documents"]) == (0.5, 1, 2, 1)
    assert sand42_cards._scores_by_id(card) == {"a": 1.0, "b": 0.0}


def test_remote_mailroom_state_lives_on_the_run_volume(tmp_path):
    from mailroom_sandbox.job.deploy_env import durable_mailroom_env

    assert durable_mailroom_env(tmp_path) == {"MAILROOM_BASE_DIR": str(tmp_path / "mailroom")}


def test_worker_waits_for_background_mailroom_writers_before_commit():
    import threading

    from mailroom_sandbox.job.deploy_env import settle_mailroom_writers

    release, finished = threading.Event(), []
    scan = threading.Thread(target=lambda: (release.wait(5), finished.append(True)),
                            name="relations-scan", daemon=True)
    scan.start()
    assert settle_mailroom_writers(timeout=0.05) == ["relations-scan"]
    release.set()
    assert settle_mailroom_writers(timeout=5) == [] and finished == [True]


def test_settle_waits_for_writers_started_while_joining():
    # CircleCI 419: an aiosqlite worker thread that starts while the first
    # snapshot is joined must be waited on too, not reported as still running.
    import threading
    import time

    from mailroom_sandbox.job.deploy_env import settle_mailroom_writers

    finished = []

    def worker():
        time.sleep(0.2)
        finished.append("worker")

    def scan():
        time.sleep(0.1)  # spawn after settle's first enumerate, mid-join
        threading.Thread(target=worker, name="_connection_worker_thread", daemon=True).start()
        finished.append("scan")

    threading.Thread(target=scan, name="relations-scan", daemon=True).start()
    assert settle_mailroom_writers(timeout=5) == []
    assert finished == ["scan", "worker"]


# --- the intake block of an item result ---------------------------------------------------------

_NO_INTAKE = {"gate_fired": False, "windows": 0, "triage_class": None, "triage_confidence": None,
              "prior_sent": False, "clean_refused": False, "read_failed": False}


def test_intake_summary_when_the_gate_did_not_fire():
    from mailroom_sandbox.eval import runners

    assert runners.intake_summary({}) == _NO_INTAKE
    assert runners.intake_summary({"intake_prep": None}) == _NO_INTAKE


def test_mock_pipeline_import_fallback_keeps_the_intake_result_contract(monkeypatch):
    import builtins

    from mailroom_sandbox.eval import runners

    original = builtins.__import__

    def without_graph(name, *args, **kwargs):
        if name == "graph.build_graph":
            raise ImportError("pipeline unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_graph)
    result = runners._run_pipeline_doc({"id": "fallback", "doc_text": "A short letter.",
                                        "expected_doc_class": "correspondence", "expected_stage": "archived"},
                                       mock=True)
    assert result["offline_fallback"] is True
    assert result["intake"] == _NO_INTAKE


def test_intake_summary_reports_a_real_read_without_any_text():
    from mailroom_sandbox.eval import runners

    prep = {"triage": {"primary_doc_class": "contract", "confidence": 0.91, "gist": "SECRET GIST",
                       "keywords": ["k"]}, "windows": 1, "sections": [{"heading": "H"}],
            "cleaned": "CLEANED TEXT"}
    out = runners.intake_summary({"intake_prep": prep})
    assert out == {"gate_fired": True, "windows": 1, "triage_class": "contract", "triage_confidence": 0.91,
                   "prior_sent": True, "clean_refused": False, "read_failed": False}
    assert "SECRET" not in str(out) and "CLEANED" not in str(out)


def test_intake_summary_marks_a_failed_read_and_a_refused_clean():
    from mailroom_sandbox.eval import runners

    failed = runners.intake_summary({"intake_prep": {"triage": {}, "windows": 1, "sections": []}})
    assert failed["gate_fired"] and failed["read_failed"] and not failed["prior_sent"]
    assert failed["triage_class"] is None and failed["triage_confidence"] is None
    refused = runners.intake_summary({"intake_prep": {"triage": {"primary_doc_class": "unknown", "confidence": 0.2,
                                                                 "gist": "g"}, "windows": 2,
                                                      "clean_refused": "cleaned_text kept 3 of 90 characters"}})
    assert refused["clean_refused"] is True and refused["windows"] == 2 and not refused["read_failed"]


def test_pipeline_doc_result_carries_the_intake_block(tmp_path, monkeypatch):
    import graph.build_graph as bg
    from mailroom_sandbox.eval import runners

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    outcome = {"doc_type": "contract", "stage": "archived",
               "intake_prep": {"triage": {"primary_doc_class": "contract", "confidence": 0.8, "gist": "g"},
                               "windows": 1, "sections": []}}
    monkeypatch.setattr(bg, "run_pipeline", lambda *a, **k: outcome)
    row = {"id": "a", "doc_text": "text", "expected_doc_class": "contract"}
    result = runners._run_pipeline_doc(row, mock=False)
    assert result["intake"]["gate_fired"] is True and result["intake"]["triage_class"] == "contract"
    assert "intake_prep" not in result  # the text-bearing prep never reaches an item record
    monkeypatch.setattr(bg, "run_pipeline", lambda *a, **k: {"doc_type": "contract", "stage": "archived"})
    assert runners._run_pipeline_doc(row, mock=False)["intake"] == _NO_INTAKE


def test_intake_summary_sees_a_call_that_raised_inside_the_node(monkeypatch):
    """intake_node sets intake_prep None when the call raises; the gate is read from the state's flags."""
    from agents import intake
    from mailroom_sandbox.eval import runners

    monkeypatch.setenv("MAILROOM_LLM_INTAKE", "1")
    raised = runners.intake_summary({"intake_prep": None, "intake_messy": True, "doc_text": "messy text"})
    assert raised["gate_fired"] is True and raised["read_failed"] is True and raised["prior_sent"] is False
    assert raised["windows"] == 0 and raised["triage_class"] is None
    assert runners.intake_summary({"intake_prep": None, "intake_messy": False, "doc_text": "short"}) == _NO_INTAKE
    monkeypatch.setenv("MAILROOM_LLM_INTAKE", "0")
    assert runners.intake_summary({"intake_prep": None, "intake_messy": True, "doc_text": "x"}) == _NO_INTAKE
    assert intake.should_llm_intake("x", {"messy": True})  # the gate itself is unchanged


@pytest.mark.parametrize("windows", [[1], "x", {"n": 1}, float("inf"), float("nan")])
def test_intake_summary_never_raises_on_a_malformed_window_count(windows):
    from mailroom_sandbox.eval import runners

    prep = {"triage": {"primary_doc_class": "contract", "confidence": 0.8, "gist": "g"}, "windows": windows}
    out = runners.intake_summary({"intake_prep": prep})
    assert out["windows"] is None and out["gate_fired"] is True and out["triage_class"] == "contract"
    assert runners.intake_summary({"intake_prep": {**prep, "windows": "3"}})["windows"] == 3
