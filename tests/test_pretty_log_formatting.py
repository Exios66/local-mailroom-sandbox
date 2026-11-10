"""Deterministic formatting for the vendored Mailroom TUI primitives."""
from __future__ import annotations

import json
import shutil

import pytest

from mailroom_sandbox.tui import pretty_log as pl


def _plain(value: str) -> str:
    return pl._ANSI_RE.sub("", value)


def test_ansi_helpers_and_palette():
    assert pl._c("31", "x", on=True) == "\033[31mx\033[0m"
    assert pl._c("31", "x", on=False) == "x"
    assert pl._rgb((1, 2, 3)) == "38;2;1;2;3"
    assert pl._rgb_bg((1, 2, 3)) == "48;2;1;2;3"
    assert pl._visible_len("\033[31mabc\033[0m") == 3

    class Tty:
        def isatty(self):
            return True

    assert pl.use_color(Tty()) is True
    assert pl.use_color(object()) is False
    import io

    assert pl.use_color(io.StringIO()) is False
    assert pl.palette(False)["gold"]("x") == "x"
    assert "\033[" in pl.palette(True)["gold"]("x")


def test_brand_strings_and_markers():
    assert "plurality" in pl.mailroom_tagline()
    assert "▸TRAIN◂" in pl.mailroom_pipeline_hint("TRAIN")
    assert "TEST" in pl.mailroom_pipeline_hint("GATE")
    assert pl.mailroom_route_banner() == "INBOX → SORTER → TRAY"
    assert pl.stage_gremlin("TRAIN") == ""
    assert pl.stage_gremlin("unknown") == ""


def test_owl_and_emoticon_rendering():
    assert pl.render_owl(on=False) == pl.OWL_FULL_OPEN
    assert pl.render_owl(mini=True, on=False, blink=True) == pl.OWL_MINI_BLINK
    assert pl.render_owl_pixels(pl.OWL_FULL_OPEN, on=False) == pl.OWL_FULL_OPEN
    assert "\033[" in pl.render_owl(on=True)[0]
    assert pl.owl_width() == len(pl.OWL_FULL_OPEN[0])
    assert pl.owl_width(mini=True) == len(pl.OWL_MINI_OPEN[0])
    assert pl.owl_emoticon() == "(o,o)"
    assert pl.owl_emoticon(blink=True) == "(-,-)"
    assert "\033[" in pl.owl_emoticon(on=True)


def test_loading_status_and_layout_helpers():
    assert "waiting" in pl._loading_status_line(None, None)
    assert "sorting" in pl._loading_status_line(2, 5)
    assert "held-out" in pl._loading_status_line(5, 5)
    assert "\033[" in pl._loading_status_line(2, 5, on=True)

    assert pl._panel_width(40) == 40
    assert pl._panel_width(80) == 80
    assert pl._panel_width(200) == pl.MAX_W
    assert pl._layout(120, 40) == "wide"
    assert pl._layout(80, 24) == "medium"
    assert pl._layout(60, 24) == "narrow"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pl.shutil, "get_terminal_size", lambda fallback=None: shutil.os.terminal_size((100, 30)))
    assert pl._term_size() == (100, 30)
    monkeypatch.setattr(pl.shutil, "get_terminal_size", lambda fallback=None: (_ for _ in ()).throw(OSError()))
    assert pl._term_size() == (80, 24)
    monkeypatch.undo()


def test_progress_epoch_and_visible_width_helpers():
    assert pl.epoch_strip(None, 3) == ""
    assert pl.epoch_strip(2, 0) == ""
    assert pl.epoch_strip(5, 3) == "epoch [███] 3/3"
    assert pl.progress_bar(None, 3) == ""
    assert pl.progress_bar(0, 3) == ""
    assert pl.progress_bar(2, 4, width=4) == "micro [██░░] 50.0% (2/4)"
    assert "▓" in pl.progress_bar(3, 4, width=4, tick=1, on=True)
    assert pl._pad_visible("x", 3) == "x  "
    colored = pl._c("31", "abcd", on=True)
    assert pl._visible_len(pl._truncate_visible(colored, 3)) <= 3
    assert pl._truncate_visible("abcd", 3) == "ab…"


