"""Small output helpers shared by the ``sandbox modal|vllm|hf`` command groups."""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from typing import Any


def format_command(argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
    """The exact command line a person could paste: ``KEY=value … tool arg …``."""
    prefix = [f"{key}={shlex.quote(str(value))}" for key, value in (env or {}).items()]
    return " ".join([*prefix, *(shlex.quote(part) for part in argv)])


def print_plan(argv: Sequence[str], env: Mapping[str, str] | None = None, *, cwd: str | None = None) -> None:
    """``--dry-run`` output: what would run, from where. Nothing is executed or spent."""
    print(f"dry-run: {format_command(argv, env)}")
    if cwd:
        print(f"dry-run: (from {cwd})")


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def strip_separator(rest: Sequence[str]) -> list[str]:
    """Drop the leading ``--`` argparse leaves in a REMAINDER list."""
    items = list(rest)
    return items[1:] if items[:1] == ["--"] else items
