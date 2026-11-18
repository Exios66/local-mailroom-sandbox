#!/usr/bin/env python3
"""Build and check the interim ground-truth label overlay (``data/labels/interim/``).

The overlay holds the labels the next mailroom-dataset revision is expected to publish, taken
from gate-accepted real extractions (see ``mailroom_sandbox.interim_labels`` for the rules).

    # rebuild from the gate runs the manifest already lists (after any of them changed)
    python scripts/interim_labels.py build
    # add a new gate run (a later question set wins per document)
    python scripts/interim_labels.py build --add-run extraction-gate-luna-v1.4.0
    # integrity, staleness (a newer local gate run not yet folded in), Hub supersession, and
    # every listed review file applied as written
    python scripts/interim_labels.py check [--rows hub-rows.jsonl|ground_truth.parquet] [--prune]
    # apply reviewed labels (data/labels/review/interim_reviews.jsonl) in place; build re-applies them
    python scripts/interim_labels.py review [--apply FILE ...]
    # a Hub ground_truth parquet shard with the overlay merged into gt_fields
    python scripts/interim_labels.py apply --parquet ground_truth_train.parquet --out overlaid.parquet

``build`` reads finished gate runs from ``data/runtime/runs`` (their locked dataset rows, the
specialist extractions they reviewed and the gate answers). ``check`` needs only the committed
files; with runtime data present it also refuses a stale overlay.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mailroom_sandbox import interim_labels as il  # noqa: E402


def _version(v: Any) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def _gate_run(run_id: str) -> dict[str, Any]:
    """Everything the overlay needs from one finished gate run."""
    import extraction_gate as eg
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    store = RunStore(run_dir(run_id))
    lock = store.read_lock() or {}
    if lock.get("task") != "extraction_gate":
        raise SystemExit(f"{run_id}: not an extraction_gate run")
    if (store.read_checkpoint() or {}).get("state") != "done":
        raise SystemExit(f"{run_id}: not finished")
    reviewer = lock.get("reviewer") or {}
    qversion = str((reviewer.get("question_set") or {}).get("version") or "")
    handoff = reviewer.get("handoff") or {}
    source_of: dict[str, dict[str, Any]] = {}
    runs = reviewer.get("handoff_run") or []
    for hrun in [runs] if isinstance(runs, str) else runs:
        hstore = RunStore(run_dir(str(hrun)))
        result = (hstore.read_checkpoint() or {}).get("result") or {}
        prompt = result.get("prompt_version") or ((hstore.read_lock() or {}).get("prompt") or {}).get("default", {}).get("source")
        meta = {"extraction_run": str(hrun), "prompt_version": prompt, "extractor": result.get("model")}
        for item in hstore.load_items():
            source_of[str(item.get("item_id"))] = meta
    rows = {r["id"]: r for r in store.dataset_rows()}
    docs = []
    for item in store.load_items():
        doc = str(item.get("item_id"))
        pred = item.get("pred") or {}
        if not item.get("ok") or doc not in rows or doc not in handoff:
            continue
        row = rows[doc]
        fields = handoff[doc].get("fields") or {}
        # A scorer error leaves the row with no field truth, as before (the error is reported by calibrate).
        truth, _error = eg._field_truth(str(row.get("expected_doc_class")), row, fields, 0.8)
        docs.append({"row": row, "fields": fields, "gate": pred, "truth": truth, "source": source_of.get(doc, {})})
    return {"run_id": run_id, "question_set": qversion, "dataset_revision": (lock.get("dataset") or {}).get("revision"),
            "dataset_sha256": (lock.get("dataset") or {}).get("sha256"), "docs": docs}


def _replace(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (a reader sees the old file or the new one)."""
    # A unique temp file per writer: concurrent builds or prunes never share a staged file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _counts(root: Path, names: Iterable[str]) -> dict[str, dict[str, dict[str, int]]]:
    """Per class, field and status: the label counts of the overlay files as written."""
    counts: dict[str, dict[str, collections.Counter]] = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for name in names:
        for rec in il._jsonl(root / name):
            for field, lab in (rec.get("labels") or {}).items():
                counts[str(rec.get("doc_class"))][field][lab.get("status")] += 1
    # str() keys the sort: a label with no status (reported by verify) must not break the counts.
    return {cls: {f: dict(sorted(c.items(), key=lambda kv: str(kv[0]))) for f, c in sorted(fs.items())}
            for cls, fs in sorted(counts.items())}


