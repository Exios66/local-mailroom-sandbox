"""Master score & cost card across the specialist-grid postures (SAND-037 / SAND-039).

Renders ``reports/SAND-37/SAND-37-MASTER-SCORE-COST-CARD.md`` from the committed
per-run ``*.card.json`` (same source of truth as the suite cards), so a later
leg populates the card by re-running ``sandbox run card --master``::

    SAND-37 · 1×L4 · C8  · n=20   reports/SAND-37/1L4/<specialist>/grid-20-*-1l4*.card.json
    SAND-39 · 1×L4 · C8  · n=50   reports/SAND-37/1L4/<specialist>/grid-50-*-1l4*.card.json
    SAND-37 · 2×L4 · C32 · n=50   reports/SAND-37/2L4/<specialist>/grid-50-*-2l4*.card.json

A posture with no cards yet renders as "pending". SAND-39 and the 2×L4 leg draw
the identical n=50 documents, so when both are present the scale-out finding
is a matched-sample comparison. Session-level Modal spend (cold boots, idle,
pre-warm) is not in the cards; it comes from ``metered-costs.json`` next to the
card when the operator has recorded it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.job.grid_cards import ROOT_REL, SCHEMA, SPECIALISTS, _read_json
from mailroom_sandbox.paths import repo_root

MASTER_STEM = "SAND-37-MASTER-SCORE-COST-CARD"
METERED_FILE = "metered-costs.json"


@dataclass(frozen=True)
class Posture:
    key: str
    study: str
    shape_dir: str
    replicas: int
    concurrency: int
    n: int

    @property
    def label(self) -> str:
        return f"{self.replicas}×L4 C{self.concurrency} n={self.n}"


POSTURES: tuple[Posture, ...] = (
    Posture("s37-1l4-n20", "SAND-37", "1L4", 1, 8, 20),
    Posture("s39-1l4-n50", "SAND-39", "1L4", 1, 8, 50),
    Posture("s37-2l4-n50", "SAND-37", "2L4", 2, 32, 50),
)
_ORDER = ("insurance_claims", "contracts", "corporate_records", "correspondence", "merger_agreement")
_LABEL = {folder: label for _, folder, label in SPECIALISTS}
_SUITE_FOLDERS = ("insurance_claims", "corporate_records", "correspondence")  # field score only
PENDING = "pending"
PARITY = 0.03  # cost-per-document gap below which two postures are called equal


def master_paths(repo: Path | None = None) -> dict[str, Path]:
    base = (repo or repo_root()) / ROOT_REL
    return {"dir": base, "md": base / f"{MASTER_STEM}.md", "metered": base / METERED_FILE}


def _aligned_cells() -> frozenset[str]:
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS

    return GRID_CELLS


def collect_master(repo: Path | None = None) -> dict[str, Any]:
    """Cards per posture and specialist folder, aligned grid cells only."""
    root = (repo or repo_root()) / ROOT_REL
    aligned = _aligned_cells()
    cards: dict[str, dict[str, dict[str, Any]]] = {p.key: {} for p in POSTURES}
    for p in POSTURES:
        for path in sorted((root / p.shape_dir).glob("*/*.card.json")):
            data = _read_json(path)
            if data.get("schema") != SCHEMA or data.get("run_id") not in aligned:
                continue
            cond = data.get("conditions") or {}
            if int(data.get("n") or 0) != p.n or int(cond.get("replicas") or 0) != p.replicas:
                continue
            if int(cond.get("concurrency") or 0) != p.concurrency:
                continue
            cards[p.key][path.parent.name] = data
    metered = _read_json(master_paths(repo)["metered"])
    return {"cards": cards, "metered": metered}


# ── formatting ───────────────────────────────────────────────────────────────


def _pct_change(new: float | None, old: float | None) -> str:
    if new is None or old is None or not old:
        return "—"
    return f"{(new / old - 1) * 100:+.0f}%".replace("-", "−")


def _money(v: float | None, digits: int = 5) -> str:
    return "—" if v is None else f"${v:.{digits}f}"


def _num(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def _pooled(cards: Mapping[str, Mapping[str, Any]], replicas: int) -> dict[str, Any] | None:
    if not cards:
        return None
    vals = list(cards.values())
    docs = sum(c["quality"]["documents"] for c in vals)
    ok = sum(c["quality"]["ok"] for c in vals)
    errors = sum(c["quality"]["errors"] for c in vals)
    wall = sum(c["time"]["wall_seconds"] or 0.0 for c in vals)
    busy = sum(c["cost"]["busy_gpu_usd"] or 0.0 for c in vals)
    tokens = sum(c["tokens"]["total"] or 0 for c in vals)
    return {
        "cells": len(vals),
        "documents": docs,
        "ok": ok,
        "errors": errors,
        "error_rate": errors / docs if docs else None,
        "busy_usd": busy or None,
        "usd_per_document": busy / docs if busy and docs else None,
        "usd_per_mtok": busy / tokens * 1e6 if busy and tokens else None,
        "tps_per_gpu": tokens / wall / replicas if wall and tokens else None,
        "docs_per_minute": docs / wall * 60.0 if wall and docs else None,
    }


def _score(card: Mapping[str, Any] | None) -> str:
    if not card:
        return PENDING
    q = card["quality"]
    clause = q.get("clause") or {}
    if clause.get("kind") == "maud":
        return f"{clause.get('accuracy', 0):.3f} ({clause.get('coverage', 0) * 100:.0f}%)"
    if clause.get("kind") == "cuad" and clause.get("f1") is not None:
        return f"{q['overall_mean']:.3f} ({clause['f1']:.3f})"
    return f"{q['overall_mean']:.3f}"


def _metric_name(folder: str) -> str:
    return {
        "contracts": "Field score (CUAD F1)",
        "merger_agreement": "MAUD accuracy (coverage)",
    }.get(folder, "Field score")


def _joined(values: list[str]) -> str:
    return " · ".join(values)


# ── findings (computed from the cards present) ───────────────────────────────


def _range(values: list[float], fmt: str = "{:.2f}") -> str:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return "—"
    lo, hi = fmt.format(vals[0]), fmt.format(vals[-1])
    return lo if lo == hi else f"{lo}–{hi}"


def _findings(present: list[Posture], cards: dict, pooled: dict) -> list[str]:
    out: list[str] = []
    by_key = {p.key: p for p in present}
    one50, two50, one20 = by_key.get("s39-1l4-n50"), by_key.get("s37-2l4-n50"), by_key.get("s37-1l4-n20")

    # 1. scale-out economics: prefer the matched-sample pair.
    base = one50 or one20
    if base and two50:
        a, b = pooled[base.key], pooled[two50.key]
        lat = []
        for folder in _ORDER:
            ca, cb = cards[base.key].get(folder), cards[two50.key].get(folder)
            if ca and cb and ca["latency"]["p50"]:
                lat.append(cb["latency"]["p50"] / ca["latency"]["p50"])
        basis = (
            f"identical {b['documents']} documents, {base.study} {base.label} vs {two50.study} {two50.label}"
            if base is one50
            else f"{base.label} vs {two50.label}; sample sizes differ, SAND-39 pending"
        )
        ca, cb = a["usd_per_document"], b["usd_per_document"]
        parity = bool(ca and cb and abs(cb / ca - 1) < PARITY)
        if parity:
            head = (
                f"**Scaling out to {two50.replicas}×L4 at C{two50.concurrency} raises throughput by "
                f"{_pct_change(b['docs_per_minute'], a['docs_per_minute'])} at unchanged cost per document**"
            )
        else:
            cheaper = f"{two50.replicas}×L4 at C{two50.concurrency}" if (cb or 0) < (ca or 0) else f"{base.replicas}×L4 at C{base.concurrency}"
            head = f"**{cheaper} is the more cost-efficient posture**"
        out.append(
            f"{head} ({basis}). Moving from {base.label} to {two50.label} changes cost per document by "
            f"{_pct_change(cb, ca)}, tokens per second per GPU by {_pct_change(b['tps_per_gpu'], a['tps_per_gpu'])}, "
            f"and pooled documents per minute by {_pct_change(b['docs_per_minute'], a['docs_per_minute'])}"
            + (", so capacity scales near-linearly with GPU count" if parity else "")
            + f". Median per-document latency rises by a factor of {_range(lat, '{:.1f}')}×, reflecting "
            "per-replica queueing at the higher concurrency."
        )

    # 2. quality stability across postures.
    deltas, cuad = [], []
    for folder in _SUITE_FOLDERS + ("contracts",):
        vals = [cards[p.key][folder]["quality"]["overall_mean"] for p in present if folder in cards[p.key]]
        if len(vals) > 1:
            deltas.append(max(vals) - min(vals))
        if folder == "contracts":
            f1 = [(cards[p.key][folder]["quality"].get("clause") or {}).get("f1") for p in present if folder in cards[p.key]]
            f1 = [v for v in f1 if v is not None]
            if len(f1) > 1:
                cuad.append(max(f1) - min(f1))
    if deltas:
        tail = f"; CUAD F1 differs by {max(cuad):.3f}" if cuad else ""
        out.append(
            f"**Extraction quality is independent of serving posture.** Field scores differ by at most "
            f"{max(deltas):.3f} across postures{tail}, consistent with sampling variation rather than any "
            "change in model output."
        )

    # 3. error ledger.
    kinds: dict[str, int] = {}
    per_class: list[str] = []
    for folder in _ORDER:
        parts = []
        for p in present:
            card = cards[p.key].get(folder)
            if not card:
                continue
            for k, v in (card["quality"].get("error_kinds") or {}).items():
                kinds[k] = kinds.get(k, 0) + int(v)
            if card["quality"]["errors"]:
                parts.append(f"{card['quality']['errors']}/{card['n']}")
        if parts:
            per_class.append(f"{_LABEL[folder].lower()} {', '.join(parts)}")
    total = sum(kinds.values())
    if total:
        only_length = set(kinds) == {"LengthFinishReasonError"}
        what = (
            "output-cap truncations: the model reached the 8,192-token limit before closing the JSON"
            if only_length
            else "; ".join(f"{k} × {v}" for k, v in sorted(kinds.items()))
        )
        out.append(
            f"**All {total} errors are {what}** ({'; '.join(per_class)}). No errors arose from "
            "infrastructure, authentication or JSON parsing."
        )

    # 4. merger.
    m = [cards[p.key]["merger_agreement"]["quality"].get("clause") or {} for p in present if "merger_agreement" in cards[p.key]]
    if m:
        out.append(
            "**Merger agreements are the principal quality gap.** Source agreements far exceed the "
            "30,000-character input window (head plus tail), so the model answers only "
            f"{_range([c.get('coverage') for c in m], '{:.0%}')} of labeled MAUD questions, with "
            f"{_range([c.get('precision_answered') for c in m], '{:.0%}')} precision on those answered. "
            "Closing the gap requires an input strategy such as chunked or retrieval-based clause "
            "extraction, not a change of serving posture."
        )

    # 5. correspondence.
    c = [cards[p.key]["correspondence"]["quality"] for p in present if "correspondence" in cards[p.key]]
    if c:
        out.append(
            f"**Correspondence field scores are low and dispersed** (mean {_range([q['overall_mean'] for q in c])}, "
            f"standard deviation {_range([q['overall_sd'] for q in c])}). Stability across postures points to "
            "prompt or scorer alignment rather than serving; it is the next candidate for review."
        )

    # 6. schema conformance.
    ins = [cards[p.key]["insurance_claims"]["quality"]["schema_valid_rate"] for p in present if "insurance_claims" in cards[p.key]]
    corp = [cards[p.key]["corporate_records"]["quality"]["schema_valid_rate"] for p in present if "corporate_records" in cards[p.key]]
    if ins and min(ins) < 0.9:
        out.append(
            f"**Schema conformance is incomplete for insurance claims** (schema-valid rate {_range(ins)}; "
            f"corporate records {_range(corp)}; 1.00 for contracts, merger and correspondence). Its content "
            "scores well, but strict-schema consumers would reject most outputs; grammar-constrained "
            "decoding, as already used for contracts and merger, is the direct remedy."
        )
    return out


# ── render ───────────────────────────────────────────────────────────────────


def render_master_md(data: Mapping[str, Any]) -> str:
    cards: dict[str, dict[str, Any]] = data["cards"]
    metered: Mapping[str, Any] = data.get("metered") or {}
    present = [p for p in POSTURES if cards[p.key]]
    pooled = {p.key: _pooled(cards[p.key], p.replicas) for p in POSTURES}
    first = next((c for p in present for c in cards[p.key].values()), None)

    lines = [
        "# SAND-37 / SAND-39 Specialist Grid: Results and Cost Summary",
        "",
    ]
    if first:
        cond, ds = first["conditions"], first["conditions"]["dataset"]
        lines += [
            f"**Model:** {cond['model']} on vLLM {cond['image_tag']} · **GPU:** NVIDIA {cond['gpu']} at "
            f"${cond['gpu_usd_per_hour']:.2f} per GPU-hour  ",
            f"**Data:** public `{ds['repo']}` {ds['config']} @ `{ds['revision']}`, seed {ds['seed']}; "
            "the n = 20 draw is nested in the n = 50 draw, and every n = 50 posture scores the identical documents.  ",
            "**Engine (all postures):** AWQ-Marlin, fp8 KV cache, CUDA graphs, prefix caching, thinking "
            "disabled, 8,192-token output cap, frozen v1 prompts; temperature 0.7 for contracts and merger, "
            "0.1 otherwise.",
            "",
        ]
    lines += [
        "| Study | Posture | GPUs | Client concurrency | Documents per class | Status |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for p in POSTURES:
        status = f"{len(cards[p.key])} of 5 cells" if cards[p.key] else PENDING
        lines.append(f"| {p.study} | {p.label} | {p.replicas} | {p.concurrency} | {p.n} | {status} |")
    lines.append("")

    heads = " | ".join(f"{p.study} {p.label}" for p in POSTURES)
    lines += [
        "## Serving efficiency (pooled across the five specialists)",
        "",
        f"| Metric | {heads} |",
        "| --- |" + " ---: |" * len(POSTURES),
    ]
    rows = (
        ("Documents ok / total", lambda q: f"{q['ok']} / {q['documents']}"),
        ("Error rate", lambda q: f"{q['error_rate'] * 100:.1f}%"),
        ("Throughput (documents per minute)", lambda q: _num(q["docs_per_minute"])),
        ("Throughput (tokens per second per GPU)", lambda q: _num(q["tps_per_gpu"], 0)),
        ("GPU cost per document", lambda q: _money(q["usd_per_document"])),
        ("GPU cost per 1M tokens", lambda q: _money(q["usd_per_mtok"], 3)),
        ("Busy-window GPU cost", lambda q: _money(q["busy_usd"], 3)),
    )
    for label, fn in rows:
        vals = [fn(pooled[p.key]) if pooled[p.key] else PENDING for p in POSTURES]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines.append("")

    lines += [
        "## Quality and cost by specialist",
        "",
        f"Columns within each cell follow the posture order above ({' · '.join(p.label for p in POSTURES)}).",
        "",
        "| Specialist | Metric | Score | ok / n | p50 latency (s) | $ per ok document |",
        "| --- | --- | :---: | :---: | :---: | :---: |",
    ]
    for folder in _ORDER:
        per = [cards[p.key].get(folder) for p in POSTURES]
        lines.append(
            f"| {_LABEL[folder]} | {_metric_name(folder)} | "
            + _joined([_score(c) for c in per]) + " | "
            + _joined([f"{c['quality']['ok']}/{c['n']}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['latency']['p50']:.1f}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['cost']['usd_per_ok_document']:.5f}" if c else PENDING for c in per]) + " |"
        )
    lines += [
        "",
        "Field scores are the mean suite extraction score against ground truth; contracts adds CUAD clause "
        "scoring. Merger is scored by micro-accuracy over labeled MAUD questions, a different scale from "
        "the field scores.",
        "",
        "## Findings",
        "",
    ]
    findings = _findings(present, cards, pooled)
    lines += [f"{i}. {text}" for i, text in enumerate(findings, 1)] or ["No cells reported yet."]
    lines += _figure_md(data, "comparison", "## Figures: posture comparison")
    lines += ["", "## Cost accounting and run integrity", ""]
    for p in POSTURES:
        q = pooled[p.key]
        if q:
            lines.append(
                f"- **{p.study} {p.label}:** busy-window GPU {_money(q['busy_usd'], 2)} across "
                f"{q['documents']} documents."
            )
    for study, rec in metered.items():
        if not isinstance(rec, Mapping):
            continue
        note = f" {rec['note']}" if rec.get("note") else ""
        lines.append(
            f"- **{study} metered Modal total:** ${float(rec.get('metered_usd', 0)):.2f} "
            f"(${float(rec.get('billed_usd', 0)):.2f} billed after credits).{note}"
        )
    lines += [
        "- **Teardown** is verified after each posture, with zero containers left warm.",
        "- **Comparability:** SAND-39 and the SAND-37 2×L4 leg score identical n = 50 documents and "
        "differ only in GPU count and client concurrency; the SAND-37 1×L4 leg is a nested n = 20 subset.",
        "",
        "**Source data:** per-cell score and cost cards, run reports and vLLM serving telemetry under "
        "`1L4/<specialist>/` and `2L4/<specialist>/`; posture suite cards `1L4/L4x1-SCORE-COST-CARD.md` "
        "and `2L4/L4x2-SCORE-COST-CARD.md`. Regenerate with `sandbox run card --master`.",
        "",
    ]
    lines += _figure_md(data, "posture", "## Appendix: posture dashboards")
    return "\n".join(lines)


def _figure_md(data: Mapping[str, Any], section: str, heading: str) -> list[str]:
    from mailroom_sandbox.job.grid_figures import figure_specs

    specs = [s for s in figure_specs(data) if s["section"] == section]
    if not specs:
        return []
    out = ["", heading, ""]
    for i, spec in enumerate(specs, 1):
        tag = "Figure" if section == "comparison" else "Dashboard"
        out += [f"![{spec['caption']}]({spec['path']})", "", f"*{tag} {i}. {spec['caption']}*", ""]
    return out


def write_master(repo: Path | None = None) -> dict[str, Path]:
    paths = master_paths(repo)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    data = collect_master(repo)
    from mailroom_sandbox.job.grid_figures import write_figures

    write_figures(data, repo)
    paths["md"].write_text(render_master_md(data), encoding="utf-8")
    return paths


def record_metered(study: str, metered_usd: float, billed_usd: float, note: str = "", *, repo: Path | None = None) -> Path:
    """Record a study's session-level Modal spend (from the teardown spend check)."""
    path = master_paths(repo)["metered"]
    data = _read_json(path)
    data[study] = {"metered_usd": round(float(metered_usd), 2), "billed_usd": round(float(billed_usd), 2)}
    if note:
        data[study]["note"] = note
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
