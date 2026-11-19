"""Human-facing console logging for the ``sandbox`` CLI (stderr only).

One line per event, one format for every source::

    01:34:57 INFO  run       run=rb1-r13  doc=cba5ebbc  doc done  12/50 latency=3.2s spent=$0.0412

Sources: the sandbox's own stdlib loggers, the vendored pipeline's structlog
events (bridged here, never printed by structlog's own renderer) and the run
store's lifecycle events. This module only renders; ``events.jsonl``,
``items.jsonl`` and run locks are written elsewhere and are unchanged by it.

Verbosity (``-q`` / default / ``-v`` / ``-vv``):

- ``-1`` quiet: warnings and errors only.
- ``0`` default: key events only — run start/finish, per-document completion,
  spend/cap checkpoints, cancellation — plus warnings and errors.
- ``1``: also routine INFO detail (per-call pipeline events, sandbox setup notes).
- ``2``: also DEBUG, and third-party loggers (httpx, urllib3, ...) at INFO.

Color only on a TTY stderr, never with ``NO_COLOR`` or ``SANDBOX_PLAIN_LOGS=1``.
``LOG_FORMAT=json`` (the pipeline's own switch) prints uncolored JSON lines.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Mapping

RUN_LOGGER = "mailroom_sandbox.run"
PIPELINE_LOGGER = "pipeline"
_OWN_LOGGERS = ("mailroom_sandbox", PIPELINE_LOGGER)

#: Third-party loggers held at WARNING unless ``-vv``.
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "huggingface_hub",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "langsmith",
    "openai",
    "anthropic",
    "langfuse",
    "opentelemetry",
    "watchdog",
    "modal",
    "grpc",
)
#: Loggers whose INFO is a firehose (SQL echo, font scans): WARNING even at ``-vv``.
ALWAYS_QUIET = ("sqlalchemy", "aiosqlite", "asyncio", "matplotlib", "PIL", "filelock", "fsspec")

# Key-event kinds and the record attribute that carries them.
RUN = "run"
DOC_OK = "doc_ok"
DOC_FAIL = "doc_fail"
SPEND = "spend"
CANCEL = "cancel"
_KIND_ATTR = "sb_kind"

# Vendored pipeline events: promoted to key events, or demoted to DEBUG.
_PIPELINE_KEY_EVENTS: dict[str, tuple[str, str]] = {
    "pipeline_complete": (DOC_OK, "doc done"),
    "pipeline_paused_for_review": (DOC_OK, "doc done (held for review)"),
    "pipeline_failed": (DOC_FAIL, "doc failed"),
}
_PIPELINE_DEMOTED = frozenset({"audit_migration_pending"})  # startup hint about a DB the harness owns
# Context fields every pipeline event repeats; shown only at -vv.
_CONTEXT_FIELDS = frozenset({"matter_id", "trace_id", "timestamp", "logger", "level"})

# Run-store events -> (level, kind, message). Unlisted events render at DEBUG.
_RUN_EVENTS: dict[str, tuple[int, str | None, str]] = {
    # Per-document lines come from doc_done(), which carries progress and spend.
    "item_done": (logging.DEBUG, None, "item done"),
    "item_failed": (logging.DEBUG, None, "item failed"),
    "preflight_ok": (logging.INFO, RUN, "preflight ok"),
    "spend_authorized": (logging.INFO, SPEND, "spend authorized"),
    "fired": (logging.INFO, RUN, "remote job fired"),
    "remote_reattached": (logging.INFO, RUN, "remote job reattached"),
    "start": (logging.INFO, RUN, "run started"),
    "resume": (logging.INFO, RUN, "run resumed"),
    "done": (logging.INFO, RUN, "run finished"),
    "yielded": (logging.INFO, RUN, "run yielded"),
    "failed": (logging.ERROR, RUN, "run failed"),
    "cost_cap_abort": (logging.ERROR, SPEND, "cap reached, aborting"),
    "cancel_requested": (logging.WARNING, CANCEL, "cancel requested"),
    "paused": (logging.WARNING, CANCEL, "run paused"),
}

# ANSI SGR codes (16-color: safe on every terminal theme).
_DIM, _BOLD = "2", "1"
_LEVEL_STYLE = {
    logging.DEBUG: ("DEBUG", _DIM),
    logging.INFO: ("INFO ", ""),
    logging.WARNING: ("WARN ", "33"),
    logging.ERROR: ("ERROR", "1;31"),
    logging.CRITICAL: ("CRIT ", "1;37;41"),
}
_KIND_STYLE = {
    RUN: "1;36",  # bold cyan: run lifecycle
    DOC_OK: "32",  # green: document done
    DOC_FAIL: "1;31",  # bold red: document failed
    SPEND: "1;35",  # bold magenta: spend / cap
    CANCEL: "1;33",  # bold yellow: cancel / pause
}

_state: dict[str, Any] = {"verbosity": 0, "configured": False}


def verbosity() -> int:
    """Current console verbosity (-1 quiet … 2 debug); 0 before ``configure``."""
    return int(_state["verbosity"])


def color_enabled(stream: Any = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("SANDBOX_PLAIN_LOGS", "").strip().lower() in ("1", "true", "yes"):
        return False
    fh = stream if stream is not None else sys.stderr
    return hasattr(fh, "isatty") and bool(fh.isatty())


def _sgr(code: str, text: str, on: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if on and code else text


def short_id(value: Any) -> str:
    """UUID-like ids shrink to their first 8 characters; other ids pass through."""
    text = str(value)
    if len(text) == 36 and text.count("-") == 4:
        return text[:8]
    return text


def format_value(value: Any, *, limit: int = 80) -> str:
    """Compact, single-line rendering of one field value."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        text = f"{value:.4g}"
    elif isinstance(value, (list, tuple, set)):
        text = "[" + ",".join(format_value(v, limit=limit) for v in value) + "]"
    elif isinstance(value, Mapping):
        text = "{" + ",".join(f"{k}:{format_value(v, limit=limit)}" for k, v in value.items()) + "}"
    elif isinstance(value, str) and len(value) >= 32 and all(c in "0123456789abcdef" for c in value):
        text = value[:12]  # hashes and fingerprints: the prefix is enough to match by eye
    else:
        text = " ".join(str(value).split())
        if text != str(value) or " " in text or not text:
            text = json.dumps(text, ensure_ascii=False)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def format_fields(fields: Mapping[str, Any], *, color: bool = False, verbose: bool = False) -> str:
    parts = []
    for key, value in fields.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        if not verbose and key in _CONTEXT_FIELDS:
            continue
        rendered = format_value(short_id(value) if key.endswith("_id") else value)
        parts.append(_sgr(_DIM, f"{key}=", color) + rendered)
    return " ".join(parts)


