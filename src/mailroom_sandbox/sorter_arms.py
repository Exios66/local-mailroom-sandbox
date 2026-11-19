"""Head-to-head of sorter arms on the same documents (evaluation runbook H5, SAND-108).

Arm A is the LLM sorter (``task: isolated`` / ``sorter``); arm B is a Decisions-API model acting
as the sorter (``task: sorter_reviewer`` with ``reviewer.backend: decisions`` and a question set
without ``handoff:``, so ``decision_backends.decide`` classifies doc_type and subclass from the
document alone). Both write the same ``items.jsonl`` rows (``pred``, ``latency_ms``,
``prompt_tokens``, ``completion_tokens``, ``llm_calls``), and both are scored here against the
same truth: each run's locked ``dataset.jsonl`` (interim and near-gold overlays applied at
prepare time), with the subclass scored exactly and at its split unit
(``experiment_splits.unit_correct``).

Cost is priced the same way for both arms: the item's tokens through
``job.metrics.call_cost`` (``config/api_prices.yaml`` tiers for chat models, the
``config/decision_models.yaml`` input-only price for Decisions models). The provider-reported
``pred.usage.cost`` of a Decisions call is shown beside it as a check, never mixed in.

Refusals (``ArmError``), never silent filtering:

* the runs do not cover the same documents (or a named ``--set``),
* the dataset revisions differ, or the truth for a paired document differs,
* a run is a mock run (simulated output is not evidence) unless ``allow_mock``,
* a paired document is in the sealed held-out set and the call is not ``confirmatory``; a
  confirmatory call needs a held-out ``--set`` and run ids on the sealed convention
  (``rb1-r70*`` .. ``rb1-r72*``, or the older ``runbook-r7*`` prefix).

A failed item (error, not ok, or no doc_type) counts as wrong for class and subclass, keeps any
tokens it billed, and is listed. Every random step is seeded.
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SEED = 20261118
N_BOOT = 2000
N_PERM = 5000
ALPHA = 0.05
MARGIN_MACRO_F1 = 0.02   # H5 pre-registered non-inferiority margin, class macro-F1
MARGIN_UNIT = 0.04       # H5 pre-registered non-inferiority margin, subclass-unit accuracy
FAILED = "__failed__"
SORTER_TASKS = frozenset({"sorter", "isolated"})
DECISION_SORTER_TASK = "sorter_reviewer"
HELDOUT_SETS = ("heldout", "heldout-never-tuned", "heldout-train")
SPLIT_SETS = ("dev", "dev-look1", "dev-look2", "calibration", "pool") + HELDOUT_SETS
SEALED_RUN_ID = re.compile(r"^(rb1|runbook)-r7[0-2][a-z]?(-|$)")


class ArmError(ValueError):
    """The runs cannot be compared as asked."""


def _default_split_dir() -> Path:
    from mailroom_sandbox.paths import repo_root

    return repo_root() / "config" / "splits" / "runbook-v1"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ArmError(f"{path}: missing")
    with path.open(encoding="utf-8", newline="\n") as handle:  # text holds U+2028: split on \n only
        return [json.loads(line) for line in handle.read().split("\n") if line.strip()]


# --------------------------------------------------------------------------- runs


@dataclass
class Arm:
    run_id: str
    path: Path
    task: str
    model: str
    mock: bool
    revision: str | None
    identity: dict[str, Any]
    items: dict[str, dict[str, Any]]
    truth: dict[str, tuple[str, str | None]]


def _resolve(ref: str | Path, runs_root: Path | None) -> Path:
    path = Path(ref)
    if path.is_dir():
        return path
    if runs_root is None:
        from mailroom_sandbox.job.spec import runs_root as _root

        runs_root = _root()
    candidate = Path(runs_root) / str(ref)
    if not candidate.is_dir():
        raise ArmError(f"run {ref!r}: no run directory at {candidate}")
    return candidate


def arm_model(lock: Mapping[str, Any]) -> tuple[str, str]:
    """``(task, billed model)`` of a sorter arm; anything else is refused."""
    task = str(lock.get("task") or (lock.get("spec_core") or {}).get("task") or "")
    if task == DECISION_SORTER_TASK:
        reviewer = lock.get("reviewer") or {}
        if not reviewer.get("model"):
            raise ArmError(f"{lock.get('run_id')}: a sorter_reviewer arm needs a locked reviewer model")
        if (reviewer.get("question_set") or {}).get("handoff"):
            raise ArmError(f"{lock.get('run_id')}: question set {reviewer.get('questions')!r} reads the sorter handoff, "
                           "so the decision model is not a stand-alone sorter")
        return task, str(reviewer["model"])
    if task in SORTER_TASKS:
        assigned = ((lock.get("agent_assignments") or {}).get("sorter") or {}).get("model")
        model = assigned or (lock.get("engine") or {}).get("model")
        if not model:
            raise ArmError(f"{lock.get('run_id')}: no sorter model in the lock")
        return task, str(model)
    raise ArmError(f"{lock.get('run_id')}: task {task!r} is not a sorter arm "
                   f"(expected one of {sorted(SORTER_TASKS | {DECISION_SORTER_TASK})})")


def load_arm(ref: str | Path, *, runs_root: Path | None = None) -> Arm:
    path = _resolve(ref, runs_root)
    lock_path = path / "spec.lock.json"
    if not lock_path.is_file():
        raise ArmError(f"{path}: no spec.lock.json (preflight never ran here)")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    task, model = arm_model(lock)
    items: dict[str, dict[str, Any]] = {}
    for item in _jsonl(path / "items.jsonl"):
        items.setdefault(str(item.get("item_id")), item)  # the first row is the evidence (runner)
    truth: dict[str, tuple[str, str | None]] = {}
    revisions = set()
    for row in _jsonl(path / "dataset.jsonl"):
        sub = row.get("expected_subclass")
        truth[str(row["id"])] = (str(row.get("expected_doc_class") or ""), str(sub) if sub not in (None, "") else None)
        if row.get("source_revision"):
            revisions.add(str(row["source_revision"]))
    dataset = lock.get("dataset") or {}
    revision = dataset.get("revision_resolved") or dataset.get("revision")
    if revisions and revision and revisions != {revision}:
        raise ArmError(f"{path.name}: dataset rows carry revisions {sorted(revisions)}, the lock says {revision}")
    reviewer = lock.get("reviewer") or {}
    identity = {
        "spec_hash": lock.get("spec_hash"),
        "prompt_text_sha": lock.get("prompt_text_sha"),
        "questions": reviewer.get("questions") if task == DECISION_SORTER_TASK else None,
        "questions_sha256": reviewer.get("questions_sha256") if task == DECISION_SORTER_TASK else None,
        "dataset_sha256": dataset.get("sha256"),
        "dependency_sources": {k: (v or {}).get("commit") for k, v in (lock.get("dependency_sources") or {}).items()},
    }
    return Arm(run_id=str(lock.get("run_id") or path.name), path=path, task=task, model=model,
               mock=bool((lock.get("job") or {}).get("mock")), revision=revision or (sorted(revisions)[0] if revisions else None),
               identity=identity, items=items, truth=truth)


# --------------------------------------------------------------------------- sets


def _assignments(split_dir: Path) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in _jsonl(Path(split_dir) / "assignments.jsonl")}


def set_ids(name: str, split_dir: Path | None = None) -> set[str]:
    """Document ids of a split set, or of a held-out exposure stratum.

    ``heldout-never-tuned``: held-out documents from the HF test split and not on the production
    tuning list (305 on runbook-v1); ``heldout-train``: the rest of held-out (695).
    """
    split_dir = Path(split_dir or _default_split_dir())
    if name not in SPLIT_SETS:
        raise ArmError(f"unknown set {name!r}; expected one of {list(SPLIT_SETS)}")
    rows = _assignments(split_dir)
    if name in ("heldout-never-tuned", "heldout-train"):
        never = name == "heldout-never-tuned"
        return {i for i, r in rows.items() if r.get("set") == "heldout"
                and (r.get("hf_split") == "test" and not r.get("tuned")) == never}
    if name.startswith("dev-look"):
        path = split_dir / f"{name}.ids"
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")}
    return {i for i, r in rows.items() if r.get("set") == name}


def exposure_of(split_dir: Path | None = None) -> dict[str, str]:
    """``{doc_id: never_tuned | train_untuned | tuned}`` (the split's exposure ranking)."""
    out = {}
    for i, r in _assignments(Path(split_dir or _default_split_dir())).items():
        out[i] = "tuned" if r.get("tuned") else ("never_tuned" if r.get("hf_split") == "test" else "train_untuned")
    return out


def pair(arms: Sequence[Arm], *, set_name: str | None = None, split_dir: Path | None = None,
         confirmatory: bool = False, allow_mock: bool = False) -> list[str]:
    """The paired document ids (sorted), or an ``ArmError`` naming why they cannot be paired."""
    if len(arms) < 2:
        raise ArmError("a comparison needs at least two runs")
    split_dir = Path(split_dir or _default_split_dir())
    mocks = [a.run_id for a in arms if a.mock]
    if mocks and not allow_mock:
        raise ArmError(f"mock runs are simulated output, not evidence: {mocks}")
    revisions = {a.run_id: a.revision for a in arms}
    if len(set(revisions.values())) != 1 or None in revisions.values():
        raise ArmError(f"dataset revisions differ (or are missing): {revisions}")
    if set_name:
        wanted = set_ids(set_name, split_dir)
        if not wanted:
            raise ArmError(f"set {set_name!r} is empty in {split_dir}")
        for a in arms:
            missing = wanted - set(a.items)
            if missing:
                raise ArmError(f"unpaired: {a.run_id} has no item for {len(missing)} of the {len(wanted)} "
                               f"{set_name} documents (e.g. {sorted(missing)[0]})")
        ids = wanted
    else:
        ids = set(arms[0].items)
        for a in arms[1:]:
            if set(a.items) != ids:
                only_a, only_b = ids - set(a.items), set(a.items) - ids
                raise ArmError(f"unpaired: {arms[0].run_id} and {a.run_id} differ on {len(only_a)} + {len(only_b)} "
                               "documents; name a --set both cover, or run both on the same draw")
    for a in arms:
        missing = ids - set(a.truth)
        if missing:
            raise ArmError(f"{a.run_id}: {len(missing)} paired documents are not in its dataset.jsonl")
    differ = [i for i in sorted(ids) if len({a.truth[i] for a in arms}) != 1]
    if differ:
        raise ArmError(f"the truth differs between runs for {len(differ)} paired documents (e.g. {differ[0]}): "
                       "were they prepared with the same label overlays?")
    sealed = ids & set_ids("heldout", split_dir)
    if sealed and not confirmatory:
        raise ArmError(f"{len(sealed)} paired documents are in the sealed held-out set; held-out is read once, "
                       "in the confirmatory call (R70b) with --confirmatory")
    if confirmatory:
        if set_name not in HELDOUT_SETS:
            raise ArmError(f"--confirmatory needs a held-out --set ({', '.join(HELDOUT_SETS)})")
        bad = [a.run_id for a in arms if not SEALED_RUN_ID.match(a.run_id)]
        if bad:
            raise ArmError(f"--confirmatory reads only sealed-convention runs (rb1-r70*..rb1-r72*): {bad}")
    return sorted(ids)


# --------------------------------------------------------------------------- per-document outcomes


@dataclass
class Outcome:
    doc_id: str
    truth_class: str
    pred_class: str
    class_ok: bool
    sub_scored: bool
    sub_ok: bool
    unit_scored: bool
    unit_ok: bool
    failed: bool
    confidence: float | None
    latency_ms: float | None
    cost_usd: float | None
    reported_cost_usd: float | None
    tokens: tuple[int, int] = (0, 0)
    # A 4.0.0+ Decisions answer the routing contract parked (abstained / route_to_human). Its
    # forced-choice doc_type still scores above; ``routing`` reports the parked share and the
    # accuracy of the documents it would auto-route.
    abstained: bool = False
    abstain_reasons: tuple[str, ...] = ()
    # SHF-013: a reviewed correction replaced the Hub subclass (sub_ok / unit_ok score the corrected
    # truth); the hub_* fields keep the outcome on the Hub truth.
    sub_corrected: bool = False
    hub_sub_ok: bool = False
    hub_unit_scored: bool = False
    hub_unit_ok: bool = False


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def item_cost(model: str, item: Mapping[str, Any]) -> float | None:
    """USD for one item's billed tokens; None when an answered item carries no usage or the model has no price."""
    from mailroom_sandbox.job.metrics import call_cost

    prompt, completion = item.get("prompt_tokens"), item.get("completion_tokens")
    if prompt is None and completion is None:
        failed = not item.get("ok") or item.get("error")
        return 0.0 if failed else None
    return call_cost(model, float(prompt or 0), float(completion or 0), calls=int(item.get("llm_calls") or 1))


def _confidence(pred: Mapping[str, Any]) -> float | None:
    for key in ("doc_type_probability", "confidence"):
        value = _num(pred.get(key))
        if value is not None and 0.0 <= value <= 1.0:
            return value
    return None


def outcomes(arm: Arm, ids: Iterable[str], units: Mapping[tuple[str, str], str]) -> list[Outcome]:
    """Per-document outcomes. The subclass and the unit score the reviewed subclass corrections
    (SHF-013, ``data/labels/review/subclass_corrections.jsonl``) when the fix is current; the outcome
    on the Hub truth is kept beside them (``hub_sub_ok``, ``hub_unit_scored``, ``hub_unit_ok``)."""
    from mailroom_sandbox import scoring_hotfixes as sh
    from mailroom_sandbox.experiment_splits import _subclass_token, unit_correct, unit_of

    correct = sh.enabled("SHF-013")
    out = []
    for doc_id in ids:
        item = arm.items[doc_id]
        pred = item.get("pred") or {}
        truth_class, hub_sub = arm.truth[doc_id]
        corrected = sh.corrected_subclass(doc_id, truth_class, hub_sub) if correct and hub_sub else None
        truth_sub = corrected or hub_sub
        failed = bool(item.get("error")) or not item.get("ok") or not pred.get("doc_type")
        pred_class = FAILED if failed else str(pred.get("doc_type"))
        pred_sub = None if failed else (pred.get("doc_subclass") or pred.get("contract_subtype"))
        sub_scored = bool(truth_sub)
        class_ok = pred_class == truth_class

        def scored(sub: str | None, pred_class: str = pred_class, pred_sub: Any = pred_sub,
                   failed: bool = failed, class_ok: bool = class_ok, truth_class: str = truth_class
                   ) -> tuple[bool, bool, bool]:
            """(subclass right, unit scored, unit right) against one truth subclass."""
            unit_in = unit_of(truth_class, sub, units) is not None
            sub_right = bool(sub and class_ok and pred_sub
                             and _subclass_token(truth_class, sub) == _subclass_token(truth_class, pred_sub))
            return sub_right, unit_in, bool(unit_in and not failed
                                            and unit_correct(truth_class, sub, pred_class, pred_sub, units))

        sub_ok, unit_scored, unit_ok = scored(truth_sub)
        hub_sub_ok, hub_unit_scored, hub_unit_ok = scored(hub_sub) if corrected else (sub_ok, unit_scored, unit_ok)
        usage = pred.get("usage") if isinstance(pred.get("usage"), Mapping) else {}
        out.append(Outcome(
            doc_id=doc_id, truth_class=truth_class, pred_class=pred_class, class_ok=class_ok,
            sub_scored=sub_scored, sub_ok=sub_ok, unit_scored=unit_scored, unit_ok=unit_ok, failed=failed,
            confidence=None if failed else _confidence(pred), latency_ms=_num(item.get("latency_ms")),
            cost_usd=item_cost(arm.model, item), reported_cost_usd=_num(usage.get("cost")),
            tokens=(int(item.get("prompt_tokens") or 0), int(item.get("completion_tokens") or 0)),
            abstained=bool(not failed and (pred.get("abstained") or pred.get("route_to_human"))),
            abstain_reasons=tuple(str(r) for r in (pred.get("abstain_reasons") or ()) if not failed),
            sub_corrected=corrected is not None, hub_sub_ok=hub_sub_ok, hub_unit_scored=hub_unit_scored,
            hub_unit_ok=hub_unit_ok,
        ))
    return out


def _routing(rows: Sequence[Outcome]) -> dict[str, Any]:
    """Parked (abstained) share and the accuracy of the auto-routed rest; failures are neither."""
    answered = [r for r in rows if not r.failed]
    parked = [r for r in answered if r.abstained]
    auto = [r for r in answered if not r.abstained]
    auto_unit = [r for r in auto if r.unit_scored]
    reasons: dict[str, int] = {}
    for r in parked:
        for reason in r.abstain_reasons or ("unspecified",):
            key = reason.split(":", 1)[0]
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "answered": len(answered), "abstained": len(parked), "auto_routed": len(auto),
        "abstain_rate": _rate(len(parked), len(answered)),
        "auto_class_accuracy": _rate(sum(r.class_ok for r in auto), len(auto)),
        "auto_unit_accuracy": _rate(sum(r.unit_ok for r in auto_unit), len(auto_unit)),
        "abstained_class_accuracy": _rate(sum(r.class_ok for r in parked), len(parked)),
        "abstain_reasons": dict(sorted(reasons.items())),
    }


