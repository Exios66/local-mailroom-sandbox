#!/usr/bin/env python
"""SAND-042 coverage ledger: prove the designed metric matrix landed, per cell.

A card only rewrites at the END of its leg, so a capture that silently stopped halfway
stays invisible for hours. This reads the run stores directly and reports, per cell, the
things the re-run campaign exists to capture — plus the contract draw — and exits non-zero
if anything is missing.

    .venv/bin/python scripts/sand42/coverage-ledger.py            # all five cells
    .venv/bin/python scripts/sand42/coverage-ledger.py 1l4-c8     # one cell, as it stands

Columns: runs found · stores at 50 docs · verbatim before/mid/after · mid series ·
mid-run KV in the card · nvidia-smi samples in the card · draw loaded · fleet ready_ts.
"""

from __future__ import annotations

import glob
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNS = REPO / "data" / "runtime" / "runs"
CELLS = ("1l4-c8", "1l4-c16", "2l4-c8", "2l4-c16", "2l4-c32")
FAMILY = re.compile(r"^vllm:", re.M)


def folder(cell: str) -> str:
    return cell.replace("l4-c", "L4-c").upper().replace("L4-C", "L4-c")


def _json(p: pathlib.Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _lines(rid: str, name: str) -> int:
    p = RUNS / rid / name
    if not p.is_file():
        return 0
    return sum(1 for x in p.read_text(encoding="utf-8").splitlines() if x.strip())


def _cards(rid: str) -> list[pathlib.Path]:
    return [pathlib.Path(x) for x in glob.glob(
        str(REPO / "reports" / "SAND42" / "*" / "*" / f"{rid}.card.json"))]


def _midrun(rid: str) -> dict:
    for c in _cards(rid):
        et = _json(c).get("engine_telemetry") or {}
        if et.get("midrun"):
            return et["midrun"]
    return {}


def _bw_samples(rid: str) -> int:
    """nvidia-smi samples behind the card's 'GPU mem bandwidth (mean)' row.

    That row renders from `utilization_memory_perc` (the nvidia-smi memory-bandwidth gauge)
    in the summarized telemetry, so this checks exactly that field and nothing looser — a
    per-replica sample count would report positive on cards whose bandwidth row still reads
    "not captured".
    """
    for c in _cards(rid):
        et = _json(c).get("engine_telemetry") or {}
        n = ((et.get("gpu") or {}).get("utilization_memory_perc") or {}).get("n")
        if n:
            return int(n)
    return 0


def check_run(rid: str, gaps: list[str], ok: list[str]) -> None:
    d = RUNS / rid
    if not d.is_dir():
        gaps.append(f"{rid}: no run store")
        return
    items = _lines(rid, "items.jsonl")
    if items < 50:
        gaps.append(f"{rid}: store {items}/50 documents")

    for lbl in ("before", "mid", "after"):
        j, t = d / f"vllm_metrics_{lbl}.json", d / f"vllm_metrics_{lbl}.txt"
        if not j.is_file() or not t.is_file():
            gaps.append(f"{rid}: {lbl} scrape missing ({j.name}{'' if j.is_file() else ' MISSING'} / "
                        f"{t.name}{'' if t.is_file() else ' MISSING'})")
        elif not FAMILY.search(t.read_text(encoding="utf-8", errors="replace")):
            gaps.append(f"{rid}: {lbl} text carries no vllm: family (verbatim not preserved)")

    if _lines(rid, "vllm_metrics_mid.series.jsonl") < 1:
        gaps.append(f"{rid}: no mid-run SERIES — the card's mid max has no source")

    if not _cards(rid):
        gaps.append(f"{rid}: no card written")
    else:
        cm = (_midrun(rid).get("cell_max") or {})
        if cm.get("kv_cache_usage_perc") is None:
            gaps.append(f"{rid}: card has no mid-run kv_cache_usage_perc")
        if _bw_samples(rid) == 0:
            gaps.append(f"{rid}: card carries no GPU memory-bandwidth samples "
                        f"(utilization_memory_perc) — the bandwidth row stays empty")

    rows = [json.loads(x) for x in
            (d / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] \
        if (d / "dataset.jsonl").is_file() else []
    if len(rows) != 50:
        gaps.append(f"{rid}: draw is {len(rows)} documents, expected 50")
    if "contract" in rid:
        blank = [r.get("id") for r in rows
                 if not str((r.get("expected_fields") or {}).get("cuad_clause_labels") or "").strip()]
        if blank:
            gaps.append(f"{rid}: {len(blank)} drawn contract(s) carry no cuad_clause_labels "
                        f"— the CUAD metric cannot score them: {blank[:4]}")
        else:
            ok.append(f"{rid}: draw 50/50 annotated (CUAD-scorable)")


def main(argv: list[str]) -> int:
    cells = [c for c in argv if c in CELLS] or list(CELLS)
    gaps: list[str] = []
    ok: list[str] = []
    print(f"{'cell':<8} {'runs':>4} {'store':>7} {'verbatim':>9} {'series':>7} "
          f"{'midKV':>6} {'bw':>6} {'draw':>6} {'fleet':>5}  verdict")
    print("-" * 74)
    for cell in cells:
        reps = sorted(pathlib.Path(p).stem for p in
                      glob.glob(str(REPO / "config" / "runs" / f"sand42-*-awq-{cell}.yaml"))
                      if not pathlib.Path(p).name.startswith("sand42-check-"))
        if not reps:
            print(f"{cell:<8}    -  no configs found")
            continue
        before = len(gaps)
        for rid in reps:
            check_run(rid, gaps, ok)
        fw = REPO / "reports" / "SAND42" / folder(cell) / "fleet_window.json"
        ready = bool(_json(fw).get("ready_ts"))
        if not ready:
            gaps.append(f"{cell}: fleet_window.json missing/incomplete ready_ts")

        t = len(reps)
        store = sum(1 for r in reps if _lines(r, "items.jsonl") >= 50)
        verb = sum(1 for r in reps if all((RUNS / r / f"vllm_metrics_{l}.{e}").is_file()
                                          for l in ("before", "mid", "after") for e in ("json", "txt")))
        ser = sum(1 for r in reps if _lines(r, "vllm_metrics_mid.series.jsonl") >= 1)
        mid = sum(1 for r in reps
                  if (_midrun(r).get("cell_max") or {}).get("kv_cache_usage_perc") is not None)
        gpu = sum(1 for r in reps if _bw_samples(r) > 0)
        draw = sum(1 for r in reps if _lines(r, "dataset.jsonl") == 50)
        here = len(gaps) - before
        print(f"{cell:<8} {t:>4} {store:>4}/{t} {verb:>6}/{t} {ser:>4}/{t} "
              f"{mid:>3}/{t} {gpu:>3}/{t} {draw:>3}/{t} {('yes' if ready else 'NO'):>5}  "
              f"{'ALL CAPTURES' if here == 0 else f'{here} gap(s)'}")
    print()
    if gaps:
        print(f"GAPS ({len(gaps)}):")
        for g in gaps:
            print(f"  - {g}")
        return 1
    print(f"COVERAGE COMPLETE for {', '.join(cells)} ({len(ok)} positive draw checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
