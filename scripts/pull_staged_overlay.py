#!/usr/bin/env python3
"""Fetch a pinned staged label overlay from mailroom-issues into the local label cache.

    python scripts/pull_staged_overlay.py --version 9.3.1-rc.9 [--root DIR]
    python scripts/pull_staged_overlay.py --latest [--export cut.tar.gz]
    python scripts/pull_staged_overlay.py --import cut.tar.gz
    python scripts/pull_staged_overlay.py --list

Reads the pin in ``config/staged_overlays.yaml`` (repository, commit, MANIFEST.json sha256),
fetches only that cut at that commit, and refuses bytes that differ from the pin. ``--latest``
selects the most recent pinned version; it never reaches past the pins. The cache root is
``--root``, else ``$SANDBOX_LABEL_CACHE``, else ``data/cache/mailroom_cache``.

``--export`` writes the verified cut as a ``.tar.gz`` (pulling it first when it is not cached),
so a checkout without GitHub access to mailroom-issues, such as a laptop clone, can keep the
same cache: ``--import`` re-verifies every file against the pin before it installs the cut.

Nothing runs this for you: ``deploy/Dockerfile`` and remote job workers do not pull the cut.
Whoever builds an image or starts a worker must run it (or ``--check`` a copied cut) and bundle the
verified cache into the image, or mount it and set ``$SANDBOX_LABEL_CACHE``, before preflight.
Network: GitHub only, and only when the cut is not cached yet. No spend.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Runs from an uninstalled checkout too: put src/ on the path before importing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _list(so, root: Path | None) -> int:
    newest = so.latest()
    for v in sorted(so.pins(), key=so._version_key):
        problems = so.snapshot(v, root)[2]
        state = "cached" if not problems else ("not cached" if "not pulled" in problems[0] else "bad cache")
        print(f"{v:<14} {state:<10} {so.cut_dir(v, root)}{'  (latest)' if v == newest else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from mailroom_sandbox import staged_overlay as so

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--version", help="a version pinned in config/staged_overlays.yaml")
    which.add_argument("--latest", action="store_true", help="the most recent pinned version")
    which.add_argument("--import", dest="bundle", type=Path, default=None,
                       help="install a cut from a bundle written by --export (re-verified against its pin)")
    which.add_argument("--list", action="store_true", help="list pinned versions and whether each is cached")
    ap.add_argument("--root", type=Path, default=None, help="label cache root (default: $SANDBOX_LABEL_CACHE)")
    ap.add_argument("--remote", default=None, help="git URL to fetch from instead of the pinned GitHub repository")
    ap.add_argument("--check", action="store_true", help="only verify an already pulled cut")
    ap.add_argument("--export", type=Path, default=None, metavar="FILE",
                    help="also write the verified cut to FILE (.tar.gz) for another checkout's cache")
    args = ap.parse_args(argv)
    if (args.bundle or args.list) and (args.check or args.export or args.remote):
        ap.error("--import and --list take no --check, --export or --remote")
    if args.check and args.export:
        ap.error("--check verifies only; drop it to --export")
    try:
        if args.list:
            return _list(so, args.root)
        if args.bundle:
            version, dest = so.import_bundle(args.bundle, root=args.root)
            print(f"ok: {version} {dest}")
            return 0
        version = so.latest() if args.latest else args.version
        if args.check:
            overlay, sha, problems = so.snapshot(version, args.root)
            if problems:
                print(f"error: {problems[0]}", file=sys.stderr)
                return 1
            print(f"ok: {version} manifest {sha[:12]}, {len(overlay)} documents")
            return 0
        dest = so.pull(version, root=args.root, remote=args.remote)
        print(f"ok: {dest}")
        if args.export:
            print(f"ok: exported {so._version(version)} to {so.export_bundle(version, args.export, root=args.root)}")
    except (so.StagedOverlayError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # git or archive failure: name it, never a traceback in a deploy log
        print(f"error: fetch failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
