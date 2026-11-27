"""Phase 4 references: the reference pool, examples, earlier attempts and guide definitions."""

from __future__ import annotations

import collections
import json

import pytest

from mailroom_sandbox import correcting_judge as cj
from mailroom_sandbox import judge_references as jr
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec

ASSIGN = [
    {"id": "C-1", "set": "calibration", "component": "K1", "doc_class": "contract", "subclass": "Service"},
    {"id": "C-2", "set": "pool", "component": "K2", "doc_class": "contract", "subclass": "Service"},
    {"id": "C-3", "set": "dev", "component": "K3", "doc_class": "contract", "subclass": "Service"},
    {"id": "C-4", "set": "heldout", "component": "K4", "doc_class": "contract", "subclass": "Service"},
    {"id": "C-5", "set": "pool", "component": "K5", "doc_class": "contract", "subclass": "Lease"},
    {"id": "C-6", "set": "pool", "component": "K6", "doc_class": "contract", "subclass": "Service"},
]


def _ng(value, basis="near_gold:two_pass_agree", text="quoted"):
    """One gold-overlay label (the scorer's near-gold layer, ``data/labels/gold-overlay``)."""
    return {"value": value, "basis": basis, "use_as_truth": False, "status": "gap_fill",
            "evidence": [{"start": 0, "end": 6, "text": text}]}


def _overlay(doc_id, labels):
    return {"doc_id": doc_id, "doc_class": "contract", "doc_subclass": "Service", "labels": labels}


def _interim(doc_id, labels):
    return {"doc_id": doc_id, "doc_class": "contract", "doc_subclass": "Service", "labels": labels}


def _truth(value, status="gap_fill", basis="gate_accepted_grounded"):
    return {"value": value, "status": status, "basis": basis, "use_as_truth": status != "disputed"}


def _pool():
    near_gold = [_overlay("C-1", {"governing_law": _ng("Delaware"), "parties": _ng(["C1 Ltd"]),
                                  "effective_date": _ng("2020-01-01")}),
                 _overlay("C-3", {"governing_law": _ng("Texas")}), _overlay("C-4", {"governing_law": _ng("Ohio")}),
                 _overlay("C-2", {"parties": _ng(["A Ltd"])}),
                 _overlay("C-6", {"governing_law": _ng("Utah", basis="candidate:one_pass")})]
    interim = [_interim("C-1", {"governing_law": _truth("New York"),  # a gate gap fill: near-gold supersedes it
                                "parties": _truth(["C1 Holdings Ltd"], basis="original_header"),  # kept over near-gold
                                "effective_date": _truth("2020-02-02", status="correction", basis="review_read_record"),
                                "term_length": _truth("2 years")}),
               _interim("C-2", {"governing_law": _truth("Maine", status="disputed")}),
               _interim("C-5", {"term_length": _truth("1 year")})]
    return jr.build_pool(ASSIGN, interim, near_gold)


def test_the_pool_holds_only_calibration_and_pool_documents():
    pool = _pool()
    assert [r["doc_id"] for r in pool] == ["C-1", "C-2", "C-5"]
    assert {r["set"] for r in pool} == {"calibration", "pool"}
    assert pool[0]["component"] == "K1" and pool[0]["subclass"] == "Service"


def test_the_pool_follows_the_scorers_truth_precedence():
    """Owner (2026-11-27): examples match the truth runs are scored against (``gold_labels.apply_near_gold``)."""
    fields = _pool()[0]["fields"]
    # SHF-010: reviewed near-gold supersedes an interim gate gap fill.
    assert fields["governing_law"] == {"value": "Delaware", "source": "near_gold", "evidence": ["quoted"]}
    # An original_header gap fill and an interim correction stand over near-gold.
    assert fields["parties"]["value"] == ["C1 Holdings Ltd"] and fields["parties"]["source"] == "interim"
    assert fields["effective_date"]["value"] == "2020-02-02" and fields["effective_date"]["source"] == "interim"
    assert fields["term_length"]["source"] == "interim"  # a field only interim labels gives a value


def test_disputed_labels_are_left_out():
    c2 = next(r for r in _pool() if r["doc_id"] == "C-2")
    assert set(c2["fields"]) == {"parties"}  # the disputed interim label and a non-near-gold basis are not truth


