"""Offline pipeline resolution: explicit source, matching install/cache, vendor."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from mailroom_sandbox import dojo_source
from mailroom_sandbox.paths import vendored_mailroom_src
from mailroom_sandbox.snapshots import PINS, selected, valid_source


@dataclass(frozen=True)
class PipelineSource:
    source: str
    path: str | None
    version: str | None
    commit: str | None
    reason: str
    tree_sha256: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_CHOICE: PipelineSource | None = None


def pinned() -> dict:
    """Return reviewed pipeline identity even without a vendor directory."""
    return dict(PINS["pipeline"])


def installed() -> dict | None:
    """Inspect installed mailroom metadata without importing family modules."""
    try:
        dist = importlib.metadata.distribution("mailroom")
    except importlib.metadata.PackageNotFoundError:
        return None
    try:
        commit = (
            (json.loads(dist.read_text("direct_url.json") or "{}")).get("vcs_info") or {}
        ).get("commit_id")
    except (ValueError, TypeError, AttributeError):
        commit = None
    return {
        "version": dist.version,
        "commit": commit,
        "path": str(Path(dist.locate_file("")).resolve()),
    }


def _prepend(root: Path) -> str:
    """Keep cached modules from a prior explicit selection from shadowing this one."""
    for package in ("pipeline", "graph", "agents", "llm", "legalbench"):
        module = sys.modules.get(package)
        origin = getattr(module, "__file__", None)
        if origin and Path(origin).resolve().parent != root.resolve() / package:
            for name in list(sys.modules):
                if name == package or name.startswith(package + "."):
                    del sys.modules[name]
    return dojo_source._prepend(root)


def choose() -> PipelineSource:
    """Select and remember the first acceptable offline pipeline source."""
    global _CHOICE
    diagnostics = []
    env = dojo_source._setting("MAILROOM_SRC")
    if env:
        root = Path(env).expanduser()
        root = root / "src" if (root / "src" / "pipeline").is_dir() else root
        if valid_source("pipeline", root):
            _CHOICE = PipelineSource("env", _prepend(root), None, None, "MAILROOM_SRC")
            return _CHOICE
        diagnostics.append("MAILROOM_SRC has no complete runtime tree")
    else:
        diagnostics.append("MAILROOM_SRC unset")
    snapshot, why = selected("pipeline")
    target = snapshot or pinned()
    have = installed()
    if have and have["version"] == target["version"] and have["commit"] == target["commit"]:
        root = Path(have["path"])
        # Wheel must include every runtime namespace; source-only helpers remain optional.
        if valid_source("pipeline", root):
            try:
                _prepend(root)
                module = importlib.import_module("pipeline")
                if Path(module.__file__).resolve().parent != root / "pipeline":
                    raise ImportError("pipeline import is shadowed")
                _CHOICE = PipelineSource(
                    "installed",
                    str(root),
                    have["version"],
                    have["commit"],
                    "matching installed mailroom",
                )
                return _CHOICE
            except Exception as exc:  # noqa: BLE001 - broken installed layer falls back
                diagnostics.append(f"installed import rejected ({type(exc).__name__})")
        else:
            diagnostics.append("installed mailroom lacks runtime namespaces")
    else:
        diagnostics.append("installed mailroom missing or off pin/lock")
    if snapshot:
        _CHOICE = PipelineSource(
            "cached",
            _prepend(Path(snapshot["path"])),
            snapshot["version"],
            snapshot["commit"],
            why,
            snapshot["tree_sha256"],
        )
        return _CHOICE
    diagnostics.append(why)
    vendor = vendored_mailroom_src()
    if vendor is not None:
        # The tracked snapshot can be newer than its package's version string.
        pin = pinned()
        metadata = vendor.parent / "VENDOR.md"
        if metadata.is_file():
            match = re.search(r"Exact source commit:\s*`([0-9a-f]{40})`", metadata.read_text())
            if match:
                pin["commit"] = match.group(1)
        _CHOICE = PipelineSource(
            "vendored",
            _prepend(vendor),
            pin["version"],
            pin["commit"],
            "; ".join(diagnostics),
        )
        return _CHOICE
    diagnostics.append("vendored pipeline missing")
    _CHOICE = PipelineSource("none", None, None, None, "; ".join(diagnostics))
    return _CHOICE


def current() -> PipelineSource | None:
    """Return the source selected at package bootstrap."""
    return _CHOICE
