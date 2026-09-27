"""SAND-032: `sandbox watch` — a mailroom-themed live view of a Modal eval run.

One terminal pane that combines:
  * the run's in-tray (checkpoint cursor/total, delivered vs returned docs,
    postmark latency p50/p95, mean score) read from the local run store;
  * postage — spend so far (ledger) + the live run's GPU estimate vs the cap;
  * the dispatch log — `modal app logs <app>` streamed from the dedicated
    Modal app, colour-coded (errors, warnings, vLLM throughput, KV pool).

Stdlib only (ANSI escapes); render functions are pure and unit-tested.
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterable

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.tui import pretty_log as pl

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
GATE_USD = 4.50
SUBTITLE_PATH = "Qwen3-8B-AWQ · vLLM L4 eval"
ROUTE = "INBOX → SPECIALIST → REPORT"


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def progress_bar(done: int, total: int, *, width: int = 30) -> str:
    """mailroom-ml bar glyphs (█ filled / ░ empty), clamped to [0, total]."""
    frac = 0.0 if total <= 0 else min(1.0, max(0.0, done / total))
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


def classify_log_line(line: str) -> str:
    low = line.lower()
    if "traceback" in low or re.search(r"\berror\b", low) or "exception" in low:
        return "error"
    if re.search(r"\bwarn(ing)?\b", low):
        return "warn"
    if "throughput" in low:
        return "throughput"
    if "kv cache" in low:
        return "kv"
    if "ready on port" in low or "application startup complete" in low:
        return "ready"
    return "plain"


# log class -> mailroom-ml palette role
_LOG_ROLE = {"error": "warn", "warn": "gold", "throughput": "cyan", "kv": "mint",
             "ready": "teal", "plain": "dim"}


def run_snapshot(store: RunStore) -> dict[str, Any]:
    """Everything the in-tray panel needs, read from the local run store."""
    lock = (store.read_lock() if store.lock_path.is_file() else None) or {}
    cp = (store.read_checkpoint() if store.checkpoint_path.is_file() else None) or {}
    items = store.load_items()
    modal = ((lock.get("engine") or {}).get("modal") or {}) if isinstance(lock, dict) else {}
    ok = [i for i in items if i.get("ok", True) is not False]
    errs = [i for i in items if i.get("ok") is False]
    lat = sorted(float(i["latency_ms"]) / 1000.0 for i in ok if i.get("latency_ms") is not None)
    scores = [
        float((i.get("score") or {}).get("overall_extraction_score"))
        for i in ok
        if isinstance((i.get("score") or {}).get("overall_extraction_score"), (int, float))
    ]
    p95 = lat[max(0, int(0.95 * len(lat) + 0.999999) - 1)] if lat else None
    return {
        "run_id": lock.get("run_id") or store.dir.name,
        "task": lock.get("task") or "?",
        "state": cp.get("state") or ("waiting" if not items else "running"),
        "done": max(int(cp.get("cursor") or 0), len(items)),
        "total": int(cp.get("total") or 0),
        "ok": len(ok),
        "errors": len(errs),
        "replicas": max(1, int(modal.get("max_containers") or 1)),
        "gpu": str(modal.get("gpu") or "L4"),
        "p50_s": round(statistics.median(lat), 3) if lat else None,
        "p95_s": round(p95, 3) if p95 is not None else None,
        "mean_score": round(statistics.mean(scores), 4) if scores else None,
        "last_error": (errs[-1].get("error") or "") if errs else "",
    }


def _fmt(v: Any, suffix: str = "") -> str:
    return "—" if v is None else f"{v}{suffix}"


def _stage_for(run_id: str) -> str:
    if run_id.startswith("sand032-l"):
        return "LADDER"
    if run_id.startswith("sand032-s2"):
        return "SCALE-OUT"
    if run_id.startswith("sand032-s3"):
        return "SWEEP"
    if run_id.startswith("sand032-s4"):
        return "BF16"
    return "EVAL"


def _header(run_id: str, *, width: int, on: bool) -> list[str]:
    """mailroom-ml double-line frame + owl/amber THE MAILROOM, eval subtitle."""
    p = pl.palette(on)
    inner = width - 2
    mark = pl._wordmark_lines(inner=inner, on=on, compact=width < 90)
    tag = run_id if len(run_id) <= 28 else run_id[:27] + "…"
    brand = "DIGITAL MAILROOM"
    if on:
        sub = p["brand"](brand) + p["dim"]("  ·  ") + p["snow"](SUBTITLE_PATH) + p["dim"]("  ·  ") + p["gold"](tag)
        route = p["teal"](ROUTE)
    else:
        sub = f"{brand}  ·  {SUBTITLE_PATH}  ·  {tag}"
        route = ROUTE
    top = pl.DTL + pl.DH * inner + pl.DTR
    bot = pl.DBL + pl.DH * inner + pl.DBR
    rows = [p["frame"](top) if on else top]
    rows += [pl._centered_row(line, width=width, on=on) for line in mark]
    rows += [pl._panel_row(sub, on=on, width=width), pl._panel_row(route, on=on, width=width)]
    rows.append(p["frame"](bot) if on else bot)
    return rows


def render_frame(
    *,
    snapshot: dict[str, Any],
    app: str,
    log_lines: list[str],
    spend: dict[str, float],
    width: int = 100,
    on: bool = False,
    blink: bool = False,
) -> str:
    width = max(60, min(int(width), pl.MAX_W))
    p = pl.palette(on)
    s = snapshot
    out: list[str] = _header(s["run_id"], width=width, on=on)
    out.append(
        pl.render_status_bar(
            timestamp=time.strftime("%H:%M:%S") + f" · app {app}",
            stage=_stage_for(s["run_id"]),
            on=on,
            width=width,
            blink=blink,
        )
    )

    wide = width >= 100
    box_w = (width - 2) // 2 if wide else width
    mw = box_w - 4
    bar = progress_bar(s["done"], s["total"], width=max(10, mw - 14))
    tray = [
        pl._metric("run", s["run_id"], total_w=mw, on=on),
        pl._metric("specialist", s["task"], total_w=mw, on=on),
        pl._metric("fleet", f"×{s['replicas']} {s['gpu']} · {s['state']}", total_w=mw, on=on),
        (p["cyan"](bar) if on else bar) + f"  {s['done']}/{s['total']}",
        pl._metric("sorted", f"delivered {s['ok']} · returned {s['errors']}", total_w=mw, on=on),
        pl._metric("postmark", f"p50 {_fmt(s['p50_s'], 's')} · p95 {_fmt(s['p95_s'], 's')}", total_w=mw, on=on),
        pl._metric("score", _fmt(s["mean_score"]), total_w=mw, on=on),
    ]
    if s.get("last_error"):
        err = f"last return: {s['last_error']}"
        tray.append(p["warn"](err) if on else err)
    tray_box = pl._box(f"{pl.owl_emoticon(on=False)} IN-TRAY", tray, width=box_w, on=on)

    spent = float(spend.get("spent_usd") or 0.0)
    live = float(spend.get("live_usd") or 0.0)
    cap = float(spend.get("cap_usd") or 5.0)
    total = spent + live
    pbar = progress_bar(int(total * 100), int(cap * 100), width=max(10, mw - 14))
    postage = [
        pl._metric("ledger", f"${spent:.4f}", total_w=mw, on=on),
        pl._metric("live run", f"${live:.4f}", total_w=mw, on=on),
        pl._metric("total", f"${total:.4f} / ${cap:.2f}", total_w=mw, on=on),
        (p["gold"](pbar) if on else pbar) + f"  {100 * total / cap:.0f}%",
        pl._metric("gate", f"${GATE_USD:.2f} projected-total stop", total_w=mw, on=on),
    ]
    if total > GATE_USD:
        warn = f"⚠ OVER ${GATE_USD:.2f} GATE — stop and reconcile"
        postage.append(p["warn"](warn) if on else warn)
    postage_box = pl._box("POSTAGE ($)", postage, width=box_w, on=on)
    if wide:
        out.append(pl._side_by_side(tray_box, postage_box, gap=2))
    else:
        out += [tray_box, postage_box]

    tail = log_lines[-14:]
    log = [
        (p[_LOG_ROLE[classify_log_line(line)]](line) if on else line) for line in tail
    ] or [p["dim"]("(waiting on modal app logs …)") if on else "(waiting on modal app logs …)"]
    out.append(pl._box(f"DISPATCH LOG · modal app logs {app}", log, width=width, on=on))
    return "\n".join(out)


def _stream_logs(app: str, sink: deque, stop: threading.Event) -> None:
    """Follow `modal app logs <app>` into ``sink``; restart if the stream drops."""
    while not stop.is_set():
        try:
            proc = subprocess.Popen(
                ["modal", "app", "logs", app],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            sink.append("ERROR modal CLI not found on PATH — logs unavailable")
            return
        assert proc.stdout is not None
        for raw in proc.stdout:
            if stop.is_set():
                break
            line = raw.rstrip()
            if line:
                sink.append(line)
        proc.terminate()
        if not stop.is_set():
            sink.append("WARNING log stream ended — reconnecting in 5s")
            stop.wait(5)


def _read_spend(ledger: Path | None) -> float:
    if ledger is None or not ledger.is_file():
        return 0.0
    try:
        return float(json.loads(ledger.read_text()).get("spent_usd") or 0.0)
    except (ValueError, OSError):
        return 0.0


def watch(
    *,
    resolve: Callable[[], tuple[RunStore, str]],
    ledger: Path | None,
    cap_usd: float = 5.0,
    once: bool = False,
    logs: bool = True,
    interval: float = 2.0,
) -> int:
    from mailroom_sandbox.job.metrics import estimate_gpu_cost_usd

    sink: deque[str] = deque(maxlen=400)
    stop = threading.Event()
    store, app = resolve()
    if not once:
        sys.stdout.write(pl.ALT_ENTER + pl.HIDE_CURSOR)
    if logs and not once:
        threading.Thread(target=_stream_logs, args=(app, sink, stop), daemon=True).start()
    started = time.time()
    try:
        while True:
            store, _ = resolve()  # --follow: the current run can change between frames
            snap = run_snapshot(store)
            live = 0.0
            if snap["state"] == "running":
                live = float(
                    estimate_gpu_cost_usd(time.time() - started, gpu=snap["gpu"], replicas=snap["replicas"])
                    or 0.0
                )
            frame = render_frame(
                snapshot=snap,
                app=app,
                log_lines=list(sink),
                spend={"spent_usd": _read_spend(ledger), "live_usd": live, "cap_usd": cap_usd},
                width=shutil.get_terminal_size((100, 40)).columns,
                on=pl.use_color(sys.stdout),
                blink=int(time.time()) % 7 == 0,
            )
            if once:
                sys.stdout.write(frame + "\n")
                return 0
            sys.stdout.write(pl.CURSOR_HOME + pl.CLEAR_SCREEN + frame + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
        if not once:
            sys.stdout.write(pl.SHOW_CURSOR + pl.ALT_LEAVE)
            sys.stdout.flush()
