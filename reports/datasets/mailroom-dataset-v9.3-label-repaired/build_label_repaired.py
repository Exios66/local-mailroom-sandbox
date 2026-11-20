"""Build the label-repaired CSV release of mailroom-dataset v9.3 by weighted consensus vote.

Every (document, field) label is put to a vote among every source that speaks to it:

* the Hub v9.3 ground truth (``ground_truth`` config, revision ff4ca546),
* the interim overlay (``data/labels/interim/``: reviewed corrections, original-header fills,
  gate-supported gap fills, subclass-derived labels, disputed gate values),
* the gold catalog and its exported near-gold overlay (``data/labels/gold*/``),
* the reviewed subclass corrections (``data/labels/review/subclass_corrections.jsonl``),
* labels generated here: conversions of the Hub's own CUAD / MAUD / subclass labels through the
  vendored Dojo rules (``generated_derived``), and rule extractions that quote verbatim document
  text (``generated_rule``).

Each source casts one vote with a weight set by how much review stands behind it. Values are
compared field-aware (token-normalised, order-free lists, ISO dates, "State of X" == "X", party
defined terms stripped), every empty value is one "documented absence" candidate, and the value
with the most weight wins; a weight tie goes to the better-reviewed source. The owner's own
decisions (``human_reviews.jsonl``) are final and are not put to a vote. A vote whose winner holds
under half of the weight while three or more values compete is marked ``needs_human``.

Run (network-free once ``sandbox datasets pull`` has cached v9.3)::

    PYTHONPATH=vendor/llm-dojo-scoring/src .venv/bin/python -I \
        reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py [--with-text]

Writes, next to this file: the wide CSV (one row per document), the long provenance CSV (one
row per document and field, with every vote), the per-field completeness CSV and a JSON summary.
"""

from __future__ import annotations

import csv
import datetime as dt
import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "vendor" / "llm-dojo-scoring" / "src")]

from llm_dojo_scoring.schemas import extraction_schemas as es  # noqa: E402
from llm_dojo_scoring.schemas.maud_schema import hub_merger_expected_fields  # noqa: E402

REVISION = "ff4ca546d4346991628c2616ae014afc15e9fe04"
CACHE = ROOT / "data" / "cache" / f"Lucius-Morningstar__mailroom-dataset__{REVISION[:12]}" / "ground_truth_all.jsonl"
LABELS = ROOT / "data" / "labels"
STEM = "mailroom_dataset_v9.3_label_repaired"

# --------------------------------------------------------------------------- voters

#: source -> (weight, tie-break rank: lower wins). Weight reflects the review behind a label.
SOURCES: dict[str, tuple[float, int]] = {
    "owner_review": (99.0, 0),             # human_reviews.jsonl: final, never outvoted
    "interim_reviewed": (3.0, 1),          # review_read_message / original_header / review_read_record
    "subclass_review": (3.0, 1),           # reviewed subclass corrections (SHF-013)
    "interim_correction": (3.0, 2),        # Hub defect fixed against the Hub's own CUAD evidence
    "near_gold_reviewed": (3.0, 3),        # gold label accepted or corrected by a reviewing model
    "near_gold_two_pass": (2.0, 4),        # two independent labeling passes agreed
    "hub_v9.3": (2.0, 5),                  # published ground truth
    "interim_derived": (2.0, 6),           # computed from the Hub subclass, no model
    "generated_derived": (2.0, 7),         # this build: Hub CUAD / MAUD / subclass through Dojo rules
    "interim_gate": (1.5, 8),              # gate-accepted extraction, every token in the text
    "cuad_span": (1.5, 8),                 # this build: a CUAD annotator's clause span mapped to a pending field
    "gold_candidate": (1.0, 9),            # gold labeler output that passed checks, not yet reviewed
    "generated_rule": (1.0, 10),           # this build: regex extraction quoting verbatim text
    "gold_disputed": (0.5, 11),            # gold label a check disputed
    "interim_disputed": (0.5, 11),         # gate value that disagreed with the Hub
}

#: Schema fields left out of the release entirely (no column, no target cell).
DROPPED_FIELDS = frozenset({"claim_checklist"})

EMPTY = "<documented_absence>"
NOT_LABELED = "unlabeled"

# --------------------------------------------------------------------------- normalisation

_TOKEN = re.compile(r"[a-z0-9]+")
_ANNOT = re.compile(r"\([^()]*[\"“”][^()]*\)|\"[^\"]*\"|“[^”]*”")
_PLACE_PREFIX = re.compile(r"^(?:the\s+)?(?:laws\s+of\s+)?(?:the\s+)?(?:state|commonwealth|province|republic)\s+of\s+",
                           re.I)
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    if isinstance(v, (list, dict, tuple, set)):
        return not v
    return str(v).strip().lower() in {"", "nan", "none", "null", "n/a", "[]", "{}"}


