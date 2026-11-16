"""Audit-trail check of the production slice gate: every decision links to its trace and archive (offline)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from mailroom_sandbox.job import gate, gate_audit
from mailroom_sandbox.job.gate import Bars

RUN_ID = "slice-run"


def _span(item_id, trace_id, name="job.node"):
    return {"trace_id": trace_id, "span_id": ("item-" if name == "job.item" else "node-") + trace_id, "name": name, "attributes": {"item_id": item_id}}


def _checkout(root: Path, docs, *, spans="all", nodes="all", archives="all"):
    """A checkout shaped like the real one: ``<root>/data/{runtime/runs/<run_id>,traces,archive}``.

    ``docs``: ``(id, class, stage)``. ``spans`` / ``nodes`` / ``archives``: ``"all"``, ``"none"`` or a set
    of ids that have them (archives only ever apply to archived documents).
    """
    data = root / "data"
    run = data / "runtime" / "runs" / RUN_ID
    run.mkdir(parents=True)
    (run / "spec.lock.json").write_text(json.dumps({"run_id": RUN_ID, "trace": {"sink": "none"}}))
    have = lambda which, doc_id: which == "all" or (which != "none" and doc_id in which)  # noqa: E731
    with open(run / "dataset.jsonl", "w") as ds, open(run / "items.jsonl", "w") as it, \
            open(run / "nodes.jsonl", "w") as nd:
        for doc_id, cls, stage in docs:
            ds.write(json.dumps({"id": doc_id, "expected_doc_class": cls,
                                 "expected_fields": json.dumps({"sender": "A", "recipient": "B"})}) + "\n")
            it.write(json.dumps({"item_id": doc_id, "ok": True, "error": None,
                                 "pred": {"doc_type": cls, "stage": stage, "extracted_data": {},
                                          "review_causes": ["judge_error"] if stage == "review" else []}}) + "\n")
            if have(nodes, doc_id):
                nd.write(json.dumps({"doc": doc_id, "node": "intake", "status": "running", "ts": 1.0}) + "\n")
    if spans != "none":
        (data / "traces").mkdir()
        with gzip.open(data / "traces" / f"{RUN_ID}.spans.jsonl.gz", "wt") as fh:
            for i, (doc_id, _, _) in enumerate(docs):
                if have(spans, doc_id):
                    fh.write(json.dumps(_span(doc_id, f"trace{i}", "job.item")) + "\n")
                    fh.write(json.dumps(_span(doc_id, f"trace{i}")) + "\n")
    for doc_id, cls, stage in docs:
        if stage == "archived" and have(archives, doc_id):
            (data / "archive" / f"SANDBOX-sandbox_pipeline_{RUN_ID}-{doc_id}" / cls).mkdir(parents=True)
    return run


@pytest.fixture(autouse=True)
def fake_score(monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: 0.95)


def _audit(run, doc_ids, archived):
    data = run.parents[2]
    return gate_audit.audit_trail(run, doc_ids, set(archived), traces_dir=data / "traces",
                                  archive_dir=data / "archive")


DOCS = [("DOC-a", "correspondence", "archived"), ("DOC-b", "correspondence", "archived")]


def test_links_each_document_to_trace_and_archive(tmp_path):
    run = _checkout(tmp_path, DOCS)
    audit = _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])
    assert audit["ok"] is True
    assert audit["trace_ids"] == {"DOC-a": "trace0", "DOC-b": "trace1"}
    assert audit["span_ids"] == {"DOC-a": "item-trace0", "DOC-b": "item-trace1"}
    data = tmp_path / "data"
    assert audit["archives"] == {d: str(gate_audit.archive_path_for(RUN_ID, d, data / "archive"))
                                 for d in ("DOC-a", "DOC-b")}
    assert audit["missing_spans"] == audit["missing_nodes"] == audit["missing_archive"] == []


def test_archive_path_for_matches_the_real_directory_name():
    path = gate_audit.archive_path_for("r1", "DOC-0123", Path("/x/archive"))
    assert path == Path("/x/archive/SANDBOX-sandbox_pipeline_r1-DOC-0123")


def test_missing_spans_fail_and_are_named(tmp_path):
    run = _checkout(tmp_path, DOCS, spans={"DOC-a"})
    audit = _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])
    assert audit["missing_spans"] == ["DOC-b"] and audit["ok"] is False
    assert audit["trace_ids"] == {"DOC-a": "trace0", "DOC-b": None}
    report = gate.gate_report(run, Bars())
    assert "missing spans: 1" in report["verdict"]["reasons"]
    assert report["verdict"]["pass"] is False


def test_no_span_file_fails_once(tmp_path):
    run = _checkout(tmp_path, DOCS, spans="none")
    report = gate.gate_report(run, Bars())
    reasons = report["verdict"]["reasons"]
    assert f"no span mirror at data/traces/{RUN_ID}.spans.jsonl.gz" in reasons
    assert not [r for r in reasons if r.startswith("missing spans")]  # not once per document as well
    assert report["audit"]["ok"] is False and report["audit"]["trace_ids"] == {"DOC-a": None, "DOC-b": None}


def test_review_documents_need_no_archive(tmp_path):
    docs = [("DOC-a", "correspondence", "archived"), ("DOC-r", "correspondence", "review")]
    run = _checkout(tmp_path, docs)
    audit = _audit(run, ["DOC-a", "DOC-r"], ["DOC-a"])
    assert audit["missing_archive"] == [] and audit["ok"] is True
    assert audit["archives"]["DOC-r"] is None


def test_archived_document_without_archive_dir_fails(tmp_path):
    run = _checkout(tmp_path, DOCS, archives={"DOC-a"})
    report = gate.gate_report(run, Bars())
    assert report["audit"]["missing_archive"] == ["DOC-b"]
    assert "missing archive: 1" in report["verdict"]["reasons"]


def test_empty_archive_dir_does_not_count(tmp_path):
    run = _checkout(tmp_path, DOCS)
    (tmp_path / "data" / "archive" / f"SANDBOX-sandbox_pipeline_{RUN_ID}-DOC-b" / "correspondence").rmdir()
    audit = _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])
    assert audit["missing_archive"] == ["DOC-b"] and audit["archives"]["DOC-b"] is None


def test_missing_nodes_fail_and_are_named(tmp_path):
    run = _checkout(tmp_path, DOCS, nodes={"DOC-a"})
    report = gate.gate_report(run, Bars())
    assert report["audit"]["missing_nodes"] == ["DOC-b"]
    assert "missing nodes: 1" in report["verdict"]["reasons"]


def test_complete_trail_keeps_the_verdict_passing(tmp_path):
    run = _checkout(tmp_path, DOCS)
    report = gate.gate_report(run, Bars())
    assert report["audit"]["ok"] is True
    assert not [r for r in report["verdict"]["reasons"] if "missing" in r or "span mirror" in r]


def test_gate_report_defaults_the_dirs_from_the_run_dir(tmp_path):
    run = _checkout(tmp_path, DOCS)
    explicit = gate.gate_report(run, Bars(), traces_dir=tmp_path / "data" / "traces",
                                archive_dir=tmp_path / "data" / "archive")
    assert gate.gate_report(run, Bars())["audit"] == explicit["audit"]
    assert explicit["audit"]["ok"] is True


def test_run_dir_outside_a_checkout_fails_closed(tmp_path):
    run = tmp_path / "loose"
    run.mkdir()
    (run / "dataset.jsonl").write_text(json.dumps({"id": "DOC-a", "expected_doc_class": "correspondence",
                                                    "expected_fields": json.dumps({"sender": "A", "recipient": "B"})}) + "\n")
    reasons = gate.gate_report(run, Bars())["verdict"]["reasons"]
    assert any(r.startswith("audit trail not located") for r in reasons)


def test_bucket_entries_carry_real_archive_and_trace_id(tmp_path):
    docs = [("DOC-a", "correspondence", "archived"), ("DOC-r", "correspondence", "review"),
            ("DOC-s", "correspondence", "review")]
    run = _checkout(tmp_path, docs, spans={"DOC-r"})
    report = gate.gate_report(run, Bars())
    entries = {d["id"]: d for d in report["buckets"]["mechanism:judge_error"]["docs"]}
    assert entries["DOC-r"] == {"id": "DOC-r", "archive": None, "trace_id": "trace1", "span_id": "item-trace1"}
    assert entries["DOC-s"]["trace_id"] is None and entries["DOC-s"]["span_id"] is None  # reported, not invented


def test_bucket_entries_link_the_archive_of_a_wrong_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_score", lambda row, pred: 0.5)
    run = _checkout(tmp_path, [("DOC-a", "correspondence", "archived")])
    entry = gate.gate_report(run, Bars())["buckets"]
    [(cause, bucket)] = entry.items()
    assert cause.startswith("extraction:") or cause.startswith("mechanism:")
    expected = gate_audit.archive_path_for(RUN_ID, "DOC-a", tmp_path / "data" / "archive")
    assert bucket["docs"] == [{"id": "DOC-a", "archive": str(expected), "trace_id": "trace0",
                                "span_id": "item-trace0"}]


def test_spans_are_streamed_not_loaded_whole(tmp_path, monkeypatch):
    run = _checkout(tmp_path, DOCS)
    reads = []
    real = gzip.open

    class Spy:
        def __init__(self, fh):
            self._fh = fh

        def __iter__(self):
            return iter(self._fh)

        def read(self, *a):
            reads.append(a)
            return self._fh.read(*a)

        def __enter__(self):
            self._fh.__enter__()
            return self

        def __exit__(self, *a):
            return self._fh.__exit__(*a)

    monkeypatch.setattr(gate_audit.gzip, "open", lambda *a, **k: Spy(real(*a, **k)))
    assert _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])["ok"] is True
    assert reads == []  # only iterated line by line


def test_span_id_is_the_last_job_item_span_of_the_document(tmp_path):
    run = _checkout(tmp_path, DOCS)
    with gzip.open(tmp_path / "data" / "traces" / f"{RUN_ID}.spans.jsonl.gz", "at") as fh:
        again = _span("DOC-a", "trace0", "job.item")
        again["span_id"] = "item-retry"
        fh.write(json.dumps(again) + "\n")
        fh.write(json.dumps(_span("DOC-a", "trace0")) + "\n")  # a later node span is not the item span
    audit = _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])
    assert audit["span_ids"] == {"DOC-a": "item-retry", "DOC-b": "item-trace1"}


def test_doc_statuses_carry_the_span_pointer(tmp_path):
    run = _checkout(tmp_path, DOCS, spans={"DOC-a"})
    docs = {d["id"]: d for d in gate.gate_report(run, Bars())["docs"]}
    assert docs["DOC-a"]["span_id"] == "item-trace0" and docs["DOC-b"]["span_id"] is None
    assert docs["DOC-a"]["trace_id"] == "trace0" and docs["DOC-a"]["archive"].endswith(f"{RUN_ID}-DOC-a")


def test_unaudited_report_has_no_span_pointer(tmp_path):
    run = _checkout(tmp_path, DOCS)
    assert all("span_id" not in d for d in gate.gate_report(run, Bars(), audit=False)["docs"])


def test_truncated_span_mirror_is_one_failing_reason(tmp_path):
    run = _checkout(tmp_path, DOCS)
    path = tmp_path / "data" / "traces" / f"{RUN_ID}.spans.jsonl.gz"
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])  # a run killed mid-write: no gzip trailer
    report = gate.gate_report(run, Bars())
    reasons = [r for r in report["verdict"]["reasons"] if "span mirror" in r]
    assert reasons == [f"span mirror unreadable at data/traces/{RUN_ID}.spans.jsonl.gz: EOFError"]
    assert not [r for r in report["verdict"]["reasons"] if r.startswith("missing spans")]
    assert report["audit"]["ok"] is False and report["verdict"]["pass"] is False
    assert report["audit"]["trace_ids"] == {"DOC-a": None, "DOC-b": None}


def test_corrupt_span_mirror_is_one_failing_reason(tmp_path):
    run = _checkout(tmp_path, DOCS)
    (tmp_path / "data" / "traces" / f"{RUN_ID}.spans.jsonl.gz").write_bytes(b"not a gzip file at all")
    reasons = gate.gate_report(run, Bars())["verdict"]["reasons"]
    assert f"span mirror unreadable at data/traces/{RUN_ID}.spans.jsonl.gz: BadGzipFile" in reasons


def test_a_document_without_its_job_item_span_fails(tmp_path):
    """Node spans alone do not link a document: its own ``job.item`` span is required (review I4)."""
    run = _checkout(tmp_path, DOCS, spans="none")
    (tmp_path / "data" / "traces").mkdir()
    with gzip.open(tmp_path / "data" / "traces" / f"{RUN_ID}.spans.jsonl.gz", "wt") as fh:
        fh.write(json.dumps(_span("DOC-a", "trace0", "job.item")) + "\n")
        fh.write(json.dumps(_span("DOC-b", "trace1")) + "\n")  # node span only
    audit = _audit(run, ["DOC-a", "DOC-b"], ["DOC-a", "DOC-b"])
    assert audit["missing_spans"] == ["DOC-b"] and audit["ok"] is False
    report = gate.gate_report(run, Bars())
    assert "missing spans: 1" in report["verdict"]["reasons"]


def test_archive_under_another_class_does_not_count(tmp_path):
    """The archive must sit under the class the document was archived as (review M3)."""
    run = _checkout(tmp_path, DOCS, archives={"DOC-a"})
    (tmp_path / "data" / "archive" / f"SANDBOX-sandbox_pipeline_{RUN_ID}-DOC-b" / "contract").mkdir(parents=True)
    report = gate.gate_report(run, Bars())
    assert report["audit"]["missing_archive"] == ["DOC-b"]
    assert "missing archive: 1" in report["verdict"]["reasons"]
