"""Interim GT label overlay: the committed files stay consistent and the admission rules hold."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import interim_labels as il
from mailroom_sandbox.job.spec import DatasetSpec


def _row(cls="corporate_record", sub="bylaws", text="ACME HOLDINGS, INC. Bylaws adopted March 3, 2020 by Jane Roe.", **exp):
    return {"id": "D1", "expected_doc_class": cls, "expected_subclass": sub, "doc_text": text,
            "expected_fields": json.dumps({"intent": "governance_rules", "gt_presence": json.dumps({"intent": "populated"}), **exp})}


def test_committed_overlay_is_consistent():
    assert il.verify() == []
    man = il.load_manifest()
    assert man["schema"] == il.SCHEMA and man["sources"] and man["files"]
    for rec in il.load_overlay().values():
        cls = rec["doc_class"]
        src = rec["source"]
        assert rec["doc_sha256"] and ((src.get("gate_run") and src.get("question_set")) or src.get("review"))
        for field, lab in rec["labels"].items():
            assert lab["use_as_truth"] == (lab["status"] in il.TRUTH_STATUSES)
            if "review" in lab:  # a reviewed label: a header read or a read of the message, with evidence
                assert lab["basis"] in il.REVIEW_BASES and lab["review"]["file"] and lab["review"]["reviewer"]
                assert (field in il.HEADER_FIELDS) == (lab["basis"] == "original_header"), (rec["doc_id"], field)
                assert lab["evidence"] or lab["basis"] == "review_read_message", (rec["doc_id"], field)
                continue
            if lab["status"] == "gap_fill":
                assert field in il.GAP_FIELDS[cls], (rec["doc_id"], field)
                assert lab["support"] >= (il.NULL_SUPPORT_MIN if lab["value"] is None else il.SUPPORT_MIN)
            if lab["status"] == "derived":
                want = (il.derived_value(cls, rec["doc_subclass"]) if field == il.SUBCLASS_FIELDS.get(cls)
                        else rec["doc_subclass"])
                assert lab["value"] == want, (rec["doc_id"], field)
            if lab["status"] == "correction":
                assert cls == "contract" and lab["basis"] in ("cuad_party_spans", "cuad_agreement_date")


def test_derived_record_type_is_the_dojo_enum_token_not_the_subclass():
    pytest.importorskip("llm_dojo_scoring.schemas.corporate_record_schema")
    from llm_dojo_scoring.schemas.corporate_record_schema import RECORD_TYPES

    # The specialist emits the 5-token enum, so a raw subclass label would score a correct "other" wrong.
    assert il.derived_value("corporate_record", "indenture") == "other"
    assert il.derived_value("corporate_record", "charter_amendment") == "articles_of_incorporation"
    assert il.derived_value("corporate_record", "bylaws") == "bylaws"
    assert il.derived_value("correspondence", "attorney_demand") == "attorney_demand"  # already the vocabulary
    committed = [r["labels"]["record_type"]["value"] for r in il._jsonl(il.overlay_dir() / "corporate_record.jsonl")
                 if "record_type" in r["labels"]]
    assert committed and set(committed) <= set(RECORD_TYPES)


def test_gap_fill_needs_support_grounding_and_no_hub_label():
    row = _row()
    gate = {"verdict": "retry_extraction",
            "field_support": {"entity_name": 0.97, "signatories": 0.95, "jurisdiction": 0.6, "intent": 0.99,
                              "effective_date": 0.93, "filing_number": 0.92}}
    fields = {"entity_name": "Acme Holdings, Inc.", "signatories": ["Roe, Jane"], "jurisdiction": "Delaware",
              "intent": "governance_rules", "effective_date": "2020-03-03", "filing_number": "F-123"}
    out = il.labels_for(row, fields, gate, {"intent": True})
    assert out["entity_name"]["status"] == "gap_fill"
    assert out["signatories"]["value"] == ["Roe, Jane"]  # name order does not matter
    assert out["effective_date"]["status"] == "gap_fill"  # "March 3, 2020" grounds the ISO date
    assert "jurisdiction" not in out  # support below SUPPORT_MIN
    assert "filing_number" not in out  # not in the document: ungrounded
    assert "intent" not in out  # the Hub labels it and the extraction agrees
    assert out["record_type"] == {"value": "bylaws", "status": "derived", "basis": "hub_subclass",
                                  "hub_value": None, "use_as_truth": True}
    assert il.labels_for(row, fields, {**gate, "verdict": "human_review"}, {"intent": True}).keys() == {"record_type"}


def test_disputed_is_never_truth_and_cms_table_is_derived():
    row = _row("correspondence", "email", "Please send the report.", intent="notice", intent_source="heuristic")
    out = il.labels_for(row, {"intent": "request"}, {"verdict": "accept", "field_support": {"intent": 0.98}},
                        {"intent": False})
    assert out["intent"]["status"] == "disputed" and out["intent"]["use_as_truth"] is False
    assert out["intent"]["hub_value"] == "notice" and out["intent"]["hub_source"] == "heuristic"
    cms = il.labels_for(_row("insurance_claim", "carrier", "x"), {}, {"verdict": "accept", "field_support": {}}, {})
    assert cms["cms_source_table"]["value"] == "carrier" and cms["cms_source_table"]["use_as_truth"]


def test_contract_corrections_rest_on_the_hubs_own_cuad_evidence(monkeypatch):
    spans = {"Parties": ["Seller", "NMS COMMUNICATIONS CORP.", "Backhaul", "VERSO BACKHAUL SOLUTIONS, INC."],
             "Effective Date": [], "Agreement Date": ["December 20, 2007"]}
    import llm_dojo_scoring.sandbox_scoring as ss

    monkeypatch.setattr(ss, "gt_categories", lambda labels: spans)
    exp = {"cuad_clause_labels": "{}"}
    assert il.contract_correction("parties", ['NMS COMMUNICATIONS CORP. ("Seller")', "Verso Backhaul Solutions, Inc."], exp) == "cuad_party_spans"
    assert il.contract_correction("parties", ["NMS COMMUNICATIONS CORP.", "Someone Else LLC"], exp) is None
    # A subset of the parties is incomplete, not a correction: Verso's legal name is unaccounted for.
    assert il.contract_correction("parties", ['NMS COMMUNICATIONS CORP. ("Seller")'], exp) is None
    # Without annotations: "Seller" and "Backhaul" name no further legal entity; still complete.
    assert il.contract_correction("parties", ["NMS COMMUNICATIONS CORP.", "Verso Backhaul Solutions, Inc."], exp) == "cuad_party_spans"
    spans["Parties"] = ["we", "NMS COMMUNICATIONS CORP.", "Verso Backhaul Solutions, Inc.",
                        "NMS and Verso may each be referred to herein as a Party"]
    assert il.contract_correction("parties", ["NMS Communications Corp.", "Verso Backhaul Solutions, Inc."], exp) == "cuad_party_spans"
    spans["Parties"] = ["Seller", "NMS COMMUNICATIONS CORP.", "Backhaul", "VERSO BACKHAUL SOLUTIONS, INC."]
    assert il.contract_correction("effective_date", "2007-12-20", exp) == "cuad_agreement_date"
    assert il.contract_correction("effective_date", "2008-01-01", exp) is None
    spans["Effective Date"] = ["January 1, 2008"]
    assert il.contract_correction("effective_date", "2007-12-20", exp) is None  # CUAD states one: no correction


def test_apply_overlay_merges_truth_only_and_hub_wins():
    row = _row(entity_name="Hub Name Inc.", gt_presence=json.dumps({"intent": "populated", "entity_name": "populated"}))
    rec = {"doc_id": "D1", "doc_sha256": il.doc_sha(row["doc_text"]), "labels": {
        "entity_name": {"value": "Overlay Inc.", "status": "gap_fill", "use_as_truth": True},
        "jurisdiction": {"value": None, "status": "gap_fill", "use_as_truth": True},
        "intent": {"value": "other", "status": "disputed", "use_as_truth": False},
        "record_type": {"value": "bylaws", "status": "derived", "use_as_truth": True}}}
    out = il.apply_overlay(row, {"D1": rec}, overlay_sha="abc")
    exp = json.loads(out["expected_fields"])
    assert exp["entity_name"] == "Hub Name Inc." and exp["intent"] == "governance_rules"
    assert exp["record_type"] == "bylaws" and exp["jurisdiction"] is None
    pres = json.loads(exp["gt_presence"])
    assert pres["record_type"] == "populated" and pres["jurisdiction"] == "schema_documented_absence"
    assert out["interim_labels"] == {"fields": ["jurisdiction", "record_type"], "overlay_sha256": "abc"}
    changed = {**row, "doc_text": row["doc_text"] + " amended"}
    assert il.apply_overlay(changed, {"D1": rec}, overlay_sha="abc") == changed  # stale text: untouched
    assert row["expected_fields"] == _row(entity_name="Hub Name Inc.", gt_presence=json.dumps(
        {"intent": "populated", "entity_name": "populated"}))["expected_fields"]  # input not mutated


def test_superseded_reports_hub_labels_and_changed_text():
    row = _row()
    rec = {"doc_id": "D1", "doc_sha256": il.doc_sha(row["doc_text"]),
           "labels": {"entity_name": {"value": "Acme", "status": "gap_fill", "use_as_truth": True}}}
    assert il.superseded([row], {"D1": rec}) == []
    hub = _row(entity_name="Acme", gt_presence=json.dumps({"entity_name": "populated"}))
    assert il.superseded([hub], {"D1": rec}) == [("D1", "entity_name")]
    assert il.superseded([{**row, "doc_text": "new"}], {"D1": rec}) == [("D1", "*")]


def test_interim_labels_is_hashed_only_when_set():
    base = DatasetSpec(repo="r", split="train")
    assert "interim_labels" not in base.request_core()
    on = DatasetSpec(repo="r", split="train", interim_labels=True).request_core()
    assert on["interim_labels"] == il.overlay_fingerprint() and len(on["interim_labels"]) == 64


def test_prepare_subset_applies_the_overlay_only_when_asked(tmp_path, monkeypatch):
    from mailroom_sandbox.corpus import prepare_subset

    row = _row()
    row["id"] = "D1"
    src = tmp_path / "rows.jsonl"
    src.write_text(json.dumps(row) + "\n", encoding="utf-8")
    rec = {"doc_id": "D1", "doc_sha256": il.doc_sha(row["doc_text"]),
           "labels": {"record_type": {"value": "bylaws", "status": "derived", "use_as_truth": True}}}
    monkeypatch.setattr(il, "verify", lambda root=None: [])
    monkeypatch.setattr(il, "load_overlay", lambda root=None: {"D1": rec})
    monkeypatch.setattr(il, "overlay_fingerprint", lambda root=None: "f" * 64)
    off = prepare_subset(DatasetSpec(local_path=str(src)), tmp_path / "off.jsonl")
    assert "interim_labels" not in off["metadata"]
    assert "interim_labels" not in json.loads((tmp_path / "off.jsonl").read_text())
    on = prepare_subset(DatasetSpec(local_path=str(src), interim_labels=True), tmp_path / "on.jsonl")
    assert on["metadata"]["interim_labels"] == {"overlay_sha256": "f" * 64, "rows_with_labels": 1, "fields_applied": 1}
    locked = json.loads((tmp_path / "on.jsonl").read_text())
    exp = locked["expected_fields"]
    assert (json.loads(exp) if isinstance(exp, str) else exp)["record_type"] == "bylaws"
    monkeypatch.setattr(il, "verify", lambda root=None: ["corporate_record.jsonl: sha256 differs"])
    import pytest

    with pytest.raises(ValueError, match="inconsistent"):
        prepare_subset(DatasetSpec(local_path=str(src), interim_labels=True), tmp_path / "bad.jsonl")


def test_null_truth_label_is_a_documented_absence_the_dojo_scores():
    """A null gap fill must read as "expected empty", not unlabeled, so corporate scoring keeps it."""
    from llm_dojo_scoring.corporate_record_schema import unlabeled_fields

    row = _row()
    rec = {"doc_id": "D1", "doc_sha256": il.doc_sha(row["doc_text"]), "labels": {
        "jurisdiction": {"value": None, "status": "gap_fill", "use_as_truth": True}}}
    exp = json.loads(il.apply_overlay(row, {"D1": rec}, overlay_sha="abc")["expected_fields"])
    assert "jurisdiction" not in unlabeled_fields("bylaws", exp)
    assert "jurisdiction" in unlabeled_fields("bylaws", json.loads(row["expected_fields"]))


def _overlay_two_labels(root):
    """An overlay of one document with two gap fills, written as the builder would."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "interim_labels_script", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "interim_labels.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    row = _row()
    rec = {"doc_id": "D1", "doc_class": "corporate_record", "doc_sha256": il.doc_sha(row["doc_text"]), "labels": {
        "entity_name": {"value": "Acme", "status": "gap_fill", "use_as_truth": True},
        "jurisdiction": {"value": "Delaware", "status": "gap_fill", "use_as_truth": True}}}
    root.mkdir()
    text = json.dumps(rec, sort_keys=True) + "\n"
    (root / "corporate_record.jsonl").write_text(text, encoding="utf-8")
    man = {"schema": il.SCHEMA, "sources": [], "files": {"corporate_record.jsonl": il._sha(text)},
           "counts": {"corporate_record": {"entity_name": {"gap_fill": 1}, "jurisdiction": {"gap_fill": 1}}}}
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    hub = _row(entity_name="Acme", gt_presence=json.dumps({"entity_name": "populated"}))
    return mod, hub