def parse_jsonish(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def to_iso(text: str) -> str | None:
    """ISO date (or ``YYYY-MM`` for a month and year) of a date phrase; None when it holds no date."""
    s = re.sub(r"(\d)\s*(s\s*t|n\s*d|r\s*d|t\s*h)\b", lambda m: m.group(1) + m.group(2).replace(" ", ""),
               str(text).strip())
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", s)
    if iso:
        try:
            return dt.date.fromisoformat(iso.group()).isoformat()
        except ValueError:
            return None
    ymd = None
    m = re.search(r"\b([A-Za-z]{3,9})\.?\s*(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b", s)
    if m and m.group(1).lower() in MONTHS:
        ymd = (int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    if ymd is None:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", s)
        if m and m.group(2).lower() in MONTHS:
            ymd = (int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    if ymd is None:
        m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            ymd = (int(m.group(3)), b, a) if a > 12 else (int(m.group(3)), a, b)
    if ymd is None:
        m = re.search(r"\b([A-Za-z]{3,9})\.?\s*,?\s+(\d{4})\b", s)
        if m and m.group(1).lower() in MONTHS:
            return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
        return None
    try:
        return dt.date(*ymd).isoformat()
    except ValueError:
        return None


DATE_FIELDS = {"agreement_date", "effective_date", "expiration_date", "communication_date", "date_of_loss",
               "date_filed", "outside_date"}
PLACE_FIELDS = {"jurisdiction", "governing_law"}
PARTY_FIELDS = {"parties", "signatories", "merger_sub", "financial_advisors", "legal_counsel", "acquirer", "target",
                "entity_name", "sender", "recipient", "additional_recipients", "insured_party", "insurer"}


def _toks(s: str) -> str:
    return " ".join(_TOKEN.findall(s.lower()))


def canon(field: str, v: Any) -> str:
    """Field-aware comparison key; every empty value is the documented-absence key."""
    v = parse_jsonish(v)
    if is_empty(v):
        return EMPTY
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True)

    def one(x: Any) -> str:
        s = str(x)
        if field in DATE_FIELDS:
            return to_iso(s) or _toks(s)
        if field in PLACE_FIELDS:
            return _toks(_PLACE_PREFIX.sub("", s.strip()))
        if field in PARTY_FIELDS:
            return _toks(_ANNOT.sub(" ", s)) or _toks(s)
        if field == "contract_value" or field.endswith("_fee") or field.endswith("_amount"):
            amount = re.fullmatch(r"\s*([A-Za-z]{3}|[$€£])?\s*(-?\d[\d,]*(?:\.\d+)?)\s*([A-Za-z]{3})?\s*", s)
            if amount:
                currency = (amount[1] or amount[3] or "").upper()
                currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(currency, currency)
                try:
                    number = format(Decimal(amount[2].replace(",", "")).normalize(), "f")
                    return f"{currency}:{number}"
                except InvalidOperation:
                    pass
            return _toks(s)
        return _toks(s)

    if isinstance(v, list):
        return json.dumps(sorted({one(x) for x in v if not is_empty(x)}))
    return one(v)


# --------------------------------------------------------------------------- inputs

class InputSnapshot:
    """Hash the exact bytes parsed, including each consumed Parquet shard."""

    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}

    def read(self, path: Path, *, label: str | None = None) -> bytes:
        data = path.read_bytes()
        key = label or str(path.relative_to(ROOT))
        digest = hashlib.sha256(data).hexdigest()
        if key in self.hashes and self.hashes[key] != digest:
            raise ValueError(f"input changed during build: {key}")
        self.hashes[key] = digest
        return data

    def jsonl(self, path: Path) -> list[dict[str, Any]]:
        # Use "\n" only: str.splitlines() also splits on U+2028/U+2029 inside doc_text.
        return [json.loads(line) for line in self.read(path).decode("utf-8").split("\n") if line.strip()]


def doc_sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def load_parquet_meta(inputs: InputSnapshot) -> dict[str, dict[str, Any]]:
    import pyarrow.parquet as pq

    meta: dict[str, dict[str, Any]] = {}
    hf_home = Path(os.environ.get("HF_HOME") or ROOT / "data" / "cache" / "hf")
    hub = Path(os.environ.get("HF_HUB_CACHE") or hf_home / "hub")
    snapshot = hub / "datasets--Lucius-Morningstar--mailroom-dataset" / "snapshots" / REVISION
    shards = sorted(snapshot.glob("parquet/ground_truth/*/*.parquet"))
    if not shards:
        raise ValueError("pinned ground-truth Parquet metadata is not cached; configure HF_HOME/HF_HUB_CACHE")
    for p in shards:
        data = inputs.read(p, label=f"hf-snapshot/{REVISION}/{p.relative_to(snapshot)}")
        for r in pq.read_table(io.BytesIO(data)).to_pylist():
            r.pop("gt_fields", None)
            r.pop("prompt", None)
            did = r["document_id"]
            if did in meta:
                raise ValueError(f"duplicate Parquet metadata ID: {did}")
            meta[did] = r
    return meta


def class_fields() -> dict[str, list[str]]:
    """Target fields per class: the Dojo extraction schema (minus not_applicable) and label tasks."""
    out: dict[str, list[str]] = {}
    for d in es.MAILROOM_DOC_TYPES:
        out[d] = [n for n, f in es.extraction_schema(d).fields.items() if f.status != "not_applicable"]
    out["corporate_record"].append("filing_number")  # schema n/a, but interim gap-fills it for EDA
    out["insurance_claim"] += [f for f in ("keywords", "cms_source_table") if f not in out["insurance_claim"]]
    # Dropped from the release: no experiment or production path reads it, and no source labels it.
    for cls in out:
        out[cls] = [f for f in out[cls] if f not in DROPPED_FIELDS]
    return out


# --------------------------------------------------------------------------- generated labels

TITLE_RX = re.compile(r"^\s*((?:AMENDED\s+AND\s+RESTATED\s+)?AGREEMENT\s+AND\s+PLAN\s+OF\s+(?:MERGER|REORGANIZATION)"
                      r"(?:\s+AND\s+REORGANIZATION)?|MERGER\s+AGREEMENT|PLAN\s+OF\s+MERGER)\s*$", re.I | re.M)
GOV_RX = re.compile(r"governed\s+by,?\s+(?:and\s+(?:shall\s+be\s+)?construed\s+(?:and\s+enforced\s+)?in\s+accordance"
                    r"\s+with,?\s+)?(?:and\s+construed\s+in\s+accordance\s+with\s+)?the\s+(?:internal\s+)?laws?\s+of\s+"
                    r"(?:the\s+)?((?:State|Commonwealth)\s+of\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?|[A-Z][a-zA-Z]+"
                    r"(?:\s+[A-Z][a-zA-Z]+)?)", re.S)
DATED_RX = re.compile(r"(?:dated|made\s+and\s+entered\s+into|entered\s+into|made)\s+(?:as\s+of|on|this)\s+"
                      r"((?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+day\s+of\s+[A-Z][a-z]+,?\s+\d{4}|[A-Z][a-z]+\.?\s+\d{1,2},?"
                      r"\s+\d{4})", re.S)
ROLE_RX = re.compile(r"([A-Z][A-Za-z0-9.,&'\- ]{2,90}?),\s+an?\s+[A-Za-z .\-]{0,60}?(?:corporation|company|limited"
                     r"\s+partnership|partnership|trust|bank|N\.V\.|plc|S\.A\.)[^()]{0,40}?\(\s*(?:the\s+|together\s+"
                     r"with\s+[^)]*?)?[\"“]([A-Z][A-Za-z ]{1,30})[\"”]", re.S)
CORP_JUR_RX = re.compile(r"\ba\s+(Delaware|Nevada|Maryland|New\s+York|California|Texas|Florida|Ohio|Colorado|"
                         r"Washington|Pennsylvania|Massachusetts|New\s+Jersey|Minnesota|Wisconsin|Utah|Georgia|Virginia|"
                         r"Indiana|Michigan|Illinois|Oregon|Arizona|Wyoming|Oklahoma|Missouri|Tennessee|Connecticut|"
                         r"North\s+Carolina|Louisiana|Kansas|Iowa|British\s+Columbia|Cayman\s+Islands)\s+"
                         r"(?:corporation|limited\s+liability\s+company|statutory\s+trust|company)\b")
FEE_RX = {
    "target_termination_fee": re.compile(r"[\"“]Company\s+Termination\s+Fee[\"”]\s+(?:shall\s+)?means?\s+"
                                         r"(?:an\s+amount\s+(?:in\s+cash\s+)?equal\s+to\s+)?(\$\s?[\d,]+(?:\.\d+)?)"),
    "parent_termination_fee": re.compile(r"[\"“](?:Parent|Buyer)\s+(?:Reverse\s+)?Termination\s+Fee[\"”]\s+"
                                         r"(?:shall\s+)?means?\s+(?:an\s+amount\s+(?:in\s+cash\s+)?equal\s+to\s+)?"
                                         r"(\$\s?[\d,]+(?:\.\d+)?)"),
}
CASH_RX = re.compile(r"(?:right\s+to\s+receive|converted\s+into\s+the\s+right\s+to\s+receive)\s+(?:an\s+amount\s+in\s+cash"
                     r"\s+equal\s+to\s+)?(\$\s?\d[\d,]*\.\d{2,4})\s+(?:in\s+cash|per\s+share)", re.S)
OUTSIDE_RX = [
    re.compile(r"(?:on\s+or\s+before|prior\s+to|later\s+than)\s+(?:11:59\s+p\.m\.[^,]{0,40},?\s+on\s+)?"
               r"([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})\s*\((?:such\s+date[^)]*|the\s+)?[\"\u201c](?:Outside|End|"
               r"Termination)\s+Date[\"\u201d]", re.S),
    re.compile(r"[\"\u201c](?:Outside|End|Termination)\s+Date[\"\u201d]\s+(?:shall\s+)?means?\s+"
               r"([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})"),
]
RATIO_RX = [
    re.compile(r"[\"\u201c]Exchange\s+Ratio[\"\u201d]\)?\s+(?:shall\s+)?(?:means?|equal\s+to|of)\s+(\d+\.\d+)"),
    re.compile(r"(\d+\.\d{3,6})\s+\(the\s+[\"\u201c]Exchange\s+Ratio[\"\u201d]\)"),
]
SIGNER_RX = re.compile(r"By:\s*/s/\s*([A-Z][A-Za-z.'\- ]{2,40}?)\s*\n")
BROKER_RX = re.compile(r"(?:broker|financial\s+advisor|investment\s+bank)[^.]{0,200}?other\s+than\s+([A-Z][A-Za-z&.,' ]"
                       r"{2,70}?(?:LLC|Inc\.|L\.P\.|& Co\.|Incorporated|LLP|Securities|Partners|Group))", re.S | re.I)
COUNSEL_RX = re.compile(r"copy[^:]{0,80}:\s*\n?\s*([A-Z][A-Za-z&,.' ]{2,80}?(?:LLP|L\.L\.P\.|P\.C\.|P\.A\.))", re.S)
CMS_SUBCLASSES = {"carrier", "inpatient", "outpatient", "pde"}
ACQ_ROLES = {"parent", "buyer", "acquirer", "acquiror", "purchaser"}
TGT_ROLES = {"company", "target"}
SUB_ROLES = {"merger sub", "sub", "merger subsidiary", "acquisition sub", "purchaser sub"}


_ABBREV_END = re.compile(r"\b(?:Inc|Corp|Co|Ltd|L\.P|L\.L\.C|N\.V|S\.A|P\.C|P\.A|L\.L\.P|plc|Incorporated)$")
_TITLES = {"ceo", "cfo", "coo", "president", "secretary", "treasurer", "director", "manager", "chairman", "officer",
           "title", "name", "vice", "chief", "executive", "partner", "member", "talent", "authorized", "signatory"}


def _clean_name(s: str) -> str:
    """A party name without preamble ("dated ..., by and among"), spacing fixed, abbreviation dot kept."""
    s = re.sub(r"\s+", " ", s).strip(" ,")
    parts = re.split(r"\b(?:by\s+and\s+(?:among|between)|among|between)\s+", s, flags=re.I)
    s = parts[-1]
    s = re.sub(r"^(?:and|by)\s+", "", s, flags=re.I).strip(" ,")
    if s.endswith(".") and not _ABBREV_END.search(s[:-1]):
        s = s[:-1]
    elif _ABBREV_END.search(s) and not s.endswith("."):
        s += "."
    return re.sub(r",(?=\S)", ", ", s)


def _clean_signer(s: str) -> str:
    """A /s/ signer without a repeated printed name or a trailing title."""
    words = re.sub(r"\s+", " ", s).strip(" ,.").split()
    for n in range(2, len(words) // 2 + 1):
        if [w.lower() for w in words[:n]] == [w.lower() for w in words[n:2 * n]]:
            words = words[:n]
            break
    while len(words) > 2 and words[-1].lower().strip(",.") in _TITLES:
        words.pop()
    return " ".join(words)


def _date_value(span: str) -> str | None:
    """ISO date of a span; None for a blank template date ("[___], 2020") or no date at all."""
    iso = to_iso(span)
    if iso:
        return iso
    # A year with no month, or a blank template ("[___], 2020", "this  day of , 2012"), is no date.
    has_month = any(w.lower().strip(".,") in MONTHS for w in span.split())
    blank = re.search(r"_{2,}|\[|\]", span) or not re.search(r"\d{4}", span)
    return span.strip() if has_month and not blank else None


# CUAD clause spans that answer schema fields the Dojo still marks pending_annotation.
_MONTH_RX = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar"
             r"|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)")
SPAN_DATE_RX = re.compile(rf"({_MONTH_RX}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s*\d{{4}}"
                          rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?{_MONTH_RX},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})")