def build(run_ids: list[str], root: Path, reviews: list[Path] | None = None) -> dict[str, Any]:
    runs = [_gate_run(r) for r in run_ids]
    # Per document, the latest question set wins (then the later run in the list).
    best: dict[str, tuple[tuple[int, ...], int, dict[str, Any], dict[str, Any]]] = {}
    for order, run in enumerate(runs):
        key = _version(run["question_set"])
        for d in run["docs"]:
            doc = d["row"]["id"]
            if doc not in best or (key, order) >= best[doc][:2]:
                best[doc] = (key, order, run, d)
    by_class: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    counts: dict[str, dict[str, collections.Counter]] = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    # Precision proxy of the admission rule: on fields the Hub DOES label, how often a value the
    # gate accepts at >= SUPPORT_MIN is right by the dojo (the same rule admits the gap fills).
    proxy: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for doc in sorted(best):
        _, _, run, d = best[doc]
        row, gate = d["row"], d["gate"]
        cls = str(row.get("expected_doc_class"))
        for field, ok in d["truth"].items():
            s = (gate.get("field_support") or {}).get(field)
            if s is not None and gate.get("verdict") != "human_review" and float(s) >= il.SUPPORT_MIN:
                proxy[cls]["n"] += 1
                proxy[cls]["right"] += int(bool(ok))
        labels = il.labels_for(row, d["fields"], gate, d["truth"])
        for field, lab in labels.items():
            counts[cls][field][lab["status"]] += 1
        if not labels:
            continue
        by_class[cls].append({
            "doc_id": doc, "doc_class": cls, "doc_subclass": row.get("expected_subclass"),
            "doc_sha256": il.doc_sha(row.get("doc_text")),
            "labels": labels,
            "source": {**d["source"], "gate_run": run["run_id"], "question_set": run["question_set"],
                       "verdict": gate.get("verdict"), "accept_probability": gate.get("accept_probability")},
        })
    # Reviewed labels (a committed review file) outrank the gate's: re-apply them on every build.
    review_entries = []
    for path in reviews or []:
        lines, problems = il.read_reviews(path)
        records = {r["doc_id"]: r for recs in by_class.values() for r in recs}
        new = [doc for doc in {line["doc_id"] for line in lines} if doc not in records]
        _, bad = il.apply_reviews(records, lines, _rel(path))
        if problems or bad:
            raise SystemExit("build refused: the review file does not apply:\n  " + "\n  ".join(problems + bad))
        for doc in sorted(new):
            by_class[records[doc]["doc_class"]].append(records[doc])
        for cls, recs in by_class.items():
            recs.sort(key=lambda r: r["doc_id"])
        review_entries.append(_review_entry(path, lines))
    counts = _label_counts(by_class)
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for cls, recs in sorted(by_class.items()):
        name = f"{cls}.jsonl"
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs)
        _replace(root / name, text)
        files[name] = il._sha(text)
    # Old class files are removed only once every replacement is in place (never a missing file).
    for old in root.glob("*.jsonl"):
        if old.name not in files:
            old.unlink()
    manifest = {
        "schema": il.SCHEMA,
        "status": "interim: unpublished enhancements to the mailroom-dataset ground truth; a Hub label supersedes the overlay field by field",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": "scripts/interim_labels.py build",
        "rules": {"support_min": il.SUPPORT_MIN, "null_support_min": il.NULL_SUPPORT_MIN,
                  "gap_fields": {k: list(v) for k, v in il.GAP_FIELDS.items() if v},
                  "truth_statuses": list(il.TRUTH_STATUSES)},
        "superseded_by": il.SUPERSEDED_BY,
        "sources": [{"gate_run": r["run_id"], "question_set": r["question_set"], "docs": len(r["docs"]),
                     "dataset_revision": r["dataset_revision"], "dataset_sha256": r["dataset_sha256"]} for r in runs],
        "documents": len(best),
        "admission_precision_proxy": {cls: {"n": c["n"], "right_rate": round(c["right"] / c["n"], 4) if c["n"] else None}
                                      for cls, c in sorted(proxy.items())},
        "counts": counts,
        "files": files,
    }
    if review_entries:
        manifest["reviews"] = review_entries
    _replace(root / "MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return manifest


def _rel(path: Path) -> str:
    """``path`` relative to the repository (how the manifest names a review file)."""
    from mailroom_sandbox.paths import repo_root

    try:
        return str(path.resolve().relative_to(repo_root().resolve()))
    except ValueError:
        return str(path)


def _repo_path(rel: str) -> Path:
    from mailroom_sandbox.paths import repo_root

    return repo_root() / rel


def _review_entry(path: Path, lines: list[dict[str, Any]]) -> dict[str, Any]:
    by = collections.Counter(f"{line['doc_class']}.{line['field']}:{line['status']}/{line['basis']}" for line in lines)
    return {"path": _rel(path), "sha256": il._sha(path.read_text(encoding="utf-8")), "lines": len(lines),
            "labels": dict(sorted(by.items()))}


def _label_counts(by_class: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, int]]]:
    counts: dict[str, dict[str, collections.Counter]] = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for cls, recs in by_class.items():
        for rec in recs:
            for field, lab in rec["labels"].items():
                counts[cls][field][lab["status"]] += 1
    return {cls: {f: dict(sorted(c.items())) for f, c in sorted(fs.items())} for cls, fs in sorted(counts.items())}


