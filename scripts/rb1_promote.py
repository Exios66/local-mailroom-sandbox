#!/usr/bin/env python3
"""Verdicts for the rb1 specialist prompt A/Bs (plan finding 16, runbook R41; docs/rb1-prompt-promotion.md).

Reads the scored run stores of each candidate / frontrunner pair at one sequential look
(``data/runtime/runs/rb1-r41-<lineage>-<arm>-look<N>``), checks the pair is a clean A/B (same
locked documents, specs equal except the prompt, both runs done, neither a mock unless
``--allow-mock``), and applies the promotion rule:

* per-document field F1 (``score.extraction_f1``), paired sign-flip permutation test
  (``experiment_stats.paired_permutation``), Holm-adjusted across the four A/Bs of the look
  (``experiment_stats.holm``; a pair with no result enters the family at p = 1);
* the sequential keep rule (``experiment_stats.keep_at_look``) on the paired z of the same
  differences: look 1 only screens; look 2 keeps at z >= 2.45;
* hallucination does not rise: the candidate's pooled hallucination rate (hallucinated / predicted
  items over every field audit of every document) is not above the frontrunner's.

PROMOTE needs all of: look 2, keep-rule ``keep``, Holm-adjusted p < alpha, a positive mean gain,
and no rise in hallucination. The script only prints (and, when the campaign tree exists, records)
the verdict. It never edits a default on its own: ``--apply --initials XX`` is the human step that
moves a promoted candidate to frontrunner in ``config/prompts/specialist_condensed_lineage.yaml``.

    python scripts/rb1_promote.py --look 1
    python scripts/rb1_promote.py --look 2
    python scripts/rb1_promote.py --look 2 --apply --initials JB
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LINEAGE = ROOT / "config" / "prompts" / "specialist_condensed_lineage.yaml"
EXPERIMENT_KEY = "rb1-r41"

#: agent -> (lineage short name, frontrunner stem, frontrunner arm, candidate stem, candidate arm)
PAIRS: dict[str, tuple[str, str, str, str, str]] = {
    "corporate_records_specialist": ("corporate", "corporate_records_specialist_condensed_v1", "condensed-v1",
                                     "corporate_records_specialist_condensed_v2", "condensed-v2"),
    "correspondence_specialist": ("correspondence", "correspondence_specialist_condensed_v3", "condensed-v3",
                                  "correspondence_specialist_condensed_v4", "condensed-v4"),
    "contracts_specialist": ("contracts", "contracts_specialist_v33_simplified", "v33-simplified",
                             "contracts_specialist_condensed_v1", "condensed-v1"),
    "insurance_claims_specialist": ("insurance", "insurance_claims_specialist_condensed_v3", "condensed-v3",
                                    "insurance_claims_specialist_condensed_v5", "condensed-v5"),
}
#: Lock keys that may differ inside a clean A/B pair (identity, timestamps, the prompt itself, trace tags).
_FREE = {"run_id", "created_at", "generation_id", "spec_hash", "prompt", "prompt_text_sha", "trace"}


def run_ids(agent: str, look: int) -> tuple[str, str]:
    lin, _, farm, _, carm = PAIRS[agent]
    return f"{EXPERIMENT_KEY}-{lin}-{farm}-look{look}", f"{EXPERIMENT_KEY}-{lin}-{carm}-look{look}"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_run(runs_dir: Path, run_id: str) -> dict[str, Any] | None:
    d = runs_dir / run_id
    lock = _read_json(d / "spec.lock.json")
    if lock is None:
        return None
    items = []
    path = d / "items.jsonl"
    if path.is_file():
        with path.open(encoding="utf-8") as fh:
            items = [json.loads(line) for line in fh if line.strip()]
    rows = []
    dpath = d / "dataset.jsonl"
    if dpath.is_file():
        with dpath.open(encoding="utf-8") as fh:
            rows = [json.loads(line).get("id") for line in fh if line.strip()]
    return {"run_id": run_id, "lock": lock, "checkpoint": _read_json(d / "checkpoint.json") or {},
            "items": {str(i.get("item_id")): i for i in items}, "ids": rows}


def _core_without_prompt(lock: dict) -> dict:
    core = dict(lock.get("spec_core") or {})
    for key in _FREE:
        core.pop(key, None)
    return core


def pair_problems(base: dict, cand: dict, *, allow_mock: bool) -> list[str]:
    """Why two runs are not a clean, finished A/B (empty when they are)."""
    out = []
    for run in (base, cand):
        if (run["checkpoint"].get("state")) != "done":
            out.append(f"{run['run_id']}: state {run['checkpoint'].get('state')!r}, not done")
        if (run["lock"].get("job") or {}).get("mock", True) and not allow_mock:
            out.append(f"{run['run_id']}: a mock run (simulated output is never evidence)")
    if base["lock"].get("dataset", {}).get("sha256") != cand["lock"].get("dataset", {}).get("sha256"):
        out.append("the arms locked different documents (dataset.sha256 differs)")
    if base["ids"] != cand["ids"]:
        out.append("the arms' locked document ids differ")
    if _core_without_prompt(base["lock"]) != _core_without_prompt(cand["lock"]):
        out.append("the arms' specs differ beyond the prompt")
    return out


def _f1(item: dict | None) -> float:
    """Per-document field F1; a failed or missing document scores 0 (it extracted nothing usable)."""
    if not item or not item.get("ok"):
        return 0.0
    value = (item.get("score") or {}).get("extraction_f1")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def _hallucination(items: dict[str, dict], ids: list[str]) -> tuple[int, int]:
    """(hallucinated, predicted) items pooled over every field audit of every document."""
    bad = total = 0
    for doc in ids:
        audit = (((items.get(doc) or {}).get("score") or {}).get("fields") or {}).get("entity_list_audit") or {}
        for row in audit.values():
            if isinstance(row, dict):
                bad += int(row.get("hallucinated") or 0)
                total += int(row.get("n_predicted") or 0)
    return bad, total


def paired_z(diffs: list[float]) -> float:
    n = len(diffs)
    if n < 2:
        return 0.0
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var == 0:
        return 0.0 if mean == 0 else math.copysign(math.inf, mean)
    return mean / math.sqrt(var / n)


def compare(base: dict, cand: dict, *, n_perm: int, seed: int) -> dict[str, Any]:
    from mailroom_sandbox.experiment_stats import paired_permutation

    ids = base["ids"]
    b = [_f1(base["items"].get(i)) for i in ids]
    c = [_f1(cand["items"].get(i)) for i in ids]
    gain, p = paired_permutation(b, c, n_perm=n_perm, seed=seed)
    hb, tb = _hallucination(base["items"], ids)
    hc, tc = _hallucination(cand["items"], ids)
    rate_b = hb / tb if tb else 0.0
    rate_c = hc / tc if tc else 0.0
    failed = {r["run_id"]: sum(1 for i in ids if not (r["items"].get(i) or {}).get("ok")) for r in (base, cand)}
    return {"n": len(ids), "mean_f1_frontrunner": sum(b) / len(b) if b else 0.0,
            "mean_f1_candidate": sum(c) / len(c) if c else 0.0, "gain": gain, "p": p,
            "z": paired_z([y - x for x, y in zip(b, c)]),
            "wins": sum(y > x for x, y in zip(b, c)), "losses": sum(y < x for x, y in zip(b, c)),
            "hallucination_frontrunner": rate_b, "hallucination_candidate": rate_c,
            "hallucinated": {"frontrunner": [hb, tb], "candidate": [hc, tc]}, "failed_docs": failed}


def verdicts(runs_dir: Path, look: int, *, target: float, alpha: float, n_perm: int, seed: int,
             allow_mock: bool) -> dict[str, Any]:
    from mailroom_sandbox.experiment_stats import holm, keep_at_look

    rows: dict[str, dict[str, Any]] = {}
    for agent in PAIRS:
        base_id, cand_id = run_ids(agent, look)
        base, cand = load_run(runs_dir, base_id), load_run(runs_dir, cand_id)
        row: dict[str, Any] = {"agent": agent, "frontrunner": PAIRS[agent][1], "candidate": PAIRS[agent][3],
                               "runs": {"frontrunner": base_id, "candidate": cand_id}}
        missing = [rid for rid, r in ((base_id, base), (cand_id, cand)) if r is None]
        problems = [f"{rid}: no run store" for rid in missing] or pair_problems(base, cand, allow_mock=allow_mock)
        if problems:
            row.update(status="incomplete", problems=problems)
        else:
            row.update(status="scored", **compare(base, cand, n_perm=n_perm, seed=seed))
        rows[agent] = row
    # Holm over the whole family: a pair without a result enters at p = 1, never shrinking the family.
    adjusted = holm({a: (r["p"] if r["status"] == "scored" else 1.0) for a, r in rows.items()})
    for agent, row in rows.items():
        row["holm_p"] = adjusted[agent]
        if row["status"] != "scored":
            row["verdict"] = "NO VERDICT"
            continue
        row["keep_rule"] = keep_at_look(row["n"], row["z"], row["gain"], target, look=look)
        no_rise = row["hallucination_candidate"] <= row["hallucination_frontrunner"]
        checks = {"look_2": look == 2, "keep_rule_keep": row["keep_rule"] == "keep",
                  "holm_p_below_alpha": row["holm_p"] < alpha, "positive_gain": row["gain"] > 0,
                  "hallucination_not_up": no_rise}
        row["checks"] = checks
        if all(checks.values()):
            row["verdict"] = "PROMOTE"
        elif look == 1:
            row["verdict"] = "SCREEN: run look 2"
        elif row["keep_rule"] == "continue" and no_rise:
            row["verdict"] = "HOLD: keep rule says continue (full-dev look 3 is an owner decision)"
        else:
            row["verdict"] = "KEEP FRONTRUNNER"
    return {"schema": "mailroom.rb1-promotion/v1", "experiment": EXPERIMENT_KEY, "look": look,
            "alpha": alpha, "target_gain": target, "n_perm": n_perm, "seed": seed, "allow_mock": allow_mock,
            "pairs": rows}


# ── --apply: the human step ──────────────────────────────────────────────────────────────────
def _agent_block(lines: list[str], agent: str) -> tuple[int, int]:
    start = next(i for i, line in enumerate(lines) if line.rstrip() == f"  {agent}:")
    end = next((j for j in range(start + 1, len(lines)) if re.match(r"^  \S", lines[j]) or re.match(r"^\S", lines[j])),
               len(lines))
    return start, end


def apply_promotion(text: str, row: dict[str, Any], *, initials: str, today: str) -> str:
    """Return the lineage text with ``row``'s candidate as the agent's frontrunner (comments kept)."""
    lines = text.split("\n")
    agent, cand, old = row["agent"], row["candidate"], row["frontrunner"]
    start, end = _agent_block(lines, agent)
    block = lines[start:end]
    note = (f"rb1-r41 look {row.get('look', 2)}: gain {row['gain']:+.4f} field F1, holm p {row['holm_p']:.4g}, "
            f"z {row['z']:.2f}, hallucination {row['hallucination_frontrunner']:.4f} -> "
            f"{row['hallucination_candidate']:.4f}; promoted {today} by {initials}")
    out, i, seen_cand = [], 0, False
    while i < len(block):
        line = block[i]
        if re.match(r"^    frontrunner:", line):
            out.append(f"    frontrunner: {cand}   # rb1 promotion {today} by {initials} (was {old})")
        elif re.match(r"^    frontrunner_outside_lineage:", line):
            pass  # the new frontrunner is a lineage version
        elif re.match(rf"^      - version: {re.escape(cand)}\s*$", line):
            seen_cand = True
            out.append(line)
        elif seen_cand and re.match(r"^        status:", line):
            out.append(f"        status: adopted   # {note}")
            out.append(f"        promotion: {{campaign: rb1, experiment: rb1-r41, look: {row.get('look', 2)}, "
                       f"frontrunner_run: {row['runs']['frontrunner']}, candidate_run: {row['runs']['candidate']}, "
                       f"decided: '{today}', initials: {initials}}}")
            seen_cand = False
            # drop the comment-only lines that continued the old status
            while i + 1 < len(block) and re.match(r"^        #", block[i + 1]):
                i += 1
        elif re.match(rf"^      - version: {re.escape(old)}\s*$", line):
            out.append(line)
            j = i + 1
            while j < len(block) and not re.match(r"^      - version:", block[j]):
                if re.match(r"^        status: adopted", block[j]):
                    block[j] = f"        status: superseded   # by {cand} (rb1 promotion {today}, {initials})"
                j += 1
        else:
            out.append(line)
        i += 1
    if not any(f"frontrunner: {cand}" in x for x in out):
        raise ValueError(f"{agent}: no frontrunner line to move")
    if not any(x.startswith("        status: adopted   # rb1-r41") for x in out):
        raise ValueError(f"{agent}: candidate {cand} has no status line")
    return "\n".join(lines[:start] + out + lines[end:])


def _pinned_elsewhere(stem: str) -> list[str]:
    hits = []
    for path in sorted((ROOT / "config" / "runs" / "production").glob("*.yaml")):
        if re.search(rf"\bfile: {re.escape(stem)}\b", path.read_text(encoding="utf-8")):
            hits.append(str(path.relative_to(ROOT)))
    return hits


def _record(result: dict[str, Any], out: str | None) -> Path | None:
    """Write the verdict to --out, else into the campaign tree when report_campaigns exists."""
    if out:
        path = Path(out)
    else:
        try:
            from mailroom_sandbox.report_campaigns import experiment_paths
        except ImportError:
            return None
        path = experiment_paths(EXPERIMENT_KEY).file(f"promotion-look{result['look']}", "json", subdir="analysis")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--look", type=int, choices=(1, 2), default=2)
    parser.add_argument("--target", type=float, default=0.03, help="lineage gain target (H2: +3 or +4 pts)")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--n-perm", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--runs-dir", default=str(ROOT / "data" / "runtime" / "runs"))
    parser.add_argument("--allow-mock", action="store_true", help="score mock runs (pipeline checks only; never with --apply)")
    parser.add_argument("--out", help="write the verdict JSON here (default: the rb1 campaign tree when present)")
    parser.add_argument("--apply", action="store_true", help="move PROMOTE candidates to frontrunner in the lineage file")
    parser.add_argument("--initials", help="the person applying (2-6 capital letters); required with --apply")
    args = parser.parse_args(argv)

    if args.apply and (not args.initials or not re.fullmatch(r"[A-Z]{2,6}", args.initials)):
        parser.error("--apply needs --initials XX (2-6 capital letters) from the person applying")
    if args.apply and args.allow_mock:
        parser.error("--apply never acts on mock runs")
    if args.apply and args.look != 2:
        parser.error("--apply acts only on a look-2 verdict")

    result = verdicts(Path(args.runs_dir), args.look, target=args.target, alpha=args.alpha, n_perm=args.n_perm,
                      seed=args.seed, allow_mock=args.allow_mock)
    print(f"rb1 prompt A/B verdicts, look {args.look} (alpha {args.alpha}, Holm over {len(PAIRS)}; target {args.target:+.2f})")
    for row in result["pairs"].values():
        head = f"  {row['agent']:30} {row['candidate']} vs {row['frontrunner']}"
        if row["status"] != "scored":
            print(f"{head}\n      {row['verdict']}: " + "; ".join(row["problems"]))
            continue
        print(f"{head}\n      n={row['n']} F1 {row['mean_f1_frontrunner']:.4f} -> {row['mean_f1_candidate']:.4f} "
              f"(gain {row['gain']:+.4f}, {row['wins']}W/{row['losses']}L) p={row['p']:.4g} holm={row['holm_p']:.4g} "
              f"z={row['z']:.2f} keep_rule={row['keep_rule']} halluc {row['hallucination_frontrunner']:.4f} -> "
              f"{row['hallucination_candidate']:.4f}  => {row['verdict']}")
    if args.allow_mock:
        print("NOTE: mock runs were allowed; these numbers are simulated and are not evidence.")
    recorded = None if (args.allow_mock and not args.out) else _record(result, args.out)
    if recorded:
        print(f"verdict written: {recorded}")

    promoted = [row for row in result["pairs"].values() if row.get("verdict") == "PROMOTE"]
    if not args.apply:
        if promoted:
            print(f"{len(promoted)} candidate(s) meet the rule; nothing was changed. A person applies it with "
                  "--apply --initials XX.")
        return 0
    if not promoted:
        print("--apply: no candidate meets the rule; nothing changed.")
        return 0
    today = dt.date.today().isoformat()
    text = LINEAGE.read_text(encoding="utf-8")
    for row in promoted:
        text = apply_promotion(text, {**row, "look": args.look}, initials=args.initials, today=today)
    LINEAGE.write_text(text, encoding="utf-8")
    print(f"--apply: {LINEAGE.relative_to(ROOT)} updated for {', '.join(r['agent'] for r in promoted)}.")
    for row in promoted:
        pins = _pinned_elsewhere(row["frontrunner"])
        if pins:
            print(f"  follow-up: {row['frontrunner']} is still pinned in {', '.join(pins)} "
                  "(tests/test_production_slices.py ties them to the frontrunner); move them in a reviewed PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
