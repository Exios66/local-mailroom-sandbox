"""`sandbox floor`: argparse wiring, the builder's callable API, the stat-sweep skip and the port default.

Offline: no LLM and no run launch. The one socket test binds an ephemeral loopback port.
"""

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.tui import floor_app

STUB_GRAPH = '''
def build():
    workflow = StateGraph(dict)
    workflow.add_node("intake", traced_node("intake")(_bounded(intake_node)))
    workflow.add_node("archive", traced_node("archive")(_bounded(archive_node)))
    workflow.add_edge(START, "intake")
    workflow.add_edge("intake", "archive")
    workflow.add_edge("archive", END)
    return workflow.compile()
'''


@pytest.fixture
def store(tmp_path):
    """A one-run store plus a stub graph file; returns (base, graph, run_dir)."""
    graph = tmp_path / "build_graph.py"
    graph.write_text(STUB_GRAPH, encoding="utf-8")
    run = tmp_path / "data" / "runtime" / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "items.jsonl").write_text(json.dumps({"item_id": "d1", "ok": True, "stage": "archived"}) + "\n", encoding="utf-8")
    (run / "nodes.jsonl").write_text(
        "".join(json.dumps({"doc": "d1", "node": n, "status": s}) + "\n"
                for n in ("intake", "archive") for s in ("running", "done")), encoding="utf-8")
    (run / "checkpoint.json").write_text(json.dumps({"state": "running", "cursor": 1, "total": 2}), encoding="utf-8")
    return tmp_path / "data", graph, run


# ── argparse wiring ─────────────────────────────────────────────────────────────


def test_floor_is_registered_with_documented_flags(capsys):
    args = cli.build_parser().parse_args(["floor"])
    assert args.handler is cli._cmd_floor
    assert (args.target, args.run, args.base, args.port, args.interval) == (None, None, None, None, 5.0)
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["floor", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--base", "--port", "--interval", "--run"):
        assert flag in out, flag
    assert "floor" in cli.build_parser().format_help()


def test_floor_flag_parsing_and_validation():
    a = cli.build_parser().parse_args(["floor", "run-9", "--base", "/x/y", "--port", "0", "--interval", "0.5"])
    assert (a.target, a.base, a.port, a.interval) == ("run-9", "/x/y", 0, 0.5)
    for bad in (["--port", "65536"], ["--interval", "0"], ["--interval", "-1"]):
        with pytest.raises(SystemExit) as exc:
            cli.build_parser().parse_args(["floor", *bad])
        assert exc.value.code == 2


def test_port_default_clears_the_claimed_tui_slots():
    from mailroom_sandbox.tui import board, web

    assert floor_app.DEFAULT_PORT == 8769
    assert floor_app.DEFAULT_PORT not in (web.DEFAULT_PORT, board.DEFAULT_PORT, 8766, 8768)
    assert floor_app.DEFAULT_HOST == "127.0.0.1"


def test_dispatch_passes_defaults_and_run_to_serve_floor(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: seen.append(kw) or 0)
    monkeypatch.delenv("MAILROOM_BASE_DIR", raising=False)
    assert cli.main(["floor", "--base", str(tmp_path), "run-a"]) == 0
    assert seen[-1] == {"base": tmp_path, "port": 8769, "interval": 5.0, "run": "run-a"}
    assert cli.main(["floor", "--run", "run-b", "--port", "0", "--interval", "2"]) == 0
    assert (seen[-1]["port"], seen[-1]["interval"], seen[-1]["run"]) == (0, 2.0, "run-b")
    assert seen[-1]["base"] == floor_app.resolve_base(None)


def test_target_and_run_must_agree(monkeypatch, capsys):
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: pytest.fail("must not serve"))
    assert cli.main(["floor", "run-a", "--run", "run-b"]) == 2
    assert "different runs" in capsys.readouterr().err
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: 0)
    assert cli.main(["floor", "run-a", "--run", "run-a"]) == 0


def test_base_resolution_flag_then_env_then_repo_data(monkeypatch, tmp_path):
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "env"))
    assert floor_app.resolve_base(str(tmp_path / "flag")) == tmp_path / "flag"
    assert floor_app.resolve_base(None) == (tmp_path / "env").resolve()
    monkeypatch.delenv("MAILROOM_BASE_DIR")
    assert floor_app.resolve_base(None).name == "data"


def test_floor_url_deep_selects_a_run():
    assert floor_app.floor_url(8769) == "http://127.0.0.1:8769/floor.template.html"
    assert floor_app.floor_url(1, "a b/c") == "http://127.0.0.1:1/floor.template.html?run=a%20b%2Fc"


# ── digest build API ────────────────────────────────────────────────────────────


def test_build_emits_both_files(store, tmp_path):
    base, graph, _ = store
    out = tmp_path / "out"
    digest, json_path, js_path = floor_app.build(base, out, graph)
    assert json_path == out / "floor_digest.json" and js_path == out / "floor_digest.js"
    assert json.loads(json_path.read_text(encoding="utf-8")) == digest
    assert js_path.read_bytes() == b"window.DIGEST=" + json_path.read_bytes() + b";\n"
    run = digest["runs"][0]
    assert run["name"] == "run-1" and run["state"] == "running" and run["inflight"] == {}


