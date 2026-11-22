"""House figures for the Modal vLLM measurement-priority research.

Numbers are copied from committed serving reports. The script does not call a model.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Load the house style by file so package import does not select vendor sources.
_spec = importlib.util.spec_from_file_location(
    "figure_style",
    ROOT / "src" / "mailroom_sandbox" / "figure_style.py",
)
fs = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(fs)

OUT = Path(__file__).resolve().parent

# SAND-032 stages 7 and 9, same 100 correspondence documents, seqs 32, concurrency 64, 2×L4.
# reports/serving/QWEN3-L4-LADDER-SUMMARY.md (2026-09-28).
ADMISSION = (
    {"label": "Admission 32", "seconds": 39.0, "note": "split 51/49", "role": "reference"},
    {"label": "Admission 64", "seconds": 149.4, "note": "97 of 100 on one replica", "role": "llm"},
)

# Five-specialist sweep, n=50 per class, 2×L4, concurrency 32.
# Same summary, section 3. Wall-clock only; document lengths differ.
CLASSES = (
    {"label": "Merger agreement", "seconds": 342.4, "n": 50},
    {"label": "Contract", "seconds": 234.3, "n": 50},
    {"label": "Insurance claim", "seconds": 60.7, "n": 50},
    {"label": "Corporate record", "seconds": 56.3, "n": 50},
    {"label": "Correspondence", "seconds": 16.0, "n": 50},
)

# Context that actually reached ready on one L4 under vLLM v0.29.0.
# Qwen3-8B bf16: ladder summary section 4, 16k correspondence n=20.
# Qwen3-8B-AWQ: same program at 32768.
# Granite FP8: reports/SAND-32/granite, served at 32768 with no admission raise.
# Qwen3.5-9B: config/models.yaml marks the row unverified. The catalog 16384 is not plotted.
BOOT = (
    {"label": "Qwen3.5 9B, online FP8", "tokens": None},
    {"label": "Granite 4.2 8B, FP8", "tokens": 32768},
    {"label": "Qwen3 8B, AWQ", "tokens": 32768},
    {"label": "Qwen3 8B, bf16", "tokens": 16384},
)


def emit(house: fs.Fig, fig, stem: str) -> str:
    fs._place_heading(fig)
    fig.savefig(OUT / f"{stem}.png", dpi=160, bbox_inches="tight", pad_inches=0.18)
    buf = io.StringIO()
    fig.savefig(
        buf,
        format="svg",
        metadata={"Date": None, "Creator": None},
        bbox_inches="tight",
        pad_inches=0.18,
    )
    house.plt.close(fig)
    svg = fs.system_fonts(buf.getvalue())
    (OUT / f"{stem}.svg").write_text(svg, encoding="utf-8")
    problems = fs.lint_svg(svg)
    if problems:
        raise SystemExit(f"{stem}: {problems}")
    return svg


def _bars(house: fs.Fig, rows: list[dict], colours: list[str], values: list[float], notes: list[str],
          xlabel: str, title: str, subtitle: str, source: str, xlim: float):
    if len(title) > fs.TITLE_MAX:
        raise SystemExit(f"title {len(title)} > {fs.TITLE_MAX}: {title}")
    if len(subtitle) > fs.SUBTITLE_MAX:
        raise SystemExit(f"subtitle {len(subtitle)} > {fs.SUBTITLE_MAX}: {subtitle}")
    fig, ax = house.plt.subplots(figsize=(fs.WIDTH, 0.52 * len(rows) + 1.55))
    y = list(range(len(rows)))[::-1]
    ax.barh(y, values, color=colours, height=0.56)
    gap = xlim * 0.015
    for yi, value, note in zip(y, values, notes):
        if value <= 0:
            ax.text(gap, yi, note, va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
        else:
            ax.text(value + gap, yi, note, va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_yticks(y, [row["label"] for row in rows])
    ax.set_xlim(0, xlim)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, xlabel)
    fs.heading(fig, ax, title, subtitle, source)
    return fig


def admission(house: fs.Fig) -> str:
    ref = ADMISSION[0]["seconds"]
    slow = ADMISSION[1]["seconds"]
    title = f"The same 100 documents took {slow / ref:.1f}× longer at admission 64"
    subtitle = (
        "Wall-clock time · 100 correspondence documents · 2 L4 replicas · concurrency 64 · Qwen3 8B AWQ"
    )
    notes = [f"{row['seconds']:.1f} s · {row['note']}" for row in ADMISSION]
    colours = [fs.NEUTRAL if row["role"] == "reference" else fs.LLM for row in ADMISSION]
    fig = _bars(
        house,
        list(ADMISSION),
        colours,
        [row["seconds"] for row in ADMISSION],
        notes,
        "Total run time (s)",
        title,
        subtitle,
        "Source: SAND-032 stages 7 and 9 · Qwen3-8B-AWQ · vLLM v0.29.0 · 2026-09-28",
        slow * 2.15,
    )
    ax = fig.axes[0]
    fs.legend_below(
        fig,
        ax,
        2,
        handles=[
            house.plt.Rectangle((0, 0), 1, 1, color=fs.NEUTRAL, label="Admission matched to sequences"),
            house.plt.Rectangle((0, 0), 1, 1, color=fs.LLM, label="Admission above the sequence cap"),
        ],
    )
    return emit(house, fig, "admission-cliff")


def classes(house: fs.Fig) -> str:
    slow = CLASSES[0]
    fast = CLASSES[-1]
    title = f"50 merger agreements took {slow['seconds'] / fast['seconds']:.1f}× longer than correspondence"
    subtitle = "Wall-clock time · 50 documents per class · 2 L4 replicas · concurrency 32 · lengths differ"
    notes = []
    for row in CLASSES:
        per_min = row["n"] / row["seconds"] * 60
        hours = 100_000 / per_min / 60
        notes.append(f"{row['seconds']:.1f} s · {per_min:.0f} documents/min · {hours:.1f} h per 100k")
    fig = _bars(
        house,
        list(CLASSES),
        [fs.LLM] * len(CLASSES),
        [row["seconds"] for row in CLASSES],
        notes,
        "Total run time (s)",
        title,
        subtitle,
        "Source: SAND-032 five-specialist sweep · Qwen3-8B-AWQ · vLLM v0.29.0 · 2026-09-28",
        slow["seconds"] * 2.45,
    )
    return emit(house, fig, "class-wall-time")


def boot(house: fs.Fig) -> str:
    measured = [row for row in BOOT if row["tokens"]]
    missing = [row for row in BOOT if not row["tokens"]]
    title = f"{missing[0]['label'].split(',')[0]} has no recorded L4 boot; {len(measured)} peers do"
    subtitle = "Configured context that reached ready on one L4 · vLLM v0.29.0 · the 9B row was not run"
    notes = ["Not measured" if row["tokens"] is None else f"{row['tokens']:,} tokens" for row in BOOT]
    colours = [fs.WARNING if row["tokens"] is None else fs.LLM for row in BOOT]
    fig = _bars(
        house,
        list(BOOT),
        colours,
        [0 if row["tokens"] is None else row["tokens"] for row in BOOT],
        notes,
        "Context that reached ready (tokens)",
        title,
        subtitle,
        "Source: SAND-032 Qwen ladder and Granite L4 reports · 9B catalog row unverified",
        52000,
    )
    return emit(house, fig, "boot-context")


def write_csv() -> None:
    path = OUT / "figure-data.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["figure", "label", "value", "unit", "n", "measured", "source"],
        )
        writer.writeheader()
        for row in ADMISSION:
            writer.writerow({
                "figure": "admission-cliff",
                "label": row["label"],
                "value": row["seconds"],
                "unit": "s",
                "n": 100,
                "measured": "yes",
                "source": "reports/serving/QWEN3-L4-LADDER-SUMMARY.md stages 7 and 9",
            })
        for row in CLASSES:
            writer.writerow({
                "figure": "class-wall-time",
                "label": row["label"],
                "value": row["seconds"],
                "unit": "s",
                "n": row["n"],
                "measured": "yes",
                "source": "reports/serving/QWEN3-L4-LADDER-SUMMARY.md section 3",
            })
        for row in BOOT:
            writer.writerow({
                "figure": "boot-context",
                "label": row["label"],
                "value": "" if row["tokens"] is None else row["tokens"],
                "unit": "tokens",
                "n": "",
                "measured": "no" if row["tokens"] is None else "yes",
                "source": "SAND-032 live boots, except Qwen3.5-9B which config/models.yaml leaves unverified",
            })


def main() -> None:
    write_csv()
    first: dict[str, str] = {}
    second: dict[str, str] = {}
    for bucket in (first, second):
        with fs.Fig("modal-vllm-measurement-priorities") as house:
            bucket["admission-cliff"] = admission(house)
        with fs.Fig("modal-vllm-measurement-priorities") as house:
            bucket["class-wall-time"] = classes(house)
        with fs.Fig("modal-vllm-measurement-priorities") as house:
            bucket["boot-context"] = boot(house)
    for stem, svg in first.items():
        if svg != second[stem]:
            raise SystemExit(f"{stem} is not deterministic")
    print("lint clean, deterministic")


if __name__ == "__main__":
    main()
