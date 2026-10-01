"""SAND-037 score & cost cards for the aligned specialist grid.

Every grid run exports one card (markdown + JSON) and every fleet shape gets one
finalized suite card, all under ``reports/SAND-37/``::

    reports/SAND-37/1L4/<specialist>/<run_id>.card.md     # one per 1×L4 run
    reports/SAND-37/1L4/<specialist>/<run_id>.card.json
    reports/SAND-37/1L4/L4x1-SCORE-COST-CARD.md           # finalized 1×L4 suite card
    reports/SAND-37/1L4/L4x1-SCORE-COST-CARD.json
    reports/SAND-37/2L4/...                                # same for 2×L4 (L4x2-…)
    reports/SAND-37/probes/<specialist>/<run_id>.card.md  # SAND-40 validation probes

SAND-40 probe cards stay in ``probes/``. They are not cells of the 1×L4 or
2×L4 suite, and ``collect_master`` never reads that directory, so a probe
cannot fill the master scorecard.

The card follows the S2a/S2b score-card template: a conditions table, then one
Metric | Value table grouped into Run, Time, Cost, Tokens, Throughput, Latency,
Engine (vLLM /metrics), Quality and clause scoring, then the error ledger and
per-document rows. Values are measured from the run store (items, lock, serving
record, ``vllm_metrics_{before,after}.json``); nothing is inferred. A field the
run did not capture renders as "not captured".

The JSON twin is the post hoc source of truth: the suite card is rebuilt from the
committed ``*.card.json`` files, so it never needs the gitignored run stores.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.paths import repo_root

_log = logging.getLogger("mailroom_sandbox.job.grid_cards")

SCHEMA = "sandbox.grid-card/v1"
ROOT_REL = Path("reports") / "SAND-37"
SHAPE_DIRS: dict[int, str] = {1: "1L4", 2: "2L4"}
SUITE_STEMS: dict[int, str] = {1: "L4x1-SCORE-COST-CARD", 2: "L4x2-SCORE-COST-CARD"}
RUNBOOK_FOR_REPLICAS: dict[int, str] = {1: "grid-1l4", 2: "grid-2l4"}

# Specialist folder and display label, in grid order.
SPECIALISTS: tuple[tuple[str, str, str], ...] = (
    ("correspondence_specialist", "correspondence", "Correspondence"),
    ("insurance_claims_specialist", "insurance_claims", "Insurance Claims"),
    ("corporate_records_specialist", "corporate_records", "Corporate Records"),
    ("contracts_specialist", "contracts", "Contracts"),
    ("merger_agreement_specialist", "merger_agreement", "Merger Agreements"),
)
_FOLDER = {task: folder for task, folder, _ in SPECIALISTS}
_LABEL = {task: label for task, _, label in SPECIALISTS}

NOT_CAPTURED = "not captured"


# ── helpers ──────────────────────────────────────────────────────────────────


def _d(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _error_kind(error: Any) -> str:
    text = str(error or "").strip()
    if not text:
        return "unknown"
    return text.split(":", 1)[0].strip() or "unknown"


def _probe_run(run_id: str) -> bool:
    """True for a SAND-40 validation probe. Those cards are not scorecard cells."""
    from mailroom_sandbox.job.specialist_posture import SAND40_PROBE_CELLS

    return run_id in SAND40_PROBE_CELLS


def card_dir(task: str, replicas: int, *, repo: Path | None = None, run_id: str | None = None) -> Path:
    folder = _FOLDER.get(task, task)
    root = (repo or repo_root()) / ROOT_REL
    if run_id and _probe_run(run_id):
        return root / "probes" / folder
    shape = SHAPE_DIRS.get(int(replicas), f"{int(replicas)}L4")
    return root / shape / folder


def card_paths(run_id: str, task: str, replicas: int, *, repo: Path | None = None) -> dict[str, Path]:
    base = card_dir(task, replicas, repo=repo, run_id=run_id)
    return {"dir": base, "md": base / f"{run_id}.card.md", "json": base / f"{run_id}.card.json"}


def suite_paths(replicas: int, *, repo: Path | None = None) -> dict[str, Path]:
    base = (repo or repo_root()) / ROOT_REL / SHAPE_DIRS[int(replicas)]
    stem = SUITE_STEMS[int(replicas)]
    return {"dir": base, "md": base / f"{stem}.md", "json": base / f"{stem}.json"}


# ── engine telemetry (vLLM /metrics before/after) ───────────────────────────


def _engine_block(store: RunStore, replicas: int) -> dict[str, Any]:
    before = _read_json(store.dir / "vllm_metrics_before.json")
    after = _read_json(store.dir / "vllm_metrics_after.json")
    if not after:
        return {"captured": False, "expected_replicas": replicas}
    b_reps = _d(before.get("replicas"))
    rows = []
    for key, rep in sorted(_d(after.get("replicas")).items()):
        rep = _d(rep)
        prev = _d(b_reps.get(key))

        def delta(name: str) -> float | None:
            now = _num(rep.get(name))
            if now is None:
                return None
            return now - (_num(prev.get(name)) or 0.0)

        rows.append(
            {
                "replica": key,
                "requests": delta("requests"),
                "preemptions": delta("preemptions"),
                "length_finishes": delta("length_finishes"),
                "ttft_mean_seconds": _num(rep.get("ttft_mean_seconds")),
                "prefix_cache_hit_rate": _num(rep.get("prefix_cache_hit_rate")),
                "kv_cache_usage_perc": _num(rep.get("kv_cache_usage_perc")),
            }
        )
    return {
        "captured": True,
        "expected_replicas": replicas,
        "coverage": after.get("coverage"),
        "replicas": rows,
        "scrape_errors": list(after.get("errors") or []),
    }


# ── per-run card ─────────────────────────────────────────────────────────────


def collect_card(
    store: RunStore,
    *,
    wall_seconds: float | None = None,
    scores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Every metric the card shows, measured from one run store."""
    from mailroom_sandbox.job import metrics
    from mailroom_sandbox.job.specialist_posture import posture_for_run

    lock = store.read_lock() or {}
    engine = _d(lock.get("engine"))
    vllm = _d(engine.get("vllm"))
    modal = _d(engine.get("modal"))
    job = _d(lock.get("job"))
    dataset = _d(lock.get("dataset"))
    prompt = _d(lock.get("prompt"))
    task = str(lock.get("task") or "")
    run_id = str(lock.get("run_id") or store.run_id)
    replicas = max(1, int(modal.get("max_containers") or 1))
    concurrency = max(1, int(job.get("concurrency") or 1))
    gpu = str(modal.get("gpu") or "L4")
    rate = metrics.gpu_usd_per_hour(gpu)
    posture = posture_for_run(run_id) or {}

    items = store.load_items()
    rec = metrics.serving_record_from_store(store, wall_seconds=wall_seconds, scores=scores)
    n = len(items)
    ok_rows = [i for i in items if i.get("ok") is not False]
    err_rows = [i for i in items if i.get("ok") is False]

    wall = _num(rec.get("wall_seconds"))
    busy_usd = wall * replicas * rate / 3600.0 if wall else None
    ptok = sum(int(i.get("prompt_tokens") or 0) for i in ok_rows)
    ctok = sum(int(i.get("completion_tokens") or 0) for i in ok_rows)
    tot = ptok + ctok
    compl = [int(i["completion_tokens"]) for i in ok_rows if i.get("completion_tokens") is not None]
    lat_ok = [float(i["latency_ms"]) / 1000.0 for i in ok_rows if i.get("latency_ms") is not None]
    lat_all = [float(i["latency_ms"]) / 1000.0 for i in items if i.get("latency_ms") is not None]
    parallelism = (sum(lat_all) / wall) if wall and lat_all else None

    item_scores = [_d(i.get("score")) for i in ok_rows]
    overall = [float(s["overall_extraction_score"]) for s in item_scores
               if isinstance(s.get("overall_extraction_score"), (int, float))]
    suite_overall = [float(s["suite_overall_extraction_score"]) for s in item_scores
                     if isinstance(s.get("suite_overall_extraction_score"), (int, float))]
    schema = [bool(s["schema_valid"]) for s in item_scores if "schema_valid" in s]
    method = next((s.get("scoring_method") for s in item_scores if s.get("scoring_method")), None)

    def total(key: str) -> int:
        return sum(int(s.get(key) or 0) for s in item_scores)

    clause: dict[str, Any] = {}
    if method and str(method).endswith("+cuad"):
        tp, fp, fn = total("cuad_tp"), total("cuad_fp"), total("cuad_fn")
        prec = tp / (tp + fp) if tp + fp else None
        rcl = tp / (tp + fn) if tp + fn else None
        clause = {
            "kind": "cuad",
            "docs_labeled": sum(1 for s in item_scores if s.get("cuad_presence_f1") is not None),
            "precision": prec,
            "recall": rcl,
            "f1": (2 * prec * rcl / (prec + rcl)) if prec and rcl else None,
            "value_correct": total("cuad_value_correct"),
            "value_checked": total("cuad_value_checked"),
        }
    elif method and str(method).endswith("+maud"):
        q, a, c = total("maud_questions"), total("maud_answered"), total("maud_correct")
        clause = {
            "kind": "maud",
            "questions": q,
            "answered": a,
            "correct": c,
            "accuracy": c / q if q else None,
            "coverage": a / q if q else None,
            "precision_answered": c / a if a else None,
            "clean_correct": total("maud_clean_correct"),
            "clean_questions": total("maud_clean_questions"),
        }

    temperature = posture.get("temperature")
    temperature_source = "posture knob" if temperature is not None else "vendored call site"
    if temperature is None:
        temperature = 0.1

    agents = _d(prompt.get("agents"))
    prompt_file = next((str(_d(v).get("file")) for v in agents.values() if _d(v).get("file")), None)

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "task": task,
        "specialist": _LABEL.get(task, task),
        "n": int(dataset.get("limit") or n),
        "conditions": {
            "model": engine.get("model"),
            "image_tag": modal.get("image_tag"),
            "modal_app": modal.get("app"),
            "gpu": gpu,
            "gpu_usd_per_hour": rate,
            "replicas": replicas,
            "concurrency": concurrency,
            "prompt": prompt_file,
            "temperature": temperature,
            "temperature_source": temperature_source,
            "max_tokens": posture.get("max_tokens"),
            "max_input_chars": posture.get("max_input_chars"),
            "max_retries": job.get("max_retries"),
            "dataset": {
                "repo": dataset.get("repo"),
                "config": dataset.get("config"),
                "split": dataset.get("split"),
                "revision": str(dataset.get("revision") or "")[:8] or None,
                "seed": dataset.get("sample_seed"),
                "fingerprint": rec.get("dataset_fingerprint"),
            },
            "engine": {
                "quantization": vllm.get("quantization"),
                "kv_cache_dtype": vllm.get("kv_cache_dtype") or "auto",
                "cuda_graphs": not bool(vllm.get("enforce_eager")),
                "cudagraph_capture_sizes": vllm.get("cudagraph_capture_sizes"),
                "max_model_len": vllm.get("max_model_len"),
                "max_num_seqs": vllm.get("max_num_seqs"),
                "max_inputs": vllm.get("max_inputs"),
                "prefix_caching": vllm.get("enable_prefix_caching"),
                "thinking": vllm.get("enable_thinking"),
            },
            "spec_hash": store.spec_hash(),
            **_optimized_conditions(posture, vllm),
        },
        "time": {
            "wall_seconds": wall,
            "gpu_seconds": _num(rec.get("gpu_seconds")),
            "cold_boot_seconds": _num(rec.get("cold_boot_seconds")),
        },
        "cost": {
            "busy_gpu_usd": busy_usd,
            "billed_gpu_usd": _num(rec.get("estimated_gpu_cost_usd")),
            "idle_usd": _num(rec.get("idle_estimated_usd")),
            "idle_seconds": _num(rec.get("idle_container_seconds")),
            "usd_per_document": busy_usd / n if busy_usd and n else None,
            "usd_per_ok_document": busy_usd / len(ok_rows) if busy_usd and ok_rows else None,
            "usd_per_million_tokens": busy_usd / tot * 1e6 if busy_usd and tot else None,
        },
        "tokens": {
            "prompt": ptok,
            "completion": ctok,
            "total": tot,
            "completion_share": ctok / tot if tot else None,
            "per_document": tot / len(ok_rows) if ok_rows else None,
            "completion_p95": _p95([float(c) for c in compl]),
            "completion_max": max(compl) if compl else None,
        },
        "throughput": {
            "tokens_per_second": tot / wall if wall and tot else None,
            "tokens_per_second_per_gpu": tot / wall / replicas if wall and tot else None,
            "documents_per_minute": n / wall * 60.0 if wall and n else None,
        },
        "latency": {
            "mean": statistics.mean(lat_ok) if lat_ok else None,
            "p50": statistics.median(lat_ok) if lat_ok else None,
            "p95": _p95(lat_ok),
            "max": max(lat_ok) if lat_ok else None,
        },
        "concurrency": {
            "parallelism": parallelism,
            "occupancy": parallelism / concurrency if parallelism else None,
            "slot_utilization": _num(rec.get("slot_utilization")),
        },
        "engine_telemetry": _engine_block(store, replicas),
        "quality": {
            "documents": n,
            "ok": len(ok_rows),
            "errors": len(err_rows),
            "error_kinds": dict(Counter(_error_kind(i.get("error")) for i in err_rows)),
            "overall_mean": statistics.mean(overall) if overall else None,
            "overall_sd": statistics.pstdev(overall) if len(overall) > 1 else None,
            "overall_min": min(overall) if overall else None,
            "overall_max": max(overall) if overall else None,
            "suite_overall_mean": statistics.mean(suite_overall) if suite_overall else None,
            "schema_valid_rate": sum(schema) / len(schema) if schema else None,
            "parse_errors": sum(1 for s in item_scores if s.get("parse_error")),
            "scoring_method": method,
            "clause": clause,
        },
        "documents": [
            {
                "item_id": i.get("item_id"),
                "ok": i.get("ok") is not False,
                "score": _d(i.get("score")).get("overall_extraction_score"),
                "latency_seconds": float(i["latency_ms"]) / 1000.0 if i.get("latency_ms") is not None else None,
                "prompt_tokens": i.get("prompt_tokens"),
                "completion_tokens": i.get("completion_tokens"),
                "error": str(i.get("error"))[:160] if i.get("error") else None,
            }
            for i in items
        ],
    }


