# Mailroom watch — browser UI

Short reference for the **browser** surface. Full operator guide (terminal + web +
Modal log tail + SAND-032 paths): **[mailroom-themed-logging.md](mailroom-themed-logging.md)**.

## Commands

```bash
# Attach to a run YAML (or bare `sandbox watch --web` when sand032/current exists)
sandbox watch --web --config config/runs/my-run.yaml

# Follow the active SAND-032 run file
sandbox watch --web --follow data/runtime/sand032/current

# Launcher equivalent
scripts/mailroom-tui web [--config …]

# Custom bind (localhost only recommended)
sandbox watch --web --host 127.0.0.1 --port 8765
NO_BROWSER=1 sandbox watch --web --config …
# or: sandbox watch --web --no-browser …

# Synthetic UI (no Modal spend)
sandbox dev
sandbox watch --web --demo
```

Default URL: **http://127.0.0.1:8765/** — live JSON via **SSE** at `/api/stream`; snapshot at `/api/state`.

Stop the server with **Ctrl+C** in the terminal that launched it (does not stop the eval).

## Security

The server binds to `127.0.0.1` by default and has **no authentication**. Do not expose it on `0.0.0.0` without a reverse proxy and auth.

## Implementation

`mailroom_sandbox.tui.web` (stdlib HTTP + SSE), sharing render state with `mailroom_sandbox.watch.compose_watch_state`.
