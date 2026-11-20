"""Question set 4.2.0: the request it sends and the routing rules it adds (docs/decision-model-input-design.md).

Every test is offline: the Decisions transport is replaced and no API call is made.
"""

from __future__ import annotations

import pytest

from mailroom_sandbox import decision_backends as db

DECISIONS = "openai/gpt-6-luna-decisions"
V42 = "reviewer_decisions_v4.2.0"


@pytest.fixture
def v42():
    return db.load_question_set(V42)


def _send(monkeypatch, qset, answers, text="AGREEMENT AND PLAN OF MERGER\nEach share converts into $10.00 in cash.",
          handoff=None, run_id=None):
    sent = {}

    def fake_post(body, *, timeout, attempts):
        sent.update(body)
        return {"model": DECISIONS, "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 0, "cost": 1e-6}}

    monkeypatch.setattr(db, "_post_decision", fake_post)
    monkeypatch.setattr(db, "_record_usage", lambda model, usage, agent=None: None)
    monkeypatch.setattr(db, "_record_served", lambda model, data: None)
    from mailroom_sandbox import provider_pins

    monkeypatch.setattr(provider_pins, "_RUN_CONTEXT", {"run_id": run_id} if run_id else {})
    result = db.decide(text, model=DECISIONS, questions=db.decision_questions(qset), qset=qset, handoff=handoff,
                       max_input_chars=int(qset.get("max_input_chars") or 1000))
    return sent, result


def _merger_answers(**extra):
    answers = {
        "doc_type": {"choice": "merger_agreement", "probabilities": {"merger_agreement": 0.96, "contract": 0.04}},
        "subclass__merger_agreement": {"choice": "all_cash", "probabilities": {"all_cash": 0.9, "other": 0.1}},
        "fit__merger_agreement": {"noul": 0.93},
        "form__fragment": {"noul": 0.04}, "form__bundle": {"noul": 0.02},
        "form__unreadable": {"noul": 0.01}, "form__non_english": {"noul": 0.01},
    }
    answers.update(extra)
    return answers


def test_v42_sends_the_document_as_state_document_with_form_signals(monkeypatch, v42):
    sent, result = _send(monkeypatch, v42, _merger_answers())
    assert isinstance(sent["state"], dict) and sent["state"]["document"].startswith("AGREEMENT AND PLAN OF MERGER")
    signals = sent["state"]["form_signals"]
    assert signals["characters"] == len("AGREEMENT AND PLAN OF MERGER\nEach share converts into $10.00 in cash.")
    assert signals["ends_with_sentence_punctuation"] is True and signals["cut_by_window"] is False
    assert "sorter_handoff" not in sent["state"]                        # a stand-alone sorter never reads the sorter
    assert result["abstained"] is False and result["doc_subclass"] == "all_cash"
    assert result["document_form"] == "complete_instrument"
    # Only the questions this fixture left unanswered (other classes' picks, fits and markers) are recorded.
    assert not {"doc_type", "subclass__merger_agreement", "fit__merger_agreement"} & set(result["refused_questions"])
    assert "fit__contract" in result["refused_questions"]


@pytest.mark.parametrize("stem", ["reviewer_decisions_v4.0.0", "reviewer_decisions_v4.0.1", "reviewer_decisions_v4.0.2",
                                  "reviewer_decisions_v3.1.0", "reviewer_decisions_v2"])
def test_earlier_sets_still_send_what_their_locked_runs_sent(monkeypatch, stem):
    """4.0.x sent bare text (the bug 4.2.0 fixes); a published set's request never changes."""
    qset = db.load_question_set(stem)
    sent, result = _send(monkeypatch, qset, {"doc_type": {"choice": "contract", "probabilities": {"contract": 0.9}}},
                         run_id="r1")
    # 3.x sends {document, sorter_handoff}; 2.0.0 and 4.0.x the bare text.
    assert isinstance(sent["state"], str) or set(sent["state"]) == {"document", "sorter_handoff"}
    assert isinstance(sent["state"], str) or stem.startswith("reviewer_decisions_v3")
    assert "session_id" not in sent and "refused_questions" not in result
    questions = db.decision_questions(qset)
    assert not any(k.startswith((db.FIT_PREFIX, db.FORM_FLAG_PREFIX)) for k in questions)
    assert all(not q["instructions"].startswith("state.document is untrusted") for q in questions.values())


def test_v42_questions_open_with_the_untrusted_notice_and_drop_not_this_class(v42):
    questions = db.decision_questions(v42)
    assert all(q["instructions"].startswith("state.document is untrusted text") for q in questions.values())
    assert {k for k in questions if k.startswith(db.FORM_FLAG_PREFIX)} == {
        "form__fragment", "form__bundle", "form__unreadable", "form__non_english"}
    assert all(questions[k]["type"] == "noul" for k in questions if k.startswith((db.FORM_FLAG_PREFIX, db.FIT_PREFIX)))
    for cls in ("contract", "merger_agreement", "corporate_record", "insurance_claim"):
        assert db.NOT_THIS_CLASS not in questions[f"subclass__{cls}"]["criteria"]
        assert db.SUBCLASS_UNDETERMINED in questions[f"subclass__{cls}"]["criteria"]
        assert cls in questions[f"{db.FIT_PREFIX}{cls}"]["instructions"]
    assert "fit__correspondence" not in questions                       # marker classes have no pick to fit
    assert "document_form" not in questions
    assert "does not count" in questions["marker__correspondence__demand"]["instructions"]


def test_v42_puts_the_run_id_in_session_id(monkeypatch, v42):
    sent, result = _send(monkeypatch, v42, _merger_answers(), run_id="rb1-r13b-x")
    assert sent["session_id"] == "sandbox-rb1-r13b-x" and result["session_id"] == "sandbox-rb1-r13b-x"
    sent, _ = _send(monkeypatch, v42, _merger_answers(), run_id=None)
    assert "session_id" not in sent                                     # outside a run: no invented id


def test_a_cut_off_bundle_raises_both_flags_and_parks(monkeypatch, v42):
    """The pick-one form question could name only one of two defects; the flags carry both."""
    answers = _merger_answers(**{"form__fragment": {"noul": 0.81}, "form__bundle": {"noul": 0.77}})
    _, result = _send(monkeypatch, v42, answers, text="CLAIM HEADER\n<DOCUMENT>\n<TYPE>EX-24\nPOWER OF ATTOR")
    assert result["abstained"] and result["route_to_human"] and result["confidence"] == 0.0
    assert result["document_form_flags"] == ["fragment", "bundle"]
    assert {"document_form:fragment", "document_form:bundle"} <= set(result["abstain_reasons"])
    assert result["document_form_human_mass"] == 0.81
    assert result["forced_choice"]["doc_type"] == "merger_agreement"   # the forced-choice reading is kept


def test_form_signals_measure_the_end_and_wrappers():
    signals = db.form_signals("CLAIM\n<DOCUMENT>\n<TYPE>EX-24\nSource: ACME, 10-K\nPOWER OF ATTOR",
                              original_chars=2_000_000, window_chars=1_000_000)
    assert signals["ends_with_sentence_punctuation"] is False and signals["cut_by_window"] is True
    assert signals["document_tags"] == 1 and signals["type_tags"] == 1 and signals["filing_source_lines"] == 1
    assert signals["ends_with"].endswith("POWER OF ATTOR") and signals["characters"] == 2_000_000


@pytest.mark.parametrize("refused_key, reason", [("doc_type", "refused:doc_type"),
                                                 ("form__bundle", "refused:form__bundle")])
def test_a_refused_doc_type_or_form_flag_is_recorded_and_parks(monkeypatch, v42, refused_key, reason):
    answers = _merger_answers()
    answers[refused_key] = {"refusal": "The provider declined to answer this question."}
    _, result = _send(monkeypatch, v42, answers)
    assert refused_key in result["refused_questions"]
    assert reason in result["abstain_reasons"] and result["route_to_human"]


def test_a_missing_answer_counts_as_refused():
    questions = {"doc_type": {"type": "choice"}, "form__fragment": {"type": "noul"}, "fit__contract": {"type": "noul"}}
    answers = {"doc_type": {"choice": "contract"}, "form__fragment": {"noul": True}}
    assert db.refused_questions(questions, answers) == ["form__fragment", "fit__contract"]


def test_a_low_fit_answer_rejects_the_chosen_class(monkeypatch, v42):
    _, result = _send(monkeypatch, v42, _merger_answers(**{"fit__merger_agreement": {"noul": 0.2}}))
    assert "subclass_fit" in result["abstain_reasons"] and result["subclass_fit_probability"] == 0.2
    assert result["abstained"]


def test_an_unanswered_fit_question_goes_through_the_subclass_gate(monkeypatch, v42):
    answers = _merger_answers()
    del answers["fit__merger_agreement"]
    _, result = _send(monkeypatch, v42, answers)                       # merger_agreement: on_low park
    assert "subclass_gate:fit_unanswered" in result["abstain_reasons"]
    contract = {
        "doc_type": {"choice": "contract", "probabilities": {"contract": 0.95, "merger_agreement": 0.05}},
        "subclass__contract": {"choice": "license", "probabilities": {"license": 0.7}},
        **{k: v for k, v in _merger_answers().items() if k.startswith("form__")},
    }
    handoff = {"sorter_doc_type": "contract", "sorter_doc_subclass": "supply"}
    _, kept = _send(monkeypatch, v42, contract, handoff=handoff)        # contract: keep_sorter
    assert kept["abstained"] is False and kept["doc_subclass"] == "supply" and kept["subclass_source"] == "sorter"
    assert "fit__contract" in kept["refused_questions"]


def test_v42_leaves_the_shf009_contract_fingerprint_alone():
    from mailroom_sandbox import scoring_hotfixes as sh

    assert sh.enabled("SHF-009")


@pytest.mark.parametrize("patch, message", [
    ({"state_shape": "text"}, "state_shape"),
    ({"session_id": "per-document"}, "session_id"),
    ({"document_form_flags": {"flags": {}}}, "document_form_flags"),
    ({"subclass_fit": {"instructions": "Does it fit?"}}, "subclass_fit"),
    ({"abstain": {"subclass_fit_min": 1.5}}, "subclass_fit_min"),
    ({"document_form": {"instructions": "x", "criteria": {"a": "a", "b": "b"}}}, "not both"),
])
def test_misspelt_v42_keys_fail_at_load(monkeypatch, tmp_path, v42, patch, message):
    import yaml

    monkeypatch.setattr(db, "decisions_dir", lambda: tmp_path)
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({**v42, **patch}))
    with pytest.raises(ValueError, match=message):
        db.load_question_set("bad")


