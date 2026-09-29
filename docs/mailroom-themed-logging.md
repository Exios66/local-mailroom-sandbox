# Mailroom themed logging & live watch

Long Modal GPU evals (vLLM serve + `sandbox run start --job-mode endpoint`) can run for
hours. The sandbox ships a **mailroom-themed live watch** (SAND-032) that combines run
progress, spend, lifecycle phase, and a **live tail of Modal app logs** in one
surface — terminal alt-screen or browser — without losing scrollback in the job tab.

A lighter **CLI session layer** (SAND-033) adds themed banners and progress lines to
`sandbox run … --watch` and related commands; it does **not** replace the full watch
TUI when you need vLLM dispatch logs.

## Which surface to use

| Goal | Command | Modal log tail | UI |
| --- | --- | --- | --- |
| Full in-tray + postage + **dispatch log** while a long Modal eval runs | `sandbox watch` (or `scripts/mailroom-tui`) | yes (`modal app logs -f`) | alt-screen terminal or browser |
| Same panels in a browser tab; terminal free for other work | `sandbox watch --web` / `scripts/mailroom-tui web` | yes | `http://127.0.0.1:8765/` (SSE) |
| Theme preview with **no Modal spend** | `sandbox dev` / `watch --web --demo` | synthetic only | browser |
| Themed progress while **this shell** runs the job (endpoint mode) | `sandbox run start … --watch` | no — use watch in a **second pane** | scroll-friendly stderr lines |
| Poll a **Modal job worker** (`--job-mode modal`) | `sandbox run start|status … --watch` | no — worker logs in Modal dashboard / `modal app logs` | stderr progress lines |
| Post-run quality + serving summary | `sandbox scorecard --run <id>` | — | one-shot terminal |
| Every beacon job in the family (not one run YAML) | `sandbox board` | optional per job | browser `:8767` or `--tui` |

**Rule of thumb:** for attended L4 ladder / warm-flow / multi-hour endpoint runs, open
**watch in a second terminal** (or `--web`) before starting `scripts/sand032/*` or
`sandbox run start --job-mode endpoint`.

---

## Quick start (long Modal eval)

### Two-pane terminal (recommended)

**Pane A — start the job** (example: single run YAML):

```bash
sandbox run preflight --config config/runs/my-run.yaml --live
sandbox run start --config config/runs/my-run.yaml --job-mode endpoint
```

**Pane B — attach the watch TUI** (same run):

```bash
sandbox watch --config config/runs/my-run.yaml
```

Or, during SAND-032 warm flows that update `data/runtime/sand032/current`:

```bash
# Pane B — no flags while sand032/current exists
sandbox watch
```

Stop the watch with **Ctrl+C** (restores the terminal; does not stop the eval).

### Browser watch (same machine)

```bash
sandbox watch --web --config config/runs/my-run.yaml
# or
scripts/mailroom-tui web --config config/runs/my-run.yaml
```

Default URL: **http://127.0.0.1:8765/** — live updates via **SSE** (`/api/stream`).
Leave the server running in one terminal; **Ctrl+C** there stops the web UI only.

Headless / CI / SSH without browser:

```bash
NO_BROWSER=1 sandbox watch --web --config config/runs/my-run.yaml
# or
sandbox watch --web --no-browser --config config/runs/my-run.yaml
```

### Launcher shorthand (`scripts/mailroom-tui`)

Equivalent to `sandbox` via `PYTHONPATH=src`:

```bash
scripts/mailroom-tui                              # terminal watch (follows sand032/current if set)
scripts/mailroom-tui --config config/runs/x.yaml  # terminal watch, one run
scripts/mailroom-tui web [--config …]             # browser watch
scripts/mailroom-tui dev                          # synthetic demo UI (= sandbox dev)
scripts/mailroom-tui score <run-id>               # = sandbox scorecard --run <run-id>
scripts/mailroom-tui board [--tui|--demo]         # family job board
```

Optional alias: `alias mailroom-tui="$PWD/scripts/mailroom-tui"`.

---

## `sandbox watch` — full command reference

```bash
sandbox watch \
  [--config config/runs/<name>.yaml] \
  [--follow data/runtime/sand032/current] \
  [--app <modal-app-name>] \
  [--ledger data/runtime/sand032/spend.json] \
  [--cap-usd 5.0] \
  [--interval 2.0] \
  [--once] \
  [--no-logs] \
  [--web] [--host 127.0.0.1] [--port 8765] [--no-browser] [--demo]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--config` | — | Run YAML whose `run_id` resolves the store under `data/runtime/runs/<run_id>/`. |
