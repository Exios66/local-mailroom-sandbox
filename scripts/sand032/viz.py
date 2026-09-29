"""SAND-032 chart kit — /dataviz method, reference palette (validated light + dark).

Forms (chosen before color, per choosing-a-form.md):
  * hbar      — one series of magnitudes (single hue slot 1; no legend box — the
                title names it); optional EMPHASIS (kept = accent, rest = gray)
  * dumbbell  — before → after per item (two series, slots 1 & 2, legend + labels)
  * small_multiples — one axis per metric, never a dual axis
Marks (marks-and-anatomy.md): bars <= 24px thick (we use 14), 4px rounded data-end,
square at the baseline, 2px surface gap between adjacent bars, 1px solid hairline
grid, clean ticks, text in text tokens (never the series color), selective labels
(value at bar tip only). Every mark has a <title> (native hover); every figure is
paired with a markdown table (the table-view twin). Dark mode is SELECTED: its own
validated steps under prefers-color-scheme, not an automatic flip.
Palette validated with scripts/validate_palette.js:
  light #2a78d6,#eb6834 → ALL PASS (CVD ΔE 24.7, normal 33.6, contrast ≥3:1)
  dark  #3987e5,#d95926 → ALL PASS (CVD ΔE 26.8, normal 31.8, contrast ≥3:1)
"""
from __future__ import annotations

import html
import math

STYLE = """
<style>
  .viz { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --s1:#2a78d6; --s2:#eb6834; --deemph:#c3c2b7;
    --good:#0ca30c; --critical:#d03b3b; }
  @media (prefers-color-scheme: dark) {
    .viz { --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --axis:#383835; --s1:#3987e5; --s2:#d95926; --deemph:#52514e; }
  }
  .viz .bg { fill: var(--surface); }
  .viz .title { fill: var(--ink); font-size: 15px; font-weight: 600; }
  .viz .sub { fill: var(--ink2); font-size: 12px; }
  .viz .lbl { fill: var(--ink2); font-size: 12px; }
  .viz .val { fill: var(--ink); font-size: 12px; font-variant-numeric: tabular-nums;
    paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }
  .viz .reflbl { paint-order: stroke; stroke: var(--surface); stroke-width: 3px; }
  .viz .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  .viz .grid { stroke: var(--grid); stroke-width: 1; }
  .viz .axis { stroke: var(--axis); stroke-width: 1; }
  .viz .ref { stroke: var(--ink2); stroke-width: 1; }
  .viz .reflbl { fill: var(--ink2); font-size: 11px; }
  .viz .s1 { fill: var(--s1); } .viz .s2 { fill: var(--s2); }
  .viz .ln1 { stroke: var(--s1); } .viz .ln2 { stroke: var(--s2); }
  .viz .deemph { fill: var(--deemph); }
  .viz .conn { stroke: var(--axis); stroke-width: 2; }
  .viz .ring { stroke: var(--surface); stroke-width: 2; }
</style>
"""

BAR = 14          # bar thickness (<= 24)
GAP = 2           # surface gap between adjacent bars
ROW = BAR + 10    # band per row (leftover band is air)


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


# Approximate advance widths (em) for system-ui sans. Deliberately a little
# generous: labels are laid out from these, so an under-estimate clips text
# (the 0.x figures cut doc-id labels off the left edge at a fixed 190px).
_NARROW = set("il.,:;|!'`·()[]{} ")
_WIDE = set("MWmw@%")


def text_w(s: str, px: float = 12) -> float:
    """Estimated rendered width of ``s`` at font size ``px``."""
    em = 0.0
    for ch in str(s):
        # Calibrated against DejaVu Sans (the widest common system-ui fallback,
        # used by headless Chromium on Linux), so other platforms only gain air.
        if ch in _NARROW:
            em += 0.34
        elif ch in _WIDE:
            em += 0.92
        elif ch.isupper() or ch in "_—–×":
            em += 0.72
        elif ch.isdigit():
            em += 0.64
        else:
            em += 0.61
    return em * px


