"""Console logging: format, verbosity levels, colors and the run/pipeline bridges (network-free)."""
from __future__ import annotations

import json
import logging

import pytest

from mailroom_sandbox import console_log


@pytest.fixture(autouse=True)
def _restore_logging(monkeypatch):
    """configure() edits global logging/structlog state; put it back after each test."""
    import structlog

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("SANDBOX_PLAIN_LOGS", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    root = logging.getLogger()
    names = ("mailroom_sandbox", "pipeline", *console_log.NOISY_LOGGERS, *console_log.ALWAYS_QUIET)
    saved = (list(root.handlers), root.level, {n: logging.getLogger(n).level for n in names})
    structlog_cfg = structlog.get_config()
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    for name, level in saved[2].items():
        logging.getLogger(name).setLevel(level)
    structlog.configure(**structlog_cfg)
    console_log._state["verbosity"] = 0


def _lines(capsys) -> list[str]:
    return [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]


def test_line_format_has_time_level_component_ids_and_fields(capsys):
    console_log.configure(0)
    console_log.doc_done("rb1-r13", "cba5ebbc-ee54-4d3f-a71a-a606ab4a9ebc", ok=True, done=3, total=10,
                         latency_ms=3200, prompt_tokens=900, completion_tokens=40, spent_usd=0.0412)
    (line,) = _lines(capsys)
    assert "\033[" not in line  # captured stderr is not a TTY
    stamp, level, component, rest = line.split(None, 3)
    assert len(stamp) == 8 and stamp.count(":") == 2
    assert (level, component) == ("INFO", "run")
    assert rest.startswith("run=rb1-r13 doc=cba5ebbc  doc done  ")
    assert "n=3/10 latency=3.2s tokens=900/40 spent=$0.0412" in rest


def test_default_hides_routine_info_but_keeps_key_events_and_warnings(capsys):
    console_log.configure(0)
    log = logging.getLogger("mailroom_sandbox.vendor_hotfixes")
    log.info("HF-001 applied")
    log.debug("detail")
    log.warning("something odd")
    console_log.run_event("r1", "start", "info", {"task": "sorter"})
    console_log.run_event("r1", "item_done", "info", {"index": 0})  # doc_done carries the doc line
    console_log.run_event("r1", "checkpoint_reconciled", "warn", {"stored": 1, "recomputed": 2})
    console_log.run_event("r1", "cancel_requested", "info", {})
    console_log.run_event("r1", "cost_cap_abort", "error", {"message": "api cap"})
    console_log.run_event("r1", "done", "info", {"cursor": 4, "ok_count": 4})
    text = "\n".join(_lines(capsys))
    assert "HF-001" not in text and "detail" not in text and "item done" not in text
    for expected in ("something odd", "run started", "checkpoint reconciled", "cancel requested",
                     "cap reached, aborting", "run finished"):
        assert expected in text


def test_quiet_and_verbose_levels(capsys):
    log = logging.getLogger("mailroom_sandbox.vendor_hotfixes")
    console_log.configure(-1)
    console_log.run_event("r1", "start", "info", {})
    console_log.doc_done("r1", "d1", ok=True)
    console_log.doc_done("r1", "d2", ok=False, error="timeout")
    log.warning("warned")
    quiet = _lines(capsys)
    assert len(quiet) == 2 and "doc failed" in quiet[0] and "error=timeout" in quiet[0]

    console_log.configure(1)
    log.info("HF-001 applied")
    log.debug("hidden at -v")
    shown = _lines(capsys)
    assert any("HF-001" in ln for ln in shown) and not any("hidden at -v" in ln for ln in shown)

    console_log.configure(2)
    log.debug("shown at -vv")
    assert any("DEBUG" in ln and "shown at -vv" in ln for ln in _lines(capsys))


def test_third_party_loggers_held_at_warning_until_vv():
    console_log.configure(0)
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("huggingface_hub").getEffectiveLevel() == logging.WARNING
    console_log.configure(2)
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("sqlalchemy").getEffectiveLevel() == logging.WARNING  # SQL echo stays off


def test_pipeline_structlog_events_are_bridged_promoted_and_demoted(capsys):
    import structlog

    console_log.configure(0)
    logger = structlog.get_logger()
    logger.info("llm_structured_call", agent="sorter", run_id="r1", doc_id="", matter_id="M", trace_id="")
    logger.info("pipeline_complete", run_id="r1", doc_id="cba5ebbc-ee54-4d3f-a71a-a606ab4a9ebc",
                archive="/very/long/path")
    logger.warning("audit_migration_pending", hint="run the migration")
    logger.warning("classification_guardrail_triggered", run_id="r1", issues=["doc_subclass_missing"])
    logger.warning("classification_guardrail_triggered", run_id="r1", issues=["doc_subclass_missing"])
    lines = _lines(capsys)
    assert len(lines) == 2, lines  # per-call info hidden, startup hint demoted, repeat dropped
    assert "pipeline  run=r1 doc=cba5ebbc  doc done" in lines[0] and "archive" not in lines[0]
    assert "WARN" in lines[1] and "issues=[doc_subclass_missing]" in lines[1]
    assert "matter_id" not in lines[1] and "trace_id" not in lines[1]


def test_format_value_is_compact():
    assert console_log.format_value({"a": 1, "b": [1, 2]}) == "{a:1,b:[1,2]}"
    assert console_log.format_value("two words") == '"two words"'
    assert console_log.format_value(0.123456) == "0.1235"
    assert console_log.format_value("x" * 200).endswith("…")
    assert console_log.short_id("plain-id") == "plain-id"
    assert console_log.format_value("804f191d242e53ce266e65bd86e00b449a52d307b3093f051abaa5306cccb99b") == "804f191d242e"


def test_color_only_on_tty_and_never_with_no_color(monkeypatch):
    class _Tty:
        def isatty(self):
            return True

    assert console_log.color_enabled(_Tty()) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert console_log.color_enabled(_Tty()) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("SANDBOX_PLAIN_LOGS", "1")
    assert console_log.color_enabled(_Tty()) is False


def test_color_palette_marks_key_events():
    fmt = console_log.ConsoleFormatter(color=True)

    def render(level, kind, msg="m"):
        record = logging.LogRecord("mailroom_sandbox.run", level, "", 0, msg, (), None)
        if kind:
            record.sb_kind = kind
        return fmt.format(record)

    assert "\033[1;36mrun started" in render(logging.INFO, console_log.RUN, "run started")
    assert "\033[32mdoc done" in render(logging.INFO, console_log.DOC_OK, "doc done")
    assert "\033[1;31mdoc failed" in render(logging.WARNING, console_log.DOC_FAIL, "doc failed")
    assert "\033[1;35mspend" in render(logging.INFO, console_log.SPEND, "spend")
    assert "\033[1;33mpaused" in render(logging.WARNING, console_log.CANCEL, "paused")
    assert "\033[1;31mboom" in render(logging.ERROR, None, "boom")
    plain_info = render(logging.INFO, None, "neutral")
    assert "neutral" in plain_info and "\033[" + "1" not in plain_info.split("neutral")[0][-8:]
    assert render(logging.DEBUG, None, "quiet").startswith("\033[2m")


def test_json_lines_are_uncolored(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    console_log.configure(0)
    console_log.doc_done("r1", "d1", ok=True, done=1, total=2)
    (line,) = _lines(capsys)
    payload = json.loads(line)
    assert payload["event"] == "doc done" and payload["kind"] == "doc_ok" and payload["doc_id"] == "d1"


def test_spend_checkpoints_fire_once_per_mark(capsys):
    console_log.configure(0)

    class _Budget:
        cap_usd = 1.0
        spent_usd = 0.3

    marks = console_log.SpendCheckpoints("r1", _Budget)
    marks.check()
    marks.check()
    _Budget.spent_usd = 0.95
    marks.check()
    lines = _lines(capsys)
    assert len(lines) == 4  # a jump past several marks still reports each one
    assert "spend at 25% of cap" in lines[0] and "spent=$0.3000 cap=$1.00" in lines[0]
    assert ["50%" in lines[1], "75%" in lines[2]] == [True, True]
    assert lines[3].split()[1] == "WARN" and "spend at 90% of cap" in lines[3]


def test_unconfigured_run_logger_is_silent(capsys):
    """Library use (tests, Modal workers) never falls back to logging.lastResort."""
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not getattr(h, "_sandbox_console", False)]
    console_log.doc_done("r1", "d1", ok=False, error="x")
    assert capsys.readouterr().err == ""


def test_cli_verbosity_flags_parse_before_or_after_the_subcommand():
    from mailroom_sandbox import cli

    parser = cli.build_parser()
    for argv, want in ((["doctor"], 0), (["-v", "doctor"], 1), (["doctor", "-vv"], 2),
                       (["-q", "doctor"], -1), (["doctor", "--quiet"], -1)):
        args = parser.parse_args(argv)
        assert (-1 if args.quiet else args.verbose) == want, argv


def test_main_configures_console_from_flags(monkeypatch):
    from mailroom_sandbox import cli

    seen = []
    monkeypatch.setattr(console_log, "configure", lambda v=0: seen.append(v))
    parser = cli.build_parser()
    args = parser.parse_args(["doctor", "-v"])
    args.handler = lambda _a: 0
    monkeypatch.setattr(cli, "build_parser", lambda: _Fixed(parser, args))
    assert cli.main(["-v", "doctor", "-v"]) == 0
    assert seen == [2]


class _Fixed:
    def __init__(self, parser, args):
        self._parser, self._args = parser, args

    def parse_args(self, *_a, **_k):
        return self._args

    def print_help(self):
        self._parser.print_help()


def test_console_progress_is_throttled_to_quarters(capsys):
    from mailroom_sandbox.tui.session import MailroomConsole

    console = MailroomConsole(enabled=False)
    for done in range(1, 51):
        console.progress(done, 50, ok=done, errors=0)
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("[progress]")]
    assert len(lines) == 5  # first, each 25% step, and the last
    assert lines[-1].startswith("[progress] 50/50")


