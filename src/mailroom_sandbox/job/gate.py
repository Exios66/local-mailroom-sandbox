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

The audit trail is a hard requirement (``job/gate_audit.py``): every document needs spans in the
local span mirror and a node log, and every archived document its archive directory. Each failure
kind is a failing verdict reason and the report's ``audit`` block lists the documents; ``buckets``
entries carry the document's real ``archive`` path, run-level ``trace_id`` and own ``span_id`` (``None`` when it has none).
``gate_report`` finds the traces and archive from the run dir's checkout (``<root>/data/...``);
a run dir outside that layout fails with "audit trail not located" unless ``traces_dir`` and
``archive_dir`` are passed, or ``audit=False`` (no audit block, unlinked buckets).
Design: ``docs/superpowers/specs/2026-11-16-production-slice-gate-design.md``.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Collection, Mapping

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


def scored_fields(doc_class: str) -> frozenset[str] | None:
    """The fields the Dojo scores for ``doc_class`` (its extraction schema), or None if unregistered.

    Corpus annotations such as ``content_topic``, ``sentiment_label`` and ``sentiment_score`` ride
    on the rows but are not in the schema, so the Dojo never scores them. Counting them as labels
    made a correspondence row scored on ``intent`` alone look like a four-label row.
    """
    import mailroom_sandbox.eval.scoring  # noqa: F401 - puts the selected Dojo on the path
    from llm_dojo_scoring.schemas.doc_classes import field_names

    try:
        return frozenset(field_names(doc_class))
    except KeyError:
        return None


