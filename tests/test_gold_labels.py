"""Gold-label gate, agreement and catalog (``mailroom_sandbox.gold_labels``)."""
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


def sub(fields, doc_id="DOC-1"):
    return {"doc_id": doc_id, "labeler": {"model": "test", "role": "label"}, "fields": fields}


def test_locate_is_whitespace_and_case_tolerant():
    span = gl.locate("please  REMIT $18,530.00", EMAIL)
    assert span is not None
    assert EMAIL[span["start"]:span["end"]] == span["text"]
    assert span["text"].startswith("Please remit")
    assert gl.locate("not in the text", EMAIL) is None


def test_valid_correspondence_labels_pass_every_gate():
    res = gl.validate_submission(sub({
        "sender": {"value": "Jane Roe, VP Finance, Acme Corp", "evidence": ["Jane Roe\nVP Finance, Acme Corp"]},
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-14", "evidence": ["Mon, 14 May 2001"]},
        "demand_amount": {"value": "$18,530.00", "evidence": ["Please remit $18,530.00"]},
        "urgency": {"value": "time-sensitive", "evidence": ["by May 31, 2001"]},
        "action_items": {"value": ["Remit $18,530.00 by May 31, 2001"], "evidence": ["Please remit $18,530.00 by May 31, 2001"]},
        "additional_recipients": {"value": [], "absent": "no cc line"},
    }), EMAIL, "correspondence")
    assert res.payload_valid, res.payload_error
    assert all(fr.ok for fr in res.fields.values()), {k: v.reason for k, v in res.fields.items()}
    assert res.fields["demand_amount"].value == 18530.0
    assert res.fields["additional_recipients"].presence == "schema_documented_absence"
    assert res.fields["recipient"].evidence[0]["text"] == "To: John Doe"


@pytest.mark.parametrize("entry, reason", [
    ({"value": "John Doe", "evidence": ["To: Jim Doe"]}, "evidence not found"),
    ({"value": "Somebody Else", "evidence": ["To: John Doe"]}, "not supported"),
    ({"value": None}, "absent reason"),
    ({"value": "John Doe"}, "no evidence"),
])
def test_recipient_rejections(entry, reason):
    res = gl.validate_submission(sub({"recipient": entry}), EMAIL, "correspondence")
    assert not res.fields["recipient"].ok
    assert reason in res.fields["recipient"].reason


def test_closed_label_out_of_vocabulary_is_rejected_not_mapped():
    res = gl.validate_submission(sub({"urgency": {"value": "high", "evidence": ["by May 31"]}}), EMAIL, "correspondence")
    assert not res.fields["urgency"].ok
    assert res.fields["urgency"].reason.startswith("out_of_vocabulary")


def test_urgency_is_never_empty_but_routine_may_rest_on_a_basis():
    empty = gl.validate_submission(sub({"urgency": {"value": None, "absent": "none"}}), EMAIL, "correspondence")
    assert not empty.fields["urgency"].ok
    routine = gl.validate_submission(sub({"urgency": {"value": "routine", "basis": "no deadline"}}), EMAIL, "correspondence")
    assert routine.fields["urgency"].ok


def test_date_must_be_iso_and_match_its_evidence():
    bad_fmt = gl.validate_submission(sub({"communication_date": {"value": "05/14/2001", "evidence": ["14 May 2001"]}}),
                                     EMAIL, "correspondence")
    assert "ISO" in bad_fmt.fields["communication_date"].reason
    wrong = gl.validate_submission(sub({"communication_date": {"value": "2001-05-31", "evidence": ["Mon, 14 May 2001"]}}),
                                   EMAIL, "correspondence")
    assert not wrong.fields["communication_date"].ok


def test_action_items_cap():
    items = ["Please remit"] * 4
    res = gl.validate_submission(sub({"action_items": {"value": items, "evidence": ["Please remit"]}}), EMAIL, "correspondence")
    assert "at most 3" in res.fields["action_items"].reason


def test_non_target_field_is_rejected():
    res = gl.validate_submission(sub({"intent": {"value": "payment_demand", "evidence": ["remit"]}}), EMAIL, "correspondence")
    assert res.fields["intent"].reason == "not a target field"


CONTRACT = """SERVICES AGREEMENT dated as of June 21, 1999 between Alpha Inc. ("Supplier") and Beta LLC ("Customer").
Customer shall pay Supplier a fee of $250,000 within thirty days of invoice.
IN WITNESS WHEREOF  By: /s/ Mary Major, President  By: /s/ Sam Minor, CEO
"""


def test_contract_value_stays_a_currency_phrase_for_the_pipeline_schema():
    res = gl.validate_submission(sub({"contract_value": {"value": "$250,000", "evidence": ["a fee of $250,000"]}}),
                                 CONTRACT, "contract")
    assert res.payload_valid, res.payload_error
    assert res.fields["contract_value"].ok
    assert res.fields["contract_value"].value == "$250,000"


def test_party_roles_need_a_known_role():
    ok = gl.validate_submission(sub({"party_roles": {
        "value": ["Alpha Inc.: supplier", "Beta LLC: customer"],
        "evidence": ['Alpha Inc. ("Supplier") and Beta LLC ("Customer")']}}), CONTRACT, "contract")
    assert ok.fields["party_roles"].ok, ok.fields["party_roles"].reason
    bad = gl.validate_submission(sub({"party_roles": {
        "value": ["Alpha Inc.: vendor"], "evidence": ['Alpha Inc. ("Supplier")']}}), CONTRACT, "contract")
    assert "known role" in bad.fields["party_roles"].reason


def test_values_agree_is_type_aware():
    assert gl.values_agree(["Mary Major", "Sam Minor"], ["Sam Minor", "Mary Major"], "entity_list:name")
    assert gl.values_agree("Jane Roe", "Jane Roe, VP Finance", "name")
    assert not gl.values_agree("Jane Roe", "John Doe", "name")
    assert gl.values_agree(None, [], "entity_list")
    assert not gl.values_agree("2001-05-14", "2001-05-15", "date")
    assert gl.values_agree(18530.0, 18530.0, "money")


def test_reconcile_and_review():
    label = gl.validate_submission(sub({
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-14", "evidence": ["14 May 2001"]},
    }), EMAIL, "correspondence")
    check = gl.validate_submission(sub({
        "recipient": {"value": "John Doe", "evidence": ["To: John Doe"]},
        "communication_date": {"value": "2001-05-31", "evidence": ["May 31, 2001"]},
    }), EMAIL, "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence", "filename": "f", "content_sha256": "abc"}
    records, rejects = gl.reconcile(doc, EMAIL, label, check, {"model": "a"}, {"model": "b"}, {"dataset_revision": "r"})
    by_field = {r["field"]: r for r in records}
    assert by_field["recipient"]["status"] == "near_gold" and not by_field["recipient"]["use_as_truth"]
    assert by_field["communication_date"]["status"] == "disputed"
    assert not by_field["communication_date"]["use_as_truth"]
    assert rejects == []
    settled = gl.apply_review(by_field["communication_date"], {"verdict": "accept", "reviewer": OPUS})
    assert settled["status"] == "near_gold" and not settled["use_as_truth"]
    dropped = gl.apply_review(by_field["recipient"], {"verdict": "reject", "reviewer": OPUS})
    assert dropped["status"] == "rejected" and not dropped["use_as_truth"]


