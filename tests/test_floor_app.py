"""`sandbox floor`: argparse wiring, the builder's callable API, the stat-sweep skip and the port default.

Offline: no LLM and no run launch. The one socket test binds an ephemeral loopback port.
"""

import hashlib
import json
import threading
import time
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
    """`sandbox floor` is wired to `_cmd_floor` with its documented flags and default port."""
    args = cli.build_parser().parse_args(["floor"])
    assert args.handler is cli._cmd_floor
    assert (args.target, args.run, args.base, args.port, args.interval, args.replay) == (None, None, None, None, 5.0, False)
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["floor", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--base", "--port", "--interval", "--run", "--replay"):
        assert flag in out, flag
    assert "floor" in cli.build_parser().format_help()
    assert f"default {floor_app.DEFAULT_PORT};" in " ".join(out.split()), "--port help must derive from DEFAULT_PORT"


def test_floor_flag_parsing_and_validation():
    """Flags parse as documented; an out-of-range port or interval exits 2."""
    a = cli.build_parser().parse_args(["floor", "run-9", "--base", "/x/y", "--port", "0", "--interval", "0.5"])
    assert (a.target, a.base, a.port, a.interval) == ("run-9", "/x/y", 0, 0.5)
    for bad in (["--port", "65536"], ["--interval", "0"], ["--interval", "-1"]):
        with pytest.raises(SystemExit) as exc:
            cli.build_parser().parse_args(["floor", *bad])
        assert exc.value.code == 2


def test_port_default_clears_the_claimed_tui_slots():
    """The default port avoids the other loopback UIs and binds loopback only."""
    from mailroom_sandbox.tui import board, web

    assert floor_app.DEFAULT_PORT == 8769
    assert floor_app.DEFAULT_PORT not in (web.DEFAULT_PORT, board.DEFAULT_PORT, 8766, 8768)
    assert floor_app.DEFAULT_HOST == "127.0.0.1"


def test_dispatch_passes_defaults_and_run_to_serve_floor(monkeypatch, tmp_path):
    """`cli.main` forwards the resolved base, default port, interval, run and replay flag."""
    seen = []
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: seen.append(kw) or 0)
    monkeypatch.delenv("MAILROOM_BASE_DIR", raising=False)
    assert cli.main(["floor", "--base", str(tmp_path), "run-a"]) == 0
    assert seen[-1] == {"base": tmp_path, "port": 8769, "interval": 5.0, "run": "run-a", "replay": False}
    assert cli.main(["floor", "--run", "run-b", "--port", "0", "--interval", "2", "--replay"]) == 0
    assert (seen[-1]["port"], seen[-1]["interval"], seen[-1]["run"], seen[-1]["replay"]) == (0, 2.0, "run-b", True)
    assert seen[-1]["base"] == floor_app.resolve_base(None)


def test_target_and_run_must_agree(monkeypatch, capsys):
    """A target and --run naming different runs is a usage error; equal names serve."""
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: pytest.fail("must not serve"))
    assert cli.main(["floor", "run-a", "--run", "run-b"]) == 2
    assert "different runs" in capsys.readouterr().err
    monkeypatch.setattr(floor_app, "serve_floor", lambda **kw: 0)
    assert cli.main(["floor", "run-a", "--run", "run-a"]) == 0


def test_base_resolution_flag_then_env_then_repo_data(monkeypatch, tmp_path):
    """--base wins over MAILROOM_BASE_DIR, which wins over the repo's ./data."""
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path / "env"))
    assert floor_app.resolve_base(str(tmp_path / "flag")) == tmp_path / "flag"
    assert floor_app.resolve_base(None) == (tmp_path / "env").resolve()
    monkeypatch.delenv("MAILROOM_BASE_DIR")
    assert floor_app.resolve_base(None).name == "data"


def test_floor_url_deep_selects_a_run():
    """The printed URL deep-selects a run and quotes its name."""
    assert floor_app.floor_url(8769) == "http://127.0.0.1:8769/floor.template.html"
    assert floor_app.floor_url(1, "a b/c") == "http://127.0.0.1:1/floor.template.html?run=a%20b%2Fc"


# ── digest build API ────────────────────────────────────────────────────────────


