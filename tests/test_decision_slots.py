"""llm-mailroom decision slots in a sandbox run: spec, resolver backend, lock, activation, spend and scoring."""
from __future__ import annotations

import json
import sys
import types

import pytest

from mailroom_sandbox import decision_backends as db
from mailroom_sandbox.job.spec import RunSpec, spec_hash

GATE = {"model": "openai/gpt-6-luna-decisions", "questions": "extraction_gate_v1.3.0"}
RESOLVER = {"model": "openai/gpt-6-luna-decisions", "questions": "closed_field_resolver_v1.0.0"}
HANDOFF = {"doc_type": "correspondence", "field": "intent", "value": "Complaint!", "allowed": ["complaint", "inquiry"]}


def _spec(**kw):
    """A pipeline run spec."""
    return RunSpec.model_validate({"task": "pipeline", "profile": "openrouter", **kw})


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_block_is_hashed_only_when_set_and_kept_verbatim():
    """The block changes the spec hash only when set; the slot keys reach the taxonomy verbatim."""
    plain = _spec(extraction_gate=GATE)
    slotted = _spec(extraction_gate=GATE, decision_slots={"archive_gate": {"mode": "enforce", "park_cap": 0.1}})
    assert spec_hash(plain) != spec_hash(slotted)
    assert slotted.decision_slots.slots() == {"archive_gate": {"mode": "enforce", "park_cap": 0.1}}
    assert not slotted.decision_slots.is_baseline()
    assert _spec(decision_slots={"archive_gate": {"mode": "baseline"}}).decision_slots.is_baseline()


@pytest.mark.parametrize("kw, needle", [
    ({"task": "sorter", "decision_slots": {}}, "runs none"),
    ({"decision_slots": {"archive_gaet": {"mode": "enforce"}}}, "unknown keys"),
    ({"decision_slots": {"archive_gate": {"mode": False}}}, "YAML boolean"),
    ({"decision_slots": {"archive_gate": "enforce"}}, "must be a mapping"),
    ({"decision_slots": {"judge_replacement": {"mode": "gate"}}}, "add an extraction_gate block"),
    ({"decision_slots": {"closed_field_resolver": {"mode": "resolve"}}}, "needs decision_slots.resolver"),
    ({"decision_slots": {"resolver": RESOLVER}}, "nothing would call it"),
    ({"decision_slots": {"sorter_reviewer": {"park_cap": 0.1}}}, "add a reviewer block"),
    ({"decision_slots": {"closed_field_resolver": {"mode": "resolve"},
                         "resolver": {**RESOLVER, "model": "openai/gpt-5"}}}, "not a Decisions-API model"),
])
def test_bad_blocks_are_refused(kw, needle):
    """Every misconfiguration is refused when the spec loads, before preflight."""
    with pytest.raises(ValueError, match=needle):
        RunSpec.model_validate({"task": "pipeline", "profile": "openrouter", **kw})


# ---------------------------------------------------------------------------
# Resolver question set and backend
# ---------------------------------------------------------------------------


def test_question_set_offers_every_allowed_label_and_a_none_option():
    """One pick-one question: the allowed labels in order, then the none option."""
    qset = db.load_question_set("closed_field_resolver_v1.0.0")
    assert qset["kind"] == db.CLOSED_FIELD_RESOLVER
    q = db.resolver_question(qset, HANDOFF)["label"]
    assert q["type"] == "choice" and list(q["criteria"]) == ["complaint", "inquiry", "none_of_these"]
    assert '"Complaint!"' in q["instructions"] and "correspondence" in q["instructions"]
    with pytest.raises(ValueError, match="no allowed labels"):
        db.resolver_question(qset, {**HANDOFF, "allowed": []})
    with pytest.raises(ValueError, match="also an allowed label"):
        db.resolver_question(qset, {**HANDOFF, "allowed": ["none_of_these"]})


