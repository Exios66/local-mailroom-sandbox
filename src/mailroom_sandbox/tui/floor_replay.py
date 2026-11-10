"""Provider-agnostic replay of a recorded pipeline run.

The bundled floor sample ships a pre-scripted ``replay.jsonl``. This module
turns a *real* run directory from any serving path (Modal vLLM, OpenRouter,
Ollama, a remote host, …) into the same timeline contract:

* ``nodes.jsonl`` supplies node start/finish times and durations;
* ``items.jsonl`` supplies document outcomes;
* ``checkpoint.json`` supplies the terminal cursor/state;
* ``spec.lock.json`` supplies provider/model provenance.

No provider-specific field is interpreted. The original engine block is kept
verbatim so the viewer shows where the run was served, while the generated
``replay`` block marks the copy as a recorded replay. Timelines without
reliable timestamps fall back to document order and are labelled synthetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid
from typing import Any

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
MAX_ROWS = 200_000
MAX_TIMELINE_S = 7 * 24 * 3600
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REPLAY_MODES = {"recorded", "bundled", "replay"}


@dataclass(frozen=True)
class RecordedReplay:
    """A materialized recorded replay and the timeline the driver will play."""

    run_id: str
    path: Path
    events: list[tuple[float, dict[str, Any]]]
    meta: dict[str, Any]


def _slug(value: str) -> str:
    return _SAFE.sub("-", str(value)).strip("-")[:48] or "run"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path, *, limit: int = MAX_ROWS) -> tuple[list[dict[str, Any]], int]:
    """Read object rows from a bounded JSONL file; skip malformed/torn rows."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if len(rows) >= limit:
                    raise ValueError(f"{path}: more than {limit} records")
                try:
                    row = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(row, dict):
                    skipped += 1
                    continue
                rows.append(row)
    except OSError:
        return [], skipped
    return rows, skipped


def _parse_time(value: Any) -> float | None:
    """Epoch seconds from a number, numeric string, or ISO-8601 timestamp."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        # Accept epoch milliseconds from exporters that use the wrong unit.
        return number / 1000.0 if number > 100_000_000_000 else number
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        pass
    else:
        return _parse_time(number)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _engine_label(lock: dict[str, Any]) -> tuple[str | None, str | None]:
    engine = lock.get("engine") if isinstance(lock.get("engine"), dict) else {}
    kind = engine.get("kind")
    model = engine.get("model")
    return (str(kind) if kind else None, str(model) if model else None)


def _source_run_id(source: Path, lock: dict[str, Any]) -> str:
    value = lock.get("run_id") or source.name
    return str(value or "recorded")


def _event_copy(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a recorded row without its original wall-clock stamp.

    The replay driver assigns a new ``ts`` anchored to this playback, so a
    recorded epoch cannot make a replayed node look hours old.
    """
    return {key: value for key, value in record.items() if key != "ts"}


