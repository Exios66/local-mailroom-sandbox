"""Per-stage queue-depth limits for the pipeline's filesystem bins.

The vendored pipeline uses directories as queues: an upload lands in ``inbox/``, the
watcher queues it in memory for a worker slot (``dispatch``), a worker claims it into
``processing/<worker>/``, and a document a person must look at waits in ``review/``.
Nothing upstream bounds any of them, so a burst of intake (a batch eval, a mailbox
backlog) piles work into the bins faster than the workers drain it.

This module gives each stage a maximum depth and one rule: **when a stage is full,
intake waits; nothing is dropped.** A held document stays where it is (in the caller's
hands, or in ``inbox/``) and is offered again once the stage drains.

- ``limit(stage)`` reads ``MAILROOM_MAX_QUEUE_DEPTH_<STAGE>`` (a positive integer;
  ``0`` turns the limit off) and falls back to :data:`DEFAULT_LIMITS`.
- ``stage_depth(stage)`` counts the documents in a bin (``.meta`` sidecars excluded),
  cached for :data:`DEPTH_CACHE_SECONDS` so a 1-second rescan over a large inbox does
  not rescan the disk once per file.
- ``wait_for_capacity(stages)`` blocks the calling producer, with capped exponential
  back-off, until every named stage is below its limit.

``review`` is unbounded by default: only a person drains it, so a limit there would
stall an unattended batch run for good. Set ``MAILROOM_MAX_QUEUE_DEPTH_REVIEW`` where a
reviewer is on hand. HF-005 in ``vendor_hotfixes`` applies the ``dispatch`` and
``processing`` limits inside the vendored watcher.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("mailroom_sandbox.backpressure")

STAGES: tuple[str, ...] = ("inbox", "dispatch", "processing", "review")

#: Defaults per stage; 0 means unbounded. ``dispatch`` and ``processing`` are a few multiples
#: of the watcher's default four worker slots; ``inbox`` absorbs a batch without letting it grow
#: without bound.
DEFAULT_LIMITS: dict[str, int] = {"inbox": 256, "dispatch": 32, "processing": 32, "review": 0}

ENV_PREFIX = "MAILROOM_MAX_QUEUE_DEPTH_"
DEPTH_CACHE_SECONDS = 0.5
INITIAL_WAIT_SECONDS = 0.25
MAX_WAIT_SECONDS = 5.0
LOG_EVERY_SECONDS = 30.0

#: How long an in-process producer waits for room before it gives up on one document
#: (``MAILROOM_BACKPRESSURE_TIMEOUT_SECONDS``; ``0`` waits for as long as it takes). Bounded by
#: default because a run checks its ``job.max_wall_seconds`` only between documents.
TIMEOUT_ENV = "MAILROOM_BACKPRESSURE_TIMEOUT_SECONDS"
DEFAULT_INTAKE_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class Saturation:
    stage: str
    depth: int
    limit: int

    def __str__(self) -> str:
        return f"{self.stage} {self.depth}/{self.limit}"


class BackpressureTimeout(RuntimeError):
    """A producer waited longer than its ``timeout`` for a stage to drain."""

    def __init__(self, full: list[Saturation], waited: float) -> None:
        self.full = full
        self.waited = waited
        super().__init__(f"queue still full after {waited:.0f}s: {', '.join(map(str, full))}")


def limit(stage: str) -> int:
    """The maximum depth of ``stage`` (0 = unbounded). A bad env value falls back to the default."""
    if stage not in DEFAULT_LIMITS:
        raise ValueError(f"unknown stage {stage!r}; expected one of {', '.join(STAGES)}")
    raw = os.environ.get(ENV_PREFIX + stage.upper(), "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if value >= 0:
            return value
        _log.warning("ignoring %s%s=%r: not a non-negative integer", ENV_PREFIX, stage.upper(), raw)
    return DEFAULT_LIMITS[stage]


def intake_timeout() -> float | None:
    """Seconds a producer may wait for room (None = no limit). A bad env value falls back."""
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    value = DEFAULT_INTAKE_TIMEOUT_SECONDS
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = -1.0
        if parsed >= 0 and parsed == parsed and parsed != float("inf"):
            value = parsed
        else:
            _log.warning("ignoring %s=%r: not a finite non-negative number", TIMEOUT_ENV, raw)
    return value or None


def limits() -> dict[str, int]:
    return {stage: limit(stage) for stage in STAGES}


def _bin_dir(stage: str) -> Path:
    from pipeline import bins  # type: ignore

    return {"inbox": bins.inbox_dir, "processing": bins.processing_dir, "review": bins.review_dir}[stage]()


def _count_documents(root: Path, *, recursive: bool) -> int:
    if not root.is_dir():
        return 0
    count = 0
    try:
        for p in (root.rglob("*") if recursive else root.iterdir()):
            # A document that moves on mid-scan is simply not counted.
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() != ".meta":
                count += 1
    except OSError:  # a worker directory removed mid-walk: keep the partial count
        pass
    return count


_cache: dict[str, tuple[float, int]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def stage_depth(stage: str, *, max_age: float = DEPTH_CACHE_SECONDS,
                clock: Callable[[], float] = time.monotonic) -> int:
    """Documents in a filesystem stage's bin. ``dispatch`` is in memory: read it from the pool."""
    if stage == "dispatch":
        raise ValueError("dispatch depth lives in the watcher's pool (queued_count), not on disk")
    now = clock()
    with _cache_lock:
        hit = _cache.get(stage)
        if hit is not None and max_age > 0 and now - hit[0] < max_age:
            return hit[1]
    if stage == "inbox":
        from pipeline import bins  # type: ignore

        depth = bins.count_inbox_pending()
    else:
        # processing/<worker_id>/<file> nests one level per worker; review is counted the same way.
        depth = _count_documents(_bin_dir(stage), recursive=True)
    with _cache_lock:
        _cache[stage] = (now, depth)
    return depth