def test_gate_rejects_go_to_supplementary():
    label = gl.validate_submission(sub({"recipient": {"value": "Nobody", "evidence": ["To: John Doe"]}}),
                                   EMAIL, "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence"}
    records, rejects = gl.reconcile(doc, EMAIL, label, None, {"model": "a"}, None, {})
    assert records == [] and rejects[0]["field"] == "recipient"


def test_work_queue_skips_fields_the_hub_labels():
    rows = [{
        "document_id": "DOC-9", "filename": "f", "expected": "corporate_record", "expected_subclass": "bylaws",
        "content_sha256": "x",
        "gt_fields": json.dumps({"entity_name": "Acme Inc.",
                                 "gt_presence": json.dumps({"signatories": "not_applicable"})}),
    }, {"document_id": "DOC-8", "filename": "g", "expected": "merger_agreement", "gt_fields": "{}"}]
    queue = gl.work_queue(rows)
    assert [q["doc_id"] for q in queue] == ["DOC-9"]
    assert queue[0]["fields"] == ["effective_date", "jurisdiction"]


def test_cuad_dates_need_exactly_one_calendar_date():
    labels = {"Agreement Date": [{"start": 0, "text": "the 21st day of June, 1999"}],
              "Expiration Date": [{"start": 9, "text": "five years after the Effective Date"}]}
    row = {"document_id": "DOC-7", "expected": "contract",
           "gt_fields": json.dumps({"cuad_clause_labels": labels})}
    out = gl.cuad_date_submission(row)
    assert out["fields"] == {"agreement_date": {"value": "1999-06-21", "evidence": ["the 21st day of June, 1999"]}}
    assert gl.parse_dates("June 1, 2000 and 6/2/2000") == {"2000-06-01", "2000-06-02"}


def test_catalog_round_trip_and_tamper_detection(tmp_path):
    rec = {"doc_id": "D", "field": "recipient", "status": "near_gold", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}],
           "check": {"agrees": True, "gate_ok": True}}
    sha = gl.write_jsonl(tmp_path / "correspondence.jsonl", [rec])
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"schema": gl.SCHEMA, "files": {"correspondence.jsonl": sha}}))
    assert gl.verify_catalog(tmp_path) == []
    (tmp_path / "correspondence.jsonl").write_text(json.dumps({**rec, "use_as_truth": True}) + "\n")
    problems = gl.verify_catalog(tmp_path)
    assert any("sha256" in p for p in problems)
    assert any("use_as_truth" in p for p in problems)


def test_free_text_lists_agree_on_paraphrase_but_not_on_count():
    a = ["Update the Excel worksheet by 5 p.m. on Thursday to reflect payments"]
    b = ["Update the worksheet by 5 p.m. Thursday to reflect any payments received"]
    assert gl.values_agree(a, b, "entity_list")
    assert not gl.values_agree(a, a + ["Call me"], "entity_list")
    assert not gl.values_agree(["Call the bank"], ["Sign the lease"], "entity_list")


def test_overlay_exports_only_near_gold_never_truth():
    base = {"doc_class": "correspondence", "subclass": "email", "content_sha256": "ab" * 32,
            "presence": "populated", "evidence": [], "labeler": {"model": "s"}}
    recs = [
        {**base, "doc_id": "D1", "field": "recipient", "value": "John Doe", "status": "near_gold"},
        {**base, "doc_id": "D1", "field": "sender", "value": "Jane", "status": "near_gold",
         "review": {"verdict": "correct"}},
        {**base, "doc_id": "D1", "field": "urgency", "value": "routine", "status": "candidate"},
        {**base, "doc_id": "D2", "field": "recipient", "value": "X", "status": "disputed"},
        {**base, "doc_id": "D3", "field": "recipient", "value": "Y", "status": "rejected"},
        {**base, "doc_id": "D4", "field": "recipient", "value": "Z", "status": "candidate"},
    ]
    out = gl.overlay_records(recs, gate_run="gold-labels-x")
    assert [o["doc_id"] for o in out] == ["D1"]  # D4 holds a single-pass candidate only
    labels = out[0]["labels"]
    assert set(labels) == {"recipient", "sender"}
    assert out[0]["doc_sha256"] == "ab" * 8 and out[0]["source"]["gate_run"] == "gold-labels-x"
    assert labels["recipient"]["basis"] == "near_gold:two_pass_agree"
    assert labels["sender"]["basis"] == "near_gold:opus_reviewed_correct"
    assert all(v["status"] == "gap_fill" and v["use_as_truth"] is False for v in labels.values())


def test_near_empty_documents_are_tagged():
    res = gl.validate_submission(sub({"recipient": {"value": "John Doe", "evidence": ["To: John Doe"]}}),
                                 "To: John Doe\nsee attached", "correspondence")
    doc = {"doc_id": "DOC-1", "doc_class": "correspondence"}
    records, _ = gl.reconcile(doc, "To: John Doe\nsee attached", res, None, {"model": "a"}, None, {})
    assert records[0]["near_empty"] is True


def test_review_correction_keeps_the_basis_of_a_default_label():
    rec = {"doc_id": "D", "field": "urgency", "value": "urgent", "status": "disputed", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}], "absent_reason": None}
    out = gl.apply_review(rec, {"verdict": "correct", "value": "routine", "evidence": [], "presence": "populated",
                                "absent_reason": "standing weekly invitation", "reviewer": OPUS})
    assert out["absent_reason"] == "standing weekly invitation" and out["evidence"] == []
    assert "absent_reason" not in out["review"]


def test_day_first_numeric_dates_only_when_unambiguous():
    assert gl._date_supported("2001-03-27", "Sent: 27/03/2001 18:38")
    assert not gl._date_supported("2000-11-02", "Sent: 02/11/2000 12:38")
    assert gl._date_supported("2000-02-11", "Sent: 02/11/2000 12:38")


# --------------------------------------------------------------------------- adversarial-review fixes


def _money(value, evidence, doc="Pay: " , name="demand_amount", cls="correspondence"):
    text = f"{doc}{evidence}"
    res = gl.validate_submission(sub({name: {"value": value, "evidence": [evidence]}}), text, cls)
    return res.fields[name]


@pytest.mark.parametrize("value, evidence", [
    (21844.0, "$218,440.00"),          # a substring of the digits
    (4.0, "$218,440.00"),
    (0, "Date: May 3, 2001"),          # no figure zero
    (float("nan"), "$18,530.00"),
    (float("inf"), "$18,530.00"),
    ("NaN", "$18,530.00"),
    ("1_000", "$1,000"),
    ("1e3", "$1,000"),
    (2.5, "$2.5 million"),             # a scaled figure is only its scaled amount
])
def test_money_needs_an_exactly_equal_figure_in_the_evidence(value, evidence):
    fr = _money(value, evidence)
    assert not fr.ok, fr


