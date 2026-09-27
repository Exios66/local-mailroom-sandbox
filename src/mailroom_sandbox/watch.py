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


# ── lifecycle (driver stamps + Modal boot log markers) ─────────────────────
BOOT_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("container starting", re.compile(r"sandbox-vllm serve config|launching vllm subprocess|secrets check", re.I)),
    ("loading weights", re.compile(r"loading weights|load(ing)? model|safetensors|model loading took|downloading", re.I)),
    ("profiling KV cache", re.compile(r"kv cache|memory profiling|# gpu blocks", re.I)),
    ("capturing CUDA graphs", re.compile(r"captur(e|ing) cuda graph|cudagraph|torch\.compile|compil(ing|ation)", re.I)),
    ("engine ready", re.compile(r"application startup complete|vllm ready on port", re.I)),
)
TEARDOWN_PHASES = ("TEARDOWN", "STOPPED")


def read_times(path: Path) -> dict[str, float]:
    """Parse the driver's ``"key": epoch,`` stamp lines (scripts/sand032/run_one.sh)."""
    out: dict[str, float] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*"([a-z_]+)":\s*([0-9.]+)', line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def _boot_detail(boot_lines: list[str]) -> str:
    detail = "container starting"
    for line in boot_lines:
        for name, pat in BOOT_MARKERS:
            if pat.search(line):
                detail = name
    return detail


def lifecycle(times: dict[str, float], boot_lines: list[str], *, now: float) -> dict[str, Any]:
    """Current phase of a run from its driver stamps; COLD BOOT sub-phase from logs."""
    def since(key: str) -> int:
        return int(max(0.0, now - times[key]))

    if "stopped" in times:
        return {"phase": "STOPPED", "detail": "fleet stopped · billing ended", "elapsed_s": since("stopped")}
    if "run_end" in times:
        return {"phase": "TEARDOWN", "detail": "metrics · serving record · evidence rows · stop", "elapsed_s": since("run_end")}
    if "run_start" in times:
        return {"phase": "SORTING", "detail": "specialist extraction in flight", "elapsed_s": since("run_start")}
    if "ready" in times:
        return {"phase": "PREFLIGHT", "detail": "engine verified · /metrics baseline", "elapsed_s": since("ready")}
    if "deploy_done" in times:
        return {"phase": "COLD BOOT", "detail": _boot_detail(boot_lines), "elapsed_s": since("deploy_done")}
    if "deploy_start" in times:
        return {"phase": "DEPLOYING", "detail": "modal deploy · image + app", "elapsed_s": since("deploy_start")}
    return {"phase": "QUEUED", "detail": "waiting for the driver", "elapsed_s": 0}


# ── persistent dispatch log ─────────────────────────────────────────────────
class LogBuffer:
    """Thread-safe tail of streamed Modal logs, mirrored to disk so history
    survives TUI restarts and run switches (never cleared between runs)."""

    def __init__(self, path: Path | None, *, maxlen: int = 2000) -> None:
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._count = 0
        self._lock = threading.Lock()
        self._path = path
        if path is not None and path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-maxlen:]:
                self._lines.append(line)
                self._count += 1

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            self._count += 1
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")

    def mark(self) -> int:
        return self._count

    def since(self, mark: int) -> list[str]:
        with self._lock:
            n = max(0, min(self._count - mark, len(self._lines)))
            return list(self._lines)[-n:] if n else []

    def tail(self, n: int) -> list[str]:
        with self._lock:
            return list(self._lines)[-n:]

    def last(self) -> str | None:
        with self._lock:
            return self._lines[-1] if self._lines else None


