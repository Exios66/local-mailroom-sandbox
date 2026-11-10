"""Run provenance and refusal of dependency source drift (no imports switched mid-run)."""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path, PurePosixPath

from mailroom_sandbox import dojo_source, pipeline_source
from mailroom_sandbox.snapshots import (
    MAX_EXPANDED,
    MAX_FILES,
    SnapshotError,
    _inventory,
    digest,
    verify,
)


def _mutable_tree_sha256(component: str, row: dict) -> str:
    """Hash owned runtime files, including additions, without scanning site-packages."""
    try:
        roots = {}
        if row["source"] == "installed" and component == "dojo":
            candidates = dojo_source._installed_package_dirs() or []
            origin = getattr(sys.modules.get(dojo_source.PACKAGE), "__file__", None)
            package = Path(origin).resolve().parent if origin else None
            if package not in candidates:
                raise SnapshotError(
                    "Installed Dojo import has no matching distribution source root"
                )
            roots[dojo_source.PACKAGE] = package
        elif row["source"] == "installed":
            root = Path(row["path"])
            files = importlib.metadata.distribution("mailroom").files
            if not files:
                raise SnapshotError("Installed mailroom has no source ownership manifest")
            # Whole owned package roots catch newly added, unrecorded modules too.
            # RECORD may also name ../bin entry points; those are not import roots.
            names = {
                PurePosixPath(str(entry)).parts[0]
                for entry in files
                if PurePosixPath(str(entry)).parts and not PurePosixPath(str(entry)).is_absolute()
            }
            roots = {
                name: root / name
                for name in names
                if name not in {".", "..", "__pycache__"}
                and not name.endswith(".pyc")
                and not name.startswith(".")
                and not name.endswith((".dist-info", ".egg-info", ".data"))
            }
            if "pipeline" not in roots:
                raise SnapshotError("Installed mailroom manifest does not own its pipeline root")
        else:
            roots[""] = Path(row["path"])
        inventory = {}
        for prefix, root in sorted(roots.items()):
            if root.is_symlink():
                raise SnapshotError("Symlinked mutable source root")
            if root.is_dir():
                for name, item in _inventory(root).items():
                    inventory[f"{prefix}/{name}" if prefix else name] = item
            elif root.is_file():
                if root.stat().st_size > MAX_EXPANDED:
                    raise SnapshotError("Mutable source file exceeds size limit")
                inventory[prefix] = {
                    "sha256": digest(root.read_bytes()),
                    "executable": bool(root.stat().st_mode & 0o111),
                }
            else:
                raise SnapshotError("Missing installed source file or package")
            if len(inventory) > MAX_FILES:
                raise SnapshotError("Mutable source exceeds file limit")
        if not inventory:
            raise SnapshotError("Empty mutable source tree")
        return digest(json.dumps(inventory, sort_keys=True).encode())
    except (OSError, TypeError, importlib.metadata.PackageNotFoundError) as exc:
        raise SnapshotError(
            f"Cannot fingerprint {component} {row['source']} source ({type(exc).__name__})"
        ) from exc


def describe() -> dict:
    """Record portable source identities and revalidate selected cached bytes."""
    result = {}
    for name, module in (("dojo", dojo_source), ("pipeline", pipeline_source)):
        choice = module.current() or module.choose()
        row = choice.as_dict()
        # Absolute checkout paths and diagnostics are machine-local, not identity.
        result[name] = {key: row.get(key) for key in ("source", "version", "commit", "tree_sha256")}
        if row["source"] == "cached":
            verified = verify(Path(row["path"]).parent / "snapshot.lock.json", name)
            if any(verified[key] != row.get(key) for key in ("commit", "version", "tree_sha256")):
                raise SnapshotError(
                    f"Dependency source drift: selected {name} snapshot identity changed"
                )
            result[name]["tree_sha256"] = verified["tree_sha256"]
            result[name]["artifact_sha256"] = verified["sha256"]
        elif row["source"] in {"env", "installed", "vendored"}:
            result[name]["tree_sha256"] = _mutable_tree_sha256(name, row)
    return result


def verify_locked(lock: dict) -> None:
    """Refuse changed dependency identities while preserving pre-feature locks."""
    frozen = lock.get("dependency_sources")
    if frozen is None:
        return  # Historical run locks predate this field.
    current = describe()
    if current != frozen:
        changed = [name for name in ("dojo", "pipeline") if current.get(name) != frozen.get(name)]
        raise SnapshotError(
            "Dependency source drift: "
            + ", ".join(changed)
            + "; restore the locked source/explicit snapshot before resuming; run locks are not rewritten"
        )


def bundle_job_snapshots(image, *, remote_root: str = "/root"):
    """Bundle only the selected verified entries into a Modal job image at deploy time.

    No downloading, paid invocation or global cache upload. Local endpoint mode
    uses the same snapshots without a worker deployment.
    """
    settings = {}
    for name, module in (("dojo", dojo_source), ("pipeline", pipeline_source)):
        choice = module.current()
        if choice is None or choice.source != "cached":
            continue
        lock_path = Path(choice.path).parent / "snapshot.lock.json"
        item = verify(lock_path, name)
        remote = f"{remote_root}/data/cache/snapshots/{name}/{lock_path.parent.name}"
        image = image.add_local_dir(
            lock_path.parent, remote_path=remote, ignore=["**/__pycache__/**", "**/*.pyc"]
        )
        settings[f"SANDBOX_{name.upper()}_SNAPSHOT"] = f"{remote}/snapshot.lock.json"
        if item["tree_sha256"] != choice.tree_sha256:
            raise SnapshotError("Snapshot changed before image bundling")
    return image.env(settings) if settings else image
