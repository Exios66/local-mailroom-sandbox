"""Bounded, verified release snapshots. No network or writes during source selection."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import shutil
import stat
import tarfile
import tempfile
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import httpx

from mailroom_sandbox.paths import repo_root

COMPONENTS = {"dojo": "llm-dojo-scoring", "pipeline": "llm-mailroom"}
# Independent of vendor availability. Deliberately reviewed alongside _VENDOR_PINS.
PINS = {
    "dojo": {"version": "0.28.1", "commit": "00a2a7f7b058a4ade06b027c2afbd8b03bea6a5f"},
    "pipeline": {"version": "0.9.1", "commit": "19203eac07f67c215f50af2fd498560ce195adae"},
}
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILES = 20000
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class SnapshotError(ValueError):
    """A release or cache entry could not be verified."""


def cache_root() -> Path:
    """Repo-local like the dataset cache; MAILROOM_BASE_DIR does not relocate it."""
    return repo_root() / "data" / "cache" / "snapshots"


def digest(data: bytes) -> str:
    """Hash the supplied artifact or canonical inventory bytes with SHA-256."""
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (ValueError, UnicodeError) as exc:
        raise SnapshotError(f"Invalid JSON metadata: {exc}") from exc


def _get(url: str, *, limit: int = MAX_DOWNLOAD) -> bytes:
    """Public GitHub only; no credentials forwarded to redirected download hosts."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"api.github.com", "github.com", "codeload.github.com"}
        or parsed.username
        or parsed.query
    ):
        raise SnapshotError("Unexpected release URL")
    try:

        def guard(request):
            host = request.url.host
            if request.url.scheme != "https" or not (
                host in {"github.com", "api.github.com", "codeload.github.com"}
                or host.endswith(".githubusercontent.com")
            ):
                raise SnapshotError("Unexpected release redirect host")

        with httpx.Client(
            follow_redirects=True, timeout=60.0, event_hooks={"request": [guard]}
        ) as client:
            with client.stream(
                "GET", url, headers={"User-Agent": "mailroom-sandbox-snapshots"}
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise SnapshotError(f"Download exceeds {limit} bytes")
                    chunks.append(chunk)
                return b"".join(chunks)
    except httpx.HTTPError as exc:
        # Do not include signed redirect URLs from response exceptions.
        raise SnapshotError(f"Release download failed ({type(exc).__name__})") from None


def release(component: str, version: str | None = None) -> dict:
    """Resolve a published stable release through the component owner's GitHub API."""
    repo = COMPONENTS[component]
    if version and not _TAG.fullmatch(version):
        raise SnapshotError("Version must be a safe release tag")
    suffix = f"tags/{quote(version, safe='')}" if version else "latest"
    value = _json(
        _get(f"https://api.github.com/repos/Exios66/{repo}/releases/{suffix}", limit=1024 * 1024)
    )
    tag = value.get("tag_name", "")
    if (
        not isinstance(tag, str)
        or not _TAG.fullmatch(tag)
        or value.get("draft")
        or value.get("prerelease")
    ):
        raise SnapshotError("Expected a stable published release")
    if version and tag != version:
        raise SnapshotError("Release tag differs from requested version")
    return value


def _commit(component: str, tag: str) -> str:
    """Peel lightweight or annotated tags without trusting mutable target_commitish."""
    base = f"https://api.github.com/repos/Exios66/{COMPONENTS[component]}/git"
    obj = _json(_get(f"{base}/ref/tags/{quote(tag, safe='')}", limit=1024 * 1024)).get("object", {})
    for _ in range(8):
        if not isinstance(obj, dict):
            raise SnapshotError("Invalid Git tag object")
        sha = obj.get("sha", "")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise SnapshotError("Tag has no immutable commit")
        if obj.get("type") == "commit":
            return sha
        if obj.get("type") != "tag":
            break
        obj = _json(_get(f"{base}/tags/{sha}", limit=1024 * 1024)).get("object", {})
    raise SnapshotError("Tag does not resolve to a commit")


def _relative(name: str) -> Path:
    """Validate portable archive member names before joining the staging root."""
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or ":" in name
        or "\x00" in name
    ):
        raise SnapshotError(f"Unsafe archive path: {name!r}")
    return Path(*path.parts)