# ── scorecard ───────────────────────────────────────────────────────────────
def scorecard_lines(store: RunStore, *, serving_dir: Path, width: int = 100, on: bool = False) -> list[str]:
    """Post-run scorecard: items (quality) + serving record (speed/cost) + /metrics."""
    p = pl.palette(on)
    snap = run_snapshot(store)
    mw = max(40, width - 4)
    items = store.load_items()
    schema = [
        (i.get("score") or {}).get("parse_error") is False
        for i in items
        if "parse_error" in (i.get("score") or {})
    ]
    rec: dict[str, Any] = {}
    path = serving_dir / f"{snap['run_id']}.serving.json"
    if path.is_file():
        try:
            rec = json.loads(path.read_text())
        except ValueError:
            rec = {}
    scores = rec.get("scores") or {}
    score = scores.get("overall_extraction_score", snap["mean_score"])
    valid = scores.get("schema_valid_rate", round(sum(schema) / len(schema), 4) if schema else None)
    n = int(rec.get("n") or snap["done"] or 0)
    tokens = (rec.get("prompt_tokens") or 0, rec.get("completion_tokens") or 0)

    def m(label: str, value: Any) -> str:
        return pl._metric(label, str(value), label_w=18, total_w=mw, on=on)

    lines = [
        m("sorted", f"delivered {snap['ok']} · returned {snap['errors']} · of {snap['total'] or n}"),
        m("overall score", _fmt(score)),
        m("schema valid", _fmt(valid)),
    ]
    if rec:
        per_doc = rec.get("gpu_cost_per_document")
        lines += [
            m("wall", _fmt(rec.get("wall_seconds"), " s")),
            m("cold boot", _fmt(rec.get("cold_boot_seconds"), " s")),
            m("postmark p50/p95", f"{_fmt(rec.get('latency_p50_seconds'), 's')} / {_fmt(rec.get('latency_p95_seconds'), 's')}"),
            m("throughput", _fmt(rec.get("tokens_per_second"), " tok/s")),
            m("tokens in/out", f"{tokens[0]} / {tokens[1]}"),
            m("GPU $ (busy)", f"${rec.get('estimated_gpu_cost_usd', 0):.4f}"),
            m("$/doc", "—" if per_doc is None else f"${per_doc:.5f}"),
            m("run span ≥", f"${rec.get('run_span_usd_lower_bound', 0):.4f} (×{rec.get('replicas', 1)} GPU)"),
        ]
    else:
        lines.append(p["dim"]("serving record pending …") if on else "serving record pending …")
    mpath = store.dir / "vllm_metrics_after.json"
    if mpath.is_file():
        try:
            met = json.loads(mpath.read_text())
        except ValueError:
            met = {}
        lines.append(m("/metrics", met.get("coverage", "—")))
        for key, rep in sorted((met.get("replicas") or {}).items()):
            hit = rep.get("prefix_cache_hit_rate")
            lines.append(
                m(
                    f"replica {key[-6:]}",
                    f"ttft {_fmt(rep.get('ttft_mean_seconds'), 's')} · prefix "
                    f"{'—' if hit is None else f'{100 * hit:.1f}%'} · preempt {_fmt(rep.get('preemptions'))}"
                    f" · len-cut {_fmt(rep.get('length_finishes'))}",
                )
            )
    return lines


def render_frame(
    *,
    snapshot: dict[str, Any],
    app: str,
    log_lines: list[str],
    spend: dict[str, float],
    width: int = 100,
    on: bool = False,
    blink: bool = False,
    lifecycle: dict[str, Any] | None = None,
    scorecard: list[str] | None = None,
) -> str:
    width = max(60, min(int(width), pl.MAX_W))
    p = pl.palette(on)
    s = snapshot
    out: list[str] = _header(s["run_id"], width=width, on=on)
    out.append(
        pl.render_status_bar(
            timestamp=time.strftime("%H:%M:%S") + f" · app {app}",
            stage=(lifecycle or {}).get("phase") or _stage_for(s["run_id"]),
            on=on,
            width=width,
            blink=blink,
        )
    )

    if lifecycle:
        el = int(lifecycle.get("elapsed_s") or 0)
        phase = f"▸{lifecycle['phase']}◂  {lifecycle.get('detail', '')}  ·  {el // 60}m{el % 60:02d}s  ·  {_stage_for(s['run_id'])}"
        out.append(pl._box("LIFECYCLE", [p["gold"](phase) if on else phase], width=width, on=on))

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

    if scorecard and lifecycle and lifecycle.get("phase") in TEARDOWN_PHASES:
        out.append(pl._box(f"📊 SCORECARD · {s['run_id']}", scorecard, width=width, on=on))

    tail = log_lines[-14:]
    log = [
        (p[_LOG_ROLE[classify_log_line(line)]](line) if on else line) for line in tail
    ] or [p["dim"]("(waiting on modal app logs …)") if on else "(waiting on modal app logs …)"]
    out.append(pl._box(f"DISPATCH LOG · modal app logs {app}", log, width=width, on=on))
    return "\n".join(out)