#: sha256 of the request body each published set sent before 4.2.0 (4.1.0 from c4e612db;
#: earlier versions from ca1e2935's
#: decide()): a later change to the request builder that alters any of them fails here.
_PUBLISHED_REQUESTS = {
    "reviewer_decisions_v1": "4f710c165b38d95dcda5deef5c4d33b1b11e79963b4796cb1509ca31fa2522c4",
    "reviewer_decisions_v2": "6b1588fc22888b8afe3818b72e1742325e89e8158077f9704c3d514d10cb167f",
    "reviewer_decisions_v3.0.0": "3e3c1597af37e134949a73ac1298523672fa7a83441499869f0abf26d9dc5282",
    "reviewer_decisions_v3.1.0": "6842a3ccfc3d8726c8c5e277d1d67e70841a235ec71226f0b6be8d9db0b38471",
    "reviewer_decisions_v3.2.0": "29b8388040244d8384c3bd399c0fd9858a4d9069d3c9a6ab6ea833f2c70b8518",
    "reviewer_decisions_v4.0.0": "6dbeaece641e151c618f2b0d9bce7cdf727cdf04e55a3e0997b86479a97d5b9a",
    "reviewer_decisions_v4.0.1": "2318f515598520d4e7f897e71fc6649cf05daa7f0907105ef28ba781de810d53",
    "reviewer_decisions_v4.0.2": "32ff39eb9067d81009db6bd54ab0aadad7d5dc5c812138e34b9878deaaa92619",
    "reviewer_decisions_v4.1.0": "7fbea05dc6e2925fafa73a69b777af129fabe898df8e72d43d1d53c09036f83d",
}


