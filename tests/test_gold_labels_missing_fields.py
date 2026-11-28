"""Missing-field admission for the gold catalog (``gold_labels.py add --missing-fields``).

The original ``add`` refuses any document that already has a catalog record, so a field added
to the guide later cannot be landed on the documents it belongs to. These tests pin the opt-in
path, the corporate ``filing_number`` gate and the refusals that keep existing truth untouched.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mailroom_sandbox import gold_labels as gl

EMAIL = """Message-ID: <1@x>
Date: Mon, 14 May 2001 09:02:00 -0700 (PDT)
From: Jane Roe
To: John Doe
Subject: unpaid invoice

John,
Please remit $18,530.00 by May 31, 2001 or we will refer the matter to counsel.
Jane Roe
VP Finance, Acme Corp
"""

OPUS = {"model": "opus", "role": "reviewer"}
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gold_labels.py"


def _sub(fields, doc_id="DOC-1"):
    return {"doc_id": doc_id, "labeler": {"model": "test", "role": "label"}, "fields": fields}


def _s(doc, role, fields):
    labeler = {"model": "test" if role == "label" else "chk-model", "role": role}
    return {"doc_id": doc, "labeler": labeler, "fields": fields}


RECIPIENT = {"recipient": {"value": "John Doe", "evidence": ["To: John Doe"]}}
RECIPIENT2 = {"recipient": {"value": "John Doe", "evidence": ["To: John Doe\nSubject"]}}
DATE_LABEL = {"communication_date": {"value": "2001-05-14", "evidence": ["Mon, 14 May 2001"]}}
DATE_CHECK = {"communication_date": {"value": "2001-05-14", "evidence": ["14 May 2001"]}}


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gold_labels_cli_missing", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gold_labels_cli_missing"] = mod
    spec.loader.exec_module(mod)
    rows = [{"document_id": f"DOC-{i}", "filename": f"f{i}.txt", "expected": "correspondence",
             "expected_subclass": "email", "content_sha256": hashlib.sha256(EMAIL.encode()).hexdigest()}
            for i in (1, 2)]
    texts = {"f1.txt": EMAIL, "f2.txt": EMAIL}
    monkeypatch.setattr(mod, "_load_corpus", lambda _corpus: (rows, texts))
    monkeypatch.setattr(mod, "_schema_binding", lambda revision: {"dataset_revision": revision})
    monkeypatch.setattr(gl, "gold_dir", lambda root=None: tmp_path / "gold")
    monkeypatch.setattr(gl, "supplementary_dir", lambda root=None: tmp_path / "supp")

    def write(name, subs):
        path = tmp_path / name
        gl.write_jsonl(path, subs)
        return str(path)

    def build(*argv):
        return mod.main(["build", "--corpus", "ignored", "--revision", "r", *argv])

    return mod, write, build, tmp_path


def _built(cli):
    """A catalog holding DOC-1.recipient as near_gold, built before filing_number support."""
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    chk = write("chk.jsonl", [_s("DOC-1", "check", RECIPIENT2)])
    assert build("--label", lab, "--check", chk) == 0
    return tmp


def _add(cli, label_subs, check_subs, *, review=None, missing_fields=True, revision="r2"):
    mod, write, _, _ = cli
    args = ["add", "--corpus", "ignored", "--revision", revision,
            "--label", write("add-lab.jsonl", label_subs),
            "--check", write("add-chk.jsonl", check_subs)]
    if missing_fields:
        args.append("--missing-fields")
    if review is not None:
        args += ["--review", write("add-rv.jsonl", review)]
    return mod.main(args)


def _store_bytes(tmp):
    return {p: p.read_bytes() for d in (tmp / "gold", tmp / "supp") for p in sorted(d.iterdir())}


# --------------------------------------------------------------------------- filing_number


def test_filing_number_is_a_supported_corporate_tier2_target():
    assert "filing_number" in gl.TARGET_FIELDS["corporate_record"]["tier2"]
    assert "filing_number" in gl.target_fields("corporate_record")


@pytest.mark.parametrize("value, quote, ok", [
    ("0-1234", "File No. 0-1234", True),                 # an official File No.
    ("0012345", "Document No. 0012345", True),           # leading zeros are part of the identifier
    ("0", "File No. 0", True),                           # zero is a stated identifier
    ("0-1234", "File No. 10-1234", False),               # token overlap is not the same identifier
    ("1234", "File No. 12-1234", False),                 # a substring is a different number
    ("12345", "Document No. 0012345", False),            # a dropped leading zero is a different number
    ("1234", "Document No. AB_1234", False),             # underscore joins the same identifier
    ("ab-1234", "Document No. AB-1234", False),           # exact transcription preserves letter case
    ("AB_1234", "Document No. AB_1234", True),            # a compound identifier stays intact
])
def test_filing_number_must_be_one_exact_identifier(value, quote, ok):
    text = f"STATE OF DELAWARE\n{quote}\nGiven under my hand."
    res = gl.validate_submission(_sub({"filing_number": {"value": value, "evidence": [quote]}}),
                                 text, "corporate_record")
    fr = res.fields["filing_number"]
    assert fr.ok is ok, (value, quote, fr.reason)
    if ok:
        assert res.payload_valid, res.payload_error


def test_filing_number_zero_may_be_written_as_a_number_in_the_submission():
    res = gl.validate_submission(_sub({"filing_number": {"value": 0, "evidence": ["File No. 0"]}}),
                                 "STATE OF DELAWARE\nFile No. 0\n", "corporate_record")
    assert res.fields["filing_number"].ok and res.payload_valid
    assert res.fields["filing_number"].value == "0"


def test_filing_number_absence_needs_a_documented_reason():
    text = "STATE OF DELAWARE\nNo filing number is printed on this record.\n"
    res = gl.validate_submission(_sub({"filing_number": {
        "value": None, "absent": "not found in full read or search"}}), text, "corporate_record")
    assert res.fields["filing_number"].ok
    assert res.fields["filing_number"].presence == "schema_documented_absence"
    no_reason = gl.validate_submission(_sub({"filing_number": {"value": None}}), text, "corporate_record")
    assert "absent reason" in no_reason.fields["filing_number"].reason


# --------------------------------------------------------------------------- add --missing-fields


def test_add_without_the_flag_still_refuses_an_existing_document(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)],
                missing_fields=False) == 1
    assert "DOC-1: already has a catalog record" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_appends_the_new_field_and_preserves_existing_records(cli, capsys):
    tmp = _built(cli)
    gold, supp = tmp / "gold", tmp / "supp"
    old_lines = (gold / "correspondence.jsonl").read_text().splitlines()
    supp_file = supp / "correspondence.jsonl"
    old_supp = supp_file.read_bytes() if supp_file.is_file() else None
    old_rec = json.loads(old_lines[0])
    assert old_rec["schema"]["dataset_revision"] == "r"
    # A catalog built before the guide listed filing_number: the add refreshes the metadata.
    manifest = json.loads((gold / "MANIFEST.json").read_text())
    old_binding = manifest["binding"]
    manifest["target_fields"]["corporate_record"]["tier2"] = []
    (gold / "MANIFEST.json").write_text(json.dumps(manifest))

    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)]) == 0
    assert "added 1 missing-field labels on 1 documents" in capsys.readouterr().out

    new_lines = (gold / "correspondence.jsonl").read_text().splitlines()
    assert set(old_lines) <= set(new_lines)                       # existing records byte for byte
    assert len(new_lines) == len(old_lines) + 1
    recs = gl.read_jsonl(gold / "correspondence.jsonl")
    assert [r for r in recs if r["field"] == "recipient"] == [old_rec]
    added = next(r for r in recs if r["field"] == "communication_date")
    assert added["status"] == "near_gold" and added["doc_id"] == "DOC-1"
    assert added["schema"]["dataset_revision"] == "r2"            # new rows carry this add's binding
    assert (supp_file.read_bytes() if supp_file.is_file() else None) == old_supp
    man = json.loads((gold / "MANIFEST.json").read_text())
    assert man["binding"] == old_binding
    assert man["target_fields"]["corporate_record"]["tier2"] == ["filing_number"]
    assert man["additions"][-1]["missing_fields"] is True
    assert man["additions"][-1]["documents"] == ["DOC-1"]
    assert gl.verify_catalog(gold) == [] and gl.verify_catalog(supp) == []


@pytest.mark.parametrize("store", ["gold", "supp"])
def test_add_preserves_unrelated_noncanonical_class_bytes(cli, store):
    tmp = _built(cli)
    folder = tmp / store
    path = folder / "corporate_record.jsonl"
    if store == "gold":
        rec = gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]
        rec = {**rec, "doc_id": "OTHER", "label_id": "other-label", "note": "·"}
    else:
        rec = {"kind": "notes", "doc_id": "OTHER", "label": {"note": "·"}}
    original = (json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.write_bytes(original)
    manifest_path = folder / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(original).hexdigest()
    manifest["files"][path.name] = digest
    manifest_path.write_text(json.dumps(manifest))
    assert gl.verify_catalog(folder) == []

    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)]) == 0
    assert path.read_bytes() == original
    assert json.loads(manifest_path.read_text())["files"][path.name] == digest
    assert gl.verify_catalog(folder) == []


@pytest.mark.parametrize("store", ["gold", "supp"])
def test_add_refuses_noncanonical_touched_class_atomically(cli, capsys, store):
    tmp = _built(cli)
    folder = tmp / store
    path = folder / "correspondence.jsonl"
    if store == "gold":
        rec = {**gl.read_jsonl(path)[0], "note": "·"}
    else:
        rec = {"kind": "notes", "doc_id": "OTHER", "label": {"note": "·"}}
    original = (json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.write_bytes(original)
    manifest_path = folder / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name] = hashlib.sha256(original).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    assert gl.verify_catalog(folder) == []
    before = _store_bytes(tmp)
    label = {**_s("DOC-1", "label", DATE_LABEL), "supplementary": {"note": "new"}}
    assert _add(cli, [label], [_s("DOC-1", "check", DATE_CHECK)]) == 1
    assert "re-serialising its rows changes the file" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_a_duplicate_key_without_mutating(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", RECIPIENT)], [_s("DOC-1", "check", RECIPIENT2)]) == 1
    assert "DOC-1.recipient: already has a catalog record" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


@pytest.mark.parametrize("label_fields, check_fields", [
    ({**DATE_LABEL, **RECIPIENT}, DATE_CHECK),                 # the label pass collides
    (DATE_LABEL, {**DATE_CHECK, **RECIPIENT2}),                # a one-sided check collides
])
def test_add_missing_fields_refuses_a_collision_from_either_pass(cli, capsys, label_fields, check_fields):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", label_fields)], [_s("DOC-1", "check", check_fields)]) == 1
    assert "DOC-1.recipient: already has a catalog record" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_a_review_that_lands_on_an_existing_field(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    review = [{"doc_id": "DOC-1", "field": "recipient", "verdict": "reject", "reviewer": OPUS}]
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)],
                review=review) == 1
    assert "DOC-1.recipient: already has a catalog record" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_a_new_document(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-2", "label", DATE_LABEL)], [_s("DOC-2", "check", DATE_CHECK)]) == 1
    assert "DOC-2: not in the catalog" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_text_that_changed_since_the_catalog(cli, capsys, monkeypatch):
    tmp = _built(cli)
    mod, _, _, _ = cli
    before = _store_bytes(tmp)
    changed = EMAIL + "Edited after the catalog was built.\n"
    rows = [{"document_id": f"DOC-{i}", "filename": f"f{i}.txt", "expected": "correspondence",
             "expected_subclass": "email", "content_sha256": hashlib.sha256(changed.encode()).hexdigest()}
            for i in (1, 2)]
    monkeypatch.setattr(mod, "_load_corpus", lambda _c: (rows, {"f1.txt": changed, "f2.txt": changed}))
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)]) == 1
    assert "does not match the document record's content_sha256" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_a_stale_source_filename(cli, capsys, monkeypatch):
    tmp = _built(cli)
    mod, _, _, _ = cli
    before = _store_bytes(tmp)
    rows = [{"document_id": f"DOC-{i}", "filename": f"new{i}.txt", "expected": "correspondence",
             "expected_subclass": "email", "content_sha256": hashlib.sha256(EMAIL.encode()).hexdigest()}
            for i in (1, 2)]
    monkeypatch.setattr(mod, "_load_corpus", lambda _c: (rows, {"new1.txt": EMAIL, "new2.txt": EMAIL}))
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)]) == 1
    assert "source filename 'new1.txt' differs" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_keeps_the_review_binding_check(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    review = [{"doc_id": "DOC-1", "field": "urgency", "verdict": "accept", "reviewer": OPUS}]
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [_s("DOC-1", "check", DATE_CHECK)],
                review=review) == 1
    assert "match no catalog record" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_malformed_fields(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", [])], [_s("DOC-1", "check", DATE_CHECK)]) == 1
    assert "fields is not an object" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_refuses_a_submission_with_no_fields(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", {})], [_s("DOC-1", "check", DATE_CHECK)]) == 1
    assert "submission has no fields to add" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_add_missing_fields_keeps_the_independence_gate(cli, capsys):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    copy = {"communication_date": {"value": "2001-05-14", "evidence": ["Mon, 14 May 2001"]}}
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", copy)], [_s("DOC-1", "check", copy)]) == 1
    assert "identical to the label pass" in capsys.readouterr().err
    assert _store_bytes(tmp) == before


@pytest.mark.parametrize("new_subclass, expected", [("subsidiary_list", 0), ("indenture", 1)])
def test_missing_fields_corporate_subclass_identity_is_atomic(cli, monkeypatch, capsys, new_subclass, expected):
    mod, write, build, tmp = cli
    text = "Acme Inc is the parent. Subsidiaries: Beta LLC. Trustee: Trust Co."
    row = {"document_id": "DOC-1", "filename": "corp.txt", "expected": "corporate_record",
           "expected_subclass": "subsidiary_list", "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
    monkeypatch.setattr(mod, "_load_corpus", lambda _: ([row], {"corp.txt": text}))
    label = write("corp-lab.jsonl", [_s("DOC-1", "label", {"entity_name": {"value": "Acme Inc", "evidence": ["Acme Inc"]}})])
    check = write("corp-chk.jsonl", [_s("DOC-1", "check", {"entity_name": {"value": "Acme Inc", "evidence": ["Acme Inc is the parent"]}})])
    assert build("--label", label, "--check", check) == 0
    before = _store_bytes(tmp)
    row["expected_subclass"] = new_subclass
    fields = {"subsidiaries": {"value": ["Beta LLC"], "evidence": ["Beta LLC"]}}
    check_fields = {"subsidiaries": {"value": ["Beta LLC"], "evidence": ["Subsidiaries: Beta LLC"]}}
    assert _add(cli, [_s("DOC-1", "label", fields)], [_s("DOC-1", "check", check_fields)]) == expected
    if expected:
        assert "subclass differs" in capsys.readouterr().err
        assert _store_bytes(tmp) == before
    else:
        records = gl.read_jsonl(tmp / "gold" / "corporate_record.jsonl")
        assert {r["schema"]["dataset_revision"] for r in records} == {"r", "r2"}


def test_missing_fields_source_identity_allows_legacy_missing_subclass(cli):
    mod, _, _, _ = cli
    doc = {"doc_id": "D", "doc_class": "corporate_record", "subclass": "indenture",
           "filename": "d", "content_sha256": "hash"}
    class Result:
        payload_error = None
        fields = {"subject_matter": object()}
    held = {"corporate_record": [{"doc_id": "D", "doc_class": "corporate_record", "filename": "d",
                                  "content_sha256": "hash", "doc_sha": gl.doc_sha("text")}]}
    submitted = [(doc, {"fields": {"subject_matter": {}}}, Result(), "text")]
    assert mod._missing_field_source_problems(submitted, [], held) == []
    held["corporate_record"].extend([{**held["corporate_record"][0], "subclass": "subsidiary_list"},
                                     {**held["corporate_record"][0], "subclass": "indenture"}])
    assert mod._missing_field_source_problems(submitted, [], held)


@pytest.mark.parametrize('new_subclass', ['all_stock', None])
def test_missing_merger_subclass_drift_refuses_atomically(cli, monkeypatch, capsys, new_subclass):
    mod, write, build, tmp = cli
    text = 'Agreement by Alpha Corp, parent, and Beta LLC, target.'
    row = {'document_id': 'DOC-1', 'filename': 'merger.txt', 'expected': 'merger_agreement',
           'expected_subclass': 'all_cash', 'content_sha256': hashlib.sha256(text.encode()).hexdigest()}
    monkeypatch.setattr(mod, '_load_corpus', lambda _: ([row], {'merger.txt': text}))
    label = write('merger-label.jsonl', [_s('DOC-1', 'label', {'acquirer': {'value': 'Alpha Corp', 'evidence': ['Alpha Corp']}})])
    check = write('merger-check.jsonl', [_s('DOC-1', 'check', {'acquirer': {'value': 'Alpha Corp', 'evidence': ['Alpha Corp, parent']}})])
    assert build('--label', label, '--check', check) == 0
    before = _store_bytes(tmp)
    row['expected_subclass'] = new_subclass
    label_fields = {'target': {'value': 'Beta LLC', 'evidence': ['Beta LLC']}}
    check_fields = {'target': {'value': 'Beta LLC', 'evidence': ['Beta LLC, target']}}
    if new_subclass is None:
        with pytest.raises(SystemExit):
            _add(cli, [_s('DOC-1', 'label', label_fields)], [_s('DOC-1', 'check', check_fields)])
    else:
        assert _add(cli, [_s('DOC-1', 'label', label_fields)], [_s('DOC-1', 'check', check_fields)]) == 1
        assert 'subclass differs' in capsys.readouterr().err
    assert _store_bytes(tmp) == before


def test_corpus_rows_take_the_reviewed_subclass_and_keep_the_hub_one(cli):
    """SHF-013: a corrected document is labelled against its reviewed subclass's schema."""
    mod, _, _, _ = cli
    rows = [{"document_id": "DOC-59d072355f2c3b14", "expected": "corporate_record",
             "expected_subclass": "board_resolution"},
            {"document_id": "DOC-59d072355f2c3b14", "expected": "corporate_record", "expected_subclass": "bylaws"},
            {"document_id": "DOC-not-corrected", "expected": "corporate_record", "expected_subclass": "bylaws"}]
    out = mod.apply_subclass_corrections([dict(r) for r in rows])
    assert out[0]["expected_subclass"] == "charter_amendment" and out[0]["hub_subclass"] == "board_resolution"
    # a correction applies only against the Hub value it was reviewed against
    assert out[1] == rows[1] and out[2] == rows[2]


