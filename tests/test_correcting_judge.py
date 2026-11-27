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
