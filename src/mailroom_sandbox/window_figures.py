"""Figures for chunk-window experiments on isolated specialist runs (#214), offline.

A specialist on Modal/vLLM reads a long document as overlapping windows and merges one
confidence per window. These figures answer the questions the window experiments ask
(``.claude/skills/experiment-figures/references/figure-catalog.md``, "Chunk windows"):

- ``paired``: did a change (the length fix, a shorter window) move quality on the same
  documents, and did it stop losing windows?
- ``window-rules``: does any merge rule (weakest, strongest, length-weighted window) separate
  documents that met the quality target from those that missed?
- ``confidence``: does the specialist's final confidence rank document quality?
- ``window-count``: does quality move with the number of windows a document needs?
- ``runs``: per-document quality of every run against the target.

The ``figure-data.csv`` table contains per-document values. Merge-rule AUROCs
also require the source window confidences (``job.routing_audit.window_rule_separation``). Built with the house
style (``figure_style``); run ids only in the source line.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mailroom_sandbox import figure_style as fs
from mailroom_sandbox.decision_figures import plural
from mailroom_sandbox.job import routing_audit as ra

TARGET = ra.DEFAULT_TARGET
FEW = 5  # below this many documents on either side of the target, a ranking is too few to judge
RULE_LABELS = {"min": "Weakest window (adopted)", "max": "Strongest window", "length_weighted": "Length-weighted mean"}
# Doc-level cross-window agreement (HF-008 `_window_agreement`) is not a
# confidence merge rule: it gets its own plotted row and title label, so a
# best-AUROC selection that lands on it never indexes RULE_LABELS.
AGREEMENT_KEY = "agreement"
AGREEMENT_LABEL = "Cross-window agreement"
CONFIDENCE_SPLIT = 0.85
FOLD_WINDOWS = 5  # documents needing this many windows or more share a row


def load_run(run_dir: Path | str) -> list[dict[str, Any]]:
    """One record per document of an isolated specialist run: quality, final confidence, windows."""
    root = Path(run_dir)
    rows = {str(r.get("id")): r for r in ra._jsonl(root / "dataset.jsonl")}
    items = {str(i.get("item_id")): i for i in ra._jsonl(root / "items.jsonl")}
    docs = ra._doc_records([], items, rows)
    for d in docs:
        pred = (items.get(d["id"]) or {}).get("pred") or {}
        d["confidence"] = ra._number(pred.get("confidence"))
    return docs


def _jitter(key: str, width: float) -> float:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return (h - 0.5) * width


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _scored(docs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [d for d in docs if d.get("quality") is not None]


def _lost(docs: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for d in docs if d.get("failed_windows"))


def _target_line(ax: Any, axis: str = "x", label: bool = True) -> None:
    line = ax.axvline if axis == "x" else ax.axhline
    line(TARGET, color=fs.INK_2, linewidth=1, linestyle=(0, (4, 2)), zorder=2)
    if label and axis == "x":
        ax.text(TARGET + 0.012, ax.get_ylim()[1], f"Target {TARGET:g}", ha="left", va="top",
                fontsize=fs.SIZE["annotation"], color=fs.INK_2)


def _paired(f: fs.Fig, base: list[dict[str, Any]], cand: list[dict[str, Any]], labels: tuple[str, str],
            source: str) -> str | None:
    by_id = {d["id"]: d for d in _scored(base)}
    pairs = [(by_id[d["id"]], d) for d in _scored(cand) if d["id"] in by_id]
    if not pairs:
        return None
    delta = sum(c["quality"] - b["quality"] for b, c in pairs) / len(pairs)
    up = sum(c["quality"] > b["quality"] for b, c in pairs)
    down = sum(c["quality"] < b["quality"] for b, c in pairs)
    lost_b, lost_c = _lost([b for b, _ in pairs]), _lost([c for _, c in pairs])
    title = f"Documents losing a window fell from {lost_b} to {lost_c}; mean quality moved {delta:+.3f}"
    if lost_b == lost_c:
        title = f"Mean quality moved {delta:+.3f} on the same documents"
    sub = (f"Overall extraction score per document, {labels[0]} vs {labels[1]} · same {len(pairs)} documents"
           f" · {up} up, {down} down")
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 4.6))
    ax.plot([0, 1], [0, 1], color=fs.AXIS, linewidth=1, linestyle=(0, (4, 2)), zorder=1)
    ax.text(0.85, 0.95, "No change", ha="right", va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    for lost, colour, label in ((False, fs.THIRD, "Both runs read every window"),
                                (True, fs.CRITICAL, f"Lost a window in {labels[0]}")):
        pts = [(b, c) for b, c in pairs if bool(b.get("failed_windows")) == lost]
        if pts:
            ax.scatter([b["quality"] for b, _ in pts], [c["quality"] for _, c in pts], s=30, color=colour,
                       alpha=0.92, edgecolors=fs.SURFACE, linewidths=0.9, label=label, zorder=3)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect("equal")
    ax.grid(True)
    ax.set_axisbelow(True)
    fs.axis_labels(ax, f"Score, {labels[0]}", f"Score, {labels[1]}")
    fs.heading(fig, ax, title, sub, source)
    fs.legend_below(fig, ax, 2)
    return f.svg(fig)


def _window_rules(f: fs.Fig, runs: Sequence[tuple[str, list[dict[str, Any]], str]], source: str) -> str | None:
    seps = [(label, ra.window_rule_separation(docs, target=TARGET), colour) for label, docs, colour in runs]
    seps = [s for s in seps if any(v is not None for v in s[1]["auroc"].values())]
    if not seps:
        return None
    values = [v for _, sep, _ in seps for v in sep["auroc"].values() if v is not None]
    best = max(values)
    few = any(min(sep["met_target"], sep["n"] - sep["met_target"]) < FEW for _, sep, _ in seps)
    rule_best = max(v for _, sep, _ in seps for r, v in sep["auroc"].items()
                    if v is not None and r in RULE_LABELS)
    if few:
        title = "Too few documents on one side of the target to judge the merge rules"
    elif best >= 0.7 and best > rule_best:
        # Agreement is doc-level self-consistency, not a merge rule: when it is
        # the unique best signal it names itself, never a merge-rule label.
        title = f"{AGREEMENT_LABEL} separates good from poor documents best (AUROC {best:.2f})"
    elif best < 0.7:
        title = f"No window merge rule separates good from poor documents (best AUROC {best:.2f})"
    else:
        rule = next(RULE_LABELS[r] for _, sep, _ in seps for r, v in sep["auroc"].items()
                    if v == best and r in RULE_LABELS)
        title = f"{rule} separates good from poor documents best (AUROC {best:.2f})"
    counts = " · ".join(f"{label} n = {sep['n']} ({sep['met_target']} met)" for label, sep, _ in seps)
    sub = f"AUROC, documents at or above {TARGET:g} vs below · {counts} · 0.5 is chance"
    rules = list(RULE_LABELS)
    recorded_agreement = any(sep["auroc"].get(AGREEMENT_KEY) is not None for _, sep, _ in seps)
    if recorded_agreement:
        rules.append(AGREEMENT_KEY)
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.55 * len(rules) + 1.6))
    y_of = {r: i for i, r in enumerate(rules[::-1])}
    offsets = [(i - (len(seps) - 1) / 2) * 0.22 for i in range(len(seps))]
    for (label, sep, colour), dy in zip(seps, offsets, strict=True):
        pts = [(sep["auroc"][r], y_of[r] + dy) for r in rules if sep["auroc"][r] is not None]
        ax.scatter([x for x, _ in pts], [y for _, y in pts], s=44, color=colour, edgecolors=fs.SURFACE,
                   linewidths=0.9, label=label, zorder=3)
        for x, y in pts:  # label on the side away from the chance line, so it never crosses it
            right = x >= 0.5
            ax.text(x + (0.018 if right else -0.018), y, f"{x:.2f}", ha="left" if right else "right",
                    va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.axvline(0.5, color=fs.INK_2, linewidth=1, linestyle=(0, (4, 2)), zorder=2)
    row_labels = {**RULE_LABELS, AGREEMENT_KEY: AGREEMENT_LABEL}
    ax.set_yticks(list(y_of.values()), list(row_labels[r] for r in y_of))
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(rules) - 0.4)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "AUROC (1 = perfect separation, 0.5 = chance)")
    fs.heading(fig, ax, title, sub, source)
    fs.legend_below(fig, ax, len(seps))
    return f.svg(fig)


def _confidence(f: fs.Fig, docs: list[dict[str, Any]], label: str, source: str) -> str | None:
    pts = [d for d in _scored(docs) if d.get("confidence") is not None]
    if not pts:
        return None
    met = [d["confidence"] for d in pts if d["quality"] >= TARGET]
    missed = [d["confidence"] for d in pts if d["quality"] < TARGET]
    a = ra._auroc(met, missed)
    hi = _mean([d["quality"] for d in pts if d["confidence"] >= CONFIDENCE_SPLIT])
    lo = _mean([d["quality"] for d in pts if d["confidence"] < CONFIDENCE_SPLIT])
    if a is None or min(len(met), len(missed)) < FEW:
        title = "Too few documents on one side of the target to judge the confidence"
    elif 0.4 <= a <= 0.6:
        title = f"Specialist confidence does not rank document quality (AUROC {a:.2f})"
    elif a > 0.6:
        title = f"Specialist confidence ranks document quality (AUROC {a:.2f})"
    else:
        title = f"Specialist confidence ranks poor documents higher (AUROC {a:.2f})"
    split = (f" · mean score {hi:.2f} at ≥ {CONFIDENCE_SPLIT:g}, {lo:.2f} below"
             if hi is not None and lo is not None else "")
    sub = f"Final specialist confidence vs overall extraction score · {label} n = {len(pts)}{split}"
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.8))
    ax.scatter([d["confidence"] + _jitter(d["id"], 0.018) for d in pts], [d["quality"] for d in pts], s=30,
               color=fs.THIRD, alpha=0.92, edgecolors=fs.SURFACE, linewidths=0.9, zorder=3)
    ax.axhline(TARGET, color=fs.INK_2, linewidth=1, linestyle=(0, (4, 2)), zorder=2)
    lo_x = min(d["confidence"] for d in pts) - 0.03
    ax.text(lo_x + 0.3 * (1.0 - lo_x), TARGET + 0.02, f"Target {TARGET:g}", ha="left", va="bottom",
            fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_xlim(lo_x, 1.0)
    ax.set_ylim(-0.02, 1.02)
    fs.value_axis(ax, "y")
    ax.tick_params(axis="x", length=3)
    fs.axis_labels(ax, "Final specialist confidence (jittered)", "Overall extraction score")
    fs.heading(fig, ax, title, sub, source)
    return f.svg(fig)


def _strip_by(f: fs.Fig, groups: list[tuple[str, list[dict[str, Any]], str]], title: str, sub: str,
              source: str) -> str:
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.55 * len(groups) + 1.6))
    y_of = {g: i for i, (g, _, _) in enumerate(groups[::-1])}
    for g, docs, colour in groups:
        ys = [y_of[g] + _jitter(d["id"], 0.32) for d in docs]
        ax.scatter([d["quality"] for d in docs], ys, s=26, color=colour, alpha=0.85, edgecolors=fs.SURFACE,
                   linewidths=0.8, zorder=3)
        m = _mean([d["quality"] for d in docs])
        ax.plot([m, m], [y_of[g] - 0.3, y_of[g] + 0.3], color=fs.INK, linewidth=2, zorder=4)
        ax.text(1.04, y_of[g], f"mean {m:.2f} · n {len(docs)}", ha="left", va="center",
                fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_yticks(list(y_of.values()), list(y_of))
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.6, len(groups) - 0.4)
    _target_line(ax)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "Overall extraction score per document")
    fs.heading(fig, ax, title, sub, source)
    return f.svg(fig)


def _window_count(f: fs.Fig, docs: list[dict[str, Any]], label: str, source: str) -> str | None:
    full = [d for d in _scored(docs) if not d.get("failed_windows") and d.get("windows")]

    def bucket(d: Mapping[str, Any]) -> int:  # the few longest documents fold into one row
        return min(len(d["windows"]), FOLD_WINDOWS)

    counts = sorted({bucket(d) for d in full})
    groups = [(plural(k, "window") if k < FOLD_WINDOWS else f"{k} or more windows",
               [d for d in full if bucket(d) == k], fs.THIRD) for k in counts]
    if len(groups) < 2:
        return None
    means = [_mean([d["quality"] for d in docs_]) for _, docs_, _ in groups]
    spread = max(means) - min(means)
    top = f"{counts[-1]}+" if counts[-1] == FOLD_WINDOWS else str(counts[-1])
    title = (f"Mean quality moves only {spread:.2f} across {counts[0]}–{top} windows per document"
             if spread < 0.1 else f"Mean quality moves {spread:.2f} across {counts[0]}–{top} windows per document")
    sub = f"Overall extraction score by windows read, documents with no lost window · {label} · black bar: mean"
    return _strip_by(f, groups, title, sub, source)


def _runs(f: fs.Fig, runs: Sequence[tuple[str, list[dict[str, Any]], str]], source: str) -> str | None:
    groups = [(label, _scored(docs), colour) for label, docs, colour in runs if _scored(docs)]
    if not groups:
        return None
    means = {label: _mean([d["quality"] for d in docs]) for label, docs, _ in groups}
    reached = [label for label, m in means.items() if m >= TARGET]
    worst = min(means, key=means.get)
    title = (f"No run reached the {TARGET:g} target on average; {worst[:1].lower() + worst[1:]} scored {means[worst]:.2f}"
             if not reached else f"{len(reached)} of {len(groups)} runs reached the {TARGET:g} target on average")
    sub = "Overall extraction score per document, calibration split · black bar: mean"
    return _strip_by(f, groups, title, sub, source)


def build(runs: Sequence[tuple[str, list[dict[str, Any]]]], *, base: str, cand: str, source: str,
          salt: str = "window-figures") -> tuple[dict[str, str], list[dict[str, Any]]]:
    """``({figure name: svg}, table rows)``. ``runs`` is ``(label, docs)``; ``base`` and ``cand``
    name the paired pair (same documents); every run appears in ``runs``."""
    by_label = dict(runs)
    colour = {label: (fs.NEUTRAL if label == base else fs.THIRD) for label, _ in runs}
    out: dict[str, str | None] = {}
    with fs.Fig(salt) as f:
        out["runs"] = _runs(f, [(label, docs, colour[label]) for label, docs in runs], source)
        out["paired"] = _paired(f, by_label[base], by_label[cand], (base, cand), source)
        out["window-rules"] = _window_rules(
            f, [(base, by_label[base], fs.NEUTRAL), (cand, by_label[cand], fs.THIRD)], source)
        out["confidence"] = _confidence(f, by_label[cand], cand, source)
        out["window-count"] = _window_count(f, by_label[cand], cand, source)
    table = [{"run": label, "id": d["id"], "chars": d["chars"], "quality": d["quality"],
              "confidence": d.get("confidence"), "windows": len(d.get("windows") or []),
              "failed_windows": d.get("failed_windows") or 0}
             for label, docs in runs for d in docs]
    return {k: v for k, v in out.items() if v}, table


def _csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_DIR",
                   help="a run to include, e.g. 'Contracts r1=data/runtime/runs/<id>' (repeatable)")
    p.add_argument("--base", required=True, help="label of the paired reference run")
    p.add_argument("--cand", required=True, help="label of the paired candidate run")
    p.add_argument("--stem", required=True, help="file stem, e.g. sand214-windows")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--source", help="source line (default: the run ids; keep it under 120 characters)")
    args = p.parse_args(argv)
    runs, ids = [], []
    for spec in args.run:
        label, _, path = spec.partition("=")
        runs.append((label, load_run(path)))
        ids.append(Path(path).name)
    source = args.source or ("Source: runs " + ", ".join(ids))
    figs, table = build(runs, base=args.base, cand=args.cand, source=source, salt=args.stem)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, svg in figs.items():
        (args.out / f"{args.stem}.{name}.svg").write_text(svg, encoding="utf-8")
    (args.out / f"{args.stem}.figure-data.csv").write_text(_csv(table), encoding="utf-8")
    print(json.dumps({"figures": sorted(figs), "rows": len(table), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