| `--follow` | — | Path to a **file containing a run YAML path**; re-read every refresh so the UI tracks the active SAND-032 step. |
| *(bare)* | — | If `data/runtime/sand032/current` exists, sets `--follow` to that file and `--ledger` to `data/runtime/sand032/spend.json`. |
| `--app` | from spec `engine.modal.app` | Modal app name passed to `modal app logs -f`. |
| `--ledger` | — | JSON with `spent_usd` (and optional `includes_live`) for the **postage** panel. |
| `--cap-usd` | `5.0` | Spend bar denominator (independent of the $4.50 **gate** warning in the UI). |
| `--interval` | `2.0` | Seconds between frame refreshes (terminal and web). |
| `--once` | off | Render one frame to stdout and exit (scripting / screenshots). |
| `--no-logs` | off | Skip `modal app logs -f` (in-tray + postage only). |
| `--web` | off | Browser UI instead of alt-screen terminal. |
| `--host` | `127.0.0.1` | Bind address (web only). |
| `--port` | `8765` | Bind port; `0` = ephemeral (web only). |
| `--no-browser` / `NO_BROWSER=1` | open if stderr is a TTY | Do not auto-open a browser tab (web only). |
| `--demo` | off | With `--web`: synthetic looping run in a temp dir (no Modal). |

**Requirements for dispatch log tail:**

