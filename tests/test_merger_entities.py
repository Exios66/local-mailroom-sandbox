"""Phase 5 part 2: the offline merger entity check, near-gold tiers and the spot-check sample.

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 7); design part 7.
"""

from __future__ import annotations

import csv
import hashlib
import json

import pytest

from mailroom_sandbox import gold_labels, interim_labels
from mailroom_sandbox.job import merger_entities as me

DOC = ("AGREEMENT AND PLAN OF MERGER, dated as of May 1, 2020, by and among Parent Inc. and Target Corp. "
       "This Agreement is governed by the laws of the State of Delaware.")
GT = json.dumps({"No-Shop": {"answer": "Yes", "valid_classes": ["No", "Yes"]},
                 "Type of Consideration": {"answer": "All Cash", "valid_classes": ["All Cash", "All Stock"]}})


def _row(doc_id: str, text: str = DOC) -> dict:
    return {"id": doc_id, "expected_doc_class": "merger_agreement", "doc_text": text,
            "expected_fields": json.dumps({"maud_clause_labels": GT})}


def _item(doc_id: str, **extracted) -> dict:
    data = {"document_name": "Agreement and Plan of Merger", "governing_law": "State of Delaware",
            "acquirer": "Parent Inc.", "maud_clauses": ["No-Shop: Yes", "Type of Consideration: All Cash"],
            **extracted}
    return {"item_id": doc_id, "ok": True, "pred": {"doc_type": "merger_agreement", "stage": "archived",
                                                    "extracted_data": data}}