def test_build_emits_both_files(store, tmp_path):
    """The builder writes matching JSON and window.DIGEST twins."""
    base, graph, _ = store
    out = tmp_path / "out"
    digest, json_path, js_path = floor_app.build(base, out, graph)
    assert json_path == out / "floor_digest.json" and js_path == out / "floor_digest.js"
    assert json.loads(json_path.read_text(encoding="utf-8")) == digest
    assert js_path.read_bytes() == b"window.DIGEST=" + json_path.read_bytes() + b";\n"
    run = digest["runs"][0]
    assert run["name"] == "run-1" and run["state"] == "running" and run["inflight"] == {}


def test_build_reports_no_runs_with_the_builders_exit_code(tmp_path):
    """No runs raises DigestError with the no-runs exit code."""
    builder = floor_app.load_builder()
    graph = tmp_path / "g.py"
    graph.write_text(STUB_GRAPH, encoding="utf-8")
    with pytest.raises(builder.DigestError) as exc:
        floor_app.build(tmp_path / "empty", tmp_path / "out", graph)
    assert exc.value.code == builder.EXIT_NO_RUNS


# ── bundled replay ──────────────────────────────────────────────────────────────

REPLAY_RUN = floor_app.replay_base() / "runtime" / "runs" / floor_app.REPLAY_RUN_ID


def test_replay_fixture_is_a_pinned_sample_with_a_complete_trace():
    """The sample covers all five classes, stays text-free, and its trace names every row."""
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    dataset_text = (REPLAY_RUN / "dataset.jsonl").read_text(encoding="utf-8")
    dataset = [json.loads(line) for line in dataset_text.splitlines()]
    assert len(dataset) == 120
    assert {row["expected_doc_class"] for row in dataset} == {
        "contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim"}
    for cls in {"contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim"}:
        assert sum(1 for row in dataset if row["expected_doc_class"] == cls) == 24, cls
    assert len({row["id"] for row in dataset}) == 120
    assert all("doc_text" not in row for row in dataset), "the fixture carries IDs/metadata, not document text"
    assert "/home/" not in dataset_text and "C:\\Users\\" not in dataset_text

    lock = json.loads((REPLAY_RUN / "spec.lock.json").read_text(encoding="utf-8"))
    assert lock["dataset"]["revision"] == FAMILY_HF_REVISION
    assert lock["dataset"]["sha256"] == hashlib.sha256((REPLAY_RUN / "dataset.jsonl").read_bytes()).hexdigest()
    assert lock["engine"]["kind"] == "replay"

    events = [json.loads(line) for line in (REPLAY_RUN / "replay.jsonl").read_text(encoding="utf-8").splitlines()]
    ids = {row["id"] for row in dataset}
    assert {event["item"]["item_id"] for event in events if "item" in event} == ids
    assert all(event["node"]["doc"] in ids for event in events if "node" in event)
    assert all(isinstance(event["at"], (int, float)) for event in events)
    assert [event["at"] for event in events] == sorted(event["at"] for event in events), "chronological timeline"
    final = [event["checkpoint"] for event in events if "checkpoint" in event][-1]
    assert final == {"state": "done", "cursor": 120, "total": 120}


def test_replay_store_makes_the_run_visible_before_the_first_tick(tmp_path):
    """The replay store copies the sample and gets empty item/node files for discovery."""
    base = floor_app.replay_store(tmp_path / "base")
    run = base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID
    assert (run / "items.jsonl").is_file() and (run / "items.jsonl").stat().st_size == 0
    assert (run / "nodes.jsonl").is_file() and (run / "nodes.jsonl").stat().st_size == 0
    assert (run / "dataset.jsonl").read_bytes() == (REPLAY_RUN / "dataset.jsonl").read_bytes()


