"""`sandbox floor` — the pipeline-floor viewer as one resident app.

A background thread keeps private ``floor_digest.json`` / ``floor_digest.js`` files current
by calling ``reports/dashboard/build_floor_digest.py`` in-process (read-only against the run store).
A loopback ``http.server`` serves dashboard assets and that instance's private digest.
The thread rebuilds only when a run artifact's stat changed, so an
idle floor costs one cheap stat sweep per interval.
"""

from __future__ import annotations

import hashlib
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
from urllib.parse import parse_qs, quote, urlsplit

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.read_ranges import SHINGLE, ShingleIndex, match_ranges, text_hash
from mailroom_sandbox.paths import data_dir, repo_root
from mailroom_sandbox.tui.floor_replay import is_replay_run as _is_replay_run
from mailroom_sandbox.tui.floor_replay import prepare_recorded_replay
# viewer port + its claim note live in ports.py so parser help never imports this
from mailroom_sandbox.ports import DEFAULT_VIEWER_PORT as DEFAULT_PORT

DEFAULT_HOST = "127.0.0.1"  # loopback only, like web/board
_ALLOWED_HOST_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})  # Host header names (DNS-rebinding guard)
DEFAULT_INTERVAL_S = 5.0
MIN_INTERVAL_S = 0.1
# A run whose checkpoint says running is rebuilt at least this often even when no artifact
# changed, so the builder's idle-time "stalled" verdict can flip (a dead run writes nothing).
STALL_RECHECK_S = 60.0
PAGE = "floor.template.html"
DOC_ENDPOINT = "/api/floor/doc"
REPLAY_RUN_ID = "replay-mailroom-sample"
REPLAY_DIR = ("data", "fixtures", "floor", "replay")
# files in a run dir that change as a run progresses (a dir counts as a run once items.jsonl exists)
RUN_ARTIFACTS = ("items.jsonl", "nodes.jsonl", "checkpoint.json", "spec.lock.json", "prompt.lock.json", "dataset.jsonl", "reads.jsonl")


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
        self._live_runs = False  # the last digest had a run whose checkpoint says running
        self._built_at = 0.0

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
        recheck = self._live_runs and time.monotonic() - self._built_at >= STALL_RECHECK_S
        if sig == self._sig and not recheck:
            return False
        try:
            result = build(self.base, self.out, self.graph_path)
        except Exception as exc:  # noqa: BLE001 — a transient read/replace failure must not kill the loop
            if self._sig is None and self.builds == 0:
                raise
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        self._sig, self.builds, self.last_error = sig, self.builds + 1, None
        self._built_at = time.monotonic()
        digest = result[0] if isinstance(result, tuple) and result and isinstance(result[0], dict) else {}
        self._live_runs = any(r.get("checkpoint_state") == "running" for r in digest.get("runs") or [])
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


# ── document inspector endpoint ─────────────────────────────────────────────────


def _normalise_text(text: str) -> str:
    """The trivial normalisation behind ``rewritten``: LF newlines and no outer whitespace."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _index_lists(run_dir: Path, doc: str) -> bool:
    """True when ``doc_texts/index.jsonl`` lists ``doc``."""
    index = run_dir / "doc_texts" / "index.jsonl"
    return any(row.get("doc") == doc for row in load_builder().read_jsonl(index))


def _working_text(run_dir: Path, doc: str) -> str | None:
    """The recorded working text for a ``doc`` the index lists, or None.

    The file name is recomputed (``sha1(doc)[:16].txt``), never taken from the request or
    from an index line, so no user-supplied string reaches a path. A symlink is not followed.
    """
    path = run_dir / "doc_texts" / (hashlib.sha1(doc.encode("utf-8"), usedforsecurity=False).hexdigest()[:16] + ".txt")
    if path.is_symlink() or not path.is_file():
        return None
    try:  # bytes, not read_text: universal newlines would turn CRLF and lone CR into LF and shift every offset
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _last_row(path: Path, matches: Callable[[dict], bool]) -> dict | None:
    """The last JSONL object in ``path`` for which ``matches`` holds (a resumed run re-appends)."""
    found = None
    for row in load_builder().read_jsonl(path):
        if matches(row):
            found = row
    return found


def _verbatim_overlap(original: str, working: str) -> float | None:
    """Fraction of the working text's characters that appear verbatim in the original, or None."""
    if not working:
        return None
    result = match_ranges(ShingleIndex(original), working)
    if result["skipped"]:
        return None
    matched = result["matched_chars"]
    if matched < len(working) and len(working) < SHINGLE:
        # Below the matcher's shingle floor a short working text cannot be placed by the bulk
        # matcher and stays under the unanchored threshold; its blank-line pieces still count
        # toward the overlap when they occur verbatim in the original ("Rent" over "Rent" is 1.0).
        counted = 0
        for piece in working.split("\n"):
            piece = piece.strip()
            if not piece:
                continue
            if piece in original:
                counted += len(piece)
                continue
            # A partial piece keeps its word-level verbatim hits instead of falling to zero.
            counted += sum(len(word) for word in piece.split() if word in original)
        matched = max(matched, counted)
    return round(min(1.0, matched / len(working)), 4)


