"""The judge's record (phase 4): every ruling, and the extraction the judge first saw.

Kept in the document's call-guard scope and copied into the result by
``eval.runners._run_pipeline_doc``, so a run reports what each judge pass ruled, the
extraction before the judge touched it, and whether an accepted fix changed it. Outside a
document scope (an ad-hoc graph call) nothing is recorded.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

#: The scope keys the runner copies into a result.
KEYS = ("judge_rulings", "before_judge", "judge_corrected", "judge_conflict")


def _scope() -> dict[str, Any] | None:
    from mailroom_sandbox.job import call_guard

    return call_guard.scope()


def note_before(extracted: Mapping[str, Any]) -> None:
    """The first judge pass's cleaned extraction; later passes never overwrite it."""
    scope = _scope()
    if scope is not None and "before_judge" not in scope:
        scope["before_judge"] = copy.deepcopy(dict(extracted or {}))


def note_ruling(entry: Mapping[str, Any]) -> None:
    """Append one ruling: pass, mode, ruling, score, reason, fixes, retry_fields, wrong_fields, model."""
    scope = _scope()
    if scope is not None:
        scope.setdefault("judge_rulings", []).append(copy.deepcopy(dict(entry)))


def note_corrected() -> None:
    """An accept applied at least one verified fix (ruling 15)."""
    scope = _scope()
    if scope is not None:
        scope["judge_corrected"] = True


def note_conflict() -> None:
    """A judged document carried a matter conflict (spec "Matter conflicts ... Each one is counted")."""
    scope = _scope()
    if scope is not None:
        scope["judge_conflict"] = True


def merge(result: Mapping[str, Any], scope: Mapping[str, Any]) -> dict[str, Any]:
    """``result`` with the record's keys that the document set (none when no judge section ran)."""
    extra = {key: scope[key] for key in KEYS if key in scope}
    return {**result, **extra} if extra else dict(result)