# --------------------------------------------------------------------------- metrics


def _f1_table(truth: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> dict[str, float]:
    tp, fp, fn = Counter(), Counter(), Counter()
    for t, p in zip(truth, pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    return {c: (2 * tp[c] / (2 * tp[c] + fp[c] + fn[c]) if tp[c] else 0.0) for c in labels}


def fast_macro_f1(truth: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> float:
    """``experiment_stats.macro_f1`` in one pass (the bootstrap calls it thousands of times)."""
    table = _f1_table(truth, pred, labels)
    return sum(table.values()) / len(labels) if labels else 0.0


def _quantile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))]


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def arm_summary(arm: Arm, rows: Sequence[Outcome], *, labels: Sequence[str], seed: int = SEED) -> dict[str, Any]:
    from mailroom_sandbox.experiment_stats import (
        auroc,
        brier_score,
        ece_null_floor,
        expected_calibration_error,
    )

    n = len(rows)
    truth = [r.truth_class for r in rows]
    pred = [r.pred_class for r in rows]
    per_class = _f1_table(truth, pred, labels)
    sub = [r for r in rows if r.sub_scored]
    unit = [r for r in rows if r.unit_scored]
    conf = [(r.confidence, r.class_ok) for r in rows if r.confidence is not None]
    costs = [r.cost_usd for r in rows]
    cost_ok = all(c is not None for c in costs)
    total = sum(c for c in costs if c is not None) if cost_ok else None
    reported = [r.reported_cost_usd for r in rows if r.reported_cost_usd is not None]
    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    class_correct = sum(r.class_ok for r in rows)
    unit_correct_n = sum(r.unit_ok for r in unit)
    calibration = None
    if conf:
        calibration = {
            "n": len(conf),
            "ece": expected_calibration_error(conf),
            "ece_null_floor": ece_null_floor([c for c, _ in conf], seed=seed),
            "brier": brier_score(conf),
            "auroc": auroc([c for c, _ in conf], [ok for _, ok in conf]),
        }
    return {
        "run_id": arm.run_id, "task": arm.task, "model": arm.model, "identity": arm.identity,
        "n": n, "failed": sum(r.failed for r in rows),
        "failed_ids": [r.doc_id for r in rows if r.failed][:20],
        "class_accuracy": _rate(class_correct, n),
        "class_macro_f1": sum(per_class.values()) / len(labels) if labels else None,
        "class_f1": per_class,
        "subclass_scored": len(sub), "subclass_accuracy": _rate(sum(r.sub_ok for r in sub), len(sub)),
        "unit_scored": len(unit), "unit_accuracy": _rate(unit_correct_n, len(unit)),
        # SHF-013: the two figures above score the reviewed subclass corrections; hub_truth keeps the Hub's.
        "subclass_corrections_applied": sum(r.sub_corrected for r in rows),
        "hub_truth": {
            "subclass_scored": len(sub), "subclass_accuracy": _rate(sum(r.hub_sub_ok for r in sub), len(sub)),
            "unit_scored": sum(r.hub_unit_scored for r in rows),
            "unit_accuracy": _rate(sum(r.hub_unit_ok for r in rows if r.hub_unit_scored),
                                   sum(r.hub_unit_scored for r in rows)),
        },
        "calibration": calibration,
        "routing": _routing(rows),
        "latency_ms": {"n": len(latencies), "p50": _quantile(latencies, 0.50), "p95": _quantile(latencies, 0.95)},
        "tokens": {"prompt": sum(r.tokens[0] for r in rows), "completion": sum(r.tokens[1] for r in rows)},
        "cost": {
            "priced": cost_ok,
            "unpriced_docs": sum(c is None for c in costs),
            "total_usd": total,
            "per_doc_usd": total / n if cost_ok and n else None,
            "per_1k_docs_usd": 1000 * total / n if cost_ok and n else None,
            "per_class_correct_usd": total / class_correct if cost_ok and class_correct else None,
            "per_unit_correct_usd": total / unit_correct_n if cost_ok and unit_correct_n else None,
            "provider_reported_usd": sum(reported) if reported else None,
            "provider_reported_docs": len(reported),
        },
    }


