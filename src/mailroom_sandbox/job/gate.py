"""Production slice gate: bars, per-document outcome and pooled rates for one finished run.

Offline and deterministic (no LLM call, nothing written). Each document of a run lands in one
outcome, using the same scoring as ``job/pair_report.py`` (Dojo ``overall_extraction_score`` on
the row without the templated fields):

- ``correct_archive``: archived and scored at or above the quality bar;
- ``wrong_archive``: archived and scored below it, or archived under another class than the expected one
  (a wrong-class archive is wrong whatever the extraction scores, and counts as scorable);
- ``review``: routed to review (counts toward the review rate, never the wrong-archive rate);
- ``unscorable_archive``: archived but with fewer than ``min_labelled`` labelled fields, so no
  score is trusted (left out of the wrong-archive rate);
- ``crashed``: no item at all, or an item with an error (a run error, which fails the slice).

Every ``review``, ``wrong_archive`` and ``crashed`` status also carries one ``cause`` (see
``job/gate_causes.py``) and the report groups them in ``buckets``.

The slice passes when, pooled over the gated classes, the wrong-archive rate (wrong archives
over scorable archives) and the review rate (reviews over documents) are within the bars and
there are no crashes and no ``judge_error``. Point rates come with Wilson 95% upper bounds.
Per-class bars bite only from ``per_class_from_n`` documents (counted over the whole slice, every
class); below that they are diagnostic.

Rates and what they divide: ``review_rate`` is reviews over all documents of the pool;
``wrong_archive_rate`` is wrong archives over scorable archives; ``correct_archive_rate`` (per class,
reporting only) is correct archives over all documents. Crashes and ``judge_error`` count slice-wide,
``merger_agreement`` included: they are harness faults, not quality. Rates use the gated classes only.

Contracts and mergers are scored by the Dojo on their label field alone (CUAD category spans,
MAUD question answers), so their labelled count is the number of categories or questions in that
field, and only when at least one carries gold; see ``labelled_count``.

The gate never passes blind: gated archives with none scorable fail ("no scorable archives", also
per gated class once per-class bars apply). A share of unscorable gated archives above
``_UNSCORABLE_WARN`` adds a ``verdict["warnings"]`` entry; warnings never change ``pass``.
Design: ``docs/superpowers/specs/2026-11-16-production-slice-gate-design.md``.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import yaml

from mailroom_sandbox.eval.extraction_scope import is_empty_gt, scope_extraction_pair
from mailroom_sandbox.job.pair_report import (
    TEMPLATED_FIELDS,
    _fields,
    _jsonl,
    _score,
    load_arm,
    without_fields,
)
from mailroom_sandbox.paths import config_dir

DEFAULT_BARS_PATH = "production/bars.yaml"
# Not labels: annotation metadata kept on corporate rows so Dojo can tell absence from unlabelled,
# and the evidence columns, which Dojo drops rather than scores (``peel_non_extraction_fields``).
_NOT_LABELS = frozenset({"gt_presence", "label_evidence", "topic_evidence", "sentiment_evidence"})
_Z95 = 1.96
_UNSCORABLE_WARN = 0.25
# Classes the Dojo scores on one label field (a dict of category or question to gold) instead of
# per-field values; that field is not in the live extraction schema, so field scoping drops it.
_UNIT_FIELD = {"contract": "cuad_clause_labels", "merger_agreement": "maud_clause_labels"}


@dataclass(frozen=True)
class Bars:
    quality: float = 0.90
    wrong_archive_max: float = 0.02
    review_max: float = 0.05
    gated: tuple[str, ...] = ("contract", "corporate_record", "correspondence", "insurance_claim")
    min_labelled: int = 2
    per_class_from_n: int = 500


def load_bars(path: Path | None = None) -> Bars:
    """Bars from ``path`` (default ``config/production/bars.yaml``); unknown keys are an error."""
    path = Path(path) if path else config_dir() / DEFAULT_BARS_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(Bars)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"{path}: unknown bar key(s) {unknown}; known: {sorted(known)}")
    if "gated" in raw:
        raw["gated"] = tuple(raw["gated"])
    return Bars(**raw)


def _blank(value: Any) -> bool:
    """Absence, not a stated fact: empty values and strings that spell an empty list or dict."""
    if is_empty_gt(value):
        return True
    if isinstance(value, str) and value.strip() in ("[]", "{}", "null"):
        return True
    return False


def _has_gold(value: Any) -> bool:
    """A category's gold: a non-empty span list, or for MAUD a mapping with some non-blank part."""
    if isinstance(value, Mapping):
        return any(not _blank(v) for v in value.values())
    return not _blank(value)


