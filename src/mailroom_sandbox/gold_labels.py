"""Gold labels for unlabelled extraction fields: work queue, validation gate and catalog.

The Hub ground truth leaves many scored extraction fields unlabelled (correspondence sender,
recipient, date and urgency; contract signatories and dates; corporate dates, signatories and
jurisdiction). This module turns model-written labels for those fields into a catalog the
pipeline can score against, and keeps everything else the labeler said apart from it.

A labeler (an agent session, never an API call from here) writes one **submission** per
document::

    {"doc_id": "DOC-…", "labeler": {"model": "…", "role": "label|check", "batch": "…"},
     "fields": {"sender": {"value": "Jane Roe", "evidence": ["From: Jane Roe <jr@x.com>"]},
                "demand_amount": {"value": null, "absent": "no amount is demanded"}},
     "supplementary": {...anything else...}}

:func:`validate_submission` gates every field, in order:

1. the field is a target of the document's class (:data:`TARGET_FIELDS`);
2. an empty value carries an ``absent`` reason (the Dojo's documented absence), except a
   field whose contract empty value is not empty (correspondence ``urgency`` is ``routine``);
3. a closed-label value is in the Dojo scored vocabulary (``scored_enums``), never mapped;
4. every evidence quote is a verbatim slice of the document (whitespace-insensitive), at most
   :data:`MAX_QUOTE_CHARS` long, and is recorded as ``{start, end, text}``;
5. the value is supported by its evidence, by field type (dates: a written form of the ISO date
   with digit boundaries, or one spelled date expression holding the month name, the day and the
   year together; money: the exact figure appears in a quote that shows it as money, by a currency
   marker beside it or a word of payment in the quote; party roles: the role word appears too; name tokens;
   free-text token coverage; a closed label other than its default needs a quote of at least
   :data:`MIN_LABEL_QUOTE_TOKENS` tokens);
6. the whole payload (the class's contract-empty payload with the labels applied) validates
   against the pipeline's own pydantic model in ``schemas.documents.EXTRACTION_SCHEMAS``.

Fields that pass become catalog labels with status ``candidate``. :func:`reconcile` compares a
label pass with an independent check pass: agreeing values become ``near_gold`` (the owner's
name for labels Opus reviewed or two independent passes agree on). "Independent" means two
separate agent passes that did not see each other's output; the same model family may write
both. ``scripts/gold_labels.py build`` enforces what it can: no file serves as both passes, the
submissions' roles are ``label`` and ``check``, and no document appears twice in one pass;
disagreements are ``disputed`` and need a review decision (:func:`apply_review`, which keeps the
label it replaces under ``review.original`` and, for a ``correct`` or ``accept_check`` verdict,
records who produced the stored value in ``value_source``). :func:`verify_catalog` enforces the
``near_gold`` invariant: an agreeing check pass that passed the gate, or a review by a reviewer
with a model and a role. No status here
sets ``use_as_truth``: the refined-GT master copy lives in ``Exios66/Mailroom-Corpus-EDA``
(its issue #65), and an agent's label becomes gold there only with a reviewer's initials.
:func:`overlay_records` exports the ``near_gold`` labels in the overlay shape EDA's
``labeling/interim.py`` reads. Anything that fails a gate, plus each submission's ``supplementary``
block, goes to the supplementary store, which no scorer reads.

Files: ``data/labels/gold/`` (``<class>.jsonl`` + ``MANIFEST.json``, schema
``mailroom-gold-labels/v1``) and ``data/labels/gold-supplementary/`` (same layout, schema
``mailroom-gold-supplementary/v1``). Built by ``scripts/gold_labels.py``.
"""
from __future__ import annotations

import difflib
import functools
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from mailroom_sandbox.paths import repo_root, vendored_dojo_src, vendored_mailroom_src

SCHEMA = "mailroom-gold-labels/v1"
SUPPLEMENTARY_SCHEMA = "mailroom-gold-supplementary/v1"
STATUSES = ("candidate", "near_gold", "disputed", "rejected")
#: Empty on purpose: ``near_gold`` (Opus-reviewed, or two independent passes agree) is the tier
#: just below gold; a label becomes gold in EDA's master copy with a reviewer's initials.
TRUTH_STATUSES: tuple[str, ...] = ()
#: Below this many characters of text a correspondence row is a near-empty cover note
#: (Mailroom-Corpus-EDA #63); its labels are tagged ``near_empty``.
NEAR_EMPTY_CHARS = 200
OVERLAY_SCHEMA = "mailroom-interim-labels/v1"
#: An evidence quote is the smallest span that shows the value; a whole-document quote supports
#: anything, so the gate refuses quotes longer than this.
MAX_QUOTE_CHARS = 400
#: List fields quote whole To:/cc: blocks, which run long in distribution mail.
MAX_LIST_QUOTE_CHARS = 1500
#: A closed label other than its contract default needs a quote of at least this many tokens.
MIN_LABEL_QUOTE_TOKENS = 3

#: Unlabelled scored fields to label, per class, in priority order. Tier 1 is mission-critical:
#: who sent what to whom and when, how urgent it is, money demanded, who signed and when it
#: binds. Tier 2 is captured when the evidence supports it. Merger agreements are excluded
#: (length); their easy wins are deterministic, not labeled here.
TARGET_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "correspondence": {
        "tier1": ("sender", "recipient", "communication_date", "urgency", "demand_amount", "action_items"),
        "tier2": ("additional_recipients",),
    },
    "corporate_record": {
        "tier1": ("effective_date", "signatories", "jurisdiction", "entity_name"),
        "tier2": (),
    },
    "contract": {
        "tier1": ("agreement_date", "expiration_date", "signatories", "party_roles",
                  "termination_notice_period", "contract_value"),
        "tier2": ("dispute_forum", "payment_terms", "territory"),
    },
}

#: Presence codes that mean the Hub already labels the field: never relabel those.
_HUB_LABELLED = frozenset({"populated", "schema_documented_absence", "not_applicable"})


def _ensure_vendor_path() -> None:
    """Put the vendored pipeline and Dojo snapshots first on ``sys.path`` (the pinned pair)."""
    for src in (vendored_dojo_src(), vendored_mailroom_src()):
        if src is not None and str(src) not in sys.path:
            sys.path.insert(0, str(src))


def target_fields(doc_class: str, tiers: Iterable[str] = ("tier1", "tier2")) -> tuple[str, ...]:
    spec = TARGET_FIELDS.get(doc_class, {})
    return tuple(f for tier in tiers for f in spec.get(tier, ()))


# --------------------------------------------------------------------------- work queue


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def hub_labels(field_name: str, gt_fields: Mapping[str, Any]) -> bool:
    """Whether the Hub row already labels ``field_name`` (a value or a presence code)."""
    presence = _parse_json(gt_fields.get("gt_presence")) or {}
    if isinstance(presence, Mapping) and presence.get(field_name) in _HUB_LABELLED:
        return True
    value = _parse_json(gt_fields.get(field_name))
    return value not in (None, "", [], {}, "nan", "[]", "{}")


def work_queue(rows: Iterable[Mapping[str, Any]], tiers: Iterable[str] = ("tier1", "tier2")) -> list[dict[str, Any]]:
    """One entry per document with at least one unlabelled target field.

    ``rows`` are ``ground_truth`` rows (``expected``, ``gt_fields``, ``document_id``, …).
    """
    tiers = tuple(tiers)
    out = []
    for row in rows:
        cls = row.get("expected")
        fields = target_fields(cls, tiers)
        if not fields:
            continue
        gt = _parse_json(row.get("gt_fields")) or {}
        todo = [f for f in fields if not hub_labels(f, gt)]
        if todo:
            out.append({
                "doc_id": row["document_id"],
                "filename": row["filename"],
                "doc_class": cls,
                "subclass": row.get("expected_subclass"),
                "content_sha256": row.get("content_sha256"),
                "fields": todo,
            })
    return out


