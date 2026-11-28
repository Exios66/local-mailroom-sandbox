"""SHF-019: correspondence header truth the document text does not show is not scored on the headline.

The interim overlay restores ``sender``, ``recipient``, ``additional_recipients`` and
``communication_date`` from the original Enron email header (``basis: original_header`` in
``data/labels/review/interim_reviews.jsonl``), but the corpus text dropped that header. The
headline leaves such a field out of both sides while the text shows neither its header line nor
its value; the raw side keeps it. Network-free; no LLM calls.
"""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval import runners
from mailroom_sandbox.eval.scoring import score_extraction_row
from mailroom_sandbox.job import gate, gate_causes

# A reviewed document whose four header fields are all original_header labels.
DOC = "DOC-0578dca6e6328d88"
HEADER = {
    "sender": "Jeff Dasovich",
    "recipient": "Joseph Alamo",
    "additional_recipients": ["Sandra McCubbin", "James D Steffes", "Mary Hain", "Paul Kaufman", "Karen Denne"],
    "communication_date": "2000-11-03",
}
BODY = "Please find the draft comments attached. Call me with questions before the filing goes out."


def _row(fields=None, *, text=BODY, doc_id=DOC):
    fields = {**HEADER, "intent": "information_sharing"} if fields is None else fields
    presence = {k: "populated" for k in fields}
    return {"id": doc_id, "expected_doc_class": "correspondence", "doc_text": text,
            "expected_fields": json.dumps({**fields, "gt_presence": json.dumps(presence)}),
            "interim_labels": {"fields": sorted(HEADER), "overlay_sha256": "x"}}


def _score(row, predicted):
    return runners._score_pipeline_extraction(row, {"extracted_data": predicted})


# --- the fix and its fingerprint ----------------------------------------------------------------


def test_shf019_is_registered_current_extraction_scoped_and_pinned():
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-019")
    assert sh.status(refresh=True)["SHF-019"] == "current"
    assert "SHF-019" in sh.EXTRACTION_FIXES
    described = next(f for f in sh.describe()["fixes"] if f["id"] == "SHF-019")
    assert {t["target"] for t in described["targets"]} == {t for t, _ in fix.targets}
    assert f"file:{sh.HEADER_REVIEWS}" in {t for t, _ in fix.targets}


def test_shf019_covers_exactly_the_fields_the_interim_overlay_restores_from_the_header():
    from mailroom_sandbox import interim_labels as il

    assert set(sh.HEADER_FIELDS) == set(il.HEADER_FIELDS)
    reviews = sh.header_reviews()
    assert len(reviews) == 1795  # every original_header line of interim_reviews.jsonl
    assert {field for _, field in reviews} == set(sh.HEADER_FIELDS)
    assert reviews[(DOC, "sender")] == {"value": "Jeff Dasovich",
                                        "headers": ("X-From: Jeff Dasovich", "From: jeff.dasovich@enron.com")}


# --- the headline and the raw side --------------------------------------------------------------


def test_shf019_unseen_header_truth_leaves_the_headline_and_stays_raw():
    scored = _score(_row(), {"intent": "information_sharing"})
    assert scored["header_unseen"] == sorted(HEADER)
    assert scored["overall_extraction_score"] == 1.0
    assert scored["raw_dojo"]["overall_extraction_score"] < 1.0  # the raw pass still scores the four misses
    assert "SHF-019" in scored["scoring_hotfixes"]
    assert "overall_extraction_score" in scored["scoring_hotfixes_changed"]


def test_shf019_a_pipeline_item_records_the_header_fields_it_left_off():
    """items.jsonl (and ``sandbox rescore``) names the dropped fields; a clean row carries no key."""
    row, result = _row(), {"doc_type": "correspondence", "stage": "archived",
                           "extracted_data": {"intent": "information_sharing"}}
    item = runners.pipeline_item_score(row, result, runners._score_pipeline_extraction(row, result))
    assert item["header_unseen"] == sorted(HEADER)
    shown = _row(text=BODY + "\nFrom: Jeff Dasovich\nTo: Joseph Alamo\nDate: 2000-11-03\n"
                 "Cc: Sandra McCubbin, James D Steffes, Mary Hain, Paul Kaufman, Karen Denne")
    clean = runners.pipeline_item_score(shown, result, runners._score_pipeline_extraction(shown, result))
    assert "header_unseen" not in clean
    assert "header_unseen" not in runners.pipeline_item_score(row, result, None)


def test_shf019_drops_the_prediction_of_an_unseen_field_too():
    # A guessed value for a dropped field is no scoring event: never a false positive or a hit.
    scored = _score(_row(), {"intent": "information_sharing", "sender": "Someone Else"})
    assert scored["overall_extraction_score"] == 1.0
    assert scored.get("fp") in (None, 0)


