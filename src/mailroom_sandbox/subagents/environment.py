"""Read-only execution identity and local harness configuration checks.

No dotenv loading, network requests, credential reads, installs or repairs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import mailroom_sandbox

from mailroom_sandbox.paths import repo_root

# `git -C` still honors inherited repository/config selectors. Scrub them so a
# caller cannot redirect these reads to a different checkout or object store.
_GIT_LOCATION_ENV = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_PREFIX",
    "GIT_IMPLICIT_WORK_TREE", "GIT_QUARANTINE_PATH", "GIT_SHALLOW_FILE",
    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_REPLACE_REF_BASE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_GRAFT_FILE",
})


def _git_env() -> dict[str, str]:
    """Environment for identity reads: no repository redirection, no prompts."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git_value(root: Path, *args: str) -> str | None:
    """Run a bounded local Git read; never include stderr or remote URLs."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), *args],
            capture_output=True, text=True, timeout=5, check=False, env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def hook_findings(root: Path) -> list[dict]:
    """Inspect project hook references without executing configured commands."""
    config = root / ".claude/settings.json"
    if not config.is_file():
        return []
    try:
        doc = json.loads(config.read_text())
        if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
            raise ValueError
        findings = []
        for groups in doc.get("hooks", {}).values():
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "")
                    marker = "$CLAUDE_PROJECT_DIR/"
                    if marker not in command:
                        continue
                    rel = command.split(marker, 1)[1].split('"', 1)[0].split("'", 1)[0].split()[0]
                    target = (root / rel).resolve()
                    if not target.is_relative_to(root) or not target.is_file():
                        findings.append({"code": "hook.target_missing", "severity": "fail",
                                         "message": "A project hook target is missing or outside the checkout"})
        return findings
    except (OSError, ValueError, TypeError, AttributeError, IndexError):
        return [{"code": "hook.config_invalid", "severity": "fail",
                 "message": "Cannot validate project hook configuration"}]


def environment_report(root: Path, expected_sha: str | None = None) -> dict:
    """Describe the actual runtime and flag checkout/import identity mismatches."""
    root = root.expanduser().resolve()
    git_root = git_value(root, "rev-parse", "--show-toplevel")
    head = git_value(root, "rev-parse", "HEAD")
    status = git_value(root, "status", "--porcelain", "--untracked-files=normal")
    branch = git_value(root, "symbolic-ref", "--short", "HEAD")
    final_head = git_value(root, "rev-parse", "HEAD")
    final_branch = git_value(root, "symbolic-ref", "--short", "HEAD")
    package = Path(mailroom_sandbox.__file__).resolve()
    findings = hook_findings(root)
    if final_head != head or final_branch != branch:
        findings.append({"code": "checkout.changed", "severity": "fail",
                         "message": "Checkout identity changed during inspection; retry after it is stable"})
    if not git_root or Path(git_root).resolve() != root or head is None or status is None:
        findings.append({"code": "checkout.unverified", "severity": "fail",
                         "message": "Requested root is not a verified Git checkout root"})
    if not package.is_relative_to(root / "src/mailroom_sandbox"):
        findings.append({"code": "runtime.foreign_import", "severity": "fail",
                         "message": "Python imports mailroom_sandbox from outside the requested checkout"})
    if expected_sha and head != expected_sha:
        findings.append({"code": "checkout.head_mismatch", "severity": "fail",
                         "message": "HEAD differs from the explicitly expected SHA"})
    if status:
        findings.append({"code": "checkout.dirty", "severity": "warn",
                         "message": "Checkout has changes; preserve them and establish ownership"})
    return {
        "schema": "mailroom.environment/v1",
        "ok": not any(f["severity"] == "fail" for f in findings),
        "checkout": {"root": str(root), "git_root": git_root, "head": head,
                     "branch": branch,
                     "dirty": bool(status) if status is not None else None},
        "python": {"executable": sys.executable, "prefix": sys.prefix,
                   "base_prefix": sys.base_prefix, "package": str(package)},
        "commands": {name: shutil.which(name) for name in ("sandbox", "python", "git", "ruff", "modal", "hf")},
        "local_worker_budget": 1,
        "findings": findings,
    }


def command(args: argparse.Namespace) -> int:
    """Print a fingerprint without loading runtime dotenv or creating beacons."""
    report = environment_report(Path(args.root) if args.root else repo_root(), args.expected_sha)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"checkout: {report['checkout']['root']} @ {report['checkout']['head']}")
        print(f"python: {report['python']['executable']}")
        print(f"package: {report['python']['package']}")
        for finding in report["findings"]:
            print(f"[{finding['severity']}] {finding['code']}: {finding['message']}")
    return 0 if report["ok"] else 1


def register(sub: argparse._SubParsersAction, leaf: argparse.ArgumentParser) -> None:
    parser = sub.add_parser("preflight", parents=[leaf], help="read-only checkout, import and hook identity checks")
    parser.add_argument("--root", help="intended Git checkout root (default: package checkout)")
    parser.add_argument("--expected-sha", help="require this exact full HEAD SHA; older intentional branches are allowed")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(handler=command, offline_inspection=True)
