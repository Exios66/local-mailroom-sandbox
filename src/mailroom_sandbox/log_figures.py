"""House-style figures for the experiment log explorer (notebook 04), offline and deterministic.

Three questions, one figure each, all built with ``figure_style``:

- ``inventory_svg``: which runs exist, and how many are real rather than mock plumbing checks.
- ``setups_svg``: within one comparable cohort (same task **and** dataset fingerprint), which
  setup (provider, profile, model and prompt) scores best, with a 95% Wilson interval.
- ``trend_svg``: how one setup's exact match moved run by run in a cohort, each with its interval.

Runs in a cohort re-score the same documents, so pooling a setup's runs averages run-to-run
noise but adds no documents: its interval uses the dataset's document count, not runs × documents.
Exact match is a share of documents only when every document scores 0 or 1; a run whose mean
times its scored count is not a whole number has partial credit, and gets no binomial interval.

Every builder returns ``(svg, rows)``: the SVG text and the table view of every plotted number.
Titles are computed from the data (``.claude/skills/experiment-figures``), so they stay true when
the log changes. Mock scores are 1.0 by construction and are always labelled as such.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from mailroom_sandbox import figure_style as fs

METRIC = "exact_match"
TASK_LABELS = {"sorter": "LLM sorter", "isolated": "LLM sorter", "sorter_reviewer": "Decision model",
               "pipeline": "Pipeline"}
MOCK_NOTE = "mock runs score 100% by construction"


def task_label(task: str | None) -> str:
    return TASK_LABELS.get(task or "", fs.humanize(task) if task else "No task")


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def scored_n(record: dict[str, Any]) -> int | None:
    """Documents behind ``exact_match``: ``n_scored`` when recorded (rows without truth are left
    out, SHF-006), else the interval's or the scores' ``n``, else the run's row count."""
    scores = record.get("scores") or {}
    ci = scores.get(f"{METRIC}_ci") if isinstance(scores.get(f"{METRIC}_ci"), dict) else {}
    for value in (scores.get("n_scored"), ci.get("n"), scores.get("n"), record.get("n")):
        if _count(value) is not None:
            return _count(value)
    return None


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    """One log record as a flat row: identity fields, run size, scored size and exact match."""
    scores = record.get("scores") or {}
    git = record.get("git") or {}
    value = scores.get(METRIC)
    n = record.get("n") if record.get("n") is not None else scores.get("n")
    return {
        "timestamp": record.get("timestamp"),
        "experiment": record.get("experiment_name"),
        "task": record.get("task"),
        "profile": record.get("profile"),
        "provider": record.get("provider"),
        "model": record.get("model"),
        "prompt": record.get("prompt_version"),
        "mock": bool(record.get("mock")),
        "n": _count(n),
        "n_scored": scored_n(record),
        "fingerprint": record.get("dataset_fingerprint"),
        "git": (git.get("sha") or git.get("commit") or "")[:10] if isinstance(git, dict) else "",
        METRIC: float(value) if isinstance(value, (int, float)) else None,
    }


def setup_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """What defines a setup: provider, profile, full model id and prompt version. One model id can
    be served by different providers or profiles (with different quantization or limits)."""
    return tuple(str(row.get(k) or "") for k in ("provider", "profile", "model", "prompt"))


def setup_label(row: dict[str, Any], full_model: bool = False, serving: bool = False) -> str:
    """``model · prompt``; ``full_model`` keeps the org prefix, ``serving`` adds provider/profile."""
    model = row.get("model")
    model = (model if full_model else fs.short_model(model)) if model else "Default model"
    prompt = row.get("prompt") or "default prompt"
    label = f"{model} · {prompt.replace('_', ' ')}"
    if serving:
        serving_on = "/".join(str(row.get(k)).replace("_", " ") for k in ("provider", "profile") if row.get(k))
        label += f" ({serving_on or 'default serving'})"
    return label