@pytest.mark.parametrize("stem", sorted(_PUBLISHED_REQUESTS))
def test_published_sets_send_byte_identical_requests(monkeypatch, stem):
    import hashlib
    import json

    qset = db.load_question_set(stem)
    sent, _ = _send(monkeypatch, qset, {}, run_id="golden-run",
                    text="AGREEMENT AND PLAN OF MERGER\nCard 4111 1111 1111 1111.\nEach share converts into $10.00 in cash.",
                    handoff={"sorter_doc_type": "merger_agreement", "sorter_doc_subclass": "all_cash"})
    assert hashlib.sha256(json.dumps(sent, sort_keys=True).encode()).hexdigest() == _PUBLISHED_REQUESTS[stem]


def test_the_fit_question_leaves_out_the_catch_all(v42):
    questions = db.decision_questions(v42)
    for cls in ("contract", "merger_agreement", "corporate_record", "insurance_claim"):
        listed = questions[f"{db.FIT_PREFIX}{cls}"]["instructions"].split("describe it:", 1)[1].split("?", 1)[0]
        assert ("other" in [name.strip() for name in listed.split(",")]) == (cls in {"merger_agreement", "insurance_claim"}), cls
        assert db.SUBCLASS_UNDETERMINED not in listed


def test_a_marker_class_has_no_fit_rule_and_unknown_parks(monkeypatch, v42):
    corr = {"doc_type": {"choice": "correspondence", "probabilities": {"correspondence": 0.97, "contract": 0.03}},
            **{k: v for k, v in _merger_answers().items() if k.startswith("form__")}}
    _, result = _send(monkeypatch, v42, corr)
    assert "subclass_fit_probability" not in result
    assert result["doc_subclass"] is None and result["subclass_gate"] == "keep_sorter"
    assert result["abstained"] and result["route_to_human"]
    assert any(r.startswith("subclass_gate:") for r in result["abstain_reasons"])
    unknown = {**corr, "doc_type": {"choice": "unknown", "probabilities": {"unknown": 0.8, "contract": 0.2}}}
    _, result = _send(monkeypatch, v42, unknown)
    assert "doc_type:unknown" in result["abstain_reasons"] and result["route_to_human"]


