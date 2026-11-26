"""Phase 2 loop governor: the job.governor switch, budgets, stop outcomes and loop fixes L2, L4, L5."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import governor, runtime
from mailroom_sandbox.job.spec import DatasetSpec, GovernorSpec, RunSpec, spec_core


@pytest.fixture(autouse=True)
def _governor_off():
    governor.activate(None)
    yield
    governor.activate(None)


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-gov", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_governor_true_means_the_spec_defaults():
    spec = _spec(governor=True).job.governor
    assert spec == GovernorSpec()
    assert (spec.retries, spec.calls, spec.spend_usd) == (2, 30, None)
    assert spec.calls_by_class == {"merger_agreement": 36}
    assert (spec.sorter_ceiling, spec.near_empty_chars, spec.link_duplicates) == (None, 64, True)
    assert spec.near_duplicate_jaccard == 0.9
    assert _spec(governor=False).job.governor is None


def test_governor_is_hashed_only_when_set():
    assert "governor" not in spec_core(_spec(), source_sha256="0" * 64)["job"]
    assert spec_core(_spec(governor={"retries": 1}), source_sha256="0" * 64)["job"]["governor"]["retries"] == 1


@pytest.mark.parametrize("bad", [{"calls": 40}, {"calls_by_class": {"merger_agreement": 40}}, {"retries": -1},
                                 {"sorter_ceiling": 1.5}, {"spend_usd": 0}])
def test_governor_refuses_a_budget_outside_its_range(bad):
    with pytest.raises(ValidationError):
        _spec(governor=bad)


def test_governor_is_refused_outside_pipeline():
    with pytest.raises(ValidationError, match="governor"):
        _spec(task="correspondence_specialist", governor=True)


def test_the_lock_activates_the_governor(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {"governor": {"retries": 1}}}, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert governor.active().retries == 1
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):  # a lock from before phase 2
        runtime.activate("modal-vllm", load_env_file=False)
    assert governor.active() is None


def test_merger_call_budget_is_36():
    governor.activate(GovernorSpec())
    assert governor.call_budget("merger_agreement") == 36
    assert governor.call_budget("contract") == 30
    assert governor.call_budget(None) == 30


def test_the_runner_merges_governor_stop_into_the_result(monkeypatch):
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.job import call_guard

    stop = {"reason": "retry_budget", "outcome": "human_review", "node": "arbiter", "proposed": "retry_extract",
            "calls": 9, "retries": 2, "spend_usd": 0.0}

    def fake(row, **_):
        call_guard.scope()["governor_stop"] = dict(stop)
        call_guard.scope()["duplicate_of"] = {"doc_id": "d0", "kind": "exact", "similarity": 1.0}
        call_guard.scope()["governor"]["skipped_classify_retries"] = 1
        return {"id": row["id"], "stage": "review"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", fake)
    result = runners._run_pipeline_doc({"id": "d1"})
    assert result["governor_stop"] == stop
    assert result["duplicate_of"]["kind"] == "exact"
    assert result["governor_skips"] == {"classify_retry": 1}


def test_the_runner_adds_no_governor_fields_when_nothing_happened(monkeypatch):
    from mailroom_sandbox.eval import runners

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", lambda row, **_: {"id": row["id"], "stage": "archived"})
    assert runners._run_pipeline_doc({"id": "d1"}) == {"id": "d1", "stage": "archived"}


# --- Task 4: the governor (HF-018) and L2 -------------------------------------------------------------------

from _arbiter_harness import Script, activate_profile, arbiter_harness_state, run  # noqa: E402, F401 (fixture)

from mailroom_sandbox.job import call_guard  # noqa: E402

_ARB = {"arbiter", "compile_report", "retry_extract", "human_review"}
_EXTRACT = {"extract", "retry_extract", "compile_report", "judge_verify", "human_review", "boss_escalation"}


def _harness(monkeypatch, tmp_path, script, *, spec=None, preset=None, bypass=False):
    """One harness document inside a document scope, with the governor set to ``spec``."""
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    governor.activate(spec)
    if bypass:
        import graph.route_spec as rs

        monkeypatch.setattr(rs, "decide_route", rs.decide_route.__wrapped__)
    with call_guard.document() as scope:
        for key, value in (preset or {}).items():
            if key in scope["governor"]:
                scope["governor"][key] = value
            else:
                scope[key] = value
        out = run(bg, monkeypatch, script)
    return out, scope


def _decide(node, proposed, destinations, state=None, spec=None, **counters):
    governor.activate(spec or GovernorSpec())
    with call_guard.document() as scope:
        for key, value in counters.items():
            (scope["governor"] if key in scope["governor"] else scope)[key] = value
        dest = governor.govern(node, state or {}, proposed, destinations)
    return dest, scope


#: A sample of test_arbiter_termination.CASES: every judge verdict once, each arbiter policy, both bands.
_OFF_CASES = [
    ([("complete", "accurate")], ["accept_with_caveats"], [0.95] * 6),
    ([("partial", "accurate")], ["retry_extraction", "accept_with_caveats"], [0.88] * 6),
    ([("incomplete", "accurate")], ["retry_extraction"], [0.88] * 6),
    (["parse_c"], ["accept_with_caveats"], [0.88] * 6),
    (["parse_a_once"], ["retry_extraction"], [0.5] * 6),
    (["blip", ("partial", "accurate")], ["blip"], [0.88] * 6),
]


@pytest.mark.usefixtures("arbiter_harness_state")
@pytest.mark.parametrize(("judge", "arbiter", "confs"), _OFF_CASES)
def test_governor_off_routes_every_harness_case_exactly_as_before(judge, arbiter, confs, monkeypatch, tmp_path):
    script = dict(judge=judge, arbiter=arbiter, confs=confs)
    paths = {}
    for bypass in (False, True):  # each document in its own patch context, so the node wrappers never stack
        with pytest.MonkeyPatch.context() as mp:
            paths[bypass], _ = _harness(mp, tmp_path / str(bypass), Script(**script), bypass=bypass)
    on, off = paths[False], paths[True]
    assert (on["path"], on["stage"]) == (off["path"], off["stage"])


@pytest.mark.usefixtures("arbiter_harness_state")
def test_the_retry_budget_sends_a_third_round_to_review(monkeypatch, tmp_path):
    out, scope = _harness(monkeypatch, tmp_path, Script(judge=[("partial", "accurate")] * 3,
                                                        arbiter=["retry_extraction"], confs=[0.88] * 6),
                          spec=GovernorSpec())
    assert out["stage"] == "review"
    assert out["path"][-3:] == ["retry_extract", "judge_verify", "human_review"]  # no third round (arbiter)
    stop = scope["governor_stop"]
    assert (stop["reason"], stop["outcome"], stop["retries"]) == ("retry_budget", "human_review", 2)
    assert (stop["node"], stop["proposed"]) == ("judge_verify", "arbiter")


@pytest.mark.usefixtures("arbiter_harness_state")
def test_the_call_budget_stops_before_a_round(monkeypatch, tmp_path):
    out, scope = _harness(monkeypatch, tmp_path, Script(judge=[("partial", "accurate")],
                                                        arbiter=["retry_extraction"], confs=[0.88] * 6),
                          spec=GovernorSpec(), preset={"llm_calls": 30})
    assert out["stage"] == "review" and "arbiter" not in out["path"]
    assert scope["governor_stop"]["reason"] == "call_budget" and scope["governor_stop"]["calls"] == 30


def test_mergers_get_36_calls():
    merger = {"doc_type": "merger_agreement"}
    assert _decide("judge_verify", "arbiter", _ARB, merger, llm_calls=30)[0] == "arbiter"
    dest, scope = _decide("judge_verify", "arbiter", _ARB, merger, llm_calls=36)
    assert dest == "human_review" and scope["governor_stop"]["reason"] == "call_budget"
    assert _decide("judge_verify", "arbiter", _ARB, {"doc_type": "contract"}, llm_calls=30)[0] == "human_review"


def test_a_second_boss_entry_is_boss_repeat():
    dest, scope = _decide("extract", "boss_escalation", _EXTRACT)
    assert dest == "boss_escalation" and scope["governor"]["boss"] == 1 and scope["governor"]["retries"] == 1
    dest, scope = _decide("retry_extract", "boss_escalation", _EXTRACT, boss=1, retries=1)
    assert dest == "human_review" and scope["governor_stop"]["reason"] == "boss_repeat"


def test_spend_budget_off_by_default_and_on_when_set():
    assert _decide("judge_verify", "arbiter", _ARB, spend_usd=50.0)[0] == "arbiter"
    dest, scope = _decide("judge_verify", "arbiter", _ARB, spec=GovernorSpec(spend_usd=0.02), spend_usd=0.02)
    assert dest == "human_review" and scope["governor_stop"]["reason"] == "spend_budget"
    assert _decide("judge_verify", "arbiter", _ARB, spec=GovernorSpec(spend_usd=0.02), spend_usd=0.01)[0] == "arbiter"


def test_a_passed_extraction_stops_as_archive_with_caveats():
    passed = {"judge_verdict": "complete", "judge_findings": ["the extraction matches the source"],
              "extraction_attempt_history": [{"judge_verdict": "complete"}]}
    dest, scope = _decide("extract", "boss_escalation", _EXTRACT, passed, retries=2)
    assert dest == "compile_report"
    assert (scope["governor_stop"]["reason"], scope["governor_stop"]["outcome"]) == ("retry_budget",
                                                                                      "archive_with_caveats")
    # a verdict on an earlier attempt does not vouch for the current one
    stale = {**passed, "extraction_attempt_history": [{"judge_verdict": "complete"}, {}]}
    assert _decide("retry_extract", "boss_escalation", _EXTRACT, stale, retries=2)[0] == "human_review"
    assert _decide("extract", "boss_escalation", _EXTRACT, {"judge_verdict": "partial"}, retries=2)[0] == "human_review"


@pytest.mark.usefixtures("arbiter_harness_state")
def test_a_passed_extraction_stopped_in_the_graph_is_archived(monkeypatch, tmp_path):
    import inspect

    from graph import route_spec

    original = inspect.unwrap(route_spec.decide_route)

    def judge_wants_arbiter(spec, state):  # a passed verdict that still proposes a round
        dest = original(spec, state)
        return "arbiter" if spec.node == "judge_verify" and dest == "compile_report" else dest

    from mailroom_sandbox import vendor_hotfixes as vh

    governed = vh._install_governor(route_spec, judge_wants_arbiter)
    governed._sandbox_hotfix = "HF-018"  # activation keeps it, as it keeps an applied fix
    monkeypatch.setattr(route_spec, "decide_route", governed)
    out, scope = _harness(monkeypatch, tmp_path, Script(judge=[("complete", "accurate")], confs=[0.95] * 6),
                          spec=GovernorSpec(), preset={"retries": 2})
    assert out["stage"] == "archived" and "arbiter" not in out["path"]
    assert scope["governor_stop"]["outcome"] == "archive_with_caveats"


def test_every_stop_destination_is_wired_for_its_node():
    from graph.route_spec import ROUTE_SPECS

    proposing = [s for s in ROUTE_SPECS if set(s.destinations) & (governor.ROUND_DESTINATIONS - {s.node})]
    assert {s.node for s in proposing} >= {"classify", "extract", "retry_extract", "judge_verify", "arbiter"}
    for spec in proposing:
        assert "human_review" in spec.destinations, spec.node


def test_a_transient_self_loop_is_not_counted_as_a_round():
    dest, scope = _decide("retry_extract", "retry_extract", _EXTRACT, retries=2)
    assert dest == "retry_extract" and scope["governor"]["retries"] == 2 and "governor_stop" not in scope


def test_the_hard_ceiling_still_backs_up_the_governor():
    spec = GovernorSpec()
    assert call_guard.CALL_CEILING["pipeline"] == 40
    assert max([spec.calls, *spec.calls_by_class.values()]) == 36 < 40


def test_only_the_first_stop_is_recorded():
    governor.activate(GovernorSpec())
    with call_guard.document() as scope:
        scope["governor"]["retries"] = 2
        governor.govern("judge_verify", {}, "arbiter", _ARB)
        governor.govern("arbiter", {}, "retry_extract", _ARB)
    assert scope["governor_stop"]["node"] == "judge_verify"


def test_no_document_scope_means_no_governing():
    governor.activate(GovernorSpec())
    assert governor.govern("judge_verify", {}, "arbiter", _ARB) == "arbiter"


@pytest.mark.usefixtures("arbiter_harness_state")
def test_l2_skips_a_classify_retry_at_the_sorter_ceiling(monkeypatch, tmp_path):
    out, scope = _harness(monkeypatch, tmp_path, Script(sorter=0.95, confs=[0.88] * 6),
                          spec=GovernorSpec(sorter_ceiling=0.95))
    assert out["path"][:3] == ["intake", "classify", "review_classify"] and "retry_classify" not in out["path"]
    assert scope["governor"]["skipped_classify_retries"] == 1 and scope["governor"]["retries"] == 0


@pytest.mark.usefixtures("arbiter_harness_state")
def test_l2_off_keeps_the_classify_retry(monkeypatch, tmp_path):
    out, scope = _harness(monkeypatch, tmp_path, Script(sorter=0.95, confs=[0.88] * 6), spec=GovernorSpec())
    assert out["path"][:3] == ["intake", "classify", "retry_classify"]
    assert scope["governor"]["skipped_classify_retries"] == 0 and scope["governor"]["retries"] == 1


# --- Task 6: L4, duplicates are linked before the conflict check (HF-019) -----------------------------------

import types  # noqa: E402

_WORDS = [f"w{n}" for n in range(300)]
_TEXT = " ".join(_WORDS)


def _row(doc_id, sha, governing_law="New York", doc_type="contract", stage="archived"):
    return types.SimpleNamespace(doc_id=doc_id, doc_type=doc_type, stage=stage, file_sha256=sha,
                                 extracted_data={"governing_law": governing_law})


def _conflict(monkeypatch, rows, *, state=None, spec=GovernorSpec()):
    """HF-019's ``_detect_conflict`` against a catalog holding ``rows``; returns (result, scope)."""
    from mailroom_sandbox import vendor_hotfixes as vh

    assert vh.apply_hotfixes()["HF-019"] == "applied"
    import graph.build_graph as bg
    import storage.catalog as catalog

    async def matter_rows(matter_id):
        return list(rows)

    monkeypatch.setattr(catalog, "get_matter_documents", matter_rows)
    governor.activate(spec)
    doc = {"matter_id": "M1", "doc_id": "d1", "doc_type": "contract", "file_sha256": "sha-new", "doc_text": _TEXT,
           **(state or {})}
    with call_guard.document() as scope:
        result = bg._detect_conflict(doc, {"governing_law": "Delaware"})
    return result, scope


