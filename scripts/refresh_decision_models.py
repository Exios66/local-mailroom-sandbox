#!/usr/bin/env python3
"""Refresh ``config/decision_models.yaml``, the catalog of OpenRouter Decisions-API models.

The catalog is ``GET https://openrouter.ai/api/v1/models?output_modalities=decisions`` (no key
needed): every model that answers ``POST /api/alpha/decisions``. ``mailroom_sandbox.decision_backends
.is_decisions_model`` accepts an id only when this file lists it, so a chat model with a similar
name (``typesafe/jev-router``) is never a decision reviewer. Moving aliases (``~...``, ``...-latest``)
are left out on purpose: a tuned cutoff is tied to one pinned model version.

Prices are USD per 1M input tokens; the Decisions API bills input only.

    python scripts/refresh_decision_models.py                      # rewrite in place (network)
    python scripts/refresh_decision_models.py --check              # exit 1 if the file is stale (network)
    python scripts/refresh_decision_models.py --from-json FILE     # offline: build from a saved response
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from mailroom_sandbox.paths import repo_root

CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
HEADER = (
    "# OpenRouter Decisions-API models (POST /api/alpha/decisions): the only ids a decision reviewer or\n"
    "# extraction gate may name. Refresh with scripts/refresh_decision_models.py (--check shows drift).\n"
    "# Pinned ids only: moving aliases (~org/model-latest) are excluded, and chat models never appear here.\n"
    "# prompt is USD per 1M input tokens; the Decisions API bills input only (completion is 0).\n"
)


def is_alias(model_id: str) -> bool:
    """A moving alias (``~org/model``, ``...-latest``): never pinned, never in the catalog."""
    base = model_id.split(":", 1)[0]          # a ``:variant`` of an alias is still an alias
    return base.startswith("~") or base.endswith("-latest")


def _per_million(value: Any) -> float:
    return round(float(value) * 1_000_000, 6)


def entry_from_catalog(entry: dict[str, Any]) -> dict[str, Any]:
    """One catalog row from an OpenRouter ``/models`` entry."""
    top = entry.get("top_provider") or {}
    return {
        "canonical_slug": entry.get("canonical_slug") or entry["id"],
        "endpoints": list(entry.get("endpoints") or []),
        "context_length": entry["context_length"] if entry.get("context_length") is not None else top.get("context_length"),
        "prompt": _per_million((entry.get("pricing") or {}).get("prompt") or 0),
    }


def build(catalog: list[dict[str, Any]], *, today: str) -> dict[str, Any]:
    """The catalog document from a ``/models?output_modalities=decisions`` ``data`` list."""
    models = {}
    for entry in catalog:
        model_id = str(entry["id"])
        if is_alias(model_id):
            continue
        out = entry_from_catalog(entry)
        if "/api/alpha/decisions" not in out["endpoints"]:
            continue
        models[model_id] = out
    return {"source": CATALOG_URL, "checked": today, "unit": "USD per 1M input tokens",
            "models": dict(sorted(models.items()))}


def fetch_catalog(url: str = CATALOG_URL) -> list[dict[str, Any]]:
    if not url.startswith("https://"):
        raise ValueError(f"model catalog URL must be https: {url!r}")
    with urllib.request.urlopen(url, timeout=30) as resp:  # nosec B310 - https only, checked above
        return json.load(resp)["data"]


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Human-readable differences between two catalog documents (``checked`` is ignored)."""
    lines = []
    old_models, new_models = old.get("models") or {}, new.get("models") or {}
    for model_id in sorted(set(old_models) | set(new_models)):
        if model_id not in old_models:
            lines.append(f"added: {model_id}")
        elif model_id not in new_models:
            lines.append(f"removed: {model_id}")
        elif old_models[model_id] != new_models[model_id]:
            lines.append(f"changed: {model_id}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    parser.add_argument("--from-json", type=Path, default=None, metavar="FILE",
                        help="read a saved /models response instead of fetching it")
    args = parser.parse_args(argv)
    path = args.file or repo_root() / "config" / "decision_models.yaml"
    if args.from_json:
        data = json.loads(args.from_json.read_text(encoding="utf-8"))["data"]
    else:
        data = fetch_catalog()
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    new = build(data, today=dt.date.today().isoformat())
    changes = diff(old or {}, new)
    for line in changes:
        print(line)
    if args.check:
        return 1 if changes else 0
    if changes or not path.exists():
        path.write_text(HEADER + yaml.safe_dump(new, sort_keys=False), encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
