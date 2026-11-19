"""House style for every experiment figure: colour roles, typography, layout and a text lint (offline).

One module so a decision-model run, an LLM-sorter run and a comparison of the two read as one
system (``.claude/skills/experiment-figures/SKILL.md`` is the method; this is its implementation).

Colour follows the role, never the order a figure happens to draw things in:

- **System** (who produced the answer): decision model blue, LLM sorter orange, a third system
  aqua. These are categorical slots 1-3 of the validated reference palette, the three that pass
  every all-pairs check, so they are safe on scatter plots too. A figure of one run uses its
  system's colour for single-series marks, so a run's figures are recognisable at a glance.
- **Reference vs candidate** of the same system (question set 4.0.1 vs 4.0.2): reference neutral
  grey, candidate the system colour.
- **Outcome state**: archived correct green, parked amber, misarchived red, unscored grey (status
  colours, always with a text label).
- **Passed vs parked** points: passed slate, parked amber (the same amber as "parked" bars).

Typography: layout is measured with DejaVu Sans, which ships with matplotlib, so an SVG is
byte-identical on macOS and on Linux CI; the SVG then declares the system sans stack, which is
narrower, so text always fits. One type scale (points) for every figure, title flush with the
figure's left edge (not the axes'), subtitle under it, source line at the bottom.

Text conventions are checked by ``lint_svg`` (and ``python -m mailroom_sandbox.figure_style lint``):
sentence case, no trailing full stop, no snake_case identifiers, length limits. Run ids belong in
the source line, never in a title.
"""
from __future__ import annotations

import io
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- colour roles

SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
NEUTRAL = "#b4b2a9"                           # reference arm, unscored, "no truth"

DECISION, LLM, THIRD = "#2a78d6", "#eb6834", "#1baf7a"   # categorical slots 1-3 (all-pairs safe)
SYSTEM_COLOURS = {"decision": DECISION, "llm": LLM, "other": THIRD}
SYSTEM_NAMES = {"decision": "Decision model", "llm": "LLM sorter", "other": "Other system"}

GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"  # status: outcome states
PASSED, PARKED = INK_2, WARNING

STATES = (  # (key, legend label, colour); also the stacking order
    ("correct", "Archived, correct", GOOD),
    ("parked", "Parked for review", WARNING),
    ("misarchived", "Misarchived", CRITICAL),
    ("unscored", "Archived, no truth class", NEUTRAL),
    ("failed", "Failed, no answer", INK_2),
)

# ---------------------------------------------------------------- typography

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Helvetica, Arial, "DejaVu Sans", sans-serif'
SIZE = {"title": 12.0, "subtitle": 9.5, "label": 9.0, "tick": 8.5, "annotation": 8.5, "legend": 9.0,
        "source": 7.5}
WIDTH = 6.4  # inches: one column of a report page
TITLE_MAX, SUBTITLE_MAX, LABEL_MAX = 80, 120, 60


def system_of_task(task: str | None) -> str:
    """``decision`` / ``llm`` / ``other`` from a run's task (``sorter_reviewer`` is the decision model)."""
    if task == "sorter_reviewer":
        return "decision"
    if task in ("sorter", "isolated"):
        return "llm"
    return "other"


