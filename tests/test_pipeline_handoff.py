"""job.pipeline_handoff: an isolated specialist sees the extract node's handoff (llm-mailroom #174)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mailroom_sandbox import runtime
from mailroom_sandbox.eval import agents
from mailroom_sandbox.job.spec import SPECIALIST_TASKS, DatasetSpec, RunSpec, core_hash, load_run_spec, spec_core
from mailroom_sandbox.paths import repo_root

ARMS = ("v3arm-plain", "v3arm", "v4arm")


def _spec(task="insurance_claims_specialist", **job):
    return RunSpec(run_id="r-handoff", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_pipeline_handoff_is_hashed_only_when_set_and_only_for_specialists():
    plain, handed = _spec(), _spec(pipeline_handoff=True)
    assert "pipeline_handoff" not in spec_core(plain, source_sha256="0" * 64)["job"]
    assert spec_core(handed, source_sha256="0" * 64)["job"]["pipeline_handoff"] is True
    assert core_hash(spec_core(plain, source_sha256="0" * 64)) != core_hash(spec_core(handed, source_sha256="0" * 64))
    assert _spec(task="specialist", pipeline_handoff=True).job.pipeline_handoff is True
    for task in ("pipeline", "sorter"):
        with pytest.raises(ValidationError, match="pipeline_handoff"):
            _spec(task=task, pipeline_handoff=True)


def test_specialist_tasks_name_every_isolated_specialist():
    assert SPECIALIST_TASKS == {"specialist", *agents.SPECIALIST_CLASS}


def test_only_a_locked_handoff_run_activates_the_pipeline_handoff(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    try:
        with runtime.locked_runtime({"profile": "modal-vllm", "job": {"pipeline_handoff": True}}, {}):
            runtime.activate("modal-vllm", load_env_file=False)
        assert runtime.pipeline_handoff_active() is True
        runtime.activate("modal-vllm", load_env_file=False)  # an unlocked activation never adds it
        assert runtime.pipeline_handoff_active() is False
    finally:
        runtime.activate("modal-vllm", load_env_file=False)


class _Recorder:
    seen: list = []

    def extract(self, doc_text, pages=None, handoff_context=None):
        _Recorder.seen.append(handoff_context)
        return {"claim_type": "Part D", "insured_party": "A"}


@pytest.mark.parametrize("handed", [False, True])
def test_the_specialist_gets_the_extract_nodes_handoff_and_normalization_only_when_set(monkeypatch, handed):
    pytest.importorskip("graph.build_graph")
    import types

    module = types.ModuleType("fake_insurance_specialist")
    module.Fake = _Recorder
    monkeypatch.setitem(__import__("sys").modules, "fake_insurance_specialist", module)
    monkeypatch.setitem(agents.LIVE_CLASS_MAP, "insurance_claims_specialist", ("fake_insurance_specialist", "Fake"))
    monkeypatch.setattr(runtime, "pipeline_handoff_active", lambda: handed)
    monkeypatch.setattr(runtime, "agent_knobs_for", lambda agent: {})
    _Recorder.seen = []
    out = agents._live_specialist("insurance_claims_specialist", {"id": "d0", "doc_text": "MEDICARE SUMMARY NOTICE"})
    (handoff,) = _Recorder.seen
    if handed:
        assert handoff.startswith("Sorter classification: doc_type=insurance_claim")
        assert "INSURANCE CLAIM INVENTORY" in handoff  # the vendored doc_inventories note
        assert "doc_subclass" not in handoff and "confidence=" not in handoff  # no claimed subclass
        # the node's post-extraction normalization: a CMS table maps to its product line (#280)
        assert out["claim_type"] == "health"
    else:
        assert handoff is None
        assert out["claim_type"] == "Part D"


def _ids(path):
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}


def test_the_insurance_v4_arms_share_one_draw_that_avoids_every_production_slice():
    root = repo_root()
    specs = {arm: load_run_spec(root / f"config/runs/specialist-condensed-v4-insurance-claim-qwen-{arm}.yaml") for arm in ARMS}
    assert len({spec.dataset.model_dump_json() for spec in specs.values()}) == 1
    assert {arm: spec.job.pipeline_handoff for arm, spec in specs.items()} == {"v3arm-plain": False, "v3arm": True, "v4arm": True}
    assert {arm: spec.prompt["agents"]["insurance_claims_specialist"]["file"] for arm, spec in specs.items()} == {
        "v3arm-plain": "insurance_claims_specialist_condensed_v3", "v3arm": "insurance_claims_specialist_condensed_v3",
        "v4arm": "insurance_claims_specialist_condensed_v4"}
    dataset = specs["v4arm"].dataset
    assert dataset.draw == "ranked" and dataset.exclude_ids_file == "config/production/excluded-ids-insurance-v4-ab.txt"
    # The arm list holds every tuning document plus the slice-500 draw (checked offline; CI has no Hub access).
    arm_list = _ids(root / dataset.exclude_ids_file)
    tuning = _ids(root / "config/production/excluded-ids.txt")
    # The arm list is frozen; excluded-ids.txt has since gained the A/B's own 40 documents, which the
    # arm list cannot hold (the arms drew them). Everything else in it was frozen into the arm list.
    ab_draw = tuning - arm_list
    assert len(ab_draw) == 40
    assert len(arm_list) == len(tuning - ab_draw) + 500  # a slice never draws a tuning document


def test_the_insurance_v5_arms_reuse_the_v4_draw():
    root = repo_root()
    v4 = load_run_spec(root / "config/runs/specialist-condensed-v4-insurance-claim-qwen-v4arm.yaml")
    specs = {arm: load_run_spec(root / f"config/runs/specialist-condensed-v5-insurance-claim-qwen-{arm}.yaml")
             for arm in ("v4arm", "v5arm")}
    for spec in specs.values():
        assert spec.dataset.model_dump_json() == v4.dataset.model_dump_json()
        assert spec.job.pipeline_handoff is True
    assert {arm: spec.prompt["agents"]["insurance_claims_specialist"]["file"] for arm, spec in specs.items()} == {
        "v4arm": "insurance_claims_specialist_condensed_v4", "v5arm": "insurance_claims_specialist_condensed_v5"}