@pytest.mark.parametrize("value, evidence", [
    (218440.0, "$218,440.00"), (218440, "USD 218,440"), (18530.5, "$18,530.50"), (0, "pay $0 now"),
    (2500000, "$2.5 million"), ("$18,530.00", "remit $18,530.00 today"),
])
def test_money_accepts_the_exact_figure(value, evidence):
    fr = _money(value, evidence)
    assert fr.ok, fr.reason


def test_contract_value_text_must_appear_in_the_evidence_with_its_figure():
    def one(value, evidence):
        return gl.validate_submission(sub({"contract_value": {"value": value, "evidence": [evidence]}}),
                                      CONTRACT, "contract").fields["contract_value"]
    assert one("$250,000", "a fee of $250,000").ok
    assert not one("$25,000", "a fee of $250,000").ok          # inside a longer figure
    assert not one("$250", "a fee of $250,000").ok
    assert not one("$250,000.50", "a fee of $250,000").ok
    assert not one("$1_000", "a fee of $250,000").ok
    assert not one("1e3", "a fee of $250,000").ok
    assert not one("a fee of", "a fee of $250,000").ok          # no figure at all


@pytest.mark.parametrize("value, evidence", [
    ("2001-05-14", "Date: May 3, 2001 14:02"),     # the day token 14 is the time of day
    ("2001-01-05", "Sent 11/5/2001"),              # numeric form inside a longer one
    ("2001-05-06", "Sent 15/6/01"),
    ("2001-05-14", "May 2001, page 14"),           # day not beside the month
    ("2001-05-14", "14 June 2001 and May 2001"),
    ("2001-05-14", "May 14"),                      # no year
    ("2001-05-14", "Date: May 14 at 10, 2001"),    # a time of day between the day and the year
    ("2001-05-14", "May 14 the year 2001"),        # "th" of another word is not an ordinal
])
def test_dates_need_digit_boundaries_and_the_day_beside_the_month(value, evidence):
    assert not gl._date_supported(value, evidence)


@pytest.mark.parametrize("value, evidence", [
    ("2001-05-14", "May 14th, 2001"), ("2001-05-14", "the 14th day of May, 2001"),
    ("2001-05-14", "14 May 2001"), ("2001-05-14", "May 14th 2001"),
    ("2001-05-14", "2001-05-14T09:02"), ("2001-01-05", "Sent 1/5/2001"),
    ("2024-03-27", "this 27 th day of March, 2024"), ("2017-02-21", "21 st day of February, 2017"),
])
def test_dates_accept_written_forms(value, evidence):
    assert gl._date_supported(value, evidence)


def test_party_roles_need_the_role_word_in_the_evidence():
    def roles(value, evidence):
        doc = CONTRACT + "\nAlpha Inc., the Suppliers\nAlpha Inc. is a supply house\n"
        return gl.validate_submission(sub({"party_roles": {"value": value, "evidence": [evidence]}}),
                                      doc, "contract").fields["party_roles"]
    assert not roles(["Alpha Inc.: licensee"], "Alpha Inc.").ok
    assert roles(["Alpha Inc.: supplier"], 'Alpha Inc. ("Supplier")').ok
    assert roles(["Alpha Inc.: supplier"], "Alpha Inc., the Suppliers").ok
    assert not roles(["Alpha Inc.: supplier"], "Alpha Inc. is a supply house").ok
    assert roles(["Alpha Inc.: other"], "Alpha Inc.").ok


def test_evidence_quote_is_capped_at_400_characters():
    long_text = "To: John Doe " + "word " * 120 + "\nSincerely"
    quote = long_text[:401]
    res = gl.validate_submission(sub({"recipient": {"value": "John Doe", "evidence": [quote]}}),
                                 long_text, "correspondence")
    assert "evidence quote too long" in res.fields["recipient"].reason
    short = gl.validate_submission(sub({"recipient": {"value": "John Doe", "evidence": [long_text[:400]]}}),
                                   long_text, "correspondence")
    assert short.fields["recipient"].ok


def test_non_default_closed_label_needs_a_three_token_quote():
    def urgency(value, quote, **extra):
        return gl.validate_submission(sub({"urgency": {"value": value, "evidence": [quote], **extra}}),
                                      EMAIL, "correspondence").fields["urgency"]
    assert not urgency("urgent", "remit").ok
    assert "3 tokens" in urgency("urgent", "remit").reason
    assert urgency("urgent", "Please remit $18,530.00").ok
    assert urgency("routine", "remit").ok  # the default needs no wording of its own


def test_locate_keeps_exact_spans_where_casefold_changes_length():
    text = "İstanbul is big. Straße"
    for quote, expected in (("STRASSE", "Straße"), ("İSTANBUL IS", "İstanbul is"), ("straße", "Straße")):
        span = gl.locate(quote, text)
        assert span is not None, quote
        assert text[span["start"]:span["end"]] == span["text"]
        if expected:
            assert span["text"] == expected
    assert gl.locate("big. strasse", text)["text"] == "big. Straße"
    assert gl.locate("not there ß", text) is None


def test_read_jsonl_splits_on_newline_only(tmp_path):
    rec = {"doc_id": "D", "value": "line\u2028sep\u2029para\u0085next"}
    gl.write_jsonl(tmp_path / "x.jsonl", [rec, {"doc_id": "E"}])
    assert gl.read_jsonl(tmp_path / "x.jsonl") == [rec, {"doc_id": "E"}]


def test_fields_that_are_not_an_object_fail_cleanly():
    for bad in ([], ["sender"], "sender", 3):
        res = gl.validate_submission({"doc_id": "D", "fields": bad}, EMAIL, "correspondence")
        assert not res.payload_valid and "fields is not an object" in res.payload_error
        assert res.fields == {}


def test_review_correction_keeps_the_original_label_and_needs_a_reviewer():
    rec = {"doc_id": "D", "field": "sender", "value": "Jane", "status": "disputed", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 4, "text": "Jane"}], "absent_reason": None,
           "labeler": {"model": "sonnet"}}
    out = gl.apply_review(rec, {"verdict": "correct", "value": "Jane Roe", "evidence": [], "presence": "populated",
                                "reviewer": OPUS})
    assert out["review"]["original"] == {
        "value": "Jane", "evidence": [{"start": 0, "end": 4, "text": "Jane"}], "presence": "populated",
        "absent_reason": None, "labeler": {"model": "sonnet"}}
    assert out["value"] == "Jane Roe"
    assert "original" not in gl.apply_review(rec, {"verdict": "accept", "reviewer": OPUS})["review"]
    with pytest.raises(ValueError, match="reviewer"):
        gl.apply_review(rec, {"verdict": "accept"})