def test_wordmark_fonts_and_composition():
    with pytest.raises(AssertionError):
        pl._assert_uniform_font({"A": ["x"], "B": ["y", "z"]})
    with pytest.raises(AssertionError):
        pl._assert_uniform_font({"A": ["xx"], "B": ["y"]})
    normalized = pl._normalize_font({"A": ["x", "xx"]})
    assert normalized["A"] == ["x ", "xx"]
    face = pl._face_bitmap("A?", pl._WM_FONT_3)
    assert len(face) == 5 and all(len(row) == len(face[0]) for row in face)
    assert pl._extrude_roles([]) == []
    roles = pl._extrude_roles(["█"])
    assert len(roles) == 2 and all(len(row) == 2 for row in roles)
    assert pl._paint_extrude_cell(" ", on=False) == " "
    assert pl._paint_extrude_cell(pl._ROLE_EXTRUDE, on=False) == "▓"
    assert pl._paint_extrude_cell(pl._ROLE_HIGHLIGHT, on=False) == "█"
    assert "\033[" in pl._paint_extrude_cell(pl._ROLE_FACE, on=True)
    wordmark = pl._compose_wordmark("HI", pl._WM_FONT_3, on=False)
    assert wordmark and all(pl._visible_len(row) == pl._visible_len(wordmark[0]) for row in wordmark)
    stacked = pl._stack_centered([["xx"], ["x"]])
    assert stacked == ["xx", "x "]
    wide, row, stack = pl._wordmark_variants(on=False)
    assert wide and row and stack
    assert pl._pick_mark(200, on=False, prefer_stack=False) == wide
    assert pl._pick_mark(20, on=False, prefer_stack=False) == row
    assert pl._join_owl_wordmark(["x"], ["yy"], budget=1, stacked=True)
    assert len(pl._wordmark_lines(inner=40, on=False, compact=True)) >= 3


def test_header_status_box_and_metric():
    banner = pl.render_header_banner(run_tag="run-1", on=False)
    assert banner[0].startswith("╔") and banner[-1].startswith("╚")
    assert any("DIGITAL MAILROOM" in line for line in banner)
    assert "\033[" in pl.render_header_banner(run_tag="run-1", on=True)[0]
    compact = pl.render_header_banner(run_tag=None, on=False, width=40, compact=True)
    assert compact

    status = pl.render_status_bar(timestamp="12:00", stage="TRAIN", on=False)
    assert "watch @ 12:00" in status and "TRAIN" in status
    assert "\033[" in pl.render_status_bar(timestamp="12:00", stage="TRAIN", on=True)

    box = pl._box("Title", ["one", "two"], on=False)
    assert "Title" in box and "one" in box
    long_box = pl._box("T" * 80, ["x" * 200], on=False)
    assert "…" in long_box
    assert "\033[" in pl._box("Title", ["one"], on=True)
    plain_metric = pl._metric("loss", "0.1", on=False)
    assert "loss" in plain_metric and "0.1" in plain_metric
    assert "\033[" in pl._metric("loss", "0.1", on=True)


def test_formatters():
    assert pl.fmt_loss(None) == "—"
    assert pl.fmt_loss(0.1234) == "0.1234"
    assert pl.fmt_rate(None, "steps/s") == "— steps/s"
    assert pl.fmt_rate(2.345, "steps/s") == "2.35 steps/s"
    assert pl.fmt_f1(None) == "—" and pl.fmt_f1("bad") == "—" and pl.fmt_f1("0.5") == "0.5000"
    assert pl.fmt_lr(None) == "—" and pl.fmt_lr("bad") == "—" and pl.fmt_lr(0.001) == "1.00e-03"
    assert pl.fmt_progress(None, 3) == ""
    assert pl.fmt_loss_delta(None, 1) == ""
    assert pl.fmt_loss_delta("bad", 1) == ""
    assert pl.fmt_loss_delta(0.2, 0.1) == " (Δ +0.1000)"
    assert pl.fmt_loss_delta(0.1, 0.2) == " (Δ -0.1000)"
    assert pl.step_spark(0) == "" and pl.step_spark(1) == " ·" and pl.step_spark(500) == " ·"
    assert pl._fmt_duration(None) == "—"
    assert pl._fmt_duration("bad") == "—"
    assert pl._fmt_duration(3661) == "1h 1m 1s"
    assert pl._fmt_mem("bad") == "—" and pl._fmt_mem(512) == "512M" and pl._fmt_mem(2048) == "2.0G"


