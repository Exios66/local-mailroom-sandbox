#!/usr/bin/env python3
"""Refresh ``config/api_prices.yaml`` from OpenRouter's public model catalog.

Every model listed in the file is looked up in ``GET https://openrouter.ai/api/v1/models``
(no key needed) and its full price sheet is rewritten: base and long-prompt tiers
(``pricing.overrides``), input-cache read/write, context length and max completion tokens.
Prices are stored in USD per 1M tokens. ``--add MODEL`` adds a model to the list.

    python scripts/refresh_api_prices.py            # rewrite in place
    python scripts/refresh_api_prices.py --check    # exit 1 if the file is stale
    python scripts/refresh_api_prices.py --add qwen/qwen3.7-flash

Each row is priced from its OpenRouter ``canonical_slug`` (the dated id that is billed).
A public alias uses that slug's catalog row when the slug is listed on its own.
Decisions-API ids are read from the decisions catalog and priced the same way.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

import yaml

from mailroom_sandbox.decision_backends import is_decisions_model
from mailroom_sandbox.paths import repo_root

CATALOG_URL = "https://openrouter.ai/api/v1/models"
DECISIONS_CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
_FIELDS = {"prompt": "prompt", "completion": "completion",
           "input_cache_read": "cache_read", "input_cache_write": "cache_write"}


def _per_million(value) -> float:
    return round(float(value) * 1_000_000, 6)


_WINDOW_KEYS = ("utc_days", "utc_start", "utc_end")


def sheet_from_catalog(entry: dict) -> dict:
    """One ``config/api_prices.yaml`` model row from an OpenRouter ``/models`` entry.

    ``pricing.overrides`` holds two kinds of entry. One with ``min_prompt_tokens`` is a
    long-prompt tier. One with ``utc_days`` / ``utc_start`` / ``utc_end`` is a time-of-day
    window, not a tier: reading it as one wrote several ``min_prompt_tokens: 0`` tiers with
    different prices. Cost caps cannot know when a call lands, so each field of every tier
    takes the highest price any window charges, and the row records how many windows exist.
    """
    pricing = entry.get("pricing") or {}
    overrides = list(pricing.get("overrides") or [])
    windows = [o for o in overrides if any(k in o for k in _WINDOW_KEYS)]
    lengths = [o for o in overrides if o not in windows]
    tiers = []
    for minimum, block in [(0, pricing)] + [(int(o.get("min_prompt_tokens") or 0), o) for o in lengths]:
        tier = {"min_prompt_tokens": minimum}
        tier.update({out: _per_million(block[src]) for src, out in _FIELDS.items() if block.get(src) is not None})
        for window in windows if minimum == 0 else ():
            for src, out in _FIELDS.items():
                if window.get(src) is not None and out in tier:
                    tier[out] = max(tier[out], _per_million(window[src]))
        tiers.append(tier)
    top = entry.get("top_provider") or {}
    row = {"context_length": entry.get("context_length") or top.get("context_length"),
           "max_completion_tokens": top.get("max_completion_tokens"),
           "tiers": sorted(tiers, key=lambda t: t["min_prompt_tokens"])}
    slug = entry.get("canonical_slug") or entry.get("id")
    if slug:
        row["canonical_slug"] = slug
    if windows:
        row["time_windows"] = len(windows)
    return row


def priced_entry(catalog: dict[str, dict], model_id: str) -> dict | None:
    """The catalog row whose pricing is ``model_id``'s canonical-slug price.

    OpenRouter bills the dated ``canonical_slug``. When that slug is its own
    catalog row, that row's pricing is the genuine price. Otherwise the row
    that declares the slug carries it (the public id is an alias of that slug).
    """
    entry = catalog.get(model_id)
    if entry is None:
        entry = next((row for row in catalog.values() if row.get("canonical_slug") == model_id), None)
    if not entry:
        return None
    slug = entry.get("canonical_slug") or model_id
    return catalog.get(slug) or entry


def _fetch(url: str) -> dict[str, dict]:
    if not url.startswith("https://"):
        raise ValueError(f"model catalog URL must be https: {url!r}")
    with urllib.request.urlopen(url, timeout=30) as resp:  # nosec B310 - https only, checked above
        return {m["id"]: m for m in json.load(resp)["data"]}


def fetch_catalog(url: str = CATALOG_URL) -> dict[str, dict]:
    """Chat catalog, plus Decisions-API models so their slug prices refresh too.

    A decisions id is absent from the chat catalog. Its price lives on the
    decisions catalog row of its canonical slug.
    """
    catalog = _fetch(url)
    if url == CATALOG_URL:
        for model_id, entry in _fetch(DECISIONS_CATALOG_URL).items():
            catalog.setdefault(model_id, entry)
    return catalog


def refresh(doc: dict, catalog: dict[str, dict], *, today: str) -> tuple[dict, list[str]]:
    """The refreshed document and the ids that changed (or are missing from the catalog)."""
    changed = []
    models = dict(doc.get("models") or {})
    for model_id, row in models.items():
        entry = priced_entry(catalog, model_id)
        if entry is None:
            # A decisions id with no catalog row is kept as written, never flagged. It is an id of
            # config/decision_models.yaml (not a name suffix) or a row that carries its own endpoint.
            if not is_decisions_model(model_id) and not (row or {}).get("endpoint"):
                changed.append(f"{model_id}: not in the OpenRouter catalog")
            continue
        kept = {k: v for k, v in (row or {}).items() if k != "time_windows"}  # recomputed below
        new = {**kept, **sheet_from_catalog(entry)}
        if new != row:
            changed.append(model_id)
        models[model_id] = new
    out = {**doc, "models": models}
    if changed:
        out["checked"] = today
    return out, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    parser.add_argument("--add", action="append", default=[], metavar="MODEL")
    args = parser.parse_args()
    path = args.file or repo_root() / "config" / "api_prices.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"models": {}}
    for model_id in args.add:
        doc.setdefault("models", {}).setdefault(model_id, {})
    new, changed = refresh(doc, fetch_catalog(), today=dt.date.today().isoformat())
    for line in changed:
        print(f"changed: {line}")
    if args.check:
        return 1 if changed else 0
    if changed:
        header = "".join(l + "\n" for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("#")) if path.exists() else ""
        path.write_text(header + yaml.safe_dump(new, sort_keys=False), encoding="utf-8")
        print(f"wrote {path}")
    else:
        print("up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
