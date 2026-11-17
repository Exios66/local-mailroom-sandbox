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
   with digit boundaries, or the month name with the day beside it and the year; money: the
   exact figure appears in the evidence; party roles: the role word appears too; name tokens;
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
label it corrects under ``review.original``). No status here
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
    return {
        f"{d:%Y-%m-%d}", f"{d.month}/{day}/{d.year}", f"{d:%m/%d/%Y}", f"{d.month}/{day}/{d:%y}",
        f"{d:%m/%d/%y}", f"{m} {day}, {d.year}", f"{m} {day} {d.year}", f"{day} {m} {d.year}",
        f"{day} {m}, {d.year}", f"{s} {day}, {d.year}", f"{s}. {day}, {d.year}", f"{s} {day} {d.year}",
        f"{m} {day}{suf}, {d.year}", f"{day}{suf} day of {m}, {d.year}", f"{day}{suf} day of {m} {d.year}",
        f"{day}{suf} of {m}, {d.year}", f"{day}-{s}-{d.year}", f"{day}-{s}-{d:%y}", f"{d:%d}-{s}-{d:%y}",
        f"{d.year}.{d:%m}.{d:%d}", f"{d.year}/{d:%m}/{d:%d}",
    } | ({f"{d:%d}/{d:%m}/{d.year}", f"{day}/{d.month}/{d.year}"} if day > 12 else set())


def _bounded(form: str, text: str) -> bool:
    """Whether ``form`` occurs in ``text`` with no digit (or, for slash forms, slash) beside it."""
    extra = "/" if "/" in form else ""
    pattern = rf"(?<![0-9{extra}]){re.escape(form)}(?![0-9{extra}])"
    return re.search(pattern, text) is not None


def _spelled_date_supported(d: date, ev: str) -> bool:
    """The month name with the day beside it ("May 14", "May 14th", "14 May", "14th day of May")
    and the year somewhere in the quote. Never a bare day token far from the month."""
    if not re.search(rf"(?<![0-9]){d.year}(?![0-9])", ev):
        return False
    names = {d.strftime("%B").casefold(), d.strftime("%b").casefold()}
    if d.month == 9:
        names.add("sept")
    mon = r"(?:" + "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True)) + r")\.?"
    day = rf"0?{d.day}(?:st|nd|rd|th)?(?![0-9]|:[0-9])"
    return bool(re.search(rf"(?<![a-z]){mon}\s*,?\s*{day}", ev)
                or re.search(rf"(?<![0-9]){day}\s+(?:day\s+)?(?:of\s+)?{mon}(?![a-z])", ev))


def _date_supported(value: str, evidence: str) -> bool:
    ev = _WS.sub(" ", evidence.casefold())
    if any(_bounded(f.casefold(), ev) for f in _date_forms(value)):
        return True
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return False
    return _spelled_date_supported(d, ev)


_FIGURE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?!\d)(\s*(?:million|billion|thousand)\b)?"
                     r"(?!\s*%)", re.I)
_SCALE = {"thousand": Decimal(10) ** 3, "million": Decimal(10) ** 6, "billion": Decimal(10) ** 9}
_NOT_PLAIN_NUMBER = re.compile(r"\d_\d|\d[eE][+-]?\d")


def _figures(text: str) -> set[Decimal]:
    """Every numeric figure written in ``text`` ($, thousands commas, decimals, "2.5 million"),
    exactly. A figure followed by a scale word counts only as its scaled amount."""
    out = set()
    for m in _FIGURE.finditer(text):
        try:
            num = Decimal(m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else ""))
        except InvalidOperation:  # pragma: no cover - the pattern only admits digits
            continue
        scale = (m.group(3) or "").strip().casefold()
        out.add(num * _SCALE[scale] if scale else num)
    return out