def _store(tmp_path, name: str, items: list[dict], *, digest: bool = True):
    run = tmp_path / name
    run.mkdir()
    (run / "dataset.jsonl").write_text("".join(json.dumps(_row(i["item_id"])) + "\n" for i in items))
    lock = {"run_id": name, "profile": "openrouter", "task": "pipeline", "job": {}, "confidence": {}}
    if digest:
        lock["dataset"] = {"sha256": hashlib.sha256((run / "dataset.jsonl").read_bytes()).hexdigest()}
    (run / "spec.lock.json").write_text(json.dumps(lock))
    (run / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
    return run


def _label(value, basis="near_gold:two_pass_agree", **extra) -> dict:
    return {"value": value, "basis": basis, "use_as_truth": basis.startswith("gate_"), **extra}


def _labels(tmp_path, records: dict[str, dict[str, dict]], name: str = "merger_agreement.jsonl"):
    root = tmp_path / "labels"
    root.mkdir(exist_ok=True)
    path = root / name
    path.write_text("".join(json.dumps({"doc_class": "merger_agreement", "doc_id": d, "doc_sha256": interim_labels.doc_sha(DOC),
                                        "labels": labs}) + "\n" for d, labs in records.items()))
    (root / "MANIFEST.json").write_text(json.dumps({"schema": "mailroom-interim-labels/v1",
                                                    "files": {name: hashlib.sha256(path.read_bytes()).hexdigest()}}))
    return path


LABELS = {"d1": {"governing_law": _label("State of Delaware"), "acquirer": _label("Parent Inc."),
                 "document_name": _label("Agreement and Plan of Merger", basis="gate_accepted_grounded")},
          "d2": {"governing_law": _label("State of New York"), "acquirer": _label("Parent Inc.")}}


def test_merger_target_fields_are_the_sixteen_entities_and_the_consideration():
    fields = gold_labels.target_fields("merger_agreement")
    assert len(fields) == 17 and fields[-1] == "merger_consideration"
    assert gold_labels.target_fields("merger_agreement", ("tier2",)) == ("merger_consideration",)
    assert "maud_clauses" not in fields


def test_a_field_with_no_labels_reads_unlabelled_not_zero(tmp_path):
    result = me.check(_store(tmp_path, "r1", [_item("d1"), _item("d2")]), _labels(tmp_path, LABELS))
    fields = result["fields"]
    assert fields["outside_date"] == {"accuracy": None, "n": 0, "source": None, "status": "unlabelled",
                                      "verified": None, "filled_on_null": 0}
    assert fields["governing_law"]["status"] == "scored" and fields["governing_law"]["n"] == 2
    assert fields["document_name"]["source"] == "interim" and fields["governing_law"]["source"] == "near_gold"


def test_fields_are_scored_by_the_suite_scorer_not_a_local_comparison(tmp_path, monkeypatch):
    from mailroom_sandbox.eval import scoring

    seen: list[dict] = []
    real = scoring.score_extraction_row

    def spy(*args, **kwargs):
        if set(args[2]) <= set(me.FIELDS):  # the entity calls (the MAUD headline call scores maud labels)
            seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(scoring, "score_extraction_row", spy)
    result = me.check(_store(tmp_path, "r1", [_item("d1"), _item("d2")]), _labels(tmp_path, LABELS))
    assert len(seen) == 2 and all(k.get("field_scores") is True for k in seen)
    assert result["fields"]["governing_law"]["accuracy"] < 1.0       # d2's label differs from the read


def test_near_gold_numbers_are_unverified_until_the_spot_check_is_recorded(tmp_path):
    labels = _labels(tmp_path, LABELS)
    run = _store(tmp_path, "r1", [_item("d1"), _item("d2")])
    before = me.check(run, labels)
    assert before["fields"]["governing_law"]["verified"] is False and before["spot_check"] is None
    assert before["fields"]["document_name"]["verified"] is None          # interim: not a near-gold number
    me.record_spot_check(_filled_sheet(tmp_path, labels, right=True), labels)
    after = me.check(run, labels)
    assert after["fields"]["governing_law"]["verified"] is True and after["spot_check"]["cite_blocked"] is False


def _filled_sheet(tmp_path, labels, *, right: bool | list[bool]):
    sheet = me.spot_sample(labels, n=2, seed=7, out_dir=tmp_path / "sheets")
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    marks = right if isinstance(right, list) else [right] * len(rows)
    for row, mark in zip(rows, marks):
        row["correct"] = "y" if mark else "n"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return sheet


def test_the_spot_sample_holds_every_labelled_field_of_its_documents(tmp_path):
    labels = _labels(tmp_path, LABELS)
    sheet = me.spot_sample(labels, n=5, seed=1, out_dir=tmp_path / "sheets")
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert {(r["doc_id"], r["field"]) for r in rows} == {("d1", "governing_law"), ("d1", "acquirer"),
                                                         ("d2", "governing_law"), ("d2", "acquirer")}
    assert all(r["correct"] == "" for r in rows)
    assert me.spot_sample(labels, n=5, seed=1, out_dir=tmp_path / "again").read_text() == sheet.read_text()


def test_a_spot_check_under_ninety_percent_blocks_citing(tmp_path):
    labels = _labels(tmp_path, LABELS)
    recorded = me.record_spot_check(_filled_sheet(tmp_path, labels, right=[True, True, True, False]), labels)
    assert recorded["agreement"] == 0.75 and recorded["cite_blocked"] is True
    manifest = json.loads((labels.parent / "MANIFEST.json").read_text())
    assert manifest["spot_check"]["merger_agreement.jsonl"]["cite_blocked"] is True
    result = me.check(_store(tmp_path, "r1", [_item("d1")]), labels)
    assert result["spot_check"]["cite_blocked"] is True
    assert "do not cite" in me.digest(result)


def test_an_unmarked_sheet_cannot_be_recorded(tmp_path):
    labels = _labels(tmp_path, LABELS)
    with pytest.raises(me.EntityCheckError, match="unmarked"):
        me.record_spot_check(me.spot_sample(labels, n=2, seed=7, out_dir=tmp_path / "s"), labels)


def test_paired_deltas_use_only_documents_in_both_runs(tmp_path):
    labels = _labels(tmp_path, LABELS)
    base = _store(tmp_path, "base", [_item("d1", governing_law="Delaware", acquirer=None), _item("d2")])
    arm = _store(tmp_path, "arm", [_item("d1")])
    result = me.check(arm, labels, baseline=base)
    pair = result["paired"]
    assert pair["n_docs"] == 1
    assert pair["fields"]["acquirer"]["n"] == 1 and pair["fields"]["acquirer"]["delta"] == 1.0
    assert pair["fields"]["governing_law"]["delta"] > 0
    assert set(pair["maud_accuracy"]) == {"run", "baseline"}


def test_a_document_whose_text_changed_since_labelling_is_not_scored(tmp_path):
    labels = _labels(tmp_path, LABELS)
    run = _store(tmp_path, "r1", [_item("d1")])
    rows = [json.loads(line) for line in (run / "dataset.jsonl").read_text().splitlines()]
    rows[0]["doc_text"] = DOC + " Amended."
    (run / "dataset.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    lock = json.loads((run / "spec.lock.json").read_text())
    lock["dataset"]["sha256"] = hashlib.sha256((run / "dataset.jsonl").read_bytes()).hexdigest()
    (run / "spec.lock.json").write_text(json.dumps(lock))
    result = me.check(run, labels)
    assert result["fields"]["governing_law"]["status"] == "unlabelled" and result["counts"]["stale_labels"] == 1


def test_it_refuses_a_running_run_a_drifted_dataset_an_output_inside_the_run_and_a_missing_file(tmp_path):
    labels = _labels(tmp_path, LABELS)
    run = _store(tmp_path, "r1", [_item("d1")])
    (run / "checkpoint.json").write_text(json.dumps({"state": "running"}))
    with pytest.raises(me.EntityCheckError, match="running|finished"):
        me.check(run, labels)
    (run / "checkpoint.json").write_text(json.dumps({"state": "done"}))
    result = me.check(run, labels)
    with pytest.raises(me.EntityCheckError, match="inside the source run"):
        me.write_check(result, run / "check.json", source=run)
    with pytest.raises(me.EntityCheckError, match="missing|not found|No such"):
        me.check(run, tmp_path / "nope.jsonl")
    with pytest.raises(me.EntityCheckError):
        me.check(tmp_path / "no-such-run", labels)
    with (run / "dataset.jsonl").open("a") as fh:
        fh.write(json.dumps(_row("extra")) + "\n")
    with pytest.raises(me.EntityCheckError, match="dataset.jsonl changed"):
        me.check(run, labels)


def test_it_never_writes_the_source_run(tmp_path):
    labels = _labels(tmp_path, LABELS)
    run = _store(tmp_path, "r1", [_item("d1"), _item("d2")])

    def snapshot():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.iterdir())}

    before = snapshot()
    result = me.check(run, labels)
    me.write_check(result, tmp_path / "out" / "check.json", source=run)
    assert snapshot() == before


