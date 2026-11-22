#!/usr/bin/env python3
"""Export the repaired label sets into the semantically versioned ``mailroom_cache`` of mailroom-issues.

LLM-Mailroom-Services/mailroom-issues holds no code (its law #1), so its ``mailroom_cache/``
folder is generated here and never hand-edited there. The cache keeps two channels per
mailroom-dataset release:

- ``hf-revision``: the published Hugging Face dataset revision (tag commit, parquet parent),
  a pin only. The bytes live on the Hub (and, for v9.1, in ``data/hf_cache``).
- ``pre-release``: label repairs and enhancements made after that release and not yet
  published. Each one is an immutable SemVer pre-release (``9.3.1-rc.1``) nested under the
  release it builds on, so everything between two minor versions sits in one folder::

    mailroom_cache/
      REGISTRY.json                      every cached version, channel, pins and digests
      v9.3.0/                            mailroom-dataset release (Hub tag v9.3)
        hf-revision/MANIFEST.json
        pre-release/v9.3.1-rc.1/
          MANIFEST.json
          repairs/full-label-set/        the full 3,302-row repaired label set (CSV)
          repairs/review/                review verdicts and decisions behind the repairs
          enhancements/gold/ ...         near-gold catalogs, overlay, supplementary, interim

Usage (``local-mailroom-sandbox`` and ``mailroom-issues`` checked out side by side)::

    python scripts/export_mailroom_cache.py --version 9.3.1-rc.1 \\
        --full-labels mailroom_dataset_v9.3_label_repaired_copy.csv
    python scripts/export_mailroom_cache.py --version 9.3.1-rc.1 --check

A written pre-release is immutable: writing the same version with different bytes is refused
(cut ``rc.2`` instead). ``--check`` rebuilds in memory from the committed labels and the cached
CSV and exits 1 if anything under ``--out`` is stale.
Exports and checks hold a nonblocking sibling ``.<output-name>.export.lock`` across
the entire cache transaction. Keep that lock file in place; concurrent attempts
are refused and can be retried after the active export finishes.
"""
from __future__ import annotations

import argparse
import collections
import csv
import fcntl
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mailroom_sandbox.job.spec import (  # noqa: E402
    FAMILY_CORPUS_SIZE,
    FAMILY_HF_DATA_REVISION,
    FAMILY_HF_REVISION,
    FAMILY_HF_TAG,
    HF_DEFAULT_REPO,
    LEGACY_FAMILY_HF_REVISIONS,
)

SCHEMA = "mailroom-cache/v1"
SOURCE_REPO = "Exios66/local-mailroom-sandbox"
BUILDER = "scripts/export_mailroom_cache.py"
LABELS = ROOT / "data" / "labels"
# Cached label sets: source folder under data/labels -> path inside the pre-release.
LABEL_SETS = {
    "gold": "enhancements/gold",
    "gold-overlay": "enhancements/gold-overlay",
    "gold-supplementary": "enhancements/gold-supplementary",
    "interim": "enhancements/interim",
    "review": "repairs/review",
}
FULL_SET_DIR = "repairs/full-label-set"
REQUIRED_COLUMNS = ("document_id", "split", "doc_class", "subclass", "subclass_hub_v9_3", "subclass_changed")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)$")


