#!/usr/bin/env python3
"""Stage the merged label repairs as a production-scoring overlay in mailroom-issues ``mailroom_cache``.

Inputs, all on mailroom-dataset v9.3 (Hub ``ff4ca546``):

- ``--builder-dir``: the output of ``build_label_repaired.py`` (sandbox PR #384): the wide label
  CSV, its per-cell ``label_provenance`` CSV, ``field_completeness`` CSV and ``summary`` JSON.
- ``--assist``: an earlier repaired CSV that kept different labels (the full clause phrase for
  ``termination_notice_period``). It only adds evidence-backed terms; it never removes one.
- ``--corpus``: the pinned Hub ``ground_truth`` rows (``sandbox datasets pull``) for grounding.

Join rules (per cell where the two CSVs differ):

- builder value only: keep it (the builder's guards admitted it).
- ``termination_notice_period``: compare notice terms (operator, magnitude, unit, qualifier).
  A term only the assist value carries is added when it reads as a notice period (an operator,
  or notice / prior / before / advance words around it), is not a cure or breach period, has
  no magnitude the builder already holds, and its phrase occurs verbatim in the document text.
  An assist value with no admissible term goes to the review queue.
- any other field, and duplicate links: keep the builder value and queue the assist value.

Outputs, under ``<out>/v9.3.0/pre-release/v<version>/`` (immutable once written):

- ``master/``: the joined wide CSV, provenance, completeness and summary (with join counts);
- ``overlay/<class>.jsonl``: per document, every label that differs from the Hub v9.3 label
  (``override: true`` when it replaces a populated Hub value): the file deployments pull and
  overlay for production scoring;
- ``queues/needs_human.csv`` (unresolved disputes plus queued join cells) and
  ``queues/gold_override_signoff.csv`` (Hub overrides, ``decided_by`` left blank).

    python scripts/stage_label_overlay.py --version 9.3.1-rc.2 \\
        --builder-dir reports/datasets/mailroom-dataset-v9.3-label-repaired \\
        --assist mailroom_dataset_v9.3_label_repaired_copy.csv \\
        --corpus data/cache/Lucius-Morningstar__mailroom-dataset__ff4ca546d434/ground_truth_all.jsonl
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("export_mailroom_cache", HERE / "export_mailroom_cache.py")
emc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emc)

CacheError = emc.CacheError
STEM = "mailroom_dataset_v9.3_label_repaired"
BUILDER_FILES = {"labels": f"{STEM}.csv", "provenance": f"{STEM}_label_provenance.csv",
                 "completeness": f"{STEM}_field_completeness.csv", "summary": f"{STEM}_summary.json"}
NOTICE = "termination_notice_period"
#: per-document bookkeeping columns: recomputed, never joined
META_COLUMNS = {"fields_targeted", "fields_labeled", "label_completeness", "fields_with_conflict",
                "fields_needs_human"}
LABELED = ("populated", "documented_absence")
ASSIST_SOURCE = "assist_upload"
HUB = "hub_v9.3"
QUEUE_COLUMNS = ("document_id", "doc_class", "field", "reason", "builder_value", "assist_value")
SIGNOFF_COLUMNS = ("document_id", "doc_class", "field", "hub_v9_3_value", "staged_value", "chosen_source",
                   "evidence", "decided_by", "decided_utc")

# Same period grammar as build_label_repaired.py (PERIOD_RX / _notice_terms), so terms compare alike.
PERIOD_RX = re.compile(r"((?:(?:at\s+least|at\s+most|not\s+less\s+than|no\s+less\s+than|not\s+more\s+than|"
                       r"no\s+more\s+than|no\s+later\s+than|a\s+minimum\s+of|a\s+maximum\s+of)\s+)?"
                       r"(?:[a-z\-]+\s+)?\(?\d+\)?\s*(?:calendar\s+|business\s+|working\s+)?"
                       r"(?:days?|months?|years?))\b", re.I)
_NOTICE_AFTER = re.compile(r"^['’]?s?\s*(?:advance|prior|written|notice|notification|before|in\s+advance)\b", re.I)
_NOTICE_BEFORE = re.compile(r"(?:notice|notif\w*|upon|on|giving|providing|given)\s*$", re.I)
_CURE = re.compile(r"\b(?:cure[ds]?|curing|breach\w*|default\w*)\b", re.I)
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())} | {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                                                    "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_DIGITS = re.compile(r"\b([a-z]+(?:-[a-z]+)?)\s+\(?(\d+)\)?\s*(?:calendar\s+|business\s+|working\s+)?(?:days?|months?|years?)\b", re.I)
#: refusals a person should look at; a refused term length next to a builder value is not one
REVIEW_REFUSALS = ("garbled magnitude", "cure or breach period", "not in document text")


def garbled(phrase: str) -> bool:
    """A number word that contradicts its digits ("sixty 90 days"); "eighty (180)" is a cut-off
    "one hundred eighty", so a word smaller than the digits only when they are unbracketed."""
    m = _WORD_DIGITS.search(phrase)
    parts = m.group(1).lower().split("-") if m else []
    if not parts or not all(w in _NUMBER_WORDS for w in parts):
        return False
    word, digits = sum(_NUMBER_WORDS[w] for w in parts), int(m.group(2))  # "forty-five" -> 45
    return word != digits and not (f"({m.group(2)})" in phrase and digits % 100 == word)


def notice_term(phrase: str) -> tuple[str, str, str, str]:
    p = phrase.lower()
    op = "exact"
    if re.search(r"at least|(?:not|no) less than|minimum", p):
        op = "minimum"
    elif re.search(r"at most|(?:not|no) more than|maximum|no later than", p):
        op = "maximum"
    qual = re.search(r"\b(business|calendar|working)\b", p)
    return (op, re.search(r"\d+", p).group(), re.search(r"(day|month|year)s?\b", p).group(1),
            qual.group() if qual else "")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def assist_notice_terms(assist: str, builder: str, doc_text: str) -> tuple[list[str], list[str]]:
    """Admissible extra notice phrases from ``assist`` and the reasons the rest were refused."""
    held = {(t[1], t[2]) for t in map(notice_term, (m.group() for m in PERIOD_RX.finditer(builder)))}
    text = _norm(doc_text)
    out, refused = [], []
    for segment in assist.split(";"):
        for m in PERIOD_RX.finditer(segment):
            phrase = m.group(1).strip(" ,")
            term = notice_term(phrase)
            if (term[1], term[2]) in held:
                continue
            after, before = segment[m.end():m.end() + 30], segment[max(0, m.start() - 25):m.start()]
            if garbled(phrase):
                refused.append(f"garbled magnitude: {phrase}")
            elif _CURE.search(segment):
                refused.append(f"cure or breach period: {phrase}")
            elif not (term[0] != "exact" or _NOTICE_AFTER.search(after) or _NOTICE_BEFORE.search(before)):
                refused.append(f"not a notice period: {phrase}")
            elif _norm(phrase) not in text:
                refused.append(f"not in document text: {phrase}")
            else:
                held.add((term[1], term[2]))
                out.append(phrase)
    return out, refused


def _evidence(doc_text: str, phrase: str) -> dict[str, Any] | None:
    m = re.search(r"\s+".join(map(re.escape, phrase.split())), doc_text, re.I)
    return {"start": m.start(), "end": m.end(), "text": doc_text[m.start():m.end()], "source": ASSIST_SOURCE} if m else None


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _csv_text(columns: Iterable[str], rows: Iterable[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _jsonish(value: str) -> Any:
    if value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def completeness_table(prov: list[dict[str, str]], base: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Recompute the builder's per-field completeness from provenance (Hub columns carried over)."""
    cells = collections.defaultdict(list)
    for r in prov:
        cells[(r["doc_class"], r["field"])].append(r)
    out = []
    for b in base:
        rs = cells[(b["doc_class"], b["field"])]
        n = int(b["documents"])
        count = collections.Counter(r["presence"] for r in rs)
        labeled = count["populated"] + count["documented_absence"]
        tops = collections.Counter(r["chosen_source"] for r in rs if r["presence"] in LABELED)
        row = dict(b)
        row.update(labeled_repaired=labeled, populated=count["populated"],
                   documented_absence=count["documented_absence"], unlabeled=count["unlabeled"],
                   disputed_unresolved=count["disputed_unresolved"],
                   completeness_repaired=round(labeled / n, 4) if n else 0.0,
                   conflicts=sum(r["conflict"] == "True" for r in rs),
                   needs_human=sum(r["needs_human"] == "True" for r in rs),
                   top_source=min(tops, key=lambda s: (-tops[s], s)) if tops else "")
        out.append(row)
    return out