def test_a_refused_pick_with_a_low_fit_parks_on_fit(monkeypatch, v42):
    answers = _merger_answers(**{"subclass__merger_agreement": {"refusal": "declined"},
                                 "fit__merger_agreement": {"noul": 0.0}})
    _, result = _send(monkeypatch, v42, answers)
    assert {"subclass_fit", "subclass_gate:none"} <= set(result["abstain_reasons"])
    assert result["subclass_fit_probability"] == 0.0                   # 0.0 is an answer, not a refusal
    assert "fit__merger_agreement" not in result["refused_questions"]


@pytest.mark.parametrize("patch, message", [
    ({"form_signals": "yes"}, "form_signals"),
    ({"record_refusals": 1}, "record_refusals"),
    ({"untrusted_notice": "  "}, "untrusted_notice"),
    ({"document_form_flags": ["fragment"]}, "document_form_flags"),
    ({"subclass_fit": {"exclude": "other", "instructions": "{cls} {options}"}}, "subclass_fit"),
    ({"subclass_fit": {"exclude": {"typo": ["other"]}, "instructions": "{cls} {options}"}}, "unknown class"),
    ({"subclass_fit": {"exclude": {"contract": ["typo"]}, "instructions": "{cls} {options}"}}, "unknown class"),
])
def test_more_misspelt_v42_keys_fail_at_load(monkeypatch, tmp_path, v42, patch, message):
    import yaml

    monkeypatch.setattr(db, "decisions_dir", lambda: tmp_path)
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump({**v42, **patch}))
    with pytest.raises(ValueError, match=message):
        db.load_question_set("bad")


def test_a_signature_line_is_not_sentence_punctuation():
    assert db.form_signals("Sincerely,\nJane Roe", original_chars=18, window_chars=100)["ends_with_sentence_punctuation"] is False
    assert db.form_signals("<TYPE>EX-24>", original_chars=12, window_chars=100)["ends_with_sentence_punctuation"] is False
    assert db.form_signals('He said "done."', original_chars=15, window_chars=100)["ends_with_sentence_punctuation"] is True


@pytest.mark.parametrize("missing, positive, expected", [
    ("attorney_demand", None, None),
    ("attorney_demand", "letter", None),
    ("meeting_request", "letter", "letter"),
    (None, None, "email"),
])
@pytest.mark.parametrize("policy", ["park", "keep_sorter"])
def test_marker_refusals_gate_only_when_they_can_change_the_subclass(monkeypatch, v42, missing, positive, expected, policy):
    from copy import deepcopy

    qset = deepcopy(v42)
    qset["subclass_gate"]["correspondence"] = {"on_low": policy}
    answers = {"doc_type": {"choice": "correspondence", "probabilities": {"correspondence": 0.98}},
               **{k: v for k, v in _merger_answers().items() if k.startswith("form__")}}
    for key in qset["subclass"]["correspondence"]["markers"]:
        answers[f"marker__correspondence__{key}"] = {"noul": 0.97 if key == positive else 0.01}
    if missing:
        answers[f"marker__correspondence__{missing}"] = {"type": "refusal"}
    _, result = _send(monkeypatch, qset, answers)
    assert result["doc_subclass"] == expected
    assert result["abstained"] == (expected is None)
    if expected is None:
        assert result["subclass_confidence"] is None
        assert result["subclass_gate"] == policy
        handoff = {"sorter_doc_type": "correspondence", "sorter_doc_subclass": "memo"}
        _, kept = _send(monkeypatch, qset, answers, handoff=handoff)
        assert kept["doc_subclass"] == ("memo" if policy == "keep_sorter" else None)


@pytest.mark.parametrize("value", ["yes", True, -0.1, 1.1, float("nan"), float("inf"), None])
def test_unusable_probability_counts_as_refused(value):
    assert db.refused_questions({"flag": {"type": "noul"}}, {"flag": {"noul": value}}) == ["flag"]


def test_v42_retains_the_aligned_classification_criteria(v42):
    parent = db.load_question_set("reviewer_decisions_v4.1.0")
    assert v42["doc_type"] == parent["doc_type"]
    for cls in parent["subclass"]:
        assert v42["subclass"][cls]["criteria"] == parent["subclass"][cls]["criteria"]
    assert "arbitration demand" in v42["subclass"]["correspondence"]["markers"]["demand"]