def test_jsonl_readers_and_log_parsers(tmp_path):
    assert pl.read_last_jsonl(tmp_path / "missing") is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n")
    assert pl.read_last_jsonl(empty) is None
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not-json\n")
    assert pl.read_last_jsonl(bad) is None
    rows = tmp_path / "rows.jsonl"
    rows.write_text('{"a": 1}\n{"b": 2}\n')
    assert pl.read_last_jsonl(rows) == {"b": 2}
    assert pl.read_last_two_jsonl(rows) == ({"a": 1}, {"b": 2})
    one = tmp_path / "one.jsonl"
    one.write_text('{"a": 1}\n')
    assert pl.read_last_two_jsonl(one) == (None, {"a": 1})
    assert pl.read_last_two_jsonl(bad) == (None, None)

    step = pl.parse_log_step_line("step 5 loss 0.1234 2.5 steps/s 10.0 samples/s ETA 00:10")
    assert step == {"event": "step", "step": 5, "loss": 0.1234, "steps_per_sec": 2.5,
                    "samples_per_sec": 10.0, "eta": "00:10"}
    assert pl.parse_log_step_line("nope") is None
    test_step = pl.parse_log_test_step_line("test doc 3/10 doc_type_acc 0.9 subclass_cond 0.8")
    assert test_step["doc_done"] == 3 and test_step["subclass_acc_conditional"] == 0.8
    assert pl.parse_log_test_step_line("test doc 3/10 doc_type_acc 0.9").get("subclass_acc_conditional") is None
    assert pl.parse_log_test_step_line("nope") is None
    metrics = pl.parse_log_test_metrics_line("test metrics: {'n_docs': 10, 'doc_type_acc': 0.9}")
    assert metrics == {"event": "test_complete", "n_docs": 10, "doc_type_acc": 0.9}
    assert pl.parse_log_test_metrics_line("test metrics: [1]") is None
    assert pl.parse_log_test_metrics_line("test metrics: {bad") is None


def test_summary_helpers_and_completion(tmp_path):
    assert pl._load_summary_dict(None) is None
    assert pl._load_summary_dict(tmp_path / "missing") is None
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    assert pl._load_summary_dict(bad) is None
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps({"hyperparameters": {"eval_test": True}, "epochs": [{"loss": 1}], "epochs_run": 1}))
    summary = pl._load_summary_dict(summary_file)
    assert summary and pl._eval_test_enabled(summary)
    assert pl._eval_test_enabled({"eval_test": True})
    assert pl._eval_test_enabled(None) is False
    assert pl._test_eval_pending(summary) is True
    assert pl._test_eval_pending({"hyperparameters": {"eval_test": True}, "test_metrics": {"n_docs": 2}}) is False
    assert pl._training_epochs_done(summary, None) is True
    assert pl._training_epochs_done(None, None) is False
    assert pl._active_stage({"event": "epoch"}, None) == "VAL"
    assert pl._active_stage(None, {"event": "epoch"}) == "VAL"
    assert pl._active_stage({"event": "step"}, None) == "TRAIN"
    assert pl._filter_trainers_for_run(["runs/a/x", "runs/b/x"], "a") == ["runs/a/x"]
    assert pl._filter_trainers_for_run(["x"], None) == ["x"]
    assert pl._planned_epoch_count({"epochs_requested": 3}, None) == 3
    assert pl._planned_epoch_count({"epochs": []}, {"epochs": 2}) == 2
    assert pl._planned_epoch_count({"epochs": 4}, None) == 4
    assert pl._planned_epoch_count({}, None) is None
    assert pl._last_epoch_record({"epochs": [{"a": 1}, "bad"]}) == {}
    assert pl._last_epoch_record({"epochs": [{"a": 1}]}) == {"a": 1}
    assert pl._training_wall_s({"training_wall_s": "12.5"}) == 12.5
    assert pl._training_wall_s({"wall_s": "bad"}) is None
    assert pl._trainer_pid("123 args") == 123
    assert pl._trainer_pid("bad") is None
    assert pl._trainer_pid(None) is None

    assert pl.job_completed_summary(
        run_tag="r", trainer_lines=["1 x"], jsonl_row=None, log_tail=[], summary_path=None
    ) is None
    assert pl.job_completed_summary(
        run_tag="r", trainer_lines=[], jsonl_row=None, log_tail=["run summary:"], summary_path=None
    ) == {}
    completed = pl.job_completed_summary(
        run_tag="r", trainer_lines=[], jsonl_row=None, log_tail=["run summary:"], summary_path=summary_file
    )
    assert completed == summary
    assert pl._step_row_for_display({"micro_planned": 5, "micro_done": 1}, summary=summary, trainer_lines=[]) == {
        "micro_planned": 5, "micro_done": 1
    }
    patched = pl._step_row_for_display(
        {"micro_planned": 5, "micro_done": 1}, summary=summary, trainer_lines=["1 x"]
    )
    assert patched["micro_done"] == 5 and patched["eta"] == "test eval"