def setup_labels(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str, str], str]:
    """The shortest label per setup that still tells every setup in ``rows`` apart."""
    first = {}
    for r in rows:
        first.setdefault(setup_key(r), r)
    for detail in ({}, {"full_model": True}, {"full_model": True, "serving": True}):
        labels = {key: setup_label(r, **detail) for key, r in first.items()}
        if len(set(labels.values())) == len(labels):
            break
    return labels


def _scored(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get(METRIC) is not None and r.get("n_scored")]


def _score(row: dict[str, Any]) -> float:
    """Summed per-document score: correct documents for a 0/1 metric."""
    return row[METRIC] * row["n_scored"]


def _partial(row: dict[str, Any]) -> bool:
    """True when the mean is not a share of whole documents (partial credit, e.g. extraction)."""
    return abs(_score(row) - round(_score(row))) > 1e-6


def _when(timestamp: Any) -> tuple[int, Any]:
    """Sort key in UTC; a naive timestamp counts as UTC, unparseable ones sort last as text."""
    try:
        when = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return 1, str(timestamp)
    return 0, (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _subtitle(required: Sequence[str], optional: Sequence[str] = ()) -> str:
    """Join with `` · ``, dropping optional parts from the end until it fits the house limit."""
    optional = list(optional)
    while True:
        text = " · ".join([*required, *optional])
        if len(text) <= fs.SUBTITLE_MAX or not optional:
            return text
        optional.pop()


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _n_text(ns: Sequence[int]) -> str:
    lo, hi = min(ns), max(ns)
    return f"n = {lo} each" if lo == hi else f"n = {lo}–{hi}"


def _runs(k: int) -> str:
    return f"{k} run" if k == 1 else f"{k} runs"


def _fit(title: str, fallback: str) -> str:
    return title if len(title) <= fs.TITLE_MAX else fallback


def cohorts(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Comparable cohorts (task, dataset fingerprint), most real runs first, then most runs."""
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for r in _scored(rows):
        groups.setdefault((r["task"], r["fingerprint"]), []).append(r)
    out = [{"task": t, "fingerprint": fp, "runs": len(g), "real_runs": sum(not r["mock"] for r in g),
            "documents": sum(r["n_scored"] for r in g), "setups": len({setup_key(r) for r in g})}
           for (t, fp), g in groups.items()]
    return sorted(out, key=lambda c: (-c["real_runs"], -c["runs"], str(c["task"]), str(c["fingerprint"])))


def _cohort_rows(rows: Iterable[dict[str, Any]], task: Any, fingerprint: Any) -> list[dict[str, Any]]:
    picked = [r for r in _scored(rows) if r["task"] == task and r["fingerprint"] == fingerprint]
    real = [r for r in picked if not r["mock"]]
    return sorted(real or picked, key=lambda r: (_when(r.get("timestamp")), str(r.get("experiment"))))


def _cohort_name(task: Any, fingerprint: Any) -> str:
    return f"{task_label(task)} on dataset {str(fingerprint)[:8] if fingerprint else 'unknown'}"


# ---------------------------------------------------------------- figure 1: what is in the log

def inventory_svg(rows: Iterable[dict[str, Any]], source: str = "experiment log") -> tuple[str, list[dict]]:
    """Runs per task, real vs mock, as stacked horizontal bars."""
    rows = list(rows)
    tasks: dict[Any, dict[str, int]] = {}
    for r in rows:
        t = tasks.setdefault(r.get("task"), {"real": 0, "mock": 0})
        t["mock" if r.get("mock") else "real"] += 1
    order = sorted(tasks, key=lambda t: (tasks[t]["real"] + tasks[t]["mock"], str(t)))
    data = [{"task": t, "label": task_label(t), **tasks[t]} for t in order]
    total = len(rows)
    real = sum(d["real"] for d in data)
    if total == 0:
        title = "The experiment log has no runs yet"
    elif real == 0 and total == 1:
        title = "The only logged run is a mock plumbing check, so it measures no quality"
    elif real == 0:
        title = _fit(f"All {total} logged runs are mock plumbing checks, so none measures quality",
                     f"All {total} logged runs are mock plumbing checks")
    else:
        title = f"{real} of {total} logged runs are real; the rest are mock plumbing checks"

    with fs.Fig(salt="log-inventory") as f:
        fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 1.1 + 0.42 * max(len(data), 1)))
        y = range(len(data))
        for d, yi in zip(data, y):
            colour = fs.SYSTEM_COLOURS[fs.system_of_task(d["task"])]
            ax.barh(yi, d["real"], color=colour, height=0.62, edgecolor=fs.SURFACE, linewidth=1.5)
            ax.barh(yi, d["mock"], left=d["real"], color=fs.NEUTRAL, height=0.62, edgecolor=fs.SURFACE,
                    linewidth=1.5)
            ax.annotate(f"{d['real']} real · {d['mock']} mock", (d["real"] + d["mock"], yi), xytext=(4, 0),
                        textcoords="offset points", va="center", ha="left", fontsize=fs.SIZE["annotation"],
                        color=fs.INK_2)
        ax.set_yticks(list(y), [d["label"] for d in data])
        ax.set_xlim(0, max([d["real"] + d["mock"] for d in data] + [1]) * 1.35)
        from matplotlib.ticker import MaxNLocator

        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        fs.value_axis(ax, "x")
        fs.axis_labels(ax, x="Logged runs")
        systems = sorted({fs.system_of_task(d["task"]) for d in data if d["real"]})
        labels = [f"Real: {fs.SYSTEM_NAMES[s]}" for s in systems] + ["Mock plumbing check"]
        colours = [fs.SYSTEM_COLOURS[s] for s in systems] + [fs.NEUTRAL]
        handles = [f.plt.Rectangle((0, 0), 1, 1, color=c) for c in colours]
        fs.legend_below(fig, ax, ncol=len(handles), handles=handles, labels=labels)
        fs.heading(fig, ax, title, f"Runs per task in the log · {MOCK_NOTE}", f"Source: {source}")
        return f.svg(fig), data


# ---------------------------------------------------------------- figure 2: setups in one cohort

def setups_svg(rows: Iterable[dict[str, Any]], task: Any, fingerprint: Any,
               source: str = "experiment log") -> tuple[str, list[dict]]:
    """Mean exact match per setup within one cohort, with a 95% Wilson interval on the dataset's
    documents (repeat runs re-score the same documents, so they are not pooled as new ones)."""
    picked = _cohort_rows(rows, task, fingerprint)
    mock = bool(picked) and all(r["mock"] for r in picked)
    labels = setup_labels(picked)
    pooled: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for r in picked:
        p = pooled.setdefault(setup_key(r), {"setup": labels[setup_key(r)], "provider": r.get("provider"),
                                             "profile": r.get("profile"), "model": r.get("model"),
                                             "prompt": r.get("prompt"), "runs": 0, "score": 0.0, "scored": 0,
                                             "documents": 0, "partial": False})
        p["runs"] += 1
        p["score"] += _score(r)
        p["scored"] += r["n_scored"]
        p["documents"] = max(p["documents"], r["n_scored"])
        p["partial"] = p["partial"] or _partial(r)
    data = []
    for p in pooled.values():
        rate = p["score"] / p["scored"]
        lo, hi = (None, None) if p["partial"] else fs.wilson(rate * p["documents"], p["documents"])
        correct = None if p["partial"] else round(p["score"])
        data.append({**{k: v for k, v in p.items() if k != "score"}, "correct": correct, "rate": rate,
                     "low": lo, "high": hi})
    data.sort(key=lambda d: (d["rate"], d["documents"], d["setup"]))
    partial = any(d["partial"] for d in data)

    name = _cohort_name(task, fingerprint)
    if not data:
        title = "No scored runs in this cohort"
    elif mock:
        title = "Only mock runs here, so every setup scores 100% by construction"
    elif len(data) == 1:
        d = data[0]
        title = _fit(f"One setup in this cohort: {_pct(d['rate'])} exact match on {d['documents']} documents",
                     "One setup in this cohort, so there is nothing to compare")
    elif partial:
        best = data[-1]
        title = _fit(f"Setup {best['setup']} scores highest at {_pct(best['rate'])}; partial credit has no interval",
                     "Partial-credit scores have no interval, so the setups are not ranked")
    else:
        best, rest = data[-1], data[:-1]
        overlapping = [d for d in rest if d["high"] >= best["low"]]
        if overlapping:
            title = f"No setup is clearly ahead: the top {len(overlapping) + 1} intervals overlap"
        else:
            title = _fit(f"Setup {best['setup']} leads at {_pct(best['rate'])} exact match",
                         f"One setup leads at {_pct(best['rate'])} exact match")
    measure, band = (("Mean score per setup", "no interval: partial-credit scores") if partial else
                     ("Exact match per setup", "95% Wilson interval on the dataset's documents"))
    subtitle = _subtitle([measure, name, band], [MOCK_NOTE] if mock else [])

    colour = fs.SYSTEM_COLOURS[fs.system_of_task(task)]
    with fs.Fig(salt="log-setups") as f:
        fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 1.2 + 0.45 * max(len(data), 1)))
        for yi, d in enumerate(data):
            if d["low"] is not None:
                ax.plot([100 * d["low"], 100 * d["high"]], [yi, yi], color=colour, linewidth=2.2,
                        solid_capstyle="butt", alpha=0.45)
            ax.plot(100 * d["rate"], yi, "o", color=colour, markersize=6.5,
                    markerfacecolor=fs.SURFACE if mock else colour)
            count = (f"{d['correct']}/{d['documents']}" if d["runs"] == 1 and d["correct"] is not None
                     else f"{d['documents']} docs")
            ax.annotate(f"{count} · {_runs(d['runs'])}", (100, yi), xytext=(8, 0),
                        textcoords="offset points", va="center", ha="left", fontsize=fs.SIZE["annotation"],
                        color=fs.INK_2)
        ax.set_yticks(range(len(data)), [d["setup"] for d in data])
        ax.set_xlim(0, 128)  # room for the count labels; the axis itself stops at 100%
        ax.set_xticks(range(0, 101, 20))
        ax.spines["bottom"].set_bounds(0, 100)
        ax.set_ylim(-0.6, max(len(data), 1) - 0.4)
        ax.xaxis.set_major_formatter(f.plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        fs.value_axis(ax, "x")
        fs.axis_labels(ax, x="Mean score (%)" if partial else "Exact match (% of documents)")
        fs.heading(fig, ax, title, subtitle, f"Source: {source} · dataset {fingerprint}")
        return f.svg(fig), data


# ---------------------------------------------------------------- figure 3: one cohort over time

def main_setup(rows: Iterable[dict[str, Any]], task: Any, fingerprint: Any) -> tuple[str, str, str, str] | None:
    """The cohort setup with the most runs (ties: the most recent run), the trend's default."""
    picked = _cohort_rows(rows, task, fingerprint)
    if not picked:
        return None
    last = {setup_key(r): i for i, r in enumerate(picked)}
    runs = {key: sum(setup_key(r) == key for r in picked) for key in last}
    return max(last, key=lambda key: (runs[key], last[key]))


def trend_svg(rows: Iterable[dict[str, Any]], task: Any, fingerprint: Any, setup: tuple | None = None,
              source: str = "experiment log") -> tuple[str, list[dict]]:
    """Exact match run by run (oldest to newest) for one setup in a cohort, each with a 95% Wilson
    interval. ``setup`` is a ``setup_key``; the default is ``main_setup``, so the line never joins
    runs of different setups."""
    rows = list(rows)
    cohort = _cohort_rows(rows, task, fingerprint)
    setup = tuple(setup) if setup is not None else main_setup(rows, task, fingerprint)
    picked = [r for r in cohort if setup_key(r) == setup]
    label = setup_labels(cohort).get(setup, "")
    others = len({setup_key(r) for r in cohort} - {setup})
    mock = bool(picked) and all(r["mock"] for r in picked)
    data = []
    for i, r in enumerate(picked, 1):
        n, partial = r["n_scored"], _partial(r)
        lo, hi = (None, None) if partial else fs.wilson(round(_score(r)), n)
        data.append({"run": i, "experiment": r["experiment"], "timestamp": str(r["timestamp"]), "setup": label,
                     "correct": None if partial else round(_score(r)), "documents": n, "rate": r[METRIC],
                     "partial": partial, "low": lo, "high": hi})
    partial = any(d["partial"] for d in data)

    if not data:
        title = "No scored runs in this cohort"
    elif mock:
        title = (f"All {len(data)} runs are mock, so exact match is 100% by construction" if len(data) > 1
                 else "The only run is mock, so exact match is 100% by construction")
    elif len(data) == 1:
        title = f"A single run so far: {_pct(data[0]['rate'])} exact match"
    elif partial:
        first, last = data[0], data[-1]
        title = _fit(f"Score went from {_pct(first['rate'])} to {_pct(last['rate'])} over {len(data)} runs; "
                     "partial credit has no interval",
                     f"Score went from {_pct(first['rate'])} to {_pct(last['rate'])} over {len(data)} runs")
    else:
        first, last = data[0], data[-1]
        ns = [d["documents"] for d in data]
        if first["high"] < last["low"] or last["high"] < first["low"]:
            title = f"Exact match moved from {_pct(first['rate'])} to {_pct(last['rate'])} over {len(data)} runs"
        else:
            lo, hi = min(d["rate"] for d in data), max(d["rate"] for d in data)
            level = (f"was {_pct(lo)} on every run" if lo == hi
                     else f"stayed within {100 * lo:.0f}–{_pct(hi)}")
            title = _fit(f"Exact match {level}; no change is resolvable at {_n_text(ns)}",
                         f"Exact match {level} over {len(data)} runs")
    dates = sorted(d["timestamp"][:10] for d in data)
    when = (dates[0] if dates[0] == dates[-1] else f"{dates[0]} to {dates[-1]}") if dates else "no dates"
    hidden = [f"{others} other setup{'s' if others > 1 else ''} not shown"] if others else []
    subtitle = _subtitle([_cohort_name(task, fingerprint),
                          "no interval: partial credit" if partial else "95% Wilson interval"],
                         ([f"setup {label.replace(' · ', ', ')}"] if label else []) + ([MOCK_NOTE] if mock else [])
                         + hidden + [when])

    colour = fs.SYSTEM_COLOURS[fs.system_of_task(task)]
    with fs.Fig(salt="log-trend") as f:
        fig, ax = f.plt.subplots(figsize=(fs.WIDTH, 3.0))
        xs = [d["run"] for d in data]
        bands = [d for d in data if d["low"] is not None]
        ax.vlines([d["run"] for d in bands], [100 * d["low"] for d in bands], [100 * d["high"] for d in bands],
                  color=colour, linewidth=2.2, alpha=0.4)
        ax.plot(xs, [100 * d["rate"] for d in data], "-o", color=colour, linewidth=1.2, markersize=5.5,
                markerfacecolor=fs.SURFACE if mock else colour)
        ax.set_ylim(0, 104)  # headroom so markers at 100% are not clipped
        ax.set_yticks(range(0, 101, 20))
        ax.spines["left"].set_bounds(0, 100)
        ax.set_xlim(0.4, max(len(data), 1) + 0.6)
        step = max(1, len(data) // 10)
        ax.set_xticks(list(range(1, len(data) + 1, step)) or [1])
        ax.yaxis.set_major_formatter(f.plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        fs.value_axis(ax, "y")
        fs.axis_labels(ax, x="Run, oldest to newest", y="Mean score (%)" if partial else "Exact match (%)")
        fs.heading(fig, ax, title, subtitle, f"Source: {source} · dataset {fingerprint}")
        return f.svg(fig), data
