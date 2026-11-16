"""Production slice configs: nested, held-out, r3 settings, and Modal job-host twins."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox.corpus import prepare_subset, read_id_list
from mailroom_sandbox.job.spec import load_run_spec

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "config" / "runs" / "production"
R3 = ROOT / "config" / "runs" / "pipeline-qwen-flash-25-fit-r3.yaml"
EXCLUDED = ROOT / "config" / "production" / "excluded-ids.txt"
LINEAGE = ROOT / "config" / "prompts" / "specialist_condensed_lineage.yaml"

SIZES = ("0100", "0250", "0500")
SLICES = [f"slice-{s}" for s in SIZES] + ["slice-full"]
TWINS = [f"slice-{s}-modal-host" for s in SIZES]
CACHE_REL = "data/cache/Lucius-Morningstar__mailroom-dataset__bc9eab280044/ground_truth_all.jsonl"
# Requested per-class counts (contract, corporate, correspondence, insurance, merger).
COUNTS = {
    "0100": (18, 14, 30, 33, 5),
    "0250": (45, 34, 76, 83, 12),
    "0500": (91, 68, 151, 167, 23),
}
CLASSES = ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement")
CAPS = {"0100": 2, "0250": 5, "0500": 10, "full": 70}
WALL = {"0100": 7200, "0250": 10800, "0500": 14400, "full": 86400}


def _load(name: str):
    return load_run_spec(PROD / f"{name}.yaml")


def _raw(name: str) -> dict:
    return yaml.safe_load((PROD / f"{name}.yaml").read_text(encoding="utf-8"))


def _cache_path() -> Path | None:
    env = os.environ.get("SANDBOX_DATASET_CACHE")
    path = Path(env).expanduser() if env else ROOT / CACHE_REL
    return path if path.is_file() else None


def _draw(name: str, tmp_path: Path, exclude_file: Path | None = None) -> list[dict]:
    cache = _cache_path()
    if cache is None:
        pytest.skip("cached ground_truth_all.jsonl not present (set SANDBOX_DATASET_CACHE)")
    update = {"provider": "file", "local_path": str(cache), "interim_labels": False}
    if exclude_file is not None:
        update["exclude_ids_file"] = str(exclude_file)
    ds = _load(name).dataset.model_copy(update=update)
    dest = tmp_path / f"{name}.jsonl"
    prepare_subset(ds, dest)
    with dest.open(encoding="utf-8") as fh:  # not splitlines(): doc_text may hold U+2028
        return [json.loads(line) for line in fh if line.strip()]


def test_slices_validate_and_share_settings():
    r3 = load_run_spec(R3)
    frontrunners = {a: row["frontrunner"] for a, row in yaml.safe_load(LINEAGE.read_text())["agents"].items()}
    for name in SLICES + TWINS:
        spec = _load(name)
        size = name.split("-")[1]
        assert spec.run_id == f"production-{name}"
        assert spec.task == "pipeline"
        assert spec.job.blind_routing is True
        assert spec.job.mock is False
        assert spec.dataset.interim_labels is True
        assert spec.dataset.require_task_gt is True
        assert spec.dataset.revision == r3.dataset.revision
        assert spec.dataset.repo == r3.dataset.repo and spec.dataset.config == "ground_truth"
        assert spec.dataset.sample_seed == 3302
        assert spec.dataset.exclude_ids_file == "config/production/excluded-ids.txt"
        assert spec.dataset.draw == "ranked"
        # r3's prompts, with every condensed specialist at its adopted lineage frontrunner
        # (correspondence moved to v3 after its paired A/B, #306).
        assert spec.prompt["default"] == r3.prompt["default"]
        assert set(spec.prompt["agents"]) == set(r3.prompt["agents"])
        for agent, entry in spec.prompt["agents"].items():
            assert entry == {**r3.prompt["agents"][agent], "file": frontrunners.get(agent, entry["file"])}, agent
            assert entry["file"] == frontrunners.get(agent, r3.prompt["agents"][agent]["file"]), agent
        assert spec.confidence == r3.confidence
        assert spec.reviewer == r3.reviewer
        assert spec.agent_routes == r3.agent_routes
        assert spec.agent_knobs == r3.agent_knobs
        assert spec.engine.kind == "openrouter" and spec.engine.model == r3.engine.model
        assert (spec.trace.sink, spec.trace.environment) == (r3.trace.sink, r3.trace.environment)
        assert spec.job.api_cost_cap_usd == CAPS[size]
        assert spec.job.max_wall_seconds == WALL[size]
        assert spec.job.cost_cap_usd is not None
        assert spec.job.concurrency == 10


def test_slice_strata_match_the_plan():
    for size, counts in COUNTS.items():
        spec = _load(f"slice-{size}")
        buckets = {b["doc_class"]: b["count"] for b in spec.dataset.strata["buckets"]}
        assert buckets == dict(zip(CLASSES, counts, strict=True))
        assert spec.dataset.limit is None
    full = _load("slice-full")
    assert full.dataset.strata is None and full.dataset.limit is None


def test_slices_nest(tmp_path):
    ids = {size: {r["id"] for r in _draw(f"slice-{size}", tmp_path)} for size in SIZES}
    assert ids["0100"] < ids["0250"] < ids["0500"]
    for size, counts in COUNTS.items():
        assert len(ids[size]) == sum(counts)


def test_slices_hold_out_tuning_documents(tmp_path):
    excluded = set(read_id_list(EXCLUDED))
    assert excluded
    for size in SIZES:
        drawn = {r["id"] for r in _draw(f"slice-{size}", tmp_path)}
        assert not drawn & excluded


def test_modal_twins_differ_only_in_mode_and_id():
    for size in SIZES:
        base, twin = _raw(f"slice-{size}"), _raw(f"slice-{size}-modal-host")
        assert twin["run_id"] == f"production-slice-{size}-modal-host"
        assert twin["job"]["mode"] == "modal"
        assert twin["engine"]["kind"] == "openrouter"
        for doc in (base, twin):
            doc.pop("run_id")
            doc["job"].pop("mode")
        assert base == twin


def test_slices_survive_an_exclusion_list_update(tmp_path):
    """Adding tuning ids that a slice did not draw leaves that slice and the nesting intact (review C1)."""
    before = {size: {r["id"] for r in _draw(f"slice-{size}", tmp_path)} for size in SIZES}
    full = {r["id"] for r in _draw("slice-full", tmp_path)}
    new_tuning = sorted(full - before["0500"])[:60]
    grown = tmp_path / "excluded-grown.txt"
    grown.write_text(EXCLUDED.read_text(encoding="utf-8") + "\n".join(new_tuning) + "\n", encoding="utf-8")
    after = {size: {r["id"] for r in _draw(f"slice-{size}", tmp_path, grown)} for size in SIZES}
    assert after == before