def test_build_reports_no_runs_with_the_builders_exit_code(tmp_path):
    builder = floor_app.load_builder()
    graph = tmp_path / "g.py"
    graph.write_text(STUB_GRAPH, encoding="utf-8")
    with pytest.raises(builder.DigestError) as exc:
        floor_app.build(tmp_path / "empty", tmp_path / "out", graph)
    assert exc.value.code == builder.EXIT_NO_RUNS


# ── stat-sweep skip ─────────────────────────────────────────────────────────────


def _counting(monkeypatch):
    calls = []
    monkeypatch.setattr(floor_app, "build", lambda base, out, graph=None: calls.append(1))
    return calls


def test_idle_floor_skips_rebuild_until_an_artifact_changes(store, monkeypatch, tmp_path):
    base, _, run = store
    calls = _counting(monkeypatch)
    r = floor_app.DigestRefresher(base, tmp_path / "out")
    assert r.refresh() is True and len(calls) == 1, "first sweep always builds"
    assert r.refresh() is False and r.refresh() is False and len(calls) == 1, "idle -> no rebuild"
    with open(run / "nodes.jsonl", "a", encoding="utf-8") as fh:  # a node record lands
        fh.write(json.dumps({"doc": "d2", "node": "intake", "status": "running"}) + "\n")
    assert r.refresh() is True and len(calls) == 2
    assert r.refresh() is False and len(calls) == 2


def test_new_run_dir_and_unrelated_files_in_the_sweep(store, monkeypatch, tmp_path):
    base, _, run = store
    calls = _counting(monkeypatch)
    r = floor_app.DigestRefresher(base, tmp_path / "out")
    r.refresh()
    (run / "notes.txt").write_text("not a run artifact", encoding="utf-8")
    assert r.refresh() is False, "files outside RUN_ARTIFACTS do not trigger a rebuild"
    new = base / "run-history" / "run-0"
    new.mkdir(parents=True)
    assert r.refresh() is True and len(calls) == 2, "a new run dir triggers one"
    assert floor_app.scan_signature(tmp_path / "missing") == ()


def test_failed_rebuild_is_retried_and_only_the_first_is_fatal(store, monkeypatch, tmp_path):
    base, _, run = store
    state = {"fail": False, "n": 0}

    def flaky(base, out, graph=None):
        state["n"] += 1
        if state["fail"]:
            raise OSError("file busy")

    monkeypatch.setattr(floor_app, "build", flaky)
    r = floor_app.DigestRefresher(base, tmp_path / "out")
    assert r.refresh() is True
    (run / "checkpoint.json").write_text(json.dumps({"state": "complete"}), encoding="utf-8")
    state["fail"] = True
    assert r.refresh() is False and "file busy" in r.last_error
    assert r.refresh() is False and state["n"] == 3, "signature not advanced -> retried"
    state["fail"] = False
    assert r.refresh() is True and r.last_error is None
    first = floor_app.DigestRefresher(base, tmp_path / "out")
    state["fail"] = True
    with pytest.raises(OSError):
        first.refresh()


def test_refresher_thread_stops_promptly(store, monkeypatch, tmp_path):
    base, _, _ = store
    _counting(monkeypatch)
    stop = threading.Event()
    t = threading.Thread(target=floor_app.DigestRefresher(base, tmp_path / "out").run, args=(stop, 0.1))
    t.start()
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive()


# ── serving ─────────────────────────────────────────────────────────────────────


def test_serve_floor_fails_fast_without_binding_when_first_build_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(floor_app, "make_server", lambda *a, **k: pytest.fail("must not bind"))
    monkeypatch.setenv("FLOOR_DIGEST_GRAPH", str(tmp_path / "missing_graph.py"))
    rc = floor_app.serve_floor(base=tmp_path / "empty", out=tmp_path / "out")
    assert rc != 0 and "sandbox floor: error:" in capsys.readouterr().err


def test_server_binds_loopback_and_serves_the_page_uncached(tmp_path):
    (tmp_path / "floor.template.html").write_text("<html>floor</html>", encoding="utf-8")
    httpd = floor_app.make_server(tmp_path, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        host, port = httpd.server_address[:2]
        assert host == "127.0.0.1"
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/floor.template.html?run=x")
        resp = conn.getresponse()
        assert resp.status == 200 and resp.read() == b"<html>floor</html>"
        assert resp.getheader("Cache-Control") == "no-store"
        conn.request("GET", "/nope")
        assert conn.getresponse().status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=3)


def test_template_reads_run_and_class_query_params():
    html = (Path(floor_app.dashboard_dir()) / "floor.template.html").read_text(encoding="utf-8")
    assert 'URLSearchParams(location.search)' in html and 'q.get("run")' in html and 'q.get("class")' in html
