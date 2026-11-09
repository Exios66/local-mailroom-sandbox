"""`sandbox floor` — the pipeline-floor viewer as one resident app.

A background thread keeps ``floor_digest.json`` / ``floor_digest.js`` current by calling
``reports/dashboard/build_floor_digest.py`` in-process (read-only against the run store),
and a loopback ``http.server`` serves ``reports/dashboard/`` so ``floor.template.html``
can poll the digest. The thread rebuilds only when a run artifact's stat changed, so an
idle floor costs one cheap stat sweep per interval.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import quote

from mailroom_sandbox.paths import data_dir, repo_root

DEFAULT_HOST = "127.0.0.1"  # loopback only, like web/board
DEFAULT_PORT = 8769  # 8765 web, 8766 watch-live, 8767 board, 8768 board-demo — all claimed
DEFAULT_INTERVAL_S = 5.0
MIN_INTERVAL_S = 0.1
PAGE = "floor.template.html"
# files in a run dir that change as a run progresses (a dir counts as a run once items.jsonl exists)
RUN_ARTIFACTS = ("items.jsonl", "nodes.jsonl", "checkpoint.json", "spec.lock.json", "prompt.lock.json", "dataset.jsonl")


def dashboard_dir() -> Path:
    return repo_root() / "reports" / "dashboard"


def load_builder() -> ModuleType:
    """Import ``reports/dashboard/build_floor_digest.py`` (a script, not a package) once."""
    cached = sys.modules.get("build_floor_digest")
    if cached is not None:
        return cached
    path = dashboard_dir() / "build_floor_digest.py"
    if not path.is_file():
        raise FileNotFoundError(f"digest builder not found: {path}")
    spec = importlib.util.spec_from_file_location("build_floor_digest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_floor_digest"] = module  # dataclass/typing helpers expect it registered
    spec.loader.exec_module(module)
    return module


def build(base: Path, out: Path, graph_path: Path | None = None) -> tuple[dict, Path, Path]:
    """Rebuild the digest from ``base`` into ``out``; returns ``(digest, json_path, js_path)``."""
    return load_builder().build(base, out, graph_path)


def scan_signature(base: Path) -> tuple:
    """Cheap change detector: (path, mtime_ns, size) of every run artifact plus the run dirs themselves.

    No file is opened. A new or removed run dir changes the tuple through its parent listing,
    and a growing nodes/items file changes it through mtime and size.
    """
    sig: list[tuple[str, int, int]] = []
    for parent in (base / "run-history", base / "runtime" / "runs"):
        try:
            children = sorted(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            continue
        for run in children:
            sig.append((str(run), 0, 0))
            for name in RUN_ARTIFACTS:
                try:
                    st = (run / name).stat()
                except OSError:
                    continue
                sig.append((str(run / name), st.st_mtime_ns, st.st_size))
    return tuple(sig)


class DigestRefresher:
    """Rebuild the digest into ``out`` whenever ``scan_signature`` changes; otherwise do nothing."""

    def __init__(self, base: Path, out: Path, *, graph_path: Path | None = None) -> None:
        self.base, self.out, self.graph_path = Path(base), Path(out), graph_path
        self._sig: tuple | None = None
        self.builds = 0
        self.last_error: str | None = None

    def refresh(self) -> bool:
        """Rebuild if anything changed since the last good build; True when a build ran and succeeded.

        A failed build keeps the old signature (so the next tick retries) and records
        ``last_error``; the error is raised only for the very first build, which the caller treats as fatal.
        """
        sig = scan_signature(self.base)
        if sig == self._sig:
            return False
        try:
            build(self.base, self.out, self.graph_path)
        except Exception as exc:  # noqa: BLE001 — a transient read/replace failure must not kill the loop
            if self._sig is None and self.builds == 0:
                raise
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        self._sig, self.builds, self.last_error = sig, self.builds + 1, None
        return True

    def run(self, stop: threading.Event, interval: float) -> None:
        """Thread body: refresh every ``interval`` seconds until ``stop`` is set."""
        last_reported = None
        while not stop.wait(max(interval, MIN_INTERVAL_S)):
            self.refresh()
            if self.last_error and self.last_error != last_reported:
                print(f"sandbox floor: digest rebuild failed (will retry): {self.last_error}", file=sys.stderr, flush=True)
            last_reported = self.last_error


class _FloorHandler(SimpleHTTPRequestHandler):
    """Static handler for the dashboard dir: quiet, and never cached (the digest changes under it)."""

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(directory: Path, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """A loopback server for ``directory`` (port 0 = ephemeral); bound, not yet serving."""
    return ThreadingHTTPServer((DEFAULT_HOST, port), partial(_FloorHandler, directory=str(directory)))


def floor_url(port: int, run: str | None = None) -> str:
    """The viewer URL, with ``?run=<id>`` to deep-select a run."""
    url = f"http://{DEFAULT_HOST}:{port}/{PAGE}"
    return url + (f"?run={quote(run, safe='')}" if run else "")


def resolve_base(arg: str | None) -> Path:
    """``--base``, else ``$MAILROOM_BASE_DIR``, else the repo's ``./data`` (same order as the builder)."""
    return Path(arg).expanduser() if arg else data_dir()


def serve_floor(
    *,
    base: Path,
    port: int = DEFAULT_PORT,
    interval: float = DEFAULT_INTERVAL_S,
    run: str | None = None,
    out: Path | None = None,
) -> int:
    """Build the digest, serve the dashboard on loopback, and rebuild in the background until interrupted.

    ``out`` is the served and written directory (default ``reports/dashboard``). The first build
    is synchronous so the page never loads a stale digest; if it fails the app exits with the
    builder's exit code instead of serving old data. Returns 0 after Ctrl+C.
    """
    builder = load_builder()
    out = Path(out) if out is not None else dashboard_dir()
    refresher = DigestRefresher(base, out)
    try:
        refresher.refresh()
    except builder.DigestError as exc:
        print(f"sandbox floor: error: {exc}", file=sys.stderr, flush=True)
        return exc.code
    httpd = make_server(out, port)
    stop = threading.Event()
    worker = threading.Thread(target=refresher.run, args=(stop, interval), name="floor-digest", daemon=True)
    worker.start()
    print(floor_url(httpd.server_address[1], run), flush=True)
    print(f"  run store: {base} · rebuild when it changes (checked every {max(interval, MIN_INTERVAL_S):g}s) · Ctrl+C to stop",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)
    return 0


__all__ = ["DEFAULT_PORT", "DigestRefresher", "build", "floor_url", "make_server", "resolve_base", "scan_signature", "serve_floor"]
