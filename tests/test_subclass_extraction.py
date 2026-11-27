"""job.subclass_schemas (phase 3, X1): the predicted subclass picks the extraction schema."""

from __future__ import annotations

import copy

import pytest

from mailroom_sandbox import runtime
from mailroom_sandbox import subclass_extraction as sx
from mailroom_sandbox import subclass_fields as sf


@pytest.fixture(scope="module")
def schemas():
    runtime.activate(load_env_file=False)
    from langchain_agents import specialist_agents as sa

    return sa.SPECIALIST_SCHEMAS


@pytest.fixture(scope="module")
def lists():
    return sf.load_field_lists()


def _choose(schemas, lists, cls, sub, confidence=0.99, *, low=0.5, guide=False):
    return sx.choose_schema(cls, sub, confidence, schemas[cls], lists, low=low, guide=guide)


def test_a_listed_subclass_gets_its_narrowed_schema(schemas, lists):
    base = schemas["corporate_record"]
    before = copy.deepcopy(base)
    schema, reason = _choose(schemas, lists, "corporate_record", "subsidiary_list")
    assert reason == "subclass"
    assert "filing_number" not in schema["properties"]
    assert "filing_number" not in schema["required"]
    assert base == before and "filing_number" in base["properties"]


def test_each_listed_subclass_schema_matches_the_committed_list(schemas, lists):
    for cls, subs in lists["classes"].items():
        base = set(schemas[cls]["properties"])
        for sub, entry in subs.items():
            if sub in sx.FALLBACK_SUBCLASSES:
                continue
            schema, reason = _choose(schemas, lists, cls, sub)
            assert reason == "subclass", (cls, sub)
            assert set(schema["properties"]) == (base - set(entry["drop"])) | set(entry["add"]), (cls, sub)


@pytest.mark.parametrize("sub", [None, "", "unknown", "other", "not_a_subclass"])
def test_an_unknown_or_other_subclass_gets_the_class_schema(schemas, lists, sub):
    schema, reason = _choose(schemas, lists, "corporate_record", sub)
    assert schema is schemas["corporate_record"]
    assert reason == "fallback:unknown"


@pytest.mark.parametrize(
    ("confidence", "reason"),
    [(0.59, "fallback:low_confidence"), (None, "fallback:low_confidence"), (0.6, "subclass")],
)
def test_a_low_or_missing_confidence_falls_back(schemas, lists, confidence, reason):
    schema, got = _choose(schemas, lists, "merger_agreement", "all_cash", confidence, low=0.6)
    assert got == reason
    assert (schema is schemas["merger_agreement"]) == (reason != "subclass")


def test_an_added_field_is_requested(schemas, lists):
    synthetic = copy.deepcopy(lists)
    synthetic["classes"]["corporate_record"]["bylaws"]["add"] = {"certifying_officer": {"type": "name"}}
    schema, _ = _choose(schemas, synthetic, "corporate_record", "bylaws")
    assert schema["properties"]["certifying_officer"] == {"type": ["string", "null"]}
    assert "certifying_officer" in schema["required"]
    list_lists = copy.deepcopy(lists)
    list_lists["classes"]["corporate_record"]["bylaws"]["add"] = {"amendments": {"type": "date_list"}}
    schema, _ = _choose(schemas, list_lists, "corporate_record", "bylaws")
    assert schema["properties"]["amendments"] == {"type": ["array", "null"], "items": {"type": "string"}}


def test_guide_text_replaces_descriptions_only_with_schema_guide(schemas, lists):
    entry = lists["classes"]["corporate_record"]["bylaws"]
    field, text = next(iter(entry["guide"].items()))
    plain, _ = _choose(schemas, lists, "corporate_record", "bylaws", guide=False)
    guided, _ = _choose(schemas, lists, "corporate_record", "bylaws", guide=True)
    assert plain["properties"][field].get("description") == schemas["corporate_record"]["properties"][field].get(
        "description"
    )
    assert guided["properties"][field]["description"] == text


