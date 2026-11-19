#!/usr/bin/env python3
"""List OpenRouter endpoints (providers) for every model in ``config/provider_pins.yaml``.

``GET https://openrouter.ai/api/v1/models/{id}/endpoints`` is public (no key, no spend).
Prints each model's canonical slug and its providers with price, context and quantization,
so an operator can choose the ``order`` to pin. Writes nothing unless ``--write-order``
is given, which pins every model to its single cheapest provider (review before use).

    python scripts/refresh_provider_pins.py                 # report (network, read-only)
    python scripts/refresh_provider_pins.py --from-json DIR # offline: DIR/<org>__<model>.json saved responses
    python scripts/refresh_provider_pins.py --write-order   # pin cheapest provider per model
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import yaml

from mailroom_sandbox.paths import repo_root

PINS = repo_root() / "config" / "provider_pins.yaml"
URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"


def fetch(model: str, from_dir: Path | None) -> dict:
    if from_dir:
        return json.loads((from_dir / (model.replace("/", "__") + ".json")).read_text())
    req = urllib.request.Request(URL.format(model=model), headers={"User-Agent": "mailroom-sandbox"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed https URL
        return json.load(resp)


def endpoints(payload: dict) -> tuple[str | None, list[dict]]:
    data = payload.get("data") or {}
    rows = []
    for ep in data.get("endpoints") or []:
        pricing = ep.get("pricing") or {}
        rows.append({
            "provider": ep.get("provider_name") or ep.get("tag"),
            "tag": ep.get("tag"),
            "prompt_per_m": float(pricing.get("prompt") or 0) * 1e6,
            "completion_per_m": float(pricing.get("completion") or 0) * 1e6,
            "context": ep.get("context_length"),
            "quantization": ep.get("quantization"),
            "status": ep.get("status"),
        })
    rows.sort(key=lambda r: (r["prompt_per_m"] + r["completion_per_m"], str(r["provider"])))
    return data.get("id") or data.get("canonical_slug"), rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-json", type=Path)
    ap.add_argument("--write-order", action="store_true")
    args = ap.parse_args()
    doc = yaml.safe_load(PINS.read_text()) or {}
    models = doc.get("models") or {}
    for model, pin in models.items():
        try:
            canonical, rows = endpoints(fetch(model, args.from_json))
        except Exception as exc:  # noqa: BLE001 — report and continue
            print(f"{model}: lookup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        print(f"\n{model}  (canonical {canonical}; pinned order {pin.get('order') or '-'})")
        for r in rows:
            print(f"  {str(r['provider']):24} in ${r['prompt_per_m']:.3f}/M  out ${r['completion_per_m']:.3f}/M  "
                  f"ctx {r['context']}  quant {r['quantization']}  status {r['status']}")
        if args.write_order and rows:
            pin["order"] = [rows[0]["provider"]]
    if args.write_order:
        PINS.write_text(yaml.safe_dump(doc, sort_keys=False))
        print(f"\nwrote {PINS.relative_to(repo_root())}: review the header comments were dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
