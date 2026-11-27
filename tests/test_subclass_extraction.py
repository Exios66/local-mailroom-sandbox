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
