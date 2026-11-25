"""Scoring hotfixes (SHF-*): each defect reproduced on the raw Dojo-pin path, then fixed and dual reported.

Every defect test asserts two things: the raw value (``raw_dojo``, every fix off: what the vendored
scorer and the unpatched sandbox code produce) shows the defect, and the hotfixed headline does not.
Statistics are checked against independent references (scipy, or brute-force enumeration on small n).
Network-free; no LLM calls.
"""
from __future__ import annotations

import itertools
import json
import math
import threading

import pytest

from mailroom_sandbox import experiment_stats as st
from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval.scoring import score_classification, score_extraction_row, score_subclass

ABSENT = "schema_documented_absence"


def _presence(**codes):
    return json.dumps(codes)


# --- the layer ---------------------------------------------------------------------------------

def test_every_fix_is_current_and_recorded():
    status = sh.status(refresh=True)
    assert status and all(s == "current" for s in status.values()), status
    ident = sh.describe()
    assert ident["module_sha256"] == sh.module_sha256()
    assert [f["id"] for f in ident["fixes"]] == [f.id for f in sh.HOTFIXES]
    for fix in sh.HOTFIXES:
        assert fix.upstream and fix.summary and fix.targets
        for target, sha in fix.targets:
            assert sh.target_sha(target) == sha, (fix.id, target)


def test_a_changed_target_is_stale_not_applied_and_fails_preflight(monkeypatch):
    fix = sh.HOTFIXES[1]  # SHF-002
    bogus = sh.ScoringHotfix(fix.id, fix.layer, ((fix.targets[0][0], "0" * 64),), fix.upstream, fix.summary)
    monkeypatch.setattr(sh, "HOTFIXES", tuple(bogus if f.id == fix.id else f for f in sh.HOTFIXES))
    monkeypatch.setattr(sh, "_STATUS", {})
    assert sh.status()[fix.id] == "stale"
    with sh.hotfixed() as on:
        assert fix.id not in on
        from llm_dojo_scoring.scoring import field_scoring as fs

        assert fs.score_name_field("Acme Holdings and Beta", "Acme") == 1.0  # the raw behaviour
    from mailroom_sandbox.job.preflight import _scoring_hotfix_check

    check = _scoring_hotfix_check()
    assert check["ok"] is False and fix.id in check["detail"]
    monkeypatch.setattr(sh, "_STATUS", {})


def test_an_unresolvable_target_is_not_applied_and_fails_preflight(monkeypatch):
    fix = sh.HOTFIXES[1]  # SHF-002
    missing = sh.ScoringHotfix(fix.id, fix.layer, (("no_such_module_xyz:nothing", "0" * 64),),
                               fix.upstream, fix.summary)
    monkeypatch.setattr(sh, "HOTFIXES", tuple(missing if f.id == fix.id else f for f in sh.HOTFIXES))
    monkeypatch.setattr(sh, "_STATUS", {})
    assert sh.status()[fix.id] == "unavailable"
    assert fix.id not in sh.current_ids()
    from mailroom_sandbox.job.preflight import _scoring_hotfix_check

    check = _scoring_hotfix_check()
    assert check["ok"] is False and f"{fix.id} unavailable" in check["detail"]
    monkeypatch.setattr(sh, "_STATUS", {})


def test_a_package_file_target_resolves_in_the_modal_worker_layout(monkeypatch, tmp_path):
    # The job image ships the package via add_local_python_source: /root/mailroom_sandbox/...,
    # no src/ around it, and SANDBOX_ROOT holds only the bundled data files.
    import hashlib

    package = tmp_path / "root" / "mailroom_sandbox"
    (package / "eval").mkdir(parents=True)
    target = package / "eval" / "reviewed_table.py"
    target.write_text("TABLE = {}\n", encoding="utf-8")
    sandbox_root = tmp_path / "sandbox_root"
    sandbox_root.mkdir()
    monkeypatch.setattr(sh, "__file__", str(package / "scoring_hotfixes.py"))
    monkeypatch.setenv("SANDBOX_ROOT", str(sandbox_root))
    rel = "src/mailroom_sandbox/eval/reviewed_table.py"
    fix = sh.ScoringHotfix("SHF-999", "sandbox", ((f"file:{rel}", hashlib.sha256(target.read_bytes()).hexdigest()),),
                           "sandbox", "a package file target")
    assert sh.data_path(rel) == target
    assert sh.status([fix], refresh=True) == {"SHF-999": "current"}
    assert sh.data_path("src/mailroom_sandbox/eval/no_such_file.py") is None
    monkeypatch.setattr(sh, "_STATUS", {})


def test_preflight_check_and_lock_identity():
    from mailroom_sandbox.job.preflight import _scoring_hotfix_check, _scoring_hotfix_identity

    assert _scoring_hotfix_check()["ok"] is True
    assert _scoring_hotfix_identity() == sh.describe()


def test_fixes_are_off_outside_a_hotfixed_block_and_per_thread():
    sh.install()
    from llm_dojo_scoring.scoring import field_scoring as fs

    assert fs.score_name_field("Acme Holdings and Beta", "Acme") == 1.0  # Dojo pin, unchanged
    seen = {}
    gate = threading.Barrier(2)

    def worker(mode):
        ctx = sh.hotfixed() if mode == "fixed" else sh.raw()
        with ctx:
            gate.wait()
            seen[mode] = fs.score_name_field("Acme Holdings and Beta", "Acme")

    threads = [threading.Thread(target=worker, args=(m,)) for m in ("fixed", "raw")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"fixed": 0.3333, "raw": 1.0}


