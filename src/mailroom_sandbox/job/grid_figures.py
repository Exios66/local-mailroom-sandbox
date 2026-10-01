"""Figures for the specialist-grid master card (SAND-037 / SAND-039).

Rendered from the same ``collect_master()`` data as the Markdown, so a later leg
fills its series in on the next ``sandbox run card --master``::

    reports/SAND-37/figures/cmp-*.png          posture comparison suite (master card body)
    reports/SAND-37/<1L4|2L4>/figures/*.png    one dashboard per posture (master card appendix)

``figure_specs()`` decides which figures exist from the data alone, so the
Markdown links are deterministic and testable without rendering; ``write_figures()``
draws them with matplotlib (Agg, no display).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.job.grid_cards import ROOT_REL, SPECIALISTS

# Okabe-Ito (colorblind-safe): the n=20 leg is the grey reference; the matched pair is blue vs orange.
COLORS = {"s37-1l4-n20": "#999999", "s39-1l4-n50": "#0072B2", "s37-2l4-n50": "#E69F00"}
_ORDER = ("insurance_claims", "contracts", "corporate_records", "correspondence", "merger_agreement")
_SHORT = {
    "insurance_claims": "Insurance\nclaims",
    "contracts": "Contracts",
    "corporate_records": "Corporate\nrecords",
    "correspondence": "Corres-\npondence",
    "merger_agreement": "Merger\n(MAUD acc.)",
}
_LABEL = {folder: label for _, folder, label in SPECIALISTS}


def _postures():
    from mailroom_sandbox.job.grid_master import POSTURES

    return POSTURES


def figure_specs(data: Mapping[str, Any]) -> list[dict[str, str]]:
    """Figures to render, as ``{"key", "path" (relative to reports/SAND-37), "caption", "section"}``."""
    cards = data["cards"]
    present = [p for p in _postures() if cards[p.key]]
    specs: list[dict[str, str]] = []
    if not present:
        return specs
    specs += [
        {
            "key": "cmp-efficiency",
            "path": "figures/cmp-efficiency.png",
            "section": "comparison",
            "caption": "Pooled serving efficiency by posture: GPU cost per 1,000 documents, tokens per second per GPU, "
            "and documents per minute.",
        },
        {
            "key": "cmp-quality",
            "path": "figures/cmp-quality.png",
            "section": "comparison",
            "caption": "Primary quality metric by specialist and posture; labels mark failed documents. Merger "
            "is MAUD accuracy, a different scale from the field scores.",
        },
        {
            "key": "cmp-latency-cost",
            "path": "figures/cmp-latency-cost.png",
            "section": "comparison",
            "caption": "Per-document latency (bar p50, whisker p95) and GPU cost per 1,000 successful documents, "
            "by specialist and posture.",
        },
    ]
    if cards.get("s39-1l4-n50") and cards.get("s37-2l4-n50"):
        specs.append(
            {
                "key": "cmp-matched",
                "path": "figures/cmp-matched.png",
                "section": "comparison",
                "caption": "Matched-sample check: each point is one document scored under SAND-39 (1×L4 C8) and "
                "SAND-37 (2×L4 C32). Points on the diagonal mean the posture did not change the output's score.",
            }
        )
    for p in present:
        specs.append(
            {
                "key": f"posture-{p.key}",
                "path": f"{p.shape_dir}/figures/{p.study}-{p.replicas}xL4-C{p.concurrency}-n{p.n}.png",
                "section": "posture",
                "caption": f"{p.study} {p.label}: per-document score and latency distributions, cost per "
                "1,000 successful documents, and token mix by specialist.",
            }
        )
    return specs


# ── drawing ──────────────────────────────────────────────────────────────────


def _style(plt) -> None:
    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": "#e5e5e5",
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "legend.frameon": False,
            "savefig.dpi": 160,
        }
    )


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Strip the matplotlib version stamp so re-renders of unchanged data are byte-stable.
    fig.savefig(path, bbox_inches="tight", metadata={"Software": None}, facecolor="white")


def _legend_handles(postures):
    from matplotlib.patches import Patch

    return [Patch(color=COLORS[p.key], label=f"{p.study} {p.label}") for p in postures]


def _grouped(ax, present, cards, value, fmt=None, err=None):
    """Grouped bars: one group per specialist, one bar per posture present."""
    width = 0.8 / max(len(present), 1)
    for i, p in enumerate(present):
        for j, folder in enumerate(_ORDER):
            card = cards[p.key].get(folder)
            if not card:
                continue
            x = j - 0.4 + width * (i + 0.5)
            v = value(card)
            kw = {}
            if err:
                lo_hi = err(card)
                if lo_hi:
                    kw = {"yerr": [[0], [max(lo_hi - v, 0)]], "capsize": 2, "error_kw": {"lw": 0.8}}
            ax.bar(x, v, width * 0.92, color=COLORS[p.key], **kw)
            if fmt:
                label = fmt(card)
                if label:
                    ax.text(x, v, label, ha="center", va="bottom", fontsize=7, color="#b00020")
    ax.set_xticks(range(len(_ORDER)), [_SHORT[f] for f in _ORDER])


def _pooled_bars(ax, present, pooled, key, title, fmt):
    xs = range(len(present))
    vals = [pooled[p.key][key] or 0 for p in present]
    partial = {p.key: pooled[p.key]["cells"] < 5 for p in present}
    ax.bar(xs, vals, 0.6, color=[COLORS[p.key] for p in present])
    for x, v in zip(xs, vals):
        ax.text(x, v, fmt(v), ha="center", va="bottom", fontsize=8)
    ticks = [
        f"{p.study}\n{p.replicas}×L4 C{p.concurrency}\nn={p.n}" + (f"\n({pooled[p.key]['cells']} of 5 cells)" if partial[p.key] else "")
        for p in present
    ]
    ax.set_xticks(list(xs), ticks, fontsize=7)
    ax.set_title(title)
    ax.margins(y=0.15)


def _fig_efficiency(plt, present, pooled, path):
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.2))
    _pooled_bars(axes[0], present, pooled, "usd_per_kdoc", "GPU $ per 1,000 documents (lower is better)",
                 lambda v: f"${v:.2f}")
    axes[0].yaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    _pooled_bars(axes[1], present, pooled, "tps_per_gpu", "Tokens / s / GPU (higher is better)",
                 lambda v: f"{v:,.0f}")
    _pooled_bars(axes[2], present, pooled, "docs_per_minute", "Documents / minute (higher is better)",
                 lambda v: f"{v:.1f}")
    fig.suptitle("Serving efficiency, pooled across the five specialists", fontweight="bold", y=1.03)
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def _primary(card) -> float:
    clause = card["quality"].get("clause") or {}
    if clause.get("kind") == "maud":
        return float(clause.get("accuracy") or 0.0)
    return float(card["quality"]["overall_mean"] or 0.0)


def _fig_quality(plt, present, cards, path):
    fig, ax = plt.subplots(figsize=(10, 3.4))
    _grouped(ax, present, cards, _primary,
             fmt=lambda c: f"{c['quality']['errors']} err" if c["quality"]["errors"] else "")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Score (0–1)")
    ax.set_title("Extraction quality holds across postures; merger is input-limited")
    ax.legend(handles=_legend_handles(present), loc="upper right", fontsize=8)
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def _fig_latency_cost(plt, present, cards, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    _grouped(axes[0], present, cards, lambda c: c["latency"]["p50"], err=lambda c: c["latency"]["p95"])
    axes[0].set_ylabel("Seconds per document")
    axes[0].set_title("Latency: p50 bar, p95 whisker")
    _grouped(axes[1], present, cards, lambda c: c["cost"]["usd_per_ok_document"] * 1000)
    axes[1].yaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    axes[1].set_title("GPU $ per 1,000 successful documents")
    for ax in axes:
        ax.tick_params(axis="x", labelsize=7)
    fig.legend(handles=_legend_handles(present), loc="lower center", ncol=len(present), fontsize=8,
               bbox_to_anchor=(0.5, -0.08))
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def _fig_matched(plt, cards, path):
    a, b = cards["s39-1l4-n50"], cards["s37-2l4-n50"]
    folders = [f for f in _ORDER if f in a and f in b]
    fig, axes = plt.subplots(1, len(folders), figsize=(2.1 * len(folders), 2.4), squeeze=False)
    total = 0
    for ax, folder in zip(axes[0], folders):
        sa = {d["item_id"]: d["score"] for d in a[folder]["documents"]}
        sb = {d["item_id"]: d["score"] for d in b[folder]["documents"]}
        ids = [i for i in sa if i in sb and sa[i] is not None and sb[i] is not None]
        xs, ys = [sa[i] for i in ids], [sb[i] for i in ids]
        ax.plot([0, 1], [0, 1], color="#bbbbbb", lw=0.8, zorder=1)
        ax.scatter(xs, ys, s=10, alpha=0.7, color="#009E73", zorder=2)
        same = sum(abs(x - y) < 1e-9 for x, y in zip(xs, ys))
        mad = sum(abs(x - y) for x, y in zip(xs, ys)) / max(len(ids), 1)
        total += len(ids)
        ax.set_title(_LABEL[folder], fontsize=9)
        ax.text(0.03, 0.97, f"{same}/{len(ids)} identical\nmean |Δ| {mad:.3f}", transform=ax.transAxes,
                va="top", fontsize=7)
        ax.set_xlim(-0.03, 1.03)
        ax.set_ylim(-0.03, 1.03)
        ax.set_aspect("equal")
        ax.grid(True, axis="both")
        ax.set_xlabel("1×L4 C8", fontsize=8)
    axes[0][0].set_ylabel("2×L4 C32", fontsize=8)
    fig.suptitle(f"Per-document scores, same documents under both postures ({total} scored pairs)",
                 fontweight="bold", y=1.04)
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def _fig_posture(plt, p, cards, path):
    folders = [f for f in _ORDER if f in cards]
    labels = [_SHORT[f] for f in folders]
    color = COLORS[p.key]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6))

    scores = [[d["score"] for d in cards[f]["documents"] if d["score"] is not None] for f in folders]
    bp = axes[0][0].boxplot(scores, tick_labels=labels, patch_artist=True, widths=0.55,
                            medianprops={"color": "black"}, flierprops={"markersize": 3})
    for box in bp["boxes"]:
        box.set(facecolor=color, alpha=0.75)
    axes[0][0].set_ylim(0, 1)
    axes[0][0].set_title("Per-document score")

    lat = [[d["latency_seconds"] for d in cards[f]["documents"] if d.get("latency_seconds")] for f in folders]
    bp = axes[0][1].boxplot(lat, tick_labels=labels, patch_artist=True, widths=0.55,
                            medianprops={"color": "black"}, flierprops={"markersize": 3})
    for box in bp["boxes"]:
        box.set(facecolor=color, alpha=0.75)
    axes[0][1].set_ylabel("Seconds")
    axes[0][1].set_title("Per-document latency")

    xs = range(len(folders))
    cost = [cards[f]["cost"]["usd_per_ok_document"] * 1000 for f in folders]
    axes[1][0].bar(xs, cost, 0.6, color=color)
    for x, f, v in zip(xs, folders, cost):
        q = cards[f]["quality"]
        axes[1][0].text(x, v, f"{q['ok']}/{cards[f]['n']} ok", ha="center", va="bottom", fontsize=7)
    axes[1][0].set_xticks(list(xs), labels)
    axes[1][0].yaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    axes[1][0].set_title("GPU $ per 1,000 successful documents")
    axes[1][0].margins(y=0.15)

    prompt = [cards[f]["tokens"]["prompt"] / max(cards[f]["n"], 1) for f in folders]
    compl = [cards[f]["tokens"]["completion"] / max(cards[f]["n"], 1) for f in folders]
    axes[1][1].bar(xs, prompt, 0.6, color=color, alpha=0.45, label="Prompt")
    axes[1][1].bar(xs, compl, 0.6, bottom=prompt, color=color, label="Completion")
    axes[1][1].set_xticks(list(xs), labels)
    axes[1][1].yaxis.set_major_formatter(lambda v, _: f"{v / 1000:.0f}K")
    axes[1][1].set_title("Mean tokens per document")
    axes[1][1].legend(fontsize=8, loc="upper left")

    for row in axes:
        for ax in row:
            ax.tick_params(axis="x", labelsize=7)
    fig.suptitle(f"{p.study} · {p.label} · posture dashboard", fontweight="bold")
    fig.tight_layout()
    _save(fig, path)
    plt.close(fig)


def write_figures(data: Mapping[str, Any], repo: Path | None = None) -> list[Path]:
    """Render every figure in ``figure_specs(data)``; returns the written paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from mailroom_sandbox.job.grid_master import _pooled
    from mailroom_sandbox.paths import repo_root

    _style(plt)
    root = (repo or repo_root()) / ROOT_REL
    cards = data["cards"]
    present = [p for p in _postures() if cards[p.key]]
    pooled = {p.key: _pooled(cards[p.key], p.replicas) for p in present}
    for q in pooled.values():
        q["usd_per_kdoc"] = (q["usd_per_document"] or 0) * 1000
    by_key = {p.key: p for p in present}
    written: list[Path] = []
    for spec in figure_specs(data):
        path = root / spec["path"]
        key = spec["key"]
        if key == "cmp-efficiency":
            _fig_efficiency(plt, present, pooled, path)
        elif key == "cmp-quality":
            _fig_quality(plt, present, cards, path)
        elif key == "cmp-latency-cost":
            _fig_latency_cost(plt, present, cards, path)
        elif key == "cmp-matched":
            _fig_matched(plt, cards, path)
        elif key.startswith("posture-"):
            p = by_key[key.removeprefix("posture-")]
            _fig_posture(plt, p, cards[p.key], path)
        written.append(path)
    return written
