"""`sandbox floor` — the pipeline-floor viewer as one resident app.

A background thread keeps private ``floor_digest.json`` / ``floor_digest.js`` files current
by calling ``reports/dashboard/build_floor_digest.py`` in-process (read-only against the run store).
A loopback ``http.server`` serves dashboard assets and that instance's private digest.
The thread rebuilds only when a run artifact's stat changed, so an
idle floor costs one cheap stat sweep per interval.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any, Callable
from urllib.parse import quote

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.paths import data_dir, repo_root
from mailroom_sandbox.tui.floor_replay import is_replay_run as _is_replay_run
from mailroom_sandbox.tui.floor_replay import prepare_recorded_replay
# viewer port + its claim note live in ports.py so parser help never imports this
from mailroom_sandbox.ports import DEFAULT_VIEWER_PORT as DEFAULT_PORT

DEFAULT_HOST = "127.0.0.1"  # loopback only, like web/board
DEFAULT_INTERVAL_S = 5.0
MIN_INTERVAL_S = 0.1
PAGE = "floor.template.html"
REPLAY_RUN_ID = "replay-mailroom-sample"
REPLAY_DIR = ("data", "fixtures", "floor", "replay")
# files in a run dir that change as a run progresses (a dir counts as a run once items.jsonl exists)
RUN_ARTIFACTS = ("items.jsonl", "nodes.jsonl", "checkpoint.json", "spec.lock.json", "prompt.lock.json", "dataset.jsonl")


def dashboard_dir() -> Path:
    """Return the dashboard directory under the resolved repository root."""
    return repo_root() / "reports" / "dashboard"


def load_builder() -> ModuleType:
    """Load and cache the dashboard builder script.

    Raise FileNotFoundError if the script is missing and not cached; import errors propagate.
    """
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
    """Rebuild the digest from ``base`` into ``out`` and return it with both output paths.

    ``graph_path`` overrides the builder's environment and default graph selection.
    Builder loading and digest errors propagate.
    """
    return load_builder().build(base, out, graph_path)


def scan_signature(base: Path) -> tuple:
    """Cheap change detector: (path, mtime_ns, size) of every run artifact plus the run dirs themselves.

    No file is opened. A new or removed run dir changes the tuple through its parent listing,
    and a growing nodes/items file changes it through mtime and size. Unreadable parent
    directories and artifacts that cannot be statted are omitted.
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
        """Configure the run store, output directory, and optional graph override."""
        self.base, self.out, self.graph_path = Path(base), Path(out), graph_path
        self._sig: tuple | None = None
        self._lock = threading.Lock()  # the replay thread and the sweep thread may refresh concurrently
        self.builds = 0
        self.last_error: str | None = None

    def refresh(self) -> bool:
        """Rebuild if anything changed since the last good build; True when a build ran and succeeded.

        A build exception before the first success propagates. After a successful build,
        failures keep the old signature, record ``last_error``, and return False so the
        next refresh retries. An unchanged signature also returns False. Serialized:
        the sweep thread and the replay driver may call this concurrently.
        """
        with self._lock:
            return self._refresh()

    def _refresh(self) -> bool:
        """One refresh under ``_lock``; see :meth:`refresh` for semantics."""
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
        """Refresh until ``stop`` is set, waiting ``interval`` seconds between checks.

        The wait is at least 0.1 seconds. A build exception before the first success
        propagates from ``refresh``.
        """
        last_reported = None
        while not stop.wait(max(interval, MIN_INTERVAL_S)):
            self.refresh()
            if self.last_error and self.last_error != last_reported:
                print(f"sandbox floor: digest rebuild failed (will retry): {self.last_error}", file=sys.stderr, flush=True)
            last_reported = self.last_error


