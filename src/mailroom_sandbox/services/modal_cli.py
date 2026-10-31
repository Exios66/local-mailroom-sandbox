"""``sandbox modal …``: guarded passthrough to the real ``modal`` CLI.

Wraps only what the sandbox's own deploy flow needs (``deploy``, ``prewarm``, ``status``,
``logs``, ``stop``) and injects the sandbox defaults: the pinned entrypoint
``deploy/modal_vllm.py``, the model/GPU row from ``config/models.yaml``, the scoped app
name. ``raw -- <args>`` reaches everything else. Nothing here deploys or spends on its
own: ``--dry-run`` prints the exact argv, and ``deploy``/``prewarm`` say what they bill.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from typing import Any

from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.services.beacon import service_job
from mailroom_sandbox.services._cli import format_command, nonempty, print_json, print_plan, strip_separator, warn
from mailroom_sandbox.services._redact import redact_urls
from mailroom_sandbox.services._exec import (
    ServiceError,
    ToolFailed,
    passthrough_tool,
    run_tool,
    stream_tool,
)

PINNED_SDK = "1.6.2"  # pyproject [deploy] extra: modal==1.6.2
INSTALL_HINT = 'pip install -e ".[deploy]" && modal token new'
ENTRYPOINT = "deploy/modal_vllm.py"
JOB_APP = "sandbox-job"
VERIFY_ATTEMPTS = 5
VERIFY_DELAY = 2.0

_NOT_FOUND = re.compile(r"not found|no such app|no app|could not find|does not exist", re.IGNORECASE)
_NAME_KEYS = ("description", "Description", "name", "Name", "app_name")
_STATE_KEYS = ("state", "State", "status", "Status")
_ID_KEYS = ("app_id", "App ID", "id", "Id")


def vllm_app() -> str:
    """The app name ``deploy/modal_vllm.py`` registers (``MODAL_VLLM_APP_NAME`` scopes it)."""
    return (os.environ.get("MODAL_VLLM_APP_NAME") or "").strip() or "sandbox-vllm"


def _prepare() -> None:
    from mailroom_sandbox.runtime import load_env_file

    load_env_file()  # .env may carry MODAL_WORKSPACE / MODAL_VLLM_APP_NAME


def _check_version() -> None:
    """Fail early if ``modal`` is missing; warn (never block) when the SDK is not the pin."""
    result = run_tool(["modal", "--version"], timeout=30.0, check=False, hint=INSTALL_HINT)
    match = re.search(r"\d+\.\d+\.\d+", result.stdout or "")
    if match and match.group(0) != PINNED_SDK:
        warn(
            f"modal {match.group(0)} installed, but the sandbox is verified against {PINNED_SDK} "
            f'(pip install -e ".[deploy]") — flags may differ'
        )


def _matrix_env(args: argparse.Namespace) -> dict[str, str]:
    """``MODAL_VLLM_*`` overrides for the chosen ``--model`` / ``--gpu`` (none when neither is given)."""
    model = getattr(args, "model", None)
    gpu = getattr(args, "gpu", None)
    if not model and not gpu:
        return {}
    from mailroom_sandbox.modal_matrix import resolve_modal_row

    try:
        return dict(resolve_modal_row(model, gpu_override=gpu)["env"])
    except KeyError as exc:
        raise ServiceError(str(exc.args[0])) from exc
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc


def _child_env(overrides: dict[str, str]) -> dict[str, str]:
    return {**os.environ, **overrides}


def _endpoint() -> tuple[str, str] | None:
    """(base_url, source) for the Modal endpoint, or None when it cannot be derived."""
    from mailroom_sandbox.overlay import load_profile
    from mailroom_sandbox.providers import modal_gateway_url

    explicit = os.environ.get("VLLM_BASE_URL", "").strip()
    if explicit:
        return explicit, "VLLM_BASE_URL"
    url = modal_gateway_url(load_profile("modal-vllm"))
    return (url, "MODAL_WORKSPACE") if url else None


# --------------------------------------------------------------------------- deploy / prewarm


def _run_streamed(argv: list[str], env: dict[str, str], *, on_line=None) -> None:
    rc = stream_tool(argv, env=_child_env(env), cwd=repo_root(), hint=INSTALL_HINT, on_line=on_line)
    if rc != 0:
        raise ToolFailed(argv, rc)


def _cmd_deploy(args: argparse.Namespace) -> int:
    _prepare()
    env = _matrix_env(args)
    argv = ["modal", "deploy", ENTRYPOINT]
    if args.dry_run:
        print_plan(argv, env, cwd=str(repo_root()))
        print("dry-run: nothing deployed. A deploy builds the image and registers a scale-to-zero app;")
        print("dry-run: GPU billing starts with the first request and stops after the scaledown window.")
        return 0
    _check_version()
    print("note: deploy registers a scale-to-zero app; the GPU bills from the first request until `sandbox modal stop`.")
    print(f"-> {format_command(argv, env)}")
    with service_job("modal-deploy", title="modal deploy · sandbox-vllm") as job:
        job.update(phase="DEPLOYING")
        _run_streamed(argv, env, on_line=job.log)
    endpoint = _endpoint()
    if endpoint:
        url = redact_urls(endpoint[0])
        print(f"\nendpoint: {url}")
        print(f"export VLLM_BASE_URL={url}")
    else:
        print("\nMODAL_WORKSPACE is unset, so the endpoint cannot be derived.")
        print("Copy the URL `modal deploy` printed above, then:")
        print("export VLLM_BASE_URL=<that url>/v1   # or set MODAL_WORKSPACE=<workspace slug>")
    print('export VLLM_API_KEY="$MODAL_VLLM_API_TOKEN"   # the bearer the gateway requires')
    print("next: `sandbox health` (wakes the GPU), then `sandbox modal stop` when the run is finished")
    return 0


def _cmd_prewarm(args: argparse.Namespace) -> int:
    _prepare()
    env = _matrix_env(args)
    argv = ["modal", "run", f"{ENTRYPOINT}::download_model"]
    if args.dry_run:
        print_plan(argv, env, cwd=str(repo_root()))
        print("dry-run: nothing downloaded. Prewarm runs a CPU-only job that fills the HF weights volume.")
        return 0
    _check_version()
    print("note: prewarm is a CPU-only download job (no GPU); weights persist in the Modal volume.")
    print(f"-> {format_command(argv, env)}")
    with service_job("modal-prewarm", title="modal prewarm · weights") as job:
        job.update(phase="DOWNLOADING")
        _run_streamed(argv, env, on_line=job.log)
    print("next: `sandbox modal deploy`")
    return 0


# --------------------------------------------------------------------------- status / stop


def _field(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _app_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("apps", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ServiceError("could not parse `modal app list --json` output: expected a list of apps")
    if any(not isinstance(row, dict) or not _field(row, _NAME_KEYS) or not _field(row, _STATE_KEYS) for row in payload):
        raise ServiceError("could not parse `modal app list --json` output: app name/state missing")
    return payload


def _list_apps() -> list[dict[str, Any]]:
    result = run_tool(["modal", "app", "list", "--json"], timeout=60.0, hint=INSTALL_HINT)
    try:
        payload = json.loads(result.stdout or "")
    except ValueError as exc:
        raise ServiceError("could not parse `modal app list --json` output: not JSON") from exc
    return _app_rows(payload)


def _app_state(rows: list[dict[str, Any]], app: str) -> dict[str, Any]:
    """The sandbox view of one app; names match exactly (a scoped fleet is not the default app)."""
    # Listings can retain a stopped version alongside a newer deployment.
    ordered = sorted(rows, key=lambda row: _field(row, _STATE_KEYS).lower() == "stopped")
    for row in ordered:
        if _field(row, _NAME_KEYS) == app:
            state = _field(row, _STATE_KEYS) or "unknown"
            return {
                "name": app,
                "deployed": state.lower() == "deployed",
                "state": state,
                "app_id": _field(row, _ID_KEYS) or None,
            }
    return {"name": app, "deployed": False, "state": "not deployed", "app_id": None}


def _is_deployed(app: str) -> bool:
    state = _app_state(_list_apps(), app)["state"].lower()
    return state not in {"stopped", "not deployed"}


def _cmd_status(args: argparse.Namespace) -> int:
    _prepare()
    _check_version()
    rows = _list_apps()
    names = list(dict.fromkeys([vllm_app(), JOB_APP]))
    apps = [_app_state(rows, name) for name in names]
    warm = [a["name"] for a in apps if a["deployed"]]
    if args.json:
        print_json({"apps": apps, "any_deployed": bool(warm)})
        return 0
    for a in apps:
        print(f"{a['name']:<20} {a['state']}")
    if warm:
        for name in warm:
            print(f"next: `sandbox modal stop --app {shlex.quote(name)}` — {name} still deployed (it bills while containers are warm)")
    else:
        print("next: `sandbox modal prewarm` then `sandbox modal deploy` for a run")
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    _prepare()
    app = args.app or vllm_app()
    argv = ["modal", "app", "stop", app, "--yes"]
    if args.dry_run:
        print_plan(argv)
        print("dry-run: nothing stopped. Volumes (weights, compile cache) persist across a stop.")
        return 0
    _check_version()
    with service_job("modal-stop", title=f"modal stop · {app}") as job:
        job.update(phase="STOPPING")
        return _stop(app, argv, args, job)


def _stop(app: str, argv: list[str], args: argparse.Namespace, job) -> int:
    if not _is_deployed(app):
        print(f"{app}: already stopped (not deployed)")
        return 0
    print(f"-> {format_command(argv)}")
    result = run_tool(argv, timeout=120.0, check=False, hint=INSTALL_HINT)
    if result.returncode != 0:
        output = f"{result.stderr or ''}\n{result.stdout or ''}"
        if _NOT_FOUND.search(output):
            print(f"{app}: already stopped (modal found nothing to stop)")
            return 0
        raise ToolFailed(argv, result.returncode, result.stderr or result.stdout or "")
    if args.no_verify:
        print(f"{app}: stop requested (not verified)")
        return 0
    for attempt in range(VERIFY_ATTEMPTS):
        if not _is_deployed(app):
            job.log("stopped and verified")
            print(f"{app}: stopped and verified — no deployment running; volumes persist")
            print("next: `sandbox modal status`")
            return 0
        if attempt < VERIFY_ATTEMPTS - 1:
            time.sleep(VERIFY_DELAY)
    raise ServiceError(
        f"'{app}' still shows a running deployment after {VERIFY_ATTEMPTS} checks — "
        "run `sandbox modal status` and `modal app list`"
    )


# --------------------------------------------------------------------------- url / logs / raw


def _cmd_url(args: argparse.Namespace) -> int:
    _prepare()
    endpoint = _endpoint()
    if not endpoint:
        raise ServiceError(
            "MODAL_WORKSPACE is not set, so the endpoint cannot be derived — set it to your Modal "
            "workspace slug, or export VLLM_BASE_URL=<url printed by `modal deploy`>/v1"
        )
    url, source = endpoint
    if args.json:
        print_json({"base_url": url, "source": source, "app": vllm_app()})
    else:
        print(redact_urls(url))
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    _prepare()
    app = args.app or vllm_app()
    argv = ["modal", "app", "logs", *(["-f"] if args.follow else []), app]
    if args.dry_run:
        print_plan(argv)
        return 0
    _check_version()
    try:
        rc = stream_tool(argv, hint=INSTALL_HINT)
    except KeyboardInterrupt:
        return 130
    if rc != 0:
        raise ToolFailed(argv, rc)
    return 0


def _cmd_raw(args: argparse.Namespace) -> int:
    rest = strip_separator(args.rest)
    if not rest:
        print("error: usage: sandbox modal raw -- <modal arguments>", file=sys.stderr)
        return 2
    _prepare()
    return passthrough_tool(["modal", *rest], hint=INSTALL_HINT, cwd=repo_root())


def _cmd_help(args: argparse.Namespace) -> int:
    print(
        "Use: sandbox modal deploy|prewarm|status|logs|stop|url|raw\n"
        "  deploy [--model M] [--gpu G] [--dry-run]   modal deploy deploy/modal_vllm.py (prints the endpoint exports)\n"
        "  prewarm [--model M]                        CPU-only weight download into the Modal volume\n"
        "  status [--json]                            is sandbox-vllm / sandbox-job deployed (billing)?\n"
        "  stop [--app NAME] [--no-verify]            idempotent teardown, verified by `modal app list`\n"
        "  logs [--follow] [--app NAME]               modal app logs\n"
        "  url [--json]                               the endpoint VLLM_BASE_URL should hold\n"
        "  raw -- <args>                              any other modal command, unchanged\n"
        "deploy, prewarm, stop and logs support --dry-run (prints the argv, spends nothing). Flow: `sandbox runbook show serve`."
    )
    return 0


def register(sub: argparse._SubParsersAction, leaf: argparse.ArgumentParser) -> None:
    """Add the ``modal`` group to the root parser (``leaf`` carries the cross-command flags)."""
    group = sub.add_parser(
        "modal", parents=[leaf], help="guarded passthrough to the modal CLI (deploy/prewarm/status/stop/logs/url/raw)"
    )
    cmds = group.add_subparsers(dest="modal_cmd")

    deploy = cmds.add_parser("deploy", parents=[leaf], help="modal deploy deploy/modal_vllm.py")
    deploy.add_argument("--gpu", default=None, help="override the matrix GPU (e.g. A100-40GB:2)")
    deploy.add_argument("--dry-run", action="store_true", help="print the argv, deploy nothing")
    deploy.set_defaults(handler=_cmd_deploy)

    prewarm = cmds.add_parser("prewarm", parents=[leaf], help="modal run …::download_model (CPU-only)")
    prewarm.add_argument("--gpu", default=None, help=argparse.SUPPRESS)
    prewarm.add_argument("--dry-run", action="store_true")
    prewarm.set_defaults(handler=_cmd_prewarm)

    status = cmds.add_parser("status", parents=[leaf], help="which sandbox Modal apps are deployed")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=_cmd_status)

    stop = cmds.add_parser("stop", parents=[leaf], help="stop the app (idempotent) and verify it is gone")
    stop.add_argument("--app", type=nonempty, default=None, help="app name (default: MODAL_VLLM_APP_NAME or sandbox-vllm)")
    stop.add_argument("--no-verify", action="store_true", help="skip the post-stop `modal app list` check")
    stop.add_argument("--dry-run", action="store_true")
    stop.set_defaults(handler=_cmd_stop)

    logs = cmds.add_parser("logs", parents=[leaf], help="modal app logs")
    logs.add_argument("--app", type=nonempty, default=None)
    logs.add_argument("--follow", action="store_true", help="stream live (modal app logs -f)")
    logs.add_argument("--dry-run", action="store_true")
    logs.set_defaults(handler=_cmd_logs)

    url = cmds.add_parser("url", parents=[leaf], help="print the endpoint VLLM_BASE_URL should hold")
    url.add_argument("--json", action="store_true")
    url.set_defaults(handler=_cmd_url)

    raw = cmds.add_parser("raw", parents=[leaf], help="run any modal command: sandbox modal raw -- <args>")
    raw.add_argument("rest", nargs=argparse.REMAINDER)
    raw.set_defaults(handler=_cmd_raw)

    group.set_defaults(handler=_cmd_help)