# --------------------------------------------------------------------------- evidence


_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def _collapse(text: str) -> tuple[str, list[int]]:
    """Text with whitespace runs collapsed to one space, and each kept char's source offset."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            prev_space = True
        else:
            out.append(ch)
            prev_space = False
        idx.append(i)
    return "".join(out), idx


def locate(quote: str, doc_text: str, *, _cache: dict[int, tuple[str, str, list[int]]] | None = None) -> dict[str, Any] | None:
    """The span of ``quote`` in ``doc_text`` (whitespace- then case-insensitive), or None."""
    q = _WS.sub(" ", quote).strip()
    if not q:
        return None
    collapsed, idx = _collapse(doc_text)
    pos = collapsed.find(q)
    if pos >= 0:
        start, end = idx[pos], idx[pos + len(q) - 1] + 1
        return {"start": start, "end": end, "text": doc_text[start:end]}
    # Case-insensitive pass. casefold() can change a character's length ("ß" -> "ss",
    # "İ" -> "i̇"), so every folded character maps back to the collapsed character it came from.
    folded, back = [], []
    for i, ch in enumerate(collapsed):
        piece = ch.casefold()
        folded.append(piece)
        back.extend([i] * len(piece))
    hay, needle = "".join(folded), q.casefold()
    pos = hay.find(needle)
    if pos >= 0 and needle:
        start, end = idx[back[pos]], idx[back[pos + len(needle) - 1]] + 1
        return {"start": start, "end": end, "text": doc_text[start:end]}
    return None


def _date_forms(value: str) -> set[str]:
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return set()
    m, s = d.strftime("%B"), d.strftime("%b")
    day = d.day
    suf = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    # Day-first numeric dates count only when they cannot be read month-first (day > 12).
    # A two-digit year is read only inside the window a letter or memo can plausibly mean.
    short_year = {f"{d.month}/{day}/{d:%y}", f"{d:%m/%d/%y}", f"{day}-{s}-{d:%y}", f"{d:%d}-{s}-{d:%y}"}
    forms = {
        f"{d:%Y-%m-%d}", f"{d.month}/{day}/{d.year}", f"{d:%m/%d/%Y}", f"{m} {day}, {d.year}", f"{m} {day} {d.year}", f"{day} {m} {d.year}",
        f"{day} {m}, {d.year}", f"{s} {day}, {d.year}", f"{s}. {day}, {d.year}", f"{s} {day} {d.year}",
        f"{m} {day}{suf}, {d.year}", f"{day}{suf} day of {m}, {d.year}", f"{day}{suf} day of {m} {d.year}",
        f"{day}{suf} of {m}, {d.year}", f"{day}-{s}-{d.year}",
        f"{d.year}.{d:%m}.{d:%d}", f"{d.year}/{d:%m}/{d:%d}",
    }
    if 1950 <= d.year <= 2049:
        forms |= short_year
    if day > 12:
        forms |= {f"{d:%d}/{d:%m}/{d.year}", f"{day}/{d.month}/{d.year}", f"{d:%d}-{d:%m}-{d.year}"}
    return forms


def _bounded(form: str, text: str) -> bool:
    """Whether ``form`` occurs in ``text`` with no digit (or, for slash forms, slash) beside it."""
    extra = "/" if "/" in form else ""
    pattern = rf"(?<![0-9{extra}]){re.escape(form)}(?![0-9{extra}])"
    return re.search(pattern, text) is not None


def _spelled_date_supported(d: date, ev: str) -> bool:
    """One spelled date expression that holds the month name, the day and the year together:
    "May 14, 2020", "May 14th 2020", "14 May 2020", "14th day of May, 2020". Only separators
    (spaces, a comma) and the connective "day of" / "of" may sit between the parts, so the year
    of another date in the quote ("May 14, 2019 ... December 31, 2020") never supports this one."""
    names = {d.strftime("%B").casefold(), d.strftime("%b").casefold()}
    if d.month == 9:
        names.add("sept")
    mon = r"(?:" + "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True)) + r")\.?"
    # EDGAR text often splits the ordinal from the day ("27 th day of March"): allow one space.
    day = rf"0?{d.day}(?:\s?(?:st|nd|rd|th)(?![a-z]))?(?![0-9]|:[0-9])"
    year = rf"(?<![0-9]){d.year}(?![0-9])"
    month_first = rf"(?<![a-z]){mon}(?![a-z])\s*,?\s*{day}\s*,?\s*{year}"
    day_first = rf"(?<![0-9]){day}\s+(?:day\s+)?(?:of\s+)?{mon}(?![a-z])\s*,?\s*{year}"
    return bool(re.search(month_first, ev) or re.search(day_first, ev))


def _date_supported(value: str, evidence: str) -> bool:
    ev = _WS.sub(" ", evidence.casefold())
    if any(_bounded(f.casefold(), ev) for f in _date_forms(value)):
        return True
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return _spelled_date_supported(d, ev)


_FIGURE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d]|,\d)(\s*(?:million|billion|thousand)\b)?"
                     r"(?!\s*%)", re.I)
#: A written date ("May 14, 2020", "14 May 2020", "5/14/2020", "2020-05-14"): its numbers are never
#: money by a payment word alone ("Please pay by May 14, 2020" shows no amount of 2020 or 14).
_DATE_SPAN = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+\d{4}\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", re.I)
_SCALE = {"thousand": Decimal(10) ** 3, "million": Decimal(10) ** 6, "billion": Decimal(10) ** 9}
_NOT_PLAIN_NUMBER = re.compile(r"\d_\d|\d[eE][+-]?\d")
#: A figure is shown as money by a currency marker beside it, or by a word of payment in the quote.
_CURRENCY_BEFORE = re.compile(r"(?:us\$|\$|usd|\u20ac|\u00a3)\s*$", re.I)
_CURRENCY_AFTER = re.compile(r"^\s*(?:usd|dollars?|\u20ac|\u00a3)(?![a-z])", re.I)
_MONEY_WORDS = re.compile(r"\b(?:amounts?|pay(?:s|ing|ments?|able)?|sums?|fees?|prices?|owe[sd]?|owing|"
                          r"balances?|totals?)\b", re.I)


def _figures(text: str, *, as_money: bool = False) -> set[Decimal]:
    """Every numeric figure written in ``text`` ($, thousands commas, decimals, "2.5 million"),
    exactly. A figure followed by a scale word counts only as its scaled amount. With
    ``as_money`` only figures the text shows as money count: a currency marker ($, US$, USD,
    dollars, euro, pound) beside the figure, or a word of payment (amount, pay, payment, sum,
    fee, price, owe, balance, total) anywhere in the text. "Dated May 14, 2020" shows none."""
    out = set()
    worded = as_money and _MONEY_WORDS.search(text) is not None
    dates = [d.span() for d in _DATE_SPAN.finditer(text)] if as_money else []
    for m in _FIGURE.finditer(text):
        marked = as_money and (_CURRENCY_BEFORE.search(text[:m.start()])
                               or _CURRENCY_AFTER.search(text[m.end():]))
        in_date = any(a <= m.start() and m.end() <= b for a, b in dates)
        if as_money and not (marked or (worded and not in_date)):
            continue
        try:
            num = Decimal(m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else ""))
        except InvalidOperation:  # pragma: no cover - the pattern only admits digits
            continue
        scale = (m.group(3) or "").strip().casefold()
        out.add(num * _SCALE[scale] if scale else num)
    return out


def _money_supported(value: float, evidence: str) -> bool:
    """A finite amount equals, exactly, a figure the quote shows as money."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return Decimal(repr(float(value))) in _figures(evidence, as_money=True)