def test_dual_row_names_the_fixes_and_the_moved_keys():
    row = score_extraction_row("correspondence", {"sender": "Jane Doe", "recipient": "Bob"},
                               {"sender": "Jane Doe", "recipient": None, "gt_presence": _presence(recipient=ABSENT)})
    # SHF-010 needs truth_overrides and SHF-015 the row's overlay provenance; this call passes neither.
    assert row["scoring_hotfixes"] == sorted(sh.EXTRACTION_FIXES - {"SHF-010", "SHF-015"})
    assert "extraction_precision" in row["scoring_hotfixes_changed"]
    assert row["raw_dojo"]["extraction_precision"] == 1.0
    assert sh.headline_basis()["headline"] == "hotfixed"


# --- SHF-001: hallucination on documented absence ----------------------------------------------

@pytest.mark.parametrize(("doc_type", "field", "value", "truth_field", "truth_value"), [
    ("correspondence", "demand_amount", "$5,000", "sender", "Jane Doe"),
    ("correspondence", "recipient", "Bob", "sender", "Jane Doe"),
    ("contract", "governing_law", "Delaware", "document_name", "Supply Agreement"),
    ("merger_agreement", "governing_law", "Delaware", "document_name", "Agreement and Plan of Merger"),
])
def test_shf001_a_value_on_a_documented_absence_is_a_false_positive(doc_type, field, value, truth_field, truth_value):
    expected = {truth_field: truth_value, field: None, "gt_presence": _presence(**{field: ABSENT})}
    row = score_extraction_row(doc_type, {truth_field: truth_value, field: value}, expected)
    assert row["raw_dojo"]["extraction_precision"] == 1.0  # defect: the hallucination is free
    assert row["extraction_precision"] == 0.5 and row["fp"] == 1
    assert row["n_hallucinated"] == 1 and row["hallucination_rate"] == 1.0
    assert row["hallucinated_fields"] == [field]


def test_shf001_stating_nothing_on_the_absence_is_correct_and_counted():
    expected = {"sender": "Jane Doe", "recipient": None, "gt_presence": _presence(recipient=ABSENT)}
    row = score_extraction_row("correspondence", {"sender": "Jane Doe", "recipient": None}, expected)
    assert row["extraction_f1"] == row["raw_dojo"]["extraction_f1"] == 1.0
    assert row["n_documented_absent"] == 1 and row["n_hallucinated"] == 0 and row["hallucination_rate"] == 0.0


def test_shf001_null_truth_without_a_presence_code_stays_unlabelled():
    """Hub null without a presence code means unlabelled: not scored, not a hallucination."""
    row = score_extraction_row("correspondence", {"sender": "Jane Doe", "recipient": "Bob"},
                               {"sender": "Jane Doe", "recipient": None})
    assert row["extraction_precision"] == 1.0 and row["n_documented_absent"] == 0
    assert row["hallucination_rate"] is None


@pytest.mark.parametrize("doc_type", ["correspondence", "insurance_claim", "contract", "corporate_record"])
@pytest.mark.parametrize(("pred", "truth"), [(None, None), ("", None), ([], [])])
def test_both_empty_is_skipped_consistently(doc_type, pred, truth):
    """Not a defect: both-empty never enters the F1 events, on any class (raw and hotfixed agree)."""
    field = {"correspondence": "keywords", "insurance_claim": "denial_reasons", "contract": "parties",
             "corporate_record": "signatories"}[doc_type]
    row = score_extraction_row(doc_type, {field: pred}, {field: truth})
    assert row.get("tp", 0) == row.get("fn", 0) == row.get("fp", 0) == 0
    assert row["raw_dojo"].get("tp", 0) == 0


def test_corporate_documented_absence_was_already_counted():
    """Not a defect on corporate_record: the Dojo's presence alignment already counts it."""
    expected = {"entity_name": "Acme Inc.", "jurisdiction": "", "gt_presence": _presence(entity_name="populated",
                                                                                         jurisdiction=ABSENT)}
    row = score_extraction_row("corporate_record", {"entity_name": "Acme Inc.", "jurisdiction": "Delaware"},
                               expected, expected_subclass="bylaws")
    assert row["raw_dojo"]["extraction_precision"] == row["extraction_precision"] == 0.5
    assert row["n_hallucinated"] == 1


# --- SHF-002: entity names -----------------------------------------------------------------------

@pytest.mark.parametrize(("pred", "truth", "fixed"), [
    ("John Smith, Jane Doe, Bob Jones and the Acme Legal Team", "John Smith", 0.2),
    ("Bank of America", "Bank of America Merrill Lynch", 0.6),
    ("Acme Widgets Inc.", "Acme Inc.", 0.5),
])
def test_shf002_a_token_subset_or_superset_is_not_an_exact_name(pred, truth, fixed):
    row = score_extraction_row("corporate_record", {"entity_name": pred}, {"entity_name": truth},
                               expected_subclass="bylaws", field_scores=True)
    assert row["raw_dojo"]["field_scores"]["entity_name"] == 1.0  # defect
    assert row["raw_dojo"]["extraction_f1"] == 1.0
    assert row["field_scores"]["entity_name"] == fixed
    assert row["extraction_f1"] == 0.0


@pytest.mark.parametrize("pred", [
    "Inhibikase Therapeutics, Inc.", "INHIBIKASE THERAPEUTICS,INC.", "Inhibikase Therapeutics Inc",
    "Inhibikase Therapeutics Incorporated", "The Inhibikase Therapeutics, Inc.", "inhibikase therapeutics inc.",
])
def test_shf002_keeps_every_format_variant_of_the_same_entity(pred):
    """The entity_name repair's variants (Inc./Inc, comma, case, suffix spelling) still match exactly."""
    row = score_extraction_row("corporate_record", {"entity_name": pred},
                               {"entity_name": "Inhibikase Therapeutics, Inc."}, expected_subclass="bylaws")
    assert row["extraction_f1"] == 1.0


