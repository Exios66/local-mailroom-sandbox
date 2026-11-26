"""Per-subclass extraction schemas graded against the truth runs score (sandbox schemas)."""
from __future__ import annotations

import json

import pytest

from mailroom_sandbox import runtime
from mailroom_sandbox import subclass_schemas as ss


@pytest.fixture(autouse=True)
def _vendored():
    runtime.activate(load_env_file=False)


def _row(i, cls, sub, **fields):
    return {"id": f"d{i}", "expected_doc_class": cls, "expected_subclass": sub, "expected_fields": fields}


def _split(tmp_path, ids, set_name="dev"):
    d = tmp_path / "split"
    d.mkdir()
    (d / "assignments.jsonl").write_text("".join(json.dumps({"id": i, "set": set_name}) + "\n" for i in ids))
    return d


def _build(rows, split_dir=None):
    return ss.build_registry(rows, revision="r" * 40, split_dir=split_dir)


def test_labeled_fields_are_repaired_from_pending_and_graded(tmp_path):
    rows = [_row(i, "correspondence", "email", sender=f"Person {i}", urgency="routine",
                 recipient=f"R{i}" if i < 5 else None) for i in range(25)]
    reg = _build(rows, _split(tmp_path, [r["id"] for r in rows]))
    email = reg["classes"]["correspondence"]["subclasses"]["email"]
    assert email["rows"] == 25 and email["rows_by_set"]["dev"] == 25
    sender = email["fields"]["sender"]
    assert sender["dojo_status"] == "pending_annotation"
    assert (sender["effective_status"], sender["verdict"]) == ("scored", "iterate")
    assert sender["truth"] == {"hub": 25} and sender["labeled_by_set"]["dev"] == 25
    assert "guide" in sender
    assert email["fields"]["urgency"]["verdict"] == "constant"  # one value on every label
    assert email["fields"]["urgency"]["dominant"] == {"kind": "value", "value": "routine", "share": 1.0}
    assert email["fields"]["recipient"]["verdict"] == "thin"  # 5 dev labels < MIN_DEV
    assert email["fields"]["demand_amount"]["verdict"] == "no_truth"
    assert email["fields"]["content_topic"]["verdict"] == "fixed"  # Dojo label_task
    repaired = {(r["class"], r["field"]) for r in reg["status_repairs"]}
    assert ("correspondence", "sender") in repaired
    assert "demand_amount" in reg["untruthed_output_fields"]["correspondence"]
    assert reg["problems"] == []


def test_without_a_split_counts_are_not_graded_thin():
    rows = [_row(i, "correspondence", "memo", sender=f"P{i}") for i in range(3)]
    sender = _build(rows)["classes"]["correspondence"]["subclasses"]["memo"]["fields"]["sender"]
    assert sender["verdict"] == "iterate" and "labeled_by_set" not in sender


def test_label_outside_the_closed_vocabulary_is_a_problem():
    reg = _build([_row(1, "correspondence", "letter", urgency="high")])
    (p,) = reg["problems"]
    assert (p["kind"], p["field"], p["values"], p["doc_id"]) == ("label_outside_vocabulary", "urgency", ["high"], "d1")


def test_party_roles_grade_the_role_and_check_its_vocabulary():
    rows = [_row(i, "contract", "license", party_roles=json.dumps([f"Acme {i}: licensor", f"Beta {i}: Licensee"]))
            for i in range(20)]
    reg = _build(rows + [_row(99, "contract", "license", party_roles=["Gamma: landlord"])])
    roles = reg["classes"]["contract"]["subclasses"]["license"]["fields"]["party_roles"]
    assert roles["dominant"]["kind"] == "role" and roles["verdict"] == "iterate"
    assert [p["values"] for p in reg["problems"]] == [["landlord"]]


def test_record_type_contradicting_its_subclass_is_a_problem():
    reg = _build([_row(1, "corporate_record", "bylaws", record_type="rights_instrument", entity_name="X Corp")])
    kinds = [(p["kind"], p["values"]) for p in reg["problems"]]
    assert kinds == [("record_type_contradicts_subclass", ["rights_instrument", "bylaws"])]
    bylaws = reg["classes"]["corporate_record"]["subclasses"]["bylaws"]
    assert bylaws["record_type"] == "bylaws" and "certifying_officer" in bylaws["fields"]
    assert bylaws["fields"]["certifying_officer"]["entity"]["description"]


def test_class_rollup_pools_subclasses():
    rows = [_row(i, "correspondence", "email" if i % 2 else "memo", sender=f"P{i}") for i in range(30)]
    roll = _build(rows)["classes"]["correspondence"]["fields"]["sender"]
    assert roll["labeled"] == 30 and roll["subclasses_with_truth"] == 2 and roll["verdict"] == "iterate"


def test_corporate_output_fields_follow_each_runtime_subclass():
    from mailroom_sandbox.corporate_extraction import registry, request_schema

    corp = _build([])["classes"]["corporate_record"]
    for sub in registry.SUBCLASS_SCHEMAS:
        fields = corp["subclasses"][sub]["output_schema_fields"]
        assert set(fields) == set(request_schema(sub, {})["properties"])
        for entity in registry.SUBCLASS_SCHEMAS[sub].entities:
            assert corp["subclasses"][sub]["fields"][entity.key]["in_output_schema"]
    assert "subsidiaries" in corp["subclasses"]["subsidiary_list"]["output_schema_fields"]
    assert "subsidiaries" not in corp["subclasses"]["indenture"]["output_schema_fields"]


