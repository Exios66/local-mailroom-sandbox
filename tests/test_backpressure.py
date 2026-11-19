"""Per-stage queue-depth limits: intake waits when a bin is full, and nothing is dropped (network-free)."""

from __future__ import annotations

import pytest

from mailroom_sandbox import backpressure as bp
from mailroom_sandbox import family_api
from mailroom_sandbox.datasets import load_manifest


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for stage in bp.STAGES:
        monkeypatch.delenv(bp.ENV_PREFIX + stage.upper(), raising=False)
    bp.clear_cache()
    yield
    bp.clear_cache()


def _fake_depths(monkeypatch, depths: dict[str, list[int] | int]):
    """``stage_depth`` answers from ``depths``; a list is consumed one reading at a time."""

    def depth(stage, **_kw):
        value = depths[stage]
        if isinstance(value, list):
            return value.pop(0) if len(value) > 1 else value[0]
        return value

    monkeypatch.setattr(bp, "stage_depth", depth)


# --------------------------------------------------------------------------- limits


def test_limits_default_env_override_and_off(monkeypatch):
    assert bp.limits() == bp.DEFAULT_LIMITS
    assert bp.limit("review") == 0  # only a person drains review: unbounded unless set
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_INBOX", "7")
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_PROCESSING", "0")
    assert bp.limit("inbox") == 7 and bp.limit("processing") == 0


@pytest.mark.parametrize("raw", ["-3", "lots", "1.5"])
def test_a_bad_limit_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_DISPATCH", raw)
    assert bp.limit("dispatch") == bp.DEFAULT_LIMITS["dispatch"]


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError, match="unknown stage"):
        bp.limit("archive")
    with pytest.raises(ValueError, match="pool"):
        bp.stage_depth("dispatch")


# --------------------------------------------------------------------------- depth


def test_stage_depth_counts_documents_not_sidecars_and_caches(tmp_path, monkeypatch):
    proc = tmp_path / "processing"
    (proc / "w1").mkdir(parents=True)
    (proc / "w2").mkdir()
    for p in (proc / "w1" / "a.txt", proc / "w1" / "a.txt.meta", proc / "w2" / "b.pdf", proc / "w2" / ".lock"):
        p.write_text("x")
    monkeypatch.setattr(bp, "_bin_dir", lambda stage: {"processing": proc, "review": tmp_path / "none"}[stage])
    now = [100.0]
    assert bp.stage_depth("processing", clock=lambda: now[0]) == 2
    assert bp.stage_depth("review", clock=lambda: now[0]) == 0  # a missing bin is empty
    (proc / "w2" / "c.txt").write_text("x")
    now[0] += 0.1
    assert bp.stage_depth("processing", clock=lambda: now[0]) == 2  # cached
    now[0] += 1.0
    assert bp.stage_depth("processing", clock=lambda: now[0]) == 3


def test_saturated_reports_only_full_bounded_stages(monkeypatch):
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_INBOX", "2")
    _fake_depths(monkeypatch, {"inbox": 2, "processing": 1, "review": 10_000})
    full = bp.saturated(("inbox", "processing", "review"))
    assert [(s.stage, s.depth, s.limit) for s in full] == [("inbox", 2, 2)]
    assert str(full[0]) == "inbox 2/2"
    assert bp.saturated(("dispatch",), depths={"dispatch": 32}) == [bp.Saturation("dispatch", 32, 32)]


# --------------------------------------------------------------------------- waiting


def test_wait_for_capacity_blocks_with_backoff_until_the_stage_drains(monkeypatch):
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_INBOX", "3")
    _fake_depths(monkeypatch, {"inbox": [5, 4, 3, 3, 3, 3, 2]})
    now = [0.0]
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    waited = bp.wait_for_capacity(("inbox",), sleep=sleep, clock=lambda: now[0])
    assert slept == [0.25, 0.5, 1.0, 2.0, 4.0, 5.0]  # doubling, capped at MAX_WAIT_SECONDS
    assert waited == pytest.approx(sum(slept))