def _money_supported(value: float, evidence: str) -> bool:
    """A finite amount equals, exactly, a figure written in the evidence."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return Decimal(repr(float(value))) in _figures(evidence)


def _money_text_supported(value: str, evidence: str) -> bool:
    """A currency phrase kept as text: it appears in the evidence as written (whitespace
    normalised, not inside a longer figure) and holds a finite figure the evidence also states."""
    phrase = _WS.sub(" ", value).strip()
    if not phrase or _NOT_PLAIN_NUMBER.search(phrase):
        return False
    ev = _WS.sub(" ", evidence)
    if not re.search(rf"(?<![\d,.]){re.escape(phrase.casefold())}(?![\d]|[,.]\d)", ev.casefold()):
        return False
    return bool(_figures(phrase) & _figures(ev))


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


def _check_field(name: str, entry: Mapping[str, Any], doc_text: str, ftype: str,
                 vocab: tuple[str, ...] | None, empty_value: Any, *, money_as_text: bool = False) -> FieldResult:
    res = FieldResult(field=name, ok=False, evidence=[], checks={})
    if not isinstance(entry, Mapping):
        res.reason = "entry is not an object"
        return res
    raw_value = entry.get("value")
    value = _normalize(raw_value, ftype)
    res.value = value
    quotes = entry.get("evidence") or []
    if isinstance(quotes, str):
        quotes = [quotes]
    if not isinstance(quotes, list):
        res.reason = "evidence is not a list of quotes"
        return res

    if vocab is not None and not _is_empty(value):
        res.checks["in_vocabulary"] = value in vocab
        if not res.checks["in_vocabulary"]:
            res.reason = f"out_of_vocabulary: {value!r}"
            return res

    if _is_empty(value):
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

    if not quotes:
        # A label at its contract default (urgency: routine) may rest on the absence of any
        # time pressure; it still needs a stated basis.
        if vocab is not None and value == empty_value and (entry.get("absent") or entry.get("basis")):
            res.presence = "populated"
            res.absent_reason = entry.get("absent") or entry.get("basis")
            res.ok = True
            return res
        res.reason = "no evidence quote"
        return res

    spans = []
    for q in quotes:
        if len(_WS.sub(" ", str(q)).strip()) > MAX_QUOTE_CHARS:
            res.reason = f"evidence quote too long (over {MAX_QUOTE_CHARS} characters)"
            res.checks["evidence_verbatim"] = False
            return res
        span = locate(str(q), doc_text)
        if span is None:
            res.reason = f"evidence not found verbatim: {str(q)[:80]!r}"
            res.checks["evidence_verbatim"] = False
            return res
        spans.append(span)
    res.checks["evidence_verbatim"] = True
    res.evidence = spans
    ev_text = " ".join(s["text"] for s in spans)

    if ftype == "date":
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            res.reason = f"date not ISO YYYY-MM-DD: {value!r}"
            return res
        try:
            date.fromisoformat(value)
        except ValueError:
            res.reason = f"invalid date: {value!r}"
            return res
        supported = _date_supported(value, ev_text)
    elif ftype == "money" and money_as_text:
        # The pipeline field is a currency phrase (contract_value: str), kept as written.
        supported = _money_text_supported(str(raw_value), ev_text)
    elif ftype == "money":
        if not isinstance(value, float) or not math.isfinite(value):
            res.reason = f"money not a finite number: {value!r}"
            return res
        supported = _money_supported(value, ev_text)
    elif ftype == "label":
        # Vocabulary already checked. A label other than its contract default must rest on a
        # real sentence fragment, not on a single keyword.
        supported = value == empty_value or any(len(_tokens(sp["text"])) >= MIN_LABEL_QUOTE_TOKENS for sp in spans)
        if not supported:
            res.checks["value_supported"] = False
            res.reason = f"closed label needs an evidence quote of at least {MIN_LABEL_QUOTE_TOKENS} tokens"
            return res
    elif ftype.startswith("entity_list"):
        if not isinstance(value, list):
            res.reason = "list field needs a list"
            return res
        need = 0.6 if "free_text" in ftype or ftype == "entity_list" else 0.8
        supported = all(_token_coverage(v, ev_text) >= need for v in value)
    elif ftype == "free_text":
        supported = _token_coverage(str(value), ev_text) >= 0.6
    else:  # name, id
        supported = _token_coverage(str(value), ev_text) >= 0.8
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


def validate_submission(sub: Mapping[str, Any], doc_text: str, doc_class: str) -> SubmissionResult:
    """Run the gate on one submission (see the module docstring for the order)."""
    types, vocab, empty_payload, empty_value, model = _schema_bits(doc_class)
    result = SubmissionResult(doc_id=str(sub.get("doc_id")), doc_class=doc_class)
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
    pairs = sorted(((_token_f1(x, y), i, j) for i, x in enumerate(a) for j, y in enumerate(b)), reverse=True)
    used_a, used_b = set(), set()
    for score, i, j in pairs:
        if i in used_a or j in used_b or score < threshold:
            continue
        used_a.add(i)
        used_b.add(j)
    return len(used_a) == len(a)


def values_agree(a: Any, b: Any, ftype: str) -> bool:
    """Whether two labels for one field say the same thing (type-aware, order-free lists)."""
    if _is_empty(a) or _is_empty(b):
        return _is_empty(a) and _is_empty(b)
    if ftype.startswith("entity_list"):
        ca, cb = _canon(a), _canon(b)
        if ca == cb:
            return True
        if ftype in ("entity_list", "entity_list:free_text"):
            return _lists_match(ca, cb)
        # same set of people/parties when one side adds a title or middle initial
        if len(ca) != len(cb):
            return False
        return all(set(x.split()) <= set(y.split()) or set(y.split()) <= set(x.split())
                   for x, y in zip(ca, cb))
    if ftype in ("name", "free_text"):
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
    types = _schema_bits(doc["doc_class"])[0]
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


def apply_review(record: dict[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """Settle a disputed (or candidate) record with a reviewer's decision.

    ``decision``: ``{"verdict": "accept"|"reject"|"correct", "reviewer": {...} (required),
    "value"?: corrected, "evidence"?: [spans], "note"?: str}``. A correction must already have
    passed :func:`validate_submission` (the caller re-validates it). A correction keeps the
    label it replaced under ``review.original``.
    """
    if not decision.get("reviewer"):
        raise ValueError("a review decision needs a reviewer")
    out = dict(record)
    verdict = decision["verdict"]
    if verdict == "accept":
        out["status"] = "near_gold"
    elif verdict == "reject":
        out["status"] = "rejected"
    elif verdict == "correct":
        original = {k: record.get(k) for k in ("value", "evidence", "presence", "absent_reason", "labeler")}
        out["status"] = "near_gold"
        out["value"] = decision["value"]
        if decision.get("evidence") is not None:
            out["evidence"] = decision["evidence"]
        if decision.get("presence"):
            out["presence"] = decision["presence"]
        out["absent_reason"] = decision.get("absent_reason")
    else:
        raise ValueError(f"unknown verdict {verdict!r}")
    out["use_as_truth"] = out["status"] in TRUTH_STATUSES
    out["review"] = {k: v for k, v in decision.items() if k not in ("value", "evidence", "absent_reason")}
    if verdict == "correct":
        out["review"]["original"] = original
    return out


def gold_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "labels" / "gold"


def supplementary_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "data" / "labels" / "gold-supplementary"


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records]
    text = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(text, encoding="utf-8")
    return _sha(text)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    # Split on "\n" only: str.splitlines() also breaks on U+2028, U+2029 and U+0085, which
    # write_jsonl (ensure_ascii=False) leaves unescaped inside a record.
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


_SUPPLEMENTARY_KINDS = ("gate_reject", "review_rejected", "notes")


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
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: listed but missing")
            continue
        if _sha(path.read_text(encoding="utf-8")) != sha:
            problems.append(f"{name}: sha256 does not match MANIFEST")
        for rec in read_jsonl(path):
            where = f"{rec.get('doc_id')}.{rec.get('field')}"
            if supplementary:
                if rec.get("kind") not in _SUPPLEMENTARY_KINDS:
                    problems.append(f"{where}: unknown supplementary kind {rec.get('kind')!r}")
                if rec.get("use_as_truth"):
                    problems.append(f"{where}: supplementary row claims use_as_truth")
                continue
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
    return problems


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
            "source": {"gate_run": gate_run, "catalog": SCHEMA, "labeler": rec.get("labeler"),
                       "near_empty": bool(rec.get("near_empty"))}})
        out["labels"][rec["field"]] = {
            "value": rec.get("value"), "status": "gap_fill", "basis": basis, "hub_value": None,
            "use_as_truth": False, "presence": rec.get("presence"), "evidence": rec.get("evidence"),
            "absent_reason": rec.get("absent_reason"), "label_id": rec.get("label_id")}
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
