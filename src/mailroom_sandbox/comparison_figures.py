"""Figures comparing sorter arms (LLM sorter vs decision model as sorter, H5), offline.

Built from the ``sorter_arms.compare`` report (and, for the latency strip, each arm's per-document
latencies), so every number in a figure is a number in ``comparison.json``:

- ``runtime``: total wall-clock run time per arm on the same documents, with throughput, the
  speed-up over the reference and hours per 100k documents.
- ``latency``: per-document latency per arm (log scale), median marked.
- ``quality``: candidate minus reference on class accuracy, class macro-F1 and subclass-unit
  accuracy, 95% paired-bootstrap intervals, with the pre-registered non-inferiority margins.
- ``routing``: per arm, auto-routed and right, auto-routed and wrong, parked for a person, failed.
- ``cost-quality``: cost per 1,000 documents at the compared documents' mix against subclass-unit
  accuracy. Its title names a cheaper arm only when every arm's cost is billed and at least
  ``COST_CLAIM_MIN_DOCS`` paired documents were compared; otherwise it says why cost is not yet
  comparable. A per-document cost depends on the document-length mix, so a small sample is not a
  price comparison.
- ``pricing``: each arm's list input price per million tokens against prompt size, from
  ``config/api_prices.yaml`` (OpenRouter's sheet), with the compared documents' prompt sizes
  marked. This is the ground truth any cost figure rests on.

Colour follows the system (``figure_style.SYSTEM_COLOURS``), never the arm's position.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mailroom_sandbox import figure_style as fs, sorter_arms

# A cost direction ("costs more", "cheaper") is a claim only on billed costs over at least this many
# paired documents; below it, or with any arm priced from the sheet, the figure says it is not comparable.
COST_CLAIM_MIN_DOCS = sorter_arms.COST_CLAIM_MIN_DOCS

# (difference key, label, margin key, non-inferiority test key in the report)
MEASURES = (("class_accuracy", "Class accuracy", None, None),
            ("class_macro_f1", "Class macro-F1", "class_macro_f1", "noninferiority_macro_f1"),
            ("unit_accuracy", "Subclass-unit accuracy", "unit_accuracy", "noninferiority_unit"))


def _system(arm: Mapping[str, Any]) -> str:
    return fs.system_of_task(arm.get("task"))


def arm_labels(arms: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """``run_id -> label``: the system name, plus the model when one system ran several models, plus
    the run-id words that tell apart arms still sharing a label (``Decision model, smoke20c``)."""
    out = {}
    for a in arms:
        sysname = fs.SYSTEM_NAMES[_system(a)]
        models = {x["model"] for x in arms if _system(x) == _system(a)}
        out[a["run_id"]] = sysname if len(models) == 1 else f"{sysname}, {fs.short_model(a['model'])}"
    for label in set(out.values()):
        same = [rid for rid, lab in out.items() if lab == label]
        if len(same) < 2:
            continue
        common = set.intersection(*(set(rid.split("-")) for rid in same))
        for rid in same:
            extra = [w for w in rid.split("-") if w not in common]
            out[rid] = f"{label}, {' '.join(extra) or rid}"
    return out


def _group(arms: Sequence[Mapping[str, Any]], ref: Mapping[str, Any]) -> tuple[str, list[Mapping[str, Any]]] | None:
    """The non-reference arms when they are all one system: ``("the decision model" | "decision model
    runs", arms)``; ``None`` when they mix systems."""
    others = [a for a in arms if a is not ref]
    systems = {_system(a) for a in others}
    if len(systems) != 1:
        return None
    name = fs.SYSTEM_NAMES[systems.pop()]
    return (f"the {_lower(name)}" if len(others) == 1 else f"{_lower(name)} runs"), others


def _span(values: Sequence[float], fmt: str) -> str:
    lo, hi = min(values), max(values)
    return format(lo, fmt) if format(lo, fmt) == format(hi, fmt) else f"{format(lo, fmt)}–{format(hi, fmt)}"


def _lower(s: str) -> str:
    return s if s.startswith("LLM") else s[:1].lower() + s[1:]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _ref(report: Mapping[str, Any], arms: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return next((a for a in arms if a["run_id"] == report["reference"]), arms[0])


def _seconds(arm: Mapping[str, Any]) -> float | None:
    rt = arm.get("runtime") or {}
    return rt.get("run_wall_seconds") or rt.get("active_seconds")


def _source(report: Mapping[str, Any]) -> str:
    key = report.get("experiment_key") or "sorter arms"
    scope = f"set {report['set']}" if report.get("set") else "all paired documents"
    return f"Source: {key} sorter-arm comparison · {scope} · reference {report['reference']}"


def _runtime(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str]) -> str | None:
    arms = [a for a in report["arms"] if _seconds(a)]
    if not arms:
        return None
    ref = next((a for a in arms if a["run_id"] == report["reference"]), arms[0])
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.5 * len(arms) + 1.4))
    y = list(range(len(arms)))[::-1]
    secs = [_seconds(a) for a in arms]
    ax.barh(y, secs, color=[fs.SYSTEM_COLOURS[_system(a)] for a in arms], height=0.56)
    for yi, a, s in zip(y, arms, secs):
        # rates from the same seconds the bar shows, so bar, rate and speed-up agree
        answered = (a.get("runtime") or {}).get("answered") or a.get("n") or report.get("n") or 0
        per_min = answered / s * 60 if s else 0
        bits = [fs.fmt_seconds(s)]
        if per_min:
            bits += [f"{per_min:.0f} documents/min", f"{100_000 / per_min / 60:.1f} h per 100k"]
        ax.text(s + max(secs) * 0.015, yi, " · ".join(bits), va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_yticks(y, [labels[a["run_id"]] for a in arms])
    ax.set_xlim(0, max(secs) * 1.75)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "Total run time (s)")
    n = report.get("n")
    grp = _group(arms, ref)
    ratios = [_seconds(ref) / _seconds(o) for o in (grp[1] if grp else [])]
    if grp and all(r > 1 for r in ratios):
        title = f"{_cap(grp[0])} finished {_span(ratios, '.1f')}× faster than the {_lower(labels[ref['run_id']])}"
    elif grp and all(r < 1 for r in ratios):
        title = f"{_cap(grp[0])} took {_span([1 / r for r in ratios], '.1f')}× longer than the {_lower(labels[ref['run_id']])}"
    else:
        fastest = min(arms, key=_seconds)
        title = f"The {_lower(labels[fastest['run_id']])} finished first, in {fs.fmt_seconds(_seconds(fastest))}"
    if len(title) > fs.TITLE_MAX:
        title = "Total run time per arm on the same documents"
    conc = sorted({(a.get("runtime") or {}).get("concurrency") for a in arms} - {None})
    sub = f"Wall-clock run time on the same {n} documents"
    sub += f" at concurrency {conc[0]}" if len(conc) == 1 else " · concurrency differs, compare per-worker rates"
    fs.heading(fig, ax, title, sub, _source(report))
    return f.svg(fig)