class CacheError(RuntimeError):
    """The inputs or the existing cache do not allow this export."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> int | None:
    if path.suffix not in {".jsonl", ".csv"}:
        return None
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_version(version: str) -> tuple[int, int, int, str]:
    """A SemVer pre-release (``9.3.1-rc.1``); the release it builds on must be the current Hub tag."""
    m = SEMVER.match(version.removeprefix("v"))
    if not m:
        raise CacheError(f"--version must be a SemVer pre-release such as 9.3.1-rc.1, got {version!r}")
    major, minor, patch = (int(g) for g in m.groups()[:3])
    if f"v{major}.{minor}" != FAMILY_HF_TAG:
        raise CacheError(f"{version} does not build on the pinned dataset release {FAMILY_HF_TAG}")
    if patch < 1:
        raise CacheError(f"{version}: a repair pre-release bumps the patch above {FAMILY_HF_TAG}.0")
    return major, minor, patch, m.group(4)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _labels_tree(commit: str) -> str | None:
    res = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{commit}:data/labels"], cwd=ROOT,
                         capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else None


def labels_commit(prefer: str | None = None) -> str:
    """The commit that introduced the current ``data/labels`` content; refuse uncommitted edits.

    Found by content, not by ``git log -- data/labels``: in a shallow clone a boundary commit
    looks as if it added every file. ``prefer`` (an already recorded commit) is kept when its
    labels tree is still the current one, so re-checks never drift with clone depth.
    """
    dirty = _git("status", "--porcelain", "--", "data/labels")
    if dirty:
        raise CacheError(f"data/labels has uncommitted changes; commit them first:\n{dirty}")
    tree = _labels_tree("HEAD")
    if prefer and _labels_tree(prefer) == tree:
        return prefer
    shallow_file = Path(_git("rev-parse", "--git-path", "shallow"))
    shallow_file = shallow_file if shallow_file.is_absolute() else ROOT / shallow_file
    shallow = set(shallow_file.read_text().split()) if shallow_file.exists() else set()
    found = None
    for commit in _git("rev-list", "--first-parent", "HEAD").split():
        if _labels_tree(commit) != tree:
            break
        found = commit
        if commit in shallow:
            raise CacheError("history is too shallow to find the commit that introduced data/labels; "
                             "fetch more history (git fetch --depth=200 origin <branch>)")
    return found


def accepted_subclass_corrections() -> dict[str, tuple[str, str]]:
    out = {}
    for line in (LABELS / "review" / "subclass_corrections.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("verdict") == "correct":
            out[rec["doc_id"]] = (rec["hub_subclass"], rec["subclass"])
    return out


def validate_full_labels(path: Path) -> dict[str, Any]:
    """Check the full repaired label set and summarize it; its subclass repairs must equal the
    accepted review corrections exactly (a rejected correction must not appear)."""
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CacheError(f"{path.name}: missing columns {missing}")
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    ids = [r["document_id"] for r in rows]
    if len(rows) != FAMILY_CORPUS_SIZE or len(set(ids)) != len(ids):
        raise CacheError(f"{path.name}: {len(rows)} rows, {len(set(ids))} unique ids; "
                         f"expected {FAMILY_CORPUS_SIZE} unique")
    repairs = {}
    for r in rows:
        changed = r["subclass"] != r["subclass_hub_v9_3"]
        if changed != (r["subclass_changed"] == "True"):
            raise CacheError(f"{r['document_id']}: subclass_changed disagrees with the subclass columns")
        if changed:
            repairs[r["document_id"]] = (r["subclass_hub_v9_3"], r["subclass"], r["doc_class"])
    accepted = accepted_subclass_corrections()
    if {k: v[:2] for k, v in repairs.items()} != accepted:
        raise CacheError(f"{path.name}: subclass repairs {sorted(repairs)} do not match the accepted "
                         f"corrections in data/labels/review/subclass_corrections.jsonl {sorted(accepted)}")
    return {
        "rows": len(rows),
        "columns": len(columns),
        "splits": dict(sorted(collections.Counter(r["split"] for r in rows).items())),
        "classes": dict(sorted(collections.Counter(r["doc_class"] for r in rows).items())),
        "subclass_repairs": [
            {"document_id": k, "doc_class": v[2], "hub_v9_3": v[0], "repaired": v[1]}
            for k, v in sorted(repairs.items())
        ],
    }


def _files(base: Path, *, skip: Path | None = None) -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p != skip:
            rel = p.relative_to(base).as_posix()
            entry: dict[str, Any] = {"sha256": _sha256(p), "bytes": p.stat().st_size}
            if (n := _lines(p)) is not None:
                entry["lines"] = n
            out[rel] = entry
    return out


def hf_release_manifests() -> dict[str, dict[str, Any]]:
    """``vX.Y.0`` -> hf-revision manifest for the current pin and every legacy one."""
    gold_binding = json.loads((LABELS / "gold" / "MANIFEST.json").read_text())["binding"]
    out = {}
    for tag, (tag_commit, data_rev) in {**LEGACY_FAMILY_HF_REVISIONS,
                                        FAMILY_HF_TAG: (FAMILY_HF_REVISION, FAMILY_HF_DATA_REVISION)}.items():
        current = tag == FAMILY_HF_TAG
        m: dict[str, Any] = {
            "schema": SCHEMA,
            "channel": "hf-revision",
            "version": f"{tag.removeprefix('v')}.0",
            "dataset": HF_DEFAULT_REPO,
            "hf_tag": tag,
            "tag_commit": tag_commit,
            "data_revision": data_rev,
            "status": "current family pin" if current else "superseded family pin",
            "labels_cached_here": False,
            "note": ("Pin only: the published labels are read from the Hub at tag_commit. "
                     "Pre-releases under ../pre-release/ build on this release."),
        }
        if current:
            m["labels_revision"] = gold_binding["dataset_revision"]
            m["labels_revision_note"] = ("Hub commit the sandbox gold catalogs, label review and prime "
                                         "filter read the published v9.3 ground truth from.")
        if data_rev == "ed7576b676343e0b402ec5412cded301e629bdee":
            m["byte_cache"] = "data/hf_cache (MANIFEST.json pins this data_revision)"
        out[f"{tag}.0"] = m
    return out


def build_prerelease(dest: Path, version: str, full_labels: Path, commit: str,
                     original_name: str) -> dict[str, Any]:
    """Write one pre-release into ``dest`` (an empty directory) and return its manifest."""
    summary = validate_full_labels(full_labels)
    csv_name = f"mailroom_dataset_v{version}_labels.csv"
    (dest / FULL_SET_DIR).mkdir(parents=True)
    shutil.copyfile(full_labels, dest / FULL_SET_DIR / csv_name)
    sets = {}
    for src_name, rel in LABEL_SETS.items():
        src = LABELS / src_name
        shutil.copytree(src, dest / rel)
        sub = _files(dest / rel)
        sets[rel] = {
            "source": f"data/labels/{src_name}",
            "files": len(sub),
            "lines": sum(e.get("lines", 0) for e in sub.values()),
        }
    gold_binding = json.loads((LABELS / "gold" / "MANIFEST.json").read_text())["binding"]
    manifest = {
        "schema": SCHEMA,
        "channel": "pre-release",
        "version": version,
        "semver": f"{version}+hf.{FAMILY_HF_REVISION[:8]}",
        "base_release": f"{FAMILY_HF_TAG.removeprefix('v')}.0",
        "base_hf": {
            "dataset": HF_DEFAULT_REPO,
            "hf_tag": FAMILY_HF_TAG,
            "tag_commit": FAMILY_HF_REVISION,
            "data_revision": FAMILY_HF_DATA_REVISION,
            "labels_revision": gold_binding["dataset_revision"],
        },
        "status": ("unpublished: repairs and enhancements over the Hub labels; a Hub label still "
                   "wins field by field until a later dataset release publishes them"),
        "source": {"repo": SOURCE_REPO, "labels_commit": commit, "builder": BUILDER},
        "full_label_set": {
            "path": f"{FULL_SET_DIR}/{csv_name}",
            "original_filename": original_name,
            **summary,
        },
        "sets": sets,
    }
    manifest["files"] = _files(dest, skip=dest / "MANIFEST.json")
    _dump(dest / "MANIFEST.json", manifest)
    return manifest


def render_registry(out: Path) -> dict[str, Any]:
    versions = []
    for mf in sorted(out.glob("v*/hf-revision/MANIFEST.json")) + sorted(out.glob("v*/pre-release/*/MANIFEST.json")):
        m = json.loads(mf.read_text())
        entry = {k: m[k] for k in ("version", "channel", "status") if k in m}
        entry["path"] = mf.parent.relative_to(out).as_posix()
        if m["channel"] == "hf-revision":
            entry.update(hf_tag=m["hf_tag"], tag_commit=m["tag_commit"], data_revision=m["data_revision"])
        else:
            entry.update(kind=m.get("kind", "label-sets"), base_release=m["base_release"], semver=m["semver"],
                         labels_commit=m["source"]["labels_commit"],
                         manifest_sha256=_sha256(mf))
        versions.append(entry)
    return {"schema": SCHEMA, "dataset": HF_DEFAULT_REPO, "current_release": f"{FAMILY_HF_TAG}.0",
            "versions": versions}


def render_readme(registry: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{v['version']}` | {v['channel']} | `{v['path']}/` | "
        + (f"Hub `{v['hf_tag']}` → `{v['tag_commit'][:8]}` (data `{v['data_revision'][:8]}`)"
           if v["channel"] == "hf-revision" else
           f"{v['kind']} on `{v['base_release']}`; sandbox labels `{v['labels_commit'][:8]}`")
        + " |"
        for v in registry["versions"]
    )
    return f"""# Mailroom label cache (`mailroom_cache`)