def doc_view(runs_root: Path, run: str, doc: str) -> dict | None:
    """What the viewer's DOCUMENT panel shows for one document, or None when run or doc is unknown.

    ``run`` must be a name the digest builder's run scan produced under ``runs_root``; ``doc``
    is matched against the dataset row, the stored item and the working-text index, never
    joined to a path. ``rewritten`` compares the working text with the row's ``doc_text`` after
    ``_normalise_text``; ``overlap`` is the verbatim coverage of the working text in that
    original. Both stay false and null when either text is missing.
    """
    builder = load_builder()
    run_dir = dict(builder.named_runs(builder.discover_runs(Path(runs_root)))).get(run)
    if run_dir is None:
        return None
    row = _last_row(run_dir / "dataset.jsonl", lambda r: str(r.get("id") or r.get("filename")) == doc)
    item = _last_row(run_dir / "items.jsonl", lambda r: str(r.get("item_id", r.get("id"))) == doc)
    listed = _index_lists(run_dir, doc)
    if row is None and item is None and not listed:
        return None
    working = _working_text(run_dir, doc) if listed else None
    row, item = row or {}, item or {}
    original = row.get("doc_text") if isinstance(row.get("doc_text"), str) else None
    both = working is not None and original is not None
    gt = row.get("expected_doc_class") or item.get("expected_doc_class") or item.get("expected")
    served_hash = None
    if working is not None:
        # The tag the read records carry (read_ranges.text_hash) over the exact bytes served:
        # the viewer compares it with the digest's tag and refetches/withholds when the stored
        # text was rewritten after the digest (or the panel's cache) was built.
        try:
            served_hash = text_hash(working)
        except Exception:  # noqa: BLE001 - e.g. a lone surrogate; the viewer then keeps the length check
            served_hash = None
    return {
        "working": working,
        "original": original,
        "expected": builder._expected_fields(row),
        "extracted": builder._stored_extraction(item),
        "class": {"gt": str(gt) if gt else None, "pred": builder._pred_class(item)},
        "rewritten": bool(both and _normalise_text(working) != _normalise_text(original)),
        "overlap": _verbatim_overlap(original, working) if both else None,
        "text_hash": served_hash,
    }


