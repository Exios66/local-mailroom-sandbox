"""Production slice gate: bars, per-document outcome, pooled Wilson rates and verdict (offline)."""
from __future__ import annotations

import json
import math

import pytest

from mailroom_sandbox.job import gate
from mailroom_sandbox.job.gate import Bars

CATEGORIES = ("Agreement Date", "Anti-Assignment", "Governing Law", "Parties", "Document Name")


def cuad(gold=2):
    """A CUAD-only contract label set as real E3 rows carry it: every category, gold spans on ``gold`` of them."""
    spans = {c: ([{"start": 3, "text": c.lower()}] if i < gold else []) for i, c in enumerate(CATEGORIES)}
    return {"cuad_clause_labels": spans, "label_evidence": "CUAD-annotated clauses: ...",
            "clause_count": str(len(CATEGORIES)), "gt_presence": {"parties": "not_applicable"}}


def maud(gold=2):
    """MAUD question to answer labels, as merger rows carry them (an empty answer is no gold)."""
    return {"maud_clause_labels": {f"Q{i}": ({"answer": "yes", "category": "x"} if i < gold else {})
                                   for i in range(4)},
            "label_evidence": "MAUD ...", "maud_label_count": "4"}


LABELS = {  # a scorable label set per class
    "contract": cuad(),
    "merger_agreement": maud(),
    "corporate_record": {"entity_name": "Acme Corp", "record_type": "bylaws"},
    "correspondence": {"sender": "A. Smith", "recipient": "B. Jones"},
    "insurance_claim": {"claim_number": "C-1", "policy_number": "P-9"},
}


def _run(root, docs, name="slice"):
    """docs: dicts with id, cls, and optional expected/stage/score/causes/error/item/repeat."""
    run = root / name
    run.mkdir()
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for d in docs:
            ds.write(json.dumps({"id": d["id"], "expected_doc_class": d["cls"],
                                 "expected_fields": json.dumps(d.get("expected", LABELS[d["cls"]]))}) + "\n")
            if d.get("item", True) is False:
                continue
            for _ in range(d.get("repeat", 1)):
                pred = {"stage": d.get("stage", "archived"), "extracted_data": {},
                        "review_causes": d.get("causes") or [], "_score": d.get("score", 0.95),
                        **({"arbiter_caveats": d["caveats"]} if "caveats" in d else {}),
                        **({"judge_reasks": d["reasks"]} if "reasks" in d else {})}
                it.write(json.dumps({"item_id": d["id"], "ok": d.get("error") is None, "error": d.get("error"),
                                     "prompt_tokens": 10, "completion_tokens": 5, "pred": pred}) + "\n")
    return run


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))


@pytest.fixture(autouse=True)
def no_audit(monkeypatch):
    """These tests are about outcomes, not the audit trail (``tests/test_gate_audit.py``): their run dirs are loose."""
    real = gate.gate_report
    monkeypatch.setattr(gate, "gate_report", lambda run_dir, bars, **kw: real(run_dir, bars, **{"audit": False, **kw}))


def _docs(n, cls="contract", **kw):
    return [{"id": f"{cls}-{i}", "cls": cls, **kw} for i in range(n)]


def test_outcomes_follow_score_and_stage(tmp_path):
    one = cuad(gold=0)  # every CUAD category empty: nothing to score
    run = _run(tmp_path, [
        {"id": "ok", "cls": "contract", "score": 0.95},
        {"id": "bad", "cls": "contract", "score": 0.6},
        {"id": "rev", "cls": "contract", "stage": "review"},
        {"id": "few", "cls": "contract", "expected": one},
    ])
    out = {d["id"]: d for d in gate.gate_report(run, Bars())["docs"]}
    assert out["ok"]["outcome"] == "correct_archive" and out["ok"]["score"] == 0.95 and out["ok"]["scorable"]
    assert out["bad"]["outcome"] == "wrong_archive"
    assert out["rev"]["outcome"] == "review" and out["rev"]["stage"] == "review"
    assert out["few"]["outcome"] == "unscorable_archive" and out["few"]["scorable"] is False
    assert out["ok"]["class"] == "contract" and out["ok"]["tokens"] == 15