def test_verify_catalog_flags_duplicate_label_ids_and_reads_the_supplementary_store(tmp_path):
    rec = {"doc_id": "D", "field": "recipient", "status": "near_gold", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}], "label_id": "abc"}
    gold = tmp_path / "gold"
    sha = gl.write_jsonl(gold / "c.jsonl", [rec, {**rec, "field": "sender"}])
    (gold / "MANIFEST.json").write_text(json.dumps({"schema": gl.SCHEMA, "files": {"c.jsonl": sha}}))
    assert any("duplicate label_id abc" in p for p in gl.verify_catalog(gold))

    supp = tmp_path / "supp"
    sha = gl.write_jsonl(supp / "c.jsonl", [{"kind": "gate_reject", "doc_id": "D", "field": "x", "reason": "r"},
                                            {"kind": "notes", "doc_id": "D"}])
    (supp / "MANIFEST.json").write_text(json.dumps({"schema": gl.SUPPLEMENTARY_SCHEMA, "files": {"c.jsonl": sha}}))
    assert gl.verify_catalog(supp) == []
    sha = gl.write_jsonl(supp / "c.jsonl", [{"kind": "mystery", "doc_id": "D"}])
    (supp / "MANIFEST.json").write_text(json.dumps({"schema": gl.SUPPLEMENTARY_SCHEMA, "files": {"c.jsonl": sha}}))
    assert any("unknown supplementary kind" in p for p in gl.verify_catalog(supp))


# --------------------------------------------------------------------------- scripts/gold_labels.py build

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gold_labels.py"


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gold_labels_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gold_labels_cli"] = mod
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


def _s(doc, role, fields):
    return {"doc_id": doc, "labeler": {"model": "test", "role": role}, "fields": fields}


RECIPIENT = {"recipient": {"value": "John Doe", "evidence": ["To: John Doe"]}}
RECIPIENT2 = {"recipient": {"value": "John Doe", "evidence": ["To: John Doe\nSubject"]}}  # same label, own quote
SENDER = {"sender": {"value": "Jane Roe", "evidence": ["From: Jane Roe"]}}


def test_build_refuses_a_file_used_as_both_passes(cli, capsys):
    _, write, build, _ = cli
    both = write("both.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    assert build("--label", both, "--check", both) == 1
    assert "both --label and --check" in capsys.readouterr().err


def test_build_refuses_wrong_roles_and_duplicate_documents(cli, capsys):
    _, write, build, _ = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    chk_wrong = write("chk.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    assert build("--label", lab, "--check", chk_wrong) == 1
    assert "role is 'label', a --check submission needs 'check'" in capsys.readouterr().err
    lab_wrong = write("lab2.jsonl", [_s("DOC-1", "check", RECIPIENT)])
    assert build("--label", lab_wrong) == 1
    assert "a --label submission needs 'label'" in capsys.readouterr().err
    dup_a, dup_b = write("a.jsonl", [_s("DOC-1", "label", RECIPIENT)]), write("b.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    assert build("--label", dup_a, dup_b) == 1
    assert "appears twice in the --label files" in capsys.readouterr().err
    chk_a, chk_b = write("ca.jsonl", [_s("DOC-1", "check", RECIPIENT)]), write("cb.jsonl", [_s("DOC-1", "check", RECIPIENT)])
    assert build("--label", lab, "--check", chk_a, chk_b) == 1
    assert "appears twice in the --check files" in capsys.readouterr().err
    ov_a, ov_b = write("oa.jsonl", [_s("DOC-1", "label", RECIPIENT)]), write("ob.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    assert build("--label", lab, "--override", ov_a, ov_b) == 1
    assert "appears twice in the --override files" in capsys.readouterr().err


def test_build_two_independent_passes_agree_to_near_gold(cli):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    chk = write("chk.jsonl", [_s("DOC-1", "check", RECIPIENT2)])
    assert build("--label", lab, "--check", chk) == 0
    recs = gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")
    assert [r["status"] for r in recs] == ["near_gold"]
    assert gl.verify_catalog(tmp / "gold") == [] and gl.verify_catalog(tmp / "supp") == []


def test_override_replaces_only_when_the_override_passes_the_gate(cli):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", {**RECIPIENT, **SENDER})])
    bad = {"recipient": {"value": "Somebody Else", "evidence": ["To: John Doe"]},
           "sender": {"value": "Jane Roe, VP Finance, Acme Corp", "evidence": ["Jane Roe\nVP Finance, Acme Corp"]}}
    ov = write("ov.jsonl", [{**_s("DOC-1", "label", bad), "labeler": {"model": "relabel", "role": "label"}}])
    assert build("--label", lab, "--override", ov) == 0
    by_field = {r["field"]: r for r in gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")}
    assert by_field["recipient"]["value"] == "John Doe"                       # failing override: old label stays
    assert by_field["recipient"]["labeler"]["model"] == "test"
    assert by_field["sender"]["value"] == "Jane Roe, VP Finance, Acme Corp"  # passing override replaces
    assert by_field["sender"]["labeler"]["model"] == "relabel"
    supp = gl.read_jsonl(tmp / "supp" / "correspondence.jsonl")
    assert any(r["kind"] == "gate_reject" and r["field"] == "recipient" for r in supp)


def test_build_refuses_unmatched_and_reviewerless_review_decisions(cli, capsys):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    orphan = write("rv.jsonl", [{"doc_id": "DOC-9", "field": "recipient", "verdict": "accept",
                                 "reviewer": OPUS}])
    assert build("--label", lab, "--review", orphan) == 1
    err = capsys.readouterr().err
    assert "match no catalog record" in err and "DOC-9.recipient" in err
    anon = write("rv2.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept"}])
    assert build("--label", lab, "--review", anon) == 1
    assert "has no reviewer" in capsys.readouterr().err
    ok = write("rv3.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept",
                              "reviewer": OPUS}])
    assert build("--label", lab, "--review", ok) == 0
    assert gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]["status"] == "near_gold"


def test_check_accepts_the_supplementary_directory(cli, capsys):
    mod, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", {"recipient": {"value": "Nobody", "evidence": ["To: John Doe"]}})])
    assert build("--label", lab) == 0
    assert mod.main(["check", "--dir", str(tmp / "supp")]) == 0
    assert capsys.readouterr().out.strip().endswith("ok")


def test_list_fields_may_quote_a_long_cc_block_but_names_may_not():
    names = [f"Person{i} Surname{i}" for i in range(40)]
    block = "cc: " + ", ".join(names)
    text = "From: A\n" + block + "\nbody"
    assert 400 < len(block) < 1500
    ok = gl.validate_submission(sub({"additional_recipients": {"value": names, "evidence": [block]}}),
                                text, "correspondence")
    assert ok.fields["additional_recipients"].ok, ok.fields["additional_recipients"].reason
    bad = gl.validate_submission(sub({"sender": {"value": "Person1 Surname1", "evidence": [block]}}),
                                 text, "correspondence")
    assert "too long" in bad.fields["sender"].reason


# --------------------------------------------------------------------------- second adversarial review