def join(builder: dict[str, Any], assist_rows: list[dict[str, str]], texts: dict[str, str]) -> dict[str, Any]:
    """Join the assist CSV into the builder output. Pure: returns new tables and the counts."""
    columns, rows = builder["labels"]
    by_id = {r["document_id"]: dict(r) for r in rows}
    assist = {r["document_id"]: r for r in assist_rows}
    if set(assist) != set(by_id):
        raise CacheError("the assist CSV and the builder CSV do not hold the same documents")
    pcols, prov = builder["provenance"]
    prov = [dict(r) for r in prov]
    pindex = {(r["document_id"], r["field"]): r for r in prov}
    counts: collections.Counter[str] = collections.Counter()
    queue: list[dict[str, str]] = []
    filled_docs: collections.Counter[str] = collections.Counter()
    for doc_id, row in by_id.items():
        a = assist[doc_id]
        for col in columns:
            if col in META_COLUMNS or a.get(col, "") == row[col]:
                continue
            b_val, a_val = row[col], a.get(col, "")
            base = {"document_id": doc_id, "doc_class": row["doc_class"], "field": col,
                    "builder_value": b_val, "assist_value": a_val}
            if not a_val:
                counts["kept_builder_only"] += 1
                continue
            if col == "duplicate_of":
                counts["kept_builder_duplicate_keeper"] += 1  # the builder's keepers are reviewed
                continue
            if col != NOTICE:
                counts["queued_other_field"] += 1
                queue.append({**base, "reason": "assist value differs; builder kept"})
                continue
            extra, refused = assist_notice_terms(a_val, b_val, texts.get(doc_id, ""))
            review = [r for r in refused if r.startswith(REVIEW_REFUSALS)]
            if not b_val and not extra:
                review = refused or ["no notice term found"]
            counts["notice_refused_terms"] += len(refused)
            if not extra:
                if review:
                    counts["queued_notice"] += 1
                    queue.append({**base, "reason": "; ".join(review)})
                else:
                    counts["notice_same_terms"] += 1
                continue
            cell = pindex.get((doc_id, col))
            if cell is None:
                raise CacheError(f"{doc_id}.{col}: no provenance row")
            new = "; ".join([b_val, *extra]) if b_val else "; ".join(extra)
            filled = cell["presence"] not in LABELED
            votes = json.loads(cell["votes"] or "{}")
            votes[ASSIST_SOURCE] = a_val
            evidence = json.loads(cell["evidence"] or "[]") + [e for e in (_evidence(texts[doc_id], p) for p in extra) if e]
            cell.update(value=new, presence="populated", votes=json.dumps(votes, sort_keys=True),
                        evidence=json.dumps(evidence), rule="assist_join",
                        chosen_source=ASSIST_SOURCE if filled else cell["chosen_source"],
                        agreeing_sources=ASSIST_SOURCE if filled else f"{cell['agreeing_sources']}|{ASSIST_SOURCE}")
            row[col] = new
            counts["notice_filled" if filled else "notice_terms_added"] += 1
            filled_docs[doc_id] += filled
            counts["notice_terms_total"] += len(extra)
            if review:
                queue.append({**base, "reason": "partly joined; refused " + "; ".join(review)})
    # Per-document bookkeeping: only a newly filled cell changes the builder's own counts.
    for doc_id, n in filled_docs.items():
        row = by_id[doc_id]
        targeted, labeled = int(row["fields_targeted"] or 0), int(row["fields_labeled"] or 0) + n
        row["fields_labeled"] = str(labeled)
        row["label_completeness"] = str(round(labeled / targeted, 4)) if targeted else row["label_completeness"]
    _, comp = builder["completeness"]
    return {"labels": (columns, [by_id[r["document_id"]] for r in rows]), "provenance": (pcols, prov),
            "completeness": completeness_table(prov, comp), "queue": queue, "counts": dict(sorted(counts.items()))}