def _validate_source(source: Path) -> dict[str, Path]:
    if source.is_symlink():
        raise ValueError(f"recorded replay source is a symlink: {source}")
    if not source.is_dir():
        raise ValueError(f"recorded replay source is not a directory: {source}")
    names = ("items.jsonl", "nodes.jsonl", "checkpoint.json", "spec.lock.json",
             "prompt.lock.json", "dataset.jsonl")
    found: dict[str, Path] = {}
    total = 0
    for name in names:
        path = source / name
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError(f"recorded replay artifact is a symlink: {path}")
        if not path.is_file():
            raise ValueError(f"recorded replay artifact is not a file: {path}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"recorded replay artifact exceeds 100 MB: {path}")
        total += size
        found[name] = path
    if total > MAX_TOTAL_BYTES:
        raise ValueError("recorded replay artifacts exceed 250 MB")
    if "items.jsonl" not in found and "nodes.jsonl" not in found:
        raise ValueError(f"recorded replay source has neither items.jsonl nor nodes.jsonl: {source}")
    return found


def build_timeline(source: Path) -> tuple[list[tuple[float, dict[str, Any]]], dict[str, Any]]:
    """Convert a run directory into ``(at, replay-event)`` records.

    Node starts/finishes are paired by ``(doc, node, step)`` and placed on the
    source wall clock when available. Items without a timestamp follow the last
    completed node for their document, or the running cursor. A run with no
    usable timestamps gets a document-order timeline labelled synthetic.
    """
    source = Path(source)
    _validate_source(source)
    lock = _read_json(source / "spec.lock.json")
    checkpoint = _read_json(source / "checkpoint.json")
    nodes, node_skips = _read_jsonl(source / "nodes.jsonl")
    items, item_skips = _read_jsonl(source / "items.jsonl")
    warnings: list[str] = []
    if not nodes and not items:
        raise ValueError(f"recorded replay source has no usable node or item records: {source}")
    if node_skips:
        warnings.append(f"skipped {node_skips} malformed node rows")
    if item_skips:
        warnings.append(f"skipped {item_skips} malformed item rows")

    times = [
        stamp for row in [*nodes, *items]
        if (stamp := _parse_time(row.get("ts"))) is not None
    ]
    synthetic = not times
    t0 = min(times) if times else 0.0
    cursor = 0.0
    sequence = 0
    events: list[tuple[float, int, dict[str, Any]]] = []
    running: dict[tuple[str, str, Any], float] = {}
    last_done: dict[str, float] = {}

    for row in nodes:
        doc, node = str(row.get("doc") or ""), str(row.get("node") or "")
        status = str(row.get("status") or "")
        key = (doc, node, row.get("step"))
        stamp = _parse_time(row.get("ts"))
        if stamp is not None and not synthetic:
            at = max(0.0, stamp - t0)
        elif status == "running":
            at = cursor
        elif key in running:
            at = running[key] + max(0.0, float(row.get("ms") or 0)) / 1000.0
        else:
            at = cursor + 0.1
        if status == "running":
            running[key] = at
        else:
            at = max(at, running.pop(key, at))
            last_done[doc] = max(last_done.get(doc, at), at)
        cursor = max(cursor, at)
        events.append((at, sequence, {"node": _event_copy(row)}))
        sequence += 1

    item_at: dict[str, tuple[float, int, dict[str, Any]]] = {}
    for index, row in enumerate(items):
        item_id = str(row.get("item_id") or row.get("id") or f"item-{index}")
        doc = str(row.get("doc") or row.get("item_id") or "")
        stamp = _parse_time(row.get("ts"))
        if stamp is not None and not synthetic:
            at = max(0.0, stamp - t0)
        elif doc in last_done:
            at = last_done[doc]
        else:
            at = cursor + 0.5
        cursor = max(cursor, at)
        item_at[item_id] = (at, sequence, {"item": _event_copy(row)})
        sequence += 1

    total = checkpoint.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        total = len(item_at)
    rows: list[tuple[float, int, dict[str, Any]]] = [
        (0.0, -1, {"checkpoint": {"state": "running", "cursor": 0, "total": total}}),
        *events,
        *item_at.values(),
    ]
    end_at = cursor + 0.5
    state = checkpoint.get("state")
    cursor_value = checkpoint.get("cursor")
    final_cursor = cursor_value if isinstance(cursor_value, int) and not isinstance(cursor_value, bool) else len(item_at)
    final_total = total if total else len(item_at)
    if state not in {"done", "failed", "cancelled", "running"}:
        state = "done" if final_cursor >= final_total else "running"
    rows.append((end_at, sequence + 1,
                 {"checkpoint": {"state": state, "cursor": final_cursor, "total": final_total}}))
    rows.sort(key=lambda row: (row[0], row[1]))
    duration = rows[-1][0]
    if duration > MAX_TIMELINE_S:
        raise ValueError(f"recorded timeline exceeds 7 days ({duration:.0f}s); replay a shorter run")
    engine_kind, engine_model = _engine_label(lock)
    meta = {
        "source_run_id": _source_run_id(source, lock),
        "engine_kind": engine_kind,
        "engine_model": engine_model,
        "profile": lock.get("profile"),
        "node_records": len(nodes),
        "item_records": len(item_at),
        "duration_s": round(duration, 3),
        "synthetic_timing": synthetic,
        "incomplete": state == "running",
        "warnings": warnings,
    }
    return [(round(at, 4), event) for at, _, event in rows], meta


def is_replay_run(run: Path) -> bool:
    """True when ``run`` is app-owned replay content that may be safely reset."""
    try:
        lock = json.loads((Path(run) / "spec.lock.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Path(run).is_dir() and not any(Path(run).iterdir())
    except (OSError, ValueError):
        return False
    if not isinstance(lock, dict):
        return False
    replay = lock.get("replay")
    if isinstance(replay, dict) and replay.get("mode") in _REPLAY_MODES:
        return True
    engine = lock.get("engine")
    return isinstance(engine, dict) and engine.get("kind") == "replay"


def resolve_source(base: Path, value: str) -> Path:
    """Resolve an explicit path, or a run id under the base's live/history stores."""
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate.resolve()
    for parent in (Path(base) / "runtime" / "runs", Path(base) / "run-history"):
        run = parent / value
        if run.is_dir():
            return run.resolve()
    raise FileNotFoundError(f"recorded replay source not found: {value}")


def prepare_recorded_replay(
    base: Path,
    value: str | Path,
    *,
    run_id: str | None = None,
    speed: float = 10.0,
) -> RecordedReplay:
    """Materialize a provider-agnostic recorded replay under ``base``.

    The source is read-only. The destination is app-owned and labelled with a
    ``replay.mode: recorded`` block; an existing foreign run with the same id is
    never overwritten. ``speed`` is persisted for provenance and used by the
    caller's driver.
    """
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("replay speed must be a finite positive number")
    source = resolve_source(Path(base), str(value))
    events, meta = build_timeline(source)
    lock = _read_json(source / "spec.lock.json")
    source_id = _source_run_id(source, lock)
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    run_id = run_id or f"replay-recorded-{_slug(source_id)[:36]}-{digest}"
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("recorded replay run id must contain only letters, digits, dot, dash or underscore")
    runs = Path(base) / "runtime" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    target = runs / run_id
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not is_replay_run(target):
            raise FileExistsError(f"recorded replay refuses to replace foreign run {target}")
        shutil.rmtree(target)
    staging = runs / f".{run_id}.{uuid.uuid4().hex[:8]}"
    try:
        staging.mkdir()
        (staging / "items.jsonl").touch()
        (staging / "nodes.jsonl").touch()
        with open(staging / "replay.jsonl", "w", encoding="utf-8") as fh:
            for at, event in events:
                fh.write(json.dumps({"at": at, **event}, sort_keys=True) + "\n")
        first = next(event["checkpoint"] for at, event in events if "checkpoint" in event)
        (staging / "checkpoint.json").write_text(json.dumps(first), encoding="utf-8")
        out_lock = dict(lock) if isinstance(lock, dict) else {}
        out_lock["run_id"] = run_id
        out_lock.setdefault("engine", {"kind": "recorded", "model": None})
        out_lock["replay"] = {
            "mode": "recorded",
            "source_run_id": source_id,
            "engine_kind": meta.get("engine_kind"),
            "engine_model": meta.get("engine_model"),
            "synthetic_timing": bool(meta.get("synthetic_timing")),
            "duration_s": meta.get("duration_s"),
            "speed": speed,
            "incomplete": bool(meta.get("incomplete")),
        }
        (staging / "spec.lock.json").write_text(
            json.dumps(out_lock, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        for name in ("prompt.lock.json", "dataset.jsonl"):
            source_file = source / name
            if source_file.is_file() and not source_file.is_symlink():
                shutil.copy2(source_file, staging / name)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return RecordedReplay(run_id, target, events, meta)