def _ci(values: Sequence[float], level: float = 0.95) -> tuple[float, float]:
    ordered = sorted(values)
    lo = (1 - level) / 2
    return (ordered[int(math.floor(lo * len(ordered)))],
            ordered[max(0, int(math.ceil((1 - lo) * len(ordered))) - 1)])


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in log space."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    total = 0.0
    for i in range(k + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
    return min(1.0, total)


def _cp_upper(k: int, n: int, alpha: float = ALPHA) -> float:
    """One-sided Clopper-Pearson upper bound on a binomial rate after ``k`` of ``n`` (bisection)."""
    if n <= 0 or k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def exact_noninferiority(ok_a: Sequence[bool], ok_b: Sequence[bool], margin: float) -> dict[str, Any]:
    """Exact floor for paired non-inferiority of B against A from the discordant pairs.

    A bootstrap over documents cannot see a loss it never observed: with no document where A is right
    and B wrong, every resample's difference is >= 0 and it reports p ~ 1/(B+1) whatever n is, so 20
    agreeing documents "prove" non-inferiority as strongly as 900. Here B's per-document loss rate gets
    a one-sided Clopper-Pearson upper bound, the lower bound on the difference is the observed gain rate
    minus that bound, and the p-value is the chance of seeing at most the observed losses if the loss
    rate were the gain rate plus the margin. With no losses this is the rule of three: n=20 gives a
    lower bound near -14 points, n=900 near -0.3.
    """
    n = len(ok_a)
    gains = sum(1 for x, y in zip(ok_a, ok_b) if y and not x)
    losses = sum(1 for x, y in zip(ok_a, ok_b) if x and not y)
    if n == 0:
        return {"n": 0, "gains": 0, "losses": 0, "lower95_one_sided": None, "p_value": 1.0}
    lower = gains / n - _cp_upper(losses, n)
    null_loss_rate = min(1.0, gains / n + margin)
    return {"n": n, "gains": gains, "losses": losses, "lower95_one_sided": lower,
            "p_value": _binom_cdf(losses, n, null_loss_rate)}


def compare_pair(a: Sequence[Outcome], b: Sequence[Outcome], *, labels: Sequence[str],
                 margin_macro_f1: float = MARGIN_MACRO_F1, margin_unit: float = MARGIN_UNIT,
                 n_boot: int = N_BOOT, n_perm: int = N_PERM, seed: int = SEED,
                 volume: int | None = None) -> dict[str, Any]:
    """Paired tests and bootstrap intervals for B minus A (positive = B better / B dearer for cost)."""
    from mailroom_sandbox.experiment_stats import mcnemar, paired_macro_f1

    if [r.doc_id for r in a] != [r.doc_id for r in b]:
        raise ArmError("outcomes are not paired document by document")
    n = len(a)
    truth = [r.truth_class for r in a]
    pa, pb = [r.pred_class for r in a], [r.pred_class for r in b]
    unit_idx = [i for i, r in enumerate(a) if r.unit_scored]
    cost_ok = all(r.cost_usd is not None for r in a) and all(r.cost_usd is not None for r in b)
    ca = [r.cost_usd or 0.0 for r in a]
    cb = [r.cost_usd or 0.0 for r in b]

    def stats(idx: Sequence[int]) -> dict[str, float]:
        t = [truth[i] for i in idx]
        out = {
            "class_accuracy": sum(b[i].class_ok for i in idx) / len(idx) - sum(a[i].class_ok for i in idx) / len(idx),
            "class_macro_f1": fast_macro_f1(t, [pb[i] for i in idx], labels) - fast_macro_f1(t, [pa[i] for i in idx], labels),
            "cost_per_doc_a": sum(ca[i] for i in idx) / len(idx),
            "cost_per_doc_b": sum(cb[i] for i in idx) / len(idx),
        }
        u = [i for i in idx if a[i].unit_scored]
        out["unit_accuracy"] = (sum(b[i].unit_ok for i in u) - sum(a[i].unit_ok for i in u)) / len(u) if u else 0.0
        out["cost_per_doc"] = out["cost_per_doc_b"] - out["cost_per_doc_a"]
        return out

    observed = stats(range(n))
    rng = random.Random(seed)
    boots: dict[str, list[float]] = defaultdict(list)
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        for key, value in stats(idx).items():
            boots[key].append(value)

    def interval(key: str, scale: float = 1.0) -> dict[str, float]:
        lo, hi = _ci(boots[key])
        return {"estimate": observed[key] * scale, "ci95": [lo * scale, hi * scale]}

    def ni(key: str, margin: float, ok_a: Sequence[bool], ok_b: Sequence[bool]) -> dict[str, Any]:
        boot_lower = _quantile(boots[key], ALPHA) or 0.0  # one-sided 95% lower bound
        below = sum(1 for v in boots[key] if v <= -margin)
        boot_p = (below + 1) / (n_boot + 1)
        exact = exact_noninferiority(ok_a, ok_b, margin)
        lower = min(boot_lower, exact["lower95_one_sided"])
        p_value = max(boot_p, exact["p_value"])
        return {"margin": margin, "estimate": observed[key], "lower95_one_sided": lower, "p_value": p_value,
                "non_inferior": lower > -margin and p_value < ALPHA,
                "bootstrap": {"lower95_one_sided": boot_lower, "p_value": boot_p}, "exact": exact}

    diff_mf1, p_perm = paired_macro_f1(truth, pa, pb, n_perm=n_perm, seed=seed)
    mc_class = mcnemar([r.class_ok for r in a], [r.class_ok for r in b])
    mc_unit = mcnemar([a[i].unit_ok for i in unit_idx], [b[i].unit_ok for i in unit_idx])
    result: dict[str, Any] = {
        "n": n, "unit_n": len(unit_idx), "n_boot": n_boot, "n_perm": n_perm, "seed": seed,
        "differences": {
            "class_accuracy": interval("class_accuracy"),
            "class_macro_f1": interval("class_macro_f1"),
            "unit_accuracy": interval("unit_accuracy"),
        },
        "tests": {
            "paired_macro_f1_permutation": {"difference": diff_mf1, "p_value": p_perm},
            "mcnemar_class": {"b": mc_class.b, "c": mc_class.c, "p_value": mc_class.p_value, "gain": mc_class.gain},
            "mcnemar_unit": {"b": mc_unit.b, "c": mc_unit.c, "p_value": mc_unit.p_value, "gain": mc_unit.gain},
            # The exact floor for macro-F1 uses the class-level discordant pairs (a proxy: macro-F1 has no
            # per-document decomposition); for unit accuracy it uses the unit-level pairs themselves.
            "noninferiority_macro_f1": ni("class_macro_f1", margin_macro_f1,
                                          [r.class_ok for r in a], [r.class_ok for r in b]),
            "noninferiority_unit": ni("unit_accuracy", margin_unit,
                                      [a[i].unit_ok for i in unit_idx], [b[i].unit_ok for i in unit_idx]),
        },
    }
    if cost_ok:
        dearer = sum(1 for v in boots["cost_per_doc"] if v >= 0)
        cost: dict[str, Any] = {
            "per_doc": interval("cost_per_doc"),
            "per_1k_docs": interval("cost_per_doc", 1000.0),
            "lower_cost_p_value": (dearer + 1) / (n_boot + 1),  # H0: B costs at least as much as A
        }
        if volume:
            cost["monthly"] = {
                "docs_per_month": volume,
                "a": interval("cost_per_doc_a", float(volume)),
                "b": interval("cost_per_doc_b", float(volume)),
                "difference": interval("cost_per_doc", float(volume)),
            }
        result["cost"] = cost
    else:
        result["cost"] = None
    return result


def strata_differences(a: Sequence[Outcome], b: Sequence[Outcome], exposure: Mapping[str, str],
                       labels: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Point differences (B minus A) per exposure stratum; descriptive, no tests."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(a):
        groups[exposure.get(r.doc_id, "unknown")].append(i)
    out = {}
    for name, idx in sorted(groups.items()):
        t = [a[i].truth_class for i in idx]
        u = [i for i in idx if a[i].unit_scored]
        out[name] = {
            "n": len(idx),
            "class_accuracy": (sum(b[i].class_ok for i in idx) - sum(a[i].class_ok for i in idx)) / len(idx),
            "class_macro_f1": fast_macro_f1(t, [b[i].pred_class for i in idx], labels)
            - fast_macro_f1(t, [a[i].pred_class for i in idx], labels),
            "unit_accuracy": (sum(b[i].unit_ok for i in u) - sum(a[i].unit_ok for i in u)) / len(u) if u else None,
        }
    return out


def frontier(summaries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Cost-quality dominance: a run is dominated when another is at least as good on class macro-F1 and
    unit accuracy and no dearer per 1k documents, and strictly better on one of the three."""
    rows = []
    for s in summaries:
        rows.append({"run_id": s["run_id"], "model": s["model"], "class_macro_f1": s["class_macro_f1"],
                     "unit_accuracy": s["unit_accuracy"], "per_1k_docs_usd": s["cost"]["per_1k_docs_usd"]})
    for r in rows:
        r["dominated_by"] = None
        if r["per_1k_docs_usd"] is None:
            continue
        for o in rows:
            if o is r or o["per_1k_docs_usd"] is None:
                continue
            ge = (o["class_macro_f1"] >= r["class_macro_f1"] and (o["unit_accuracy"] or 0) >= (r["unit_accuracy"] or 0)
                  and o["per_1k_docs_usd"] <= r["per_1k_docs_usd"])
            gt = (o["class_macro_f1"] > r["class_macro_f1"] or (o["unit_accuracy"] or 0) > (r["unit_accuracy"] or 0)
                  or o["per_1k_docs_usd"] < r["per_1k_docs_usd"])
            if ge and gt:
                r["dominated_by"] = o["run_id"]
                break
    return sorted(rows, key=lambda r: (r["per_1k_docs_usd"] is None, r["per_1k_docs_usd"] or 0.0))


def h5_family(pairs: Mapping[str, Mapping[str, Any]], *, alpha: float = ALPHA) -> dict[str, Any]:
    """H5's confirmatory family, Holm-adjusted across every B arm: non-inferiority on class macro-F1 and on
    subclass-unit accuracy, and lower cost per document. B passes only when all three of its tests reject."""
    from mailroom_sandbox.experiment_stats import holm

    raw: dict[str, float] = {}
    for b, result in pairs.items():
        raw[f"{b}:noninferiority_macro_f1"] = result["tests"]["noninferiority_macro_f1"]["p_value"]
        raw[f"{b}:noninferiority_unit"] = result["tests"]["noninferiority_unit"]["p_value"]
        raw[f"{b}:lower_cost"] = (result.get("cost") or {}).get("lower_cost_p_value", 1.0)
    adjusted = holm(raw) if raw else {}
    secondary_raw: dict[str, float] = {}
    for b, result in pairs.items():
        for key in ("paired_macro_f1_permutation", "mcnemar_class", "mcnemar_unit"):
            secondary_raw[f"{b}:{key}"] = result["tests"][key]["p_value"]
    verdicts = {}
    for b in pairs:
        keys = [f"{b}:noninferiority_macro_f1", f"{b}:noninferiority_unit", f"{b}:lower_cost"]
        failed = [k.split(":", 1)[1] for k in keys if adjusted[k] >= alpha]
        verdicts[b] = {"supported": not failed, "failed": failed}
    return {"alpha": alpha, "raw": raw, "holm": adjusted, "verdicts": verdicts,
            "secondary_raw": secondary_raw, "secondary_holm": holm(secondary_raw) if secondary_raw else {}}


def compare(refs: Sequence[str | Path], *, set_name: str | None = None, split_dir: Path | None = None,
            runs_root: Path | None = None, confirmatory: bool = False, allow_mock: bool = False,
            volume: int | None = None, margin_macro_f1: float = MARGIN_MACRO_F1, margin_unit: float = MARGIN_UNIT,
            n_boot: int = N_BOOT, n_perm: int = N_PERM, seed: int = SEED) -> dict[str, Any]:
    """The full report: the first run is arm A (reference), every other run is a B arm compared with it."""
    from mailroom_sandbox.experiment_splits import load_unit_table

    split_dir = Path(split_dir or _default_split_dir())
    arms = [load_arm(r, runs_root=runs_root) for r in refs]
    if len({a.run_id for a in arms}) != len(arms):
        raise ArmError("the same run is named twice")
    ids = pair(arms, set_name=set_name, split_dir=split_dir, confirmatory=confirmatory, allow_mock=allow_mock)
    units = load_unit_table(split_dir)
    labels = sorted({arms[0].truth[i][0] for i in ids})
    rows = {a.run_id: outcomes(a, ids, units) for a in arms}
    summaries = [arm_summary(a, rows[a.run_id], labels=labels, seed=seed) for a in arms]
    exposure = exposure_of(split_dir)
    ref = arms[0].run_id
    pairs = {}
    strata = {}
    for b in arms[1:]:
        pairs[b.run_id] = compare_pair(rows[ref], rows[b.run_id], labels=labels, margin_macro_f1=margin_macro_f1,
                                       margin_unit=margin_unit, n_boot=n_boot, n_perm=n_perm, seed=seed, volume=volume)
        strata[b.run_id] = strata_differences(rows[ref], rows[b.run_id], exposure, labels)
    return {
        "schema": "mailroom.sorter_arms/v1",
        "reference": ref, "set": set_name, "confirmatory": confirmatory, "n": len(ids),
        "revision": arms[0].revision, "labels": labels,
        "margins": {"class_macro_f1": margin_macro_f1, "unit_accuracy": margin_unit},
        "arms": summaries, "pairs": pairs, "strata": strata,
        "h5": h5_family(pairs),
        "frontier": frontier(summaries) if len(arms) > 2 else None,
    }


# --------------------------------------------------------------------------- planning


def noninferiority_n(discordance: float, margin: float, *, true_difference: float = 0.0,
                     alpha: float = ALPHA, power: float = 0.80) -> int:
    """Paired documents a one-sided non-inferiority test of an accuracy difference needs (normal approx.).

    The per-document difference has variance ``discordance - true_difference**2``.
    """
    if not 0 < discordance <= 1 or margin <= 0 or margin + true_difference <= 0:
        raise ValueError("need 0 < discordance <= 1 and margin + true_difference > 0")
    z = statistics.NormalDist().inv_cdf
    var = discordance - true_difference ** 2
    return math.ceil((z(1 - alpha) + z(power)) ** 2 * var / (margin + true_difference) ** 2)


def noninferiority_power(n: int, se: float | None = None, *, margin: float, discordance: float | None = None,
                         true_difference: float = 0.0, alpha: float = ALPHA) -> float:
    """Power of the one-sided test at ``n`` paired documents, from a standard error or a discordance rate."""
    if se is None:
        if discordance is None:
            raise ValueError("give se or discordance")
        se = math.sqrt(max(discordance - true_difference ** 2, 1e-12) / n)
    nd = statistics.NormalDist()
    return nd.cdf((margin + true_difference) / se - nd.inv_cdf(1 - alpha))


def simulate_macro_f1_se(class_counts: Mapping[str, int], acc_a: float, acc_b: float, discordance: float, *,
                         n_sim: int = 400, seed: int = SEED) -> float:
    """Standard error of a paired macro-F1 difference (B minus A) by simulation.

    Each document is right for both arms, for A only, for B only, or for neither, with the
    discordance split so that ``acc_b - acc_a`` holds; a wrong answer goes to a random other class.
    """
    b_only = (discordance + (acc_b - acc_a)) / 2
    a_only = discordance - b_only
    both = acc_a - a_only
    if min(a_only, b_only, both) < 0 or both + a_only + b_only > 1:
        raise ValueError("accuracies and discordance are inconsistent")
    labels = sorted(class_counts)
    truth = [c for c in labels for _ in range(int(class_counts[c]))]
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_sim):
        pa, pb = [], []
        for t in truth:
            u = rng.random()
            wrong = rng.choice([c for c in labels if c != t]) if len(labels) > 1 else t
            right_a = u < both + a_only
            right_b = u < both or (both + a_only <= u < both + a_only + b_only)
            pa.append(t if right_a else wrong)
            pb.append(t if right_b else wrong)
        diffs.append(fast_macro_f1(truth, pb, labels) - fast_macro_f1(truth, pa, labels))
    return statistics.pstdev(diffs)


# --------------------------------------------------------------------------- output


def _pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{100 * value:.{digits}f}"


def _fmt(value: float | None, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def _usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def render(report: Mapping[str, Any]) -> str:
    lines = [f"sorter arms: reference {report['reference']}, set {report['set'] or '(all paired)'}, "
             f"n={report['n']}, revision {str(report['revision'])[:8]}"
             + (" [CONFIRMATORY]" if report["confirmatory"] else "")]
    lines.append(f"{'run':44} {'model':34} {'acc':>6} {'mF1':>6} {'sub':>6} {'unit':>6} {'fail':>4} "
                 f"{'ECE':>6} {'floor':>6} {'AUROC':>6} {'p50ms':>7} {'p95ms':>7} {'$/1k':>8} {'$/ok':>8}")
    for s in report["arms"]:
        cal = s["calibration"] or {}
        lat = s["latency_ms"]
        lines.append(
            f"{s['run_id'][:44]:44} {s['model'][:34]:34} {_pct(s['class_accuracy']):>6} {_pct(s['class_macro_f1']):>6} "
            f"{_pct(s['subclass_accuracy']):>6} {_pct(s['unit_accuracy']):>6} {s['failed']:>4} "
            f"{_fmt(cal.get('ece'), '.3f'):>6} {_fmt(cal.get('ece_null_floor'), '.3f'):>6} {_fmt(cal.get('auroc'), '.3f'):>6} "
            f"{_fmt(lat['p50'], '.0f'):>7} {_fmt(lat['p95'], '.0f'):>7} "
            f"{_usd(s['cost']['per_1k_docs_usd']):>8} {_usd(s['cost']['per_class_correct_usd']):>8}")
    for s in report["arms"]:
        if s.get("subclass_corrections_applied"):
            hub = s["hub_truth"]
            lines.append(f"  {s['run_id'][:44]}: {s['subclass_corrections_applied']} reviewed subclass correction(s) "
                         f"applied (SHF-013); on the Hub truth sub {_pct(hub['subclass_accuracy'])} "
                         f"unit {_pct(hub['unit_accuracy'])}")
    for s in report["arms"]:
        r = s.get("routing") or {}
        # Decision arms always show their routing line, so a measured 0% is not mistaken for missing data.
        if r.get("abstained") or s.get("task") == "sorter_reviewer":
            lines.append(f"  {s['run_id'][:44]}: parked {r['abstained']}/{r['answered']} ({_pct(r['abstain_rate'])}), "
                         f"auto-routed acc {_pct(r['auto_class_accuracy'])}, unit {_pct(r['auto_unit_accuracy'])}; "
                         f"reasons {r['abstain_reasons']}")
    for b, p in report["pairs"].items():
        d, t = p["differences"], p["tests"]
        lines.append(f"\n{b} minus {report['reference']} (points; 95% paired bootstrap, B={p['n_boot']}, seed {p['seed']}):")
        for key in ("class_accuracy", "class_macro_f1", "unit_accuracy"):
            lo, hi = d[key]["ci95"]
            lines.append(f"  {key:16} {_pct(d[key]['estimate'], 2):>7}  [{_pct(lo, 2)}, {_pct(hi, 2)}]")
        lines.append(f"  macro-F1 swap permutation p={t['paired_macro_f1_permutation']['p_value']:.4f}; "
                     f"McNemar class b={t['mcnemar_class']['b']} c={t['mcnemar_class']['c']} p={t['mcnemar_class']['p_value']:.4f}; "
                     f"McNemar unit b={t['mcnemar_unit']['b']} c={t['mcnemar_unit']['c']} p={t['mcnemar_unit']['p_value']:.4f}")
        for key in ("noninferiority_macro_f1", "noninferiority_unit"):
            ni = t[key]
            lines.append(f"  {key:24} margin -{_pct(ni['margin'])} pts: lower95 {_pct(ni['lower95_one_sided'], 2)}, "
                         f"p={ni['p_value']:.4f} -> {'non-inferior' if ni['non_inferior'] else 'not shown'} "
                         f"(B worse on {(ni.get('exact') or {}).get('losses', '?')}/{(ni.get('exact') or {}).get('n', '?')} docs)")
        cost = p.get("cost")
        if cost:
            lo, hi = cost["per_1k_docs"]["ci95"]
            lines.append(f"  cost per 1k docs {_usd(cost['per_1k_docs']['estimate'])} [{_usd(lo)}, {_usd(hi)}], "
                         f"lower-cost p={cost['lower_cost_p_value']:.4f}")
            if cost.get("monthly"):
                m = cost["monthly"]
                lines.append(f"  at {m['docs_per_month']:,} docs/month: A {_usd(m['a']['estimate'])} "
                             f"B {_usd(m['b']['estimate'])} difference {_usd(m['difference']['estimate'])} "
                             f"[{_usd(m['difference']['ci95'][0])}, {_usd(m['difference']['ci95'][1])}]")
        else:
            lines.append("  cost: unavailable (an item without usage, or a model without a price)")
        for name, s in report["strata"][b].items():
            lines.append(f"  stratum {name:14} n={s['n']:>4}  acc {_pct(s['class_accuracy'], 2)}  "
                         f"mF1 {_pct(s['class_macro_f1'], 2)}  unit {_pct(s['unit_accuracy'], 2)}")
    h5 = report["h5"]
    lines.append(f"\nH5 confirmatory family (Holm, alpha {h5['alpha']}):")
    for key, adj in h5["holm"].items():
        lines.append(f"  {key:70} raw {h5['raw'][key]:.4f}  holm {adj:.4f}")
    for b, v in h5["verdicts"].items():
        lines.append(f"  {b}: {'SUPPORTED' if v['supported'] else 'not supported (' + ', '.join(v['failed']) + ')'}")
    if report.get("frontier"):
        lines.append("\ncost-quality frontier (cheapest first):")
        for r in report["frontier"]:
            lines.append(f"  {r['run_id'][:44]:44} mF1 {_pct(r['class_macro_f1'])} unit {_pct(r['unit_accuracy'])} "
                         f"{_usd(r['per_1k_docs_usd'])}/1k  {'dominated by ' + r['dominated_by'] if r['dominated_by'] else 'frontier'}")
    return "\n".join(lines)


__all__ = ["Arm", "ArmError", "Outcome", "arm_model", "arm_summary", "compare", "compare_pair", "exposure_of",
           "exact_noninferiority", "fast_macro_f1", "frontier", "h5_family", "item_cost", "load_arm", "noninferiority_n",
           "noninferiority_power", "outcomes", "pair", "render", "set_ids", "simulate_macro_f1_se",
           "strata_differences", "SEED", "MARGIN_MACRO_F1", "MARGIN_UNIT"]
