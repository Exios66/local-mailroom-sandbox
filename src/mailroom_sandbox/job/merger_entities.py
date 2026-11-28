"""Offline merger entity check: per-field accuracy of a finished run's merger entities against labels.

No model call and nothing written to the run. For every finished merger document the run stored
(``items.jsonl``), the entity fields (``gold_labels.target_fields("merger_agreement")``) are scored
against interim, near-gold or gold labels through the suite scorer itself
(``eval.scoring.score_extraction_row(..., field_scores=True)``), never a local comparison. The check
is reported next to MAUD accuracy and is never the headline score.

* A field with no labels reads ``unlabelled``, never 0.
* A label is bound to the text it was read from (``doc_sha256``): a document whose text changed since
  labelling is not scored (``counts.stale_labels``).
* Near-gold numbers are ``verified: false`` until a human spot check of that label file is recorded
  in its directory's ``MANIFEST.json`` (:func:`spot_sample`, :func:`record_spot_check`). A spot check
  under :data:`CITE_FLOOR` agreement sets ``cite_blocked``: do not cite those numbers.
* With a baseline run, per-field deltas use only documents finished and labelled in both runs.

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md (part 7).
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from mailroom_sandbox import gold_labels, interim_labels

LABEL = "offline entity check (not the headline)"
DOC_CLASS = "merger_agreement"
CITE_FLOOR = 0.90  # a spot check under this agreement blocks citing the near-gold numbers
FIELDS: tuple[str, ...] = gold_labels.target_fields(DOC_CLASS)
SOURCES = ("interim", "near_gold", "gold")  # weakest first; a label of a stronger source wins
SHEET_COLUMNS = ("doc_id", "field", "value", "evidence", "labels_sha256", "correct")
_YES = frozenset({"y", "yes", "true", "1", "correct"})
_NO = frozenset({"n", "no", "false", "0", "wrong"})


class EntityCheckError(RuntimeError):
    """A check that cannot give trustworthy numbers; nothing was written."""


# --------------------------------------------------------------------------- labels

def _source(label: Mapping[str, Any]) -> str | None:
    basis = str(label.get("basis") or "")
    if basis.startswith("near_gold:"):
        return "near_gold"
    if basis == "gold" or basis.startswith("gold:") or label.get("status") == "gold":
        return "gold"
    return "interim" if label.get("use_as_truth") is True else None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    manifest = path.parent / "MANIFEST.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EntityCheckError(f"label file missing: {path}")
    with path.open(encoding="utf-8", newline="\n") as handle:
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


def load_labels(paths: Path | str | Sequence[Path | str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """``({doc_id: {"sha", "fields": {field: {"value", "source", "file"}}}}, files)`` for merger labels.

    A label counts when it is near-gold (``basis`` ``near_gold:``), gold, or an interim label marked
    ``use_as_truth``; for one document and field a gold label beats near-gold, which beats interim.
    ``files`` maps each file's resolved path to its digest and its current spot-check entry (or ``None``):
    two files of one name in different directories keep their own spot checks (final review F8).
    """
    paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
    docs: dict[str, dict[str, Any]] = {}
    files: dict[str, Any] = {}
    for raw in paths:
        path = Path(raw)
        records = _read_records(path)
        digest = _sha(path)
        key = str(path.resolve())
        entry = (_manifest(path).get("spot_check") or {}).get(path.name)
        files[key] = {"sha256": digest,
                      "spot_check": entry if (entry or {}).get("labels_sha256") == digest else None}
        for rec in records:
            if rec.get("doc_class") != DOC_CLASS:
                continue
            doc = docs.setdefault(str(rec.get("doc_id")), {"sha": None, "fields": {}})
            accepted = False
            for name, label in (rec.get("labels") or {}).items():
                if name not in FIELDS or not isinstance(label, Mapping):
                    continue
                source = _source(label)
                held = doc["fields"].get(name)
                if source is None or (held and SOURCES.index(held["source"]) >= SOURCES.index(source)):
                    continue
                doc["fields"][name] = {"value": label.get("value"), "source": source, "file": key,
                                       "evidence": label.get("evidence") or label.get("support")}
                accepted = True
            # The text check follows the record that supplied the winning fields, not the first
            # file that mentioned the document.
            if accepted:
                doc["sha"] = rec.get("doc_sha256")
    return docs, files


# --------------------------------------------------------------------------- runs

def _load_run(run: str | Path, runs_root: Path | None) -> tuple[str, dict[str, dict[str, Any]], bool]:
    from mailroom_sandbox import rescore
    from mailroom_sandbox.job import attempt_replay
    from mailroom_sandbox.job.pair_report import load_arm

    try:
        files = rescore.locate(run, runs_root=runs_root)
        lock = rescore._finished_lock(files, force=False)  # a running checkpoint is refused
        verified = attempt_replay._verify_dataset(files.path, lock)
        if lock.get("task") not in (None, "pipeline"):
            raise EntityCheckError(f"task {lock.get('task')!r} runs no extraction: nothing to check")
        arm = load_arm(files.path)
    except EntityCheckError:
        raise
    except (FileNotFoundError, RuntimeError) as exc:
        raise EntityCheckError(str(exc).replace("re-score a finished run (or --force)", "check a finished run")) from exc
    return str(lock.get("run_id") or files.path.name), arm, verified


def _score_doc(row: Mapping[str, Any], pred: Mapping[str, Any], labels: Mapping[str, Any]) -> dict[str, float]:
    from mailroom_sandbox.eval import scoring

    expected = {f: lab["value"] for f, lab in labels.items() if lab["value"] is not None}
    if not expected:
        return {}
    out = scoring.score_extraction_row(DOC_CLASS, dict(pred.get("extracted_data") or {}), expected,
                                       row.get("doc_text"), field_scores=True)
    return {f: float(v) for f, v in (out.get("field_scores") or {}).items() if f in expected}


def _maud(row: Mapping[str, Any], pred: Mapping[str, Any]) -> float | None:
    from mailroom_sandbox.job.pair_report import _score

    return _score(row, pred)


def _scored(arm: Mapping[str, Any], labels: Mapping[str, Any], counts: Counter[str]) -> dict[str, dict[str, Any]]:
    """``{doc_id: {"fields": {field: score}, "maud": float | None}}`` for finished, labelled mergers."""
    from mailroom_sandbox.job.pair_report import _failed

    out: dict[str, dict[str, Any]] = {}
    for doc_id, entry in sorted(arm.items()):
        row, item = entry["row"], entry["item"] or {}
        if str(row.get("expected_doc_class") or "") != DOC_CLASS:
            continue
        counts["mergers"] += 1
        pred = item.get("pred")
        if not isinstance(pred, Mapping) or not isinstance(pred.get("extracted_data"), Mapping):
            counts["no_pred"] += 1
            continue
        if _failed(item):
            counts["failed"] += 1  # SHF-011 scores it 0 whatever it extracted: no entity evidence
            continue
        doc_labels = labels.get(doc_id)
        if doc_labels and doc_labels["sha"] != interim_labels.doc_sha(row.get("doc_text")):
            counts["stale_labels"] += 1
            doc_labels = None
        fields = doc_labels["fields"] if doc_labels else {}
        nulls = [f for f, lab in fields.items() if lab["value"] is None]
        filled = sorted(f for f in nulls if _filled(pred["extracted_data"].get(f)))
        counts["null_labels"] += len(nulls)
        counts["filled_on_null"] += len(filled)
        out[doc_id] = {"fields": _score_doc(row, pred, fields), "maud": _maud(row, pred), "filled_on_null": filled}
    return out


def _filled(value: Any) -> bool:
    """A read that names something: not ``None``, an empty or blank string, or an empty list or object."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return value is not None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _field_block(scored: Mapping[str, Any], labels: Mapping[str, Any], files: Mapping[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for name in FIELDS:
        hits = [(d, s["fields"][name]) for d, s in scored.items() if name in s["fields"]]
        filled = sum(1 for s in scored.values() if name in s.get("filled_on_null", ()))
        if not hits:
            block[name] = {"accuracy": None, "n": 0, "source": None, "status": "unlabelled", "verified": None,
                           "filled_on_null": filled}
            continue
        used = [labels[d]["fields"][name] for d, _ in hits]
        near = {lab["file"] for lab in used if lab["source"] == "near_gold"}
        checks = [files[f]["spot_check"] for f in near]
        block[name] = {"accuracy": _mean([v for _, v in hits]), "n": len(hits),
                       "source": min((lab["source"] for lab in used), key=SOURCES.index), "status": "scored",
                       "verified": (all(c is not None and not c.get("cite_blocked") for c in checks)
                                    if near else None),
                       "filled_on_null": filled}
    return block


