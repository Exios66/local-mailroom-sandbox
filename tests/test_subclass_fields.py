"""The committed subclass field lists (phase 3, X1): derived from the label registry, never from held-out labels."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from mailroom_sandbox import subclass_fields as sf
from mailroom_sandbox.subclass_schemas import DEFAULT_OUT as REGISTRY_PATH


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _entry(lists: dict, cls: str, sub: str) -> dict:
    return lists["classes"][cls][sub]


def test_not_applicable_class_fields_are_dropped(registry):
    lists = sf.build_field_lists(registry)
    assert _entry(lists, "corporate_record", "subsidiary_list")["drop"] == ["filing_number", "jurisdiction", "signatories"]
    assert _entry(lists, "merger_agreement", "all_cash")["drop"] == ["intent", "keywords", "subject_matter"]
    assert _entry(lists, "contract", "license")["drop"] == []


def test_a_not_applicable_field_with_values_outside_held_out_is_kept(registry):
    # Interim labels give filing_number real values on these subclasses (dev or calibration),
    # so dropping it would turn a labeled hit into a miss.
    lists = sf.build_field_lists(registry)
    for sub in ("board_resolution", "officer_certificate", "powers_of_attorney"):
        assert "filing_number" not in _entry(lists, "corporate_record", sub)["drop"], sub
    assert "filing_number" in _entry(lists, "corporate_record", "bylaws")["drop"]  # its one value is held-out


def _with_valued(registry: dict, by_set: dict[str, int]) -> dict:
    out = copy.deepcopy(registry)
    fe = out["classes"]["merger_agreement"]["subclasses"]["all_stock"]["fields"]["intent"]
    fe["valued_by_set"] = {"dev": 0, "calibration": 0, "pool": 0, "heldout": 0, **by_set}
    return out


def test_a_value_label_in_a_schema_set_keeps_a_not_applicable_field(registry):
    lists = sf.build_field_lists(_with_valued(registry, {"pool": 1}))
    assert "intent" not in _entry(lists, "merger_agreement", "all_stock")["drop"]


def test_a_value_label_only_in_held_out_does_not_keep_a_field(registry):
    lists = sf.build_field_lists(_with_valued(registry, {"heldout": 7}))
    assert "intent" in _entry(lists, "merger_agreement", "all_stock")["drop"]


def test_the_registry_counts_value_labels_by_set(registry):
    fields = registry["classes"]["corporate_record"]["subclasses"]["board_resolution"]["fields"]
    assert fields["filing_number"]["valued_by_set"]["dev"] == 1
    merger = registry["classes"]["merger_agreement"]["subclasses"]["all_cash"]["fields"]["intent"]
    assert sum(merger["valued_by_set"].values()) == 0  # the Hub marks it not applicable, with no value


def test_every_class_and_subclass_has_an_entry(registry):
    lists = sf.build_field_lists(registry)
    assert set(lists["classes"]) == {"contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim"}
    for cls, entry in registry["classes"].items():
        assert set(lists["classes"][cls]) == set(entry["subclasses"]), cls


def _with_heldout(registry: dict, value: int) -> dict:
    out = copy.deepcopy(registry)
    for entry in out["classes"].values():
        for sub in entry["subclasses"].values():
            for fe in sub["fields"].values():
                if "labeled_by_set" in fe:
                    fe["labeled_by_set"]["heldout"] = value
    return out


def test_held_out_labels_do_not_change_the_lists(registry):
    original = sf.build_field_lists(registry)
    for value in (0, 999):
        changed = _with_heldout(registry, value)
        for entry in changed["classes"].values():
            for sub in entry["subclasses"].values():
                for fe in sub["fields"].values():
                    if "valued_by_set" in fe:
                        fe["valued_by_set"]["heldout"] = value
        assert sf.build_field_lists(changed)["classes"] == original["classes"]


def _with_extension(registry: dict, by_set: dict[str, int]) -> dict:
    out = copy.deepcopy(registry)
    out["classes"]["corporate_record"]["subclasses"]["bylaws"]["fields"]["certifying_officer"] = {
        "type": "name",
        "dojo_status": "scored",
        "in_output_schema": False,
        "labeled_by_set": {"dev": 0, "calibration": 0, "pool": 0, "heldout": 0, **by_set},
    }
    return out


def test_a_labeled_extension_field_is_added(registry):
    lists = sf.build_field_lists(_with_extension(registry, {"dev": 3}))
    assert _entry(lists, "corporate_record", "bylaws")["add"] == {"certifying_officer": {"type": "name"}}


def test_a_held_out_only_extension_field_is_not_added(registry):
    lists = sf.build_field_lists(_with_extension(registry, {"heldout": 5}))
    assert "certifying_officer" not in _entry(lists, "corporate_record", "bylaws")["add"]


def test_label_task_fields_are_never_added(registry):
    lists = sf.build_field_lists(registry)
    for sub, entry in lists["classes"]["correspondence"].items():
        assert not {"content_topic", "sentiment_label"} & set(entry["add"]), sub


def test_the_committed_field_lists_match_the_registry(registry):
    assert sf.load_field_lists() == sf.build_field_lists(registry)
    canonical = json.dumps(registry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert sf.load_field_lists()["registry_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert sf.field_lists_sha256() == hashlib.sha256(sf.FIELDS_PATH.read_bytes()).hexdigest()
