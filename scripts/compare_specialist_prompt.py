#!/usr/bin/env python3
"""Compare a specialist prompt run with its reference run on the same documents (no model call).

Pairs the two runs' items by document id and reports, from the dojo scores both runs stored:
mean extraction score of each, the paired mean difference, wins / ties / losses, parse errors and
input tokens per document. The verdict applies the specialist-condensed adoption rule from
``config/prompts/specialist_condensed_lineage.yaml``: adopt when the candidate's mean is not lower
by more than ``max_mean_drop`` and it adds no parse errors. Writes
``reports/specialist-condensed/<candidate>.compare.json``.

    python scripts/compare_specialist_prompt.py --reference extraction-gate-specialist-correspondence-qwen \\
        --candidate specialist-condensed-v1-correspondence-qwen-ab
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import yaml

from mailroom_sandbox.paths import repo_root


def _items(root: Path, run_id: str) -> dict[str, dict]:
    path = root / "data" / "runtime" / "runs" / run_id / "items.jsonl"
    with path.open(encoding="utf-8", newline="\n") as handle:
        rows = [json.loads(line) for line in handle.read().split("\n") if line.strip()]
    return {str(r["item_id"]): r for r in rows}


def _score(item: dict) -> float | None:
    value = (item.get("score") or {}).get("overall_extraction_score")
    return float(value) if isinstance(value, (int, float)) else None


def _parse_error(item: dict) -> bool:
    return bool((item.get("pred") or {}).get("_parse_error") or (item.get("score") or {}).get("parse_error")
                or not item.get("ok") or item.get("error"))


def compare(reference: dict[str, dict], candidate: dict[str, dict], *, max_mean_drop: float) -> dict:
    shared = sorted(set(reference) & set(candidate))
    pairs = [(_score(reference[d]) or 0.0, _score(candidate[d]) or 0.0) for d in shared]
    deltas = [c - r for r, c in pairs]
    ref_err = sum(_parse_error(reference[d]) for d in shared)
    cand_err = sum(_parse_error(candidate[d]) for d in shared)
    tok = lambda items: statistics.mean(int(items[d].get("prompt_tokens") or 0) for d in shared) if shared else 0  # noqa: E731
    ref_mean = statistics.mean(r for r, _ in pairs) if pairs else 0.0
    cand_mean = statistics.mean(c for _, c in pairs) if pairs else 0.0
    adopt = bool(shared) and cand_mean >= ref_mean - max_mean_drop and cand_err <= ref_err
    return {
        "documents": len(shared),
        "reference_mean": round(ref_mean, 4), "candidate_mean": round(cand_mean, 4),
        "mean_delta": round(statistics.mean(deltas), 4) if deltas else 0.0,
        "wins": sum(d > 1e-9 for d in deltas), "ties": sum(abs(d) <= 1e-9 for d in deltas),
        "losses": sum(d < -1e-9 for d in deltas),
        "reference_parse_errors": ref_err, "candidate_parse_errors": cand_err,
        "reference_prompt_tokens_per_doc": round(tok(reference)), "candidate_prompt_tokens_per_doc": round(tok(candidate)),
        "max_mean_drop": max_mean_drop,
        "verdict": "adopt" if adopt else "reject",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    root = repo_root()
    lineage = yaml.safe_load((root / "config" / "prompts" / "specialist_condensed_lineage.yaml").read_text(encoding="utf-8"))
    result = {"reference": args.reference, "candidate": args.candidate,
              **compare(_items(root, args.reference), _items(root, args.candidate),
                        max_mean_drop=float(lineage.get("max_mean_drop", 0.02)))}
    out = root / "reports" / "specialist-condensed" / f"{args.candidate}.compare.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
