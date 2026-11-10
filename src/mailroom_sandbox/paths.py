"""Filesystem roots for the local-mailroom-sandbox checkout."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


OFFLINE_SHARED_VALUE_OPTIONS = frozenset({"--profile", "--model", "--prompt", "--agent-model"})
OFFLINE_AGENT_COMMANDS = frozenset({"preflight", "dispatch-check", "checkpoint"})

_DOTENV_DISABLED: ContextVar[bool] = ContextVar("mailroom_dotenv_disabled", default=False)


def offline_agent_invocation(argv: list[str]) -> bool:
    """Recognize offline agent entry points before package/CLI bootstrap.

    Consume shared option values so a prompt/model named ``subagents`` does
    not accidentally disable normal configuration loading.
    """
    shared = OFFLINE_SHARED_VALUE_OPTIONS
    words = []
    index = 0
    while index < len(argv) and len(words) < 2:
        token = argv[index]
        if token in shared:
            index += 2
            continue
        if token.split("=", 1)[0] not in shared and not token.startswith("-"):
            words.append(token)
        index += 1
    return len(words) == 2 and words[0] == "subagents" and words[1] in OFFLINE_AGENT_COMMANDS


@contextmanager
def without_dotenv():
    """Suppress dotenv discovery in this context without changing environment variables."""
    token = _DOTENV_DISABLED.set(True)
    try:
        yield
    finally:
        _DOTENV_DISABLED.reset(token)


def repo_root() -> Path:
    """Resolve the sandbox checkout root.

    Walks up from this file looking for ``pyproject.toml``. ``SANDBOX_ROOT``
    wins when set (tests, relocated installs).
    """
    env = os.environ.get("SANDBOX_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir():
            return candidate
    return Path.cwd()


def dotenv_files() -> list[Path]:
    """Existing dotenv files by precedence, unless offline bootstrap suppresses discovery."""
    if _DOTENV_DISABLED.get() or offline_agent_invocation(sys.argv[1:]):
        return []
    root = repo_root()
    return [p for p in (root / ".env", root / "config" / ".env") if p.is_file()]


def config_dir() -> Path:
    return repo_root() / "config"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def prompts_dir() -> Path:
    return config_dir() / "prompts"


def runbooks_dir() -> Path:
    return config_dir() / "runbooks"


def deploy_dir() -> Path:
    return repo_root() / "deploy"


def data_dir() -> Path:
    return Path(os.environ.get("MAILROOM_BASE_DIR") or (repo_root() / "data")).resolve()


def fixtures_dir() -> Path:
    return repo_root() / "data" / "fixtures"


def runtime_dir() -> Path:
    path = data_dir() / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    path = repo_root() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def vendor_dir() -> Path:
    return repo_root() / "vendor"


def vendored_mailroom_src() -> Path | None:
    """Tracked llm-mailroom snapshot (DMR-057) or None when pruned."""
    cand = vendor_dir() / "llm-mailroom" / "src"
    return cand if (cand / "pipeline" / "config.py").is_file() else None


def vendored_dojo_src() -> Path | None:
    """Tracked llm-dojo-scoring snapshot (DMR-057) or None when pruned."""
    cand = vendor_dir() / "llm-dojo-scoring" / "src"
    return cand if (cand / "llm_dojo_scoring" / "__init__.py").is_file() else None