def test_year_must_belong_to_the_same_date_expression_as_the_day_and_month():
    two_dates = "Agreement made May 14, 2019. Term ends December 31, 2020."
    assert not gl._date_supported("2020-05-14", two_dates)
    assert gl._date_supported("2019-05-14", two_dates)
    assert gl._date_supported("2020-12-31", two_dates)
    assert not gl._date_supported("2020-05-14", "May 14, 2019 and 14 June 2020")
    assert not gl._date_supported("2020-05-14", "On 14 May 2019 or by 2020")
    for text in ("May 14, 2020", "14 May 2020", "the 14th day of May, 2020", "May 14th 2020",
                 "Sent: Monday, May 14, 2020 9:02 AM", "14th of May 2020"):
        assert gl._date_supported("2020-05-14", text), text


def _near_gold(**extra):
    rec = {"doc_id": "D", "field": "recipient", "status": "near_gold", "use_as_truth": False,
           "presence": "populated", "evidence": [{"start": 0, "end": 1, "text": "x"}]}
    return {**rec, **extra}


def _problems(tmp_path, *recs):
    sha = gl.write_jsonl(tmp_path / "c.jsonl", [{**r, "label_id": f"id{i}"} for i, r in enumerate(recs)])
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"schema": gl.SCHEMA, "files": {"c.jsonl": sha}}))
    return gl.verify_catalog(tmp_path)


def test_verify_catalog_enforces_the_near_gold_invariant(tmp_path):
    good = [
        _near_gold(check={"agrees": True, "gate_ok": True}),
        _near_gold(review={"verdict": "accept", "reviewer": OPUS}),
        _near_gold(review={"verdict": "correct", "reviewer": OPUS},
                   value_source={"kind": "review_correction", "labeler": OPUS}),
        _near_gold(review={"verdict": "accept_check", "reviewer": OPUS},
                   value_source={"kind": "check_pass", "labeler": {"model": "m", "role": "check"}}),
    ]
    assert _problems(tmp_path, *good) == []
    bad = [
        _near_gold(),                                                                  # nothing settles it
        _near_gold(check={"agrees": True, "gate_ok": False}),
        _near_gold(check={"agrees": False, "gate_ok": True}),
        _near_gold(review={"verdict": "accept", "reviewer": {"model": "opus"}}),       # no role
        _near_gold(review={"verdict": "accept", "reviewer": {"role": "reviewer"}}),    # no model
        _near_gold(review={"verdict": "accept", "reviewer": "opus"}),
        _near_gold(review={"verdict": "reject", "reviewer": OPUS}),
        _near_gold(review={"verdict": "correct", "reviewer": OPUS}),                   # no value_source
        _near_gold(presence="populated", evidence=[], check={"agrees": True, "gate_ok": True}),
    ]
    for rec in bad:
        found = _problems(tmp_path, rec)
        assert found, rec
    assert any("near_gold" in p for p in _problems(tmp_path, bad[0]))
    assert any("populated without evidence" in p for p in _problems(tmp_path, bad[-1]))


def _built(cli, label_fields, check_fields, reviews=None, extra=()):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", label_fields)])
    chk = write("chk.jsonl", [{**_s("DOC-1", "check", check_fields), "labeler": {"model": "chk-model", "role": "check"}}])
    args = ["--label", lab, "--check", chk, *extra]
    if reviews is not None:
        args += ["--review", write("rv.jsonl", reviews)]
    return build(*args)


DISPUTE_CHECK = {"recipient": {"value": "Jane Roe", "evidence": ["From: Jane Roe"]}}


def test_overlay_refuses_a_failing_catalog_and_a_foreign_out_dir(cli, capsys):
    mod, write, build, tmp = cli
    assert _built(cli, RECIPIENT, RECIPIENT2) == 0
    gold = tmp / "gold"
    # a near_gold record with nothing behind it fails verify, and so does the overlay
    path = gold / "correspondence.jsonl"
    rec = gl.read_jsonl(path)[0]
    sha = gl.write_jsonl(path, [{**rec, "check": {"agrees": False, "gate_ok": True}}])
    manifest = json.loads((gold / "MANIFEST.json").read_text())
    manifest["files"]["correspondence.jsonl"] = sha
    (gold / "MANIFEST.json").write_text(json.dumps(manifest))
    capsys.readouterr()
    assert mod.main(["overlay", "--out", str(tmp / "ov")]) == 1
    assert "near_gold" in capsys.readouterr().err
    assert not (tmp / "ov").exists()

    assert _built(cli, RECIPIENT, RECIPIENT2) == 0
    for out in (gold, tmp / "supp", tmp / "supp" / ".." / "gold"):
        before = sorted(p.name for p in Path(out).iterdir())
        assert mod.main(["overlay", "--out", str(out)]) == 1, out
        assert sorted(p.name for p in Path(out).iterdir()) == before
        assert "overlay refused" in capsys.readouterr().err
    other = tmp / "other"
    other.mkdir()
    (other / "MANIFEST.json").write_text(json.dumps({"schema": "something/else"}))
    (other / "keep.jsonl").write_text("{}\n")
    assert mod.main(["overlay", "--out", str(other)]) == 1
    assert (other / "keep.jsonl").exists() and "not 'mailroom-interim-labels/v1'" in capsys.readouterr().err
    loose = tmp / "loose"
    loose.mkdir()
    (loose / "keep.jsonl").write_text("{}\n")
    assert mod.main(["overlay", "--out", str(loose)]) == 1
    assert (loose / "keep.jsonl").exists()
    assert mod.main(["overlay", "--dir", str(tmp / "supp"), "--out", str(tmp / "ov2")]) == 1
    # a fresh directory, and an earlier overlay, are fine
    assert mod.main(["overlay", "--out", str(tmp / "ov")]) == 0
    assert mod.main(["overlay", "--out", str(tmp / "ov")]) == 0
    assert json.loads((tmp / "ov" / "MANIFEST.json").read_text())["schema"] == gl.OVERLAY_SCHEMA


def test_build_refuses_a_check_that_copies_the_label(cli, capsys):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", {**RECIPIENT, **SENDER})])
    # the same fields, written in another key order: still byte-identical once sorted
    same = {**SENDER, **RECIPIENT}
    chk = write("chk.jsonl", [_s("DOC-1", "check", same)])
    assert build("--label", lab, "--check", chk) == 1
    assert "identical" in capsys.readouterr().err
    own = write("own.jsonl", [_s("DOC-1", "check", {**RECIPIENT2, **SENDER})])
    assert build("--label", lab, "--check", own) == 0


def test_build_refuses_one_batch_out_of_identical_file_content(cli, capsys):
    _, write, build, tmp = cli
    batch = {"model": "m", "batch": "correspondence-000"}
    lab = write("lab.jsonl", [{**_s("DOC-1", "label", RECIPIENT), "labeler": {**batch, "role": "label"}}])
    # a check whose fields differ is fine when the batch differs ...
    other = write("c1.jsonl", [{**_s("DOC-1", "check", RECIPIENT2), "labeler": {**batch, "role": "check", "batch": "x"}}])
    assert build("--label", lab, "--check", other) == 0
    # ... and when the batch is shared but the files are different
    shared = write("c2.jsonl", [{**_s("DOC-1", "check", RECIPIENT2), "labeler": {**batch, "role": "check"}}])
    assert build("--label", lab, "--check", shared) == 0
    # the same batch out of a copy of the label file is refused (the role check fires too, so
    # exercise the guard directly)
    import shutil
    copy = tmp / "copy.jsonl"
    shutil.copy(lab, copy)
    problems = sys.modules["gold_labels_cli"]._independence_problems([lab], [str(copy)])
    assert any("same content" in p for p in problems), problems


