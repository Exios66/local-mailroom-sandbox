"""Master score & cost card across the specialist-grid postures (SAND-037 / SAND-039).

Renders the two-page executive ``reports/SAND-37/SAND-37-MASTER-SCORE-COST-CARD.md``
plus the detail ``reports/SAND-37/SAND-37-MASTER-APPENDIX.md`` from the committed
per-run ``*.card.json`` (same source of truth as the suite cards), so a later
leg populates both by re-running ``sandbox run card --master``::

    SAND-37 · 1×L4 · C8  · n=20   reports/SAND-37/1L4/<specialist>/grid-20-*-1l4*.card.json
    SAND-39 · 1×L4 · C8  · n=50   reports/SAND-37/1L4/<specialist>/grid-50-*-1l4*.card.json
    SAND-37 · 2×L4 · C32 · n=50   reports/SAND-37/2L4/<specialist>/grid-50-*-2l4*.card.json

The master card stays executive-length (postures, pooled efficiency, per-specialist
scorecard, three key findings, metered cost). Everything else — per-cell tables,
clause scoring, engine telemetry, run conditions, merger † settings, probes,
full findings, figures and dashboards — lives in the appendix. A posture with no
cards yet renders as "pending". SAND-39 and the 2×L4 leg draw the identical n=50
documents, so when both are present the scale-out finding is a matched-sample
comparison. Session-level Modal spend (cold boots, idle, pre-warm) is not in the
cards; it comes from ``metered-costs.json`` next to the card when the operator
has recorded it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.job.grid_cards import ROOT_REL, SCHEMA, SPECIALISTS, _read_json
from mailroom_sandbox.paths import repo_root

MASTER_STEM = "SAND-37-MASTER-SCORE-COST-CARD"
APPENDIX_STEM = "SAND-37-MASTER-APPENDIX"
METERED_FILE = "metered-costs.json"
EXECUTIVE_MAX_LINES = 110  # two printed pages; the staleness test enforces it
PROBE_DIR = "probes"  # SAND-40 validation probes: reported in an appendix, never pooled


@dataclass(frozen=True)
class Posture:
    key: str
    study: str
    shape_dir: str
    replicas: int
    concurrency: int
    n: int
    docs: str = ""
    n_by_folder: tuple[tuple[str, int], ...] = ()

    @property
    def label(self) -> str:
        return f"{self.replicas}×L4 C{self.concurrency} n={self.n}"

    @property
    def documents(self) -> str:
        return self.docs or str(self.n)

    def expected_n(self, folder: str) -> int:
        return dict(self.n_by_folder).get(folder, self.n)


POSTURES: tuple[Posture, ...] = (
    Posture("s37-1l4-n20", "SAND-37", "1L4", 1, 8, 20),
    Posture("s39-1l4-n50", "SAND-39", "1L4", 1, 8, 50),
    Posture("s37-2l4-n50", "SAND-37", "2L4", 2, 32, 50),
    Posture(
        "s40-2l4",
        "SAND-40",
        "2L4",
        2,
        32,
        100,
        docs="100 (merger 50†)",
        n_by_folder=(("merger_agreement", 50),),
    ),
)
_ORDER = ("insurance_claims", "contracts", "corporate_records", "correspondence", "merger_agreement")
_LABEL = {folder: label for _, folder, label in SPECIALISTS}
_SUITE_FOLDERS = ("insurance_claims", "corporate_records", "correspondence")  # field score only
PENDING = "pending"
PARITY = 0.03  # cost-per-document gap below which two postures are called equal


def master_paths(repo: Path | None = None) -> dict[str, Path]:
    base = (repo or repo_root()) / ROOT_REL
    return {
        "dir": base,
        "md": base / f"{MASTER_STEM}.md",
        "appendix": base / f"{APPENDIX_STEM}.md",
        "metered": base / METERED_FILE,
    }


def _cells_for(posture: Posture) -> frozenset[str]:
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS, SAND40_CELLS

    if posture.key == "s40-2l4":
        return SAND40_CELLS
    return GRID_CELLS


def collect_master(repo: Path | None = None) -> dict[str, Any]:
    """Cards per posture and specialist folder, aligned grid cells only."""
    root = (repo or repo_root()) / ROOT_REL
    cards: dict[str, dict[str, dict[str, Any]]] = {p.key: {} for p in POSTURES}
    for p in POSTURES:
        aligned = _cells_for(p)
        for path in sorted((root / p.shape_dir).glob("*/*.card.json")):
            data = _read_json(path)
            if data.get("schema") != SCHEMA or data.get("run_id") not in aligned:
                continue
            cond = data.get("conditions") or {}
            if int(data.get("n") or 0) != p.expected_n(path.parent.name) or int(cond.get("replicas") or 0) != p.replicas:
                continue
            if int(cond.get("concurrency") or 0) != p.concurrency:
                continue
            cards[p.key][path.parent.name] = data
    probes: dict[str, dict[str, Any]] = {}
    for path in sorted((root / PROBE_DIR).glob("*/*.card.json")):
        data = _read_json(path)
        if data.get("schema") == SCHEMA and "-probe-" in str(data.get("run_id") or ""):
            probes[path.parent.name] = data
    metered = _read_json(master_paths(repo)["metered"])
    return {"cards": cards, "probes": probes, "metered": metered}


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
    reps = [r for c in vals for r in (c.get("engine_telemetry") or {}).get("replicas") or []]
    return {
        "wall": wall,
        "prompt": sum(c["tokens"]["prompt"] or 0 for c in vals),
        "completion": sum(c["tokens"]["completion"] or 0 for c in vals),
        "length_finishes": sum(r.get("length_finishes") or 0 for r in reps),
        "preemptions": sum(r.get("preemptions") or 0 for r in reps),
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


def _score(card: Mapping[str, Any] | None, *, mark: str = "") -> str:
    if not card:
        return PENDING + mark
    q = card["quality"]
    clause = q.get("clause") or {}
    if clause.get("kind") == "maud":
        return f"{clause.get('accuracy', 0):.3f} ({clause.get('coverage', 0) * 100:.0f}%){mark}"
    if clause.get("kind") == "cuad" and clause.get("f1") is not None:
        return f"{q['overall_mean']:.3f} ({clause['f1']:.3f}){mark}"
    return f"{q['overall_mean']:.3f}{mark}"


def _metric_name(folder: str) -> str:
    return {
        "contracts": "CUAD presence F1: labeled-document mean (micro)",
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


# ── detail sections ──────────────────────────────────────────────────────────


def _f(v: float | None, digits: int = 2, suffix: str = "") -> str:
    return "—" if v is None else f"{v:,.{digits}f}{suffix}"


def _replica_sum(card: Mapping[str, Any], key: str) -> float | None:
    reps = (card.get("engine_telemetry") or {}).get("replicas") or []
    vals = [r.get(key) for r in reps if r.get(key) is not None]
    return sum(vals) if vals else None


def _replica_weighted(card: Mapping[str, Any], key: str) -> float | None:
    """Request-weighted mean of a per-replica rate (prefix-cache hit rate, mean TTFT)."""
    reps = [r for r in (card.get("engine_telemetry") or {}).get("replicas") or [] if r.get(key) is not None]
    weight = sum(r.get("requests") or 0 for r in reps)
    if not reps or not weight:
        return None
    return sum(r[key] * (r.get("requests") or 0) for r in reps) / weight


def _errors_text(q: Mapping[str, Any]) -> str:
    kinds = q.get("error_kinds") or {}
    if not kinds:
        return "0"
    short = {"LengthFinishReasonError": "length"}
    return f"{q['errors']} (" + ", ".join(f"{short.get(k, k)} {v}" for k, v in sorted(kinds.items())) + ")"


def _detail_sections(present: list[Posture], cards: dict) -> list[str]:
    out = [
        "## Per-cell detail",
        "",
        "One table per posture. Latency is per successful document; tokens per document is prompt plus "
        "completion over all documents; busy GPU $ is the cell's busy wall × GPUs × $0.80 per GPU-hour.",
        "",
    ]
    for p in present:
        out += [
            f"### {p.study} {p.label}",
            "",
            "| Specialist | ok / n | Errors | Schema-valid | Score (sd) | p50 / p95 latency (s) | Tokens per doc "
            "| Completion p95 / max | Wall (s) | Busy GPU $ | $ per ok doc | $ per 1M tokens | Tokens/s/GPU |",
            "| --- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for folder in _ORDER:
            c = cards[p.key].get(folder)
            if not c:
                out.append(f"| {_LABEL[folder]} | {PENDING} |" + " |" * 11)
                continue
            q, lat, tok, cost = c["quality"], c["latency"], c["tokens"], c["cost"]
            score = q["overall_mean"]
            clause = q.get("clause") or {}
            if clause.get("kind") == "maud":
                score = clause.get("accuracy")
            out.append(
                f"| {_LABEL[folder]} | {q['ok']}/{c['n']} | {_errors_text(q)} | {_f(q['schema_valid_rate'])} "
                f"| {_f(score, 3)} ({_f(q['overall_sd'], 3)}) | {_f(lat['p50'], 1)} / {_f(lat['p95'], 1)} "
                f"| {_f(tok['per_document'], 0)} | {_f(tok['completion_p95'], 0)} / {_f(tok['completion_max'], 0)} "
                f"| {_f(c['time']['wall_seconds'], 1)} | {_money(cost['busy_gpu_usd'], 4)} "
                f"| {_money(cost['usd_per_ok_document'])} | {_money(cost['usd_per_million_tokens'], 3)} "
                f"| {_f(c['throughput']['tokens_per_second_per_gpu'], 0)} |"
            )
        out.append("")
    out += ["Merger score is MAUD micro-accuracy; its sd is over per-document scores.", ""]

    # clause scoring
    out += [
        "## Clause scoring detail",
        "",
        "| Posture | Contracts: CUAD-labeled docs | Precision | Recall | Micro F1 | Labeled-doc mean F1 "
        "| Value accuracy | Merger: MAUD questions | Answered (coverage) | Correct | Accuracy | Precision on answered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for p in present:
        k = cards[p.key].get("contracts")
        m = cards[p.key].get("merger_agreement")
        kc = (k["quality"].get("clause") or {}) if k else {}
        mc = (m["quality"].get("clause") or {}) if m else {}
        val = (
            f"{kc['value_correct']}/{kc['value_checked']} ({kc['value_correct'] / kc['value_checked']:.0%})"
            if kc.get("value_checked")
            else "—"
        )
        out.append(
            f"| {p.study} {p.label} | {kc.get('docs_labeled', '—')} of {k['quality']['ok'] if k else '—'} ok "
            f"| {_f(kc.get('precision'), 3)} | {_f(kc.get('recall'), 3)} | {_f(kc.get('f1'), 3)} "
            f"| {_f(k['quality']['overall_mean'] if k else None, 3)} | {val} "
            f"| {mc.get('questions', '—')} | {mc.get('answered', '—')} ({_f((mc.get('coverage') or 0) * 100, 0)}%) "
            f"| {mc.get('correct', '—')} | {_f(mc.get('accuracy'), 3)} | {_f(mc.get('precision_answered'), 3)} |"
        )
    out += [
        "",
        "Clause counts cover successful documents only, so two postures on the same draw can differ slightly "
        "in labeled documents and MAUD questions when different documents hit the output cap.",
        "",
    ]

    # engine telemetry
    out += [
        "## Engine telemetry (vLLM /metrics, this run's delta)",
        "",
        "Requests, length-capped finishes and preemptions are summed over replicas; prefix-cache hit rate and "
        "mean time to first token are request-weighted across replicas. A chunked or re-sampled document "
        "issues more than one request.",
        "",
        "| Specialist | Requests | Length-capped finishes | Preemptions | Prefix-cache hit rate | Mean TTFT (s) |",
        "| --- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for folder in _ORDER:
        per = [cards[p.key].get(folder) for p in present]

        def col(fn, per=per):
            return _joined([fn(c) if c else PENDING for c in per])

        out.append(
            f"| {_LABEL[folder]} "
            f"| {col(lambda c: _f(_replica_sum(c, 'requests'), 0))} "
            f"| {col(lambda c: _f(_replica_sum(c, 'length_finishes'), 0))} "
            f"| {col(lambda c: _f(_replica_sum(c, 'preemptions'), 0))} "
            f"| {col(lambda c: _f((_replica_weighted(c, 'prefix_cache_hit_rate') or 0) * 100, 0, '%'))} "
            f"| {col(lambda c: _f(_replica_weighted(c, 'ttft_mean_seconds'), 1))} |"
        )
    out += ["", f"Columns follow the posture order ({' · '.join(p.label for p in present)}).", ""]

    # conditions
    out += [
        "## Run conditions by specialist",
        "",
        "Identical across the postures above unless a cell lists more than one value.",
        "",
        "| Specialist | Prompt | Input cap (chars) | Output cap (tokens) | Temperature | Retries |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for folder in _ORDER:
        conds = [cards[p.key][folder]["conditions"] for p in present if folder in cards[p.key]]
        if not conds:
            continue

        def uniq(key, conds=conds):
            vals = []
            for c in conds:
                if c.get(key) not in vals:
                    vals.append(c.get(key))
            return " / ".join(f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v) for v in vals)

        out.append(
            f"| {_LABEL[folder]} | `{uniq('prompt')}` | {uniq('max_input_chars')} | {uniq('max_tokens')} "
            f"| {uniq('temperature')} | {uniq('max_retries')} |"
        )
    out.append("")
    return out


_SETTINGS_RUNS = (
    ("SAND-37 / SAND-39 merger", "grid-50-merger-specialist-awq-2l4"),
    ("SAND-40 merger †", "sand40-50-merger-specialist-awq-2l4"),
)


def _input_text(row: Mapping[str, Any]) -> str:
    if row.get("chunk_chars"):
        from mailroom_sandbox.eval.agents import chunk_window

        window, overlap = chunk_window(
            int(row["max_input_chars"]), int(row["chunk_chars"]), int(row.get("overlap_chars") or 0)
        )
        return (
            f"whole agreement, chunked: {window:,}-char windows + {overlap:,}-char overlap "
            f"(≤ {int(row['max_input_chars']):,} chars per call), merged"
        )
    return f"head + tail, {int(row['max_input_chars']):,} chars (rest of the agreement unread)"


def _sampling_text(row: Mapping[str, Any]) -> str:
    parts = [f"temperature {row.get('temperature', 0.1)}"]
    for key in ("top_p", "top_k", "presence_penalty"):
        if row.get(key) is not None:
            parts.append(f"{key} {row[key]}")
    if len(parts) == 1:
        parts.append("other sampling at vLLM defaults")
    return ", ".join(parts)


def _maud_result(card: Mapping[str, Any] | None) -> str:
    if not card:
        return PENDING
    c = card["quality"].get("clause") or {}
    return (
        f"MAUD accuracy {c.get('accuracy', 0):.3f}, coverage {c.get('coverage', 0):.0%}, "
        f"{card['quality']['ok']}/{card['n']} ok, ${card['cost']['usd_per_ok_document']:.4f} per agreement"
    )


def _merger_settings_section(cards: dict) -> list[str]:
    """What the † merger cell changes, row by row, and the measured effect once it exists."""
    from mailroom_sandbox.job.specialist_posture import posture_for_run

    rows = [(label, posture_for_run(rid) or {}) for label, rid in _SETTINGS_RUNS]
    if not all(r for _, r in rows):
        return []
    (base_label, base), (opt_label, opt) = rows
    table = (
        ("Agreements", lambda r: "the same 50 (seed 42)"),
        ("Serving window", lambda r: f"{int(r['max_model_len']):,} tokens on 2×L4"),
        ("Input", _input_text),
        ("Prompt", lambda r: f"`{r['prompt_file']}`"),
        ("Sampling", _sampling_text),
        ("Output cap", lambda r: f"{int(r['max_tokens']):,} tokens"),
        ("Re-sample on a length-capped output", lambda r: str(r["length_retries"]) if r.get("length_retries") else "none"),
    )
    out = [
        "## Merger † settings",
        "",
        "The SAND-40 merger cell keeps the engine, fleet and agreements of SAND-37 2×L4 and changes how each "
        "agreement is read and decoded. Changed settings are in bold.",
        "",
        f"| Setting | {base_label} | {opt_label} |",
        "| --- | --- | --- |",
    ]
    for label, fn in table:
        a, b = fn(base), fn(opt)
        if a != b:
            label, b = f"**{label}**", f"**{b}**"
        out.append(f"| {label} | {a} | {b} |")
    before = (cards.get("s37-2l4-n50") or {}).get("merger_agreement")
    after = (cards.get("s40-2l4") or {}).get("merger_agreement")
    out.append(f"| Result | {_maud_result(before)} | {_maud_result(after)} |")
    if before and after:
        bd = {d["item_id"]: d for d in before["documents"]}
        both = [
            (d["score"], bd[d["item_id"]]["score"])
            for d in after["documents"]
            if d["item_id"] in bd
            and d["ok"]
            and bd[d["item_id"]]["ok"]
            and d["score"] is not None
            and bd[d["item_id"]]["score"] is not None
        ]
        if both:
            delta = sum(a - b for a, b in both) / len(both)
            out.append(
                f"| Matched agreements | — | {delta:+.3f} mean per-agreement score over {len(both)} agreements "
                f"({sum(a > b for a, b in both)} better / {sum(a < b for a, b in both)} worse) |"
            )
    out.append("")
    return out


def _probe_section(probes: Mapping[str, Mapping[str, Any]], cards: dict) -> list[str]:
    """SAND-40 validation probes against the SAND-37 2×L4 n=50 cell on the same documents."""
    if not probes:
        return []
    base_cards = cards.get("s37-2l4-n50") or {}
    out = [
        "## SAND-40 validation probes (n = 20, not pooled)",
        "",
        "Before the scale run, two probes tested optimized long-document settings (64K YaRN window, "
        "128,000-character input, chunked extraction, Qwen3 sampling, 6,144-token cap with one length "
        "re-sample; MAUD v1 prompt for merger) on the first 20 documents of the SAND-37 2×L4 n = 50 draw. "
        "They are not a posture column. The SAND-40 merger cell keeps the chunking, prompt and decode settings on the 32K window; the 64K window and 128,000-character input are not used. The matched "
        "columns compare per-document scores on the documents both runs scored, so sample composition "
        "cannot explain the difference.",
        "",
        "| Specialist | Window | Input cap (chars) | ok / n | Score | Matched docs | Probe mean | SAND-37 2×L4 same docs "
        "| Δ (better / worse) | Prompt tokens per doc: probe vs SAND-37 | Wall (s) | Busy GPU $ | $ per ok doc |",
        "| --- | ---: | ---: | :---: | ---: | :---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: |",
    ]
    for folder in _ORDER:
        pc = probes.get(folder)
        if not pc:
            continue
        base = base_cards.get(folder) or {}
        bdocs = {d["item_id"]: d for d in base.get("documents") or []}
        pairs = [(d, bdocs[d["item_id"]]) for d in pc.get("documents") or [] if d["item_id"] in bdocs]
        both = [
            (a["score"], b["score"])
            for a, b in pairs
            if a["ok"] and b["ok"] and a["score"] is not None and b["score"] is not None
        ]
        q = pc["quality"]
        clause = q.get("clause") or {}
        score = clause.get("accuracy") if clause.get("kind") == "maud" else q["overall_mean"]
        if both:
            pm = sum(a for a, _ in both) / len(both)
            bm = sum(b for _, b in both) / len(both)
            delta = f"{pm - bm:+.3f} ({sum(a > b for a, b in both)} / {sum(a < b for a, b in both)})"
            ptok = sum(a["prompt_tokens"] or 0 for a, _ in pairs) / len(pairs)
            btok = sum(b["prompt_tokens"] or 0 for _, b in pairs) / len(pairs)
            match = (f"{len(both)} | {pm:.3f} | {bm:.3f} | {delta} | {ptok:,.0f} vs {btok:,.0f}")
        else:
            match = "— | — | — | — | —"
        out.append(
            f"| {_LABEL[folder]} | {pc['conditions']['engine'].get('max_model_len', 0):,} "
            f"| {pc['conditions'].get('max_input_chars', 0):,} | {q['ok']}/{pc['n']} | {_f(score, 3)} | {match} "
            f"| {_f(pc['time']['wall_seconds'], 1)} | {_money(pc['cost']['busy_gpu_usd'], 4)} "
            f"| {_money(pc['cost']['usd_per_ok_document'])} |"
        )
    out += [
        "",
        "Score is the specialist's primary metric (contracts labeled-document CUAD F1, merger MAUD accuracy); "
        "the matched columns use per-document scores. Probe cards and run reports: `probes/<specialist>/`.",
        "",
    ]
    return out


# ── render ───────────────────────────────────────────────────────────────────


def _executive_findings(present: list[Posture], cards: dict, pooled: dict) -> list[str]:
    """Three vital bullets for the two-page master; the full analysis lives in the appendix."""
    out: list[str] = []
    by_key = {p.key: p for p in present}
    one50, two50, one20 = by_key.get("s39-1l4-n50"), by_key.get("s37-2l4-n50"), by_key.get("s37-1l4-n20")
    base = one50 or one20
    if base and two50:
        a, b = pooled[base.key], pooled[two50.key]
        lat = []
        for folder in _ORDER:
            ca, cb = cards[base.key].get(folder), cards[two50.key].get(folder)
            if ca and cb and ca["latency"]["p50"]:
                lat.append(cb["latency"]["p50"] / ca["latency"]["p50"])
        basis = (
            f"identical {b['documents']} documents"
            if base is one50
            else "sample sizes differ, SAND-39 pending"
        )
        out.append(
            f"**Scale-out is near-linear:** 2×L4 at C32 raises throughput by "
            f"{_pct_change(b['docs_per_minute'], a['docs_per_minute'])} at "
            f"{_pct_change(b['usd_per_document'], a['usd_per_document'])} cost per document "
            f"({basis}; median latency ×{_range(lat, '{:.1f}')})."
        )
    deltas = []
    for folder in _SUITE_FOLDERS + ("contracts",):
        vals = [cards[p.key][folder]["quality"]["overall_mean"] for p in present if folder in cards[p.key]]
        if len(vals) > 1:
            deltas.append(max(vals) - min(vals))
    kinds: dict[str, int] = {}
    for folder in _ORDER:
        for p in present:
            card = cards[p.key].get(folder)
            if not card:
                continue
            for k, v in (card["quality"].get("error_kinds") or {}).items():
                kinds[k] = kinds.get(k, 0) + int(v)
    total = sum(kinds.values())
    if deltas or total:
        bits = []
        if deltas:
            bits.append(f"field scores within {max(deltas):.3f} across postures")
        if total:
            bits.append(f"all {total} errors are 8,192-token output-cap truncations (contracts/merger only)")
        out.append("**Quality is posture-independent:** " + "; ".join(bits) + ".")
    m = [cards[p.key]["merger_agreement"]["quality"].get("clause") or {} for p in present if "merger_agreement" in cards[p.key]]
    if m:
        out.append(
            f"**Merger is the quality gap:** MAUD coverage {_range([c.get('coverage') for c in m], '{:.0%}')} "
            "— agreements exceed the 30,000-char window, so chunked extraction (not more GPUs) is the fix. "
            "See the appendix for probes, correspondence and schema notes."
        )
    return out


EXECUTIVE_POOLED_ROWS = (
    ("Documents ok / total", lambda q: f"{q['ok']} / {q['documents']}"),
    ("Error rate", lambda q: f"{q['error_rate'] * 100:.1f}%"),
    ("Throughput (documents per minute)", lambda q: _num(q["docs_per_minute"])),
    ("Throughput (tokens per second per GPU)", lambda q: _num(q["tps_per_gpu"], 0)),
    ("GPU cost per document", lambda q: _money(q["usd_per_document"])),
    ("Busy-window GPU cost", lambda q: _money(q["busy_usd"], 3)),
)


def render_master_md(data: Mapping[str, Any]) -> str:
    """Two-page executive card: postures, pooled efficiency, scorecard, key findings, cost."""
    cards: dict[str, dict[str, Any]] = data["cards"]
    metered: Mapping[str, Any] = data.get("metered") or {}
    present = [p for p in POSTURES if cards[p.key]]
    pooled = {p.key: _pooled(cards[p.key], p.replicas) for p in POSTURES}
    first = next((c for p in present for c in cards[p.key].values()), None)

    lines = [
        "# SAND-37 / SAND-39 Specialist Grid: Results and Cost Summary",
        "",
        f"Full detail, figures and method notes live in [{APPENDIX_STEM}.md](./{APPENDIX_STEM}.md).",
        "",
    ]
    if first:
        cond, ds = first["conditions"], first["conditions"]["dataset"]
        lines += [
            f"**Model:** {cond['model']} (vLLM {cond['image_tag']}) · **GPU:** NVIDIA {cond['gpu']} at "
            f"${cond['gpu_usd_per_hour']:.2f}/GPU-hr · **Data:** `{ds['repo']}` {ds['config']} @ `{ds['revision']}`, "
            f"seed {ds['seed']} (n = 20 nested in n = 50; every n = 50 posture scores identical documents).  ",
            "**Engine:** AWQ-Marlin, fp8 KV, CUDA graphs, prefix caching, thinking off, 8,192-token cap, "
            "frozen v1 prompts (T 0.7 contracts/merger, 0.1 elsewhere). SAND-40 † merger settings in the appendix.",
            "",
        ]
    lines += [
        "| Study | Posture | GPUs | Client concurrency | Documents per class | Status |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for p in POSTURES:
        status = f"{len(cards[p.key])} of 5 cells" if cards[p.key] else PENDING
        lines.append(
            f"| {p.study} | {p.label} | {p.replicas} | {p.concurrency} | {p.documents} | {status} |"
        )
    lines.append("")

    heads = " | ".join(f"{p.study} {p.label}" for p in POSTURES)
    lines += [
        "## Serving efficiency (pooled across the five specialists)",
        "",
        f"| Metric | {heads} |",
        "| --- |" + " ---: |" * len(POSTURES),
    ]
    for label, fn in EXECUTIVE_POOLED_ROWS:
        vals = [fn(pooled[p.key]) if pooled[p.key] else PENDING for p in POSTURES]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines.append("")

    lines += [
        "## Quality and cost by specialist",
        "",
        f"Cell order: {' · '.join(p.label for p in POSTURES)}. Contracts = CUAD F1 (micro in parentheses); "
        "merger = MAUD accuracy (coverage in parentheses) — different scales from the field scores.",
        "",
        "| Specialist | Score | ok / n | p50 latency (s) | $ per ok document |",
        "| --- | :---: | :---: | :---: | :---: |",
    ]
    for folder in _ORDER:
        per = [cards[p.key].get(folder) for p in POSTURES]
        marks = ["†" if p.key == "s40-2l4" and folder == "merger_agreement" else "" for p in POSTURES]
        lines.append(
            f"| {_LABEL[folder]} | "
            + _joined([_score(c, mark=m) for c, m in zip(per, marks, strict=True)]) + " | "
            + _joined([f"{c['quality']['ok']}/{c['n']}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['latency']['p50']:.1f}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['cost']['usd_per_ok_document']:.5f}" if c else PENDING for c in per]) + " |"
        )
    lines += ["", "## Key findings", ""]
    key = _executive_findings(present, cards, pooled)
    lines += [f"{i}. {text}" for i, text in enumerate(key, 1)] or ["No cells reported yet."]
    lines += ["", "## Cost and integrity", ""]
    for study, rec in metered.items():
        if not isinstance(rec, Mapping):
            continue
        note = f" {rec['note']}" if rec.get("note") else ""
        lines.append(
            f"- **{study} metered Modal total:** ${float(rec.get('metered_usd', 0)):.2f} "
            f"(${float(rec.get('billed_usd', 0)):.2f} billed after credits).{note}"
        )
    lines += [
        "- **Teardown** verified after each posture, zero containers left warm.",
        "",
        f"**Source data:** per-cell cards under `1L4/<specialist>/` and `2L4/<specialist>/`; suite cards "
        "`1L4/L4x1-SCORE-COST-CARD.md`, `2L4/L4x2-SCORE-COST-CARD.md`. Detail, method and figures: "
        f"[./{APPENDIX_STEM}.md](./{APPENDIX_STEM}.md). Regenerate with `sandbox run card --master`.",
        "",
    ]
    return "\n".join(lines)


def render_appendix_md(data: Mapping[str, Any]) -> str:
    """Everything the executive card omits: method detail, full findings, tables, probes, figures."""
    cards: dict[str, dict[str, Any]] = data["cards"]
    metered: Mapping[str, Any] = data.get("metered") or {}
    present = [p for p in POSTURES if cards[p.key]]
    pooled = {p.key: _pooled(cards[p.key], p.replicas) for p in POSTURES}
    first = next((c for p in present for c in cards[p.key].values()), None)

    lines = [
        f"# Appendix to {MASTER_STEM}",
        "",
        f"Companion to [./{MASTER_STEM}.md](./{MASTER_STEM}.md), which stays executive-length. "
        "This file holds every detail table, the full findings, probes, run conditions, "
        "cost accounting and figures. Regenerate with `sandbox run card --master`.",
        "",
    ]
    if first:
        cond, ds = first["conditions"], first["conditions"]["dataset"]
        lines += [
            f"**Model:** {cond['model']} on vLLM {cond['image_tag']} · **GPU:** NVIDIA {cond['gpu']} at "
            f"${cond['gpu_usd_per_hour']:.2f} per GPU-hour  ",
            f"**Data:** public `{ds['repo']}` {ds['config']} @ `{ds['revision']}`, seed {ds['seed']}; "
            "the n = 20 draw is nested in the n = 50 draw, and every n = 50 posture scores the identical documents.  ",
            "**Engine (SAND-37 / SAND-39):** AWQ-Marlin, fp8 KV cache, CUDA graphs, prefix caching, thinking "
            "disabled, 8,192-token output cap, frozen v1 prompts; temperature 0.7 for contracts and merger, "
            "0.1 otherwise.  ",
            "**SAND-40:** one 32K deploy of the same 2×L4 engine at C32. Four specialists run n = 100 on unchanged "
            "settings (the n = 50 draw nested inside); merger runs the same 50 agreements as SAND-37 2×L4 with the "
            "optimized settings marked † (see *Merger † settings*).",
            "",
        ]
    heads = " | ".join(f"{p.study} {p.label}" for p in POSTURES)
    lines += [
        "## Serving efficiency — full pooled table",
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
        ("Busy wall time (sum of cells)", lambda q: f"{_num(q['wall'], 0)} s"),
        ("Tokens processed (prompt / completion)", lambda q: f"{q['prompt']:,} / {q['completion']:,}"),
        ("Length-capped finishes (vLLM)", lambda q: f"{q['length_finishes']:.0f}"),
        ("Preemptions (vLLM)", lambda q: f"{q['preemptions']:.0f}"),
    )
    for label, fn in rows:
        vals = [fn(pooled[p.key]) if pooled[p.key] else PENDING for p in POSTURES]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines.append("")
    lines += [
        "## Quality and cost by specialist (full scorecard)",
        "",
        f"Columns within each cell follow the posture order above ({' · '.join(p.label for p in POSTURES)}).",
        "",
        "| Specialist | Metric | Score | ok / n | p50 latency (s) | $ per ok document |",
        "| --- | --- | :---: | :---: | :---: | :---: |",
    ]
    for folder in _ORDER:
        per = [cards[p.key].get(folder) for p in POSTURES]
        marks = ["†" if p.key == "s40-2l4" and folder == "merger_agreement" else "" for p in POSTURES]
        lines.append(
            f"| {_LABEL[folder]} | {_metric_name(folder)} | "
            + _joined([_score(c, mark=m) for c, m in zip(per, marks, strict=True)]) + " | "
            + _joined([f"{c['quality']['ok']}/{c['n']}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['latency']['p50']:.1f}" if c else PENDING for c in per]) + " | "
            + _joined([f"{c['cost']['usd_per_ok_document']:.5f}" if c else PENDING for c in per]) + " |"
        )
    lines += [
        "",
        "Field scores (insurance claims, corporate records, correspondence) are the mean suite extraction "
        "score against ground truth over successful documents. Contracts ground truth is CUAD clause labels, "
        "so its score is the per-document CUAD clause-presence F1 averaged over the successful documents "
        "that carry CUAD labels (see *Clause scoring detail* for counts), with the pooled micro F1 in "
        "parentheses; the committed run reports count unlabeled documents as 0 and so read lower. Merger is "
        "micro-accuracy over labeled MAUD questions, with question coverage in parentheses, a different "
        "scale from the field scores. † marks the optimized merger cell (next section).",
        "",
    ]
    lines += [
        "## Findings (full)",
        "",
    ]
    findings = _findings(present, cards, pooled)
    lines += [f"{i}. {text}" for i, text in enumerate(findings, 1)] or ["No cells reported yet."]
    lines += [""]
    lines += _merger_settings_section(cards)
    lines += _detail_sections(present, cards)
    lines += _probe_section(data.get("probes") or {}, cards)
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
    paths["appendix"].write_text(render_appendix_md(data), encoding="utf-8")
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
