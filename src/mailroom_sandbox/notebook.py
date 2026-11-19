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
- ``alias``: a canonical abbreviation in ``ALIASES`` (``SEC``) against its written
  forms (``Securities Exchange Act``).

Matches never split a word or number at an alphanumeric edge: ``3 years`` is not
grounded by ``13 years`` and ``SEC`` is not grounded by ``SECTION``.

Those matches are ``grounded_normalized`` with the ``form`` that matched, so
they stay distinguishable from literal ones.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
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
ALIAS_FORM = "alias"

# Canonical abbreviations the extraction prompts ask for, and the written forms that
# ground them. Keep this short and explicit: every entry widens what counts as grounded.
# "SEC": the compliance prompt names it as the regulatory_body; a 10-K states its
# regulator through the Act it is filed under ("Securities Exchange Act of 1934").
ALIASES: dict[str, tuple[str, ...]] = {
    "sec": ("securities and exchange commission", "securities exchange act"),
}

_WS = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_TOKENS = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|day|of|the)\b\.?|\d+(?:st|nd|rd|th)?|[\s,./-]",
    re.I,
)
_SCALE = {
    "k": Decimal(10**3),
    "thousand": Decimal(10**3),
    "m": Decimal(10**6),
    "mm": Decimal(10**6),
    "million": Decimal(10**6),
    "b": Decimal(10**9),
    "bn": Decimal(10**9),
    "billion": Decimal(10**9),
}
_AMOUNT = re.compile(
    r"(?<![\w.\-\u2212])([-\u2212]?)\$?\s?([-\u2212]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?(?![\w])",
    re.I,
)
_AMOUNT_ONLY = re.compile(
    r"\s*([-\u2212]?)\s*(?:usd|us\$|\$)?\s*([-\u2212]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(k|thousand|mm|m|million|bn|b|billion)?\s*(?:usd|dollars)?\s*",
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


def _contains(haystack: str, needle: str) -> bool:
    """``needle`` in ``haystack`` without splitting a word or number at an alphanumeric edge.

    ``3 years`` is not in ``13 years`` and ``Delaware`` is not in ``Delawarean``;
    an edge that is punctuation (``Inc.``) matches as a plain substring.
    """
    head = r"(?<!\w)" if needle[:1].isalnum() else ""
    tail = r"(?!\w)" if needle[-1:].isalnum() else ""
    return re.search(head + re.escape(needle) + tail, haystack) is not None


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


def _amount(sign: str, sign2: str, whole: str, frac: str | None, scale: str | None) -> Decimal:
    value = Decimal(whole.replace(",", "") + (frac or "")) * _SCALE.get(
        (scale or "").casefold(), Decimal(1)
    )
    return -value if (sign or sign2) else value


def _amounts(text: str) -> set[Decimal]:
    """Every number or amount ``text`` writes, scaled (``2.5 million`` is 2500000.0)."""
    return {_amount(*m.groups()) for m in _AMOUNT.finditer(text)}


def _gold_amount(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        try:
            return Decimal(repr(value))  # the shortest repr, not the binary expansion
        except InvalidOperation:  # nan / inf
            return None
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
        if any(_contains(text, alias) for alias in ALIASES.get(_norm(item), ())):
            return ALIAS_FORM
        needle = _numerals(item)
        if needle and _contains(_numerals(text), needle):
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
                elif isinstance(item, str) and _norm(item) and _contains(text, _norm(item)):
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


# --------------------------------------------------------------------------- agent fixtures

#: Agent fixture keys that hold a span the agent must reproduce from the row's own text.
AGENT_SNIPPET_KEYS: tuple[str, ...] = ("expected_snippet", "expected")


def agent_fixture_grounding(agents: Iterable[str] | None = None) -> list[GroundingFinding]:
    """``gold_field_grounding`` over ``data/fixtures/agents/*.jsonl``.

    A row is checked when it has text: a catalog document (``subdir`` + ``filename``) or
    inline ``text``. Its ``expected_fields`` and its expected snippets (``expected_snippet``,
    ``expected``) must be written in that text. Rows that carry only model output to
    judge (``extracted_data`` with no source document) or a binary ``file`` (image, PDF) have
    no text to ground against and yield no findings. A row whose catalog document is missing
    is checked against empty text, so its gold is reported ungrounded rather than skipped.
    Row ids are ``<agent>/<id>``.
    """
    from mailroom_sandbox.paths import fixtures_dir
    from mailroom_sandbox.prep import clean_agent_rows

    if agents is None:
        agents = sorted(p.stem for p in (fixtures_dir() / "agents").glob("*.jsonl"))
    rows: list[dict[str, Any]] = []
    for agent in agents:
        prepared, _ = clean_agent_rows(agent)
        for row in prepared:
            text = row.get("text")
            if not isinstance(text, str) or not text:
                if not (row.get("subdir") and row.get("filename")):
                    continue
                text = ""  # named catalog document is missing: all its gold is ungrounded
            gold = dict(row.get("expected_fields") or {})
            gold.update({k: row[k] for k in AGENT_SNIPPET_KEYS if isinstance(row.get(k), str)})
            if gold:
                rows.append({"id": f"{agent}/{row['id']}", "text": text, "expected_fields": gold})
    return gold_field_grounding(rows)


# --------------------------------------------------------------------------- label overlays

#: Label overlays the scoring fixes read as truth: the near-gold overlay (SHF-010 supersedes
#: interim gap fills with it) and the interim overlay (``dataset.interim_labels``).
LABEL_OVERLAYS: tuple[str, ...] = ("gold-overlay", "interim")

NO_EVIDENCE = "no_evidence"
#: A closed label with no quote: its value is in the field's vocabulary, which is all a closed
#: label states without evidence.
IN_VOCABULARY = "in_vocabulary"


@dataclass(frozen=True)
class LabelFinding:
    overlay: str
    doc_id: str
    doc_class: str
    field: str
    value: Any
    status: str  # grounded | ungrounded | in_vocabulary | no_evidence
    basis: str = ""
    reason: str = ""


def _evidence_quotes(label: Mapping[str, Any]) -> list[str]:
    """The quoted text of a label's evidence: span ``text``, an email ``header`` line, or a string."""
    quotes = []
    for item in label.get("evidence") or []:
        if isinstance(item, str):
            quotes.append(item)
        elif isinstance(item, Mapping):
            quote = item.get("text") or item.get("header")
            if isinstance(quote, str):
                quotes.append(quote)
    return [q for q in quotes if q.strip()]


def cached_doc_rows(path: Any = None) -> dict[str, dict[str, Any]]:
    """``{doc_id: row}`` from the pulled Hub corpus (``sandbox datasets pull``), or ``{}``.

    Reads ``datasets.full_corpus_cache_path()`` unless ``path`` is given. Never reaches the
    network: without a pulled cache, labels that need their document stay ``no_evidence``.
    """
    import json
    from pathlib import Path

    from mailroom_sandbox.datasets import full_corpus_cache_path
    from mailroom_sandbox.interim_labels import row_id

    src = Path(path) if path is not None else full_corpus_cache_path()
    if not src.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    # Split on newlines only: JSON strings may hold U+2028 and other separators splitlines() takes.
    for line in src.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            row = json.loads(line)
            if row_id(row):
                rows[row_id(row)] = row
    return rows


def _reviewed_label_status(
    doc_class: str, name: str, label: Mapping[str, Any], quotes: list[str]
) -> tuple[str, str]:
    """A reviewed label, by the review file's rule (``interim_labels``), then its quote if any."""
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    value, basis = label.get("value"), str(label.get("basis") or "")
    problem = il._review_value_problem(name, value)
    if not problem and basis == "original_header":
        problem = il._header_problem(name, value, label.get("evidence"))
    elif not problem and basis == "review_read_record":
        problem = il._record_quote_problem(value, label.get("evidence"))
    if problem:
        return UNGROUNDED, problem
    if basis != "original_header" and quotes:
        ok, reason = gl.evidence_support(doc_class, name, value, quotes)
        return (GROUNDED, "") if ok else (UNGROUNDED, reason)
    return (GROUNDED, "") if quotes else (IN_VOCABULARY, "")


def _hub_row_label_status(
    row: Mapping[str, Any], name: str, label: Mapping[str, Any]
) -> tuple[str, str]:
    """An unquoted label against its document's Hub row, by the build's own rule."""
    from mailroom_sandbox import interim_labels as il

    value, basis = label.get("value"), str(label.get("basis") or "")
    if label.get("status") == "correction" and basis.startswith("cuad_"):
        if il.contract_correction(name, value, il._expected(row)) == basis:
            return GROUNDED, ""
        return UNGROUNDED, f"not supported by the row's CUAD spans ({basis})"
    text = row.get("doc_text") if row.get("doc_text") is not None else row.get("text")
    if il.grounded(value, str(text or "")):
        return GROUNDED, ""
    return UNGROUNDED, "value not in the document"


def _check_label(
    record: Mapping[str, Any],
    doc_class: str,
    name: str,
    label: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    """``(status, reason)`` for one populated label, by the rule that admitted it.

    - ``derived``: recomputed from the record's own ``doc_subclass``.
    - a reviewed label (``review``): the review file's rule (``interim_labels``): header lines
      for ``original_header``, the quote for ``review_read_record``, the vocabulary for intents.
    - a stored quote: the label gate's value rules (``gold_labels.evidence_support``).
    - no quote, a closed label: the value is in the field's vocabulary (``in_vocabulary``).
    - no quote, the document's Hub row available (``rows``, bound by ``doc_sha256``): the
      build's own rule. A gap fill's every token is in the text (``interim_labels.grounded``);
      a CUAD correction agrees with the row's CUAD spans (``interim_labels.contract_correction``).
    - otherwise ``no_evidence``; a gap fill whose stored ``support`` is under the admission
      threshold is ``ungrounded``.
    """
    from mailroom_sandbox import gold_labels as gl
    from mailroom_sandbox import interim_labels as il

    value = label.get("value")
    status = label.get("status")
    if status == "derived":
        sub = str(record.get("doc_subclass") or "")
        want = sub if label.get("basis") == "cms_subclass" else il.derived_value(doc_class, sub)
        return (
            (GROUNDED, "")
            if value == want
            else (UNGROUNDED, f"{doc_class} subclass {sub!r} derives {want!r}")
        )
    quotes = _evidence_quotes(label)
    if label.get("review"):
        return _reviewed_label_status(doc_class, name, label, quotes)
    if quotes:
        ok, reason = gl.evidence_support(doc_class, name, value, quotes)
        return (GROUNDED, "") if ok else (UNGROUNDED, reason)
    allowed = gl._schema_bits(doc_class)[1].get(name)
    if allowed is not None:
        ok = value in allowed
        return (IN_VOCABULARY, "") if ok else (UNGROUNDED, f"out_of_vocabulary: {value!r}")
    row = rows.get(str(record.get("doc_id") or ""))
    if row is not None and il.row_doc_sha(row) == record.get("doc_sha256"):
        return _hub_row_label_status(row, name, label)
    support = label.get("support")
    if status == "gap_fill" and isinstance(support, (int, float)) and support < il.SUPPORT_MIN:
        return UNGROUNDED, f"support {support} is under the admission threshold {il.SUPPORT_MIN}"
    if row is not None:
        return NO_EVIDENCE, "document text changed since the label was read"
    return NO_EVIDENCE, ""


def label_overlay_grounding(
    overlays: Iterable[str] = LABEL_OVERLAYS,
    *,
    root: Any = None,
    rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[LabelFinding]:
    """Every populated truth label in the scoring overlays, checked by the rule that admitted it.

    See ``_check_label`` for the rule per kind of label. ``rows`` (``{doc_id: Hub row}``, e.g.
    ``cached_doc_rows()``) lets labels with no stored quote be checked against their document;
    without it they stay ``no_evidence``. Empty values and interim ``disputed`` labels (never
    truth) are not reported.
    """
    import json
    from pathlib import Path

    from mailroom_sandbox.paths import repo_root

    base = Path(root) if root is not None else repo_root() / "data" / "labels"
    rows = rows or {}
    findings: list[LabelFinding] = []
    for overlay in overlays:
        for path in sorted((base / overlay).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                doc_class = str(record.get("doc_class") or path.stem)
                for name, label in (record.get("labels") or {}).items():
                    if not isinstance(label, Mapping) or label.get("status") == "disputed":
                        continue
                    value = label.get("value")
                    if value is None or value == "" or value == []:
                        continue
                    status, reason = _check_label(record, doc_class, name, label, rows)
                    findings.append(
                        LabelFinding(
                            overlay,
                            str(record.get("doc_id") or ""),
                            doc_class,
                            name,
                            value,
                            status,
                            str(label.get("basis") or ""),
                            reason,
                        )
                    )
    return findings