def test_low_band_reads_the_class_threshold():
    runtime.activate(load_env_file=False)
    from pipeline.config import get_confidence_thresholds

    assert sx.low_band("merger_agreement") == get_confidence_thresholds("merger_agreement").get("low")


# --- Task 3: the switch, the lock and HF-020 -------------------------------------------------

from pydantic import ValidationError  # noqa: E402

from mailroom_sandbox import vendor_hotfixes as vh  # noqa: E402
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, spec_core, spec_hash  # noqa: E402

_EXTRACTORS = {
    "contract": ("_extract_contracts", "license"),
    "merger_agreement": ("_extract_merger_agreement", "all_cash"),
    "corporate_record": ("_extract_corporate_records", "subsidiary_list"),
    "correspondence": ("_extract_correspondence", "email"),
    "insurance_claim": ("_extract_insurance_claims", "auto"),
}


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-sub", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


@pytest.fixture
def switch_off():
    sx.deactivate()
    yield
    sx.deactivate()


def test_subclass_schemas_is_off_by_default_and_unhashed():
    core = spec_core(_spec(), source_sha256="0" * 64)["job"]
    assert not any(key.startswith("subclass_") for key in core)
    assert spec_hash(_spec()) == spec_hash(_spec(subclass_schemas=False))
    on = spec_core(_spec(subclass_schemas=True), source_sha256="0" * 64)["job"]
    assert on["subclass_schemas"] is True and on["subclass_fields_sha256"] == sf.field_lists_sha256()


def test_subclass_schemas_requires_a_pipeline_task():
    with pytest.raises(ValidationError, match="subclass_schemas"):
        _spec(task="correspondence_specialist", subclass_schemas=True)


def test_the_lock_changes_when_the_field_list_changes(tmp_path, monkeypatch):
    before = spec_hash(_spec(subclass_schemas=True))
    changed = sf.load_field_lists()
    changed["classes"]["contract"]["license"]["drop"] = ["territory"]
    path = tmp_path / "fields.json"
    path.write_text(sf.render(changed), encoding="utf-8")
    monkeypatch.setattr(sf, "FIELDS_PATH", path)
    assert spec_hash(_spec(subclass_schemas=True)) != before


def test_a_field_list_changed_after_the_lock_refuses_to_activate(switch_off):
    with pytest.raises(RuntimeError, match="field list"):
        sx.activate(sf.load_field_lists(), sha256="0" * 64, guide=False)
    assert not sx.active()


def test_the_lock_activates_subclass_schemas(monkeypatch, switch_off):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    lock = {"profile": "modal-vllm", "job": {"subclass_schemas": True},
            "spec_core": {"job": {"subclass_fields_sha256": sf.field_lists_sha256()}}}
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert sx.active()
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):  # a lock from before phase 3
        runtime.activate("modal-vllm", load_env_file=False)
    assert not sx.active()


@pytest.fixture
def captured(monkeypatch, schemas):
    """Apply HF-020 and record the json_schema every specialist structured call is sent."""
    from agents import base as agents_base
    from langchain_agents import base_agent as lc_base

    assert vh.apply_hotfixes()["HF-020"] == "applied"
    calls: list[tuple[str, dict]] = []

    def stub(self, user_message, json_schema, *args, **kwargs):
        calls.append((type(self).__name__, json_schema))
        return {"confidence": 0.9}

    monkeypatch.setattr(agents_base.BaseAgent, "_call_structured", stub)
    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", stub)
    return calls


def _state(cls, sub, confidence=0.99):
    key = "contract_subtype" if cls == "contract" else "doc_subclass"
    return {"doc_id": "d1", "doc_type": cls, key: sub, "classification_confidence": confidence}


