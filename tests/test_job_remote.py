"""Modal remote transport contracts exercised with real locked stores."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import shutil
import json

import pytest

from test_generation_protocol import modal_fs  # noqa: F401 - pytest fixture
from test_job_generation_residuals import source_root, spec_file, sdk  # noqa: F401 - pytest fixtures
from mailroom_sandbox.job import preflight, remote

pytestmark = pytest.mark.usefixtures('job_data_dir')


def prepared(tmp_path, source_root):
    spec, _, store, _ = spec_file(tmp_path, source_root)
    assert preflight.preflight(spec, offline=True)['status'] == 'prepared'
    return store


def test_modal_dispatch_refuses_a_rescore_lock_before_spawn(tmp_path, source_root, modal_fs):
    """A copied remote call id must not attach or spawn, and the checkpoint stays paused."""
    store = prepared(tmp_path, source_root)
    lock = json.loads(store.lock_path.read_text(encoding="utf-8"))
    lock["lock_kind"] = "rescore.lock"
    lock["rescore"] = {"source_run": "source-run"}
    store.lock_path.write_text(json.dumps(lock), encoding="utf-8")
    store.write_checkpoint(state="paused", cursor=0, total=1, remote={"call_id": "fc-LIVE"})
    modal_fs.calls["fc-LIVE"] = "RUNNING"
    before = store.checkpoint_path.read_bytes()
    with pytest.raises(RuntimeError, match="rescore lock"):
        remote.ensure_running(store)
    with pytest.raises(RuntimeError, match="rescore lock"):
        remote.fire(store)
    assert modal_fs.spawned == []
    assert store.checkpoint_path.read_bytes() == before
    assert store.read_checkpoint()["state"] == "paused"


def test_fire_persists_call_id(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    result = remote.fire(store)
    assert result['call_id'] == store.read_checkpoint()['remote']['call_id'] == 'fc-0'
    assert any(e['event'] == 'fired' for e in store.events())


def test_is_alive_reflects_input_state(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    assert remote.is_alive(store) is True
    modal_fs.calls['fc-0'] = 'SUCCESS'
    assert remote.is_alive(store) is False


def test_is_alive_exception_treated_as_alive(tmp_path, source_root, modal_fs, caplog):
    store = prepared(tmp_path, source_root); remote.fire(store)
    modal_fs.calls['fc-0'] = OSError('SDK transport failed')
    with caplog.at_level(logging.WARNING, logger='mailroom_sandbox.job.remote'):
        assert remote.is_alive(store) is True
    assert len(modal_fs.spawned) == 1


def test_ensure_running_refuses_young_refire(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root); remote.fire(store)
    modal_fs.calls['fc-0'] = 'SUCCESS'
    with pytest.raises(RuntimeError, match='cooldown'): remote.ensure_running(store)
    assert len(modal_fs.spawned) == 1


def test_ensure_running_refires_after_cooldown(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root); remote.fire(store)
    cp = store.read_checkpoint(); cp['remote']['fired_at'] = (datetime.now(timezone.utc)-timedelta(minutes=30)).isoformat()
    store.write_checkpoint(state='running', cursor=0, total=1, remote=cp['remote'])
    modal_fs.calls['fc-0'] = 'SUCCESS'
    assert remote.ensure_running(store) == {'action':'fired','call_id':'fc-1'}
    assert len([cmd for cmd in modal_fs.transfers if cmd[2]=='put']) == 1


def test_ensure_running_reattaches_live(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root); remote.fire(store)
    assert remote.ensure_running(store) == {'action':'attached','call_id':'fc-0'}
    assert len(modal_fs.spawned) == 1


def test_cancel_calls_function_call(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root); remote.fire(store); remote.cancel(store)
    assert modal_fs.calls['fc-0'] == 'TERMINATED'
    assert any(e['event']=='cancel_requested' for e in store.events())


def test_fire_sends_lock_mock_flag(tmp_path, source_root, modal_fs):
    spec,_,store,_ = spec_file(tmp_path, source_root); spec.job.mock=True
    assert preflight.preflight(spec,offline=True)['status']=='prepared'
    remote.fire(store)
    payload=modal_fs.spawned[-1]
    assert payload['mock'] is True and payload['run_id']==store.run_id
    assert payload['generation_id']==store.read_lock()['generation_id']


def test_fire_skips_upload_when_remote_lock_matches(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    shutil.copytree(store.dir, modal_fs.volume/store.run_id)
    remote.fire(store)
    assert not any(cmd[2]=='put' for cmd in modal_fs.transfers)
    assert modal_fs.spawned[-1]['run_path']==store.run_id


def test_fire_uploads_when_remote_lock_differs(tmp_path, source_root, modal_fs):
    import json
    store = prepared(tmp_path, source_root)
    dest=modal_fs.volume/store.run_id;shutil.copytree(store.dir,dest)
    foreign=store.read_lock();foreign['generation_id']='foreign';(dest/'spec.lock.json').write_text(json.dumps(foreign))
    remote.fire(store)
    assert len([cmd for cmd in modal_fs.transfers if cmd[2]=='put'])==1
    assert json.loads((dest/'spec.lock.json').read_text())==foreign


def test_pull_run_dir_copies_files(tmp_path, source_root, modal_fs, sdk):
    store = prepared(tmp_path, source_root);remote.fire(store)
    modal_fs.worker(modal_fs.spawned[-1])
    assert remote.pull_run_dir(store)==(0,'')
    assert [item['index'] for item in store.load_items()]==[0]
    assert store.state()=='done'


def test_node_trace_survives_remote_upload_and_terminal_pull(tmp_path, source_root, modal_fs):
    """Node history is part of the generation on both sides of a Modal transfer."""
    store = prepared(tmp_path, source_root)
    first = {"doc": "d0", "node": "intake", "status": "running", "ts": 1.0}
    store.append_node(first)
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    assert (target / "nodes.jsonl").read_bytes() == store.nodes_path.read_bytes()
    last = {"doc": "d0", "node": "intake", "status": "done", "ts": 2.0, "ms": 1000}
    (target / "nodes.jsonl").write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n")
    from mailroom_sandbox.job.checkpoint import RunStore
    RunStore(target).write_checkpoint(state="done", cursor=0, total=1)
    assert remote.pull_run_dir(store) == (0, "")
    assert store.nodes() == [first, last]


def test_torn_remote_node_trace_does_not_block_valid_results(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    from mailroom_sandbox.job.checkpoint import RunStore
    RunStore(target).write_checkpoint(state="done", cursor=0, total=1)
    (target / "nodes.jsonl").write_text('{"doc": "d0", "node": "intake"}\n["not an object"]\n{"torn":')
    original = (target / "nodes.jsonl").read_bytes()
    rc, detail = remote.pull_run_dir(store)
    assert (rc, detail) == (0, "")
    assert store.state() == "done"
    assert list(store.iter_nodes()) == [{"doc": "d0", "node": "intake"}]
    assert (target / "nodes.jsonl").read_bytes() == original


def test_corrupt_remote_results_still_preserve_local_generation(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    from mailroom_sandbox.job.checkpoint import RunStore
    RunStore(target).write_checkpoint(state="done", cursor=0, total=1)
    (target / "items.jsonl").write_text('{"torn":')
    before = store.checkpoint_path.read_bytes()
    rc, detail = remote.pull_run_dir(store)
    assert rc == 1 and "validation failed" in detail
    assert store.checkpoint_path.read_bytes() == before


def test_pull_run_dir_refuses_busy_store_then_retries(tmp_path, source_root, modal_fs, sdk):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    modal_fs.worker(modal_fs.spawned[-1])
    before = {p.name: p.read_bytes() for p in store.dir.iterdir()
              if p.is_file() and p.name not in {'run.lock', 'cancel.lock'}}
    with store.acquire():
        rc, detail = remote.pull_run_dir(store)
    assert rc == 1 and 'busy' in detail
    assert {p.name: p.read_bytes() for p in store.dir.iterdir()
            if p.is_file() and p.name not in {'run.lock', 'cancel.lock'}} == before
    assert remote.pull_run_dir(store) == (0, '')
    assert store.state() == 'done'


def test_modal_job_state_dict_put_is_two_arg(tmp_path, source_root, modal_fs, sdk):
    store=prepared(tmp_path,source_root);remote.fire(store)
    modal_fs.worker(modal_fs.spawned[-1])
    # The fixture's Dict.put(key,value) signature is strict. Execute progress
    # and terminal publication and inspect the actual value the worker wrote.
    values=list(modal_fs.state.values())
    assert len(values)==1 and values[0]['state']=='done' and values[0]['cursor']==1
    assert values[0]['generation_id']==store.read_lock()['generation_id']


def test_modal_job_refuses_done_while_mailroom_writers_run(tmp_path, source_root, modal_fs, sdk, monkeypatch):
    from mailroom_sandbox.job import deploy_env

    monkeypatch.setattr(deploy_env, 'settle_mailroom_writers', lambda timeout=60.0: ['relations-scan'])
    store=prepared(tmp_path,source_root);remote.fire(store)
    modal_fs.worker(modal_fs.spawned[-1])
    # A writer outlived the wait: mailroom.db is still changing, so the worker
    # publishes a failure instead of a durable `done`.
    values=list(modal_fs.state.values())
    assert len(values)==1 and values[0]['state']=='failed'
    assert 'relations-scan' in values[0]['error']


def test_modal_worker_drops_the_openrouter_key_for_a_run_without_openrouter(tmp_path, source_root, modal_fs, sdk, monkeypatch):
    """#308: the deploy Secret reaches every input; a run that never calls OpenRouter loses it."""
    import os

    from mailroom_sandbox.job.deploy_env import lock_uses_openrouter

    monkeypatch.setenv("OPENROUTER_API_KEY", "deploy-secret-value")
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    assert not lock_uses_openrouter(store.read_lock())
    modal_fs.worker(modal_fs.spawned[-1])
    assert "OPENROUTER_API_KEY" not in os.environ
    values = list(modal_fs.state.values())
    assert len(values) == 1 and values[0]["state"] == "done"


