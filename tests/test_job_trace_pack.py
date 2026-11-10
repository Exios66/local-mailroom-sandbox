"""Trace pack/verify/prune and span flattening — pure, no OTel SDK required."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

from mailroom_sandbox.job import otel, trace_pack


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))


def _span(**overrides):
    record = {
        "trace_id": "trace-1",
        "span_id": "span-1",
        "parent_span_id": None,
        "name": "job.run",
        "kind": "internal",
        "start_time_unix_nano": 1_700_000_000_000_000_000,
        "end_time_unix_nano": 1_700_000_001_500_000_000,
        "status_code": "OK",
        "status_description": "",
        "resource": {"service.name": "mailroom", "sandbox.run_id": "run-from-resource"},
        "attributes": {"job.ok": True, "items": 3, "nested": {"a": 1}},
        "events": [{"name": "checkpoint"}],
    }
    record.update(overrides)
    return record


def _write_mirror(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(gzip.compress((json.dumps(r) + "\n").encode()) for r in records))
    return path


def test_local_trace_path_and_disabled_sink(monkeypatch, tmp_path):
    assert otel.local_trace_path("run-1") == tmp_path / "traces" / "run-1.spans.jsonl.gz"
    monkeypatch.setenv(otel.LOCAL_TRACE_ENV, "0")
    assert otel.local_trace_path("run-1") is None
    assert otel.configure_tracing(otel.resolve_sink(sink="none")) is None


def test_slug_and_runner_defaults(monkeypatch):
    assert trace_pack._slug("SAND 041 / run:1") == "SAND-041-run-1"
    assert trace_pack._slug("***") == "run"
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert trace_pack.default_runner() == "axios"
    monkeypatch.setenv("CLAUDECODE", "1")
    assert trace_pack.default_runner() == "claude"


def test_sha256_and_multi_member_read(tmp_path):
    path = tmp_path / "mirror.jsonl.gz"
    path.write_bytes(gzip.compress(b'{"a": 1}\n\n') + gzip.compress(b'{"b": 2}\n'))
    assert trace_pack.read_spans(path) == [{"a": 1}, {"b": 2}]
    assert trace_pack.sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_iso_scalar_and_flatten_attributes():
    assert trace_pack._iso(None) is None
    assert trace_pack._iso("not-an-int") is None
    assert trace_pack._iso(0) == "1970-01-01T00:00:00.000000+00:00"
    assert trace_pack._scalar(None) is None
    assert trace_pack._scalar("x") == "x"
    assert trace_pack._scalar({"a": 1}) == '{"a": 1}'

    row = trace_pack.flatten(_span(), "fallback-run")
    assert row["run_id"] == "run-from-resource"
    assert row["trace_id"] == "trace-1"
    assert row["duration_ms"] == 1500.0
    assert row["status_code"] == "OK"
    assert row["service_name"] == "mailroom"
    assert row["attr.job.ok"] is True
    assert row["attr.items"] == 3
    assert row["attr.nested"] == '{"a": 1}'
    assert json.loads(row["events_json"]) == [{"name": "checkpoint"}]

    fallback = trace_pack.flatten(
        _span(resource={}, start_time_unix_nano=None, end_time_unix_nano=None, events=[]),
        "fallback-run",
    )
    assert fallback["run_id"] == "fallback-run"
    assert fallback["start_time_utc"] is None
    assert fallback["duration_ms"] is None
    assert fallback["events_json"] is None


def test_write_table_parquet_and_csv_fallback(monkeypatch):
    rows = [
        {"name": "a", "value": 1, "mixed": {"x": 1}},
        {"name": "b", "value": 2, "mixed": "text"},
    ]
    table_name, payload = trace_pack._write_table(rows)
    if table_name == "spans.parquet":
        import io

        import pyarrow.parquet as pq

        table = pq.read_table(io.BytesIO(payload))
        assert table.num_rows == 2
        assert set(table.column_names) == {"name", "value", "mixed"}
        # A mixed column falls back to strings instead of failing the pack.
        assert table.column("mixed").to_pylist() == ["{'x': 1}", "text"]
    else:
        assert table_name == "spans.csv.gz"

    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    table_name, payload = trace_pack._write_table(rows)
    assert table_name == "spans.csv.gz"
    text = gzip.decompress(payload).decode()
    assert text.splitlines()[0] == "name,value,mixed"
    assert "a,1" in text and "b,2" in text


def test_pack_writes_manifest_and_zip(tmp_path):
    mirror = _write_mirror(tmp_path / "traces" / "run-t1.spans.jsonl.gz", [_span(), _span(span_id="span-2")])
    result = trace_pack.pack(
        "run-t1", experiment="SAND 041", runner="claude", date="2026-10-01", spans_path=mirror
    )
    assert result["zip"].endswith("2026-10-01/claude_SAND-041_run-t1.zip")
    assert result["span_count"] == 2 and result["trace_count"] == 1
    assert result["first_span_utc"] == "2023-11-14T22:13:20.000000+00:00"
    assert result["uploaded"] is None and result["verified"] is False
    assert result["source_sha256"] == trace_pack.sha256_file(mirror)
    assert result["zip_sha256"] == trace_pack.sha256_file(Path(result["zip"]))
    with zipfile.ZipFile(result["zip"]) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schema"] == "sandbox.trace-pack/v1"
        assert manifest["table"] in zf.namelist()
        assert zf.getinfo(manifest["table"]).compress_type == zipfile.ZIP_STORED
        if manifest["table"].endswith(".parquet"):
            import io

            import pyarrow.parquet as pq

            assert pq.read_table(io.BytesIO(zf.read(manifest["table"]))).num_rows == 2


def test_pack_defaults_and_missing_source(tmp_path):
    mirror = _write_mirror(tmp_path / "traces" / "sandbox-run-2.spans.jsonl.gz", [_span()])
    result = trace_pack.pack("sandbox-run-2", date="2026-10-02", spans_path=mirror)
    assert Path(result["zip"]).name == "axios_sandbox_sandbox-run-2.zip"
    assert result["source"] == str(mirror)
    with pytest.raises(FileNotFoundError, match="no local span mirror"):
        trace_pack.pack("missing-run", spans_path=tmp_path / "nope.gz")


def test_pack_copy_verify_and_prune(tmp_path):
    mirror = _write_mirror(tmp_path / "traces" / "run-t2.spans.jsonl.gz", [_span(), _span(span_id="s2")])
    dest = tmp_path / "Drive" / "LOGS"
    result = trace_pack.pack("run-t2", dest=dest, date="2026-10-03", spans_path=mirror)
    uploaded = Path(result["uploaded"])
    assert result["verified"] is True
    assert uploaded.is_file() and uploaded.parent == dest / "2026-10-03"
    assert result["uploaded_sha256"] == result["zip_sha256"]

    removed = trace_pack.prune(result)
    assert set(removed) == {str(mirror), result["zip"]}
    assert not mirror.exists() and not Path(result["zip"]).exists()
    assert uploaded.is_file()


def test_prune_refuses_unverified_changed_or_missing_upload(tmp_path):
    mirror = _write_mirror(tmp_path / "traces" / "run-t3.spans.jsonl.gz", [_span()])
    unverified = trace_pack.pack("run-t3", date="2026-10-04", spans_path=mirror)
    with pytest.raises(RuntimeError, match="no verified uploaded copy"):
        trace_pack.prune(unverified)
    assert mirror.exists()

    changed = trace_pack.pack("run-t3", dest=tmp_path / "up", date="2026-10-04", spans_path=mirror)
    with open(changed["uploaded"], "ab") as fh:
        fh.write(b"x")
    with pytest.raises(RuntimeError, match="changed or vanished"):
        trace_pack.prune(changed)
    assert mirror.exists()

    vanished = trace_pack.pack("run-t3", dest=tmp_path / "gone", date="2026-10-04", spans_path=mirror)
    Path(vanished["uploaded"]).unlink()
    with pytest.raises(RuntimeError, match="changed or vanished"):
        trace_pack.prune(vanished)


def test_copy_and_verify_detects_hash_mismatch(tmp_path):
    source = tmp_path / "one.zip"
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("manifest.json", "{}")
    result = trace_pack._copy_and_verify(source, tmp_path / "out", "0" * 64)
    assert result["verified"] is False
    assert Path(result["uploaded"]).is_file()
