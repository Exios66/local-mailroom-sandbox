"""Staged production label overlays pulled from the mailroom-issues ``mailroom_cache``.

A ``production-overlay`` pre-release (``mailroom_cache/vX.Y.0/pre-release/vX.Y.P-rc.N/``, cut by
``scripts/stage_label_overlay.py``) is the merged master of the Hub, interim, near-gold and
reviewed label layers, stored as the per-document delta against the Hub labels. A run opts in
with ``dataset.staged_overlay: <version>``; the overlay then replaces the interim and near-gold
overlays (it already contains them), so the three are mutually exclusive.

Trust comes from the pins in ``config/staged_overlays.yaml``, never from the cache: each pinned
version names the mailroom-issues commit and the sha256 of the cut's ``MANIFEST.json``, and the
manifest pins every overlay file's sha256. :func:`snapshot` refuses a cut whose bytes differ.
A record applies only to the document whose text has its ``content_sha256``; the Hub label is
replaced field by field, and a replaced Hub value is kept on the row under
``staged_overlay.overrides`` so a score that used it is never read as a Hub-GT score.

``scripts/pull_staged_overlay.py`` fetches a pinned cut into :func:`cache_root`
(``$SANDBOX_LABEL_CACHE``, default ``data/cache/mailroom_cache``).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox.paths import repo_root

PINS_FILE = "config/staged_overlays.yaml"
ENV_ROOT = "SANDBOX_LABEL_CACHE"
KIND = "production-overlay"
#: overlay presence -> the Dojo presence code the scorer reads (``gt_presence``)
PRESENCE = {"populated": "populated", "documented_absence": "schema_documented_absence"}
#: fields the overlay carries but scoring takes from elsewhere: subclass repairs are SHF-013
#: (``data/labels/review/subclass_corrections.jsonl``), never a second, unpinned copy.
NOT_APPLIED = frozenset({"subclass"})
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"\d+\.\d+\.\d+-rc\.\d+")


class StagedOverlayError(ValueError):
    """A staged overlay that is unpinned, missing or not the pinned bytes."""


def _version(version: str) -> str:
    v = str(version).removeprefix("v")
    if not _VERSION.fullmatch(v):
        raise StagedOverlayError(f"staged overlay version {version!r} is not X.Y.P-rc.N")
    return v


def pins(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The pinned staged overlays, by version (no ``v`` prefix)."""
    import yaml

    path = path or repo_root() / PINS_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for version, pin in (data.get("overlays") or {}).items():
        v = _version(version)
        missing = {"repo", "commit", "path", "manifest_sha256", "base_tag_commit"} - set(pin or {})
        if missing:
            raise StagedOverlayError(f"{PINS_FILE}: {version} lacks {sorted(missing)}")
        if not _HEX40.fullmatch(pin["commit"]) or not _HEX40.fullmatch(pin["base_tag_commit"]):
            raise StagedOverlayError(f"{PINS_FILE}: {version} commits must be 40 lowercase hex characters")
        if not _HEX64.fullmatch(pin["manifest_sha256"]):
            raise StagedOverlayError(f"{PINS_FILE}: {version} manifest_sha256 must be 64 lowercase hex characters")
        if Path(pin["path"]).is_absolute() or ".." in Path(pin["path"]).parts:
            raise StagedOverlayError(f"{PINS_FILE}: {version} path must be relative to mailroom_cache/")
        out[v] = dict(pin)
    return out


def pin(version: str) -> dict[str, Any]:
    v = _version(version)
    known = pins()
    if v not in known:
        raise StagedOverlayError(f"staged overlay {v} is not pinned in {PINS_FILE} (pinned: {sorted(known)})")
    return known[v]


def cache_root() -> Path:
    env = os.environ.get(ENV_ROOT)
    return Path(env) if env else repo_root() / "data" / "cache" / "mailroom_cache"


def cut_dir(version: str, root: Path | None = None) -> Path:
    return (root or cache_root()) / pin(version)["path"]