def _component(name: str) -> str:
    if name.startswith("mailroom_sandbox."):
        return name.rsplit(".", 1)[-1]
    if name == "mailroom_sandbox":
        return "sandbox"
    return name.split(".", 1)[0]


class ConsoleFormatter(logging.Formatter):
    """``HH:MM:SS LEVEL component  run=… doc=…  message  key=value …``."""

    def __init__(self, *, color: bool = False, verbose: bool = False, json_lines: bool = False) -> None:
        super().__init__()
        self.color = color and not json_lines
        self.verbose = verbose
        self.json_lines = json_lines

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = dict(getattr(record, "sb_fields", None) or {})
        run_id = getattr(record, "sb_run", None) or fields.pop("run_id", None)
        doc_id = getattr(record, "sb_doc", None) or fields.pop("doc_id", None)
        fields.pop("run_id", None)
        fields.pop("doc_id", None)
        kind = getattr(record, _KIND_ATTR, None)
        message = getattr(record, "sb_text", None) or record.getMessage()
        exc = self.formatException(record.exc_info) if record.exc_info else fields.pop("exception", None)
        if self.json_lines:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname.lower(),
                "component": _component(record.name),
                "event": message,
                **({"kind": kind} if kind else {}),
                **({"run_id": run_id} if run_id else {}),
                **({"doc_id": doc_id} if doc_id else {}),
                **fields,
                **({"exception": exc} if exc else {}),
            }
            return json.dumps(payload, ensure_ascii=False, default=str)
        on = self.color
        label, level_code = _LEVEL_STYLE.get(record.levelno, (record.levelname[:5].ljust(5), ""))
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        head = [_sgr(_DIM, ts, on), _sgr(level_code, label, on), _sgr(_DIM, f"{_component(record.name):<9}", on)]
        ids = " ".join(
            bit for bit in (f"run={run_id}" if run_id else "", f"doc={short_id(doc_id)}" if doc_id else "") if bit
        )
        if ids:
            head.append(_sgr(_DIM, ids, on))
        body_code = _KIND_STYLE.get(kind or "", "")
        if record.levelno >= logging.ERROR:
            body_code = _LEVEL_STYLE[logging.ERROR][1]
        elif record.levelno == logging.WARNING and not kind:
            body_code = _LEVEL_STYLE[logging.WARNING][1]
        tail = format_fields(fields, color=on, verbose=self.verbose)
        line = " ".join(head) + "  " + _sgr(body_code, message, on) + (f"  {tail}" if tail else "")
        if record.levelno == logging.DEBUG and on:
            line = _sgr(_DIM, _strip_sgr(line), True)
        if exc:
            line += "\n" + exc
        return line