@pytest.mark.parametrize("visible, field", [
    ("X-From: Jeff Dasovich", "sender"),                # the quoted header line
    ("-----Original Message-----\nFrom: jeff.dasovich@enron.com", "sender"),  # its value after the colon
    ("Joseph,\n\nsee below.", None),                      # a first name alone is not the label value
    # the label value in a signature or reply; it is also the To value quoted as evidence for the cc list
    ("Thanks, Joseph Alamo", ("recipient", "additional_recipients")),
    ("cc'd Mary   Hain on this", "additional_recipients"),  # one item of a list, whitespace-insensitive
])
def test_shf019_a_field_the_text_shows_stays_scored(visible, field):
    scored = _score(_row(text=f"{visible}\n\n{BODY}"), {"intent": "information_sharing"})
    shown = {field} if isinstance(field, str) else set(field or ())
    expected = sorted(set(HEADER) - shown)
    assert scored["header_unseen"] == expected


def test_shf019_keeps_a_header_field_another_source_relabelled():
    # A near-gold or staged label from the visible text replaced the header value: it is scored.
    scored = _score(_row({**HEADER, "sender": "Legal Team"}), {"sender": "Legal Team"})
    assert "sender" not in scored["header_unseen"]


def test_shf019_never_drops_an_empty_label_or_other_classes_or_unreviewed_documents():
    expected = {**HEADER, "gt_presence": "{}"}
    assert sh.drop_unseen_header_truth("corporate_record", DOC, expected, BODY)[1] == []
    assert sh.drop_unseen_header_truth("correspondence", "DOC-unreviewed", expected, BODY)[1] == []
    assert sh.drop_unseen_header_truth("correspondence", DOC, {"sender": None}, BODY)[1] == []
    assert sh.drop_unseen_header_truth("correspondence", None, expected, BODY)[1] == []
    assert sh.drop_unseen_header_truth("correspondence", DOC, expected, None)[1] == []


def test_shf019_marks_a_dropped_field_pending_annotation():
    expected = {**HEADER, "gt_presence": json.dumps({k: "populated" for k in HEADER})}
    out, dropped = sh.drop_unseen_header_truth("correspondence", DOC, expected, BODY)
    assert dropped == sorted(HEADER)
    assert not set(HEADER) & set(out)
    assert set(json.loads(out["gt_presence"]).values()) == {"pending_annotation"}


def test_shf019_is_off_without_the_document_id_or_text():
    expected = dict(HEADER)
    assert "header_unseen" not in score_extraction_row("correspondence", {}, expected, BODY)  # no doc_id
    for text in (None, ""):
        off = score_extraction_row("correspondence", {}, expected, text, doc_id=DOC)
        assert "header_unseen" not in off and "SHF-019" not in off["scoring_hotfixes"]


def test_shf019_a_stale_fix_leaves_the_dojo_pin(monkeypatch):
    fix = next(f for f in sh.HOTFIXES if f.id == "SHF-019")
    stale = sh.ScoringHotfix(fix.id, fix.layer, tuple((t, "0" * 64) for t, _ in fix.targets),
                             fix.upstream, fix.summary)
    monkeypatch.setattr(sh, "HOTFIXES", tuple(stale if f.id == fix.id else f for f in sh.HOTFIXES))
    monkeypatch.setattr(sh, "_BY_ID", {**sh._BY_ID, fix.id: stale})
    monkeypatch.setattr(sh, "_STATUS", {})
    scored = _score(_row(), {"intent": "information_sharing"})
    assert "header_unseen" not in scored
    assert scored["overall_extraction_score"] == scored["raw_dojo"]["overall_extraction_score"]
    monkeypatch.setattr(sh, "_STATUS", {})


def test_shf019_refuses_a_reviews_file_edited_after_validation(monkeypatch, tmp_path):
    edited = tmp_path / "interim_reviews.jsonl"
    edited.write_text('{"basis": "original_header"}\n', encoding="utf-8")
    monkeypatch.setattr(sh, "data_path", lambda rel: edited)
    with pytest.raises(RuntimeError, match="changed since SHF-019 was validated"):
        sh.header_reviews()


# --- the gate ------------------------------------------------------------------------------------


def test_shf019_the_gate_does_not_count_an_unseen_label():
    row = _row()
    assert gate.labelled_count(row, "correspondence") == gate.labelled_count(row, "correspondence",
                                                                            hotfixed=False) - len(HEADER)
    shown = _row(text="From: jeff.dasovich@enron.com\n" + BODY)
    assert gate.labelled_count(shown, "correspondence") == gate.labelled_count(row, "correspondence") + 1


def test_shf019_the_lowest_field_diagnosis_skips_an_unseen_label():
    scores = gate_causes._field_scores(_row(), {"extracted_data": {"intent": "information_sharing"}})
    assert not set(HEADER) & set(scores)


