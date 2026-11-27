"""Offline replay of Phase 5 part 1 on a finished pipeline run: best-attempt selection and the evidence check.

No model call and nothing written to the run. For each document the run stored (``items.jsonl``,
whose ``pred`` is the graph's final state with every extraction attempt), it scores three versions
with the gate's own scorer (``pair_report._score``, the Dojo headline score):

* **latest**: the extraction the run kept, which is what it scored;
* **selected** (A): the attempt the vendored #254 selection keeps with ``confidence.keep_best_attempt``
  on, through ``graph.build_graph._attempt_selection`` itself, ``for_archive`` for an archived document,
  so an unsure or below-floor earlier attempt is never put in the archive. The run's lock is
  activated with the flag forced on, so the thresholds are the run's own. Routing never reads the
  flag, so this is exact;
* **filtered** (B): the latest extraction through :func:`mailroom_sandbox.evidence_check.filter_one_read`.
  This is an estimate: the run's judge rated the unfiltered extraction, so routing could differ.

Contracts also get CUAD false and missed clauses (``score_cuad``, as ``gate_causes`` counts them),
before and after the filter. :func:`selection_meets` and :func:`evidence_meets_confirming_arm` apply
the design's adoption bars (``docs/design/specs/2026-11-27-phase5-attempt-hygiene-design.md``).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

LABEL = "offline replay (estimate)"
MIN_CLASS_N = 10  # a class with fewer scored documents cannot veto selection
FP_DROP = 0.25  # B: CUAD false clauses must fall by at least this share
FN_RISE_PER_100 = 2.0  # B: CUAD missed clauses may rise by at most this many per 100 contracts


class ReplayError(RuntimeError):
    """A replay that cannot give trustworthy numbers."""


def _forced_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    """The run's lock with ``keep_best_attempt`` on for every class (its own thresholds otherwise)."""
    from mailroom_sandbox.job.routing_audit import legacy_thresholds

    forced = deepcopy(dict(lock))
    block = deepcopy(forced.get("effective_confidence") or legacy_thresholds(forced.get("confidence")))
    block["keep_best_attempt"] = True
    for cls_block in (block.get("by_class") or {}).values():
        if isinstance(cls_block, dict):
            cls_block.pop("keep_best_attempt", None)
    forced["effective_confidence"] = block
    return forced


def _activate(lock: Mapping[str, Any]) -> None:
    from mailroom_sandbox import runtime

    profile = lock.get("profile")
    if not profile:
        raise ReplayError("the run's lock names no profile, so its thresholds cannot be activated")
    with runtime.locked_runtime(_forced_lock(lock), {}):
        runtime.activate(str(profile), load_env_file=False)


def _cuad(row: Mapping[str, Any], extracted: Mapping[str, Any]) -> tuple[int, int] | None:
    """``(false, missed)`` CUAD clause categories of one contract extraction, or None when unscorable."""
    from mailroom_sandbox.eval.cuad_scoring import score_cuad
    from mailroom_sandbox.eval.extraction_scope import scope_extraction_pair
    from mailroom_sandbox.job.gate import _UNIT_FIELD, _unit_labels
    from mailroom_sandbox.job.pair_report import _fields

    labels = _unit_labels(_fields(row).get(_UNIT_FIELD["contract"]))
    if not labels:
        return None
    predicted, _ = scope_extraction_pair("contract", dict(extracted), {})
    try:
        scored = score_cuad(predicted, labels)
    except Exception:  # noqa: BLE001 - counted as unscorable, never a silent zero
        return None
    return int(scored.get("cuad_fp") or 0), int(scored.get("cuad_fn") or 0)


