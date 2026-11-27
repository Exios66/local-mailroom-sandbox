"""Step-up verdict on the new documents and offline threshold evidence for the production slice gate.

Offline and read-only; the outcomes are the gate's own (``job/gate.py``), so these numbers match it.

``step_up(prev_dir, next_dir, bars)`` compares two slice runs. The new documents (in ``next``, not in
``prev``) are the only ones whose outcomes decide the step-up: ``new_docs_gate`` is ``gate_report``
restricted to them (``only_ids``), ``shared_paired`` is ``pair_report.paired_report`` over the shared
documents (diagnostic: has the run's behaviour on the old documents moved). ``nested`` is whether every
``prev`` document is in ``next``; a step-up between slices that do not nest fails, because "new
documents" is then not a fresh sample on top of the old one. The verdict is the new-documents gate
verdict plus the reasons ``"slices do not nest"`` and ``"no new documents"``.

``rerun(prev_dir, next_dir, bars)`` is the fix loop's paired check on the SAME slice: both runs gated on
the same documents, failing when the re-run's wrong-archive rate, review rate, crashes or ``judge_error``
rose. ``sandbox run gate --prev-run-id`` picks it when the two runs drew the same documents.

``threshold_evidence(run_dir, bars)`` replays, per gated class and pooled, the threshold-only decision
"an archived document with ``extraction_confidence < t`` would have gone to the judge". It never calls
a judge, so ``wrong_archives_caught_upper_bound`` assumes the judge rejects every wrong archive it
sees (``LABEL``). ``extra_judged`` counts every archived document under ``t`` (unscorable archives
included, they cost a judge call too); the other two count the gate's ``wrong_archive`` and
``correct_archive`` outcomes. An archived document without a numeric ``extraction_confidence`` cannot be
placed against any ``t``: it is counted under ``no_confidence`` (total and by outcome), never dropped
silently and never in the threshold counts. Each threshold row also projects the gate's pooled
``wrong_archive_rate`` and ``review_rate`` (and the worst-case ``review_rate_if_disturbed_rejected``) under
the same upper-bound assumption, next to each block's ``baseline`` rates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from mailroom_sandbox.job import gate
from mailroom_sandbox.job.gate import Bars
from mailroom_sandbox.job.pair_report import _jsonl, paired_report

DEFAULT_GRID: tuple[float, ...] = (0.90, 0.92, 0.94, 0.96, 0.98, 1.01)
LABEL = "upper bound: assumes the judge rejects every caught wrong archive"


def _ids(run_dir: Path) -> list[str]:
    return [str(row.get("id")) for row in _jsonl(Path(run_dir) / "dataset.jsonl")]


def same_documents(prev_dir: Path, next_dir: Path) -> bool:
    """Whether two runs drew exactly the same documents (a re-run, not a step-up)."""
    return set(_ids(Path(prev_dir))) == set(_ids(Path(next_dir)))


def step_up(prev_dir: Path, next_dir: Path, bars: Bars, *, traces_dir: Path | None = None,
            archive_dir: Path | None = None, audit: bool = True) -> dict[str, Any]:
    """The step-up from ``prev_dir`` to ``next_dir``: gate on the new documents, paired report on the shared ones."""
    prev_dir, next_dir = Path(prev_dir), Path(next_dir)
    prev_ids, next_ids = _ids(prev_dir), _ids(next_dir)
    in_prev, in_next = set(prev_ids), set(next_ids)
    new_docs = [doc_id for doc_id in next_ids if doc_id not in in_prev]
    nested = in_prev <= in_next
    new_gate = gate.gate_report(next_dir, bars, traces_dir=traces_dir, archive_dir=archive_dir, audit=audit,
                                only_ids=new_docs)
    reasons = list(new_gate["verdict"]["reasons"])
    if not new_docs:
        reasons.append("no new documents")
    if not nested:
        reasons.append("slices do not nest")
    return {"prev": prev_dir.name, "next": next_dir.name, "new_docs": new_docs, "nested": nested,
            "new_docs_gate": new_gate, "shared_paired": paired_report(prev_dir, next_dir),
            "verdict": {"pass": not reasons, "reasons": reasons}}


def rerun(prev_dir: Path, next_dir: Path, bars: Bars, *, traces_dir: Path | None = None,
          archive_dir: Path | None = None, audit: bool = True) -> dict[str, Any]:
    """A fix re-run of the same slice: paired on the same documents, kept only when it is not worse.

    Both runs are gated on the shared documents. The re-run fails when it drew different documents,
    or when its pooled wrong-archive rate, review rate, crash count or ``judge_error`` count is above
    the earlier run's. The re-run's own gate verdict is separate and still applies.
    """
    prev_dir, next_dir = Path(prev_dir), Path(next_dir)
    in_prev, in_next = set(_ids(prev_dir)), set(_ids(next_dir))
    shared = sorted(in_prev & in_next)
    kwargs = {"traces_dir": traces_dir, "archive_dir": archive_dir, "audit": audit, "only_ids": shared}
    before = gate.gate_report(prev_dir, bars, **{**kwargs, "audit": False})["pooled"]
    after = gate.gate_report(next_dir, bars, **kwargs)["pooled"]
    reasons = [] if in_prev == in_next else ["re-run drew different documents"]
    paired = paired_report(prev_dir, next_dir)
    mismatch = list(paired.get("label_mismatch") or [])
    if mismatch:
        # Same ids, different gold: the rates below would compare the label change, not the fix.
        reasons.append(f"re-run labels differ on {len(mismatch)} document(s): {', '.join(mismatch[:10])}")
    for key in ("wrong_archive_rate", "review_rate", "crashes", "judge_errors"):
        old, new = before.get(key), after.get(key)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new > old:
            shown = f"{old:.3f} -> {new:.3f}" if isinstance(old, float) or isinstance(new, float) else f"{old} -> {new}"
            reasons.append(f"{key} rose {shown}")
    return {"prev": prev_dir.name, "next": next_dir.name, "same_documents": in_prev == in_next,
            "shared_docs": len(shared), "label_mismatch": mismatch, "prev_pooled": before, "next_pooled": after,
            "shared_paired": paired,
            "verdict": {"pass": not reasons, "reasons": reasons}}


def _confidence(item: dict[str, Any] | None) -> float | None:
    value = ((item or {}).get("pred") or {}).get("extraction_confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _block(archived: list[tuple[float | None, str]], grid: tuple[float, ...],
           counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Threshold counts of one pool of archived documents, as ``(confidence, outcome)``.

    With the pool's gate ``counts`` it also projects the gate's rates per threshold, under the replay's
    upper-bound assumption: every caught wrong archive goes to review and leaves the scorable archives.
    ``review_rate`` assumes the judge passes everything else it sees; ``review_rate_if_disturbed_rejected``
    assumes it rejects every judged document (the worst case for review).
    """
    scored = [(conf, outcome) for conf, outcome in archived if conf is not None]
    absent = Counter(outcome for conf, outcome in archived if conf is None)
    thresholds: dict[float, dict[str, Any]] = {}
    for t in grid:
        row = {"extra_judged": sum(conf < t for conf, _ in scored),
               "wrong_archives_caught_upper_bound": sum(conf < t and o == "wrong_archive" for conf, o in scored),
               "correct_archives_disturbed": sum(conf < t and o == "correct_archive" for conf, o in scored)}
        if counts is not None:
            caught, n = row["wrong_archives_caught_upper_bound"], counts["n"]
            scorable = counts["wrong"] + counts["correct"] - caught
            row["wrong_archive_rate"] = (counts["wrong"] - caught) / scorable if scorable else None
            row["review_rate"] = (counts["review"] + caught) / n if n else None
            row["review_rate_if_disturbed_rejected"] = (counts["review"] + row["extra_judged"]) / n if n else None
        thresholds[t] = row
    out: dict[str, Any] = {"archived": len(archived), "no_confidence": sum(absent.values()),
                           "no_confidence_by_outcome": dict(absent), "thresholds": thresholds}
    if counts is not None:
        scorable = counts["wrong"] + counts["correct"]
        out["baseline"] = {"n": counts["n"], "review_rate": counts["review"] / counts["n"] if counts["n"] else None,
                           "wrong_archive_rate": counts["wrong"] / scorable if scorable else None}
    return out