def _spot_block(files: Mapping[str, Any], labels: Mapping[str, Any]) -> dict[str, Any] | None:
    near = {lab["file"] for doc in labels.values() for lab in doc["fields"].values() if lab["source"] == "near_gold"}
    recorded = {f: files[f]["spot_check"] for f in sorted(near) if files[f]["spot_check"] is not None}
    if not recorded:
        return None
    return {"agreement": min(e["agreement"] for e in recorded.values()),
            "n_fields": sum(int(e.get("n_fields") or 0) for e in recorded.values()),
            "cite_blocked": any(e.get("cite_blocked") for e in recorded.values()) or len(recorded) < len(near),
            "unrecorded": sorted(near - set(recorded)), "files": recorded}


def _paired(run: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    both = sorted(set(run) & set(base))
    fields: dict[str, Any] = {}
    for name in FIELDS:
        docs = [d for d in both if name in run[d]["fields"] and name in base[d]["fields"]]
        a, b = _mean([run[d]["fields"][name] for d in docs]), _mean([base[d]["fields"][name] for d in docs])
        fields[name] = {"n": len(docs), "run": a, "baseline": b,
                        "delta": round(a - b, 4) if a is not None and b is not None else None}
    maud = {side: _mean([v for d in both if (v := arm[d]["maud"]) is not None])
            for side, arm in (("run", run), ("baseline", base))}
    return {"n_docs": len(both), "fields": fields, "maud_accuracy": maud}


def check(run: str | Path, labels: Path | str | Sequence[Path | str], *, baseline: str | Path | None = None,
          runs_root: Path | None = None) -> dict[str, Any]:
    """Score one finished run's merger entities against ``labels`` (and pair it with ``baseline``)."""
    doc_labels, files = load_labels(labels)
    run_id, arm, verified = _load_run(run, runs_root)
    counts: Counter[str] = Counter()
    scored = _scored(arm, doc_labels, counts)
    result: dict[str, Any] = {
        "label": LABEL,
        "run_id": run_id,
        "counts": {"items": len(arm), "scored_docs": len(scored), "dataset_verified": verified,
                   **{k: counts[k] for k in ("mergers", "no_pred", "failed", "stale_labels", "null_labels",
                                                  "filled_on_null")}},
        "label_files": {name: {"sha256": f["sha256"], "spot_check": f["spot_check"]} for name, f in files.items()},
        "fields": _field_block(scored, doc_labels, files),
        "spot_check": _spot_block(files, doc_labels),
        "maud_accuracy": _mean([v for s in scored.values() if (v := s["maud"]) is not None]),
        "paired": None,
    }
    if baseline is not None:
        base_id, base_arm, _ = _load_run(baseline, runs_root)
        result["baseline_id"] = base_id
        result["paired"] = _paired(scored, _scored(base_arm, doc_labels, Counter()))
    return result


def default_output(run_id: str, *, runs_root: Path | None = None) -> Path:
    """Where the script writes a check by default: beside the run store, never inside a run."""
    if runs_root is None:
        from mailroom_sandbox.job.spec import runs_root as _root

        runs_root = _root()
    return Path(runs_root).parent / "entity_checks" / f"{run_id}.merger_entities.json"


def write_check(result: Mapping[str, Any], path: Path | str, *,
                source: Path | str | Sequence[Path | str] | None = None) -> Path:
    """Write the result; refuse a path inside any ``source`` run directory (the run and its baseline)."""
    out = Path(path)
    sources = [] if source is None else [source] if isinstance(source, (str, Path)) else list(source)
    target = out.resolve()
    for src in sources:
        run_dir = Path(src).resolve()
        if target == run_dir or run_dir in target.parents:
            raise EntityCheckError(f"{out} is inside the source run {run_dir}; the check never writes the run")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def digest(result: Mapping[str, Any], path: Path | str | None = None) -> str:
    """A short text summary: counts, the spot check, one line per field, MAUD and the paired deltas."""
    c = result["counts"]
    head = f"{result['label']}: run {result['run_id']}"
    if result.get("baseline_id"):
        head += f" vs baseline {result['baseline_id']}"
    lines = [head, f"mergers {c['mergers']}, scored {c['scored_docs']}, failed {c['failed']}, "
                   f"stale labels {c['stale_labels']}, null labels (not scored) {c['null_labels']}, "
                   f"filled where the label is null {c['filled_on_null']}, "
                   f"dataset digest {'checked' if c['dataset_verified'] else 'not in the lock'}"]
    spot = result["spot_check"]
    if spot is None:
        lines.append("near-gold: unverified (no spot check recorded)")
    elif spot["cite_blocked"]:
        lines.append(f"near-gold spot check agreement {spot['agreement']} (floor {CITE_FLOOR}"
                     f"{', unrecorded files ' + ', '.join(spot['unrecorded']) if spot['unrecorded'] else ''}): "
                     "do not cite near-gold numbers")
    else:
        lines.append(f"near-gold spot check agreement {spot['agreement']} over {spot['n_fields']} fields")
    for name, f in result["fields"].items():
        if f["status"] == "unlabelled":
            lines.append(f"  {name}: unlabelled")
            continue
        mark = {None: "", True: ", verified", False: ", unverified"}[f["verified"]]
        lines.append(f"  {name}: accuracy {f['accuracy']} (n {f['n']}, {f['source']}{mark})")
    lines.append(f"MAUD on finished mergers (not the gate's headline): {result['maud_accuracy']}")
    pair = result.get("paired")
    if pair:
        lines.append(f"paired over {pair['n_docs']} documents: MAUD {pair['maud_accuracy']['baseline']} -> "
                     f"{pair['maud_accuracy']['run']}")
        for name, f in pair["fields"].items():
            if f["n"]:
                lines.append(f"  {name}: {f['baseline']} -> {f['run']} (delta {f['delta']}, n {f['n']})")
    if path is not None:
        lines.append(f"full result: {path}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- spot check

def default_sheet_dir() -> Path:
    from mailroom_sandbox.job.spec import runs_root as _root

    return Path(_root()).parent / "merger_spot_check"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)


def _evidence(value: Any) -> str:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    return " | ".join(_text(e.get("quote", e)) if isinstance(e, Mapping) else _text(e) for e in items)


def spot_sample(labels: Path | str, *, n: int = 5, seed: int, out_dir: Path | str | None = None) -> Path:
    """Write a review sheet: every near-gold field of ``n`` seeded documents, ``correct`` left blank."""
    path = Path(labels)
    docs, files = load_labels(path)
    near = {d: {f: lab for f, lab in doc["fields"].items() if lab["source"] == "near_gold"}
            for d, doc in docs.items()}
    pool = sorted(d for d, fields in near.items() if fields)
    if not pool:
        raise EntityCheckError(f"{path}: no near-gold merger labels to spot-check")
    chosen = sorted(random.Random(seed).sample(pool, min(n, len(pool))))
    out = Path(out_dir) if out_dir is not None else default_sheet_dir()
    out.mkdir(parents=True, exist_ok=True)
    sheet = out / f"{path.stem}.seed{seed}.n{n}.csv"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        for doc_id in chosen:
            for name in FIELDS:
                if name in near[doc_id]:
                    lab = near[doc_id][name]
                    writer.writerow({"doc_id": doc_id, "field": name, "value": _text(lab["value"]),
                                     "evidence": _evidence(lab["evidence"]),
                                     "labels_sha256": files[str(path.resolve())]["sha256"], "correct": ""})
    return sheet


def record_spot_check(sheet: Path | str, labels: Path | str) -> dict[str, Any]:
    """Write the sheet's agreement into the label directory's ``MANIFEST.json``; under 0.90 blocks citing."""
    sheet, path = Path(sheet), Path(labels)
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise EntityCheckError(f"{sheet}: empty sheet")
    digest_now = _sha(path)
    if any(r.get("labels_sha256") != digest_now for r in rows):
        raise EntityCheckError(f"{sheet} was drawn from another version of {path.name}; draw a new sample")
    marks = [str(r.get("correct") or "").strip().lower() for r in rows]
    unmarked = sum(1 for m in marks if m not in _YES | _NO)
    if unmarked:
        raise EntityCheckError(f"{sheet}: {unmarked} unmarked rows (mark correct y or n)")
    agreement = round(sum(1 for m in marks if m in _YES) / len(marks), 4)
    manifest_path = path.parent / "MANIFEST.json"
    if not manifest_path.is_file():
        raise EntityCheckError(f"{path.parent}: no MANIFEST.json to record the spot check in")
    entry = {"agreement": agreement, "n_fields": len(rows), "n_docs": len({r["doc_id"] for r in rows}),
             "cite_blocked": agreement < CITE_FLOOR, "labels_sha256": digest_now, "sheet": sheet.name,
             "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("spot_check", {})[path.name] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return entry