def test_shf002_list_items_keep_initials_and_honorifics():
    sh.install()
    from llm_dojo_scoring.scoring import field_scoring as fs

    with sh.hotfixed():
        assert fs.score_name_field("John A. Smith", "John Smith") == 1.0
        assert fs.score_name_field("Dr. Jane Doe", "Jane Doe") == 1.0
        assert fs.score_name_field("Jane Doe", "Bob Jones") < 1.0


# --- SHF-003 / SHF-004: money and identifiers ----------------------------------------------------

def test_shf003_different_currencies_do_not_match():
    row = score_extraction_row("contract", {"contract_value": "EUR 1,000"}, {"contract_value": "$1,000.00"})
    assert row["raw_dojo"]["extraction_f1"] == 1.0  # defect
    assert row["extraction_f1"] == 0.0
    same = score_extraction_row("contract", {"contract_value": "1000 USD"}, {"contract_value": "$1,000.00"})
    assert same["extraction_f1"] == 1.0  # same currency, or one side unstated, still matches
    bare = score_extraction_row("contract", {"contract_value": "1000"}, {"contract_value": "$1,000.00"})
    assert bare["extraction_f1"] == 1.0
    assert sh.currencies("US$400,000.00") == {"USD"} and sh.currencies("C$5") == {"CAD"}


def test_shf004_identifiers_ignore_punctuation_and_spacing():
    row = score_extraction_row("insurance_claim", {"claim_number": "CLM12345"}, {"claim_number": "CLM-12345"})
    assert row["raw_dojo"]["extraction_f1"] == 0.0  # defect: CLM 12345 matched, CLM12345 did not
    assert row["extraction_f1"] == 1.0
    other = score_extraction_row("insurance_claim", {"claim_number": "CLM12346"}, {"claim_number": "CLM-12345"})
    assert other["extraction_f1"] == 0.0


# --- SHF-005 / SHF-006: errored and truthless rows ------------------------------------------------

def test_shf005_an_errored_row_scores_zero_not_dropped():
    from mailroom_sandbox.eval.runners import _isolated_headline

    rows = [{"score": {"match": 1.0}}, {"score": {"match": 1.0}}, {"score": {}, "error": "TimeoutError: x"}]
    head = _isolated_headline(rows)
    assert head["raw_dojo"]["exact_match"] == 1.0  # defect: the timeout left the denominator
    assert head["exact_match"] == pytest.approx(2 / 3) and head["n_scored"] == 3
    assert "SHF-005" in head["scoring_hotfixes"]


