"""scripts/export_mailroom_cache.py: SemVer layout, full-label-set validation, immutability, --check."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

FILLER = 3  # unchanged rows added next to the accepted corrections
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_mailroom_cache.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("export_mailroom_cache", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _csv(path: Path, mod, *, extra_repair: bool = False, drop_repair: bool = False) -> Path:
    accepted = mod.accepted_subclass_corrections()
    rows = []
    for i, (doc_id, (hub, fixed)) in enumerate(sorted(accepted.items())):
        new = hub if (drop_repair and i == 0) else fixed
        rows.append({"document_id": doc_id, "split": "train", "doc_class": "x", "subclass": new,
                     "subclass_hub_v9_3": hub, "subclass_changed": str(new != hub)})
    for i in range(FILLER):
        rows.append({"document_id": f"DOC-{i:04d}", "split": "test", "doc_class": "y", "subclass": "a",
                     "subclass_hub_v9_3": "a", "subclass_changed": "False"})
    if extra_repair:
        rows[-1].update(subclass="b", subclass_changed="True")
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def small(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "FAMILY_CORPUS_SIZE", len(mod.accepted_subclass_corrections()) + FILLER)
    return tmp_path


@pytest.mark.parametrize("bad", ["9.3.1", "9.4.1-rc.1", "9.3.0-rc.1", "v9.3.x-rc.1"])
def test_parse_version_rejects(mod, bad):
    with pytest.raises(mod.CacheError):
        mod.parse_version(bad)


def test_parse_version_accepts_prerelease_on_current_tag(mod):
    major, minor = (int(x) for x in mod.FAMILY_HF_TAG.removeprefix("v").split("."))
    assert mod.parse_version(f"v{major}.{minor}.1-rc.2") == (major, minor, 1, "rc.2")


def test_full_labels_must_match_accepted_corrections(mod, small):
    summary = mod.validate_full_labels(_csv(small / "ok.csv", mod))
    assert {r["document_id"] for r in summary["subclass_repairs"]} == set(mod.accepted_subclass_corrections())
    for kw in ({"extra_repair": True}, {"drop_repair": True}):
        with pytest.raises(mod.CacheError, match="do not match"):
            mod.validate_full_labels(_csv(small / "bad.csv", mod, **kw))


def test_export_layout_check_and_immutability(mod, small):
    src = _csv(small / "123abcde-labels.csv", mod)
    out = small / "mailroom_cache"
    version = mod.FAMILY_HF_TAG.removeprefix("v") + ".1-rc.1"
    mod.export(out, version, src, check=False)

    pre = out / f"{mod.FAMILY_HF_TAG}.0" / "pre-release" / f"v{version}"
    manifest = json.loads((pre / "MANIFEST.json").read_text())
    assert manifest["channel"] == "pre-release"
    assert manifest["base_hf"]["tag_commit"] == mod.FAMILY_HF_REVISION
    assert manifest["full_label_set"]["original_filename"] == "labels.csv"
    for rel, entry in manifest["files"].items():
        assert mod._sha256(pre / rel) == entry["sha256"], rel
    for rel in mod.LABEL_SETS.values():
        assert (pre / rel / "MANIFEST.json").exists() or rel == "repairs/review"
    assert (out / f"{mod.FAMILY_HF_TAG}.0" / "hf-revision" / "MANIFEST.json").exists()
    registry = json.loads((out / "REGISTRY.json").read_text())
    assert [v["channel"] for v in registry["versions"]].count("pre-release") == 1

    assert mod.export(out, version, None, check=True) == []  # re-check from the cached CSV
    (out / "README.md").write_text("edited\n")
    assert mod.export(out, version, None, check=True) == ["README.md"]

    csv_path = next((pre / mod.FULL_SET_DIR).glob("*.csv"))
    csv_path.write_bytes(csv_path.read_bytes().replace(b"DOC-0000", b"DOC-9999"))
    with pytest.raises(mod.CacheError, match="immutable"):
        mod.export(out, version, src, check=False)


def test_foreign_output_is_preserved(mod, small):
    out = small / "foreign"
    out.mkdir()
    foreign = out / "important.txt"
    foreign.write_text("keep")
    with pytest.raises(mod.CacheError, match="valid cache registry"):
        mod.export(out, "9.3.1-rc.1", None, check=False)
    assert foreign.read_text() == "keep"


def test_export_refuses_unmanaged_files_in_an_owned_cache(mod, small):
    source = _csv(small / "labels.csv", mod)
    out = small / "mailroom_cache"
    version = mod.FAMILY_HF_TAG.removeprefix("v") + ".1-rc.1"
    mod.export(out, version, source, check=False)
    extra = out / "operator-note.txt"
    extra.write_text("keep")
    with pytest.raises(mod.CacheError, match="unmanaged"):
        mod.export(out, version, None, check=False)
    assert extra.read_text() == "keep"


def test_concurrent_export_is_refused_without_losing_prereleases(mod, small, monkeypatch):
    source = _csv(small / "labels.csv", mod)
    out = small / "mailroom_cache"
    base = mod.FAMILY_HF_TAG.removeprefix("v") + ".1-rc."
    build = mod.build_prerelease

    def build_while_another_export_attempts(*args):
        with pytest.raises(mod.CacheError, match="already in progress"):
            mod.export(out, base + "2", source, check=False)
        return build(*args)

    monkeypatch.setattr(mod, "build_prerelease", build_while_another_export_attempts)
    mod.export(out, base + "1", source, check=False)
    first = out / f"{mod.FAMILY_HF_TAG}.0" / "pre-release" / f"v{base}1"
    before = {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    monkeypatch.setattr(mod, "build_prerelease", build)
    mod.export(out, base + "2", source, check=False)
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == before
    registry = json.loads((out / "REGISTRY.json").read_text())
    assert {v["version"] for v in registry["versions"] if v["channel"] == "pre-release"} == {
        base + "1", base + "2",
    }


def test_export_copy_failure_preserves_the_cache(mod, small, monkeypatch):
    source = _csv(small / "labels.csv", mod)
    out = small / "mailroom_cache"
    version = mod.FAMILY_HF_TAG.removeprefix("v") + ".1-rc.1"
    mod.export(out, version, source, check=False)
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    copytree = mod.shutil.copytree

    def fail_replacement(src, dest, *args, **kwargs):
        if Path(dest).name == "new":
            raise OSError("disk full during publication")
        return copytree(src, dest, *args, **kwargs)

    monkeypatch.setattr(mod.shutil, "copytree", fail_replacement)
    with pytest.raises(OSError, match="disk full"):
        mod.export(out, version, None, check=False)
    assert {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()} == before


def test_cache_copy_failure_preserves_previous_generation(mod, small, monkeypatch):
    out, stage = small / "mailroom_cache", small / "stage"
    out.mkdir()
    stage.mkdir()
    (out / "REGISTRY.json").write_text(json.dumps({"schema": mod.SCHEMA, "dataset": mod.HF_DEFAULT_REPO}))
    previous = out / "important.txt"
    previous.write_text("previous generation")

    def fail_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod.shutil, "copytree", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        mod._publish_cache(stage, out)
    assert previous.read_text() == "previous generation"


def test_cache_swap_failure_restores_previous_generation(mod, small, monkeypatch):
    out, stage = small / "mailroom_cache", small / "stage"
    out.mkdir()
    stage.mkdir()
    (out / "REGISTRY.json").write_text(json.dumps({"schema": mod.SCHEMA, "dataset": mod.HF_DEFAULT_REPO}))
    (out / "previous.txt").write_text("keep")
    rename = Path.rename

    def fail_new(self, target):
        if self.name == "new":
            raise OSError("publication failed")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_new)
    with pytest.raises(OSError, match="publication failed"):
        mod._publish_cache(stage, out)
    assert (out / "previous.txt").read_text() == "keep"


def test_failed_rollback_retains_recovery_directory(mod, small, monkeypatch):
    out, stage = small / "mailroom_cache", small / "stage"
    out.mkdir()
    stage.mkdir()
    (out / "REGISTRY.json").write_text(json.dumps({"schema": mod.SCHEMA, "dataset": mod.HF_DEFAULT_REPO}))
    (out / "previous.txt").write_text("keep")
    rename = Path.rename

    def fail_publication_and_rollback(self, target):
        if self.name in {"new", "previous"}:
            raise OSError("rename failed")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_publication_and_rollback)
    with pytest.raises(OSError, match="rename failed") as failure:
        mod._publish_cache(stage, out)
    (recovery,) = small.glob(".mailroom-cache-*/previous/previous.txt")
    assert recovery.read_text() == "keep"
    assert "retained for recovery" in " ".join(failure.value.__notes__)
