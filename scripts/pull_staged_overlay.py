#!/usr/bin/env python3
"""Fetch a pinned staged label overlay from mailroom-issues into the local label cache.

    python scripts/pull_staged_overlay.py --version 9.3.1-rc.5 [--root DIR]

Reads the pin in ``config/staged_overlays.yaml`` (repository, commit, MANIFEST.json sha256),
fetches only that cut at that commit, and refuses bytes that differ from the pin. The cache
root is ``--root``, else ``$SANDBOX_LABEL_CACHE``, else ``data/cache/mailroom_cache``. Nothing
runs this for you: ``deploy/Dockerfile`` and remote job workers do not pull the cut. Whoever
builds an image or starts a worker must run it (or ``--check`` a copied cut) and bundle the
verified cache into the image, or mount it and set ``$SANDBOX_LABEL_CACHE``, before preflight.
Network: GitHub only. No spend.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Runs from an uninstalled checkout too: put src/ on the path before importing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv: list[str] | None = None) -> int:
    from mailroom_sandbox import staged_overlay as so

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True, help="a version pinned in config/staged_overlays.yaml")
    ap.add_argument("--root", type=Path, default=None, help="label cache root (default: $SANDBOX_LABEL_CACHE)")
    ap.add_argument("--remote", default=None, help="git URL to fetch from instead of the pinned GitHub repository")
    ap.add_argument("--check", action="store_true", help="only verify an already pulled cut")
    args = ap.parse_args(argv)
    try:
        if args.check:
            overlay, sha, problems = so.snapshot(args.version, args.root)
            if problems:
                print(f"error: {problems[0]}", file=sys.stderr)
                return 1
            print(f"ok: {args.version} manifest {sha[:12]}, {len(overlay)} documents")
            return 0
        dest = so.pull(args.version, root=args.root, remote=args.remote)
    except (so.StagedOverlayError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # git failure: name it, never a traceback in a deploy log
        print(f"error: fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"ok: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
