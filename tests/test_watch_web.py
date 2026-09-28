"""Browser mailroom watch UI — payload + HTTP handlers (network-free)."""

import json
from http.client import HTTPConnection
from threading import Thread

from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.tui import web as web_mod
from mailroom_sandbox.watch import LogBuffer, compose_watch_state


def _store(tmp_path, *, replicas=2):
    s = RunStore(tmp_path / "sand032-x")
    s.write_lock(
        {
            "run_id": "sand032-x",
            "task": "correspondence_specialist",
            "engine": {
                "model": "Qwen/Qwen3-8B-AWQ",
                "vllm": {"kv_cache_dtype": "fp8"},
                "modal": {"gpu": "L4", "max_containers": replicas, "min_containers": replicas},
            },
            "job": {"concurrency": 16},
        }
    )
    s.write_checkpoint(state="running", cursor=3, total=10, remote=None)
    for i, (ok, lat) in enumerate([(True, 1000.0), (True, 3000.0), (False, 500.0)]):
        s.append_item(
            {
                "item_id": f"d{i}",
                "ok": ok,
                "latency_ms": lat,
                "error": None if ok else "OpenAIConnectionError: x",
                "score": {"overall_extraction_score": 0.5} if ok else {},
            }
        )
    return s


def test_compose_watch_state_is_json_friendly(tmp_path):
    store = _store(tmp_path)
    sink = LogBuffer(None)
    sink.append("vLLM ready on port 8000")
    sink.append("ERROR boom")
    state = compose_watch_state(
        store=store,
        app="sandbox-vllm-sand032",
        sink=sink,
        ledger=None,
        cap_usd=5.0,
        times_dir=None,
        serving_dir=tmp_path / "serving",
        started=__import__("time").time() - 60,
        boot_mark={},
    )
    raw = json.dumps(state)
    data = json.loads(raw)
    assert data["snapshot"]["run_id"] == "sand032-x"
    assert data["spend"]["cap_usd"] == 5.0
    assert len(data["logs"]) == 2
    assert data["logs"][1]["role"] == "error"
    assert data["progress"]["done"] == 3


def test_should_open_browser_respects_no_browser(monkeypatch):
    monkeypatch.delenv("NO_BROWSER", raising=False)
    assert web_mod.should_open_browser(stream=type("S", (), {"isatty": lambda self: True})())
    monkeypatch.setenv("NO_BROWSER", "1")
    assert not web_mod.should_open_browser(stream=type("S", (), {"isatty": lambda self: True})())


def test_browser_url_maps_wildcard_bind():
    assert web_mod.browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765/"


def test_web_handler_serves_index_and_state(tmp_path):
    store = _store(tmp_path)

    def resolve():
        return store, "sandbox-vllm-test"

    session = web_mod.WatchWebSession(
        resolve=resolve,
        ledger=None,
        cap_usd=5.0,
        times_dir=None,
        log_path=None,
        serving_dir=tmp_path / "serving",
        interval=0.05,
        follow_logs=False,
    )
    session.refresh()
    handler = web_mod.make_handler(session)
    httpd = web_mod.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read()
        assert b"THE MAILROOM" in body
        assert b"text/event-stream" not in body

        conn.request("GET", "/api/state")
        resp = conn.getresponse()
        assert resp.status == 200
        state = json.loads(resp.read().decode())
        assert state["ok"] is True
        assert state["app"] == "sandbox-vllm-test"
    finally:
        session.stop()
        httpd.shutdown()
        httpd.server_close()
