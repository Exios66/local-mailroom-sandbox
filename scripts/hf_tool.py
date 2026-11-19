#!/usr/bin/env python3
"""In-house Hugging Face integration tooling for the sandbox (huggingface-tool-builder).

Composable, pipe-friendly subcommands over the Hub REST API with ``HF_TOKEN`` auth.
Everything is read-only and offline-aware: network commands refuse (exit 3) while
``HF_HUB_OFFLINE`` is set, and the family pin contract (``job/spec.py``) is first-class
so provenance checks stay one ``jq`` away.

Examples:
    hf_tool pins | jq .revision
    hf_tool verify-pin ff4ca546... 0f0f0f... | jq -s 'all(.[]; .known)'
    HF_TOKEN=$(...) hf_tool search qwen --type model --limit 20 \\
        | jq -s 'sort_by(-.downloads) | .[0:5]'
    hf_tool card org/repo --type dataset | jq .license
    hf_tool files org/repo --type dataset --revision ff4ca546 | jq -s 'map(select(.size)) '
    hf_tool status | jq '.cache'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROG = "hf_tool"
OFFLINE_EXIT = 3

#: Hub API segment per repo type (the API is plural, the CLI type is singular).
_API_SEGMENT = {"model": "models", "dataset": "datasets"}

#: Injectable transport: ``(url, headers) -> (status, body_bytes)``. Tests replace this.
TRANSPORT = None


# ---- transport -----------------------------------------------------------------------


def _default_transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _fetch(url: str, token: str | None) -> tuple[int, bytes]:
    transport = TRANSPORT if TRANSPORT is not None else _default_transport
    headers: dict[str, str] = {"User-Agent": "mailroom-sandbox/hf-tool"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return transport(url, headers)


def _token(args_token: str | None) -> str | None:
    """``HF_TOKEN`` from the environment, or an explicit ``--token`` override (never logged)."""
    token = args_token or os.environ.get("HF_TOKEN") or ""
    return token or None


def _offline() -> bool:
    raw = (os.environ.get("HF_HUB_OFFLINE") or "").strip().lower()
    return raw not in ("", "0", "false", "no")


def _emit(records) -> None:
    """NDJSON out: one JSON object per line, jq-friendly."""
    for record in records:
        sys.stdout.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _project(record: dict, keys: tuple[str, ...]) -> dict:
    """Keep only the named keys that are actually present (NDJSON stays clean)."""
    return {key: record[key] for key in keys if record.get(key) is not None}


def _hub_get(path: str, token: str | None) -> bytes:
    """GET a Hub API path; a non-200 is a loud failure with the status and body."""
    url = f"https://huggingface.co{path}"
    status, body = _fetch(url, token)
    if status != 200:
        snippet = body[:200].decode("utf-8", "replace")
        _die(f"{PROG}: HTTP {status} for {url}: {snippet}")
    return body


def _require_online() -> None:
    if _offline():
        _die(f"{PROG}: offline (HF_HUB_OFFLINE is set) — refusing Hub API access", OFFLINE_EXIT)


# ---- commands ------------------------------------------------------------------------


def cmd_pins(args) -> int:
    """The family dataset pin ledger (offline, deterministic)."""
    from mailroom_sandbox.job.spec import (
        FAMILY_HF_DATA_REVISION,
        FAMILY_HF_REVISION,
        FAMILY_HF_TAG,
        KNOWN_FAMILY_HF_REVISIONS,
    )

    legacy = {
        tag: {"revision": revision, "data_revision": data}
        for tag, (revision, data) in sorted(
            __import__("mailroom_sandbox.job.spec", fromlist=["LEGACY_FAMILY_HF_REVISIONS"])
            .LEGACY_FAMILY_HF_REVISIONS.items()
        )
    }
    _emit([{
        "tag": FAMILY_HF_TAG,
        "revision": FAMILY_HF_REVISION,
        "data_revision": FAMILY_HF_DATA_REVISION,
        "legacy": legacy,
        "known_revisions": sorted(KNOWN_FAMILY_HF_REVISIONS),
    }])
    return 0


def cmd_verify_pin(args) -> int:
    """Exit 0 when every sha is a known family revision (provenance check, offline)."""
    from mailroom_sandbox.job.spec import KNOWN_FAMILY_HF_REVISIONS

    known = True
    for sha in args.shas:
        is_known = sha in KNOWN_FAMILY_HF_REVISIONS
        known = known and is_known
        _emit([{"sha": sha, "known": is_known}])
    return 0 if known else 1


def cmd_status(args) -> int:
    """Offline cache report, plus (online only) whether the pin still matches Hub HEAD."""
    record: dict = {"cache": _cache_status(), "revision": _pin_revision()}
    if not _offline():
        token = _token(args.token)
        try:
            head = json.loads(_hub_get(f"/api/datasets/{_dataset_repo()}", token))["sha"]
            record["hub_head"] = head
            record["pin_is_head"] = head == record["revision"]
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - status reports, never crashes
            record["hub_error"] = f"{type(exc).__name__}: {exc}"
    else:
        record["hub_head"] = None
        record["note"] = "offline: Hub HEAD not checked"
    _emit([record])
    return 0


def _cache_status() -> dict:
    root = cache_root()
    total = 0
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    return {"root": str(root), "exists": root.is_dir(), "bytes": total}


def cache_root() -> Path:
    """The sandbox HF cache (``data/cache/hf``, matching ``corpus._ensure_hf_home``)."""
    from mailroom_sandbox.paths import repo_root

    return repo_root() / "data" / "cache" / "hf"


def _pin_revision() -> str:
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    return FAMILY_HF_REVISION


def _dataset_repo() -> str:
    from mailroom_sandbox.job.spec import HF_DEFAULT_REPO
    return HF_DEFAULT_REPO


def cmd_whoami(args) -> int:
    """Who the token identifies as (``/api/whoami-v2``)."""
    _require_online()
    body = json.loads(_hub_get("/api/whoami-v2", _token(args.token)))
    _emit([{key: body.get(key) for key in ("name", "type", "authType") if key in body}])
    return 0


def cmd_search(args) -> int:
    """Search the Hub (models or datasets); NDJSON records out."""
    _require_online()
    body = json.loads(_hub_get(
        f"/api/{_API_SEGMENT[args.type]}?search={urllib.request.quote(args.query)}&limit={args.limit}"
        f"&sort={args.sort}&direction=-1", _token(args.token)))
    _emit(_project(record, ("id", "downloads", "likes", "pipeline_tag", "license")) for record in body)
    return 0


def cmd_card(args) -> int:
    """One repo's card metadata as a single NDJSON record."""
    _require_online()
    body = json.loads(_hub_get(f"/api/{_API_SEGMENT[args.type]}/{args.repo}", _token(args.token)))
    _emit([_project(body, ("id", "license", "gated", "tags", "pipeline_tag", "downloads", "sha", "lastModified"))])
    return 0