def test_money_needs_the_quote_to_show_a_figure_as_money():
    def money(value, evidence):
        return gl.validate_submission(sub({"demand_amount": {"value": value, "evidence": [evidence]}}),
                                      evidence, "correspondence").fields["demand_amount"].ok
    assert not money(2020, "Dated May 14, 2020")
    assert not money(14, "Dated May 14, 2020")
    assert not money(2001, "Meeting on 5/14/2001 at 2001 Ross Avenue")
    for value, quote in ((14, "$14"), (14, "USD 14"), (14, "14 dollars"), (14, "US$14"), (14, "£14"),
                         (14, "14 USD"), (1200, "Please pay 1,200 by Friday"), (1200, "balance of 1,200"),
                         (1200, "the total is 1,200"), (14, "fee 14"), (14, "owes 14")):
        assert money(value, quote), quote
    # the word must sit in the same quote as the figure
    res = gl.validate_submission(sub({"demand_amount": {"value": 1200, "evidence": ["Please pay", "due 1,200"]}}),
                                 "Please pay\n\ndue 1,200", "correspondence")
    assert not res.fields["demand_amount"].ok
    contract = gl.validate_submission(sub({"contract_value": {"value": "250,000", "evidence": ["Dated 250,000"]}}),
                                      "Dated 250,000", "contract")
    assert not contract.fields["contract_value"].ok


def test_values_agree_treats_a_one_sided_negation_as_disagreement():
    assert not gl.values_agree(["Contact the sender if you can attend"], ["Contact the sender if you cannot attend or do not"],
                               "entity_list")
    assert not gl.values_agree(["Please do not forward this"], ["Please forward this"], "entity_list")
    assert not gl.values_agree(["Notify us if payment is made without notice"], ["Notify us if payment is made with notice"],
                               "entity_list:free_text")
    assert gl.values_agree(["Please do not forward this"], ["Do not forward this please"], "entity_list")
    assert not gl.values_agree("pay within 30 days, no extensions", "pay within 30 days, extensions allowed", "free_text")
    assert not gl.values_agree("never assign this agreement", "assign this agreement", "free_text")
    assert gl.values_agree("no extensions, pay within 30 days", "pay within 30 days, no extensions", "free_text")
    # the name rules are unchanged
    assert gl.values_agree("Jane Roe", "Jane Roe, VP Finance", "name")
    assert gl.values_agree(["No Name Corp"], ["No Name Corp, Inc"], "entity_list:name")


def test_reviewer_must_name_a_model_and_a_role(cli, capsys):
    _, write, build, tmp = cli
    for reviewer in ({"model": "opus"}, {"role": "reviewer"}, {"model": "", "role": "r"}, "opus", ["opus"]):
        review = {"doc_id": "DOC-1", "field": "recipient", "verdict": "accept", "reviewer": reviewer}
        assert _built(cli, RECIPIENT, RECIPIENT2, [review]) == 1, reviewer
        assert "reviewer" in capsys.readouterr().err
    with pytest.raises(ValueError, match="reviewer"):
        gl.apply_review({"status": "disputed"}, {"verdict": "accept", "reviewer": {"model": "opus"}})


def test_correct_and_accept_check_record_who_produced_the_value(cli):
    _, write, build, tmp = cli
    entry = {"value": "Jane Roe", "evidence": ["From: Jane Roe"]}
    reviews = [{"doc_id": "DOC-1", "field": "recipient", "verdict": "correct", "reviewer": OPUS, "entry": entry}]
    assert _built(cli, RECIPIENT, DISPUTE_CHECK, reviews) == 0
    rec = gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]
    assert rec["review"]["verdict"] == "correct" and rec["value"] == "Jane Roe"
    assert rec["value_source"] == {"kind": "review_correction", "labeler": OPUS}
    assert rec["review"]["original"]["value"] == "John Doe"
    assert gl.verify_catalog(tmp / "gold") == []

    reviews = [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept_check", "reviewer": OPUS}]
    assert _built(cli, RECIPIENT, DISPUTE_CHECK, reviews) == 0
    rec = gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]
    assert rec["review"]["verdict"] == "accept_check"           # not rewritten into "correct"
    assert rec["value"] == "Jane Roe"
    assert rec["value_source"] == {"kind": "check_pass", "labeler": {"model": "chk-model", "role": "check"}}
    assert rec["review"]["original"]["value"] == "John Doe"
    assert "check_labeler" not in rec["review"]
    assert gl.verify_catalog(tmp / "gold") == []
    over = gl.overlay_records([rec], gate_run="g")
    assert over[0]["labels"]["recipient"]["basis"] == "near_gold:opus_reviewed_accept_check"

    reviews = [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept", "reviewer": OPUS}]
    assert _built(cli, RECIPIENT, DISPUTE_CHECK, reviews) == 0
    assert "value_source" not in gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]


def test_overlay_carries_labeler_and_near_empty_per_label():
    base = {"doc_class": "correspondence", "doc_id": "D", "content_sha256": "ab" * 32, "presence": "populated",
            "evidence": [], "status": "near_gold"}
    first = {"model": "a", "role": "label"}
    other = {"model": "b", "role": "label"}
    out = gl.overlay_records([
        {**base, "field": "recipient", "value": "X", "labeler": first, "near_empty": False},
        {**base, "field": "sender", "value": "Y", "labeler": other, "near_empty": True,
         "review": {"verdict": "correct"}, "value_source": {"kind": "review_correction", "labeler": OPUS}},
    ], gate_run="g")
    labels = out[0]["labels"]
    assert labels["recipient"]["labeler"] == first and labels["recipient"]["near_empty"] is False
    assert labels["sender"]["labeler"] == other and labels["sender"]["near_empty"] is True
    assert labels["sender"]["value_source"]["kind"] == "review_correction"
    assert out[0]["source"]["labeler"] == first and out[0]["source"]["near_empty"] is False   # first, for EDA


@pytest.mark.parametrize("review, message", [
    ({"field": "recipient", "reviewer": OPUS}, "has no verdict"),
    ({"field": "recipient", "reviewer": OPUS, "verdict": "maybe"}, "unknown verdict"),
    ({"field": "recipient", "reviewer": OPUS, "verdict": "correct"}, "needs an entry"),
])
def test_malformed_review_lines_exit_1_with_a_message(cli, capsys, review, message):
    _, write, build, _ = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    rv = write("rv.jsonl", [{"doc_id": "DOC-1", **review}])
    assert build("--label", lab, "--review", rv) == 1
    assert message in capsys.readouterr().err