def test_labeled_corporate_entity_missing_from_runtime_is_a_problem(monkeypatch):
    from mailroom_sandbox import corporate_extraction

    original = corporate_extraction.request_schema

    def missing_entity(sub, transport):
        schema = original(sub, transport)
        schema["properties"].pop("subsidiaries", None)
        return schema

    monkeypatch.setattr(corporate_extraction, "request_schema", missing_entity)
    reg = _build([_row(1, "corporate_record", "subsidiary_list", subsidiaries=["Acme LLC"])])
    assert any(p["kind"] == "truth_not_in_output_schema" and p["field"] == "subsidiaries"
               for p in reg["problems"])


def test_parse_guide_reads_the_field_tables(tmp_path):
    guide = tmp_path / "g.md"
    guide.write_text("## Correspondence fields\n\n| Field | Type | Convention |\n| --- | --- | --- |\n"
                     "| `sender` | string | Who sent it |\n\n## Something else\n\n| `ignored` | x | y |\n")
    assert ss.parse_guide(guide) == {"correspondence": {"sender": "string: Who sent it"}}


def test_render_is_stable_and_summary_filters():
    reg = _build([_row(1, "correspondence", "email", sender="A")])
    assert ss.render(reg) == ss.render(json.loads(ss.render(reg)))
    rows = ss.summary_rows(reg, cls="correspondence", sub="email", verdict="iterate")
    assert {r[2]: r[3]["effective_status"] for r in rows} == {"sender": "scored", "communication_type": "derived"}


def test_committed_registry_matches_current_inputs_and_has_no_mismatch():
    from mailroom_sandbox import gold_labels, interim_labels
    from mailroom_sandbox.corpus import FAMILY_HF_REVISION

    reg = json.loads(ss.DEFAULT_OUT.read_text(encoding="utf-8"))
    assert reg["schema"] == ss.SCHEMA and reg["problems"] == []
    inputs = reg["inputs"]
    assert inputs["dataset_revision"] == FAMILY_HF_REVISION
    assert inputs["interim_overlay_sha256"] == interim_labels.overlay_fingerprint()
    assert inputs["near_gold_overlay_sha256"] == gold_labels.near_gold_fingerprint()
    assert inputs["labeling_guide_sha256"] == ss._sha(ss.GUIDE.read_bytes())
    assert inputs["split_assignments_sha256"] == ss._read_sets(ss.DEFAULT_SPLIT)[1]
    assert set(reg["classes"]) == set(ss.CLASSES)


def test_every_corpus_subclass_is_a_sorter_catalog_key():
    """Sorter alignment: each subclass with documents is one the sorter can emit, and vice versa."""
    from langchain_agents.doc_inventories import sorter_subclass_catalog

    reg = json.loads(ss.DEFAULT_OUT.read_text(encoding="utf-8"))
    no_docs = {("corporate_record", "certificate_of_formation"), ("correspondence", "other")}
    for cls, centry in reg["classes"].items():
        with_docs = {s for s, e in centry["subclasses"].items() if e["rows"]}
        catalog = set(sorter_subclass_catalog(cls))
        assert with_docs <= catalog, (cls, sorted(with_docs - catalog))
        assert {(cls, s) for s in catalog - with_docs} <= no_docs, cls


def test_cli_check_reports_stale_and_mismatch(tmp_path, monkeypatch, capsys):
    from mailroom_sandbox.cli import main

    reg = _build([_row(1, "correspondence", "letter", urgency="high")])
    monkeypatch.setattr(ss, "load_corpus_rows", lambda revision=None: ([], "r" * 40))
    monkeypatch.setattr(ss, "truth_rows", lambda rows: rows)
    monkeypatch.setattr(ss, "build_registry", lambda rows, **kw: reg)
    out = tmp_path / "reg.json"
    assert main(["schemas", "build", "--check", "--out", str(out), "--split", ""]) == 1
    assert "stale" in capsys.readouterr().err
    assert main(["schemas", "build", "--out", str(out), "--split", ""]) == 1  # written, but a mismatch remains
    assert "MISMATCH label_outside_vocabulary" in capsys.readouterr().out
    assert main(["schemas", "show", "--out", str(out), "--class", "correspondence", "--subclass", "letter",
                 "--verdict", "iterate"]) == 0


def test_cli_build_refuses_an_unreadable_corpus(tmp_path, monkeypatch, capsys):
    from mailroom_sandbox.cli import main

    def boom(revision=None):
        raise ss.SchemaError("corpus rrrr is not readable; run `sandbox datasets pull` first")

    monkeypatch.setattr(ss, "load_corpus_rows", boom)
    assert main(["schemas", "build", "--out", str(tmp_path / "x.json")]) == 2
    assert "datasets pull" in capsys.readouterr().err


def test_record_type_problem_names_the_staged_overlay_as_its_source():
    row = _row(1, "corporate_record", "bylaws", record_type="rights_instrument", entity_name="X Corp")
    row["staged_overlay"] = {"fields": ["record_type"]}
    (p,) = [p for p in _build([row])["problems"] if p["kind"] == "record_type_contradicts_subclass"]
    assert p["source"] == "staged"