Semantically versioned, cached copies of the
[`{HF_DEFAULT_REPO}`](https://huggingface.co/datasets/{HF_DEFAULT_REPO}) labels and of the
label repairs and enhancements made after each release. **Generated, never hand-edited:** the
builder is `{BUILDER}` in [`{SOURCE_REPO}`](https://github.com/{SOURCE_REPO}).

## Layout

The top-level folder is the dataset release (`vMAJOR.MINOR.0`, one per Hub tag). Everything made
between that release and the next minor version nests under it, as an immutable SemVer
pre-release:

```text
mailroom_cache/
  REGISTRY.json                         every cached version with its pins and digests
  vX.Y.0/                               dataset release = Hub tag vX.Y
    hf-revision/MANIFEST.json           channel "hf-revision": tag commit + parquet parent (pin only)
    pre-release/vX.Y.P-rc.N/            channel "pre-release": unpublished label work on vX.Y
      MANIFEST.json                     base revision, source commit, counts, sha256 of every file
      repairs/full-label-set/*.csv      the full repaired label set, one row per document
      repairs/review/                   review verdicts and decisions behind the repairs
      enhancements/gold/                near-gold catalogs (schema-gated)
      enhancements/gold-overlay/        the near-gold overlay production runs merge
      enhancements/gold-supplementary/  supplementary labeler output (never ground truth)
      enhancements/interim/             repaired interim gap fills and corrections
    pre-release/vX.Y.P-rc.N/            kind "production-overlay": the merged master, staged
      MANIFEST.json                     inputs (builder commit, sha256), coverage, overlay counts
      master/                           joined wide CSV, per-cell provenance, completeness, summary
      overlay/<class>.jsonl             every label that differs from Hub vX.Y (pulled by deployments)
      builder/                          the builder outputs it was staged from (rc.3 on)
      queues/needs_human.csv            unresolved disputes and join cells a person must decide
      queues/gold_override_signoff.csv  Hub overrides, decided_by blank until initialled
      queues/header_restoration.csv     correspondence whose labels quote the lost Enron header (rc.4 on)
```

A pre-release is either `label-sets` (the raw sandbox layers, as cut) or `production-overlay`
(those layers merged into one master by the repaired-label builder, then staged as an overlay).
Production scoring applies one pinned `production-overlay`, never "the newest": the sandbox pins
the version, this repository's commit and the MANIFEST.json sha256 in `config/staged_overlays.yaml`
and refuses a cut that does not match (`scripts/pull_staged_overlay.py`, then `dataset.staged_overlay`
in the run config). The Hub label comes first, replaced field by field by `overlay/<class>.jsonl`,
where `override: true` marks a replaced Hub value. Each record's `content_sha256` is checked
against the document before it is applied. The overlay already contains the interim and
near-gold labels it merged, so it is applied instead of those layers, never on top of them.

From rc.4 the stager also validates the merged staged (non-Hub) labels before staging
(`validation_repair` in the manifest); Hub-backed cells are only keyword-cleaned. It keeps only
whole ISO dates, maps `cuad_family` to its canonical key, reduces whole governing-law clauses to
the named jurisdiction, and removes defined-term aliases and clause fragments from `parties`. It
strips the maildir user, folder and timestamp tokens from Hub correspondence `keywords`, and
applies reviewed corrections (a populated one must quote the document text). From rc.5 it also
drops bare defined terms ("the Company") and suffix-only captures ("Inc.") from `parties` and
unlabels a name field that holds only one. It holds back as `disputed_unresolved` an interim
value whose audit waits for the owner, and the conflicting values of documents with the same
text. Both go to `queues/needs_human.csv`. From rc.6 a party, advisor or counsel name loses a
describing lead-in ("the retention of X", "Subsidiary of Y, and X" become X; the evidence quote is
kept), and the master summary's `outputs_sha256` hashes the `master/` files, with the builder's
own digests under `builder_outputs_sha256`. From rc.7 `parties` also loses party-role words ("the
Customer", "Member"), descriptions of a party ("an individual", "your") and alias clauses ("d/b/a
X"), and a role label before a name is trimmed ("the Supplier: X" becomes X). A merger
`effective_date` that is only the signing date follows the owner's answer in the interim audit
(`signing_date_policy` in the manifest): held back as disputed while it is pending, cleared or
kept once it is recorded.

Some correspondence labels quote the original Enron email header (sender, recipients, date,
subject). The cleaned corpus text dropped that header, so `queues/header_restoration.csv` lists
each such document with its maildir file and the quoted header lines. The next official release
restores those lines into `doc_text`, so a model can read what the labels expect.

- **Patch** (`X.Y.P`) counts label repair rounds on release `X.Y`.
- **Pre-release** (`-rc.N`) is one cut of that round. A cut is never rewritten: changed labels
  get the next `rc.N`. Build metadata `+hf.<tag commit>` in each manifest names the Hub revision.
- When the Hub publishes the repairs as a new tag, it gets its own `vX.Y.0/hf-revision/`.

## Versions

| Version | Channel | Path | Pins |
| --- | --- | --- | --- |
{rows}

The current family pin is `{registry['current_release']}`. Two label paths exist, and a run uses
one of them. With the `label-sets` layers, precedence is the Hub label, then interim truth, then
the near-gold overlay for fields nothing else labels. With a `production-overlay` cut, the
overlay replaces the Hub value field by field (`override: true`), and the interim and near-gold
layers are not applied again. Supplementary output is never ground truth.

## Use

```bash
git clone --filter=blob:none --sparse https://github.com/LLM-Mailroom-Services/mailroom-issues.git
cd mailroom-issues
git sparse-checkout set mailroom_cache/{registry['current_release']}
cd mailroom_cache/<pre-release path>   # e.g. v9.3.0/pre-release/v9.3.1-rc.1
python3 -c "import json;[print(v['sha256']+'  '+k) for k,v in json.load(open('MANIFEST.json'))['files'].items()]" | sha256sum -c --quiet
```

`sha256sum` prints nothing when every file matches its manifest digest.

## Regenerate

In `{SOURCE_REPO}`, with `mailroom-issues` checked out next to it:

```bash
python {BUILDER} --version X.Y.P-rc.N --full-labels <repaired-labels.csv>
python {BUILDER} --version X.Y.P-rc.N --check
```
"""


def _check_output_owner(out: Path) -> None:
    """Refuse a populated foreign directory before any cache publication can replace it."""
    if out.is_symlink():
        raise CacheError(f"cache output must not be a symlink: {out}")
    if not out.exists():
        return
    if not out.is_dir():
        raise CacheError(f"cache output is not a directory: {out}")
    if not any(out.iterdir()):
        return
    try:
        registry = json.loads((out / "REGISTRY.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CacheError(f"refusing to replace a directory without a valid cache registry: {out}") from exc
    if not isinstance(registry, dict) or registry.get("schema") != SCHEMA or registry.get("dataset") != HF_DEFAULT_REPO:
        raise CacheError(f"refusing to replace a foreign cache directory: {out}")


def _publish_cache(stage: Path, out: Path) -> None:
    """Prepare the replacement before renaming the current cache; roll back a failed swap."""
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".mailroom-cache-", dir=out.parent))
    new, backup = work / "new", work / "previous"
    preserve = False
    try:
        shutil.copytree(stage, new)
        _check_output_owner(out)
        if out.exists():
            out.rename(backup)
        try:
            new.rename(out)
        except BaseException:
            if backup.exists():
                try:
                    backup.rename(out)
                except BaseException as exc:
                    preserve = True
                    exc.add_note(f"Previous cache retained for recovery at {backup}")
                    raise
            raise
    finally:
        if not preserve:
            shutil.rmtree(work)


@contextmanager
def _cache_lock(out: Path):
    """Hold a stable sibling lock across the read, build and publication transaction."""
    out.parent.mkdir(parents=True, exist_ok=True)
    lock = out.parent / f".{out.name}.export.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise CacheError(f"cannot open cache export lock: {lock}") from exc
    with os.fdopen(fd, "a") as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CacheError(f"cache export already in progress: {out}") from exc
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def export(out: Path, version: str, full_labels: Path | None, *, check: bool) -> list[str]:
    """Write (or, with ``check``, compare) the cache. Returns the list of stale paths."""
    if out.is_symlink():
        raise CacheError(f"cache output must not be a symlink: {out}")
    out = out.parent.resolve() / out.name
    with _cache_lock(out):
        return _export_locked(out, version, full_labels, check=check)


def _export_locked(out: Path, version: str, full_labels: Path | None, *, check: bool) -> list[str]:
    _check_output_owner(out)
    major, minor, _patch, _pre = parse_version(version)
    version = version.removeprefix("v")
    pre_rel = Path(f"v{major}.{minor}.0") / "pre-release" / f"v{version}"
    existing = out / pre_rel
    recorded = (json.loads((existing / "MANIFEST.json").read_text())["source"]["labels_commit"]
                if (existing / "MANIFEST.json").exists() else None)
    commit = labels_commit(prefer=recorded)
    if full_labels is None:
        cached = sorted((existing / FULL_SET_DIR).glob("*.csv")) if existing.exists() else []
        if len(cached) != 1 or not (existing / "MANIFEST.json").exists():
            raise CacheError(f"no cached full label set under {existing / FULL_SET_DIR}; pass --full-labels")
        full_labels = cached[0]
        original_name = json.loads((existing / "MANIFEST.json").read_text())["full_label_set"]["original_filename"]
    else:
        # Uploads carry an 8-hex-digit prefix; record the name the file was published under.
        original_name = re.sub(r"^[0-9a-f]{8}-", "", full_labels.name)
    stale: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "mailroom_cache"
        build_prerelease(stage / pre_rel, version, full_labels, commit, original_name)
        for rel, m in hf_release_manifests().items():
            _dump(stage / rel / "hf-revision" / "MANIFEST.json", m)
        # Other pre-releases already in the cache are immutable history: carry them over as is.
        for other in sorted(out.glob("v*/pre-release/*")) if out.exists() else []:
            rel = other.relative_to(out)
            if rel != pre_rel:
                shutil.copytree(other, stage / rel)
        registry = render_registry(stage)
        _dump(stage / "REGISTRY.json", registry)
        (stage / "README.md").write_text(render_readme(registry), encoding="utf-8")

        new_files = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
        old_files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} if out.exists() else set()
        for rel in sorted(new_files | old_files):
            a, b = stage / rel, out / rel
            if not (a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)):
                stale.append(rel)
        if check:
            return stale
        foreign = sorted(old_files - new_files)
        if foreign:
            raise CacheError(f"refusing to remove unmanaged cache files: {foreign[:3]}")
        frozen = [r for r in stale if r.startswith(pre_rel.as_posix() + "/") and (out / r).exists()]
        if frozen:
            raise CacheError(f"v{version} is already cached with different bytes ({len(frozen)} files, "
                             f"e.g. {frozen[0]}); pre-releases are immutable, cut the next rc instead")
        _publish_cache(stage, out)
    return stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT.parent / "mailroom-issues" / "mailroom_cache"))
    ap.add_argument("--version", required=True, help="SemVer pre-release, e.g. 9.3.1-rc.1")
    ap.add_argument("--full-labels", type=Path, default=None,
                    help="full repaired label set CSV (default: the copy already cached for --version)")
    ap.add_argument("--check", action="store_true", help="exit 1 if the cache under --out is stale")
    args = ap.parse_args(argv)
    try:
        stale = export(Path(args.out), args.version, args.full_labels, check=args.check)
    except CacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        for rel in stale[:20]:
            print(f"stale: {rel}")
        print(f"{len(stale)} stale file(s) under {args.out}" if stale else f"up to date: {args.out}")
        return 1 if stale else 0
    print(f"wrote {args.out} ({len(stale)} file(s) changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