def test_an_exact_re_ingestion_is_linked_not_escalated(monkeypatch):
    (found, details), scope = _conflict(monkeypatch, [_row("d0", "sha-new")])
    assert (found, details) == (False, [])
    assert scope["duplicate_of"] == {"doc_id": "d0", "kind": "exact", "similarity": 1.0}


def test_a_near_duplicate_is_linked(monkeypatch):
    governor.activate(GovernorSpec())
    edited = " ".join(["changed" if i == 150 else w for i, w in enumerate(_WORDS)])
    governor.note_seen("M1", "d0", _TEXT)
    monkeypatch.setattr(governor, "activate", lambda spec: None)  # keep the index the archived document left
    (found, _), scope = _conflict(monkeypatch, [_row("d0", "sha-old")], state={"doc_text": edited})
    assert found is False
    assert scope["duplicate_of"]["kind"] == "near" and scope["duplicate_of"]["similarity"] >= 0.9


def test_a_conflict_with_a_non_duplicate_row_still_escalates(monkeypatch):
    (found, details), scope = _conflict(monkeypatch, [_row("d0", "sha-new"), _row("d2", "sha-other")])
    assert found is True and details and "duplicate_of" not in scope


def test_duplicates_are_not_linked_with_the_governor_off(monkeypatch):
    (found, _), scope = _conflict(monkeypatch, [_row("d0", "sha-new")], spec=None)
    assert found is True and "duplicate_of" not in scope