END_CUE_RX = re.compile(r"(?:until|through|thru|expir\w*|end\w*|terminat\w*|to\s+and\s+including)\W+(?:\w+\W+){0,6}?$", re.I)
PERIOD_RX = re.compile(r"((?:(?:at\s+least|at\s+most|not\s+less\s+than|no\s+less\s+than|not\s+more\s+than|"
                       r"no\s+more\s+than|no\s+later\s+than|a\s+minimum\s+of|a\s+maximum\s+of)\s+)?"
                       r"(?:[a-z\-]+\s+)?\(?\d+\)?\s*(?:calendar\s+|business\s+|working\s+)?"
                       r"(?:days?|months?|years?))\b", re.I)
START_CUE_RX = re.compile(r"(?:commenc\w*|begin\w*|effective|from|dated|as\s+of|start\w*|since|force)\W+(?:\w+\W+){0,3}?$",
                          re.I)
FORUM_TAIL_RX = re.compile(r",?\s+(?:pursuant|for\s+the\s+(?:resolution|purpose)|in\s+relation|in\s+connection|with\s+respect"
                           r"|in\s+any\s+(?:action|suit|proceeding)|provided|and\s+(?:each|both|the)\s+part|having\s+jurisdiction"
                           r"\s+over\s+(?:the|any)|in\s+that\s+regard|and\s+waive|to\s+(?:the\s+)?exclusion|which\s+shall|shall\s+(?:have|be)"
                           r"|arising|and\s+agree)\b.*$",
                          re.I)