def test_prune_rewrites_counts_and_still_fails_on_other_problems(tmp_path, monkeypatch):
    root = tmp_path / "interim"
    mod, hub = _overlay_two_labels(root)
    monkeypatch.setattr(mod, "_local_gate_runs", lambda: {})
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps(hub) + "\n", encoding="utf-8")
    assert mod.check(root, rows, prune=True) == 0
    man = json.loads((root / "MANIFEST.json").read_text())
    assert man["counts"] == {"corporate_record": {"jurisdiction": {"gap_fill": 1}}}
    assert il.verify(root) == []
    # An integrity problem left beside the pruned labels must still fail the check.
    (root / "stray.jsonl").write_text("", encoding="utf-8")
    hub2 = _row(jurisdiction="Delaware", gt_presence=json.dumps({"jurisdiction": "populated"}))
    rows.write_text(json.dumps(hub2) + "\n", encoding="utf-8")
    assert mod.check(root, rows, prune=True) == 1
    # ...and the prune is refused, so the still-superseded label stays in place.
    assert "jurisdiction" in json.loads((root / "corporate_record.jsonl").read_text())["labels"]


def test_prune_never_rehashes_a_file_that_fails_integrity(tmp_path, monkeypatch):
    root = tmp_path / "interim"
    mod, hub = _overlay_two_labels(root)
    monkeypatch.setattr(mod, "_local_gate_runs", lambda: {})
    path = root / "corporate_record.jsonl"
    rec = json.loads(path.read_text())
    rec["labels"]["jurisdiction"]["value"] = "Nevada"  # a hand edit the manifest hash does not cover
    path.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")
    sha_before = json.loads((root / "MANIFEST.json").read_text())["files"]["corporate_record.jsonl"]
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps(hub) + "\n", encoding="utf-8")
    assert mod.check(root, rows, prune=True) == 1
    assert json.loads((root / "MANIFEST.json").read_text())["files"]["corporate_record.jsonl"] == sha_before
    assert any("sha256 differs" in p for p in il.verify(root))