class _FloorHandler(SimpleHTTPRequestHandler):
    """Static handler for the dashboard dir: quiet, and never cached (the digest changes under it)."""

    def __init__(self, *args: Any, digest_directory: Path | None = None, **kwargs: Any) -> None:
        """Serve dashboard assets with optional process-private digest files."""
        self.digest_directory = digest_directory
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        """Resolve the two root digest URLs in this server's private directory."""
        resolved = Path(super().translate_path(path))
        if (self.digest_directory is not None and resolved.parent == Path(self.directory)
                and resolved.name in {"floor_digest.json", "floor_digest.js"}):
            return str(self.digest_directory / resolved.name)
        return str(resolved)

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress HTTP request logging."""
        return

    def end_headers(self) -> None:
        """Send a no-store cache directive before completing the response headers."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def make_server(directory: Path, port: int = DEFAULT_PORT, *, digest_dir: Path | None = None) -> ThreadingHTTPServer:
    """Bind a loopback server for ``directory`` (port 0 = ephemeral), without serving yet.

    Socket binding errors propagate.
    """
    return ThreadingHTTPServer(
        (DEFAULT_HOST, port),
        partial(_FloorHandler, directory=str(directory.resolve()), digest_directory=digest_dir),
    )


def floor_url(port: int, run: str | None = None) -> str:
    """The viewer URL, with ``?run=<id>`` to deep-select a run."""
    url = f"http://{DEFAULT_HOST}:{port}/{PAGE}"
    return url + (f"?run={quote(run, safe='')}" if run else "")


def resolve_base(arg: str | None) -> Path:
    """``--base``, else ``$MAILROOM_BASE_DIR``, else the repo's ``./data`` (same order as the builder)."""
    return Path(arg).expanduser() if arg else data_dir()


def replay_base() -> Path:
    """The committed replay base: a run store with a pinned sample and a scripted trace."""
    return repo_root().joinpath(*REPLAY_DIR)


def replay_store(base: Path) -> Path:
    """Reset the replay run inside ``base`` from the bundled fixture and return the base.

    Only ``runtime/runs/<REPLAY_RUN_ID>`` is written: the previous attempt is removed,
    the fixture's dataset/trace/lock copied in, and empty ``items.jsonl``/``nodes.jsonl``
    touched so the builder discovers the run before the first tick. Historical runs are
    left untouched (and interrupted replays read as a killed replay, like any run).
    A missing fixture raises FileNotFoundError; copy and filesystem errors propagate.
    """
    run = Path(base) / "runtime" / "runs" / REPLAY_RUN_ID
    if run.is_symlink() or (run.exists() and not _is_replay_run(run)):
        # --replay owns ONLY these fixture-driven runs: never a real run the
        # operator launched under a coincidental id
        raise FileExistsError(
            f"floor --replay refuses to reset {run}: its spec.lock.json is not the replay "
            "fixture. Move or rename that run, then retry."
        )
    if run.exists():
        shutil.rmtree(run)  # reset the app-owned replay run; history stays
    shutil.copytree(replay_base() / "runtime", Path(base) / "runtime", dirs_exist_ok=True)
    if not (run / "dataset.jsonl").is_file():
        raise FileNotFoundError(f"floor replay dataset missing: {run / 'dataset.jsonl'}")
    for name in ("items.jsonl", "nodes.jsonl"):
        (run / name).touch(exist_ok=True)
    return Path(base)


