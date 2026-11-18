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
    # must be independent (build refuses a file in both roles, a wrong labeler role, a document
    # twice in one pass, a check whose fields are byte-identical to the label's, or two files
    # with the same batch and the same content) and every review decision must match a catalog
    # record. A review line is {"doc_id", "field", "verdict", "reviewer": {"model", "role"}, ...}:
    #   accept        the label stands (near_gold); on a field an --override replaced it must
    #                 also give "value" equal to the current label (a stale accept is refused)
    #   reject        the label is dropped to the supplementary store
    #   correct       "entry": {"value", "evidence"} replaces the label; it must pass the gate
    #   accept_check  adopt the check pass's own entry (value and quotes) for this field; no
    #                 "entry" is written, build takes it from the check submission and gates it.
    #                 The record keeps verdict "accept_check" and value_source.kind "check_pass"
    #                 (a correct verdict gives value_source.kind "review_correction"); the
    #                 overlay basis is near_gold:opus_reviewed_accept_check.
    python scripts/gold_labels.py build --corpus … --revision … --label L.jsonl… --check C.jsonl… \
        [--review R.jsonl…] [--override O.jsonl…]
    # apply accept/correct review lines to the committed catalog in place (no label or check
    # passes needed); the correction is gated on the corpus text as in build, and the file joins
    # the manifest's sources.review so the next full build is given it too
    python scripts/gold_labels.py review --corpus … --review R.jsonl…
    # integrity of the catalog (or of data/labels/gold-supplementary via --dir), including the
    # near_gold invariant (agreeing check pass, or a review with reviewer model and role)
    python scripts/gold_labels.py check
    # near_gold overlay for Mailroom-Corpus-EDA; refuses a failing catalog and an --out that is a
    # catalog directory or holds some other MANIFEST
    python scripts/gold_labels.py overlay [--out DIR]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
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
            measured = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if row.get("content_sha256") and row["content_sha256"] != measured:
                raise SystemExit(f"{sub.get('doc_id')}: corpus text does not match its content_sha256; "
                                 "refusing to label a document whose text is not the published one")
            doc = {"doc_id": row["document_id"], "filename": row["filename"], "doc_class": row["expected"],
                   "subclass": row.get("expected_subclass"), "content_sha256": measured}
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
    problems += _independence_problems(label_files, check_files)
    return problems