def _extract(data: bytes, dest: Path, *, wheel: bool) -> None:
    """Copy only regular files; refuse links/specials, duplicates and expansion bombs."""
    size, count, seen = 0, 0, set()

    def copy(name, length, mode, stream):
        nonlocal size, count
        relative = _relative(name)
        if "__pycache__" in relative.parts or relative.suffix == ".pyc":
            raise SnapshotError("Release contains precompiled bytecode")
        count += 1
        size += length
        if count > MAX_FILES or length < 0 or size > MAX_EXPANDED or relative in seen:
            raise SnapshotError("Archive exceeds extraction limits or has duplicate files")
        seen.add(relative)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            remaining = length
            while remaining:
                block = stream.read(min(remaining, 1024 * 1024))
                if not block:
                    raise SnapshotError("Truncated archive member")
                output.write(block)
                remaining -= len(block)
            if stream.read(1):
                raise SnapshotError("Archive member exceeds declared size")
        target.chmod(0o755 if mode & 0o111 else 0o644)

    try:
        if wheel:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > MAX_FILES:
                    raise SnapshotError("Archive exceeds member limit")
                for entry in members:
                    _relative(entry.filename)
                    mode = entry.external_attr >> 16
                    if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise SnapshotError("Archive links and special files are refused")
                    if not entry.is_dir():
                        with archive.open(entry) as stream:
                            copy(entry.filename, entry.file_size, mode, stream)
        else:
            # tarfile stops at the tar end marker without necessarily reading
            # the gzip trailer. Consume it separately to detect truncation/CRC
            # failures, with a bound including tar headers and alignment.
            expanded_size = 0
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as expanded:
                while block := expanded.read(1024 * 1024):
                    expanded_size += len(block)
                    if expanded_size > MAX_EXPANDED + MAX_FILES * 1024 + 10240:
                        raise SnapshotError("Archive exceeds decompression limit")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                for index, entry in enumerate(archive):
                    if index >= MAX_FILES:
                        raise SnapshotError("Archive exceeds member limit")
                    _relative(entry.name)
                    if entry.isdir():
                        continue
                    if not entry.isfile():
                        raise SnapshotError("Archive links and special files are refused")
                    with archive.extractfile(entry) as stream:
                        copy(entry.name, entry.size, entry.mode, stream)
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, OSError) as exc:
        raise SnapshotError(f"Invalid archive ({type(exc).__name__})") from exc
    if not count:
        raise SnapshotError("Empty archive")


def valid_source(component: str, root: Path) -> bool:
    """Require the import namespaces consumed by the sandbox runtime."""
    required = (
        ["llm_dojo_scoring/__init__.py"]
        if component == "dojo"
        else [
            "pipeline/config.py",
            "graph/build_graph.py",
            "agents/__init__.py",
            "llm/__init__.py",
            "legalbench/__init__.py",
        ]
    )
    return all((root / name).is_file() for name in required)