class _FloorHandler(SimpleHTTPRequestHandler):
    """Static handler for the dashboard dir: quiet, and never cached (the digest changes under it)."""

    def __init__(self, *args: Any, digest_directory: Path | None = None,
                 runs_root: Path | None = None, **kwargs: Any) -> None:
        """Serve dashboard assets with optional process-private digest files and a run store."""
        self.digest_directory = digest_directory
        self.runs_root = runs_root
        super().__init__(*args, **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        """Write one JSON response (never cached; ``end_headers`` adds the cache directive)."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_allowed(self) -> bool:
        """True when the Host header names this loopback server (anti DNS rebinding).

        Only ``127.0.0.1``, ``localhost`` and ``[::1]``, bare or with this server's own port,
        pass. A page served from another hostname that resolves to 127.0.0.1 sends that
        hostname, so it cannot read the digest or a document's text.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):  # [::1] or [::1]:port
            name, _, rest = host[1:].partition("]")
            name, port = f"[{name}]", rest[1:] if rest.startswith(":") else rest
        else:
            name, _, port = host.partition(":")
        if name not in _ALLOWED_HOST_NAMES:
            return False
        return port in ("", str(self.server.server_address[1]))

    def _refuse_foreign_host(self, *, body: bool) -> bool:
        """Answer 403 and return True when the Host header is not this server's loopback name."""
        if self._host_allowed():
            return False
        if body:
            self._send_json(403, {"error": "forbidden host"})
        else:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
        return True

    def do_HEAD(self) -> None:  # noqa: N802 — http.server dispatch name
        """Static HEAD, behind the same Host check as GET."""
        if self._refuse_foreign_host(body=False):
            return
        super().do_HEAD()

    def do_GET(self) -> None:  # noqa: N802 — http.server dispatch name
        """Answer ``GET /api/floor/doc`` itself; every other path is a static file.

        Every request, static files and the digest included, needs a loopback Host header.
        """
        if self._refuse_foreign_host(body=True):
            return
        parts = urlsplit(self.path)
        if parts.path != DOC_ENDPOINT:
            super().do_GET()
            return
        query = parse_qs(parts.query, keep_blank_values=True)
        run, doc = query.get("run", [None])[0], query.get("doc", [None])[0]
        if run is None or doc is None:
            self._send_json(400, {"error": "run and doc are required"})
            return
        view = None
        if self.runs_root is not None:
            try:
                view = doc_view(self.runs_root, run, doc)
            except (OSError, ValueError):
                view = None
        if view is None:
            self._send_json(404, {"error": "unknown run or document"})
            return
        self._send_json(200, view)

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


def make_server(directory: Path, port: int = DEFAULT_PORT, *, digest_dir: Path | None = None,
                runs_root: Path | None = None) -> ThreadingHTTPServer:
    """Bind a loopback server for ``directory`` (port 0 = ephemeral), without serving yet.

    ``runs_root`` is the run store (the builder's ``--base``) behind ``GET /api/floor/doc``;
    without it that endpoint answers 404. Socket binding errors propagate.
    """
    return ThreadingHTTPServer(
        (DEFAULT_HOST, port),
        partial(_FloorHandler, directory=str(directory.resolve()), digest_directory=digest_dir,
                runs_root=runs_root),
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
    """Replay a selected run into a materialized base, one scheduled record at a time.

    The trace is a timeline in simulated seconds (`at`), scaled by ``speed``:
    docs arrive staggered, nodes are in flight for their recorded ``ms`` while
    later docs proceed, and held docs park open — the store therefore looks like
    a real live run. ``run_id`` selects the bundled sample or a recorded replay.
    """

    def __init__(self, base: Path, *, run_id: str = REPLAY_RUN_ID, speed: float = 1.0) -> None:
        """Load a replay run and prepare its store; ``speed`` scales the schedule.

        Nonpositive speed or a malformed trace raises ValueError; file errors propagate.
        """
        if speed <= 0:
            raise ValueError("replay speed must be positive")
        self.base = Path(base)
        self.run_id = run_id
        self.speed = float(speed)
        self.run_dir = self.base / "runtime" / "runs" / run_id
        self.store = RunStore(self.run_dir)
        self.events = _load_trace(self.run_dir / "replay.jsonl")
        self.pos = 0

    @property
    def documents(self) -> int:
        """Number of documents the trace replays (one scripted item each)."""
        return sum(1 for _, event in self.events if "item" in event)

    def step(self, refresh: Callable[[], Any] | None = None) -> bool:
        """Apply the next record and return whether more records remain.

        Call ``refresh`` after an item, checkpoint, or non-running node, if given.
        Store and callback errors propagate.
        """
        if self.pos >= len(self.events):
            return False
        at, event = self.events[self.pos]
        self.pos += 1
        if "node" in event:
            record = dict(event["node"])
            # Wall clock at emission, not simulated event time: a 10x replay
            # must not stamp nodes minutes in the future.
            record["ts"] = time.time()
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
        """Play the timeline until it ends or ``stop`` is set.

        Each target is ``at / speed`` wall seconds after playback starts. A
        supplied refresh callback is eligible at most once per 0.5 seconds and
        is called only for item, checkpoint, or non-running node records. Store
        and callback errors propagate.
        """
        start = time.monotonic()
        last_refresh = time.monotonic()
        while not stop.is_set():
            if self.pos >= len(self.events):
                return
            at, _ = self.events[self.pos]
            if stop.wait(max(0.0, at / self.speed - (time.monotonic() - start))):
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
    ``replay_run`` instead imports a recorded run from any provider; ``replay_speed``
    scales the schedule (default 1x for the bundled sample, 10x for a recorded run).
    Selecting both replay modes returns 2; replay preparation failures return 1.
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
        httpd = make_server(out, port, digest_dir=digest_dir, runs_root=base)
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
            for warning in recorded_meta.get("warnings") or []:
                print(f"sandbox floor: recorded replay warning: {warning}", file=sys.stderr, flush=True)
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
