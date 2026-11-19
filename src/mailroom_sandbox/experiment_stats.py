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
]

# Sequential-look keep thresholds from the prompt-iteration design: keep at
# z >= 2.45 on the 600-doc look or z >= 2.00 on the full 900; look 1 only screens.
KEEP_Z = {600: 2.45, 900: 2.00}


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

    @property
    def discordance(self) -> float:
        return (self.b + self.c) / self.n if self.n else 0.0

    @property
    def gain(self) -> float:
        """Accuracy difference, candidate minus baseline."""
        return (self.c - self.b) / self.n if self.n else 0.0


def mcnemar(baseline: Sequence[bool], candidate: Sequence[bool]) -> McNemar:
    """Exact McNemar test on paired per-document correctness."""
    if len(baseline) != len(candidate):
        raise ValueError("paired sequences differ in length")
    b = sum(1 for x, y in zip(baseline, candidate) if x and not y)
    c = sum(1 for x, y in zip(baseline, candidate) if y and not x)
    z = (c - b) / math.sqrt(b + c) if (b + c) else 0.0
    return McNemar(n=len(baseline), b=b, c=c, p_value=_binom_two_sided(c, b + c), z=z)


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
    documents to failed calls (n = 897 at look 3) still decides. Without it the
    look is inferred from ``n``.
    """
    if look is None:
        look = 3 if n >= 900 else 2 if n >= 600 else 1
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