def _inventory(root: Path) -> dict:
    """Hash every regular source file and executable mode within bounded limits."""
    if root.is_symlink() or not root.is_dir():
        raise SnapshotError("Missing or symlinked cached source root")
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        # Python import caches are generated after validation, never source inputs.
        relative = path.relative_to(root)
        if path.is_symlink():
            raise SnapshotError("Symlink in cached source")
        if "__pycache__" in relative.parts:
            continue
        if path.suffix == ".pyc":
            raise SnapshotError("Untracked bytecode in cached source")
        if path.is_file():
            total += path.stat().st_size
            if len(result) >= MAX_FILES or total > MAX_EXPANDED:
                raise SnapshotError("Cached source exceeds limits")
            result[relative.as_posix()] = {
                "sha256": digest(path.read_bytes()),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        elif not path.is_dir():
            raise SnapshotError("Special file in cached source")
    return result


def verify(lock_path: Path, component: str) -> dict:
    """Validate complete source inventory before returning an offline cache choice."""
    if lock_path.is_symlink() or any(p.is_symlink() for p in lock_path.parents):
        raise SnapshotError("Symlinked snapshot path")
    try:
        if lock_path.stat().st_size > 8 * 1024 * 1024:
            raise SnapshotError("Oversized snapshot lock")
        lock = _json(lock_path.read_bytes())
        if lock.get("schema") != "mailroom.snapshot/v1" or lock.get("component") != component:
            raise SnapshotError("Snapshot schema/component mismatch")
        if not _SHA.fullmatch(str(lock.get("commit", ""))) or not _HASH.fullmatch(
            str(lock.get("sha256", ""))
        ):
            raise SnapshotError("Snapshot commit/digest missing")
        if not isinstance(lock.get("tag"), str) or not _TAG.fullmatch(lock["tag"]):
            raise SnapshotError("Invalid snapshot tag")
        if not isinstance(lock.get("version"), str) or not lock["version"]:
            raise SnapshotError("Missing snapshot package version")
        try:
            if datetime.fromisoformat(lock["fetched_at"]).tzinfo is None:
                raise ValueError("missing timezone")
        except (ValueError, TypeError, KeyError) as exc:
            raise SnapshotError("Invalid snapshot fetch date") from exc
        root = lock_path.parent / "source"
        inventory = _inventory(root)
        if not valid_source(component, root) or not inventory or inventory != lock.get("files"):
            raise SnapshotError("Snapshot source inventory mismatch")
        if digest(json.dumps(inventory, sort_keys=True).encode()) != lock.get("tree_sha256"):
            raise SnapshotError("Snapshot tree digest mismatch")
        return {**lock, "path": str(root.resolve()), "lock_path": str(lock_path.resolve())}
    except (OSError, TypeError) as exc:
        raise SnapshotError(f"Unreadable snapshot ({type(exc).__name__})") from exc


def cached(component: str) -> tuple[list[dict], list[str]]:
    """Return verified entries newest first, alongside rejected-entry diagnostics."""
    entries, errors = [], []
    for path in sorted((cache_root() / component).glob("*/snapshot.lock.json")):
        try:
            entries.append(verify(path, component))
        except SnapshotError as exc:
            errors.append(f"{path.parent.name}: {exc}")
    return sorted(entries, key=lambda item: item.get("fetched_at", ""), reverse=True), errors


def selected(component: str) -> tuple[dict | None, str]:
    """Explicit lock or pin-matching cache only; a fetch never upgrades imports."""
    from mailroom_sandbox.dojo_source import _setting

    path = _setting(f"SANDBOX_{component.upper()}_SNAPSHOT")
    if path:
        try:
            return verify(Path(path).expanduser(), component), "explicit snapshot lock"
        except SnapshotError as exc:
            return None, f"explicit snapshot rejected: {exc}"
    entries, errors = cached(component)
    for item in entries:
        if all(item[key] == PINS[component][key] for key in ("commit", "version")):
            return item, "verified cache matches reviewed pin"
    return None, "; ".join(["no verified pin-matching cache", *errors])


def fetch(component: str, *, version: str | None = None, refresh: bool = False) -> dict:
    """Resolve once, verify, stage, and atomically install. Never touch vendor files."""
    if component not in COMPONENTS or (version and not _TAG.fullmatch(version)):
        raise SnapshotError("Invalid component or release tag")
    entries, _ = cached(component)
    if not refresh:
        for entry in entries:
            if (version and entry["tag"] == version) or (
                not version and entry.get("resolved_stable")
            ):
                return {**entry, "cache_hit": True}
    rel = release(component, version)
    tag = rel["tag_name"]
    commit = _commit(component, tag)
    if any(e["tag"] == tag and e["commit"] != commit for e in entries):
        raise SnapshotError("Released tag moved since the verified cache was created")
    release_assets = rel.get("assets", [])
    if not isinstance(release_assets, list) or any(
        not isinstance(a, dict)
        or not isinstance(a.get("name"), str)
        or not isinstance(a.get("browser_download_url"), str)
        for a in release_assets
    ):
        raise SnapshotError("Invalid release asset metadata")
    assets = {a["name"]: a["browser_download_url"] for a in release_assets}
    if len(assets) != len(release_assets):
        raise SnapshotError("Duplicate release asset names")
    provenance = "release-manifest+SHA256SUMS"
    wheel = False
    if "release-manifest.json" in assets and "SHA256SUMS" in assets:
        manifest = _json(_get(assets["release-manifest.json"], limit=1024 * 1024))
        if (
            manifest.get("commit") != commit
            or manifest.get("tag") != tag
            or manifest.get("package") != COMPONENTS[component]
        ):
            raise SnapshotError("Release manifest identity does not match resolved tag")
        files = manifest.get("files", [])
        if not isinstance(files, list) or any(not isinstance(f, dict) for f in files):
            raise SnapshotError("Invalid release manifest file metadata")
        artifact = next((f for f in files if f.get("kind") == "wheel"), None) or next(
            (f for f in files if f.get("kind") == "sdist"), None
        )
        if not artifact or artifact.get("name") not in assets:
            raise SnapshotError("Manifest artifact missing from release")
        name = artifact["name"]
        checksums = {}
        for line in _get(assets["SHA256SUMS"], limit=1024 * 1024).decode("utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                checksums[parts[1].lstrip("*")] = parts[0]
        expected = artifact.get("sha256", "")
        if (
            not isinstance(expected, str)
            or not _HASH.fullmatch(expected)
            or checksums.get(name) != expected
        ):
            raise SnapshotError("Manifest and SHA256SUMS disagree")
        url = assets[name]
        data = _get(url)
        if digest(data) != expected or len(data) != artifact.get("size"):
            raise SnapshotError("Release artifact checksum/size mismatch")
        wheel = name.endswith(".whl")
    elif component == "pipeline" and not assets:
        # The tag is peeled to a commit; target_commitish may be mutable 'main'.
        url = f"https://api.github.com/repos/Exios66/{COMPONENTS[component]}/tarball/{commit}"
        data = _get(url)
        expected = digest(data)
        provenance = "github-commit-archive; locally-computed-sha256"
        manifest = {"version": tag.removeprefix("v")}
    else:
        raise SnapshotError("Release manifest or SHA256SUMS missing")
    parent = cache_root() / component
    if any(p.is_symlink() for p in [parent, *parent.parents]):
        raise SnapshotError("Symlinked cache root")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / f"{tag}-{commit[:12]}"
    if destination.exists():
        existing = verify(destination / "snapshot.lock.json", component)
        if existing["sha256"] != expected:
            raise SnapshotError("Existing immutable release differs from download")
        return {**existing, "cache_hit": True}
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=parent) as temporary:
        staging = Path(temporary)
        extracted = staging / "unpacked"
        extracted.mkdir()
        _extract(data, extracted, wheel=wheel)
        if provenance.startswith("github-commit-archive"):
            projects = list(extracted.glob("*/pyproject.toml"))
            if len(projects) != 1:
                raise SnapshotError("Commit archive lacks package version metadata")
            try:
                project = tomllib.loads(projects[0].read_text(encoding="utf-8"))["project"]
                if project.get("name") != "mailroom" or not isinstance(project.get("version"), str):
                    raise ValueError("wrong package metadata")
                manifest["version"] = project["version"]
            except (ValueError, KeyError, UnicodeError) as exc:
                raise SnapshotError("Invalid commit archive package metadata") from exc
        candidates = [
            extracted,
            extracted / "src",
            *[p / "src" for p in extracted.iterdir() if p.is_dir()],
            *[p for p in extracted.iterdir() if p.is_dir()],
        ]
        source = next((p for p in candidates if valid_source(component, p)), None)
        if source is None:
            raise SnapshotError("Release has no usable runtime source tree")
        ready = staging / "ready"
        ready.mkdir()
        shutil.move(str(source), ready / "source")
        inventory = _inventory(ready / "source")
        lock = {
            "schema": "mailroom.snapshot/v1",
            "component": component,
            "tag": tag,
            "version": manifest.get("version", tag.removeprefix("v")),
            "commit": commit,
            "sha256": expected,
            "source_url": url,
            "verification": provenance,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "published_at": rel.get("published_at"),
            "resolved_stable": version is None,
            "files": inventory,
            "tree_sha256": digest(json.dumps(inventory, sort_keys=True).encode()),
        }
        (ready / "snapshot.lock.json").write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8"
        )
        verify(ready / "snapshot.lock.json", component)
        try:
            ready.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            other = verify(destination / "snapshot.lock.json", component)
            if other["sha256"] != expected:
                raise SnapshotError("Concurrent fetch installed different release bytes") from None
    return {**verify(destination / "snapshot.lock.json", component), "cache_hit": False}


