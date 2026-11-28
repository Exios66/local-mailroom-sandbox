#!/usr/bin/env python3
"""Offline check of the merger section locator on the calibration mergers (no model call, read only).

Usage: python -I scripts/check_merger_sections.py [--out <json>]

Reads the cached Hub dataset's **calibration-set** merger agreements only
(config/splits/runbook-v2/assignments.jsonl; dev and sealed held-out documents are never read) and
prints, per MAUD question, the share of agreements where the locator found a section, the median and
maximum excerpt size, and the estimated tokens per group read (characters / 4). The labels carry no
clause text, so this measures coverage and size, not whether the sections hold the answer.
Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md (part 2).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from mailroom_sandbox import merger_sections, merger_tables

FOUND_BAR = 0.80


def _calibration_texts() -> list[tuple[str, str]]:
    import pyarrow.parquet as pq

    sets, _ = merger_tables._assignment_sets()
    default = merger_tables.DATASET_GT.parent / "default"
    out = []
    for split in ("train", "test"):
        gt = pq.read_table(merger_tables.DATASET_GT / split / f"{split}-00000-of-00001.parquet",
                           columns=["filename", "document_id", "expected"]).to_pydict()
        wanted = {f: i for f, i, e in zip(gt["filename"], gt["document_id"], gt["expected"])
                  if "merger" in str(e).lower() and sets.get(i) == "calibration"}
        if not wanted:
            continue
        docs = pq.read_table(default / split / f"{split}-00000-of-00001.parquet",
                             columns=["filename", "doc_text"],
                             filters=[("filename", "in", list(wanted))]).to_pydict()
        out += [(wanted[f], t or "") for f, t in zip(docs["filename"], docs["doc_text"]) if f in wanted]
    return out


def check(texts: list[tuple[str, str]], groups: int = 3) -> dict:
    questions = list(merger_sections.rules()["questions"])
    per_q = {q: {"found": 0, "chars": []} for q in questions}
    per_group: dict[str, list[int]] = {}
    headings: dict[str, Counter[str]] = {}
    doc_chars = []
    for _doc_id, text in texts:
        doc_chars.append(len(text))
        for key, excerpt in merger_sections.locate(text).items():
            if key != "preamble":
                headings.setdefault(key, Counter())[excerpt.heading] += 1
        for q in questions:
            excerpts, missed = merger_sections.question_excerpts(text, [q])
            if not missed:
                per_q[q]["found"] += 1
                per_q[q]["chars"].append(sum(len(e.text) for e in excerpts))
        for key, qs in merger_tables.group_questions(groups).items():
            excerpts, _ = merger_sections.question_excerpts(text, qs)
            per_group.setdefault(key, []).append(sum(len(e.text) for e in excerpts))
    n = len(texts)
    rows = {q: {"found_share": round(v["found"] / n, 3) if n else None,
                "median_chars": int(statistics.median(v["chars"])) if v["chars"] else 0,
                "max_chars": max(v["chars"]) if v["chars"] else 0} for q, v in per_q.items()}
    groups_out = {k: {"median_chars": int(statistics.median(v)), "est_tokens": int(statistics.median(v) / 4)}
                  for k, v in per_group.items() if v}
    median_doc = statistics.median(doc_chars) if doc_chars else 0
    share = (sum(g["median_chars"] for g in groups_out.values()) / median_doc) if median_doc else None
    return {"n": n, "questions": rows, "groups": groups_out, "median_doc_chars": int(median_doc),
            "group_reads_whole_doc_share": round(share, 3) if share is not None else None,
            # Correctness is a person's call: every heading each key took, to read down the list, plus
            # the excerpts whose heading still reads like a contents line (should be 0).
            "headings": {k: dict(c.most_common()) for k, c in sorted(headings.items())},
            "contents_like_headings": sum(n for c in headings.values() for h, n in c.items()
                                          if merger_sections._contents_like(h.split(" ", 2)[-1])),
            "under_bar": sorted(q for q, r in rows.items() if (r["found_share"] or 0) < FOUND_BAR)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/runtime/merger_sections_check.json"))
    args = parser.parse_args(argv)
    if not merger_tables.DATASET_GT.exists():
        print(f"the dataset is not cached at {merger_tables.DATASET_GT}", file=sys.stderr)
        return 2
    result = check(_calibration_texts())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"calibration mergers: {result['n']} (offline locator check: coverage and size; correctness is read "
          f"from the per-key headings in the full result)")
    print(f"  headings that read like a contents line: {result['contents_like_headings']}")
    for q, r in sorted(result["questions"].items(), key=lambda x: x[1]["found_share"] or 0):
        print(f"  {r['found_share']:>5.0%}  median {r['median_chars']:>6}  max {r['max_chars']:>6}  {q}")
    for k, g in result["groups"].items():
        print(f"  group {k}: median {g['median_chars']} chars (~{g['est_tokens']} tokens)")
    print(f"  group reads together: {result['group_reads_whole_doc_share']} of a median whole document "
          f"({result['median_doc_chars']} chars)")
    print(f"  under {FOUND_BAR:.0%}: {result['under_bar'] or 'none'}")
    print(f"full result: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
