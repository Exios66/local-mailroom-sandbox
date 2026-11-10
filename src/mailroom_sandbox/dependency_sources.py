"""Run provenance and refusal of dependency source drift (no imports switched mid-run)."""

from __future__ import annotations

from pathlib import Path

from mailroom_sandbox import dojo_source, pipeline_source
from mailroom_sandbox.snapshots import SnapshotError, digest, verify


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
        elif row["source"] == "env" and row.get("path"):
            # Explicit development trees have no release identity: freeze their Python bytes.
            root = Path(row["path"])
            hashes = [
                (p.relative_to(root).as_posix(), digest(p.read_bytes()))
                for p in sorted(root.rglob("*.py"))
                if "__pycache__" not in p.parts
            ]
            import json

            result[name]["tree_sha256"] = digest(json.dumps(hashes).encode())
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