def _file_sha(path: str, cache: dict[str, str]) -> str:
    if path not in cache:
        cache[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return cache[path]


def _independence_problems(label_files: list[str], check_files: list[str]) -> list[str]:
    """A check that is a copy of its label is not a second reading: byte-identical fields for a
    document, or label and check labelers with one batch id out of files with identical content."""
    labels = {}
    for path in label_files:
        for sub in gl.read_jsonl(Path(path)):
            labels.setdefault(sub.get("doc_id"), (path, sub))
    hashes: dict[str, str] = {}
    problems = []
    for path in check_files:
        for chk in gl.read_jsonl(Path(path)):
            doc_id = chk.get("doc_id")
            if doc_id not in labels:
                continue
            lpath, lab = labels[doc_id]
            fields = chk.get("fields")
            if fields and json.dumps(fields, sort_keys=True) == json.dumps(lab.get("fields"), sort_keys=True):
                problems.append(f"{path}: {doc_id}: check fields are identical to the label pass in {lpath}; "
                                "not an independent pass")
            lb, cb = (s.get("labeler") for s in (lab, chk))
            lbatch = lb.get("batch") if isinstance(lb, dict) else None
            cbatch = cb.get("batch") if isinstance(cb, dict) else None
            if lbatch and lbatch == cbatch and _file_sha(lpath, hashes) == _file_sha(path, hashes):
                problems.append(f"{path}: {doc_id}: label and check carry batch {lbatch!r} out of files "
                                f"with the same content ({lpath}); not an independent pass")
    return problems


class _BuildError(Exception):
    """A build step that stops the run; the message goes to stderr, exit code 1."""


def _review_line_problems(where: str, r: dict) -> list[str]:
    """Why one review line is unusable (reviewer, then verdict)."""
    problems = []
    why = gl.reviewer_problem(r.get("reviewer"))
    if why:
        problems.append(f"{where} {why}" if why == "has no reviewer" else f"{where}: {why}")
    verdict = r.get("verdict")
    if verdict is None:
        problems.append(f"{where} has no verdict")
    elif verdict not in gl.REVIEW_VERDICTS:
        problems.append(f"{where}: unknown verdict {verdict!r}")
    elif verdict == "correct" and not isinstance(r.get("entry"), dict):
        problems.append(f"{where}: verdict 'correct' needs an entry")
    return problems


def _load_reviews(paths: list[str], problems: list[str]) -> dict[tuple[str, str], dict]:
    """Read the review files into {(doc_id, field): decision}; append what is wrong to ``problems``."""
    reviews: dict[tuple[str, str], dict] = {}
    for path in paths:
        for n, r in enumerate(gl.read_jsonl(Path(path)), start=1):
            if not isinstance(r, dict) or not isinstance(r.get("doc_id"), str) or not isinstance(r.get("field"), str):
                problems.append(f"{path}: line {n}: a review needs a doc_id and a field")
                continue
            where = f"{path}: review of {r['doc_id']}.{r['field']}"
            problems += _review_line_problems(where, r)
            key = (r["doc_id"], r["field"])
            if key in reviews:
                problems.append(f"{where}: duplicate review for {r['doc_id']}.{r['field']} (in {path})")
            reviews[key] = r
    return reviews


def _merge_overrides(corpus: Path, args: argparse.Namespace, labels: list) -> list:
    """Apply the relabel pass (--override) to the label passes.

    A relabel pass replaces the named fields of earlier label passes, for example after a guide
    rule changed. Its fields are catalogued with its own labeler and are not reconciled against
    an earlier check pass. Only a field that passes the gate replaces the earlier label; a
    failing one leaves it in place (its reject is kept).
    """
    overrides = _validate_all(corpus, args.override or [])
    replaced = {(d["doc_id"], f) for d, _, res, _ in overrides for f, fr in res.fields.items() if fr.ok}
    for doc, sub, res, _ in labels:
        for name in [f for f in res.fields if (doc["doc_id"], f) in replaced]:
            del res.fields[name]
    return labels + [(d, {**sub, "relabel": True}, r, t) for d, sub, r, t in overrides]


def _resolve_decision(rec: dict, decision: dict, chk: Any, doc: dict, text: str, *,
                      relabel: bool = False) -> dict:
    """Turn a review line into the fields ``gl.apply_review`` takes (raises _BuildError)."""
    if decision["verdict"] == "accept" and (relabel or "value" in decision):
        # An accept is keyed by doc and field only: on a relabelled field (or whenever the line
        # names a value) it must name the value it reviewed, so a stale accept of the replaced
        # label never promotes the new one.
        if "value" not in decision or decision["value"] != rec.get("value"):
            raise _BuildError(f"accept for {rec['doc_id']}.{rec['field']} does not name the current "
                              f"value {rec.get('value')!r}; re-review it")
    if decision["verdict"] == "accept_check":
        # The reviewer adopts the check pass's answer, quotes and all; the record
        # keeps the verdict and names the check labeler as the value's source.
        entry = ((chk[0].get("fields") or {}).get(rec["field"]) if chk else None)
        if entry is None:
            raise _BuildError(f"accept_check for {rec['doc_id']}.{rec['field']}: no check answer")
        decision = {**decision, "entry": entry, "check_labeler": chk[0].get("labeler")}
    if decision["verdict"] in ("correct", "accept_check"):
        fixed = gl.validate_submission(
            {"doc_id": doc["doc_id"], "fields": {rec["field"]: decision["entry"]}}, text,
            doc["doc_class"])
        fr = fixed.fields[rec["field"]]
        if not fr.ok:
            raise _BuildError(f"review correction for {rec['doc_id']}.{rec['field']} fails the gate: "
                              f"{fr.reason}")
        decision = {**decision, "value": fr.value, "evidence": fr.evidence,
                    "presence": fr.presence, "absent_reason": fr.absent_reason}
    return {k: v for k, v in decision.items() if k not in ("doc_id", "field", "entry")}


def _build_rows(labels: list, checks: dict, reviews: dict[tuple[str, str], dict], binding: dict[str, Any]
                ) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Reconcile every label with its check pass and review into catalog and supplementary rows."""
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
                rec = gl.apply_review(rec, _resolve_decision(rec, decision, chk, doc, text,
                                                                relabel=bool(sub.get("relabel"))))
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
        raise _BuildError("build refused: review decisions match no catalog record:\n  "
                          + "\n  ".join(f"{d}.{f}" for d, f in orphans))
    return catalog, supplementary


def _class_counts(data: dict[str, list[dict]]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for cls, recs in data.items():
        c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for r in recs:
            c[r.get("field", "-")][r.get("status") or r.get("kind")] += 1
        counts[cls] = {f: dict(v) for f, v in sorted(c.items())}
    return counts


@contextmanager
def _staging(directory: Path):
    """A temporary directory beside ``directory`` (same filesystem, so files move atomically)."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent, prefix=f".{directory.name}-stage-") as tmp:
        yield Path(tmp)


def _swap_in(stage: Path, directory: Path) -> None:
    """Replace ``directory``'s jsonl files and MANIFEST with the staged ones; restore them on failure."""
    directory.mkdir(parents=True, exist_ok=True)
    owned = [*directory.glob("*.jsonl"), directory / "MANIFEST.json"]
    previous = {p.name: p.read_bytes() for p in owned if p.exists()}
    try:
        for stale in directory.glob("*.jsonl"):
            stale.unlink()
        for staged in sorted(stage.iterdir()):
            os.replace(staged, directory / staged.name)
    except BaseException:
        for stale in directory.glob("*.jsonl"):
            stale.unlink()
        for name, blob in previous.items():
            (directory / name).write_bytes(blob)
        raise


def _write_catalog_dir(directory: Path, data: dict[str, list[dict]], schema: str, now: str,
                       binding: dict[str, Any], args: argparse.Namespace) -> None:
    """Replace one catalog directory's jsonl files and MANIFEST."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.jsonl"):
        stale.unlink()
    files = {}
    for cls, recs in sorted(data.items()):
        recs.sort(key=lambda r: (r.get("doc_id", ""), r.get("field", ""), r.get("kind", "")))
        files[f"{cls}.jsonl"] = gl.write_jsonl(directory / f"{cls}.jsonl", recs)
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
        "counts": _class_counts(data),
        "files": files,
    }
    if schema == gl.SUPPLEMENTARY_SCHEMA:
        manifest["note"] = "Supplementary labeler output. Never ground truth; no scorer reads it."
    (directory / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    missing = [p for p in [*args.label, *(args.check or []), *(args.review or []), *(args.override or [])]
               if not Path(p).is_file()]
    if missing:
        print("build refused: input files not found:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    problems = _pass_problems(args)
    reviews = _load_reviews(args.review or [], problems)
    if problems:
        print("build refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    labels = _merge_overrides(corpus, args, _validate_all(corpus, args.label))
    checks = {(d["doc_id"]): (sub, res) for d, sub, res, _ in _validate_all(corpus, args.check or [])}
    binding = _schema_binding(args.revision)
    try:
        catalog, supplementary = _build_rows(labels, checks, reviews, binding)
    except _BuildError as exc:
        print(exc, file=sys.stderr)
        return 1

    gold, supp = gl.gold_dir(), gl.supplementary_dir()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Build both stores beside their directories and verify the catalog there; nothing is
    # replaced unless it passes (a near_gold value the Dojo cannot parse is refused before writing).
    with _staging(gold) as gold_stage, _staging(supp) as supp_stage:
        _write_catalog_dir(gold_stage, catalog, gl.SCHEMA, now, binding, args)
        left = gl.verify_catalog(gold_stage)
        if left:
            print("build refused: the built catalog fails its check; nothing was written:\n  "
                  + "\n  ".join(left), file=sys.stderr)
            return 1
        _write_catalog_dir(supp_stage, supplementary, gl.SUPPLEMENTARY_SCHEMA, now, binding, args)
        _swap_in(gold_stage, gold)
        _swap_in(supp_stage, supp)
    print(f"catalog: {sum(len(v) for v in catalog.values())} labels; "
          f"supplementary: {sum(len(v) for v in supplementary.values())} rows")
    print(f"MANIFEST sha256 {gl.manifest_sha(gold)}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Apply review files to the committed catalog in place, without the label and check passes.

    Only ``accept`` and ``correct`` lines, each for a record no review has settled yet; a
    correction passes the same gate as in ``build`` (on the corpus text). The file names join
    ``sources.review`` in the manifest, so the next full ``build`` must be given them too.
    """
    gold = gl.gold_dir()
    problems: list[str] = []
    reviews = _load_reviews(args.review, problems)
    # A problem of a record this run reviews is what the review fixes; the result is verified below.
    problems += [p for p in gl.verify_catalog(gold) if not any(p.startswith(f"{d}.{f}:") for d, f in reviews)]
    problems += [f"{d}.{f}: in-place review takes accept or correct, not {r['verdict']!r} (use build)"
                 for (d, f), r in reviews.items() if r.get("verdict") not in ("accept", "correct")]
    if problems:
        print("review refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    manifest = json.loads((gold / "MANIFEST.json").read_text(encoding="utf-8"))
    data = {Path(name).stem: gl.read_jsonl(gold / name) for name in sorted(manifest["files"])}
    index = {(r["doc_id"], r["field"]): (cls, i) for cls, recs in data.items() for i, r in enumerate(recs)}
    _, texts = _load_corpus(Path(args.corpus))
    for key, decision in sorted(reviews.items()):
        if key not in index:
            problems.append(f"{key[0]}.{key[1]}: no catalog record")
            continue
        cls, i = index[key]
        rec = data[cls][i]
        if rec.get("review"):
            problems.append(f"{key[0]}.{key[1]}: already reviewed; change that review in its own file and rebuild")
            continue
        text = texts.get(rec.get("filename"))
        if text is None or gl.doc_sha(text) != rec.get("doc_sha"):
            problems.append(f"{key[0]}.{key[1]}: the corpus text is missing or differs from the label's")
            continue
        try:
            # relabel=True: the catalog does not mark a field an --override pass relabelled, so an
            # in-place accept always names the value it reviewed (the build replays it either way).
            resolved = _resolve_decision(rec, decision, None, {"doc_id": rec["doc_id"], "doc_class": cls}, text,
                                         relabel=True)
        except _BuildError as exc:
            problems.append(str(exc))
            continue
        data[cls][i] = gl.apply_review(rec, resolved)
    if problems:
        print("review refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    # Stage the new catalog beside the old one and verify it there; the committed files are
    # replaced only when it passes (a failing review leaves the catalog and its reviews as they were).
    with _staging(gold) as stage:
        files = {f"{cls}.jsonl": gl.write_jsonl(stage / f"{cls}.jsonl", recs) for cls, recs in data.items()}
        manifest["files"] = files
        manifest["counts"] = _class_counts(data)
        manifest["sources"]["review"] = sorted({*manifest["sources"].get("review", []),
                                                *(Path(p).name for p in args.review)})
        manifest["reviewed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (stage / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        left = gl.verify_catalog(stage)
        if left:
            print("review refused: the reviewed catalog fails its check; nothing was written:\n  "
                  + "\n  ".join(left), file=sys.stderr)
            return 1
        _swap_in(stage, gold)
    print(f"reviewed {len(reviews)} labels in place; MANIFEST sha256 {gl.manifest_sha(gold)}")
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


def _overlay_out_problem(out: Path, gold: Path) -> str | None:
    """Why the overlay may not be written to ``out`` (None = fine). The export deletes the
    ``*.jsonl`` files already in ``out``, so it must not be a catalog directory or a directory
    some other tool keeps (a MANIFEST of another schema, or loose JSONL with none)."""
    resolved = out.resolve()
    for name, directory in (("the gold catalog", gold), ("the gold catalog", gl.gold_dir()),
                            ("the supplementary store", gl.supplementary_dir())):
        if resolved == directory.resolve():
            return f"overlay refused: --out {out} is {name} directory"
    manifest = out / "MANIFEST.json"
    if manifest.is_file():
        try:
            schema = json.loads(manifest.read_text(encoding="utf-8")).get("schema")
        except (ValueError, AttributeError):
            schema = None
        if schema != gl.OVERLAY_SCHEMA:
            return f"overlay refused: {manifest} has schema {schema!r}, not {gl.OVERLAY_SCHEMA!r}"
    elif out.is_dir() and any(out.glob("*.jsonl")):
        return f"overlay refused: {out} holds JSONL files and no MANIFEST.json"
    return None


def cmd_overlay(args: argparse.Namespace) -> int:
    """Export the catalog as EDA overlay records (candidates for Mailroom-Corpus-EDA)."""
    gold = Path(args.dir) if args.dir else gl.gold_dir()
    problems = gl.verify_catalog(gold)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    schema = json.loads((gold / "MANIFEST.json").read_text(encoding="utf-8")).get("schema")
    if schema != gl.SCHEMA:
        print(f"overlay refused: {gold} is a {schema!r} catalog, not {gl.SCHEMA!r}", file=sys.stderr)
        return 1
    gate_run = f"gold-labels-{gl.manifest_sha(gold)[:12]}"
    out = Path(args.out) if args.out else gold.parent / "gold-overlay"
    refusal = _overlay_out_problem(out, gold)
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
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

    rv = sub.add_parser("review", help="apply accept/correct review files to the committed catalog in place")
    rv.add_argument("--corpus", required=True)
    rv.add_argument("--review", nargs="+", required=True)
    rv.set_defaults(fn=cmd_review)

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