NOTICE_CUE_RX = re.compile(r"\b(?:notice|notification)\b", re.I)
FORUM_RX = re.compile(r"((?:(?:the\s+)?(?:state\s+(?:and|or)\s+federal|federal\s+(?:and|or)\s+state|state|federal|"
                      r"exclusive|competent)\s+)?courts?\s+(?:of|located\s+in|in|sitting\s+in|for|having\s+jurisdiction\s+in)"
                      r"\s+[^.;]{3,160}|arbitration\s+(?:in|held\s+in|conducted\s+in|administered\s+by|under)\s+[^.;]{3,140})",
                      re.I)
def _cuad_expiration(spans: list[str]) -> str | None | bool:
    """ISO end date stated in the Expiration Date spans; None when no calendar date; False when ambiguous."""
    if not spans or not any(s.strip() for s in spans):
        return False  # an absent annotation is not evidence of documented absence
    hits = []
    for s in spans:
        for m in SPAN_DATE_RX.finditer(s):
            iso = to_iso(m.group(1))
            if iso is None:
                return False  # invalid calendar dates cannot support an absence vote
            if iso and len(iso) == 10:
                before = s[:m.start()][-80:]
                hits.append((iso, bool(END_CUE_RX.search(before)), bool(START_CUE_RX.search(before[-40:]))))
    cued = sorted({d for d, c, _ in hits if c})
    every = sorted({d for d, _, start in hits if not start})
    if not hits:
        # Span text without a parseable calendar date is not evidence of documented absence.
        return False
    if len(cued) == 1:
        return cued[0]
    if not cued and len(every) == 1 and len(hits) == 1:
        return every[0]
    if not cued and not every:  # only a start date ("begins on February 1, 1998 and ends on ...")
        return None
    return False


def _cuad_notice(spans: list[str]) -> str | None:
    """Verbatim notice-period phrases from renewal-notice and termination-for-convenience spans."""
    out: list[str] = []
    for s in spans:
        flat = re.sub(r"\s+", " ", s)
        periods = list(PERIOD_RX.finditer(flat))
        for cue in NOTICE_CUE_RX.finditer(flat):
            nearby = [m for m in periods if max(m.start() - cue.end(), cue.start() - m.end(), 0) <= 80
                      and not re.search(r"[.;]", flat[min(m.end(), cue.end()):max(m.start(), cue.start())])]
            if not nearby:
                continue
            m = min(nearby, key=lambda m: max(m.start() - cue.end(), cue.start() - m.end(), 0))
            phrase = m.group(1).strip(" ,")
            if phrase and canon("termination_notice_period", phrase) not in {canon("x", p) for p in out}:
                out.append(phrase)
    return "; ".join(out)[:400] or None


def _ev(text: str, m: re.Match, g: int = 0) -> dict[str, Any]:
    return {"start": m.start(g), "end": m.end(g), "text": text[m.start(g):m.end(g)][:300]}


def _span_ev(cuad: dict[str, Any], cat: str, *, matching: str | None = None) -> list[dict[str, Any]]:
    return [{"start": x.get("start"), "cuad_category": cat, "text": str(x.get("text", ""))[:300]}
            for x in (cuad.get(cat) or []) if isinstance(x, dict)
            and (matching is None or x.get("text") == matching)]