def test_wait_for_capacity_returns_at_once_when_there_is_room(monkeypatch):
    _fake_depths(monkeypatch, {"inbox": 0})
    assert bp.wait_for_capacity(sleep=pytest.fail) == pytest.approx(0, abs=0.01)


def test_wait_for_capacity_timeout_raises_instead_of_waiting_forever(monkeypatch):
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_INBOX", "1")
    _fake_depths(monkeypatch, {"inbox": 9})
    now = [0.0]

    def sleep(s):
        now[0] += s

    with pytest.raises(bp.BackpressureTimeout, match="inbox 9/1") as info:
        bp.wait_for_capacity(("inbox",), timeout=3.0, sleep=sleep, clock=lambda: now[0])
    assert info.value.waited == pytest.approx(3.0)


# --------------------------------------------------------------------------- HF-005: the watcher


def _watcher():
    pytest.importorskip("langfuse", reason="pipeline.watcher needs the observability extra")
    from mailroom_sandbox import vendor_hotfixes as vh

    status = vh.apply_hotfixes()
    assert status["HF-005"] == "applied", status
    from pipeline import watcher  # type: ignore

    return watcher


class _Pool:
    def __init__(self, queued: int):
        self.queued = queued

    def queued_count(self):
        return self.queued


def test_hf005_a_full_stage_leaves_the_file_in_the_inbox(monkeypatch):
    watcher = _watcher()
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_PROCESSING", "4")
    _fake_depths(monkeypatch, {"processing": 4, "review": 0})
    called = []
    assert watcher._DispatchPool.submit(_Pool(0), "a.txt", called.append, "a.txt") is False
    _fake_depths(monkeypatch, {"processing": 0, "review": 0})
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_DISPATCH", "2")
    assert watcher._DispatchPool.submit(_Pool(2), "a.txt", called.append, "a.txt") is False
    assert called == []


def test_hf005_below_the_limits_the_file_is_queued_as_upstream_does(monkeypatch, tmp_path):
    watcher = _watcher()
    _fake_depths(monkeypatch, {"processing": 0, "review": 0})
    pool = watcher._DispatchPool()
    done = []
    try:
        assert pool.submit("b.txt", done.append, tmp_path / "b.txt") is True
        assert pool.submit("b.txt", done.append, tmp_path / "b.txt") in (True, False)  # de-dup is upstream's
    finally:
        pool.close()


def test_hf005_held_files_are_offered_again_by_the_rescan():
    """The rescan re-offers every inbox file each poll: a hold delays a file, it never loses it."""
    import inspect

    watcher = _watcher()
    source = inspect.getsource(watcher.Watcher._rescan_loop)
    assert "for f in list_inbox_files():" in source and "_dispatch.submit(" in source


# --------------------------------------------------------------------------- the sandbox's own intake


def test_pipeline_runner_waits_for_inbox_room_before_writing(monkeypatch, job_data_dir):
    pytest.importorskip("graph.build_graph")
    from mailroom_sandbox.eval import runners

    class Held(Exception):
        pass

    seen = []

    def hold(stages, **kw):
        seen.append((tuple(stages), kw.get("what", "")))
        raise Held

    monkeypatch.setattr(bp, "wait_for_capacity", hold)
    row = next(r for r in load_manifest() if r["expected_doc_class"] == "contract")
    with pytest.raises(Held):
        runners._run_pipeline_doc_once(dict(row), mock=True)
    from pipeline.bins import list_inbox_files  # type: ignore

    assert seen and seen[0][0] == ("inbox",) and "pipeline intake" in seen[0][1]
    assert list_inbox_files() == []  # the gate runs before the document is written


