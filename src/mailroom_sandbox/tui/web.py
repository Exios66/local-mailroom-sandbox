"""Browser-hosted Tray TUI (`sandbox watch --web`).

Stdlib HTTP + SSE; reuses ``mailroom_sandbox.watch.compose_watch_state``.
Binds ``127.0.0.1`` by default — not a public dashboard (see operator docs).
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from mailroom_sandbox.tui.services_panel import SERVICES_CSS, SERVICES_HTML, SERVICES_JS
from mailroom_sandbox.tui.services_snapshot import read_services
from mailroom_sandbox.tui.shell import OPERATOR_CSS, OPERATOR_HTML, OPERATOR_JS
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.tui import pretty_log as pl
from mailroom_sandbox.watch import _LOG_ROLE, LogBuffer, _header, _stream_logs, compose_watch_state

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


# Mailroom brand — derived from pretty_log so the browser and terminal never drift.
THEME = {
    "blue": _hex(pl.BLUE),
    "teal": _hex(pl.TEAL),
    "cyan": _hex(pl.CYAN),
    "navy": _hex(pl.NAVY),
    "gold": _hex(pl.GOLD),
    "cream": _hex(pl.CREAM),
    "snow": _hex(pl.SNOW),
    "muted": _hex(pl.MUTED),
    "sky": _hex(pl.SKY),
    "amber": _hex(pl.AMBER_FACE),
    "extrude": _hex(pl.AMBER_EXTRUDE),
}
# terminal palette role → THEME token (pretty_log: warn=gold, mint=sky, dim=faint)
_ROLE_TOKEN = {"warn": "gold", "gold": "gold", "cyan": "cyan", "mint": "sky", "teal": "teal", "dim": "muted"}

# lifecycle phase → THEME token (mirrors watch._LIFECYCLE_ROLE palette roles)
_STATE_TOKEN = {
    "FAILED": "gold",
    "COMPLETE": "teal",
    "STOPPED": "teal",
    "TEARDOWN": "teal",
    "PAUSED": "gold",
    "REMOTE": "cyan",
    "SORTING": "gold",
    "COLD BOOT": "gold",
    "DEPLOYING": "gold",
    "PREFLIGHT": "cyan",
    "QUEUED": "muted",
}

_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def ansi_to_html(text: str) -> str:
    """Truecolor SGR (pretty_log output) → escaped HTML spans; other codes dropped."""
    out: list[str] = []
    open_span = False
    pos = 0
    for m in _SGR_RE.finditer(text):
        out.append(_html.escape(text[pos:m.start()], quote=False))
        pos = m.end()
        codes = [int(c) for c in m.group(1).split(";") if c] or [0]
        style: list[str] = []
        i = 0
        while i < len(codes):
            c = codes[i]
            if c in (38, 48) and i + 4 < len(codes) and codes[i + 1] == 2:
                prop = "color" if c == 38 else "background"
                style.append(f"{prop}:{_hex(tuple(codes[i + 2:i + 5]))}")
                i += 5
                continue
            if c == 1:
                style.append("font-weight:bold")
            elif c == 2:
                style.append("opacity:0.6")
            i += 1
        if open_span:
            out.append("</span>")
            open_span = False
        if style:
            # color first, then weight — stable order for callers/tests
            style.sort(key=lambda d: (not d.startswith(("color", "background")), d))
            out.append(f'<span style="{";".join(style)}">')
            open_span = True
    out.append(_html.escape(text[pos:], quote=False))
    if open_span:
        out.append("</span>")
    return "".join(out)


def should_open_browser(*, stream: Any = None) -> bool:
    if os.environ.get("NO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
        return False
    fh = stream or sys.stderr
    return hasattr(fh, "isatty") and bool(fh.isatty())


def browser_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{display_host}:{port}/"


class WatchWebSession:
    """Shared state for SSE clients and the background refresh loop."""

    def __init__(
        self,
        *,
        resolve: Callable[[], tuple[RunStore, str]],
        ledger: Path | None,
        cap_usd: float,
        times_dir: Path | None,
        sand032_root: Path | None = None,
        log_path: Path | None = None,
        serving_dir: Path,
        interval: float,
        follow_logs: bool,
        tick: Callable[[LogBuffer], None] | None = None,
        campaign_path: Path | None = None,
    ) -> None:
        self.resolve = resolve
        self.campaign_path = campaign_path
        self.tick = tick  # dev-server hook: advance a synthetic run before each refresh
        self.ledger = ledger
        self.cap_usd = cap_usd
        self.times_dir = times_dir
        self.sand032_root = sand032_root
        self.serving_dir = serving_dir
        self.interval = interval
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"ok": False, "error": "initializing"}
        self._version = 0
        self._stop = threading.Event()
        self._log_path_override = log_path
        self.sink = LogBuffer(None)
        self._started = time.time()
        self._last_run_id: str | None = None
        self._boot_mark: dict[str, int] = {}
        self._log_stop = threading.Event()
        self._follow_logs = follow_logs
        self._log_identity: tuple[Path, str] | None = None

    def refresh(self) -> dict[str, Any]:
        if self.tick is not None:
            self.tick(self.sink)
        from mailroom_sandbox.watch import _watch_paths

        store, app = self.resolve()
        rid = store.run_id
        identity = (store.dir, app)
        if identity != self._log_identity:
            from mailroom_sandbox.watch import start_log_streams

            self._log_stop.set()
            self._log_stop = threading.Event()
            _, resolved_log = _watch_paths(store, times_dir=self.times_dir,
                sand032_root=self.sand032_root, log_path=self._log_path_override)
            if self._follow_logs or self._log_identity is not None:
                self.sink = LogBuffer(resolved_log)
            if self._follow_logs:
                start_log_streams(store, app, self.sink, self._log_stop)
            self._log_identity = identity
        if self._last_run_id != rid:
            self._started = time.time()
            self._boot_mark = {}
            self._last_run_id = rid
        frame_times_dir, _ = _watch_paths(
            store,
            times_dir=self.times_dir,
            sand032_root=self.sand032_root,
            log_path=None,
        )
        state = compose_watch_state(
            store=store,
            app=app,
            sink=self.sink,
            ledger=self.ledger,
            cap_usd=self.cap_usd,
            times_dir=frame_times_dir,
            serving_dir=self.serving_dir,
            started=self._started,
            boot_mark=self._boot_mark,
            width=100,
            blink=int(time.time()) % 7 == 0,
            campaign_path=self.campaign_path,
        )
        layout = state.get("layout") or {}
        rid = state["snapshot"]["run_id"]
        hero_kw = dict(
            subtitle=layout.get("subtitle"),
            route_label=layout.get("route_label"),
            brand=str(layout.get("brand") or "DIGITAL MAILROOM"),
        )
        state["hero_html"] = ansi_to_html("\n".join(_header(rid, width=100, on=True, **hero_kw)))
        state["hero_compact_html"] = ansi_to_html(
            "\n".join(_header(rid, width=60, on=True, **hero_kw))
        )
        state["services"] = read_services()
        state["ok"] = True
        with self._lock:
            self._version += 1
            state["ui_version"] = self._version
            self._state = state
        return state

    def snapshot(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            return self._version, dict(self._state)

    def run_refresh_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception as exc:  # noqa: BLE001 — surface to UI
                with self._lock:
                    self._state = {"ok": False, "error": str(exc)}
                    self._version += 1
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        self._log_stop.set()


def _theme_css() -> tuple[str, str]:
    tokens = "; ".join(f"--{k}: {v}" for k, v in THEME.items())
    roles = "\n".join(
        f".log-line.{role} {{ color: var(--{_ROLE_TOKEN.get(tone, 'muted')}); }}" for role, tone in _LOG_ROLE.items()
    )
    states = "\n".join(
        f".stage-{phase.lower().replace(' ', '-')} {{ color: var(--{token}); }}"
        for phase, token in _STATE_TOKEN.items()
    )
    return tokens, roles + "\n" + states


def _html_page() -> bytes:
    tokens, roles = _theme_css()
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tray TUI · THE MAILROOM · live watch</title>
<style>
:root {{
  {tokens};
  --frame: linear-gradient(135deg, var(--blue), var(--teal));
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; min-height: 100vh; font-family: ui-monospace, "IBM Plex Mono", Menlo, monospace;
  background: #080f17; color: var(--snow); font-size: 13px; line-height: 1.5;
}}
.wrap {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
.frame {{
  border: 1px solid #294051; border-radius: 8px;
  background: #101c28;
}}
.inner {{ padding: 24px; }}
header {{ position: relative; padding-right: 120px; }}
header h1 {{
  margin: 0 0 6px; font-size: 20px; letter-spacing: 0.1em;
  color: var(--gold);
}}
header .sub {{ color: #b6c8d8; font-size: 12px; margin-bottom: 8px; overflow-wrap: anywhere; }}
header .brand-art {{ position: absolute; top: 0; right: 0; color: #b6c8d8; font-size: 11px; }}
header .brand-art[open] {{ position: static; padding: 12px 0; }}
summary {{ cursor: pointer; }}
.view-nav {{ display: flex; gap: 4px; border-bottom: 1px solid #294051; margin: 20px 0; overflow-x: auto; }}
.view-nav button {{ font: inherit; padding: 10px 14px; background: transparent; color: #b6c8d8; border: 0; border-bottom: 2px solid transparent; cursor: pointer; }}
.view-nav button[aria-current="page"] {{ color: var(--gold); border-bottom-color: var(--gold); }}
[hidden] {{ display: none !important; }}
.view-heading {{ font-size: 15px; color: var(--cream); margin: 0 0 12px; }}
.view-note {{ color: #b6c8d8; font-size: 12px; }}
.configuration {{ border: 1px solid #294051; padding: 16px; border-radius: 4px; }}
.campaign-run {{ display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; border-bottom: 1px solid #294051; padding: 12px 0; overflow-wrap: anywhere; }}
@media (max-width: 600px) {{ .wrap {{ padding: 8px; }} .inner {{ padding: 14px; }} header {{ padding-right: 0; }} header .brand-art {{ position: static; margin-top: 8px; }} .view-nav button {{ padding: 10px 8px; font-size: 12px; }} }}
header .route {{ color: var(--cyan); font-size: 11px; letter-spacing: 0.06em; }}
.status {{
  display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
  padding: 10px 12px; margin: 16px 0 12px; background: #080f17;
  border: 1px solid #294051; border-radius: 4px; font-size: 12px;
}}
{SERVICES_CSS}
{OPERATOR_CSS}
.status .stage {{ color: var(--gold); font-weight: 600; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
@media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.panel {{
  border: 1px solid #294051; border-radius: 4px; overflow: hidden; min-width: 0;
}}
.panel h2 {{
  margin: 0; padding: 10px 14px; font-size: 11px; letter-spacing: 0.1em;
  background: #172836; color: var(--cream); text-transform: uppercase;
}}
.panel .body {{ padding: 14px; }}
.metric {{ display: flex; justify-content: space-between; gap: 12px; padding: 2px 0; }}
.metric .k {{ color: #b6c8d8; }}
.metric .v {{ color: var(--snow); text-align: right; overflow-wrap: anywhere; min-width: 0; }}
.bar {{
  font-family: inherit; letter-spacing: 1px; color: var(--cyan);
  margin: 6px 0; white-space: nowrap; overflow: hidden;
}}
.lifecycle {{
  margin: 12px 0; padding: 10px 12px; border-left: 3px solid var(--gold);
  background: rgba(245,196,69,0.08); color: var(--cream);
}}
.lifecycle.live {{ animation: lifecycle-pulse 2.2s ease-in-out infinite; }}
@keyframes lifecycle-pulse {{ 50% {{ border-left-color: var(--cyan); opacity: 0.92; }} }}
.route-lines {{ white-space: pre-wrap; overflow-wrap: anywhere; color: #b6c8d8; font-size: 11px; line-height: 1.5; }}
.log {{
  margin-top: 12px; max-height: 280px; overflow-y: auto;
  border: 1px solid var(--teal); border-radius: 6px; background: #050f1a;
}}
.log h2 {{ position: sticky; top: 0; }}
.log-line {{ padding: 2px 10px; border-bottom: 1px solid rgba(14,116,144,0.2); word-break: break-all; }}
.log-line .src {{ color: #b6c8d8; font-size: 10px; text-transform: uppercase; margin-right: 6px; }}
{roles}
.log-line.error {{ font-weight: 600; }}
.log-line.dim {{ color: #b6c8d8; }}
.log-line.plain {{ color: #b6c8d8; }}
.log-line.ready {{ color: var(--cyan); }}
.stage-complete, .stage-stopped, .stage-teardown {{ color: var(--cyan); }}
.hero span[style="color:#0e7490"] {{ color: var(--cyan) !important; }}
.log-tools {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 16px; }}
.log-tools input, .log-tools select {{ font: inherit; color: var(--snow); background: #071a2e; border: 1px solid var(--cyan); padding: 6px; border-radius: 4px; max-width: 100%; }}
.log-tools input[type="search"] {{ width: 180px; }}
:focus-visible {{ outline: 2px solid var(--gold); outline-offset: 3px; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }}
@media (prefers-reduced-motion: reduce) {{ .lifecycle.live, .blink .stage {{ animation: none; }} }}
#hero {{ font-size: min(12px, calc((100vw - 84px) / 60)); }}
#hero-compact {{ display: none; font-size: min(12px, calc((100vw - 84px) / 36)); }}
@media (max-width: 800px) {{ #hero {{ display: none; }} #hero-compact {{ display: block; }} }}
.hero {{
  margin: 0 0 10px; line-height: 1.15; font-family: ui-monospace, "IBM Plex Mono", Menlo, monospace;
  white-space: pre; overflow-x: auto; color: var(--snow);
}}
.err-banner {{ background: var(--gold); color: #1a0505; padding: 10px; border-radius: 4px; margin-bottom: 12px; }}
.blink .stage {{ animation: pulse 1s ease-in-out infinite; }}
@keyframes pulse {{ 50% {{ opacity: 0.55; }} }}
footer {{ margin-top: 16px; font-size: 11px; color: #b6c8d8; text-align: center; }}
</style>
</head>
<body>
<main class="wrap">
  <div class="frame"><div class="inner">
    <header>
      <h1>THE MAILROOM <span aria-hidden="true">(o,o)</span></h1>
      <div class="sub" id="brand-sub" hidden>DIGITAL MAILROOM</div>
      <div class="route" id="route-label" hidden>INBOX → SPECIALIST → REPORT</div>
      <details class="brand-art"><summary>Wordmark</summary>
        <pre class="hero" id="hero" aria-hidden="true">(o,o) THE MAILROOM</pre>
        <pre class="hero" id="hero-compact" aria-hidden="true">(o,o) THE MAILROOM</pre>
      </details>
    </header>
    <div id="error" class="err-banner" role="alert" hidden></div>
    <div class="status" id="status-bar">
      <span class="stage" id="stage">—</span>
      <span id="ts">—</span>
      <span id="app-line">—</span>
      <span id="connection" role="status">Connecting…</span>
    </div>
    {SERVICES_HTML}
    <nav class="view-nav" aria-label="Operator workspace">
      <button type="button" data-target="overview" aria-current="page">Overview</button>
      <button type="button" data-target="terminal">Terminal</button>
      <button type="button" data-target="configuration">Configuration</button>
      <button type="button" data-target="campaign">Campaign</button>
    </nav>
    <section data-view="configuration" hidden aria-labelledby="config-heading">
      <h2 class="view-heading" id="config-heading">Locked run configuration</h2>
      <p class="view-note">Values from the active run manifest. Configured capacity is not a measurement of active GPUs.</p>
      <pre class="route-lines configuration" id="configuration"></pre>
    </section>
    <section data-view="campaign" hidden aria-labelledby="campaign-heading">
      <h2 class="view-heading" id="campaign-heading">Experimental campaign</h2>
      <div id="campaign-content" class="view-note">No campaign associated with this watcher.</div>
    </section>
    {OPERATOR_HTML}
    <section data-view="overview" aria-label="Run overview">
    <div class="lifecycle" id="lifecycle" hidden></div>
    <details><summary class="view-note">Run route and campaign details</summary><div class="route-lines" id="program-route" hidden></div></details>
    <div class="grid">
      <section class="panel">
        <h2 id="tray-heading">Tray TUI · In-tray</h2>
        <div class="body" id="intray"></div>
      </section>
      <section class="panel">
        <h2 id="postage-heading">Postage ($)</h2>
        <div class="body" id="postage"></div>
      </section>
    </div>
    <section class="panel log" id="scorecard-wrap" hidden>
      <h2 id="scorecard-heading">Scorecard</h2>
      <div class="body" id="scorecard"></div>
    </section>
    <div class="log-tools" aria-label="Dispatch log controls">
      <label>Filter <input id="log-query" type="search" placeholder="Search log text" aria-keyshortcuts="/ Escape"></label>
      <label>Level <select id="log-level"><option value="all">All messages</option><option value="error">Errors</option><option value="warn">Warnings + errors</option></select></label>
      <label><input id="log-follow" type="checkbox" checked> Follow latest</label>
      <span id="log-count"></span>
    </div>
    <section class="panel log" tabindex="0" aria-labelledby="dispatch-heading">
      <h2 id="dispatch-heading">Dispatch log</h2>
      <div id="logs"></div>
    </section>
    </section>
  </div></div>
  <footer id="footer-line">Tray TUI · localhost-only · SSE + poll · hard-refresh after a watch restart</footer>
</main>
<script>
const LOG_CLASS = {{ error: "error", warn: "warn", throughput: "throughput", kv: "kv", ready: "ready", plain: "plain" }};  // = watch._LOG_ROLE keys

function metric(k, v) {{
  return `<div class="metric"><span class="k">${{k}}</span><span class="v">${{esc(v)}}</span></div>`;
}}
function esc(s) {{
  return String(s ?? "—").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}}
function showView(name) {{
  for (const panel of document.querySelectorAll("[data-view]")) panel.hidden = panel.dataset.view !== name;
  for (const button of document.querySelectorAll("[data-target]")) {{
    if (button.dataset.target === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }}
  if (name === "terminal") document.getElementById("command-input").focus();
}}
for (const button of document.querySelectorAll("[data-target]")) button.addEventListener("click", () => showView(button.dataset.target));
let logLines = [];
let dispatchName = "Dispatch log";
function renderLogs() {{
  const logs = document.getElementById("logs");
  const pane = logs.parentElement;
  const scrollTop = pane.scrollTop;
  const query = document.getElementById("log-query").value.toLowerCase();
  const level = document.getElementById("log-level").value;
  const lines = logLines.filter(e => (level === "all" || e.role === "error" || (level === "warn" && e.role === "warn")) &&
    String(e.text ?? "").toLowerCase().includes(query));
  logs.innerHTML = lines.length
    ? lines.map(e => `<div class="log-line ${{LOG_CLASS[e.role] || "plain"}}"><span class="src">${{esc(e.source || "modal")}}</span> ${{esc(e.text)}}</div>`).join("")
    : `<div class="log-line dim">${{logLines.length ? "No matching messages" : `(waiting on ${{esc(dispatchName)}} · job events appear here)…`}}</div>`;
  document.getElementById("log-count").textContent = `${{lines.length}}/${{logLines.length}} messages`;
  if (document.getElementById("log-follow").checked) pane.scrollTop = pane.scrollHeight;
  else pane.scrollTop = scrollTop;
}}
for (const id of ["log-query", "log-level", "log-follow"]) document.getElementById(id).addEventListener("input", renderLogs);
document.addEventListener("keydown", ev => {{
  const editing = ev.target.closest("input, select, textarea, [contenteditable]");
  if (ev.key === "/" && !editing && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {{
    ev.preventDefault(); document.getElementById("log-query").focus();
  }}
  if (ev.key === "Escape" && ev.target.id === "log-query") {{ ev.target.value = ""; renderLogs(); }}
}});

{SERVICES_JS}
{OPERATOR_JS}
function render(state) {{
  operatorState = state || {{}};
  services(state && state.services);
  if (!state || (state.ok === false && !state.snapshot)) {{
    document.getElementById("error").hidden = false;
    document.getElementById("error").textContent = (state && state.error) || "unknown error";
    return;
  }}
  if (state.ok === false) {{
    document.getElementById("error").hidden = false;
    document.getElementById("error").textContent = state.error || "unknown error";
  }} else {{
    document.getElementById("error").hidden = true;
  }}
  if (state.hero_html) document.getElementById("hero").innerHTML = state.hero_html;
  if (state.hero_compact_html) document.getElementById("hero-compact").innerHTML = state.hero_compact_html;
  const s = state.snapshot || {{}};
  const sp = state.spend || {{}};
  const layout = state.layout || {{}};
  const panels = layout.panels || {{}};
  document.getElementById("configuration").textContent = (layout.configuration || []).join("\\n");
  const campaign = state.campaign;
  document.getElementById("campaign-content").innerHTML = campaign
    ? `<p>${{esc(campaign.study)}} · ${{esc(campaign.design)}} · ${{esc(campaign.completed)}}/${{esc(campaign.total)}} runs complete</p>` +
      campaign.runs.map(run => `<div class="campaign-run"><span>${{run.run_id === campaign.current ? "▶ " : ""}}${{esc(run.run_id)}}</span><span>${{esc(run.state)}} · ${{esc(run.done)}}/${{esc(run.total)}}</span></div>`).join("")
    : "No campaign associated with this watcher. Use sandbox experiment watch --config <experiment.yaml>.";
  document.title = panels.window_title || "Tray TUI · THE MAILROOM · live watch";
  document.getElementById("brand-sub").hidden = false;
  document.getElementById("route-label").hidden = false;
  document.getElementById("brand-sub").textContent =
    (layout.brand || "DIGITAL MAILROOM") + "  ·  " + (state.subtitle || "") + "  ·  " + (s.run_id || "");
  document.getElementById("route-label").textContent = state.route_label || "";
  if (panels.tray) document.getElementById("tray-heading").textContent = panels.tray;
  if (panels.postage) document.getElementById("postage-heading").textContent = panels.postage;
  if (panels.dispatch) document.getElementById("dispatch-heading").textContent = panels.dispatch;
  if (panels.scorecard) document.getElementById("scorecard-heading").textContent = panels.scorecard;
  const bar = document.getElementById("status-bar");
  bar.classList.toggle("blink", !!state.blink && !!state.animate_lifecycle);
  const L = state.lifecycle || {{}};
  let phase = L.phase || state.stage || "—";
  let detail = L.detail || "";
  // In-flight docs are never COLD BOOT — first SSE frame used to stick here.
  if (s.state === "running" && (phase === "COLD BOOT" || phase === "DEPLOYING" || phase === "QUEUED")) {{
    phase = "SORTING";
    detail = detail && !/engine ready|container starting|loading weights/i.test(detail)
      ? detail
      : ((s.task || "specialist") + " in flight");
  }}
  const stageEl = document.getElementById("stage");
  stageEl.textContent = phase;
   stageEl.className = "stage stage-" + String(phase || "unknown").toLowerCase().replace(/\\s+/g, "-");
  document.getElementById("ts").textContent = state.ts || "";
  const watcher = state.watcher_label || ("Tray TUI watcher · app " + (state.app || "—"));
  document.getElementById("app-line").textContent = watcher;

  const life = document.getElementById("lifecycle");
  if (state.lifecycle || s.state === "running") {{
    life.hidden = false;
    life.classList.toggle("live", phase === "SORTING" || !!state.animate_lifecycle);
    const el = L.elapsed_s || 0;
    const tag = layout.stage || "";
    life.textContent = `▸${{phase}}◂  ${{detail}}  ·  ${{Math.floor(el/60)}}m${{String(el%60).padStart(2,"0")}}s` + (tag ? `  ·  ${{tag}}` : "");
  }} else {{ life.hidden = true; life.classList.remove("live"); }}

  const route = document.getElementById("program-route");
  if (state.route && state.route.length) {{
    route.hidden = false;
    route.textContent = state.route.join("\\n");
  }} else if (state.job_route && state.job_route.length) {{
    route.hidden = false;
    route.textContent = state.job_route.join("\\n");
  }} else route.hidden = true;

  const prog = state.progress || {{}};
  document.getElementById("intray").innerHTML =
    metric("run", s.run_id) +
    metric("specialist", s.task) +
    metric("capacity", `${{s.gpu === "—" ? "no GPU declared" : `×${{s.replicas}} ${{s.gpu}}`}} · ${{s.state}}`) +
    `<div class="bar">${{esc(prog.bar)}}  ${{prog.done}}/${{prog.total}}</div>` +
    metric("sorted", `delivered ${{s.ok}} · returned ${{s.errors}}`) +
    metric("postmark", `p50 ${{s.p50_s ?? "—"}}s · p95 ${{s.p95_s ?? "—"}}s`) +
    metric("score", s.mean_score) +
    (s.last_error ? `<div class="metric"><span class="k">last return</span><span class="v" style="color:var(--gold)">${{esc(s.last_error)}}</span></div>` : "");

  const pct = sp.pct_of_cap != null ? sp.pct_of_cap + "%" : "";
  const tokIn = Number(s.prompt_tokens ?? sp.prompt_tokens ?? 0);
  const tokOut = Number(s.completion_tokens ?? sp.completion_tokens ?? 0);
  document.getElementById("postage").innerHTML =
    metric("basis", sp.basis || "not measured") +
    metric("sorted", `delivered ${{s.ok ?? sp.ok ?? 0}} · returned ${{s.errors ?? sp.errors ?? 0}}`) +
    metric("docs", `${{prog.done ?? s.done ?? 0}}/${{prog.total ?? s.total ?? 0}}`) +
    metric("tokens", `${{tokIn}} in · ${{tokOut}} out`) +
    metric("ledger", "$" + Number(sp.spent_usd || 0).toFixed(4)) +
    metric("live run", "$" + Number(sp.live_usd || 0).toFixed(4)) +
    metric("total", `$${{Number(sp.total_usd || 0).toFixed(4)}} / $${{Number(sp.cap_usd || 0).toFixed(2)}}`) +
    `<div class="bar">${{esc(sp.bar || "")}}  ${{pct}}</div>` +
    metric("gate", `$${{Number(sp.gate_usd || 4.5).toFixed(2)}} projected-total stop`) +
    (sp.over_gate ? `<div class="metric"><span class="v" style="color:var(--gold)">⚠ OVER GATE</span></div>` : "");
  const foot = document.getElementById("footer-line");
  if (foot) {{
    foot.textContent = `Tray TUI · ${{s.run_id || "—"}} · ${{prog.done ?? 0}}/${{prog.total ?? 0}} · $${{Number(sp.total_usd || 0).toFixed(4)}} · v${{state.ui_version || "—"}}`;
  }}

  const sc = document.getElementById("scorecard-wrap");
  if (state.scorecard && state.scorecard.length) {{
    sc.hidden = false;
    document.getElementById("scorecard").innerHTML = state.scorecard.map(l => `<div>${{esc(l)}}</div>`).join("");
  }} else sc.hidden = true;

   logLines = state.logs || [];
   dispatchName = (panels.dispatch || "Dispatch log").replace(/^Dispatch log · /, "");
   renderLogs();
}}

function pullState() {{
  fetch("/api/state?t=" + Date.now(), {{ cache: "no-store" }})
    .then((r) => {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
    .then(state => {{ document.getElementById("connection").textContent = es.readyState === EventSource.OPEN ? "Live · SSE" : "Connected · polling"; render(state); }})
    .catch(() => {{ document.getElementById("connection").textContent = "Disconnected · retrying"; }});
}}
pullState();
setInterval(pullState, 2000);
const es = new EventSource("/api/stream?t=" + Date.now());
es.onmessage = (ev) => {{
  document.getElementById("connection").textContent = "Live · SSE";
  try {{ render(JSON.parse(ev.data)); }} catch (e) {{ console.error(e); }}
}};
es.onerror = () => {{
  document.getElementById("connection").textContent = "Reconnecting · polling";
  document.getElementById("error").hidden = false;
  document.getElementById("error").textContent = "SSE disconnected — polling /api/state…";
}};
</script>
</body>
</html>"""
    return page.encode("utf-8")