def test_corpus_rows_refuse_a_stale_subclass_correction(cli, monkeypatch):
    """A stale SHF-013 never labels a corrected document against its Hub schema without saying so."""
    from mailroom_sandbox import scoring_hotfixes as sh

    mod, _, _, _ = cli
    monkeypatch.setattr(sh, "enabled", lambda hotfix_id: hotfix_id != "SHF-013")
    with pytest.raises(SystemExit, match="SHF-013"):
        mod.apply_subclass_corrections([{"document_id": "DOC-59d072355f2c3b14", "expected": "corporate_record",
                                         "expected_subclass": "board_resolution"}])


@pytest.mark.parametrize("hub_subclass, expected", [("board_resolution", 0), ("bylaws", 1)])
def test_missing_fields_accept_records_written_under_the_hub_subclass(cli, monkeypatch, capsys, hub_subclass,
                                                                       expected):
    """Records written before a correction carry the Hub subclass; new fields follow the reviewed one."""
    mod, write, build, tmp = cli
    text = "CERTIFICATE OF AMENDMENT of Acme Inc. Article 4 is amended to read as follows."
    row = {"document_id": "DOC-1", "filename": "corp.txt", "expected": "corporate_record",
           "expected_subclass": "board_resolution", "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
    monkeypatch.setattr(mod, "_load_corpus", lambda _: ([row], {"corp.txt": text}))
    label = write("corp-lab.jsonl", [_s("DOC-1", "label", {"entity_name": {"value": "Acme Inc", "evidence": ["Acme Inc"]}})])
    check = write("corp-chk.jsonl", [_s("DOC-1", "check", {"entity_name": {"value": "Acme Inc", "evidence": ["of Acme Inc"]}})])
    assert build("--label", label, "--check", check) == 0
    before = _store_bytes(tmp)
    row.update(expected_subclass="charter_amendment", hub_subclass=hub_subclass)
    fields = {"amended_provisions": {"value": ["Article 4"], "evidence": ["Article 4 is amended"]}}
    check_fields = {"amended_provisions": {"value": ["Article 4"], "evidence": ["Article 4 is amended to read"]}}
    assert _add(cli, [_s("DOC-1", "label", fields)], [_s("DOC-1", "check", check_fields)]) == expected
    records = gl.read_jsonl(tmp / "gold" / "corporate_record.jsonl")
    if expected:
        assert "subclass differs" in capsys.readouterr().err
        assert _store_bytes(tmp) == before
    else:
        by_field = {r["field"]: r["subclass"] for r in records}
        assert by_field == {"entity_name": "board_resolution", "amended_provisions": "charter_amendment"}


def test_add_takes_a_label_only_document_whose_every_field_a_review_settles(cli, capsys):
    """A reviewer's source reading is the second reading when the check was a copy and is withheld."""
    tmp = _built(cli)
    review = [{"doc_id": "DOC-1", "field": "communication_date", "verdict": "accept", "value": "2001-05-14",
               "reviewer": OPUS, "note": "read the header"}]
    capsys.readouterr()
    # The check file covers another document only: DOC-1 has a label and a review, no check.
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [], review=review) == 0
    added = next(r for r in gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")
                 if r["field"] == "communication_date")
    assert added["status"] == "near_gold" and added["review"]["verdict"] == "accept"
    assert gl.verify_catalog(tmp / "gold") == []


@pytest.mark.parametrize("review", [
    [],                                                                     # no review at all
    [{"doc_id": "DOC-1", "field": "recipient2", "verdict": "accept", "reviewer": OPUS}],   # another field
    [{"doc_id": "DOC-1", "field": "communication_date", "verdict": "reject", "reviewer": OPUS}],
    # an accept settles only the value it names: none, or another value, is no second reading
    [{"doc_id": "DOC-1", "field": "communication_date", "verdict": "accept", "reviewer": OPUS}],
    [{"doc_id": "DOC-1", "field": "communication_date", "verdict": "accept", "value": "2001-05-15",
      "reviewer": OPUS}],
])
def test_add_refuses_a_label_only_document_a_review_does_not_settle(cli, capsys, review):
    tmp = _built(cli)
    before = _store_bytes(tmp)
    capsys.readouterr()
    assert _add(cli, [_s("DOC-1", "label", DATE_LABEL)], [], review=review) == 1
    assert "has no check pass" in capsys.readouterr().err
    assert _store_bytes(tmp) == before
