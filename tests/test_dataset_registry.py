"""Named datasets: registry resolution, ${VAR} expansion and pull provenance (DMR-116)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailroom_sandbox import dataset_registry
from mailroom_sandbox.corpus import prepare_subset
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, load_run_spec
from mailroom_sandbox.paths import config_dir

REGISTRY = """
datasets:
  demo:
    provider: file
    local_path: ${FLOOR_TEST_DIR}/demo.jsonl
    pull: {source: family-corpus, note: unit test}
"""


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the registry env at a temp file and give it a dataset dir."""
    path = tmp_path / "datasets.yaml"
    path.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.setenv("SANDBOX_DATASETS_REGISTRY", str(path))
    monkeypatch.setenv("FLOOR_TEST_DIR", str(tmp_path / "sets"))
    return path


def _rows(n: int = 2) -> list[dict]:
    """Minimal valid corpus rows."""
    return [{"id": f"d{i}", "expected_doc_class": "contract", "doc_text": f"doc {i}"} for i in range(n)]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write rows as JSONL, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_named_dataset_resolves_to_an_env_expanded_path(registry, tmp_path):
    """A registry key resolves to its ${VAR}-expanded path and pull provenance."""
    spec = DatasetSpec(name="demo")
    assert spec.local_file() == tmp_path / "sets" / "demo.jsonl"
    assert (spec.pull or {}).get("source") == "family-corpus"


def test_explicit_spec_fields_win_over_the_entry(registry, tmp_path):
    """Spec-level fields override the registry entry."""
    spec = DatasetSpec(name="demo", limit=7)
    assert spec.limit == 7
    assert spec.local_file() == tmp_path / "sets" / "demo.jsonl"


def test_env_default_and_unset_variable_are_loud(tmp_path, monkeypatch):
    """${VAR:-default} works; an unset var without a default is loud, only for the entry in use."""
    path = tmp_path / "datasets.yaml"
    path.write_text(
        "datasets:\n"
        "  a:\n    provider: file\n    local_path: ${NOPE_X:-./fallback}/x.jsonl\n"
        "  b:\n    provider: file\n    local_path: ${NOPE_Y}/y.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SANDBOX_DATASETS_REGISTRY", str(path))
    monkeypatch.delenv("NOPE_X", raising=False)
    monkeypatch.delenv("NOPE_Y", raising=False)
    assert DatasetSpec(name="a").local_path == "./fallback/x.jsonl"
    # a missing variable in another entry must not break this lane's entry
    assert dataset_registry.load()["b"]["local_path"] == "${NOPE_Y}/y.jsonl"
    with pytest.raises(ValueError, match=r"\$\{NOPE_Y\} is not set"):
        DatasetSpec(name="b")


