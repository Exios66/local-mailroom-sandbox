"""Dispatch evidence and durable handoffs never launch remote tasks."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox import cli
from mailroom_sandbox.subagents import dispatch


@pytest.fixture
def contract(tmp_path):
    return {"schema": "mailroom.dispatch/v1", "request_id": "review-1", "objective": "Review a bounded change",
            "checkout": {"root": str(tmp_path), "branch": "feature", "start_sha": "a" * 40, "pr_base": "main"},
            "provider_instance_id": "provider-one", "model": "model-one", "read_only": True, "write_scope": [],
            "instructions": ["AGENTS.md"], "source_owner": "local-mailroom-sandbox",
            "acceptance": ["Evidence against the exact commit"], "stop_conditions": ["Authentication unavailable"],
            "artifact_paths": ["reports/review.md"],
            "resources": {"local_workers": 1, "max_wall_seconds": 300, "spend_authorized": False}}


@pytest.fixture
def snapshot():
    return {"schema": "mailroom.capabilities/v1", "captured_at": datetime.now(timezone.utc).isoformat(),
            "catalog": {"inheritedProviderInstanceId": "provider-one", "providers": [
                {"providerInstanceId": "provider-one", "canRunChildTask": True, "constraints": [],
                 "models": [{"id": "model-one"}]}]}}


def test_contract_rejects_absent_authority_and_unbounded_scope(contract, tmp_path):
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump(contract))
    assert dispatch.contract_document(path) == contract
    for change in ({"resources": {"local_workers": 4}}, {"read_only": False}, {"token": "private"}):
        path.write_text(yaml.safe_dump({**contract, **change}))
        with pytest.raises(ValueError):
            dispatch.contract_document(path)
    for scope in ("../foreign", "/absolute", "**"):
        path.write_text(yaml.safe_dump({**contract, "read_only": False, "write_scope": [scope]}))
        with pytest.raises(ValueError, match="bounded"):
            dispatch.contract_document(path)


def test_catalog_checks_instance_availability_model_age_and_cross_provider(snapshot):
    assert dispatch.readiness(snapshot, "provider-one", "model-one")["ok"]
    assert not dispatch.readiness(snapshot, "missing", "model-one")["ok"]
    assert not dispatch.readiness(snapshot, "provider-one", "missing")["ok"]
    snapshot["catalog"]["providers"][0]["canRunChildTask"] = False
    assert dispatch.readiness(snapshot, "provider-one", "model-one")["code"] == "provider.unavailable"
    snapshot["catalog"]["providers"][0]["canRunChildTask"] = True
    snapshot["catalog"]["inheritedProviderInstanceId"] = "another-provider"
    assert dispatch.readiness(snapshot, "provider-one", "model-one")["code"] == "provider.cross_dispatch_unavailable"
    snapshot["catalog"]["providers"][0]["canRunCrossProviderChildTask"] = True
    assert dispatch.readiness(snapshot, "provider-one", "model-one")["ok"]
    snapshot["captured_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    assert dispatch.readiness(snapshot, "provider-one", "model-one")["code"] == "capabilities.invalid_or_stale"
    assert not dispatch.readiness({"captured_at": "bad"}, "x", "y")["ok"]


def test_handoff_clean_rejects_credential_uris_and_cycles():
    with pytest.raises(ValueError, match="Credential-bearing"):
        dispatch.clean({"evidence": ["postgres://user:password@db.example/app"]})
    with pytest.raises(ValueError, match="Credential"):
        dispatch.clean({"known_findings": [{"api_key": "private"}]})
    assert dispatch.clean("ssh://git@github.com/org/repo") == "ssh://git@github.com/org/repo"
    loop: dict = {}
    loop["self"] = loop
    with pytest.raises(ValueError, match="Cyclic"):
        dispatch.clean(loop)


def save(contract, task="task-1", state="running", **kwargs):
    return dispatch.checkpoint(contract, task, state, "Inspect hosted CI", evidence=[
        "https://user:password@ci.example/job/1?signature=private#secret"], blockers=[], review_ids=["thread-1"], **kwargs)


def test_handoff_preserves_history_redacts_urls_and_rejects_ambiguous_relaunch(contract):
    path = save(contract)
    text = path.read_text()
    assert "signature" not in text and "password" not in text and "#secret" not in text
    assert "ci.example/job/1" in text
    with pytest.raises(ValueError, match="active task"):
        save(contract, task="task-2", new_attempt=True)
    save(contract, state="done")
    with pytest.raises(ValueError, match="immutable"):
        save(contract)
    save(contract, task="task-2", new_attempt=True)
    doc = json.loads(path.read_text())
    assert len(doc["attempts"]) == 2 and len(doc["attempts"][0]["history"]) == 2
    assert path.stat().st_mode & 0o777 == 0o600


def test_handoff_refuses_tampered_contract_and_oversized_events(contract):
    path = save(contract)
    doc = json.loads(path.read_text())
    doc["contract"]["objective"] = "Tampered"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="foreign or changed"):
        save(contract)
    doc["contract"]["objective"] = contract["objective"]
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="exceeds 64 KB"):
        dispatch.checkpoint(contract, "task-1", "running", "Inspect hosted CI",
                            evidence=["x" * 70_000], blockers=[], review_ids=[])


def test_explicit_record_allows_symlinked_parent(contract, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    path = dispatch.checkpoint(contract, "task-1", "running", "Inspect hosted CI",
                               evidence=[], blockers=[], review_ids=[],
                               record=link / "handoff.json")
    assert path.is_file() and path.parent == link


def test_handoff_refuses_foreign_records_symlinks_and_changed_contract(contract, tmp_path):
    path = save(contract)
    changed = {**contract, "objective": "Different scope"}
    with pytest.raises(ValueError, match="foreign or changed"):
        save(changed)
    outside = tmp_path / "foreign.json"
    outside.write_text("leave me")
    linked = tmp_path / "linked.json"
    linked.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        save(contract, record=linked)
    assert outside.read_text() == "leave me"
    assert path.exists()


def test_handoff_busy_writer_does_not_lose_state(contract):
    import fcntl
    path = save(contract)
    before = path.read_bytes()
    with path.with_suffix(".json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="busy"):
            save(contract, state="blocked")
    assert path.read_bytes() == before


def test_cli_contract_errors_are_redacted_and_never_load_dotenv(tmp_path, monkeypatch, capsys):
    path = tmp_path / "contract.yaml"
    path.write_text("schema: wrong\nsecret: private-value\n")
    monkeypatch.setattr("mailroom_sandbox.runtime.load_env_file", lambda: pytest.fail("dotenv loaded"))
    assert cli.main(["subagents", "dispatch-check", "--contract", str(path), "--capabilities", "missing"]) == 1
    text = capsys.readouterr().out
    assert "private-value" not in text and not json.loads(text)["ok"]


def test_dispatch_check_cli_reads_exported_evidence_only(contract, snapshot, tmp_path, monkeypatch, capsys):
    path, cap = tmp_path / "contract.yaml", tmp_path / "capabilities.json"
    path.write_text(yaml.safe_dump(contract))
    cap.write_text(json.dumps(snapshot))
    monkeypatch.setattr(dispatch, "environment_report", lambda *a: {"ok": True, "checkout": {"branch": "feature"}, "findings": []})
    assert cli.main(["subagents", "dispatch-check", "--contract", str(path), "--capabilities", str(cap)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["readiness"]["workflow_verified"]


def test_read_document_bounds_and_shapes(tmp_path):
    big = tmp_path / "big.json"
    big.write_text("x" * 1_000_001)
    with pytest.raises(ValueError, match="1 MB"):
        dispatch.read_document(big)
    malformed = tmp_path / "bad.yaml"
    malformed.write_text("[unterminated")
    with pytest.raises(ValueError, match="Invalid JSON/YAML"):
        dispatch.read_document(malformed)
    sequence = tmp_path / "list.yaml"
    sequence.write_text("- one\n- two\n")
    with pytest.raises(ValueError, match="mapping"):
        dispatch.read_document(sequence)


@pytest.mark.parametrize("change", [
    {"schema": "wrong"},
    {"extra": 1},
    {"request_id": "bad id"},
    {"objective": ""},
    {"checkout": {"root": "relative", "branch": "b", "start_sha": "a" * 40, "pr_base": "main"}},
    {"checkout": {"root": "/tmp", "branch": "b", "start_sha": "short", "pr_base": "main"}},
    {"checkout": {"root": "/tmp", "branch": "b", "start_sha": "a" * 40}},
    {"checkout": ["not", "a", "mapping"]},
    {"read_only": "yes"},
    {"read_only": False, "write_scope": []},
    {"read_only": True, "write_scope": ["src"]},
    {"read_only": False, "write_scope": ["."]},
    {"read_only": False, "write_scope": ["../outside"]},
    {"instructions": []},
    {"instructions": [1]},
    {"acceptance": "not-a-list"},
    {"resources": {"local_workers": 2, "max_wall_seconds": 10, "spend_authorized": False}},
    {"resources": {"local_workers": 1, "max_wall_seconds": 0, "spend_authorized": False}},
    {"resources": {"local_workers": 1, "max_wall_seconds": 10, "spend_authorized": "yes"}},
    {"resources": {}},
])
def test_contract_rejects_bounded_field_violations(contract, tmp_path, change):
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump({**contract, **change}))
    with pytest.raises(ValueError):
        dispatch.contract_document(path)


def test_credential_uri_detection():
    assert dispatch._credential_uri("postgres://user:password@db.example/app") is True
    assert dispatch._credential_uri("ssh://git@github.com/org/repo") is False
    assert dispatch._credential_uri("https://user:password@example.test") is False
    assert dispatch._credential_uri("plain text") is False


def test_checkpoint_rejects_invalid_identity_and_default_symlink(contract, tmp_path):
    with pytest.raises(ValueError, match="safe task ID"):
        dispatch.checkpoint(contract, "bad id", "running", "next", evidence=[], blockers=[], review_ids=[])
    with pytest.raises(ValueError, match="known state"):
        dispatch.checkpoint(contract, "task-1", "bogus", "next", evidence=[], blockers=[], review_ids=[])
    with pytest.raises(ValueError, match="nonempty next action"):
        dispatch.checkpoint(contract, "task-1", "running", "  ", evidence=[], blockers=[], review_ids=[])

    default = Path(contract["checkout"]["root"]) / "data/runtime/agent-tasks/review-1.json"
    default.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("leave me")
    default.symlink_to(outside)
    with pytest.raises(ValueError, match="traverse symlinks"):
        save(contract)
    assert outside.read_text() == "leave me"


def test_checkpoint_rejects_malformed_existing_records(contract, tmp_path):
    record = tmp_path / "handoff.json"
    record.write_text(json.dumps({
        "schema": "mailroom.handoff/v1", "request_id": "review-1",
        "contract_sha256": "0" * 64, "attempts": [{"task_id": "task-1", "history": []}],
    }))
    with pytest.raises(ValueError, match="embedded contract"):
        save(contract, record=record)

    digest = __import__("hashlib").sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    record.write_text(json.dumps({
        "schema": "mailroom.handoff/v1", "request_id": "review-1",
        "contract_sha256": digest, "contract": contract, "attempts": [],
    }))
    with pytest.raises(ValueError, match="attempt history"):
        save(contract, record=record)

    record.write_text(json.dumps({
        "schema": "mailroom.handoff/v1", "request_id": "review-1",
        "contract_sha256": digest, "contract": contract,
        "attempts": [{"task_id": "task-1", "history": "bad", "state": "running"}],
    }))
    with pytest.raises(ValueError, match="Invalid existing history"):
        save(contract, record=record)


def test_new_attempt_rules_and_cli_commands(contract, snapshot, tmp_path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="requires an existing completed record"):
        save(contract, task="task-1", new_attempt=True, record=tmp_path / "new.json")
    record = tmp_path / "handoff.json"
    save(contract, record=record)
    save(contract, task="task-1", state="done", record=record)
    save(contract, task="task-2", new_attempt=True, record=record)
    save(contract, task="task-2", state="done", record=record)
    with pytest.raises(ValueError, match="Cannot reuse"):
        save(contract, task="task-1", new_attempt=True, record=record)

    from argparse import Namespace

    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract))
    cap = tmp_path / "capabilities.json"
    cap.write_text(json.dumps(snapshot))
    monkeypatch.setattr(dispatch, "environment_report", lambda *a: {
        "ok": True, "checkout": {"branch": "other"}, "findings": []
    })
    args = Namespace(subagents_cmd="dispatch-check", contract=str(contract_path), capabilities=str(cap))
    assert dispatch.command(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["environment"]["findings"]

    checkpoint_args = Namespace(
        subagents_cmd="checkpoint", contract=str(contract_path), task_id="task-9",
        state="running", next_action="Inspect hosted CI", evidence=[], blocker=[], review_id=[],
        record=str(tmp_path / "cli.json"), new_attempt=False,
    )
    assert dispatch.command(checkpoint_args) == 0
    assert json.loads(capsys.readouterr().out)["record"].endswith("cli.json")


def test_fsync_dir_tolerates_missing_directory(tmp_path):
    dispatch._fsync_dir(tmp_path / "missing")
