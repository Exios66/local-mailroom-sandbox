"""``sandbox schemas``: per-subclass extraction schemas graded against the scored truth. Offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mailroom_sandbox import subclass_schemas as ss

VERDICTS = ("iterate", "thin", "constant", "fixed", "no_truth", "not_applicable")


def register(sub, leaf) -> None:
    parser = sub.add_parser(
        "schemas", parents=[leaf],
        help="per-subclass extraction schemas graded against Hub + interim + near-gold truth (offline)",
    )
    commands = parser.add_subparsers(dest="schemas_command", required=True)

    def common(p):
        p.add_argument("--out", default=str(ss.DEFAULT_OUT), help="registry file (default config/extraction/subclass_schemas.json)")
        p.add_argument("--revision", default="", help="dataset revision (default FAMILY_HF_REVISION)")
        p.add_argument("--split", default=str(ss.DEFAULT_SPLIT), help="split whose sets the counts use ('' for none)")

    build = commands.add_parser("build", parents=[leaf], help="rebuild the registry from the cached corpus and label overlays")
    common(build)
    build.add_argument("--check", action="store_true", help="fail if the committed file is stale or a mismatch remains")
    build.set_defaults(handler=_build)

    show = commands.add_parser("show", parents=[leaf], help="field verdicts per class or subclass")
    common(show)
    show.add_argument("--class", dest="doc_class", choices=ss.CLASSES, help="one class")
    show.add_argument("--subclass", help="one subclass (needs --class)")
    show.add_argument("--verdict", choices=VERDICTS, help="only fields with this verdict")
    show.add_argument("--json", action="store_true", help="print the selected entries as JSON")
    show.set_defaults(handler=_show)


def _build(args) -> int:
    from mailroom_sandbox import runtime

    runtime.activate()
    try:
        rows, rev = ss.load_corpus_rows(args.revision or None)
        reg = ss.build_registry(ss.truth_rows(rows), revision=rev,
                                split_dir=Path(args.split) if args.split else None)
    except ss.SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    data = ss.render(reg)
    out = Path(args.out)
    rc = 0
    if args.check:
        current = out.read_bytes() if out.is_file() else b""
        if current != data:
            print(f"stale: {out} differs from a rebuild (run `sandbox schemas build`)", file=sys.stderr)
            rc = 1
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"wrote {out} ({len(data):,} bytes)")
    for p in reg["problems"][:20]:
        print(f"MISMATCH {p['kind']}: {p['class']}/{p['subclass']}.{p['field']} {p['doc_id'] or ''} {p['values']}")
    if reg["problems"]:
        rc = 1
    print(f"{len(reg['status_repairs'])} fields repaired from Dojo pending_annotation to scored; "
          f"{len(reg['status_conflicts'])} labeled fields the Dojo marks not_applicable; "
          f"{len(reg['problems'])} mismatches")
    return rc


def _show(args) -> int:
    out = Path(args.out)
    if not out.is_file():
        print(f"error: {out} is missing; run `sandbox schemas build`", file=sys.stderr)
        return 2
    reg = json.loads(out.read_text(encoding="utf-8"))
    if args.subclass and not args.doc_class:
        print("error: --subclass needs --class", file=sys.stderr)
        return 2
    if args.subclass:
        subs = reg["classes"][args.doc_class]["subclasses"]
        if args.subclass not in subs:
            print(f"error: no subclass {args.subclass!r}; one of {sorted(subs)}", file=sys.stderr)
            return 2
        entry = subs[args.subclass]
        fields = entry["fields"]
        head = f"{args.doc_class}/{args.subclass}: {entry['rows']} docs {entry.get('rows_by_set') or ''}"
    else:
        sel = [args.doc_class] if args.doc_class else list(reg["classes"])
        fields = {f"{c}.{f}": e for c in sel for f, e in reg["classes"][c]["fields"].items()}
        head = "class-level fields (truth summed over subclasses)"
    if args.verdict:
        fields = {k: v for k, v in fields.items() if v["verdict"] == args.verdict}
    if args.json:
        print(json.dumps(fields, indent=1, sort_keys=True, ensure_ascii=False))
        return 0
    print(head)
    print(f"  {'field':38} {'verdict':14} {'status':17} {'dojo':19} {'labeled':>7} {'dev':>5}  sources")
    for name, e in fields.items():
        dev = (e.get("labeled_by_set") or {}).get("dev", "-")
        dom = e.get("dominant")
        extra = f"  dominant {dom['value']!r} {dom['share']:.0%}" if dom and dom["share"] >= 0.8 else ""
        print(f"  {name:38} {e['verdict']:14} {e['effective_status']:17} {e['dojo_status']:19} "
              f"{e['labeled']:>7} {dev:>5}  {e['truth']}{extra}")
    return 0