def test_unknown_name_and_unknown_key_are_loud(registry):
    """Unknown dataset names and unknown registry keys are loud."""
    with pytest.raises(ValueError, match="is not in .*datasets.yaml"):
        DatasetSpec(name="missing")
    bad = registry.parent / "bad.yaml"
    bad.write_text("datasets:\n  x:\n    provider: file\n    path: /tmp/x.jsonl\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"unknown key\(s\) \['path'\]"):
        dataset_registry.load(bad)


@pytest.mark.parametrize(("body", "message"), [
    ("- not a mapping", "must be a mapping with a 'datasets' key"),
    ("datasets: [", "is not valid YAML"),
    ("datasets: {}", "non-empty mapping"),
    ("datasets: {x: 5}", "dataset 'x' must be a mapping"),
    ("datasets: {x: {bogus: 1}}", r"unknown key\(s\) \['bogus'\]"),
    ("datasets: {x: {local_path: ''}}", "local_path must be a non-empty string"),
    ("datasets: {x: {sha256: XYZ}}", "sha256 must be 64 lowercase hex"),
    ("datasets: {x: {pull: nope}}", "pull must be a mapping"),
])
def test_registry_shape_errors_are_loud(tmp_path, body, message):
    """Every malformed registry shape fails fast with a specific message."""
    path = tmp_path / "d.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        dataset_registry.load(path)


def test_unreadable_registry_is_loud(tmp_path):
    """A registry path that cannot be read names the file instead of raising OSError."""
    with pytest.raises(ValueError, match="not readable"):
        dataset_registry.load(tmp_path)  # a directory, not a file


def test_inline_sha_pin_must_be_a_sha256():
    """A pin that can never match a sha256 is rejected at parse time."""
    with pytest.raises(ValueError, match="64 lowercase hex"):
        DatasetSpec(local_path="x.jsonl", source_sha256="not-a-sha")


def test_named_hub_entry_supplies_the_pinned_pull(monkeypatch):
    """A Hub entry (family-corpus) resolves to the pinned repo/config/revision."""
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    monkeypatch.delenv("SANDBOX_DATASETS_REGISTRY", raising=False)
    spec = DatasetSpec(name="family-corpus")
    assert (spec.provider, spec.repo, spec.config, spec.split) == (
        "huggingface", "Lucius-Morningstar/mailroom-dataset", "ground_truth", "all"
    )
    assert spec.revision == FAMILY_HF_REVISION
    assert spec.local_path is None and not spec.is_local()


def test_sha256_pin_is_verified_and_recorded(registry, tmp_path):
    """A matching pin is recorded in provenance; a drifted file is refused."""
    source = tmp_path / "sets" / "demo.jsonl"
    _write_jsonl(source, _rows())
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    registry.write_text(
        "datasets:\n"
        "  demo:\n"
        "    provider: file\n"
        "    local_path: ${FLOOR_TEST_DIR}/demo.jsonl\n"
        f"    sha256: {sha}\n"
        "    pull: {source: family-corpus, command: unit-test}\n",
        encoding="utf-8",
    )
    prov = prepare_subset(DatasetSpec(name="demo"), tmp_path / "out.jsonl")
    assert prov["metadata"]["sha256"] == sha
    assert prov["metadata"]["name"] == "demo"
    assert prov["metadata"]["pull"] == {"source": "family-corpus", "command": "unit-test"}

    _write_jsonl(source, _rows(3))
    with pytest.raises(ValueError, match="does not match the registered pin"):
        prepare_subset(DatasetSpec(name="demo"), tmp_path / "out2.jsonl")


def test_local_spec_hash_keys_on_name_and_bytes_not_the_path(tmp_path):
    """spec_hash keys on file name + bytes, not the checkout path."""
    def spec_at(directory: Path, text: str) -> RunSpec:
        """Write one row at a path and build a matching spec."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "same.jsonl").write_text(
            json.dumps({"id": "d1", "expected_doc_class": "contract", "doc_text": text}) + "\n", encoding="utf-8"
        )
        return RunSpec(
            task="sorter",
            engine={"kind": "vllm-local", "modal": None},
            dataset=DatasetSpec(local_path=str(directory / "same.jsonl")),
        )

    a = spec_at(tmp_path / "a", "alpha")
    b = spec_at(tmp_path / "b", "alpha")
    assert a.spec_hash() == b.spec_hash(), "the same bytes in another checkout must hash the same"
    c = spec_at(tmp_path / "c", "different")
    assert a.spec_hash() != c.spec_hash()


def test_demo_run_spec_names_a_registry_dataset(monkeypatch):
    """The shipped demo spec names a registry dataset and carries no machine path."""
    from mailroom_sandbox.job.spec import spec_hash

    monkeypatch.delenv("MAILROOM_BASE_DIR", raising=False)
    monkeypatch.delenv("SANDBOX_DATASETS_REGISTRY", raising=False)
    path = config_dir() / "runs" / "pipeline-lmstudio-even50-demo.yaml"
    spec = load_run_spec(path)
    assert spec.dataset.name == "pipeline-even100-shuffled2"
    assert "/home/" not in path.read_text(encoding="utf-8"), "no machine path may live in a run spec"
    assert not Path(spec.dataset.local_path).is_absolute()
    assert spec.dataset.local_path.endswith("datasets/pipeline-even100-shuffled2.jsonl")
    assert len(spec_hash(spec)) == 64, "a missing dataset file must still hash (name only)"

    monkeypatch.setenv("MAILROOM_BASE_DIR", str(config_dir().parent / "data"))
    moved = load_run_spec(path)
    assert moved.dataset.local_path == str(config_dir().parent / "data" / "datasets" / "pipeline-even100-shuffled2.jsonl")
    assert spec_hash(moved) == spec_hash(spec), "the same dataset hashes the same under any lane root"


def test_committed_run_specs_never_embed_a_machine_path():
    """Future runs resolve data through the registry or a repo-relative path."""
    import yaml

    offenders = []
    for path in sorted((config_dir() / "runs").rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        dataset = raw.get("dataset") if isinstance(raw, dict) else None
        local = dataset.get("local_path") if isinstance(dataset, dict) else None
        if not isinstance(local, str):
            continue
        bare = local[len("file://"):] if local.startswith("file://") else local
        if not bare.startswith("${") and (Path(bare).is_absolute() or bare.startswith("~")):
            offenders.append(f"{path.name}: {local}")
    assert not offenders, "run specs must not embed a machine path (use config/datasets.yaml): " + "; ".join(offenders)


def test_tracked_registry_paths_stay_portable():
    """The tracked registry does not embed a home directory."""
    for name, entry in dataset_registry.load(config_dir() / "datasets.yaml").items():
        local = entry.get("local_path")
        if local is None:
            continue
        portable = local.startswith("${") or not (Path(local).is_absolute() or local.startswith("~"))
        assert portable, (
            f"dataset {name!r}: {local} — the tracked registry must resolve through ${{VAR}}, not a home directory"
        )