def test_event_renderers_plain_and_colored():
    step = {"event": "step", "step": 7, "loss": 0.5, "epoch": 2, "epochs": 3,
            "micro_done": 1, "micro_planned": 4, "steps_per_sec": 2.0,
            "samples_per_sec": 8.0, "wall_s": 12, "eta": "00:05"}
    plain = pl.render_step_event(step, on=False, prev_row={"loss": 0.6})
    assert "step 7" in plain and "loss 0.5000" in plain and "Δ -0.1000" in plain
    colored = pl.render_step_event(step, on=True, tick=1, show_owl=True)
    assert "\033[" in colored and "step 7" in _plain(colored)
    assert "step 7" in _plain(pl.render_step_event(step, on=False, show_owl=True))

    epoch = {"event": "epoch", "epoch": 2, "epochs": 3, "loss": 0.5, "val_loss": 0.4,
             "lr": 0.001, "doc_type_window_acc": 0.9, "doc_type_doc_acc": 0.8,
             "doc_type_macro_f1_observed": 0.7, "doc_type_ece": 0.1,
             "doc_type_ece_calibrated": 0.05, "selected_this_epoch": True,
             "gate_met": True, "selection_epoch": 2, "epoch_wall_s": 30,
             "per_head_macro_f1_observed": {"a": 0.9}, "subclass_objective": 0.6}
    plain = pl.render_epoch_event(epoch, on=False, show_owl=True)
    assert "epoch 2" in plain and "val" in plain and "selected" in plain
    assert "\033[" in pl.render_epoch_event(epoch, on=True)

    test_step = {"event": "test_step", "doc_done": 3, "doc_planned": 10, "doc_type_acc": 0.9,
                 "subclass_acc_conditional": 0.8, "wall_s": 5}
    plain = pl.render_test_step_event(test_step, on=False, prev_row={"doc_type_acc": 0.8})
    assert "test doc 3/10" in plain and "Δ +0.1000" in plain
    assert "\033[" in pl.render_test_step_event(test_step, on=True)

    metrics = {"event": "test_complete", "n_docs": 10, "doc_type_acc": 0.9,
               "subclass_acc_conditional": 0.8, "doc_type_correct": 9,
               "subclass_correct": 8, "subclass_scorable": 10,
               "subclass_unscorable": 1, "wall_s": 20}
    plain = pl.render_test_metrics_event(metrics, on=False)
    assert "TEST complete" in plain and "unscorable" in plain
    assert "\033[" in pl.render_test_metrics_event(metrics, on=True)


def test_hardware_panel_and_resources(monkeypatch):
    class Result:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        if cmd[0] == "nvidia-smi":
            return Result("0, NVIDIA L4, 55, 1000, 24000, 50, 25.5\n")
        if cmd[0] == "ps":
            return Result("12.5 2048\n")
        return Result()

    monkeypatch.setattr(pl.subprocess, "run", fake_run)
    resources = pl.sample_resources(lock_line="123 args")
    assert resources["gpu_name"] == "NVIDIA L4" and resources["cpu_pct"] == "12.5"
    assert resources["rss"] == "2M" and resources["pid"] == 123

    assert "unavailable" in pl.render_hardware_panel(None, on=False)
    assert "unavailable" in pl.render_hardware_panel(None, on=False, compact=True)
    assert "NVIDIA L4" in pl.render_hardware_panel(resources, on=False)
    assert "HW" in pl.render_hardware_panel(resources, on=False, compact=True)
    assert "\033[" in pl.render_hardware_panel(resources, on=True)
    assert pl._side_by_side("a\nb", "x").startswith("a  x")


