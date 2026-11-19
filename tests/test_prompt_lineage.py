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


def test_a_code_default_spec_hashes_and_locks_the_frontrunners(tmp_path):
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