- [`modal`](https://modal.com/docs/guide) CLI on `PATH` and authenticated (`modal token new`).
- Correct `--app` (usually `sandbox-vllm` or the app name in your run YAML).

Implementation: `src/mailroom_sandbox/watch.py` (terminal), `src/mailroom_sandbox/tui/web.py` (browser).

---

## What the watch UI shows

### Panels

1. **Header** — owl wordmark, “DIGITAL MAILROOM”, eval subtitle, run id, route `INBOX → SPECIALIST → REPORT`.
2. **Status bar** — clock, Modal app name, lifecycle **stage** (blink cadence on terminal).
3. **Lifecycle** (SAND-032 driver stamps) — phases such as `QUEUED`, `DEPLOYING`, `COLD BOOT`, `PREFLIGHT`, `SORTING`, `TEARDOWN`, `STOPPED`, with sub-detail (e.g. KV cache profiling during cold boot).
4. **Program route** (when `times_dir` is set) — multi-run ladder checklist (✓ / ▶ / ·).
5. **In-tray** — checkpoint cursor/total, delivered vs returned docs, postmark p50/p95, mean score, last error.
6. **Postage ($)** — ledger spend + live GPU estimate, cap bar, **$4.50 gate** warning when projected total exceeds the gate.
7. **Scorecard** — appears in teardown/stopped phases from `reports/serving/<run_id>.serving.json` and optional `/metrics` scrape files.
8. **Dispatch log** — last lines from Modal app logs, colour-coded: errors, warnings, throughput, KV cache, engine ready.

Progress and spend bars use mailroom-ml glyphs (`█` / `░`).

### On-disk artifacts (SAND-032)

| Path | Role |
| --- | --- |
| `data/runtime/sand032/current` | One line: path to the **active** run YAML (`run_one.sh` updates each step). |
| `data/runtime/sand032/spend.json` | Ledger for postage (`scripts/sand032/spend.py`). |
| `data/runtime/sand032/logs/modal-app.log` | Persistent Modal log mirror (first watch instance holds the write lock). |
| `data/runtime/sand032/logs/<run_id>.times` | Driver epoch stamps for lifecycle (`deploy_start`, `ready`, `run_start`, …). |
| `data/runtime/runs/<run_id>/` | Run store: `items.jsonl`, `checkpoint.json`, lock, metrics scrapes. |

---

## Tailing Modal logs manually

The watch TUI runs:

```bash
modal app logs -f <app>
```

(`-f` is required — without it Modal returns a snapshot and exits.)

Useful when watch is not running or you need full scrollback in plain text:

```bash
modal app logs -f sandbox-vllm          # or your engine.modal.app
modal app logs -f sandbox-vllm-sand032  # SAND-032 fleet name when used
```

Remote **job worker** logs (CPU container running `run_job`, not the vLLM serve app):

```bash
modal app logs -f <modal-job-app>   # see deploy/modal_job.py app name after deploy
```

Watch **does not** automatically tail the job worker app — only the vLLM **serve** app configured for the run.

---

## Browser watch (details)

See also [mailroom-watch-web.md](mailroom-watch-web.md) for a short browser-only cheat sheet.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | Themed HTML page |
| `GET /api/stream` | Server-Sent Events: JSON snapshots (same shape as `compose_watch_state`) |
| `GET /api/state` | One-shot JSON snapshot |

Security: binds **`127.0.0.1` by default**, no authentication. Do not expose on `0.0.0.0` without a reverse proxy and auth.

Dev / design review without Modal:

```bash
sandbox dev
# equivalent:
sandbox watch --web --demo
scripts/mailroom-tui dev
```

Claude Code / IDE launch configs (`.claude/launch.json`): `mailroom-watch-dev` (port 8765), `mailroom-watch-live` (8766).

---

## `sandbox run … --watch` (job-attached console)

These commands use `mailroom_sandbox.tui.session.MailroomConsole` — **not** the alt-screen watch:

```bash
# Endpoint mode: this process runs items; progress lines on stderr
sandbox run start --config config/runs/x.yaml --job-mode endpoint --watch

# Modal worker mode: poll remote state dict (20 min stall guard)
sandbox run start --config config/runs/x.yaml --job-mode modal --watch
sandbox run status --run-id <id> --watch
```

For endpoint runs against Modal vLLM, still run **`sandbox watch --web`** in another pane if you want dispatch logs and postage while the job tab stays plain.

Plain output (no colour / banners): set `NO_COLOR=1` or `SANDBOX_PLAIN_LOGS=1`, or redirect stderr to a file.

---

## Scorecard (finished run)

```bash
sandbox scorecard --run sand032-s2a-corr100-1rep
sandbox scorecard --run <run_id> --serving-dir reports/serving
scripts/mailroom-tui score <run_id>
```

One-shot mailroom frame with quality + serving metrics (same data as the watch scorecard panel).

---

## Family job board (related)

Persistent view of **all** `mailroom.beacon/v1` jobs under `~/.mailroom/jobs` (or `$MAILROOM_BEACON_DIR`):

```bash
sandbox board                    # browser http://127.0.0.1:8767/
sandbox board --tui              # terminal alt-screen
sandbox board --demo             # synthetic jobs for UI dev
sandbox beacon update --job ID --package P --done N --total M
scripts/mailroom-tui board [--tui|--demo]
```

Long shell scripts can publish progress with `mailroom_sandbox.tui.beacon.Beacon` or `sandbox beacon update`.

Spec: [superpowers/specs/2026-09-28-mailroom-job-beacon-design.md](superpowers/specs/2026-09-28-mailroom-job-beacon-design.md).

---

## Typical operator workflows

### SAND-032 warm flow (`scripts/sand032/flow*.sh`)

1. Terminal 1: `scripts/sand032/flow.sh` (or `flow2.sh`, …).
2. Terminal 2: `sandbox watch` (follows `current` + ledger automatically).
3. Optional: `sandbox watch --web` on a laptop browser via SSH local forward:

   ```bash
   ssh -L 8765:127.0.0.1:8765 user@host
   # on host: sandbox watch --web --no-browser
   ```

### Single runbook eval (Modal endpoint)

Documented in operator runbooks; pattern:

```bash
sandbox run preflight --config "$cfg" --live
sandbox run start --config "$cfg" --job-mode endpoint --watch   # pane A
# pane B (recommended for vLLM logs):
sandbox watch --config "$cfg"
```

### Modal remote **job** worker (not endpoint against serve app)

```bash
cd deploy && modal deploy modal_job.py
sandbox run start --job-mode modal --config config/runs/x.yaml --watch
```

Use `modal app logs` on the **worker** app for container stderr; use **`sandbox watch`** against the **vLLM serve** app if the worker calls a Modal-hosted endpoint listed in the run spec.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `ERROR: --config or --follow required` | No `data/runtime/sand032/current`; pass `--config` or `--follow`. |
| `ERROR modal CLI not found on PATH` | Install Modal CLI / `[deploy]` extra; or use `--no-logs`. |
| Dispatch log stuck on “waiting on modal app logs …” | App not deployed yet, wrong `--app`, or fleet between runs (watch shows reconnect note and retries every 10s). |
| Postage always $0 | Pass `--ledger` or run SAND-032 spend writer; live estimate needs `state: running` in checkpoint. |
| Two watch instances, duplicate log lines on disk | Only one instance holds `modal-app.log.lock`; others read the buffer. |
| Web UI “SSE disconnected” | Server stopped or network; refresh page; restart `sandbox watch --web`. |
| `--watch` on run shows no vLLM lines | Expected — use `sandbox watch` for Modal serve logs. |
| Modal job `--watch` exits after 20 min idle | Stall guard (hub#41); check `sandbox run status <id>` and worker logs. |

---

## Code map

| Module | Responsibility |
| --- | --- |
| `mailroom_sandbox/watch.py` | Terminal TUI, log buffer, lifecycle, `modal app logs -f` |
| `mailroom_sandbox/tui/web.py` | Browser SSE server, shared `compose_watch_state` |
| `mailroom_sandbox/tui/pretty_log.py` | Shared palette / frames (pinned to mailroom-ml upstream) |
| `mailroom_sandbox/tui/session.py` | SAND-033 lines for `sandbox run --watch` |
| `mailroom_sandbox/tui/board.py` | Beacon job board |
| `scripts/mailroom-tui` | Convenience launcher |
| `scripts/sand032/run_one.sh` | Writes `current`, `.times`, triggers eval |

Tests: `tests/test_watch.py`, `tests/test_watch_web.py`, `tests/test_mailroom_session.py`.
