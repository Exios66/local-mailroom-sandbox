"""scripts/stage_label_overlay.py: assist join rules, Hub-delta overlay and override sign-off."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage_label_overlay.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("stage_label_overlay", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TEXT = ("This Agreement renews for one (1) year periods unless either Party notifies the other Party "
        "not less than six (6) months before the end of the term. Either party may terminate upon "
        "ninety (90) days' prior written notice. For material breach, written notice and at least "
        "sixty (60) days to cure.")


@pytest.mark.parametrize("phrase, expected", [
    ("at least sixty 90 days", True), ("eighty (180) days", False), ("with 60 days", False),
    ("sixty (60) days", False), ("Thirty (30) business days", False), ("forty-five (45) days", False),
    ("forty-five 40 days", True),
])
def test_garbled(mod, phrase, expected):
    assert mod.garbled(phrase) is expected


def test_assist_terms_add_only_grounded_notice_periods(mod):
    assist = ("one (1) year periods unless either Party notifies the other Party not less than six (6) "
              "months before the end; upon ninety (90) days' prior written notice; written notice and "
              "at least sixty (60) days to cure")
    extra, refused = mod.assist_notice_terms(assist, "ninety (90) days", TEXT)
    assert extra == ["not less than six (6) months"]
    assert any(r.startswith("not a notice period: one (1) year") for r in refused)
    assert any(r.startswith("cure or breach period") for r in refused)


def test_assist_term_must_occur_in_text(mod):
    extra, refused = mod.assist_notice_terms("at least forty-five (45) days prior notice", "", TEXT)
    assert extra == [] and refused == ["not in document text: at least forty-five (45) days"]


def _cell(**kw):
    base = {"document_id": "DOC-1", "doc_class": "contract", "field": "f", "value": "v", "presence": "populated",
            "chosen_source": "interim_reviewed", "agreeing_sources": "interim_reviewed", "agreement": "1-of-2",
            "rule": "weighted_vote", "conflict": "False", "needs_human": "False", "evidence": "[]", "votes": "{}"}
    return base | kw


def test_overlay_is_the_hub_delta_and_flags_overrides(mod):
    prov = [
        _cell(field="a", chosen_source="hub_v9.3", agreeing_sources="hub_v9.3", votes='{"hub_v9.3": "v"}'),
        _cell(field="b", votes='{"hub_v9.3": "old", "interim_reviewed": "v"}'),
        _cell(field="c", votes='{"near_gold_reviewed": "v"}'),
        _cell(field="d", presence="unlabeled"),
        _cell(field="e", agreeing_sources="hub_v9.3|interim_reviewed", votes='{"hub_v9.3": "v"}'),
    ]
    overlay = mod.overlay_records(prov, {"DOC-1": "sha"})
    labels = overlay["contract"][0]["labels"]
    assert set(labels) == {"b", "c"}
    assert labels["b"]["override"] is True and labels["c"]["override"] is False
    assert overlay["contract"][0]["content_sha256"] == "sha"
    signoff = mod.signoff_rows(prov)
    assert [(r["field"], r["hub_v9_3_value"], r["decided_by"]) for r in signoff] == [("b", "old", "")]


def test_join_fills_and_extends_notice_cells(mod):
    cols = ["document_id", "doc_class", "fields_targeted", "fields_labeled", "label_completeness",
            "termination_notice_period", "duplicate_of"]
    rows = [
        {"document_id": "DOC-1", "doc_class": "contract", "fields_targeted": "4", "fields_labeled": "2",
         "label_completeness": "0.5", "termination_notice_period": "ninety (90) days", "duplicate_of": ""},
        {"document_id": "DOC-2", "doc_class": "contract", "fields_targeted": "4", "fields_labeled": "1",
         "label_completeness": "0.25", "termination_notice_period": "", "duplicate_of": "DOC-1"},
    ]
    prov = [_cell(document_id="DOC-1", field="termination_notice_period", value="ninety (90) days",
                  chosen_source="cuad_span", agreeing_sources="cuad_span"),
            _cell(document_id="DOC-2", field="termination_notice_period", value="", presence="unlabeled",
                  chosen_source="", agreeing_sources="")]
    comp = [{"doc_class": "contract", "field": "termination_notice_period", "documents": "2",
             "labeled_hub_v9_3": "0", "labeled_repaired": "1", "populated": "1", "documented_absence": "0",
             "unlabeled": "1", "disputed_unresolved": "0", "completeness_hub_v9_3": "0.0",
             "completeness_repaired": "0.5", "conflicts": "0", "needs_human": "0", "top_source": "cuad_span"}]
    assist = [dict(rows[0], termination_notice_period="notifies the other Party not less than six (6) months before"),
              dict(rows[1], termination_notice_period="upon ninety (90) days' prior written notice", duplicate_of="DOC-9")]
    builder = {"labels": (cols, rows), "provenance": (list(prov[0]), prov), "completeness": (list(comp[0]), comp)}
    out = mod.join(builder, assist, {"DOC-1": TEXT, "DOC-2": TEXT})
    _, joined = out["labels"]
    assert joined[0]["termination_notice_period"] == "ninety (90) days; not less than six (6) months"
    assert joined[0]["fields_labeled"] == "2"  # extended, not newly filled
    assert joined[1]["termination_notice_period"] == "ninety (90) days"
    assert (joined[1]["fields_labeled"], joined[1]["label_completeness"]) == ("2", "0.5")
    assert joined[1]["duplicate_of"] == "DOC-1"  # reviewed keeper wins
    _, p = out["provenance"]
    assert p[1]["chosen_source"] == "assist_upload" and json.loads(p[1]["evidence"])[0]["text"]
    assert out["completeness"][0]["labeled_repaired"] == 2
    assert out["counts"]["kept_builder_duplicate_keeper"] == 1 and out["queue"] == []
    # the input tables are not mutated
    assert rows[1]["termination_notice_period"] == "" and prov[1]["presence"] == "unlabeled"


GROUND = "renews unless notice is given One Hundred Eighty (180) days, or one hundred and twenty  (120) days, before"


@pytest.mark.parametrize("value, expected, missing", [
    ("eighty (180) days", "One Hundred Eighty (180) days", []),
    ("at least six (6) months; twenty (120) days", "at least six (6) months; one hundred and twenty  (120) days", []),
    ("one hundred eighty (180) days", "one hundred eighty (180) days", []),
    ("twenty four (24) months", "twenty four (24) months", []),
    ("forty-five (45) days", "forty-five (45) days", []),
    ("eighty (280) days", "eighty (280) days", ["eighty (280)"]),
])
def test_repair_magnitudes_uses_the_document_spelling(mod, value, expected, missing):
    new, _repaired, gaps = mod.repair_magnitudes(value, GROUND)
    assert (new, gaps) == (expected, missing)


def test_repair_cells_leaves_hub_values_and_queues_ungrounded(mod):
    prov = [_cell(field="termination_notice_period", value="eighty (180) days", chosen_source="cuad_span",
                  agreeing_sources="cuad_span"),
            _cell(field="renewal_terms", value="eighty (180) days", agreeing_sources="hub_v9.3"),
            _cell(field="term_length", value="eighty (280) days")]
    rows = [{"document_id": "DOC-1", "termination_notice_period": "eighty (180) days",
             "renewal_terms": "eighty (180) days", "term_length": "eighty (280) days"}]
    new_prov, new_rows, queue, counts = mod.repair_cells(prov, rows, {"DOC-1": GROUND})
    assert new_rows[0]["termination_notice_period"] == "One Hundred Eighty (180) days"
    assert new_prov[0]["rule"].endswith("+magnitude_grounded")
    assert new_rows[0]["renewal_terms"] == "eighty (180) days"  # a Hub value is never rewritten here
    assert [q["field"] for q in queue] == ["term_length"]
    assert counts == {"magnitude_cells_repaired": 1, "magnitude_phrases_repaired": 1, "magnitude_unresolved": 1}
    assert prov[0]["value"] == "eighty (180) days"  # inputs untouched


def test_verify_builder_refuses_other_bytes(mod, tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "repo"
    files = repo / mod.BUILDER_PATH
    files.mkdir(parents=True)
    for name in [*mod.BUILDER_FILES.values(), mod.BUILDER_SCRIPT]:
        (files / name).write_text(name)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "b"], check=True)
    monkeypatch.setattr(mod.emc, "ROOT", repo)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert mod.verify_builder(head[:8], files, files / mod.BUILDER_SCRIPT) == head
    (files / mod.BUILDER_SCRIPT).write_text("edited")
    with pytest.raises(mod.CacheError, match="is not the"):
        mod.verify_builder(head, files, files / mod.BUILDER_SCRIPT)
    with pytest.raises(mod.CacheError, match="not in this clone"):
        mod.verify_builder("0" * 40, files, files / mod.BUILDER_SCRIPT)


@pytest.mark.parametrize("value, text, expected", [
    ("This Agreement shall be governed by the laws of the State of New York, without regard to conflicts.",
     "governed by the laws of the State of New York", "State of New York"),
    ("THIS AGREEMENT SHALL BE GOVERNED BY THE LAWS, OTHER THAN CHOICE OF LAW RULES, OF THE STATE OF GEORGIA.",
     "OF THE STATE OF GEORGIA", "State of Georgia"),
    ("This Agreement shall be governed by the laws of the St",
     "This Agreement shall be governed by the laws of the State of Ohio. Notices", "State of Ohio"),
    ("construed in accordance with English law.", "in accordance with English law.", "English law"),
    ("governed by the laws of the People's Republic of China", "laws of the People's Republic of China",
     "People's Republic of China"),
    ("governed by the law governing the Distributor Agreement.", "the Distributor Agreement", None),
    ("governed by the laws of the State of Nevada.", "no jurisdiction here", None),  # must be in the text
])
def test_jurisdiction_reads_the_named_place(mod, value, text, expected):
    assert mod.jurisdiction(value, text) == expected


def test_clean_parties_drops_defined_term_clauses(mod):
    items = ['ACCURAY INCORPORATED ("Accuray")', '("MSCI")', "Siemens AG",
             'Accuray and Siemens are each referred to as a "Party" and collectively as the "Parties"',
             'e-centives, Inc., ("Application Provider")', "SIEMENS AG"]
    assert mod.clean_parties(items) == ["ACCURAY INCORPORATED", "Siemens AG", "e-centives, Inc."]


def test_keyword_metadata_keeps_topic_words(mod):
    kw = ["energy_market", "notice", "dasovich-j", "all_documents", "2001-04-09T08:00:00+00:00", "Dabhol"]
    assert mod.keyword_metadata(kw, "dasovich-j/all_documents/10778.") == ["energy_market", "notice", "Dabhol"]


VTEXT = 'This AGREEMENT is made the 20 March day of 1998 between A ("A") and B. Governed by the laws of the State of Texas.'


def _row(**cells):
    return {"document_id": "DOC-1", "filename": "f", "fields_targeted": "4", "fields_labeled": "4",
            "label_completeness": "1.0", **cells}


def test_validate_repairs_applies_rules_and_reviewed_corrections(mod):
    prov = [_cell(field="agreement_date", value="20 March day of 1998", chosen_source="generated_derived",
                  agreeing_sources="generated_derived", rule="weighted_vote"),
            _cell(field="effective_date", value="1998-03", chosen_source="generated_derived",
                  agreeing_sources="generated_derived", rule="weighted_vote"),
            _cell(field="parties", value='["A (\\"A\\")", "B", "b"]', chosen_source="generated_derived",
                  agreeing_sources="generated_derived", rule="weighted_vote"),
            _cell(field="governing_law", value="Governed by the laws of the State of Texas.", rule="weighted_vote",
                  chosen_source="generated_derived", agreeing_sources="generated_derived")]
    for c in prov:
        c["doc_class"] = "contract"
    rows = [_row(agreement_date="20 March day of 1998", effective_date="1998-03", parties=prov[2]["value"],
                 governing_law=prov[3]["value"])]
    fix = {("DOC-1", "agreement_date"): {"doc_id": "DOC-1", "field": "agreement_date", "presence": "populated",
                                         "value": "1998-03-20", "quote": "the 20 March day of 1998", "note": "n"}}
    new_prov, new_rows, queue, counts = mod.validate_repairs(prov, rows, {"DOC-1": VTEXT}, fix)
    got = {c["field"]: (c["value"], c["presence"]) for c in new_prov}
    assert got == {"agreement_date": ("1998-03-20", "populated"), "effective_date": ("", "unlabeled"),
                   "parties": ('["A", "B"]', "populated"), "governing_law": ("State of Texas", "populated")}
    assert new_prov[0]["chosen_source"] == mod.VALIDATION_SOURCE
    assert json.loads(new_prov[0]["evidence"])[0]["text"] == "the 20 March day of 1998"
    assert new_rows[0]["fields_labeled"] == "3" and new_rows[0]["parties"] == '["A", "B"]'
    assert [q["field"] for q in queue] == ["effective_date"]
    assert counts == {"governing_law_jurisdiction": 1, "partial_date_unlabeled": 1, "parties_cleaned": 1,
                      "validation_review": 1}
    assert prov[1]["value"] == "1998-03"  # inputs untouched


def test_validate_repairs_strips_hub_keywords_as_an_override(mod):
    cell = _cell(field="keywords", doc_class="correspondence", value='["notice", "kean-s", "inbox"]',
                 chosen_source="hub_v9.3", agreeing_sources="hub_v9.3", votes='{"hub_v9.3": ["notice"]}')
    new_prov, _rows, _q, counts = mod.validate_repairs([cell], [_row(filename="kean-s/inbox/1.", keywords="")],
                                                       {"DOC-1": ""}, {})
    assert new_prov[0]["value"] == '["notice"]' and mod.is_override(new_prov[0])
    assert counts == {"keyword_metadata_stripped": 1}


def test_corrections_must_quote_the_text_and_match_a_cell(mod, tmp_path):
    bad = tmp_path / "c.jsonl"
    bad.write_text(json.dumps({"doc_id": "D", "field": "f", "presence": "populated", "value": "v", "note": "n"}) + "\n")
    with pytest.raises(mod.CacheError, match="needs a value and a quote"):
        mod.read_corrections(bad)
    fix = {("DOC-1", "x"): {"doc_id": "DOC-1", "field": "x", "presence": "unlabeled", "note": "n"}}
    with pytest.raises(mod.CacheError, match="no merged cell"):
        mod.validate_repairs([], [], {}, fix)
    cell = _cell(field="agreement_date", doc_class="contract")
    fix = {("DOC-1", "agreement_date"): {"doc_id": "DOC-1", "field": "agreement_date", "presence": "populated",
                                         "value": "2000-01-01", "quote": "not there", "note": "n"}}
    with pytest.raises(mod.CacheError, match="quote is not in the document text"):
        mod.validate_repairs([cell], [_row()], {"DOC-1": VTEXT}, fix)


def test_header_restoration_lists_the_quoted_header_lines(mod, tmp_path):
    src = tmp_path / "correspondence.jsonl"
    rec = {"doc_id": "DOC-1", "labels": {
        "sender": {"basis": "original_header", "evidence": [{"file": "kean-s/inbox/1.", "header": "From: a@x.com"}]},
        "communication_date": {"basis": "original_header", "evidence": [{"file": "kean-s/inbox/1.", "header": "Date: Mon"}]},
        "intent": {"basis": "review_read_message", "evidence": []}}}
    src.write_text(json.dumps(rec) + "\n" + json.dumps({"doc_id": "DOC-9", "labels": rec["labels"]}) + "\n")
    out = mod.header_restoration(src, [_row(filename="kean-s/inbox/1.")])
    assert out == [{"document_id": "DOC-1", "filename": "kean-s/inbox/1.", "maildir_file": "kean-s/inbox/1.",
                    "fields": "communication_date|sender", "header_lines": '["Date: Mon", "From: a@x.com"]'}]


def test_clean_parties_drops_a_sentence_period_the_text_lacks(mod):
    text = "between DSP Group, Inc. and Synaptics Incorporated, a Delaware corporation"
    assert mod.clean_parties(["DSP Group, Inc.", "Synaptics Incorporated."], text) == [
        "DSP Group, Inc.", "Synaptics Incorporated"]


def test_join_extension_of_a_hub_value_leaves_the_hub_agreement(mod):
    cols = ["document_id", "doc_class", "fields_targeted", "fields_labeled", "label_completeness",
            "termination_notice_period", "duplicate_of"]
    rows = [{"document_id": "DOC-1", "doc_class": "contract", "fields_targeted": "4", "fields_labeled": "2",
             "label_completeness": "0.5", "termination_notice_period": "ninety (90) days", "duplicate_of": ""}]
    prov = [_cell(field="termination_notice_period", value="ninety (90) days", chosen_source="hub_v9.3",
                  agreeing_sources="hub_v9.3|cuad_span", votes='{"hub_v9.3": "ninety (90) days"}')]
    comp = [{"doc_class": "contract", "field": "termination_notice_period", "documents": "1",
             "labeled_hub_v9_3": "1", "labeled_repaired": "1", "populated": "1", "documented_absence": "0",
             "unlabeled": "0", "disputed_unresolved": "0", "completeness_hub_v9_3": "1.0",
             "completeness_repaired": "1.0", "conflicts": "0", "needs_human": "0", "top_source": "hub_v9.3"}]
    assist = [dict(rows[0], termination_notice_period="notifies the other Party not less than six (6) months before")]
    builder = {"labels": (cols, rows), "provenance": (list(prov[0]), prov), "completeness": (list(comp[0]), comp)}
    _, p = mod.join(builder, assist, {"DOC-1": TEXT})["provenance"]
    assert p[0]["agreeing_sources"] == "cuad_span|assist_upload" and p[0]["chosen_source"] == "assist_upload"
    assert not mod.from_hub(p[0]) and mod.is_override(p[0])
    assert mod.overlay_records(p, {"DOC-1": "s"})["contract"][0]["labels"]["termination_notice_period"]["override"]


@pytest.mark.parametrize("value, expected", [
    ("Inc.", True), ("Holdings, Inc.", True), ("the Company", True), ("COMPANY", True), ("Holding Company", True),
    ("Acme Holdings, Inc.", False), ("Company Store LLC", False)])
def test_not_a_name_spots_suffix_and_defined_term_captures(mod, value, expected):
    assert mod.not_a_name(value) is expected


def test_validate_repairs_withholds_suffix_names_open_decisions_and_same_text_conflicts(mod):
    prov = [_cell(field="acquirer", doc_class="merger_agreement", value="Inc.", chosen_source="generated_rule",
                  agreeing_sources="generated_rule"),
            _cell(field="parties", doc_class="merger_agreement", value='["Acme Corp.", "Inc.", "the Company"]',
                  chosen_source="generated_rule", agreeing_sources="generated_rule"),
            _cell(field="effective_date", doc_class="merger_agreement", value="2021-06-28",
                  chosen_source="interim_gate", agreeing_sources="interim_gate"),
            _cell(document_id="DOC-2", field="maud_clauses", doc_class="merger_agreement", value='["a: Yes"]',
                  chosen_source="generated_derived", agreeing_sources="generated_derived"),
            _cell(document_id="DOC-3", field="maud_clauses", doc_class="merger_agreement", value='["a: No"]',
                  chosen_source="generated_derived", agreeing_sources="generated_derived")]
    rows = [_row(), _row(document_id="DOC-2"), _row(document_id="DOC-3")]
    decisions = {("DOC-1", "effective_date"): {"value": "2021-06-28", "kind": "signing_date_as_effective_date",
                                                "reason": "signing date", "action": "owner_decides"}}
    new, _, queue, counts = mod.validate_repairs(prov, rows, {"DOC-1": VTEXT}, {}, decisions=decisions,
                                                 shas={"DOC-1": "x", "DOC-2": "same", "DOC-3": "same"})
    got = [(c["field"], c["value"], c["presence"]) for c in new]
    assert got == [("acquirer", "", "unlabeled"), ("parties", '["Acme Corp."]', "populated"),
                   ("effective_date", "2021-06-28", "disputed_unresolved"),
                   ("maud_clauses", '["a: Yes"]', "disputed_unresolved"),
                   ("maud_clauses", '["a: No"]', "disputed_unresolved")]
    assert counts == {"name_capture_unlabeled": 1, "owner_decision_pending": 1, "parties_cleaned": 1,
                      "same_text_conflict": 2}
    assert [q["field"] for q in queue] == ["acquirer", "effective_date", "maud_clauses", "maud_clauses"]
    assert "DOC-2, DOC-3" in queue[-1]["reason"]
    assert mod.overlay_records(new, {}).get("merger_agreement", [{}])[0]["labels"].keys() == {"parties"}


@pytest.mark.parametrize("value, expected", [
    ("the retention of Keefe, Bruyette & Woods, Inc.", "Keefe, Bruyette & Woods, Inc."),
    ("engagement of Goldman Sachs & Co. LLC", "Goldman Sachs & Co. LLC"),
    ("Subsidiary of Standard Industries Holdings Inc., and Gibraltar Merger Sub Inc.", "Gibraltar Merger Sub Inc."),
    ("a wholly owned subsidiary of Parent, and Merger Sub LLC", "Merger Sub LLC"),
    ("Eli Lilly and Company", "Eli Lilly and Company"), ("Retention Partners LLC", "Retention Partners LLC"),
    ("Subsidiary of Parent Inc.", "Subsidiary of Parent Inc.")])
def test_trim_name_drops_a_describing_lead_in(mod, value, expected):
    assert mod.trim_name(value) == expected


def test_validate_repairs_trims_lead_ins_from_party_and_advisor_names(mod):
    ev = '[{"text": "the retention of Keefe, Bruyette & Woods, Inc."}]'
    run_on = "Subsidiary of Standard Industries Holdings Inc., and Gibraltar Merger Sub Inc."
    prov = [_cell(field="financial_advisors", doc_class="merger_agreement", evidence=ev,
                  value='["the retention of Keefe, Bruyette & Woods, Inc.", "the retention of Boenning & Scattergood, Inc."]',
                  chosen_source="generated_rule", agreeing_sources="generated_rule"),
            _cell(field="merger_sub", doc_class="merger_agreement", value=json.dumps([run_on]),
                  chosen_source="generated_rule", agreeing_sources="generated_rule"),
            _cell(field="parties", doc_class="merger_agreement", value=json.dumps(["W. R. Grace & Co.", run_on]),
                  chosen_source="generated_rule", agreeing_sources="generated_rule"),
            _cell(field="legal_counsel", doc_class="merger_agreement", value='["Wilmer Cutler Pickering Hale and Dorr LLP"]',
                  chosen_source="generated_rule", agreeing_sources="generated_rule")]
    new, _, queue, counts = mod.validate_repairs(prov, [_row()], {"DOC-1": VTEXT}, {})
    assert [json.loads(c["value"]) for c in new] == [
        ["Keefe, Bruyette & Woods, Inc.", "Boenning & Scattergood, Inc."], ["Gibraltar Merger Sub Inc."],
        ["W. R. Grace & Co.", "Gibraltar Merger Sub Inc."], ["Wilmer Cutler Pickering Hale and Dorr LLP"]]
    assert new[0]["evidence"] == ev and queue == []
    assert counts == {"name_lead_in_trimmed": 2, "parties_cleaned": 1}


@pytest.mark.parametrize("value, dropped", [
    ("Licensor", True), ("the Customer", True), ("The seller:", True), ("sales agent", True), ("Guarantors", True),
    ("an individual", True), ("your", True), ("the Reseller named above", True), ('you as an "Affiliate"', True),
    ("each other party hereto identified on the signature page(s) hereto", True),
    ("its associated chapter 11 debtors in possession", True), ("a subsidiary of Dynamex Inc.", True),
    ("d/b/a Recreation USA", True), ("formerly known as Tarzan HoldCo, Inc.)", True), ("a.k.a. Beyond.com", True),
    ("F/K/A SKYEPHARMA, INC.", True), ("f/s/o Dwyane Wade", True),
    ("The Johns Hopkins University", False), ("THE BANKERS BANK", False), ("The Associated Press", False),
    ("salesforce.com, inc.", False), ("iPass", False), ("YOU ON DEMAND HOLDINGS, INC.", False), ("Bank of America, N.A.", False), ("Agent Inc.", False)])
def test_clean_parties_drops_role_words_descriptions_and_alias_clauses(mod, value, dropped):
    assert (mod.clean_parties(["Acme Corp.", value]) == ["Acme Corp."]) is dropped


def test_clean_parties_trims_a_role_label_before_the_name(mod):
    assert mod.clean_parties(["The buyer/End-User: Shenzhen LOHAS Supply Chain Management Co., Ltd."]) == [
        "Shenzhen LOHAS Supply Chain Management Co., Ltd."]


SIGNED = ("AGREEMENT AND PLAN OF MERGER\n" + "x" * 2000 + " This Agreement is made and entered into as of "
          "May 10, 2021, by and among Parent and the Company. The Effective Time is the time the certificate is filed.")


@pytest.mark.parametrize("value, text, expected", [
    ("2021-05-10", SIGNED, True),
    ("2021-05-10", "Exhibit 2.1 AGREEMENT AND PLAN OF MERGER by and among A, B and C. May 10, 2021", True),
    ("2021-05-10", SIGNED + " The merger shall be effective as of May 10, 2021.", False),
    ("2021-05-11", SIGNED, False), ("2021-05", SIGNED, False)])
def test_signing_date_only(mod, value, text, expected):
    assert mod.signing_date_only(value, text) is expected


def test_signing_date_policy_follows_the_audit_rows(mod, tmp_path):
    p = tmp_path / "audit.jsonl"
    assert mod.signing_date_policy(p) is None
    rows = lambda *acts: "".join(json.dumps({"kind": mod.SIGNING_KIND, "action": a}) + "\n" for a in acts)
    p.write_text(rows("owner_decides", "clear"))
    assert mod.signing_date_policy(p) == "pending"
    p.write_text(rows("clear", "clear"))
    assert mod.signing_date_policy(p) == "clear"
    p.write_text(rows("keep"))
    assert mod.signing_date_policy(p) == "keep"


@pytest.mark.parametrize("policy, value, presence, rule", [
    ("pending", "2021-05-10", "disputed_unresolved", "signing_date_pending_owner"),
    ("clear", "", "documented_absence", "signing_date_not_effective_date"),
    ("keep", "2021-05-10", "populated", None), (None, "2021-05-10", "populated", None)])
def test_merger_signing_dates_follow_the_owner_policy(mod, policy, value, presence, rule):
    cell = _cell(field="effective_date", doc_class="merger_agreement", value="2021-05-10",
                 chosen_source="generated_rule", agreeing_sources="generated_rule")
    new, _, queue, counts = mod.validate_repairs([cell], [_row()], {"DOC-1": SIGNED}, {}, signing_policy=policy)
    assert (new[0]["value"], new[0]["presence"]) == (value, presence)
    assert counts == ({rule: 1} if rule else {})
    assert len(queue) == (policy == "pending")


def test_completeness_counts_cells_validation_disputed(mod):
    """The field report is recomputed after validation, so a held cell is disputed, not labeled."""
    cell = _cell(field="effective_date", doc_class="merger_agreement", value="2021-05-10",
                 chosen_source="generated_rule", agreeing_sources="generated_rule")
    base = [{"doc_class": "merger_agreement", "field": "effective_date", "documents": "1", "labeled_hub_v9_3": "0",
             "labeled_repaired": "1", "populated": "1", "documented_absence": "0", "unlabeled": "0",
             "disputed_unresolved": "0", "completeness_hub_v9_3": "0.0", "completeness_repaired": "1.0",
             "conflicts": "0", "needs_human": "0", "top_source": "generated_rule"}]
    assert mod.completeness_table([cell], base)[0]["labeled_repaired"] == 1
    new, _, _, _ = mod.validate_repairs([cell], [_row()], {"DOC-1": SIGNED}, {}, signing_policy="pending")
    row = mod.completeness_table(new, base)[0]
    assert (row["labeled_repaired"], row["disputed_unresolved"], row["completeness_repaired"]) == (0, 1, 0.0)


def test_open_decisions_reads_only_owner_decides_rows(mod, tmp_path):
    p = tmp_path / "audit.jsonl"
    p.write_text(json.dumps({"doc_id": "D", "field": "f", "action": "owner_decides", "value": "v"}) + "\n"
                 + json.dumps({"doc_id": "D", "field": "g", "action": "keep", "value": "v"}) + "\n")
    assert list(mod.open_decisions(p)) == [("D", "f")]
    assert mod.open_decisions(tmp_path / "missing.jsonl") == {}


def test_assist_terms_keep_qualifiers_and_flag_other_operators(mod):
    text = "upon ninety (90) business days notice; terminate on not less than thirty (30) days written notice"
    out, refused = mod.assist_notice_terms(
        "ninety (90) business days notice; not less than thirty (30) days written notice",
        "ninety (90) days; thirty (30) days", text)
    assert out == ["ninety (90) business days"]
    assert refused == ["same period, other operator: not less than thirty (30) days"]
