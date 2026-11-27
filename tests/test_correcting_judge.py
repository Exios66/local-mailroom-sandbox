"""Phase 4 correcting judge: the judge: switch, lock, preflight refusals, ruling, record and reports."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from mailroom_sandbox import correcting_judge as cj
from mailroom_sandbox.job import api_budget, preflight
from mailroom_sandbox.job.spec import DatasetSpec, JudgeSpec, RunSpec, spec_core

QWEN = "qwen/qwen3.7-plus"
FLASH = "deepseek/deepseek-v4.1-flash-1017"


@pytest.fixture(autouse=True)
def _judge_off():
    cj.deactivate()
    yield
    cj.deactivate()


@pytest.fixture
def pool(tmp_path):
    path = tmp_path / "pool.jsonl"
    path.write_text(json.dumps({"doc_id": "DOC-1", "doc_class": "contract", "subclass": "Service",
                                "set": "pool", "component": "DOC-1", "fields": {}}) + "\n")
    return path


def _spec(task="pipeline", profile="openrouter", judge=None, **extra):
    return RunSpec(run_id="r-judge", task=task, profile=profile, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True}, judge=judge, **extra)


def _correct(pool=None, **over):
    return {"mode": "correct", **({"references": "train_pool", "reference_pool": str(pool)} if pool else {}), **over}


def _core(spec):
    return spec_core(spec, source_sha256="0" * 64)


# --- Task 1: the switch, the lock and the preflight refusals -------------------------------------


def test_no_judge_section_leaves_the_spec_hash_unchanged():
    base = _spec()
    assert "judge" not in _core(base)
    assert base.spec_hash() == _spec(judge=None).spec_hash()


def test_a_judge_section_is_hashed_with_the_pool_sha(pool):
    spec = _spec(judge=_correct(pool))
    before = _core(spec)["judge"]
    assert before["reference_pool_sha256"] == hashlib.sha256(pool.read_bytes()).hexdigest()
    first = spec.spec_hash()
    pool.write_text(pool.read_text() + "\n")
    assert spec.spec_hash() != first


def test_judge_requires_a_pipeline_task():
    with pytest.raises(ValidationError, match="pipeline"):
        _spec(task="sorter", judge={"mode": "correct"})


def test_preflight_refuses_an_unpriced_or_unpinned_judge_model(monkeypatch):
    errors = preflight._judge_errors(_spec(judge=_correct(model="acme/unpriced-judge")))
    assert any("acme/unpriced-judge" in e and "price" in e for e in errors), errors
    from mailroom_sandbox import provider_pins

    monkeypatch.setattr(provider_pins, "load_pins", lambda path=None: {FLASH: {"order": [], "allow_fallbacks": False}})
    errors = preflight._judge_errors(_spec(judge=_correct()))
    assert any(QWEN in e and "pin" in e for e in errors), errors
    assert any(FLASH in e and "pin" in e for e in errors), errors  # models_by_class is checked too


def test_preflight_refuses_correct_mode_off_openrouter(monkeypatch):
    from mailroom_sandbox import provider_pins

    pinned = {m: {"order": ["x"], "allow_fallbacks": False} for m in (QWEN, FLASH)}
    monkeypatch.setattr(provider_pins, "load_pins", lambda path=None: pinned)
    assert preflight._judge_errors(_spec(judge=_correct())) == []
    errors = preflight._judge_errors(_spec(profile="modal-vllm", judge=_correct()))
    assert any("openrouter" in e.lower() for e in errors), errors


def test_preflight_refuses_a_missing_or_changed_pool(tmp_path, pool, monkeypatch):
    from mailroom_sandbox import provider_pins

    pinned = {m: {"order": ["x"], "allow_fallbacks": False} for m in (QWEN, FLASH)}
    monkeypatch.setattr(provider_pins, "load_pins", lambda path=None: pinned)
    missing = _spec(judge=_correct(tmp_path / "absent.jsonl"))
    assert any("reference_pool" in e for e in preflight._judge_errors(missing))
    spec = _spec(judge=_correct(pool))
    assert preflight._judge_errors(spec) == []
    locked = spec.spec_hash()
    pool.write_text(pool.read_text().replace("Service", "Lease"))
    assert spec.spec_hash() != locked  # a changed pool is a drifted spec: resume refuses it


def test_catalog_references_are_refused():
    with pytest.raises(ValidationError, match="catalog"):
        _spec(judge={"mode": "correct", "references": "catalog"})


def test_a_train_pool_needs_a_reference_pool_file():
    with pytest.raises(ValidationError, match="reference_pool"):
        _spec(judge={"mode": "correct", "references": "train_pool"})


def test_train_pool_is_refused_on_a_draw_with_calibration_or_pool_rows(pool):
    sets = {"DOC-dev": "dev", "DOC-cal": "calibration", "DOC-pool": "pool"}
    spec = _spec(judge=_correct(pool))
    assert cj.reference_set_errors(spec, ["DOC-dev"], sets=sets) == []
    errors = cj.reference_set_errors(spec, ["DOC-dev", "DOC-cal", "DOC-pool"], sets=sets)
    assert errors and "calibration" in errors[0] and "2" in errors[0]
    assert cj.reference_set_errors(_spec(judge=_correct()), ["DOC-cal"], sets=sets) == []  # references off


def test_the_spend_cap_prices_the_judge_models():
    models = api_budget.spec_api_models(_spec(judge=_correct()))
    assert {QWEN, FLASH} <= set(models)
    lock = {"task": "pipeline", "judge": {"mode": "correct", "model": QWEN, "models_by_class": {"merger_agreement": FLASH}}}
    assert {QWEN, FLASH} <= set(api_budget.api_models(lock))
    assert api_budget.api_models({"task": "pipeline", "judge": {"mode": "verify", "model": QWEN}}) == []


def test_the_lock_activates_the_judge_and_refuses_a_changed_pool(pool, monkeypatch):
    from mailroom_sandbox import runtime

    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    spec = _spec(judge=_correct(pool))
    core = _core(spec)
    lock = {"profile": "modal-vllm", "task": "pipeline", "job": {}, "judge": core["judge"], "spec_core": core}
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert cj.active()["mode"] == "correct"
    with runtime.locked_runtime({"profile": "modal-vllm", "task": "pipeline", "job": {}}, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert cj.active() is None  # a lock without the key: today's judge, no record
    pool.write_text(pool.read_text().replace("Service", "Lease"))
    with pytest.raises(RuntimeError, match="reference pool"):
        with runtime.locked_runtime(lock, {}):
            runtime.activate("modal-vllm", load_env_file=False)


def test_judge_model_picks_the_class_override():
    cj.activate(JudgeSpec(mode="correct").model_dump(), pool_sha256=None)
    assert cj.judge_model("merger_agreement") == FLASH
    assert cj.judge_model("contract") == QWEN


def test_verify_mode_refuses_judge_models_and_references(pool):
    for over in ({"model": FLASH}, {"models_by_class": {}}, {"references": "train_pool", "reference_pool": str(pool)}):
        with pytest.raises(ValidationError, match="verify"):
            _spec(judge={"mode": "verify", **over})
    assert _spec(judge={"mode": "verify"}).judge.mode == "verify"


def test_verify_mode_is_not_price_or_route_checked():
    assert preflight._judge_errors(_spec(profile="modal-vllm", judge={"mode": "verify"})) == []
    assert api_budget.spec_api_models(_spec(profile="modal-vllm", judge={"mode": "verify"})) == []


# --- Task 2: the record for both judges ----------------------------------------------------------

from _arbiter_harness import Script, activate_profile, arbiter_harness_state, run  # noqa: E402, F401 (fixture)

from mailroom_sandbox.job import call_guard  # noqa: E402


def _judged(monkeypatch, tmp_path, script, judge=None):
    """One harness document inside a document scope, with the judge section set to ``judge``."""
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    cj.activate(judge, pool_sha256=None)
    with call_guard.document() as scope:
        out = run(bg, monkeypatch, script)
    return bg, out, scope


@pytest.mark.usefixtures("arbiter_harness_state")
def test_verify_mode_records_the_verdict_and_the_extraction_before_the_judge(monkeypatch, tmp_path):
    from _arbiter_harness import DATA

    script = Script(judge=[("partial", "accurate"), ("complete", "accurate")], arbiter=["retry_extraction"],
                    confs=[0.88, 0.88])
    bg, out, scope = _judged(monkeypatch, tmp_path, script, {"mode": "verify"})
    rulings = scope["judge_rulings"]
    assert [r["pass"] for r in rulings] == [1, 2], rulings
    assert [r["ruling"] for r in rulings] == ["partial", "complete"]
    assert all(r["mode"] == "verify" and r["fixes"] == [] and r["model"] == "harness-model" for r in rulings)
    assert isinstance(rulings[0]["score"], float) and rulings[0]["reason"]
    assert scope["before_judge"] == bg._clean_fields_for_judge(dict(DATA))
    assert "judge_corrected" not in scope


@pytest.mark.usefixtures("arbiter_harness_state")
def test_no_judge_section_records_nothing(monkeypatch, tmp_path):
    script = Script(judge=[("partial", "accurate"), ("complete", "accurate")], arbiter=["retry_extraction"],
                    confs=[0.88, 0.88])
    _, out, scope = _judged(monkeypatch, tmp_path, script, None)
    assert out["judge_passes"] == 2
    assert not {"judge_rulings", "before_judge", "judge_corrected"} & set(scope)


def test_the_runner_copies_the_record_into_the_result(monkeypatch):
    from mailroom_sandbox import judge_record
    from mailroom_sandbox.eval import runners

    entry = {"pass": 1, "mode": "verify", "ruling": "partial", "score": 0.5, "reason": "r", "fixes": [],
             "retry_fields": [], "wrong_fields": [], "model": "m"}

    def fake(row, **_):
        judge_record.note_before({"a": 1})
        judge_record.note_before({"a": 2})  # a later pass never overwrites the first
        judge_record.note_ruling(entry)
        judge_record.note_corrected()
        return {"id": row["id"], "stage": "archived"}

    monkeypatch.setattr(runners, "_run_pipeline_doc_once", fake)
    result = runners._run_pipeline_doc({"id": "d1"})
    assert result["judge_rulings"] == [entry]
    assert result["before_judge"] == {"a": 1}
    assert result["judge_corrected"] is True
    monkeypatch.setattr(runners, "_run_pipeline_doc_once", lambda row, **_: {"id": row["id"], "stage": "archived"})
    assert runners._run_pipeline_doc({"id": "d1"}) == {"id": "d1", "stage": "archived"}


def test_the_runner_records_the_dataset_row_id_in_the_document_scope(monkeypatch):
    from mailroom_sandbox.eval import runners

    seen = {}
    monkeypatch.setattr(runners, "_run_pipeline_doc_once",
                        lambda row, **k: seen.update(call_guard.scope() or {}) or {"stage": "archived"})
    runners._run_pipeline_doc({"id": "DOC-row-7"})
    assert seen["row_id"] == "DOC-row-7"


def test_hf025_is_registered_with_a_pinned_source():
    import graph.build_graph as bg
    import graph.routing as routing
    from agents.judge import CompletenessJudge

    from mailroom_sandbox import vendor_hotfixes as vh

    fix = next(f for f in vh.HOTFIXES if f.id == "HF-025")
    assert [f.id for f in vh.HOTFIXES].count("HF-025") == 1
    assert (fix.module, fix.attr) == ("graph.build_graph", "judge_verify_node")
    assert fix.source_sha256 == vh._source_sha(bg.judge_verify_node)
    also = dict(fix.also)
    assert also["graph.routing:after_judge"] == vh._source_sha(routing.after_judge)
    assert also["agents.judge:CompletenessJudge.judge_completeness"] == vh._source_sha(
        CompletenessJudge.judge_completeness)
    assert vh.apply_hotfixes()["HF-025"] == "applied"
    node = bg.judge_verify_node
    assert vh.apply_hotfixes()["HF-025"] == "applied"  # idempotent: the node is not wrapped twice
    assert bg.judge_verify_node is node


# --- Task 4: the correcting judge and its ruling -------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402

DOC = ("This Services Agreement is made between Acme Holdings Ltd and Birch Logistics LLC. "
       "It is effective as of March 3, 2024.")
EXTRACTED = {"document_name": "Services Agreement", "parties": ["Acme Holdings Ltd"], "effective_date": None,
             "governing_law": "Delaware", "maud_clauses": ["x"], "confidence": 0.7, "reasoning": "r"}


def _reply(ruling="accept", fixes=(), wrong=(), retry=(), score=0.9, reason="harness ruling"):
    return {"ruling": ruling, "score": score, "reason": reason, "wrong_fields": list(wrong),
            "retry_fields": list(retry), "fixes": [dict(f) for f in fixes]}


def _fake_judge(monkeypatch, replies):
    """Answer each correcting-judge call with the next reply; return the captured calls."""
    calls: list[dict] = []
    seq = list(replies)

    def call(self, user_message, json_schema=None, *a, **k):
        calls.append({"model": self.model, "prompt": user_message, "schema": json_schema})
        return seq[min(len(calls), len(seq)) - 1]

    monkeypatch.setattr("agents.base.get_llm", lambda *a, **k: (MagicMock(), "harness-model"))
    monkeypatch.setattr(cj.CorrectingJudge, "_call_structured", call)
    return calls


def _state(**over):
    return {"doc_id": "D1", "doc_type": "contract", "contract_subtype": "Service", "doc_text": DOC,
            "extracted_data": dict(EXTRACTED), "extraction_confidence": 0.7, "judge_pass_count": 0, **over}


_DATE_FIX = {"field": "effective_date", "value": "2024-03-03", "quote": "effective as of March 3, 2024"}
_BAD_FIX = {"field": "governing_law", "value": "England", "quote": "governed by English law"}


def _correct_on():
    cj.activate({**JudgeSpec(mode="correct").model_dump(), "reference_pool_sha256": None}, pool_sha256=None)


def test_the_prompt_puts_the_document_first():
    prompt = cj.build_prompt(doc_text=DOC, doc_type="contract", subclass="Service",
                             extracted={"parties": ["Acme Holdings Ltd"]}, requested_fields=["parties"],
                             guide={"parties": "Every party named as bound."},
                             examples=[{"doc_id": "EX-1", "fields": {"parties": ["X"]}}],
                             attempts=[{"attempt": 1, "fields": {"parties": []}}])
    assert prompt.startswith("Rule on this extraction.")
    order = [prompt.index(DOC), prompt.index("Every party named as bound."), prompt.index("EX-1"),
             prompt.index('"attempt": 1'), prompt.index('"Acme Holdings Ltd"')]
    assert order == sorted(order), order


@pytest.mark.usefixtures("arbiter_harness_state")
def test_an_accept_applies_only_verified_fixes(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    _fake_judge(monkeypatch, [_reply(fixes=[_DATE_FIX, _BAD_FIX], wrong=["effective_date"])])
    _correct_on()
    with call_guard.document() as scope:
        update = bg.judge_verify_node(_state())
    assert update["judge_verdict"] == "complete" and update["judge_source_verified"] is True
    assert update["extracted_data"]["effective_date"] == "2024-03-03"
    assert update["extracted_data"]["governing_law"] == "Delaware"  # the unsupported fix is not applied
    assert update["judge_pass_count"] == 1 and update["judge_findings"] == ["harness ruling"]
    assert scope["judge_corrected"] is True
    [entry] = scope["judge_rulings"]
    assert [(f["field"], f["why"]) for f in entry["fixes"]] == [("effective_date", "ok"), ("governing_law", "quote_not_found")]
    assert scope["before_judge"]["effective_date"] is None


@pytest.mark.usefixtures("arbiter_harness_state")
def test_an_accept_with_an_unfixed_wrong_field_retries_on_the_first_ruling(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    _fake_judge(monkeypatch, [_reply(fixes=[_BAD_FIX], wrong=["governing_law"])])
    _correct_on()
    with call_guard.document() as scope:
        first = bg.judge_verify_node(_state())
        second = bg.judge_verify_node(_state(judge_pass_count=1))
    assert first["judge_verdict"] == "partial" and "extracted_data" not in first
    assert second["judge_verdict"] == "incomplete"
    assert [r["ruling"] for r in scope["judge_rulings"]] == ["retry_fields", "human_review"]
    assert scope["judge_rulings"][0]["retry_fields"] == ["governing_law"]
    assert "judge_corrected" not in scope


def test_a_ruling_is_one_call(monkeypatch):
    calls = _fake_judge(monkeypatch, [_reply()])
    _correct_on()
    with call_guard.document():
        entry = cj.rule(_state(), pass_no=1)
    assert len(calls) == 1 and entry["ruling"] == "accept" and entry["mode"] == "correct"
    assert calls[0]["schema"] == cj.RULING_SCHEMA


def test_a_parse_failure_is_asked_once_then_reviewed(monkeypatch):
    from mailroom_sandbox.vendor_hotfixes import JUDGE_REPAIR_NOTE, JudgeParseError

    garbage = {"_raw": "not json", "_parse_error": True}
    calls = _fake_judge(monkeypatch, [garbage, _reply()])
    _correct_on()
    with call_guard.document():
        assert cj.rule(_state(), pass_no=1)["ruling"] == "accept"
    assert len(calls) == 2 and JUDGE_REPAIR_NOTE in calls[1]["prompt"]
    calls = _fake_judge(monkeypatch, [garbage, {"ruling": "maybe"}])
    with call_guard.document(), pytest.raises(JudgeParseError):
        cj.rule(_state(), pass_no=1)
    assert len(calls) == 2


@pytest.mark.usefixtures("arbiter_harness_state")
def test_a_parse_failure_twice_goes_to_review_from_the_node(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    _fake_judge(monkeypatch, [{"_raw": "x", "_parse_error": True}])
    _correct_on()
    with call_guard.document() as scope:
        update = bg.judge_verify_node(_state())
    assert update["judge_verdict"] == "judge_error" and "review" in update["escalation_reason"]
    assert scope["judge_rulings"][-1]["ruling"] == "human_review"


def test_a_document_over_the_judge_context_goes_to_review(monkeypatch):
    from mailroom_sandbox import context_fit

    calls = _fake_judge(monkeypatch, [_reply()])
    monkeypatch.setattr(context_fit, "api_context_lengths", lambda: {QWEN: 1000})
    _correct_on()
    with call_guard.document():
        entry = cj.rule(_state(doc_text="x" * 10_000), pass_no=1)
    assert calls == []
    assert (entry["ruling"], entry["reason"]) == ("human_review", "judge_input_too_long")


def test_merger_documents_are_judged_by_the_class_model(monkeypatch):
    calls = _fake_judge(monkeypatch, [_reply()])
    _correct_on()
    with call_guard.document():
        entry = cj.rule(_state(doc_type="merger_agreement", doc_subclass="stock_purchase"), pass_no=1)
    assert calls[0]["model"] == FLASH and entry["model"] == FLASH


def test_the_judge_sees_only_the_requested_fields(monkeypatch):
    calls = _fake_judge(monkeypatch, [_reply(fixes=[{"field": "maud_clauses", "value": ["y"], "quote": "Acme"}])])
    _correct_on()
    with call_guard.document() as scope:
        scope["subclass_schema"] = {"drop": ["maud_clauses"], "add": {}}
        requested = cj.requested_fields("contract")
        entry = cj.rule(_state(), pass_no=1)
    assert "maud_clauses" not in requested and {"parties", "effective_date"} <= set(requested)
    assert not {"confidence", "reasoning"} & set(requested)
    assert "maud_clauses" not in calls[0]["prompt"]
    assert entry["fixes"][0]["why"] == "not_requested"


def test_the_mock_answers_the_correcting_judge():
    from mailroom_sandbox.mock_llm import fake_structured_payload

    prompt = cj.build_prompt(doc_text="Evaluate extraction completeness of this Arbiter text.", doc_type="contract",
                             subclass=None, extracted={}, requested_fields=[], guide={}, examples=[], attempts=[])
    answer = fake_structured_payload(prompt, {"doc_type": "contract"})
    assert answer["ruling"] == "accept" and answer["fixes"] == [] and set(cj.RULING_SCHEMA["required"]) <= set(answer)


# --- Task 5: arbiter pass-through, field-only retry, the two-ruling limit and the governor -------

from mailroom_sandbox import governor  # noqa: E402
from mailroom_sandbox.job.spec import GovernorSpec  # noqa: E402

ACCEPT = _reply()
REVIEW = _reply(ruling="human_review", reason="a person must decide")
RETRY = _reply(ruling="retry_fields", wrong=["entity_name"], retry=["entity_name"], reason="re-read the name")
ACCEPT_UNFIXED = _reply(wrong=["record_type"], reason="record type wrong")
QUOTED = _reply(fixes=[{"field": "entity_name", "value": "Cedar Sample Ltd", "quote": "Cedar Sample Ltd board"}],
                wrong=["entity_name"])


def _corrected(monkeypatch, tmp_path, rulings, *, gov=None, preset=None, **script):
    """One harness document with the correcting judge on and its rulings scripted."""
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    governor.activate(gov)
    _correct_on()
    with call_guard.document() as scope:
        for key, value in (preset or {}).items():
            (scope["governor"] if key in scope["governor"] else scope)[key] = value
        out = run(bg, monkeypatch, Script(rulings=list(rulings), confs=[0.88] * 4, real_retry=True,
                                          judge=[("complete", "accurate")], **script))
    governor.activate(None)
    return out, scope


pytestmark_t5 = pytest.mark.usefixtures("arbiter_harness_state")


@pytestmark_t5
def test_the_arbiter_makes_no_call_in_correct_mode(monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT])
    assert out["arbiter"] == 0 and "arbiter" in out["path"]
    assert out["judge_c"] == out["judge_a"] == 0  # the vendored judge calls are replaced, not added to


@pytestmark_t5
def test_a_retry_asks_only_for_the_named_fields(monkeypatch, tmp_path):
    out, _ = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT])
    [schema] = out["retry_schemas"]
    assert set(schema["properties"]) == {"entity_name", "confidence"}
    assert set(schema.get("required") or ()) <= {"entity_name", "confidence"}


@pytestmark_t5
def test_a_retry_keeps_every_other_field(monkeypatch, tmp_path):
    out, _ = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT])
    data = out["state"]["extracted_data"]
    assert data["entity_name"] == "Cedar Sample Limited"  # the named field is re-read
    assert data["record_type"] == "minutes"  # the unnamed one keeps the first extraction's value
    history = out["state"]["extraction_attempt_history"]
    assert history[-1]["kind"] == "retry_extract" and history[-1]["extracted_data"]["record_type"] == "minutes"


@pytestmark_t5
def test_a_retry_returns_to_the_judge(monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT])
    assert out["rulings"] == 2 and out["path"].count("judge_verify") == 2
    assert out["stage"] == "archived", out["path"]
    assert [r["ruling"] for r in scope["judge_rulings"]] == ["retry_fields", "accept"]


@pytestmark_t5
def test_a_second_ruling_cannot_retry(monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, RETRY])
    assert out["stage"] == "review", out["path"]
    assert out["rulings"] == 2 and out["path"].count("retry_extract") == 1
    assert [r["ruling"] for r in scope["judge_rulings"]] == ["retry_fields", "human_review"]


@pytestmark_t5
@pytest.mark.parametrize("second", ["accept", "quoted"])
def test_a_failed_field_retry_goes_to_a_person_not_the_judge(second, monkeypatch, tmp_path):
    """Review finding: a re-read whose specialist raised must never be archived by the second ruling."""
    import graph.build_graph as bg_module

    def boom(*a, **k):
        raise ValueError("specialist blew up")

    monkeypatch.setattr(bg_module, "_instantiate_specialist", boom)
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, {"accept": ACCEPT, "quoted": QUOTED}[second]])
    assert out["stage"] == "review", out["path"]
    assert [r["ruling"] for r in scope["judge_rulings"]] == ["retry_fields"]  # no second ruling on a failed re-read


@pytest.mark.parametrize("bad", ["parse_error", "schema_invalid", "empty", "guardrail"])
def test_the_rejudge_route_refuses_an_unreviewable_retry(bad, monkeypatch):
    from graph import routing

    from mailroom_sandbox import vendor_hotfixes as vh

    monkeypatch.setattr(cj, "retry_owed", lambda state: True)
    monkeypatch.setattr(routing, "validate_extraction", lambda doc_type, data: {"schema_valid": True})
    state = {"doc_type": "corporate_record", "extracted_data": {"entity_name": "Cedar Sample Ltd"}}
    assert vh._judge_retry_rule(state, "human_review") == "judge_verify"  # a sound re-read owes its ruling
    if bad == "schema_invalid":
        monkeypatch.setattr(routing, "validate_extraction", lambda doc_type, data: {"schema_valid": False})
    elif bad == "parse_error":
        state["extracted_data"] = {"_parse_error": True, "_exception": "boom"}
    elif bad == "empty":
        state["extracted_data"] = {}
    elif bad == "guardrail":
        state["extraction_guardrail"] = "hollow_extraction"
    assert vh._judge_retry_rule(state, "human_review") is None
    assert vh._judge_retry_rule(state, "compile_report") is None


_FIRST = {"accept": ACCEPT, "accept_unfixed": ACCEPT_UNFIXED, "retry": RETRY, "human_review": REVIEW}


@pytestmark_t5
@pytest.mark.parametrize("first", sorted(_FIRST))
@pytest.mark.parametrize("second", sorted(_FIRST))
def test_every_path_ends_within_two_rulings_and_one_retry(first, second, monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [_FIRST[first], _FIRST[second]])
    assert out["rulings"] <= 2 and out["path"].count("retry_extract") <= 1 and out["arbiter"] == 0
    assert out["stage"] in ("archived", "review"), out["path"]
    if first == "accept":
        assert out["stage"] == "archived" and out["rulings"] == 1
    if first == "human_review":
        assert out["stage"] == "review" and out["rulings"] == 1


@pytestmark_t5
def test_a_matter_conflict_after_the_judge_goes_to_review_as_today(monkeypatch, tmp_path):
    out, _ = _corrected(monkeypatch, tmp_path, [ACCEPT], conflict=True, boss="reject")
    assert out["boss"] == 1 and out["stage"] == "review", out["path"]


@pytestmark_t5
def test_a_pass_through_arbiter_is_not_a_governor_round(monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT], gov=GovernorSpec())
    assert scope["governor"]["retries"] == 1  # the judge-ordered re-extraction only
    assert "governor_stop" not in scope and out["stage"] == "archived"


@pytestmark_t5
@pytest.mark.parametrize(("rulings", "rulings_n", "extractions"), [
    ([ACCEPT], 1, 0), ([QUOTED], 1, 0), ([REVIEW], 1, 0),
    ([RETRY, ACCEPT], 2, 1), ([RETRY, REVIEW], 2, 1), ([RETRY, RETRY], 2, 1),
])
def test_call_counts_per_path_match_the_design(rulings, rulings_n, extractions, monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, rulings)
    assert out["rulings"] == rulings_n and len(out["retry_schemas"]) == extractions
    assert out["arbiter"] == 0 and out["judge_c"] == out["judge_a"] == 0
    assert scope["llm_calls"] == rulings_n + extractions  # every ruling and re-read reached the call guard


@pytestmark_t5
@pytest.mark.parametrize(("reason", "gov", "preset", "script"), [
    ("retry_budget", {"retries": 0}, {}, {}),
    ("call_budget", {}, {"llm_calls": 99}, {}),
    ("spend_budget", {"spend_usd": 0.01}, {"spend_usd": 1.0}, {}),
    ("boss_repeat", {}, {"boss": 1}, {"conflict": True}),
])
def test_every_governor_outcome_is_reached_with_the_correcting_judge(reason, gov, preset, script, monkeypatch,
                                                                     tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT], gov=GovernorSpec(**gov), preset=preset,
                            **script)
    assert scope["governor_stop"]["reason"] == reason, scope.get("governor_stop")
    assert scope["governor_stop"]["outcome"] == "human_review" and out["stage"] == "review"
    assert not scope["refused"]  # the hard ceiling never had to stop the document


def test_a_stopped_round_after_an_accept_archives_with_caveats():
    # An accepted extraction proposes no further round in correct mode (the only one left is a boss
    # entry, never archived), so the archive outcome is pinned where a round can still follow an accept.
    _correct_on()
    governor.activate(GovernorSpec(retries=0))
    passed = {"judge_verdict": "complete", "extraction_confidence": 0.95, "conflict_detected": False,
              "extraction_attempt_history": [{"judge_verdict": "complete"}]}
    with call_guard.document() as scope:
        dest = governor.govern("arbiter", passed, "retry_extract", {"compile_report", "retry_extract", "human_review"})
    governor.activate(None)
    assert dest == "compile_report" and scope["governor_stop"]["outcome"] == "archive_with_caveats"


@pytestmark_t5
def test_rulings_and_retries_count_toward_the_governor_budgets(monkeypatch, tmp_path):
    out, scope = _corrected(monkeypatch, tmp_path, [RETRY, ACCEPT], gov=GovernorSpec())
    assert scope["llm_calls"] == 3  # ruling, re-read, ruling
    assert scope["governor"]["retries"] == 1  # the judge-ordered retry is a round


def test_hf026_and_hf027_are_registered_with_pinned_sources():
    import graph.build_graph as bg
    import graph.routing as routing
    from graph import route_spec

    from mailroom_sandbox import vendor_hotfixes as vh

    for fid, attr in (("HF-026", "arbiter_node"), ("HF-027", "retry_extract_node")):
        fix = next(f for f in vh.HOTFIXES if f.id == fid)
        assert [f.id for f in vh.HOTFIXES].count(fid) == 1
        assert (fix.module, fix.attr) == ("graph.build_graph", attr)
        assert fix.source_sha256 == vh._source_sha(getattr(bg, attr))
    also = dict(next(f for f in vh.HOTFIXES if f.id == "HF-027").also)
    assert also["_enrich_contract_result"] == vh._source_sha(bg._enrich_contract_result)
    assert also["graph.routing:after_retry_extraction_gated"] == vh._source_sha(routing.after_retry_extraction_gated)
    status = vh.apply_hotfixes()
    assert status["HF-026"] == status["HF-027"] == "applied"
    enrich = bg._enrich_contract_result
    vh.apply_hotfixes()  # idempotent: no second merge layer, one route rule
    assert bg._enrich_contract_result is enrich
    assert [r.name for r in route_spec.route_rules("retry_extract")].count(vh.JUDGE_RETRY_RULE) == 1


@pytest.mark.usefixtures("arbiter_harness_state")
def test_verify_mode_keeps_the_vendored_arbiter_and_retry(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    cj.activate({"mode": "verify"}, pool_sha256=None)
    with call_guard.document() as scope:
        out = run(bg, monkeypatch, Script(judge=[("partial", "accurate"), ("complete", "accurate")],
                                          arbiter=["retry_extraction"], confs=[0.88, 0.88]))
    assert out["arbiter"] == 1 and out["judge_c"] == 2 and len(scope["judge_rulings"]) == 2


# --- Task 7: reports ------------------------------------------------------------------------------

from mailroom_sandbox.job import gate  # noqa: E402
from mailroom_sandbox.job.gate import Bars  # noqa: E402

_LABELS = {"entity_name": "Acme Corp", "record_type": "bylaws"}


def _ruling(pass_no, ruling, fixes=()):
    return {"pass": pass_no, "mode": "correct", "ruling": ruling, "score": 0.9, "reason": "r", "fixes": list(fixes),
            "retry_fields": ["entity_name"] if ruling == "retry_fields" else [], "wrong_fields": [], "model": QWEN}


def _fixcheck(field, value, verified=True, why="ok"):
    return {"field": field, "value": value, "quote": "q", "verified": verified, "why": why}


def _gate_run(root, name, docs):
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": "corporate_record",
                                 "expected_fields": json.dumps(_LABELS)}) + "\n")
            pred = {"stage": d.get("stage", "archived"), "doc_type": "corporate_record", "review_causes": [],
                    "extraction_confidence": 1.0, "extracted_data": {"_s": d.get("score", 0.95)},
                    **({"judge_rulings": d["rulings"], "before_judge": {"_s": d.get("before", 0.8)}}
                       if "rulings" in d else {}),
                    **({"judge_corrected": True} if d.get("corrected") else {}),
                    **({"judge_conflict": True} if d.get("conflict") else {}),
                    **({"governor_stop": d["stop"]} if d.get("stop") else {})}
            usage = {"judge": {"calls": d.get("judge_calls", 1), "prompt_tokens": 10, "completion_tokens": 5,
                               "models": [QWEN]},
                     "arbiter": {"calls": d.get("arbiter_calls", 0), "prompt_tokens": 0, "completion_tokens": 0,
                                 "models": []}}
            it.write(json.dumps({"item_id": d["id"], "ok": not d.get("crash"), "error": "boom" if d.get("crash") else None,
                                 "prompt_tokens": 10, "completion_tokens": 5, "llm_calls": d.get("calls", 3),
                                 "usage_by_agent": usage, "reported_cost_usd": d.get("cost", 0.01),
                                 **({"cached_tokens": d["cached"]} if "cached" in d else {}), "pred": pred}) + "\n")
    return run


@pytest.fixture
def scored(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: (pred.get("extracted_data") or {}).get("_s"))


def test_the_gate_reports_rulings_fixes_and_scores_before_and_after(tmp_path, scored):
    run = _gate_run(tmp_path, "judged", [
        {"id": "a", "rulings": [_ruling(1, "accept", [_fixcheck("entity_name", "Acme Corp"),
                                                       _fixcheck("record_type", "x", False, "unsupported")])],
         "corrected": True, "score": 0.95, "before": 0.85, "cached": 100},
        {"id": "b", "rulings": [_ruling(1, "retry_fields"), _ruling(2, "human_review")], "stage": "review",
         "calls": 5, "conflict": True, "stop": {"reason": "retry_budget", "outcome": "human_review"}},
        {"id": "c"},  # not judged
    ])
    block = gate.gate_report(run, Bars(), audit=False)["judge"]
    assert block["docs_judged"] == 2 and block["docs"] == ["a", "b"]
    assert block["rulings"] == {"accept": {"1": 1}, "retry_fields": {"1": 1}, "human_review": {"2": 1}}
    assert block["fixes"]["proposed"] == 2 and block["fixes"]["verified"] == 1
    assert block["fixes"]["rejected"] == {"unsupported": 1}
    assert block["judge_corrected"] == 1 and block["retries"] == 1
    assert block["score_before"] == pytest.approx(0.825) and block["score_after"] == pytest.approx(0.95)
    assert block["scores_label"] == "after judge" and block["scored_n"] == 2
    assert block["calls_per_judged_doc"] == pytest.approx(4.0)
    assert block["judge_related_calls_per_judged_doc"] == pytest.approx(1.5)  # judge 1 each, plus b's retry
    assert block["cost_per_judged_doc"] == {"corporate_record": pytest.approx(0.01)}
    assert block["cached_prompt_tokens"] == 100
    assert block["review_rate"] == pytest.approx(0.5) and block["crashes"] == 0
    assert block["matter_conflicts"] == 1 and block["governor_stops"] == {"retry_budget": 1}


def test_runs_without_a_judge_section_report_no_judge_block(tmp_path, scored):
    run = _gate_run(tmp_path, "plain", [{"id": "a"}, {"id": "b"}])
    assert "judge" not in gate.gate_report(run, Bars(), audit=False)


def test_fix_accuracy_scores_verified_fixes_against_the_truth(tmp_path, scored):
    run = _gate_run(tmp_path, "fixes", [
        {"id": "a", "rulings": [_ruling(1, "accept", [_fixcheck("entity_name", "Acme Corp"),
                                                       _fixcheck("record_type", "minutes")])]}])
    fixes = gate.gate_report(run, Bars(), audit=False)["judge"]["fixes"]
    assert (fixes["right"], fixes["wrong"]) == (1, 1)


def test_only_fixes_an_accept_applied_are_counted_as_applied_and_scored(tmp_path, scored):
    """Review finding: a verified fix on a retry or review ruling was never written to the extraction."""
    run = _gate_run(tmp_path, "applied", [
        {"id": "a", "rulings": [_ruling(1, "retry_fields", [_fixcheck("record_type", "minutes")]),
                                _ruling(2, "accept", [_fixcheck("entity_name", "Acme Corp")])]},
        {"id": "b", "rulings": [_ruling(1, "human_review", [_fixcheck("entity_name", "Wrong Co")])], "stage": "review"}])
    fixes = gate.gate_report(run, Bars(), audit=False)["judge"]["fixes"]
    assert fixes["verified"] == 3 and fixes["applied"] == 1
    assert (fixes["right"], fixes["wrong"]) == (1, 0)  # only the applied fix is scored against the truth


def test_the_routing_audit_reports_the_judge_section(tmp_path):
    from mailroom_sandbox.job import routing_audit

    run = _gate_run(tmp_path, "audited", [
        {"id": "a", "rulings": [_ruling(1, "accept")]},
        {"id": "b", "rulings": [_ruling(1, "retry_fields"), _ruling(2, "accept")]}, {"id": "c"}])
    lock = {"run_id": "audited", "judge": {"mode": "correct", "model": QWEN,
                                           "models_by_class": {"merger_agreement": FLASH}, "references": "off"}}
    (run / "spec.lock.json").write_text(json.dumps(lock))
    block = routing_audit.audit(run)["judge"]
    assert block["mode"] == "correct" and block["models"] == {"default": QWEN, "merger_agreement": FLASH}
    assert block["classes"]["corporate_record"] == {"judged": 2, "rulings_per_judged_doc": 1.5, "retries": 1}
    (run / "spec.lock.json").write_text(json.dumps({"run_id": "audited"}))
    assert "judge" not in routing_audit.audit(run)


@pytest.mark.usefixtures("arbiter_harness_state")
def test_a_judged_matter_conflict_is_recorded(monkeypatch, tmp_path):
    bg = activate_profile(monkeypatch, tmp_path, "openrouter")
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    _fake_judge(monkeypatch, [_reply()])
    _correct_on()
    with call_guard.document() as scope:
        bg.judge_verify_node(_state(conflict_detected=True, conflict_details=["governing_law"]))
    assert scope["judge_conflict"] is True


# --- Task 8: models, pins and the stage configs --------------------------------------------------

from pathlib import Path  # noqa: E402

STAGES = {
    "p4-s1-verify-gov-off": ("dev-look1", "verify", False), "p4-s1-verify-gov-on": ("dev-look1", "verify", True),
    "p4-s1-correct-refs": ("dev-look1", "train_pool", True), "p4-s1-correct-norefs": ("dev-look1", "off", True),
    "p4-s2-verify": ("dev", "verify", True), "p4-s2-correct-refs": ("dev", "train_pool", True),
}
PIPELINE_CAP_PER_DOC = 0.02
RULING_COST = {"merger_agreement": 0.17}
RULING_COST_DEFAULT = 0.03


def _stage(name):
    from mailroom_sandbox.job.spec import load_run_spec

    return load_run_spec(Path("config/runs") / f"{name}.yaml")


def test_both_judge_models_are_priced_and_pinned():
    from mailroom_sandbox import provider_pins
    from mailroom_sandbox.job.metrics import token_price

    pins = provider_pins.load_pins()
    for model in (QWEN, FLASH):
        assert token_price(model) is not None, model
        assert pins[model]["order"] and pins[model]["allow_fallbacks"] is False, model
    assert pins[QWEN]["order"] == ["alibaba"]


@pytest.mark.parametrize("name", sorted(STAGES))
def test_every_stage_config_preflights_offline(name, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-offline-check")
    split, refs, gov = STAGES[name]
    spec = _stage(name)
    assert spec.run_id == name and spec.task == "pipeline" and spec.job.max_wall_seconds
    assert spec.dataset.exclude_ids_file == f"config/splits/runbook-v2/{split}.exclude.ids"
    assert (spec.job.governor is not None) is gov
    for cls in ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement"):
        limits = spec.confidence["by_class"][cls]
        assert (limits["judge_max_passes"], limits["arbiter_retry_max"]) == (2, 1), cls
    assert preflight._engine_errors(spec) == []  # routes, reviewer, judge models, pins, prices (no network)
    assert not api_budget.unpriced(api_budget.spec_api_models(spec))
    if refs == "verify":
        assert spec.judge.mode == "verify"
    else:
        assert spec.judge.mode == "correct" and spec.judge.references == refs
    if refs == "train_pool":
        ids = [line.strip() for line in Path(f"config/splits/runbook-v2/{split}.ids").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
        from mailroom_sandbox import judge_references as jr

        components = jr.assigned_components()
        assert cj.reference_set_errors(spec, ids) == []
        assert jr.pool_leaks(jr.load_pool(spec.judge.reference_pool), {i: components.get(i, i) for i in ids}) == []


@pytest.mark.parametrize("name", sorted(STAGES))
def test_stage_caps_cover_two_rulings_per_document(name):
    spec = _stage(name)
    buckets = {b["doc_class"]: int(b["count"]) for b in spec.dataset.strata["buckets"]}
    docs = sum(buckets.values())
    assert spec.dataset.limit in (None, docs)
    assert docs == (300 if STAGES[name][0] == "dev-look1" else 900)
    judge = 0.0 if spec.judge.mode == "verify" else sum(
        n * 2 * RULING_COST.get(cls, RULING_COST_DEFAULT) for cls, n in buckets.items())
    assert spec.job.api_cost_cap_usd == pytest.approx(round(1.5 * (docs * PIPELINE_CAP_PER_DOC + judge), 2))


def test_a_yaml_off_reads_as_references_off():
    # YAML 1.1 reads a bare ``references: off`` as False; the section means "off".
    assert JudgeSpec.model_validate({"mode": "correct", "references": False}).references == "off"
    with pytest.raises(ValidationError):
        JudgeSpec.model_validate({"mode": "correct", "references": True})
