"""Read-only CircleCI pipeline and failed-job diagnostics."""
from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import quote, urlsplit

import httpx

from mailroom_sandbox.services._exec import ServiceError

API = "https://circleci.com/api"
DEFAULT_PROJECT = "gh/Exios66/local-mailroom-sandbox"


def _get(url: str, *, authenticated: bool = True):
    token = os.environ.get("CIRCLE_TOKEN", "")
    if authenticated and not token:
        raise ServiceError("set CIRCLE_TOKEN to a CircleCI personal API token")
    try:
        response = httpx.get(url, headers={"Circle-Token": token} if authenticated else {},
                             timeout=30, follow_redirects=False)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Never print an HTTP exception: output URLs may contain credentials.
        raise ServiceError(f"CircleCI request failed ({type(exc).__name__}); check access and job availability") from None


def _pages(path: str):
    token = None
    seen = set()
    for _ in range(100):
        url = API + path + ("?page-token=" + quote(token, safe="") if token else "")
        data = _get(url)
        yield from data.get("items", [])
        token = data.get("next_page_token")
        if not token:
            return
        if token in seen:
            raise ServiceError("CircleCI pagination repeated a page token")
        seen.add(token)
    raise ServiceError("CircleCI pagination exceeded 100 pages")


def _project(value: str) -> str:
    if not re.fullmatch(r"(?:gh|github|bb|bitbucket)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ServiceError("project must be a VCS slug such as gh/owner/repository")
    vcs, owner, repo = value.split("/")
    vcs = {"github": "gh", "bitbucket": "bb"}.get(vcs, vcs)
    return f"{vcs}/{owner}/{repo}"


def _uuid(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ServiceError("pipeline ID must be a UUID")
    return value


def failed_jobs(pipeline: str, project: str = DEFAULT_PROJECT):
    pipeline = _uuid(pipeline)
    expected = _project(project)
    metadata = _get(f"{API}/v2/pipeline/{pipeline}")
    try:
        actual = _project(metadata.get("project_slug", ""))
    except (ServiceError, TypeError):
        actual = None
    if actual != expected:
        raise ServiceError("pipeline does not belong to the requested project")
    jobs = []
    for workflow in _pages(f"/v2/pipeline/{_uuid(pipeline)}/workflow"):
        for job in _pages(f"/v2/workflow/{_uuid(workflow['id'])}/job"):
            if job.get("status") in {"failed", "failing", "infrastructure_fail", "timedout"}:
                jobs.append(job)
    return jobs


def print_job_logs(project: str, number: int, *, all_steps: bool = False) -> None:
    vcs, owner, repo = _project(project).split("/")
    vcs = {"gh": "github", "bb": "bitbucket"}.get(vcs, vcs)
    detail = _get(f"{API}/v1.1/project/{vcs}/{owner}/{repo}/{number}")
    found = False
    for step in detail.get("steps", []):
        for action in step.get("actions", []):
            if not all_steps and action.get("status") not in {"failed", "timedout", "infrastructure_fail"} and action.get("exit_code") in (None, 0):
                continue
            url = action.get("output_url")
            if not url:
                continue
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and parsed.port in (None, 443)
            except ValueError:
                valid = False
            if not valid:
                raise ServiceError("CircleCI returned an invalid output URL")
            chunks = _get(url, authenticated=False)
            if not isinstance(chunks, list):
                raise ServiceError("CircleCI returned an unexpected log format")
            found = True
            print(f"\n--- job {number}: {step.get('name', 'step')} (node {action.get('index', '?')}) ---")
            for chunk in chunks:
                print(str(chunk.get("message", "")), end="")
            print()
    if not found:
        print(f"job {number}: no {'available' if all_steps else 'failed step'} output; use --all-steps for other steps")


def _cmd(args: argparse.Namespace) -> int:
    if args.pipeline:
        jobs = failed_jobs(args.pipeline, args.project)
        errors = 0
        if not jobs:
            print("No failed jobs found in this pipeline.")
        for job in jobs:
            number = job.get("job_number")
            if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
                print(f"{job.get('name', 'job')}: no job number available", file=sys.stderr)
                errors += 1
                continue
            try:
                print_job_logs(args.project, number, all_steps=args.all_steps)
            except ServiceError as exc:
                print(f"job {number}: {exc}", file=sys.stderr)
                errors += 1
        if errors:
            return 1
    else:
        if args.job is None:
            raise ServiceError("specify --job NUMBER or --pipeline UUID")
        if args.job <= 0:
            raise ServiceError("job number must be positive")
        print_job_logs(args.project, args.job, all_steps=args.all_steps)
    return 0


def register(sub, leaf) -> None:
    circle = sub.add_parser("circleci", parents=[leaf], help="read CircleCI failed-job logs")
    commands = circle.add_subparsers(dest="circleci_command", required=True)
    logs = commands.add_parser("logs", parents=[leaf], help="fetch failed steps from a job or pipeline")
    # No required=True: the CLI-surface dispatch harness builds parser-valid
    # argv for required actions only, and a required mutex group hides both
    # members from it. _cmd validates the choice instead (house style).
    source = logs.add_mutually_exclusive_group()
    source.add_argument("--job", type=int, help="CircleCI job number")
    source.add_argument("--pipeline", help="CircleCI pipeline UUID")
    logs.add_argument("--project", default=DEFAULT_PROJECT, help="VCS/owner/repository (default: this repository)")
    logs.add_argument("--all-steps", action="store_true", help="include successful step output")
    logs.set_defaults(handler=_cmd)
