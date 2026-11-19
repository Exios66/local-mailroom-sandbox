"""Per-run figures for sorter and decision-model runs, built from a run's items (offline).

Each figure answers one question a run is judged on (H5); the title states the answer for this run:

- ``routing``: where each document went, per group (archived correct, parked for review,
  misarchived, archived with no truth class).
- ``confidence``: does the class probability rank right answers above wrong ones?
- ``risk-coverage``: the error rate among archived documents as a class-probability floor
  archives more of them, with the run's own routing marked (the threshold-calibration view).
- ``form-mass``: document-form probability on human forms per group, against the park line.
- ``park-reasons``: which rule parked each document.
- ``subclass``: subclass accuracy per truth class among archived documents, with 95% intervals.
- ``latency``: latency against input size, with throughput and cost in the subtitle.

Style, colour roles and the text lint live in ``figure_style``. Every figure has a table view:
``figure_rows`` is written next to the figures as CSV. SVGs are deterministic.
"""
from __future__ import annotations

import hashlib
import statistics
from collections.abc import Callable, Mapping
from typing import Any

from mailroom_sandbox import figure_style as fs
from mailroom_sandbox.figure_style import wilson  # noqa: F401  (re-exported for callers)

INTACT = "intact"
FEW_ERRORS = 5  # below this many wrong answers an AUROC is shown but flagged as too few to rank on

REASONS = {  # park-rule ids as a reader would say them
    "margin": "Class margin too small",
    "unknown_max": "Unknown class too likely",
    "subclass_not_this_class": "Subclass belongs to another class",
    "below_high_band": "Confidence below the high band",
    "document_form": "Document form",
}


def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return None
    return None


def reason_label(reason: str) -> str:
    key, _, value = str(reason).partition(":")
    head = REASONS.get(key, fs.humanize(key))
    return f"{head}: {value.replace('_', ' ')}" if value else head


def _fold(label: Any) -> str:
    """Class labels compare case-, hyphen- and whitespace-folded, as the scorer does (SHF-007,
    ``eval.agents._fold``), so a figure never shows an error the scorer does not count."""
    return " ".join(str(label or "").strip().lower().replace("-", "_").split()).replace(" ", "_")


