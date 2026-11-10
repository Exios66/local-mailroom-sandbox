#!/usr/bin/env python3
"""Bound direct local pytest/campaign commands; hosted CI retains full gates.

This is a harness aid, not a shell sandbox. It recognizes direct commands and
simple shell lists, not dynamically constructed Python/shell programs.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import PurePath
import shlex
import sys

# Options whose next token is a value, never a test selection. Without this,
# `pytest --ignore=unused.py` looks like a selected test file and slips through.
_LONG_VALUE_OPTIONS = frozenset({
    "--ignore", "--ignore-glob", "--doctest-glob", "--doctest-report",
    "--deselect", "--confcutdir", "--rootdir",
    "--basetemp", "--maxfail", "--tb", "--capture", "--durations",
    "--durations-min", "--junitxml", "--junit-xml", "--result-log",
    "--log-level", "--log-format", "--log-date-format", "--log-file",
    "--log-file-level", "--log-file-format", "--log-auto-indent", "--log-disable",
    "--show-capture", "--color", "--code-highlight", "--import-mode",
    "--pythonwarnings", "--verbosity", "--cache-dir", "--override-ini",
    "--config-file", "--plugin", "--numprocesses", "--dist", "--timeout",
    "--timeout-method", "--cov-report", "--cov-config", "--cov-fail-under",
})
_SHORT_VALUE_OPTIONS = frozenset({"-k", "-m", "-c", "-o", "-p", "-n", "-W", "-r"})


def _pytest_arguments(tail: list[str]) -> tuple[list[str], list[str]]:
    """Split pytest arguments into options and positional test selections."""
    options: list[str] = []
    positional: list[str] = []
    take_value = False
    for arg in tail:
        if take_value:
            options.append(arg)
            take_value = False
            continue
        if arg == "--":
            positional.extend(tail[tail.index(arg) + 1:])
            break
        if arg.startswith("--"):
            options.append(arg)
            if "=" not in arg and arg in _LONG_VALUE_OPTIONS:
                take_value = True
            continue
        if arg.startswith("-") and len(arg) > 1:
            options.append(arg)
            if arg in _SHORT_VALUE_OPTIONS:
                take_value = True
            continue
        positional.append(arg)
    return options, positional


def violation(command: str) -> str | None:
    """Return a resource-policy violation for a recognizable expensive command."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {";", "&&", "||", "|", "&"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for argv in segments:
        while argv:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
                argv = argv[1:]
                continue
            if argv[0] == "env":
                argv = argv[1:]
                while argv:
                    token = argv[0]
                    if token in {"-S", "--split-string"}:
                        text = argv[1] if len(argv) > 1 else ""
                        try:
                            argv = shlex.split(text) + argv[2:]
                        except ValueError:
                            argv = []
                        break
                    if token.startswith("--split-string="):
                        try:
                            argv = shlex.split(token.split("=", 1)[1]) + argv[1:]
                        except ValueError:
                            argv = []
                        break
                    if token in {"-u", "--unset", "-C", "--chdir"}:
                        argv = argv[2:]
                        continue
                    if token.startswith(("--unset=", "--chdir=")):
                        argv = argv[1:]
                        continue
                    if token.startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                        argv = argv[1:]
                        continue
                    break
                continue
            if argv[0] in {"command", "exec", "nohup"}:
                argv = argv[1:]
                while argv and argv[0].startswith("-"):
                    argv = argv[1:]
                continue
            break
        if not argv:
            continue
        name, tail = PurePath(argv[0]).name, argv[1:]
        if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", name):
            if "-m" in tail and "-c" not in tail:
                module = tail.index("-m")
                if module + 1 >= len(tail):
                    continue
                name, tail = tail[module + 1], tail[module + 2:]
            elif tail and PurePath(tail[0]).name == "smoke_campaign.py":
                name = "smoke_campaign.py"
        if name in {"smoke_campaign.py", "scripts.smoke_campaign"}:
            return "Large mock campaigns require a separately scoped hosted job."
        if name not in {"pytest", "py.test"}:
            continue
        options, selected = _pytest_arguments(tail)
        if any(arg == "--cov" or arg.startswith("--cov=") for arg in options):
            return "Coverage sweeps belong in hosted CI."
        for j, arg in enumerate(options):
            if arg in {"-n", "--numprocesses"}:
                if j + 1 >= len(options) or options[j + 1] not in {"0", "1"}:
                    return "Local regressions use one worker (-n 0 or -n 1)."
            elif arg.startswith("--numprocesses=") and arg.split("=", 1)[1] not in {"0", "1"}:
                return "Local regressions use one worker."
            elif arg.startswith("-n") and len(arg) > 2 and arg[2:] not in {"0", "1"}:
                return "Local regressions use one worker."
        if any(arg.rstrip("/") in {"tests", "./tests", "."} for arg in selected):
            return "Select specific test files/nodes; full suites belong in hosted CI."
        if not selected:
            return "Select specific test files/nodes; full suites belong in hosted CI."
        if any(not arg.split("::", 1)[0].endswith(".py") for arg in selected):
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
