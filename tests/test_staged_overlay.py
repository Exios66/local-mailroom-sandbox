"""mailroom_sandbox.staged_overlay: pinned, hash-checked staged label overlays for production scoring."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from mailroom_sandbox import staged_overlay as so

VERSION = "9.3.1-rc.9"
BASE = "f" * 40
CUT = f"v9.3.0/pre-release/v{VERSION}"
TEXT = "This Agreement is governed by Delaware law. Notice: one hundred eighty (180) days."


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(**labels):
    return {"doc_id": "DOC-1", "doc_class": "contract", "content_sha256": _sha(TEXT.encode()), "labels": labels}


LABELS = {
    "governing_law": {"value": "Delaware", "presence": "populated", "override": False},
    "parties": {"value": ["A Corp", "B LLC"], "presence": "populated", "override": True},
    "territory": {"value": None, "presence": "documented_absence", "override": False},
    "subclass": {"value": "license", "presence": "populated", "override": True},
}


def _write_cut(cache: Path, records: list[dict]) -> str:
    """Write a cut under ``cache`` and return its MANIFEST.json sha256."""
    d = cache / CUT
    (d / "overlay").mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records).encode()
    (d / "overlay" / "contract.jsonl").write_bytes(body)
    manifest = {"kind": so.KIND, "version": VERSION, "base_hf": {"tag_commit": BASE},
                "files": {"overlay/contract.jsonl": {"sha256": _sha(body), "bytes": len(body)}}}
    raw = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
    (d / "MANIFEST.json").write_bytes(raw)
    return _sha(raw)


def _pin(root: Path, manifest_sha: str, commit: str = "a" * 40) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / so.PINS_FILE).write_text(json.dumps({"overlays": {VERSION: {
        "repo": "owner/issues", "commit": commit, "path": CUT,
        "manifest_sha256": manifest_sha, "base_tag_commit": BASE}}}))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root, cache = tmp_path / "repo", tmp_path / "cache"
    root.mkdir()
    monkeypatch.setattr(so, "repo_root", lambda: root)
    monkeypatch.setenv(so.ENV_ROOT, str(cache))
    _pin(root, _write_cut(cache, [_record(**LABELS)]))
    return root, cache


def _row(**kw):
    exp = {"parties": ["A Corporation"], "gt_presence": json.dumps({"parties": "populated"})}
    return {"id": "DOC-1", "doc_text": TEXT, "expected_doc_class": "contract", "expected_subclass": "other",
            "expected_fields": exp} | kw


def test_apply_replaces_hub_fields_and_keeps_overrides(cache):
    rows, meta = so.apply_rows([_row(), _row(id="DOC-2")], VERSION, source_revision=BASE)
    row = rows[0]
    exp = row["expected_fields"]
    pres = json.loads(exp["gt_presence"])
    assert exp["governing_law"] == "Delaware" and exp["parties"] == ["A Corp", "B LLC"]
    assert exp["territory"] is None and pres["territory"] == "schema_documented_absence"
    assert pres["governing_law"] == "populated"
    assert row["expected_subclass"] == "other" and "subclass" not in exp  # SHF-013 owns subclass repairs
    assert row["staged_overlay"]["fields"] == ["governing_law", "parties", "territory"]
    assert row["staged_overlay"]["overrides"] == {"parties": {"hub": ["A Corporation"], "hub_presence": "populated"}}
    assert "staged_overlay" not in rows[1]
    assert meta == {"version": VERSION, "manifest_sha256": so.fingerprint(VERSION), "issues_commit": "a" * 40,
                    "rows_with_labels": 1, "fields_applied": 3, "hub_overrides": 1, "stale_rows": 0}


def test_string_labels_stay_strings_and_hub_rows_use_content_sha(cache):
    overlay, sha, problems = so.snapshot(VERSION)
    assert problems == []
    hub_row = {"document_id": "DOC-1", "content_sha256": _sha(TEXT.encode()), "gt_fields": "{}"}
    out = so.apply_staged(hub_row, overlay, version=VERSION, manifest_sha=sha)
    assert isinstance(out["gt_fields"], str) and json.loads(out["gt_fields"])["governing_law"] == "Delaware"


def test_changed_text_is_left_untouched_and_marked_stale(cache):
    rows, meta = so.apply_rows([_row(doc_text=TEXT + " amended")], VERSION)
    assert rows[0]["expected_fields"] == _row()["expected_fields"]
    assert rows[0]["staged_overlay"]["stale"] is True and meta["stale_rows"] == 1 and meta["fields_applied"] == 0


def test_refuses_bytes_that_are_not_the_pin(cache):
    _root, cache_dir = cache
    path = cache_dir / CUT / "overlay" / "contract.jsonl"
    path.write_text(path.read_text().replace("Delaware", "Nevada"))
    with pytest.raises(so.StagedOverlayError, match="not the sha256 its manifest pins"):
        so.apply_rows([_row()], VERSION)
    (cache_dir / CUT / "MANIFEST.json").write_text("{}")
    with pytest.raises(so.StagedOverlayError, match="is not the pinned"):
        so.apply_rows([_row()], VERSION)


def test_refuses_other_hub_revision_unpulled_and_unpinned(cache, tmp_path, monkeypatch):
    with pytest.raises(so.StagedOverlayError, match="delta against Hub"):
        so.apply_rows([_row()], VERSION, source_revision="e" * 40)
    monkeypatch.setenv(so.ENV_ROOT, str(tmp_path / "empty"))
    with pytest.raises(so.StagedOverlayError, match="not pulled"):
        so.apply_rows([_row()], VERSION)
    with pytest.raises(so.StagedOverlayError, match="not pinned"):
        so.pin("9.3.1-rc.1")
    with pytest.raises(so.StagedOverlayError, match="X.Y.P-rc.N"):
        so.pin("latest")


def test_dataset_spec_hashes_the_pin_and_refuses_stacked_overlays(cache):
    from mailroom_sandbox.job.spec import DatasetSpec

    spec = DatasetSpec(provider="file", local_path="x.jsonl", staged_overlay=f"v{VERSION}")
    core = spec.request_core(source_sha256="0" * 64)
    assert core["staged_overlay"] == {"version": VERSION, "manifest_sha256": so.fingerprint(VERSION)}
    assert "staged_overlay" not in DatasetSpec(provider="file", local_path="x.jsonl").request_core(
        source_sha256="0" * 64)
    with pytest.raises(ValueError, match="already contains"):
        DatasetSpec(provider="file", local_path="x.jsonl", staged_overlay=VERSION, interim_labels=True)
    with pytest.raises(ValueError, match="not pinned"):
        DatasetSpec(provider="file", local_path="x.jsonl", staged_overlay="9.3.1-rc.1")


def test_rescore_keeps_the_locked_staged_overlay(cache):
    from mailroom_sandbox.rescore import truth_spec

    lock = {"spec_core": {"dataset": {"provider": "file", "staged_overlay": {"version": VERSION}}}}
    assert truth_spec(lock, dataset_file="x.jsonl").staged_overlay == VERSION
    spec = truth_spec(lock, dataset_file="x.jsonl", overlays="all")
    assert (spec.staged_overlay, spec.interim_labels, spec.near_gold_labels) == (VERSION, False, False)
    assert truth_spec(lock, dataset_file="x.jsonl", overlays="none").staged_overlay is None


def test_pull_fetches_exactly_the_pinned_commit(cache, tmp_path):
    root, _cache = cache
    remote = tmp_path / "issues"
    sha = _write_cut(remote / "mailroom_cache", [_record(**LABELS)])
    (remote / "README.md").write_text("not fetched\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(remote)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "cut"], check=True)
    subprocess.run([*git, "config", "uploadpack.allowAnySHA1InWant", "true"], check=True)
    subprocess.run([*git, "config", "uploadpack.allowFilter", "true"], check=True)
    commit = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    _pin(root, sha, commit)
    dest_root = tmp_path / "pulled"
    dest = so.pull(VERSION, root=dest_root, remote=f"file://{remote}")
    assert dest == dest_root / CUT and (dest / "overlay" / "contract.jsonl").is_file()
    assert so.snapshot(VERSION, dest_root)[2] == []
    assert so.pull(VERSION, root=dest_root, remote=f"file://{remote}") == dest  # idempotent