def test_caveat_archives_are_marked_counted_and_scored(tmp_path):
    """HF-014: an archive the arbiter accepted with caveats is scored like any other, and shown apart."""
    marker = {"decision": "accept_with_caveats", "judge_verdict": "partial", "whole_source": True, "hf014": True}
    run = _run(tmp_path, [{"id": "cav", "cls": "contract", "score": 0.95, "caveats": marker},
                          {"id": "old", "cls": "contract", "score": 0.6, "caveats": {**marker, "hf014": False}},
                          {"id": "clean", "cls": "contract", "score": 0.95}])
    report = gate.gate_report(run, Bars())
    out = {d["id"]: d for d in report["docs"]}
    assert out["cav"]["arbiter_caveats"] and out["cav"]["caveats_hf014"] and out["cav"]["outcome"] == "correct_archive"
    assert out["old"]["outcome"] == "wrong_archive" and not out["old"]["caveats_hf014"]
    assert "arbiter_caveats" not in out["clean"]
    assert report["arbiter_caveats"] == {"archives": 2, "hf014": 1, "docs": ["cav", "old"]}
    assert report["pooled"]["scorable"] == 3  # caveat archives stay in the score denominators


def test_a_run_without_caveat_archives_keeps_its_report_shape(tmp_path):
    assert "arbiter_caveats" not in gate.gate_report(_run(tmp_path, _docs(3)), Bars())


def test_judge_re_asks_are_counted_with_their_outcome(tmp_path):
    """HF-002 / HF-013: every re-ask ends recovered, parked (the second answer did not parse) or errored."""
    run = _run(tmp_path, [
        {"id": "ok", "cls": "contract", "score": 0.95,
         "reasks": {"completeness": {"asked": 1, "recovered": 1, "parked": 0}}},
        # a re-ask that raised (transport error, guard refusal): not recovered, not parked; HF-012 re-ran
        # the node and the document archived
        {"id": "both", "cls": "contract", "score": 0.95,
         "reasks": {"completeness": {"asked": 1, "recovered": 1}, "correctness": {"asked": 1, "recovered": 0}}},
        {"id": "parked", "cls": "contract", "stage": "review", "causes": ["judge_error"],
         "reasks": {"correctness": {"asked": 1, "recovered": 0, "parked": 1}}},
        {"id": "clean", "cls": "contract", "score": 0.95}])
    report = gate.gate_report(run, Bars())
    assert report["judge_reasks"] == {
        "documents": 3, "asked": 4, "recovered": 2, "parked": 1, "errored": 1,
        "by_judge": {"completeness": {"asked": 2, "recovered": 2, "parked": 0, "errored": 0},
                     "correctness": {"asked": 2, "recovered": 0, "parked": 1, "errored": 1}},
        "docs": ["ok", "both", "parked"]}
    block = report["judge_reasks"]
    assert block["asked"] == block["recovered"] + block["parked"] + block["errored"]
    out = {d["id"]: d for d in report["docs"]}
    assert out["ok"]["judge_reasks"] == {"completeness": {"asked": 1, "recovered": 1, "parked": 0}}
    assert out["both"]["judge_reasks"]["correctness"] == {"asked": 1, "recovered": 0, "parked": 0}
    assert "judge_reasks" not in out["clean"]
    assert report["pooled"]["judge_errors"] == 1  # the re-ask whose second answer failed too parked a document


def test_a_re_ask_made_by_a_document_that_ended_as_an_error_row_still_counts(tmp_path):
    """A pipeline abort the run returned (not raised) is an error item whose pred carries the counts (M2)."""
    run = _run(tmp_path, [
        {"id": "boom", "cls": "contract", "error": "pipeline failed",
         "reasks": {"completeness": {"asked": 1, "recovered": 0, "parked": 0}}},
        {"id": "fine", "cls": "contract", "score": 0.95}])
    report = gate.gate_report(run, Bars())
    boom = {d["id"]: d for d in report["docs"]}["boom"]
    assert boom["outcome"] == "crashed" and report["pooled"]["crashes"] == 1
    assert report["judge_reasks"]["docs"] == ["boom"]
    assert report["judge_reasks"]["errored"] == 1 and report["judge_reasks"]["asked"] == 1


