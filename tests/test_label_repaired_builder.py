"""Fixture regressions for the v9.3 label-repaired CSV builder (no Hub pull)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox.paths import repo_root

_BUILDER = repo_root() / "reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py"
_SPEC = importlib.util.spec_from_file_location("label_repaired_builder", _BUILDER)
blr = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(blr)


def test_amount_canon_keeps_distinct_magnitudes():
    ten = blr.canon("contract_value", "$10")
    hundred = blr.canon("contract_value", "$100")
    ten_cents = blr.canon("termination_fee", "$10.00")
    assert ten != hundred
    assert ten == ten_cents
    assert ten == blr.canon("per_share_cash_amount", "USD 10")


def test_duplicate_keepers_prefer_reviewed_subclass():
    rows = [
        {"id": "DOC-uncorrected", "content_sha256": "aaa", "doc_text": "same"},
        {"id": "DOC-reviewed", "content_sha256": "aaa", "doc_text": "same"},
    ]
    meta = {
        "DOC-uncorrected": {"normalized_text_sha256": "norm"},
        "DOC-reviewed": {"normalized_text_sha256": "norm"},
    }
    corrections = {"DOC-reviewed": {"subclass": "charter_amendment"}}
    keepers = blr.duplicate_keepers(rows, meta, corrections)
    assert keepers["DOC-reviewed"] == "DOC-reviewed"
    assert keepers["DOC-uncorrected"] == "DOC-reviewed"


def test_duplicate_keepers_reject_conflicting_reviews():
    rows = [
        {"id": "A", "content_sha256": "x", "doc_text": "t"},
        {"id": "B", "content_sha256": "x", "doc_text": "t"},
    ]
    meta = {"A": {}, "B": {}}
    corrections = {"A": {"subclass": "charter_amendment"}, "B": {"subclass": "board_resolution"}}
    with pytest.raises(ValueError, match="conflicting reviewed subclasses"):
        blr.duplicate_keepers(rows, meta, corrections)


def test_missing_expiration_annotation_is_not_absence():
    assert blr._cuad_expiration([]) is False
    assert blr._cuad_expiration(["   "]) is False
    assert blr._cuad_expiration(["The term expires on 2027-06-30."]) == "2027-06-30"
    assert blr._cuad_expiration(["perpetual agreement with no calendar end"]) is False


def test_notice_span_compatible_rejects_reversed_threshold():
    least = blr.canon("termination_notice_period", "at least 30 days' notice")
    most = blr.canon("termination_notice_period", "at most 30 days' notice")
    assert not blr.span_compatible(least, most, field="termination_notice_period")
    same = blr.canon("termination_notice_period", "written notice of at least 30 days")
    assert blr.span_compatible(least, same, field="termination_notice_period")


def test_vote_normalizes_selected_date_for_output():
    result = blr.vote(
        "expiration_date",
        [{"source": "hub_v9.3", "value": "July 4, 2025"}],
    )
    assert result["value"] == "2025-07-04"
    assert result["votes"]["hub_v9.3"] == "July 4, 2025"


def test_build_refuses_existing_output(tmp_path: Path):
    existing = tmp_path / "generation"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="output exists"):
        blr.build(existing)


def test_jsonl_split_keeps_unicode_line_separators_inside_records():
    raw = json.dumps({"id": "DOC-1", "doc_text": "line\u2028with\u2029separators"}, ensure_ascii=False) + "\n"
    rows = [json.loads(line) for line in raw.split("\n") if line.strip()]
    assert rows[0]["doc_text"] == "line\u2028with\u2029separators"
    with pytest.raises(json.JSONDecodeError):
        [json.loads(line) for line in raw.splitlines() if line.strip()]
    src = Path(blr.__file__).read_text(encoding="utf-8")
    body = src.split("def jsonl", 1)[1].split("\ndef ", 1)[0]
    assert '.split("\\n")' in body
    assert "decode(\"utf-8\").splitlines()" not in body