def _unit_labels(value: Any) -> dict[str, Any]:
    """The label dict of a CUAD/MAUD field, parsing the JSON string E3 rows store; ``{}`` if unusable."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def labelled_count(row: Mapping[str, Any], doc_class: str) -> int:
    """Labelled units of a row: what the Dojo scores it on, after dropping the templated fields.

    Contracts (``cuad_clause_labels``) and mergers (``maud_clause_labels``) are scored on that one
    field: the count is its number of categories (the scored universe) when at least one carries
    gold, else 0. Other classes count non-empty expected values after class scoping.
    """
    unit_field = _UNIT_FIELD.get(doc_class)
    if unit_field:
        labels = _unit_labels(_fields(row).get(unit_field))
        return len(labels) if any(_has_gold(v) for v in labels.values()) else 0
    _, expected = scope_extraction_pair(doc_class, {}, _fields(row))
    drop = TEMPLATED_FIELDS.get(doc_class, ())
    return sum(1 for key, value in expected.items()
               if key not in drop and key not in _NOT_LABELS and not _blank(value))


def _wilson_upper(k: int, n: int) -> float | None:
    if n <= 0:
        return None
    p, z2 = k / n, _Z95 * _Z95
    centre = p + z2 / (2 * n)
    spread = _Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return min(1.0, (centre + spread) / (1 + z2 / n))


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def is_wrong_class(expected_class: str, pred: Mapping[str, Any]) -> bool:
    """Whether the prediction names a class other than the expected one (never when it names none)."""
    got = str(pred.get("doc_type") or "").strip().lower()
    return bool(got) and got != str(expected_class).strip().lower()


def _status(doc: Mapping[str, Any], bars: Bars) -> dict[str, Any]:
    row, item = doc["row"], doc.get("item")
    doc_class = str(row.get("expected_doc_class"))
    out: dict[str, Any] = {"id": str(row.get("id")), "class": doc_class, "stage": "crashed", "score": None,
                           "scorable": False, "outcome": "crashed", "tokens": 0, "judge_error": False,
                           "labelled": labelled_count(row, doc_class)}
    if item is None or item.get("error") or item.get("ok") is False:
        return out
    pred = item.get("pred") or {}
    if pred.get("error"):
        return out
    out["tokens"] = int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0)
    out["judge_error"] = "judge_error" in (pred.get("review_causes") or [])
    out["stage"] = "review" if pred.get("stage") == "review" else "archived"
    out["scorable"] = out["labelled"] >= bars.min_labelled
    if out["stage"] == "review":
        out["outcome"] = "review"
        return out
    if out["scorable"]:
        out["score"] = _score(without_fields(row, TEMPLATED_FIELDS.get(doc_class, ())), pred)
        out["scorable"] = out["score"] is not None
    if is_wrong_class(doc_class, pred):
        out["scorable"], out["outcome"] = True, "wrong_archive"
    elif not out["scorable"]:
        out["outcome"] = "unscorable_archive"
    else:
        out["outcome"] = "correct_archive" if out["score"] >= bars.quality else "wrong_archive"
    return out


def doc_status(doc: Mapping[str, Any], bars: Bars) -> dict[str, Any]:
    """The outcome of one document: ``doc`` is ``{"row", "item", "nodes"}`` with ``item`` None if missing.

    A review, a wrong archive or a crash also gets its primary ``cause``.
    """
    from mailroom_sandbox.job.gate_causes import primary_cause

    out = _status(doc, bars)
    if out["outcome"] in ("review", "wrong_archive", "crashed"):
        out["cause"] = primary_cause(doc, out)
    return out


def _load(run_dir: Path) -> list[dict[str, Any]]:
    """Every dataset row of the run with its latest item (None when the run never wrote one)."""
    arm = load_arm(run_dir)
    docs = []
    for row in _jsonl(run_dir / "dataset.jsonl"):
        doc_id = str(row.get("id"))
        docs.append(arm.get(doc_id) or {"row": row, "item": None, "nodes": []})
    return docs


def _counts(docs: list[dict[str, Any]]) -> dict[str, int]:
    tally = {"n": len(docs), "review": 0, "wrong": 0, "correct": 0, "unscorable": 0, "crashed": 0, "tokens": 0}
    for d in docs:
        tally["tokens"] += d["tokens"]
        key = {"review": "review", "wrong_archive": "wrong", "correct_archive": "correct",
               "unscorable_archive": "unscorable", "crashed": "crashed"}[d["outcome"]]
        tally[key] += 1
    return tally


def _class_rates(c: Mapping[str, int]) -> dict[str, Any]:
    scorable = c["wrong"] + c["correct"]
    return {"n": c["n"], "review_rate": _rate(c["review"], c["n"]),
            "wrong_archive_rate": _rate(c["wrong"], scorable),
            "correct_archive_rate": _rate(c["correct"], c["n"]),
            "scorable": scorable, "unscorable": c["unscorable"], "tokens_per_doc": c["tokens"] / c["n"] if c["n"] else None}


def _breaches(label: str, review: float | None, wrong: float | None, bars: Bars) -> list[str]:
    reasons = []
    if wrong is not None and wrong > bars.wrong_archive_max:
        reasons.append(f"{label}wrong_archive_rate {wrong:.3f} > {bars.wrong_archive_max:g}")
    if review is not None and review > bars.review_max:
        reasons.append(f"{label}review_rate {review:.3f} > {bars.review_max:g}")
    return reasons


def _blindness(label: str, c: Mapping[str, int]) -> tuple[list[str], list[str]]:
    """(failing reasons, warnings) for one pool: no scorable archive at all, or too many unscorable."""
    scorable = c["wrong"] + c["correct"]
    archives = scorable + c["unscorable"]
    reasons = [f"{label}no scorable archives"] if archives and not scorable else []
    share = c["unscorable"] / archives if archives else 0.0
    warnings = []
    if share > _UNSCORABLE_WARN:
        warnings.append(f"{label}unscorable share {share:.3f} of gated archives exceeds {_UNSCORABLE_WARN:g} "
                        f"({c['unscorable']}/{archives})")
    return reasons, warnings


def _buckets(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    """Documents grouped by primary cause, biggest bucket first; ``archive``/``trace_id`` are audit links."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for status in statuses:
        if "cause" in status:
            grouped[status["cause"]].append(status["id"])
    order = sorted(grouped, key=lambda cause: (-len(grouped[cause]), cause))
    return {cause: {"count": len(grouped[cause]),
                    "docs": [{"id": doc_id, "archive": None, "trace_id": None} for doc_id in grouped[cause]]}
            for cause in order}


