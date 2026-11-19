"""Gold-label audit sheets for evaluation runbook row R03 (offline, no model call).

R03 adjudicates about 100 v0-vs-gold disagreements per lineage as ``model_wrong``, ``gold_wrong``
or ``ambiguous``. Its gate: gold is wrong on at most 15% of the audited documents, or the labels are
corrected as a new labels version (``docs/superpowers/plans/2026-11-18-evaluation-runbook-plan.md``,
Task 4).

``build_sheet`` reads one finished v0 run (its locked ``dataset.jsonl``, the truth it was scored on
with the interim and near-gold overlays applied, and its ``items.jsonl`` predictions) and lists the
disagreements:

* ``sorter``: the document class, or the subclass when the class is right (contract subclasses
  compared through the Dojo's ``normalize_subtype``, as ``scripts/compare_sorter_prompt.py`` does);
* per-field specialists: every labelled field whose verdict in
  field registry (``config/extraction/subclass_schemas-runbook-v1.json`` for campaign rb1, graded on
  the run's revision; ``check_schemas_revision`` refuses another one) is ``iterate`` and whose Dojo per-field score
  (``job.gate_causes._field_scores``, the slice gate's scorer) is below ``mismatch_below``.
  Templated fields (``pair_report.TEMPLATED_FIELDS``) are left out, as the gate leaves them out;
* contract CUAD categories (``cuad_clauses:<category>``): gold categories the run missed and
  predicted categories CUAD does not label, resolved with the Dojo's own CUAD helpers and
  cross-checked against its ``cuad_fn`` / ``cuad_fp`` counts;
* merger MAUD questions (``maud_clauses:<question>``): every gold question the run left unanswered
  or answered differently (Dojo ``parse_maud_answers`` / ``same_answer``, as ``score_maud`` counts).

Fields an isolated run with ``job.specialist_subclass: gold`` derives from the gold subclass copy the
truth there, so they are never sampled (``DERIVED_FROM_SUBCLASS``).

Only dev and pool documents may be audited: a run holding any held-out, calibration or unknown id is
refused (``AuditError``), never filtered, so a mis-pointed run cannot leak the sealed sets into
label work. The sample is deterministic: candidates are ordered by ``sha256(seed:doc:field)``, at
most ``per_doc`` per document, the first ``n`` kept.

``summarize`` reads a filled sheet and reports the gold-wrong rate per audited document (a document
counts as gold-wrong when any of its rows is) and per row, each with a two-sided Clopper-Pearson 95%
interval built from the Dojo's ``clopper_pearson_upper`` (``experiment_stats``). The gate compares
the per-document point rate with the threshold; a blank verdict leaves it ``incomplete``.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Audit lineage -> document class (``None``: the sorter, every class).
LINEAGES: dict[str, str | None] = {
    "sorter": None,
    "insurance": "insurance_claim",
    "correspondence": "correspondence",
    "corporate": "corporate_record",
    "contracts": "contract",
    "merger": "merger_agreement",
}
#: Fields the pipeline handoff derives from the subclass (``doc_inventories.enrich_extraction``):
#: with ``job.specialist_subclass: gold`` they copy the truth, so they are not audited.
DERIVED_FROM_SUBCLASS: dict[str, frozenset[str]] = {
    "insurance_claim": frozenset({"cms_source_table"}),
    "corporate_record": frozenset({"record_type"}),
    "contract": frozenset({"cuad_family"}),
}
AUDITABLE_SETS = frozenset({"dev", "pool"})
VERDICTS = ("model_wrong", "gold_wrong", "ambiguous")
GATE_MAX_GOLD_WRONG = 0.15
COLUMNS = ("doc_id", "set", "doc_class", "gold_subclass", "field", "v0_value", "gold_value",
           "field_score", "label_source", "run_id", "verdict", "note")
_VALUE_CHARS = 2000


class AuditError(ValueError):
    """The run or sheet cannot be audited as asked (wrong sets, missing files, bad verdicts)."""


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AuditError(f"{path}: missing")
    with path.open(encoding="utf-8", newline="\n") as handle:
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


def load_assignments(split_dir: Path) -> dict[str, str]:
    """``{doc_id: set}`` from a split's ``assignments.jsonl``."""
    return {str(r["id"]): str(r["set"]) for r in _jsonl(Path(split_dir) / "assignments.jsonl")}


