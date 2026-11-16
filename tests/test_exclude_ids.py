"""dataset.exclude_ids_file: tuning documents are dropped before the stratified draw."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailroom_sandbox.corpus import prepare_subset, read_id_list, select_rows
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, core_hash, spec_core

CLASSES = ("contract", "correspondence")


def _rows(per_class: int = 15) -> list[dict]:
    """Synthetic rows: ``per_class`` documents for each of two classes."""
    return [
        {
            "id": f"{cls}-{i:02d}",
            "filename": f"{cls}-{i:02d}.txt",
            "expected_doc_class": cls,
            "expected_subclass": "x",
            "doc_text": f"{cls} {i}",
        }
        for cls in CLASSES
        for i in range(per_class)
    ]


def _buckets(count: int) -> dict:
    return {"buckets": [{"doc_class": cls, "count": count} for cls in CLASSES]}


EXCLUDED = {"contract-00", "contract-03", "contract-07", "correspondence-02", "correspondence-11"}


def _draw(count: int, *, exclude: set[str] | None = EXCLUDED, seed: int = 7) -> list[dict]:
    return select_rows(
        _rows(), strata=_buckets(count), sample_seed=seed, limit=None, exclude_ids=exclude
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _spec(tmp_path: Path, exclude_file: Path | str | None, **dataset) -> RunSpec:
    source = tmp_path / "rows.jsonl"
    if not source.exists():
        _write_jsonl(source, _rows())
    return RunSpec(
        run_id="exclude-ids",
        task="sorter",
        engine={"kind": "vllm-local", "modal": None},
        dataset=DatasetSpec(
            local_path=str(source),
            exclude_ids_file=str(exclude_file) if exclude_file is not None else None,
            **dataset,
        ),
        trace={"sink": "none"},
    )


def test_excluded_ids_are_never_drawn():
    chosen = _draw(10)
    assert len(chosen) == 20
    assert {r["id"] for r in chosen}.isdisjoint(EXCLUDED)


def test_draws_stay_nested_under_exclusion():
    small, large = _draw(4), _draw(9)
    for cls in CLASSES:
        small_ids = {r["id"] for r in small if r["expected_doc_class"] == cls}
        large_ids = {r["id"] for r in large if r["expected_doc_class"] == cls}
        assert len(small_ids) == 4 and len(large_ids) == 9
        assert small_ids < large_ids


def test_exclusion_does_not_change_the_default_draw():
    """No exclusion set (None or empty) draws exactly what the legacy call drew."""
    legacy = select_rows(_rows(), strata=_buckets(6), sample_seed=7, limit=None)
    assert legacy == _draw(6, exclude=None) == _draw(6, exclude=set())


def test_read_id_list_skips_comments_and_blanks(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("# tuning ids\nabc\n\n  def  # trailing note\n#skip\nabc\n", encoding="utf-8")
    assert read_id_list(path) == ["abc", "def", "abc"]


def test_exclude_file_is_hashed_only_when_set(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("contract-00\n", encoding="utf-8")
    b.write_text("contract-01\n", encoding="utf-8")
    core_a = spec_core(_spec(tmp_path, a))
    core_b = spec_core(_spec(tmp_path, b))
    assert core_a["dataset"]["exclude_ids_sha256"] != core_b["dataset"]["exclude_ids_sha256"]
    assert core_hash(core_a) != core_hash(core_b)
    assert "exclude_ids_sha256" not in spec_core(_spec(tmp_path, None))["dataset"]


def test_exclude_file_path_is_not_hashed(tmp_path):
    """The identity is the file's bytes, not where it lives."""
    a, b = tmp_path / "a.txt", tmp_path / "sub" / "b.txt"
    b.parent.mkdir()
    a.write_text("contract-00\n", encoding="utf-8")
    b.write_text("contract-00\n", encoding="utf-8")
    assert core_hash(spec_core(_spec(tmp_path, a))) == core_hash(spec_core(_spec(tmp_path, b)))


