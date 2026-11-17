"""The keep rule: whether a candidate replaces the champion.

A quality lever is kept only when all of these hold:

1. the paired utility gain is real: the bootstrap interval's lower bound is above
   ``max(0, noise_floor)``;
2. no guarded class loses more than ``max_class_drop`` (0.05) of mean utility;
3. the wrong-archive count is not higher than the champion's;
4. cost per document is at most ``cost_ratio`` (1.25) times the champion's, unless the gain is at
   least ``cost_win`` (0.05) mean utility.

A cost lever (``goal: cost``, the derived placements) trades the first rule for non-inferiority
and a saving: the interval's lower bound must be above ``-tolerance`` (0.02 by default) and the cost
per document at most ``saving_ratio`` (0.9) times the champion's; rules 2 and 3 apply as they are.

The result is ``(keep, reasons)``: every failed rule when reverted, the evidence for each rule when kept.
"""
from __future__ import annotations

import math
from typing import Iterable

from mailroom_sandbox.autoresearch.scoring import PairedDelta, RunScores

# Cost ratios compare sums of floats; allow rounding error so "exactly 1.25x" behaves the same on every Python.
_REL_EPS = 1e-9


def decide_keep(champ: RunScores, cand: RunScores, delta: PairedDelta, *, goal: str = "quality",
                noise_floor: float = 0.0, guard_classes: Iterable[str] | None = None, max_class_drop: float = 0.05,
                cost_ratio: float = 1.25, cost_win: float = 0.05, tolerance: float = 0.02,
                saving_ratio: float = 0.9) -> tuple[bool, list[str]]:
    failed: list[str] = []
    passed: list[str] = []

    def check(ok: bool, good: str, bad: str) -> None:
        (passed if ok else failed).append(good if ok else bad)

    if delta.n == 0 or not math.isfinite(delta.mean):
        return False, ["no documents in common with the champion's run (a different draw)"]
    if goal == "cost":
        check(delta.ci_low > -tolerance, f"not worse: CI low {delta.ci_low:+.3f} > -{tolerance:g}",
              f"worse: CI low {delta.ci_low:+.3f} <= -{tolerance:g}")
    else:
        floor = max(0.0, noise_floor)
        check(delta.ci_low > floor, f"gain is real: CI low {delta.ci_low:+.3f} > {floor:g}",
              f"gain is not established: CI low {delta.ci_low:+.3f} <= {floor:g} (mean {delta.mean:+.3f})")
    guarded = set(guard_classes) if guard_classes else set(delta.by_class)
    drops = {cls: d["mean"] for cls, d in delta.by_class.items() if cls in guarded and d["mean"] < -max_class_drop}
    check(not drops, f"no guarded class drops more than {max_class_drop:g}",
          "class drop: " + ", ".join(f"{c} {v:+.3f}" for c, v in sorted(drops.items())) + f" (limit -{max_class_drop:g})")
    check(cand.wrong_archives <= champ.wrong_archives,
          f"wrong archives {cand.wrong_archives} <= champion {champ.wrong_archives}",
          f"wrong archives rose: {cand.wrong_archives} > champion {champ.wrong_archives}")
    champ_cost, cand_cost = champ.cost_per_doc, cand.cost_per_doc
    if goal == "cost":
        if champ_cost > 0:
            check(cand_cost <= saving_ratio * champ_cost * (1 + _REL_EPS),
                  f"saves cost: {cand_cost:.5f} <= {saving_ratio:g} x {champ_cost:.5f} USD/doc",
                  f"no saving: {cand_cost:.5f} > {saving_ratio:g} x {champ_cost:.5f} USD/doc")
        else:
            failed.append("cost saving cannot be shown: the champion's run recorded no priced usage")
    elif champ_cost > 0:
        over = cand_cost > cost_ratio * champ_cost * (1 + _REL_EPS)
        check(not over or delta.mean >= cost_win,
              f"cost {cand_cost:.5f} USD/doc within {cost_ratio:g} x {champ_cost:.5f}" if not over
              else f"cost {cand_cost:.5f} USD/doc over {cost_ratio:g} x champion, paid for by gain {delta.mean:+.3f} >= {cost_win:g}",
              f"cost {cand_cost:.5f} USD/doc is over {cost_ratio:g} x {champ_cost:.5f} and the gain {delta.mean:+.3f} < {cost_win:g}")
    else:
        passed.append("cost rule not applied: the champion's run recorded no priced usage")
    return (not failed), (passed if not failed else failed)
