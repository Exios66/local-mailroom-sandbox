#!/usr/bin/env python3
"""Work queue, labeler batches, validation and catalog build for gold labels.

See ``mailroom_sandbox.gold_labels`` for the rules. No model is called here: labels come from
agent sessions that read the batch files and write submission JSONL.

    # the pinned corpus (``ground_truth`` + ``default`` parquet of one revision) in a directory
    python scripts/gold_labels.py queue --corpus data/cache/corpus-ccd040f6 --revision ccd040f6… \
        --out data/runtime/gold/queue.jsonl
    # labeler batches (doc text + target fields), never committed
    python scripts/gold_labels.py batch --queue data/runtime/gold/queue.jsonl --corpus … \
        --doc-class correspondence --size 25 --out data/runtime/gold/batches
    # gate one or more submission files and print a report
    python scripts/gold_labels.py validate --corpus … --submissions data/runtime/gold/sub/*.jsonl
    # build the catalog from label passes, check passes and review decisions; the two passes
    # must be independent (build refuses a file in both roles, a wrong labeler role, or a
    # document twice in one pass) and every review decision must match a catalog record
    python scripts/gold_labels.py build --corpus … --revision … --label L.jsonl… --check C.jsonl… \
        [--review R.jsonl…] [--override O.jsonl…]
    # integrity of the catalog (or of data/labels/gold-supplementary via --dir)
    python scripts/gold_labels.py check
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mailroom_sandbox import gold_labels as gl  # noqa: E402


def _load_corpus(corpus: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    import pandas as pd

    gt = pd.concat([pd.read_parquet(p) for p in sorted(corpus.glob("ground_truth_*.parquet"))])
    docs = pd.concat([pd.read_parquet(p) for p in sorted(corpus.glob("default_*.parquet"))])
    texts = dict(zip(docs["filename"], docs["doc_text"]))
    return gt.to_dict("records"), texts


def _rows_by_doc(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["document_id"]: r for r in rows}


def cmd_queue(args: argparse.Namespace) -> int:
    rows, _ = _load_corpus(Path(args.corpus))
    queue = gl.work_queue(rows, tiers=args.tiers)
    for q in queue:
        q["revision"] = args.revision
    gl.write_jsonl(Path(args.out), queue)
    counts = collections.Counter()
    for q in queue:
        for f in q["fields"]:
            counts[(q["doc_class"], f)] += 1
    print(f"{len(queue)} documents queued")
    for (cls, f), n in sorted(counts.items()):
        print(f"  {cls:18} {f:26} {n}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    queue = [q for q in gl.read_jsonl(Path(args.queue)) if q["doc_class"] == args.doc_class]
    done = set()
    for path in args.skip or []:
        done |= {s["doc_id"] for s in gl.read_jsonl(Path(path))}
    queue = [q for q in queue if q["doc_id"] not in done]
    if args.max_chars:
        _, texts = _load_corpus(Path(args.corpus))
        queue = [q for q in queue if len(texts.get(q["filename"], "")) <= args.max_chars]
    else:
        texts = _load_corpus(Path(args.corpus))[1]
    queue.sort(key=lambda q: (len(texts.get(q["filename"], "")), q["doc_id"]))
    if args.limit:
        queue = queue[: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    chunks, cur, cur_chars = [], [], 0
    for q in queue:
        size = len(texts[q["filename"]])
        if cur and (len(cur) >= args.size or (args.max_batch_chars and cur_chars + size > args.max_batch_chars)):
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.append(q)
        cur_chars += size
    if cur:
        chunks.append(cur)
    for i, chunk in enumerate(chunks):
        bdir = out / f"{args.doc_class}-{i:03d}"
        bdir.mkdir(parents=True, exist_ok=True)
        entries = []
        for q in chunk:
            text = texts[q["filename"]]
            (bdir / f"{q['doc_id']}.txt").write_text(text, encoding="utf-8")
            entries.append({**q, "text_file": f"{q['doc_id']}.txt", "chars": len(text)})
        gl.write_jsonl(bdir / "batch.jsonl", entries)
        n += 1
    print(f"{len(queue)} documents in {n} batches under {out}")
    return 0


def _validate_all(corpus: Path, paths: list[str]) -> list[tuple[dict, dict, gl.SubmissionResult, str]]:
    rows, texts = _load_corpus(corpus)
    by_doc = _rows_by_doc(rows)
    out = []
    for path in paths:
        for sub in gl.read_jsonl(Path(path)):
            row = by_doc.get(sub.get("doc_id"))
            if row is None:
                print(f"unknown doc_id {sub.get('doc_id')!r} in {path}", file=sys.stderr)
                continue
            text = texts[row["filename"]]
            doc = {"doc_id": row["document_id"], "filename": row["filename"], "doc_class": row["expected"],
                   "subclass": row.get("expected_subclass"), "content_sha256": row.get("content_sha256")}
            out.append((doc, sub, gl.validate_submission(sub, text, row["expected"]), text))
    return out


def cmd_validate(args: argparse.Namespace) -> int:
    results = _validate_all(Path(args.corpus), args.submissions)
    ok = collections.Counter()
    bad = collections.Counter()
    reasons = collections.Counter()
    for doc, _sub, res, _text in results:
        for name, fr in res.fields.items():
            key = (doc["doc_class"], name)
            if fr.ok:
                ok[key] += 1
            else:
                bad[key] += 1
                reasons[(name, (fr.reason or "")[:60])] += 1
                if args.verbose:
                    print(f"  REJECT {doc['doc_id']}.{name}: {fr.reason} (value={fr.value!r})")
        if not res.payload_valid:
            print(f"  SCHEMA {doc['doc_id']}: {res.payload_error}")
    print(f"{len(results)} submissions")
    for key in sorted(set(ok) | set(bad)):
        total = ok[key] + bad[key]
        print(f"  {key[0]:18} {key[1]:26} pass {ok[key]}/{total}")
    if reasons:
        print("rejections:")
        for (name, why), n in reasons.most_common(20):
            print(f"  {n:4}  {name}: {why}")
    return 0


def _schema_binding(revision: str) -> dict[str, Any]:
    gl._ensure_vendor_path()
    from schemas import documents

    import llm_dojo_scoring

    def _vendor_commit(name: str) -> str | None:
        text = (gl.repo_root() / "vendor" / name / "VENDOR.md").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("- Exact source commit:"):
                return line.split("`")[1]
        return None

    schema_json = {k: v.model_json_schema() for k, v in documents.EXTRACTION_SCHEMAS.items()}
    return {
        "dataset": "Lucius-Morningstar/mailroom-dataset",
        "dataset_revision": revision,
        "mailroom_commit": _vendor_commit("llm-mailroom"),
        "dojo_commit": _vendor_commit("llm-dojo-scoring"),
        "dojo_version": getattr(llm_dojo_scoring, "__version__", None),
        "extraction_schemas_sha256": hashlib.sha256(
            json.dumps(schema_json, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def _pass_problems(args: argparse.Namespace) -> list[str]:
    """Why these inputs cannot make independent passes (empty = fine).

    ``near_gold`` from agreement means two independent agent passes; a file in both roles, a
    submission that says it is the other pass, or one document twice in a pass would let a
    single reading agree with itself. (The same model family may write both passes.)
    """
    problems = []
    label_files, check_files = list(args.label), list(args.check or [])
    override_files = list(args.override or [])
    both = {str(Path(p).resolve()) for p in label_files} & {str(Path(p).resolve()) for p in check_files}
    problems += [f"{p}: given to both --label and --check" for p in sorted(both)]
    for kind, role, files in (("label", "label", label_files), ("check", "check", check_files),
                              ("override", "label", override_files)):
        seen: dict[str, str] = {}
        for path in files:
            for sub in gl.read_jsonl(Path(path)):
                doc_id = sub.get("doc_id")
                labeler = sub.get("labeler")
                got = labeler.get("role") if isinstance(labeler, dict) else None
                if got != role:
                    problems.append(f"{path}: {doc_id}: labeler role is {got!r}, a --{kind} submission needs {role!r}")
                if doc_id in seen:
                    problems.append(f"{path}: {doc_id} appears twice in the --{kind} files (also in {seen[doc_id]})")
                seen[doc_id] = path
    return problems


def cmd_build(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    problems = _pass_problems(args)
    reviews: dict[tuple[str, str], dict] = {}
    for path in args.review or []:
        for r in gl.read_jsonl(Path(path)):
            if not r.get("reviewer"):
                problems.append(f"{path}: review of {r.get('doc_id')}.{r.get('field')} has no reviewer")
            reviews[(r["doc_id"], r["field"])] = r
    if problems:
        print("build refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    labels = _validate_all(corpus, args.label)
    # A relabel pass (--override) replaces the named fields of earlier label passes, for
    # example after a guide rule changed. Its fields are catalogued with its own labeler and
    # are not reconciled against an earlier check pass. Only a field that passes the gate
    # replaces the earlier label; a failing one leaves it in place (its reject is kept).
    overrides = _validate_all(corpus, args.override or [])
    replaced = {(d["doc_id"], f) for d, _, res, _ in overrides for f, fr in res.fields.items() if fr.ok}
    for doc, sub, res, _ in labels:
        for name in [f for f in res.fields if (doc["doc_id"], f) in replaced]:
            del res.fields[name]
    labels = labels + [(d, {**sub, "relabel": True}, r, t) for d, sub, r, t in overrides]
    checks = {(d["doc_id"]): (sub, res) for d, sub, res, _ in _validate_all(corpus, args.check or [])}
    binding = _schema_binding(args.revision)
    applied: set[tuple[str, str]] = set()

    catalog: dict[str, list[dict]] = collections.defaultdict(list)
    supplementary: dict[str, list[dict]] = collections.defaultdict(list)
    for doc, sub, res, text in labels:
        chk = None if sub.get("relabel") else checks.get(doc["doc_id"])
        records, rejects = gl.reconcile(doc, text, res, chk[1] if chk else None, sub.get("labeler", {}),
                                        chk[0].get("labeler", {}) if chk else None, binding)
        for rec in records:
            decision = reviews.get((rec["doc_id"], rec["field"]))
            if decision is not None:
                applied.add((rec["doc_id"], rec["field"]))
                if decision["verdict"] == "correct":
                    fixed = gl.validate_submission(
                        {"doc_id": doc["doc_id"], "fields": {rec["field"]: decision["entry"]}}, text,
                        doc["doc_class"])
                    fr = fixed.fields[rec["field"]]
                    if not fr.ok:
                        print(f"review correction for {rec['doc_id']}.{rec['field']} fails the gate: "
                              f"{fr.reason}", file=sys.stderr)
                        return 1
                    decision = {**decision, "value": fr.value, "evidence": fr.evidence,
                                "presence": fr.presence, "absent_reason": fr.absent_reason}
                decision = {k: v for k, v in decision.items() if k not in ("doc_id", "field", "entry")}
                rec = gl.apply_review(rec, decision)
            if rec["status"] == "rejected":
                supplementary[doc["doc_class"]].append({"kind": "review_rejected", **rec})
            else:
                catalog[doc["doc_class"]].append(rec)
        for rej in rejects:
            supplementary[doc["doc_class"]].append({"kind": "gate_reject", **rej})
        extra = {"label": sub.get("supplementary")}
        if chk:
            extra["check"] = chk[0].get("supplementary")
        if any(v for v in extra.values()):
            supplementary[doc["doc_class"]].append({"kind": "notes", "doc_id": doc["doc_id"], **extra})

    orphans = sorted(set(reviews) - applied)
    if orphans:
        print("build refused: review decisions match no catalog record:\n  "
              + "\n  ".join(f"{d}.{f}" for d, f in orphans), file=sys.stderr)
        return 1

    gold, supp = gl.gold_dir(), gl.supplementary_dir()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for directory, data, schema in ((gold, catalog, gl.SCHEMA), (supp, supplementary, gl.SUPPLEMENTARY_SCHEMA)):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.jsonl"):
            stale.unlink()
        files = {}
        for cls, recs in sorted(data.items()):
            recs.sort(key=lambda r: (r.get("doc_id", ""), r.get("field", ""), r.get("kind", "")))
            files[f"{cls}.jsonl"] = gl.write_jsonl(directory / f"{cls}.jsonl", recs)
        counts: dict[str, Any] = {}
        for cls, recs in data.items():
            c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
            for r in recs:
                c[r.get("field", "-")][r.get("status") or r.get("kind")] += 1
            counts[cls] = {f: dict(v) for f, v in sorted(c.items())}
        manifest = {
            "schema": schema,
            "built_at": now,
            "builder": "scripts/gold_labels.py build",
            "binding": binding,
            "target_fields": gl.TARGET_FIELDS,
            "truth_statuses": list(gl.TRUTH_STATUSES) if schema == gl.SCHEMA else [],
            "sources": {"label": sorted(Path(p).name for p in args.label),
                        "check": sorted(Path(p).name for p in args.check or []),
                        "review": sorted(Path(p).name for p in args.review or []),
                        "override": sorted(Path(p).name for p in args.override or [])},
            "counts": counts,
            "files": files,
        }
        if schema == gl.SUPPLEMENTARY_SCHEMA:
            manifest["note"] = "Supplementary labeler output. Never ground truth; no scorer reads it."
        (directory / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                 encoding="utf-8")
    print(f"catalog: {sum(len(v) for v in catalog.values())} labels; "
          f"supplementary: {sum(len(v) for v in supplementary.values())} rows")
    print(f"MANIFEST sha256 {gl.manifest_sha(gold)}")
    return 0


def cmd_disputes(args: argparse.Namespace) -> int:
    """A compact review sheet: every disputed field with both readings and nearby text."""
    corpus = Path(args.corpus)
    labels = _validate_all(corpus, args.label)
    checks = {d["doc_id"]: (sub, res) for d, sub, res, _ in _validate_all(corpus, args.check)}
    fields = set(args.fields or [])
    rows = []
    for doc, sub, res, text in labels:
        chk = checks.get(doc["doc_id"])
        records, _ = gl.reconcile(doc, text, res, chk[1] if chk else None, {}, {}, {})
        for rec in records:
            if rec["status"] != "disputed" or (fields and rec["field"] not in fields):
                continue
            spans = rec["evidence"] or []
            lo = min((sp["start"] for sp in spans), default=0)
            hi = max((sp["end"] for sp in spans), default=min(len(text), 300))
            ctx = text[max(0, lo - args.context): hi + args.context]
            rows.append({"doc_id": rec["doc_id"], "field": rec["field"], "label": rec["value"],
                         "label_absent": rec.get("absent_reason"), "check": rec["check"]["value"],
                         "check_gate": rec["check"]["gate_ok"], "chars": len(text),
                         "context": " ".join(ctx.split())})
    gl.write_jsonl(Path(args.out), rows)
    print(f"{len(rows)} disputed fields -> {args.out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    problems = gl.verify_catalog(Path(args.dir) if args.dir else gl.gold_dir())
    for p in problems:
        print(p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_overlay(args: argparse.Namespace) -> int:
    """Export the catalog as EDA overlay records (candidates for Mailroom-Corpus-EDA)."""
    gold = Path(args.dir) if args.dir else gl.gold_dir()
    problems = gl.verify_catalog(gold)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    gate_run = f"gold-labels-{gl.manifest_sha(gold)[:12]}"
    out = Path(args.out) if args.out else gold.parent / "gold-overlay"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.jsonl"):
        stale.unlink()
    files, counts = {}, {}
    for path in sorted(gold.glob("*.jsonl")):
        recs = gl.overlay_records(gl.read_jsonl(path), gate_run=gate_run)
        files[path.name] = gl.write_jsonl(out / path.name, recs)
        c: collections.Counter = collections.Counter()
        for r in recs:
            for lab in r["labels"].values():
                c[lab["basis"]] += 1
        counts[path.stem] = dict(sorted(c.items()))
    manifest = {
        "schema": gl.OVERLAY_SCHEMA,
        "status": "near-gold candidates for the Mailroom-Corpus-EDA master copy; gold only with a "
                  "reviewer's initials there (EDA #65)",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": "scripts/gold_labels.py overlay",
        "gate_run": gate_run,
        "catalog_manifest_sha256": gl.manifest_sha(gold),
        "rules": {"truth_statuses": [], "exported_statuses": ["near_gold"],
                  "near_empty_chars": gl.NEAR_EMPTY_CHARS},
        "counts": counts,
        "files": files,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"overlay: {sum(sum(v.values()) for v in counts.values())} labels; "
          f"MANIFEST sha256 {gl.manifest_sha(out)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("queue")
    q.add_argument("--corpus", required=True)
    q.add_argument("--revision", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--tiers", nargs="+", default=["tier1", "tier2"])
    q.set_defaults(fn=cmd_queue)

    b = sub.add_parser("batch")
    b.add_argument("--queue", required=True)
    b.add_argument("--corpus", required=True)
    b.add_argument("--doc-class", required=True)
    b.add_argument("--size", type=int, default=25)
    b.add_argument("--limit", type=int)
    b.add_argument("--max-chars", type=int)
    b.add_argument("--max-batch-chars", type=int, help="start a new batch before this many characters")
    b.add_argument("--skip", nargs="*", help="submission files whose documents are already labelled")
    b.add_argument("--out", required=True)
    b.set_defaults(fn=cmd_batch)

    v = sub.add_parser("validate")
    v.add_argument("--corpus", required=True)
    v.add_argument("--submissions", nargs="+", required=True)
    v.add_argument("--verbose", action="store_true")
    v.set_defaults(fn=cmd_validate)

    bd = sub.add_parser("build")
    bd.add_argument("--corpus", required=True)
    bd.add_argument("--revision", required=True)
    bd.add_argument("--label", nargs="+", required=True)
    bd.add_argument("--check", nargs="*")
    bd.add_argument("--review", nargs="*")
    bd.add_argument("--override", nargs="*", help="relabel passes whose fields replace earlier label passes")
    bd.set_defaults(fn=cmd_build)

    ds = sub.add_parser("disputes")
    ds.add_argument("--corpus", required=True)
    ds.add_argument("--label", nargs="+", required=True)
    ds.add_argument("--check", nargs="+", required=True)
    ds.add_argument("--fields", nargs="*")
    ds.add_argument("--context", type=int, default=250)
    ds.add_argument("--out", required=True)
    ds.set_defaults(fn=cmd_disputes)

    c = sub.add_parser("check")
    c.add_argument("--dir", help="catalog directory: data/labels/gold (default) or gold-supplementary")
    c.set_defaults(fn=cmd_check)

    ov = sub.add_parser("overlay", help="export near-gold candidates in EDA's overlay shape")
    ov.add_argument("--dir", help="catalog directory (default data/labels/gold)")
    ov.add_argument("--out", help="output directory (default data/labels/gold-overlay)")
    ov.set_defaults(fn=cmd_overlay)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