def threshold_evidence(run_dir: Path, bars: Bars, *, grid: tuple[float, ...] = DEFAULT_GRID) -> dict[str, Any]:
    """Per gated class and pooled: what a confidence threshold ``t`` would have sent to the judge."""
    by_class: dict[str, list[tuple[float | None, str]]] = defaultdict(list)
    statuses: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in gate._load(Path(run_dir)):
        status = gate._status(doc, bars)
        if status["class"] not in bars.gated:
            continue
        statuses[status["class"]].append(status)
        if status["stage"] == "archived":
            by_class[status["class"]].append((_confidence(doc["item"]), status["outcome"]))
    pooled = [entry for entries in by_class.values() for entry in entries]
    every = [s for group in statuses.values() for s in group]
    return {"run_id": Path(run_dir).name, "label": LABEL, "grid": list(grid),
            "classes": {cls: _block(entries, grid, gate._counts(statuses[cls])) for cls, entries in sorted(by_class.items())},
            "pooled": _block(pooled, grid, gate._counts(every))}


# --- phase 4: the correcting judge against today's judge (stages 1 and 2) -------------------------

#: Judge-related calls per judged document must fall by at least this share (spec "Success").
JUDGE_CALL_CUT = 0.5
#: On judged documents the score may be at most this many points below today's (owner decision).
SCORE_MARGIN_POINTS = 2.0


