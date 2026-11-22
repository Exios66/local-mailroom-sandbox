"""Pins the live confidence source for each specialist class.

Production slices pin condensed stems that ask for an evidence share, and every
live extraction schema has a ``confidence`` number. The frozen corporate
simplified stem still says confidence is unregistered; it is not the production
pin and this test does not rewrite it.
"""
from __future__ import annotations

import yaml

from mailroom_sandbox import vendor_hotfixes as vh
from mailroom_sandbox.paths import repo_root

_EVIDENCE = "confidence = share of fields found"
_FROZEN = "corporate_records_specialist_simplified.txt"
_PRODUCTION_PINS = {
    "corporate_records_specialist": "corporate_records_specialist_condensed_v1",
    "correspondence_specialist": "correspondence_specialist_condensed_v3",
    "insurance_claims_specialist": "insurance_claims_specialist_condensed_v3",
}
_BASE_SPECIALISTS = (
    "ContractsSpecialist",
    "CorporateRecordsSpecialist",
    "CorrespondenceSpecialist",
    "MergerAgreementSpecialist",
)


def test_every_live_schema_registers_confidence():
    from langchain_agents.specialist_agents import SPECIALIST_SCHEMAS

    assert set(SPECIALIST_SCHEMAS) == {
        "contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim",
    }
    for doc_type, schema in SPECIALIST_SCHEMAS.items():
        field = schema["properties"]["confidence"]
        assert field["type"] == "number", doc_type
        assert field["minimum"] == 0.0 and field["maximum"] == 1.0


def test_production_pins_request_an_evidence_share_and_the_frozen_stem_stays_frozen():
    root = repo_root()
    spec = yaml.safe_load((root / "config/runs/production/slice-0100.yaml").read_text())
    agents = spec["prompt"]["agents"]
    assert {name: pin["file"] for name, pin in agents.items()} == _PRODUCTION_PINS
    prompts = root / "config/prompts"
    for stem in _PRODUCTION_PINS.values():
        text = (prompts / f"{stem}.txt").read_text()
        assert _EVIDENCE in text
        assert "not a registered field" not in text
    frozen = (prompts / _FROZEN).read_text()
    assert "confidence is not a registered field" in frozen
    assert all(pin["file"] != _FROZEN.removesuffix(".txt") for pin in agents.values())


def test_a_stated_zero_stays_zero_on_every_live_specialist(monkeypatch):
    from langchain_agents import specialist_agents as sa

    vh.apply_hotfixes()
    for class_name in _BASE_SPECIALISTS:
        agent = object.__new__(getattr(sa, class_name))
        monkeypatch.setattr(agent, "truncate_input", lambda text: text)
        monkeypatch.setattr(agent, "_call_structured", lambda *a, **kw: {"confidence": 0.0, "entity_name": "Kept"})
        monkeypatch.setattr(agent, "_evidence_confidence", lambda result: 0.9)
        stated = agent.extract("source")
        assert stated["confidence"] == 0.0
        monkeypatch.setattr(agent, "_call_structured", lambda *a, **kw: {"entity_name": "Kept"})
        missing = agent.extract("source")
        assert missing["confidence"] == 0.9

    kept = sa.normalize_extraction({"confidence": 0.0, "claim_number": "A"}, sa.INSURANCE_CLAIMS_SCHEMA)
    missing = sa.normalize_extraction({"claim_number": "A"}, sa.INSURANCE_CLAIMS_SCHEMA)
    assert kept["confidence"] == 0.0
    assert missing["confidence"] == 0.0


def test_window_rules_keep_a_low_populated_window_that_max_would_hide():
    from mailroom_sandbox.job.routing_audit import compare_window_rules

    compared = compare_window_rules([(0.99, 100), (0.2, 4000)])
    assert compared["adopted"] == "min"
    assert compared["min"] == 0.2
    assert compared["max"] == 0.99
    assert compared["length_weighted"] != compared["max"]