#: A plain dollar figure ("$5,000,000", "$400,000.00"): the currency-phrase form the Dojo's money
#: scorer parses. Scale words, currency codes and rates ("$5 million", "US$", "USD", "per month")
#: are not parsed, so a correct prediction would score below 1 against them.
_PLAIN_DOLLARS = re.compile(r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _money_text_supported(value: str, evidence: str) -> bool:
    """A currency phrase kept as text: it appears in the evidence as written (whitespace
    normalised, not inside a longer figure) and holds a finite figure the quote shows as money.
    A plain dollar figure may also restate, exactly, a figure the quote writes with a scale word
    ("$5,000,000" for "$5 million")."""
    phrase = _WS.sub(" ", value).strip()
    if not phrase or _NOT_PLAIN_NUMBER.search(phrase):
        return False
    ev = _WS.sub(" ", evidence)
    shown = _figures(ev, as_money=True)
    if _PLAIN_DOLLARS.fullmatch(phrase):
        return bool(_figures(phrase) & shown)
    if not re.search(rf"(?<![\d,.]){re.escape(phrase.casefold())}(?![\d]|[,.]\d)", ev.casefold()):
        return False
    return bool(_figures(phrase) & shown)


def money_text_parses(value: Any) -> bool:
    """Whether the Dojo's money scorer reads a currency-phrase label as a number."""
    _ensure_vendor_path()
    from llm_dojo_scoring.scoring.field_scoring import parse_money

    return _is_empty(value) or parse_money(value) is not None


def _token_coverage(value: str, evidence: str) -> float:
    toks = _tokens(value)
    if not toks:
        return 0.0
    ev = set(_tokens(evidence))
    return sum(t in ev for t in toks) / len(toks)


# --------------------------------------------------------------------------- validation


@dataclass
class FieldResult:
    field: str
    ok: bool
    value: Any = None
    presence: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    absent_reason: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass
class SubmissionResult:
    doc_id: str
    doc_class: str
    fields: dict[str, FieldResult] = field(default_factory=dict)
    payload_valid: bool = False
    payload_error: str | None = None

    @property
    def accepted_fields(self) -> dict[str, FieldResult]:
        return {k: v for k, v in self.fields.items() if v.ok}


def _schema_bits(doc_class: str):
    _ensure_vendor_path()
    from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS
    from llm_dojo_scoring.schemas.schema_contract import contract_empty_payload, contract_empty_value
    from llm_dojo_scoring.scoring.suites import DEFAULT_FIELD_TYPES
    from schemas.documents import EXTRACTION_SCHEMAS

    return (
        DEFAULT_FIELD_TYPES[doc_class],
        {f: tuple(v[0]) for f, v in SCORED_ENUM_FIELDS.get(doc_class, {}).items()},
        contract_empty_payload(doc_class),
        lambda f: contract_empty_value(doc_class, f),
        EXTRACTION_SCHEMAS[doc_class],
    )


def _text_field(model: Any, name: str) -> bool:
    """Whether the pipeline model declares ``name`` as text only (no float)."""
    info = getattr(model, "model_fields", {}).get(name)
    return info is not None and "float" not in str(info.annotation)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _normalize(value: Any, ftype: str) -> Any:
    if isinstance(value, str):
        value = _WS.sub(" ", value).strip()
    if isinstance(value, list):
        value = [_WS.sub(" ", str(v)).strip() for v in value if str(v).strip()]
    if ftype == "money" and isinstance(value, str):
        text = re.sub(r"\s+", "", value.replace("USD", "").replace("$", "").replace(",", ""))
        # Only a plain decimal is a number: float() would also take "1_000", "1e3", "nan" and "inf".
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            value = float(text)
    if ftype == "money" and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    return value


def _party_roles() -> tuple[str, ...]:
    _ensure_vendor_path()
    from llm_dojo_scoring.schemas.cuad_schema import CONTRACT_PARTY_ROLES

    return tuple(CONTRACT_PARTY_ROLES)


def _role_in_evidence(role: str, evidence: str) -> bool:
    """The role word (plural or defined-term form, any case) is written in the evidence."""
    words = [re.escape(w) for w in re.split(r"[_\s-]+", role.strip().casefold()) if w]
    pattern = r"(?<![a-z0-9])" + r"[\s_-]+".join(words) + r"s?(?![a-z0-9])"
    return re.search(pattern, evidence.casefold()) is not None


def _field_rule(name: str, value: Any, evidence: str = "") -> str | None:
    """Per-field rules the pipeline prompts state beyond the field type."""
    if name == "action_items" and isinstance(value, list) and len(value) > 3:
        return "action_items holds at most 3 items"
    if name == "party_roles" and isinstance(value, list):
        roles = _party_roles()
        for item in value:
            party, sep, role = str(item).rpartition(":")
            if not sep or not party.strip() or role.strip() not in roles:
                return f"party_roles item {item!r} is not '<party>: <role>' with a known role"
            # "other" is the honest fallback and has no word of its own to quote.
            if role.strip() != "other" and not _role_in_evidence(role, evidence):
                return f"party_roles item {item!r}: role {role.strip()!r} is not stated in the evidence"
    return None


def _entry_quotes(entry: Mapping[str, Any]) -> list | None:
    """The entry's evidence as a list of quotes (None = not a list or a string)."""
    quotes = entry.get("evidence") or []
    if isinstance(quotes, str):
        quotes = [quotes]
    return quotes if isinstance(quotes, list) else None


def _finish_empty(res: FieldResult, entry: Mapping[str, Any], ftype: str, empty_value: Any) -> FieldResult:
    """An empty value is valid only at the contract's empty value, with a stated absent reason."""
    if not _is_empty(empty_value):
        res.reason = f"empty value not allowed; contract empty value is {empty_value!r}"
        return res
    reason = (entry.get("absent") or "").strip() if isinstance(entry.get("absent"), str) else ""
    if not reason:
        res.reason = "empty value without an absent reason"
        return res
    res.value = [] if ftype.startswith("entity_list") else None
    res.presence = "schema_documented_absence"
    res.absent_reason = reason
    res.ok = True
    return res


def _finish_unquoted(res: FieldResult, entry: Mapping[str, Any], value: Any,
                     vocab: tuple[str, ...] | None, empty_value: Any) -> FieldResult:
    """A value without evidence quotes: only a closed label at its contract default may stand."""
    # A label at its contract default (urgency: routine) may rest on the absence of any
    # time pressure; it still needs a stated basis.
    if vocab is not None and value == empty_value and (entry.get("absent") or entry.get("basis")):
        res.presence = "populated"
        res.absent_reason = entry.get("absent") or entry.get("basis")
        res.ok = True
        return res
    res.reason = "no evidence quote"
    return res


def _locate_quotes(res: FieldResult, quotes: list, ftype: str, doc_text: str) -> list | None:
    """Locate every quote verbatim in the document (None = one failed; ``res`` says why)."""
    spans = []
    cap = MAX_LIST_QUOTE_CHARS if ftype.startswith("entity_list") else MAX_QUOTE_CHARS
    for q in quotes:
        if len(_WS.sub(" ", str(q)).strip()) > cap:
            res.reason = f"evidence quote too long (over {cap} characters)"
            res.checks["evidence_verbatim"] = False
            return None
        span = locate(str(q), doc_text)
        if span is None:
            res.reason = f"evidence not found verbatim: {str(q)[:80]!r}"
            res.checks["evidence_verbatim"] = False
            return None
        spans.append(span)
    return spans


def _date_value_supported(res: FieldResult, value: Any, spans: list) -> bool | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        res.reason = f"date not ISO YYYY-MM-DD: {value!r}"
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        res.reason = f"invalid date: {value!r}"
        return None
    return any(_date_supported(value, sp["text"]) for sp in spans)


def _money_value_supported(res: FieldResult, value: Any, spans: list) -> bool | None:
    if not isinstance(value, float) or not math.isfinite(value):
        res.reason = f"money not a finite number: {value!r}"
        return None
    return any(_money_supported(value, sp["text"]) for sp in spans)


def _label_value_supported(res: FieldResult, value: Any, empty_value: Any, spans: list) -> bool | None:
    # Vocabulary already checked. A label other than its contract default must rest on a
    # real sentence fragment, not on a single keyword.
    supported = value == empty_value or any(len(_tokens(sp["text"])) >= MIN_LABEL_QUOTE_TOKENS for sp in spans)
    if not supported:
        res.checks["value_supported"] = False
        res.reason = f"closed label needs an evidence quote of at least {MIN_LABEL_QUOTE_TOKENS} tokens"
        return None
    return supported


def _list_value_supported(res: FieldResult, value: Any, ftype: str, ev_text: str) -> bool | None:
    if not isinstance(value, list):
        res.reason = "list field needs a list"
        return None
    need = 0.6 if "free_text" in ftype or ftype == "entity_list" else 0.8
    return all(_token_coverage(v, ev_text) >= need for v in value)


def _value_supported(res: FieldResult, value: Any, raw_value: Any, ftype: str, spans: list,
                     ev_text: str, empty_value: Any, money_as_text: bool) -> bool | None:
    """Whether the located evidence supports the value (None = a type rule failed; ``res`` says why)."""
    if ftype == "date":
        # One quote must hold the whole date: "May 14" and "2020" from two quotes never make one.
        return _date_value_supported(res, value, spans)
    if ftype == "money" and money_as_text:
        # The pipeline field is a currency phrase (contract_value: str), kept as written.
        return any(_money_text_supported(str(raw_value), sp["text"]) for sp in spans)
    if ftype == "money":
        return _money_value_supported(res, value, spans)
    if ftype == "label":
        return _label_value_supported(res, value, empty_value, spans)
    if ftype.startswith("entity_list"):
        return _list_value_supported(res, value, ftype, ev_text)
    if ftype == "free_text":
        return _token_coverage(str(value), ev_text) >= 0.6
    return _token_coverage(str(value), ev_text) >= 0.8  # name, id


def _check_field(name: str, entry: Mapping[str, Any], doc_text: str, ftype: str,
                 vocab: tuple[str, ...] | None, empty_value: Any, *, money_as_text: bool = False) -> FieldResult:
    res = FieldResult(field=name, ok=False, evidence=[], checks={})
    if not isinstance(entry, Mapping):
        res.reason = "entry is not an object"
        return res
    raw_value = entry.get("value")
    value = _normalize(raw_value, ftype)
    res.value = value
    quotes = _entry_quotes(entry)
    if quotes is None:
        res.reason = "evidence is not a list of quotes"
        return res

    if vocab is not None and not _is_empty(value):
        res.checks["in_vocabulary"] = value in vocab
        if not res.checks["in_vocabulary"]:
            res.reason = f"out_of_vocabulary: {value!r}"
            return res

    if _is_empty(value):
        return _finish_empty(res, entry, ftype, empty_value)
    if not quotes:
        return _finish_unquoted(res, entry, value, vocab, empty_value)

    spans = _locate_quotes(res, quotes, ftype, doc_text)
    if spans is None:
        return res
    res.checks["evidence_verbatim"] = True
    res.evidence = spans
    ev_text = " ".join(s["text"] for s in spans)

    supported = _value_supported(res, value, raw_value, ftype, spans, ev_text, empty_value, money_as_text)
    if supported is None:
        return res
    res.checks["value_supported"] = supported
    if not supported:
        res.reason = "value not supported by its evidence"
        return res
    rule = _field_rule(name, value, ev_text)
    if rule:
        res.reason = rule
        return res
    if ftype == "money" and money_as_text:
        res.value = _WS.sub(" ", str(raw_value)).strip()
    res.presence = "populated"
    res.ok = True
    return res


def evidence_support(doc_class: str, name: str, value: Any, quotes: list[str]) -> tuple[bool, str]:
    """``(supported, reason)``: whether ``quotes`` support ``value`` under the gate's value rules.

    The same type rules as the gate (dates in one quote, money by value, token coverage for
    names, ids and free text, label vocabulary and quote length) applied to a stored label and
    its stored evidence. The gate's quote-location and quote-length caps are not applied: the
    evidence is already the text, and a long header line is still evidence. An empty value is
    supported (absence is not checked here).
    """
    types, vocab, _empty, empty_value, model = _schema_bits(doc_class)
    if name not in types:
        return False, f"not a target field of {doc_class}"
    ftype = str(types[name])
    norm = _normalize(value, ftype)
    allowed = vocab.get(name)
    if allowed is not None and not _is_empty(norm) and norm not in allowed:
        return False, f"out_of_vocabulary: {norm!r}"
    if _is_empty(norm):
        return True, ""
    spans = [{"text": q} for q in quotes if isinstance(q, str) and q]
    if not spans:
        return False, "no evidence quote"
    res = FieldResult(field=name, ok=False)
    supported = _value_supported(res, norm, value, ftype, spans, " ".join(s["text"] for s in spans),
                                 empty_value(name), _text_field(model, name))
    if supported is None:
        return False, res.reason or "type rule failed"
    return bool(supported), "" if supported else "value not supported by its evidence"


def validate_submission(sub: Mapping[str, Any], doc_text: str, doc_class: str) -> SubmissionResult:
    """Run the gate on one submission (see the module docstring for the order)."""
    result = SubmissionResult(doc_id=str(sub.get("doc_id")), doc_class=doc_class)
    try:
        types, vocab, empty_payload, empty_value, model = _schema_bits(doc_class)
    except KeyError:
        # A class the pipeline has no extraction schema for: nothing can pass the gate.
        result.payload_error = f"no extraction schema for class {doc_class!r}"
        fields = sub.get("fields")
        for name in (fields if isinstance(fields, Mapping) else {}):
            result.fields[name] = FieldResult(field=name, ok=False, evidence=[], checks={},
                                              reason=f"no extraction schema for class {doc_class!r}")
        return result
    allowed = set(target_fields(doc_class))
    fields = sub.get("fields")
    if fields is None:
        fields = {}
    if not isinstance(fields, Mapping):
        result.payload_error = f"fields is not an object (got {type(fields).__name__})"
        return result
    for name, entry in fields.items():
        if name not in allowed:
            result.fields[name] = FieldResult(field=name, ok=False, reason="not a target field",
                                              evidence=[], checks={})
            continue
        result.fields[name] = _check_field(name, entry, doc_text, str(types[name]), vocab.get(name),
                                           empty_value(name), money_as_text=_text_field(model, name))
    payload = dict(empty_payload)
    for name, fr in result.accepted_fields.items():
        payload[name] = fr.value
    try:
        model.model_validate(payload)
        result.payload_valid = True
    except Exception as exc:  # pydantic.ValidationError; keep this module pydantic-agnostic
        result.payload_valid = False
        result.payload_error = str(exc).splitlines()[0][:300]
        for fr in result.accepted_fields.values():
            fr.ok = False
            fr.reason = "pipeline schema rejected the payload"
    return result


# --------------------------------------------------------------------------- agreement


def _canon(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(" ".join(_tokens(str(v))) for v in value)
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, str):
        return " ".join(_tokens(value))
    return value


#: A negation in one reading of a free-text value and not in the other flips its meaning.
_NEGATIONS = frozenset({"not", "no", "never", "without"})
#: Stems of n't contractions; tokenising splits "didn't" into "didn" + "t".
_CONTRACTION_STEMS = frozenset({"didn", "doesn", "don", "isn", "aren", "wasn", "weren", "haven", "hasn",
                                "hadn", "won", "wouldn", "can", "couldn", "shouldn", "mustn"})


def _negated(canon: str) -> bool:
    """Whether a canonical value negates: "not", "no", "never", "without", "cannot" or an n't contraction."""
    words = canon.split()
    if not _NEGATIONS.isdisjoint(words) or "cannot" in words:
        return True
    return any(w == "t" and i and words[i - 1] in _CONTRACTION_STEMS for i, w in enumerate(words))


def _token_f1(x: str, y: str) -> float:
    tx, ty = set(x.split()), set(y.split())
    if not tx or not ty:
        return 0.0
    both = len(tx & ty)
    return 0.0 if not both else 2 * both / (len(tx) + len(ty))


def _lists_match(a: list[str], b: list[str], threshold: float = 0.5) -> bool:
    """Free-text lists agree when they have the same length and pair up item by item
    (greedy, best pair first) with token F1 at least ``threshold`` (paraphrase-tolerant)."""
    if len(a) != len(b):
        return False
    pairs = sorted(((_token_f1(x, y), i, j) for i, x in enumerate(a) for j, y in enumerate(b)
                    if _negated(x) == _negated(y)), reverse=True)
    used_a, used_b = set(), set()
    for score, i, j in pairs:
        if i in used_a or j in used_b or score < threshold:
            continue
        used_a.add(i)
        used_b.add(j)
    return len(used_a) == len(a)


_ROLE_ITEM = re.compile(r"^(.+?):\s*([A-Za-z][A-Za-z _-]*)$")


def _role_map(value: Any) -> list[tuple[frozenset[str], str]] | None:
    """``[(party tokens, role)]`` when every item reads "Party: role", else None."""
    if not isinstance(value, list) or not value:
        return None
    out = []
    for item in value:
        m = _ROLE_ITEM.match(str(item).strip())
        if not m:
            return None
        out.append((frozenset(_tokens(m.group(1))), " ".join(_tokens(m.group(2)))))
    return out


def _party_match(a: frozenset[str], b: frozenset[str]) -> float:
    """How surely two names are one party: 2 same words, 1 one adds words, the typo ratio, or 0."""
    if a == b:
        return 2.0
    if a <= b or b <= a:
        return 1.0
    ratio = difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return ratio if ratio >= 0.9 else 0.0


def _role_maps_agree(a: list, b: list) -> bool:
    """Same parties with the same role each. Parties are paired by name alone, best match
    first, and only then are their roles compared, so overlapping names cannot swap roles.
    A pairing that ties with another open pairing for the same party is ambiguous, and an
    ambiguous pairing never agrees (list order must not decide it)."""
    if len(a) != len(b):
        return False
    score = {(i, j): _party_match(na, nb) for i, (na, _) in enumerate(a) for j, (nb, _) in enumerate(b)}
    left, right, matched = set(range(len(a))), set(range(len(b))), {}
    for (i, j), s in sorted(score.items(), key=lambda kv: kv[1], reverse=True):
        if s > 0 and i in left and j in right:
            if any(score[i, k] == s for k in right - {j}) or any(score[k, j] == s for k in left - {i}):
                return False
            matched[i] = j
            left.discard(i)
            right.discard(j)
    return not left and all(a[i][1] == b[j][1] for i, j in matched.items())


def values_agree(a: Any, b: Any, ftype: str) -> bool:
    """Whether two labels for one field say the same thing (type-aware, order-free lists)."""
    if _is_empty(a) or _is_empty(b):
        return _is_empty(a) and _is_empty(b)
    if ftype.startswith("entity_list"):
        ca, cb = _canon(a), _canon(b)
        if ca == cb:
            return True
        ra, rb = _role_map(a), _role_map(b)
        if ra is not None and rb is not None:
            # "Party: role" lists (contract party_roles) agree only when each party has the same role.
            return _role_maps_agree(ra, rb)
        if ftype in ("entity_list", "entity_list:free_text"):
            return _lists_match(ca, cb)
        # same set of people/parties when one side adds a title or middle initial
        if len(ca) != len(cb):
            return False
        return all(set(x.split()) <= set(y.split()) or set(y.split()) <= set(x.split())
                   for x, y in zip(ca, cb))
    if ftype in ("name", "free_text"):
        if ftype == "free_text" and _negated(_canon(a)) != _negated(_canon(b)):
            return False
        ta, tb = set(_canon(a).split()), set(_canon(b).split())
        if ta == tb:
            return True
        small, big = sorted((ta, tb), key=len)
        if not small or not small <= big:
            return False
        # A full personal name inside a longer "name, title, entity" line is the same sender.
        return len(small) >= 2 or len(small) / len(big) >= (0.6 if ftype == "name" else 0.5)
    return _canon(a) == _canon(b)


# --------------------------------------------------------------------------- catalog


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_sha(doc_text: str) -> str:
    return _sha(doc_text)[:16]


def label_record(doc: Mapping[str, Any], fr: FieldResult, labeler: Mapping[str, Any], *,
                 status: str, schema_binding: Mapping[str, Any], doc_text: str,
                 check: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rec = {
        "label_id": _sha(f"{doc['doc_id']}|{fr.field}")[:20],
        "doc_id": doc["doc_id"],
        "filename": doc.get("filename"),
        "doc_class": doc["doc_class"],
        "subclass": doc.get("subclass"),
        "content_sha256": doc.get("content_sha256"),
        "doc_sha": doc_sha(doc_text),
        "field": fr.field,
        "value": fr.value,
        "presence": fr.presence,
        "evidence": fr.evidence,
        "absent_reason": fr.absent_reason,
        "status": status,
        "use_as_truth": status in TRUTH_STATUSES,
        "near_empty": len(doc_text.strip()) < NEAR_EMPTY_CHARS,
        "labeler": dict(labeler),
        "checks": dict(fr.checks or {}),
        "schema": dict(schema_binding),
    }
    if check is not None:
        rec["check"] = dict(check)
    return rec


def reconcile(doc: Mapping[str, Any], doc_text: str, label: SubmissionResult, check: SubmissionResult | None,
              labeler: Mapping[str, Any], checker: Mapping[str, Any] | None,
              schema_binding: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Catalog records and supplementary rejects for one document.

    A field passes when the label pass passed the gate. With a check pass: both passed and
    agree → ``near_gold``; they disagree, or only one passed → ``disputed`` (the check's value
    is kept for review). Without a check pass → ``candidate``.
    """
    try:
        types = _schema_bits(doc["doc_class"])[0]
    except KeyError:  # no extraction schema: no field passed the gate, so nothing is compared
        types = {}
    records, rejects = [], []
    for name, fr in label.fields.items():
        if not fr.ok:
            rejects.append({"doc_id": doc["doc_id"], "field": name, "value": fr.value, "reason": fr.reason,
                            "pass": "label", "labeler": dict(labeler)})
            continue
        if check is None:
            records.append(label_record(doc, fr, labeler, status="candidate",
                                        schema_binding=schema_binding, doc_text=doc_text))
            continue
        cr = check.fields.get(name)
        info = {"labeler": dict(checker or {}), "value": None if cr is None else cr.value,
                "gate_ok": bool(cr and cr.ok), "reason": None if cr is None else cr.reason}
        agree = bool(cr and cr.ok and values_agree(fr.value, cr.value, str(types[name])))
        info["agrees"] = agree
        records.append(label_record(doc, fr, labeler, status="near_gold" if agree else "disputed",
                                    schema_binding=schema_binding, doc_text=doc_text, check=info))
    if check is not None:
        for name, cr in check.fields.items():
            if not cr.ok:
                rejects.append({"doc_id": doc["doc_id"], "field": name, "value": cr.value,
                                "reason": cr.reason, "pass": "check", "labeler": dict(checker or {})})
    return records, rejects


REVIEW_VERDICTS = ("accept", "reject", "correct", "accept_check")


def reviewer_problem(reviewer: Any) -> str | None:
    """Why ``reviewer`` cannot sign a review decision (None = fine): an object with a
    non-empty ``model`` and ``role``."""
    if not reviewer:
        return "has no reviewer"
    if not isinstance(reviewer, Mapping):
        return "reviewer must be an object with model and role"
    for key in ("model", "role"):
        val = reviewer.get(key)
        if not isinstance(val, str) or not val.strip():
            return f"reviewer.{key} is missing or empty"
    return None


def apply_review(record: dict[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """Settle a disputed (or candidate) record with a reviewer's decision.

    ``decision``: ``{"verdict": "accept"|"reject"|"correct"|"accept_check", "reviewer": {model,
    role} (required), "value"?: corrected, "evidence"?: [spans], "note"?: str}``. A correction
    (``correct``) and an adopted check answer (``accept_check``, which also carries
    ``check_labeler``) must already have passed :func:`validate_submission` (the caller
    re-validates them). Both keep the label they replace under ``review.original`` and set
    ``value_source`` to who produced the value now stored: the reviewer (``review_correction``)
    or the check labeler (``check_pass``). The stored verdict stays as given.
    """
    problem = reviewer_problem(decision.get("reviewer"))
    if problem:
        raise ValueError(f"a review decision needs a reviewer: {problem}")
    out = dict(record)
    verdict = decision.get("verdict")
    if verdict is None:
        raise ValueError("a review decision needs a verdict")
    if verdict == "accept":
        out["status"] = "near_gold"
    elif verdict == "reject":
        out["status"] = "rejected"
    elif verdict in ("correct", "accept_check"):
        if "value" not in decision:
            raise ValueError(f"a {verdict} decision needs a value")
        if verdict == "accept_check" and not decision.get("check_labeler"):
            raise ValueError("an accept_check decision needs the check labeler")
        original = {k: record.get(k) for k in ("value", "evidence", "presence", "absent_reason", "labeler")}
        out["status"] = "near_gold"
        out["value"] = decision["value"]
        if decision.get("evidence") is not None:
            out["evidence"] = decision["evidence"]
        if decision.get("presence"):
            out["presence"] = decision["presence"]
        out["absent_reason"] = decision.get("absent_reason")
        out["value_source"] = ({"kind": "review_correction", "labeler": dict(decision["reviewer"])}
                               if verdict == "correct"
                               else {"kind": "check_pass", "labeler": dict(decision["check_labeler"])})
    else:
        raise ValueError(f"unknown verdict {verdict!r}")
    out["use_as_truth"] = out["status"] in TRUTH_STATUSES
    out["review"] = {k: v for k, v in decision.items()
                     if k not in ("value", "evidence", "absent_reason", "check_labeler")}
    if verdict in ("correct", "accept_check"):
        out["review"]["original"] = original
    return out


def gold_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "labels" / "gold"


def supplementary_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "labels" / "gold-supplementary"


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii: U+2028, U+2029 and U+0085 must not split a line in a splitlines() reader.
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in records]
    text = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(text, encoding="utf-8")
    return _sha(text)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    # Split on "\n" only: str.splitlines() also breaks on U+2028, U+2029 and U+0085 (older
    # files may hold them unescaped; write_jsonl now escapes every non-ASCII character).
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


_SUPPLEMENTARY_KINDS = ("gate_reject", "review_rejected", "notes")


def _verify_supplementary_row(rec: Mapping[str, Any], where: str) -> list[str]:
    problems = []
    if rec.get("kind") not in _SUPPLEMENTARY_KINDS:
        problems.append(f"{where}: unknown supplementary kind {rec.get('kind')!r}")
    if rec.get("use_as_truth"):
        problems.append(f"{where}: supplementary row claims use_as_truth")
    return problems


def _verify_gold_row(rec: Mapping[str, Any], where: str, seen_ids: dict[str, str]) -> list[str]:
    problems = []
    label_id = rec.get("label_id")
    if label_id is not None:
        if label_id in seen_ids:
            problems.append(f"{where}: duplicate label_id {label_id} (also {seen_ids[label_id]})")
        else:
            seen_ids[label_id] = where
    if rec.get("status") not in STATUSES:
        problems.append(f"{where}: unknown status {rec.get('status')!r}")
    if rec.get("use_as_truth") != (rec.get("status") in TRUTH_STATUSES):
        problems.append(f"{where}: use_as_truth does not follow status")
    if rec.get("presence") == "populated" and not rec.get("evidence") and not rec.get("absent_reason"):
        problems.append(f"{where}: populated without evidence")
    if rec.get("status") == "near_gold":
        why = _near_gold_problem(rec)
        if why:
            problems.append(f"{where}: near_gold {why}")
        if _money_text_field(str(rec.get("doc_class")), str(rec.get("field"))) and not money_text_parses(rec.get("value")):
            problems.append(f"{where}: near_gold currency phrase {rec.get('value')!r} is not a figure the Dojo "
                            "parses; write it as a plain dollar figure (\"$5,000,000\") with a correct review")
    return problems


@functools.lru_cache(maxsize=None)
def _money_text_field(doc_class: str, field: str) -> bool:
    """Whether ``field`` is money kept as a currency phrase (contract ``contract_value``)."""
    try:
        types, _, _, _, model = _schema_bits(doc_class)
    except KeyError:
        return False
    return str(types.get(field)) == "money" and _text_field(model, field)


def _verify_manifest_file(directory: Path, name: str, sha: str, supplementary: bool,
                          seen_ids: dict[str, str]) -> list[str]:
    path = directory / name
    if not path.is_file():
        return [f"{name}: listed but missing"]
    problems = []
    if _sha(path.read_text(encoding="utf-8")) != sha:
        problems.append(f"{name}: sha256 does not match MANIFEST")
    for rec in read_jsonl(path):
        where = f"{rec.get('doc_id')}.{rec.get('field')}"
        if supplementary:
            problems += _verify_supplementary_row(rec, where)
        else:
            problems += _verify_gold_row(rec, where, seen_ids)
    return problems


def verify_catalog(directory: Path) -> list[str]:
    """Integrity problems in a catalog directory (empty list = consistent).

    Works for the gold catalog (``mailroom-gold-labels/v1``) and for the supplementary store
    (``mailroom-gold-supplementary/v1``); the manifest says which one it is.
    """
    problems = []
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.is_file():
        return [f"{manifest_path}: missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("schema")
    supplementary = schema == SUPPLEMENTARY_SCHEMA
    if schema not in (SCHEMA, SUPPLEMENTARY_SCHEMA):
        problems.append(f"schema is {schema!r}, expected {SCHEMA!r} or {SUPPLEMENTARY_SCHEMA!r}")
    listed = manifest.get("files", {})
    on_disk = {p.name for p in directory.glob("*.jsonl")}
    for name in sorted(on_disk - set(listed)):
        problems.append(f"{name}: not in MANIFEST")
    seen_ids: dict[str, str] = {}
    for name, sha in listed.items():
        problems += _verify_manifest_file(directory, name, sha, supplementary, seen_ids)
    return problems


def _near_gold_problem(rec: Mapping[str, Any]) -> str | None:
    """Why a ``near_gold`` record is not what the tier promises (None = it is).

    Either two independent passes agreed (``check.agrees`` and ``check.gate_ok``), or a reviewer
    with a model and a role settled it with accept, correct or accept_check."""
    check = rec.get("check")
    if isinstance(check, Mapping) and check.get("agrees") is True and check.get("gate_ok") is True:
        return None
    review = rec.get("review")
    if not isinstance(review, Mapping):
        return "has neither an agreeing check pass nor a review"
    problem = reviewer_problem(review.get("reviewer"))
    if problem:
        return f"review: {problem}"
    verdict = review.get("verdict")
    if verdict not in ("accept", "correct", "accept_check"):
        return f"review verdict {verdict!r} does not settle a label as near_gold"
    if verdict in ("correct", "accept_check"):
        source = rec.get("value_source")
        kind = {"correct": "review_correction", "accept_check": "check_pass"}[verdict]
        if not isinstance(source, Mapping) or source.get("kind") != kind or not source.get("labeler"):
            return f"{verdict} review without value_source {kind!r}"
    return None


def overlay_records(records: Iterable[Mapping[str, Any]], *, gate_run: str) -> list[dict[str, Any]]:
    """Catalog records as EDA overlay records (``mailroom-interim-labels/v1``), one per document.

    Only ``near_gold`` labels are exported, as ``gap_fill`` (the Hub leaves these fields
    unlabelled): EDA's loader keeps every record whose status is ``gap_fill`` and drops
    ``basis``, so a single-pass ``candidate`` exported here would be indistinguishable there.
    ``candidate``, ``disputed`` and ``rejected`` stay in this catalog. EDA shows the labels
    beside its models' answers and a reviewer may pick one with their initials;
    ``use_as_truth`` is always false. ``basis`` says how the label was settled, for humans.
    """
    docs: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.get("status") != "near_gold":
            continue
        review = rec.get("review") or {}
        if review:
            basis = f"near_gold:opus_reviewed_{review.get('verdict')}"
        else:
            basis = "near_gold:two_pass_agree"
        out = docs.setdefault(rec["doc_id"], {
            "doc_class": rec["doc_class"], "doc_id": rec["doc_id"],
            "doc_sha256": (rec.get("content_sha256") or rec.get("doc_sha") or "")[:16],
            "doc_subclass": rec.get("subclass"), "labels": {},
            # The first label's labeler and near_empty, for EDA's per-document reader; each
            # label below carries its own.
            "source": {"gate_run": gate_run, "catalog": SCHEMA, "labeler": rec.get("labeler"),
                       "near_empty": bool(rec.get("near_empty"))}})
        out["labels"][rec["field"]] = {
            "value": rec.get("value"), "status": "gap_fill", "basis": basis, "hub_value": None,
            "use_as_truth": False, "presence": rec.get("presence"), "evidence": rec.get("evidence"),
            "absent_reason": rec.get("absent_reason"), "label_id": rec.get("label_id"),
            "labeler": rec.get("labeler"), "near_empty": bool(rec.get("near_empty")),
            "value_source": rec.get("value_source")}
    return [docs[k] for k in sorted(docs)]


def manifest_sha(directory: Path) -> str:
    return hashlib.sha256((directory / "MANIFEST.json").read_bytes()).hexdigest()


# --------------------------------------------------------------------------- CUAD-derived dates

#: Contract date fields whose truth a human CUAD annotator already marked as a span.
CUAD_DATE_FIELDS = {"agreement_date": "Agreement Date", "expiration_date": "Expiration Date"}

_MONTHS = {m.casefold(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_DATE_PATTERNS = (
    re.compile(_MON + r"\s+" + _ORD + r",?\s+(\d{4})", re.I),                    # June 21, 1999
    re.compile(_ORD + r"\s+(?:day\s+of\s+)?" + _MON + r",?\s+(\d{4})", re.I),   # 21st day of June, 1999
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),                                # 6/21/1999
)


def parse_dates(text: str) -> set[str]:
    """Every full calendar date written in ``text``, as ISO strings."""
    found = set()
    for i, pat in enumerate(_DATE_PATTERNS):
        for m in pat.finditer(text):
            try:
                if i == 0:
                    mon, day, year = _MONTHS[m.group(1).casefold().rstrip(".")], int(m.group(2)), int(m.group(3))
                elif i == 1:
                    day, mon, year = int(m.group(1)), _MONTHS[m.group(2).casefold().rstrip(".")], int(m.group(3))
                else:
                    mon, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                found.add(date(year, mon, day).isoformat())
            except (KeyError, ValueError):
                continue
    return found


def cuad_date_submission(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """A submission for the CUAD-annotated contract dates of one ground-truth row.

    A field is filled only when its CUAD span states exactly one full calendar date
    (an expiration written as a term, "five years after…", is left to the labelers).
    Its labeler role is ``derived``: it is a human-annotation reference to compare label
    passes against, not a ``build --label`` submission (build accepts only ``label`` passes).
    """
    if row.get("expected") != "contract":
        return None
    gt = _parse_json(row.get("gt_fields")) or {}
    labels = _parse_json(gt.get("cuad_clause_labels")) or {}
    if not isinstance(labels, Mapping):
        return None
    fields = {}
    for name, category in CUAD_DATE_FIELDS.items():
        spans = labels.get(category) or []
        texts = [s.get("text", "") for s in spans if isinstance(s, Mapping) and s.get("text")]
        dates = set().union(*(parse_dates(t) for t in texts)) if texts else set()
        if len(dates) == 1:
            fields[name] = {"value": next(iter(dates)), "evidence": texts}
    if not fields:
        return None
    return {"doc_id": row["document_id"],
            "labeler": {"model": "deterministic", "role": "derived",
                        "basis": "cuad_clause_labels span (human CUAD annotation)"},
            "fields": fields}


# --------------------------------------------------------------------------- near-gold scoring overlay

def gold_overlay_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "labels" / "gold-overlay"


def near_gold_snapshot(root: Path | None = None) -> tuple[dict[str, dict[str, Any]], str, list[str]]:
    """``(records by doc_id, fingerprint, problems)`` of the near-gold overlay, from one read.

    The manifest and every file it lists are read once into memory; the fingerprint, the
    integrity checks and the records all come from those same bytes, so an export that lands
    while this runs can never pair records with another snapshot's fingerprint.
    """
    root = root or gold_overlay_dir()
    path = root / "MANIFEST.json"
    if not path.exists():
        return {}, "", [f"{path}: missing (build it with scripts/gold_labels.py overlay)"]
    man_bytes = path.read_bytes()
    fingerprint = hashlib.sha256(man_bytes).hexdigest()
    man = json.loads(man_bytes.decode("utf-8"))
    if man.get("schema") != OVERLAY_SCHEMA:
        return {}, fingerprint, [f"MANIFEST.json schema {man.get('schema')!r} is not {OVERLAY_SCHEMA!r}"]
    listed = man.get("files") or {}
    problems: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    for name in sorted(listed):
        f = root / name
        data = f.read_bytes() if f.is_file() else None
        if data is None:
            problems.append(f"{name}: listed in the manifest but missing")
            continue
        if hashlib.sha256(data).hexdigest() != listed[name]:
            problems.append(f"{name}: sha256 differs from the manifest (rebuild with scripts/gold_labels.py overlay)")
            continue
        for line in data.decode("utf-8").split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            for fld, lab in (rec.get("labels") or {}).items():
                if not str(lab.get("basis") or "").startswith("near_gold:") or lab.get("use_as_truth"):
                    problems.append(f"{rec.get('doc_id')}.{fld}: not a near_gold label")
            records[rec["doc_id"]] = rec
    problems += [f"{p.name}: not in the manifest" for p in sorted(root.glob("*.jsonl")) if p.name not in listed]
    return records, fingerprint, problems


def verify_overlay(root: Path | None = None) -> list[str]:
    """Integrity problems of the exported near-gold overlay (empty list: consistent)."""
    return near_gold_snapshot(root)[2]


def load_near_gold(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """``{doc_id: overlay record}`` over every file the near-gold overlay manifest lists."""
    return near_gold_snapshot(root)[0]


def near_gold_fingerprint(root: Path | None = None) -> str:
    """sha256 of the near-gold overlay's MANIFEST.json (which pins every file): what a lock records."""
    path = (root or gold_overlay_dir()) / "MANIFEST.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


#: Interim gap-fill bases near-gold never supersedes: the owner adopted the original email header over
#: the text-only near-gold labels (data/labels/review/VALIDATION.md, issue 6).
INTERIM_BASES_OVER_NEAR_GOLD = frozenset({"original_header"})
_INTERIM_CACHE: dict[str, Any] = {}


def _interim_key() -> tuple:
    """The interim overlay files' state (name, mtime, size): the cache key of ``_INTERIM_CACHE``."""
    from mailroom_sandbox import interim_labels as il

    root = il.overlay_dir()
    return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size)
                        for p in root.glob("*") if p.is_file())) if root.is_dir() else ()