def check_sets(doc_ids: Iterable[str], assignments: Mapping[str, str]) -> None:
    """Refuse any document outside dev and pool (held-out, calibration, or not in the split)."""
    bad: dict[str, list[str]] = defaultdict(list)
    for doc_id in doc_ids:
        where = assignments.get(doc_id, "unknown")
        if where not in AUDITABLE_SETS:
            bad[where].append(doc_id)
    if bad:
        detail = ", ".join(f"{s} {len(v)} (e.g. {sorted(v)[0]})" for s, v in sorted(bad.items()))
        raise AuditError(f"the audit reads dev and pool documents only; this run holds {detail}. "
                         "Point --run at a dev or pool v0 pass")


def _tag_commit(sha: str) -> str:
    """The Hub tag commit for a family revision: a tag name or its parquet parent maps to the tag
    commit; any other value is returned unchanged."""
    from mailroom_sandbox.job.spec import (
        FAMILY_HF_DATA_REVISION,
        FAMILY_HF_REVISION,
        FAMILY_HF_TAG,
        LEGACY_FAMILY_HF_REVISIONS,
    )

    pairs = {FAMILY_HF_TAG: (FAMILY_HF_REVISION, FAMILY_HF_DATA_REVISION), **LEGACY_FAMILY_HF_REVISIONS}
    return next((tag for name, (tag, data) in pairs.items() if sha in (name, tag, data)), sha)


def check_schemas_revision(rows: list[Mapping[str, Any]], schemas: Mapping[str, Any], schemas_path: Path) -> None:
    """Refuse a registry graded on another dataset revision than the run drew.

    Its ``iterate`` verdicts come from that revision's labels, so a mismatch samples the wrong fields.
    A registry or run that records no revision is not checked.
    """
    want = str((schemas.get("inputs") or {}).get("dataset_revision") or "")
    have = sorted({_tag_commit(str(r.get("source_revision") or "")) for r in rows} - {""})
    if want and have and have != [_tag_commit(want)]:
        drew = ", ".join(h[:12] for h in have)
        raise AuditError(f"{schemas_path.name} grades dataset revision {want[:12]}, but the run drew {drew}; "
                         "pass a registry built on the run's revision with --schemas "
                         "(sandbox schemas build --revision <sha> --out <file>)")


def iterate_fields(schemas: Mapping[str, Any], doc_class: str, subclass: str | None = None,
                   level: str = "class") -> frozenset[str]:
    """Fields with verdict ``iterate`` for ``doc_class`` (or its subclass entry, at ``level=subclass``)."""
    cls = (schemas.get("classes") or {}).get(doc_class)
    if cls is None:
        raise AuditError(f"the field registry has no class {doc_class!r}")
    fields_ = cls.get("fields") or {}
    if level == "subclass" and subclass:
        entry = (cls.get("subclasses") or {}).get(_norm_subclass(doc_class, subclass))
        if entry is not None:
            fields_ = entry.get("fields") or {}
    return frozenset(f for f, e in fields_.items() if e.get("verdict") == "iterate")


def _norm_subclass(doc_class: str, value: Any) -> str:
    text = str(value or "").strip()
    if doc_class == "contract" and text:
        from llm_dojo_scoring.equivalences import normalize_subtype

        return str(normalize_subtype(text) or "")
    return text.lower()


def label_source(row: Mapping[str, Any], name: str) -> str:
    """``interim`` / ``near_gold`` when that overlay filled ``name`` on this row, else ``hub``."""
    for key, source in (("interim_labels", "interim"), ("near_gold_labels", "near_gold")):
        marker = row.get(key) or {}
        if isinstance(marker, Mapping) and name in (marker.get("fields") or ()):
            return source
    return "hub"


