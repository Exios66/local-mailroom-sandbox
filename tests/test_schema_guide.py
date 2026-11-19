"""job.schema_guide: specialist schema descriptions follow the labeling guide only when set."""
from __future__ import annotations

import pytest

from mailroom_sandbox import runtime, schema_guide
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, spec_core
from mailroom_sandbox.subclass_schemas import parse_guide


@pytest.fixture
def schemas():
    runtime.activate(load_env_file=False)
    from langchain_agents import specialist_agents as sa

    yield sa.SPECIALIST_SCHEMAS
    schema_guide.apply_schema_guide(False)


def _desc(schemas, cls, field):
    return schemas[cls]["properties"][field]["description"]


def test_apply_then_restore_round_trips_the_vendored_text(schemas):
    schema_guide.apply_schema_guide(False)
    before = {c: {f: _desc(schemas, c, f) for f in fs} for c, fs in schema_guide.GUIDE_DESCRIPTIONS.items()}
    differs = sum(before[c][f] != t for c, fs in schema_guide.GUIDE_DESCRIPTIONS.items() for f, t in fs.items())
    assert schema_guide.apply_schema_guide(True) == differs > 0
    assert schema_guide.schema_guide_active()
    assert "licensor" in _desc(schemas, "contract", "party_roles")
    assert "generic salutation" in _desc(schemas, "correspondence", "recipient")
    assert schema_guide.apply_schema_guide(True) == 0  # idempotent
    schema_guide.apply_schema_guide(False)
    assert not schema_guide.schema_guide_active()
    after = {c: {f: _desc(schemas, c, f) for f in fs} for c, fs in schema_guide.GUIDE_DESCRIPTIONS.items()}
    assert after == before


def test_only_descriptions_change(schemas):
    schema_guide.apply_schema_guide(False)
    import copy

    snap = copy.deepcopy({c: schemas[c] for c in schema_guide.GUIDE_DESCRIPTIONS})
    schema_guide.apply_schema_guide(True)
    for cls, fields in schema_guide.GUIDE_DESCRIPTIONS.items():
        for name, prop in schemas[cls]["properties"].items():
            want = {k: v for k, v in snap[cls]["properties"][name].items() if k != "description"}
            assert {k: v for k, v in prop.items() if k != "description"} == want
        assert schemas[cls].get("required") == snap[cls].get("required")
        untouched = set(schemas[cls]["properties"]) - set(fields)
        for name in untouched:
            assert schemas[cls]["properties"][name] == snap[cls]["properties"][name]


def test_missing_vendored_field_fails_loudly(schemas):
    original = schema_guide.GUIDE_DESCRIPTIONS["contract"]
    schema_guide.GUIDE_DESCRIPTIONS["contract"] = {**original, "not_a_field": "x"}
    try:
        with pytest.raises(KeyError, match="not_a_field"):
            schema_guide.apply_schema_guide(True)
    finally:
        schema_guide.GUIDE_DESCRIPTIONS["contract"] = original


def test_every_guided_field_is_a_guide_convention():
    guide = parse_guide()
    for cls, fields in schema_guide.GUIDE_DESCRIPTIONS.items():
        assert set(fields) <= set(guide[cls]), cls


def _spec(**job):
    return RunSpec(run_id="r-guide", task="correspondence_specialist", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


def test_schema_guide_is_hashed_only_when_set():
    assert "schema_guide" not in spec_core(_spec(), source_sha256="0" * 64)["job"]
    assert spec_core(_spec(schema_guide=True), source_sha256="0" * 64)["job"]["schema_guide"] is True


def test_activation_restores_the_vendored_text(schemas, monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {"schema_guide": True}}, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert schema_guide.schema_guide_active()
    assert "licensor" in _desc(schemas, "contract", "party_roles")
    runtime.activate("modal-vllm", load_env_file=False)  # an unlocked activation restores the vendored text
    assert not schema_guide.schema_guide_active()
    assert "licensor" not in _desc(schemas, "contract", "party_roles")