def test_shf005_per_item_runner_scores_a_failed_row_wrong():
    from mailroom_sandbox.job.runner import _scored_pairs

    scores = _scored_pairs("sorter", ["contract", "contract", "correspondence"],
                           ["contract", "", "correspondence"], {0: True, 1: False, 2: True}, 3)
    assert scores["raw_dojo"]["accuracy"] == 1.0  # defect
    assert scores["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert scores["n_errored_scored_wrong"] == 1 and scores["scoring_hotfixes"] == ["SHF-005"]


def test_shf006_a_row_without_truth_is_not_averaged_as_zero():
    from mailroom_sandbox.eval.runners import _isolated_headline

    rows = [{"score": {"overall_extraction_score": 0.8}}, {"score": {"overall_extraction_score": None}}]
    head = _isolated_headline(rows)
    assert head["raw_dojo"]["exact_match"] == 0.4  # defect: the unlabelled row counted 0
    assert head["exact_match"] == 0.8 and head["n_no_truth"] == 1


def test_the_raw_headline_reads_each_rows_raw_value():
    from mailroom_sandbox.eval.runners import _isolated_headline

    # SHF-007 case folding turned a raw 0.0 into 1.0 on the row; the raw headline keeps the 0.0.
    rows = [{"score": {"match": 1.0, "raw_dojo": {"match": 0.0}}}, {"score": {"match": 1.0}}]
    head = _isolated_headline(rows)
    assert head["raw_dojo"]["exact_match"] == 0.5
    assert head["exact_match"] == 1.0


def test_raw_rows_keep_an_absent_count_absent():
    rows = sh.raw_rows([{"match": 1.0, "n_documented_absent": 2, "n_hallucinated": 1,
                         "raw_dojo": {"n_documented_absent": None, "n_hallucinated": None}}])
    assert "n_documented_absent" not in rows[0] and "n_hallucinated" not in rows[0]


# --- SHF-007: class labels, empty truth and abstention -------------------------------------------

def test_shf007_class_match_folds_case_and_whitespace():
    from mailroom_sandbox.eval.agents import _score_class

    out = _score_class({"expected_doc_class": "contract"}, {"doc_type": " Contract"})
    assert out["raw_dojo"]["match"] == 0.0 and out["match"] == 1.0


def test_shf007_no_truth_is_unscored_not_a_match():
    from mailroom_sandbox.eval.agents import _score_class

    out = _score_class({"id": "x"}, {"doc_type": None})
    assert out["raw_dojo"]["match"] == 1.0  # defect: empty truth == empty answer
    assert out["match"] is None and out["outcome"] == "unscored"


@pytest.mark.parametrize("pred", [{"doc_type": "contract", "route_to_human": True, "abstained": True},
                                  {"doc_type": None}, {"doc_type": "contract", "abstained": True}])
def test_shf007_an_abstention_is_its_own_outcome_never_correct(pred):
    from mailroom_sandbox.eval.agents import _score_class

    out = _score_class({"expected_doc_class": "contract"}, pred)
    assert out["match"] == 0.0 and out["abstain"] is True and out["outcome"] == "abstain"
    assert out["routed_to_review"] is True


# --- SHF-008: judge / arbiter / boss verdicts -----------------------------------------------------

def test_shf008_verdict_without_truth_is_unscored_and_a_parse_failure_is_wrong():
    from mailroom_sandbox.eval.agents import _score_verdict

    out = _score_verdict({}, {"decision": "approved"}, "decision", "expected_decision")
    assert out["raw_dojo"]["match"] == 1.0 and out["match"] is None  # defect: any output was 1.0
    failed = {"completeness": 0.0, "completeness_label": "incomplete", "reasoning": "judge output failed to parse"}
    out = _score_verdict({"expected_verdict": "incomplete"}, failed, "completeness_label", "expected_verdict")
    assert out["raw_dojo"]["match"] == 1.0  # defect: the parse failure matched "incomplete"
    assert out["match"] == 0.0 and out["parse_error"] is True
    ok = _score_verdict({"expected_verdict": "complete"}, {"completeness_label": "Complete"},
                        "completeness_label", "expected_verdict")
    assert ok["match"] == ok["raw_dojo"]["match"] == 1.0


# --- SHF-009: question set 4.0.0 contract ---------------------------------------------------------

def _v4_answers(*, top=("merger_agreement", 0.9), second=("contract", 0.05), unknown=0.0,
                form="complete_instrument", sub_choice="cash", not_this=0.05):
    probs = {top[0]: top[1], second[0]: second[1], "unknown": unknown}
    return {
        "doc_type": {"choice": top[0], "probabilities": probs},
        "document_form": {"choice": form},
        f"subclass__{top[0]}": {"choice": sub_choice,
                               "probabilities": {sub_choice: 1 - not_this, "not_this_class": not_this}},
    }


def _decide(monkeypatch, answers, handoff=None, text="Agreement and Plan of Merger ..."):
    from mailroom_sandbox import decision_backends as db

    qset = db.load_question_set("reviewer_decisions_v4.0.0")
    monkeypatch.setattr(db, "_post_decision", lambda body, **kw: {"answers": answers, "model": body["model"],
                                                                  "usage": {"input_tokens": 10}})
    monkeypatch.setattr(db, "_record_served", lambda *a, **k: None)
    monkeypatch.setattr(db, "_record_usage", lambda *a, **k: None)
    return db.decide(text, model="openai/gpt-6-luna-decisions", questions=db.decision_questions(qset),
                     qset=qset, handoff=handoff)


def test_shf009_v4_asks_document_form_and_lets_the_subclass_abstain():
    from mailroom_sandbox import decision_backends as db

    questions = db.decision_questions(db.load_question_set("reviewer_decisions_v4.0.0"))
    assert "document_form" in questions
    assert "undetermined" in questions["subclass__contract"]["criteria"]
    v3 = db.decision_questions(db.load_question_set("reviewer_decisions_v3.1.0"))
    assert "document_form" not in v3 and "undetermined" not in v3["subclass__contract"]["criteria"]


@pytest.mark.parametrize(("answers", "reason"), [
    (_v4_answers(top=("merger_agreement", 0.45), second=("contract", 0.40)), "margin"),
    (_v4_answers(form="fragment_or_excerpt"), "document_form:fragment_or_excerpt"),
    (_v4_answers(not_this=0.7, sub_choice="cash"), "subclass_not_this_class"),
    (_v4_answers(top=("contract", 0.5), second=("merger_agreement", 0.1), unknown=0.4), "unknown_max"),
    (_v4_answers(sub_choice="undetermined"), "subclass_gate:undetermined"),
])
def test_shf009_each_v4_rule_parks_the_document(monkeypatch, answers, reason):
    out = _decide(monkeypatch, answers)
    assert out["forced_choice"]["route_to_human"] is False  # defect: scored as a forced choice
    assert out["abstained"] is True and reason in out["abstain_reasons"]
    assert out["route_to_human"] is True and out["confidence"] == 0.0


def test_shf009_keep_sorter_gate_passes_the_sorter_subclass(monkeypatch):
    answers = _v4_answers(top=("contract", 0.9), second=("merger_agreement", 0.05), sub_choice="undetermined")
    out = _decide(monkeypatch, answers, handoff={"sorter_doc_type": "contract", "sorter_doc_subclass": "license"})
    assert out["abstained"] is False and out["doc_subclass"] == "license" and out["subclass_source"] == "sorter"
    assert out["subclass_confidence"] is None  # the reviewer's probability was for "undetermined"
    assert out["forced_choice"]["doc_subclass"] == "undetermined"


def test_shf009_keep_sorter_never_crosses_classes(monkeypatch):
    answers = _v4_answers(top=("contract", 0.9), second=("merger_agreement", 0.05), sub_choice="undetermined")
    out = _decide(monkeypatch, answers, handoff={"sorter_doc_type": "merger_agreement", "sorter_doc_subclass": "cash"})
    assert out["doc_subclass"] is None and out["subclass_source"] == "unresolved"
    assert out["abstained"] and "subclass_gate:undetermined" in out["abstain_reasons"]


def test_shf009_keep_sorter_without_handoff_parks(monkeypatch):
    answers = _v4_answers(top=("contract", 0.9), second=("merger_agreement", 0.05), sub_choice="undetermined")
    out = _decide(monkeypatch, answers, handoff=None)
    assert out["doc_subclass"] is None and out["subclass_source"] == "unresolved"
    assert out["abstained"] and out["route_to_human"] and out["confidence"] == 0.0
    assert "subclass_gate:undetermined" in out["abstain_reasons"]


def test_shf012_raw_subclass_macro_f1_counts_the_predicted_label():
    out = score_subclass(["contract", "contract"], ["license", "lease"], ["contract", "contract"], ["lease", "lease"])
    # truth [license, lease], prediction [lease, lease]: lease F1 = 2/3, license F1 = 0.
    assert out["subclass_raw_dojo"]["subclass_f1_macro"] == pytest.approx(1 / 3, abs=1e-6)


def test_a_live_override_of_a_mock_oracle_lock_is_refused(monkeypatch):
    from mailroom_sandbox.job import runner

    class Store:
        def read_lock(self):
            return {"task": "pipeline", "job": {"mock": True, "blind_routing": False}}

    monkeypatch.setattr(runner, "_lock_mock", lambda store, default: True)
    with pytest.raises(ValueError, match="ground truth"):
        runner._refuse_mock_override(Store(), False)
    runner._refuse_mock_override(Store(), None)  # the mock oracle run itself stays allowed


def test_a_dropped_lane_field_leaves_presence_and_overrides():
    from mailroom_sandbox.job.pair_report import without_fields

    row = {"expected_fields": {"sender": "A", "recipient": "", "gt_presence": json.dumps(
               {"recipient": ABSENT, "sender": "present"})},
           "truth_overrides": {"SHF-010": {"recipient": {"interim": "B"}, "sender": {"interim": "C"}}}}
    out = without_fields(row, ["recipient"])
    assert "recipient" not in out["expected_fields"]
    assert json.loads(out["expected_fields"]["gt_presence"]) == {"sender": "present"}
    assert list(out["truth_overrides"]["SHF-010"]) == ["sender"]


def test_shf009_a_clear_answer_is_unchanged_and_a_cut_is_noted(monkeypatch):
    from mailroom_sandbox import decision_backends as db

    out = _decide(monkeypatch, _v4_answers())
    assert out["abstained"] is False and out["route_to_human"] is False
    assert out["confidence"] == out["forced_choice"]["confidence"] == 0.9
    qset = db.load_question_set("reviewer_decisions_v4.0.0")
    monkeypatch.setattr(db, "_post_decision", lambda body, **kw: {"answers": _v4_answers(), "model": body["model"]})
    cut = db.decide("x" * 50, model="openai/gpt-6-luna-decisions", questions=db.decision_questions(qset),
                    qset=qset, max_input_chars=10)
    assert cut["truncated"] is True and "50-character" in cut["truncation_notice"]


def test_shf009_an_abstention_scores_as_review_never_correct(monkeypatch):
    from mailroom_sandbox.eval.agents import _score_class

    out = _decide(monkeypatch, _v4_answers(form="unreadable"))
    scored = _score_class({"expected_doc_class": "merger_agreement"}, out)
    assert scored["raw_dojo"]["match"] == 1.0  # the forced choice happened to be right
    assert scored["match"] == 0.0 and scored["abstain"] is True and scored["routed_to_review"] is True


# --- SHF-010: reviewed gold over interim gap fills ------------------------------------------------

def _overlay_row(basis):
    from mailroom_sandbox import interim_labels as il

    text = "From: Joe Parks\nTo: Frank Hayden\n..."
    row = {"id": "DOC-1", "doc_text": text, "expected_doc_class": "correspondence",
           "expected_fields": json.dumps({"sender": "Frank Hayden", "gt_presence": json.dumps({"sender": "populated"})}),
           "interim_labels": {"fields": ["sender"], "overlay_sha256": "x"}}
    interim = {"sender": {"status": "gap_fill", "basis": basis, "value": "Frank Hayden", "use_as_truth": True}}
    rec = {"doc_id": "DOC-1", "doc_sha256": il.doc_sha(text),
           "labels": {"sender": {"basis": "near_gold:check_agreed", "value": "Joe Parks"}}}
    return row, interim, rec


def test_shf010_near_gold_supersedes_a_gate_gap_fill(monkeypatch):
    from mailroom_sandbox import gold_labels as gl

    row, interim, rec = _overlay_row("gate_accepted_grounded")
    monkeypatch.setitem(gl._INTERIM_CACHE, "overlay", {"DOC-1": {"labels": interim}})
    monkeypatch.setitem(gl._INTERIM_CACHE, "key", gl._interim_key())
    monkeypatch.setitem(gl._INTERIM_CACHE, "sha", "x")  # the overlay the row was prepared with
    out = gl.apply_near_gold(row, {"DOC-1": rec}, overlay_sha="g")
    assert json.loads(out["expected_fields"])["sender"] == "Joe Parks"
    assert out["truth_overrides"] == {"SHF-010": {"sender": {"interim": "Frank Hayden", "interim_presence": "populated",
                                                             "near_gold": "Joe Parks"}}}
    exp = json.loads(out["expected_fields"])
    scored = score_extraction_row("correspondence", {"sender": "Joe Parks"}, exp,
                                  truth_overrides=out["truth_overrides"])
    assert scored["raw_dojo"]["extraction_f1"] == 0.0  # scored against the interim value
    assert scored["extraction_f1"] == 1.0 and "SHF-010" in scored["scoring_hotfixes"]


def test_shf010_keeps_an_original_header_fill(monkeypatch):
    from mailroom_sandbox import gold_labels as gl

    row, interim, rec = _overlay_row("original_header")
    monkeypatch.setitem(gl._INTERIM_CACHE, "overlay", {"DOC-1": {"labels": interim}})
    monkeypatch.setitem(gl._INTERIM_CACHE, "key", gl._interim_key())
    monkeypatch.setitem(gl._INTERIM_CACHE, "sha", "x")  # the overlay the row was prepared with
    out = gl.apply_near_gold(row, {"DOC-1": rec}, overlay_sha="g")
    assert "truth_overrides" not in out
    assert json.loads(out["expected_fields"])["sender"] == "Frank Hayden"


def test_shf010_precedence_reads_the_overlay_the_row_was_prepared_with(monkeypatch):
    """The overlay changes between preparation and precedence: the prepared snapshot decides."""
    from mailroom_sandbox import gold_labels as gl

    row, prepared, rec = _overlay_row("original_header")
    _, edited, _ = _overlay_row("gate_accepted_grounded")
    monkeypatch.setitem(gl._INTERIM_CACHE, "overlay", {"DOC-1": {"labels": edited}})
    monkeypatch.setitem(gl._INTERIM_CACHE, "key", gl._interim_key())
    monkeypatch.setitem(gl._INTERIM_CACHE, "sha", "edited")
    out = gl.apply_near_gold(row, {"DOC-1": rec}, overlay_sha="g", interim={"DOC-1": {"labels": prepared}})
    assert "truth_overrides" not in out and json.loads(out["expected_fields"])["sender"] == "Frank Hayden"
    # Without the snapshot, a current overlay that is not the row's (fingerprint "edited" != "x")
    # supersedes nothing: the prepared interim value stands.
    out = gl.apply_near_gold(row, {"DOC-1": rec}, overlay_sha="g")
    assert "truth_overrides" not in out and json.loads(out["expected_fields"])["sender"] == "Frank Hayden"


# --- SHF-011: paired A/B report -------------------------------------------------------------------

def test_shf011_a_failed_document_scores_zero_in_the_paired_report(tmp_path):
    from mailroom_sandbox.job import pair_report

    def arm(name, items):
        run = tmp_path / name
        run.mkdir()
        (run / "dataset.jsonl").write_text("".join(json.dumps(
            {"id": d, "expected_doc_class": "correspondence",
             "expected_fields": json.dumps({"sender": "Jane Doe"})}) + "\n" for d, _ in items))
        (run / "items.jsonl").write_text("".join(json.dumps({"item_id": d, **it}) + "\n" for d, it in items))
        return run

    good = {"ok": True, "pred": {"stage": "archived", "extracted_data": {"sender": "Jane Doe"}}}
    crashed = {"ok": False, "error": "TimeoutError", "pred": {"stage": "failed", "extracted_data": {"sender": "Jane Doe"}}}
    c = arm("c", [("D0", good), ("D1", good)])
    t = arm("t", [("D0", crashed), ("D1", good)])
    lane = pair_report.paired_report(c, t)["classes"]["correspondence"]
    assert lane["all_fields"]["raw_dojo"]["diff"] == 0.0  # defect: the crash kept its credit
    assert lane["all_fields"]["diff"] == -0.5 and lane["failed_treatment"] == 1


# --- statistics, against independent references --------------------------------------------------

@pytest.mark.parametrize(("b", "c"), [(0, 0), (0, 5), (3, 9), (10, 10), (40, 61), (600, 700), (1024, 1100), (2000, 2100)])
def test_mcnemar_exact_and_mid_p_match_scipy(b, c):
    scipy_stats = pytest.importorskip("scipy.stats")
    result = st.mcnemar([True] * b + [False] * c, [False] * b + [True] * c)
    n = b + c
    exact = scipy_stats.binomtest(c, n, 0.5).pvalue if n else 1.0
    assert result.p_value == pytest.approx(exact, rel=1e-9, abs=1e-300)
    k = min(b, c)
    mid = min(1.0, 2 * (scipy_stats.binom.cdf(k, n, 0.5) - 0.5 * scipy_stats.binom.pmf(k, n, 0.5))) if n else 1.0
    assert result.p_mid == pytest.approx(mid, rel=1e-9, abs=1e-300)
    assert result.p_mid <= result.p_value


def test_mcnemar_pairs_by_id_not_position():
    base = {"a": True, "b": False, "c": True, "d": None}
    cand = {"c": True, "b": True, "a": False}
    aligned = st.align_by_id(base, cand)
    assert aligned.ids == ("a", "b", "c") and aligned.neither == ("d",) and aligned.only_baseline == ()
    assert aligned.report()["neither"] == ["d"] and not aligned.complete
    assert st.align_by_id({"d": None}, {"d": None}).neither == ("d",)  # errored on both: reported
    m = st.mcnemar(aligned.baseline, aligned.candidate)
    assert (m.b, m.c) == (1, 1)
    kept = st.align_by_id({"x": None, "y": True}, {"x": True, "y": True}, errored_as=False)
    assert kept.ids == ("x", "y") and kept.baseline == (False, True)


def _exact_sign_flip_p(diffs):
    observed = abs(sum(diffs))
    hits = total = 0
    for signs in itertools.product((1, -1), repeat=len(diffs)):
        total += 1
        hits += abs(sum(s * d for s, d in zip(signs, diffs))) >= observed - 1e-12
    return hits / total


def test_sign_flip_permutation_matches_exact_enumeration_and_uses_plus_one():
    base = [0.2, 0.5, 0.4, 0.9, 0.1, 0.3, 0.6, 0.7]
    cand = [0.6, 0.5, 0.9, 0.8, 0.4, 0.7, 0.9, 0.9]
    diffs = [c - b for b, c in zip(base, cand)]
    exact = _exact_sign_flip_p([d for d in diffs if d])
    mean, p = st.paired_permutation(base, cand, n_perm=20_000, seed=7)
    assert mean == pytest.approx(sum(diffs) / len(diffs))
    assert p == pytest.approx(exact, abs=0.01)
    _, p_small = st.paired_permutation(base, cand, n_perm=9, seed=1)
    assert p_small * 10 == pytest.approx(round(p_small * 10))  # (k + 1) / (n + 1) with n = 9
    assert p_small >= 1 / 10  # plus-one: never zero, even with no draw at the observed statistic


def test_paired_macro_f1_matches_exact_swap_enumeration():
    truth = ["a", "a", "b", "b", "c", "c", "a", "b"]
    base = ["a", "b", "b", "a", "c", "a", "a", "c"]
    cand = ["a", "a", "b", "b", "c", "c", "b", "b"]
    labels = sorted(set(truth))
    observed = st.macro_f1(truth, cand, labels) - st.macro_f1(truth, base, labels)
    differ = [i for i in range(len(truth)) if base[i] != cand[i]]
    hits = total = 0
    for mask in itertools.product((False, True), repeat=len(differ)):
        a, b = list(base), list(cand)
        for i, swap in zip(differ, mask):
            if swap:
                a[i], b[i] = b[i], a[i]
        total += 1
        hits += abs(st.macro_f1(truth, b, labels) - st.macro_f1(truth, a, labels)) >= abs(observed) - 1e-12
    delta, p = st.paired_macro_f1(truth, base, cand, n_perm=20_000, seed=3)
    assert delta == pytest.approx(observed)
    assert p == pytest.approx(hits / total, abs=0.01)


def test_holm_matches_brute_force_step_down_and_is_monotone():
    ps = {"h1": 0.01, "h2": 0.04, "h3": 0.03, "h4": 0.005, "h5": 0.5}
    adj = st.holm(ps)
    order = sorted(ps, key=ps.get)
    m = len(ps)
    ref, running = {}, 0.0
    for rank, key in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[key]))
        ref[key] = running
    assert adj == pytest.approx(ref)
    assert [adj[k] for k in order] == sorted(adj[k] for k in order)
    assert adj == pytest.approx({"h1": 0.04, "h2": 0.09, "h3": 0.09, "h4": 0.025, "h5": 0.5})


