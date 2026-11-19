"""Notebook-facing data checks over the prepared fixture catalog.

``gold_field_grounding`` checks that every extractive gold value in
``data/fixtures/manifest.csv`` is written in its fixture text, so a gold block
copied onto the wrong row (parties that are not in the document) is caught
before a live extraction eval scores against it. Network-free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Controlled labels: a classification of the document, not a span in it.
CATEGORICAL_FIELDS: frozenset[str] = frozenset({"communication_type", "merger_consideration"})

GROUNDED = "grounded"
UNGROUNDED = "ungrounded"
CATEGORICAL = "categorical"
NON_TEXT = "non_text"

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class GroundingFinding:
    row_id: str
    field: str
    value: Any
    status: str


def _norm(text: str) -> str:
    return _WS.sub(" ", text).casefold().strip()


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def gold_field_grounding(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    categorical: Iterable[str] = CATEGORICAL_FIELDS,
) -> list[GroundingFinding]:
    """One finding per gold value (per item for list fields).

    ``rows`` are cleaned manifest rows (``id``, ``text``, ``expected_fields`` as
    a dict), as ``prep.clean_manifest_rows`` returns; the default loads them.
    A string value is ``grounded`` when it appears in the row text, ignoring
    case and whitespace runs. Fields in ``categorical`` and non-string values
    (numbers, booleans) are reported but not checked.
    """
    if rows is None:
        from mailroom_sandbox.prep import clean_manifest_rows

        rows, _ = clean_manifest_rows()
    skip = frozenset(categorical)
    findings: list[GroundingFinding] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        text = _norm(str(row.get("text") or ""))
        for name, value in (row.get("expected_fields") or {}).items():
            for item in _values(value):
                if name in skip:
                    status = CATEGORICAL
                elif not isinstance(item, str):
                    status = NON_TEXT
                else:
                    needle = _norm(item)
                    status = GROUNDED if needle and needle in text else UNGROUNDED
                findings.append(GroundingFinding(row_id, name, item, status))
    return findings


def ungrounded(findings: Iterable[GroundingFinding]) -> list[GroundingFinding]:
    """The findings whose extractive value is not in the fixture text."""
    return [f for f in findings if f.status == UNGROUNDED]
