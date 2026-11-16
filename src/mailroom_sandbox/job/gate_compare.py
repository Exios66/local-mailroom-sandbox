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
silently and never in the threshold counts.
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
    for key in ("wrong_archive_rate", "review_rate", "crashes", "judge_errors"):
        old, new = before.get(key), after.get(key)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new > old:
            shown = f"{old:.3f} -> {new:.3f}" if isinstance(old, float) or isinstance(new, float) else f"{old} -> {new}"
            reasons.append(f"{key} rose {shown}")
    return {"prev": prev_dir.name, "next": next_dir.name, "same_documents": in_prev == in_next,
            "shared_docs": len(shared), "prev_pooled": before, "next_pooled": after,
            "shared_paired": paired_report(prev_dir, next_dir),
            "verdict": {"pass": not reasons, "reasons": reasons}}


def _confidence(item: dict[str, Any] | None) -> float | None:
    value = ((item or {}).get("pred") or {}).get("extraction_confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _block(archived: list[tuple[float | None, str]], grid: tuple[float, ...]) -> dict[str, Any]:
    """Threshold counts of one pool of archived documents, as ``(confidence, outcome)``."""
    scored = [(conf, outcome) for conf, outcome in archived if conf is not None]
    absent = Counter(outcome for conf, outcome in archived if conf is None)
    thresholds = {t: {"extra_judged": sum(conf < t for conf, _ in scored),
                      "wrong_archives_caught_upper_bound": sum(conf < t and o == "wrong_archive" for conf, o in scored),
                      "correct_archives_disturbed": sum(conf < t and o == "correct_archive" for conf, o in scored)}
                  for t in grid}
    return {"archived": len(archived), "no_confidence": sum(absent.values()),
            "no_confidence_by_outcome": dict(absent), "thresholds": thresholds}


def threshold_evidence(run_dir: Path, bars: Bars, *, grid: tuple[float, ...] = DEFAULT_GRID) -> dict[str, Any]:
    """Per gated class and pooled: what a confidence threshold ``t`` would have sent to the judge."""
    by_class: dict[str, list[tuple[float | None, str]]] = defaultdict(list)
    for doc in gate._load(Path(run_dir)):
        status = gate._status(doc, bars)
        if status["class"] in bars.gated and status["stage"] == "archived":
            by_class[status["class"]].append((_confidence(doc["item"]), status["outcome"]))
    pooled = [entry for entries in by_class.values() for entry in entries]
    return {"run_id": Path(run_dir).name, "label": LABEL, "grid": list(grid),
            "classes": {cls: _block(entries, grid) for cls, entries in sorted(by_class.items())},
            "pooled": _block(pooled, grid)}