def _flat_item(item: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(pred, score)`` of an item: nested (isolated and decision runs) or the whole-run sorter
    format, which writes top-level ``expected`` and ``predicted`` strings."""
    pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
    score = item.get("score") if isinstance(item.get("score"), dict) else {}
    if not pred and not score and isinstance(item.get("expected"), str):
        predicted = item.get("predicted") if isinstance(item.get("predicted"), str) else ""
        pred = {"doc_type": predicted} if predicted else {}
        expected = item["expected"]
        outcome = "" if not (expected and predicted) else "correct" if _fold(expected) == _fold(predicted) else "wrong"
        score = {"expected": expected, "outcome": outcome}
    return pred, score


def figure_rows(items: list[dict[str, Any]], rows_by_id: Mapping[str, Mapping[str, Any]] | None = None
                ) -> list[dict[str, Any]]:
    """One flat row per item: the table view behind every figure."""
    out = []
    for item in items:
        pred, score = _flat_item(item)
        row = (rows_by_id or {}).get(str(item.get("item_id") or item.get("id"))) or {}
        control = row.get("control")
        form = row.get("expected_document_form")
        # a constructed control row is grouped by its recipe (intact controls together); any other
        # row by its truth class
        defect = control is not None and form not in (None, "complete_instrument")
        if control is not None:
            group = str(control) if defect else INTACT
        else:
            group = str(score.get("expected") or "") or "no truth class"
        parked = bool(pred.get("abstained") or pred.get("route_to_human") or score.get("abstain"))
        outcome = str(score.get("outcome") or "")
        # a failed request has no answer: never shown as archived (CP-08 keeps failure and missing truth apart)
        failed = item.get("ok") is False or (bool(item.get("error")) and not pred)
        if failed and not parked:
            state = "failed"
        elif parked:
            state = "parked"
        elif defect or outcome == "wrong":
            state = "misarchived"
        elif outcome == "correct":
            state = "correct"
        else:
            state = "unscored"
        forced = (pred.get("forced_choice") or {}).get("doc_type") or pred.get("doc_type")
        expected = score.get("expected")
        usage = pred.get("usage") or {}
        latency = _num(item.get("latency_ms"))
        out.append({
            "id": str(item.get("item_id") or item.get("id")), "group": group, "state": state,
            "parked": parked, "defect": defect, "expected_class": expected or "",
            "forced_class": forced or "",
            "forced_correct": (None if not expected or failed else _fold(forced) == _fold(expected)),
            "class_probability": _num(pred.get("doc_type_probability")) if "doc_type_probability" in pred
            else _num(pred.get("confidence")),
            "form": pred.get("document_form") or "", "form_human_mass": _num(pred.get("document_form_human_mass")),
            "subclass_match": _num(score.get("subclass_match")),
            "park_reasons": ";".join(pred.get("abstain_reasons") or []),
            "latency_s": latency / 1000.0 if latency else None,
            "input_tokens": _num(usage.get("input_tokens")) or _num(item.get("prompt_tokens")),
            "cost_usd": _num(usage.get("cost")),
        })
    return out


def is_decision_run(items: list[dict[str, Any]]) -> bool:
    return any("abstain_reasons" in (i.get("pred") or {}) or "document_form" in (i.get("pred") or {})
               for i in items)


def auroc(pos: list[float], neg: list[float]) -> float | None:
    """P(a positive scores above a negative), ties half; None when either side is empty."""
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def risk_coverage(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """``(coverage, error rate among the archived)`` when archiving the k most probable forced answers,
    for every k (ties at one probability enter together): the curve a class-probability floor walks."""
    scored = sorted((r for r in rows if r["forced_correct"] is not None and r["class_probability"] is not None),
                    key=lambda r: -r["class_probability"])
    out, wrong, n = [], 0, len(scored)
    for i, r in enumerate(scored):
        wrong += not r["forced_correct"]
        if i + 1 == n or scored[i + 1]["class_probability"] != r["class_probability"]:
            out.append(((i + 1) / n, wrong / (i + 1)))
    return out


def _jitter(key: str, width: float = 0.36) -> float:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return (h - 0.5) * width


def _group_order(rows: list[dict[str, Any]]) -> list[str]:
    groups = sorted({r["group"] for r in rows})
    lead = [g for g in (INTACT, "tail", "head", "cut", "join") if g in groups]
    return lead + [g for g in groups if g not in lead]


GROUP_LABELS = {INTACT: "Intact", "tail": "Tail cut", "head": "Head cut", "cut": "Mid-text cut",
                "join": "Two documents joined"}


def _group_label(g: str) -> str:
    return GROUP_LABELS.get(g, fs.humanize(g))


def plural(n: int, word: str, many: str | None = None) -> str:
    """``1 class error`` / ``3 class errors``."""
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _pct(k: int, n: int) -> str:
    return f"{k / n:.0%}" if n else "n/a"


# ---------------------------------------------------------------- figures

def _routing(f: fs.Fig, rows: list[dict[str, Any]], source: str) -> str:
    groups = _group_order(rows)
    counts = {g: {k: sum(r["group"] == g and r["state"] == k for r in rows) for k, _, _ in fs.STATES} for g in groups}
    states = [s for s in fs.STATES if any(counts[g][s[0]] for g in groups)]
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.42 * len(groups) + 1.4))
    y = list(range(len(groups)))[::-1]
    left = [0] * len(groups)
    widest = max(sum(counts[g].values()) for g in groups)
    for key, label, colour in states:
        vals = [counts[g][key] for g in groups]
        ax.barh(y, vals, left=left, color=colour, height=0.62, label=label, edgecolor=fs.SURFACE, linewidth=1.5)
        for yi, v, lo in zip(y, vals, left):
            if v and v >= max(2, 0.07 * widest):
                ax.text(lo + v / 2, yi, str(v), ha="center", va="center", fontsize=fs.SIZE["annotation"],
                        color=fs.INK if colour in (fs.WARNING, fs.NEUTRAL) else "#ffffff")
        left = [lo + v for lo, v in zip(left, vals)]
    for yi, g in zip(y, groups):
        ax.text(left[groups.index(g)] + widest * 0.012, yi, f"n = {sum(counts[g].values())}", va="center",
                fontsize=fs.SIZE["annotation"], color=fs.MUTED)
    ax.set_yticks(y, [_group_label(g) for g in groups])
    fs.value_axis(ax, "x")
    ax.set_xlim(0, widest * 1.14 + 0.5)
    fs.axis_labels(ax, "Documents")
    n = len(rows)
    mis = sum(r["state"] == "misarchived" for r in rows)
    park = sum(r["state"] == "parked" for r in rows)
    defects = sum(r["defect"] for r in rows)
    if defects and defects == n:
        # a failed request reached nothing: neither extraction nor a person (CP-08)
        leaked = sum(r["defect"] and not r["parked"] and r["state"] != "failed" for r in rows)
        lost = sum(r["state"] == "failed" for r in rows)
        title = f"{leaked} of {n} constructed defects reached extraction" + (f", {lost} failed" if lost else "")
    elif mis:
        title = f"{mis} of {n} documents {'was' if mis == 1 else 'were'} misarchived and {park} parked"
    else:
        title = f"No document was misarchived; {park} of {n} {'was' if park == 1 else 'were'} parked"
    failed = sum(r["state"] == "failed" for r in rows)
    sub = f"Routing outcome per group · parked {_pct(park, n)}, misarchived {_pct(mis, n)}"
    fs.heading(fig, ax, title, sub + (f", failed {_pct(failed, n)}" if failed else ""), source)
    fs.legend_below(fig, ax, len(states))
    return f.svg(fig)


def _strip(f: fs.Fig, rows: list[dict[str, Any]], value: str, groups: list[str], group_of: Callable[[dict], str],
           title: str, subtitle: str, xlabel: str, source: str, line: tuple[float, str] | None) -> str:
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.5 * len(groups) + 1.5))
    y_of = {g: i for i, g in enumerate(groups[::-1])}
    for parked, colour, label in ((False, fs.PASSED, "Passed to extraction"), (True, fs.PARKED, "Parked for review")):
        pts = [r for r in rows if r[value] is not None and r["parked"] == parked and group_of(r) in y_of]
        if pts:
            ax.scatter([r[value] for r in pts], [y_of[group_of(r)] + _jitter(r["id"]) for r in pts], s=28,
                       color=colour, alpha=0.92, edgecolors=fs.SURFACE, linewidths=0.9, label=label, zorder=3)
    if line:
        ax.axvline(line[0], color=fs.INK_2, linewidth=1, linestyle=(0, (4, 2)), zorder=2)
        ax.text(line[0] + 0.012, len(groups) - 0.42, line[1], ha="left", va="center",
                fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_yticks(list(y_of.values()), [_group_label(g) for g in y_of])
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.6, len(groups) - 0.15)
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, xlabel)
    fs.heading(fig, ax, title, subtitle, source)
    fs.legend_below(fig, ax, 2)
    return f.svg(fig)


def _bars(f: fs.Fig, labels: list[str], values: list[float], notes: list[str], colour: str, title: str,
          subtitle: str, xlabel: str, source: str, share: bool = False,
          ci: list[tuple[float, float]] | None = None) -> str:
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 0.4 * len(labels) + 1.3))
    y = list(range(len(labels)))[::-1]
    ax.barh(y, values, color=colour, height=0.56)
    top = 1.0 if share else max(values) * 1.18 + 0.5
    if ci:
        # max(0, .): at p = 1 the interval's float upper bound can sit a hair under p
        ax.errorbar(values, y, xerr=[[max(0.0, v - lo) for v, (lo, _) in zip(values, ci)],
                                     [max(0.0, hi - v) for v, (_, hi) in zip(values, ci)]],
                    fmt="none", ecolor=fs.INK_2, elinewidth=1, capsize=3, zorder=3)
    for i, (yi, v, note) in enumerate(zip(y, values, notes)):
        x = max(v, ci[i][1]) if ci else v
        ax.text(x + top * 0.015, yi, note, va="center", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, top * (1.2 if share else 1))
    if share:
        from matplotlib.ticker import FixedLocator, PercentFormatter

        ax.xaxis.set_major_locator(FixedLocator([0, 0.25, 0.5, 0.75, 1.0]))
        ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    else:
        from matplotlib.ticker import MaxNLocator

        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fs.value_axis(ax, "x")
    fs.axis_labels(ax, xlabel)
    fs.heading(fig, ax, title, subtitle, source)
    return f.svg(fig)


def _risk_coverage(f: fs.Fig, rows: list[dict[str, Any]], colour: str, source: str) -> str:
    from matplotlib.ticker import PercentFormatter

    curve = risk_coverage(rows)
    scored = [r for r in rows if r["forced_correct"] is not None and r["class_probability"] is not None]
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.3))
    xs, ys = [0.0] + [c for c, _ in curve], [curve[0][1]] + [e for _, e in curve]
    ax.step(xs, ys, where="post", color=colour, linewidth=2, label="Class-probability floor alone", zorder=3)
    passed = [r for r in scored if not r["parked"]]
    wrong = sum(not r["forced_correct"] for r in scored)
    note = ""
    if passed:
        cov = len(passed) / len(scored)
        err = sum(not r["forced_correct"] for r in passed) / len(passed)
        ax.scatter([cov], [err], s=70, color=fs.INK, edgecolors=fs.SURFACE, linewidths=2, zorder=4,
                   label="This run's routing (all park rules)")
        ax.annotate(f"{cov:.0%} archived, {err:.1%} wrong", (cov, err), textcoords="offset points",
                    xytext=(-10, 10), ha="right", fontsize=fs.SIZE["annotation"], color=fs.INK_2)
        floor_err = next((e for c, e in curve if c >= cov - 1e-9), ys[-1])
        note = (f"At {cov:.0%} coverage the park rules give {err:.1%} error; a probability floor alone "
                f"gives {floor_err:.1%}")
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_locator(MaxNLocator(5, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=None))
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, max(ys) * 1.3 + 0.01)
    ax.grid(True)
    ax.set_axisbelow(True)
    fs.axis_labels(ax, "Coverage (share of scored documents archived)", "Error rate among archived")
    title = note.split(";")[0] if note else "Error among archived documents as coverage grows"
    if len(title) > fs.TITLE_MAX:
        title = "Error among archived documents as coverage grows"
    fs.heading(fig, ax, title, f"Selective classification over {len(scored)} forced answers, {wrong} wrong · "
               "lower is better", source)
    fs.legend_below(fig, ax, 2)
    return f.svg(fig)


def _latency(f: fs.Fig, rows: list[dict[str, Any]], colour: str, source: str, wall_s: float | None) -> str | None:
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    pts = [r for r in rows if r["latency_s"] and r["input_tokens"]]
    if not pts:
        return None
    fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.3))
    xs, ys = [r["input_tokens"] for r in pts], [r["latency_s"] for r in pts]
    ax.scatter(xs, ys, s=28, color=colour, edgecolors=fs.SURFACE, linewidths=0.9, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    # plain 1-2-5 ticks inside the data range instead of powers of ten
    for axis, lo, hi, fmt in ((ax.xaxis, min(xs), max(xs), lambda v, _: f"{v / 1000:g}k" if v >= 1000 else f"{v:g}"),
                              (ax.yaxis, min(ys), max(ys), lambda v, _: f"{v:g}")):
        ticks = [m * 10 ** e for e in range(-2, 7) for m in (1, 2, 5) if lo / 1.5 <= m * 10 ** e <= hi * 1.5]
        axis.set_major_locator(FixedLocator(ticks))
        axis.set_major_formatter(FuncFormatter(fmt))
        axis.set_minor_locator(NullLocator())
    ax.set_ylim(min(ys) / 1.3, max(ys) * 1.5)
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    worst = max(pts, key=lambda r: r["latency_s"])
    ax.annotate(f"{worst['id'][:16]} ({worst['latency_s']:.1f} s)", (worst["input_tokens"], worst["latency_s"]),
                textcoords="offset points", xytext=(-9, 0), ha="right", va="center",
                fontsize=fs.SIZE["annotation"], color=fs.INK_2)
    fs.axis_labels(ax, "Input tokens per document (log scale)", "Latency (s, log scale)")
    from mailroom_sandbox.job.metrics import p95 as nearest_rank_p95

    p50, p95 = statistics.median(ys), nearest_rank_p95(ys)
    cost = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    bits = [f"{len(pts)} documents", f"p95 {p95:.2f} s"]
    if wall_s:
        bits.append(f"{len(rows) / (wall_s / 60):.0f} documents/min")
    if cost:
        bits.append(f"${sum(cost) / len(cost) * 1000:.2f} per 1,000 documents")
    fs.heading(fig, ax, f"Median latency was {p50:.2f} s per document", " · ".join(bits), source)
    return f.svg(fig)


def build(stem: str, items: list[dict[str, Any]], rows_by_id: Mapping[str, Mapping[str, Any]] | None = None,
          wall_s: float | None = None, system: str | None = None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """``({figure name: svg}, table rows)`` for a sorter or decision-model run; empty with no items."""
    if not items:
        return {}, []
    system = system or ("decision" if is_decision_run(items) else "llm")
    colour = fs.SYSTEM_COLOURS.get(system, fs.THIRD)
    source = f"Source: run {stem} · {fs.SYSTEM_NAMES.get(system, 'Other system').lower()}"
    rows = figure_rows(items, rows_by_id)
    out: dict[str, str | None] = {}
    with fs.Fig(stem) as f:
        out["routing"] = _routing(f, rows, source)

        scored = [r for r in rows if r["forced_correct"] is not None and r["class_probability"] is not None]
        if scored:
            right = [r["class_probability"] for r in scored if r["forced_correct"]]
            wrong = [r["class_probability"] for r in scored if not r["forced_correct"]]
            a = auroc(right, wrong)
            if a is None:
                title = (f"No class errors in {len(scored)} documents, so ranking is unmeasured" if not wrong
                         else f"All {len(scored)} forced answers were wrong")
            elif len(wrong) < FEW_ERRORS:
                title = f"Only {plural(len(wrong), 'class error')}: too few to judge the ranking"
            elif a > 0.5:
                title = f"Class probability ranks right above wrong answers (AUROC {a:.2f})"
            elif a < 0.5:
                title = f"Class probability ranks wrong above right answers (AUROC {a:.2f})"
            else:
                title = "Class probability does not separate right from wrong answers (AUROC 0.50)"
            sub = (f"AUROC {a:.3f} · " if a is not None else "") + f"{len(wrong)} wrong of {len(scored)} forced answers"
            out["confidence"] = _strip(
                f, scored, "class_probability", ["Right class", "Wrong class"],
                lambda r: "Right class" if r["forced_correct"] else "Wrong class",
                title, sub, "Probability of the chosen class", source, None)
            if wrong:
                out["risk-coverage"] = _risk_coverage(f, rows, colour, source)

        massed = [r for r in rows if r["form_human_mass"] is not None]
        if massed:
            groups = _group_order(massed)
            pos = [r["form_human_mass"] for r in massed if r["defect"]]
            neg = [r["form_human_mass"] for r in massed if not r["defect"] and r["group"] == INTACT]
            a = auroc(pos, neg)
            low = sum(r["defect"] and r["form_human_mass"] < 0.5 for r in massed)
            if pos:
                title = f"{low} of {len(pos)} defects scored below the 0.5 park line"
            else:
                k = sum(r["form_human_mass"] >= 0.5 for r in massed)
                title = f"{k} of {len(massed)} documents {'was' if k == 1 else 'were'} at or above the park line"
            sub = "Probability mass on a human form, per group" + (f" · AUROC defects vs intact {a:.3f}" if a is not None else "")
            out["form-mass"] = _strip(
                f, massed, "form_human_mass", groups, lambda r: r["group"], title, sub,
                "Probability of fragment, bundle, unreadable or non-English", source, (0.5, "Park line 0.5"))

        reasons: dict[str, int] = {}
        for r in rows:
            for reason in filter(None, r["park_reasons"].split(";")):
                reasons[reason] = reasons.get(reason, 0) + 1
        if reasons:
            names = sorted(reasons, key=lambda k: (-reasons[k], k))
            parked = sum(r["parked"] for r in rows)
            top = names[0]
            out["park-reasons"] = _bars(
                f, [reason_label(k) for k in names], [reasons[k] for k in names], [str(reasons[k]) for k in names],
                colour, f"{reason_label(top)} parked the most documents ({reasons[top]})",
                f"Park rules fired · {parked} documents parked; one document can fire several rules",
                "Documents", source)

        sub_rows = [r for r in rows if r["subclass_match"] is not None and not r["parked"]]
        if sub_rows:
            classes = sorted({r["expected_class"] for r in sub_rows})
            acc, notes, ci = [], [], []
            for c in classes:
                cell = [r["subclass_match"] for r in sub_rows if r["expected_class"] == c]
                acc.append(sum(cell) / len(cell))
                notes.append(f"{sum(cell):.0f}/{len(cell)}")
                ci.append(wilson(sum(cell), len(cell)))
            worst = min(range(len(classes)), key=lambda i: (acc[i], classes[i]))
            total = sum(r["subclass_match"] for r in sub_rows)
            title = (f"Subclass was right on {total:.0f} of {len(sub_rows)}; weakest is {fs.humanize(classes[worst]).lower()}"
                     if acc[worst] < 1 else f"Subclass was right on every archived document ({len(sub_rows)})")
            if len(title) > fs.TITLE_MAX:
                title = f"Subclass was right on {total:.0f} of {len(sub_rows)} archived documents"
            out["subclass"] = _bars(
                f, [fs.humanize(c) for c in classes], acc, notes, colour, title,
                "Subclass accuracy per truth class among archived documents · whiskers: 95% Wilson interval",
                "Subclass accuracy", source, share=True, ci=ci)

        out["latency"] = _latency(f, rows, colour, source, wall_s)
    return {k: v for k, v in out.items() if v}, rows


def paired_svg(stem: str, res: Mapping[str, Any], base: str, cand: str) -> str:
    """The draw-2 paired decision as a figure: errors per side under each question set, with the
    documents fixed and broken (the discordant pairs the sign test reads)."""
    with fs.Fig(stem) as f:
        fig, axes = f.plt.subplots(1, 2, figsize=(fs.WIDTH + 0.8, 2.9), sharey=False)
        for ax, side, what in zip(axes, ("defects", "intact"), ("Defects passed to extraction",
                                                                "Intact documents parked")):
            r = res[side]
            vals = [r["errors_base"], r["errors_cand"]]
            # the base question set is the reference (neutral); the candidate the system under test
            ax.bar([0, 1], vals, color=[fs.NEUTRAL, fs.DECISION], width=0.56)
            for x, v in zip((0, 1), vals):
                ax.text(x, v, f"{v}", ha="center", va="bottom", fontsize=fs.SIZE["annotation"], color=fs.INK)
            ax.set_xticks([0, 1], [base, cand])
            ax.set_ylim(0, max(vals + [1]) * 1.3)
            fs.value_axis(ax, "y")
            ax.set_title(f"{what}\nn = {r['n']} · fixed {len(r['fixed'])}, broken {len(r['broken'])} · "
                         f"p = {r['p_better']:.3f}", fontsize=fs.SIZE["label"], color=fs.INK_2, loc="left")
        fs.axis_labels(axes[0], y="Documents")
        verdict = str(res["decision"])
        fs.heading(fig, axes[0], f"Question set {cand} vs {base}: {verdict}",
                   "Errors per side under each question set, same documents", f"Source: {stem}")
        return f.svg(fig)