def _document(row: Mapping[str, Any], pred: Mapping[str, Any]) -> dict[str, Any] | None:
    from graph.build_graph import _attempt_selection

    from mailroom_sandbox import evidence_check
    from mailroom_sandbox.job.pair_report import TEMPLATED_FIELDS, _score, without_fields

    cls = str(row.get("expected_doc_class") or "")
    scored_row = without_fields(row, TEMPLATED_FIELDS.get(cls, ()))
    latest = dict(pred.get("extracted_data") or {})
    archived = pred.get("stage") != "review"
    selection = _attempt_selection(pred, for_archive=archived)
    selected = selection.get("extracted_data", latest)
    text = pred.get("doc_text") or row.get("doc_text")
    filtered = evidence_check.filter_one_read(latest, text)
    q_latest = _score(scored_row, {**pred, "extracted_data": latest})
    if q_latest is None:
        return None
    doc: dict[str, Any] = {
        "id": str(row.get("id")), "class": cls, "stage": "archived" if archived else "review",
        "selection_reason": selection.get("selected_attempt_reason"),
        "selection_changed": "extracted_data" in selection and selected != latest,
        "latest_quality": q_latest,
        "selected_quality": _score(scored_row, {**pred, "extracted_data": selected}),
        "filtered_quality": _score(scored_row, {**pred, "extracted_data": filtered}),
        "dropped": {f: len(v) for f, v in (filtered.get("_evidence_dropped") or {}).items()}
        if filtered is not latest else {},
        "would_empty": filtered.get("_evidence_skipped") == "would_empty",
        "text_from_row": not pred.get("doc_text"),
    }
    if cls == "contract":
        before, after = _cuad(row, latest), _cuad(row, filtered)
        if before is not None and after is not None:
            doc.update(cuad_fp_before=before[0], cuad_fn_before=before[1],
                       cuad_fp_after=after[0], cuad_fn_after=after[1])
    return doc