def test_relative_exclude_file_resolves_against_repo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    (root / "config" / "tuning.txt").write_text("contract-00\n", encoding="utf-8")
    monkeypatch.setenv("SANDBOX_ROOT", str(root))
    spec = _spec(tmp_path, "config/tuning.txt")
    assert spec.dataset.exclude_ids_path() == root / "config" / "tuning.txt"
    assert spec_core(spec)["dataset"]["exclude_ids_sha256"]


def test_prepare_subset_never_draws_excluded_ids(tmp_path):
    ids = tmp_path / "ids.txt"
    ids.write_text("\n".join(sorted(EXCLUDED)) + "\n", encoding="utf-8")
    spec = _spec(tmp_path, ids, strata=_buckets(10), sample_seed=7)
    prov = prepare_subset(spec.dataset, tmp_path / "out.jsonl")
    drawn = {json.loads(line)["id"] for line in (tmp_path / "out.jsonl").read_text().splitlines()}
    assert prov["rows"] == 20 and drawn.isdisjoint(EXCLUDED)
    assert {k: prov["excluded"][k] for k in ("listed", "matched")} == {"listed": 5, "matched": 5}
    assert prov["excluded"]["sha256"] == __import__("hashlib").sha256(ids.read_bytes()).hexdigest()


def test_unknown_excluded_ids_are_ignored_and_counted(tmp_path, job_data_dir):
    from mailroom_sandbox.job import preflight

    ids = tmp_path / "ids.txt"
    ids.write_text("contract-00\ncontract-01\nnot-in-corpus\n# note\nalso-missing\n", encoding="utf-8")
    spec = _spec(tmp_path, ids, strata=_buckets(10), sample_seed=7)
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    dataset_check = next(c for c in report["checks"] if c["name"] == "dataset")
    assert "excluded=2/4" in dataset_check["detail"]


def test_dataset_detail_omits_excluded_when_unset(tmp_path, job_data_dir):
    from mailroom_sandbox.job import preflight

    report = preflight.preflight(_spec(tmp_path, None), offline=True)
    dataset_check = next(c for c in report["checks"] if c["name"] == "dataset")
    assert "excluded" not in dataset_check["detail"]


def test_missing_exclude_file_fails_preflight(tmp_path, job_data_dir):
    from mailroom_sandbox.job import preflight

    missing = tmp_path / "nope.txt"
    spec = _spec(tmp_path, missing)
    with pytest.raises(ValueError, match="exclude_ids_file"):
        spec_core(spec)
    with pytest.raises(ValueError, match="exclude_ids_file"):
        prepare_subset(spec.dataset, tmp_path / "out.jsonl")
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "failed"
    dataset_check = next(c for c in report["checks"] if c["name"] == "dataset")
    assert not dataset_check["ok"] and "exclude_ids_file" in dataset_check["detail"]


def test_lock_hashes_the_exclusion_bytes_the_draw_used(tmp_path, job_data_dir, monkeypatch):
    """An edit to the exclusion file after preparation cannot reach the lock: one snapshot feeds both."""
    import hashlib

    from mailroom_sandbox.job import checkpoint, preflight

    ids = tmp_path / "ids.txt"
    original = "contract-00\n"
    ids.write_text(original, encoding="utf-8")
    spec = _spec(tmp_path, ids, strata=_buckets(10), sample_seed=7)
    real_prepare = preflight.prepare_subset

    def prepare_then_edit(dataset, dest):
        prov = real_prepare(dataset, dest)
        ids.write_text(original + "contract-01\n", encoding="utf-8")  # edited mid-preflight
        return prov

    monkeypatch.setattr(preflight, "prepare_subset", prepare_then_edit)
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    lock = json.loads(checkpoint.RunStore(preflight.run_dir(spec.run_id)).lock_path.read_text(encoding="utf-8"))
    frozen = lock["spec_core"]["dataset"]["exclude_ids_sha256"]
    assert frozen == hashlib.sha256(original.encode()).hexdigest()
    assert frozen != spec_core(spec)["dataset"]["exclude_ids_sha256"]  # the file on disk moved on
