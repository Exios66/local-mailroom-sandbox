"""Fixture catalog, tiny HF slices, and optional Hub pulls."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import fixtures_dir, repo_root

MANIFEST_NAME = "manifest.csv"
HF_DATASET = "Lucius-Morningstar/docclass-merged"


def manifest_path() -> Path:
    return fixtures_dir() / MANIFEST_NAME


def load_manifest() -> list[dict[str, str]]:
    path = manifest_path()
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fixture_file(row: dict[str, str]) -> Path:
    return fixtures_dir() / row["subdir"] / row["filename"]


def parse_expected_fields(row: dict[str, str]) -> dict | None:
    raw = row.get("expected_fields") or ""
    if isinstance(raw, dict):
        return raw
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def dataset_fingerprint(rows: list[dict[str, str]]) -> str:
    blob = json.dumps(
        [(r.get("id"), r.get("filename"), r.get("expected_doc_class")) for r in rows],
        sort_keys=True,
    )
    return hashlib.md5(blob.encode()).hexdigest()[:12]


def load_hf_fixtures() -> list[dict[str, Any]]:
    path = fixtures_dir() / "hf" / "docclass_mini.jsonl"
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_legalbench_fixtures() -> list[dict[str, Any]]:
    path = fixtures_dir() / "legalbench" / "contract_qa.jsonl"
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def agent_fixture_path(agent: str) -> Path:
    return fixtures_dir() / "agents" / f"{agent}.jsonl"


def load_agent_fixtures(agent: str) -> list[dict[str, Any]]:
    return load_jsonl(agent_fixture_path(agent))


def intake_dir() -> Path:
    return fixtures_dir() / "intake"


def cache_dir() -> Path:
    path = repo_root() / "data" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pull_hf_dataset(dataset_id: str = HF_DATASET, split: str = "test", max_rows: int = 50) -> Path:
    """Download a Hub dataset slice into data/cache (network)."""
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required for Hub pulls. pip install huggingface_hub"
        ) from exc
    dest = cache_dir() / dataset_id.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    # Best-effort: try a parquet/json in the repo; fall back to datasets lib.
    try:
        from datasets import load_dataset  # type: ignore

        ds = load_dataset(dataset_id, split=split)
        out = dest / f"{split}_head.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for i, row in enumerate(ds):
                if i >= max_rows:
                    break
                fh.write(json.dumps(dict(row), default=str) + "\n")
        return out
    except Exception:
        marker = dest / "README.md"
        marker.write_text(
            f"Could not stream {dataset_id}. Place a JSONL dump here for offline use.\n",
            encoding="utf-8",
        )
        return marker
