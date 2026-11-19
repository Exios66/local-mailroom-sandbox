"""Paired comparison statistics for the evaluation runbook (R02).

The Dojo (vendored ``llm_dojo_scoring.analysis``) owns the calibration math:
Clopper-Pearson upper bounds, ECE, Brier, AUROC, Wilson and bootstrap intervals.
This module re-exports those and adds the paired tests the keep and transfer rules
need, which the Dojo does not ship:

* exact McNemar on paired correct/incorrect outcomes (sorter accuracy keep rule),
* class macro-F1 and a paired swap-permutation test for it (H1: McNemar tests accuracy,
  not macro-F1, so a macro-F1 claim needs a test of macro-F1 itself),
* a sign-flip permutation test on per-document score differences (specialist field F1),
* Holm step-down adjustment (sealed held-out confirmatory family),
* the sequential-look z for 300 / 600 / 900 dev looks,
* cost-weighted error from a confusion count and a cost matrix,
* null floors for Brier and ECE, so a calibration figure is read beside the score a
  constant base-rate predictor or a perfectly calibrated one would get at that n,
* class-specific gate sizing: the error-free accepts a class needs for its own
  ``target_error`` bound, and the bound its calibration documents can certify.

All functions are pure and deterministic (seeded where random).
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from llm_dojo_scoring.analysis.calibration import (  # re-exported: Dojo owns these
    auroc,
    brier_score,
    clopper_pearson_upper,
    expected_calibration_error,
)

__all__ = [
    "auroc",
    "brier_score",
    "clopper_pearson_upper",
    "expected_calibration_error",
    "McNemar",
    "mcnemar",
    "paired_permutation",
    "macro_f1",
    "paired_macro_f1",
    "holm",
    "look_z",
    "keep_at_look",
    "cost_weighted_error",
    "brier_null_floor",
    "ece_null_floor",
    "KEEP_Z",
    "ClassGate",
    "zero_failure_n",
    "class_gate_plan",
    "align_by_id",
    "PairedAlignment",
    "NoiseFloor",
    "noise_floor",
    "keep_with_floor",
    "calibration_inputs",
    "LOOK_SIZES",
]

#: Documents at each sequential look (1, 2, 3).
LOOK_SIZES = {1: 300, 2: 600, 3: 900}

# Sequential-look keep thresholds from the prompt-iteration design: keep at
# z >= 2.45 on the 600-doc look or z >= 2.00 on the full 900; look 1 only screens.
KEEP_Z = {600: 2.45, 900: 2.00}


def _binom_mid_p(k: int, n: int) -> float:
    """Two-sided mid-p (p=0.5): twice the smaller tail with half the observed point mass, capped at 1."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    below = sum(math.comb(n, i) for i in range(k))
    tail = (2 * below + math.comb(n, k)) / (2 * (1 << n))
    return min(1.0, 2.0 * tail)


def _binom_two_sided(k: int, n: int) -> float:
    """Exact two-sided binomial p (p=0.5), doubling the smaller tail, capped at 1."""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    # integer true division stays exact past 2**1023, where 2.0**n overflows
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (1 << n)
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class McNemar:
    n: int
    b: int  # baseline right, candidate wrong
    c: int  # baseline wrong, candidate right
    p_value: float
    z: float  # (c - b) / sqrt(b + c); 0 when no discordant pairs
    p_mid: float | None = None  # mid-p variant (less conservative); the keep rule reads p_value

    @property
    def discordance(self) -> float:
        return (self.b + self.c) / self.n if self.n else 0.0

    @property
    def gain(self) -> float:
        """Accuracy difference, candidate minus baseline."""
        return (self.c - self.b) / self.n if self.n else 0.0