def _strip_sgr(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


class _KeyEventFilter(logging.Filter):
    """At default verbosity, INFO passes only for key events (records with a kind)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if verbosity() == 0 and record.levelno == logging.INFO:
            return bool(getattr(record, _KIND_ATTR, None))
        return True


class _RepeatFilter(logging.Filter):
    """Below ``-vv``, drop a record identical to the one just shown (the pipeline
    logs some guardrail warnings once per attempt)."""

    def __init__(self) -> None:
        super().__init__()
        self._last: tuple[Any, ...] | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        if verbosity() >= 2:
            return True
        try:
            fields = getattr(record, "sb_fields", None) or {}
            key = (record.name, record.levelno, record.getMessage(),
                   getattr(record, "sb_run", None), getattr(record, "sb_doc", None),
                   json.dumps(fields, sort_keys=True, default=str))
        except Exception:  # noqa: BLE001
            return True
        if key == self._last:
            return False
        self._last = key
        return True


class _StderrHandler(logging.StreamHandler):
    """Writes to the *current* ``sys.stderr`` (so redirection and test capture work)."""

    _sandbox_console = True

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property  # type: ignore[override]
    def stream(self):  # noqa: D401
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        pass


def _structlog_bridge(_logger: Any, method_name: str, event_dict: dict[str, Any]) -> Any:
    """Final structlog processor: hand the event to stdlib logging, then drop it."""
    import structlog

    event = str(event_dict.pop("event", ""))
    method = {"warn": "warning", "exception": "error", "msg": "info", "fatal": "critical"}.get(method_name, method_name)
    level = logging.getLevelName(method.upper())
    if not isinstance(level, int):
        level = logging.INFO
    kind, message = _PIPELINE_KEY_EVENTS.get(event, (None, event))
    if event in _PIPELINE_DEMOTED:
        level = logging.DEBUG
    event_dict.pop("level", None)
    event_dict.pop("log_level", None)
    target = logging.getLogger(PIPELINE_LOGGER)
    if target.isEnabledFor(level):
        if kind and verbosity() < 1:
            # A promoted per-document event keeps only its ids at default verbosity
            # (archive paths and thread ids are -v detail).
            event_dict = {k: event_dict[k] for k in ("run_id", "doc_id") if k in event_dict}
        extra: dict[str, Any] = {"sb_fields": event_dict}
        if kind:
            extra[_KIND_ATTR] = kind
        target.log(level, message, extra=extra)
    raise structlog.DropEvent


def _configure_structlog() -> None:
    try:
        import structlog
    except ImportError:  # pragma: no cover - structlog ships with the pipeline extra
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.format_exc_info,
            _structlog_bridge,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        logger_factory=structlog.ReturnLoggerFactory(),
        cache_logger_on_first_use=False,
    )


VERBOSITY_ENV = "SANDBOX_LOG_VERBOSITY"


def resolve_verbosity(argv: Any, args: Any = None, environ: Mapping[str, str] | None = None) -> int:
    """Verbosity from the command line, else ``SANDBOX_LOG_VERBOSITY``, else 0.

    ``-v`` counts are summed across the whole argv (before ``--``), so ``sandbox -v run start -v``
    is ``-vv`` even though argparse keeps only the subcommand's copy. ``-q`` wins over ``-v``.
    """
    env = os.environ if environ is None else environ
    count, quiet = 0, bool(getattr(args, "quiet", False))
    for token in list(argv or ()):
        if token == "--":
            break
        if token == "--verbose":
            count += 1
        elif token == "--quiet":
            quiet = True
        elif token.startswith("-") and not token.startswith("--") and len(token) > 1 and set(token[1:]) <= {"v", "q"}:
            count += token.count("v")
            quiet = quiet or "q" in token
    count = max(count, int(getattr(args, "verbose", 0) or 0))
    if quiet:
        return -1
    if count:
        return min(count, 2)
    try:
        return max(-1, min(2, int(env.get(VERBOSITY_ENV, "0") or 0)))
    except ValueError:
        return 0


class _VendorLoggingGuard:
    """Meta-path hook: once this process has configured the console, mark the vendored
    ``pipeline.logging`` module as configured whenever it is (re)imported, so a vendor
    entrypoint's module-level ``setup_logging()`` (``pipeline.watchdog``, ``pipeline.pager``)
    cannot re-point structlog at stdout. Only runtime state changes; ``vendor/`` files do not."""

    TARGET = "pipeline.logging"

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> Any:
        if name != self.TARGET:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is None:
                continue
            loader = spec.loader
            exec_module = getattr(loader, "exec_module", None)
            if exec_module is None:
                return spec

            def _exec(module: Any, _inner: Any = exec_module) -> None:
                _inner(module)
                _mark_vendor_configured(module)

            try:
                loader.exec_module = _exec  # type: ignore[union-attr]  # per-spec loader instance
            except (AttributeError, TypeError):
                pass
            return spec
        return None

    def invalidate_caches(self) -> None:  # importlib protocol
        return None


def _mark_vendor_configured(module: Any) -> None:
    if hasattr(module, "setup_logging") and hasattr(module, "_configured"):
        module._configured = True


def _guard_vendor_logging() -> None:
    if not any(isinstance(f, _VendorLoggingGuard) for f in sys.meta_path):
        sys.meta_path.insert(0, _VendorLoggingGuard())
    loaded = sys.modules.get(_VendorLoggingGuard.TARGET)
    if loaded is not None:
        _mark_vendor_configured(loaded)


def configure(verbosity: int = 0) -> None:
    """Install the console handler on the root logger (idempotent; re-callable)."""
    level_v = max(-1, min(2, int(verbosity)))
    _state["verbosity"] = level_v
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_sandbox_console", False):
            root.removeHandler(handler)
    json_lines = os.environ.get("LOG_FORMAT", "").strip().lower() == "json"
    handler = _StderrHandler()
    handler.setFormatter(
        ConsoleFormatter(color=color_enabled(), verbose=level_v >= 2, json_lines=json_lines)
    )
    handler.addFilter(_KeyEventFilter())
    handler.addFilter(_RepeatFilter())
    handler.setLevel(logging.WARNING if level_v < 0 else logging.DEBUG if level_v >= 2 else logging.INFO)
    root.addHandler(handler)
    root.setLevel(logging.INFO if level_v >= 2 else logging.WARNING)
    own = logging.WARNING if level_v < 0 else logging.DEBUG if level_v >= 2 else logging.INFO
    for name in _OWN_LOGGERS:
        logging.getLogger(name).setLevel(own)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO if level_v >= 2 else logging.WARNING)
    for name in ALWAYS_QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
    _configure_structlog()
    _guard_vendor_logging()
    _state["configured"] = True


# --- run-level helpers -------------------------------------------------------

_run_log = logging.getLogger(RUN_LOGGER)
# Unconfigured processes (Modal workers, library use, tests) stay silent instead of
# falling back to logging.lastResort.
_run_log.addHandler(logging.NullHandler())
logging.getLogger(PIPELINE_LOGGER).addHandler(logging.NullHandler())


def _emit(level: int, kind: str | None, text: str, run_id: Any = None, doc_id: Any = None,
          fields: Mapping[str, Any] | None = None) -> None:
    if not _run_log.isEnabledFor(level):
        return
    fields = dict(fields or {})
    extra: dict[str, Any] = {"sb_fields": fields, "sb_run": run_id, "sb_doc": doc_id, "sb_text": text}
    if kind:
        extra[_KIND_ATTR] = kind
    # The record's own message carries ids and fields too, so a process with a different
    # formatter (the Modal worker's basicConfig, pytest's caplog) still shows a useful line.
    ids = " ".join(bit for bit in (f"run={run_id}" if run_id else "",
                                   f"doc={short_id(doc_id)}" if doc_id else "") if bit)
    tail = format_fields(fields)
    _run_log.log(level, "  ".join(bit for bit in (ids, text, tail) if bit), extra=extra)


_self_log = logging.getLogger("mailroom_sandbox.console_log")


def _echo_failed() -> None:
    """Console output must never break a run: note the failure at DEBUG and carry on."""
    _self_log.debug("console echo failed", exc_info=True)


def run_event(run_id: Any, event: str, level: str = "info", detail: Mapping[str, Any] | None = None) -> None:
    """Console echo of one run-store event (``events.jsonl`` itself is untouched)."""
    try:
        mapped = _RUN_EVENTS.get(event)
        if mapped is None:
            lvl = {"warn": logging.WARNING, "warning": logging.WARNING, "error": logging.ERROR}.get(level)
            mapped = (lvl or logging.DEBUG, None, event.replace("_", " "))
        lvl, kind, message = mapped
        _emit(lvl, kind, message, run_id=run_id, fields=detail)
    except Exception:  # noqa: BLE001
        _echo_failed()


def doc_done(
    run_id: Any,
    item_id: Any,
    *,
    ok: bool,
    done: int | None = None,
    total: int | None = None,
    error: Any = None,
    latency_ms: Any = None,
    prompt_tokens: Any = None,
    completion_tokens: Any = None,
    spent_usd: float | None = None,
    rerun: bool = False,
) -> None:
    """One per-document completion line.

    ``rerun`` marks a document a resumed whole-run delegate processed again although an
    earlier attempt already recorded it (its item row is kept; only the console says so).
    """
    try:
        fields: dict[str, Any] = {}
        if done is not None and total:
            fields["n"] = f"{done}/{total}"
        if isinstance(latency_ms, (int, float)):
            fields["latency"] = f"{latency_ms / 1000.0:.1f}s"
        if prompt_tokens or completion_tokens:
            fields["tokens"] = f"{prompt_tokens or 0}/{completion_tokens or 0}"
        if spent_usd is not None:
            fields["spent"] = f"${spent_usd:.4f}"
        if not ok and error:
            fields["error"] = str(error)[:160]
        text = "doc done" if ok else "doc failed"
        if rerun:
            text += " (re-run; already recorded)"
        _emit(
            logging.INFO if ok else logging.WARNING,
            DOC_OK if ok else DOC_FAIL,
            text,
            run_id=run_id,
            doc_id=item_id,
            fields=fields,
        )
    except Exception:  # noqa: BLE001
        _echo_failed()


class SpendCheckpoints:
    """Log once as API spend crosses each fraction of its cap (one line per mark crossed)."""

    MARKS = (0.25, 0.5, 0.75, 0.9)

    def __init__(self, run_id: Any, budget: Any) -> None:
        self.run_id = run_id
        self.budget = budget
        self._passed: set[float] = set()

    def check(self) -> None:
        try:
            cap = float(getattr(self.budget, "cap_usd", 0) or 0)
            if cap <= 0:
                return
            spent = float(getattr(self.budget, "spent_usd", 0) or 0)
            for mark in self.MARKS:
                if spent < mark * cap or mark in self._passed:
                    continue
                self._passed.add(mark)
                _emit(
                    logging.WARNING if mark >= 0.9 else logging.INFO,
                    SPEND,
                    f"spend at {int(mark * 100)}% of cap",
                    run_id=self.run_id,
                    fields={"spent": f"${spent:.4f}", "cap": f"${cap:.2f}"},
                )
        except Exception:  # noqa: BLE001
            _echo_failed()


class DocEcho:
    """Per-run console echo of document completions plus spend checkpoints."""

    def __init__(self, run_id: Any, budget: Any = None) -> None:
        self.run_id = run_id
        self.budget = budget
        self.marks = SpendCheckpoints(run_id, budget) if budget is not None else None

    def __call__(self, item_id: Any, *, ok: bool, done: int | None, total: int | None,
                 row: Mapping[str, Any] | None = None, error: Any = None, latency_ms: Any = None,
                 rerun: bool = False) -> None:
        row = row or {}
        doc_done(
            self.run_id,
            item_id,
            ok=ok,
            done=done,
            total=total,
            error=error,
            latency_ms=row.get("latency_ms") if latency_ms is None else latency_ms,
            prompt_tokens=row.get("prompt_tokens"),
            completion_tokens=row.get("completion_tokens"),
            spent_usd=getattr(self.budget, "spent_usd", None),
            rerun=rerun,
        )
        if self.marks is not None:
            self.marks.check()