def generated_labels(row: dict[str, Any], gt: dict[str, Any], corpus: str = "") -> dict[str, tuple[str, Any, list]]:
    """{field: (source, value, evidence)} produced by this build for one row."""
    out: dict[str, tuple[str, Any, list]] = {}
    cls, sub, text = row["expected_doc_class"], row["expected_subclass"], row.get("doc_text") or ""
    pres = parse_jsonish(gt.get("gt_presence")) or {}
    # corporate record_type is left to the Hub: it uses its own coarser vocabulary (charter_amendment
    # rows are "articles_of_incorporation", indentures "other"), so a subclass vote would be a false conflict.
    subtype_field = {"contract": "cuad_family", "correspondence": "communication_type"}.get(cls)
    if subtype_field:
        out[subtype_field] = ("generated_derived", sub, [])
    signers = list(dict.fromkeys(n for n in (_clean_signer(x) for x in SIGNER_RX.findall(text)) if len(n) > 3))
    if signers and cls in ("contract", "corporate_record", "merger_agreement"):
        out["signatories"] = ("generated_rule", signers, [_ev(text, x) for x in list(SIGNER_RX.finditer(text))[:3]])
    if cls == "insurance_claim":
        cms = "cms" in corpus.lower() and sub in CMS_SUBCLASSES
        out["cms_source_table"] = ("generated_derived", sub if cms else None, [])
    if cls == "contract":
        cuad = parse_jsonish(gt.get("cuad_clause_labels")) or {}
        labelled = isinstance(cuad, dict) and bool(cuad) and pres.get("cuad_clause_labels") == "populated"
        if labelled:
            spans = {k: [s.get("text", "") for s in (v or []) if isinstance(s, dict) and s.get("text")]
                     for k, v in cuad.items()}
            present = sorted(k for k, v in spans.items() if v)
            out["cuad_clauses"] = ("generated_derived", present, [])
            if spans.get("Document Name"):
                out["document_name"] = ("generated_derived", spans["Document Name"][0].strip(), [])
            else:
                out["document_name"] = ("generated_derived", None, [])
            names, seen = [], set()
            for p in spans.get("Parties", []):
                k = canon("parties", p)
                if k not in seen and len(p) > 3:
                    seen.add(k)
                    names.append(p.strip())
            out["parties"] = ("generated_derived", names or None, [])
            for fld, cat in (("effective_date", "Effective Date"), ("agreement_date", "Agreement Date")):
                if spans.get(cat):
                    out[fld] = ("generated_derived", _date_value(spans[cat][0]), [])
            if spans.get("Governing Law"):
                m = GOV_RX.search(" ".join(spans["Governing Law"]))
                out["governing_law"] = ("generated_derived", m.group(1) if m else spans["Governing Law"][0][:200], [])
            else:
                out["governing_law"] = ("generated_derived", None, [])
            for fld, cat in (("term_length", "Expiration Date"), ("renewal_terms", "Renewal Term")):
                out[fld] = ("generated_derived", spans[cat][0].strip()[:400] if spans.get(cat) else None, [])
            # Pending schema fields that a CUAD span answers directly (source cuad_span, evidence = the span).
            exp = _cuad_expiration(spans.get("Expiration Date", []))
            if exp is not False:  # an ambiguous span (several candidate end dates) is left to other sources
                out["expiration_date"] = ("cuad_span", exp, _span_ev(cuad, "Expiration Date"))
            notice_cats = ("Notice Period To Terminate Renewal", "Termination For Convenience")
            notice = _cuad_notice([x for c in notice_cats for x in spans.get(c, [])])
            if notice:
                out["termination_notice_period"] = ("cuad_span", notice,
                                                    [e for c in notice_cats for e in _span_ev(cuad, c)])
            for s in spans.get("Governing Law", []):
                m = FORUM_RX.search(re.sub(r"\s+", " ", s))
                if m:
                    forum = FORUM_TAIL_RX.sub("", m.group(1)).strip(" ,")
                    if "governed" in forum.lower() or not re.search(r"\b(?:of|in|at)\s+(?:the\s+)?[A-Z]", forum):
                        continue  # no named place: "courts", "court of law arising out of ..."
                    out["dispute_forum"] = ("cuad_span", forum, _span_ev(cuad, "Governing Law", matching=s))
                    break
        head = text[:4000]
        m = DATED_RX.search(head)
        if m and to_iso(m.group(1)) and "agreement_date" not in out:
            out["agreement_date"] = ("generated_rule", to_iso(m.group(1)), [_ev(text, m, 1)])
        m = GOV_RX.search(text)
        if m and "governing_law" not in out:
            out["governing_law"] = ("generated_rule", m.group(1), [_ev(text, m, 1)])
    elif cls == "merger_agreement":
        mf = hub_merger_expected_fields(gt, sub)
        for k in ("maud_clauses", "merger_consideration"):
            if not is_empty(mf.get(k)):
                out[k] = ("generated_derived", mf[k], [])
        head = text[:6000]
        m = TITLE_RX.search(head)
        if m:
            out["document_name"] = ("generated_rule", re.sub(r"\s+", " ", m.group(1)).title().replace(" And ", " and ")
                                    .replace(" Of ", " of "), [_ev(text, m, 1)])
        m = GOV_RX.search(text)
        if m:
            out["governing_law"] = ("generated_rule", m.group(1), [_ev(text, m, 1)])
        m = DATED_RX.search(head)
        if m and to_iso(m.group(1)):
            out["effective_date"] = ("generated_rule", to_iso(m.group(1)), [_ev(text, m, 1)])
        acq, tgt, subs, parties = [], [], [], []
        ev: dict[str, list] = defaultdict(list)
        for m in ROLE_RX.finditer(text[:8000]):
            name, role = _clean_name(m.group(1)), m.group(2).strip().lower()
            if not name or len(name) > 90 or name.lower().startswith(("this", "the ")):
                continue
            bucket = ("acquirer" if role in ACQ_ROLES else "target" if role in TGT_ROLES
                      else "merger_sub" if role in SUB_ROLES else None)
            if bucket is None:
                continue
            {"acquirer": acq, "target": tgt, "merger_sub": subs}[bucket].append(name)
            parties.append(name)
            ev[bucket].append(_ev(text, m, 1))
            ev["parties"].append(_ev(text, m, 1))
        if acq:
            out["acquirer"] = ("generated_rule", acq[0], ev["acquirer"][:1])
        if tgt:
            out["target"] = ("generated_rule", tgt[0], ev["target"][:1])
        if subs:
            out["merger_sub"] = ("generated_rule", list(dict.fromkeys(subs)), ev["merger_sub"])
        if parties:
            out["parties"] = ("generated_rule", list(dict.fromkeys(parties)), ev["parties"])
        for fld, rx in FEE_RX.items():
            m = rx.search(text)
            if m:
                out[fld] = ("generated_rule", m.group(1).replace(" ", ""), [_ev(text, m, 1)])
        for rx in OUTSIDE_RX:
            m = rx.search(text)
            if m and to_iso(m.group(1)):
                out["outside_date"] = ("generated_rule", to_iso(m.group(1)), [_ev(text, m, 1)])
                break
        for rx in RATIO_RX:
            m = rx.search(text)
            if m:
                out["exchange_ratio"] = ("generated_rule", m.group(1), [_ev(text, m, 1)])
                break
        advisors, aev = [], []
        for m in BROKER_RX.finditer(text):
            for name in re.split(r"\s+and\s+(?=[A-Z])|;\s*", m.group(1)):
                name = _clean_name(re.sub(r"^to\s+", "", name.strip()))
                if len(name) > 2:
                    advisors.append(name)
                    aev.append(_ev(text, m, 1))
        if advisors:
            out["financial_advisors"] = ("generated_rule", list(dict.fromkeys(advisors)), aev[:3])
        counsel = list(dict.fromkeys(_clean_name(x) for x in COUNSEL_RX.findall(text)))
        if counsel:
            out["legal_counsel"] = ("generated_rule", counsel, [_ev(text, x, 1) for x in list(COUNSEL_RX.finditer(text))[:3]])
        if sub in ("all_cash", "mixed_cash_stock", "mixed_cash_stock_election"):
            m = CASH_RX.search(text)
            if m:
                out["per_share_cash_amount"] = ("generated_rule", m.group(1).replace(" ", ""), [_ev(text, m, 1)])
    elif cls == "corporate_record":
        m = CORP_JUR_RX.search(text[:6000])
        if m:
            out["jurisdiction"] = ("generated_rule", re.sub(r"\s+", " ", m.group(1)), [_ev(text, m, 1)])
    return out


# --------------------------------------------------------------------------- vote