def overlay_records(prov: list[dict[str, str]], shas: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Per class, the labels that differ from Hub v9.3 (the production overlay)."""
    docs: dict[str, dict[str, Any]] = {}
    for r in prov:
        if r["presence"] not in LABELED:
            continue
        if from_hub(r):
            continue
        hub = json.loads(r["votes"] or "{}").get("hub_v9.3")
        rec = docs.setdefault(r["document_id"], {"doc_id": r["document_id"], "doc_class": r["doc_class"],
                                                 "content_sha256": shas.get(r["document_id"], ""), "labels": {}})
        rec["labels"][r["field"]] = {
            "value": _jsonish(r["value"]) if r["presence"] == "populated" else None,
            "presence": r["presence"], "source": r["chosen_source"], "agreement": r["agreement"],
            "override": hub is not None, "evidence": json.loads(r["evidence"] or "[]"),
        }
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for doc_id in sorted(docs):
        out[docs[doc_id]["doc_class"]].append(docs[doc_id])
    return dict(sorted(out.items()))


def from_hub(cell: dict[str, str]) -> bool:
    """The Hub v9.3 label already holds this value (the builder's field-aware vote grouped them)."""
    return HUB in cell["agreeing_sources"].split("|")


def is_override(cell: dict[str, str]) -> bool:
    """The staged label replaces a value the Hub v9.3 labels hold."""
    return not from_hub(cell) and HUB in json.loads(cell["votes"] or "{}")


def signoff_rows(prov: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for r in prov:
        if r["presence"] in LABELED and is_override(r):
            hub = json.loads(r["votes"])[HUB]
            out.append({"document_id": r["document_id"], "doc_class": r["doc_class"], "field": r["field"],
                        "hub_v9_3_value": hub, "staged_value": r["value"], "chosen_source": r["chosen_source"],
                        "evidence": r["evidence"], "decided_by": "", "decided_utc": ""})
    return out


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(out: Path, version: str, builder_dir: Path, assist: Path, corpus: Path, *, builder_commit: str) -> dict[str, Any]:
    major, minor, _p, _pre = emc.parse_version(version)
    version = version.removeprefix("v")
    rel = Path(f"v{major}.{minor}.0") / "pre-release" / f"v{version}"
    builder = {}
    for key, name in BUILDER_FILES.items():
        path = builder_dir / name
        if not path.exists():
            raise CacheError(f"missing builder output {path}")
        builder[key] = json.loads(path.read_text()) if key == "summary" else _read_csv(path)
    summary = builder["summary"]
    if summary.get("revision") != emc.FAMILY_HF_REVISION:
        raise CacheError(f"builder output is on {summary.get('revision')}, not {emc.FAMILY_HF_REVISION}")
    texts, shas = {}, {}
    with corpus.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            texts[row["id"]], shas[row["id"]] = row["doc_text"], row["content_sha256"]
    corpus_sha = _sha_bytes(corpus)
    want = summary.get("inputs_sha256", {})
    pinned = next((v for k, v in want.items() if k.endswith("ground_truth_all.jsonl")), None)
    if pinned and pinned != corpus_sha:
        raise CacheError(f"corpus sha256 {corpus_sha[:12]} is not the one the builder read ({pinned[:12]})")
    # The recompute must reproduce the builder's own table before anything is joined.
    _, comp = builder["completeness"]
    again = completeness_table(builder["provenance"][1], comp)
    if _csv_text(comp[0].keys(), comp) != _csv_text(comp[0].keys(), again):
        raise CacheError("completeness recompute does not reproduce the builder's table; refusing to join")
    _, assist_rows = _read_csv(assist)
    joined = join(builder, assist_rows, texts)
    columns, rows = joined["labels"]
    pcols, prov = joined["provenance"]
    disputed = [{"document_id": r["document_id"], "doc_class": r["doc_class"], "field": r["field"],
                 "reason": "disputed_unresolved", "builder_value": r["value"], "assist_value": ""}
                for r in prov if r["needs_human"] == "True"]
    queue = disputed + joined["queue"]
    signoff = signoff_rows(prov)
    overlay = overlay_records(prov, shas)
    targeted = sum(1 for r in prov)
    labeled = sum(r["presence"] in LABELED for r in prov)

    target = out / rel
    # Reuse a commit this cut, or another cut, already recorded for the same labels tree.
    manifests = [target / "MANIFEST.json", *sorted(out.glob("v*/pre-release/*/MANIFEST.json"), reverse=True)]
    recorded = next((json.loads(m.read_text())["source"]["labels_commit"] for m in manifests
                     if m.exists() and emc._labels_tree(json.loads(m.read_text())["source"]["labels_commit"])
                     == emc._labels_tree("HEAD")), None)
    labels_commit = emc.labels_commit(prefer=recorded)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "stage"
        (dest / "master").mkdir(parents=True)
        (dest / "overlay").mkdir()
        (dest / "queues").mkdir()
        name = f"mailroom_dataset_v{version}"
        (dest / "master" / f"{name}_labels.csv").write_text(_csv_text(columns, rows), encoding="utf-8")
        (dest / "master" / f"{name}_label_provenance.csv").write_text(_csv_text(pcols, prov), encoding="utf-8")
        comp_rows = joined["completeness"]
        (dest / "master" / f"{name}_field_completeness.csv").write_text(_csv_text(comp_rows[0].keys(), comp_rows),
                                                                         encoding="utf-8")
        new_summary = dict(summary, label_cells_labeled_repaired=labeled,
                           label_cells_unlabeled=sum(r["presence"] == "unlabeled" for r in prov),
                           assist_join=joined["counts"],
                           chosen_source_counts=dict(collections.Counter(
                               r["chosen_source"] for r in prov if r["presence"] in LABELED).most_common()))
        emc._dump(dest / "master" / f"{name}_summary.json", new_summary)
        for cls, recs in overlay.items():
            (dest / "overlay" / f"{cls}.jsonl").write_text(
                "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        (dest / "queues" / "needs_human.csv").write_text(_csv_text(QUEUE_COLUMNS, queue), encoding="utf-8")
        (dest / "queues" / "gold_override_signoff.csv").write_text(_csv_text(SIGNOFF_COLUMNS, signoff), encoding="utf-8")
        manifest = {
            "schema": emc.SCHEMA, "channel": "pre-release", "kind": "production-overlay",
            "version": version, "semver": f"{version}+hf.{emc.FAMILY_HF_REVISION[:8]}",
            "base_release": f"{emc.FAMILY_HF_TAG.removeprefix('v')}.0",
            "base_hf": {"dataset": emc.HF_DEFAULT_REPO, "hf_tag": emc.FAMILY_HF_TAG,
                        "tag_commit": emc.FAMILY_HF_REVISION, "data_revision": emc.FAMILY_HF_DATA_REVISION},
            "status": ("staged for the planned v10 release, not published: overlay/ is applied over the Hub "
                       "v9.3 labels for production scoring; overrides await sign-off in queues/"),
            "source": {"repo": emc.SOURCE_REPO, "labels_commit": labels_commit,
                       "builder": "reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py",
                       "builder_commit": builder_commit, "stager": "scripts/stage_label_overlay.py"},
            "inputs_sha256": {"builder_labels": _sha_bytes(builder_dir / BUILDER_FILES["labels"]),
                              "builder_provenance": _sha_bytes(builder_dir / BUILDER_FILES["provenance"]),
                              "assist": _sha_bytes(assist), "corpus": corpus_sha},
            "coverage": {"cells_targeted": targeted, "cells_labeled": labeled,
                         "completeness": round(labeled / targeted, 4),
                         "cells_labeled_hub_v9_3": summary.get("label_cells_labeled_hub_v9_3")},
            "assist_join": joined["counts"],
            "overlay": {cls: {"documents": len(recs), "labels": sum(len(r["labels"]) for r in recs),
                              "overrides": sum(v["override"] for r in recs for v in r["labels"].values())}
                        for cls, recs in overlay.items()},
            "queues": {"needs_human": len(queue), "gold_override_signoff": len(signoff)},
        }
        manifest["files"] = emc._files(dest)
        emc._dump(dest / "MANIFEST.json", manifest)
        if target.exists():
            same = all((target / p.relative_to(dest)).is_file()
                       and (target / p.relative_to(dest)).read_bytes() == p.read_bytes()
                       for p in dest.rglob("*") if p.is_file())
            if not same:
                raise CacheError(f"v{version} is already cached with different bytes; cut the next rc instead")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dest, target)
    registry = emc.render_registry(out)
    emc._dump(out / "REGISTRY.json", registry)
    (out / "README.md").write_text(emc.render_readme(registry), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(emc.ROOT.parent / "mailroom-issues" / "mailroom_cache"))
    ap.add_argument("--version", required=True)
    ap.add_argument("--builder-dir", type=Path, required=True)
    ap.add_argument("--builder-commit", required=True, help="commit of build_label_repaired.py that wrote --builder-dir")
    ap.add_argument("--assist", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        m = stage(Path(args.out), args.version, args.builder_dir, args.assist, args.corpus,
                  builder_commit=args.builder_commit)
    except CacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: m[k] for k in ("version", "coverage", "assist_join", "overlay", "queues")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