def test_counts_tolerate_a_label_without_status(tmp_path):
    mod, _ = _overlay_two_labels(tmp_path / "interim")
    root = tmp_path / "interim"
    rec = json.loads((root / "corporate_record.jsonl").read_text())
    del rec["labels"]["jurisdiction"]["status"]
    rec2 = {**rec, "doc_id": "D2"}
    rec2["labels"] = {"jurisdiction": {"value": "Delaware", "status": "gap_fill", "use_as_truth": True}}
    (root / "corporate_record.jsonl").write_text(json.dumps(rec) + "\n" + json.dumps(rec2) + "\n", encoding="utf-8")
    counts = mod._counts(root, ["corporate_record.jsonl"])
    assert counts["corporate_record"]["jurisdiction"] == {"gap_fill": 1, None: 1}


def test_replace_leaves_no_staged_file(tmp_path):
    mod, _ = _overlay_two_labels(tmp_path / "interim")
    target = tmp_path / "out.json"
    mod._replace(target, "one")
    mod._replace(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir() if p.name != "interim"] == ["out.json"]


def test_rederive_rolls_back_when_the_manifest_write_fails(tmp_path, monkeypatch):
    """A failed manifest write must leave the overlay as it was, so a retry can still run (#303 review)."""
    root = tmp_path / "interim"
    mod, _ = _overlay_two_labels(root)
    # A stale derived label, so rederive has a real change to write.
    path = root / "corporate_record.jsonl"
    rec = json.loads(path.read_text())
    rec["doc_subclass"] = "bylaws"
    rec["labels"]["record_type"] = {"value": "stale", "status": "derived", "use_as_truth": True}
    text = json.dumps(rec, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    man = json.loads((root / "MANIFEST.json").read_text())
    man["files"]["corporate_record.jsonl"] = il._sha(text)
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    real = mod._replace

    def failing(path, text):
        if path.name == "MANIFEST.json":
            raise OSError("disk full")
        real(path, text)

    monkeypatch.setattr(mod, "_replace", failing)
    with pytest.raises(OSError, match="disk full"):
        mod.rederive(root)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert il.verify(root) == []
    monkeypatch.setattr(mod, "_replace", real)
    assert mod.rederive(root) == 0
    assert json.loads(path.read_text())["labels"]["record_type"]["value"] == "bylaws"
    assert il.verify(root) == []


# ── reviewed labels ────────────────────────────────────────────────────────

_EMAIL_SHA = "0123456789abcdef"


def _header_line(field="sender", value="Ann M Schmidt", header="X-From: Ann M Schmidt", **over):
    line = {"doc_id": "E1", "doc_class": "correspondence", "doc_subclass": "notice", "doc_sha256": _EMAIL_SHA,
            "field": field, "status": "gap_fill", "basis": "original_header", "value": value,
            "evidence": [{"source": il.HEADER_SOURCE, "file": "schmidt-a/1.", "header": header}],
            "reviewer": {"model": "m", "role": "review"}, "note": "the header states it"}
    return {**line, **over}


def _intent_line(value="request", **over):
    line = {"doc_id": "E1", "doc_class": "correspondence", "doc_subclass": "notice", "doc_sha256": _EMAIL_SHA,
            "field": "intent", "status": "correction", "basis": "review_read_message", "value": value,
            "hub_value": "notice", "evidence": [], "reviewer": {"model": "m", "role": "review"},
            "note": "it asks for the report"}
    return {**line, **over}


def test_review_line_rules():
    assert il.review_line_problem(_header_line()) is None
    assert il.review_line_problem(_intent_line()) is None
    assert il.review_line_problem(_header_line("communication_date", "2001-05-14",
                                               "Date: Mon, 14 May 2001 09:02:00 -0700 (PDT)")) is None
    assert il.review_line_problem(_header_line("additional_recipients", ["Jeff Dasovich", "Sue Mara"],
                                               "X-cc: Jeff Dasovich, Sue Mara")) is None
    # A name fused with its mail domain by the export still shows each token of the name.
    assert il.review_line_problem(_header_line("recipient", "Michael Grimes", "X-To: Michael GrimesCORPENRON")) is None
    bad = {
        "unknown basis": _header_line(basis="guess"),
        "takes status gap_fill": _header_line(status="correction"),
        "does not cover": _header_line(field="subject"),
        "16-hex": _header_line(doc_sha256="xyz"),
        "reviewer": _header_line(reviewer={"model": "m"}),
        "needs a note": _header_line(note=" "),
        "not in the quoted header": _header_line(value="Jeff Skilling"),
        "not X-cc": _header_line(header="X-cc: Ann M Schmidt"),
        "header lines as evidence": _header_line(evidence=[]),
        "evidence must be": _header_line(evidence=[{"source": "memory", "file": "f", "header": "X-From: Ann M Schmidt"}]),
        "not the date": _header_line("communication_date", "2001-05-15", "Date: Mon, 14 May 2001 09:02:00 -0700"),
        "YYYY-MM-DD": _header_line("communication_date", "May 14, 2001", "Date: Mon, 14 May 2001 09:02:00 -0700"),
        "list of names": _header_line("additional_recipients", "Sue Mara", "X-cc: Sue Mara"),
        "not in the vocabulary": _intent_line("gossip"),
        "missing": {k: v for k, v in _intent_line().items() if k != "note"},
    }
    for want, line in bad.items():
        why = il.review_line_problem(line)
        assert why and want in why, (want, why)


def test_read_reviews_refuses_a_second_review_of_one_label(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in (_header_line(), _header_line(), _intent_line())))
    lines, problems = il.read_reviews(path)
    assert len(lines) == 2 and len(problems) == 1 and "second review" in problems[0]


