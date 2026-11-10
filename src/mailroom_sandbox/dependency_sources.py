"""Run provenance and refusal of dependency source drift (no imports switched mid-run)."""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from mailroom_sandbox import dojo_source, pipeline_source
from mailroom_sandbox.snapshots import (
    MAX_EXPANDED,
    MAX_FILES,
    SnapshotError,
    _inventory,
    digest,
    selected,
    verify,
)


def _mutable_roots(component: str, row: dict) -> dict[str, Path]:
    """Locate only the component-owned import roots used for hashing and bundling."""
    roots = {}
    if row["source"] == "installed" and component == "dojo":
        candidates = dojo_source._installed_package_dirs() or []
        origin = getattr(sys.modules.get(dojo_source.PACKAGE), "__file__", None)
        package = Path(origin).resolve().parent if origin else None
        if package not in candidates:
            raise SnapshotError("Installed Dojo import has no matching distribution source root")
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
    return roots


def _mutable_tree_sha256(component: str, row: dict) -> str:
    """Hash owned runtime files, including additions, without scanning site-packages."""
    try:
        roots = _mutable_roots(component, row)
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


def _bundle_installed(image, component: str, row: dict, remote_root: str):
    """Mirror one installed distribution and its metadata, never all site-packages."""
    _mutable_tree_sha256(component, row)  # refuse unreadable or escaping sources before export
    distribution = importlib.metadata.distribution(
        "llm-dojo-scoring" if component == "dojo" else "mailroom"
    )
    metadata_names = {
        PurePosixPath(str(entry)).parts[0]
        for entry in distribution.files or []
        if PurePosixPath(str(entry)).parts
        and not PurePosixPath(str(entry)).is_absolute()
        and PurePosixPath(str(entry)).parts[0].endswith(".dist-info")
    }
    if len(metadata_names) != 1:
        raise SnapshotError("Installed source requires one distribution metadata directory")
    metadata_name = metadata_names.pop()
    metadata = Path(distribution.locate_file(metadata_name))
    if metadata.is_symlink() or not metadata.is_dir():
        raise SnapshotError("Missing or symlinked installed distribution metadata")
    direct_url = metadata / "direct_url.json"
    if direct_url.is_file():
        try:
            origin = urlsplit(json.loads(direct_url.read_text(encoding="utf-8")).get("url", ""))
            if origin.username or origin.password or origin.query:
                raise SnapshotError("Refusing credential-bearing installation metadata")
        except (ValueError, TypeError, AttributeError) as exc:
            raise SnapshotError("Invalid installed distribution provenance") from exc
    target = f"{remote_root}/data/cache/installed-sources/{component}"
    for name, source in _mutable_roots(component, row).items():
        if source.is_dir():
            image = image.add_local_dir(
                source, remote_path=f"{target}/{name}", ignore=["**/__pycache__/**", "**/*.pyc"]
            )
        else:
            image = image.add_local_file(source, remote_path=f"{target}/{name}")
    image = image.add_local_dir(metadata, remote_path=f"{target}/{metadata_name}")
    return image, target


def bundle_job_snapshots(image, *, remote_root: str = "/root"):
    """Bundle selected caches and installed distributions without changing source layers.

    Workers receive owned source roots and distribution metadata, not a host
    environment or a new pip installation. No downloading or paid invocation
    occurs here; deployment retains the existing spend gate.
    """
    settings = {}
    for name, module in (("dojo", dojo_source), ("pipeline", pipeline_source)):
        choice = module.current()
        if choice is None or choice.source not in {"cached", "installed"}:
            continue
        if choice.source == "installed":
            image, target = _bundle_installed(image, name, choice.as_dict(), remote_root)
            settings[f"SANDBOX_INSTALLED_{name.upper()}_ROOT"] = target
            if name == "dojo":
                settings["SANDBOX_DOJO_SOURCE"] = choice.mode
            # A matching install may target an explicit off-pin cache. Preserve
            # that target so worker bootstrap applies the same matching policy.
            item, _ = selected(name)
            if item is None:
                continue
            lock_path = Path(item["lock_path"])
        else:
            lock_path = Path(choice.path).parent / "snapshot.lock.json"
            item = verify(lock_path, name)
            if item["tree_sha256"] != choice.tree_sha256:
                raise SnapshotError("Snapshot changed before image bundling")
        remote = f"{remote_root}/data/cache/snapshots/{name}/{lock_path.parent.name}"
        image = image.add_local_dir(
            lock_path.parent, remote_path=remote, ignore=["**/__pycache__/**", "**/*.pyc"]
        )
        settings[f"SANDBOX_{name.upper()}_SNAPSHOT"] = f"{remote}/snapshot.lock.json"
    return image.env(settings) if settings else image