def _judge_docs(run_dir: Path, bars: Bars) -> dict[str, dict[str, Any]]:
    """Per document: status, judge-related calls, cost and score after the judge (gate scoring)."""
    from mailroom_sandbox.job.pair_report import load_arm

    out: dict[str, dict[str, Any]] = {}
    report = gate.gate_report(run_dir, bars, audit=False)
    statuses = {s["id"]: s for s in report["docs"]}
    for doc_id, doc in load_arm(run_dir).items():
        item = doc.get("item") or {}
        pred = item.get("pred") if isinstance(item.get("pred"), dict) else {}
        status = statuses.get(doc_id) or {}
        row = doc["row"]
        cls = str(row.get("expected_doc_class"))
        scored = None
        if status.get("labelled", 0) >= bars.min_labelled and not status.get("outcome") == "crashed":
            scored = gate._score(gate.without_fields(row, gate.TEMPLATED_FIELDS.get(cls, ())), pred)
        out[doc_id] = {"status": status, "class": cls, "judged": bool(pred.get("judge_rulings")),
                       "correct_mode": any(isinstance(r, dict) and r.get("mode") == "correct"
                                           for r in pred.get("judge_rulings") or ()),
                       "calls": gate.judge_related_calls(item, pred, doc.get("nodes") or ()),
                       "cost": gate.doc_cost(item), "score": scored,
                       "ceiling": "per-document ceiling" in str(item.get("error") or "")}  # not a run-cap stop
    for doc_id in set(statuses) - set(out):  # a document the run never wrote an item for
        out[doc_id] = {"status": statuses[doc_id], "class": statuses[doc_id]["class"], "judged": False,
                       "correct_mode": False, "calls": 0, "cost": None, "score": None, "ceiling": False}
    return out


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def judge_compare(baseline_dir: Path, judge_dir: Path, bars: Bars, *, stage: int = 2) -> dict[str, Any]:
    """The correcting judge's success rules against today's judge on the same documents.

    One check per rule, each with its numbers and ``pass``: judge-related calls per judged document
    cut by at least half; cost per judged document no higher, by class; the paired score delta on
    judged documents at most 2 points below with its bootstrap interval (ruling 18: gating in
    stage 2, reported in stage 1); no more wrong archives; no more crashes and none from the hard
    call ceiling. Judged documents are those the judge run's correcting judge ruled on; the score
    check pairs the documents judged in either arm.
    """
    from mailroom_sandbox.job.sand42_cards import bootstrap_mean_ci

    baseline_dir, judge_dir = Path(baseline_dir), Path(judge_dir)
    if not same_documents(baseline_dir, judge_dir):
        raise ValueError(f"judge_compare needs the same documents in both runs: {baseline_dir.name} and "
                         f"{judge_dir.name} drew different documents")
    base, new = _judge_docs(baseline_dir, bars), _judge_docs(judge_dir, bars)
    judged = sorted(i for i, d in new.items() if d["judged"] and d["correct_mode"])
    checks: list[dict[str, Any]] = []
    b_calls = _avg([float(base[i]["calls"]) for i in judged])
    n_calls = _avg([float(new[i]["calls"]) for i in judged])
    checks.append({"rule": "judge_calls_cut", "baseline": b_calls, "judge": n_calls, "max_share": JUDGE_CALL_CUT,
                   "pass": bool(judged) and b_calls is not None and n_calls is not None
                   and n_calls <= (1 - JUDGE_CALL_CUT) * b_calls, "gating": True})
    by_class: dict[str, dict[str, float | None]] = {}
    for cls in sorted({new[i]["class"] for i in judged}):
        # Both arms are averaged over the same documents: those whose cost is known in both.
        ids = [i for i in judged if new[i]["class"] == cls and base[i]["cost"] is not None
               and new[i]["cost"] is not None]
        by_class[cls] = {"baseline": _avg([base[i]["cost"] for i in ids]), "judge": _avg([new[i]["cost"] for i in ids]),
                         "paired_documents": len(ids)}
    checks.append({"rule": "judge_cost_by_class", "classes": by_class, "gating": True,
                   "pass": bool(by_class) and all(v["baseline"] is not None and v["judge"] is not None
                                                  and v["judge"] <= v["baseline"] for v in by_class.values())})
    # Ruling 18: the score check pairs the documents judged in either arm (same ids), so a
    # document only the baseline judged is not dropped from the comparison.
    either = sorted(set(judged) | {i for i, d in base.items() if d["judged"] and i in new})
    diffs = [100.0 * (new[i]["score"] - base[i]["score"]) for i in either
             if new[i]["score"] is not None and base[i]["score"] is not None]
    ci = bootstrap_mean_ci(diffs) if diffs else None
    checks.append({"rule": "score_margin", "paired_documents": len(diffs), "delta": ci[0] if ci else None,
                   "ci_low": ci[1] if ci else None, "ci_high": ci[2] if ci else None,
                   "margin_points": SCORE_MARGIN_POINTS, "gating": stage >= 2,
                   "pass": ci is not None and ci[1] >= -SCORE_MARGIN_POINTS})
    wrong = {name: sum(1 for d in arm.values() if d["status"].get("outcome") == "wrong_archive")
             for name, arm in (("baseline", base), ("judge", new))}
    checks.append({"rule": "wrong_archives", **wrong, "gating": True, "pass": wrong["judge"] <= wrong["baseline"]})
    crashes = {name: sum(1 for d in arm.values() if d["status"].get("outcome") == "crashed")
               for name, arm in (("baseline", base), ("judge", new))}
    ceiling = sum(1 for d in new.values() if d["ceiling"])
    checks.append({"rule": "ceiling_crashes", **crashes, "ceiling": ceiling, "gating": True,
                   "pass": ceiling == 0 and crashes["judge"] <= crashes["baseline"]})
    reasons = [f"{c['rule']} failed" for c in checks if c["gating"] and not c["pass"]]
    return {"baseline": baseline_dir.name, "judge": judge_dir.name, "stage": stage, "judged_docs": len(judged),
            "checks": checks, "verdict": {"pass": not reasons, "reasons": reasons}}