def test_clopper_pearson_and_gate_sizes_match_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    for k, n in [(0, 149), (0, 34), (2, 105), (5, 376)]:
        assert st.clopper_pearson_upper(k, n, confidence=0.95) == pytest.approx(
            scipy_stats.beta.ppf(0.95, k + 1, n - k), rel=1e-6)
    assert st.zero_failure_n(0.02) == 149
    plan = st.class_gate_plan({"contract": 105, "merger_agreement": 34, "insurance_claim": 376})
    assert plan["contract"].certifiable is False and plan["insurance_claim"].certifiable is True
    assert plan["merger_agreement"].best_bound == pytest.approx(0.0843, abs=1e-4)


def test_keep_at_look_no_longer_misreads_an_off_size_final_look():
    with pytest.raises(ValueError, match="look size"):
        st.keep_at_look(897, 2.1, 0.02, 0.03)  # was "continue" (read as look 2): never decided
    assert st.keep_at_look(897, 2.1, 0.02, 0.03, look=3) == "keep"
    assert st.keep_at_look(900, 2.1, 0.02, 0.03) == "keep"


def test_null_floors_and_cost_weighted_error():
    assert st.brier_null_floor([True, True, True, False]) == pytest.approx(0.1875)
    assert st.ece_null_floor([0.9] * 50, n_sim=200, seed=0) == st.ece_null_floor([0.9] * 50, n_sim=200, seed=0)
    confusion = {("contract", "contract"): 8, ("contract", "merger_agreement"): 1, ("merger_agreement", "contract"): 1}
    costs = {("contract", "merger_agreement"): 5.0}
    assert st.cost_weighted_error(confusion, costs) == pytest.approx((5.0 + 1.0) / 10)


