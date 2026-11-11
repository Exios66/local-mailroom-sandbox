"""Validate offline dispatch contracts and write durable, credential-free handoffs.

These commands never launch tasks, probe providers, load dotenv or spend money.
Capability snapshots are operator-supplied evidence, not a live health guarantee.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import yaml

from mailroom_sandbox.services._redact import redact_urls
from mailroom_sandbox.subagents.environment import environment_report, git_value

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TERMINAL = {"done", "failed", "cancelled"}
_STATES = {"running", "blocked", *_TERMINAL}
_FORBIDDEN = {
    "token", "password", "secret", "cookie", "authorization", "output_url",
    "api_key", "apikey", "access_token", "accesstoken", "refresh_token",
    "refreshtoken", "client_secret", "clientsecret", "private_key", "privatekey",
    "bearer", "credentials", "password_hash", "passwordhash",
}
_MAX_EVENT_BYTES = 64_000
_MAX_RECORD_BYTES = 1_000_000
_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


def _credential_uri(text: str) -> bool:
    """Detect non-HTTP URIs with passwords, queries, fragments, or parse errors."""
    for match in _URI.finditer(text):
        if match.group().lower().startswith(("http://", "https://")):
            continue
        try:
            parts = urlsplit(match.group())
            if parts.password or parts.query or parts.fragment:
                return True
        except ValueError:
            return True
    return False


def read_document(path: Path) -> dict:
    """Bound input size and normalize malformed documents without echoing them."""
    if path.stat().st_size > 1_000_000:
        raise ValueError("Input exceeds 1 MB")
    try:
        value = yaml.safe_load(path.read_text())
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ValueError("Invalid JSON/YAML document") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected a mapping document")
    return value


def clean(value, _seen: set[int] | None = None):
    """Redact URL credentials/query strings and reject explicit secret fields."""
    seen = _seen if _seen is not None else set()
    if isinstance(value, dict):
        if id(value) in seen:
            raise ValueError("Cyclic documents are not allowed")
        if any(str(k).lower() in _FORBIDDEN for k in value):
            raise ValueError("Credential fields and authenticated output URLs are forbidden")
        seen.add(id(value))
        try:
            return {str(k): clean(v, seen) for k, v in value.items()}
        finally:
            seen.discard(id(value))
    if isinstance(value, list):
        if id(value) in seen:
            raise ValueError("Cyclic documents are not allowed")
        seen.add(id(value))
        try:
            return [clean(v, seen) for v in value]
        finally:
            seen.discard(id(value))
    if isinstance(value, str):
        redacted = redact_urls(value)
        if _credential_uri(redacted):
            raise ValueError("Credential-bearing URIs are forbidden")
        return redacted
    if value is None or type(value) in (bool, int, float):
        return value
    raise ValueError("Only JSON-compatible values are allowed")


def contract_document(path: Path) -> dict:
    """Validate a bounded task contract; never infer absent dispatch authority."""
    doc = read_document(path)
    allowed = {"schema", "request_id", "objective", "checkout", "provider_instance_id", "model",
               "read_only", "write_scope", "instructions", "source_owner", "acceptance",
               "resources", "stop_conditions", "artifact_paths", "known_findings"}
    if set(doc) - allowed or doc.get("schema") != "mailroom.dispatch/v1":
        raise ValueError("Unknown contract field or schema")
    for key in ("request_id", "objective", "provider_instance_id", "model", "source_owner"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise ValueError(f"Missing nonempty contract field: {key}")
    if not _ID.fullmatch(doc["request_id"]):
        raise ValueError("request_id must be a safe identifier")
    checkout = doc.get("checkout")
    if not isinstance(checkout, dict) or set(checkout) != {"root", "branch", "start_sha", "pr_base"}:
        raise ValueError("checkout requires root, branch, start_sha and pr_base")
    if any(not isinstance(v, str) or not v.strip() for v in checkout.values()):
        raise ValueError("Checkout fields must be nonempty strings")
    if not Path(checkout["root"]).is_absolute() or not _SHA.fullmatch(checkout["start_sha"]):
        raise ValueError("Checkout root must be absolute and start_sha a full SHA")
    if type(doc.get("read_only")) is not bool:
        raise ValueError("read_only must be explicit")
    for key in ("write_scope", "instructions", "acceptance", "stop_conditions", "artifact_paths"):
        value = doc.get(key)
        if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
            raise ValueError(f"{key} must be a list of nonempty strings")
        if key != "write_scope" and not value:
            raise ValueError(f"{key} cannot be empty")
    if doc["read_only"] == bool(doc["write_scope"]):
        raise ValueError("Read-only tasks have no write_scope; writers need an explicit scope")
    for scope in doc["write_scope"]:
        if Path(scope).is_absolute() or ".." in Path(scope).parts or scope in {".", "*", "**"}:
            raise ValueError("Write scopes must be bounded checkout-relative paths")
    resources = doc.get("resources")
    if not isinstance(resources, dict) or set(resources) != {"local_workers", "max_wall_seconds", "spend_authorized"}:
        raise ValueError("resources requires local_workers, max_wall_seconds and spend_authorized")
    if type(resources["local_workers"]) is not int or resources["local_workers"] != 1:
        raise ValueError("Local worker budget must be one; offload expensive work")
    if type(resources["max_wall_seconds"]) is not int or resources["max_wall_seconds"] <= 0:
        raise ValueError("Wall budget must be a positive integer")
    if type(resources["spend_authorized"]) is not bool:
        raise ValueError("Spend authority must be explicit")
    return clean(doc)


def readiness(snapshot: dict, provider_id: str, model: str, *, now: datetime | None = None) -> dict:
    """Check an instance/model in an exported T3 capability snapshot.

    The snapshot must be at most 300 seconds old and not future-dated relative
    to ``now``. Invalid or stale input returns a failure code. Every result has
    ``workflow_verified: False``; catalog availability does not verify a workflow.
    """
    try:
        captured = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError
        age = ((now or datetime.now(timezone.utc)) - captured).total_seconds()
        if snapshot.get("schema") != "mailroom.capabilities/v1" or not 0 <= age <= 300:
            raise ValueError
        providers = snapshot["catalog"]["providers"]
        matches = [p for p in providers if p["providerInstanceId"] == provider_id]
        if len(matches) != 1:
            raise ValueError
        provider = matches[0]
        if provider.get("canRunChildTask") is not True or provider.get("constraints"):
            return {"ok": False, "code": "provider.unavailable", "workflow_verified": False}
        parent = snapshot["catalog"].get("inheritedProviderInstanceId")
        if parent and parent != provider_id and provider.get("canRunCrossProviderChildTask") is not True:
            return {"ok": False, "code": "provider.cross_dispatch_unavailable", "workflow_verified": False}
        if model not in [m["id"] for m in provider["models"]]:
            return {"ok": False, "code": "model.unavailable", "workflow_verified": False}
        return {"ok": True, "code": "catalog.dispatch_available", "age_seconds": age,
                "workflow_verified": False}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"ok": False, "code": "capabilities.invalid_or_stale", "workflow_verified": False}


def _fsync_dir(path: Path) -> None:
    """Make a rename durable; a directory fd failure must not hide the write."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checkpoint(contract: dict, task_id: str, state: str, next_action: str, *,
               evidence: list[str], blockers: list[str], review_ids: list[str],
               record: Path | None = None, new_attempt: bool = False) -> Path:
    """Atomically append an owned attempt's history under a nonblocking file lock."""
    import fcntl

    if not _ID.fullmatch(task_id) or state not in _STATES or not next_action.strip():
        raise ValueError("Expected safe task ID, known state and nonempty next action")
    root = Path(contract["checkout"]["root"]).resolve()
    if record is None:
        path = root / "data/runtime/agent-tasks" / f"{contract['request_id']}.json"
        probe = root
        for part in path.relative_to(root).parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError("Checkpoint paths must not traverse symlinks")
    else:
        path = Path(record).expanduser().absolute()
        if path.is_symlink():
            raise ValueError("Checkpoint record must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Checkpoint is busy; reconcile existing writer before retrying") from exc
        digest = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        if path.exists():
            doc = read_document(path)
            stored_contract = doc.get("contract")
            if not isinstance(stored_contract, dict):
                raise ValueError("Record is missing its embedded contract")
            stored_digest = hashlib.sha256(
                json.dumps(stored_contract, sort_keys=True).encode()
            ).hexdigest()
            if (doc.get("schema") != "mailroom.handoff/v1" or doc.get("request_id") != contract["request_id"]
                    or doc.get("contract_sha256") != stored_digest or stored_digest != digest):
                raise ValueError("Refusing to overwrite a foreign or changed-contract record")
            attempts = doc.get("attempts")
            if not isinstance(attempts, list) or not attempts or any(not isinstance(a, dict) for a in attempts):
                raise ValueError("Invalid existing attempt history")
            last = attempts[-1]
            if last.get("task_id") != task_id:
                if not new_attempt or last.get("state") not in _TERMINAL:
                    raise ValueError("Reconcile active task before starting another attempt")
                if any(a.get("task_id") == task_id for a in attempts):
                    raise ValueError("Cannot reuse a prior task ID")
                attempts.append({"task_id": task_id, "history": []})
            elif new_attempt or last.get("state") in _TERMINAL:
                raise ValueError("Completed attempts are immutable; use a new task ID")
        else:
            if new_attempt:
                raise ValueError("A new attempt requires an existing completed record")
            doc = {"schema": "mailroom.handoff/v1", "request_id": contract["request_id"],
                   "contract_sha256": digest, "contract": contract,
                   "attempts": [{"task_id": task_id, "history": []}]}
        event = clean({"at": datetime.now(timezone.utc).isoformat(), "state": state,
                       "head_sha": git_value(root, "rev-parse", "HEAD"), "next_action": next_action,
                       "evidence": evidence, "blockers": blockers, "unresolved_review_ids": review_ids})
        if len(json.dumps(event, allow_nan=False).encode()) > _MAX_EVENT_BYTES:
            raise ValueError("Checkpoint event exceeds 64 KB; attach artifacts instead")
        attempt = doc["attempts"][-1]
        if not isinstance(attempt.get("history"), list):
            raise ValueError("Invalid existing history")
        attempt["history"].append(event)
        attempt["state"] = state
        # Revalidate stored content and redact again; never retain raw capability dumps.
        serialized = json.dumps(clean(doc), indent=2, allow_nan=False) + "\n"
        if len(serialized.encode()) > _MAX_RECORD_BYTES:
            raise ValueError("Handoff record would exceed 1 MB; archive it and start a new record")
        temp_fd, temp_path = tempfile.mkstemp(prefix=".handoff-", dir=path.parent)
        try:
            with os.fdopen(temp_fd, "w") as out:
                out.write(serialized)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_path, path)
            _fsync_dir(path.parent)
        finally:
            Path(temp_path).unlink(missing_ok=True)
        return path
    finally:
        os.close(fd)


