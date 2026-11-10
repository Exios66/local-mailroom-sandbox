#!/usr/bin/env python3
"""Bound direct local pytest/campaign commands; hosted CI retains full gates.

This is a harness aid, not a shell sandbox. It recognizes direct commands and
simple shell lists, not dynamically constructed Python/shell programs.
"""
from __future__ import annotations

import json
import os
from pathlib import PurePath
import shlex
import sys


def violation(command: str) -> str | None:
    """Return a resource-policy violation for a recognizable expensive command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for i, token in enumerate(tokens):
        if PurePath(token).name == "smoke_campaign.py":
            return "Large mock campaigns require a separately scoped hosted job."
        if PurePath(token).name not in {"pytest", "py.test"}:
            continue
        tail = tokens[i + 1:]
        for j, arg in enumerate(tail):
            if arg in {";", "&&", "||", "|"}:
                tail = tail[:j]
                break
        if any(arg == "--cov" or arg.startswith("--cov=") for arg in tail):
            return "Coverage sweeps belong in hosted CI."
        for j, arg in enumerate(tail):
            if arg in {"-n", "--numprocesses"}:
                if j + 1 >= len(tail) or tail[j + 1] not in {"0", "1"}:
                    return "Local regressions use one worker (-n 0 or -n 1)."
            elif arg.startswith("--numprocesses=") and arg.split("=", 1)[1] not in {"0", "1"}:
                return "Local regressions use one worker."
            elif arg.startswith("-n") and len(arg) > 2 and arg[2:] not in {"0", "1"}:
                return "Local regressions use one worker."
        if any(arg.rstrip("/") in {"tests", "./tests", "."} for arg in tail):
            return "Select specific test files/nodes; full suites belong in hosted CI."
        if not any(arg.split("::", 1)[0].endswith(".py") for arg in tail):
            return "Select specific test files/nodes; full suites belong in hosted CI."
    return None


def main() -> int:
    # An operator can explicitly authorize exceptional local work. Agents must
    # not set this escape hatch on their own; it is not used in normal checks.
    if os.environ.get("SANDBOX_ALLOW_EXPENSIVE_TESTS") == "1":
        return 0
    try:
        doc = json.load(sys.stdin)
        command = (doc.get("tool_input") or {}).get("command", "")
        reason = violation(command)
    except (ValueError, TypeError, AttributeError):
        return 0
    if reason:
        print(f"Resource policy: {reason} See AGENTS.md#tests.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
