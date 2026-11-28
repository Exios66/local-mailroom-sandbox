#!/usr/bin/env python3
"""Inspect label coverage and pull rows of interest from the merged label truth (offline, read-only).

Subcommands (all take the shared filters below; see docs/label-eda.md for recipes):

  summary    per-class coverage, by tier, and which source won the labelled cells
  coverage   completeness grouped by --by (doc_class, subclass, field, split, tier, chosen_source)
  gaps       open (unlabeled or disputed) cells by class, subclass and field, most first
  focus      ranked work list: unscorable documents, gate gaps, suite gaps, the human queue
  rows       the cells themselves, with --evidence and --votes
  doc        everything about one document: cells, votes, near-gold and interim records
  catalog    raw near-gold catalog records (data/labels/gold)
  interim    raw interim overlay records (data/labels/interim)

Shared filters: --class, --subclass, --split (dev, calibration, heldout, pool), --slice (a
production slice: slice-0100, slice-0250, slice-0500, slice-full; needs the cached corpus),
--doc / --ids-file, --field, --tier (gate, unit, reported, unscored), --presence, --source,
--rule, --needs-human, --conflict.

Output: --format table (default), json or csv; --limit caps the rows printed; --out writes the
full result to a file instead of stdout.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mailroom_sandbox import label_eda as eda  # noqa: E402

PRESENCE = ("populated", "documented_absence", "unlabeled", "disputed_unresolved")


def _split_list(values: Sequence[str] | None) -> frozenset[str] | None:
    if not values:
        return None
    return frozenset(v.strip() for item in values for v in item.split(",") if v.strip())


def _filter(args: argparse.Namespace) -> eda.Filter:
    # Any id source given selects exactly its ids: an empty --ids-file selects nothing, not everything.
    ids: set[str] | None = None
    if args.doc or args.ids_file:
        ids = set(_split_list(args.doc) or ())
        if args.ids_file:
            ids |= {line.strip() for line in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
                    if line.strip()}
    if args.slice:
        drawn = set(eda.slice_ids(args.slice))
        ids = drawn if ids is None else ids & drawn
    return eda.Filter(doc_ids=frozenset(ids) if ids is not None else None, doc_class=args.doc_class,
                      subclass=args.subclass, split=args.split, fields=_split_list(args.field),
                      tiers=_split_list(args.tier), presence=_split_list(args.presence), source=args.source,
                      rule=args.rule, needs_human=args.needs_human, conflict=args.conflict)


def _table(rows: list[dict[str, Any]], limit: int | None) -> str:
    if not rows:
        return "(no rows)"
    shown = rows[:limit] if limit else rows
    cols = list(dict.fromkeys(k for r in shown for k in r))
    cells = [[_short(r.get(c)) for c in cols] for r in shown]
    width = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(cols, width)), "  ".join("-" * w for w in width)]
    lines += ["  ".join(v.ljust(w) for v, w in zip(row, width)) for row in cells]
    if limit and len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows (raise --limit or use --out)")
    return "\n".join(lines)


def _short(v: Any, n: int = 70) -> str:
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else ("" if v is None else str(v))
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _emit(result: Any, args: argparse.Namespace) -> None:
    limit = None if args.out else args.limit  # --out writes the full result
    if args.format == "json" or not isinstance(result, list):
        text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
        if args.format == "table" and not isinstance(result, list):
            text = _sections(result, limit)
    elif args.format == "csv":
        buf = io.StringIO()
        cols = list(dict.fromkeys(k for r in result for k in r))
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        w.writerows({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                     for k, v in r.items()} for r in result)
        text = buf.getvalue()
    else:
        text = _table(result, limit)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


def _sections(result: dict[str, Any], limit: int | None) -> str:
    out = []
    for key, val in result.items():
        out.append(f"== {key}")
        if isinstance(val, list) and val and isinstance(val[0], dict):
            out.append(_table(val, limit))
        elif isinstance(val, list):
            out.append(f"({len(val)}) " + ", ".join(map(str, val[: limit or len(val)])))
        else:
            out.append(json.dumps(val, ensure_ascii=False, default=str))
    return "\n".join(out)


def cmd_summary(args, labels, flt):
    cells = eda.select(labels, flt)
    return {"coverage_by_class": eda.coverage(cells, ["doc_class"]),
            "coverage_by_class_and_tier": eda.coverage(cells, ["doc_class", "tier"]),
            "winning_source": eda.source_mix(cells)}


def cmd_coverage(args, labels, flt):
    by = [b.strip() for b in args.by.split(",") if b.strip()]
    rows = eda.coverage(eda.select(labels, flt), by)
    if args.below is not None:
        rows = [r for r in rows if r["completeness"] < args.below]
    return rows


def cmd_gaps(args, labels, flt):
    return eda.gaps(eda.select(labels, flt), top=args.top)


def cmd_focus(args, labels, flt):
    result = eda.focus(labels, flt, top=args.top)
    if args.ids_out:
        ids = sorted({d["doc_id"] for d in result["1_unscorable_docs"]}
                     | {c.doc_id for c in eda.select(labels, flt) if not c.labeled and c.tier == "gate"})
        Path(args.ids_out).write_text("\n".join(ids) + "\n", encoding="utf-8")
        result["ids_out"] = f"{len(ids)} document ids with open gate work written to {args.ids_out}"
    return result


def cmd_rows(args, labels, flt):
    return [c.as_dict(evidence=args.evidence, votes=args.votes) for c in eda.select(labels, flt)]


def cmd_doc(args, labels, flt):
    return eda.doc_card(labels, args.doc_id)


def _store_ids(labels, flt) -> frozenset[str] | None:
    """Document ids for a raw-store query: ``--subclass`` and ``--split`` resolve through the release."""
    if flt.subclass is None and flt.split is None:
        return flt.doc_ids
    return frozenset(d.doc_id for d in labels.docs.values() if flt.doc_ok(d))


def cmd_catalog(args, labels, flt):
    return eda.catalog_records(doc_ids=_store_ids(labels, flt), doc_class=args.doc_class, fields=flt.fields,
                               status=args.status)


def cmd_interim(args, labels, flt):
    return eda.interim_records(doc_ids=_store_ids(labels, flt), doc_class=args.doc_class, fields=flt.fields)


# Filters that describe a merged release cell; a raw store record has none of them.
_CELL_ONLY = (("tier", "--tier"), ("presence", "--presence"), ("source", "--source"), ("rule", "--rule"),
              ("needs_human", "--needs-human"), ("conflict", "--conflict"))
_DICT_COMMANDS = frozenset({"summary", "focus", "doc"})


def _usage_error(args) -> str | None:
    if args.format == "csv" and args.cmd in _DICT_COMMANDS:
        return f"{args.cmd} returns sections, not rows: use --format table or json"
    if args.cmd in ("catalog", "interim"):
        bad = [flag for attr, flag in _CELL_ONLY if getattr(args, attr)]
        if bad:
            return f"{args.cmd} reads raw label records, which have no {', '.join(bad)}: use rows for those"
    return None


def parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    g = shared.add_argument_group("filters")
    g.add_argument("--class", dest="doc_class", help="document class, e.g. corporate_record")
    g.add_argument("--subclass", help="reviewed subclass (SHF-013 corrections applied), e.g. indenture")
    g.add_argument("--split", choices=("dev", "calibration", "heldout", "pool"), help="runbook-v2 split")
    g.add_argument("--slice", help="production slice name (config/runs/production/<name>.yaml)")
    g.add_argument("--doc", action="append", help="document id(s), comma-separated or repeated")
    g.add_argument("--ids-file", help="file of document ids, one per line")
    g.add_argument("--field", action="append", help="field name(s), comma-separated or repeated")
    g.add_argument("--tier", action="append", help="gate, unit, reported or unscored (comma-separated)")
    g.add_argument("--presence", action="append", help="|".join(PRESENCE) + " (comma-separated)")
    g.add_argument("--source", help="a source that backs the value, e.g. near_gold_two_pass, hub_v9.3")
    g.add_argument("--rule", help="vote rule, e.g. reviewed_over_hub, owner_final")
    g.add_argument("--needs-human", action="store_true", help="only cells queued for a human")
    g.add_argument("--conflict", action="store_true", help="only cells whose sources disagreed")
    o = shared.add_argument_group("output")
    o.add_argument("--format", choices=("table", "json", "csv"), default="table")
    o.add_argument("--limit", type=int, default=40, help="rows printed in a table (0: all)")
    o.add_argument("--out", help="write the full result here instead of stdout")
    o.add_argument("--release", type=Path, help="label-repaired release directory (default: the committed one)")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary", parents=[shared], help="per-class coverage, tiers and winning sources")
    c = sub.add_parser("coverage", parents=[shared], help="completeness grouped by --by")
    c.add_argument("--by", default="doc_class,field", help="comma list of doc_class, subclass, field, split, tier, "
                                                        "chosen_source")
    c.add_argument("--below", type=float, help="only groups with completeness below this (0-1)")
    for name, helptext in (("gaps", "open cells by class, subclass and field"),
                           ("focus", "ranked work list (unscored cells left out)")):
        p = sub.add_parser(name, parents=[shared], help=helptext)
        p.add_argument("--top", type=int, default=30)
        if name == "focus":
            p.add_argument("--ids-out", help="write the document ids with open gate work here")
    r = sub.add_parser("rows", parents=[shared], help="the matching cells")
    r.add_argument("--evidence", action="store_true", help="include the winning evidence quotes")
    r.add_argument("--votes", action="store_true", help="include every source's vote")
    d = sub.add_parser("doc", parents=[shared], help="one document's card")
    d.add_argument("doc_id")
    k = sub.add_parser("catalog", parents=[shared], help="near-gold catalog records")
    k.add_argument("--status", help="catalog status, e.g. near_gold, candidate, disputed")
    sub.add_parser("interim", parents=[shared], help="interim overlay records")
    return ap


COMMANDS = {"summary": cmd_summary, "coverage": cmd_coverage, "gaps": cmd_gaps, "focus": cmd_focus,
            "rows": cmd_rows, "doc": cmd_doc, "catalog": cmd_catalog, "interim": cmd_interim}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.limit = args.limit or None
    problem = _usage_error(args)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    labels = eda.load(release=args.release)
    try:
        flt = _filter(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        result = COMMANDS[args.cmd](args, labels, flt)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 2
    _emit(result, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
