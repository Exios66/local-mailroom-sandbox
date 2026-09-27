"""SAND-032: `sandbox watch` — mailroom-themed live view (pure render functions)."""

import json
import re

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.watch import (
    classify_log_line,
    progress_bar,
    render_frame,
    run_snapshot,
    strip_ansi,
)


def test_progress_bar_uses_mailroom_glyphs_and_clamps():
    assert progress_bar(5, 10, width=10) == "█████░░░░░"
    assert progress_bar(0, 0, width=4) == "░░░░"
    assert progress_bar(12, 10, width=4) == "████"


def test_vendored_pretty_log_is_pinned():
    import hashlib
    from pathlib import Path

    from mailroom_sandbox import tui

    path = Path(tui.__file__).with_name("pretty_log.py")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == tui.PRETTY_LOG_SHA256
    assert "mailroom-ml@f85f79e" in tui.PRETTY_LOG_UPSTREAM


def test_header_is_mailroom_frame_with_eval_subtitle(tmp_path):
    frame = strip_ansi(render_frame(snapshot=run_snapshot(_store(tmp_path)), app="sandbox-vllm-sand032",
                                    log_lines=[], spend={"spent_usd": 0, "cap_usd": 5.0}, width=100))
    lines = frame.splitlines()
    assert lines[0].startswith("╔") and "(o,o)" in frame
    assert "DIGITAL MAILROOM" in frame and "vLLM L4 eval" in frame
    assert "INBOX → SPECIALIST → REPORT" in frame
    assert "╭" in frame and "IN-TRAY" in frame and "POSTAGE" in frame and "DISPATCH LOG" in frame


def test_classify_log_line():
    assert classify_log_line("ERROR vLLM engine died") == "error"
    assert classify_log_line("Traceback (most recent call last):") == "error"
    assert classify_log_line("WARNING kv cache 95%") == "warn"
    assert classify_log_line("Avg prompt throughput: 812.3 tokens/s, Avg generation throughput: 140.1") == "throughput"
    assert classify_log_line("GPU KV cache size: 181,344 tokens") == "kv"
    assert classify_log_line("vLLM ready on port 8000 (pid=12)") == "ready"
    assert classify_log_line("some other line") == "plain"


def _store(tmp_path, *, replicas=2):
    s = RunStore(tmp_path / "sand032-x")
    s.write_lock({"run_id": "sand032-x", "task": "correspondence_specialist",
                  "engine": {"model": "Qwen/Qwen3-8B-AWQ",
                             "vllm": {"kv_cache_dtype": "fp8"},
                             "modal": {"gpu": "L4", "max_containers": replicas,
                                       "min_containers": replicas}},
                  "job": {"concurrency": 16}})
    s.write_checkpoint(state="running", cursor=3, total=10, remote=None)
    for i, (ok, lat) in enumerate([(True, 1000.0), (True, 3000.0), (False, 500.0)]):
        s.append_item({"item_id": f"d{i}", "ok": ok, "latency_ms": lat,
                       "error": None if ok else "OpenAIConnectionError: x",
                       "score": {"overall_extraction_score": 0.5} if ok else {}})
    return s


def test_run_snapshot_counts_and_latency(tmp_path):
    snap = run_snapshot(_store(tmp_path))
    assert snap["run_id"] == "sand032-x"
    assert (snap["done"], snap["total"], snap["ok"], snap["errors"]) == (3, 10, 2, 1)
    assert snap["state"] == "running"
    assert snap["replicas"] == 2
    assert snap["p50_s"] == 2.0 and snap["mean_score"] == 0.5
    assert snap["last_error"].startswith("OpenAIConnectionError")


def test_run_snapshot_missing_store_is_waiting(tmp_path):
    snap = run_snapshot(RunStore(tmp_path / "nope"))
    assert snap["state"] == "waiting" and snap["done"] == 0


def test_render_frame_has_mailroom_sections_and_fits_width(tmp_path):
    frame = render_frame(
        snapshot=run_snapshot(_store(tmp_path)),
        app="sandbox-vllm-sand032",
        log_lines=["vLLM ready on port 8000 (pid=12)", "ERROR boom"],
        spend={"spent_usd": 1.2345, "cap_usd": 5.0, "live_usd": 0.01},
        width=100,
    )
    plain = strip_ansi(frame)
    for needle in ("MAILROOM", "sandbox-vllm-sand032", "sand032-x", "3/10",
                   "delivered 2", "returned 1", "$1.2345", "$5.00", "ERROR boom", "×2 L4"):
        assert needle in plain, needle
    assert all(len(line) <= 100 for line in plain.splitlines())


def test_render_frame_warns_near_budget(tmp_path):
    frame = render_frame(snapshot=run_snapshot(_store(tmp_path)), app="a", log_lines=[],
                         spend={"spent_usd": 4.6, "cap_usd": 5.0, "live_usd": 0.0}, width=80)
    assert "OVER $4.50 GATE" in strip_ansi(frame)


def test_strip_ansi():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert not re.search(r"\x1b", strip_ansi("\x1b[1;36mx\x1b[0m"))


def test_cli_watch_once_renders_single_frame(tmp_path, monkeypatch, capsys):
    from mailroom_sandbox.cli import main
    from mailroom_sandbox.job import spec as spec_mod
    from mailroom_sandbox.paths import config_dir

    monkeypatch.setattr(spec_mod, "runs_root", lambda: tmp_path)
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"spent_usd": 0.42}))
    rc = main(["watch", "--config", str(config_dir() / "runs" / "sand032-l0-baseline.yaml"),
               "--once", "--no-logs", "--ledger", str(ledger)])
    out = strip_ansi(capsys.readouterr().out)
    assert rc == 0
    assert "sandbox-vllm-sand032" in out and "sand032-l0-baseline" in out and "$0.4200" in out


def test_cli_watch_follow_file_tracks_current_config(tmp_path, monkeypatch, capsys):
    """One terminal pane follows whichever SAND-032 run is current."""
    from mailroom_sandbox.cli import main
    from mailroom_sandbox.job import spec as spec_mod
    from mailroom_sandbox.paths import config_dir

    monkeypatch.setattr(spec_mod, "runs_root", lambda: tmp_path)
    follow = tmp_path / "current"
    follow.write_text(str(config_dir() / "runs" / "sand032-s3-merger50.yaml") + "\n")
    rc = main(["watch", "--follow", str(follow), "--once", "--no-logs"])
    out = strip_ansi(capsys.readouterr().out)
    assert rc == 0 and "sand032-s3-merger50" in out and "SWEEP" in out


def test_cli_watch_requires_config_or_follow(capsys):
    from mailroom_sandbox.cli import main

    assert main(["watch", "--once", "--no-logs"]) == 2


def test_ledger_with_live_fleet_is_not_double_counted(tmp_path):
    from mailroom_sandbox.watch import read_ledger

    p = tmp_path / "l.json"
    p.write_text(json.dumps({"spent_usd": 1.5, "includes_live": True}))
    assert read_ledger(p) == (1.5, True)
    p.write_text(json.dumps({"spent_usd": 0.5}))
    assert read_ledger(p) == (0.5, False)
    assert read_ledger(tmp_path / "missing.json") == (0.0, False)