def test_quiet_console_skips_banner_and_progress(capsys):
    from mailroom_sandbox.tui.session import MailroomConsole

    console_log.configure(-1)
    console = MailroomConsole(enabled=False)
    console.run_banner(run_id="r1", task="sorter")
    console.phase("PREFLIGHT", "ok")
    console.progress(1, 2)
    console.complete(state="done", summary="2/2")
    assert capsys.readouterr().err.strip() == "[done] done — 2/2"


def test_run_job_mock_prints_lifecycle_and_doc_lines(tmp_path, capsys):
    from mailroom_sandbox.job import runner

    import shutil
    import uuid

    console_log.configure(0)
    store = _prepped_store(tmp_path, rows=3, run_id=f"console-log-{uuid.uuid4().hex[:8]}")
    try:
        summary = runner.run_job(store, mock=None)
    finally:
        events_text = store.events_path.read_text()
        shutil.rmtree(store.dir, ignore_errors=True)
    assert summary["state"] == "done"
    lines = _lines(capsys)
    text = "\n".join(lines)
    assert "run started" in text and "run finished" in text
    assert sum("doc done" in ln for ln in lines) == 3
    assert "n=3/3" in text
    events = [json.loads(ln)["event"] for ln in events_text.splitlines()]
    assert "item_done" in events  # events.jsonl unchanged by the console echo


