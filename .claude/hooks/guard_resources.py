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


_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
_SHELL_KEYWORDS = {"if", "elif", "while", "until", "then", "do", "else", "!", "{", "}"}
_SHELLS = {"bash", "sh", "zsh", "dash"}


def _strip_redirections(tokens: list[str]) -> list[str]:
    """Drop redirect operators and targets so ``2>&1`` is not a test selection."""
    clean: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (re.fullmatch(r"\d*[<>]+", token) and index + 2 < len(tokens)
                and tokens[index + 1] == "&" and tokens[index + 2].isdigit()):
            index += 3
            continue
        if re.fullmatch(r"\d*>&\d+", token):
            index += 1
            continue
        if re.fullmatch(r"\d*[<>]+", token) or token in {"&>", "&>>"}:
            index += 1
            if index < len(tokens) and tokens[index] not in _SEPARATORS:
                index += 1
            continue
        if re.match(r"\d*[<>]", token) and len(token) > 1:
            index += 1
            continue
        clean.append(token)
        index += 1
    return clean


def _skip_options(argv: list[str], value_options: set[str]) -> list[str]:
    """Drop launcher options and their values, preserving the command tail."""
    while argv and argv[0].startswith("-"):
        token = argv[0]
        option = token.split("=", 1)[0]
        argv = argv[1:]
        if option in value_options and "=" not in token and argv:
            argv = argv[1:]
    return argv


def _pytest_reason(tail: list[str]) -> str | None:
    """Return a policy reason for coverage, worker count, or test selection, if any."""
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


def _argv_reason(argv: list[str], depth: int) -> str | None:
    """Check recognized commands and wrappers; return a violation reason or None.

    ``depth`` limits recursive inspection of shell ``-c`` commands. Unparseable
    split strings and unrecognized commands return None.
    """
    while argv:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or argv[0] in _SHELL_KEYWORDS:
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
                        return None
                    break
                if token.startswith("--split-string="):
                    try:
                        argv = shlex.split(token.split("=", 1)[1]) + argv[1:]
                    except ValueError:
                        return None
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
        if argv[0] == "command":
            if len(argv) > 1 and argv[1] in {"-v", "-V"}:
                return None
            argv = _skip_options(argv[1:], set())
            continue
        launcher = argv[0]
        if launcher in {"time", "timeout", "nice", "sudo", "nohup", "exec", "xargs", "uv"}:
            argv = argv[1:]
            if launcher == "timeout":
                argv = _skip_options(argv, {"-s", "--signal", "-k", "--kill-after"})
                if argv:
                    argv = argv[1:]  # duration
            elif launcher == "nice":
                argv = _skip_options(argv, {"-n", "--adjustment"})
            elif launcher == "sudo":
                argv = _skip_options(argv, {"-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "--close-from"})
            elif launcher in {"time", "nohup", "exec"}:
                argv = _skip_options(argv, set())
            elif launcher == "xargs":
                argv = _skip_options(argv, {"-n", "--max-args", "-P", "--max-procs", "-I", "--replace",
                                            "-L", "--max-lines", "-s", "--max-chars", "-d", "--delimiter"})
            elif launcher == "uv":
                if argv and argv[0] == "run":
                    argv = argv[1:]
                argv = _skip_options(argv, {"--with", "--python", "-p", "--project", "--directory",
                                            "--index", "--extra", "--group"})
            continue
        break

    if not argv:
        return None
    name, tail = PurePath(argv[0]).name, argv[1:]
    if name in _SHELLS and depth < 4:
        for index, token in enumerate(tail):
            # Only inspect option words before the script/command operand.
            if token == "--" or not token.startswith("-"):
                break
            if re.fullmatch(r"-[a-zA-Z]+", token) and "c" in token[1:]:
                command = tail[index + 1] if index + 1 < len(tail) else ""
                return _violation(command, depth + 1)
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", name):
        index = 0
        while index < len(tail):
            token = tail[index]
            if token == "-m":
                if index + 1 >= len(tail):
                    return None
                name, tail = tail[index + 1], tail[index + 2:]
                break
            if token == "-c":
                return None  # Inline Python and dynamic programs are outside scope.
            if token == "--":
                if index + 1 >= len(tail):
                    return None
                name, tail = PurePath(tail[index + 1]).name, tail[index + 2:]
                break
            if token.startswith("-m") and len(token) > 2:
                name, tail = token[2:], tail[index + 1:]
                break
            if token in {"-W", "-X", "-Q"}:
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            name, tail = PurePath(token).name, tail[index + 1:]
            break
        else:
            return None
    if name in {"smoke_campaign.py", "scripts.smoke_campaign"}:
        return "Large mock campaigns require a separately scoped hosted job."
    if name in {"pytest", "py.test"}:
        return _pytest_reason(tail)
    return None


def _without_literal_heredocs(command: str) -> str:
    """Omit quoted here-document bodies, which shells never execute/expand.

    Recognize simple word delimiters only. Unquoted here-documents can execute
    substitutions and remain visible to the command scanner.
    """
    result: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.splitlines(keepends=True):
        if pending:
            delimiter, tabs = pending[0]
            candidate = line.rstrip("\r\n")
            if tabs:
                candidate = candidate.lstrip("\t")
            if candidate == delimiter:
                pending.pop(0)
            result.append("\n")
            continue
        result.append(line)
        # Tokenize the header before matching so quoted strings containing
        # heredoc-like prose do not hide later commands.
        lexer = shlex.shlex(line, posix=False, punctuation_chars="<")
        lexer.whitespace_split = True
        try:
            words = list(lexer)
        except ValueError:
            continue
        for index, word in enumerate(words[:-1]):
            if word != "<<":
                continue
            target = words[index + 1]
            tabs = target.startswith("-")
            target = target[1:] if tabs else target
            if re.fullmatch(r"(['\"])[A-Za-z_][A-Za-z0-9_]*\1", target):
                pending.append((target[1:-1], tabs))
    return "".join(result)


def _violation(command: str, depth: int = 0) -> str | None:
    """Return the first recognized violation in a shell list, or None.

    Malformed shell quoting returns None; ``depth`` tracks nested inspection.
    """
    # Shell continuation removes the pair, even within a command word.
    command = command.replace("\\\n", "")
    command = _without_literal_heredocs(command)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = _strip_redirections(list(lexer))
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEPARATORS or (token and all(c in ";&|()\n" for c in token)):
            segments.append([])
        else:
            segments[-1].append(token)
    for argv in segments:
        reason = _argv_reason(argv, depth)
        if reason:
            return reason
    return None


def violation(command: str) -> str | None:
    """Return a resource-policy violation for a recognizable expensive command."""
    return _violation(command)

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