def test_watch_snapshot_renders_narrow_and_wide():
    narrow = pl.render_watch_snapshot(
        timestamp="12:00", lock_line=None, trainer_lines=[], log_tail=[],
        jsonl_row={"event": "step", "step": 2, "loss": 0.4}, run_tag="run-1",
        on=False, width=60, height=20,
    )
    assert "watch @ 12:00" in narrow and "run-1" in narrow and "HW" in narrow
    wide = pl.render_watch_snapshot(
        timestamp="12:00", lock_line="123 run-1", trainer_lines=[], log_tail=[],
        jsonl_row={"event": "epoch", "epoch": 1, "epochs": 2, "loss": 0.4},
        run_tag="run-1", on=False, width=120, height=40,
    )
    assert "epoch 1" in wide and "HARDWARE" in wide
    done = pl.render_watch_snapshot(
        timestamp="12:00", lock_line=None, trainer_lines=[], log_tail=[],
        jsonl_row=None, run_tag=None, on=False, width=80, height=24,
        summary_path=None,
    )
    assert "lock: (none)" in done


def test_completed_banner_and_pending_panel(monkeypatch):
    summary = {
        "run_id": "run-1",
        "hyperparameters": {"loss_lambda_dt": 0.25},
        "epochs_run": 2,
        "epochs_requested": 3,
        "training_wall_s": 7200,
        "epochs": [{
            "doc_type_macro_f1_observed": 0.91,
            "doc_type_ece_calibrated": 0.04,
            "gate_met": True,
            "subclass_objective": 0.87,
            "contract_macro_f1": 0.9,
            "correspondence_macro_f1": 0.8,
            "corporate_record_macro_f1": 0.7,
            "merger_agreement_macro_f1": 0.6,
        }],
        "test_metrics": {"doc_type_acc": 0.93, "subclass_acc_conditional": 0.88, "n_docs": 10},
    }
    monkeypatch.setattr(pl, "_load_eval_report", lambda tag: {
        "doc_type_accuracy": 0.92, "fast_path_rate": 0.5, "ood": {"rate": 0.1}
    })
    lines = pl.job_completed_banner_lines(summary, run_tag="run-1")
    text = "\n".join(lines)
    assert "JOB COMPLETED" in text and "2/3 epochs" in text
    assert "selection gate PASS" in text and "test doc_type acc" in text
    assert "eval harness acc" in text and "complete_run done" in text
    assert "UNCALIBRATED" not in text

    failed = pl.job_completed_banner_lines(
        {**summary, "checkpoint_selection": {"gate_met": False}}, run_tag="run-1"
    )
    assert "UNCALIBRATED" in "\n".join(failed)
    gate_failed = {**summary, "epochs": [{**summary["epochs"][0], "gate_met": False}]}
    assert "FAIL" in pl.render_job_completed_banner(gate_failed, run_tag="run-1", on=False, width=120)
    assert "\033[" in pl.render_job_completed_banner(gate_failed, run_tag="run-1", on=True, width=120)
    assert "held-out test eval running" in pl.render_test_eval_pending_panel(
        {"test_metrics": {"n_docs": 12}}, on=False, width=60
    )
    assert "323 docs" in pl.render_test_eval_pending_panel(None, on=False, width=60)


def test_discover_trainers_and_watch_completion_states(monkeypatch, tmp_path):
    class Result:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd, **kwargs):
        if cmd[0] == "pgrep":
            return Result("111\n222\n")
        if cmd[0] == "ps":
            return Result("python training/train_modernbert.py --run runs/run-1/x" if cmd[-1] == "111" else "other")
        return Result()

    monkeypatch.setattr(pl.subprocess, "run", fake_run)
    assert pl.discover_trainer_lines("run-1") == ["111 python training/train_modernbert.py --run runs/run-1/x"]
    assert pl.discover_trainer_lines(None) == []

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({
        "epochs_run": 1, "epochs_requested": 1,
        "test_metrics": {"n_docs": 10, "doc_type_acc": 0.9},
    }))
    done = pl.render_watch_snapshot(
        timestamp="12:00", lock_line=None, trainer_lines=[], log_tail=[],
        jsonl_row=None, run_tag="run-1", on=False, width=80, height=24,
        summary_path=summary_path,
    )
    assert "JOB COMPLETED" in done

    test_row = {"event": "test_step", "doc_done": 2, "doc_planned": 10, "doc_type_acc": 0.9}
    testing = pl.render_watch_snapshot(
        timestamp="12:00", lock_line=None, trainer_lines=[], log_tail=[],
        jsonl_row={"event": "step", "step": 2, "loss": 0.4}, test_jsonl_row=test_row,
        run_tag="run-1", on=False, width=80, height=24,
    )
    assert "test doc 2/10" in testing
