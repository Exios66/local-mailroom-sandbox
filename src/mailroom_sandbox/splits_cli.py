"""``sandbox splits``: build, audit and use the frozen runbook split (R00). Offline."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from mailroom_sandbox import experiment_splits as es

DEFAULT_NAME = "runbook-v1"
DEFAULT_SEED = 20261118


def register(sub, leaf) -> None:
    parser = sub.add_parser(
        "splits", parents=[leaf],
        help="frozen dev / calibration / held-out / pool split for the runbook (offline)",
    )
    commands = parser.add_subparsers(dest="splits_command", required=True)

    def common(p):
        p.add_argument("--name", default=DEFAULT_NAME, type=_split_name,
                       help=f"split directory under config/splits (default {DEFAULT_NAME})")
        p.add_argument("--families", default=str(es.DEFAULT_FAMILIES), help="subclass family vocabulary (YAML)")
        p.add_argument("--exposure", default=str(es.DEFAULT_EXPOSURE),
                       help="ids already used for tuning; held-out avoids them ('' for none)")
        p.add_argument("--revision", default="", help="dataset revision (default FAMILY_HF_REVISION)")

    build = commands.add_parser("build", parents=[leaf], help="build and write the split (refuses to overwrite)")
    common(build)
    build.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"draw seed (default {DEFAULT_SEED})")
    build.add_argument("--force", action="store_true", help="overwrite an existing split (never after runs use it)")
    build.add_argument("--dry-run", action="store_true", help="build and audit in memory; write nothing")
    build.set_defaults(handler=_build)

    audit = commands.add_parser("audit", parents=[leaf], help="re-check every split rule and file hash (leak audit)")
    common(audit)
    audit.add_argument("--json", action="store_true", help="print the checks as JSON")
    audit.set_defaults(handler=_audit)

    show = commands.add_parser("show", parents=[leaf], help="sizes, length-band counts and the run-config dataset block")
    common(show)
    show.add_argument("--set", choices=[*es.SETS, "dev-look1", "dev-look2"], default="dev",
                      help="which set's dataset block to print")
    show.set_defaults(handler=_show)


def _split_name(value: str) -> str:
    """One plain directory name: no separators, '..' or absolute paths escaping config/splits."""
    import argparse
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value or "") or ".." in value:
        raise argparse.ArgumentTypeError(f"invalid split name {value!r}: use letters, digits, '.', '_' or '-'")
    return value


def _out_dir(name: str) -> Path:
    return es.DEFAULT_OUT_ROOT / name


def _exposure(path: str) -> Path | None:
    """The tuning-exposure list; only an explicit '' means none. A missing file is refused."""
    if not path:
        return None
    if not Path(path).is_file():
        raise es.SplitError(f"exposure list {path} does not exist; pass --exposure '' to build with none")
    return Path(path)


def _load(args):
    from mailroom_sandbox.job.spec import FAMILY_HF_REVISION

    revision = args.revision or FAMILY_HF_REVISION
    exposure = _exposure(args.exposure)  # refuse a mistyped list before reading the corpus
    rows = es.load_cached_rows(revision=revision)
    docs = es.docs_from_rows(rows, es.read_id_file(exposure))
    families = es.load_families(Path(args.families))
    return revision, docs, families, exposure


def _print_checks(checks) -> int:
    failed = 0
    for c in checks:
        tag = "PASS" if c.ok else ("FAIL" if c.gate else "INFO")
        if not c.gate:
            tag = "INFO"
        failed += int(c.gate and not c.ok)
        print(f"  {tag:4}  {c.name}: {c.detail}")
    print(f"{'audit passed' if not failed else f'audit FAILED: {failed} gate check(s)'}")
    return 1 if failed else 0


def _build(args) -> int:
    try:
        revision, docs, families, exposure = _load(args)
        out = _out_dir(args.name)
        if out.exists() and any(out.iterdir()) and not (args.force or args.dry_run):
            print(f"refusing: {out} exists. A frozen split is never rebuilt; pass --force only "
                  "before any run has used it.", file=sys.stderr)
            return 2
        result = es.build_split(docs, families, seed=args.seed)
        if args.dry_run:
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                es.write_split(result, Path(tmp), seed=args.seed, revision=revision,
                               families_path=Path(args.families), exposure_path=exposure)
                fresh = es.docs_from_rows(es.load_cached_rows(revision=revision), es.read_id_file(exposure))
                print(f"dry run (nothing written): seed {args.seed}, revision {revision[:12]}")
                return _print_checks(es.audit(Path(tmp), fresh, families))
        manifest = es.write_split(result, out, seed=args.seed, revision=revision,
                                  families_path=Path(args.families), exposure_path=exposure)
    except es.SplitError as exc:
        print(f"splits build: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {out} (seed {args.seed}, revision {revision[:12]})")
    print("  " + ", ".join(f"{s}={n}" for s, n in manifest["sizes"].items()))
    fresh = es.docs_from_rows(es.load_cached_rows(revision=revision), es.read_id_file(exposure))
    code = _print_checks(es.audit(out, fresh, families))
    print("next: commit config/splits/" + args.name + " (R00 gate: split hashes committed)")
    return code


def _audit(args) -> int:
    out = _out_dir(args.name)
    if not (out / "manifest.json").is_file():
        print(f"no split at {out}; run `sandbox splits build --name {args.name}`", file=sys.stderr)
        return 2
    try:
        manifest = json.loads((out / "manifest.json").read_text())
        args.revision = args.revision or manifest["dataset"]["revision"]
        _, docs, families, _ = _load(args)
    except es.SplitError as exc:
        print(f"splits audit: {exc}", file=sys.stderr)
        return 2
    checks = es.audit(out, docs, families)
    if args.json:
        print(json.dumps([c.__dict__ for c in checks], indent=2))
        return 1 if any(c.gate and not c.ok for c in checks) else 0
    print(f"split {args.name} (seed {manifest['seed']}, revision {manifest['dataset']['revision'][:12]})")
    return _print_checks(checks)


def _show(args) -> int:
    out = _out_dir(args.name)
    if not (out / "manifest.json").is_file():
        print(f"no split at {out}; run `sandbox splits build --name {args.name}`", file=sys.stderr)
        return 2
    manifest = json.loads((out / "manifest.json").read_text())
    rows = [json.loads(line) for line in (out / "assignments.jsonl").read_text().splitlines() if line]
    print(f"split {args.name}: " + ", ".join(f"{s}={n}" for s, n in manifest["sizes"].items()))
    print("length bands (R00 length-band counts):")
    for s in es.SETS:
        c = Counter(r["band"] for r in rows if r["set"] == s)
        print(f"  {s:12} " + "  ".join(f"{b}={c.get(b, 0)}" for b in es.BANDS))
    print("classes:")
    for s in es.SETS:
        c = Counter(r["doc_class"] for r in rows if r["set"] == s)
        print(f"  {s:12} " + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))
    rel = f"config/splits/{args.name}/{args.set}.exclude.ids"
    n = manifest["looks"].get(args.set) or manifest["sizes"].get(args.set)
    print(f"\nrun-config dataset block for {args.set} ({n} docs):")
    print("dataset:\n  split: all\n  draw: ranked\n  require_task_gt: false\n"
          f"  revision: {manifest['dataset']['revision']}   # the split's frozen corpus revision\n"
          f"  exclude_ids_file: {rel}\n  limit: {n}\n"
          "  interim_labels: true      # repaired truth (data/labels/interim); see `sandbox schemas show`\n"
          "  near_gold_labels: true    # near-gold truth (data/labels/gold-overlay)")
    print("job:\n  schema_guide: true        # output-schema descriptions follow the labeling guide")
    return 0