def _latency(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str],
             latencies: Mapping[str, Sequence[float]]) -> str | None:
    import hashlib

    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    arms = [a for a in report["arms"] if latencies.get(a["run_id"])]
    if not arms:
        return None
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.55 * len(arms) + 1.4))
    y = list(range(len(arms)))[::-1]
    allv = []
    medians = {}
    for yi, a in zip(y, arms):
        vals = sorted(float(v) for v in latencies[a["run_id"]] if v and v > 0)
        allv += vals
        jit = [(int(hashlib.sha256(f"{a['run_id']}{i}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF - 0.5) * 0.36
               for i in range(len(vals))]
        ax.scatter(vals, [yi + j for j in jit], s=24, color=fs.SYSTEM_COLOURS[_system(a)], alpha=0.85,
                   edgecolors=fs.SURFACE, linewidths=0.8, zorder=3)
        med = vals[len(vals) // 2]
        medians[a["run_id"]] = med
        ax.plot([med, med], [yi - 0.3, yi + 0.3], color=fs.INK, linewidth=2, zorder=4)
        ax.text(med, yi + 0.34, f"median {med:.2f} s", ha="center", va="bottom", fontsize=fs.SIZE["annotation"],
                color=fs.INK)
    ax.set_xscale("log")
    lo, hi = min(allv), max(allv)
    ticks = [m * 10 ** e for e in range(-2, 5) for m in (1, 2, 5) if lo / 1.5 <= m * 10 ** e <= hi * 1.5]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_yticks(y, [labels[a["run_id"]] for a in arms])
    ax.set_ylim(-0.6, len(arms) - 0.2)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "Latency per document (s, log scale)")
    ref = _ref(report, arms)
    grp = _group(arms, ref)
    if grp:
        title = (f"Median latency: {_span([medians[o['run_id']] for o in grp[1]], '.2f')} s for {grp[0]}, "
                 f"{medians[ref['run_id']]:.2f} s for the {_lower(labels[ref['run_id']])}")
    else:
        title = f"Median latency per document ranged {_span(list(medians.values()), '.2f')} s"
    if len(title) > fs.TITLE_MAX:
        title = f"Median latency per document ranged {_span(list(medians.values()), '.2f')} s"
    fs.heading(fig, ax, title, "Each dot is one document; bar marks the median", _source(report))
    return f.svg(fig)


def _quality(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str]) -> str | None:
    pairs = report.get("pairs") or {}
    arms = {a["run_id"]: a for a in report["arms"]}
    rows = []
    for rid, p in pairs.items():
        for key, name, margin_key, test_key in MEASURES:
            d = (p.get("differences") or {}).get(key) or {}
            if d.get("estimate") is None:
                continue
            ci = d.get("ci95") or [d["estimate"], d["estimate"]]
            margin = (report.get("margins") or {}).get(margin_key) if margin_key else None
            test = ((p.get("tests") or {}).get(test_key) or {}) if test_key else {}
            bound = test.get("lower95_one_sided")
            rows.append((rid, name, 100 * d["estimate"], 100 * ci[0], 100 * ci[1], margin,
                         100 * bound if isinstance(bound, (int, float)) else None))
    if not rows:
        return None
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.36 * len(rows) + 1.6))
    y = list(range(len(rows)))[::-1]
    for yi, (rid, _name, est, lo, hi, margin, bound) in zip(y, rows):
        colour = fs.SYSTEM_COLOURS[_system(arms[rid])]
        if bound is not None:
            # the bound the non-inferiority test decides on (exact, one-sided): thin ink line to it
            ax.plot([bound, est], [yi, yi], color=fs.INK_2, linewidth=1, zorder=2)
            ax.plot([bound], [yi], marker="|", markersize=9, markeredgewidth=1.6, color=fs.INK, zorder=3)
        ax.plot([lo, hi], [yi, yi], color=colour, linewidth=2.5, solid_capstyle="butt", zorder=3)
        ax.scatter([est], [yi], s=46, color=colour, edgecolors=fs.SURFACE, linewidths=1.5, zorder=4)
        if margin:
            ax.plot([-100 * margin] * 2, [yi - 0.38, yi + 0.38], color=fs.CRITICAL, linewidth=1.2,
                    linestyle=(0, (3, 2)), zorder=2)
        note = f"{est:+.1f} [{lo:+.1f}, {hi:+.1f}]" + (f", test bound {bound:+.1f}" if bound is not None else "")
        ax.text(max(hi, est) + 0.6, yi, note, va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.axvline(0, color=fs.INK_2, linewidth=1, zorder=2)
    multi = len(pairs) > 1
    ax.set_yticks(y, [f"{name} · {labels[rid]}" if multi else name for rid, name, *_ in rows])
    span = max(max(abs(r[3]), abs(r[4]), abs(r[6] or 0)) for r in rows) + 4
    ax.set_xlim(-span, span * 1.6)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "Candidate minus reference (percentage points)")
    tests = [(p.get("tests") or {}) for p in pairs.values()]
    flags = [t.get(k, {}).get("non_inferior") for t in tests for k in ("noninferiority_macro_f1", "noninferiority_unit")]
    n = report.get("n")
    if flags and all(flags):
        title = "Non-inferior on class macro-F1 and subclass-unit accuracy"
    elif any(flags):
        title = "Non-inferiority shown on some margins but not all"
    else:
        title = f"Non-inferiority not shown at n = {n}: test bounds fall below the margins"
    ref = arms.get(report["reference"])
    sub = (f"Each arm minus the {_lower(labels[ref['run_id']]) if ref else 'reference'} · colour: 95% bootstrap · "
           "black tick: test bound · red: margin")
    if len(sub) > fs.SUBTITLE_MAX:
        sub = "Candidate minus reference · colour: 95% bootstrap · black tick: test bound · red: margin"
    fs.heading(fig, ax, title, sub, _source(report))
    return f.svg(fig)