def cmd_files(args) -> int:
    """List a repo's file tree at a revision (path, size) — directories carry no size."""
    _require_online()
    body = json.loads(_hub_get(
        f"/api/{_API_SEGMENT[args.type]}/{args.repo}/tree/{args.revision}?recursive=1", _token(args.token)))
    _emit({"path": record.get("path"), "size": record.get("size"), "type": record.get("type")}
          for record in body)
    return 0


# ---- parser --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    parser.add_argument("--token", help="explicit token (default: HF_TOKEN; never logged)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pins", help="the family dataset pin ledger (offline)").set_defaults(func=cmd_pins)
    verify = sub.add_parser("verify-pin", help="exit 0 when every sha is a known family revision")
    verify.add_argument("shas", nargs="+", help="40-hex revisions to check")
    verify.set_defaults(func=cmd_verify_pin)
    status = sub.add_parser("status", help="sandbox HF cache + pin-vs-HEAD status")
    status.set_defaults(func=cmd_status)
    whoami = sub.add_parser("whoami", help="who the token identifies as")
    whoami.set_defaults(func=cmd_whoami)
    search = sub.add_parser("search", help="search models or datasets (NDJSON out)")
    search.add_argument("query")
    search.add_argument("--type", choices=("model", "dataset"), default="model")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--sort", choices=("downloads", "likes", "trendingScore", "lastModified"),
                        default="downloads")
    search.set_defaults(func=cmd_search)
    card = sub.add_parser("card", help="one repo's card metadata (NDJSON)")
    card.add_argument("repo")
    card.add_argument("--type", choices=("model", "dataset"), default="model")
    card.set_defaults(func=cmd_card)
    files = sub.add_parser("files", help="list a repo's file tree at a revision")
    files.add_argument("repo")
    files.add_argument("--type", choices=("model", "dataset"), default="dataset")
    files.add_argument("--revision", default=None, help="defaults to the family pin")
    files.set_defaults(func=cmd_files)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", "") == "files" and getattr(args, "revision", None) is None:
        args.revision = _pin_revision()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