def test_a_run_without_judge_re_asks_keeps_its_report_shape(tmp_path):
    assert "judge_reasks" not in gate.gate_report(_run(tmp_path, _docs(3)), Bars())


def test_bar_edge_is_inclusive(tmp_path):
    run = _run(tmp_path, [{"id": "edge", "cls": "contract", "score": 0.90}])
    assert gate.gate_report(run, Bars())["docs"][0]["outcome"] == "correct_archive"


def test_pooled_rates_and_pass(tmp_path):
    docs = _docs(39) + [{"id": "r", "cls": "contract", "stage": "review"}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["n"] == 40 and report["run_id"] == "slice"
    assert report["pooled"]["review_rate"] == pytest.approx(0.025)
    assert report["pooled"]["wrong_archive_rate"] == 0
    assert report["verdict"] == {"pass": True, "reasons": [], "warnings": []}
    assert report["bars"]["quality"] == 0.90 and report["bars"]["gated"][0] == "contract"
    cls = report["classes"]["contract"]
    assert cls["n"] == 40 and cls["gated"] is True and cls["tokens_per_doc"] == 15
    assert cls["correct_archive_rate"] == pytest.approx(39 / 40)


def test_wilson_upper_bounds(tmp_path):
    docs = _docs(39) + [{"id": "r", "cls": "contract", "stage": "review"}]
    pooled = gate.gate_report(_run(tmp_path, docs), Bars())["pooled"]
    z, k, n = 1.96, 1, 40
    p = k / n
    expected = (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
    assert pooled["review_upper95"] == pytest.approx(expected)
    assert 0.0 < pooled["wrong_archive_upper95"] < 0.1  # 0 of 39 still has a non-zero upper bound


def test_wrong_archive_bar_fails(tmp_path):
    docs = _docs(29) + [{"id": "w", "cls": "contract", "score": 0.5}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["verdict"]["pass"] is False
    assert "wrong_archive_rate 0.033 > 0.02" in report["verdict"]["reasons"]


def test_review_bar_fails(tmp_path):
    docs = _docs(18) + [{"id": f"r{i}", "cls": "contract", "stage": "review"} for i in range(2)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["verdict"]["pass"] is False
    assert "review_rate 0.100 > 0.05" in report["verdict"]["reasons"]


def test_mergers_are_reported_not_gated(tmp_path):
    docs = _docs(40) + [{"id": f"m{i}", "cls": "merger_agreement", "score": 0.2} for i in range(5)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    merger = report["classes"]["merger_agreement"]
    assert merger["gated"] is False and merger["wrong_archive_rate"] == 1.0 and merger["n"] == 5
    assert report["pooled"]["wrong_archive_rate"] == 0 and report["pooled"]["review_rate"] == 0
    assert report["verdict"]["pass"] is True


def test_per_class_bar_applies_from_500(tmp_path):
    # contract: 2 wrong of 40 (0.05); two other gated classes are clean. Pooled 2/120 = 0.017.
    docs = (_docs(38) + [{"id": f"w{i}", "cls": "contract", "score": 0.5} for i in range(2)]
            + _docs(40, "corporate_record") + _docs(40, "correspondence"))
    run = _run(tmp_path, docs)
    below = gate.gate_report(run, Bars())
    assert below["n"] == 120 and below["classes"]["contract"]["wrong_archive_rate"] == pytest.approx(0.05)
    assert below["pooled"]["wrong_archive_rate"] == pytest.approx(2 / 120)
    assert below["verdict"]["pass"] is True  # pooled rate decides below slice 500

    above = gate.gate_report(run, Bars(per_class_from_n=100))
    assert above["verdict"]["pass"] is False
    assert any("contract" in r and "wrong_archive_rate" in r for r in above["verdict"]["reasons"])


def test_missing_items_are_crashes_and_fail(tmp_path):
    docs = _docs(39) + [{"id": "lost", "cls": "contract", "item": False}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    lost = next(d for d in report["docs"] if d["id"] == "lost")
    assert lost["stage"] == "crashed" and lost["outcome"] == "crashed" and lost["score"] is None
    assert report["pooled"]["crashes"] == 1
    assert report["verdict"]["pass"] is False and any("crash" in r for r in report["verdict"]["reasons"])


def test_errored_items_are_crashes(tmp_path):
    docs = _docs(39) + [{"id": "boom", "cls": "contract", "error": "RuntimeError: x"}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["crashes"] == 1 and report["verdict"]["pass"] is False


def test_duplicate_items_keep_latest(tmp_path):
    run = tmp_path / "dup"
    run.mkdir()
    (run / "dataset.jsonl").write_text(json.dumps(
        {"id": "d1", "expected_doc_class": "contract", "expected_fields": json.dumps(cuad())}) + "\n")
    first = {"item_id": "d1", "ok": True, "error": None, "pred": {"stage": "review", "_score": None}}
    last = {"item_id": "d1", "ok": True, "error": None, "pred": {"stage": "archived", "_score": 0.97}}
    (run / "items.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n")
    report = gate.gate_report(run, Bars())
    assert report["n"] == 1 and report["docs"][0]["outcome"] == "correct_archive"
    assert report["pooled"]["review_rate"] == 0


def test_judge_error_fails(tmp_path):
    docs = _docs(39) + [{"id": "j", "cls": "contract", "stage": "review", "causes": ["judge_error"]}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["judge_errors"] == 1
    assert report["verdict"]["pass"] is False and any("judge_error" in r for r in report["verdict"]["reasons"])


def test_no_gated_documents_fails(tmp_path):
    report = gate.gate_report(_run(tmp_path, _docs(5, "merger_agreement")), Bars())
    assert report["pooled"]["review_rate"] is None and report["pooled"]["wrong_archive_rate"] is None
    assert report["pooled"]["review_upper95"] is None
    assert report["verdict"] == {"pass": False, "reasons": ["no gated documents"], "warnings": []}


def test_labelled_count_scopes_and_drops_templated():
    corp = {"expected_doc_class": "corporate_record", "expected_fields": json.dumps({
        "entity_name": "Acme", "record_type": "bylaws", "keywords": ["EX-3.1"],
        "subject_matter": "bylaws of Acme", "filing_number": "", "signatories": [],
        "gt_presence": {"entity_name": "present"}, "clause_count": "7"})}
    assert gate.labelled_count(corp, "corporate_record") == 2  # templated, blank, metadata and foreign keys are not labels
    claim = {"expected_fields": json.dumps({"claim_number": "C1", "denial_reasons": [], "document_name": "x"})}
    assert gate.labelled_count(claim, "insurance_claim") == 1
    assert gate.labelled_count({"expected_fields": ""}, "contract") == 0
    evidence = {"expected_fields": json.dumps({"document_name": "x", "label_evidence": "CUAD-annotated clauses: ..."})}
    assert gate.labelled_count(evidence, "contract") == 0  # the Dojo scores contracts on CUAD only


def test_corpus_annotations_the_dojo_never_scores_are_not_labels(tmp_path):
    """A correspondence row whose only scored field is intent is unscorable, not a 4-label row."""
    annotated = {"intent": "update", "content_topic": "general_business", "sentiment_label": "neutral",
                 "sentiment_score": "0.0476", "keywords": ["email"], "subject_matter": "Correspondence concerning x"}
    row = {"expected_doc_class": "correspondence", "expected_fields": json.dumps(annotated)}
    assert gate.labelled_count(row, "correspondence") == 1
    with_sender = {**annotated, "sender": "A. Smith"}
    assert gate.labelled_count({"expected_fields": json.dumps(with_sender)}, "correspondence") == 2
    claim = {**LABELS["insurance_claim"], "content_topic": "auto", "sentiment_label": "negative"}
    assert gate.labelled_count({"expected_fields": json.dumps(claim)}, "insurance_claim") == 2
    (doc,) = gate.gate_report(_run(tmp_path, [{"id": "c0", "cls": "correspondence", "expected": annotated}]),
                              Bars())["docs"]
    assert doc["outcome"] == "unscorable_archive" and doc["labelled"] == 1


def test_contract_scored_on_cuad_units():
    row = {"expected_fields": json.dumps(cuad(gold=2))}
    assert gate.labelled_count(row, "contract") == len(CATEGORIES)  # the scored universe, not the gold count
    as_text = {"expected_fields": json.dumps({**cuad(gold=1), "cuad_clause_labels": json.dumps(cuad(1)["cuad_clause_labels"])})}
    assert gate.labelled_count(as_text, "contract") == len(CATEGORIES)  # E3 stores the labels as a JSON string
    assert gate.labelled_count({"expected_fields": cuad(gold=1)}, "contract") == len(CATEGORIES)  # dict expected_fields
    assert gate.labelled_count({"expected_fields": json.dumps(cuad(gold=0))}, "contract") == 0
    assert gate.labelled_count({"expected_fields": json.dumps({**cuad(), "cuad_clause_labels": {}})}, "contract") == 0
    assert gate.labelled_count({"expected_fields": json.dumps({**cuad(), "cuad_clause_labels": "{}"})}, "contract") == 0
    assert gate.labelled_count({"expected_fields": json.dumps({**cuad(), "cuad_clause_labels": "not json"})}, "contract") == 0


def test_merger_scored_on_maud_units():
    assert gate.labelled_count({"expected_fields": json.dumps(maud(gold=2))}, "merger_agreement") == 4
    assert gate.labelled_count({"expected_fields": json.dumps(maud(gold=0))}, "merger_agreement") == 0
    text = {"expected_fields": json.dumps({"maud_clause_labels": json.dumps(maud(1)["maud_clause_labels"])})}
    assert gate.labelled_count(text, "merger_agreement") == 4
    assert gate.labelled_count({"expected_fields": json.dumps({"document_name": "x", "parties": ["A"]})},
                               "merger_agreement") == 0


def test_cuad_contract_is_scorable_only_with_gold_spans(tmp_path):
    run = _run(tmp_path, [
        {"id": "gold", "cls": "contract", "expected": cuad(gold=3), "score": 0.95},
        {"id": "empty", "cls": "contract", "expected": cuad(gold=0), "score": 0.95},
    ])
    out = {d["id"]: d for d in gate.gate_report(run, Bars())["docs"]}
    assert out["gold"]["outcome"] == "correct_archive" and out["gold"]["labelled"] == len(CATEGORIES)
    assert out["empty"]["outcome"] == "unscorable_archive" and out["empty"]["labelled"] == 0


def test_all_unscorable_archives_never_pass_blind(tmp_path):
    docs = [{"id": f"u{i}", "cls": "contract", "expected": cuad(gold=0)} for i in range(10)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["wrong_archive_rate"] is None
    assert report["pooled"]["scorable"] == 0 and report["pooled"]["unscorable"] == 10
    assert report["verdict"]["pass"] is False
    assert "no scorable archives" in report["verdict"]["reasons"]


def test_review_only_slice_is_not_blind(tmp_path):
    docs = [{"id": f"r{i}", "cls": "contract", "stage": "review"} for i in range(2)]
    reasons = gate.gate_report(_run(tmp_path, docs), Bars())["verdict"]["reasons"]
    assert "no scorable archives" not in reasons  # no archives at all: the review bar speaks


def test_per_class_blind_class_fails_once_per_class_bars_apply(tmp_path):
    docs = [{"id": f"u{i}", "cls": "contract", "expected": cuad(gold=0)} for i in range(4)] + _docs(6, "correspondence")
    run = _run(tmp_path, docs)
    pooled_only = gate.gate_report(run, Bars())
    assert pooled_only["verdict"]["pass"] is True  # pooled has scorable archives; per-class bars are diagnostic
    per_class = gate.gate_report(run, Bars(per_class_from_n=10, min_scorable_per_class=0))
    assert per_class["verdict"]["pass"] is False
    assert "class contract no scorable archives" in per_class["verdict"]["reasons"]
    assert not any(r.startswith("class correspondence") for r in per_class["verdict"]["reasons"])
    assert not any(r.startswith("class merger") for r in per_class["verdict"]["reasons"])


def test_scorable_counts_and_unscorable_warnings(tmp_path):
    # 3 of 10 gated archives unscorable (0.3 > 0.25); the contract class is 3 of 4 unscorable.
    docs = ([{"id": f"u{i}", "cls": "contract", "expected": cuad(gold=0)} for i in range(3)]
            + _docs(1) + _docs(6, "correspondence"))
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["pooled"]["scorable"] == 7 and report["pooled"]["unscorable"] == 3
    assert report["classes"]["contract"]["scorable"] == 1 and report["classes"]["contract"]["unscorable"] == 3
    assert report["verdict"]["pass"] is True  # warnings never fail the slice
    warnings = report["verdict"]["warnings"]
    assert any(w.startswith("unscorable share 0.300") for w in warnings)
    assert any(w.startswith("class contract unscorable share 0.750") for w in warnings)
    assert not any(w.startswith("class correspondence") for w in warnings)


def test_no_warning_at_or_below_the_unscorable_share(tmp_path):
    docs = [{"id": "u", "cls": "contract", "expected": cuad(gold=0)}] + _docs(3)  # 1 of 4 = 0.25, pooled and per class
    assert gate.gate_report(_run(tmp_path, docs), Bars())["verdict"]["warnings"] == []


def test_merger_unscorable_does_not_warn_or_gate(tmp_path):
    docs = _docs(8) + [{"id": f"m{i}", "cls": "merger_agreement", "expected": maud(0)} for i in range(5)]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    assert report["verdict"] == {"pass": True, "reasons": [], "warnings": []}
    assert report["classes"]["merger_agreement"]["unscorable"] == 5


def test_load_bars_defaults_to_the_committed_config(tmp_path):
    bars = gate.load_bars()
    assert bars == Bars()
    custom = tmp_path / "b.yaml"
    custom.write_text("quality: 0.8\ngated: [contract]\n")
    loaded = gate.load_bars(custom)
    assert loaded.quality == 0.8 and loaded.gated == ("contract",) and loaded.review_max == 0.05
    custom.write_text("qualty: 0.8\n")
    with pytest.raises(ValueError, match="qualty"):
        gate.load_bars(custom)


def test_per_class_minimum_of_scorable_archives(tmp_path):
    """From the per-class slice size, a gated class with too few scorable archives fails (corporate, dojo#164)."""
    docs = (_docs(30) + _docs(25, "correspondence")
            + [{"id": f"c{i}", "cls": "corporate_record"} for i in range(5)])
    run = _run(tmp_path, docs)
    above = gate.gate_report(run, Bars(per_class_from_n=50, min_scorable_per_class=20))
    reasons = above["verdict"]["reasons"]
    assert "class corporate_record has 5 scorable archives < 20" in reasons
    assert not any(r.startswith("class contract has") or r.startswith("class correspondence has") for r in reasons)
    below = gate.gate_report(run, Bars(per_class_from_n=500, min_scorable_per_class=20))
    assert not any("scorable archives <" in r for r in below["verdict"]["reasons"] + below["verdict"]["warnings"])


def test_committed_bars_set_the_scorable_minimum():
    assert gate.load_bars().min_scorable_per_class == 20


def test_an_absent_gated_class_fails_the_scorable_minimum(tmp_path):
    """A 500-document slice with no corporate records must not pass the per-class minimum (#311 review)."""
    docs = _docs(30) + _docs(25, "correspondence") + _docs(25, "insurance_claim")
    reasons = gate.gate_report(_run(tmp_path, docs), Bars(per_class_from_n=50, min_scorable_per_class=20))["verdict"]["reasons"]
    assert "class corporate_record has 0 scorable archives < 20" in reasons
    assert not any(r.startswith(("class contract has", "class insurance_claim has")) for r in reasons)


def test_a_scorable_archive_the_scorer_cannot_score_fails_the_gate(tmp_path, monkeypatch):
    """Enough labels but no score is a scorer failure, not an unscorable archive (#311 review)."""
    docs = _docs(9) + [{"id": "lost", "cls": "contract", "score": None}]
    report = gate.gate_report(_run(tmp_path, docs), Bars())
    lost = next(d for d in report["docs"] if d["id"] == "lost")
    assert lost["outcome"] == "unscorable_archive" and lost["scorer_failed"] is True
    assert "1 archive(s) with enough labels that the scorer could not score" in report["verdict"]["reasons"]


def test_load_bars_rejects_a_duplicate_key(tmp_path):
    """A repeated bar would silently take the later, possibly looser, value (#311 review)."""
    custom = tmp_path / "b.yaml"
    custom.write_text("quality: 0.9\nquality: 0.5\n")
    with pytest.raises(ValueError, match="duplicate bar key 'quality'"):
        gate.load_bars(custom)


@pytest.mark.parametrize("item", [
    {"error": "x", "pred": "boom"}, {"error": "x", "pred": ["a"]}, {"ok": False, "pred": 3},
    {"error": "x", "pred": None}])
def test_an_error_row_with_a_malformed_pred_stays_crashed(item):
    """The base returned ``crashed`` before touching ``pred``; the re-ask read must not raise first."""
    status = gate._status({"row": {"id": "d", "expected_doc_class": "contract"}, "item": item}, Bars())
    assert status["outcome"] == "crashed" and "judge_reasks" not in status


@pytest.mark.parametrize("asked", ["x", "1.5", [1], float("inf"), float("nan")])
def test_a_malformed_re_ask_count_is_skipped_not_raised(asked):
    pred = {"stage": "review", "judge_reasks": {"completeness": {"asked": asked},
                                                "correctness": {"asked": 1, "recovered": 1}}}
    status = gate._status({"row": {"id": "d", "expected_doc_class": "contract"}, "item": {"pred": pred}}, Bars())
    assert status["judge_reasks"] == {"correctness": {"asked": 1, "recovered": 1, "parked": 0}}


@pytest.mark.parametrize("asked", [-1, 1.5, True])
def test_a_negative_fractional_or_boolean_re_ask_count_is_skipped(asked):
    """``int()`` would accept these and understate or flip the totals."""
    pred = {"stage": "review", "judge_reasks": {"completeness": {"asked": asked},
                                                "correctness": {"asked": 2.0, "recovered": 2}}}
    status = gate._status({"row": {"id": "d", "expected_doc_class": "contract"}, "item": {"pred": pred}}, Bars())
    assert status["judge_reasks"] == {"correctness": {"asked": 2, "recovered": 2, "parked": 0}}


@pytest.mark.parametrize("pred", ["boom", ["a"], 3])
def test_an_ok_row_with_a_malformed_pred_is_crashed_not_archived(pred):
    """A corrupted prediction must not count as an archive (a silent wrong outcome)."""
    status = gate._status({"row": {"id": "d", "expected_doc_class": "contract"},
                           "item": {"ok": True, "pred": pred}}, Bars())
    assert status["outcome"] == "crashed" and status["stage"] == "crashed"


def test_errored_never_goes_negative_on_inconsistent_counts():
    status = {"id": "d", "judge_reasks": {"completeness": {"asked": 1, "recovered": 1, "parked": 1}}}
    block = gate._judge_reask_block([status])
    assert block["errored"] == 0 and block["by_judge"]["completeness"]["errored"] == 0
