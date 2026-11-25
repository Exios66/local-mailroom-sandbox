"""Post-run routing audit: did each escalation earn its cost, and are thresholds calibrated?

Offline and model-free; reads a finished run store (``nodes.jsonl``,
``items.jsonl``, ``dataset.jsonl``, ``spec.lock.json``). Per document class it
reports:

* **fire rates**: ``retry_classify``, ``judge_verify``, ``arbiter``,
  ``retry_extract`` and human review;
* **yield**: whether a retry changed anything (classification answer, judge
  verdict);
* **discrimination**: whether the documents that were escalated are the ones
  that needed it, comparing scored quality of judged and unjudged documents,
  and of parked and archived ones;
* **escalation input cost**: judge and arbiter calls priced at the vendored
  16k source window and at full-document coverage
  (``config/api_prices.yaml`` tiers);
* **threshold suggestions**: from the recorded gate inputs (sorter
  ``classification_confidence``, specialist ``extraction_confidence``) against
  each document's score.
* **above-band quality**: for each class, how many scored documents at or
  above ``judge_band_high`` met the target, with a 95% exact interval.

Suggestions are evidence, not settings. A run's thresholds change only through
its own ``confidence`` block, which is locked and hashed. Small samples are
labelled as such.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

VERDICT_RANK = {"incomplete": 0, "partial": 1, "complete": 2}
DEFAULT_TARGET = 0.7
MIN_DOCS = 5
_CHARS_PER_TOKEN = 2.4  # context_fit's conservative ratio: costs are upper bounds
_PROMPT_OVERHEAD_TOKENS = 8000
_VENDORED_WINDOW = 16000


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def effective_thresholds(lock_confidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The run's ``confidence`` block, merged in the order ``build_merged_taxonomy`` uses:
    vendored, taxonomy overlay, the ``config/components.yaml`` routing overlay, then the run lock.

    Preflight freezes this block and a locked activation replaces the runtime block with it, so
    a layer missing here would silently change a locked run's routing.
    """
    from mailroom_sandbox.components import load_components, routing_overlay
    from mailroom_sandbox.overlay import deep_merge, load_yaml, mailroom_taxonomy_path
    from mailroom_sandbox.paths import config_dir

    block = deep_merge(load_yaml(mailroom_taxonomy_path()).get("confidence") or {},
                       load_yaml(config_dir() / "taxonomy.overlay.yaml").get("confidence") or {})
    block = deep_merge(block, routing_overlay(load_components()).get("confidence") or {})
    return deep_merge(block, dict(lock_confidence or {}))


# Keys the taxonomy overlay's retry-budget block set (HF-011/HF-012 routing). A lock written
# before preflight froze ``effective_confidence`` never saw them, so on resume they fall back
# to the vendored + components value (absent keys stay absent, which leaves HF-011/HF-012 inert).
OVERLAY_RETRY_KEYS = ("retry_max", "arbiter_retry_max", "judge_max_passes",
                      "transient_retry_max", "judge_exhausted_to_arbiter")