def test_duplicate_review_keys_exit_1(cli, capsys):
    _, write, build, _ = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    one = {"doc_id": "DOC-1", "field": "recipient", "verdict": "accept", "reviewer": OPUS}
    rv = write("rv.jsonl", [one, {**one, "verdict": "reject"}])
    assert build("--label", lab, "--review", rv) == 1
    assert "duplicate review for DOC-1.recipient" in capsys.readouterr().err
    assert build("--label", lab, "--review", rv, write("rv2.jsonl", [one])) == 1
    assert "duplicate review" in capsys.readouterr().err


def test_a_class_without_an_extraction_schema_is_a_clean_reject():
    res = gl.validate_submission(sub({"recipient": {"value": "John Doe", "evidence": ["To: John Doe"]}}),
                                 EMAIL, "no_such_class")
    assert not res.payload_valid and "no extraction schema" in res.payload_error
    assert not res.fields["recipient"].ok and "no extraction schema" in res.fields["recipient"].reason
    doc = {"doc_id": "DOC-1", "doc_class": "no_such_class"}
    records, rejects = gl.reconcile(doc, EMAIL, res, None, {"model": "a"}, None, {})
    assert records == [] and rejects[0]["field"] == "recipient"
    assert gl.validate_submission({"doc_id": "D"}, EMAIL, "no_such_class").fields == {}


def test_two_digit_years_only_inside_1950_to_2049():
    assert gl._date_supported("2001-05-14", "5/14/01")
    assert gl._date_supported("1950-05-14", "05/14/50")
    assert gl._date_supported("2049-05-14", "14-May-49")
    assert not gl._date_supported("1949-05-14", "5/14/49")
    assert not gl._date_supported("2050-05-14", "5/14/50")
    assert not gl._date_supported("1850-05-14", "05/14/50")
    assert gl._date_supported("1850-05-14", "05/14/1850")


def test_jsonl_is_ascii_so_line_separators_cannot_split_a_record(tmp_path):
    rec = {"doc_id": "D", "value": "a b c\u0085d é"}
    gl.write_jsonl(tmp_path / "x.jsonl", [rec])
    raw = (tmp_path / "x.jsonl").read_text(encoding="utf-8")
    assert raw.isascii() and len(raw.splitlines()) == 1
    assert gl.read_jsonl(tmp_path / "x.jsonl") == [rec]


def test_contractions_count_as_negation_on_both_sides():
    a = ["Tell the sender if you did not get the invitation or cannot attend"]
    b = ["If you didn't get the invitation or can't attend, please let me know"]
    assert gl.values_agree(a, b, "entity_list")
    assert not gl.values_agree(["Pay the invoice"], ["Don't pay the invoice"], "entity_list")


# --------------------------------------------------------------------------- bot-review fixes (PR #323)


def test_a_malformed_comma_group_is_not_a_figure():
    assert not _money(12.0, "$12,34").ok
    assert _money(12340.0, "$12,340").ok


def test_numbers_of_a_written_date_are_not_money_by_a_payment_word_alone():
    for value in (2020.0, 14.0):
        assert not _money(value, "Please pay by May 14, 2020").ok, value
    assert not _money(2020.0, "Payment due 5/14/2020").ok
    assert _money(500.0, "Please pay 500 by May 14, 2020").ok
    assert _money(2020.0, "Please pay $2,020 by May 14, 2020").ok


def test_unambiguous_day_first_hyphen_dates():
    assert gl._date_supported("2001-03-27", "Date: 27-03-2001")
    assert not gl._date_supported("2001-11-02", "Date: 02-11-2001")


def test_an_accept_on_a_relabelled_field_must_name_the_current_value(cli, capsys):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", SENDER)])
    new = {"sender": {"value": "Jane Roe, VP Finance, Acme Corp", "evidence": ["Jane Roe\nVP Finance, Acme Corp"]}}
    ov = write("ov.jsonl", [{**_s("DOC-1", "label", new), "labeler": {"model": "relabel", "role": "label"}}])
    stale = write("rv.jsonl", [{"doc_id": "DOC-1", "field": "sender", "verdict": "accept", "reviewer": OPUS}])
    assert build("--label", lab, "--override", ov, "--review", stale) == 1
    assert "does not name the current value" in capsys.readouterr().err
    old = write("rv2.jsonl", [{"doc_id": "DOC-1", "field": "sender", "verdict": "accept", "reviewer": OPUS,
                               "value": "Jane Roe"}])
    assert build("--label", lab, "--override", ov, "--review", old) == 1
    named = write("rv3.jsonl", [{"doc_id": "DOC-1", "field": "sender", "verdict": "accept", "reviewer": OPUS,
                                 "value": "Jane Roe, VP Finance, Acme Corp"}])
    assert build("--label", lab, "--override", ov, "--review", named) == 0
    assert gl.read_jsonl(tmp / "gold" / "correspondence.jsonl")[0]["status"] == "near_gold"


def test_a_date_must_sit_whole_in_one_quote():
    text = "Sent May 14, 2019. Archived December 31, 2020."
    res = gl.validate_submission(sub({"communication_date": {"value": "2020-05-14",
                                                             "evidence": ["May 14", "2020"]}}), text, "correspondence")
    assert not res.fields["communication_date"].ok
    res = gl.validate_submission(sub({"communication_date": {"value": "2019-05-14",
                                                             "evidence": ["May 14, 2019"]}}), text, "correspondence")
    assert res.fields["communication_date"].ok


def test_party_roles_agree_only_when_each_party_has_the_same_role():
    ft = "entity_list:free_text"
    a = ["Alpha Inc.: supplier", "Beta LLC: customer"]
    assert not gl.values_agree(a, ["Alpha Inc.: customer", "Beta LLC: supplier"], ft)
    assert gl.values_agree(a, ["Beta LLC: customer", "Alpha Inc: supplier"], ft)
    assert gl.values_agree(["PRIMEEVERGY CORPORATION: other"], ["PRIMEEVERG CORPORATION: other"], ft)
    assert not gl.values_agree(a, ["Alpha Inc.: supplier"], ft)
    # Overlapping names pair by name first, so their roles cannot swap.
    assert not gl.values_agree(["Alpha Inc: supplier", "Alpha Inc Services: customer"],
                               ["Alpha Inc: customer", "Alpha Inc Services: supplier"], ft)
    assert gl.values_agree(["Alpha Inc: supplier", "Alpha Inc Services: customer"],
                           ["Alpha Inc Services: customer", "Alpha Inc: supplier"], ft)
    # Ambiguous name pairings (a tie) never agree, in either list order.
    left = ["Alpha Inc: supplier", "Alpha Inc Services: customer"]
    right = ["Alpha Inc Services LLC: supplier", "Alpha: customer"]
    assert not gl.values_agree(left, right, ft)
    assert not gl.values_agree(left, right[::-1], ft)


def test_build_refuses_missing_input_files_and_keeps_the_catalog(cli, capsys):
    _, write, build, tmp = cli
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    assert build("--label", lab) == 0
    before = (tmp / "gold" / "correspondence.jsonl").read_text()
    assert build("--label", str(tmp / "missing.jsonl")) == 1
    assert "input files not found" in capsys.readouterr().err
    assert build("--label", lab, "--review", str(tmp / "nope.jsonl")) == 1
    assert (tmp / "gold" / "correspondence.jsonl").read_text() == before