def _interim_labels_of(doc_id: str, overlay_sha: str | None = None) -> Mapping[str, Any] | None:
    """The current interim overlay's labels for ``doc_id``; None when the overlay is not the one
    (``overlay_sha``) the row was prepared with, so precedence never reads a newer overlay."""
    from mailroom_sandbox import interim_labels as il

    key = _interim_key()
    if _INTERIM_CACHE.get("key") != key or "overlay" not in _INTERIM_CACHE:
        _INTERIM_CACHE["overlay"] = il.load_overlay()
        _INTERIM_CACHE["key"] = key
        _INTERIM_CACHE.pop("sha", None)
    if overlay_sha is not None:
        if "sha" not in _INTERIM_CACHE:
            _INTERIM_CACHE["sha"] = il.overlay_fingerprint()
        if _INTERIM_CACHE["sha"] != overlay_sha:
            return None
    return ((_INTERIM_CACHE["overlay"].get(doc_id) or {}).get("labels")) or {}


def supersede_interim_gap_fills(row: Mapping[str, Any], rec: Mapping[str, Any],
                                interim: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """SHF-010: the interim gap fills on ``row`` that ``rec``'s near-gold labels supersede.

    The owner's decision (``data/labels/review/INTERIM_AUDIT.md`` step 2): reviewed gold supersedes
    an interim gap fill it conflicts with. An ``original_header`` fill is kept (the owner adopted the
    header over near-gold), as are interim corrections of a Hub value and derived labels. Returns
    ``{field: {"interim": value, "interim_presence": code, "near_gold": value}}``.
    """
    from mailroom_sandbox import interim_labels as il

    mark = row.get("interim_labels") or {}
    applied = set(mark.get("fields") or [])
    if not applied:
        return {}
    # ``interim`` is the overlay snapshot the row was prepared from. Without it, the current
    # overlay is read only when it is that snapshot (its fingerprint matches the row's); after an
    # overlay edit nothing is superseded, so the prepared interim value stands.
    labels = interim if interim is not None else _interim_labels_of(
        str(row.get("id")), str(mark.get("overlay_sha256") or ""))
    if labels is None:
        return {}
    exp = il._expected(row)
    pres = il._presence(exp)
    out: dict[str, dict[str, Any]] = {}
    for fld, lab in (rec.get("labels") or {}).items():
        ilab = labels.get(fld) or {}
        if (fld not in applied or ilab.get("status") != "gap_fill"
                or str(ilab.get("basis") or "") in INTERIM_BASES_OVER_NEAR_GOLD
                or not str(lab.get("basis") or "").startswith("near_gold:")):
            continue
        new, old = lab.get("value"), exp.get(fld)
        if json.dumps(new, sort_keys=True, default=str) == json.dumps(old, sort_keys=True, default=str):
            continue
        out[fld] = {"interim": old, "interim_presence": pres.get(fld), "near_gold": new}
    return out


def apply_near_gold(row: Mapping[str, Any], overlay: Mapping[str, Mapping[str, Any]], *,
                    overlay_sha: str, interim: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The row with near-gold labels filling fields that nothing else labels.

    Precedence is Hub GT, then the interim overlay's truth labels (applied before this), then
    near-gold: a field the row already labels (a value, or a presence code such as
    ``schema_documented_absence``; :func:`hub_labels`) is left alone, with one exception: while
    SHF-010 is current, a near-gold label replaces a conflicting interim gate gap fill (not an
    ``original_header`` fill) and the replaced value is kept under ``truth_overrides``
    (``docs/scoring-hotfixes.md``). A document whose text no longer matches the label's
    ``doc_sha256`` is untouched. ``near_gold_labels`` on the returned row names every field that
    came from here, so a score that used them is never read as a Hub-GT score.
    """
    from mailroom_sandbox import interim_labels as il

    out = dict(row)
    rec = overlay.get(str(row.get("id")))
    if not rec or rec.get("doc_sha256") != il.doc_sha(row.get("doc_text")):
        return out
    exp = il._expected(row)
    pres = il._presence(exp)
    from mailroom_sandbox import scoring_hotfixes as sh

    # SHF-010 (docs/scoring-hotfixes.md): reviewed near-gold supersedes a conflicting interim gap fill.
    # ``interim`` is the interim overlay the row was prepared with (doc id -> record).
    snap = None if interim is None else ((interim.get(str(row.get("id"))) or {}).get("labels") or {})
    overrides = supersede_interim_gap_fills(row, rec, snap) if sh.enabled("SHF-010") else {}
    applied = []
    for fld, lab in sorted((rec.get("labels") or {}).items()):
        if not str(lab.get("basis") or "").startswith("near_gold:"):
            continue
        if hub_labels(fld, exp) and fld not in overrides:  # Hub GT, or an interim label merged before this
            continue
        value = lab.get("value")
        exp[fld] = value
        pres[fld] = "schema_documented_absence" if value in (None, [], "") else "populated"
        applied.append(fld)
    if not applied:
        return out
    exp["gt_presence"] = json.dumps(pres, sort_keys=True)
    out["expected_fields"] = (json.dumps(exp, ensure_ascii=False, sort_keys=True)
                              if isinstance(row.get("expected_fields"), str) else exp)
    out["near_gold_labels"] = {"fields": applied, "overlay_sha256": overlay_sha, "status": "near_gold"}
    if overrides:
        # The replaced interim truth stays on the row: the scorer reports it as the raw side.
        out["truth_overrides"] = {"SHF-010": overrides}
    return out