def test_calibration_inputs_report_what_the_dojo_drops_silently():
    pairs = [(0.9, True), (95, True), (float("nan"), False), ("0.9", True), (None, False), (True, True), (0.2, False)]
    clean, report = st.calibration_inputs(pairs)
    assert clean == [(0.9, True), (0.2, False)]
    assert report == {"n": 2, "n_dropped": 5, "dropped": {"out_of_range": 1, "not_finite": 1, "not_a_number": 2,
                                                          "missing": 1}}
    assert st.brier_score(pairs) == st.brier_score(clean)  # the Dojo drops them without saying so


# --- class / subclass ------------------------------------------------------------------------------

def test_macro_f1_zero_support_is_consistent_with_the_dojo():
    """Not a defect: predicted-only classes are excluded (truth classes only), in both scorers."""
    for truth, pred in [(["a", "a", "b"], ["a", "c", "b"]), (["a", "a"], ["a", "b"])]:
        assert score_classification(truth, pred)["f1_macro"] == pytest.approx(st.macro_f1(truth, pred), abs=1e-3)


def test_subclass_scoring_counts_a_wrong_class_as_a_wrong_subclass():
    out = score_subclass(["correspondence", "contract", "corporate_record", "merger_agreement"],
                         ["other", "license", "bylaws", ""],
                         ["contract", "contract", "corporate_record", "merger_agreement"],
                         ["other", "license", "charter_amendment", "cash"])
    # correspondence/other vs contract/other is wrong (the Dojo's pipeline_subclass_match calls it right)
    assert out["subclass_accuracy"] == pytest.approx(1 / 3)
    assert out["subclass_n"] == 3 and out["subclass_n_no_truth"] == 1
    assert out["subclass_accuracy_given_class"] == 0.5 and out["subclass_n_given_class"] == 2
    truth = ["correspondence/other", "contract/license", "corporate_record/bylaws"]
    pred = ["contract/other", "contract/license", "corporate_record/charter_amendment"]
    assert out["subclass_f1_macro"] == pytest.approx(st.macro_f1(truth, pred))