def fingerprint(version: str) -> str:
    """What the spec hash and run lock record: the pinned MANIFEST.json sha256."""
    return pin(version)["manifest_sha256"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(version: str, root: Path | None = None
             ) -> tuple[dict[str, dict[str, Any]], str, list[str]]:
    """``(overlay by document id, manifest sha256, problems)`` for a pinned version.

    Problems name every way the cache differs from the pin; callers refuse on any.
    """
    p, v = pin(version), _version(version)
    d = cut_dir(v, root)
    mpath = d / "MANIFEST.json"
    if not mpath.is_file():
        return {}, "", [f"staged overlay {v} is not pulled to {d} (run scripts/pull_staged_overlay.py --version {v})"]
    raw = mpath.read_bytes()
    sha = _sha(raw)
    if sha != p["manifest_sha256"]:
        return {}, sha, [f"{mpath}: sha256 {sha[:12]} is not the pinned {p['manifest_sha256'][:12]}"]
    manifest = json.loads(raw)
    problems = []
    if manifest.get("kind") != KIND or manifest.get("version") != v:
        problems.append(f"{mpath}: not the {KIND} {v} (kind {manifest.get('kind')!r}, version {manifest.get('version')!r})")
    if (manifest.get("base_hf") or {}).get("tag_commit") != p["base_tag_commit"]:
        problems.append(f"{mpath}: base Hub revision is not the pinned {p['base_tag_commit'][:12]}")
    overlay: dict[str, dict[str, Any]] = {}
    # Every file the manifest pins is checked (master, builder, queues too), not only the overlay.
    files = dict(manifest.get("files") or {})
    if not any(rel.startswith("overlay/") for rel in files):
        problems.append(f"{mpath}: lists no overlay/ files")
    for rel, entry in sorted(files.items()):
        path = d / rel
        data = path.read_bytes() if path.is_file() else None
        if data is None or _sha(data) != entry.get("sha256"):
            problems.append(f"{path}: missing or not the sha256 its manifest pins")
            continue
        if not rel.startswith("overlay/"):
            continue
        # JSON Lines records end at "\n" only; str.splitlines would also split on U+2028 in a value.
        for line in data.decode("utf-8").split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["doc_id"] in overlay:
                problems.append(f"{path}: {rec['doc_id']} appears twice")
            overlay[rec["doc_id"]] = rec
    return overlay, sha, problems


def row_content_sha(row: Mapping[str, Any]) -> str:
    """sha256 of the row's document text (a Hub row without text: its ``content_sha256``)."""
    if row.get("doc_text") is not None:
        return _sha(str(row["doc_text"]).encode("utf-8"))
    content = str(row.get("content_sha256") or "")
    return content if _HEX64.fullmatch(content) else ""


def apply_staged(row: Mapping[str, Any], overlay: Mapping[str, Mapping[str, Any]], *,
                 version: str, manifest_sha: str) -> dict[str, Any]:
    """The row with its staged labels merged over the Hub labels (the overlay wins).

    ``staged_overlay`` on the returned row names every field taken from the overlay and keeps
    each replaced Hub value (and its presence code) under ``overrides``. A document whose text
    no longer has the record's ``content_sha256`` is left untouched and marked ``stale``.
    """
    from mailroom_sandbox import interim_labels as il

    out = dict(row)
    rec = overlay.get(il.row_id(row))
    if not rec:
        return out
    mark: dict[str, Any] = {"version": _version(version), "manifest_sha256": manifest_sha}
    if rec.get("content_sha256") != row_content_sha(row):
        out["staged_overlay"] = {**mark, "fields": [], "overrides": {}, "stale": True}
        return out
    exp = il._expected(row)
    pres = il._presence(exp)
    applied, overrides = [], {}
    for field, lab in sorted((rec.get("labels") or {}).items()):
        code = PRESENCE.get(lab.get("presence"))
        if field in NOT_APPLIED or code is None:
            continue
        if lab.get("override"):
            overrides[field] = {"hub": exp.get(field), "hub_presence": pres.get(field)}
        exp[field] = lab.get("value") if code == "populated" else None
        pres[field] = code
        applied.append(field)
    if not applied:
        return out
    exp["gt_presence"] = json.dumps(pres, sort_keys=True)
    key = il._labels_key(row)
    out[key] = json.dumps(exp, ensure_ascii=False, sort_keys=True) if isinstance(row.get(key), str) else exp
    out["staged_overlay"] = {**mark, "fields": applied, "overrides": overrides}
    return out


def apply_rows(rows: list[dict[str, Any]], version: str, *, source_revision: str | None = None,
               root: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a pinned overlay to prepared rows; return them and the run-lock provenance.

    Refuses a cut that is not the pinned bytes, and a Hub source on another revision than the
    one the overlay is a delta against (a local file source is bound by each row's text hash).
    """
    p = pin(version)
    if source_revision and _HEX40.fullmatch(source_revision) and source_revision != p["base_tag_commit"]:
        raise StagedOverlayError(f"staged overlay {_version(version)} is a delta against Hub "
                                 f"{p['base_tag_commit'][:12]}, not {source_revision[:12]}")
    overlay, sha, problems = snapshot(version, root)
    if problems:
        raise StagedOverlayError(f"staged label overlay is not the pinned cut: {problems[0]}")
    out = [apply_staged(r, overlay, version=version, manifest_sha=sha) for r in rows]
    marks = [r["staged_overlay"] for r in out if r.get("staged_overlay")]
    return out, {"version": _version(version), "manifest_sha256": sha, "issues_commit": p["commit"],
                 "rows_with_labels": sum(1 for m in marks if m["fields"]),
                 "fields_applied": sum(len(m["fields"]) for m in marks),
                 "hub_overrides": sum(len(m["overrides"]) for m in marks),
                 "stale_rows": sum(1 for m in marks if m.get("stale"))}


def pull(version: str, *, root: Path | None = None, remote: str | None = None) -> Path:
    """Fetch the pinned cut from mailroom-issues into the cache and verify it.

    Sparse, shallow fetch of exactly the pinned commit; the cut is written next to its final
    place and renamed only after every byte matches the pin. Network access to GitHub only.
    """
    p, v = pin(version), _version(version)
    dest = cut_dir(v, root)
    if dest.exists():
        _overlay, _sha256, problems = snapshot(v, root)
        if not problems:
            return dest
        raise StagedOverlayError(f"{dest} exists but is not the pinned cut ({problems[0]}); remove it and pull again")
    url = remote or f"https://github.com/{p['repo']}.git"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        def git(*args: str) -> None:
            subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True)

        git("init", "-q")
        git("remote", "add", "origin", url)
        git("sparse-checkout", "set", "--no-cone", f"/mailroom_cache/{p['path']}/")
        git("fetch", "-q", "--depth=1", "--filter=blob:none", "origin", p["commit"])
        git("checkout", "-q", "FETCH_HEAD")
        Path(tmp, "mailroom_cache", p["path"]).rename(dest)
    _overlay, _sha256, problems = snapshot(v, root)
    if problems:
        import shutil

        shutil.rmtree(dest)
        raise StagedOverlayError(f"pulled {v} does not match its pin: {problems[0]}")
    return dest


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", _version(version)))


def latest() -> str:
    """The most recent pinned version (highest ``X.Y.P-rc.N``), never an unpinned cut."""
    known = pins()
    if not known:
        raise StagedOverlayError(f"no staged overlay is pinned in {PINS_FILE}")
    return max(known, key=_version_key)


def _bundle_names(version: str, root: Path | None = None) -> tuple[Path, list[str]]:
    """The verified cut and the files a bundle carries: its manifest and every file it pins."""
    v = _version(version)
    _overlay, _sha256, problems = snapshot(v, root)
    if problems:
        raise StagedOverlayError(f"cannot bundle {v}: {problems[0]}")
    d = cut_dir(v, root)
    files = json.loads((d / "MANIFEST.json").read_bytes()).get("files") or {}
    return d, ["MANIFEST.json", *sorted(files)]


def export_bundle(version: str, out: Path, *, root: Path | None = None) -> Path:
    """Write the verified cached cut to ``out`` as a ``.tar.gz`` another checkout can import.

    The bundle holds the cut's ``MANIFEST.json`` and exactly the files it pins, under the cut's
    path relative to the cache root, so it unpacks into ``data/cache/mailroom_cache/``. The bytes
    are deterministic (sorted names, zeroed owners and times); trust still comes from the pin, not
    from the bundle, so :func:`import_bundle` re-verifies every file.
    """
    import gzip
    import io
    import tarfile

    v = _version(version)
    d, names = _bundle_names(v, root)
    rel = pin(v)["path"]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".partial")
    with open(tmp, "wb") as fh, gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in names:
            data = (d / name).read_bytes()
            info = tarfile.TarInfo(f"{rel}/{name}")
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    tmp.replace(out)
    return out


def import_bundle(bundle: Path, *, version: str | None = None, root: Path | None = None) -> tuple[str, Path]:
    """Install a bundle written by :func:`export_bundle` into the cache; return ``(version, dir)``.

    The bundle must hold one pinned cut and nothing else: only regular files under that cut's
    pinned path, no links, absolute paths or ``..``. It is unpacked beside its final place and
    renamed only after every byte matches the pin, as :func:`pull` does. An already cached,
    verified cut is left as it is.
    """
    import tarfile

    with tarfile.open(bundle, mode="r:gz") as tar:
        members = tar.getmembers()
        files = [m for m in members if not m.isdir()]
        bad = [m.name for m in members if not (m.isfile() or m.isdir())
               or Path(m.name).is_absolute() or ".." in Path(m.name).parts]
        if bad or not files:
            raise StagedOverlayError(f"{bundle}: not a staged overlay bundle ({bad[:1] or 'no files'})")
        by_path = {p["path"]: v for v, p in pins().items()}
        cuts = {next((path for path in by_path if m.name.startswith(path + "/")), None) for m in files}
        if len(cuts) != 1 or None in cuts:
            raise StagedOverlayError(f"{bundle}: files must all lie under one pinned cut path "
                                     f"(pinned: {sorted(by_path.values())})")
        v = by_path[cuts.pop()]
        if version is not None and _version(version) != v:
            raise StagedOverlayError(f"{bundle} holds {v}, not {_version(version)}")
        dest = cut_dir(v, root)
        if dest.exists():
            _overlay, _sha256, problems = snapshot(v, root)
            if not problems:
                return v, dest
            raise StagedOverlayError(f"{dest} exists but is not the pinned cut ({problems[0]}); remove it and import again")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
            for m in files:
                target = Path(tmp, m.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                assert src is not None  # a regular file member
                target.write_bytes(src.read())
            _overlay, _sha256, problems = snapshot(v, Path(tmp))
            if problems:
                raise StagedOverlayError(f"{bundle} does not match the pin for {v}: {problems[0]}")
            extra = {str(p.relative_to(cut_dir(v, Path(tmp)))) for p in cut_dir(v, Path(tmp)).rglob("*")
                     if p.is_file()} - set(_bundle_names(v, Path(tmp))[1])
            if extra:
                raise StagedOverlayError(f"{bundle} carries files its manifest does not pin: {sorted(extra)[:3]}")
            cut_dir(v, Path(tmp)).rename(dest)
    return v, dest