def mcnemar(baseline: Sequence[bool], candidate: Sequence[bool]) -> McNemar:
    """Exact McNemar test on paired per-document correctness.

    The p-value is the exact binomial one for every count of discordant pairs (integer
    arithmetic, so it stays exact past 1,024 pairs, where ``2.0 ** n`` overflows); ``p_mid`` is
    the mid-p variant. Pair the two vectors by document id first (:func:`align_by_id`).
    """
    if len(baseline) != len(candidate):
        raise ValueError("paired sequences differ in length")
    b = sum(1 for x, y in zip(baseline, candidate) if x and not y)
    c = sum(1 for x, y in zip(baseline, candidate) if y and not x)
    z = (c - b) / math.sqrt(b + c) if (b + c) else 0.0
    return McNemar(n=len(baseline), b=b, c=c, p_value=_binom_two_sided(c, b + c), z=z,
                   p_mid=_binom_mid_p(c, b + c))


def paired_permutation(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    n_perm: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """Two-sided sign-flip permutation test on paired differences.

    Returns ``(mean_difference, p_value)`` with the +1 correction, so p is never 0.
    A NaN or infinite score raises instead of yielding a finite p for an invalid comparison.
    """
    if len(baseline) != len(candidate):
        raise ValueError("paired sequences differ in length")
    diffs = [float(y) - float(x) for x, y in zip(baseline, candidate)]
    bad = [i for i, d in enumerate(diffs) if not math.isfinite(d)]
    if bad:
        raise ValueError(f"non-finite paired difference at {len(bad)} position(s), e.g. index {bad[0]}")
    n = len(diffs)
    if n == 0:
        return 0.0, 1.0
    observed = abs(sum(diffs))
    nonzero = [d for d in diffs if d != 0.0]
    if not nonzero:
        return 0.0, 1.0
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        s = sum(d if rng.random() < 0.5 else -d for d in nonzero)
        if abs(s) >= observed - 1e-12:
            hits += 1
    return sum(diffs) / n, (hits + 1) / (n_perm + 1)


def macro_f1(truth: Sequence[str], pred: Sequence[str], labels: Sequence[str] | None = None) -> float:
    """Unweighted mean of per-class F1 over ``labels`` (default: every class in ``truth``)."""
    if len(truth) != len(pred):
        raise ValueError("truth and predictions differ in length")
    classes = sorted(set(labels) if labels is not None else set(truth))
    if not classes:
        return 0.0
    total = 0.0
    for c in classes:
        tp = sum(1 for t, p in zip(truth, pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(truth, pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(truth, pred) if t == c and p != c)
        total += 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return total / len(classes)


def paired_macro_f1(
    truth: Sequence[str],
    baseline: Sequence[str],
    candidate: Sequence[str],
    *,
    n_perm: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """Two-sided paired test of a macro-F1 difference: swap each document's two predictions
    with probability 1/2 and recompute. Returns ``(candidate - baseline, p)`` with the +1
    correction. The class set is fixed to ``truth``'s classes across permutations."""
    if not (len(truth) == len(baseline) == len(candidate)):
        raise ValueError("truth, baseline and candidate differ in length")
    labels = sorted(set(truth))
    observed = macro_f1(truth, candidate, labels) - macro_f1(truth, baseline, labels)
    differ = [i for i, (a, b) in enumerate(zip(baseline, candidate)) if a != b]
    if not differ:
        return observed, 1.0
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_perm):
        a, b = list(baseline), list(candidate)
        for i in differ:
            if rng.random() < 0.5:
                a[i], b[i] = b[i], a[i]
        if abs(macro_f1(truth, b, labels) - macro_f1(truth, a, labels)) >= abs(observed) - 1e-12:
            hits += 1
    return observed, (hits + 1) / (n_perm + 1)


def holm(p_values: Mapping[str, float] | Sequence[float]) -> dict:
    """Holm step-down adjusted p-values (monotone, capped at 1), keyed like the input."""
    items = list(p_values.items()) if isinstance(p_values, Mapping) else list(enumerate(p_values))
    m = len(items)
    ordered = sorted(items, key=lambda kv: kv[1])
    adjusted: dict = {}
    running = 0.0
    for rank, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * float(p)))
        adjusted[key] = running
    return {key: adjusted[key] for key, _ in items}


def look_z(baseline: Sequence[bool], candidate: Sequence[bool]) -> float:
    """McNemar z at a sequential look (positive = candidate better)."""
    return mcnemar(baseline, candidate).z


def keep_at_look(
    n: int, z: float, gain: float, target: float, *, look: int | None = None
) -> str:
    """Sequential-look decision: ``keep`` | ``drop`` | ``continue``.

    Look 1 (300) only screens, so it never keeps. At 600: keep at z >= 2.45, drop
    when the gain is under half the target. At the full set: keep at z >= 2.00,
    otherwise drop.

    ``look`` (1, 2 or 3) names the look explicitly, so a look that lost a few
    documents to failed calls (n = 897 at look 3) still decides. Without it ``n``
    must be a look size (300, 600 or 900): inferring the look from any other n
    read a 897-document final look as look 2 (``continue``, never a decision),
    so an unnamed off-size look raises instead.
    """
    if look is None:
        by_size = {size: k for k, size in LOOK_SIZES.items()}
        if n not in by_size:
            raise ValueError(f"n={n} is not a look size {sorted(by_size)}; pass look= explicitly")
        look = by_size[n]
    if look not in (1, 2, 3):
        raise ValueError(f"look must be 1, 2 or 3, got {look}")
    if look == 3:
        return "keep" if z >= KEEP_Z[900] else "drop"
    if look == 2:
        if z >= KEEP_Z[600]:
            return "keep"
        return "drop" if gain < target / 2.0 else "continue"
    return "continue"


def cost_weighted_error(
    confusion: Mapping[tuple[str, str], int],
    costs: Mapping[tuple[str, str], float],
    *,
    default_cost: float = 1.0,
) -> float:
    """Mean misroute cost per document.

    ``confusion[(gold, predicted)]`` counts documents; ``costs[(gold, predicted)]``
    gives the cost of that error (correct cells cost 0; missing error cells use
    ``default_cost``).
    """
    total = sum(confusion.values())
    if total == 0:
        return 0.0
    cost = 0.0
    for (gold, pred), n in confusion.items():
        if gold == pred:
            continue
        cost += n * float(costs.get((gold, pred), default_cost))
    return cost / total


def brier_null_floor(correct: Sequence[bool]) -> float | None:
    """Brier score of a constant predictor at the observed accuracy: p(1-p)."""
    if not correct:
        return None
    p = sum(1 for c in correct if c) / len(correct)
    return round(p * (1.0 - p), 6)


def ece_null_floor(
    confidences: Sequence[float],
    *,
    bins: int = 10,
    n_sim: int = 500,
    seed: int = 0,
    quantile: float = 0.95,
) -> float | None:
    """ECE a perfectly calibrated model would show at this n (simulated quantile).

    Draws correctness as Bernoulli(confidence) for the observed confidences, so an
    observed ECE at or under this value is indistinguishable from perfect calibration.
    """
    if not confidences:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(n_sim):
        pairs = [(c, rng.random() < c) for c in confidences]
        ece = expected_calibration_error(pairs, bins=bins)
        values.append(ece if ece is not None else 0.0)
    values.sort()
    index = min(len(values) - 1, int(math.ceil(quantile * len(values))) - 1)
    return round(values[index], 6)


def zero_failure_n(target_error: float, confidence: float = 0.95) -> int:
    """Fewest error-free accepts whose one-sided Clopper-Pearson bound is <= ``target_error``.

    Zero errors in n accepts bound the rate at ``1 - (1 - confidence) ** (1 / n)``, so
    n = ceil(ln(1 - confidence) / ln(1 - target_error)): 149 for 2% at 95%.
    """
    if not 0 < target_error < 1 or not 0 < confidence < 1:
        raise ValueError("target_error and confidence must lie in (0, 1)")
    n = math.ceil(math.log(1 - confidence) / math.log(1 - target_error))
    while n > 1 and (clopper_pearson_upper(0, n - 1, confidence=confidence) or 1.0) <= target_error:
        n -= 1  # guard the float ceiling against an off-by-one
    return n


@dataclass(frozen=True)
class PairedAlignment:
    """Two arms' per-document values on their shared documents, in one id order."""

    ids: tuple[str, ...]
    baseline: tuple
    candidate: tuple
    only_baseline: tuple[str, ...]  # missing or errored on the candidate arm
    only_candidate: tuple[str, ...]  # missing or errored on the baseline arm
    neither: tuple[str, ...] = ()  # errored on both arms

    @property
    def complete(self) -> bool:
        return not self.only_baseline and not self.only_candidate and not self.neither

    def report(self) -> dict:
        return {"paired": len(self.ids), "only_baseline": list(self.only_baseline),
                "only_candidate": list(self.only_candidate), "neither": list(self.neither)}


def align_by_id(baseline: Mapping[str, object], candidate: Mapping[str, object], *,
                errored_as: object | None = None) -> PairedAlignment:
    """Pair two arms by document id (sorted ids, so both vectors share one order).

    A ``None`` value is an errored or missing document. With ``errored_as`` (e.g. ``False`` for
    correctness, ``0.0`` for a score) it stands in for the error and the pair is kept; otherwise
    the pair is left out and the id is reported under ``only_baseline`` / ``only_candidate``, never
    dropped silently. Every pairwise test here takes the aligned vectors.
    """
    ids, base, cand, only_b, only_c, neither = [], [], [], [], [], []
    for doc in sorted(set(baseline) | set(candidate), key=str):
        b, c = baseline.get(doc), candidate.get(doc)
        in_b, in_c = doc in baseline, doc in candidate
        if errored_as is not None and in_b and in_c:
            b = errored_as if b is None else b
            c = errored_as if c is None else c
        b_ok, c_ok = in_b and b is not None, in_c and c is not None
        if b_ok and c_ok:
            ids.append(str(doc))
            base.append(b)
            cand.append(c)
        elif b_ok:
            only_b.append(str(doc))
        elif c_ok:
            only_c.append(str(doc))
        else:
            neither.append(str(doc))
    return PairedAlignment(tuple(ids), tuple(base), tuple(cand), tuple(only_b), tuple(only_c), tuple(neither))


@dataclass(frozen=True)
class NoiseFloor:
    """Run-to-run noise of one configuration repeated (R20's 5 runs, R40's repeats)."""

    n_runs: int
    n_docs: int  # documents every run scored
    metric_by_run: tuple[float, ...]  # accuracy (or mean score) per run on the shared documents
    mean: float
    sd: float  # sample standard deviation across runs (0 for a single run)
    floor: float  # the largest gap between two runs of the same config: a gain under it is noise
    flip_rate: float  # share of shared documents whose outcome differs between at least two runs
    missing: dict  # {run: [doc ids it did not score]}

    def as_dict(self) -> dict:
        return {"n_runs": self.n_runs, "n_docs": self.n_docs, "metric_by_run": list(self.metric_by_run),
                "mean": self.mean, "sd": self.sd, "floor": self.floor, "flip_rate": self.flip_rate,
                "missing": self.missing}


def noise_floor(runs: Mapping[str, Mapping[str, object]]) -> NoiseFloor:
    """Noise floor of repeated runs of one config, each ``{doc_id: correct | score | None}``.

    Every run is restricted to the documents all runs scored (a ``None`` or absent document is
    listed under ``missing`` for that run). ``floor`` is ``max - min`` of the per-run metric, the
    largest difference chance produced between identical configurations; ``flip_rate`` the share
    of documents whose outcome is not the same in every run.
    """
    if not runs:
        raise ValueError("noise_floor needs at least one run")
    labels = sorted(runs)
    scored = {r: {d for d, v in runs[r].items() if v is not None} for r in labels}
    every = set.union(*(set(runs[r]) for r in labels))
    shared = sorted(set.intersection(*scored.values()), key=str)
    if not shared:
        raise ValueError("no document was scored by every run")
    missing = {r: sorted((every - scored[r]), key=str) for r in labels if every - scored[r]}
    per_run = tuple(round(sum(float(runs[r][d]) for d in shared) / len(shared), 6) for r in labels)
    mean = sum(per_run) / len(per_run)
    sd = math.sqrt(sum((m - mean) ** 2 for m in per_run) / (len(per_run) - 1)) if len(per_run) > 1 else 0.0
    flips = sum(1 for d in shared if len({float(runs[r][d]) for r in labels}) > 1)
    return NoiseFloor(len(labels), len(shared), per_run, round(mean, 6), round(sd, 6),
                      round(max(per_run) - min(per_run), 6), round(flips / len(shared), 6), missing)


def keep_with_floor(decision: str, gain: float, floor: float | NoiseFloor, *, look: int) -> dict:
    """Apply the noise floor to a sequential-look decision.

    A ``keep`` whose gain does not exceed the floor is noise: at the final look it is a ``drop``,
    at an earlier look ``continue``. ``drop`` and ``continue`` pass through.
    """
    value = floor.floor if isinstance(floor, NoiseFloor) else float(floor)
    if decision == "keep" and gain <= value:
        return {"decision": "drop" if look == 3 else "continue", "reason": "gain_within_noise_floor",
                "gain": gain, "floor": value}
    return {"decision": decision, "reason": "rule" if decision != "keep" else "gain_above_noise_floor",
            "gain": gain, "floor": value}


def calibration_inputs(pairs: Sequence[tuple[object, object]]) -> tuple[list[tuple[float, bool]], dict]:
    """``(confidence, correct)`` pairs the calibration math can use, plus what was dropped and why.

    The Dojo's Brier / ECE drop an unusable confidence silently (None, NaN, a string, a bool, a value
    outside [0, 1] such as 95 on a 0-100 scale). Nothing is clamped or rescaled here either; the
    dropped count and reasons are returned so a report states its calibration n honestly.
    """
    clean: list[tuple[float, bool]] = []
    reasons: dict[str, int] = {}

    def drop(why: str) -> None:
        reasons[why] = reasons.get(why, 0) + 1

    for conf, correct in pairs:
        if conf is None:
            drop("missing")
        elif isinstance(conf, bool) or not isinstance(conf, (int, float)):
            drop("not_a_number")
        elif not math.isfinite(float(conf)):
            drop("not_finite")
        elif not 0.0 <= float(conf) <= 1.0:
            drop("out_of_range")
        else:
            clean.append((float(conf), bool(correct)))
    return clean, {"n": len(clean), "n_dropped": len(pairs) - len(clean), "dropped": reasons}


@dataclass(frozen=True)
class ClassGate:
    """One class's calibration plan for its own accept gate."""

    doc_class: str
    calibration_docs: int
    required_accepts: int
    best_bound: float | None  # the bound if every calibration doc were an error-free accept
    certifiable: bool         # best_bound <= target_error


def class_gate_plan(
    calibration_docs: Mapping[str, int], target_error: float = 0.02, confidence: float = 0.95
) -> dict[str, ClassGate]:
    """Per-class gate sizing for the calibration set.

    A class whose calibration documents cannot certify ``target_error`` even with every one
    accepted error-free still gets its own gate, calibrated on its own documents: it reports
    ``best_bound`` (the tightest bound it can reach) instead of borrowing the global gate.
    """
    need = zero_failure_n(target_error, confidence)
    plan = {}
    for cls, n in sorted(calibration_docs.items()):
        bound = clopper_pearson_upper(0, int(n), confidence=confidence)
        plan[cls] = ClassGate(cls, int(n), need, bound, bound is not None and bound <= target_error)
    return plan
