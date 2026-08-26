"""Prompt variant loading."""

from mailroom_sandbox.prompts import list_variants, load_variant


def test_sorter_local_variant_mentions_json():
    assert "sorter_local_v0" in list_variants()
    text = load_variant("sorter_local_v0")
    assert "json" in text.lower()
    assert "sorter_reviewer_local_v0" in list_variants()
    assert "json" in load_variant("sorter_reviewer_local_v0").lower()
    assert "json" in load_variant("judge_local_v0").lower()