def humanize(token: str) -> str:
    """``corporate_record`` -> ``Corporate record``; a ``key:value`` reason -> ``Key: value``."""
    text = str(token).replace("_", " ").replace(":", ": ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:1].upper() + text[1:]


def short_model(model: str) -> str:
    return str(model).rsplit("/", 1)[-1]


class Fig:
    """matplotlib under the house rc; ``svg()`` returns deterministic, linted-ready SVG text."""

    def __init__(self, salt: str):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        self.plt = plt
        self.rc = matplotlib.rc_context({
            "svg.hashsalt": salt, "svg.fonttype": "none", "path.simplify": True,
            "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": SIZE["tick"],
            "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK_2,
            "axes.labelsize": SIZE["label"], "axes.labelpad": 6,
            "axes.spines.top": False, "axes.spines.right": False,
            "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
            "xtick.labelsize": SIZE["tick"], "ytick.labelsize": SIZE["tick"],
            "xtick.major.size": 3, "ytick.major.size": 3,
            "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
            "legend.frameon": False, "legend.fontsize": SIZE["legend"], "legend.handlelength": 1.2,
            "legend.columnspacing": 1.6, "text.color": INK, "axes.unicode_minus": True,
        })

    def __enter__(self) -> Fig:
        self.rc.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self.rc.__exit__(*exc)

    def svg(self, fig: Any) -> str:
        _place_heading(fig)
        buf = io.StringIO()
        fig.savefig(buf, format="svg", metadata={"Date": None, "Creator": None}, bbox_inches="tight",
                    pad_inches=0.18)
        self.plt.close(fig)
        return system_fonts(buf.getvalue())


def system_fonts(svg: str) -> str:
    """Declare the system font stack in an SVG measured with DejaVu Sans (the system sans is
    narrower, so nothing overflows). Handles matplotlib's longhand ``font-family`` and 3.8's
    shorthand ``font: [style weight] <size>px <family>``."""
    stack = FONT_STACK.replace('"', "'")
    svg = re.sub(r"font-family: [^;\"]+", "font-family: " + stack, svg)
    return re.sub(r"(font: (?:[^;\"]*? )?[0-9.]+px) [^;\"]+", r"\1 " + stack, svg)


def heading(fig: Any, ax: Any, title: str, subtitle: str | None = None, source: str | None = None) -> None:
    """Record the title, subtitle and source line; ``Fig.svg`` places them once the layout is known."""
    fig._house_heading = (ax, title, subtitle, source)


def _place_heading(fig: Any) -> None:
    spec = getattr(fig, "_house_heading", None)
    if not spec:
        return
    from matplotlib.transforms import offset_copy

    ax, title, subtitle, source = spec
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    axes = fig.get_axes()
    left = min(min(a.get_tightbbox(renderer).x0 for a in axes), ax.bbox.x0) / fig.bbox.width
    top = max(a.bbox.y1 for a in axes) / fig.bbox.height
    base = fig.transFigure
    sub_gap = 12 if subtitle else 0
    t = fig.text(left, top, title, transform=offset_copy(base, fig=fig, y=sub_gap + 12, units="points"),
                 fontsize=SIZE["title"], fontweight="bold", color=INK, va="bottom", ha="left")
    t.set_gid("title")
    if subtitle:
        s = fig.text(left, top, subtitle, transform=offset_copy(base, fig=fig, y=10, units="points"),
                     fontsize=SIZE["subtitle"], color=INK_2, va="bottom", ha="left")
        s.set_gid("subtitle")
    if source:
        bottom = min(a.get_tightbbox(renderer).y0 for a in axes) / fig.bbox.height
        legends = [a.get_legend() for a in axes if a.get_legend()]
        if legends:
            bottom = min([bottom] + [lg.get_window_extent(renderer).y0 / fig.bbox.height for lg in legends])
        n = fig.text(left, bottom, source, transform=offset_copy(base, fig=fig, y=-8, units="points"),
                     fontsize=SIZE["source"], color=MUTED, va="top", ha="left")
        n.set_gid("source")


def axis_labels(ax: Any, x: str | None = None, y: str | None = None) -> None:
    if x is not None:
        ax.set_xlabel(x)
        ax.xaxis.label.set_gid("xlabel")
    if y is not None:
        ax.set_ylabel(y)
        ax.yaxis.label.set_gid("ylabel")


def legend_below(fig: Any, ax: Any, ncol: int, **kw: Any) -> Any:
    """Legend centred under the x-axis label, a fixed 8 pt below it whatever the figure height."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    low = min(ax.xaxis.get_tightbbox(renderer).y0, ax.bbox.y0)
    y = (low - ax.bbox.y0) / (ax.bbox.height or 1) - 8 / 72 * fig.dpi / (ax.bbox.height or 1)
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, y), ncol=ncol, **kw)
    for i, text in enumerate(leg.get_texts()):
        text.set_gid(f"legend-{i}")
    return leg


def value_axis(ax: Any, axis: str = "x") -> None:
    """Gridlines on the value axis only, behind the marks; no tick marks on the category axis."""
    (ax.xaxis if axis == "x" else ax.yaxis).grid(True)
    ax.tick_params(axis="y" if axis == "x" else "x", length=0)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------- statistics shared by figures

def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n (stays inside [0, 1] at small n)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def fmt_seconds(s: float) -> str:
    if s >= 3600:
        return f"{s / 3600:.1f} h"
    if s >= 120:
        return f"{s / 60:.1f} min"
    return f"{s:.1f} s" if s >= 10 else f"{s:.2f} s"


# ---------------------------------------------------------------- text lint

_GID_TEXT = re.compile(r'<g id="(title|subtitle|xlabel|ylabel|legend-\d+|source)"[^>]*>(.*?)</g>', re.S)
_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.S)
_SNAKE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")
_FONT_SIZE = re.compile(r"(?:font-size: |font: (?:[^;\"]*? )?)([0-9.]+)px")  # longhand, or 3.8's shorthand


def lint_text(kind: str, text: str) -> list[str]:
    """Problems with one piece of figure text under the house conventions (empty when clean)."""
    problems = []
    t = text.strip()
    if not t:
        return [f"{kind}: empty"]
    if kind == "source":
        return [f"source: over {SUBTITLE_MAX} characters"] if len(t) > SUBTITLE_MAX else []
    limit = {"title": TITLE_MAX, "subtitle": SUBTITLE_MAX}.get(kind, LABEL_MAX)
    if len(t) > limit:
        problems.append(f"{kind}: {len(t)} characters, over {limit}: {t!r}")
    if t[0].isalpha() and not t[0].isupper():
        problems.append(f"{kind}: starts lower-case (use sentence case): {t!r}")
    if kind in ("title", "xlabel", "ylabel") and t.endswith("."):
        problems.append(f"{kind}: ends with a full stop: {t!r}")
    if _SNAKE.search(t):
        problems.append(f"{kind}: contains an identifier ({_SNAKE.search(t).group(0)}); humanize it: {t!r}")
    if kind == "title" and re.search(r"\brb1-|\bDOC-", t):
        problems.append(f"title: names a run or document id (put it in the source line): {t!r}")
    if re.search(r"[A-Za-z]\(s\)", t):  # "error(s)"; a unit "(s)" after a space is fine
        problems.append(f"{kind}: hedged plural '(s)'; agree the noun with its number: {t!r}")
    if kind in ("title", "xlabel", "ylabel") and re.search(r"\b(\w+) \1\b", t, re.I):
        problems.append(f"{kind}: repeated word: {t!r}")
    return problems


def _unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&#x27;", "'"))


def lint_svg(svg: str) -> list[str]:
    """Check a house figure: a title exists, every tagged text passes ``lint_text``, nothing is set
    below the source-line size, and the system font stack is declared."""
    problems = []
    found = {}
    for gid, body in _GID_TEXT.findall(svg):
        texts = [_unescape(t) for t in _TEXT.findall(body)]
        kind = "legend" if gid.startswith("legend") else gid
        for t in texts:
            found.setdefault(kind, []).append(t)
            problems += lint_text(kind, t)
    if "title" not in found:
        problems.append("no title")
    sizes = [float(s) for s in _FONT_SIZE.findall(svg)]
    if sizes and min(sizes) < SIZE["source"] - 0.01:
        problems.append(f"text set at {min(sizes)} pt, below the {SIZE['source']} pt floor")
    if "system-ui" not in svg:
        problems.append("SVG does not declare the system font stack")
    return problems


def lint_paths(paths: Iterable[Path]) -> dict[str, list[str]]:
    return {str(p): probs for p in paths if (probs := lint_svg(Path(p).read_text(encoding="utf-8")))}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "lint" or len(args) < 2:
        print("usage: python -m mailroom_sandbox.figure_style lint <file.svg|dir> ...", file=sys.stderr)
        return 2
    paths: list[Path] = []
    for a in args[1:]:
        p = Path(a)
        paths += sorted(p.rglob("*.svg")) if p.is_dir() else [p]
    bad = lint_paths(paths)
    for path, probs in bad.items():
        for prob in probs:
            print(f"{path}: {prob}")
    print(f"{len(paths)} figure(s) checked, {len(bad)} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