def _load_trace(path: Path) -> list[tuple[float, dict]]:
    """Read ``replay.jsonl`` and return its records ordered by the ``at`` timeline.

    Each line is an object with a non-negative numeric ``at`` (simulated seconds) and
    exactly one of ``node``, ``item`` or ``checkpoint``. Malformed traces raise
    ValueError naming the line.
    """
    events: list[tuple[float, dict]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            at = event.get("at") if isinstance(event, dict) else None
            if not isinstance(at, (int, float)) or isinstance(at, bool) or at < 0:
                raise ValueError(f"{path}:{lineno}: expected a record with a non-negative numeric 'at'")
            if sum(kind in event for kind in ("node", "item", "checkpoint")) != 1:
                raise ValueError(f"{path}:{lineno}: expected exactly one of node/item/checkpoint")
            events.append((float(at), event))
    if not events:
        raise ValueError(f"{path}: empty timeline")
    return sorted(events, key=lambda pair: pair[0])


class ReplayDriver:
    """Replay the bundled scripted run into a materialized base, one scheduled record at a time.

    The trace is a wall-clock timeline in simulated seconds (`at`), played 1:1: docs
    arrive staggered, nodes are in flight for their recorded ``ms`` while later docs
    proceed, and held docs park open — the store therefore looks like a real live run.
    """

    def __init__(self, base: Path, *, run_id: str = REPLAY_RUN_ID, speed: float = 1.0) -> None:
        """Load a replay run and prepare its store; ``speed`` scales the timeline."""
        if speed <= 0:
            raise ValueError("replay speed must be positive")
        self.base = Path(base)
        self.run_id = run_id
        self.speed = float(speed)
        self.run_dir = self.base / "runtime" / "runs" / run_id
        self.store = RunStore(self.run_dir)
        self.events = _load_trace(self.run_dir / "replay.jsonl")
        self.pos = 0
        self._epoch: float | None = None  # wall clock at simulated t=0, set by the first record

    @property
    def documents(self) -> int:
        """Number of documents the trace replays (one scripted item each)."""
        return sum(1 for _, event in self.events if "item" in event)

    def _stamp(self, at: float) -> dict[str, Any]:
        """Anchor the 0 point once, and return the record with its simulated epoch ``ts``."""
        if self._epoch is None:
            self._epoch = time.time() - at
        return {"ts": self._epoch + at}

    def step(self, refresh: Callable[[], Any] | None = None) -> bool:
        """Apply the next scheduled record, call ``refresh`` if given, and return False at the end."""
        if self.pos >= len(self.events):
            return False
        at, event = self.events[self.pos]
        self.pos += 1
        if "node" in event:
            record = dict(event["node"])
            # Every replayed node is stamped in this playback, including the
            # finish row; source epochs must not leak into the viewer.
            record["ts"] = self._stamp(at)["ts"]
            self.store.append_node(record)
        elif "item" in event:
            self.store.append_item(event["item"])
        else:
            checkpoint = event["checkpoint"]
            self.store.write_checkpoint(
                state=checkpoint["state"], cursor=checkpoint["cursor"], total=checkpoint["total"]
            )
        if refresh is not None and ("node" not in event or event["node"].get("status") != "running"):
            refresh()
        return self.pos < len(self.events)

    def play(self, stop: threading.Event, refresh: Callable[[], Any] | None = None) -> None:
        """Play the timeline in real time until it ends or ``stop`` is set.

        Falls behind never: the wait to the next record is `at - elapsed`; a digest
        refresh happens per finished node/item/checkpoint record, at most ~2 per second
        for the busy node phase (the builder only needs one sweep per wall second).
        """
        start = time.monotonic()
        last_refresh = time.monotonic()
        while not stop.is_set():
            if self.pos >= len(self.events):
                return
            at, _ = self.events[self.pos]
            if stop.wait(max(0.0, at - (time.monotonic() - start)) / self.speed):
                return
            done_refresh = None
            if refresh is not None:
                now = time.monotonic()
                if now - last_refresh >= 0.5:
                    done_refresh, last_refresh = refresh, now
            if not self.step(done_refresh):
                return


def has_runs(base: Path) -> bool:
    """True when ``base`` has a run directory with ``items.jsonl`` (the builder's discovery rule)."""
    for parent in (base / "runtime" / "runs", base / "run-history"):
        try:
            if any((p / "items.jsonl").is_file() for p in parent.iterdir() if p.is_dir()):
                return True
        except OSError:
            continue
    return False


def serve_floor(
    *,
    base: Path,
    port: int = DEFAULT_PORT,
    interval: float = DEFAULT_INTERVAL_S,
    run: str | None = None,
    out: Path | None = None,
    replay: bool = False,
    replay_run: str | None = None,
    replay_speed: float | None = None,
) -> int:
    """Build the digest, serve the dashboard on loopback, and rebuild in the background until interrupted.

    ``out`` is the dashboard asset directory (default ``reports/dashboard``); digests
    are built in temporary storage private to this call and removed on exit. ``run``
    identifies a run to preselect via the printed URL. ``port=0`` chooses an ephemeral port, and checks
    run at least 0.1 seconds apart. With ``replay`` (or when the base has no runs and no run is
    named), the bundled pinned sample is replayed INTO the base as an app-owned run alongside the
    base's historical runs — both are selectable in the viewer; only that labeled run dir is reset.
    The first build is synchronous: a DigestError returns its code before the server binds, a build
    surprise or a port that cannot be bound returns 1 with one line. Later build exceptions
    are recorded and retried. Returns 0 after Ctrl+C.
    """
    with TemporaryDirectory(prefix="mailroom-floor-") as digest_dir:
        return _serve_floor(base=base, port=port, interval=interval, run=run, out=out,
                            replay=replay, replay_run=replay_run, replay_speed=replay_speed,
                            digest_dir=Path(digest_dir))


def _serve_floor(
    *, base: Path, port: int, interval: float, run: str | None, out: Path | None,
    replay: bool, digest_dir: Path, replay_run: str | None = None,
    replay_speed: float | None = None,
) -> int:
    """Run one viewer using its caller-owned private digest directory."""
    try:
        builder = load_builder()
    except (OSError, ImportError) as exc:
        print(f"sandbox floor: error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    out = Path(out) if out is not None else dashboard_dir()
    driver: ReplayDriver | None = None
    recorded_meta: dict[str, Any] | None = None
    if replay_run is not None and replay:
        print("sandbox floor: choose --replay or --replay-run, not both", file=sys.stderr, flush=True)
        return 2
    if replay_run is not None:
        speed = 10.0 if replay_speed is None else replay_speed
        try:
            recorded = prepare_recorded_replay(base, replay_run, speed=speed)
            driver = ReplayDriver(base, run_id=recorded.run_id, speed=speed)
            recorded_meta = {**recorded.meta, "path": str(recorded.path)}
        except Exception as exc:  # noqa: BLE001 — bad source/path: one line, no traceback
            print(f"sandbox floor: recorded replay unavailable: {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)
            return 1
        run = run or recorded.run_id
    elif not replay and run is None and replay_base().is_dir() and not has_runs(base):
        print(f"sandbox floor: no runs under {base}; replaying the bundled sample", file=sys.stderr, flush=True)
        replay = True
    if replay and driver is None:
        try:
            base = replay_store(base)
            driver = ReplayDriver(base, speed=1.0 if replay_speed is None else replay_speed)
        except Exception as exc:  # noqa: BLE001 — missing fixture or copy error: one line, no traceback
            print(f"sandbox floor: replay unavailable: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return 1
        run = run or REPLAY_RUN_ID
    refresher = DigestRefresher(base, digest_dir)
    try:
        refresher.refresh()
    except builder.DigestError as exc:
        print(f"sandbox floor: error: {exc}", file=sys.stderr, flush=True)
        return exc.code
    except Exception as exc:  # noqa: BLE001 — OSError on an odd --base, or any builder surprise: clean message, no traceback
        print(f"sandbox floor: error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    try:
        httpd = make_server(out, port, digest_dir=digest_dir)
    except OSError as exc:  # port already in use / not bindable
        print(f"sandbox floor: cannot listen on {DEFAULT_HOST}:{port}: {exc}", file=sys.stderr, flush=True)
        return 1
    stop = threading.Event()
    worker = threading.Thread(target=refresher.run, args=(stop, interval), name="floor-digest", daemon=True)
    worker.start()
    replay_worker = None
    if driver is not None:
        replay_worker = threading.Thread(target=driver.play, args=(stop, refresher.refresh), name="floor-replay", daemon=True)
        replay_worker.start()
    print(floor_url(httpd.server_address[1], run), flush=True)
    if driver is not None:
        if recorded_meta is not None:
            engine = recorded_meta.get("engine_kind") or "recorded"
            model = recorded_meta.get("engine_model")
            label = f"{engine}/{model}" if model else engine
            extra = " · synthetic timing" if recorded_meta.get("synthetic_timing") else ""
            incomplete = " · source run was not terminal" if recorded_meta.get("incomplete") else ""
            print(f"  recorded replay: {label} · {driver.documents} documents over a "
                  f"{recorded_meta.get('duration_s', driver.events[-1][0]):.1f}s timeline at {driver.speed:g}x"
                  f" -> {recorded_meta['path']}{extra}{incomplete} · not live results", flush=True)
        else:
            print(f"  replay: {driver.documents} simulated documents over a {driver.events[-1][0]:.1f}s wall-clock"
                  f" timeline -> {base / 'runtime' / 'runs' / REPLAY_RUN_ID}"
                  f" (reset on each --replay; history untouched) · not live results", flush=True)
    else:
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
        if replay_worker is not None:
            replay_worker.join(timeout=5)
    return 0


__all__ = ["DEFAULT_PORT", "DigestRefresher", "ReplayDriver", "build", "floor_url", "make_server",
           "replay_base", "replay_store", "resolve_base", "scan_signature", "serve_floor"]
