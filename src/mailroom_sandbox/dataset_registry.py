"""Named datasets: the one registry a run spec points at (``config/datasets.yaml``).

A run spec names a dataset instead of embedding a machine path::

    dataset:
      name: pipeline-even100-shuffled2
      limit: 50

The entry supplies the provider fields (a pinned Hub pull or a local JSONL file).
``local_path`` expands ``${VAR}`` / ``${VAR:-default}`` from the environment — the
CLI loads ``.env`` before parsing a spec — so no checkout hard-codes a home
directory. An optional ``sha256`` pins the exact file: preparing the dataset
refuses a different one. A run lock records the prepared subset's sha256 and,
for local inputs, the source SHA in ``dataset.metadata.sha256``. Registry
``name`` and ``pull`` are recorded in metadata only when supplied.

``$SANDBOX_DATASETS_REGISTRY`` overrides the registry path (a lane- or
experiment-specific registry), defaulting to ``<repo>/config/datasets.yaml``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from mailroom_sandbox.paths import config_dir

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Keys a registry entry may hand to DatasetSpec. ``sha256`` (verified at prepare
# time), ``pull`` (lock provenance) are handled here.
_ALLOWED = frozenset({
    "provider", "repo", "config", "split", "revision", "limit", "sample_seed", "strata",
    "exclude_expected", "require_task_gt", "interim_labels", "columns", "expected_fields",
    "local_path", "sha256", "pull",
})


def registry_path() -> Path:
    """The registry file: ``$SANDBOX_DATASETS_REGISTRY``, else ``<repo>/config/datasets.yaml``."""
    return Path(os.environ.get("SANDBOX_DATASETS_REGISTRY") or (config_dir() / "datasets.yaml"))


def expand_env(value: str, *, where: str) -> str:
    """Expand ``${VAR}`` / ``${VAR:-default}``; unset (or empty) without a default raises.

    Exception: an unset ``MAILROOM_BASE_DIR`` resolves through
    :func:`mailroom_sandbox.paths.data_dir` (which reads the same variable), so a
    registry fallback like ``${MAILROOM_BASE_DIR:-...}`` matches the CLI's data
    directory instead of the caller's working directory.
    """
    def sub(match: re.Match[str]) -> str:
        """Replace one ``${VAR}`` reference with its value or default."""
        var, default = match.group(1), match.group(2)
        got = os.environ.get(var)
        if got:
            return got
        if var == "MAILROOM_BASE_DIR" and not got:
            from mailroom_sandbox.paths import data_dir

            return str(data_dir())
        if default is not None:
            return default
        raise ValueError(
            f"{where}: ${{{var}}} is not set — export it, add it to .env, "
            f"or give a fallback: ${{{var}:-path}}"
        )

    return _ENV.sub(sub, value)


def _strict_loader(yaml):
    """A SafeLoader whose mappings reject duplicate keys (a silently lost sha256 pin is a real break).

    Keys may repeat neither across dataset names nor inside one entry; both surface
    as ``yaml.constructor.ConstructorError`` — recall the load() wrapper translating it
    to a ValueError naming the registry file. No YAML merge keys (``<<``) are supported.
    """

    class StrictLoader(yaml.SafeLoader):
        """``yaml.SafeLoader`` with duplicate-key rejection at every mapping depth."""

    def construct_mapping(loader: yaml.Loader, node: yaml.Node, deep: bool = False):
        """Build one mapping; a duplicated key becomes a loud ConstructorError."""
        mapping: dict = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate registry key {key!r}", key_node.start_mark
                )
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    return StrictLoader


def load(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Parse and validate the registry; any problem raises ValueError naming the file."""
    path = Path(path) if path is not None else registry_path()
    import yaml

    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_strict_loader(yaml)) or {}  # nosec B506 -- the loader is our strict SafeLoader subclass: no arbitrary constructors
    except OSError as exc:
        raise ValueError(f"dataset registry not readable: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"dataset registry is not valid YAML: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"dataset registry must be a mapping with a 'datasets' key: {path}")
    entries = raw.get("datasets")
    if entries is None:
        return {}
    if not isinstance(entries, dict) or not entries:
        raise ValueError(f"dataset registry 'datasets' must be a non-empty mapping: {path}")
    return {str(name): _clean(str(name), body, path) for name, body in entries.items()}


def _clean(name: str, body: Any, path: Path) -> dict[str, Any]:
    """Validate one entry and normalize ``sha256`` to the spec's ``source_sha256``."""
    if not isinstance(body, dict):
        raise ValueError(f"dataset registry {path}: dataset {name!r} must be a mapping")
    unknown = sorted(set(body) - _ALLOWED)
    if unknown:
        raise ValueError(
            f"dataset registry {path}: dataset {name!r} has unknown key(s) {unknown} "
            f"(allowed: {sorted(_ALLOWED)})"
        )
    entry = dict(body)
    sha = entry.pop("sha256", None)
    if sha is not None:
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise ValueError(f"dataset registry {path}: dataset {name!r} sha256 must be 64 lowercase hex")
        entry["source_sha256"] = sha
    if "local_path" in entry:
        local = entry["local_path"]
        if not isinstance(local, str) or not local:
            raise ValueError(f"dataset registry {path}: dataset {name!r} local_path must be a non-empty string")
        # ${VAR} stays a template here and expands at spec load (exactly once),
        # so a lane missing another entry's variables can still use its own dataset.
    if entry.get("pull") is not None and not isinstance(entry["pull"], dict):
        raise ValueError(f"dataset registry {path}: dataset {name!r} pull must be a mapping")
    return entry


def resolve(data: dict[str, Any]) -> dict[str, Any]:
    """Merge a spec's ``name:`` entry under its explicit fields (the spec wins)."""
    name = data.get("name")
    if not name:
        return data
    entries = load()
    try:
        entry = entries[str(name)]
    except KeyError:
        raise ValueError(
            f"dataset.name {name!r} is not in {registry_path()} "
            f"(known: {sorted(entries) or 'none'})"
        ) from None
    merged = {"name": str(name), **entry, **{k: v for k, v in data.items() if k != "name"}}
    # NO expansion here: DatasetSpec's validator expands local_path exactly once,
    # for named and explicit specs alike (a second pass re-expanded any literal
    # ${...} that survived the first one).
    return merged


__all__ = ["expand_env", "load", "registry_path", "resolve"]