def command(args: argparse.Namespace) -> int:
    """Validate or checkpoint without launching work or loading secrets."""
    try:
        contract = contract_document(Path(args.contract))
        if args.subagents_cmd == "dispatch-check":
            snapshot = read_document(Path(args.capabilities))
            status = readiness(snapshot, contract["provider_instance_id"], contract["model"])
            env = environment_report(Path(contract["checkout"]["root"]), contract["checkout"]["start_sha"])
            if env["checkout"]["branch"] != contract["checkout"]["branch"]:
                env["ok"] = False
                env["findings"].append({"code": "checkout.branch_mismatch", "severity": "fail",
                                        "message": "Branch differs from dispatch contract"})
            payload = {"ok": status["ok"] and env["ok"], "readiness": status, "environment": env}
            print(json.dumps(payload, indent=2))
            return 0 if payload["ok"] else 1
        path = checkpoint(contract, args.task_id, args.state, args.next_action,
                          evidence=args.evidence, blockers=args.blocker, review_ids=args.review_id,
                          record=Path(args.record) if args.record else None, new_attempt=args.new_attempt)
        print(json.dumps({"record": str(path)}))
        return 0
    except (ValueError, OSError) as exc:
        # Only our validation errors are descriptive; filesystem messages can echo input.
        message = str(exc) if isinstance(exc, ValueError) else "Cannot read or write task documents"
        print(json.dumps({"ok": False, "error": redact_urls(message)}))
        return 1


def register(sub: argparse._SubParsersAction, leaf: argparse.ArgumentParser) -> None:
    check = sub.add_parser("dispatch-check", parents=[leaf], help="validate contract, runtime and recent capability evidence offline")
    check.add_argument("--contract", required=True)
    check.add_argument("--capabilities", required=True, help="mailroom.capabilities/v1 snapshot, at most five minutes old")
    check.set_defaults(handler=command, offline_inspection=True)
    save = sub.add_parser("checkpoint", parents=[leaf], help="persist an owned task handoff atomically; never launches a task")
    save.add_argument("--contract", required=True)
    save.add_argument("--task-id", required=True)
    save.add_argument("--state", required=True, choices=sorted(_STATES))
    save.add_argument("--next-action", required=True)
    save.add_argument("--record", help="explicit durable record path; default data/runtime/agent-tasks/<request_id>.json")
    save.add_argument("--new-attempt", action="store_true")
    for flag in ("evidence", "blocker", "review-id"):
        save.add_argument("--" + flag, action="append", default=[])
    save.set_defaults(handler=command, offline_inspection=True)