#: free-text fields whose CUAD phrase is folded into a label that contains it.
SPAN_COMPAT_FIELDS = {"termination_notice_period", "dispute_forum"}
_STOP = {"the", "of", "a", "an", "and", "or", "to", "in", "by", "for", "with", "any", "such", "this", "that", "be",
         "shall", "other", "party", "parties", "upon", "after", "thereof", "written", "prior", "notice", "located", "courts", "court"}


def span_compatible(span_key: str, other_key: str, *, field: str = "") -> bool:
    """True when every number and most content words of the span phrase appear in the other label."""
    if EMPTY in (span_key, other_key):
        return False
    if field == "termination_notice_period" and _notice_terms(span_key) != _notice_terms(other_key):
        return False
    a, b = set(_TOKEN.findall(span_key)), set(_TOKEN.findall(other_key))
    nums = {t for t in a if t.isdigit()}
    content = {t for t in a - _STOP if not t.isdigit()}
    if not nums <= b or not (nums or content):
        return False
    return not content or len(content & b) / len(content) >= 0.6


def _notice_terms(text: str) -> set[tuple[str, str, str, str]]:
    """Compare operators, magnitudes, units and business/calendar day qualifiers conservatively."""
    terms = set()
    for m in PERIOD_RX.finditer(text):
        phrase = m.group().lower()
        operator = "exact"
        if re.search(r"at least|(?:not|no) less than|minimum", phrase):
            operator = "minimum"
        elif re.search(r"at most|(?:not|no) more than|maximum|no later than", phrase):
            operator = "maximum"
        number = re.search(r"\d+", phrase).group()
        unit = re.search(r"(day|month|year)s?\b", phrase).group(1)
        qualifier = re.search(r"\b(business|calendar|working)\b", phrase)
        terms.add((operator, number, unit, qualifier.group() if qualifier else ""))
    return terms