def test_build_refuses_text_that_does_not_match_its_content_hash(cli, monkeypatch):
    mod, write, build, _ = cli
    rows = [{"document_id": "DOC-1", "filename": "f1.txt", "expected": "correspondence",
             "expected_subclass": "email", "content_sha256": "0" * 64}]
    monkeypatch.setattr(mod, "_load_corpus", lambda _corpus: (rows, {"f1.txt": EMAIL}))
    lab = write("lab.jsonl", [_s("DOC-1", "label", RECIPIENT)])
    with pytest.raises(SystemExit, match="does not match its content_sha256"):
        build("--label", lab)


# --------------------------------------------------------------------------- Dojo-parseable contract values


def test_a_plain_dollar_figure_may_restate_a_scaled_figure_exactly():
    assert gl._money_text_supported("$5,000,000", "a fee of $5 million to Merrill")
    assert gl._money_text_supported("$2,500,000", "up to $2.5 million")
    assert not gl._money_text_supported("$5", "a fee of $5 million")             # only the scaled amount
    assert not gl._money_text_supported("$50,000,000", "a fee of $5 million")
    assert not gl._money_text_supported("$5,000,000", "issued 5 million shares")  # not money in the quote
    assert gl._money_text_supported("$5 million", "a fee of $5 million")          # as written, as before


def test_money_text_parses_follows_the_dojo_scorer():
    pytest.importorskip("llm_dojo_scoring.scoring.field_scoring")
    for ok in ("$5,000,000", "$400,000.00", "$0.05", "$40", "$5M", None, ""):
        assert gl.money_text_parses(ok), ok
    for bad in ("$5 million", "US$55,000", "$40 per hour"):
        assert not gl.money_text_parses(bad), bad


def test_verify_catalog_flags_a_near_gold_contract_value_the_dojo_cannot_parse(tmp_path):
    pytest.importorskip("llm_dojo_scoring.scoring.field_scoring")
    reviewed = {"review": {"verdict": "accept", "reviewer": OPUS}}
    base = _near_gold(doc_class="contract", field="contract_value", **reviewed)
    assert _problems(tmp_path, {**base, "value": "$5,000,000"}) == []
    found = _problems(tmp_path, {**base, "value": "$5 million"})
    assert any("not a figure the Dojo parses" in p for p in found), found
    # Only near_gold is checked: a disputed phrase waits for its review.
    assert _problems(tmp_path, {**base, "value": "$5 million", "status": "disputed", "review": None}) == []


def test_review_command_settles_a_disputed_record_in_place(cli, capsys):
    mod, write, _, tmp = cli
    assert _built(cli, RECIPIENT, DISPUTE_CHECK) == 0
    gold = tmp / "gold"
    assert [r["status"] for r in gl.read_jsonl(gold / "correspondence.jsonl")
            if r["field"] == "recipient"] == ["disputed"]
    review = write("fix.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "correct", "reviewer": OPUS,
                                  "note": "the To line", "entry": {"value": "John Doe", "evidence": ["To: John Doe"]}}])
    assert mod.main(["review", "--corpus", "ignored", "--review", review]) == 0
    rec = next(r for r in gl.read_jsonl(gold / "correspondence.jsonl") if r["field"] == "recipient")
    assert rec["status"] == "near_gold" and rec["value"] == "John Doe" and rec["review"]["verdict"] == "correct"
    man = json.loads((gold / "MANIFEST.json").read_text())
    assert "fix.jsonl" in man["sources"]["review"] and man["reviewed_at"]
    assert gl.verify_catalog(gold) == []
    before = (gold / "correspondence.jsonl").read_text()
    capsys.readouterr()
    # a second review of the same record, a reject, and a correction the gate refuses all leave the catalog alone
    assert mod.main(["review", "--corpus", "ignored", "--review", review]) == 1
    assert "already reviewed" in capsys.readouterr().err
    reject = write("rej.jsonl", [{"doc_id": "DOC-1", "field": "sender", "verdict": "reject", "reviewer": OPUS}])
    assert mod.main(["review", "--corpus", "ignored", "--review", reject]) == 1
    assert "accept or correct" in capsys.readouterr().err
    assert (gold / "correspondence.jsonl").read_text() == before


def test_review_command_refuses_text_that_changed_since_labelling(cli, capsys, monkeypatch):
    mod, write, _, _ = cli
    assert _built(cli, RECIPIENT, DISPUTE_CHECK) == 0
    rows, _ = mod._load_corpus("x")
    monkeypatch.setattr(mod, "_load_corpus", lambda _c: (rows, {"f1.txt": EMAIL + "edited", "f2.txt": EMAIL}))
    review = write("fix.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "correct", "reviewer": OPUS,
                                  "note": "n", "entry": {"value": "John Doe", "evidence": ["To: John Doe"]}}])
    assert mod.main(["review", "--corpus", "ignored", "--review", review]) == 1
    assert "differs from the label's" in capsys.readouterr().err


def test_review_command_accept_must_name_the_current_value(cli, capsys):
    mod, write, _, tmp = cli
    assert _built(cli, RECIPIENT, DISPUTE_CHECK) == 0
    bare = write("acc.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept", "reviewer": OPUS}])
    assert mod.main(["review", "--corpus", "ignored", "--review", bare]) == 1
    assert "does not name the current value" in capsys.readouterr().err
    named = write("acc2.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "accept", "reviewer": OPUS,
                                  "value": "John Doe"}])
    assert mod.main(["review", "--corpus", "ignored", "--review", named]) == 0


def test_review_command_writes_nothing_when_the_reviewed_catalog_fails(cli, capsys, monkeypatch):
    mod, write, _, tmp = cli
    assert _built(cli, RECIPIENT, DISPUTE_CHECK) == 0
    gold = tmp / "gold"
    before = {p.name: p.read_bytes() for p in gold.iterdir()}
    real = gl.verify_catalog
    # The committed catalog verifies; the staged, reviewed one does not.
    monkeypatch.setattr(gl, "verify_catalog", lambda d: real(d) if Path(d) == gold else ["c.jsonl: staged failure"])
    review = write("fix.jsonl", [{"doc_id": "DOC-1", "field": "recipient", "verdict": "correct", "reviewer": OPUS,
                                  "note": "n", "entry": {"value": "John Doe", "evidence": ["To: John Doe"]}}])
    capsys.readouterr()
    assert mod.main(["review", "--corpus", "ignored", "--review", review]) == 1
    assert "nothing was written" in capsys.readouterr().err
    assert {p.name: p.read_bytes() for p in gold.iterdir()} == before
    assert not [p for p in tmp.iterdir() if p.name.startswith(".gold-review-")]
    # Once the catalog passes, the same review applies (it was never recorded as done).
    monkeypatch.setattr(gl, "verify_catalog", real)
    assert mod.main(["review", "--corpus", "ignored", "--review", review]) == 0
