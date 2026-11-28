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
    # Start-date-only span text must not become a documented-absence ballot.
    assert blr._cuad_expiration(
        ["The term of this Agreement shall commence on January 10th, 2020."]
    ) is False
    # "end" inside Vendor must not act as an end cue.
    assert blr._cuad_expiration(
        ["Vendor shall commence services on March 1, 2020."]
    ) is False


def test_date_value_skips_event_defined_spans():
    assert blr._date_value("[___], 2020") is None
    assert blr._date_value("March 1, 2020") == "2020-03-01"
    assert blr._date_value(
        "the date on which this Agreement is signed by both parties"
    ) is False


def test_expected_cache_digest_is_pinned():
    assert len(blr.EXPECTED_CACHE_SHA256) == 64
    assert blr.EXPECTED_CACHE_SHA256 == (
        "8a5f0ce26067cef4fa958f5aa53035d6dbd63d0eba9455b3c1f8b5ab509ad45f"
    )
    assert blr.PINNED_HUB_INPUT_SHA256[
        f"data/cache/Lucius-Morningstar__mailroom-dataset__{blr.REVISION[:12]}/ground_truth_all.jsonl"
    ] == blr.EXPECTED_CACHE_SHA256
    assert len(blr.PINNED_HUB_INPUT_SHA256) == 3
    for digest in blr.PINNED_HUB_INPUT_SHA256.values():
        assert len(digest) == 64


def test_require_pinned_rejects_tampered_hub_bytes():
    snap = blr.InputSnapshot()
    snap.hashes = dict(blr.PINNED_HUB_INPUT_SHA256)
    snap.require_pinned(blr.PINNED_HUB_INPUT_SHA256)
    bad = dict(snap.hashes)
    key = next(iter(bad))
    bad[key] = "0" * 64
    snap.hashes = bad
    with pytest.raises(ValueError, match="digest mismatch"):
        snap.require_pinned(blr.PINNED_HUB_INPUT_SHA256)


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


def test_a_near_gold_label_beats_the_hub_and_its_derived_votes():
    # The Hub value echoed by a Hub-derived and a generated source weighs 6.0 against 2.0, but
    # a label read and checked against the document is truth over the Hub.
    ballots = [
        {"source": "hub_v9.3", "value": "Acme Corp"},
        {"source": "interim_derived", "value": "Acme Corp"},
        {"source": "generated_derived", "value": "Acme Corp"},
        {"source": "near_gold_two_pass", "value": "Acme Holdings, Inc."},
    ]
    out = blr.vote("trustee", ballots)
    assert out["value"] == "Acme Holdings, Inc."
    assert out["chosen_source"] == "near_gold_two_pass"
    assert out["rule"] == "reviewed_over_hub"
    assert out["votes"]["hub_v9.3"] == "Acme Corp"  # the replaced Hub value stays on record
    assert out["needs_human"] is False
    assert out["moved_by_precedence"] is True


def test_reviewed_labels_still_rank_among_themselves():
    # The reviewed original header outranks a near-gold reading of the stripped text.
    ballots = [
        {"source": "interim_reviewed", "value": "Jeff Dasovich"},
        {"source": "near_gold_two_pass", "value": "jd"},
        {"source": "hub_v9.3", "value": "jd"},
    ]
    assert blr.vote("sender", ballots)["chosen_source"] == "interim_reviewed"


def test_independent_evidence_still_counts_against_a_reviewed_label():
    # A CUAD annotator's span and a verbatim rule match are not Hub echoes; only the Hub's own
    # weight is set aside. Losing a reviewed label that way is queued for a human.
    ballots = [
        {"source": "hub_v9.3", "value": "2005-12-21"},
        {"source": "cuad_span", "value": "2005-12-21"},
        {"source": "generated_rule", "value": "2005-12-21"},
        {"source": "near_gold_two_pass", "value": "2006-01-04"},
    ]
    out = blr.vote("agreement_date", ballots)
    assert out["value"] == "2005-12-21"
    assert out["needs_human"] is True
    assert out["moved_by_precedence"] is False


def test_a_reviewed_absence_over_a_populated_value_is_queued_for_a_human():
    ballots = [{"source": "hub_v9.3", "value": "ACME INC"}, {"source": "interim_reviewed", "value": None}]
    out = blr.vote("entity_name", ballots)
    assert (out["value"], out["presence"]) == (None, "documented_absence")
    assert out["needs_human"] is True


def test_the_committed_summary_records_what_the_precedence_moved():
    summary = json.loads((_BUILDER.parent / "mailroom_dataset_v9.3_label_repaired_summary.json").read_text(encoding="utf-8"))
    assert summary["values_moved_by_reviewed_precedence"] == {}


def test_without_a_reviewed_label_the_weighted_vote_is_unchanged():
    ballots = [{"source": "hub_v9.3", "value": "A"}, {"source": "generated_rule", "value": "B"}]
    out = blr.vote("trustee", ballots)
    assert (out["value"], out["rule"]) == ("A", "weighted_vote")


def test_corporate_subclasses_target_their_salient_fields():
    # Without a target cell a near-gold subclass label never reaches the release, nor the staged
    # overlay production scores against (rc.10 carried none of them).
    fields = blr.subclass_fields(blr.InputSnapshot())
    reg = json.loads(blr.SUBCLASS_REGISTRY.read_text(encoding="utf-8"))["classes"]["corporate_record"]["subclasses"]
    assert set(fields) == {"corporate_record"}
    assert fields["corporate_record"]["indenture"] == reg["indenture"]["salient"]
    assert "trustee" in fields["corporate_record"]["indenture"]
    assert all(fields["corporate_record"].values())


def test_the_committed_release_holds_the_subclass_labels():
    import csv

    path = _BUILDER.parent / "mailroom_dataset_v9.3_label_repaired_label_provenance.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        sources = {(r["field"], r["chosen_source"]) for r in csv.DictReader(fh) if r["doc_class"] == "corporate_record"}
    assert ("trustee", "near_gold_two_pass") in sources
    assert ("authorized_capital", "near_gold_two_pass") in sources