def test_apply_reviews_replaces_adds_and_is_idempotent():
    gate = {"value": "Ann Schmidt", "status": "gap_fill", "basis": "gate_accepted_grounded", "support": 0.95,
            "use_as_truth": True}
    disputed = {"value": "request", "status": "disputed", "basis": "gate_vs_hub", "hub_value": "notice",
                "use_as_truth": False}
    records = {"E1": {"doc_id": "E1", "doc_class": "correspondence", "doc_subclass": "notice",
                      "doc_sha256": _EMAIL_SHA, "labels": {"sender": gate, "intent": disputed}, "source": {"gate_run": "g"}}}
    lines = [_header_line(), _intent_line(), _header_line(doc_id="E2")]
    n, problems = il.apply_reviews(records, lines, "rev.jsonl")
    assert (n, problems) == (3, [])
    sender = records["E1"]["labels"]["sender"]
    assert sender["value"] == "Ann M Schmidt" and sender["use_as_truth"] and sender["review"]["file"] == "rev.jsonl"
    assert sender["replaced"] == {"status": "gap_fill", "basis": "gate_accepted_grounded", "value": "Ann Schmidt"}
    intent = records["E1"]["labels"]["intent"]
    assert intent["status"] == "correction" and intent["hub_value"] == "notice" and intent["use_as_truth"]
    assert intent["replaced"]["status"] == "disputed"
    assert records["E2"]["source"] == {"review": "rev.jsonl"} and records["E2"]["labels"].keys() == {"sender"}
    # Applying again changes nothing and keeps what the first application replaced.
    assert il.apply_reviews(records, lines, "rev.jsonl") == (0, [])
    assert records["E1"]["labels"]["sender"]["replaced"]["value"] == "Ann Schmidt"
    assert il.reviews_reflected(records, lines) == []
    # A review of other text (or another class) is refused, and the record is left alone.
    n, problems = il.apply_reviews(records, [_header_line(doc_sha256="f" * 16, value=None)], "rev.jsonl")
    assert n == 0 and "other text" in problems[0] and records["E1"]["labels"]["sender"]["value"] == "Ann M Schmidt"