def gate_report(run_dir: Path, bars: Bars) -> dict[str, Any]:
    """Per-document outcomes, per-class and pooled rates, and the pass/fail verdict for one run."""
    run_dir = Path(run_dir)
    statuses = [doc_status(doc, bars) for doc in _load(run_dir)]
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for status in statuses:
        by_class[status["class"]].append(status)
    classes = {cls: {**_class_rates(_counts(docs)), "gated": cls in bars.gated}
               for cls, docs in sorted(by_class.items())}
    pooled_docs = [s for s in statuses if s["class"] in bars.gated]
    pooled = _counts(pooled_docs)
    scorable = pooled["wrong"] + pooled["correct"]
    crashes = sum(s["outcome"] == "crashed" for s in statuses)
    judge_errors = sum(s["judge_error"] for s in statuses)
    review_rate, wrong_rate = _rate(pooled["review"], pooled["n"]), _rate(pooled["wrong"], scorable)

    reasons: list[str] = []
    warnings: list[str] = []
    if not pooled_docs:
        reasons.append("no gated documents")
    else:
        reasons += _breaches("", review_rate, wrong_rate, bars)
        blind, warn = _blindness("", pooled)
        reasons, warnings = reasons + blind, warnings + warn
        per_class = len(statuses) >= bars.per_class_from_n
        for cls, docs in sorted(by_class.items()):
            if cls not in bars.gated:
                continue
            block = classes[cls]
            if per_class:
                reasons += _breaches(f"class {cls} ", block["review_rate"], block["wrong_archive_rate"], bars)
            blind, warn = _blindness(f"class {cls} ", _counts(docs))
            reasons += blind if per_class else []
            warnings += warn
    if crashes:
        reasons.append(f"{crashes} crashed document(s) (run error or missing item)")
    if judge_errors:
        reasons.append(f"{judge_errors} judge_error document(s)")
    return {
        "run_id": run_dir.name, "n": len(statuses), "bars": {**asdict(bars), "gated": list(bars.gated)},
        "classes": classes,
        "pooled": {"review_rate": review_rate, "wrong_archive_rate": wrong_rate,
                   "review_upper95": _wilson_upper(pooled["review"], pooled["n"]),
                   "wrong_archive_upper95": _wilson_upper(pooled["wrong"], scorable),
                   "scorable": scorable, "unscorable": pooled["unscorable"],
                   "crashes": crashes, "judge_errors": judge_errors},
        "verdict": {"pass": not reasons, "reasons": reasons, "warnings": warnings},
        "buckets": _buckets(statuses),
        "docs": statuses,
    }