def _routing(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str]) -> str:
    arms = report["arms"]
    cats = (("right", "Auto-routed, right class", fs.GOOD), ("wrong", "Auto-routed, wrong class", fs.CRITICAL),
            ("parked", "Parked for a person", fs.WARNING), ("failed", "Failed", fs.NEUTRAL))
    data = []
    for a in arms:
        r = a.get("routing") or {}
        auto = r.get("auto_routed") or 0
        right = round(auto * (r.get("auto_class_accuracy") or 0))
        data.append({"right": right, "wrong": auto - right, "parked": r.get("abstained") or 0,
                     "failed": a.get("failed") or 0})
    used = [c for c in cats if any(d[c[0]] for d in data)]
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.5 * len(arms) + 1.5))
    y = list(range(len(arms)))[::-1]
    left = [0] * len(arms)
    n = max(sum(d.values()) for d in data) or 1
    for key, label, colour in used:
        vals = [d[key] for d in data]
        ax.barh(y, vals, left=left, color=colour, height=0.56, label=label, edgecolor=fs.SURFACE, linewidth=1.5)
        for yi, v, lo in zip(y, vals, left):
            if v and v >= max(1, 0.06 * n):
                ax.text(lo + v / 2, yi, str(v), ha="center", va="center", fontsize=fs.SIZE["annotation"],
                        color=fs.INK if colour in (fs.WARNING, fs.NEUTRAL) else "#ffffff")
        left = [lo + v for lo, v in zip(left, vals)]
    ax.set_yticks(y, [labels[a["run_id"]] for a in arms])
    ax.set_xlim(0, n * 1.04)
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 5, 10]))
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, "Documents")
    ref = _ref(report, arms)
    rate = {a["run_id"]: (a.get("routing") or {}).get("abstain_rate") or 0 for a in arms}
    grp = _group(arms, ref)
    if grp:
        title = (f"{_cap(grp[0])} parked {_span([rate[o['run_id']] for o in grp[1]], '.0%')}; the "
                 f"{_lower(labels[ref['run_id']])} parked {rate[ref['run_id']]:.0%}")
    else:
        title = f"{_span(list(rate.values()), '.0%')} of documents were parked for a person"
    if len(title) > fs.TITLE_MAX:
        title = "Share of documents parked for a person, per arm"
    wrong = sum(d["wrong"] for d in data)
    sub = f"Routing on the same {report.get('n')} documents · {wrong} auto-routed with the wrong class across arms"
    fs.heading(fig, ax, title, sub, _source(report))
    fs.legend_below(fig, ax, len(used))
    return f.svg(fig)


