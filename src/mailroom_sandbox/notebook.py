"""Notebook-facing data checks over the prepared fixture catalog.

``gold_field_grounding`` checks that every extractive gold value in
``data/fixtures/manifest.csv`` is written in its fixture text, so a gold block
copied onto the wrong row (parties that are not in the document) is caught
before a live extraction eval scores against it. Network-free.

A value is first matched literally (case and whitespace runs ignored). Gold is
often stored in a canonical form the document does not use verbatim, so a value
that fails the literal match is then compared in canonical form:

- ``date``: a full calendar date (``2024-01-15``) against every date the text
  writes (``January 15, 2024``, ``15th day of January, 2024``, ``1/15/2024``).
- ``number``: an amount or number (``2500000``, ``"$2.5M"``, ``5000000.0``)
  against every amount the text writes (``$2,500,000``, ``2.5 million``).
- ``numeral``: spelled-out numbers read as digits on both sides, so
  ``3 years`` matches ``three (3) years`` and ``thirty days`` matches ``30 days``.

Those matches are ``grounded_normalized`` with the ``form`` that matched, so
they stay distinguishable from literal ones.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from mailroom_sandbox.gold_labels import parse_dates

# Controlled labels: a classification of the document, not a span in it.
CATEGORICAL_FIELDS: frozenset[str] = frozenset({"communication_type", "merger_consideration"})

GROUNDED = "grounded"
GROUNDED_NORMALIZED = "grounded_normalized"
UNGROUNDED = "ungrounded"
CATEGORICAL = "categorical"
NON_TEXT = "non_text"

DATE_FORM = "date"
NUMBER_FORM = "number"
NUMERAL_FORM = "numeral"

_WS = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_TOKENS = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|day|of|the)\b\.?|\d+(?:st|nd|rd|th)?|[\s,./-]",
    re.I,
)
_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}
_AMOUNT = re.compile(
    r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?(?![\w])",
    re.I,
)
_AMOUNT_ONLY = re.compile(
    r"\s*(?:usd|us\$|\$)?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?\s*(?:usd|dollars)?\s*",
    re.I,
)
_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUM = {w: i for i, w in enumerate(_UNITS)} | _TENS
_NUM_WORDS = re.compile(
    r"\b(?:("
    + "|".join(_TENS)
    + r")[\s-]("
    + "|".join(_UNITS[1:10])
    + r")|("
    + "|".join(sorted(_WORD_NUM, key=len, reverse=True))
    + r"))\b"
)


@dataclass(frozen=True)
class GroundingFinding:
    row_id: str
    field: str
    value: Any
    status: str
    form: str = ""  # which canonical form matched, for ``grounded_normalized``


def _norm(text: str) -> str:
    return _WS.sub(" ", text).casefold().strip()


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _dates(text: str) -> set[str]:
    """Every full calendar date ``text`` writes, as ISO strings."""
    found = parse_dates(text)
    for y, m, d in _ISO_DATE.findall(text):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            continue
    return found


def _gold_date(value: str) -> str | None:
    """The one full date ``value`` states, as ISO, when ``value`` is only a date.

    A sentence that mentions a date ("signed on 1/2/2024 by both") is not a date
    value and falls through to the literal and numeral checks.
    """
    if _DATE_TOKENS.sub("", value):
        return None
    dates = _dates(value)
    return next(iter(dates)) if len(dates) == 1 else None


def _amount(whole: str, frac: str | None, scale: str | None) -> float:
    return float(whole.replace(",", "") + (frac or "")) * _SCALE.get((scale or "").casefold(), 1.0)


def _amounts(text: str) -> set[float]:
    """Every number or amount ``text`` writes, scaled (``2.5 million`` is 2500000.0)."""
    return {_amount(*m.groups()) for m in _AMOUNT.finditer(text)}


def _gold_amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _AMOUNT_ONLY.fullmatch(value) if isinstance(value, str) else None
    return _amount(*m.groups()) if m else None


def _numerals(text: str) -> str:
    """Spelled-out numbers as digits; ``three (3)`` collapses to ``3``."""

    def word(m: re.Match[str]) -> str:
        if m.group(3):
            return str(_WORD_NUM[m.group(3)])
        return str(_TENS[m.group(1)] + _WORD_NUM[m.group(2)])

    text = _NUM_WORDS.sub(word, _norm(text))
    return re.sub(r"\b(\d+)\s*\(\s*\1\s*\)", r"\1", text)


def _normalized_form(item: Any, raw_text: str, text: str) -> str | None:
    """The canonical form under which ``item`` is written in the text, if any."""
    if isinstance(item, str):
        iso = _gold_date(item)
        if iso is not None:
            return DATE_FORM if iso in _dates(raw_text) else None
    amount = _gold_amount(item)
    if amount is not None and amount in _amounts(raw_text):
        return NUMBER_FORM
    if isinstance(item, str):
        needle = _numerals(item)
        if needle and needle in _numerals(text):
            return NUMERAL_FORM
    return None


def gold_field_grounding(
    rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    categorical: Iterable[str] = CATEGORICAL_FIELDS,
) -> list[GroundingFinding]:
    """One finding per gold value (per item for list fields).

    ``rows`` are cleaned manifest rows (``id``, ``text``, ``expected_fields`` as
    a dict), as ``prep.clean_manifest_rows`` returns; the default loads them.
    A string value is ``grounded`` when it appears in the row text, ignoring
    case and whitespace runs, and ``grounded_normalized`` when it appears only
    in a canonical form (see the module docstring). Numbers are matched by
    value. Fields in ``categorical`` are reported but not checked, and so are
    values with no text form (booleans, ``None``, objects).
    """
    if rows is None:
        from mailroom_sandbox.prep import clean_manifest_rows

        rows, _ = clean_manifest_rows()
    skip = frozenset(categorical)
    findings: list[GroundingFinding] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        raw_text = str(row.get("text") or "")
        text = _norm(raw_text)
        for name, value in (row.get("expected_fields") or {}).items():
            for item in _values(value):
                form = ""
                if name in skip:
                    status = CATEGORICAL
                elif isinstance(item, str) and _norm(item) and _norm(item) in text:
                    status = GROUNDED
                elif not isinstance(item, (str, int, float)) or isinstance(item, bool):
                    status = NON_TEXT
                elif isinstance(item, str) and not _norm(item):
                    status = UNGROUNDED
                else:
                    form = _normalized_form(item, raw_text, text) or ""
                    status = GROUNDED_NORMALIZED if form else UNGROUNDED
                findings.append(GroundingFinding(row_id, name, item, status, form))
    return findings


def ungrounded(findings: Iterable[GroundingFinding]) -> list[GroundingFinding]:
    """The findings whose extractive value is not in the fixture text."""
    return [f for f in findings if f.status == UNGROUNDED]