def fit_label(s: str, max_w: float, px: float = 12) -> str:
    """Middle-truncate with an ellipsis so ``s`` fits ``max_w`` (full text stays in the <title>)."""
    s = str(s)
    if text_w(s, px) <= max_w:
        return s
    keep = len(s)
    while keep > 4 and text_w(s[: keep // 2] + "…" + s[len(s) - keep // 2:], px) > max_w:
        keep -= 1
    return s[: keep // 2] + "…" + s[len(s) - keep // 2:]


def _ref_lane(refs_px: list[tuple[float, str]], plot_r: float, px: float = 11) -> list[tuple[float, int, str]]:
    """Place reference-line labels in a lane above the plot: (x, row, text).

    Labels sit right of their line unless that would run off the plot, and drop
    to a second row when they would collide (p50/p95 on a tight distribution)."""
    placed: list[tuple[float, float, int, str]] = []
    for x, lab in sorted(refs_px):
        w = text_w(lab, px)
        x0 = x + 4 if x + 4 + w <= plot_r + 60 else x - 4 - w
        row = 0
        for (a, b, r, _) in placed:
            if r == row and not (x0 + w + 6 < a or x0 > b + 6):
                row = 1
        placed.append((x0, x0 + w, row, lab))
    return [(a, r, lab) for a, _, r, lab in placed]


def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    """Clean round ticks 0..>=vmax (1/2/2.5/5 × 10^k)."""
    if vmax <= 0:
        return [0.0, 1.0]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    ticks, t = [], 0.0
    while t < vmax - 1e-12:
        ticks.append(round(t, 10))
        t += step
    ticks.append(round(t, 10))
    return ticks


def _fmt_tick(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v == int(v):
        return f"{int(v)}"
    return f"{v:g}"


def _bar_path(x0: float, y: float, length: float, h: float, r: float = 4) -> str:
    """Horizontal bar: square at the baseline (x0), 4px rounded data-end."""
    if length <= 0:
        return ""
    r = min(r, length, h / 2)
    x1 = x0 + length
    return (f"M{x0:.1f},{y:.1f} H{x1 - r:.1f} Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x1:.1f},{y + h:.1f} {x1 - r:.1f},{y + h:.1f} H{x0:.1f} Z")


def hbar(title: str, subtitle: str, rows: list[dict], *, unit: str = "", fmt=None,
         refs: list[tuple[float, str]] | None = None, width: int = 720, label_w: int = 190,
         max_label_w: int = 320) -> str:
    """rows: [{label, value, emphasis(bool, default True), note(optional)}].

    ``label_w`` is a minimum: the label column grows to fit the longest label
    (capped at ``max_label_w``, beyond which labels are middle-ellipsized with
    the full text kept in the hover <title>), and the figure widens with it so
    the plot keeps its length."""
    fmt = fmt or (lambda v: f"{v:g}")
    vals = [r["value"] for r in rows if r.get("value") is not None]
    ticks = nice_ticks(max(vals + [x for x, _ in (refs or [])] or [1]))
    vmax = ticks[-1]
    need = max([text_w(r["label"]) for r in rows] or [0]) + 12  # label sits 8px left of the axis
    label_w = math.ceil(max(label_w, min(need + 2, max_label_w)))
    plot_len = width - 70 - 190  # the plot length a default-label figure gets
    width = max(width, label_w + plot_len + 70, int(text_w(title, 15)) + 32, int(text_w(subtitle)) + 32)
    lane = 30 if refs else 0  # reference labels get their own lane under the subtitle
    top, plot_l, plot_r = 58 + lane, label_w, width - 70
    plot_h = len(rows) * ROW
    h = top + plot_h + 34
    sx = lambda v: plot_l + (plot_r - plot_l) * (v / vmax if vmax else 0)  # noqa: E731
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {width} {h}" width="{width}" '
         f'height="{h}" role="img" aria-label="{_esc(title)}">', STYLE,
         f'<rect class="bg" width="{width}" height="{h}" rx="8"/>',
         f'<text class="title" x="16" y="24">{_esc(title)}</text>',
         f'<text class="sub" x="16" y="42">{_esc(subtitle)}</text>']
    for t in ticks:
        x = sx(t)
        o.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{top + plot_h}"/>')
        o.append(f'<text class="tick" x="{x:.1f}" y="{top + plot_h + 16}" text-anchor="middle">{_fmt_tick(t)}{unit}</text>')
    o.append(f'<line class="axis" x1="{plot_l}" y1="{top - 4}" x2="{plot_l}" y2="{top + plot_h}"/>')
    for x, _lab in refs or []:  # reference lines sit BEHIND the marks
        px = sx(x)
        o.append(f'<line class="ref" x1="{px:.1f}" y1="{top - lane + 4}" x2="{px:.1f}" y2="{top + plot_h}"/>')
    for x0, row, lab in _ref_lane([(sx(x), lab) for x, lab in refs or []], plot_r):
        o.append(f'<text class="reflbl" x="{x0:.1f}" y="{top - lane + 12 + row * 13}">{_esc(lab)}</text>')
    for i, r in enumerate(rows):
        y = top + i * ROW + (ROW - BAR) / 2
        shown = fit_label(r["label"], plot_l - 12)
        full = f'<title>{_esc(r["label"])}</title>' if shown != r["label"] else ""
        o.append(f'<text class="lbl" x="{plot_l - 8}" y="{y + BAR - 3}" text-anchor="end">{full}{_esc(shown)}</text>')
        v = r.get("value")
        if v is None:
            o.append(f'<text class="tick" x="{plot_l + 6}" y="{y + BAR - 3}">n/a</text>')
            continue
        cls = "s1" if r.get("emphasis", True) else "deemph"
        tip = f'{r["label"]}: {fmt(v)}{unit}' + (f' — {r["note"]}' if r.get("note") else "")
        o.append(f'<path class="{cls}" d="{_bar_path(plot_l, y, sx(v) - plot_l, BAR)}"><title>{_esc(tip)}</title></path>')
        o.append(f'<text class="val" x="{sx(v) + 6:.1f}" y="{y + BAR - 3}">{_esc(fmt(v))}{_esc(unit)}</text>')
    o.append("</svg>")
    return "\n".join(o)


def dumbbell(title: str, subtitle: str, rows: list[dict], names: tuple[str, str], *, unit: str = "",
             fmt=None, width: int = 720, label_w: int = 190, val=None) -> str:
    """rows: [{label, a, b}] — before (slot 1) → after (slot 2) on ONE axis.

    ``val(row) -> str`` overrides the end-of-row value label (default: the
    slot-2 value); the right margin grows to fit the longest one.
    """
    fmt = fmt or (lambda v: f"{v:g}")
    val = val or (lambda r: f"{fmt(r['b'])}{unit}")
    vals = [v for r in rows for v in (r["a"], r["b"]) if v is not None]
    ticks = nice_ticks(max(vals or [1]))
    vmax = ticks[-1]
    label_w = math.ceil(max(label_w, min(max([text_w(r["label"]) for r in rows] or [0]) + 14, 320)))
    width = max(width, label_w + 450, int(text_w(title, 15)) + 32, int(text_w(subtitle)) + 32)
    right_w = max(80, math.ceil(max([text_w(val(r)) for r in rows] or [0])) + 24)
    width = max(width, label_w + 370 + right_w)
    top, plot_l, plot_r = 78, label_w, width - right_w
    leg2 = 22 + 10 + text_w(names[0]) + 20
    plot_h = len(rows) * (ROW + 6)
    h = top + plot_h + 34
    sx = lambda v: plot_l + (plot_r - plot_l) * (v / vmax if vmax else 0)  # noqa: E731
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {width} {h}" width="{width}" '
         f'height="{h}" role="img" aria-label="{_esc(title)}">', STYLE,
         f'<rect class="bg" width="{width}" height="{h}" rx="8"/>',
         f'<text class="title" x="16" y="24">{_esc(title)}</text>',
         f'<text class="sub" x="16" y="42">{_esc(subtitle)}</text>',
         # legend (always present for >= 2 series): marker keys + text-token labels
         f'<circle class="s1" cx="22" cy="58" r="5"/><text class="lbl" x="32" y="62">{_esc(names[0])}</text>',
         f'<circle class="s2" cx="{leg2:.0f}" cy="58" r="5"/>'
         f'<text class="lbl" x="{leg2 + 10:.0f}" y="62">{_esc(names[1])}</text>']
    for t in ticks:
        x = sx(t)
        o.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{top + plot_h}"/>')
        o.append(f'<text class="tick" x="{x:.1f}" y="{top + plot_h + 16}" text-anchor="middle">{_fmt_tick(t)}{unit}</text>')
    for i, r in enumerate(rows):
        cy = top + i * (ROW + 6) + (ROW + 6) / 2
        o.append(f'<text class="lbl" x="{plot_l - 8}" y="{cy + 4}" text-anchor="end">{_esc(fit_label(r["label"], plot_l - 12))}</text>')
        if r["a"] is None or r["b"] is None:
            continue
        xa, xb = sx(r["a"]), sx(r["b"])
        o.append(f'<line class="conn" x1="{xa:.1f}" y1="{cy}" x2="{xb:.1f}" y2="{cy}"/>')
        for cls, x, v, nm in (("s1", xa, r["a"], names[0]), ("s2", xb, r["b"], names[1])):
            o.append(f'<circle class="{cls} ring" cx="{x:.1f}" cy="{cy}" r="5"><title>'
                     f'{_esc(r["label"])} · {_esc(nm)}: {_esc(fmt(v))}{_esc(unit)}</title></circle>')
        right = max(xa, xb)
        o.append(f'<text class="val" x="{right + 10:.1f}" y="{cy + 4}">{_esc(val(r))}</text>')
    o.append("</svg>")
    return "\n".join(o)


def small_multiples(title: str, panels: list[str], cols: int = 2) -> str:
    """Stack independent single-axis panels (each its own <svg>) in a grid SVG."""
    import re

    sizes = [tuple(int(x) for x in re.search(r'viewBox="0 0 (\d+) (\d+)"', p).groups()) for p in panels]
    pw = max(w for w, _ in sizes)
    rows_h, y, out = [], 36, []
    for i in range(0, len(panels), cols):
        chunk = panels[i:i + cols]
        rh = max(sizes[i + j][1] for j in range(len(chunk)))
        for j, p in enumerate(chunk):
            out.append(f'<g transform="translate({j * (pw + 16)},{y})">{p}</g>')
        y += rh + 16
    W = cols * pw + (cols - 1) * 16
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {W} {y}" width="{W}" height="{y}" '
            f'role="img" aria-label="{_esc(title)}">{STYLE}<rect class="bg" width="{W}" height="{y}" rx="8"/>'
            f'<text class="title" x="16" y="24">{_esc(title)}</text>{"".join(out)}</svg>')