def test_examples_match_type_and_subtype_and_are_capped_at_two():
    pool = _pool() + [{**_pool()[1], "doc_id": "C-7"}, {**_pool()[1], "doc_id": "C-8"}]
    picked = jr.examples(pool, "contract", "Service", k=2, max_chars=3000)
    assert [e["doc_id"] for e in picked] == ["C-1", "C-2"]  # deterministic: sorted by doc id
    assert all(e["subclass"] == "Service" for e in picked)
    assert jr.examples(pool, "contract", "Service", k=2, max_chars=3000, exclude={"C-1"})[0]["doc_id"] == "C-2"
    assert jr.examples(pool, "merger_agreement", "Service", k=2, max_chars=3000) == []
    assert all(len(json.dumps(e)) <= 120 for e in jr.examples(pool, "contract", "Service", k=2, max_chars=120))


def test_examples_show_only_the_requested_fields():
    """Review finding: an example must not show a field the extraction was not asked for (a Phase 3 drop)."""
    picked = jr.examples(_pool(), "contract", "Service", k=2, max_chars=3000, fields={"governing_law"})
    assert [e["doc_id"] for e in picked] == ["C-1"]  # C-2 labels only parties, so it has nothing to show
    assert set(picked[0]["fields"]) == {"governing_law"}


def test_a_drawn_document_sharing_a_component_with_the_pool_is_refused(tmp_path, monkeypatch):
    from mailroom_sandbox.job import preflight

    pool_path = tmp_path / "pool.jsonl"
    pool_path.write_text("".join(json.dumps(r) + "\n" for r in _pool()))
    assert jr.pool_leaks(_pool(), {"C-3": "K3"}) == []
    leaks = jr.pool_leaks(_pool(), {"C-3": "K1", "C-1": "K1"})
    assert len(leaks) == 1 and "C-1" in leaks[0] and "C-3" in leaks[0]

    spec = RunSpec(run_id="r-judge", task="pipeline", profile="openrouter",
                   dataset=DatasetSpec(local_path="file:///x.jsonl"), engine={"kind": "vllm-local", "modal": None},
                   job={"mock": True}, judge={"mode": "correct", "references": "train_pool",
                                              "reference_pool": str(pool_path)})

    class Store:
        dataset_path = tmp_path / "rows.jsonl"

        @staticmethod
        def dataset_rows():
            return [{"id": "D-9"}]

    Store.dataset_path.write_text("{}\n")
    monkeypatch.setattr(preflight, "prepare_subset", lambda *a, **k: {})
    monkeypatch.setattr(preflight, "_dataset_check", lambda prov: {"name": "dataset", "ok": True})
    monkeypatch.setattr(preflight, "_target_row_failure", lambda *a: None)
    monkeypatch.setattr(cj, "_assigned_sets", lambda path=cj.ASSIGNMENTS: {"D-9": "dev"})
    monkeypatch.setattr(jr, "assigned_components", lambda path=None: {"D-9": "K2"})
    report = {"status": "ok", "checks": []}
    prov, failed = preflight._prepare_dataset_rows(spec, Store, report)
    assert prov is None and failed["status"] == "failed"
    detail = next(c for c in report["checks"] if c["name"] == "judge_references")["detail"]
    assert "D-9" in detail and "K2" in detail and "C-2" in detail
    monkeypatch.setattr(jr, "assigned_components", lambda path=None: {"D-9": "K9"})
    report = {"status": "ok", "checks": []}
    assert preflight._prepare_dataset_rows(spec, Store, report) == ({}, None)
    # Review finding: the leak scan must cover the bytes the lock pins; a pool edited between the
    # scan and the lock's hash is refused rather than locked unchecked.
    from mailroom_sandbox.job import spec as spec_module

    monkeypatch.setattr(spec_module, "judge_core", lambda judge: {"reference_pool_sha256": "f" * 64})
    report = {"status": "ok", "checks": []}
    prov, failed = preflight._prepare_dataset_rows(spec, Store, report)
    assert prov is None and "changed during preflight" in report["checks"][-1]["detail"]


