"""Interim ground-truth labels: the unpublished enhancements to the mailroom-dataset GT.

The Hub ``ground_truth`` rows leave key fields unlabelled (corporate entity/jurisdiction/dates/
signatories, correspondence sender/recipient/date/type, every merger field but consideration) and
carry a few labels the document contradicts or the scorer reads too strictly (CUAD party spans,
CUAD effective date; CMS claim_type collapsed onto ``health``). Until the next dataset revision
publishes them, this overlay supplies those labels from REAL specialist extractions that the
extraction gate accepted field by field, plus deterministic labels derived from the row itself.

Every label carries its status and basis:

``gap_fill``    the Hub has no label for the field; the gate supports the extracted value
                (field support >= ``SUPPORT_MIN``, verdict not human_review) and every token of
                it is in the document (``grounded``).
``derived``     computed from the row, no model involved (``cms_source_table``: dojo #93;
                ``record_type`` / ``communication_type``: the row's own expected_subclass).
``correction``  the Hub label exists but a documented GT/scorer defect makes it unattainable;
                the extracted value is gate-accepted AND checked against the Hub's own evidence
                (``cuad_party_spans``: every extracted party is a CUAD Parties span;
                ``cuad_agreement_date``: CUAD Effective Date is empty and the value equals the
                CUAD Agreement Date).
``disputed``    the Hub label exists, the scorer says the extraction is wrong, the gate says it
                is right, and no rule decides: NOT ground truth (``use_as_truth`` false), kept
                for the human review that the dataset revision needs.

Reviewed labels come from a committed review file (``data/labels/review/interim_reviews.jsonl``),
not from a gate run, and carry a ``review`` block (reviewer, note, file). They use the same
statuses, with a basis of their own (``REVIEW_BASES``):

``correction`` / ``review_read_message``  a heuristic Hub ``intent`` the review found wrong after
                reading the message; it replaces the Hub value, which the label keeps as
                ``hub_value``.
``gap_fill`` / ``original_header``  a correspondence header field the corpus text omits because
                the email header was stripped; the value is read from the original message's
                header (CMU Enron maildir), and the label quotes that header line as evidence.
``correction`` / ``review_read_record``  a corporate ``entity_name`` the review found wrong after
                reading the record (the Hub took the filer's name from the EDGAR template, not
                the entity the record names); it replaces the Hub value, kept as ``hub_value``.
                A name quotes the text that states it; null means the record names no entity.

A reviewed label replaces any gate label of the same field; the replaced label is kept as
``replaced``. ``scripts/interim_labels.py review`` applies the file, and ``build`` re-applies it.

Files live in ``data/labels/interim/`` (one JSONL per class plus ``MANIFEST.json`` with hashes,
sources and counts), built only by ``scripts/interim_labels.py build`` and verified by
``scripts/interim_labels.py check`` and ``tests/test_interim_labels.py``. Nothing reads them
unless a run asks: ``dataset.interim_labels: true`` merges the truth labels into the locked
rows' ``expected_fields`` and records the overlay hash in the lock, so a score that used them is
never mistaken for a Hub-GT score (dojo #97). A label the Hub publishes supersedes the overlay
(``check --rows`` reports it; ``build`` drops it on the next rebuild).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from mailroom_sandbox.paths import repo_root

SCHEMA = "mailroom-interim-labels/v1"
STATUSES = ("gap_fill", "derived", "correction", "disputed")
TRUTH_STATUSES = ("gap_fill", "derived", "correction")
SUPPORT_MIN = 0.9  # field support a gap fill / correction needs (calibrated in the manifest)
NULL_SUPPORT_MIN = 0.95  # "the document does not state it" needs more
CMS_TABLES = ("carrier", "inpatient", "outpatient", "pde")
# Extraction fields the Hub already labels under another name: the row's expected_subclass IS the
# record kind / communication form, so the label is derived from it, never from an extraction
# (a gap fill read "bylaws" off a board consent's exhibit title the Hub files as board_resolution).
SUBCLASS_FIELDS = {"corporate_record": "record_type", "correspondence": "communication_type"}
# Fields per class the overlay may gap-fill: the gate's key fields the Hub leaves unlabelled.
GAP_FIELDS: dict[str, tuple[str, ...]] = {
    "corporate_record": ("entity_name", "jurisdiction", "effective_date", "filing_number", "signatories"),
    "correspondence": ("sender", "recipient", "communication_date"),
    "merger_agreement": ("document_name", "parties", "effective_date", "effective_time", "governing_law"),
    "contract": (),
    "insurance_claim": (),
}
# The dojo issue whose dataset/scorer change supersedes each class's interim labels.
SUPERSEDED_BY = {
    "corporate_record": "llm-dojo-scoring#52 (corporate-record annotation)",
    "correspondence": "llm-dojo-scoring#94 (correspondence GT)",
    "merger_agreement": "llm-dojo-scoring#95 (merger fields without GT)",
    "insurance_claim": "llm-dojo-scoring#93 (CMS mapping)",
    "contract": "CUAD Parties / Effective Date scoring (dojo scorer)",
}


def overlay_dir() -> Path:
    return repo_root() / "data" / "labels" / "interim"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def doc_sha(doc_text: str | None) -> str:
    """Short hash binding a label to the exact document text it was read from."""
    return _sha(doc_text or "")[:16]


#: Where a row keeps its field labels: the prepared row shape, then the Hub ``ground_truth`` column.
_LABEL_KEYS = ("expected_fields", "gt_fields")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _labels_key(row: Mapping[str, Any]) -> str:
    return next((k for k in _LABEL_KEYS if k in row), _LABEL_KEYS[0])


def _expected(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get(_labels_key(row)) or {}
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def row_id(row: Mapping[str, Any]) -> str:
    """The document id of a prepared row (``id``) or of a Hub parquet row (``document_id``)."""
    return str(row.get("id") or row.get("document_id") or "")


def row_doc_sha(row: Mapping[str, Any]) -> str:
    """The text hash of a row, comparable with a record's ``doc_sha256``.

    The document text when the row carries it. A Hub ``ground_truth`` row has no text, so its
    ``content_sha256`` (the sha256 of that same text, which ``doc_sha`` shortens) stands in.
    """
    if row.get("doc_text") is not None:
        return doc_sha(row.get("doc_text"))
    content = str(row.get("content_sha256") or "")
    return content[:16] if _HEX64.fullmatch(content) else doc_sha(None)


def _presence(exp: Mapping[str, Any]) -> dict[str, str]:
    raw = exp.get("gt_presence") or {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return {}


def hub_has(exp: Mapping[str, Any], field: str) -> bool:
    """Whether the Hub row labels ``field`` (populated, not a template/absence marker)."""
    pres = _presence(exp).get(field)
    if pres is not None:
        return pres == "populated"
    value = exp.get(field)
    return value not in (None, "", "nan", [], {}, "[]", "{}")


def _empty(value: Any) -> bool:
    return value in (None, "", [], {}) or (isinstance(value, str) and value.strip().lower() in {"none", "null", "n/a"})


_TOKEN = re.compile(r"[a-z0-9]+")
_ANNOTATION = re.compile(r"\((?:[^()]*)\)|\"[^\"]*\"|“[^”]*”")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.casefold()))


def _date_forms(value: str) -> set[str]:
    from datetime import date

    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return set()
    month, short = d.strftime("%B"), d.strftime("%b")
    return {f"{d:%Y-%m-%d}", f"{d.month}/{d.day}/{d.year}", f"{d:%m/%d/%Y}", f"{month} {d.day}, {d.year}",
            f"{month} {d.day} {d.year}", f"{d.day} {month} {d.year}", f"{short} {d.day}, {d.year}",
            f"{short}. {d.day}, {d.year}", f"{month} {d.day}st, {d.year}", f"{month} {d.day}nd, {d.year}",
            f"{month} {d.day}rd, {d.year}", f"{month} {d.day}th, {d.year}", f"{d.day}th day of {month}, {d.year}",
            f"{d.day}th day of {month} {d.year}", f"{d.day}st day of {month}, {d.year}",
            f"{d.day}nd day of {month}, {d.year}", f"{d.day}rd day of {month}, {d.year}"}


def grounded(value: Any, doc_text: str) -> bool:
    """Every token of the value (each list element; annotations stripped) occurs in the document.

    Dates (``YYYY-MM-DD``) must appear in one of the usual written forms. Token-level, so name
    order ("Denne, Karen" / "Karen Denne") and punctuation do not matter.
    """
    if _empty(value):
        return True
    folded = re.sub(r"\s+", " ", doc_text.casefold())
    items = value if isinstance(value, list) else [value]
    doc_tokens = _tokens(doc_text)
    for item in items:
        text = str(item)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", text.strip()):
            forms = _date_forms(text.strip())
            if not any(f.casefold() in folded for f in forms):
                return False
            continue
        core = _ANNOTATION.sub(" ", text)
        toks = _tokens(core)
        if not toks or not toks <= doc_tokens:
            return False
    return True


def _party_core(text: str) -> str:
    return re.sub(r"\s+", " ", _ANNOTATION.sub(" ", str(text))).strip(" ,.;").casefold()


def _same_date(a: Any, b: str) -> bool:
    from dateutil import parser

    try:
        return parser.parse(str(a), fuzzy=True).date() == parser.parse(str(b), fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return False


#: Tokens that mark a span as a legal entity's name.
_ENTITY_SUFFIXES = frozenset({
    "inc", "incorporated", "llc", "l", "corp", "corporation", "co", "company", "ltd", "limited", "lp",
    "llp", "plc", "gmbh", "ag", "sa", "nv", "bv", "pty", "trust", "bank", "holdings", "partnership",
})


def _parties_cover_spans(value: list[Any], spans: list[str]) -> bool:
    """Whether the extracted parties are CUAD ``Parties`` spans and miss no named entity.

    Each extracted party (annotation stripped) must be a span. CUAD's ``Parties`` spans also
    hold defined terms, pronouns, abbreviations and whole "referred to as the Parties"
    sentences; those name no further party. A span that carries an entity suffix
    (``Inc.``, ``LLC``, ``Corporation`` ...) and is neither an extracted party, a defined term
    the extraction attaches, nor contained in an extracted party's name is a **missed legal
    entity**: the extraction is incomplete, and is not a correction of the Hub label.
    """
    gt = {_party_core(s) for s in spans} - {""}
    cores = [_party_core(v) for v in value]
    if not gt or not all(c in gt for c in cores):
        return False
    defined = {_party_core(m.group(0).strip("()\"“”")) for v in value for m in _ANNOTATION.finditer(str(v))}
    party_tokens = [_tokens(c) for c in cores]
    for span in gt:
        toks = _tokens(span)
        if span in cores or span in defined or any(toks <= p for p in party_tokens):
            continue
        if toks & _ENTITY_SUFFIXES and len(toks) <= 12:
            return False
    return True


def contract_correction(field: str, value: Any, exp: Mapping[str, Any]) -> str | None:
    """The basis that makes a contract value a correction of its CUAD label, or None."""
    from llm_dojo_scoring.sandbox_scoring import gt_categories

    spans = gt_categories(exp.get("cuad_clause_labels"))
    if field == "parties" and isinstance(value, list) and value and _parties_cover_spans(value, spans.get("Parties") or []):
        return "cuad_party_spans"
    if field == "effective_date" and not _empty(value):
        agreement = spans.get("Agreement Date") or []
        if not (spans.get("Effective Date") or []) and agreement and any(_same_date(value, a) for a in agreement):
            return "cuad_agreement_date"
    return None


def derived_value(cls: str, subclass: str) -> str:
    """The ``SUBCLASS_FIELDS`` label a row's own subclass implies.

    Correspondence subclasses are the ``communication_type`` vocabulary itself. Corporate
    subclasses are not the ``record_type`` vocabulary: the Dojo maps the ten subclasses onto a
    5-token enum (``indenture`` / ``board_resolution`` / ... -> ``other``, ``charter_amendment``
    -> ``articles_of_incorporation``), and the specialist is told to emit that enum.
    """
    if cls == "corporate_record":
        from llm_dojo_scoring.schemas.corporate_record_schema import record_type_for_subclass

        return record_type_for_subclass(subclass)
    return subclass


# ── reviewed labels ────────────────────────────────────────────────────────

#: Correspondence fields an email header states: the corpus text lost them with the header.
HEADER_FIELDS = ("sender", "recipient", "additional_recipients", "communication_date")
#: basis -> (status, {doc_class: fields}) a reviewed label may take.
REVIEW_BASES: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "review_read_message": ("correction", {"correspondence": ("intent",)}),
    "original_header": ("gap_fill", {"correspondence": HEADER_FIELDS}),
    "review_read_record": ("correction", {"corporate_record": ("entity_name",)}),
}
#: Where an ``original_header`` quote must come from, and the header lines each field reads.
HEADER_SOURCE = "cmu_enron_maildir"
HEADER_LINES = {"sender": ("X-From", "From"), "recipient": ("X-To", "To"),
                "additional_recipients": ("X-To", "X-cc", "To", "Cc"), "communication_date": ("Date",)}
_HEX16 = re.compile(r"[0-9a-f]{16}")
_REVIEW_KEYS = ("doc_id", "doc_class", "doc_subclass", "doc_sha256", "field", "status", "basis", "value",
                "evidence", "reviewer", "note")


def review_path() -> Path:
    """The committed review file ``scripts/interim_labels.py review`` applies by default."""
    return repo_root() / "data" / "labels" / "review" / "interim_reviews.jsonl"


def _intent_vocabulary() -> tuple[str, ...]:
    from mailroom_sandbox import gold_labels as gl

    return gl._schema_bits("correspondence")[1]["intent"]


def _header_date(header: str) -> str | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(header.split(":", 1)[1].strip()).date().isoformat()
    except (IndexError, TypeError, ValueError):
        return None


def _header_problem(field: str, value: Any, evidence: Any) -> str | None:
    """Why the quoted header lines do not show ``value`` (None: they do)."""
    if not isinstance(evidence, list) or not evidence:
        return "an original_header label needs the header lines as evidence"
    headers = []
    for ev in evidence:
        if not isinstance(ev, dict) or ev.get("source") != HEADER_SOURCE or not ev.get("file") \
                or not isinstance(ev.get("header"), str):
            return f"evidence must be {{source: {HEADER_SOURCE!r}, file, header}}: {ev!r}"
        if ":" not in ev["header"]:
            return f"a header line reads 'Name: value', not {ev['header']!r}"
        name = ev["header"].split(":", 1)[0]
        if name not in HEADER_LINES[field]:
            return f"{field} is read from {'/'.join(HEADER_LINES[field])}, not {name}"
        headers.append(ev["header"])
    if value is None or value == []:
        return _empty_header_problem(field, headers)
    if field == "communication_date":
        if value not in {_header_date(h) for h in headers}:
            return f"{value!r} is not the date the Date header states"
        return None
    # Each token of each name occurs in the quoted header lines (a mangled export can fuse a
    # name with its mail domain, "Michael GrimesCORPENRON", so a token match is too strict).
    text = " ".join(h.split(":", 1)[1] for h in headers).casefold()
    for item in value if isinstance(value, list) else ([] if value is None else [value]):
        missing = [t for t in _TOKEN.findall(str(item).casefold()) if t not in text]
        if missing:
            return f"{item!r} is not in the quoted header ({', '.join(missing)} missing)"
    return None


def _header_body(header: str) -> str:
    return header.split(":", 1)[1].strip() if ":" in header else ""


_BRACKETED = re.compile(r"<[^>]*>")


def _addressees(body: str) -> int:
    """How many people a To/X-To line names ("Roe, Jane <...>" is one, "a@x, b@y" two)."""
    if not body:
        return 0
    bracketed = len(_BRACKETED.findall(body))
    rest = _BRACKETED.sub("", body)
    if bracketed or "@" in rest:
        # each <...> is one person, and so is each bare address outside them;
        # a bare name after the last <...> ("Roe <...>, Sue Mara") is one more
        tail = body[body.rfind(">") + 1 :]
        bare_names = [part for part in tail.split(",") if part.strip() and "@" not in part]
        return bracketed + rest.count("@") + len(bare_names)
    return len([part for part in rest.split(",") if part.strip()])


def _empty_header_problem(field: str, headers: list[str]) -> str | None:
    """Why an empty value contradicts the quoted header lines (None: they are empty too)."""
    if field == "communication_date":
        dated = [h for h in headers if _header_date(h)]
        return f"null, but the header states a date: {dated[0]!r}" if dated else None
    if field == "additional_recipients":
        # No one besides the recipient: every cc line is empty and each To line names one person at most.
        for h in headers:
            name, body = h.split(":", 1)[0], _header_body(h)
            if (name in ("X-cc", "Cc") and body) or (name in ("X-To", "To") and _addressees(body) > 1):
                return f"empty, but the header names more people: {h!r}"
        return None
    filled = [h for h in headers if _header_body(h)]
    return f"null, but the header states it: {filled[0]!r}" if filled else None


def _review_value_problem(field: str, value: Any) -> str | None:
    if field == "intent":
        return None if value in _intent_vocabulary() else f"intent {value!r} is not in the vocabulary"
    if field == "additional_recipients":
        ok = isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
        return None if ok else "additional_recipients must be a list of names"
    if field == "communication_date":
        if value is None:
            return None
        ok = isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
        return None if ok else "communication_date must be YYYY-MM-DD or null"
    return None if value is None or (isinstance(value, str) and value.strip()) else f"{field} must be a name or null"


def review_line_problem(line: Mapping[str, Any]) -> str | None:
    """Why one review line cannot become an overlay label (None: it can)."""
    missing = [k for k in _REVIEW_KEYS if k not in line]
    if missing:
        return f"missing {', '.join(missing)}"
    basis, status = line["basis"], line["status"]
    if basis not in REVIEW_BASES:
        return f"unknown basis {basis!r}"
    want, allowed = REVIEW_BASES[basis]
    if status != want:
        return f"basis {basis} takes status {want}, not {status!r}"
    if line["field"] not in allowed.get(line["doc_class"], ()):
        return f"basis {basis} does not cover {line['doc_class']}.{line['field']}"
    if not isinstance(line["doc_sha256"], str) or not _HEX16.fullmatch(line["doc_sha256"]):
        return "doc_sha256 must be the 16-hex doc_sha of the document text"
    reviewer = line["reviewer"]
    if not isinstance(reviewer, dict) or not reviewer.get("model") or not reviewer.get("role"):
        return "reviewer needs a model and a role"
    if not str(line["note"] or "").strip():
        return "a review needs a note"
    if status == "correction" and line.get("hub_value") in (None, "", [], {}):
        return "a correction needs the hub_value it replaces"
    problem = _review_value_problem(line["field"], line["value"])
    if problem:
        return problem
    if basis == "original_header":
        return _header_problem(line["field"], line["value"], line["evidence"])
    if basis == "review_read_record":
        return _record_quote_problem(line["value"], line["evidence"])
    return None


def _record_quote_problem(value: Any, evidence: Any) -> str | None:
    """A ``review_read_record`` name quotes the text that states it; a null quotes nothing."""
    if not isinstance(evidence, list) or not all(isinstance(q, str) and q.strip() for q in evidence):
        return "a review_read_record label's evidence must be a list of quotes from the text"
    if value is None:
        return "a null review_read_record label quotes nothing" if evidence else None
    if not evidence:
        return "a review_read_record name needs a quote from the text as evidence"
    return None


def read_reviews(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The review lines of ``path`` and what is wrong with them (duplicates included)."""
    return _review_lines(path, _jsonl(path))