def legacy_thresholds(lock_confidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The confidence block for a lock with no frozen ``effective_confidence``.

    As ``effective_thresholds``, but the overlay's retry-budget keys keep the value the run
    had before they existed (vendored, then ``config/components.yaml``), unless the run's own
    ``confidence`` block sets them. Use it as a replacement block, not an overlay to merge.
    """
    from mailroom_sandbox.components import load_components, routing_overlay
    from mailroom_sandbox.overlay import deep_merge, load_yaml, mailroom_taxonomy_path

    explicit = dict(lock_confidence or {})
    before = deep_merge(load_yaml(mailroom_taxonomy_path()).get("confidence") or {},
                        routing_overlay(load_components()).get("confidence") or {})
    block = effective_thresholds(explicit)
    for key in OVERLAY_RETRY_KEYS:
        if key in explicit:
            continue
        if key in before:
            block[key] = before[key]
        else:
            block.pop(key, None)
    return block


def _unknown_unless_explicit(block: Mapping[str, Any], explicit: Mapping[str, Any], key: str) -> dict[str, Any]:
    """``block`` with ``key`` set to ``None`` (unknown) wherever the run did not set it itself."""
    out = {k: v for k, v in block.items() if k != "by_class"}
    out[key] = explicit.get(key)
    by_explicit = explicit.get("by_class") or {}
    out["by_class"] = {cls: {**dict(vals), key: (by_explicit.get(cls) or {}).get(key, explicit.get(key))}
                       for cls, vals in (block.get("by_class") or {}).items()}
    return out


def thresholds_for(block: Mapping[str, Any], doc_class: str) -> dict[str, Any]:
    base = {k: v for k, v in block.items() if k != "by_class"}
    return {**base, **((block.get("by_class") or {}).get(doc_class) or {})}


def _answers(seq: list[dict[str, Any]], node_names: tuple[str, ...], question: str) -> list[dict[str, Any]]:
    return [d for n in seq if n.get("node") in node_names
            for d in n.get("decisions") or [] if d.get("question") == question]


def _recorded_windows(extracted: Any) -> list[tuple[float, int]]:
    """``(confidence, character length)`` per chunk window HF-008 recorded; windows missing either are skipped."""
    if not isinstance(extracted, Mapping):
        return []
    confidences = extracted.get("_window_confidences") or []
    lengths = extracted.get("_window_lengths") or []
    return [(float(c), int(n)) for c, n in zip(confidences, lengths)
            if _number(c) is not None and _number(n) is not None]


def _window_agreement(extracted: Any) -> float | None:
    """The HF-008 cross-window agreement of a chunked extraction, when recorded."""
    if not isinstance(extracted, Mapping):
        return None
    block = extracted.get("_window_agreement")
    if not isinstance(block, Mapping):
        return None
    value = _number(block.get("agreement"))
    return float(value) if value is not None else None


def _failed_windows(extracted: Any) -> int:
    """Chunk windows whose call failed (``_failed_chunks``); their confidence was never recorded."""
    n = _number(extracted.get("_failed_chunks")) if isinstance(extracted, Mapping) else None
    return int(n) if n is not None else 0


def _doc_records(nodes: Iterable[Mapping[str, Any]], items: Mapping[str, Mapping[str, Any]],
                 rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        if n.get("status") == "done":
            by_doc[str(n.get("doc"))].append(dict(n))
    out = []
    for doc_id, row in rows.items():
        seq = sorted(by_doc.get(doc_id, []), key=lambda n: float(n.get("ts") or 0))
        item = items.get(doc_id) or {}
        pred, score = item.get("pred") or {}, item.get("score") or {}
        quality = score.get("overall_extraction_score")
        out.append({
            "id": doc_id,
            "class": str(row.get("expected_doc_class") or "unknown"),
            "chars": len(str(row.get("doc_text") or "")),
            "nodes": [n.get("node") for n in seq],
            "classify": [(d.get("answer"), d.get("p")) for d in _answers(seq, ("classify", "retry_classify"), "doc_type")],
            "extraction_confidence": [d.get("p") for d in _answers(seq, ("extract", "retry_extract"), "extraction_confidence")],
            "verdicts": [d.get("answer") for d in _answers(seq, ("judge_verify",), "extraction_verdict")],
            "arbiter": [d.get("answer") for d in _answers(seq, ("arbiter",), "arbiter_route")],
            "stage": pred.get("stage"),
            "final_extraction_confidence": pred.get("extraction_confidence"),
            # A pipeline item nests the extraction; an isolated specialist item is the extraction.
            "windows": _recorded_windows(pred.get("extracted_data", pred)),
            "failed_windows": _failed_windows(pred.get("extracted_data", pred)),
            "window_agreement": _window_agreement(pred.get("extracted_data", pred)),
            "quality": float(quality) if isinstance(quality, (int, float)) and not isinstance(quality, bool) else None,
        })
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _retry_yield(verdicts: list[str]) -> tuple[int, int]:
    """(retries followed by a judge, of which the verdict improved)."""
    ranks = [VERDICT_RANK.get(v, -1) for v in verdicts]
    pairs = list(zip(ranks, ranks[1:]))
    return len(pairs), sum(1 for a, b in pairs if b > a)


def _escalation_cost(docs: list[dict[str, Any]], model: str | None) -> dict[str, float | None]:
    from mailroom_sandbox.job.metrics import call_cost

    def priced(window: int | None) -> float | None:
        total = 0.0
        for doc in docs:
            calls = doc["nodes"].count("judge_verify") + doc["nodes"].count("arbiter")
            if not calls:
                continue
            chars = doc["chars"] if window is None else min(doc["chars"], window)
            cost = call_cost(model, calls * (chars / _CHARS_PER_TOKEN + _PROMPT_OVERHEAD_TOKENS), 0, calls=calls)
            if cost is None:
                return None
            total += cost
        return round(total, 4)

    return {"at_vendored_16k_usd": priced(_VENDORED_WINDOW), "at_full_document_usd": priced(None)}


def suggest_judge_band_high(docs: list[dict[str, Any]], *, target: float = DEFAULT_TARGET) -> dict[str, Any]:
    """Lowest first-pass confidence above which every scored document met ``target``.

    Documents at or above the suggestion could skip the judge without archiving
    a below-target extraction in this sample. A retried extraction is left out: its
    score is the retry's, not the first pass's. Fewer than ``MIN_DOCS`` scored
    documents with a recorded confidence gives no suggestion.
    """
    pairs = sorted((conf, quality) for d in docs
                   if (conf := _first_confidence(d)) is not None and (quality := _first_pass_quality(d)) is not None)
    if len(pairs) < MIN_DOCS:
        return {"suggestion": None, "basis": f"{len(pairs)} scored document(s) with a recorded extraction_confidence; need {MIN_DOCS}"}
    for i, (conf, _) in enumerate(pairs):
        if all(q >= target for _, q in pairs[i:]):
            return {"suggestion": round(conf, 4), "would_judge": i, "of": len(pairs),
                    "basis": f"every document at confidence >= {conf:.3f} scored >= {target}"}
    return {"suggestion": None, "basis": f"the most confident document scored below {target}: confidence does not separate quality"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _first_confidence(doc: Mapping[str, Any]) -> float | None:
    """First-pass extraction confidence, or None when the decision recorded no number."""
    confidences = doc.get("extraction_confidence") or []
    return _number(confidences[0]) if confidences else None


def _first_pass_quality(doc: Mapping[str, Any]) -> float | None:
    """Quality of the first extraction, or None when a retry replaced it.

    A retried document's score belongs to the retry. Pairing it with the first
    confidence would credit a skipped judge with a retry that would never have run.
    """
    return None if len(doc.get("extraction_confidence") or []) > 1 else _number(doc.get("quality"))


def _quality_above(doc: Mapping[str, Any], threshold: float) -> float | None:
    confidence, quality = _first_confidence(doc), _first_pass_quality(doc)
    if confidence is None or quality is None or confidence < threshold:
        return None
    return quality


def above_band_quality(docs: list[dict[str, Any]], band: Any, *, target: float = DEFAULT_TARGET) -> dict[str, Any]:
    """Accuracy of scored documents whose first extraction confidence is at or above ``band``.

    The interval is the same two-sided exact interval the gold audit uses. A
    class with no scored document above the band, or a run with no numeric
    ``judge_band_high``, returns a null rate. This is the table a labelled run
    records; it does not choose the band.
    """
    from mailroom_sandbox.gold_audit import clopper_pearson_interval

    threshold = _number(band)
    if threshold is None:
        return {"band": None, "target": target, "n": 0, "met_target": 0, "rate": None, "ci95": None}
    qualities = [quality for doc in docs if (quality := _quality_above(doc, threshold)) is not None]
    met = sum(quality >= target for quality in qualities)
    n = len(qualities)
    if n == 0:
        return {"band": threshold, "target": target, "n": 0, "met_target": 0, "rate": None, "ci95": None}
    lower, upper = clopper_pearson_interval(met, n)
    return {"band": threshold, "target": target, "n": n, "met_target": met,
            "rate": round(met / n, 4), "ci95": [round(lower, 4), round(upper, 4)]}


def compare_window_rules(windows: list[tuple[float, int]]) -> dict[str, Any]:
    """Compare the three recorded-window merge rules. The adopted rule stays the weakest window.

    ``windows`` is ``(confidence, character length)`` for each surviving window.
    Length-weighted uses those lengths. A labelled long-document comparison is
    what can replace ``adopted``; this checkout does not contain one.
    """
    if not windows:
        raise ValueError("no windows")
    confidences = [float(confidence) for confidence, _length in windows]
    weights = [max(int(length), 0) for _confidence, length in windows]
    total = sum(weights)
    weighted = sum(c * w for c, w in zip(confidences, weights, strict=True)) / total if total else sum(confidences) / len(confidences)
    return {"min": min(confidences), "max": max(confidences),
            "length_weighted": round(weighted, 4), "adopted": "min"}


def _auroc(met: list[float], missed: list[float]) -> float | None:
    """Chance a document that met the target has the higher confidence (ties count half)."""
    if not met or not missed:
        return None
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in met for b in missed)
    return round(wins / (len(met) * len(missed)), 4)


def _chunked_and_scored(doc: Mapping[str, Any]) -> bool:
    # A document that lost a window ranks the rules on the surviving windows only: its min
    # and length-weighted confidence describe a merge the scorer never saw, so it is left out.
    return (len(doc.get("windows") or []) >= 2 and _number(doc.get("quality")) is not None
            and not doc.get("failed_windows"))


def window_rule_separation(docs: list[dict[str, Any]], *, target: float = DEFAULT_TARGET) -> dict[str, Any]:
    """How well each merge rule's confidence separates documents that met ``target`` from those that did not.

    Only scored documents with two or more recorded windows and no failed window
    count; ``partial_excluded`` counts the scored documents left out for a failed
    window. AUROC is 1.0
    when every met-target document outranks every miss, 0.5 for no separation,
    and null when one group is empty. The adopted rule stays ``min``; this is
    the labelled comparison that could replace it.
    """
    scored = [(compare_window_rules(d["windows"]), d["quality"]) for d in docs if _chunked_and_scored(d)]
    met = [rules for rules, quality in scored if quality >= target]
    missed = [rules for rules, quality in scored if quality < target]
    auroc = {rule: _auroc([r[rule] for r in met], [r[rule] for r in missed])
             for rule in ("min", "max", "length_weighted")}
    # The HF-008 cross-window agreement is doc-level, not a per-window rule: it
    # ranks only the chunked-and-scored documents that recorded one. Self-reported
    # confidence is not in this table (#214: AUROC 0.36-0.47, no signal).
    agreed = [(d["window_agreement"], d["quality"]) for d in docs
              if _chunked_and_scored(d) and d.get("window_agreement") is not None]
    auroc["agreement"] = _auroc([a for a, q in agreed if q >= target],
                                [a for a, q in agreed if q < target])
    partial = sum(1 for d in docs if d.get("failed_windows") and _number(d.get("quality")) is not None)
    return {"n": len(scored), "met_target": len(met), "target": target, "auroc": auroc, "adopted": "min",
            "partial_excluded": partial}


def _class_report(cls: str, docs: list[dict[str, Any]], thresholds: Mapping[str, Any], *,
                  model: str | None, target: float, pipeline: bool = True) -> dict[str, Any]:
    nodes = Counter(n for d in docs for n in d["nodes"])
    verdicts = Counter(v for d in docs for v in d["verdicts"])
    arbiter = Counter(a for d in docs for a in d["arbiter"])
    judged = [d for d in docs if "judge_verify" in d["nodes"]]
    unjudged = [d for d in docs if "judge_verify" not in d["nodes"]]
    retries, improved = map(sum, zip(*[_retry_yield(d["verdicts"]) for d in docs])) if docs else (0, 0)
    classify_retries = classify_changed = 0
    sorter_p = []
    for d in docs:
        sorter_p += [p for _, p in d["classify"] if isinstance(p, (int, float))]
        for prev, cur in zip(d["classify"], d["classify"][1:]):
            classify_retries += 1
            classify_changed += prev != cur
    q = lambda group: _mean([d["quality"] for d in group if d["quality"] is not None])  # noqa: E731
    report: dict[str, Any] = {
        "docs": len(docs),
        "thresholds": {k: thresholds.get(k) for k in ("high", "low", "judge_band_high", "arbiter_retry_max",
                                                     "judge_max_passes", "judge_rejudge_retry", "retry_max",
                                                     "transient_retry_max", "judge_exhausted_to_arbiter")},
        "fires": {k: nodes.get(k, 0) for k in ("retry_classify", "judge_verify", "arbiter", "retry_extract")},
        "judged_docs": len(judged),
        "review_docs": sum(1 for d in docs if d["stage"] == "review"),
        "verdicts": dict(verdicts),
        "arbiter_decisions": dict(arbiter),
        "retry_yield": {"retries_rejudged": retries, "verdict_improved": improved},
        "retry_classify_yield": {"retries": classify_retries, "changed": classify_changed},
        "sorter_confidence_max": max(sorter_p) if sorter_p else None,
        "quality": {"judged": q(judged), "unjudged": q(unjudged),
                    "parked": q([d for d in docs if d["stage"] == "review"]),
                    "archived": q([d for d in docs if d["stage"] == "archived"])},
        "escalation_input_cost": _escalation_cost(docs, model),
        "judge_band_high": suggest_judge_band_high(docs, target=target),
        "above_band": above_band_quality(docs, thresholds.get("judge_band_high"), target=target),
        "window_rules": window_rule_separation(docs, target=target),
        "findings": [],
    }
    report["findings"] = _findings(cls, report, thresholds, target, pipeline=pipeline)
    return report


def _findings(cls: str, r: Mapping[str, Any], th: Mapping[str, Any], target: float, *,
              pipeline: bool = True) -> list[str]:
    out: list[str] = []
    judge_calls = r["fires"]["judge_verify"]
    if judge_calls >= 3 and r["verdicts"].get("complete", 0) / judge_calls < 0.1:
        out.append(f"{cls}: the judge passed {r['verdicts'].get('complete', 0)}/{judge_calls} calls; a judge that "
                   "almost never says complete triggers the arbiter loop unconditionally. Check source coverage "
                   "(context_plan) and the judge before paying for more passes")
    ry = r["retry_yield"]
    if ry["retries_rejudged"] >= 3 and ry["verdict_improved"] == 0:
        out.append(f"{cls}: {ry['retries_rejudged']} arbiter-ordered retries improved no judge verdict; lower "
                   "confidence.by_class arbiter_retry_max (and judge_max_passes = 1 + it) for this model")
    cy = r["retry_classify_yield"]
    high, top = th.get("high"), r["sorter_confidence_max"]
    if cy["retries"] >= 3 and cy["changed"] == 0 and high is not None and top is not None and top < high:
        out.append(f"{cls}: {cy['retries']} retry_classify passes returned the same answer; the sorter's highest "
                   f"confidence ({top}) sits below high ({high}), so every document retries. Set "
                   f"confidence.by_class.{cls}.high <= {top} for this model if the reviewer lane stays on")
    qual = r["quality"]
    # An isolated specialist run has no judge, so an unjudged low mean says nothing about the band.
    if pipeline and r["judged_docs"] == 0 and qual["unjudged"] is not None and qual["unjudged"] < target:
        out.append(f"{cls}: no document was judged, yet mean quality is {qual['unjudged']} (< {target}); the "
                   "self-reported confidence cleared judge_band_high without tracking quality")
    if r["review_docs"] and qual["parked"] is not None and qual["archived"] is not None and qual["parked"] >= qual["archived"]:
        out.append(f"{cls}: parked documents score {qual['parked']} vs archived {qual['archived']}; review is "
                   "catching the wrong documents")
    return out


def audit(run_dir: Path | str, *, target: float = DEFAULT_TARGET) -> dict[str, Any]:
    """The routing audit for one run store."""
    root = Path(run_dir)
    lock_path = root / "spec.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
    rows = {str(r.get("id")): r for r in _jsonl(root / "dataset.jsonl")}
    items = {str(i.get("item_id")): i for i in _jsonl(root / "items.jsonl")}
    docs = _doc_records(_jsonl(root / "nodes.jsonl"), items, rows)
    if isinstance(lock.get("effective_confidence"), Mapping):
        block, source = dict(lock["effective_confidence"]), "locked"
    else:
        # An older run froze only its explicit overrides. Fill the numeric thresholds from the
        # current config, but never report today's default as the run's rejudge setting.
        block, source = legacy_thresholds(lock.get("confidence")), "current_config"
        block = _unknown_unless_explicit(block, lock.get("confidence") or {}, "judge_rejudge_retry")
    assignments = lock.get("agent_assignments") or {}
    model = ((assignments.get("judge") or {}).get("model")
             or ((lock.get("agent_routes") or {}).get("judge") or {}).get("model")
             or (lock.get("engine") or {}).get("model"))
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in docs:
        by_class[d["class"]].append(d)
    pipeline = (root / "nodes.jsonl").is_file()
    classes = {cls: _class_report(cls, group, thresholds_for(block, cls), model=model, target=target,
                                  pipeline=pipeline)
               for cls, group in sorted(by_class.items())}
    recorded = sum(1 for d in docs if d["extraction_confidence"])
    notes = []
    if not pipeline:
        notes.append("isolated specialist run (no nodes.jsonl): routing fires, verdicts and judge bands do not "
                     "apply; window_rules reads the chunk windows on each prediction")
    elif docs and not recorded:
        notes.append("no extraction_confidence was recorded (runs before the routing audit); judge_band_high "
                     "suggestions need a run that records it")
    if docs and len(docs) < 50:
        notes.append(f"{len(docs)} documents: treat fire rates and suggestions as directional, not calibrated")
    return {"run_id": lock.get("run_id") or root.name, "target_quality": target, "judge_model": model,
            "thresholds_source": source,
            "docs": len(docs), "classes": classes,
            "findings": [f for c in classes.values() for f in c["findings"]], "notes": notes}