def test_the_committed_pool_is_current():
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "scripts/build_judge_reference_pool.py", "--check"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_label_counts_match_the_spec_table():
    rows = [json.loads(line) for line in jr.POOL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = collections.Counter(row["doc_class"] for row in rows)
    assert counts == {"contract": 33, "corporate_record": 119, "correspondence": 550, "insurance_claim": 322,
                      "merger_agreement": 4}
    assert {row["set"] for row in rows} == {"calibration", "pool"}


def test_without_examples_the_prompt_has_none(monkeypatch):
    from unittest.mock import MagicMock

    prompts: list[str] = []
    monkeypatch.setattr("agents.base.get_llm", lambda *a, **k: (MagicMock(), "m"))
    monkeypatch.setattr(cj.CorrectingJudge, "_call_structured",
                        lambda self, msg, *a, **k: prompts.append(msg) or {"ruling": "accept", "score": 1.0,
                                                                            "reason": "", "wrong_fields": [],
                                                                            "retry_fields": [], "fixes": []})
    cj.activate({"mode": "correct", "model": "qwen/qwen3.7-plus", "models_by_class": {}, "references": "off",
                 "max_examples": 2, "max_attempt_chars": 4000, "max_example_chars": 3000}, pool_sha256=None)
    try:
        cj.rule({"doc_type": "contract", "contract_subtype": "Service", "doc_text": "Text.",
                 "extracted_data": {"governing_law": "Delaware"}}, pass_no=1)
    finally:
        cj.deactivate()
    assert prompts and "LABELED_EXAMPLES" not in prompts[0] and "EARLIER_ATTEMPTS" not in prompts[0]


def test_attempts_are_the_earlier_ones_and_bounded():
    history = [{"attempt_no": 1, "kind": "extract", "extracted_data": {"a": "x" * 50, "_report": {}, "reasoning": "r"},
                "judge_verdict": "partial", "judge_findings": ["a wrong"]},
               {"attempt_no": 2, "kind": "retry_extract", "extracted_data": {"a": "y"}}]
    out = jr.attempts_for({"extraction_attempt_history": history}, max_chars=4000)
    assert [a["attempt"] for a in out] == [1]  # the latest attempt is the extraction under review
    assert out[0]["fields"] == {"a": "x" * 50} and out[0]["judge_verdict"] == "partial"
    assert jr.attempts_for({"extraction_attempt_history": history}, max_chars=10) == []


def test_guide_definitions_prefer_the_curated_text():
    from mailroom_sandbox.schema_guide import GUIDE_DESCRIPTIONS

    guide = jr.guide_for("contract", "Service")
    for name, text in GUIDE_DESCRIPTIONS["contract"].items():
        assert guide[name] == text


@pytest.mark.parametrize("references", ["off", "train_pool"])
def test_rule_feeds_the_prompt_its_references(references, monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    pool_path = tmp_path / "pool.jsonl"
    pool_path.write_text("".join(json.dumps(r) + "\n" for r in _pool()))
    prompts: list[str] = []
    monkeypatch.setattr("agents.base.get_llm", lambda *a, **k: (MagicMock(), "m"))
    monkeypatch.setattr(cj.CorrectingJudge, "_call_structured",
                        lambda self, msg, *a, **k: prompts.append(msg) or {"ruling": "accept", "score": 1.0,
                                                                            "reason": "", "wrong_fields": [],
                                                                            "retry_fields": [], "fixes": []})
    import hashlib

    sha = hashlib.sha256(pool_path.read_bytes()).hexdigest()
    cj.activate({"mode": "correct", "model": "qwen/qwen3.7-plus", "models_by_class": {}, "references": references,
                 "reference_pool": str(pool_path) if references == "train_pool" else None, "max_examples": 2,
                 "max_attempt_chars": 4000, "max_example_chars": 3000}, pool_sha256=sha)
    history = [{"attempt_no": 1, "kind": "extract", "extracted_data": {"governing_law": "Nevada"}},
               {"attempt_no": 2, "kind": "retry_extract", "extracted_data": {"governing_law": "Delaware"}}]
    from mailroom_sandbox.job import call_guard

    try:
        with call_guard.document() as scope:
            scope["row_id"] = "C-1"  # the dataset row id; the pipeline's own doc_id is an intake UUID
            cj.rule({"doc_id": "6ca7c5fa-a4ee-4bad-b9ae-87d1029e0f35", "doc_type": "contract",
                     "contract_subtype": "Service", "doc_text": "Text.", "extracted_data": {"governing_law": "Delaware"},
                     "extraction_attempt_history": history}, pass_no=2)
    finally:
        cj.deactivate()
    assert "EARLIER_ATTEMPTS" in prompts[0] and "Nevada" in prompts[0]
    assert "FIELD_DEFINITIONS" in prompts[0]
    if references == "train_pool":
        assert "LABELED_EXAMPLES" in prompts[0] and '"C-2"' in prompts[0]
        assert '"C-1"' not in prompts[0].split("LABELED_EXAMPLES")[1]  # never the judged document's own labels
    else:
        assert "LABELED_EXAMPLES" not in prompts[0]


def test_read_sources_accepts_a_one_shot_class_iterable():
    """A generator of class names filters near-gold the same way a list does (it is read once)."""
    assignments, interim, near_gold = jr.read_sources(["contract"])
    assert near_gold, "the committed overlay has contract near-gold records"
    once = jr.read_sources(c for c in ["contract"])
    assert once == (assignments, interim, near_gold)