def test_duplicates_are_not_linked_when_link_duplicates_is_off(monkeypatch):
    (found, _), scope = _conflict(monkeypatch, [_row("d0", "sha-new")], spec=GovernorSpec(link_duplicates=False))
    assert found is True and "duplicate_of" not in scope


def test_other_types_and_unarchived_rows_do_not_block_a_link(monkeypatch):
    rows = [_row("d0", "sha-new"), _row("d3", "sha-x", doc_type="corporate_record"), _row("d4", "sha-y", stage="review")]
    (found, _), scope = _conflict(monkeypatch, rows)
    assert found is False and scope["duplicate_of"]["doc_id"] == "d0"


def test_the_near_duplicate_index_is_safe_across_threads():
    import threading

    governor.activate(GovernorSpec())
    threads = [threading.Thread(target=lambda n=n: [governor.note_seen("M", f"d{n}-{i}", f"{_TEXT} {n} {i}")
                                                     for i in range(25)]) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(governor.seen("M", f"d{n}-{i}") for n in range(8) for i in range(25))
    governor.activate(GovernorSpec())
    assert not governor.seen("M", "d0-0")  # activation starts a fresh index


def test_shingles_are_word_5_grams_of_the_casefolded_collapsed_text():
    assert governor.shingles("A b  C\nd E f") == frozenset({"a b c d e", "b c d e f"})
    assert governor.shingles("one two") == frozenset({"one two"}) and governor.shingles("  ") == frozenset()


def test_a_long_document_keeps_a_bounded_sketch():
    governor.activate(GovernorSpec())
    governor.note_seen("M", "long", " ".join(f"w{n}" for n in range(50_000)))
    assert len(governor.seen("M", "long")) == governor.SKETCH_SIZE
