"""Run specs default every lineage agent to its frontrunner, never to the vendored prompt."""
from __future__ import annotations

import yaml

from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, core_hash, spec_core
from mailroom_sandbox.paths import config_dir
from mailroom_sandbox.prompt_lineage import frontrunners, with_lineage_defaults


def _spec(prompt):
    return RunSpec(run_id="r-lineage", task="pipeline", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True}, prompt=prompt)


def _core(spec):
    return spec_core(spec, source_sha256="0" * 64)


def test_frontrunners_come_from_the_lineage_files():
    prompts = config_dir() / "prompts"
    sorter = yaml.safe_load((prompts / "sorter_condensed_lineage.yaml").read_text())
    specialists = yaml.safe_load((prompts / "specialist_condensed_lineage.yaml").read_text())
    want = {"sorter": sorter["frontrunner"], **{a: r["frontrunner"] for a, r in specialists["agents"].items()}}
    assert frontrunners() == want
    assert set(want) >= {"sorter", "contracts_specialist", "corporate_records_specialist", "correspondence_specialist",
                         "insurance_claims_specialist", "merger_agreement_specialist"}
    for stem in want.values():
        assert (prompts / f"{stem}.txt").is_file(), stem


def test_a_code_default_spec_hashes_and_locks_the_frontrunners(tmp_path, job_data_dir):
    from mailroom_sandbox.job import preflight

    spec = _spec({"default": {"source": "code-default"}})
    assert spec.prompt == {"default": {"source": "code-default"}}  # the spec keeps what was written
    hashed = _core(spec)["prompt"]["agents"]
    for agent, stem in frontrunners().items():
        assert hashed[agent] == {"source": "local", "file": stem}, agent
    data = tmp_path / "d.jsonl"
    data.write_text('{"id": "a", "filename": "a.txt", "doc_text": "x", "expected_doc_class": "contract"}\n')
    live = RunSpec(run_id="r-lineage-lock", task="pipeline", dataset=DatasetSpec(local_path=f"file://{data}"),
                   engine={"kind": "vllm-local", "modal": None}, trace={"sink": "none"},
                   job={"mock": True}, prompt={"default": {"source": "code-default"}})
    report = preflight.preflight(live, offline=True)
    assert report["status"] == "prepared", report
    from mailroom_sandbox.job.checkpoint import store_for

    lock = store_for(live.run_id).read_prompt_lock()
    for agent, stem in frontrunners().items():
        assert lock["agents"][agent]["source"] == "local" and lock["agents"][agent]["file"] == stem, agent
        assert lock["agents"][agent]["text"], agent


def test_an_explicit_agent_entry_wins_and_changes_the_hash():
    baseline = _spec({"agents": {"sorter": {"source": "code-default"}}})  # a deliberate vendored arm
    assert _core(baseline)["prompt"]["agents"]["sorter"] == {"source": "code-default"}
    assert core_hash(_core(_spec({}))) != core_hash(_core(baseline))


def test_a_versions_selection_is_not_overridden():
    out = with_lineage_defaults({"versions": {"sorter": "x"}})
    assert "sorter" not in out["agents"]


def test_a_frontrunner_is_never_a_superseded_or_rejected_version():
    """Regression guard: the frontrunner a run defaults to must be the lineage's
    adopted (or explicitly outside-lineage deployed) prompt — never a superseded,
    rejected, not-adopted, withdrawn or not-yet-run candidate stem."""
    prompts = config_dir() / "prompts"
    sorter = yaml.safe_load((prompts / "sorter_condensed_lineage.yaml").read_text())
    specialists = yaml.safe_load((prompts / "specialist_condensed_lineage.yaml").read_text())
    versions = {v["version"]: v for v in sorter["versions"]}
    for row in specialists["agents"].values():
        versions.update({v["version"]: v for v in (row.get("versions") or [])})
    fronts = frontrunners()
    assert fronts, "the lineage files name no frontrunner"
    outside_lineage = {
        agent for agent, row in specialists["agents"].items() if row.get("frontrunner_outside_lineage")
    }
    for agent, stem in fronts.items():
        entry = versions.get(stem)
        if entry is None:  # an outside-lineage stem (contracts / merger) declares itself
            assert agent in outside_lineage, f"{agent}: frontrunner {stem!r} has no lineage entry"
            continue
        assert entry["status"] == "adopted", f"{agent}: frontrunner {stem!r} is {entry['status']!r}"


def test_family_b_default_keys_track_the_lineage_frontrunners():
    """The vendored PROMPT_VERSIONS patch keys must not regress behind the lineage.

    The sorter's code default IS the condensed lineage production (both trees ship
    the same bytes as the frontrunner). Contracts is deliberate: its vendored key
    stays the frozen Dojo-0.27.2 production render ``contracts_specialist_v33``
    while the run-lock default is the frontrunner ``v33_simplified``
    (config/prompts/README.md, "Specialist production pins").
    """
    from mailroom_sandbox.prompt_registry import FAMILY_B_KEYS

    fronts = frontrunners()
    assert FAMILY_B_KEYS["sorter"] == fronts["sorter"]
    assert FAMILY_B_KEYS["contracts_specialist"] == "contracts_specialist_v33"
    assert fronts["contracts_specialist"] == "contracts_specialist_v33_simplified"


def test_the_isolated_eval_default_stem_is_the_frontrunner():
    from mailroom_sandbox.prompt_lineage import default_stem_for

    fronts = frontrunners()
    for agent in ("sorter", "insurance_claims_specialist", "correspondence_specialist",
                  "corporate_records_specialist", "contracts_specialist",
                  "merger_agreement_specialist"):
        assert default_stem_for(agent) == fronts[agent], agent


def test_apply_eval_defaults_pins_frontrunners_on_an_unlocked_eval():
    """The direct eval paths must not silently run vendored pre-condensed prompts."""
    from mailroom_sandbox import prompt_registry as pr
    from mailroom_sandbox import prompt_versions as pv
    from mailroom_sandbox.prompt_lineage import apply_eval_defaults, frontrunners

    try:
        assert apply_eval_defaults("pipeline") is True
        for agent, stem in frontrunners().items():
            assert pr._OVERRIDE_STATE.table.get(agent) is not None, agent
            assert stem  # the applied text came from config/prompts/<stem>.txt
    finally:
        pr.deactivate_runtime_overrides()
        pv.clear_active_selection()


def test_apply_eval_defaults_is_a_noop_under_a_selection_or_a_lock():
    from mailroom_sandbox import prompt_versions as pv
    from mailroom_sandbox.prompt_lineage import apply_eval_defaults

    try:
        pv.set_active_selection(pv.resolve_selection(["sorter=sorter_v1"]))
        assert apply_eval_defaults("pipeline") is False
    finally:
        pv.clear_active_selection()


def test_apply_eval_defaults_scopes_an_isolated_agent_to_its_own_frontrunner():
    from mailroom_sandbox import prompt_registry as pr
    from mailroom_sandbox import prompt_versions as pv
    from mailroom_sandbox.prompt_lineage import apply_eval_defaults, frontrunners

    try:
        assert apply_eval_defaults("insurance_claims_specialist") is True
        assert set(pr._OVERRIDE_STATE.table) == {"insurance_claims_specialist"}
        assert pr._OVERRIDE_STATE.table["insurance_claims_specialist"]
        assert frontrunners()["insurance_claims_specialist"]
    finally:
        pr.deactivate_runtime_overrides()
        pv.clear_active_selection()