def vote(field: str, ballots: list[dict[str, Any]]) -> dict[str, Any]:
    owner = [b for b in ballots if b["source"] == "owner_review"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in ballots:
        if b["source"] != "cuad_span":
            groups[canon(field, b["value"])].append(b)
    for b in ballots:  # a CUAD span phrase backs a longer label that states the same thing
        if b["source"] == "cuad_span":
            key = canon(field, b["value"])
            if field in SPAN_COMPAT_FIELDS and key not in groups:
                key = next((k for k in groups if span_compatible(key, k, field=field)), key)
            groups[key].append(b)
    if owner:
        win_key = canon(field, owner[0]["value"])
        rule = "owner_final"
    else:
        def score(k: str) -> tuple[float, int]:
            return (sum(SOURCES[b["source"]][0] for b in groups[k]), -min(SOURCES[b["source"]][1] for b in groups[k]))
        win_key = max(groups, key=score)
        rule = "weighted_vote"
    win = groups[win_key]
    # A folded CUAD phrase backs the label it agrees with; that label keeps its fuller wording.
    named = [b for b in win if b["source"] != "cuad_span"] if field in SPAN_COMPAT_FIELDS else []
    best = min(named or win, key=lambda b: SOURCES[b["source"]][1])
    total = sum(SOURCES[b["source"]][0] for b in ballots)
    share = sum(SOURCES[b["source"]][0] for b in win) / total if total else 0.0
    n = len(ballots)
    if n == 1:
        agreement = "single_source"
    elif len(groups) == 1:
        agreement = "unanimous"
    else:
        agreement = f"{len(win)}-of-{n}"
    needs_human = rule != "owner_final" and len(groups) >= 3 and share < 0.5
    disputed_only = all(b["source"] in ("gold_disputed", "interim_disputed") for b in win)
    presence = "documented_absence" if win_key == EMPTY else "populated"
    if disputed_only:  # a value a check disputed is not truth on its own
        presence, needs_human = "disputed_unresolved", True
    return {
        "value": (to_iso(str(best["value"])) or best["value"] if field in DATE_FIELDS else best["value"])
                 if win_key != EMPTY and not disputed_only else None,
        "presence": presence,
        "chosen_source": best["source"],
        "agreeing_sources": "|".join(sorted({b["source"] for b in win})),
        "agreement": agreement,
        "rule": rule,
        "weight_share": round(share, 3),
        "n_sources": n,
        "n_distinct_values": len(groups),
        "conflict": len(groups) > 1,
        "needs_human": needs_human,
        "evidence": [
            {**(e if isinstance(e, dict) else {"text": str(e)}), "source": b["source"]}
            for b in win for e in (b.get("evidence") or [])
        ],
        "votes": {b["source"]: b["value"] for b in ballots},
    }


# --------------------------------------------------------------------------- build

def interim_source(lab: dict[str, Any]) -> str | None:
    status, basis = lab.get("status"), str(lab.get("basis") or "")
    if status == "disputed":
        return "interim_disputed"
    if not lab.get("use_as_truth"):
        return None
    if basis in ("review_read_message", "original_header", "review_read_record") or "review" in lab:
        return "interim_reviewed"
    if status == "correction":
        return "interim_correction"
    if status == "derived":
        return "interim_derived"
    return "interim_gate"


def duplicate_keepers(rows: list[dict[str, Any]], meta: dict[str, dict[str, Any]],
                      corrections: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Choose a reviewed representative across connected exact/normalized duplicate groups."""
    parent = {r["id"]: r["id"] for r in rows}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    seen: dict[tuple[str, str], str] = {}
    for row in rows:
        did = row["id"]
        keys = [("exact", row.get("content_sha256") or hashlib.sha256((row.get("doc_text") or "").encode()).hexdigest()),
                ("normalized", meta[did].get("normalized_text_sha256"))]
        for kind, digest in keys:
            if not digest:
                continue
            key = (kind, digest)
            if key in seen:
                parent[find(did)] = find(seen[key])
            seen[key] = did
    groups: dict[str, list[str]] = defaultdict(list)
    for did in parent:
        groups[find(did)].append(did)
    result = {}
    for members in groups.values():
        reviewed = {corrections[did]["subclass"] for did in members if did in corrections}
        if len(reviewed) > 1:
            raise ValueError("duplicate group has conflicting reviewed subclasses")
        keeper = min(members, key=lambda did: (did not in corrections, did))
        result.update({did: keeper for did in members})
    return result


def _build(output: Path, *, with_text: bool = False) -> dict[str, Any]:
    inputs = InputSnapshot()
    jsonl = inputs.jsonl
    rows = jsonl(CACHE)
    meta = load_parquet_meta(inputs)
    missing_meta = [r["id"] for r in rows if not (meta.get(r["id"]) or {}).get("source_corpus")]
    if missing_meta:
        raise ValueError(f"missing required source metadata for {len(missing_meta)} documents")
    fields_by_class = class_fields()
    interim = {}
    for p in sorted((LABELS / "interim").glob("*.jsonl")):
        for r in jsonl(p):
            interim[r["doc_id"]] = r
    overlay = {}
    for p in sorted((LABELS / "gold-overlay").glob("*.jsonl")):
        for r in jsonl(p):
            overlay[r["doc_id"]] = r
    gold_cat: dict[tuple[str, str], dict[str, Any]] = {}
    for p in sorted((LABELS / "gold").glob("*.jsonl")):
        for r in jsonl(p):
            gold_cat[(r["doc_id"], r["field"])] = r
    owner = {(r["doc_id"], r["field"]): r for r in jsonl(LABELS / "review" / "human_reviews.jsonl")
             if r.get("decision") in ("keep", "use_suggestion", "correct")}
    subfix = {r["doc_id"]: r for r in jsonl(LABELS / "review" / "subclass_corrections.jsonl")
              if r.get("verdict") == "correct"}
    keepers = duplicate_keepers(rows, meta, subfix)

    all_fields: list[str] = []
    for d in es.MAILROOM_DOC_TYPES:
        all_fields += [f for f in fields_by_class[d] if f not in all_fields]

    wide, long_rows = [], []
    stale = Counter()
    nan_cleaned = 0
    content_groups: dict[str, list[str]] = defaultdict(list)
    norm_groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        m = meta.get(row["id"], {})
        content_key = row.get("content_sha256") or hashlib.sha256((row.get("doc_text") or "").encode()).hexdigest()
        content_groups[content_key].append(row["id"])
        if m.get("normalized_text_sha256"):
            norm_groups[m["normalized_text_sha256"]].append(row["id"])

    for row in sorted(rows, key=lambda r: r["id"]):
        did, cls, text = row["id"], row["expected_doc_class"], row.get("doc_text") or ""
        m = meta.get(did, {})
        sha = doc_sha(text)
        gt = dict(row["expected_fields"])
        nan_cleaned += sum(1 for v in gt.values() if isinstance(v, str) and v.strip().lower() == "nan")
        pres = parse_jsonish(gt.get("gt_presence")) or {}
        irec = interim.get(did)
        if irec and irec.get("doc_sha256") != sha:
            stale["interim"] += 1
            irec = None
        orec = overlay.get(did)
        if orec and orec.get("doc_sha256") != sha:
            stale["near_gold"] += 1
            orec = None

        # subclass: Hub vs reviewed correction vs interim/near-gold doc_subclass is not a label; vote Hub + review
        sub_ballots = [{"source": "hub_v9.3", "value": row["expected_subclass"]}]
        if did in subfix:
            sub_ballots.append({"source": "subclass_review", "value": subfix[did]["subclass"],
                                "evidence": [{"text": e[:300]} for e in subfix[did].get("evidence") or []]})
        sub_res = vote("subclass", sub_ballots)
        gen = generated_labels({**row, "expected_subclass": sub_res["value"]}, gt, m["source_corpus"])
        if sub_res["value"] != row["expected_subclass"]:
            for field in ("merger_consideration", "cuad_family", "communication_type", "cms_source_table"):
                if field in gen:
                    source, value, evidence = gen[field]
                    gen[field] = (source, value, [*evidence, {"derived_from_subclass": sub_res["value"],
                                                           "source": sub_res["chosen_source"],
                                                           "review_evidence": sub_res["evidence"]}])
        content_key = row.get("content_sha256") or hashlib.sha256(text.encode()).hexdigest()
        out = {
            "document_id": did,
            "filename": row["filename"],
            "split": row["split"],
            "doc_class": cls,
            "subclass": sub_res["value"],
            "subclass_hub_v9_3": row["expected_subclass"],
            "subclass_changed": sub_res["value"] != row["expected_subclass"],
            "source_corpus": m.get("source_corpus", ""),
            "annotation_source": m.get("annotation_source", ""),
            "annotation_method": m.get("annotation_method", ""),
            "annotation_confidence": m.get("annotation_confidence", ""),
            "expected_specialist": m.get("expected_specialist", ""),
            "expected_stage": row.get("expected_stage", ""),
            "review_expected": m.get("review_expected", ""),
            "matter_id": m.get("matter_id", ""),
            "group_id": m.get("group_id", ""),
            "thread_size": m.get("thread_size", ""),
            "related_document_ids": json.dumps(m.get("related_document_ids") or []),
            "token_estimate": gt.get("token_estimate", ""),
            "context_window_band": gt.get("context_window_band", ""),
            "char_count": len(text),
            "word_count": len(text.split()),
            "content_sha256": row["content_sha256"],
            "exact_duplicate_count": len(content_groups[content_key]),
            "normalized_duplicate_count": len(norm_groups.get(m.get("normalized_text_sha256", ""), [did])),
            "duplicate_of": "",
            "doc_text_preview": re.sub(r"\s+", " ", text[:280]).strip(),
        }
        if keepers[did] != did:
            out["duplicate_of"] = keepers[did]
        if sub_res["value"] != row["expected_subclass"]:
            long_rows.append({"document_id": did, "doc_class": cls, "field": "subclass", **_long(sub_res)})

        targets = fields_by_class[cls]
        n_target = n_labeled = n_conflict = n_human = 0
        for field in all_fields:
            if field not in targets:
                out[field] = ""
                continue
            ballots: list[dict[str, Any]] = []
            p = pres.get(field)
            hv = parse_jsonish(gt.get(field))
            if p == "populated" or (p is None and not is_empty(hv)):
                ballots.append({"source": "hub_v9.3", "value": hv})
            elif p == "schema_documented_absence":
                ballots.append({"source": "hub_v9.3", "value": None})
            if irec and field in irec["labels"]:
                lab = irec["labels"][field]
                src = interim_source(lab)
                if src:
                    ballots.append({"source": src, "value": lab.get("value"), "evidence": lab.get("evidence") or []})
            if orec and field in (orec.get("labels") or {}):
                lab = orec["labels"][field]
                basis = str(lab.get("basis") or "")
                src = "near_gold_two_pass" if basis.endswith("two_pass_agree") else "near_gold_reviewed"
                ballots.append({"source": src, "value": lab.get("value"), "evidence": lab.get("evidence") or []})
            elif (did, field) in gold_cat:
                g = gold_cat[(did, field)]
                if (g.get("content_sha256") or "")[:16] == sha or g.get("doc_sha") == sha:
                    src = {"candidate": "gold_candidate", "disputed": "gold_disputed",
                           "near_gold": "near_gold_two_pass"}.get(g.get("status"))
                    if src:
                        ballots.append({"source": src, "value": g.get("value"), "evidence": g.get("evidence") or []})
            if field in gen:
                s, v, ev = gen[field]
                ballots.append({"source": s, "value": v, "evidence": ev})
            if (did, field) in owner:
                ballots.append({"source": "owner_review", "value": owner[(did, field)]["value"]})
            n_target += 1
            if not ballots:
                out[field] = ""
                long_rows.append({"document_id": did, "doc_class": cls, "field": field, "value": "",
                                  "presence": NOT_LABELED, "chosen_source": "", "agreeing_sources": "",
                                  "agreement": "", "rule": "", "weight_share": "", "n_sources": 0,
                                  "n_distinct_values": 0, "conflict": False, "needs_human": False,
                                  "evidence": "", "votes": "{}"})
                continue
            res = vote(field, ballots)
            n_labeled += res["presence"] in ("populated", "documented_absence")
            n_conflict += res["conflict"]
            n_human += res["needs_human"]
            out[field] = _cell(res["value"])
            long_rows.append({"document_id": did, "doc_class": cls, "field": field, **_long(res)})
        out["fields_targeted"] = n_target
        out["fields_labeled"] = n_labeled
        out["label_completeness"] = round(n_labeled / n_target, 4) if n_target else 1.0
        out["fields_with_conflict"] = n_conflict
        out["fields_needs_human"] = n_human
        wide.append(out)

    _write(output / f"{STEM}.csv", wide)
    _write(output / f"{STEM}_label_provenance.csv", long_rows)

    # per-field completeness, before (Hub only) and after
    comp = []
    by = defaultdict(list)
    for lr in long_rows:
        if lr["field"] != "subclass":
            by[(lr["doc_class"], lr["field"])].append(lr)
    for (cls, field), items in sorted(by.items()):
        hub_only = sum(1 for i in items if "hub_v9.3" in json.loads(i["votes"] or "{}"))
        labeled = sum(1 for i in items if i["presence"] in ("populated", "documented_absence"))
        src = Counter(i["chosen_source"] for i in items if i["chosen_source"])
        comp.append({
            "doc_class": cls, "field": field, "documents": len(items),
            "labeled_hub_v9_3": hub_only, "labeled_repaired": labeled,
            "populated": sum(1 for i in items if i["presence"] == "populated"),
            "documented_absence": sum(1 for i in items if i["presence"] == "documented_absence"),
            "unlabeled": sum(1 for i in items if i["presence"] == NOT_LABELED),
            "disputed_unresolved": sum(1 for i in items if i["presence"] == "disputed_unresolved"),
            "completeness_hub_v9_3": round(hub_only / len(items), 4),
            "completeness_repaired": round(labeled / len(items), 4),
            "conflicts": sum(1 for i in items if str(i["conflict"]) == "True"),
            "needs_human": sum(1 for i in items if str(i["needs_human"]) == "True"),
            "top_source": src.most_common(1)[0][0] if src else "",
        })
    _write(output / f"{STEM}_field_completeness.csv", comp)

    chosen = Counter(lr["chosen_source"] for lr in long_rows if lr["chosen_source"])
    summary = {
        "dataset": "Lucius-Morningstar/mailroom-dataset", "revision": REVISION, "release": "v9.3",
        "documents": len(wide),
        "class_counts": dict(Counter(w["doc_class"] for w in wide)),
        "label_cells_targeted": sum(w["fields_targeted"] for w in wide),
        "label_cells_labeled_hub_v9_3": sum(c["labeled_hub_v9_3"] for c in comp),
        "label_cells_labeled_repaired": sum(c["labeled_repaired"] for c in comp),
        "label_cells_unlabeled": sum(c["unlabeled"] for c in comp),
        "label_cells_disputed_unresolved": sum(c["disputed_unresolved"] for c in comp),
        "conflicts_resolved": sum(c["conflicts"] for c in comp),
        "needs_human": sum(c["needs_human"] for c in comp),
        "subclass_changed": sum(1 for w in wide if w["subclass_changed"]),
        "nan_placeholders_dropped": nan_cleaned,
        "duplicate_rows_flagged": sum(1 for w in wide if w["duplicate_of"]),
        "stale_overlay_records_skipped": dict(stale),
        "chosen_source_counts": dict(chosen.most_common()),
        "source_weights": {k: {"weight": w, "tie_rank": r} for k, (w, r) in SOURCES.items()},
        "inputs_sha256": dict(sorted(inputs.hashes.items())),
    }
    if with_text:  # full document text, joined on document_id; never committed
        import gzip

        with (output / f"{STEM}_text.csv.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed, io.TextIOWrapper(compressed, newline="", encoding="utf-8") as f:
            tw = csv.writer(f)
            tw.writerow(["document_id", "doc_text"])
            for r in sorted(rows, key=lambda r: r["id"]):
                tw.writerow([r["id"], r.get("doc_text") or ""])
    summary["outputs_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir())}
    (output / f"{STEM}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def build(output: Path, *, with_text: bool = False) -> dict[str, Any]:
    """Publish a complete new generation by directory rename; never replace existing output."""
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output exists; choose a new generation directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".label-repair-", dir=output.parent) as temp:
        staged = Path(temp) / "generation"
        staged.mkdir()
        summary = _build(staged, with_text=with_text)
        staged.rename(output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT / "generated", help="new output directory; existing directories are refused")
    parser.add_argument("--with-text", action="store_true")
    args = parser.parse_args()
    summary = build(args.out, with_text=args.with_text)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("inputs_sha256", "outputs_sha256", "source_weights")}, indent=1))


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _long(res: dict[str, Any]) -> dict[str, Any]:
    return {"value": _cell(res["value"]), "presence": res["presence"], "chosen_source": res["chosen_source"],
            "agreeing_sources": res["agreeing_sources"], "agreement": res["agreement"], "rule": res["rule"],
            "weight_share": res["weight_share"], "n_sources": res["n_sources"],
            "n_distinct_values": res["n_distinct_values"], "conflict": res["conflict"],
            "needs_human": res["needs_human"],
            "evidence": json.dumps(res["evidence"], ensure_ascii=False) if res["evidence"] else "",
            "votes": json.dumps(res["votes"], ensure_ascii=False, sort_keys=True, default=str)}


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