RECONNECT_NOTE = "… waiting for app (stopped between runs or booting) — will attach when it is live"


def log_command(app: str) -> list[str]:
    """`modal app logs <app>` fetches 100 lines and exits — `-f` streams live."""
    return ["modal", "app", "logs", "-f", app]


def note_reconnect(sink: Any) -> None:
    last = sink.last() if isinstance(sink, LogBuffer) else (sink[-1] if sink else None)
    if last != RECONNECT_NOTE:
        sink.append(RECONNECT_NOTE)


def _stream_logs(app: str, sink: Any, stop: threading.Event) -> None:
    """Follow `modal app logs <app>` into ``sink``; restart if the stream drops."""
    while not stop.is_set():
        try:
            proc = subprocess.Popen(
                log_command(app),
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
            note_reconnect(sink)
            stop.wait(10)


def read_ledger(ledger: Path | None) -> tuple[float, bool]:
    """(spent_usd, includes_live). ``includes_live`` = the ledger already counts
    the open fleet's time, so the TUI must not add its own live estimate."""
    if ledger is None or not ledger.is_file():
        return 0.0, False
    try:
        data = json.loads(ledger.read_text())
        return float(data.get("spent_usd") or 0.0), bool(data.get("includes_live"))
    except (ValueError, OSError):
        return 0.0, False


def watch(
    *,
    resolve: Callable[[], tuple[RunStore, str]],
    ledger: Path | None,
    cap_usd: float = 5.0,
    once: bool = False,
    logs: bool = True,
    interval: float = 2.0,
    times_dir: Path | None = None,
    log_path: Path | None = None,
    serving_dir: Path | None = None,
) -> int:
    from mailroom_sandbox.job.metrics import estimate_gpu_cost_usd
    from mailroom_sandbox.paths import reports_dir

    serving_dir = serving_dir or (reports_dir() / "serving")
    sink = LogBuffer(log_path)
    stop = threading.Event()
    store, app = resolve()
    if not once:
        sys.stdout.write(pl.ALT_ENTER + pl.HIDE_CURSOR)
    if logs and not once:
        threading.Thread(target=_stream_logs, args=(app, sink, stop), daemon=True).start()
    started = time.time()
    boot_mark: dict[str, int] = {}
    try:
        while True:
            store, _ = resolve()  # --follow: the current run can change between frames
            snap = run_snapshot(store)
            times = read_times(times_dir / f"{snap['run_id']}.times") if times_dir else {}
            key = f"{snap['run_id']}@{times.get('deploy_done', times.get('ready', 0))}"
            boot_mark.setdefault(key, sink.mark())
            life = lifecycle(times, sink.since(boot_mark[key]), now=time.time()) if times_dir else None
            card = (
                scorecard_lines(store, serving_dir=serving_dir, width=shutil.get_terminal_size((100, 40)).columns,
                                on=pl.use_color(sys.stdout))
                if life and life["phase"] in TEARDOWN_PHASES
                else None
            )
            spent, includes_live = read_ledger(ledger)
            live = 0.0
            if snap["state"] == "running" and not includes_live:
                live = float(
                    estimate_gpu_cost_usd(time.time() - started, gpu=snap["gpu"], replicas=snap["replicas"])
                    or 0.0
                )
            frame = render_frame(
                snapshot=snap,
                app=app,
                log_lines=sink.tail(14),
                spend={"spent_usd": spent, "live_usd": live, "cap_usd": cap_usd},
                width=shutil.get_terminal_size((100, 40)).columns,
                on=pl.use_color(sys.stdout),
                blink=int(time.time()) % 7 == 0,
                lifecycle=life,
                scorecard=card,
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


def print_scorecard(store: RunStore, *, serving_dir: Path, width: int | None = None) -> int:
    """`sandbox scorecard --run <id>`: one-shot mailroom scorecard for a finished run."""
    width = max(60, min(width or shutil.get_terminal_size((100, 40)).columns, pl.MAX_W))
    on = pl.use_color(sys.stdout)
    snap = run_snapshot(store)
    out = _header(snap["run_id"], width=width, on=on)
    out.append(pl._box(f"📊 SCORECARD · {snap['run_id']}", scorecard_lines(store, serving_dir=serving_dir, width=width, on=on), width=width, on=on))
    sys.stdout.write("\n".join(out) + "\n")
    return 0