# --- noise floor -----------------------------------------------------------------------------------

def test_noise_floor_and_keep_rule():
    runs = {"r1": {"a": True, "b": True, "c": False, "d": True},
            "r2": {"a": True, "b": False, "c": False, "d": True},
            "r3": {"a": True, "b": True, "c": True, "d": None}}
    floor = st.noise_floor(runs)
    assert floor.n_docs == 3 and floor.missing == {"r3": ["d"]}
    assert floor.metric_by_run == pytest.approx((2 / 3, 1 / 3, 1.0), abs=1e-5)
    assert floor.floor == pytest.approx(2 / 3, abs=1e-5) and floor.flip_rate == pytest.approx(2 / 3, abs=1e-5)
    assert floor.sd == pytest.approx(math.sqrt(((1 / 3 - 2 / 3) ** 2 + (1 - 2 / 3) ** 2) / 2), abs=1e-5)
    assert st.keep_with_floor("keep", 0.05, floor, look=3)["decision"] == "drop"
    assert st.keep_with_floor("keep", 0.05, 0.02, look=2)["decision"] == "keep"
    assert st.keep_with_floor("keep", 0.01, 0.02, look=2)["decision"] == "continue"


def test_a_gain_equal_to_the_repeat_noise_is_dropped():
    # 450 and 454 of 900 correct: the floor is exactly 4/900, and a 4/900 gain is noise.
    runs = {"r1": {i: i < 450 for i in range(900)}, "r2": {i: i < 454 for i in range(900)}}
    floor = st.noise_floor(runs)
    assert floor.floor == pytest.approx(4 / 900, abs=1e-12)
    assert st.keep_with_floor("keep", 4 / 900, floor, look=3)["decision"] == "drop"