def _cost_quality(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str]) -> str | None:
    from matplotlib.ticker import PercentFormatter

    arms = [a for a in report["arms"] if (a.get("cost") or {}).get("per_1k_docs_usd") is not None
            and a.get("unit_accuracy") is not None]
    if len(arms) < 2:
        return None
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.4))
    xs = [a["cost"]["per_1k_docs_usd"] for a in arms]
    ys = [a["unit_accuracy"] for a in arms]
    for a, x, yv in zip(arms, xs, ys):
        ax.scatter([x], [yv], s=70, color=fs.SYSTEM_COLOURS[_system(a)], edgecolors=fs.SURFACE, linewidths=1.5, zorder=3)
    # direct labels, nudged apart when two arms sit on the same point
    seen: dict[tuple[float, float], int] = {}
    for a, x, yv in zip(arms, xs, ys):
        k = (round(x, 2), round(yv, 3))
        i = seen.get(k, 0)
        seen[k] = i + 1
        ax.annotate(labels[a["run_id"]], (x, yv), textcoords="offset points", xytext=(8, -4 - 12 * i),
                    ha="left", va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    pad = (max(xs) - min(xs)) or max(xs) * 0.2 or 1
    ax.set_xlim(max(0, min(xs) - pad * 0.6), max(xs) + pad * 1.5)
    ax.set_ylim(max(0, min(ys) - 0.1), 1.0)
    for coll in ax.collections:
        coll.set_clip_on(False)  # a 100% arm sits on the top edge
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.xaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    ax.grid(True)
    ax.set_axisbelow(True)
    fs.axis_labels(ax, "Cost per 1,000 documents at this mix (USD)", "Subclass-unit accuracy")
    ref = _ref(report, arms)
    n = int(report.get("n") or 0)
    # where each cost comes from: billed by the provider, or priced from the list prices
    est = [labels[a["run_id"]] for a in arms
           if (a["cost"].get("provider_reported_docs") or 0) < (a.get("n") or 0)]
    cost = {a["run_id"]: a["cost"]["per_1k_docs_usd"] for a in arms}
    grp = _group(arms, ref)
    title = None
    if grp and not est and n >= COST_CLAIM_MIN_DOCS:
        diffs = [cost[o["run_id"]] - cost[ref["run_id"]] for o in grp[1]]
        word = "more" if all(d > 0 for d in diffs) else "less" if all(d < 0 for d in diffs) else None
        if word:
            title = (f"{_cap(grp[0])} cost ${_span([abs(d) for d in diffs], '.2f')} {word} per 1,000 documents "
                     f"than the {_lower(labels[ref['run_id']])}")
    if title is None:
        why = ([f"n = {n}"] if n < COST_CLAIM_MIN_DOCS else []) + (
            [f"{_lower(est[0])} cost estimated"] if len(est) == 1 else ["costs estimated"] if est else [])
        title = "Cost is not yet comparable: " + " and ".join(why) if why else \
            "Cost per 1,000 documents against subclass-unit accuracy"
    if len(title) > fs.TITLE_MAX:
        title = "Cost is not yet comparable" if est or n < COST_CLAIM_MIN_DOCS else \
            "Cost per 1,000 documents against subclass-unit accuracy"
    basis = ("all costs as billed" if not est else
             "priced from list prices: " + ", ".join(_lower(e) for e in est)
             if len(est) < len(arms) else "all costs priced from list prices")
    sub = f"Same {n} documents, this sample's length mix · up and left is better · {basis}"
    if len(sub) > fs.SUBTITLE_MAX:
        sub = f"Same {n} documents, this sample's length mix · {basis}"
    if len(sub) > fs.SUBTITLE_MAX:
        sub = f"Same {n} documents, this sample's length mix · some costs priced from list prices"
    fs.heading(fig, ax, title, sub, _source(report))
    return f.svg(fig)


def _price_checked() -> str | None:
    """The date ``config/api_prices.yaml`` was last checked against OpenRouter."""
    try:
        import yaml

        from mailroom_sandbox.paths import repo_root

        doc = yaml.safe_load((repo_root() / "config" / "api_prices.yaml").read_text(encoding="utf-8")) or {}
        return str(doc["checked"]) if doc.get("checked") else None
    except Exception:  # noqa: BLE001 - the date is a caption, never a reason to drop the figure
        return None


def _pricing(f: fs.Fig, report: Mapping[str, Any], labels: Mapping[str, str],
             prompt_tokens: Mapping[str, Sequence[float]]) -> str | None:
    """List input price per million tokens against prompt size, one step line per model."""
    from matplotlib.ticker import FixedLocator, NullLocator

    from mailroom_sandbox.job import metrics

    models: dict[str, Mapping[str, Any]] = {}
    for a in report["arms"]:
        models.setdefault(str(a.get("model") or ""), a)
    sheets = {m: metrics.price_sheet(m) for m in models if m}
    sheets = {m: sh for m, sh in sheets.items() if sh}
    if len(sheets) < 2:
        return None
    lo_x, hi_x = 1_000, 1_000_000
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.2))
    top = 0.0
    for m, sheet in sheets.items():
        arm = models[m]
        colour = fs.SYSTEM_COLOURS[_system(arm)]
        xs, ys = [], []
        for i, tier in enumerate(sheet):
            start = max(lo_x, float(tier.get("min_prompt_tokens") or 0))
            end = float(sheet[i + 1]["min_prompt_tokens"]) if i + 1 < len(sheet) else hi_x
            if end <= lo_x:
                continue
            xs += [start, end]
            ys += [float(tier["prompt"])] * 2
        top = max(top, *ys)
        ax.plot(xs, ys, color=colour, linewidth=2, drawstyle="default", zorder=3)
        name = fs.SYSTEM_NAMES[_system(arm)]
        # a flat price is labelled at the left, a tiered one at its last step, so no step cuts a label
        at, ha, dx = ((xs[0], ys[0]), "left", 4) if len(set(ys)) == 1 else ((xs[-1], ys[-1]), "right", -4)
        ax.annotate(f"{name} ({fs.short_model(m)})", at, textcoords="offset points",
                    xytext=(dx, 6), ha=ha, va="bottom", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    # the compared documents' prompt sizes, one tick row per system
    systems = []
    for a in report["arms"]:
        toks = [t for t in prompt_tokens.get(a["run_id"], []) if t]
        if toks and _system(a) not in systems:
            systems.append(_system(a))
            yrow = -top * (0.06 + 0.07 * (len(systems) - 1))
            ax.scatter([min(max(t, lo_x), hi_x) for t in toks], [yrow] * len(toks), marker="|", s=60,
                       linewidths=1.2, color=fs.SYSTEM_COLOURS[_system(a)], zorder=3, clip_on=False)
            ax.annotate(f"{fs.SYSTEM_NAMES[_system(a)]} documents", (hi_x, yrow), textcoords="offset points",
                        xytext=(-4, 0), ha="right", va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_xscale("log")
    ax.set_xlim(lo_x, hi_x)
    ax.set_ylim(-top * (0.06 + 0.07 * max(len(systems), 1)), top * 1.25)
    ax.xaxis.set_major_locator(FixedLocator([1e3, 1e4, 3.2e4, 1e5, 2.56e5, 1e6]))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(lambda v, _: f"{v / 1000:g}k" if v < 1e6 else "1M")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.2f}" if v >= 0 else "")
    fs.value_axis(ax, "y")
    fs.axis_labels(ax, "Prompt size of one call (tokens, log scale)", "Input price per 1M tokens (USD)")
    checked = _price_checked()
    sub = (f"OpenRouter list prices{', checked ' + checked if checked else ''} · output billed separately · "
           "ticks: each document's prompt size")
    fs.heading(fig, ax, "List input price per million tokens, by prompt size", sub, _source(report))
    return f.svg(fig)


def build(report: Mapping[str, Any], latencies: Mapping[str, Sequence[float]] | None = None,
          prompt_tokens: Mapping[str, Sequence[float]] | None = None) -> dict[str, str]:
    """``{figure name: svg}`` for a ``sorter_arms`` comparison report."""
    labels = arm_labels(report["arms"])
    out: dict[str, str | None] = {}
    with fs.Fig(str(report.get("experiment_key") or report["reference"])) as f:
        out["runtime"] = _runtime(f, report, labels)
        out["latency"] = _latency(f, report, labels, latencies or {})
        out["quality"] = _quality(f, report, labels)
        out["routing"] = _routing(f, report, labels)
        out["cost-quality"] = _cost_quality(f, report, labels)
        out["pricing"] = _pricing(f, report, labels, prompt_tokens or {})
    return {k: v for k, v in out.items() if v}