def test_resolve_verbosity_sums_flags_across_argv_and_reads_env():
    resolve = console_log.resolve_verbosity
    assert resolve(["pilot", "--mock"], environ={}) == 0
    assert resolve(["-v", "run", "start", "-v"], environ={}) == 2
    assert resolve(["-vvv", "pilot"], environ={}) == 2
    assert resolve(["--verbose", "pilot"], environ={}) == 1
    assert resolve(["-v", "pilot", "-q"], environ={}) == -1  # quiet wins
    assert resolve(["pilot", "--", "-v"], environ={}) == 0  # passthrough args are not ours
    assert resolve(["pilot"], environ={console_log.VERBOSITY_ENV: "1"}) == 1
    assert resolve(["pilot"], environ={console_log.VERBOSITY_ENV: "junk"}) == 0
    assert resolve(["-q", "pilot"], environ={console_log.VERBOSITY_ENV: "2"}) == -1


def test_vendor_setup_logging_cannot_override_console(tmp_path, monkeypatch):
    """A vendor module-level setup_logging() after configure() is a no-op (guarded on import)."""
    import sys

    pkg = tmp_path / "pipeline"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "logging.py").write_text(
        "_configured = False\ncalls = []\n"
        "def setup_logging():\n    if _configured:\n        return\n    calls.append(1)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("pipeline", "pipeline.logging"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    console_log.configure(0)
    import pipeline.logging as vendor_logging

    vendor_logging.setup_logging()
    assert vendor_logging._configured is True and vendor_logging.calls == []
    monkeypatch.delitem(sys.modules, "pipeline.logging")
    monkeypatch.delitem(sys.modules, "pipeline")
    monkeypatch.setattr(sys, "meta_path", [f for f in sys.meta_path
                                           if not isinstance(f, console_log._VendorLoggingGuard)])


def test_run_records_read_well_under_a_foreign_formatter():
    """The Modal worker uses basicConfig; its lines still carry ids and fields."""
    records = []

    class _Keep(logging.Handler):
        def emit(self, record):
            records.append(logging.Formatter("%(levelname)s %(name)s %(message)s").format(record))

    handler = _Keep()
    run_log = logging.getLogger(console_log.RUN_LOGGER)
    run_log.addHandler(handler)
    run_log.setLevel(logging.INFO)
    try:
        console_log.doc_done("r1", "d7", ok=True, done=2, total=5)
    finally:
        run_log.removeHandler(handler)
        run_log.setLevel(logging.NOTSET)
    assert records == ["INFO mailroom_sandbox.run run=r1 doc=d7  doc done  n=2/5"]


def test_repeat_filter_keeps_identical_warnings_from_different_docs(capsys):
    console_log.configure(0)
    for doc in ("d1", "d1", "d2"):
        console_log.doc_done("r1", doc, ok=False, error="timeout")
    lines = _lines(capsys)
    assert [ln.split("doc=")[1].split()[0] for ln in lines] == ["d1", "d2"]


def test_doc_echo_reports_resumed_reruns_and_spend(capsys):
    console_log.configure(0)

    class _Budget:
        cap_usd = 1.0
        spent_usd = 0.26

    echo = console_log.DocEcho("r1", _Budget)
    echo("d1", ok=True, done=1, total=2, row={"latency_ms": 1500, "prompt_tokens": 10, "completion_tokens": 2},
         rerun=True)
    lines = _lines(capsys)
    assert "doc done (re-run; already recorded)" in lines[0]
    assert "latency=1.5s tokens=10/2 spent=$0.2600" in lines[0]
    assert "spend at 25% of cap" in lines[1]


def test_echo_failure_never_raises(caplog):
    console_log.configure(0)
    caplog.set_level(logging.DEBUG, logger="mailroom_sandbox.console_log")

    class _Boom:
        @property
        def cap_usd(self):
            raise RuntimeError("boom")

    console_log.SpendCheckpoints("r1", _Boom()).check()
    assert any("console echo failed" in r.getMessage() for r in caplog.records)


def _prepped_store(tmp_path, rows, run_id):
    """A prepared offline mock sorter run (mirrors tests/test_job_runner.py; bare `pytest`
    does not put the repo root on sys.path, so test modules cannot import each other)."""
    from mailroom_sandbox.job import preflight
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, run_dir

    path = tmp_path / "f.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(rows):
            fh.write(json.dumps({"id": f"d{i}", "filename": f"{i}.txt", "doc_text": f"t{i}",
                                 "expected": "contract" if i % 2 else "insurance_claim",
                                 "expected_subclass": "service" if i % 2 else "auto"}) + "\n")
    spec = RunSpec(
        run_id=run_id,
        task="sorter",
        dataset=DatasetSpec(local_path=f"file://{path}", limit=rows),
        engine={"kind": "vllm-local", "modal": None},
        trace={"sink": "none"},
        job={"mock": True},
    )
    report = preflight.preflight(spec, offline=True)
    assert report["status"] == "prepared", report
    return RunStore(run_dir(report["run_id"]))