def _render(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return text if len(text) <= _VALUE_CHARS else text[:_VALUE_CHARS] + "…"


def _prediction(item: Mapping[str, Any]) -> dict[str, Any]:
    pred = item.get("pred") or {}
    nested = pred.get("extracted_data") if isinstance(pred, Mapping) else None
    return dict(nested if isinstance(nested, Mapping) else pred)


def _failed(item: Mapping[str, Any] | None) -> bool:
    if not item:
        return True
    return bool(item.get("error") or item.get("ok") is False or _prediction(item).get("_parse_error"))


def sorter_disagreements(row: Mapping[str, Any], item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The class disagreement, or the subclass one when the class is right."""
    pred = item.get("pred") or {}
    gold_class = str(row.get("expected_doc_class") or "")
    got_class = str(pred.get("doc_type") or "")
    if got_class != gold_class:
        return [{"field": "doc_class", "v0_value": got_class, "gold_value": gold_class,
                 "label_source": label_source(row, "expected_doc_class")}]
    got_sub = pred.get("contract_subtype") if gold_class == "contract" else None
    got_sub = got_sub or pred.get("doc_subclass")
    gold_sub = row.get("expected_subclass")
    if _norm_subclass(gold_class, got_sub) != _norm_subclass(gold_class, gold_sub):
        return [{"field": "subclass", "v0_value": got_sub or "", "gold_value": gold_sub or "",
                 "label_source": label_source(row, "expected_subclass")}]
    return []


def _cuad_disagreements(row: Mapping[str, Any], pred: Mapping[str, Any]) -> list[dict[str, Any]]:
    from llm_dojo_scoring.pipeline import sandbox_scoring as ss

    from mailroom_sandbox.eval.cuad_scoring import score_cuad
    from mailroom_sandbox.job.pair_report import _fields

    raw = _fields(row).get("cuad_clause_labels")
    gt = ss.gt_categories(raw)
    if not gt:
        return []
    universe = list(gt)
    present = {c for c, spans in gt.items() if spans}
    # The category set score_cuad credits (recall-only date fields, effective-from-agreement).
    found, _ = ss.predicted_categories(pred, universe)
    strict, _ = ss.predicted_categories({**pred, **dict.fromkeys(ss.RECALL_ONLY_FIELDS)}, universe)
    found = strict | (found & present)
    if "Effective Date" in found and ss.effective_from_agreement(pred.get("effective_date"), gt):
        found.discard("Effective Date")
    missed, false = sorted(present - found), sorted(found - present)
    scored = score_cuad(pred, raw)
    if (len(missed), len(false)) != (scored.get("cuad_fn"), scored.get("cuad_fp")):
        raise AuditError(f"{row.get('id')}: CUAD category diff ({len(missed)} missed, {len(false)} false) "
                         f"disagrees with the Dojo (fn {scored.get('cuad_fn')}, fp {scored.get('cuad_fp')})")
    source = label_source(row, "cuad_clause_labels")
    out = [{"field": f"cuad_clauses:{c}", "v0_value": "", "gold_value": _render(gt[c]),
            "label_source": source} for c in missed]
    out += [{"field": f"cuad_clauses:{c}", "v0_value": "predicted", "gold_value": "",
             "label_source": source} for c in false]
    return out


def _maud_disagreements(row: Mapping[str, Any], pred: Mapping[str, Any]) -> list[dict[str, Any]]:
    from llm_dojo_scoring.pipeline import sandbox_scoring as ss

    from mailroom_sandbox.job.pair_report import _fields

    gt = ss.gt_labels(_fields(row).get("maud_clause_labels"))
    answers = ss.parse_maud_answers(pred, list(gt))
    source = label_source(row, "maud_clause_labels")
    out = []
    for question in sorted(gt):
        answer = answers.get(question)
        if answer is None or ss.is_non_answer(answer, question) or not ss.same_answer(answer, gt[question], question):
            out.append({"field": f"maud_clauses:{question}", "v0_value": _render(answer),
                        "gold_value": gt[question], "label_source": source})
    return out


def specialist_disagreements(row: Mapping[str, Any], item: Mapping[str, Any], fields_: frozenset[str],
                             *, mismatch_below: float = 1.0) -> list[dict[str, Any]]:
    """Per-field disagreements on ``fields_`` (plus CUAD categories or MAUD questions when audited)."""
    from mailroom_sandbox.job.gate_causes import _field_scores
    from mailroom_sandbox.job.pair_report import TEMPLATED_FIELDS, _fields

    doc_class = str(row.get("expected_doc_class") or "")
    pred = _prediction(item)
    audited = fields_ - DERIVED_FROM_SUBCLASS.get(doc_class, frozenset()) - set(TEMPLATED_FIELDS.get(doc_class, ()))
    out: list[dict[str, Any]] = []
    if doc_class == "contract" and "cuad_clauses" in audited:
        out += _cuad_disagreements(row, pred)
    if doc_class == "merger_agreement" and "maud_clauses" in audited:
        out += _maud_disagreements(row, pred)
    per_field = audited - {"cuad_clauses", "maud_clauses"}
    scores = _field_scores(row, {"extracted_data": pred}) if per_field else {}
    gold = _fields(row)
    for name in sorted(audited & set(scores)):
        if scores[name] < mismatch_below:
            out.append({"field": name, "v0_value": _render(pred.get(name)), "gold_value": _render(gold.get(name)),
                        "field_score": round(scores[name], 4), "label_source": label_source(row, name)})
    return out


def _rank(seed: int, doc_id: str, name: str) -> str:
    return hashlib.sha256(f"{seed}:{doc_id}:{name}".encode()).hexdigest()


def sample(candidates: list[dict[str, Any]], *, n: int, seed: int, per_doc: int = 1) -> list[dict[str, Any]]:
    """Deterministic draw: seeded hash order, at most ``per_doc`` rows per document, first ``n``."""
    ordered = sorted(candidates, key=lambda c: _rank(seed, c["doc_id"], c["field"]))
    taken: Counter = Counter()
    out = []
    for cand in ordered:
        if per_doc and taken[cand["doc_id"]] >= per_doc:
            continue
        taken[cand["doc_id"]] += 1
        out.append(cand)
        if len(out) >= n:
            break
    return sorted(out, key=lambda c: (c["doc_id"], c["field"]))


@dataclass
class SheetResult:
    rows: list[dict[str, Any]]
    digest: dict[str, Any] = field(default_factory=dict)


def build_sheet(run_dir: Path, lineage: str, *, split_dir: Path, schemas_path: Path, n: int = 100,
                seed: int, per_doc: int = 1, mismatch_below: float = 1.0,
                verdict_level: str = "class") -> SheetResult:
    """Disagreement rows sampled from one finished v0 run (see the module docstring)."""
    if lineage not in LINEAGES:
        raise AuditError(f"unknown lineage {lineage!r}; have {sorted(LINEAGES)}")
    if verdict_level not in ("class", "subclass"):
        raise AuditError("verdict_level must be 'class' or 'subclass'")
    run_dir = Path(run_dir)
    rows = _jsonl(run_dir / "dataset.jsonl")
    items = {str(i.get("item_id")): i for i in _jsonl(run_dir / "items.jsonl")}
    assignments = load_assignments(split_dir)
    check_sets([str(r.get("id")) for r in rows], assignments)
    doc_class = LINEAGES[lineage]
    if doc_class is not None:
        other = sorted({str(r.get("expected_doc_class")) for r in rows} - {doc_class})
        if other:
            raise AuditError(f"lineage {lineage} audits {doc_class} documents; the run also holds {other}")
    schemas = json.loads(Path(schemas_path).read_text(encoding="utf-8")) if doc_class else {}
    if schemas:
        check_schemas_revision(rows, schemas, Path(schemas_path))
    counts: Counter = Counter()
    candidates: list[dict[str, Any]] = []
    scorer_errors: list[str] = []
    for row in rows:
        doc_id = str(row.get("id"))
        item = items.get(doc_id)
        counts["documents"] += 1
        if _failed(item):
            counts["failed_or_missing"] += 1
            continue
        if doc_class is None:
            found = sorter_disagreements(row, item)
        else:
            from mailroom_sandbox.job.gate_causes import ScorerError

            fields_ = iterate_fields(schemas, doc_class, row.get("expected_subclass"), verdict_level)
            try:
                found = specialist_disagreements(row, item, fields_, mismatch_below=mismatch_below)
            except ScorerError as exc:
                # Counted and named, never folded into "no disagreement".
                counts["scorer_error"] += 1
                scorer_errors.append(f"{doc_id}: {exc}")
                continue
        if found:
            counts["documents_with_disagreement"] += 1
        for cand in found:
            candidates.append({"doc_id": doc_id, "set": assignments[doc_id],
                               "doc_class": row.get("expected_doc_class") or "",
                               "gold_subclass": row.get("expected_subclass") or "",
                               "field_score": "", "run_id": run_dir.name, "verdict": "", "note": "", **cand})
    chosen = sample(candidates, n=n, seed=seed, per_doc=per_doc)
    digest = {"run": str(run_dir), "lineage": lineage, "seed": seed, "n_requested": n, "per_doc": per_doc,
              "mismatch_below": mismatch_below, "verdict_level": verdict_level, **counts,
              "disagreements": len(candidates), "sampled": len(chosen),
              "sampled_documents": len({c["doc_id"] for c in chosen}),
              "sampled_rows_sha256": rows_digest(chosen),
              "by_field": dict(Counter(c["field"].split(":", 1)[0] for c in candidates).most_common()),
              "by_label_source": dict(Counter(c["label_source"] for c in chosen).most_common()),
              "scorer_errors": scorer_errors[:20]}
    return SheetResult(rows=chosen, digest=digest)


MIN_AUDITED_DOCS = 100  # R03: ~100 disagreements per lineage, or all a run has when it has fewer


def rows_digest(rows: list[dict[str, Any]]) -> str:
    """sha256 of the sheet's (doc_id, field) rows, so a trimmed or padded sheet is detected."""
    keys = sorted(f"{r['doc_id']}\t{r['field']}" for r in rows)
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def check_sheet_size(rows: list[dict[str, Any]], meta: dict[str, Any] | None) -> list[str]:
    """Why a sheet is too small or altered for the gate (empty when it is the builder's full sample)."""
    if meta is None:
        return ["no <sheet>.meta.json from build_gold_audit_sheet.py; the sample size cannot be checked"]
    problems = []
    if meta.get("sampled_rows_sha256") and rows_digest(rows) != meta["sampled_rows_sha256"]:
        problems.append("the sheet's rows differ from the builder's sample (trimmed, padded or edited ids)")
    if len(rows) != meta.get("sampled"):
        problems.append(f"{len(rows)} rows, but the builder sampled {meta.get('sampled')}")
    floor = min(MIN_AUDITED_DOCS, int(meta.get("documents_with_disagreement") or meta.get("disagreements") or 0))
    docs = len({r["doc_id"] for r in rows})
    if docs < floor or docs == 0:
        problems.append(f"{docs} audited documents < {floor} required (min({MIN_AUDITED_DOCS}, the run's documents "
                        "with a disagreement))")
    return problems


def write_sheet(rows: list[dict[str, Any]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})


def clopper_pearson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Two-sided exact interval for ``k`` of ``n``, from the Dojo's one-sided upper bound."""
    from mailroom_sandbox.experiment_stats import clopper_pearson_upper

    if n <= 0:
        raise AuditError("no adjudicated rows")
    level = 1.0 - (1.0 - confidence) / 2.0
    upper = 1.0 if k >= n else float(clopper_pearson_upper(k, n, confidence=level))
    lower = 0.0 if k <= 0 else 1.0 - float(clopper_pearson_upper(n - k, n, confidence=level))
    return lower, upper


def _rate(k: int, n: int) -> dict[str, Any]:
    lower, upper = clopper_pearson_interval(k, n)
    return {"gold_wrong": k, "n": n, "rate": round(k / n, 4), "ci95": [round(lower, 4), round(upper, 4)]}


def summarize(path: Path, *, threshold: float = GATE_MAX_GOLD_WRONG) -> dict[str, Any]:
    """Gold-wrong rates of a filled sheet and the R03 gate (per audited document, point rate)."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AuditError(f"{path}: no rows")
    missing = set(COLUMNS) - set(rows[0])
    if missing:
        raise AuditError(f"{path}: missing columns {sorted(missing)}")
    bad = sorted({r["verdict"].strip() for r in rows if r["verdict"].strip() and r["verdict"].strip() not in VERDICTS})
    if bad:
        raise AuditError(f"{path}: unknown verdicts {bad}; use one of {list(VERDICTS)}")
    blank = sum(1 for r in rows if not r["verdict"].strip())
    done = [r for r in rows if r["verdict"].strip()]
    verdicts = Counter(r["verdict"].strip() for r in done)
    out: dict[str, Any] = {"sheet": str(path), "rows": len(rows), "adjudicated": len(done), "blank": blank,
                           "verdicts": {v: verdicts.get(v, 0) for v in VERDICTS}, "threshold": threshold}
    if not done:
        out["gate"] = "incomplete"
        return out
    per_doc: dict[str, bool] = defaultdict(bool)
    for r in done:
        per_doc[r["doc_id"]] |= r["verdict"].strip() == "gold_wrong"
    out["per_row"] = _rate(verdicts.get("gold_wrong", 0), len(done))
    out["per_document"] = _rate(sum(per_doc.values()), len(per_doc))
    by_source: dict[str, Counter] = defaultdict(Counter)
    for r in done:
        by_source[r["label_source"]][r["verdict"].strip()] += 1
    out["by_label_source"] = {s: dict(c) for s, c in sorted(by_source.items())}
    meta_path = Path(path).with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    out["size_problems"] = check_sheet_size(rows, meta)
    if blank:
        out["gate"] = "incomplete"
    elif out["size_problems"]:
        out["gate"] = "too_small"
    else:
        out["gate"] = "pass" if out["per_document"]["rate"] <= threshold else "fail"
    out["upper_bound_within_threshold"] = out["per_document"]["ci95"][1] <= threshold
    return out