def test_shf019_the_gate_does_not_score_a_fix_to_an_unseen_label():
    fixes = [{"field": "sender", "value": "Jeff Dasovich"}]
    assert gate._fix_accuracy(_row(), fixes) == (0, 0)
    assert gate._fix_accuracy(_row(text="X-From: Jeff Dasovich\n" + BODY), fixes) == (1, 0)


# --- retirement ----------------------------------------------------------------------------------


def test_shf019_is_a_no_op_once_the_corpus_restores_the_header_lines():
    """Writing each document's quoted header lines back into its text leaves nothing to drop."""
    reviews = sh.header_reviews()
    by_doc: dict[str, dict[str, dict]] = {}
    for (doc_id, field), entry in reviews.items():
        by_doc.setdefault(doc_id, {})[field] = entry
    for doc_id, entries in by_doc.items():
        truth = {field: entry["value"] for field, entry in entries.items()}
        restored = "\n".join(h for entry in entries.values() for h in entry["headers"]) + "\n\n" + BODY
        assert sh.drop_unseen_header_truth("correspondence", doc_id, truth, BODY)[1] or all(
            not sh._header_items(v) for v in truth.values()), doc_id
        assert sh.drop_unseen_header_truth("correspondence", doc_id, truth, restored)[1] == [], doc_id


# --- review follow-ups ---------------------------------------------------------------------------


def test_shf019_empty_text_drops_nothing_on_the_headline_or_in_the_gate():
    row = _row(text="")
    assert sh.drop_unseen_header_truth("correspondence", DOC, dict(HEADER), "")[1] == []
    assert gate.labelled_count(row, "correspondence") == gate.labelled_count(row, "correspondence", hotfixed=False)
    assert "header_unseen" not in score_extraction_row("correspondence", {}, dict(HEADER), "", doc_id=DOC)


def test_shf019_folds_periods_and_commas_in_the_visibility_check():
    entry = {"value": "Stacy E. Dickson", "headers": ("X-From: Stacy E. Dickson",)}
    assert sh.header_visible(entry, "Regards,\nStacy E Dickson")
    assert sh.header_visible({"value": "Stacy E Dickson", "headers": ()}, "Stacy E. Dickson, Esq.")


def test_shf019_can_be_left_off_by_the_caller():
    on = score_extraction_row("correspondence", {}, dict(HEADER), BODY, doc_id=DOC)
    off = score_extraction_row("correspondence", {}, dict(HEADER), BODY, doc_id=DOC, drop_unseen_headers=False)
    assert on["header_unseen"] == sorted(HEADER) and "header_unseen" not in off
    assert "SHF-019" not in off["scoring_hotfixes"]
    row = _row()
    assert gate.labelled_count(row, "correspondence", drop_unseen_headers=False) == gate.labelled_count(
        row, "correspondence", hotfixed=False)


def test_shf019_the_gate_attributes_an_unscorable_document_to_the_fix_that_took_it_below_the_bar():
    bars = gate.Bars()
    assert bars.min_labelled == 2
    shf019 = {"outcome": "unscorable_archive", "labelled": 1, "labelled_raw": 5, "labelled_header_unseen": 4}
    shf015 = {"outcome": "unscorable_archive", "labelled": 1, "labelled_raw": 2}
    both = {"outcome": "unscorable_archive", "labelled": 0, "labelled_raw": 3, "labelled_header_unseen": 1}
    scorable = {"outcome": "correct_archive", "labelled": 1, "labelled_raw": 5, "labelled_header_unseen": 4}
    statuses = [shf019, shf015, both, scorable]
    assert gate._unscorable_by_shf019(statuses, bars) == 1
    assert gate._unscorable_by_shf015(statuses, bars) == 2  # shf015 and both: below the bar before SHF-019


def test_shf019_the_gate_status_records_the_header_drop():
    status = gate._status({"row": _row(), "item": None, "nodes": []}, gate.Bars())
    assert status["labelled_raw"] - status["labelled"] == status["labelled_header_unseen"] == len(HEADER)


def test_every_scoring_hotfix_data_file_is_bundled_in_the_modal_worker():
    """The worker has no checkout: a ``file:`` target missing from the image makes the fix
    ``unavailable`` there, and ``verify_locked_hotfixes`` refuses every locked remote job."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "deploy" / "modal_job.py").read_text(encoding="utf-8")
    files = {t[len(sh.FILE_TARGET):] for fix in sh.HOTFIXES for t, _ in fix.targets if t.startswith(sh.FILE_TARGET)}
    assert files

    def bundled(rel: str) -> bool:
        # A file mount, or a directory mount of the file or one of its parents. The config tree,
        # including SHF-018's field list, is one directory mount.
        if f'remote_path=f"{{SANDBOX_ROOT}}/{rel}"' in source:
            return True
        parent = rel
        while "/" in parent:
            parent = parent.rsplit("/", 1)[0]
            if f'remote_path=f"{{SANDBOX_ROOT}}/{parent}"' in source:
                return True
        return False

    missing = sorted(rel for rel in files if not bundled(rel))
    assert missing == []
