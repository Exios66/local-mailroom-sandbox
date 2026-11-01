"""Where ``llm_dojo_scoring`` is imported from: the installed release first, the vendored snapshot as backup.

The sandbox carries a tracked Dojo snapshot under ``vendor/llm-dojo-scoring`` (DMR-057), so
a fresh checkout scores offline. When a released ``llm-dojo-scoring`` distribution is
installed in the environment (``pip install -r requirements/dojo-release.txt``, the pinned
GitHub release), it is the primary source and the snapshot is only the fallback: if the release
is missing, is a different version or commit than the snapshot pins, or fails to import,
the snapshot is used instead, so scoring never goes down with the install.

``SANDBOX_DOJO_SOURCE`` picks the policy:

* ``auto`` (default): installed when it matches the pin and imports; vendored otherwise.
* ``installed``: installed whenever it imports, even off-pin; vendored only if it is absent.
* ``vendored``: always the snapshot (the pre-0.25 behaviour).

``DOJO_SRC`` (a source tree) overrides all three. :func:`choose` runs once, from the
package ``__init__``, before anything imports the Dojo; :func:`current` reports the choice
(the run lock records it under ``versions.llm_dojo_scoring_source``).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import vendored_dojo_src

DIST = "llm-dojo-scoring"
PACKAGE = "llm_dojo_scoring"
MODES = ("auto", "installed", "vendored")


@dataclass(frozen=True)
class DojoSource:
    source: str  # installed | vendored | env | none
    path: str | None  # import root that was put on sys.path (None for installed)
    version: str | None
    commit: str | None
    mode: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_CHOICE: DojoSource | None = None


def pinned() -> dict[str, str | None]:
    """Version and commit the vendored snapshot pins (read from files; nothing imported)."""
    src = vendored_dojo_src()
    if src is None:
        return {"version": None, "commit": None}
    init = (src / PACKAGE / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'^__version__\s*=\s*["\']([^"\']+)', init, re.M)
    commit = None
    vendor_md = src.parent / "VENDOR.md"
    if vendor_md.is_file():
        found = re.search(r"Exact source commit:\s*`([0-9a-f]{40})`", vendor_md.read_text(encoding="utf-8"))
        commit = found.group(1) if found else None
    return {"version": version.group(1) if version else None, "commit": commit}


def installed() -> dict[str, str | None] | None:
    """The installed distribution's version and git commit, or None when not installed."""
    try:
        dist = importlib.metadata.distribution(DIST)
    except importlib.metadata.PackageNotFoundError:
        return None
    commit = None
    raw = dist.read_text("direct_url.json")
    if raw:
        try:
            commit = (json.loads(raw).get("vcs_info") or {}).get("commit_id")
        except ValueError:
            commit = None
    return {"version": dist.version, "commit": commit}


def _purge() -> None:
    for name in [m for m in sys.modules if m == PACKAGE or m.startswith(PACKAGE + ".")]:
        del sys.modules[name]


def _import_ok() -> str | None:
    """Import the Dojo from the current sys.path; the error text, or None when it imported."""
    try:
        if importlib.util.find_spec(PACKAGE) is None:
            return "not importable"
        importlib.import_module(PACKAGE)
        return None
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        _purge()
        return f"{type(exc).__name__}: {exc}"


def _prepend(path: Path) -> str:
    resolved = str(path.resolve())
    if resolved in sys.path:
        sys.path.remove(resolved)
    sys.path.insert(0, resolved)
    return resolved


def _vendored(mode: str, reason: str) -> DojoSource:
    src = vendored_dojo_src()
    pin = pinned()
    if src is None:
        return DojoSource("none", None, None, None, mode, reason + "; no vendored snapshot either")
    return DojoSource("vendored", _prepend(src), pin["version"], pin["commit"], mode, reason)


def choose(*, mode: str | None = None, verify_import: bool = True) -> DojoSource:
    """Pick the Dojo source, put it on ``sys.path``, and remember the choice."""
    global _CHOICE
    mode = (mode or os.environ.get("SANDBOX_DOJO_SOURCE") or "auto").strip().lower()
    if mode not in MODES:
        mode = "auto"
    env = os.environ.get("DOJO_SRC", "").strip()
    if env and (Path(env) / PACKAGE / "__init__.py").is_file():
        _CHOICE = DojoSource("env", _prepend(Path(env)), None, None, mode, "DOJO_SRC")
        return _CHOICE
    if mode == "vendored":
        _CHOICE = _vendored(mode, "SANDBOX_DOJO_SOURCE=vendored")
        return _CHOICE
    have, pin = installed(), pinned()
    if have is None:
        _CHOICE = _vendored(mode, f"{DIST} is not installed")
        return _CHOICE
    if mode == "auto":
        if pin["version"] and have["version"] != pin["version"]:
            _CHOICE = _vendored(mode, f"installed {have['version']} != pinned {pin['version']}")
            return _CHOICE
        if pin["commit"] and have["commit"] and have["commit"] != pin["commit"]:
            _CHOICE = _vendored(mode, f"installed commit {have['commit'][:12]} != pinned {pin['commit'][:12]}")
            return _CHOICE
    # The vendored root must not shadow the release we are about to verify.
    src = vendored_dojo_src()
    if src is not None:
        vendored = src.resolve()
        sys.path[:] = [p for p in sys.path if not p or Path(p).resolve() != vendored]
    error = _import_ok() if verify_import else None
    if error is not None:
        _CHOICE = _vendored(mode, f"installed release failed to import ({error})")
        return _CHOICE
    _CHOICE = DojoSource("installed", None, have["version"], have["commit"], mode,
                         "installed release matches the pin" if mode == "auto" else "SANDBOX_DOJO_SOURCE=installed")
    return _CHOICE


def current() -> DojoSource | None:
    return _CHOICE


def import_root() -> Path | None:
    """The source tree to prepend for the chosen Dojo (None when the installed release is used)."""
    choice = _CHOICE or choose()
    return Path(choice.path) if choice.path else None