@dataclass(frozen=True)
class Bars:
    quality: float = 0.90
    wrong_archive_max: float = 0.02
    review_max: float = 0.05
    gated: tuple[str, ...] = ("contract", "corporate_record", "correspondence", "insurance_claim")
    min_labelled: int = 2
    per_class_from_n: int = 500
    # From per_class_from_n, a gated class needs this many scorable archives, or its per-class rates
    # are not evidence (corporate records are mostly unscorable: llm-dojo-scoring#164).
    min_scorable_per_class: int = 20


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that refuses a repeated mapping key (the bars are the pass/fail policy)."""

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ValueError(f"duplicate bar key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_bars(path: Path | None = None) -> Bars:
    """Bars from ``path`` (default ``config/production/bars.yaml``); unknown or repeated keys are an error."""
    path = Path(path) if path else config_dir() / DEFAULT_BARS_PATH
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader) or {}  # noqa: S506  # nosec B506 — SafeLoader subclass
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None
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


def labelled_count(row: Mapping[str, Any], doc_class: str, *, hotfixed: bool = True) -> int:
    """Labelled units of a row: what the Dojo scores it on, after dropping the templated fields.

    Contracts (``cuad_clause_labels``) and mergers (``maud_clause_labels``) are scored on that one
    field: the count is its number of categories (the scored universe) when at least one carries
    gold, else 0. Other classes count non-empty expected values after class scoping. SHF-015: a
    stale Hub label no overlay supplied (a heuristic ``intent``) is no label, as the headline
    score does not score it (``docs/scoring-hotfixes.md``). ``hotfixed=False`` counts as the Dojo pin
    does, with no SHF-015 drop: ``_status`` records that as ``labelled_raw`` beside it.
    """
    from mailroom_sandbox import scoring_hotfixes as sh

    unit_field = _UNIT_FIELD.get(doc_class)
    if unit_field:
        labels = _unit_labels(_fields(row).get(unit_field))
        return len(labels) if any(_has_gold(v) for v in labels.values()) else 0
    raw = _fields(row)
    stale: dict[str, str] = {}
    if hotfixed and sh.enabled("SHF-015"):
        _, stale = sh.drop_stale_hub_truth(doc_class, raw, sh.overlay_fields(row))
    _, expected = scope_extraction_pair(doc_class, {}, raw)
    drop = {*TEMPLATED_FIELDS.get(doc_class, ()), *stale}
    scored = scored_fields(doc_class)
    return sum(1 for key, value in expected.items()
               if key not in drop and key not in _NOT_LABELS and not _blank(value)
               and (scored is None or key in scored))


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
    # Exact comparison after lowercasing, with no alias map: a future class alias must be added here.
    got = str(pred.get("doc_type") or "").strip().lower()
    return bool(got) and got != str(expected_class).strip().lower()


def _status(doc: Mapping[str, Any], bars: Bars) -> dict[str, Any]:
    row, item = doc["row"], doc.get("item")
    doc_class = str(row.get("expected_doc_class"))
    out: dict[str, Any] = {"id": str(row.get("id")), "class": doc_class, "stage": "crashed", "score": None,
                           "scorable": False, "outcome": "crashed", "tokens": 0, "judge_error": False,
                           "labelled": labelled_count(row, doc_class)}
    # SHF-015: the count before the stale-label drop, recorded only when the drop changed it, so a
    # class that fell below min_labelled shows which documents moved and by how much.
    raw_labelled = labelled_count(row, doc_class, hotfixed=False)
    if raw_labelled != out["labelled"]:
        out["labelled_raw"] = raw_labelled
    if item is None or item.get("error") or item.get("ok") is False:
        return out
    pred = item.get("pred") or {}
    if pred.get("error"):
        return out
    out["tokens"] = int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0)
    out["judge_error"] = "judge_error" in (pred.get("review_causes") or [])
    out["stage"] = "review" if pred.get("stage") == "review" else "archived"
    if out["stage"] == "archived":
        out["archived_class"] = str(pred.get("doc_type") or "").strip().lower() or None
    out["scorable"] = out["labelled"] >= bars.min_labelled
    if out["stage"] == "review":
        out["outcome"] = "review"
        return out
    out["scorer_failed"] = False
    if out["scorable"]:
        out["score"] = _score(without_fields(row, TEMPLATED_FIELDS.get(doc_class, ())), pred)
        # Enough labels but no score: the scorer failed. The archive cannot count either way, so
        # it is unscorable here and fails the gate below rather than shrinking the denominator.
        out["scorer_failed"] = out["score"] is None
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
    """Every dataset row of the run with its latest item (None when the run never wrote one).

    A run without ``items.jsonl`` loads with every document crashed; the CLI refuses such a run
    before gating it, but the report itself fails closed rather than raising.
    """
    arm = load_arm(run_dir) if (run_dir / "items.jsonl").is_file() else {}
    docs = []
    for row in _jsonl(run_dir / "dataset.jsonl"):
        doc_id = str(row.get("id"))
        docs.append(arm.get(doc_id) or {"row": row, "item": None, "nodes": []})
    return docs


def _unscorable_by_shf015(statuses: Collection[Mapping[str, Any]], bars: Bars) -> int:
    """Archived documents that SHF-015 alone made unscorable: enough labels before the stale drop, too few after."""
    return sum(1 for s in statuses
               if s["outcome"] == "unscorable_archive" and s["labelled"] < bars.min_labelled <= s.get("labelled_raw", 0))


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


def _buckets(statuses: list[dict[str, Any]], audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Documents grouped by primary cause, biggest bucket first; ``archive``/``trace_id`` are audit links."""
    archives = (audit or {}).get("archives") or {}
    traces = (audit or {}).get("trace_ids") or {}
    spans = (audit or {}).get("span_ids") or {}
    grouped: dict[str, list[str]] = defaultdict(list)
    for status in statuses:
        if "cause" in status:
            grouped[status["cause"]].append(status["id"])
    order = sorted(grouped, key=lambda cause: (-len(grouped[cause]), cause))
    return {cause: {"count": len(grouped[cause]),
                    "docs": [{"id": doc_id, "archive": archives.get(doc_id), "trace_id": traces.get(doc_id),
                             "span_id": spans.get(doc_id)}
                             for doc_id in grouped[cause]]}
            for cause in order}


def _audit(run_dir: Path, statuses: list[dict[str, Any]], traces_dir: Path | None,
           archive_dir: Path | None) -> dict[str, Any]:
    from mailroom_sandbox.job.gate_audit import audit_trail, default_dirs

    located = default_dirs(run_dir) if traces_dir is None or archive_dir is None else None
    traces_dir = Path(traces_dir) if traces_dir is not None else (located[0] if located else None)
    archive_dir = Path(archive_dir) if archive_dir is not None else (located[1] if located else None)
    if traces_dir is None or archive_dir is None:
        reason = ("audit trail not located: the run dir is not <root>/data/runtime/runs/<run_id>; "
                  "pass traces_dir and archive_dir")
        return {"trace_ids": {}, "span_ids": {}, "archives": {}, "missing_spans": [], "missing_nodes": [], "missing_archive": [],
                "span_mirror": False, "reasons": [reason], "ok": False}
    archived = {s["id"]: s.get("archived_class") for s in statuses if s["stage"] == "archived"}
    return audit_trail(run_dir, [s["id"] for s in statuses], archived, traces_dir=traces_dir, archive_dir=archive_dir)


