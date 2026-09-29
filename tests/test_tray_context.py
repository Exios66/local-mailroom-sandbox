"""Tray TUI job-aware layout (network-free)."""

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.tui import tray_context as tc
from mailroom_sandbox.watch import compose_watch_state, LogBuffer


def _generic_store(tmp_path) -> RunStore:
    s = RunStore(tmp_path / "run-20-correspondence-awq")
    s.write_lock(
        {
            "run_id": "run-20-correspondence-awq",
            "task": "correspondence_specialist",
            "profile": "modal-vllm",
            "engine": {
                "model": "Qwen/Qwen3-8B-AWQ",
                "vllm": {"quantization": "awq", "kv_cache_dtype": "fp8"},
                "modal": {"gpu": "L4", "max_containers": 1, "app": "sandbox-vllm"},
            },
            "job": {"mode": "endpoint", "concurrency": 8, "cost_cap_usd": 0.55},
        }
    )
    s.write_checkpoint(state="running", cursor=4, total=20, remote=None)
    s.append_event("preflight_ok", "info")
    return s


def test_build_layout_uses_lock_not_sand032_defaults(tmp_path):
    store = _generic_store(tmp_path)
    layout = tc.build_tray_layout(
        store, app="sandbox-vllm", times_dir=None, cap_usd=5.0, gate_usd=4.5
    )
    assert layout["profile"] == "modal-vllm"
    assert layout["job_mode"] == "endpoint"
    assert "Qwen3-8B-AWQ" in layout["subtitle"]
    assert layout["route_label"] == "INBOX → SPECIALIST → REPORT"
    assert layout["job_route"] is not None
    assert layout["route"] is None
    assert layout["panels"]["tray"].startswith("Tray TUI")
    assert layout["cap_usd"] == 0.55


def test_lifecycle_from_checkpoint_when_no_driver_times(tmp_path):
    store = _generic_store(tmp_path)
    life = tc.lifecycle_from_store(store, [], now=__import__("time").time())
    assert life["phase"] == "SORTING"
    assert "correspondence_specialist" in life["detail"]


def test_compose_state_includes_layout_and_job_route(tmp_path):
    store = _generic_store(tmp_path)
    state = compose_watch_state(
        store=store,
        app="sandbox-vllm",
        sink=LogBuffer(None),
        ledger=None,
        cap_usd=5.0,
        times_dir=None,
        serving_dir=tmp_path / "serving",
        started=__import__("time").time(),
        boot_mark={},
    )
    assert state["layout"]["profile"] == "modal-vllm"
    assert state["job_route"]
    assert state["watcher_label"].startswith("Tray TUI watcher")
    assert "animate_lifecycle" in state


def test_resolve_watch_paths_prefers_run_dir_log(tmp_path):
    store = _generic_store(tmp_path)
    td, log_path = tc.resolve_watch_paths(store, sand032_root=tmp_path / "sand032")
    assert td is None
    assert log_path == store.dir / "modal-app.log"