def _extract(cls, sub, text="A short document body for extraction.", confidence=0.99):
    import graph.build_graph as bg

    name, _ = _EXTRACTORS[cls]
    handoff = bg._build_handoff_context(_state(cls, sub, confidence))
    return getattr(bg, name)(text, [], handoff)


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_an_extraction_requests_the_subclass_schema(cls, captured, schemas, lists, switch_off):
    sub = _EXTRACTORS[cls][1]
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract(cls, sub)
    assert captured, cls
    expected, reason = sx.choose_schema(cls, sub, 0.99, schemas[cls], lists, low=sx.low_band(cls), guide=False)
    assert reason == "subclass"
    for _, sent in captured:
        assert sent is not schemas[cls]
        assert sent == expected
        assert not set(lists["classes"][cls][sub]["drop"]) & set(sent["properties"])


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_off_sends_the_class_schema_unchanged(cls, captured, schemas, switch_off):
    _extract(cls, _EXTRACTORS[cls][1])
    assert captured and all(sent is schemas[cls] for _, sent in captured)


def test_a_low_confidence_extraction_sends_the_class_schema(captured, schemas, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("merger_agreement", "all_cash", confidence=0.01)
    assert captured and all(sent is schemas["merger_agreement"] for _, sent in captured)


def test_every_chunk_gets_the_narrowed_schema(captured, schemas, lists, switch_off, monkeypatch):
    import graph.build_graph as bg

    monkeypatch.setattr(bg, "_chunk_config", lambda: {"enabled": True, "chunk_chars": 1_000, "overlap_chars": 100})
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    result = _extract("merger_agreement", "all_cash", text="Section text. " * 400)
    assert len(captured) > 1
    assert all("intent" not in sent["properties"] and sent is not schemas["merger_agreement"] for _, sent in captured)
    assert isinstance(result, dict)


def test_the_narrowed_schema_ends_with_its_extraction(captured, schemas, lists, switch_off):
    from agents.corporate_records_specialist import CorporateRecordsSpecialist

    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("corporate_record", "subsidiary_list")
    captured.clear()
    agent = CorporateRecordsSpecialist()  # a later caller (the judge, the next document) builds its own agent
    agent._call_structured("again", json_schema=schemas["corporate_record"])
    assert captured[0][1] is schemas["corporate_record"]


# --- Task 4: scoring guards -------------------------------------------------------------------

_KEPT = {"merger_agreement": "document_name", "corporate_record": "entity_name", "contract": "document_name",
         "correspondence": "sender", "insurance_claim": "claim_number"}


def _score(cls, sub, predicted, expected):
    from mailroom_sandbox.eval.scoring import score_extraction_row

    out = score_extraction_row(cls, dict(predicted), dict(expected), doc_subclass=sub, field_scores=True)
    return out["overall_extraction_score"], out.get("field_scores")


def _drops(lists):
    return [(cls, sub, f) for cls, subs in lists["classes"].items() for sub, e in subs.items() for f in e["drop"]]


def test_a_dropped_field_never_changes_a_score(lists):
    runtime.activate(load_env_file=False)
    drops = _drops(lists)
    assert drops
    for cls, sub, field in drops:
        kept = _KEPT[cls]
        # The truth every dropped field carries: blank, marked not applicable (Hub gt_presence).
        expected = {kept: "Acme Holdings Inc.", field: "", "gt_presence": {field: "not_applicable"}}
        asked = _score(cls, sub, {kept: "Acme Holdings Inc.", field: None}, expected)
        dropped = _score(cls, sub, {kept: "Acme Holdings Inc."}, expected)
        assert dropped == asked, (cls, sub, field)
        stated = _score(cls, sub, {kept: "Acme Holdings Inc.", field: "a stated value"}, expected)
        assert dropped[0] >= stated[0], (cls, sub, field)  # dropping can only remove a false positive


def test_every_added_field_is_scoreable(lists):
    from mailroom_sandbox.eval.extraction_scope import applicable_expected_fields

    runtime.activate(load_env_file=False)
    added = [(cls, f) for cls, subs in lists["classes"].items() for e in subs.values() for f in e["add"]]
    added.append(("corporate_record", "certifying_officer"))  # the synthetic extension of Task 1
    for cls, field in added:
        assert field in applicable_expected_fields(cls, {field: "x"}), (cls, field)
