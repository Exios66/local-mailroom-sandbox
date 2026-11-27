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
Design: ``docs/design/specs/2026-11-16-production-slice-gate-design.md``.
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


def _judge_reask_counts(raw: Any) -> dict[str, dict[str, int]]:
    """A pipeline result's ``judge_reasks`` as plain ints: ``{judge: {"asked", "recovered", "parked"}}``."""
    out: dict[str, dict[str, int]] = {}
    for judge, counts in raw.items():
        if not isinstance(counts, Mapping):
            continue
        try:
            out[str(judge)] = {key: _reask_count(counts.get(key)) for key in ("asked", "recovered", "parked")}
        except (TypeError, ValueError, OverflowError):
            continue  # a hand-edited or corrupt count: skip that judge, never raise out of the gate
    return out


def _reask_count(value: Any) -> int:
    """A non-negative whole count; a negative, fractional or boolean value is corrupt (ValueError)."""
    if value is None:
        return 0
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"not a whole count: {value!r}")
    count = int(value)
    if count < 0:
        raise ValueError(f"negative count: {value!r}")
    return count


def _judge_reask_block(reasked: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Totals of the documents whose judge was re-asked: per judge and overall.

    Every re-ask ends as ``recovered`` (the second answer parsed), ``parked`` (it did not parse either, so
    the judge raised and the document went to review as a ``judge_error``) or ``errored`` (the second call
    itself raised, a transport error or the call guard's refusal: no parse outcome, and HF-012 may have
    re-run the node), so ``asked = recovered + parked + errored``.
    """
    by_judge: dict[str, dict[str, int]] = {}
    for status in reasked:
        for judge, counts in status["judge_reasks"].items():
            total = by_judge.setdefault(judge, {"asked": 0, "recovered": 0, "parked": 0, "errored": 0})
            for key in ("asked", "recovered", "parked"):
                total[key] += counts[key]
            total["errored"] += max(0, counts["asked"] - counts["recovered"] - counts["parked"])
    totals = {key: sum(c[key] for c in by_judge.values()) for key in ("asked", "recovered", "parked", "errored")}
    return {"documents": len(reasked), **totals, "by_judge": dict(sorted(by_judge.items())),
            "docs": [s["id"] for s in reasked]}


def _governor_fields(out: dict[str, Any], pred: Mapping[str, Any]) -> None:
    """The loop governor's marks on a result (phase 2): its stop, a linked duplicate, skipped sorter retries."""
    stop = pred.get("governor_stop")
    if isinstance(stop, Mapping) and stop.get("reason"):
        out["governor_stop"] = {"reason": str(stop["reason"]), "outcome": str(stop.get("outcome") or "")}
    duplicate = pred.get("duplicate_of")
    if isinstance(duplicate, Mapping) and duplicate.get("kind"):
        out["duplicate_of"] = str(duplicate["kind"])
    skips = pred.get("governor_skips")
    if isinstance(skips, Mapping) and _reask_count(skips.get("classify_retry")):
        out["governor_skips"] = _reask_count(skips.get("classify_retry"))


def _governor_block(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    stops: dict[str, dict[str, int]] = {}
    duplicates: dict[str, int] = {}
    for s in statuses:
        if "governor_stop" in s:
            by_outcome = stops.setdefault(s["governor_stop"]["reason"], {})
            by_outcome[s["governor_stop"]["outcome"]] = by_outcome.get(s["governor_stop"]["outcome"], 0) + 1
        if "duplicate_of" in s:
            duplicates[s["duplicate_of"]] = duplicates.get(s["duplicate_of"], 0) + 1
    return {"stops": {r: dict(sorted(o.items())) for r, o in sorted(stops.items())},
            "duplicates": dict(sorted(duplicates.items())),
            "skipped_classify_retries": sum(int(s.get("governor_skips") or 0) for s in statuses),
            "docs": [s["id"] for s in statuses
                     if "governor_stop" in s or "duplicate_of" in s or "governor_skips" in s]}


# --- phase 4: the judge block (judge: section, ``judge_record``) -------------------------------------------

#: Agents whose calls are judge-related (ruling 17), beside the judge-ordered re-extractions.
JUDGE_AGENTS = ("judge", "arbiter")


def _agent_calls(item: Mapping[str, Any], agents: Collection[str]) -> int:
    usage = item.get("usage_by_agent") or {}
    return sum(_reask_count((usage.get(a) or {}).get("calls")) for a in agents if isinstance(usage, Mapping))


def judge_retries(pred: Mapping[str, Any], nodes: Collection[Mapping[str, Any]] = ()) -> int:
    """Re-extractions a judge (or the vendored arbiter) ordered: retry_extract visits, else retry rulings."""
    visits = sum(1 for n in nodes or () if n.get("node") == "retry_extract")
    if visits:
        return visits
    return sum(1 for r in pred.get("judge_rulings") or () if isinstance(r, Mapping) and r.get("ruling") == "retry_fields")


def judge_related_calls(item: Mapping[str, Any], pred: Mapping[str, Any], nodes: Collection[Mapping[str, Any]] = ()) -> int:
    """Judge, arbiter and judge-ordered re-extraction calls of one document (ruling 17)."""
    return _agent_calls(item, JUDGE_AGENTS) + judge_retries(pred, nodes)


def doc_cost(item: Mapping[str, Any]) -> float | None:
    """The document's USD cost: the provider's reported cost, else its usage priced per agent model."""
    reported = item.get("reported_cost_usd")
    if isinstance(reported, (int, float)) and not isinstance(reported, bool):
        return float(reported)
    from mailroom_sandbox.job.metrics import call_cost

    total, usage = 0.0, item.get("usage_by_agent") or {}
    for slot in usage.values() if isinstance(usage, Mapping) else ():
        models = slot.get("models") or []
        if not slot.get("calls"):
            continue
        cost = call_cost(models[0] if models else None, slot.get("prompt_tokens") or 0,
                         slot.get("completion_tokens") or 0, calls=int(slot["calls"]))
        if cost is None:
            return None
        total += cost
    return total if usage else None


def _fix_accuracy(row: Mapping[str, Any], fixes: list[Mapping[str, Any]]) -> tuple[int, int]:
    """Verified fixes on labelled fields scored against the truth: ``(right, wrong)`` (ruling 16).

    The truth is the headline's: a Hub label SHF-015 drops as stale (a heuristic ``intent``, a
    templated title) is no label here either, so a fix to that field is not scored.
    """
    from mailroom_sandbox import scoring_hotfixes as sh
    from mailroom_sandbox.job.gate_causes import ScorerError, _field_scores

    stale: dict[str, str] = {}
    if sh.enabled("SHF-015"):
        _, stale = sh.drop_stale_hub_truth(str(row.get("expected_doc_class")), _fields(row), sh.overlay_fields(row))
    right = wrong = 0
    for fix in fixes:
        if fix["field"] in stale:
            continue
        try:
            scores = _field_scores(row, {"extracted_data": {fix["field"]: fix.get("value")}})
        except ScorerError:
            continue
        if fix["field"] in scores:
            if scores[fix["field"]] >= 0.999:
                right += 1
            else:
                wrong += 1
    return right, wrong


def _judge_fields(out: dict[str, Any], doc: Mapping[str, Any], pred: Mapping[str, Any], bars: Bars) -> None:
    """A judged document's record (rulings, fixes, scores before and after the judge, calls, cost)."""
    rulings = [r for r in pred.get("judge_rulings") or () if isinstance(r, Mapping)]
    if not rulings:
        return
    row, item = doc["row"], doc.get("item") or {}
    fixes = [f for r in rulings for f in r.get("fixes") or () if isinstance(f, Mapping)]
    verified = [f for f in fixes if f.get("verified")]
    # An accept and a retry write their verified fixes (HF-025, correcting_judge.APPLIES_FIXES); a review
    # ruling's are not applied.
    from mailroom_sandbox.correcting_judge import APPLIES_FIXES

    applied = [f for r in rulings if r.get("ruling") in APPLIES_FIXES for f in r.get("fixes") or ()
               if isinstance(f, Mapping) and f.get("verified")]
    scorable = out["labelled"] >= bars.min_labelled
    scored_row = without_fields(row, TEMPLATED_FIELDS.get(out["class"], ()))
    before = pred.get("before_judge")
    right, wrong = _fix_accuracy(row, applied) if scorable else (0, 0)
    out["judge"] = {
        "rulings": [[int(r.get("pass") or 0), str(r.get("ruling") or "")] for r in rulings],
        "proposed": len(fixes), "verified": len(verified), "applied": len(applied),
        "rejected": dict(sorted(defaultdict_count(str(f.get("why")) for f in fixes if not f.get("verified")).items())),
        "right": right, "wrong": wrong,
        "corrected": bool(pred.get("judge_corrected")),
        "retries": sum(1 for r in rulings if r.get("ruling") == "retry_fields"),
        "score_before": _score(scored_row, {"extracted_data": before}) if scorable and isinstance(before, Mapping) else None,
        "score_after": _score(scored_row, pred) if scorable else None,
        "calls": _reask_count(item.get("llm_calls")),
        "judge_calls": judge_related_calls(item, pred, doc.get("nodes") or ()),
        "cost": doc_cost(item),
        "cached_tokens": _reask_count(item.get("cached_tokens")) if item.get("cached_tokens") is not None else None,
        "conflict": bool(pred.get("judge_conflict")),
    }


def defaultdict_count(keys: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return counts


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _judge_block(statuses: list[dict[str, Any]]) -> dict[str, Any] | None:
    judged = [s for s in statuses if "judge" in s]
    if not judged:
        return None
    rulings: dict[str, dict[str, int]] = {}
    rejected: dict[str, int] = {}
    for s in judged:
        for pass_no, kind in s["judge"]["rulings"]:
            rulings.setdefault(kind, {})[str(pass_no)] = rulings.get(kind, {}).get(str(pass_no), 0) + 1
        for why, n in s["judge"]["rejected"].items():
            rejected[why] = rejected.get(why, 0) + n
    paired = [s["judge"] for s in judged if s["judge"]["score_before"] is not None and s["judge"]["score_after"] is not None]
    costs: dict[str, list[float]] = {}
    for s in judged:
        if s["judge"]["cost"] is not None:
            costs.setdefault(s["class"], []).append(s["judge"]["cost"])
    cached = [s["judge"]["cached_tokens"] for s in judged if s["judge"]["cached_tokens"] is not None]
    archived = [s for s in judged if s["outcome"] in ("correct_archive", "wrong_archive")]
    stops: dict[str, int] = {}
    for s in judged:
        if "governor_stop" in s:
            stops[s["governor_stop"]["reason"]] = stops.get(s["governor_stop"]["reason"], 0) + 1
    return {
        "docs_judged": len(judged),
        "rulings": {k: dict(sorted(v.items())) for k, v in sorted(rulings.items())},
        "fixes": {"proposed": sum(s["judge"]["proposed"] for s in judged),
                  "verified": sum(s["judge"]["verified"] for s in judged),
                  "applied": sum(s["judge"]["applied"] for s in judged),
                  "rejected": dict(sorted(rejected.items())),
                  "right": sum(s["judge"]["right"] for s in judged), "wrong": sum(s["judge"]["wrong"] for s in judged)},
        "judge_corrected": sum(s["judge"]["corrected"] for s in judged),
        "retries": sum(s["judge"]["retries"] for s in judged),
        # Scores that include judge fixes are labelled "after judge" (spec "How we will measure it").
        "scores_label": "after judge", "scored_n": len(paired),
        "score_before": _mean([j["score_before"] for j in paired]),
        "score_after": _mean([j["score_after"] for j in paired]),
        "calls_per_judged_doc": _mean([float(s["judge"]["calls"]) for s in judged]),
        "judge_related_calls_per_judged_doc": _mean([float(s["judge"]["judge_calls"]) for s in judged]),
        "cost_per_judged_doc": {cls: _mean(v) for cls, v in sorted(costs.items())},
        **({"cached_prompt_tokens": sum(cached)} if cached else {}),
        "review_rate": _rate(sum(s["outcome"] == "review" for s in judged), len(judged)),
        "wrong_archive_rate": _rate(sum(s["outcome"] == "wrong_archive" for s in archived), len(archived)),
        "crashes": sum(s["outcome"] == "crashed" for s in judged),
        "matter_conflicts": sum(s["judge"]["conflict"] for s in judged),
        "governor_stops": dict(sorted(stops.items())),
        "docs": [s["id"] for s in judged],
    }


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
    if item is None:
        return out
    pred = item.get("pred") or {}  # an absent or empty prediction reads as before
    if not isinstance(pred, Mapping):
        # A malformed ``pred`` (hand-edited items.jsonl) is never read as an archive or a review:
        # the row stays ``crashed``, error row or not.
        return out
    if isinstance(pred.get("judge_reasks"), Mapping):
        # HF-002 / HF-013: a judge answer was asked twice. Read before the crash returns below: a document
        # the run returned as failed still made (and billed) its re-asks. A document that raises (the API
        # call guard stopped it, say) writes no item, so its re-asks are not counted: a lower bound.
        out["judge_reasks"] = _judge_reask_counts(pred["judge_reasks"])
    if pred.get("judge_rulings") and not (item.get("error") or item.get("ok") is False or pred.get("error")):
        _judge_fields(out, doc, pred, bars)
    elif pred.get("judge_rulings"):
        out["judge"] = {"rulings": [[int(r.get("pass") or 0), str(r.get("ruling") or "")]
                                    for r in pred["judge_rulings"] if isinstance(r, Mapping)],
                        "proposed": 0, "verified": 0, "applied": 0, "rejected": {}, "right": 0, "wrong": 0, "corrected": False,
                        "retries": sum(1 for r in pred["judge_rulings"] if isinstance(r, Mapping)
                                       and r.get("ruling") == "retry_fields"),
                        "score_before": None, "score_after": None,  # a crashed judged document has no score
                        # ...but the calls it made before the failure were made, and billed
                        "calls": _reask_count(item.get("llm_calls")),
                        "judge_calls": judge_related_calls(item, pred, doc.get("nodes") or ()),
                        "cost": doc_cost(item),
                        "cached_tokens": _reask_count(item.get("cached_tokens"))
                        if item.get("cached_tokens") is not None else None, "conflict": False}
    if item.get("error") or item.get("ok") is False or pred.get("error"):
        return out
    out["tokens"] = int(item.get("prompt_tokens") or 0) + int(item.get("completion_tokens") or 0)
    _governor_fields(out, pred)
    out["judge_error"] = "judge_error" in (pred.get("review_causes") or [])
    out["stage"] = "review" if pred.get("stage") == "review" else "archived"
    if out["stage"] == "archived":
        out["archived_class"] = str(pred.get("doc_type") or "").strip().lower() or None
        if isinstance(pred.get("arbiter_caveats"), Mapping):  # HF-014 marker: accepted with caveats
            out["arbiter_caveats"] = True
            out["caveats_hf014"] = bool(pred["arbiter_caveats"].get("hf014"))
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

    caveated = [s for s in statuses if s.get("arbiter_caveats")]
    reasked = [s for s in statuses if s.get("judge_reasks")]
    governor = _governor_block(statuses)
    judge = _judge_block(statuses)
    return {
        # Present only when a judge: section recorded rulings (phase 4, judge_record): rulings, fixes
        # and their accuracy, scores before and after the judge, calls, cost, outcomes and stops.
        **({"judge": judge} if judge else {}),
        # Present only when the loop governor acted (phase 2, job.governor): stops by reason and
        # outcome, duplicates linked instead of escalated (HF-019) and sorter retries skipped (L2).
        **({"governor": governor} if governor["docs"] else {}),
        # Present only when a judge answer that did not parse was asked once more (HF-002 / HF-013):
        # how often, and how each re-ask ended: ``recovered`` (second answer parsed), ``parked``
        # (it did not parse either: a judge error, counted under ``judge_errors`` above) or
        # ``errored`` (the second call raised; HF-012 may have re-run the node). Counts only; the
        # block carries no judge-call denominator, so the live parse-failure rate needs the run's
        # judge calls from its usage.
        **({"judge_reasks": _judge_reask_block(reasked)} if reasked else {}),
        # Present only when the run used llm-mailroom decision slots (job/gate_slots.py).
        **({"decision_slots": slots} if slots is not None else {}),
        # Present only when an archive was accepted with arbiter caveats (HF-014 marker). These
        # archives are scored like any other; ``hf014`` counts those the vendored route parked.
        **({"arbiter_caveats": {"archives": len(caveated),
                                "hf014": sum(1 for s in caveated if s.get("caveats_hf014")),
                                "docs": [s["id"] for s in caveated]}} if caveated else {}),
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