def _public(item: dict) -> dict:
    """Omit the verbose file inventory from operator-facing JSON output."""
    return {k: v for k, v in item.items() if k != "files"}


def check(component: str, *, online: bool = True, version: str | None = None) -> dict:
    """Read-only layer report. Network failures are facts, not update failures."""
    from mailroom_sandbox import dojo_source
    from mailroom_sandbox import pipeline_source

    entries, errors = cached(component)
    module = dojo_source if component == "dojo" else pipeline_source
    report = {
        "component": component,
        "vendored_pin": module.pinned(),
        "installed": module.installed(),
        "cached": [_public(e) for e in entries],
        "cache_errors": errors,
        "selected": module.current().as_dict() if module.current() else None,
        "latest_stable": None,
        "requested_match": None,
    }
    if online:
        try:
            rel = release(component)
            report["latest_stable"] = {
                "tag": rel["tag_name"],
                "published_at": rel.get("published_at"),
            }
        except SnapshotError as exc:
            report["latest_error"] = str(exc)
    if version:
        report["requested_match"] = any(e["tag"] == version for e in entries)
    return report


def register(sub, leaf) -> None:
    """Register the dependency command family with shared CLI options."""
    parser = sub.add_parser(
        "deps", parents=[leaf], help="verified stable dependency snapshot cache"
    )
    commands = parser.add_subparsers(dest="deps_command", required=True)
    command = commands.add_parser(
        "fetch", parents=[leaf], help="fetch a release or inspect dependency layers"
    )
    command.add_argument("--component", choices=[*COMPONENTS, "all"], default="all")
    group = command.add_mutually_exclusive_group()
    group.add_argument("--stable", action="store_true", help="resolve latest stable on first fetch")
    group.add_argument("--version", help="exact published release tag")
    command.add_argument(
        "--check", action="store_true", help="read-only comparison including latest stable"
    )
    command.add_argument(
        "--offline", action="store_true", help="check local layers without network"
    )
    command.add_argument(
        "--refresh",
        action="store_true",
        help="explicitly resolve stable again instead of offline cache reuse",
    )
    command.set_defaults(handler=_command)


def _command(args) -> int:
    """Report each requested component and preserve independent failure evidence."""
    components = COMPONENTS if args.component == "all" else [args.component]
    if args.offline and not args.check:
        print("--offline requires --check; normal cache hits already work offline")
        return 2
    reports, failed = [], False
    for component in components:
        try:
            report = (
                check(component, online=not args.offline, version=args.version)
                if args.check
                else _public(fetch(component, version=args.version, refresh=args.refresh))
            )
            if args.check and report["requested_match"] is False:
                failed = True
            reports.append(report)
        except (SnapshotError, OSError, UnicodeError, KeyError, TypeError) as exc:
            failed = True
            reports.append({"component": component, "error": str(exc)})
    print(json.dumps(reports, indent=2))
    return int(failed)
