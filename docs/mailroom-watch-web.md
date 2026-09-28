# Mailroom watch — browser UI

Long Modal eval runs can use the **same SAND-032 panels** (in-tray, postage, dispatch log) in a browser instead of an alt-screen terminal tab.

```bash
# Attach to a run YAML (or bare `sandbox watch` when sand032/current exists)
sandbox watch --web --config config/runs/my-run.yaml

# Follow the active SAND-032 run file
sandbox watch --web --follow data/runtime/sand032/current

# Custom bind (localhost only recommended)
sandbox watch --web --host 127.0.0.1 --port 8765
NO_BROWSER=1 sandbox watch --web --config ...
```

Security: the server binds to `127.0.0.1` by default and has no authentication. Do not expose it on `0.0.0.0` without a reverse proxy and auth.

Implementation: `mailroom_sandbox.tui.web` (stdlib HTTP + SSE). Operator guide: Project store `docs/mailroom-themed-logging.md`.