def review(root: Path, paths: list[Path]) -> int:
    """Apply review files to the committed overlay in place; no gate run needed.

    Each line replaces the label of its field (or adds one, and a record if the document has
    none). The manifest lists each file with its sha256, so ``check`` fails once a file changes
    without being re-applied, and ``build`` re-applies them after a rebuild.
    """
    integrity = il.verify(root, reviews=False)
    if integrity:
        print("review refused: the overlay fails its integrity check; rebuild with scripts/interim_labels.py build")
        for p in integrity:
            print(f"  {p}")
        return 1
    man = il.load_manifest(root)
    names = list(man.get("files") or {})
    by_name = {name: il._jsonl(root / name) for name in names}
    records = {r["doc_id"]: r for recs in by_name.values() for r in recs}
    entries, changed, problems = [], 0, []
    for path in paths:
        if not path.is_file():
            problems.append(f"{path}: not found")
            continue
        lines, bad = il.read_reviews(path)
        n, bad2 = il.apply_reviews(records, lines, _rel(path))
        problems += bad + bad2
        changed += n
        entries.append(_review_entry(path, lines))
    if problems:
        print("review refused:")
        for p in problems:
            print(f"  {p}")
        return 1
    by_class: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for rec in records.values():
        by_class[rec["doc_class"]].append(rec)
    texts = {f"{cls}.jsonl": "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                     for r in sorted(recs, key=lambda r: r["doc_id"]))
             for cls, recs in sorted(by_class.items())}
    unknown = sorted(set(texts) - set(names))
    if unknown:  # a review never creates a class file: the build owns which classes exist
        print(f"review refused: no overlay file for {', '.join(unknown)}")
        return 1
    for name, text in texts.items():
        man["files"][name] = il._sha(text)
    man["counts"] = _label_counts(by_class)
    man["reviews"] = entries
    if changed:
        man["reviewed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # As in rederive: keep the previous generation so a failed write restores every file.
    previous = {name: (root / name).read_bytes() for name in [*texts, "MANIFEST.json"]}
    try:
        for name, text in texts.items():
            _replace(root / name, text)
        _replace(root / "MANIFEST.json", json.dumps(man, indent=2) + "\n")
    except BaseException:
        for name, data in previous.items():
            (root / name).write_bytes(data)
        raise
    print(f"reviewed: {changed} labels added or changed from {len(paths)} file(s)")
    return 0


def _local_gate_runs() -> dict[str, str]:
    """Finished local gate runs and their question-set versions (empty without runtime data)."""
    from mailroom_sandbox.job.spec import run_dir

    base = run_dir("x").parent
    out = {}
    if not base.exists():
        return out
    for lock_path in sorted(base.glob("*/spec.lock.json")):
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            cp = json.loads((lock_path.parent / "checkpoint.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if lock.get("task") == "extraction_gate" and cp.get("state") == "done" and not (lock.get("job") or {}).get("mock", True):
            out[lock_path.parent.name] = str(((lock.get("reviewer") or {}).get("question_set") or {}).get("version") or "")
    return out


def rederive(root: Path) -> int:
    """Recompute every ``derived`` subclass label (``il.derived_value``) in place; no gate run needed.

    The other labels and their bases are unchanged. File hashes and counts are rewritten.
    """
    integrity = il.verify(root)
    if integrity:
        print("rederive refused: the overlay fails its integrity check; rebuild with scripts/interim_labels.py build")
        return 1
    man = il.load_manifest(root)
    changed = 0
    texts: dict[str, str] = {}
    for name in list(man.get("files") or {}):
        recs = il._jsonl(root / name)
        for rec in recs:
            field = il.SUBCLASS_FIELDS.get(rec.get("doc_class") or "")
            label = rec["labels"].get(field) if field else None
            if label and label.get("status") == "derived" and rec.get("doc_subclass"):
                value = il.derived_value(rec["doc_class"], rec["doc_subclass"])
                if label.get("value") != value:
                    label["value"] = value
                    changed += 1
        texts[name] = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs)
        man["files"][name] = il._sha(texts[name])
    # Keep the previous generation in memory: if any write fails (the manifest last), every
    # file is restored, so the overlay still passes its integrity check and a retry can run.
    previous = {name: (root / name).read_bytes() for name in [*texts, "MANIFEST.json"]}
    try:
        for name, text in texts.items():
            _replace(root / name, text)
        man["counts"] = _counts(root, man["files"])
        if changed:
            man["rederived_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _replace(root / "MANIFEST.json", json.dumps(man, indent=2) + "\n")
    except BaseException:
        for name, data in previous.items():
            (root / name).write_bytes(data)
        raise
    print(f"rederived {changed} labels")
    return 0


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """Hub rows from JSONL, or from a parquet shard (``ground_truth`` rows need no text)."""
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pylist()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def apply_parquet(root: Path, source: Path, out: Path) -> int:
    """Write ``source`` (a Hub ground_truth shard) with the overlay merged into ``out``."""
    problems = il.verify(root)
    if problems:
        print("apply refused: the overlay fails its check")
        for p in problems:
            print(f"  {p}")
        return 1
    try:
        table = il.apply_overlay_parquet(source, out, overlay=il.load_overlay(root),
                                         overlay_sha=il.overlay_fingerprint(root))
    except (OSError, ValueError) as exc:
        print(f"apply refused: {exc}")
        return 1
    marks = [m for m in table.column("interim_labels").to_pylist() if m]
    fields = sum(len(json.loads(m)["fields"]) for m in marks)
    print(f"applied: {fields} labels on {len(marks)} of {table.num_rows} rows -> {out}")
    return 0


def check(root: Path, rows_path: Path | None, prune: bool) -> int:
    integrity = il.verify(root)
    problems = list(integrity)
    man = il.load_manifest(root)
    listed = {s["gate_run"] for s in man.get("sources") or []}
    top = max((_version(s["question_set"]) for s in man.get("sources") or []), default=(0,))
    stale = [f"{run} (question set {v}) is not in the overlay; run: scripts/interim_labels.py build --add-run {run}"
             for run, v in _local_gate_runs().items() if run not in listed and _version(v) >= top]
    problems += stale
    if rows_path:
        rows = _read_rows(rows_path)
        overlay = il.load_overlay(root)
        gone, reviewed = [], []
        for doc, field in il.superseded(rows, overlay):
            labels = overlay[doc]["labels"]
            # A reviewed label belongs to its review file: prune never drops it (check would then
            # fail on the unapplied review line). The Hub wins over it anyway, and a record whose
            # text changed is skipped by its hash, so it is reported and kept.
            if field != "*" and "review" in labels[field]:
                reviewed.append(f"{doc}.{field}")
                continue
            if field == "*" and any("review" in lab for lab in labels.values()):
                reviewed.append(f"{doc} (text changed)")
                gone += [(doc, f) for f, lab in labels.items() if "review" not in lab]
                continue
            gone.append((doc, field))
        for note in reviewed:
            print(f"note: {note}: a reviewed label the Hub rows supersede is kept; drop its review line to retire it")
        for doc, field in gone:
            problems.append(f"{doc}.{field}: superseded by the Hub rows ({'text changed' if field == '*' else 'now labelled'})")
        if prune and gone and integrity:
            # Rewriting would re-hash files that already fail verification and hide the mismatch.
            print("prune refused: the overlay fails its integrity check; rebuild with scripts/interim_labels.py build")
        elif prune and gone:
            drop = collections.defaultdict(set)
            for doc, field in gone:
                drop[doc].add(field)
            for name in list(man.get("files") or {}):
                recs = []
                for rec in il._jsonl(root / name):
                    fields = drop.get(rec["doc_id"], set())
                    if "*" in fields:
                        continue
                    rec["labels"] = {f: v for f, v in rec["labels"].items() if f not in fields}
                    if rec["labels"]:
                        recs.append(rec)
                text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs)
                _replace(root / name, text)
                man["files"][name] = il._sha(text)
            man["counts"] = _counts(root, man["files"])
            man["pruned_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _replace(root / "MANIFEST.json", json.dumps(man, indent=2) + "\n")
            print(f"pruned {len(gone)} superseded labels")
            # The superseded labels are gone; integrity and staleness problems still fail the check.
            problems = [p for p in problems if "superseded by the Hub rows" not in p]
    for p in problems:
        print(p)
    print("interim labels: OK" if not problems else f"interim labels: {len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None, help="overlay directory (default data/labels/interim)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="(re)build the overlay from gate runs")
    b.add_argument("--run", action="append", default=[], help="gate run (replaces the manifest's list; repeat)")
    b.add_argument("--add-run", action="append", default=[], help="gate run added to the manifest's list")
    c = sub.add_parser("check", help="integrity, staleness and Hub supersession")
    c.add_argument("--rows", type=Path, help="Hub rows (JSONL, or a ground_truth .parquet shard) to test for superseded labels")
    c.add_argument("--prune", action="store_true", help="drop superseded labels and rewrite the manifest")
    sub.add_parser("rederive", help="recompute the derived subclass labels with the current mapping")
    r = sub.add_parser("review", help="apply review files (reviewed corrections and header fills) in place")
    r.add_argument("--apply", action="append", type=Path, default=[],
                   help="review file (repeat); default: the manifest's list, else data/labels/review/interim_reviews.jsonl")
    a = sub.add_parser("apply", help="write a Hub ground_truth parquet shard with the overlay merged into gt_fields")
    a.add_argument("--parquet", type=Path, required=True, help="Hub ground_truth shard")
    a.add_argument("--out", type=Path, required=True, help="output parquet (not the source)")
    args = ap.parse_args(argv)
    root = args.root or il.overlay_dir()
    if args.cmd == "apply":
        return apply_parquet(root, args.parquet, args.out)
    if args.cmd == "rederive":
        return rederive(root)
    listed = [_repo_path(e["path"]) for e in il.load_manifest(root).get("reviews") or []]
    if args.cmd == "review":
        return review(root, args.apply or listed or [il.review_path()])
    if args.cmd == "build":
        runs = args.run or [s["gate_run"] for s in il.load_manifest(root).get("sources") or []]
        runs += [r for r in args.add_run if r not in runs]
        if not runs:
            raise SystemExit("no gate runs: pass --run")
        man = build(runs, root, listed)
        print(json.dumps({k: man[k] for k in ("documents", "admission_precision_proxy", "counts", "files")}, indent=1))
        return 0
    return check(root, args.rows, args.prune)


if __name__ == "__main__":
    raise SystemExit(main())
