"""job.specialist_subclass: which subclass an isolated specialist's pipeline handoff names."""
from __future__ import annotations

import json
import sys
import types

import pytest
from pydantic import ValidationError

from mailroom_sandbox import runtime
from mailroom_sandbox.eval import agents
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, core_hash, spec_core


def _spec(task="insurance_claims_specialist", **job):
    return RunSpec(run_id="r-sub", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_the_setting_needs_the_handoff_a_file_for_sorter_and_no_gold_for_mergers(tmp_path):
    saved = tmp_path / "sorter.jsonl"
    saved.write_text('{"id": "d0", "sorter_doc_subclass": "carrier"}\n')
    with pytest.raises(ValidationError, match="pipeline_handoff"):
        _spec(specialist_subclass="gold")
    with pytest.raises(ValidationError, match="specialist_subclass_file"):
        _spec(pipeline_handoff=True, specialist_subclass="sorter")
    with pytest.raises(ValidationError, match="specialist_subclass_file"):
        _spec(pipeline_handoff=True, specialist_subclass_file=str(saved))
    with pytest.raises(ValidationError, match="merger_consideration"):
        _spec(task="merger_agreement_specialist", pipeline_handoff=True, specialist_subclass="gold")
    assert _spec(pipeline_handoff=True, specialist_subclass="sorter",
                 specialist_subclass_file=str(saved)).job.specialist_subclass == "sorter"


def test_the_setting_is_hashed_only_when_set_and_the_sorter_file_by_content(tmp_path):
    saved = tmp_path / "sorter.jsonl"
    saved.write_text('{"id": "d0", "sorter_doc_subclass": "carrier"}\n')
    core = lambda s: spec_core(s, source_sha256="0" * 64)  # noqa: E731
    plain = core(_spec(pipeline_handoff=True))
    assert "specialist_subclass" not in plain["job"] and "specialist_subclass_file" not in plain["job"]
    gold = core(_spec(pipeline_handoff=True, specialist_subclass="gold"))
    assert gold["job"]["specialist_subclass"] == "gold" and core_hash(gold) != core_hash(plain)
    sorter = _spec(pipeline_handoff=True, specialist_subclass="sorter", specialist_subclass_file=str(saved))
    before = core(sorter)
    saved.write_text('{"id": "d0", "sorter_doc_subclass": "outpatient"}\n')
    assert core_hash(core(sorter)) != core_hash(before)


class _Recorder:
    seen: list = []
    output: dict = {}

    def extract(self, doc_text, pages=None, handoff_context=None):
        _Recorder.seen.append(handoff_context)
        return dict(_Recorder.output)


def _run(monkeypatch, agent, row, mode, path=None, output=None):
    pytest.importorskip("graph.build_graph")
    from mailroom_sandbox.vendor_hotfixes import apply_hotfixes

    apply_hotfixes()
    module = types.ModuleType("fake_specialist")
    module.Fake = _Recorder
    monkeypatch.setitem(sys.modules, "fake_specialist", module)
    monkeypatch.setitem(agents.LIVE_CLASS_MAP, agent, ("fake_specialist", "Fake"))
    monkeypatch.setattr(runtime, "pipeline_handoff_active", lambda: True)
    monkeypatch.setattr(runtime, "specialist_subclass_source", lambda: (mode, path))
    monkeypatch.setattr(runtime, "agent_knobs_for", lambda a: {})
    _Recorder.seen, _Recorder.output = [], dict(output or {})
    out = agents._live_specialist(agent, row)
    return _Recorder.seen[-1], out


def test_none_names_no_subclass_and_an_isolated_cms_row_has_no_table(monkeypatch):
    handoff, out = _run(monkeypatch, "insurance_claims_specialist",
                        {"id": "d0", "doc_text": "x", "expected_subclass": "carrier"}, "none",
                        output={"claim_type": "health"})
    assert "doc_subclass" not in handoff and "cms_source_table" not in out


def test_gold_names_the_expected_subclass_and_derives_the_cms_table(monkeypatch):
    handoff, out = _run(monkeypatch, "insurance_claims_specialist",
                        {"id": "d0", "doc_text": "x", "expected_subclass": "carrier"}, "gold",
                        output={"claim_type": "health"})
    assert "doc_subclass=carrier" in handoff
    assert out["cms_source_table"] == "carrier"


def test_sorter_names_the_saved_pass_subclass_and_refuses_a_missing_row(monkeypatch, tmp_path):
    saved = tmp_path / "sorter.jsonl"
    saved.write_text(json.dumps({"id": "d0", "sorter_doc_subclass": "outpatient"}) + "\n")
    agents._saved_sorter_pass.cache_clear()
    row = {"id": "d0", "doc_text": "x", "expected_subclass": "carrier"}
    handoff, out = _run(monkeypatch, "insurance_claims_specialist", row, "sorter", str(saved),
                        output={"claim_type": "health"})
    assert "doc_subclass=outpatient" in handoff and out["cms_source_table"] == "outpatient"
    with pytest.raises(KeyError, match="no sorter row"):
        _run(monkeypatch, "insurance_claims_specialist", {**row, "id": "d9"}, "sorter", str(saved))


def test_gold_corporate_subclass_fills_record_type_through_the_hotfix(monkeypatch):
    _handoff, out = _run(monkeypatch, "corporate_records_specialist",
                         {"id": "d0", "doc_text": "x", "expected_subclass": "indenture"}, "gold",
                         output={"record_type": None})
    assert out["record_type"] == "other"


def test_gold_contract_subclass_is_the_cuad_family(monkeypatch):
    state = None

    def capture(agent, row):
        nonlocal state
        state = agents.pipeline_specialist_state(agent, row)
        return state

    monkeypatch.setattr(runtime, "specialist_subclass_source", lambda: ("gold", None))
    capture("contracts_specialist", {"id": "d0", "expected_subclass": "license"})
    assert state == {"doc_type": "contract", "contract_subtype": "license"}
    capture("merger_agreement_specialist", {"id": "d0", "expected_subclass": "all_cash"})
    assert state == {"doc_type": "merger_agreement"}