def saturated(stages: Iterable[str], *, depths: dict[str, int] | None = None,
              max_age: float = DEPTH_CACHE_SECONDS) -> list[Saturation]:
    """The named stages at or over their limit (unbounded stages are never full)."""
    full: list[Saturation] = []
    for stage in stages:
        cap = limit(stage)
        if cap <= 0:
            continue
        depth = depths[stage] if depths and stage in depths else stage_depth(stage, max_age=max_age)
        if depth >= cap:
            full.append(Saturation(stage, depth, cap))
    return full


def wait_for_capacity(
    stages: Iterable[str] = ("inbox",),
    *,
    timeout: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    what: str = "intake",
) -> float:
    """Block until every stage in ``stages`` is below its limit; return the seconds waited.

    Back-off doubles from :data:`INITIAL_WAIT_SECONDS` to :data:`MAX_WAIT_SECONDS`. With
    ``timeout`` (seconds) it raises :class:`BackpressureTimeout` instead of waiting longer, so the
    caller can report the document as not sent; without one it waits for as long as it takes (a
    paid run is still bounded by its ``job.max_wall_seconds``).
    """
    names = tuple(stages)
    start = clock()
    delay = INITIAL_WAIT_SECONDS
    last_log = None
    while True:
        # A fresh read: a cached depth would hold the producer up to one cache period too long.
        full = saturated(names, max_age=0)
        if not full:
            waited = clock() - start
            if last_log is not None:
                _log.info("backpressure released for %s after %.1fs", what, waited)
            return waited
        waited = clock() - start
        if timeout is not None and waited >= timeout:
            raise BackpressureTimeout(full, waited)
        if last_log is None or clock() - last_log >= LOG_EVERY_SECONDS:
            _log.warning("backpressure: holding %s while %s", what, ", ".join(map(str, full)))
            last_log = clock()
        pause = delay if timeout is None else min(delay, max(timeout - waited, 0.0))
        sleep(pause)
        delay = min(delay * 2, MAX_WAIT_SECONDS)