def _review_lines(path: Path, records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    lines, problems, seen = [], [], set()
    for n, line in enumerate(records, start=1):
        where = f"{path.name}:{n} {line.get('doc_id')}.{line.get('field')}"
        why = review_line_problem(line)
        if why:
            problems.append(f"{where}: {why}")
            continue
        key = (line["doc_id"], line["field"])
        if key in seen:
            problems.append(f"{where}: a second review of the same label")
            continue
        seen.add(key)
        lines.append(line)
    return lines, problems


def review_label(line: Mapping[str, Any], file: str, previous: Mapping[str, Any] | None) -> dict[str, Any]:
    """The overlay label a review line makes; ``previous`` is the label it replaces, if any."""
    lab: dict[str, Any] = {"value": line["value"], "status": line["status"], "basis": line["basis"],
                           "evidence": line["evidence"], "use_as_truth": True,
                           "review": {"reviewer": line["reviewer"], "note": line["note"], "file": file}}
    if line["status"] == "correction":
        lab["hub_value"] = line.get("hub_value")
    if previous:
        if "review" in previous:  # applied before: keep what the first review replaced
            previous = previous.get("replaced")
        else:
            previous = {k: previous.get(k) for k in ("status", "basis", "value")}
        if previous:
            lab["replaced"] = previous
    return lab


def apply_reviews(records: dict[str, dict[str, Any]], lines: Iterable[Mapping[str, Any]], file: str
                  ) -> tuple[int, list[str]]:
    """Put the review lines' labels into ``records`` (``{doc_id: record}``, changed in place).

    A line replaces any label of its field; a document without a record gets one. A record whose
    text hash differs from the line's is refused (the review read other text). Returns the number
    of labels added or changed, and the problems.
    """
    changed, problems = 0, []
    for line in lines:
        doc = line["doc_id"]
        rec = records.get(doc)
        if rec is None:
            rec = records[doc] = {"doc_id": doc, "doc_class": line["doc_class"], "doc_subclass": line["doc_subclass"],
                                  "doc_sha256": line["doc_sha256"], "labels": {}, "source": {"review": file}}
        if rec.get("doc_sha256") != line["doc_sha256"] or rec.get("doc_class") != line["doc_class"]:
            problems.append(f"{doc}.{line['field']}: the review read other text or another class than the overlay record")
            continue
        old = rec["labels"].get(line["field"])
        lab = review_label(line, file, old)
        if lab != old:
            rec["labels"][line["field"]] = lab
            changed += 1
    return changed, problems


def retire_reviews(records: dict[str, dict[str, Any]], lines: Iterable[Mapping[str, Any]]) -> list[str]:
    """Drop the reviewed labels that no line of the review set makes any more (``records`` changed in place).

    A label whose review line was removed is retired: it leaves the overlay, so the Hub value (or
    near-gold) applies again. A record the review created that is left with no labels goes too.
    Returns one note per retired label; a label it had replaced comes back only with a rebuild.
    """
    keep = {(line["doc_id"], line["field"]) for line in lines}
    notes = []
    for doc in sorted(records):
        rec = records[doc]
        for field in sorted(f for f, lab in rec["labels"].items() if "review" in lab and (doc, f) not in keep):
            lab = rec["labels"].pop(field)
            was = lab.get("replaced")
            notes.append(f"{doc}.{field}: retired (no review line makes it)"
                         + (f"; it had replaced a {was.get('status')} label, which build restores" if was else ""))
        if not rec["labels"] and "review" in (rec.get("source") or {}):
            del records[doc]
    return notes


def reviews_reflected(overlay: Mapping[str, Mapping[str, Any]], lines: Iterable[Mapping[str, Any]]) -> list[str]:
    """Review lines whose label is missing from, or differs in, the overlay."""
    out = []
    for line in lines:
        lab = ((overlay.get(line["doc_id"]) or {}).get("labels") or {}).get(line["field"])
        if not lab or "review" not in lab or any(lab.get(k) != line[k] for k in ("value", "status", "basis", "evidence")):
            out.append(f"{line['doc_id']}.{line['field']}: the review is not applied (run scripts/interim_labels.py review)")
    return out


def labels_for(row: Mapping[str, Any], fields: Mapping[str, Any], gate: Mapping[str, Any],
               truth: Mapping[str, bool]) -> dict[str, dict[str, Any]]:
    """The overlay labels of one document.

    ``fields``: the specialist's extraction; ``gate``: the gate answer (``verdict``,
    ``field_support``); ``truth``: the dojo per-field truth of the extraction (labelled fields).
    """
    cls = str(row.get("expected_doc_class") or "")
    sub = str(row.get("expected_subclass") or "")
    exp = _expected(row)
    text = str(row.get("doc_text") or "")
    support = gate.get("field_support") or {}
    # The verdict is answered apart from the field rules and separates poorly (gate vetting);
    # the field's own support decides. Only a human_review verdict (unreadable / wrong class)
    # blocks every label of the document.
    accepted = gate.get("verdict") != "human_review"
    out: dict[str, dict[str, Any]] = {}
    if cls == "insurance_claim" and sub in CMS_TABLES:
        out["cms_source_table"] = {"value": sub, "status": "derived", "basis": "cms_subclass", "hub_value": None}
    if cls in SUBCLASS_FIELDS and sub and not hub_has(exp, SUBCLASS_FIELDS[cls]):
        out[SUBCLASS_FIELDS[cls]] = {"value": derived_value(cls, sub), "status": "derived", "basis": "hub_subclass",
                                     "hub_value": None}
    for field, s in sorted(support.items()):
        if field in out:  # derived from the row: the extraction never overrides it
            continue
        value = fields.get(field)
        s = float(s)
        if field in GAP_FIELDS.get(cls, ()) and not hub_has(exp, field):
            need = NULL_SUPPORT_MIN if _empty(value) else SUPPORT_MIN
            if accepted and s >= need and grounded(value, text):
                out[field] = {"value": None if _empty(value) else value, "status": "gap_fill",
                              "basis": "gate_accepted_grounded", "support": round(s, 4)}
            continue
        if field not in truth or truth[field] or s < SUPPORT_MIN or not accepted or _empty(value):
            continue
        basis = contract_correction(field, value, exp) if cls == "contract" else None
        hub_value = exp.get(field) if field in exp else None
        if basis:
            out[field] = {"value": value, "status": "correction", "basis": basis, "support": round(s, 4),
                          "hub_value": hub_value}
        else:
            out[field] = {"value": value, "status": "disputed", "basis": "gate_vs_hub", "support": round(s, 4),
                          "hub_value": hub_value,
                          **({"hub_source": exp.get("intent_source")} if field == "intent" and exp.get("intent_source") else {})}
    for lab in out.values():
        lab["use_as_truth"] = lab["status"] in TRUTH_STATUSES
    return out


# ── reading and applying ───────────────────────────────────────────────────


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    path = (root or overlay_dir()) / "MANIFEST.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_overlay(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """``{doc_id: record}`` over every class file the manifest lists."""
    root = root or overlay_dir()
    out: dict[str, dict[str, Any]] = {}
    for name in sorted((load_manifest(root).get("files") or {})):
        for rec in _jsonl(root / name):
            out[rec["doc_id"]] = rec
    return out


def verify(root: Path | None = None, *, reviews: bool = True) -> list[str]:
    """Integrity problems of the committed overlay (empty list: consistent).

    With ``reviews`` (the default) every review file the manifest lists must be unchanged since it
    was applied (its sha256) and every one of its lines must be in the overlay as written.
    """
    return overlay_snapshot(root, reviews=reviews)[2]


def overlay_snapshot(root: Path | None = None, *, reviews: bool = True
                     ) -> tuple[dict[str, dict[str, Any]], str, list[str]]:
    """Records, manifest fingerprint and validation from the same input bytes."""
    root = root or overlay_dir()
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        return {}, "", ["MANIFEST.json: missing"]
    manifest_bytes = manifest_path.read_bytes()
    fingerprint = hashlib.sha256(manifest_bytes).hexdigest()
    man = json.loads(manifest_bytes)
    overlay: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    if man.get("schema") != SCHEMA:
        return {}, fingerprint, [f"MANIFEST.json schema {man.get('schema')!r} is not {SCHEMA!r}"]
    for name, sha in (man.get("files") or {}).items():
        path = root / name
        if not path.exists():
            problems.append(f"{name}: listed in the manifest but missing")
            continue
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != sha:
            problems.append(f"{name}: sha256 differs from the manifest (edited by hand? rebuild with scripts/interim_labels.py build)")
            continue
        for line in blob.decode("utf-8").split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            overlay[rec["doc_id"]] = rec
            for field, lab in (rec.get("labels") or {}).items():
                if lab.get("status") not in STATUSES:
                    problems.append(f"{rec.get('doc_id')}.{field}: unknown status {lab.get('status')!r}")
                if lab.get("use_as_truth") != (lab.get("status") in TRUTH_STATUSES):
                    problems.append(f"{rec.get('doc_id')}.{field}: use_as_truth does not follow its status")
                if "review" in lab and REVIEW_BASES.get(lab.get("basis"), ("",))[0] != lab.get("status"):
                    problems.append(f"{rec.get('doc_id')}.{field}: a reviewed label with basis {lab.get('basis')!r} "
                                    f"cannot have status {lab.get('status')!r}")
    extra = sorted(p.name for p in root.glob("*.jsonl") if p.name not in (man.get("files") or {}))
    problems += [f"{name}: not in the manifest" for name in extra]
    if reviews and not problems:
        problems += _review_file_problems(overlay, man.get("reviews") or [])
    return overlay, fingerprint, problems


def _review_file_problems(overlay: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> list[str]:
    """Each listed review file unchanged since it was applied, and every one of its lines in the overlay."""
    problems: list[str] = []
    for entry in entries:
        path = repo_root() / entry["path"]
        if not path.exists():
            problems.append(f"{entry['path']}: review file listed in the manifest but missing")
            continue
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != entry.get("sha256"):
            problems.append(f"{entry['path']}: changed since it was applied; run scripts/interim_labels.py review")
            continue
        records = [json.loads(line) for line in blob.decode("utf-8").split("\n") if line.strip()]
        lines, bad = _review_lines(path, records)
        problems += bad + reviews_reflected(overlay, lines)
    return problems


def superseded(rows: Iterable[Mapping[str, Any]], overlay: Mapping[str, Mapping[str, Any]] | None = None) -> list[tuple[str, str]]:
    """(doc_id, field) gap fills the given Hub rows now label themselves, or whose text changed."""
    overlay = load_overlay() if overlay is None else overlay
    out: list[tuple[str, str]] = []
    for row in rows:
        rec = overlay.get(row_id(row))
        if not rec:
            continue
        if rec.get("doc_sha256") != row_doc_sha(row):
            out.append((rec["doc_id"], "*"))
            continue
        exp = _expected(row)
        out += [(rec["doc_id"], f) for f, lab in rec["labels"].items() if lab["status"] == "gap_fill" and hub_has(exp, f)]
    return out


def _same_label(a: Any, b: Any) -> bool:
    """Two label values say the same (token-normalised, order-free lists; every empty is alike)."""
    from mailroom_sandbox import gold_labels as gl

    if _empty(a) or _empty(b):
        return _empty(a) and _empty(b)
    return gl._canon(a) == gl._canon(b)


def gold_conflicts(overlay: Mapping[str, Mapping[str, Any]] | None = None,
                   near_gold: Mapping[str, Mapping[str, Any]] | None = None
                   ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Gap fills whose value reviewed gold (the near-gold overlay) contradicts.

    At run time an interim truth label is merged before near-gold and wins over it, so a gate gap
    fill that the reviewed gold catalog labels differently for the same text would replace the
    reviewed value. Returns ``(gone, kept)``: the gate gap fills to drop (reviewed gold then fills
    the field), and the reviewed labels (a review file's own, e.g. ``original_header``) that
    disagree with gold but stay, because their review file decides them.
    """
    from mailroom_sandbox import gold_labels as gl

    overlay = load_overlay() if overlay is None else overlay
    near_gold = gl.load_near_gold() if near_gold is None else near_gold
    gone: list[tuple[str, str]] = []
    kept: list[tuple[str, str]] = []
    for doc, rec in sorted(overlay.items()):
        gold = near_gold.get(doc)
        if not gold or gold.get("doc_sha256") != rec.get("doc_sha256"):
            continue
        for field, lab in sorted(rec["labels"].items()):
            ref = (gold.get("labels") or {}).get(field)
            if lab.get("status") != "gap_fill" or ref is None or _same_label(lab.get("value"), ref.get("value")):
                continue
            (kept if "review" in lab else gone).append((doc, field))
    return gone, kept


def apply_overlay(row: Mapping[str, Any], overlay: Mapping[str, Mapping[str, Any]], *, overlay_sha: str) -> dict[str, Any]:
    """The row with its truth labels merged into its field labels (Hub labels win).

    ``row`` is a prepared row (``id``, ``doc_text``, ``expected_fields``) or a Hub parquet row
    (``document_id``, ``gt_fields``, and ``content_sha256`` or ``doc_text``); the labels are
    written back to the same key, as a JSON string when they were one. A gap fill never
    overrides a Hub label; a correction replaces the Hub value it names. A document whose text
    no longer matches the label's ``doc_sha256`` is left untouched.
    """
    out = dict(row)
    rec = overlay.get(row_id(row))
    if not rec or rec.get("doc_sha256") != row_doc_sha(row):
        return out
    exp = _expected(row)
    pres = _presence(exp)
    applied = []
    for field, lab in sorted(rec["labels"].items()):
        if not lab.get("use_as_truth"):
            continue
        if lab["status"] in ("gap_fill", "derived") and hub_has(exp, field):
            continue
        exp[field] = lab["value"]
        # The Dojo's documented-absence status: a null truth label is "expected empty", not unlabeled
        # (``corporate_record_schema.unlabeled_fields`` drops any other status). ``interim_labels``
        # below records which fields came from the overlay.
        pres[field] = "populated" if lab["value"] is not None else "schema_documented_absence"
        applied.append(field)
    if not applied:
        return out
    if "gt_presence" in exp or pres:
        exp["gt_presence"] = json.dumps(pres, sort_keys=True)
    key = _labels_key(row)
    out[key] = json.dumps(exp, ensure_ascii=False, sort_keys=True) if isinstance(row.get(key), str) else exp
    out["interim_labels"] = {"fields": applied, "overlay_sha256": overlay_sha}
    return out


def apply_overlay_parquet(source: Any, out: Path | str | None = None, *,
                          overlay: Mapping[str, Mapping[str, Any]] | None = None,
                          overlay_sha: str | None = None) -> Any:
    """Apply the overlay to a Hub ``ground_truth`` parquet shard (a path or a ``pyarrow.Table``).

    Returns a table with the shard's columns in the same order and types (``gt_fields`` holds
    the merged labels) plus ``interim_labels``: a JSON string ``{"fields", "overlay_sha256"}``
    on rows that took labels, else null. Rows are matched by ``document_id`` and text hash, as
    in ``apply_overlay``. Without ``overlay`` the committed overlay is used and must pass
    ``verify()``. With ``out`` the table is also written there (never over the source file).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = source if isinstance(source, pa.Table) else pq.read_table(source)
    names = table.column_names
    if not ({"document_id", "id"} & set(names)) or not (set(_LABEL_KEYS) & set(names)):
        raise ValueError("not a ground_truth shard: it needs document_id (or id) and gt_fields (or expected_fields)")
    if "interim_labels" in names:
        raise ValueError("the table already has an interim_labels column: the overlay was applied before")
    if out is not None and not isinstance(source, pa.Table) and Path(out).resolve() == Path(source).resolve():
        raise ValueError("refusing to overwrite the source shard; write the overlaid table elsewhere")
    if overlay is None:
        overlay, overlay_sha, problems = overlay_snapshot()
        if problems:
            raise ValueError(f"interim label overlay is inconsistent: {problems[0]}")
    sha = overlay_sha or ""
    rows = [apply_overlay(r, overlay, overlay_sha=sha) for r in table.to_pylist()]
    marks = [json.dumps(r["interim_labels"], sort_keys=True) if r.get("interim_labels") else None for r in rows]
    schema = table.schema.append(pa.field("interim_labels", pa.string()))
    result = pa.Table.from_pylist([{**{n: r.get(n) for n in names}, "interim_labels": m}
                                   for r, m in zip(rows, marks)], schema=schema)
    if out is not None:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(result, out)
    return result


def overlay_fingerprint(root: Path | None = None) -> str:
    """sha256 of MANIFEST.json (which pins every file's sha): what a run lock records."""
    path = (root or overlay_dir()) / "MANIFEST.json"
    return _sha(path.read_text(encoding="utf-8")) if path.exists() else ""