# --- pipeline wrappers (HF-002) and cost evidence ---------------------------------------------------

def test_hf002_a_judge_parse_failure_is_a_judge_error():
    pytest.importorskip("agents.judge")
    from mailroom_sandbox import vendor_hotfixes as vh

    assert vh.apply_hotfixes()["HF-002"] == "applied"
    from agents.judge import CompletenessJudge

    judge = CompletenessJudge.__new__(CompletenessJudge)
    judge._call_structured = lambda *a, **k: {"_parse_error": True}
    judge._field_list = lambda doc_type: "-"
    with pytest.raises(vh.JudgeParseError):
        judge.judge_completeness("contract", {"parties": ["A"]}, "text")
    judge._call_structured = lambda *a, **k: {"completeness": 0.4, "completeness_label": "partial", "reasoning": "r"}
    assert judge.judge_completeness("contract", {"parties": ["A"]}, "text")["completeness_label"] == "partial"


def test_isolated_items_keep_the_call_count():
    from mailroom_sandbox.job.runner import _persist_isolated_items

    class Store:
        def __init__(self):
            self.items = []

        def load_items(self):
            return self.items

        def append_item(self, item):
            self.items.append(item)

    store = Store()
    _persist_isolated_items(store, [{"id": "D", "pred": {}, "score": {}, "prompt_tokens": 9, "completion_tokens": 1,
                                     "llm_calls": 4}])
    assert store.items[0]["llm_calls"] == 4


def test_decide_records_document_form_probabilities_without_changing_routing(monkeypatch):
    answers = _v4_answers(form="fragment_or_excerpt")
    answers["document_form"]["probabilities"] = {"complete_instrument": 0.45, "fragment_or_excerpt": 0.5,
                                                 "multiple_documents": 0.05}
    out = _decide(monkeypatch, answers)
    assert out["document_form_probabilities"]["complete_instrument"] == 0.45
    assert out["document_form_human_mass"] == 0.55
    assert out["abstained"] and "document_form:fragment_or_excerpt" in out["abstain_reasons"]  # still parks
    bare = _decide(monkeypatch, _v4_answers())  # no probabilities on the answer: nothing recorded
    assert "document_form_probabilities" not in bare and "document_form_human_mass" not in bare


def test_changed_keys_names_every_moved_headline_including_the_field_f1_mean():
    # An isolated specialist run merges aggregate_extraction raw and hotfixed by hand; a moved
    # extraction_f1_mean must be listed as changed, or consumers miss the score change.
    raw = {"extraction_f1_mean": 0.5556, "extraction_f1_n": 3, "hallucination_rate": float("nan")}
    fixed = {"extraction_f1_mean": 0.3333, "extraction_f1_n": 3, "hallucination_rate": float("nan")}
    assert sh.changed_keys(raw, fixed, fixed) == ["extraction_f1_mean"]


def test_shf007_per_item_runner_folds_labels_and_leaves_no_truth_rows_out():
    from mailroom_sandbox.job.runner import _scored_pairs

    scores = _scored_pairs("sorter", ["correspondence", "Contract", "", "insurance_claim"],
                           ["correspondence", "contract", "contract", "insurance-claim"],
                           {0: True, 1: True, 2: True, 3: True}, 4)
    assert scores["raw_dojo"]["accuracy"] == 0.5  # defect: case, hyphen and a blank truth count wrong
    assert scores["accuracy"] == 1.0 and scores["n"] == 3 and scores["n_no_truth"] == 1
    assert scores["scoring_hotfixes"] == ["SHF-006", "SHF-007"]


def test_shf007_per_item_runner_keeps_a_failed_row_wrong_after_folding():
    from mailroom_sandbox.job.runner import _scored_pairs

    scores = _scored_pairs("sorter", ["Contract", "contract", ""], ["contract", "", ""],
                           {0: True, 1: False, 2: False}, 3)
    assert scores["accuracy"] == 0.5 and scores["n_errored_scored_wrong"] == 1 and scores["n_no_truth"] == 1
    assert scores["scoring_hotfixes"] == ["SHF-005", "SHF-006", "SHF-007"]


def test_per_item_runner_without_a_moved_score_names_no_fix():
    from mailroom_sandbox.job.runner import _scored_pairs

    scores = _scored_pairs("sorter", ["contract"], ["contract"], {0: True}, 1)
    assert scores["scoring_hotfixes"] == [] and "n_no_truth" not in scores