# ── formatting ───────────────────────────────────────────────────────────────


def _f(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return NOT_CAPTURED
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _usd(value: Any, digits: int = 6) -> str:
    return NOT_CAPTURED if value is None else f"${float(value):,.{digits}f}"


def _pct(value: Any, digits: int = 1) -> str:
    return NOT_CAPTURED if value is None else f"{float(value) * 100:.{digits}f}%"


def _per_replica(rows: list[dict[str, Any]], key: str, fmt) -> str:
    if not rows:
        return NOT_CAPTURED
    return " / ".join(fmt(r.get(key)) for r in rows)


def _engine_text(e: Mapping[str, Any]) -> str:
    graphs = "CUDA graphs " + str(e.get("cudagraph_capture_sizes") or "") if e.get("cuda_graphs") else "eager"
    thinking = "thinking off" if e.get("thinking") is False else "thinking on"
    return (
        f"{e.get('quantization') or 'none'} · {e.get('kv_cache_dtype')} KV · {graphs} · "
        f"prefix caching {'on' if e.get('prefix_caching') else 'off'} · {thinking}"
    )


def _card_rows(c: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(metric, value) rows in template order; section headers carry an empty value."""
    cond, t, cost, tok = c["conditions"], c["time"], c["cost"], c["tokens"]
    thr, lat, conc, q = c["throughput"], c["latency"], c["concurrency"], c["quality"]
    eng = c["engine_telemetry"]
    reps = eng.get("replicas") or []
    rows: list[tuple[str, str]] = [
        ("**Run**", ""),
        ("Run ID", f"`{c['run_id']}`"),
        ("GPUs / replicas", str(cond["replicas"])),
        ("Concurrency", f"{cond['concurrency']} ({cond['concurrency'] // max(cond['replicas'], 1)} per replica)"),
        ("Documents", str(c["n"])),
        ("Spec hash", f"{str(cond.get('spec_hash') or '')[:8]}…" if cond.get("spec_hash") else NOT_CAPTURED),
        ("**Time**", ""),
        ("Wall (busy)", _f(t["wall_seconds"], 2, " s")),
        ("GPU seconds", _f(t["gpu_seconds"], 2, " s")),
        ("Cold boot", _f(t["cold_boot_seconds"], 2, " s")),
        ("**Cost**", ""),
        ("Busy-window GPU $", _usd(cost["busy_gpu_usd"])),
        ("Billed GPU $ (incl. boot)", _usd(cost["billed_gpu_usd"])),
        ("Idle $", f"{_usd(cost['idle_usd'])} ({_f(cost['idle_seconds'], 2, ' s')})" if cost["idle_usd"] is not None else NOT_CAPTURED),
        ("Cost per document", _usd(cost["usd_per_document"])),
        ("Cost per ok document", _usd(cost["usd_per_ok_document"])),
        ("Cost per 1M tokens", _usd(cost["usd_per_million_tokens"], 4)),
        ("**Tokens**", ""),
        ("Prompt tokens", _f(tok["prompt"])),
        ("Completion tokens", f"{_f(tok['completion'])} ({_pct(tok['completion_share'])})"),
        ("Total tokens", _f(tok["total"])),
        ("Tokens per document", _f(tok["per_document"], 0)),
        ("Completion p95 / max (ok docs)", f"{_f(tok['completion_p95'], 0)} / {_f(tok['completion_max'])}"),
        ("**Throughput**", ""),
        ("Tokens / second", _f(thr["tokens_per_second"], 1)),
        ("Tokens / second per L4", _f(thr["tokens_per_second_per_gpu"], 1)),
        ("Documents / minute", _f(thr["documents_per_minute"], 2)),
        ("**Latency (per document, ok rows)**", ""),
        ("Mean", _f(lat["mean"], 2, " s")),
        ("p50", _f(lat["p50"], 2, " s")),
        ("p95", _f(lat["p95"], 2, " s")),
        ("Max", _f(lat["max"], 2, " s")),
        ("**Engine (vLLM /metrics)**", ""),
        ("Parallelism (Σ latency ÷ wall)", f"{_f(conc['parallelism'], 2)}× of {cond['concurrency']}" if conc["parallelism"] else NOT_CAPTURED),
        ("Slot occupancy", _pct(conc["occupancy"])),
        ("Coverage", str(eng.get("coverage")) if eng.get("captured") else NOT_CAPTURED),
        ("Requests per replica (this run)", _per_replica(reps, "requests", lambda v: _f(v, 0))),
        ("Mean TTFT per replica", _per_replica(reps, "ttft_mean_seconds", lambda v: _f(v, 3, " s"))),
        ("Prefix-cache hit per replica", _per_replica(reps, "prefix_cache_hit_rate", _pct)),
        ("Preemptions per replica (this run)", _per_replica(reps, "preemptions", lambda v: _f(v, 0))),
        ("Length-capped finishes per replica (this run)", _per_replica(reps, "length_finishes", lambda v: _f(v, 0))),
        ("**Quality**", ""),
        ("Overall extraction score", f"{_f(q['overall_mean'], 4)} (sd {_f(q['overall_sd'], 3)})" if q["overall_mean"] is not None else NOT_CAPTURED),
        ("Score min / max", f"{_f(q['overall_min'], 4)} / {_f(q['overall_max'], 4)}"),
        ("Scoring method", f"`{q['scoring_method']}`" if q["scoring_method"] else NOT_CAPTURED),
        ("Schema-valid rate", _f(q["schema_valid_rate"], 2)),
        ("Parse errors", str(q["parse_errors"])),
        ("Errors", f"{q['errors']} / {q['documents']}"),
    ]
    clause = q.get("clause") or {}
    if clause.get("kind") == "cuad":
        rows += [
            ("**Clause scoring (CUAD)**", ""),
            ("Docs with CUAD labels", str(clause["docs_labeled"])),
            ("Micro precision / recall / F1", f"{_f(clause['precision'], 3)} / {_f(clause['recall'], 3)} / {_f(clause['f1'], 3)}"),
            ("Metadata value checks", f"{clause['value_correct']} / {clause['value_checked']}"),
            ("Suite field score (mean)", _f(q["suite_overall_mean"], 4)),
        ]
    elif clause.get("kind") == "maud":
        rows += [
            ("**Clause scoring (MAUD)**", ""),
            ("Questions answered / labeled", f"{clause['answered']} / {clause['questions']} ({_pct(clause['coverage'])})"),
            ("Micro accuracy", _pct(clause["accuracy"])),
            ("Precision on answered", _pct(clause["precision_answered"])),
            ("Clean subset", f"{clause['clean_correct']} / {clause['clean_questions']}"),
            ("Suite field score (mean)", _f(q["suite_overall_mean"], 4)),
        ]
    return rows


def render_card_md(c: Mapping[str, Any]) -> str:
    cond = c["conditions"]
    ds = cond["dataset"]
    eng = cond["engine"]
    shape = f"{cond['replicas']}× L4"
    lines = [
        f"# {c['specialist']} — {shape} · C{cond['concurrency']} · n={c['n']}",
        "",
        f"**Run:** `{c['run_id']}` · **Model:** {cond['model']} · vLLM {cond['image_tag']} · "
        f"Modal `{cond['modal_app']}` · {cond['gpu']} @ ${cond['gpu_usd_per_hour']:.2f}/GPU-hr",
        "",
        "## Conditions",
        "",
        "| Condition | Value |",
        "| --- | --- |",
        f"| Task | {c['task']} |",
        f"| Prompt | {cond['prompt'] or NOT_CAPTURED} |",
        f"| Temperature | {cond['temperature']} ({cond['temperature_source']}) |",
        f"| Output cap (max_tokens) | {_f(cond['max_tokens'])} |",
        f"| Input cap (max_input_chars) | {_f(cond['max_input_chars'])} |",
        *_sampling_rows(cond),
        f"| Job retries | {cond['max_retries']} |",
        f"| Dataset | {ds['repo']} {ds['config']} @ {ds['revision']}, split={ds['split']}, seed {ds['seed']} |",
        f"| Draw | {c['n']} docs (fingerprint {ds['fingerprint'] or NOT_CAPTURED}) |",
        f"| Engine | {_engine_text(eng)} |",
        f"| Admission | max_model_len {eng['max_model_len']} · max_num_seqs {eng['max_num_seqs']} per replica · max_inputs {eng['max_inputs']} |",
        "",
        "## Score & cost card",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines += [f"| {k} | {v} |" for k, v in _card_rows(c)]
    q = c["quality"]
    if q["error_kinds"]:
        lines += ["", "## Errors", "", "| Error | Count |", "| --- | ---: |"]
        lines += [f"| {k} | {v} |" for k, v in sorted(q["error_kinds"].items())]
    lines += [
        "",
        "## Per-document results",
        "",
        "| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, d in enumerate(c["documents"], 1):
        err = (d["error"] or "").replace("|", "/")
        lines.append(
            f"| {idx} | `{d['item_id']}` | {'yes' if d['ok'] else 'no'} | "
            f"{_f(d['score'], 4) if d['score'] is not None else '—'} | "
            f"{_f(d['latency_seconds'], 1) if d['latency_seconds'] is not None else '—'} | "
            f"{d['prompt_tokens'] if d['prompt_tokens'] is not None else '—'} | "
            f"{d['completion_tokens'] if d['completion_tokens'] is not None else '—'} | {err or '—'} |"
        )
    lines += [
        "",
        f"_Generated {c['generated_at']} by `sandbox run card`. Machine-readable twin: `{c['run_id']}.card.json`._",
        "",
    ]
    return "\n".join(lines)


def write_card(
    store: RunStore,
    *,
    repo: Path | None = None,
    wall_seconds: float | None = None,
    scores: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Write ``<run_id>.card.{md,json}`` under reports/SAND-37/<shape>/<specialist>/.

    SAND-40 probe runs write under ``reports/SAND-37/probes/<specialist>/``
    instead, so they stay out of the 2×L4 suite and the master scorecard.

    A re-render without ``wall_seconds`` (``sandbox run card`` after the
    /metrics after-scrape) reuses the runner's busy wall from the existing card,
    so the timing never falls back to item timestamps.
    """
    if wall_seconds is None:
        lock = store.read_lock() or {}
        replicas = max(1, int(_d(_d(lock.get("engine")).get("modal")).get("max_containers") or 1))
        prior = _read_json(
            card_paths(str(lock.get("run_id") or store.run_id), str(lock.get("task") or ""), replicas, repo=repo)["json"]
        )
        wall_seconds = _num(_d(prior.get("time")).get("wall_seconds"))
    card = collect_card(store, wall_seconds=wall_seconds, scores=scores)
    paths = card_paths(card["run_id"], card["task"], card["conditions"]["replicas"], repo=repo)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["md"].write_text(render_card_md(card), encoding="utf-8")
    _log.info("SAND-37 card written: %s", paths["md"])
    return paths


def _optimized_conditions(posture: Mapping[str, Any], vllm: Mapping[str, Any]) -> dict[str, Any]:
    """SAND-040 knobs recorded on the card when the posture sets them."""
    out: dict[str, Any] = {}
    for key in ("top_p", "top_k", "presence_penalty", "length_retries", "chunk_chars", "overlap_chars"):
        if posture.get(key) is not None:
            out[key] = posture[key]
    if posture.get("optimized"):
        out["optimized"] = True
    hf = vllm.get("hf_overrides")
    if hf:
        out["hf_overrides"] = hf
    return out


def _sampling_rows(cond: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    if cond.get("optimized"):
        rows.append("| Optimized long-document settings | yes |")
    for key, label in (
        ("top_p", "top_p"),
        ("top_k", "top_k"),
        ("presence_penalty", "presence_penalty"),
        ("length_retries", "Length re-samples"),
        ("chunk_chars", "Chunk window (chars)"),
        ("overlap_chars", "Chunk overlap (chars)"),
    ):
        if cond.get(key) is not None:
            rows.append(f"| {label} | {cond[key]} |")
    if cond.get("hf_overrides"):
        rows.append(f"| hf_overrides | `{json.dumps(cond['hf_overrides'], sort_keys=True)}` |")
    return rows


def maybe_write_card(store: RunStore, **kwargs: Any) -> dict[str, Path]:
    """Runner hook: grid and SAND-040 cells, never fails the scored job."""
    from mailroom_sandbox.job.specialist_posture import GRID_CELLS, SAND40_CELLS, SAND40_PROBE_CELLS

    try:
        lock = store.read_lock() or {}
        if str(lock.get("run_id") or store.run_id) not in (GRID_CELLS | SAND40_CELLS | SAND40_PROBE_CELLS):
            return {}
        if _d(lock.get("job")).get("mock") or not store.load_items():
            return {}
        return write_card(store, **kwargs)
    except Exception:
        _log.exception("SAND-37 card write failed for %s", store.run_id)
        return {}


# ── finalized suite card (one per fleet shape) ──────────────────────────────


_SUITE_ROWS: tuple[tuple[str, Any], ...] = (
    ("**Status**", None),
    ("Run ID", lambda c: f"`{c['run_id']}`"),
    ("Documents ok / total", lambda c: f"{c['quality']['ok']} / {c['quality']['documents']}"),
    ("Errors", lambda c: ", ".join(f"{k} {v}" for k, v in sorted(c["quality"]["error_kinds"].items())) or "0"),
    ("**Time**", None),
    ("Wall (busy)", lambda c: _f(c["time"]["wall_seconds"], 1, " s")),
    ("**Cost**", None),
    ("Busy-window GPU $", lambda c: _usd(c["cost"]["busy_gpu_usd"], 4)),
    ("Cost per document", lambda c: _usd(c["cost"]["usd_per_document"])),
    ("Cost per 1M tokens", lambda c: _usd(c["cost"]["usd_per_million_tokens"], 4)),
    ("**Tokens**", None),
    ("Total tokens", lambda c: _f(c["tokens"]["total"])),
    ("Completion share", lambda c: _pct(c["tokens"]["completion_share"])),
    ("Completion max (ok docs)", lambda c: _f(c["tokens"]["completion_max"])),
    ("**Throughput**", None),
    ("Tokens / second", lambda c: _f(c["throughput"]["tokens_per_second"], 1)),
    ("Tokens / second per L4", lambda c: _f(c["throughput"]["tokens_per_second_per_gpu"], 1)),
    ("Documents / minute", lambda c: _f(c["throughput"]["documents_per_minute"], 2)),
    ("**Latency**", None),
    ("p50 / p95", lambda c: f"{_f(c['latency']['p50'], 1)} / {_f(c['latency']['p95'], 1)} s"),
    ("Max", lambda c: _f(c["latency"]["max"], 1, " s")),
    ("**Engine**", None),
    ("Slot occupancy", lambda c: _pct(c["concurrency"]["occupancy"])),
    ("Mean TTFT per replica", lambda c: _per_replica(c["engine_telemetry"].get("replicas") or [], "ttft_mean_seconds", lambda v: _f(v, 2))),
    ("Prefix-cache hit per replica", lambda c: _per_replica(c["engine_telemetry"].get("replicas") or [], "prefix_cache_hit_rate", lambda v: _pct(v, 0))),
    ("Length-capped finishes", lambda c: _per_replica(c["engine_telemetry"].get("replicas") or [], "length_finishes", lambda v: _f(v, 0))),
    ("**Quality**", None),
    ("Overall extraction score", lambda c: _f(c["quality"]["overall_mean"], 4)),
    ("Clause score", lambda c: _clause_short(c["quality"].get("clause") or {})),
    ("Schema-valid rate", lambda c: _f(c["quality"]["schema_valid_rate"], 2)),
)


def _clause_short(clause: Mapping[str, Any]) -> str:
    if clause.get("kind") == "cuad":
        return f"CUAD F1 {_f(clause.get('f1'), 3)}"
    if clause.get("kind") == "maud":
        return f"MAUD acc {_pct(clause.get('accuracy'))}"
    return "—"


def _expected_cells(replicas: int) -> list[str]:
    from mailroom_sandbox.job.runbooks import get_runbook

    return [Path(rel).stem for rel in get_runbook(RUNBOOK_FOR_REPLICAS[replicas])["configs"]]


def _pooled(cards: list[Mapping[str, Any]], replicas: int) -> dict[str, Any]:
    docs = sum(c["quality"]["documents"] for c in cards)
    ok = sum(c["quality"]["ok"] for c in cards)
    errors = sum(c["quality"]["errors"] for c in cards)
    wall = sum(c["time"]["wall_seconds"] or 0.0 for c in cards)
    busy = sum(c["cost"]["busy_gpu_usd"] or 0.0 for c in cards)
    tokens = sum(c["tokens"]["total"] or 0 for c in cards)
    return {
        "cells": len(cards),
        "documents": docs,
        "ok": ok,
        "errors": errors,
        "error_rate": errors / docs if docs else None,
        "wall_seconds": wall or None,
        "busy_gpu_usd": busy or None,
        "tokens": tokens,
        "usd_per_document": busy / docs if busy and docs else None,
        "usd_per_million_tokens": busy / tokens * 1e6 if busy and tokens else None,
        "tokens_per_second": tokens / wall if wall and tokens else None,
        "tokens_per_second_per_gpu": tokens / wall / replicas if wall and tokens else None,
        "documents_per_minute": docs / wall * 60.0 if wall and docs else None,
    }


def collect_suite(replicas: int, *, repo: Path | None = None) -> dict[str, Any]:
    """Gather the committed per-run card JSON for one fleet shape."""
    root = (repo or repo_root()) / ROOT_REL / SHAPE_DIRS[int(replicas)]
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*/*.card.json")):
        data = _read_json(path)
        if data.get("schema") == SCHEMA and data.get("run_id"):
            found[str(data["run_id"])] = data
    expected = _expected_cells(int(replicas))
    cells = []
    for run_id in expected:
        n = int(run_id.split("-")[1])
        task = next(t for t, folder, _ in SPECIALISTS if f"-{_slug(folder)}-" in run_id)
        cells.append({"run_id": run_id, "n": n, "task": task, "card": found.get(run_id)})
    present = [c["card"] for c in cells if c["card"]]
    by_n = {n: _pooled([c["card"] for c in cells if c["card"] and c["n"] == n], replicas) for n in (20, 50)}
    return {
        "schema": SCHEMA,
        "kind": "suite",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "replicas": int(replicas),
        "runbook": RUNBOOK_FOR_REPLICAS[int(replicas)],
        "cells": [{"run_id": c["run_id"], "n": c["n"], "task": c["task"], "reported": bool(c["card"])} for c in cells],
        "pooled": {"all": _pooled(present, replicas), "n20": by_n[20], "n50": by_n[50]},
        "cards": {c["run_id"]: c["card"] for c in cells if c["card"]},
    }


def _slug(folder: str) -> str:
    return {
        "correspondence": "correspondence",
        "insurance_claims": "insurance-claims",
        "corporate_records": "corporate-records",
        "contracts": "contracts",
        "merger_agreement": "merger",
    }[folder]


def render_suite_md(suite: Mapping[str, Any]) -> str:
    replicas = suite["replicas"]
    cards: dict[str, Any] = suite["cards"]
    shape = f"{replicas}× L4"
    total = len(suite["cells"])
    reported = sum(1 for c in suite["cells"] if c["reported"])
    first = next(iter(cards.values()), None)
    lines = [
        f"# SAND-37 — {shape} · C{8 if replicas == 1 else 32} score & cost card",
        "",
        f"**Cells reported:** {reported} of {total} · **Runbook:** `{suite['runbook']}` · "
        "**Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr",
        "",
    ]
    if first:
        cond = first["conditions"]
        ds = cond["dataset"]
        lines += [
            "## Shared conditions",
            "",
            "| Condition | Value |",
            "| --- | --- |",
            f"| Engine | {_engine_text(cond['engine'])} |",
            f"| Admission | max_model_len {cond['engine']['max_model_len']} · max_num_seqs {cond['engine']['max_num_seqs']} per replica · max_inputs {cond['engine']['max_inputs']} |",
            f"| Fleet | {replicas} replica(s) · client concurrency {cond['concurrency']} |",
            f"| Dataset | {ds['repo']} {ds['config']} @ {ds['revision']}, split={ds['split']}, seed {ds['seed']}, one class bucket (n=20 nested in n=50) |",
            f"| Output cap | max_tokens {_f(cond['max_tokens'])} |",
            "| Temperature | 0.7 contracts and merger (JSON-schema grammar); 0.1 elsewhere (vendored call site) |",
            "",
        ]
    pooled = suite["pooled"]
    lines += [
        "## Pooled totals",
        "",
        "| Metric | n = 20 | n = 50 | All cells |",
        "| --- | ---: | ---: | ---: |",
    ]
    pooled_rows = (
        ("Cells reported", lambda p: str(p["cells"])),
        ("Documents ok / total", lambda p: f"{p['ok']} / {p['documents']}"),
        ("Error rate", lambda p: _pct(p["error_rate"])),
        ("Wall (Σ busy)", lambda p: _f(p["wall_seconds"], 1, " s")),
        ("Busy-window GPU $", lambda p: _usd(p["busy_gpu_usd"], 4)),
        ("Cost per document (pooled)", lambda p: _usd(p["usd_per_document"])),
        ("Cost per 1M tokens (pooled)", lambda p: _usd(p["usd_per_million_tokens"], 4)),
        ("Tokens", lambda p: _f(p["tokens"])),
        ("Tokens / second (pooled)", lambda p: _f(p["tokens_per_second"], 1)),
        ("Tokens / second per L4", lambda p: _f(p["tokens_per_second_per_gpu"], 1)),
        ("Documents / minute (pooled)", lambda p: _f(p["documents_per_minute"], 2)),
    )
    for label, fn in pooled_rows:
        lines.append(f"| {label} | {fn(pooled['n20'])} | {fn(pooled['n50'])} | {fn(pooled['all'])} |")
    lines.append("")
    for n in (20, 50):
        cells = [c for c in suite["cells"] if c["n"] == n]
        header = " | ".join(_LABEL[c["task"]] for c in cells)
        lines += [
            f"## Per specialist · n = {n}",
            "",
            f"| Metric | {header} |",
            "| --- |" + " ---: |" * len(cells),
        ]
        for label, fn in _SUITE_ROWS:
            if fn is None:
                lines.append(f"| {label} |" + " |" * len(cells))
                continue
            vals = []
            for c in cells:
                card = cards.get(c["run_id"])
                vals.append(fn(card) if card else "not run")
            lines.append(f"| {label} | " + " | ".join(vals) + " |")
        lines.append("")
    lines += [
        "## Per-run cards",
        "",
        "| Specialist | n | Run ID | Card |",
        "| --- | ---: | --- | --- |",
    ]
    for c in suite["cells"]:
        folder = _FOLDER[c["task"]]
        link = f"[{c['run_id']}.card.md]({folder}/{c['run_id']}.card.md)" if c["reported"] else "not run"
        lines.append(f"| {_LABEL[c['task']]} | {c['n']} | `{c['run_id']}` | {link} |")
    lines += [
        "",
        f"_Generated {suite['generated_at']} by `sandbox run card --runbook {suite['runbook']}` from the committed per-run `*.card.json`._",
        "",
    ]
    return "\n".join(lines)


def write_suite(replicas: int, *, repo: Path | None = None) -> dict[str, Path]:
    suite = collect_suite(replicas, repo=repo)
    paths = suite_paths(replicas, repo=repo)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(json.dumps(suite, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["md"].write_text(render_suite_md(suite), encoding="utf-8")
    return paths