class _API:
    """A mailroom API double: each document finishes after ``ticks`` lookups."""

    base_url = "http://mailroom.test"

    def __init__(self, ticks: int = 2, *, refuse: list[family_api.FamilyAPIError] | None = None, never=False):
        self.ticks, self.never = ticks, never
        self.refuse = list(refuse or [])
        self.seen: dict[str, int] = {}
        self.max_unfinished = 0
        self.uploads = 0

    def health(self):
        return {"status": "ok"}

    def _unfinished(self):
        return sum(1 for n in self.seen.values() if self.never or n < self.ticks)

    def upload(self, path, *, matter_id, filename):
        if self.refuse:
            raise self.refuse.pop(0)
        self.uploads += 1
        self.seen[filename] = 0
        self.max_unfinished = max(self.max_unfinished, self._unfinished())
        return {"file": filename, "upload_id": f"u{self.uploads}"}

    def lookup(self, *, filename):
        self.seen[filename] += 1
        done = not self.never and self.seen[filename] >= self.ticks
        return {"doc_id": "d", "stage": "archived" if done else "processing", "doc_type": "contract"}


@pytest.fixture
def api_rows():
    return [dict(r) for r in load_manifest() if r["expected_doc_class"] == "contract"][:2] * 3


def test_api_eval_keeps_at_most_max_in_flight_uploads_unfinished(api_rows):
    api = _API(ticks=3)
    report = family_api.run_api_eval(api_rows, api, sleep=lambda s: None, max_in_flight=2)
    assert api.uploads == len(api_rows) == report["n"]
    assert api.max_unfinished <= 2
    assert report["error"] is None and report["incomplete"] == []


def test_api_eval_window_defaults_to_the_inbox_limit(api_rows, monkeypatch):
    monkeypatch.setenv("MAILROOM_MAX_QUEUE_DEPTH_INBOX", "1")
    api = _API(ticks=2)
    family_api.run_api_eval(api_rows, api, sleep=lambda s: None)
    assert api.max_unfinished == 1


def test_api_eval_stops_sending_and_reports_when_the_window_never_drains(api_rows):
    api = _API(never=True)
    now = [0.0]

    def sleep(s):
        now[0] += s

    report = family_api.run_api_eval(api_rows, api, sleep=sleep, clock=lambda: now[0],
                                     max_in_flight=2, doc_timeout=10, poll_seconds=1)
    assert api.uploads == 2 and report["n"] == 2 and report["n_rows"] == len(api_rows)
    assert report["error"].startswith("backpressure: 2 uploaded documents stayed unfinished")
    assert report["ok"] is False and len(report["incomplete"]) == 2  # accepted documents are still reported


def test_api_eval_retries_an_upload_refused_by_the_pause_gate(api_rows):
    paused = family_api.FamilyAPIError("HTTP 503: Ingestion is paused by the ops monitor", status_code=503)
    api = _API(ticks=1, refuse=[paused, paused])
    slept: list[float] = []
    report = family_api.run_api_eval(api_rows[:1], api, sleep=slept.append, max_in_flight=0)
    assert report["ok"] is True and api.uploads == 1
    assert slept[:2] == [family_api.RATE_LIMIT_BACKOFF_SECONDS] * 2


def test_a_plain_503_is_not_retried_and_stays_unconfirmed(api_rows):
    gateway = family_api.FamilyAPIError("HTTP 503: upstream unavailable", status_code=503)
    report = family_api.run_api_eval(api_rows[:1], _API(refuse=[gateway]), sleep=lambda s: None)
    assert report["n"] == 0 and report["unconfirmed_upload"]


def test_retryable_refusal_rules():
    err = family_api.FamilyAPIError
    assert family_api._retryable_refusal(err("x", status_code=429))
    assert family_api._retryable_refusal(err("Ingestion is PAUSED", status_code=503))
    assert not family_api._retryable_refusal(err("bad gateway", status_code=502))
    assert not family_api._retryable_refusal(err("no answer"))