def test_the_digest_says_it_is_an_offline_check_not_the_headline(tmp_path):
    result = me.check(_store(tmp_path, "r1", [_item("d1")]), _labels(tmp_path, LABELS))
    text = me.digest(result, tmp_path / "check.json")
    assert text.startswith("offline entity check (not the headline)")
    assert "outside_date: unlabelled" in text and "unverified" in text


def test_the_script_runs_end_to_end(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("merger_entity_check", "scripts/merger_entity_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run = _store(tmp_path, "r1", [_item("d1")])
    out = tmp_path / "out.json"
    assert mod.main(["--run", str(run), "--labels", str(_labels(tmp_path, LABELS)), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["label"] == me.LABEL
    assert mod.main(["--run", str(run), "--labels", str(tmp_path / "labels" / "merger_agreement.jsonl"),
                     "--out", str(run / "x.json")]) == 2


def test_a_value_read_where_the_label_says_absent_is_counted_not_dropped(tmp_path):
    # Final review F7: a null label is not scored, but a filled read on it is a made-up value to report.
    labels = _labels(tmp_path, {"d1": {"governing_law": _label(None), "acquirer": _label(None)},
                                "d2": {"governing_law": _label("State of New York")}})
    result = me.check(_store(tmp_path, "r1", [_item("d1", acquirer=""), _item("d2")]), labels)
    assert result["counts"]["null_labels"] == 2 and result["counts"]["filled_on_null"] == 1
    assert result["fields"]["governing_law"]["filled_on_null"] == 1      # d1 read Delaware where none is
    assert result["fields"]["acquirer"]["filled_on_null"] == 0           # an empty read is no fill
    assert "filled where the label is null 1" in me.digest(result)


def test_two_label_files_with_one_name_keep_their_own_spot_checks(tmp_path):
    # Final review F8: a checked file must not lend its spot check to an unchecked file of the same name.
    for side in ("a", "b"):
        (tmp_path / side).mkdir()
    checked = _labels(tmp_path / "a", {"d1": LABELS["d1"]})
    unchecked = _labels(tmp_path / "b", {"d2": LABELS["d2"]})
    me.record_spot_check(_filled_sheet(tmp_path, checked, right=True), checked)
    run = _store(tmp_path, "r1", [_item("d1"), _item("d2")])
    for order in ([unchecked, checked], [checked, unchecked]):
        result = me.check(run, order)
        assert result["fields"]["governing_law"]["verified"] is False, order
        assert len(result["label_files"]) == 2 and result["spot_check"]["cite_blocked"] is True


def test_the_digest_names_maud_as_context_not_the_gate_headline(tmp_path):
    # Final review F9: the gate's headline is the paired MAUD run, not this subset of finished mergers.
    text = me.digest(me.check(_store(tmp_path, "r1", [_item("d1")]), _labels(tmp_path, LABELS)))
    assert "MAUD on finished mergers (not the gate's headline):" in text
    assert "headline, for context" not in text


def test_it_never_writes_inside_the_baseline_run_either(tmp_path):
    # Final review F10: the baseline is a source run too.
    import importlib.util

    labels = _labels(tmp_path, LABELS)
    run, base = _store(tmp_path, "r1", [_item("d1")]), _store(tmp_path, "r0", [_item("d1")])
    result = me.check(run, labels, baseline=base)
    with pytest.raises(me.EntityCheckError, match="inside the source run"):
        me.write_check(result, base / "check.json", source=[run, base])
    spec = importlib.util.spec_from_file_location("merger_entity_check", "scripts/merger_entity_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--run", str(run), "--labels", str(labels), "--baseline", str(base),
                     "--out", str(base / "x.json")]) == 2
    assert not (base / "x.json").exists()