def _review_overlay(tmp_path, monkeypatch):
    """An overlay with one correspondence record, a review file, and the script module."""
    root = tmp_path / "interim"
    mod, _ = _overlay_two_labels(root)
    rec = {"doc_id": "E1", "doc_class": "correspondence", "doc_subclass": "notice", "doc_sha256": _EMAIL_SHA,
           "labels": {}, "source": {"gate_run": "g", "question_set": "q"}}
    text = json.dumps(rec, sort_keys=True) + "\n"
    (root / "correspondence.jsonl").write_text(text, encoding="utf-8")
    man = json.loads((root / "MANIFEST.json").read_text())
    man["files"]["correspondence.jsonl"] = il._sha(text)
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    review = tmp_path / "reviews.jsonl"
    review.write_text("".join(json.dumps(x) + "\n" for x in (_header_line(), _intent_line())), encoding="utf-8")
    monkeypatch.setattr(il, "repo_root", lambda: tmp_path)
    return root, mod, review


def test_review_command_applies_in_place_and_check_tracks_the_file(tmp_path, monkeypatch, capsys):
    root, mod, review = _review_overlay(tmp_path, monkeypatch)
    assert mod.review(root, [review]) == 0
    man = il.load_manifest(root)
    assert man["reviews"][0]["lines"] == 2 and man["reviews"][0]["sha256"] == il._sha(review.read_text())
    assert man["counts"]["correspondence"] == {"intent": {"correction": 1}, "sender": {"gap_fill": 1}}
    assert il.verify(root) == []
    files = {p.name: p.read_bytes() for p in root.iterdir()}
    assert mod.review(root, [review]) == 0  # nothing to change: same files
    assert {p.name: p.read_bytes() for p in root.iterdir()} == files
    # A review file edited after it was applied fails check until it is applied again.
    review.write_text(review.read_text().replace('"request"', '"update"'), encoding="utf-8")
    assert any("changed since it was applied" in p for p in il.verify(root))
    assert mod.review(root, [review]) == 0 and il.verify(root) == []
    assert il.load_overlay(root)["E1"]["labels"]["intent"]["value"] == "update"
    # A label edited by hand away from its review fails too (after the manifest hash is redone).
    path = root / "correspondence.jsonl"
    rec = json.loads(path.read_text())
    rec["labels"]["sender"]["value"] = "Someone Else"
    text = json.dumps(rec, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    man = il.load_manifest(root)
    man["files"]["correspondence.jsonl"] = il._sha(text)
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    assert any("E1.sender: the review is not applied" in p for p in il.verify(root))


def test_review_command_refuses_bad_lines_and_new_class_files(tmp_path, monkeypatch, capsys):
    root, mod, review = _review_overlay(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(_header_line(value="Jeff Skilling")) + "\n", encoding="utf-8")
    assert mod.review(root, [bad]) == 1
    assert "not in the quoted header" in capsys.readouterr().out
    other = tmp_path / "other.jsonl"
    other.write_text(json.dumps(_header_line(doc_id="E9", doc_class="contract")) + "\n", encoding="utf-8")
    assert mod.review(root, [other]) == 1
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_review_command_rolls_back_when_the_manifest_write_fails(tmp_path, monkeypatch):
    root, mod, review = _review_overlay(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    real = mod._replace

    def failing(path, text):
        if path.name == "MANIFEST.json":
            raise OSError("disk full")
        real(path, text)

    monkeypatch.setattr(mod, "_replace", failing)
    with pytest.raises(OSError, match="disk full"):
        mod.review(root, [review])
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_reviewed_labels_reach_production_rows_over_the_hub_intent():
    text = "Please send the report."
    row = _row("correspondence", "notice", text, intent="notice", intent_source="heuristic")
    rec = {"doc_id": "D1", "doc_class": "correspondence", "doc_subclass": "notice", "doc_sha256": il.doc_sha(text),
           "labels": {}, "source": {"review": "r.jsonl"}}
    lines = [_intent_line(doc_id="D1", doc_sha256=il.doc_sha(text)),
             _header_line(doc_id="D1", doc_sha256=il.doc_sha(text))]
    assert il.apply_reviews({"D1": rec}, lines, "r.jsonl") == (2, [])
    exp = json.loads(il.apply_overlay(row, {"D1": rec}, overlay_sha="abc")["expected_fields"])
    assert exp["intent"] == "request"            # the reviewed correction replaces the Hub value
    assert exp["sender"] == "Ann M Schmidt"      # the header fill labels a field the Hub leaves empty


# ── Hub parquet rows ───────────────────────────────────────────────────────


def _hub_gt_row(doc="D1", text="Please send the report.", **fields):
    """A Hub ``ground_truth`` row: document_id, gt_fields as a JSON string, no document text."""
    import hashlib

    gt = {"intent": "notice", "intent_source": "heuristic", "sender": "",
          "gt_presence": json.dumps({"intent": "populated"}), **fields}
    return {"filename": f"{doc}.txt", "document_id": doc, "expected": "correspondence", "expected_subclass": "notice",
            "gt_fields": json.dumps(gt), "content_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _reviewed_overlay(text="Please send the report."):
    rec = {"doc_id": "D1", "doc_class": "correspondence", "doc_subclass": "notice", "doc_sha256": il.doc_sha(text),
           "labels": {}, "source": {"review": "r.jsonl"}}
    lines = [_intent_line(doc_id="D1", doc_sha256=il.doc_sha(text)),
             _header_line(doc_id="D1", doc_sha256=il.doc_sha(text))]
    assert il.apply_reviews({"D1": rec}, lines, "r.jsonl") == (2, [])
    return {"D1": rec}


def test_apply_overlay_takes_a_hub_ground_truth_row_without_text():
    overlay = _reviewed_overlay()
    row = _hub_gt_row()
    out = il.apply_overlay(row, overlay, overlay_sha="abc")
    gt = json.loads(out["gt_fields"])  # written back where the Hub keeps it, still a JSON string
    assert "expected_fields" not in out
    assert gt["intent"] == "request" and gt["sender"] == "Ann M Schmidt"
    assert json.loads(gt["gt_presence"])["sender"] == "populated"
    assert out["interim_labels"] == {"fields": ["intent", "sender"], "overlay_sha256": "abc"}
    # The text, when the row has it, decides; a content hash of other text never matches.
    assert il.apply_overlay({**row, "doc_text": "Other text."}, overlay, overlay_sha="abc") == {**row, "doc_text": "Other text."}
    assert il.apply_overlay(_hub_gt_row(text="Other text."), overlay, overlay_sha="abc").get("interim_labels") is None
    assert il.apply_overlay({**row, "content_sha256": "not-a-hash"}, overlay, overlay_sha="abc").get("interim_labels") is None
    assert il.row_id(row) == "D1" and il.row_doc_sha(row) == overlay["D1"]["doc_sha256"]
    # superseded() reads the same shape: a Hub sender label now supersedes nothing reviewed,
    # but a gap fill the Hub labels is reported.
    gate = {"D1": {**overlay["D1"], "labels": {"recipient": {"value": "Bo", "status": "gap_fill", "use_as_truth": True}}}}
    assert il.superseded([_hub_gt_row(recipient="Bo", gt_presence=json.dumps({"recipient": "populated"}))], gate) == [
        ("D1", "recipient")]


def test_apply_overlay_parquet_keeps_the_shard_schema(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    src = tmp_path / "ground_truth.parquet"
    pq.write_table(pa.Table.from_pylist([_hub_gt_row(), _hub_gt_row("D2")]), src)
    out = tmp_path / "out" / "overlaid.parquet"
    table = il.apply_overlay_parquet(src, out, overlay=_reviewed_overlay(), overlay_sha="abc")
    assert table.column_names == [*pq.read_schema(src).names, "interim_labels"]
    assert pq.read_table(out).equals(table)
    rows = table.to_pylist()
    assert json.loads(rows[0]["gt_fields"])["intent"] == "request"
    assert json.loads(rows[0]["interim_labels"]) == {"fields": ["intent", "sender"], "overlay_sha256": "abc"}
    assert rows[1]["interim_labels"] is None and json.loads(rows[1]["gt_fields"])["intent"] == "notice"
    with pytest.raises(ValueError, match="applied before"):
        il.apply_overlay_parquet(out, overlay={}, overlay_sha="")
    with pytest.raises(ValueError, match="overwrite the source"):
        il.apply_overlay_parquet(src, src, overlay={}, overlay_sha="")
    with pytest.raises(ValueError, match="not a ground_truth shard"):
        il.apply_overlay_parquet(pa.table({"filename": ["a"], "doc_text": ["x"]}), overlay={}, overlay_sha="")


def test_apply_overlay_parquet_refuses_an_inconsistent_committed_overlay(monkeypatch):
    pa = pytest.importorskip("pyarrow")
    monkeypatch.setattr(il, "verify", lambda root=None, **_: ["x.jsonl: sha256 differs"])
    with pytest.raises(ValueError, match="inconsistent"):
        il.apply_overlay_parquet(pa.Table.from_pylist([_hub_gt_row()]))


def test_apply_and_check_commands_read_parquet(tmp_path, monkeypatch, capsys):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    root, mod, review = _review_overlay(tmp_path, monkeypatch)
    assert mod.review(root, [review]) == 0
    src = tmp_path / "gt.parquet"
    pq.write_table(pa.Table.from_pylist([_hub_gt_row("E1", sender="Ann M Schmidt",
                                                     gt_presence=json.dumps({"sender": "populated"}))]), src)
    monkeypatch.setattr(il, "row_doc_sha", lambda row: _EMAIL_SHA)  # the fixture record's text hash
    capsys.readouterr()
    assert mod.main(["--root", str(root), "apply", "--parquet", str(src), "--out", str(tmp_path / "o.parquet")]) == 0
    # The Hub labels sender here, so only the intent correction applies: a gap fill never overrides it.
    assert "applied: 1 labels on 1 of 1 rows" in capsys.readouterr().out
    gt = json.loads(pq.read_table(tmp_path / "o.parquet").to_pylist()[0]["gt_fields"])
    assert gt["intent"] == "request" and gt["sender"] == "Ann M Schmidt"
    assert mod.main(["--root", str(root), "apply", "--parquet", str(src), "--out", str(src)]) == 1
    assert "overwrite the source" in capsys.readouterr().out
    monkeypatch.setattr(mod, "_local_gate_runs", lambda: {})
    # The Hub now labels sender: the reviewed fill is reported, kept by --prune, and fails nothing.
    assert mod.main(["--root", str(root), "check", "--rows", str(src), "--prune"]) == 0
    assert "note: E1.sender: a reviewed label the Hub rows supersede is kept" in capsys.readouterr().out
    assert "sender" in il.load_overlay(root)["E1"]["labels"] and il.verify(root) == []
    # A text change keeps the reviewed labels and prunes only the gate labels of the record.
    rec = json.loads((root / "correspondence.jsonl").read_text())
    rec["labels"]["recipient"] = {"value": "Bo", "status": "gap_fill", "use_as_truth": True}
    text = json.dumps(rec, sort_keys=True) + "\n"
    (root / "correspondence.jsonl").write_text(text, encoding="utf-8")
    man = il.load_manifest(root)
    man["files"]["correspondence.jsonl"] = il._sha(text)
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    monkeypatch.setattr(il, "row_doc_sha", lambda row: "f" * 16)
    assert mod.main(["--root", str(root), "check", "--rows", str(src), "--prune"]) == 0
    assert il.load_overlay(root)["E1"]["labels"].keys() == {"intent", "sender"} and il.verify(root) == []


def test_empty_header_values_must_match_empty_headers():
    def why(field, value, *headers, **over):
        ev = [{"source": il.HEADER_SOURCE, "file": "f/1.", "header": h} for h in headers]
        return il.review_line_problem(_header_line(field, value, headers[0], evidence=ev, **over))
    assert why("sender", None, "X-From: ") is None
    assert "header states it" in why("sender", None, "X-From: Ann M Schmidt")
    assert why("recipient", None, "X-To: ") is None
    assert "header states it" in why("recipient", None, "X-To: ", "To: bo@enron.com")
    assert why("communication_date", None, "Date: ") is None
    assert "states a date" in why("communication_date", None, "Date: Mon, 14 May 2001 09:02:00 -0700")
    # additional_recipients may be empty when the To line names only the recipient and no one is cc'd.
    assert why("additional_recipients", [], "X-To: Jacobson, Michael </O=ENRON/CN=Mjacobso>", "X-cc: ",
               "To: michael.jacobson@enron.com") is None
    assert "names more people" in why("additional_recipients", [], "X-To: ", "X-cc: Sue Mara")
    assert "names more people" in why("additional_recipients", [], "X-To: Jeff Dasovich, Sue Mara")
    assert "names more people" in why("additional_recipients", [], "To: a@enron.com, b@enron.com")
    # mixed forms: a bracketed address and a bare one are two people
    assert "names more people" in why("additional_recipients", [], "To: Alice <alice@enron.com>, bob@enron.com")
    assert il._addressees("Jacobson, Michael </O=ENRON/CN=Mjacobso>") == 1
    assert il._addressees("Alice <alice@enron.com>, Bob <bob@enron.com>, carl@enron.com") == 3


def test_a_correction_needs_the_hub_value_it_replaces():
    for missing in ({}, {"hub_value": None}, {"hub_value": ""}):
        line = {k: v for k, v in _intent_line().items() if k != "hub_value"}
        assert "hub_value" in il.review_line_problem({**line, **missing})
    assert il.review_line_problem(_header_line()) is None  # a header gap fill has no Hub value


def test_review_keeps_earlier_files_and_refuses_a_label_reviewed_twice(tmp_path, monkeypatch, capsys):
    root, mod, review = _review_overlay(tmp_path, monkeypatch)
    assert mod.review(root, [review]) == 0
    second = tmp_path / "more.jsonl"
    second.write_text(json.dumps(_header_line("recipient", "Jeff Dasovich", "X-To: Jeff Dasovich")) + "\n",
                      encoding="utf-8")
    assert mod.review(root, [second]) == 0  # a disjoint file joins the first one
    man = il.load_manifest(root)
    assert sorted(e["path"].rsplit("/", 1)[-1] for e in man["reviews"]) == ["more.jsonl", "reviews.jsonl"]
    assert il.load_overlay(root)["E1"]["labels"].keys() == {"intent", "recipient", "sender"}
    assert il.verify(root) == []
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    clash = tmp_path / "clash.jsonl"
    clash.write_text(json.dumps(_header_line(value=None, header="X-From: ")) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert mod.review(root, [clash]) == 1
    assert "E1.sender is also reviewed in reviews.jsonl" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    # build refuses the same overlap.
    by_class = {"correspondence": [json.loads(line) for line in (root / "correspondence.jsonl").read_text().splitlines()]}
    with pytest.raises(SystemExit, match="also reviewed in"):
        mod._apply_review_files(by_class, [review, clash])