def test_replay_store_is_loud_when_the_fixture_is_missing(tmp_path, monkeypatch):
    """A missing fixture raises instead of serving an empty run store."""
    monkeypatch.setattr(floor_app, "replay_base", lambda: tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        floor_app.replay_store(tmp_path / "dest")


def test_replay_store_resets_only_its_own_run_dir(store):
    """History is untouched; each call replaces just the labeled replay run."""
    base, _, _ = store
    floor_app.replay_store(base)
    run = base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID
    history = (base / "runtime" / "runs" / "run-1" / "items.jsonl").read_bytes()
    assert not (base / "runtime" / "runs" / "README.md").exists(), "the fixture README must not leak into the store"
    (run / "items.jsonl").write_text("garbage\n", encoding="utf-8")
    (run / "notes.txt").write_text("stray artifact\n", encoding="utf-8")
    floor_app.replay_store(base)
    assert (run / "items.jsonl").stat().st_size == 0, "the replay run resets on each call"
    assert not (run / "notes.txt").exists(), "stray artifacts do not survive a reset"
    assert (base / "runtime" / "runs" / "run-1" / "items.jsonl").read_bytes() == history


def test_replay_driver_replays_every_document_to_done(tmp_path):
    """The driver writes all 120 scripted items/nodes, refreshes items, and ends done."""
    base = floor_app.replay_store(tmp_path / "base")
    driver = floor_app.ReplayDriver(base)
    assert driver.documents == 120
    refreshes = []
    while driver.step(lambda: refreshes.append(1)):
        pass
    run = base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID
    items = [json.loads(line) for line in (run / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(items) == 120 and len({item["item_id"] for item in items}) == 120
    failed = [item for item in items if not item["ok"]]
    assert len(failed) == 3 and all(item["pred"]["stage"] == "failed" for item in failed)
    assert sum(1 for item in items if item["pred"]["stage"] == "review") == 2
    checkpoint = json.loads((run / "checkpoint.json").read_text(encoding="utf-8"))
    assert (checkpoint["state"], checkpoint["cursor"], checkpoint["total"]) == ("done", 120, 120)
    assert driver.pos == len(driver.events) and len(refreshes) >= driver.documents
    assert driver.step() is False, "an exhausted timeline is a no-op"


def _open_nodes(run_dir: Path) -> set[tuple[str, str]]:
    """(doc, node) pairs whose latest record is still ``running``."""
    latest: dict[tuple[str, str], dict] = {}
    for line in (run_dir / "nodes.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        latest[(record["doc"], record["node"])] = record
    return {key for key, record in latest.items() if record["status"] == "running"}


def test_replay_runs_concurrent_docs_and_parks_the_held_one(tmp_path):
    """Mid-replay several docs are in flight and the held doc is still open at the end."""
    base = floor_app.replay_store(tmp_path / "base")
    run = base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID
    driver = floor_app.ReplayDriver(base)
    seen = 0
    while driver.step():
        if driver.pos == len(driver.events) // 2:
            seen = len(_open_nodes(run))
    assert seen >= 2, "docs run concurrently mid-replay (real run dynamics), like live pills"
    assert (run / "checkpoint.json" and json.loads((run / "checkpoint.json").read_text(encoding="utf-8")))["state"] == "done"
    held = [pair for pair in _open_nodes(run) if pair[1] == "human_review"]
    assert held, "the parked doc stays open like a live run's held document"


def test_replay_running_records_carry_real_elapsed_timestamps(tmp_path):
    """A node record's ``ts`` is its scheduled wall-clock moment (drives pill elapsed)."""
    base = floor_app.replay_store(tmp_path / "base")
    driver = floor_app.ReplayDriver(base)
    while driver.step() and not (base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID / "nodes.jsonl").stat().st_size:
        pass
    recorded = json.loads((base / "runtime" / "runs" / floor_app.REPLAY_RUN_ID / "nodes.jsonl")
                          .read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(recorded["ts"], float) and recorded["ts"] <= time.time() + 60


def test_replay_digest_reports_five_classes_and_scripted_misses(tmp_path):
    """A finished replay feeds the digest the sample classes, outcomes and routing misses."""
    base = floor_app.replay_store(tmp_path / "base")
    driver = floor_app.ReplayDriver(base)
    while driver.step():
        pass
    graph = tmp_path / "g.py"
    graph.write_text(STUB_GRAPH, encoding="utf-8")
    digest, _, _ = floor_app.build(base, tmp_path / "out", graph)
    run = digest["runs"][0]
    assert (run["state"], run["items_attempted"], run["total"]) == ("done", 120, 120)
    assert set(run["outcomes"]) == {
        "contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim"}
    assert all(o["n"] == 24 for o in run["outcomes"].values()), "24 docs per class"
    assert sum(o["ship"] for o in run["outcomes"].values()) == 115
    assert sum(o["held"] for o in run["outcomes"].values()) == 2
    assert sum(o["failed"] for o in run["outcomes"].values()) == 3
    assert sum((v or {}).get("gt", 0) for v in run["routing"].values()) == 116, "four scripted docs carry no doc_type"
    assert run["predicted"]["insurance_claim"] == 2, "the two misrouted insurance docs"
    assert set(run["per_class"]) == set(run["outcomes"])


def test_replay_store_is_loud_when_the_fixture_is_missing(tmp_path, monkeypatch):
    """A missing fixture raises instead of serving an empty run store."""
    monkeypatch.setattr(floor_app, "replay_base", lambda: tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        floor_app.replay_store(tmp_path / "dest")


@pytest.mark.parametrize(("body", "message"), [
    ('{"at": 0, "node": {}}\nnot json\n', "invalid JSON"),
    ('{"at": "x", "node": {}}\n', "numeric 'at'"),
    ('{"at": -1, "node": {}}\n', "non-negative numeric 'at'"),
    ('{"at": 0}\n', "exactly one"),
    ('{"checkpoint": {"state": "done", "cursor": 0, "total": 0}}\n', "numeric 'at'"),
])
def test_replay_trace_shape_errors_are_loud(tmp_path, body, message):
    """Malformed replay timelines fail at load with a message naming the problem."""
    path = tmp_path / "replay.jsonl"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        floor_app._load_trace(path)


def test_replay_play_stops_promptly(tmp_path):
    """The replay thread exits when the stop event is set."""
    base = floor_app.replay_store(tmp_path / "base")
    driver = floor_app.ReplayDriver(base)
    stop = threading.Event()
    thread = threading.Thread(target=driver.play, args=(stop,))
    thread.start()
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_serve_floor_falls_back_to_the_replay_when_the_base_has_no_runs(tmp_path, monkeypatch, capsys):
    """An empty base serves the bundled sample next to nothing and keeps it in the base."""
    bases: list[Path] = []
    found: list[bool] = []

    def fake_build(base, out, graph=None):
        """Record the replay base and return a dummy digest."""
        bases.append(Path(base))
        found.append((Path(base) / "runtime" / "runs" / floor_app.REPLAY_RUN_ID / "replay.jsonl").is_file())
        return {}, out / "floor_digest.json", out / "floor_digest.js"

    def refuse(*args, **kwargs):
        """Stop after the first build by refusing the socket."""
        raise OSError("stop")

    monkeypatch.setattr(floor_app, "build", fake_build)
    monkeypatch.setattr(floor_app, "make_server", refuse)
    assert floor_app.serve_floor(base=tmp_path / "empty", out=tmp_path / "out", port=0) == 1
    assert found == [True] and bases[0] == tmp_path / "empty"
    err = capsys.readouterr().err
    assert "replaying the bundled sample" in err and "cannot listen" in err


def test_serve_floor_replay_adds_the_sample_beside_local_runs(store, tmp_path, monkeypatch, capsys):
    """`replay=True` replays the pinned sample INTO the base; historical runs stay viewable."""
    base, _, _ = store
    found: list[bool] = []
    history: list[bool] = []

    def fake_build(seen_base, out, graph=None):
        """Record whether the replay run materialized and history survived."""
        runs = Path(seen_base) / "runtime" / "runs"
        found.append((runs / floor_app.REPLAY_RUN_ID / "replay.jsonl").is_file())
        history.append((runs / "run-1" / "items.jsonl").is_file())
        return {}, out / "floor_digest.json", out / "floor_digest.js"

    def refuse(*args, **kwargs):
        """Stop after the first build by refusing the socket."""
        raise OSError("stop")

    monkeypatch.setattr(floor_app, "build", fake_build)
    monkeypatch.setattr(floor_app, "make_server", refuse)
    assert floor_app.serve_floor(base=base, out=tmp_path / "out", replay=True, port=0) == 1
    assert found == [True] and history == [True], "both the sample and the historical run are in the base"
    assert "replaying" not in capsys.readouterr().err, "an explicit --replay is not a fallback"


# ── stat-sweep skip ─────────────────────────────────────────────────────────────


def _counting(monkeypatch):
    """Patch floor_app.build with a call counter."""
    calls = []
    monkeypatch.setattr(floor_app, "build", lambda base, out, graph=None: calls.append(1))
    return calls


def test_idle_floor_skips_rebuild_until_an_artifact_changes(store, monkeypatch, tmp_path):
    """An unchanged sweep does not rebuild; an appended record does."""
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
    """Only run dirs and listed artifacts affect the signature."""
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
    """A post-success failure is retried; a first-build failure raises."""
    base, _, run = store
    state = {"fail": False, "n": 0}

    def flaky(base, out, graph=None):
        """Fail on demand while counting calls."""
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
    """The background thread exits when the stop event is set."""
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
    """A DigestError returns its code before the socket binds."""
    monkeypatch.setattr(floor_app, "make_server", lambda *a, **k: pytest.fail("must not bind"))
    monkeypatch.setenv("FLOOR_DIGEST_GRAPH", str(tmp_path / "missing_graph.py"))
    rc = floor_app.serve_floor(base=tmp_path / "empty", out=tmp_path / "out")
    assert rc != 0 and "sandbox floor: error:" in capsys.readouterr().err


@pytest.mark.parametrize("exc", [ValueError("boom: bad path"), OSError("no such store")])
def test_first_build_surprise_is_a_clean_exit_not_a_traceback(tmp_path, monkeypatch, capsys, exc):
    """A non-DigestError first-build failure is one stderr line and exit 1."""
    def explode(base, out, graph=None):
        """Raise the parameterized first-build exception."""
        raise exc

    monkeypatch.setattr(floor_app, "build", explode)
    monkeypatch.setattr(floor_app, "make_server", lambda *a, **k: pytest.fail("must not bind"))
    base = tmp_path / "data" / "runtime" / "runs" / "r1"
    base.mkdir(parents=True)
    (base / "items.jsonl").write_text("{}\n", encoding="utf-8")  # a non-empty sweep so refresh() reaches build()
    rc = floor_app.serve_floor(base=tmp_path / "data", out=tmp_path / "out")  # no exception escapes
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("sandbox floor:") and str(exc) in err and "Traceback" not in err


def test_serve_floor_reports_a_port_conflict_instead_of_a_traceback(store, tmp_path, monkeypatch, capsys):
    """A port already in use exits 1 with one line, not a traceback."""
    base, graph, _ = store
    monkeypatch.setenv("FLOOR_DIGEST_GRAPH", str(graph))

    def refuse(*args, **kwargs):
        """Simulate a socket that cannot bind."""
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(floor_app, "make_server", refuse)
    assert floor_app.serve_floor(base=base, out=tmp_path / "out", port=8769) == 1
    err = capsys.readouterr().err
    assert "cannot listen on 127.0.0.1:8769" in err and "Traceback" not in err


def test_server_binds_loopback_and_serves_the_page_uncached(tmp_path):
    """The server binds 127.0.0.1, serves the page and sends no-store."""
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
    """The template reads ?run= and ?class=."""
    html = (Path(floor_app.dashboard_dir()) / "floor.template.html").read_text(encoding="utf-8")
    assert 'URLSearchParams(location.search)' in html and 'q.get("run")' in html and 'q.get("class")' in html


def _template():
    """Read the shipped template."""
    return (Path(floor_app.dashboard_dir()) / "floor.template.html").read_text(encoding="utf-8")


def test_template_class_deep_link_uses_the_rails_per_run_guard():
    """?class= is honoured only when the class rail would allow it."""
    html = _template()
    assert "function classView(" in html
    assert "classView(rr,c)" in html, "the class rail must use the shared helper"
    deep = html[html.index('c=q.get("class")'):html.index("function run()")]
    assert "hasClasses(dr)" in deep and "dr.per_class[c]" in deep and "!classView(dr,c).why" in deep


def test_template_does_one_final_fetch_when_the_run_leaves_running():
    """One final fetch happens when a live run goes idle."""
    html = _template()
    live = html[html.index("// ── LIVE refresh"):]
    assert "wasLive" in live and "(idle&&!wasLive)" in live and "wasLive=!idle" in live
    assert live.count('fetch("floor_digest.json?ts="') == 1, "the existing fetch helper is reused, not duplicated"
