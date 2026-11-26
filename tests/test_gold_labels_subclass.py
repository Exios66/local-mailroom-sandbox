"""Corporate admission follows the corpus subclass and the registered schema."""
import importlib.util
from pathlib import Path

import pytest

from mailroom_sandbox import gold_labels as gl
from mailroom_sandbox.eval.scoring import score_extraction_row

TEXT = "Subsidiaries: Acme Inc; Beta LLC. Trustee: Trust Co. Price $50."


def gate(field, value, evidence=None, subclass="subsidiary_list"):
    entry = {"value": value, "evidence": evidence or [TEXT], "absent": "full read"}
    result = gl.validate_submission({"doc_id": "D", "fields": {field: entry}}, TEXT,
                                    "corporate_record", subclass)
    return result.fields[field]


def test_subclass_targets_and_queue_exclude_known_and_inapplicable():
    row = {"document_id": "D", "filename": "d", "expected": "corporate_record",
           "expected_subclass": "subsidiary_list", "gt_fields": {"subsidiaries": ["Acme Inc"]}}
    fields = gl.work_queue([row])[0]["fields"]
    assert "subsidiary_jurisdictions" in fields
    assert not {"subsidiaries", "filing_number", "jurisdiction", "signatories", "trustee"} & set(fields)
    assert "filing_number" not in gl.target_fields("corporate_record", doc_subclass="indenture")
    with pytest.raises(KeyError):
        gl.work_queue([{**row, "expected_subclass": None}])


def test_accepted_subsidiaries_reach_real_scoring_event():
    result = gate("subsidiaries", ["Acme Inc", "Beta LLC"], ["Acme Inc", "Beta LLC"])
    assert result.ok
    expected = {"subsidiaries": result.value, "gt_presence": {"subsidiaries": "populated"}}
    score = score_extraction_row("corporate_record", {"subsidiaries": result.value}, expected,
                                 expected_subclass="subsidiary_list")
    assert score["n_targeted"] == 1
    assert score["fields"]["entity_list_scores"]["subsidiaries"].f1 == 1


@pytest.mark.parametrize("field,value", [
    ("subsidiaries", None), ("subsidiaries", "Acme Inc"),
    ("subsidiaries", ["Acme Inc", True]), ("subsidiaries", ["Acme Inc", None]),
    ("subsidiaries", ["Acme Inc", ""]), ("subsidiaries", ["Acme Inc", "Unknown LLC"]),
    ("trustee", "Trust Co"), ("filing_number", "50"), ("jurisdiction", "Delaware"),
    ("signatories", []), ("invented", "Acme Inc"),
])
def test_invalid_and_inapplicable_fields_are_rejected(field, value):
    assert not gate(field, value).ok
    assert not gl.evidence_support("corporate_record", field, value, [TEXT], "subsidiary_list")[0]


def test_nullable_scalar_and_strict_money():
    assert gate("trustee", None, subclass="indenture").ok
    assert not gate("trustee", True, subclass="indenture").ok
    assert gate("principal_amount", "$50", subclass="indenture").ok
    assert not gate("principal_amount", "USD 50", subclass="indenture").ok
    assert not gate("principal_amount", 50, subclass="indenture").ok


def test_review_correction_cannot_bypass_subclass():
    spec = importlib.util.spec_from_file_location("subclass_cli", Path(__file__).resolve().parents[1] / "scripts/gold_labels.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    doc = {"doc_id": "D", "doc_class": "corporate_record", "subclass": "subsidiary_list"}
    rec = {"doc_id": "D", "field": "trustee"}
    decision = {"verdict": "correct", "entry": {"value": "Trust Co", "evidence": ["Trust Co"]}}
    with pytest.raises(cli._BuildError, match="fails the gate"):
        cli._resolve_decision(rec, decision, None, doc, TEXT)


def test_cli_uses_corpus_subclass_and_refuses_unknown(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("subclass_cli_validate", Path(__file__).resolve().parents[1] / "scripts/gold_labels.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    row = {"document_id": "D", "filename": "d", "expected": "corporate_record", "expected_subclass": "subsidiary_list"}
    monkeypatch.setattr(cli, "_load_corpus", lambda _: ([row], {"d": TEXT}))
    path = tmp_path / "sub.jsonl"
    gl.write_jsonl(path, [{"doc_id": "D", "subclass": "indenture", "fields": {"trustee": {"value": "Trust Co", "evidence": ["Trust Co"]}}}])
    assert not cli._validate_all(tmp_path, [str(path)])[0][2].fields["trustee"].ok
    for bad in (None, "invented"):
        row["expected_subclass"] = bad
        with pytest.raises(SystemExit):
            cli._validate_all(tmp_path, [str(path)])