def test_a_resolver_set_missing_a_text_is_refused(tmp_path, monkeypatch):
    """A set without its none option fails at load, not on the first document."""
    (tmp_path / "bad_resolver.yaml").write_text("kind: closed_field_resolver\ninstructions: x\nlabel_criterion: y\n")
    monkeypatch.setattr(db, "decisions_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="needs none_option"):
        db.load_question_set("bad_resolver")


def test_decide_closed_field_reads_the_pick_and_counts_usage(monkeypatch):
    """The pick and its probability come back; the none option is no pick; usage is recorded as the resolver."""
    qset = db.load_question_set("closed_field_resolver_v1.0.0")
    sent, usage = [], []
    answers = iter([
        {"answers": {"label": {"choice": "complaint", "probabilities": {"complaint": 0.93, "inquiry": 0.05}}},
         "usage": {"input_tokens": 100, "output_tokens": 0}},
        {"answers": {"label": {"choice": "none_of_these", "probabilities": {"none_of_these": 0.8}}}, "usage": {}},
    ])
    monkeypatch.setattr(db, "_post_decision", lambda body, **kw: sent.append(body) or next(answers))
    monkeypatch.setattr(db, "_record_usage", lambda model, u, agent: usage.append(agent))
    card = {**HANDOFF, "value": "4111 1111 1111 1111"}
    out = db.decide_closed_field("Card 4111 1111 1111 1111 complaint", card, model=RESOLVER["model"], qset=qset)
    assert (out["value"], out["probability"]) == ("complaint", 0.93)
    # Card numbers are masked in the document, the handoff and the question text quoting the value.
    assert "4111" not in json.dumps(sent[0])
    assert sent[0]["state"]["closed_field_handoff"]["allowed"] == ["complaint", "inquiry"]
    out = db.decide_closed_field("text", HANDOFF, model=RESOLVER["model"], qset=qset)
    assert out["value"] is None and out["probability"] == 0.8
    assert usage == [db.CLOSED_FIELD_RESOLVER, db.CLOSED_FIELD_RESOLVER]


def test_backends_refuse_chat_models_and_the_mock_never_calls(monkeypatch):
    """Only a Decisions-API model may resolve; the mock answers no pick without a network call."""
    qset = db.load_question_set("closed_field_resolver_v1.0.0")
    with pytest.raises(ValueError, match="not a Decisions-API model"):
        db.closed_field_resolver_backend("openai/gpt-5", qset)
    with pytest.raises(ValueError, match="closed_field_resolver question set"):
        db.closed_field_resolver_backend(RESOLVER["model"], db.load_question_set("extraction_gate_v1.3.0"))
    monkeypatch.setattr(db, "_post_decision", lambda *a, **k: pytest.fail("mock resolver called the API"))
    answer = db.mock_closed_field_resolver_backend(RESOLVER["model"], qset)("text", HANDOFF)
    assert answer["value"] is None and answer["mock"] is True


def test_the_gate_reports_the_fields_it_was_asked(monkeypatch):
    """fields_asked lets llm-mailroom count an unanswered key field as unsupported."""
    qset = db.load_question_set("extraction_gate_v1.3.0")
    monkeypatch.setattr(db, "_post_decision", lambda body, **kw: {
        "answers": {"verdict": {"choice": "accept", "probabilities": {"accept": 0.9}},
                    "field__parties": {"noul": 0.9}}, "usage": {}})
    monkeypatch.setattr(db, "_record_usage", lambda *a, **k: None)
    out = db.decide_extraction("text", {"doc_type": "contract", "fields": {"parties": ["A"]}},
                               model=GATE["model"], qset=qset)
    assert "parties" in out["fields_asked"] and "governing_law" in out["fields_asked"]
    assert out["field_support"] == {"parties": 0.9} and out["key_field_score"] == 0.0


# ---------------------------------------------------------------------------
# Preflight and lock
# ---------------------------------------------------------------------------


def _slotted(**slots):
    return _spec(extraction_gate=GATE, job={"mock": True}, decision_slots=slots)


def test_an_old_vendored_mailroom_is_refused_at_preflight(monkeypatch):
    """Without graph/decision_slots.py in the vendored mailroom, a non-baseline block cannot run."""
    from mailroom_sandbox.job import preflight

    monkeypatch.setattr(preflight, "vendored_decision_slots", lambda: None)
    errs = preflight._decision_slots_errors(_slotted(archive_gate={"mode": "enforce"}))
    assert errs and "re-vendor llm-mailroom" in errs[0]
    assert preflight._decision_slots_errors(_slotted(archive_gate={"mode": "baseline"})) == []


def test_an_all_baseline_block_is_still_validated(monkeypatch):
    """A baseline block with a bad value fails preflight, not graph compilation."""
    from mailroom_sandbox.job import preflight

    def parse_slots(raw):
        raise ValueError("decision_slots.cap_warmup must be a positive integer, got 0")

    monkeypatch.setattr(preflight, "vendored_decision_slots", lambda: types.SimpleNamespace(parse_slots=parse_slots))
    errs = preflight._decision_slots_errors(_slotted(cap_warmup=0, archive_gate={"mode": "baseline"}))
    assert errs and "cap_warmup" in errs[0]


def test_preflight_uses_the_vendored_parser(monkeypatch):
    """The vendored llm-mailroom's own parse_slots judges the values."""
    from mailroom_sandbox.job import preflight

    seen = []

    def parse_slots(raw):
        seen.append(raw)
        raise ValueError("decision_slots.archive_gate.park_cap must be null or a number in [0, 1]")

    monkeypatch.setattr(preflight, "vendored_decision_slots", lambda: types.SimpleNamespace(parse_slots=parse_slots))
    errs = preflight._decision_slots_errors(_slotted(archive_gate={"mode": "enforce", "park_cap": 2}))
    assert seen == [{"archive_gate": {"mode": "enforce", "park_cap": 2}}] and "park_cap" in errs[0]


def test_lock_freezes_the_resolver_question_set():
    """The lock keeps the slots verbatim and the resolver's question set by content and hash."""
    from mailroom_sandbox.job.preflight import _decision_slots_lock

    spec = _slotted(closed_field_resolver={"mode": "resolve"}, resolver=RESOLVER)
    block = _decision_slots_lock(spec)
    assert block["slots"] == {"closed_field_resolver": {"mode": "resolve"}}
    assert block["resolver"]["question_set"]["kind"] == db.CLOSED_FIELD_RESOLVER
    assert len(block["resolver"]["questions_sha256"]) == 64


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def test_activation_registers_and_clears_the_resolver(monkeypatch):
    """A locked resolver is registered; none clears it; an old mailroom refuses one."""
    from mailroom_sandbox import runtime

    registered = []
    fake = types.ModuleType("agents.closed_field_resolver")
    fake.register_closed_field_resolver = registered.append
    monkeypatch.setitem(sys.modules, "agents.closed_field_resolver", fake)
    block = {**RESOLVER, "question_set": db.load_question_set("closed_field_resolver_v1.0.0")}
    runtime._register_closed_field_resolver(runtime._closed_field_resolver_backend(block))
    runtime._register_closed_field_resolver(runtime._closed_field_resolver_backend(None))
    assert callable(registered[0]) and registered[1] is None
    monkeypatch.setitem(sys.modules, "agents.closed_field_resolver", None)
    with pytest.raises(RuntimeError, match="re-vendor llm-mailroom"):
        runtime._register_closed_field_resolver(lambda *a: {})
    runtime._register_closed_field_resolver(None)


def test_slots_block_reads_a_spec_and_a_lock():
    """An unlocked spec and its locked block give the same taxonomy block."""
    from mailroom_sandbox import runtime
    from mailroom_sandbox.job.preflight import _decision_slots_lock

    spec = _slotted(closed_field_resolver={"mode": "suggest"}, resolver=RESOLVER)
    from_spec, resolver = runtime._slots_block(spec.decision_slots)
    from_lock, locked = runtime._slots_block(_decision_slots_lock(spec))
    assert from_spec == from_lock == {"closed_field_resolver": {"mode": "suggest"}}
    assert resolver["model"] == locked["model"] and "question_set" in locked
    assert runtime._slots_block(None) == (None, None)


def test_every_run_gets_a_fresh_ledger_and_a_new_block_a_new_graph(monkeypatch):
    """Caps are per run: every activation resets the ledger; only a changed block rebuilds the graph."""
    from mailroom_sandbox import runtime

    calls = []
    slots_mod = types.ModuleType("graph.decision_slots")
    slots_mod.reset_ledger = lambda: calls.append("ledger")
    build_mod = types.ModuleType("graph.build_graph")
    build_mod.reset_compiled_graph = lambda: calls.append("graph")
    monkeypatch.setitem(sys.modules, "graph.decision_slots", slots_mod)
    monkeypatch.setitem(sys.modules, "graph.build_graph", build_mod)
    monkeypatch.setattr(runtime, "_ACTIVE_SLOTS", None)
    runtime._restart_decision_slots({"archive_gate": {"mode": "enforce"}})
    runtime._restart_decision_slots({"archive_gate": {"mode": "enforce"}})  # a second run, same block
    assert calls == ["ledger", "graph", "ledger"]
    runtime._restart_decision_slots(None)
    assert calls == ["ledger", "graph", "ledger", "ledger", "graph"]
    monkeypatch.setitem(sys.modules, "graph.decision_slots", None)
    block = {"arbiter_veto": {"mode": "enforce"}}
    for _ in range(2):  # a failed activation never turns a retry with the same block into a no-op
        with pytest.raises(RuntimeError, match="re-vendor llm-mailroom"):
            runtime._restart_decision_slots(block)


# ---------------------------------------------------------------------------
# Spend and budget
# ---------------------------------------------------------------------------


def test_the_resolver_bills_openrouter_and_is_in_the_api_budget():
    """A resolver puts the run under the OpenRouter checks and its model in the cap check."""
    from mailroom_sandbox.job import api_budget, deploy_env
    from mailroom_sandbox.job.spend import uses_openrouter

    other = "openai/gpt-6-nova-decisions"
    lock = {"task": "pipeline", "engine": {"kind": "vllm", "model": "Qwen/Qwen3-8B"}, "job": {"mock": False},
            "decision_slots": {"slots": {}, "resolver": {"model": other}}}
    assert uses_openrouter(lock)
    assert api_budget.api_models(lock) == [other]
    assert deploy_env.lock_uses_openrouter(lock)
    assert not deploy_env.lock_uses_openrouter({**lock, "decision_slots": {"slots": {}}})
    spec = _slotted(closed_field_resolver={"mode": "resolve"}, resolver={**RESOLVER, "model": other})
    assert other in api_budget.spec_api_models(spec)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _doc(stage, outcome, *, outcomes=None, marks=None, gate_score=None):
    pred = {"stage": stage, "decision_slot_outcomes": outcomes or {}, "decision_slot_marks": marks or []}
    if gate_score is not None:
        pred["extraction_gate"] = {"key_field_score": gate_score}
    return ({"row": {}, "item": {"pred": pred}}, {"id": outcome, "stage": stage, "outcome": outcome})


def test_scoring_reads_slot_outcomes_and_the_gate_score():
    """Per-slot rates and the gate's risk-coverage curve over the scorable archives."""
    pytest.importorskip("llm_dojo_scoring.analysis.risk_coverage")
    from mailroom_sandbox.job.gate_slots import decision_slot_report

    pairs = [
        _doc("archived", "correct_archive", outcomes={"archive_gate": {"action": "agree"}},
             marks=["seen:archive_gate"], gate_score=0.9),
        _doc("archived", "wrong_archive", outcomes={"archive_gate": {"action": "capped"}},
             marks=["seen:archive_gate"], gate_score=0.4),
        _doc("review", "review", outcomes={"archive_gate": {"action": "park", "route": "human_review"}},
             marks=["seen:archive_gate", "park:archive_gate"]),
    ]
    docs, statuses = [p[0] for p in pairs], [p[1] for p in pairs]
    out = decision_slot_report(docs, statuses, max_wrong_archive_rate=0.0)
    out["gate_operating_point"] = out["gate_operating_point"]["upper95"]
    gate = out["summary"]["slots"]["archive_gate"]
    assert gate["n_seen"] == 3 and gate["actions"] == {"agree": 1, "capped": 1, "park": 1}
    assert out["summary"]["pipeline"]["wrong_archive_rate"] == 0.5
    curve = out["gate_risk_coverage"]
    assert curve["n_scorable"] == 2  # the parked document is not on the curve
    assert out["gate_operating_point"] is None  # two archives: no Wilson bound fits a zero budget


def test_scoring_hands_the_dojo_one_record_per_document(monkeypatch):
    """Without the real Dojo module: the records and curve rows the sandbox passes it."""
    from mailroom_sandbox.job.gate_slots import decision_slot_report

    seen = {}
    fake = types.ModuleType("llm_dojo_scoring.analysis.risk_coverage")
    fake.slot_decision_summary = lambda records: seen.setdefault("records", list(records)) and "summary"
    fake.risk_coverage_curve = lambda rows: seen.setdefault("rows", list(rows)) and "curve"
    fake.operating_point = lambda curve, max_wrong_archive_rate: ("point", max_wrong_archive_rate)
    monkeypatch.setitem(sys.modules, "llm_dojo_scoring.analysis.risk_coverage", fake)
    pairs = [_doc("archived", "wrong_archive", marks=["seen:archive_gate"], gate_score=0.3),
             _doc("review", "review", marks=["seen:archive_gate"]),
             _doc("archived", "unscorable_archive", marks=["seen:archive_gate"])]
    fake.operating_point = lambda curve, max_wrong_archive_rate, use_upper=True: (use_upper, max_wrong_archive_rate)
    out = decision_slot_report([p[0] for p in pairs], [p[1] for p in pairs], max_wrong_archive_rate=0.02)
    assert out["available"] and out["gate_operating_point"] == {"observed": (False, 0.02), "upper95": (True, 0.02)}
    assert [(r["final_stage"], r["wrong_archive"]) for r in seen["records"]] == [
        ("archived", True), ("review", None), ("archived", None)]
    assert [(r["score"], r["wrong"]) for r in seen["rows"]] == [(0.3, True), (None, None)]


def test_no_slots_no_report_and_an_old_dojo_says_so(monkeypatch):
    """A run without slots has no section; a Dojo without the module gives a reason, not an error."""
    from mailroom_sandbox.job.gate_slots import decision_slot_report

    plain = {"row": {}, "item": {"pred": {"stage": "archived"}}}
    assert decision_slot_report([plain], [{"stage": "archived", "outcome": "correct_archive"}]) is None
    monkeypatch.setitem(sys.modules, "llm_dojo_scoring.analysis.risk_coverage", None)
    doc, status = _doc("archived", "correct_archive", marks=["seen:archive_gate"])
    out = decision_slot_report([doc], [status])
    assert out["available"] is False and "refresh the Dojo vendor snapshot" in out["reason"]


def test_runs_export_the_slot_fields():
    """The per-document export names every llm-mailroom slot record."""
    from mailroom_sandbox.eval.runners import DECISION_SLOT_FIELDS

    assert DECISION_SLOT_FIELDS == ("decision_slot_outcomes", "decision_slot_marks", "closed_field_resolutions",
                                    "judge_source")


def test_the_gate_report_scores_the_gated_classes_aligned(tmp_path, monkeypatch):
    """The slice gate passes each gated document with its own status; ungated classes stay out."""
    from mailroom_sandbox.job import gate, gate_slots
    from mailroom_sandbox.job.gate import Bars

    monkeypatch.setattr(gate, "_score", lambda row, pred: pred.get("_score"))
    run = tmp_path / "slice"
    run.mkdir()
    labels = {"insurance_claim": {"claim_number": "C-1", "policy_number": "P-9"},
              "correspondence": {"sender": "A. Smith", "recipient": "B. Jones"},
              "merger_agreement": {"parties": "A"}}
    docs = [("c1", "insurance_claim", 0.95, "agree"), ("k1", "correspondence", 0.2, "capped"),
            ("m1", "merger_agreement", 0.95, "park")]
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it:
        for doc_id, cls, score, action in docs:
            ds.write(json.dumps({"id": doc_id, "expected_doc_class": cls,
                                 "expected_fields": json.dumps(labels[cls])}) + "\n")
            pred = {"stage": "archived", "extracted_data": {}, "_score": score,
                    "decision_slot_marks": ["seen:archive_gate"],
                    "decision_slot_outcomes": {"archive_gate": {"action": action}}}
            it.write(json.dumps({"item_id": doc_id, "ok": True, "pred": pred}) + "\n")
    seen = {}
    monkeypatch.setattr(gate_slots, "decision_slot_report",
                        lambda d, s, **kw: seen.update(pairs=[(x["item"]["pred"]["decision_slot_outcomes"]
                                                               ["archive_gate"]["action"], y["outcome"])
                                                              for x, y in zip(d, s)]) or {"available": True})
    bars = Bars(gated=("insurance_claim", "correspondence"), min_labelled=1)
    report = gate.gate_report(run, bars, audit=False)
    assert report["decision_slots"] == {"available": True}
    assert seen["pairs"] == [("agree", "correct_archive"), ("capped", "wrong_archive")]


def test_a_mock_override_of_a_live_decisions_lock_is_refused():
    """Activation registers live Decisions models from a non-mock lock, so mock=True must not bypass the budget."""
    from mailroom_sandbox.job import runner

    lock = {"task": "pipeline", "job": {"mock": False}, "extraction_gate": {"model": GATE["model"]}}
    store = types.SimpleNamespace(read_lock=lambda: lock, verify_generation=lambda: None)
    with pytest.raises(ValueError, match="mock override would still call them"):
        runner.run_job(store, task="pipeline", model="m", profile="openrouter", mock=True)
    runner._refuse_mock_override(store, False)  # the lock's own live run is fine
    lock["job"]["mock"] = True
    runner._refuse_mock_override(store, True)  # a mock lock registers only offline stubs