def make_handler(session: WatchWebSession) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return  # quiet localhost server

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                body = _html_page()
                self._send(200, "text/html; charset=utf-8", body)
                return
            if path == "/api/state":
                _, state = session.snapshot()
                self._send_json(state)
                return
            if path == "/api/commands":
                from mailroom_sandbox.cli import build_parser
                from mailroom_sandbox.tui.shell import command_catalog

                self._send(200, "application/json", json.dumps(command_catalog(build_parser())).encode())
                return
            if path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                last_ver = -1
                try:
                    while not session._stop.is_set():
                        ver, state = session.snapshot()
                        if ver != last_ver:
                            payload = json.dumps(state, separators=(",", ":"))
                            self.wfile.write(f"data: {payload}\n\n".encode())
                            self.wfile.flush()
                            last_ver = ver
                        session._stop.wait(session.interval)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self._send(404, "text/plain", b"not found")

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, obj: dict[str, Any]) -> None:
            self._send(200, "application/json", json.dumps(obj).encode())

    return Handler


def serve_watch_web(
    *,
    resolve: Callable[[], tuple[RunStore, str]],
    ledger: Path | None,
    cap_usd: float = 5.0,
    logs: bool = True,
    interval: float = 2.0,
    times_dir: Path | None = None,
    sand032_root: Path | None = None,
    log_path: Path | None = None,
    serving_dir: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool | None = None,
    tick: Callable[[LogBuffer], None] | None = None,
    campaign_path: Path | None = None,
) -> int:
    from mailroom_sandbox.paths import reports_dir

    serving_dir = serving_dir or (reports_dir() / "serving")
    session = WatchWebSession(
        resolve=resolve,
        ledger=ledger,
        cap_usd=cap_usd,
        times_dir=times_dir,
        sand032_root=sand032_root,
        log_path=log_path,
        serving_dir=serving_dir,
        interval=interval,
        follow_logs=logs,
        tick=tick,
        campaign_path=campaign_path,
    )
    try:
        session.refresh()
        handler = make_handler(session)
        httpd = ThreadingHTTPServer((host, port), handler)
    except BaseException:
        session.stop()
        raise
    threading.Thread(target=session.run_refresh_loop, daemon=True).start()
    bound_host, bound_port = httpd.server_address[0], httpd.server_address[1]
    url = browser_url(bound_host, bound_port)
    print(f"Tray TUI watch (browser) at {url}", file=sys.stderr)
    if open_browser if open_browser is not None else should_open_browser():
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
        httpd.shutdown()
        httpd.server_close()
    return 0