def _mean(values: list[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return round(sum(kept) / len(kept), 4) if kept else None


def _selection_block(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"scored_n": len(docs), "latest": _mean([d["latest_quality"] for d in docs]),
            "selected": _mean([d["selected_quality"] for d in docs]),
            "changed": sum(1 for d in docs if d["selection_changed"]),
            "reasons": dict(sorted(Counter(str(d["selection_reason"]) for d in docs).items()))}


def _evidence_block(docs: list[dict[str, Any]]) -> dict[str, Any]:
    dropped: Counter[str] = Counter()
    for d in docs:
        dropped.update(d["dropped"])
    block: dict[str, Any] = {"scored_n": len(docs), "before": _mean([d["latest_quality"] for d in docs]),
                             "after": _mean([d["filtered_quality"] for d in docs]),
                             "dropped": dict(sorted(dropped.items())),
                             "would_empty": sum(1 for d in docs if d["would_empty"])}
    cuad = [d for d in docs if "cuad_fp_before" in d]
    if cuad:
        block["cuad_n"] = len(cuad)
        for key in ("cuad_fp_before", "cuad_fp_after", "cuad_fn_before", "cuad_fn_after"):
            block[key] = sum(d[key] for d in cuad)
    return block


def selection_meets(selection: Mapping[str, Any]) -> bool:
    """A: higher overall, and no class with at least ``MIN_CLASS_N`` scored documents lower."""
    overall = selection.get("overall") or {}
    if overall.get("latest") is None or overall.get("selected") is None or overall["selected"] <= overall["latest"]:
        return False
    for block in (selection.get("by_class") or {}).values():
        if (block.get("scored_n") or 0) >= MIN_CLASS_N and (block.get("selected") or 0) < (block.get("latest") or 0):
            return False
    return True


def evidence_meets_confirming_arm(evidence: Mapping[str, Any]) -> bool:
    """B: CUAD false clauses fall by at least ``FP_DROP``, missed rise by at most ``FN_RISE_PER_100`` per 100,
    and no class with at least ``MIN_CLASS_N`` scored documents loses filtered quality."""
    for block in (evidence.get("by_class") or {}).values():
        before, after = block.get("before"), block.get("after")
        if (block.get("scored_n") or 0) >= MIN_CLASS_N and before is not None and after is not None and after < before:
            return False
    contract = (evidence.get("by_class") or {}).get("contract") or {}
    n = contract.get("cuad_n", contract.get("scored_n")) or 0
    fp_before = contract.get("cuad_fp_before") or 0
    if not n or not fp_before:
        return False
    fp_drop = (fp_before - (contract.get("cuad_fp_after") or 0)) / fp_before
    fn_rise = ((contract.get("cuad_fn_after") or 0) - (contract.get("cuad_fn_before") or 0)) * 100.0 / n
    return fp_drop >= FP_DROP and fn_rise <= FN_RISE_PER_100


def replay(run: str | Path, *, runs_root: Path | None = None, activate: bool = True) -> dict[str, Any]:
    """The replay of one finished run (JSON-serializable); the run directory is only read."""
    from mailroom_sandbox import rescore
    from mailroom_sandbox.job.pair_report import _failed, load_arm

    files = rescore.locate(run, runs_root=runs_root)
    lock = json.loads(files.files["spec.lock.json"].read_text(encoding="utf-8"))
    if lock.get("task") not in (None, "pipeline"):
        raise ReplayError(f"task {lock.get('task')!r} runs no graph extraction: nothing to replay")
    if (lock.get("judge") or {}).get("mode") == "correct":
        # HF-025 writes verified fixes into extracted_data but not into the attempt history, so a
        # restored attempt would drop them: the combination the run spec refuses.
        raise ReplayError("judge.mode correct: keep_best_attempt is refused with it, so selection cannot be "
                          "replayed (the attempt history does not hold the judge's fixes)")
    if activate:
        _activate(lock)
    arm = load_arm(files.path)
    skipped: Counter[str] = Counter()
    docs: list[dict[str, Any]] = []
    human = 0
    for entry in arm.values():
        item = entry["item"] or {}
        pred = item.get("pred")
        if not isinstance(pred, Mapping) or not isinstance(pred.get("extracted_data"), Mapping):
            skipped["no_pred"] += 1
            continue
        if _failed(item):
            # The gate scores an unfinished document 0 whatever it extracted (SHF-011), and the
            # graph never selected or reviewed it: no evidence for either change.
            skipped["failed"] += 1
            continue
        doc = _document(entry["row"], pred)
        if doc is None:
            skipped["no_labels"] += 1
            continue
        human += pred.get("extraction_source") == "human"
        docs.append(doc)
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in docs:
        by_class[d["class"]].append(d)
    selection = {"overall": _selection_block(docs),
                 "by_class": {c: _selection_block(g) for c, g in sorted(by_class.items())}}
    evidence = {"overall": _evidence_block(docs),
                "by_class": {c: _evidence_block(g) for c, g in sorted(by_class.items())}}
    return {
        "label": LABEL,
        "run_id": lock.get("run_id") or files.path.name,
        "counts": {"items": len(arm), "scored_n": len(docs), "skipped": dict(sorted(skipped.items())),
                   "human_source": human, "text_from_row": sum(1 for d in docs if d["text_from_row"])},
        "selection": selection,
        "evidence": evidence,
        "bars": {"selection_meets": selection_meets(selection),
                 "evidence_meets_confirming_arm": evidence_meets_confirming_arm(evidence)},
        "documents": docs,
    }


def default_output(run_id: str, *, runs_root: Path | None = None) -> Path:
    """Where the script writes a replay by default: beside the run store, never inside a run."""
    if runs_root is None:
        from mailroom_sandbox.job.spec import runs_root as _root

        runs_root = _root()
    return Path(runs_root).parent / "replays" / f"{run_id}.attempt_replay.json"


def write_replay(result: Mapping[str, Any], path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def digest(result: Mapping[str, Any], path: Path | str | None = None) -> str:
    """A short text summary: counts, per-class lines, the bars and where the full result is."""
    c = result["counts"]
    lines = [f"{result['label']}: run {result['run_id']}",
             f"items {c['items']}, scored_n {c['scored_n']}, skipped {c['skipped'] or 'none'}, "
             f"human-sourced {c['human_source']}"]

    def row(name: str, sel: Mapping[str, Any], ev: Mapping[str, Any]) -> str:
        text = (f"  {name}: n {sel['scored_n']} | A latest {sel['latest']} -> selected {sel['selected']} "
                f"({sel['changed']} changed) | B {ev['before']} -> {ev['after']}, dropped {ev['dropped'] or 0}")
        if "cuad_n" in ev:
            text += (f", CUAD false {ev['cuad_fp_before']} -> {ev['cuad_fp_after']}, "
                     f"missed {ev['cuad_fn_before']} -> {ev['cuad_fn_after']}")
        return text

    lines.append(row("overall", result["selection"]["overall"], result["evidence"]["overall"]))
    for cls, sel in result["selection"]["by_class"].items():
        lines.append(row(cls, sel, result["evidence"]["by_class"][cls]))
    bars = result["bars"]
    lines.append(f"bars: A selection meets {bars['selection_meets']}; B confirming arm warranted "
                 f"{bars['evidence_meets_confirming_arm']}")
    if path is not None:
        lines.append(f"full result: {path}")
    return "\n".join(lines)