def test_a_worker_without_the_key_publishes_an_openrouter_run_as_failed(tmp_path, source_root, modal_fs, sdk, monkeypatch):
    """#314 review: the missing-key error is a terminal ``failed`` state, not a stalled checkpoint."""
    from mailroom_sandbox.job import deploy_env

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(deploy_env, "_SECRET_OPENROUTER_KEY", {})
    monkeypatch.setattr(deploy_env, "lock_uses_openrouter", lambda lock: True)
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    modal_fs.worker(modal_fs.spawned[-1])
    values = list(modal_fs.state.values())
    assert len(values) == 1 and values[0]["state"] == "failed"
    assert "has no OPENROUTER_API_KEY" in values[0]["error"]


def _write_reads(store):
    """A read-range record and a working text, as a recording run leaves them."""
    store.append_read({"doc": "d0", "call": 1, "agent": "sorter", "ranges": [[0, 5]]})
    store.write_doc_text("d0", "hello world")


def test_remote_upload_includes_reads_and_doc_texts(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    _write_reads(store)
    # Only plain files cross: a symlink and a subdirectory in doc_texts/ stay behind.
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (store.doc_texts_dir / "link.txt").symlink_to(outside)
    (store.doc_texts_dir / "sub").mkdir()
    (store.doc_texts_dir / "sub" / "x.txt").write_text("nested", encoding="utf-8")
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    assert (target / "reads.jsonl").read_bytes() == store.reads_path.read_bytes()
    sent = sorted(p.name for p in (target / "doc_texts").iterdir())
    assert sent == sorted(["index.jsonl", *(p.name for p in store.doc_texts_dir.glob("*.txt")
                                            if not p.is_symlink())])
    assert "link.txt" not in sent and "sub" not in sent


def test_remote_pull_includes_reads(tmp_path, source_root, modal_fs):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    from mailroom_sandbox.job.checkpoint import RunStore
    remote_store = RunStore(target)
    _write_reads(remote_store)
    (remote_store.doc_texts_dir / "sub").mkdir()
    (remote_store.doc_texts_dir / "sub" / "x.txt").write_text("nested", encoding="utf-8")
    remote_store.write_checkpoint(state="done", cursor=0, total=1)
    assert remote.pull_run_dir(store) == (0, "")
    assert store.reads_path.read_bytes() == remote_store.reads_path.read_bytes()
    pulled = sorted(p.name for p in store.doc_texts_dir.iterdir())
    assert pulled == sorted(["index.jsonl", *(p.name for p in remote_store.doc_texts_dir.glob("*.txt"))])
    assert "sub" not in pulled
    assert not list(store.doc_texts_dir.glob("*.pull.tmp"))
    assert store.state() == "done"


def test_pull_writes_checkpoint_after_reads_and_doc_texts(tmp_path, source_root, modal_fs, monkeypatch):
    store = prepared(tmp_path, source_root)
    remote.fire(store)
    target = modal_fs.volume / modal_fs.spawned[-1]["run_path"]
    from mailroom_sandbox.job.checkpoint import RunStore
    remote_store = RunStore(target)
    _write_reads(remote_store)
    remote_store.write_checkpoint(state="done", cursor=0, total=1)
    order = []
    real_replace = type(store.dir).replace

    def spy(self, dest):
        order.append(self.name)
        return real_replace(self, dest)

    monkeypatch.setattr(type(store.dir), "replace", spy)
    assert remote.pull_run_dir(store) == (0, "")
    pulled = [n for n in order if n.endswith(".pull.tmp")]
    assert any(n.startswith("reads.jsonl") for n in pulled)
    assert any(n.endswith(".txt.pull.tmp") for n in pulled)
    assert pulled[-1].startswith("checkpoint.json")


def test_copy_plain_files_skips_symlinks_and_directories(tmp_path):
    src, outside = tmp_path / "src", tmp_path / "outside.txt"
    src.mkdir()
    outside.write_text("secret", encoding="utf-8")
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "link.txt").symlink_to(outside)
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (src / "old.txt.pull.tmp").write_text("partial", encoding="utf-8")
    for stage in (False, True):
        dest = tmp_path / f"dest{stage}"
        remote._copy_plain_files(src, dest, stage=stage)
        assert [p.name for p in dest.iterdir()] == ["a.txt"]
    # A missing or symlinked source directory copies nothing and creates nothing.
    remote._copy_plain_files(tmp_path / "missing", tmp_path / "none")
    (tmp_path / "dirlink").symlink_to(src)
    remote._copy_plain_files(tmp_path / "dirlink", tmp_path / "none")
    assert not (tmp_path / "none").exists()