def gate_report(run_dir: Path, bars: Bars, *, traces_dir: Path | None = None, archive_dir: Path | None = None,
                audit: bool = True, only_ids: Collection[str] | None = None) -> dict[str, Any]:
    """Per-document outcomes, per-class and pooled rates, the audit trail and the verdict for one run.

    ``traces_dir`` and ``archive_dir`` default to ``<root>/data/traces`` and ``<root>/data/archive`` of the
    checkout holding ``run_dir``; ``audit=False`` skips the audit trail (the report has ``audit: None``).
    ``only_ids`` restricts everything (rates, buckets, audit, ``n``, the per-class bar threshold) to those
    documents; ``None`` is the whole run.
    """
    run_dir = Path(run_dir)
    keep = None if only_ids is None else {str(i) for i in only_ids}
    docs = [doc for doc in _load(run_dir) if keep is None or str(doc["row"].get("id")) in keep]
    statuses = [doc_status(doc, bars) for doc in docs]
    # Kept now: the per-class loop below rebinds ``docs``.
    doc_pairs = list(zip(docs, statuses))
    trail = _audit(run_dir, statuses, traces_dir, archive_dir) if audit else None
    for status in statuses if trail else []:
        status["span_id"] = trail["span_ids"].get(status["id"])
        status["trace_id"] = trail["trace_ids"].get(status["id"])
        status["archive"] = trail["archives"].get(status["id"])
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for status in statuses:
        by_class[status["class"]].append(status)
    classes = {cls: {**_class_rates(_counts(docs)), "gated": cls in bars.gated,
                     "unscorable_by_shf015": _unscorable_by_shf015(docs, bars)}
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
        # Every configured gated class needs the minimum, including one the slice holds no document of.
        for cls in bars.gated if per_class else ():
            scorable_k = (classes.get(cls) or {}).get("scorable", 0)
            # A present class with archives but none scorable is already failed by _blindness above.
            if scorable_k < bars.min_scorable_per_class and (scorable_k or cls not in by_class):
                reasons.append(f"class {cls} has {scorable_k} scorable archives < {bars.min_scorable_per_class}")
        failed = sum(1 for s in pooled_docs if s["outcome"] == "unscorable_archive" and s.get("scorer_failed"))
        if failed:
            reasons.append(f"{failed} archive(s) with enough labels that the scorer could not score")
    if crashes:
        reasons.append(f"{crashes} crashed document(s) (run error or missing item)")
    if judge_errors:
        reasons.append(f"{judge_errors} judge_error document(s)")
    reasons += trail["reasons"] if trail else []
    from mailroom_sandbox.job.gate_slots import decision_slot_report

    gated = [(d, s) for d, s in doc_pairs if s["class"] in bars.gated]
    slots = decision_slot_report([d for d, _ in gated], [s for _, s in gated],
                                 max_wrong_archive_rate=bars.wrong_archive_max)
    from mailroom_sandbox import scoring_hotfixes as sh

    return {
        # Present only when the run used llm-mailroom decision slots (job/gate_slots.py).
        **({"decision_slots": slots} if slots is not None else {}),
        "run_id": run_dir.name, "n": len(statuses), "bars": {**asdict(bars), "gated": list(bars.gated)},
        # The document scores are the hotfixed headline; these are the fixes in force when scored.
        "headline_basis": sh.headline_basis(), "scoring_hotfixes": sorted(sh.current_ids()),
        "classes": classes,
        "pooled": {"review_rate": review_rate, "wrong_archive_rate": wrong_rate,
                   "review_upper95": _wilson_upper(pooled["review"], pooled["n"]),
                   "wrong_archive_upper95": _wilson_upper(pooled["wrong"], scorable),
                   "scorable": scorable, "unscorable": pooled["unscorable"],
                   "unscorable_by_shf015": _unscorable_by_shf015(pooled_docs, bars),
                   "crashes": crashes, "judge_errors": judge_errors},
        "verdict": {"pass": not reasons, "reasons": reasons, "warnings": warnings},
        "audit": trail,
        "buckets": _buckets(statuses, trail),
        "docs": statuses,
    }
