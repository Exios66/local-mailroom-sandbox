#!/usr/bin/env python3
"""Stage the merged label repairs as a production-scoring overlay in mailroom-issues ``mailroom_cache``.

Inputs, all on mailroom-dataset v9.3 (Hub ``ff4ca546``):

- ``--builder-dir``: the output of ``build_label_repaired.py`` (sandbox PR #384): the wide label
  CSV, its per-cell ``label_provenance`` CSV, ``field_completeness`` CSV and ``summary`` JSON.
- ``--assist``: an earlier repaired CSV that kept different labels (the full clause phrase for
  ``termination_notice_period``). It only adds evidence-backed terms; it never removes one.
- ``--corpus``: the pinned Hub ``ground_truth`` rows (``sandbox datasets pull``) for grounding.
- ``--builder-script``: the ``build_label_repaired.py`` that wrote ``--builder-dir``. All five
  must be byte-identical to ``--builder-commit``. The four builder files (data) are cached
  under ``builder/`` in the cut, so it restages without the builder's branch; the script is
  code, which mailroom-issues does not hold, so the cut records its sha256 and commit only.

Magnitude repair: the builder's period grammar keeps one word before the digits, so "one hundred
eighty (180) days" is cut to "eighty (180) days". Every staged (non-Hub) value whose number words
disagree with their bracketed digits is rewritten with the full spelling found verbatim in the
document text; one that is not found goes to the review queue unchanged.

Join rules (per cell where the two CSVs differ):

- builder value only: keep it (the builder's guards admitted it).
- ``termination_notice_period``: compare notice terms (operator, magnitude, unit, qualifier).
  A term only the assist value carries is added when it reads as a notice period (an operator,
  or notice / prior / before / advance words around it), is not a cure or breach period, has
  no magnitude the builder already holds, and its phrase occurs verbatim in the document text.
  An assist value with no admissible term goes to the review queue.
- any other field, and duplicate links: keep the builder value and queue the assist value.

Outputs, under ``<out>/v9.3.0/pre-release/v<version>/`` (immutable once written):

- ``master/``: the joined wide CSV, provenance, completeness and summary (with join counts);
- ``overlay/<class>.jsonl``: per document, every label that differs from the Hub v9.3 label
  (``override: true`` when it replaces a populated Hub value): the file deployments pull and
  overlay for production scoring;
- ``builder/``: the builder's four output files, byte for byte;
- ``queues/needs_human.csv`` (unresolved disputes plus queued join cells) and
  ``queues/gold_override_signoff.csv`` (Hub overrides, ``decided_by`` left blank).

    python scripts/stage_label_overlay.py --version 9.3.1-rc.9 \\
        --builder-dir reports/datasets/mailroom-dataset-v9.3-label-repaired \\
        --builder-commit <sha> --builder-script <dir>/build_label_repaired.py \\
        --assist mailroom_dataset_v9.3_label_repaired_copy.csv \\
        --corpus data/cache/Lucius-Morningstar__mailroom-dataset__ff4ca546d434/ground_truth_all.jsonl
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("export_mailroom_cache", HERE / "export_mailroom_cache.py")
emc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emc)

CacheError = emc.CacheError
STEM = "mailroom_dataset_v9.3_label_repaired"
BUILDER_FILES = {"labels": f"{STEM}.csv", "provenance": f"{STEM}_label_provenance.csv",
                 "completeness": f"{STEM}_field_completeness.csv", "summary": f"{STEM}_summary.json"}
BUILDER_SCRIPT = "build_label_repaired.py"
NOTICE = "termination_notice_period"
#: per-document bookkeeping columns: recomputed, never joined
META_COLUMNS = {"fields_targeted", "fields_labeled", "label_completeness", "fields_with_conflict",
                "fields_needs_human"}
LABELED = ("populated", "documented_absence")
ASSIST_SOURCE = "assist_upload"
HUB = "hub_v9.3"
QUEUE_COLUMNS = ("document_id", "doc_class", "field", "reason", "builder_value", "assist_value")
SIGNOFF_COLUMNS = ("document_id", "doc_class", "field", "hub_v9_3_value", "staged_value", "chosen_source",
                   "evidence", "decided_by", "decided_utc")

# Same period grammar as build_label_repaired.py (PERIOD_RX / _notice_terms), so terms compare alike.
PERIOD_RX = re.compile(r"((?:(?:at\s+least|at\s+most|not\s+less\s+than|no\s+less\s+than|not\s+more\s+than|"
                       r"no\s+more\s+than|no\s+later\s+than|a\s+minimum\s+of|a\s+maximum\s+of)\s+)?"
                       r"(?:[a-z\-]+\s+)?\(?\d+\)?\s*(?:calendar\s+|business\s+|working\s+)?"
                       r"(?:days?|months?|years?))\b", re.I)
_NOTICE_AFTER = re.compile(r"^['’]?s?\s*(?:advance|prior|written|notice|notification|before|in\s+advance)\b", re.I)
_NOTICE_BEFORE = re.compile(r"(?:notice|notif\w*|upon|on|giving|providing|given)\s*$", re.I)
_CURE = re.compile(r"\b(?:cure[ds]?|curing|breach\w*|default\w*)\b", re.I)
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())} | {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                                                    "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_DIGITS = re.compile(r"\b([a-z]+(?:-[a-z]+)?)\s+\(?(\d+)\)?\s*(?:calendar\s+|business\s+|working\s+)?(?:days?|months?|years?)\b", re.I)
#: refusals a person should look at; a refused term length next to a builder value is not one
REVIEW_REFUSALS = ("garbled magnitude", "cure or breach period", "not in document text", "same period, other operator")


def garbled(phrase: str) -> bool:
    """A number word that contradicts its digits ("sixty 90 days"); "eighty (180)" is a cut-off
    "one hundred eighty", so a word smaller than the digits only when they are unbracketed."""
    m = _WORD_DIGITS.search(phrase)
    parts = m.group(1).lower().split("-") if m else []
    if not parts or not all(w in _NUMBER_WORDS for w in parts):
        return False
    word, digits = sum(_NUMBER_WORDS[w] for w in parts), int(m.group(2))  # "forty-five" -> 45
    return word != digits and not (f"({m.group(2)})" in phrase and digits % 100 == word)


_UNITS = "zero one two three four five six seven eight nine".split()
_SCALE = r"(?:(?:%s)\s+hundred(?:\s+and)?[\s-]+)" % "|".join(_UNITS)
_CUT = re.compile(r"(?<![a-z-])([a-z]+(?:-[a-z]+)?)(\s*\()(\d+)\)", re.I)


def _words_value(words: str) -> int | None:
    """``"one hundred eighty"`` -> 180; None when a word is not a number word."""
    total, parts = 0, re.split(r"[\s-]+", words.lower().strip())
    for i, w in enumerate(parts):
        if w == "hundred" and i and parts[i - 1] in _UNITS:
            total += _NUMBER_WORDS[parts[i - 1]] * 99  # the unit was already added once
        elif w == "and" and i:
            continue
        elif w in _NUMBER_WORDS:
            total += _NUMBER_WORDS[w]
        else:
            return None
    return total


def repair_magnitudes(value: str, doc_text: str) -> tuple[str, list[str], list[str]]:
    """``value`` with each cut-off number phrase replaced by its full spelling in ``doc_text``.

    Returns the new value, the repairs made and the phrases the text does not ground. A phrase is
    cut when its number words disagree with the bracketed digits ("eighty (180)") and no
    "hundred" precedes it in the value; the fix is the document's own words, never a spelling
    built here.
    """
    repaired, missing, out, last = [], [], [], 0
    for m in _CUT.finditer(value):
        word, digits = _words_value(m.group(1)), int(m.group(3))
        before = re.findall(r"[a-z]+", value[max(0, m.start() - 40):m.start()].lower())
        whole = any(_words_value(" ".join([*before[-k:], m.group(1)])) == digits for k in range(1, min(4, len(before)) + 1))
        if word is None or word == digits or whole:  # "twenty four (24)", "one hundred eighty (180)"
            continue
        rx = re.compile(_SCALE + "?" + re.escape(m.group(1)) + r"\s*\(" + m.group(3) + r"\)", re.I)
        full = next((t.group() for t in rx.finditer(doc_text)
                     if _words_value(t.group()[:t.group().rfind("(")]) == digits), None)
        if full is None:
            missing.append(m.group())
            continue
        out.append(value[last:m.start()] + full)
        last = m.end()
        repaired.append(f"{m.group()} -> {full}")
    return "".join(out) + value[last:], repaired, missing


def notice_term(phrase: str) -> tuple[str, str, str, str]:
    p = phrase.lower()
    op = "exact"
    if re.search(r"at least|(?:not|no) less than|minimum", p):
        op = "minimum"
    elif re.search(r"at most|(?:not|no) more than|maximum|no later than", p):
        op = "maximum"
    qual = re.search(r"\b(business|calendar|working)\b", p)
    return (op, re.search(r"\d+", p).group(), re.search(r"(day|month|year)s?\b", p).group(1),
            qual.group() if qual else "")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _extended_agreement(agreeing: str) -> str:
    """Who agrees with a value the assist join extended: the Hub held only the shorter value, so it no
    longer agrees (the extended cell then enters the overlay and the override sign-off queue)."""
    kept = [s for s in agreeing.split("|") if s and s != HUB]
    return "|".join([*kept, ASSIST_SOURCE])


def assist_notice_terms(assist: str, builder: str, doc_text: str) -> tuple[list[str], list[str]]:
    """Admissible extra notice phrases from ``assist`` and the reasons the rest were refused."""
    # A term is the same when magnitude, unit and qualifier (business/calendar) agree. The same period
    # under another operator ("not less than" vs exact) is refused for review, never dropped silently.
    terms = [notice_term(m.group()) for m in PERIOD_RX.finditer(builder)]
    held = {(t[1], t[2], t[3]) for t in terms}
    ops = {(t[1], t[2], t[3]): t[0] for t in terms}
    text = _norm(doc_text)
    out, refused = [], []
    for segment in assist.split(";"):
        for m in PERIOD_RX.finditer(segment):
            phrase = m.group(1).strip(" ,")
            term = notice_term(phrase)
            key = term[1:]
            if key in held:
                if ops.get(key, term[0]) != term[0]:
                    refused.append(f"same period, other operator: {phrase}")
                continue
            after, before = segment[m.end():m.end() + 30], segment[max(0, m.start() - 25):m.start()]
            if garbled(phrase):
                refused.append(f"garbled magnitude: {phrase}")
            elif _CURE.search(segment):
                refused.append(f"cure or breach period: {phrase}")
            elif not (term[0] != "exact" or _NOTICE_AFTER.search(after) or _NOTICE_BEFORE.search(before)):
                refused.append(f"not a notice period: {phrase}")
            elif _norm(phrase) not in text:
                refused.append(f"not in document text: {phrase}")
            else:
                held.add(key)
                ops[key] = term[0]
                out.append(phrase)
    return out, refused


def _evidence(doc_text: str, phrase: str) -> dict[str, Any] | None:
    m = re.search(r"\s+".join(map(re.escape, phrase.split())), doc_text, re.I)
    return {"start": m.start(), "end": m.end(), "text": doc_text[m.start():m.end()], "source": ASSIST_SOURCE} if m else None


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _csv_text(columns: Iterable[str], rows: Iterable[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _jsonish(value: str) -> Any:
    if value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def completeness_table(prov: list[dict[str, str]], base: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Recompute the builder's per-field completeness from provenance (Hub columns carried over)."""
    cells = collections.defaultdict(list)
    for r in prov:
        cells[(r["doc_class"], r["field"])].append(r)
    out = []
    for b in base:
        rs = cells[(b["doc_class"], b["field"])]
        n = int(b["documents"])
        count = collections.Counter(r["presence"] for r in rs)
        labeled = count["populated"] + count["documented_absence"]
        tops = collections.Counter(r["chosen_source"] for r in rs if r["presence"] in LABELED)
        row = dict(b)
        row.update(labeled_repaired=labeled, populated=count["populated"],
                   documented_absence=count["documented_absence"], unlabeled=count["unlabeled"],
                   disputed_unresolved=count["disputed_unresolved"],
                   completeness_repaired=round(labeled / n, 4) if n else 0.0,
                   conflicts=sum(r["conflict"] == "True" for r in rs),
                   needs_human=sum(r["needs_human"] == "True" for r in rs),
                   top_source=min(tops, key=lambda s: (-tops[s], s)) if tops else "")
        out.append(row)
    return out


def join(builder: dict[str, Any], assist_rows: list[dict[str, str]], texts: dict[str, str]) -> dict[str, Any]:
    """Join the assist CSV into the builder output. Pure: returns new tables and the counts."""
    columns, rows = builder["labels"]
    by_id = {r["document_id"]: dict(r) for r in rows}
    assist = {r["document_id"]: r for r in assist_rows}
    if set(assist) != set(by_id):
        raise CacheError("the assist CSV and the builder CSV do not hold the same documents")
    pcols, prov = builder["provenance"]
    prov = [dict(r) for r in prov]
    pindex = {(r["document_id"], r["field"]): r for r in prov}
    counts: collections.Counter[str] = collections.Counter()
    queue: list[dict[str, str]] = []
    filled_docs: collections.Counter[str] = collections.Counter()
    for doc_id, row in by_id.items():
        a = assist[doc_id]
        for col in columns:
            if col in META_COLUMNS or a.get(col, "") == row[col]:
                continue
            b_val, a_val = row[col], a.get(col, "")
            base = {"document_id": doc_id, "doc_class": row["doc_class"], "field": col,
                    "builder_value": b_val, "assist_value": a_val}
            if not a_val:
                counts["kept_builder_only"] += 1
                continue
            if col == "duplicate_of":
                counts["kept_builder_duplicate_keeper"] += 1  # the builder's keepers are reviewed
                continue
            if col != NOTICE:
                counts["queued_other_field"] += 1
                queue.append({**base, "reason": "assist value differs; builder kept"})
                continue
            extra, refused = assist_notice_terms(a_val, b_val, texts.get(doc_id, ""))
            review = [r for r in refused if r.startswith(REVIEW_REFUSALS)]
            if not b_val and not extra:
                review = refused or ["no notice term found"]
            counts["notice_refused_terms"] += len(refused)
            if not extra:
                if review:
                    counts["queued_notice"] += 1
                    queue.append({**base, "reason": "; ".join(review)})
                else:
                    counts["notice_same_terms"] += 1
                continue
            cell = pindex.get((doc_id, col))
            if cell is None:
                raise CacheError(f"{doc_id}.{col}: no provenance row")
            new = "; ".join([b_val, *extra]) if b_val else "; ".join(extra)
            filled = cell["presence"] not in LABELED
            votes = json.loads(cell["votes"] or "{}")
            votes[ASSIST_SOURCE] = a_val
            evidence = json.loads(cell["evidence"] or "[]") + [e for e in (_evidence(texts[doc_id], p) for p in extra) if e]
            cell.update(value=new, presence="populated", votes=json.dumps(votes, sort_keys=True),
                        evidence=json.dumps(evidence), rule="assist_join",
                        chosen_source=ASSIST_SOURCE if filled or cell["chosen_source"] == HUB else cell["chosen_source"],
                        agreeing_sources=ASSIST_SOURCE if filled else _extended_agreement(cell["agreeing_sources"]))
            row[col] = new
            counts["notice_filled" if filled else "notice_terms_added"] += 1
            filled_docs[doc_id] += filled
            counts["notice_terms_total"] += len(extra)
            if review:
                queue.append({**base, "reason": "partly joined; refused " + "; ".join(review)})
    # Per-document bookkeeping: only a newly filled cell changes the builder's own counts.
    for doc_id, n in filled_docs.items():
        row = by_id[doc_id]
        targeted, labeled = int(row["fields_targeted"] or 0), int(row["fields_labeled"] or 0) + n
        row["fields_labeled"] = str(labeled)
        row["label_completeness"] = str(round(labeled / targeted, 4)) if targeted else row["label_completeness"]
    _, comp = builder["completeness"]
    return {"labels": (columns, [by_id[r["document_id"]] for r in rows]), "provenance": (pcols, prov),
            "completeness": completeness_table(prov, comp), "queue": queue, "counts": dict(sorted(counts.items()))}


def repair_cells(prov: list[dict[str, str]], rows: list[dict[str, str]], texts: dict[str, str]
                 ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """Ground cut-off magnitudes in every staged (non-Hub) populated cell; Hub values stay as they are.

    Returns new provenance and wide rows (the inputs are not mutated), the review-queue entries
    for phrases the text does not ground, and counts.
    """
    prov = [dict(r) for r in prov]
    by_id = {r["document_id"]: dict(r) for r in rows}
    queue, counts = [], collections.Counter()
    for cell in prov:
        if cell["presence"] != "populated" or from_hub(cell) or cell["value"][:1] in "[{":
            continue
        new, repaired, missing = repair_magnitudes(cell["value"], texts.get(cell["document_id"], ""))
        if missing:
            counts["magnitude_unresolved"] += len(missing)
            queue.append({"document_id": cell["document_id"], "doc_class": cell["doc_class"], "field": cell["field"],
                          "reason": "cut-off magnitude not in document text: " + "; ".join(missing),
                          "builder_value": cell["value"], "assist_value": ""})
        if not repaired:
            continue
        counts["magnitude_cells_repaired"] += 1
        counts["magnitude_phrases_repaired"] += len(repaired)
        row = by_id[cell["document_id"]]
        if row.get(cell["field"]) != cell["value"]:
            raise CacheError(f"{cell['document_id']}.{cell['field']}: wide CSV and provenance disagree")
        row[cell["field"]] = new
        cell.update(value=new, rule=f"{cell['rule']}+magnitude_grounded")
    return prov, [by_id[r["document_id"]] for r in rows], queue, dict(sorted(counts.items()))


VALIDATION_SOURCE = "validation_review"  # a hand-read correction (CORRECTIONS_FILE)
VALIDATION_RULE = "validation_rule"  # a deterministic repair of a Hub value (queued for sign-off)
CORRECTIONS_FILE = "data/labels/review/validation_corrections.jsonl"
HEADER_SOURCE = "data/labels/interim/correspondence.jsonl"
HEADER_COLUMNS = ("document_id", "filename", "maildir_file", "fields", "header_lines")
CORRECTION_PRESENCE = ("populated", "documented_absence", "unlabeled")
#: Enron maildir folder names the Hub keywords picked up from the file path, not the message.
MAILDIR_FOLDERS = frozenset({"all_documents", "deleted_items", "sent_items", "sent", "_sent_mail", "inbox",
                             "discussion_threads", "notes_inbox", "calendar", "contacts", "archiving"})
_ISO_TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d")
_ISO_DATE = re.compile(r"\d{4}-\d\d-\d\d")
_JURIS_PREFIX = (r"(?:State|Commonwealth|Province|Republic|Kingdom|People'?s\s+Republic|Hong\s+Kong\s+Special"
                 r"\s+Administrative\s+Region|Federal\s+Republic|Canton|District)\s+of\s+(?:the\s+)?")
_JURIS = re.compile(r"(?i:\blaws?\s+(?:in\s+force\s+in|of)\s+(?:the\s+)?)(?P<j>(?i:" + _JURIS_PREFIX
                    + r")?[A-Z][A-Za-z.\-]*(?:[ \t]+(?:and[ \t]+)?[A-Z][A-Za-z.\-]*)*)")
_ALIAS = re.compile(r"[\s,]*\((?:[^()]*?)[\"“”][^()]*\)[\s,]*$")
#: a ``parties`` element that is a defined-term clause, not a party ("each referred to as a Party").
_PARTY_JUNK = re.compile(r"referred\s+to|hereinafter|hereafter|collectively|individually|separately|"
                         r"\beach,?\s+(?:as\s+)?an?\b|together\s+with|^\(|^[\"“]|^the\s+[\"“]|\bpart(?:y|ies)\b[\"”]|"
                         r"^if\s+you\b|^on\s+behalf\b|^_{3,}|\bis\s+executing\b|^.{140,}$", re.I)
#: a capture that is only a corporate suffix ("Inc.", "Holdings, Inc."): the name itself was lost.
_SUFFIX_ONLY = re.compile(r"^(?:the\s+)?(?:(?:holdings?|group|inc|incorporated|llc|l\.l\.c|ltd|limited|plc|corp|co"
                          r"|lp|l\.p|n\.v|b\.v|s\.a|ag|gmbh)\.?,?\s*)+$", re.I)
#: a bare defined term standing in for a party ("the Company"), not the party's name.
_GENERIC_PARTY = re.compile(r"^(?:the\s+)?(?:company|corporation|holding\s+company)$", re.I)
#: words before a party's name that describe it, not name it: "the retention of Keefe, Bruyette & Woods, Inc."
#: and "Subsidiary of Standard Industries Holdings Inc., and Gibraltar Merger Sub Inc." (a run-on
#: from the previous party's description); the name that follows is kept.
_NAME_LEAD_IN = re.compile(r"^(?:the\s+)?(?:retention|engagement)\s+of\s+(?=[A-Z0-9])|"
                           r"^(?i:(?:an?\s+|the\s+)?(?:(?:direct|indirect)\s+)?(?:wholly[- ]owned\s+)?"
                           r"subsidiary\s+of\s+)[^,]+,\s+and\s+(?=[A-Z0-9])|"
                           # a role label before the name: "The buyer/End-User: Shenzhen LOHAS ... Co., Ltd."
                           r"^(?i:the\s+[a-z][a-z/\- ]{1,30}:\s+)(?=[A-Z0-9])")
#: party-role words. CUAD's Parties spans list a party's defined role ("Licensor", "the Customer")
#: as its own answer, but ``parties`` holds named parties (Dojo: "full legal name plus parenthetical
#: alias"). Dojo's scorer credits a few of these as matched; the rest can never match a name.
_ROLE_WORDS = frozenset(
    "shipper sponsor seller buyer company producer reseller licensee licensor party parties transporter customer "
    "client vendor purchaser lender borrower guarantor manufacturer distributor owner operator agent bank developer "
    "provider contractor consultant executive employer employee recipient servicer issuer investor supplier "
    "franchisee franchisor individual parent member partner affiliate sales end-user user principal".split())
#: an alternative name of a listed party, not another party ("d/b/a Recreation USA", "formerly known as ...").
_PARTY_ALIAS_CLAUSE = re.compile(r"^(?:d/b/a|d\.b\.a\.?|dba|a/k/a|a\.k\.a\.?|aka|f/k/a|f\.k\.a\.?|fka|f/s/o|"
                                 r"formerly\s+known\s+as|also\s+known\s+as|doing\s+business\s+as)(?=\W)", re.I)
#: a description of who a party is, not its name ("an individual", "the Reseller named above").
_PARTY_DESCRIPTOR = re.compile(r"^(?-i:your|you|our|its|each)\b|^persons?\s+and\s+entities\b|^together\b|"
                               r"^an?\s+(?:individual|subsidiary\s+of)\b|\b(?:named\s+above|identified\s+on|"
                               r"specified\s+as|listed\s+on|hereto|debtors\s+in\s+possession)\b", re.I)
#: fields that hold party, advisor or counsel names (the lead-in trim applies to these only)
ENTITY_FIELDS = frozenset({"parties", "acquirer", "target", "merger_sub", "financial_advisors", "legal_counsel",
                           "signatories"})
INTERIM_AUDIT = "data/labels/review/interim_audit.jsonl"
DISPUTED = "disputed_unresolved"
#: words that end a jurisdiction run read from an upper-case clause ("STATE OF DELAWARE WITHOUT ...")
_JURIS_STOP = frozenset("without shall or in applicable to excluding except as which that for regardless having "
                        "arising apply governing notwithstanding its their any with by under other than".split())
_ADJ_LAW = re.compile(r"\b(?:with|under|by)\s+(?:the\s+)?((?:[A-Z][\w.]*\s+){0,2}[A-Z][\w.]*)\s+[Ll]aws?\b")
_NAMED_JURIS = re.compile(r"\b(?:State|Commonwealth|Province|Republic)\s+of\s+(?:the\s+)?[A-Z][A-Za-z.\-]*(?:[ \t]+[A-Z][A-Za-z.\-]*)*",
                          re.I)


def _field_types() -> dict[str, dict[str, str]]:
    from mailroom_sandbox import dojo_source

    dojo_source.choose()
    from llm_dojo_scoring.schemas.doc_classes import DOC_CLASSES

    return {k: dict(v.fields) for k, v in DOC_CLASSES.items()}


def _canonical_family(value: str) -> str:
    from mailroom_sandbox import dojo_source

    dojo_source.choose()
    from llm_dojo_scoring.schemas.scored_enums import canonical_label

    return canonical_label("contract", "cuad_family", value) or value


def _find(doc_text: str, quote: str) -> re.Match[str] | None:
    return re.search(r"\s+".join(map(re.escape, quote.split())), doc_text, re.I)


def jurisdiction(value: str, doc_text: str) -> str | None:
    """The jurisdiction a governing-law clause names ("State of New York"), if the text states it."""
    probe = value
    if not value.rstrip().endswith((".", ";", ")")):
        # The builder cuts long clauses ("... the laws of the St"): finish the sentence from the text.
        m = _find(doc_text, value.strip())
        if m:
            probe = value.rstrip() + doc_text[m.end():m.end() + 240].split(".")[0]
    probe = re.sub(r"\s+", " ", probe)
    probe = probe.title().replace("'S ", "'s ") if probe.isupper() else probe
    found = [_trim_juris(m.group("j")) for m in _JURIS.finditer(probe)]
    found = [j for j in found if j and j.lower() not in {"state", "commonwealth", "province"}]
    if not found:
        # "...the laws, other than choice of law rules, of the state of Florida": one named state.
        named = {re.sub(r"\s+", " ", m.group(0)).rstrip(".") for m in _NAMED_JURIS.finditer(probe)}
        named = {_trim_juris(j) for j in named}
        found = [named.pop()] if len(named) == 1 else []
    if not found:
        # "... in accordance with Swiss law" / "English law" / "New York law": the text's own phrase.
        adj = _ADJ_LAW.search(probe)
        found = [f"{adj.group(1)} law"] if adj else []
    found = [j for j in found if len(j.replace(".", "")) >= 3]
    if not found:
        return None
    best = next((j for j in found if " of " in j), found[0])
    best = re.sub(r"\b(Of|The|And)\b", lambda w: w.group(1).lower(), best)
    best = re.sub(r"(?<![\w'’])(?!of\b|the\b|and\b|law\b)([a-z])", lambda w: w.group(1).upper(), best)
    return best if _find(doc_text, best) else None


def _trim_juris(j: str) -> str:
    """Cut a jurisdiction run at the first clause word ("State of Delaware Without Giving ...")."""
    out = []
    for w in j.rstrip(".,;").split():
        if w.lower() in _JURIS_STOP:
            break
        out.append(w)
    while out and out[-1].lower() in {"and", "of", "the"}:
        out.pop()
    return " ".join(out).rstrip(".,;")


def clean_parties(items: list[Any], doc_text: str = "") -> list[Any]:
    """``parties`` without defined-term clauses and trailing alias parentheticals, de-duplicated.

    A sentence period the builder kept ("Synaptics Incorporated.") goes when the text has the name
    without it and never with it.
    """
    out, seen = [], set()
    for v in items:
        if isinstance(v, str):
            v = _ALIAS.sub("", trim_name(v)).strip()
            if not v or _PARTY_JUNK.search(v) or _PARTY_ALIAS_CLAUSE.match(v) or not_a_party(v):
                continue
            if doc_text and v.endswith(".") and not _find(doc_text, v) and _find(doc_text, v[:-1]):
                v = v[:-1]
        k = re.sub(r"\s+", " ", str(v)).strip().lower()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def trim_name(value: str) -> str:
    """A party name without a describing lead-in ("the retention of X" is X); else ``value``."""
    v = value.strip()
    m = _NAME_LEAD_IN.match(v)
    return v[m.end():] if m else value


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
#: text just before a date that makes it an effective date ("effective as of", "Effective Date: ")
_EFFECTIVE_LEAD = re.compile(r"effective(?:\s+date)?\s*(?:as\s+of|on|is|shall\s+be|:)?\s*(?:the\s+)?$", re.I)
#: text just before a date that makes it the signing date ("is made and entered into as of", "dated")
_SIGNING_LEAD = re.compile(r"(?:dated|made|entered\s+into|executed)(?:\s+(?:and\s+entered\s+into|as\s+of|on|this))*"
                           r"(?:\s+the)?(?:\s+\w+\s+day\s+of)?\s*$", re.I)


def signing_date_only(value: str, doc_text: str) -> bool:
    """True when a merger ``effective_date`` is the agreement's signing date and nothing more.

    The date must appear in the text as a signing date (after "dated" / "entered into as of", or
    in the title block), and never as an effective date ("effective as of <date>"). Dojo's
    merger schema and the extraction gate leave ``effective_date`` empty in that case: only a
    stated calendar Effective Date counts, and the closing is the defined Effective Time.
    """
    if not _ISO_DATE.fullmatch(value) or not _valid_date(value):
        return False
    y, m, d = (int(x) for x in value.split("-"))
    pat = re.compile(rf"{_MONTHS[m - 1]}\s+{d}(?:st|nd|rd|th)?,?\s+{y}\b", re.I)
    hits = list(pat.finditer(doc_text))
    if not hits:
        return False
    before = [re.sub(r"\s+", " ", doc_text[max(0, h.start() - 80):h.start()]) for h in hits]
    if any(_EFFECTIVE_LEAD.search(b) for b in before):
        return False
    return any(_SIGNING_LEAD.search(b) for b in before) or hits[0].start() < 1500


def role_only(value: str) -> bool:
    """A capture of one to three party-role words ("Licensor", "the Customer", "The seller:")."""
    words = re.findall(r"[a-z][a-z\-]*", value.lower())
    if words[:1] and words[0] in {"the", "a", "an"}:
        words = words[1:]
    return 1 <= len(words) <= 3 and all(w in _ROLE_WORDS or w.removesuffix("s") in _ROLE_WORDS for w in words)


def not_a_name(value: str) -> bool:
    """A party or company capture that names no one: a bare corporate suffix or defined term."""
    v = value.strip()
    return bool(_SUFFIX_ONLY.match(v) or _GENERIC_PARTY.match(v))


def not_a_party(value: str) -> bool:
    """``not_a_name``, or a party-role word or a description of the party (party fields only)."""
    v = value.strip()
    return not_a_name(v) or role_only(v) or bool(_PARTY_DESCRIPTOR.search(v))


SIGNING_KIND = "signing_date_as_effective_date"


def signing_date_policy(path: Path) -> str | None:
    """The owner's answer on merger signing dates, read from the interim audit's rows of that kind.

    ``"pending"`` while any row still says ``owner_decides``; ``"clear"`` when the rows say the
    gate rule stands (signing dates are not effective dates); ``"keep"`` when signing dates are
    accepted; ``None`` when the audit has no such rows.
    """
    if not path.exists():
        return None
    actions = {r.get("action") for r in (json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x.strip())
               if r.get("kind") == SIGNING_KIND}
    if not actions:
        return None
    if "owner_decides" in actions:
        return "pending"
    return "clear" if actions <= {"clear"} else "keep"


def open_decisions(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Interim-audit rows the owner has not decided yet (``action: owner_decides``), by cell."""
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {(r["doc_id"], r["field"]): r for r in rows if r.get("action") == "owner_decides"}


def keyword_metadata(values: list[Any], filename: str) -> list[Any]:
    """The Hub keywords without maildir path parts and timestamps (they come from the file, not the text)."""
    user = filename.split("/", 1)[0] if "/" in filename else ""
    return [v for v in values if not (isinstance(v, str) and (_ISO_TS.match(v) or v in MAILDIR_FOLDERS
                                                               or (user and v == user)))]


def read_corrections(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        c = json.loads(line)
        key = (c["doc_id"], c["field"])
        if key in out or c.get("presence") not in CORRECTION_PRESENCE or not c.get("note"):
            raise CacheError(f"{path}:{n}: duplicate key, bad presence or missing note")
        if c["presence"] == "populated" and not (c.get("value") not in (None, "") and c.get("quote")):
            raise CacheError(f"{path}:{n}: a populated correction needs a value and a quote")
        out[key] = c
    return out


def header_restoration(path: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Per correspondence document, the original email header lines its labels quote.

    The corpus text lost these headers in cleaning; the labels keep the header values, and this
    list is what the next dataset release needs to put the headers back into the text.
    """
    names = {r["document_id"]: r["filename"] for r in rows}
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        lines, files, fields = [], set(), []
        for field, lab in sorted(rec["labels"].items()):
            if lab.get("basis") != "original_header":
                continue
            fields.append(field)
            for e in lab.get("evidence") or []:
                files.add(e.get("file", ""))
                if e.get("header") and e["header"] not in lines:
                    lines.append(e["header"])
        if fields and rec["doc_id"] in names:
            out.append({"document_id": rec["doc_id"], "filename": names[rec["doc_id"]],
                        "maildir_file": "|".join(sorted(f for f in files if f)), "fields": "|".join(fields),
                        "header_lines": json.dumps(lines, ensure_ascii=False)})
    return sorted(out, key=lambda r: r["document_id"])


def validate_repairs(prov: list[dict[str, str]], rows: list[dict[str, str]], texts: dict[str, str],
                     corrections: dict[tuple[str, str], dict[str, Any]], *,
                     shas: dict[str, str] | None = None,
                     decisions: dict[tuple[str, str], dict[str, Any]] | None = None,
                     signing_policy: str | None = None,
                     ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """The validation pass over the merged cells (inputs are not mutated).

    - a hand-read correction (``CORRECTIONS_FILE``) replaces the cell; every correction requires
      a review note, and a populated correction additionally requires a quote in the text;
    - Hub ``keywords``: maildir folders, the mailbox owner and timestamps are dropped (a Hub override);
    - staged (non-Hub) cells: a ``date`` that is not a whole calendar date becomes unlabeled and is
      queued; ``cuad_family`` takes Dojo's canonical key; a ``governing_law`` clause becomes the
      jurisdiction it names (queued when the text does not state one); entity lists lose duplicates,
      and ``parties`` lose defined-term clauses, trailing alias parentheticals, bare defined terms
      ("the Company") and suffix-only captures ("Inc."); a ``name`` field holding only such a
      capture becomes unlabeled and is queued; party, advisor and counsel names lose a describing
      lead-in ("the retention of X", "Subsidiary of Y, and X" become X), the evidence quote kept;
      ``parties`` also lose role words ("Licensor", "the Customer"), descriptions ("an individual")
      and alias clauses ("d/b/a ..."), and a ``name`` field holding one is unlabeled and queued;
    - a merger ``effective_date`` that is only the signing date (``signing_date_only``) follows the
      owner's answer in the interim audit (``signing_policy``): held as ``disputed_unresolved`` and
      queued while it is pending, a documented absence once the gate rule is confirmed (Dojo's
      schema keeps it empty unless a calendar Effective Date is stated), unchanged if accepted;
    - an interim value whose audit still waits for the owner (``decisions``) is not truth yet: it
      becomes ``disputed_unresolved`` and is queued;
    - documents with the same text (``shas``) that hold different staged values for a field become
      ``disputed_unresolved`` and are queued, since one text cannot have two answers.
    Hub-backed cells are not date-, name- or clause-checked: only their ``keywords`` are cleaned.
    """
    types = _field_types()
    prov = [dict(r) for r in prov]
    by_id = {r["document_id"]: dict(r) for r in rows}
    queue: list[dict[str, str]] = []
    counts: collections.Counter[str] = collections.Counter()
    used: set[tuple[str, str]] = set()

    def update(cell: dict[str, str], value: str, presence: str, rule: str, source: str | None = None,
               evidence: list[dict[str, Any]] | None = None) -> None:
        row = by_id[cell["document_id"]]
        was = cell["presence"] in LABELED
        if source:
            votes = json.loads(cell["votes"] or "{}")
            votes[source] = _jsonish(value) if presence == "populated" else None
            cell.update(chosen_source=source, agreeing_sources=source, votes=json.dumps(votes, sort_keys=True),
                        agreement="single_source", conflict="False", needs_human="False")
        if evidence is not None:
            cell["evidence"] = json.dumps(evidence, ensure_ascii=False)
        cell.update(value=value, presence=presence, rule=f"{cell['rule']}+{rule}")
        row[cell["field"]] = value
        delta = (presence in LABELED) - was
        if delta:
            targeted = int(row["fields_targeted"] or 0)
            labeled = int(row["fields_labeled"] or 0) + delta
            row["fields_labeled"] = str(labeled)
            row["label_completeness"] = str(round(labeled / targeted, 4)) if targeted else row["label_completeness"]
        counts[rule] += 1

    def enqueue(cell: dict[str, str], reason: str) -> None:
        queue.append({"document_id": cell["document_id"], "doc_class": cell["doc_class"], "field": cell["field"],
                      "reason": reason, "builder_value": cell["value"], "assist_value": ""})

    decisions = decisions or {}
    for cell in prov:
        key = (cell["document_id"], cell["field"])
        text = texts.get(cell["document_id"], "")
        c = corrections.get(key)
        if c is not None:
            used.add(key)
            ev = None
            if c["presence"] == "populated":
                m = _find(text, c["quote"])
                if m is None:
                    raise CacheError(f"{CORRECTIONS_FILE}: {key} quote is not in the document text")
                ev = [{"start": m.start(), "end": m.end(), "text": text[m.start():m.end()], "source": VALIDATION_SOURCE}]
            value = c["value"] if isinstance(c.get("value"), str) else (
                json.dumps(c["value"], ensure_ascii=False) if c["presence"] == "populated" else "")
            update(cell, value, c["presence"], "validation_review", VALIDATION_SOURCE, ev if ev is not None else [])
            continue
        if cell["presence"] != "populated":
            continue
        ftype = types.get(cell["doc_class"], {}).get(cell["field"], "")
        d = decisions.get(key)
        if (d is not None and cell["chosen_source"].startswith("interim")
                and _jsonish(cell["value"]) == d.get("value")):
            enqueue(cell, f"interim audit awaits the owner ({d.get('kind', 'policy')}): {d.get('reason', '')}")
            update(cell, cell["value"], DISPUTED, "owner_decision_pending")
            continue
        if from_hub(cell):
            if cell["field"] == "keywords" and cell["value"][:1] == "[":
                old = json.loads(cell["value"])
                new = keyword_metadata(old, by_id[cell["document_id"]].get("filename", ""))
                if new != old:
                    update(cell, json.dumps(new, ensure_ascii=False) if new else "",
                           "populated" if new else "documented_absence", "keyword_metadata_stripped", VALIDATION_RULE)
            continue
        value = cell["value"]
        if cell["field"] in ENTITY_FIELDS and cell["field"] != "parties":
            if ftype == "name" and trim_name(value) != value:
                value = trim_name(value)
                update(cell, value, "populated", "name_lead_in_trimmed")
            elif ftype.startswith("entity_list") and value[:1] == "[":
                items = json.loads(value)
                trimmed = [trim_name(v) if isinstance(v, str) else v for v in items]
                if trimmed != items:
                    value = json.dumps(trimmed, ensure_ascii=False)
                    update(cell, value, "populated", "name_lead_in_trimmed")
        if (signing_policy in {"pending", "clear"} and cell["doc_class"] == "merger_agreement"
                and cell["field"] == "effective_date" and signing_date_only(value, text)):
            if signing_policy == "clear":
                update(cell, "", "documented_absence", "signing_date_not_effective_date", VALIDATION_RULE, [])
            else:
                enqueue(cell, "the value is the signing date; whether a signing date counts as the effective date "
                              "awaits the owner (interim audit kind signing_date_as_effective_date)")
                update(cell, value, DISPUTED, "signing_date_pending_owner")
        elif ftype == "date" and not (_ISO_DATE.fullmatch(value) and _valid_date(value)):
            enqueue(cell, "not a whole calendar date (the text states only part of it); left unlabeled")
            update(cell, "", "unlabeled", "partial_date_unlabeled")
        elif cell["field"] == "cuad_family":
            new = _canonical_family(value)
            if new != value:
                update(cell, new, "populated", "cuad_family_canonical")
        elif cell["field"] == "governing_law" and (len(value) > 40 or re.search(r"\blaws?\b", value, re.I)):
            new = jurisdiction(value, text)
            if new:
                update(cell, new, "populated", "governing_law_jurisdiction")
            else:
                counts["governing_law_clause_queued"] += 1
                enqueue(cell, "governing-law clause names no jurisdiction the text states; kept as is")
        elif ftype == "name" and (not_a_party(value) if cell["field"] in ENTITY_FIELDS else not_a_name(value)):
            enqueue(cell, "capture is only a corporate suffix or defined term, not a name; left unlabeled")
            update(cell, "", "unlabeled", "name_capture_unlabeled")
        elif ftype.startswith("entity_list") and value[:1] == "[":
            items = json.loads(value)
            if cell["field"] == "parties":
                new = clean_parties(items, text)
                if not new:
                    enqueue(cell, "every parties element is a defined-term clause; left unlabeled")
                    update(cell, "", "unlabeled", "parties_cleaned")
                elif new != items:
                    update(cell, json.dumps(new, ensure_ascii=False), "populated", "parties_cleaned")
                continue
            seen, dedup = set(), []
            for v in items:
                k = re.sub(r"\s+", " ", str(v)).strip().lower()
                if k not in seen:
                    seen.add(k)
                    dedup.append(v)
            if dedup != items:
                update(cell, json.dumps(dedup, ensure_ascii=False), "populated", "entity_list_deduplicated")
    missing = set(corrections) - used
    if missing:
        raise CacheError(f"{CORRECTIONS_FILE}: no merged cell for {sorted(missing)[:3]}")
    if shas:
        same_text: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
        for cell in prov:
            sha = shas.get(cell["document_id"])
            if sha and cell["presence"] in LABELED:
                same_text[(sha, cell["field"])].append(cell)
        for cells in same_text.values():
            if len({(c["presence"], c["value"]) for c in cells}) < 2:
                continue
            ids = ", ".join(sorted(c["document_id"] for c in cells))
            for cell in cells:
                enqueue(cell, f"documents with the same text disagree on this field ({ids})")
                if from_hub(cell):
                    continue
                update(cell, cell["value"], DISPUTED, "same_text_conflict")
    return prov, [by_id[r["document_id"]] for r in rows], queue, dict(sorted(counts.items()))


def _valid_date(value: str) -> bool:
    import datetime

    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def overlay_records(prov: list[dict[str, str]], shas: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Per class, the labels that differ from Hub v9.3 (the production overlay)."""
    docs: dict[str, dict[str, Any]] = {}
    for r in prov:
        if r["presence"] not in LABELED:
            continue
        if from_hub(r):
            continue
        hub = json.loads(r["votes"] or "{}").get("hub_v9.3")
        rec = docs.setdefault(r["document_id"], {"doc_id": r["document_id"], "doc_class": r["doc_class"],
                                                 "content_sha256": shas.get(r["document_id"], ""), "labels": {}})
        rec["labels"][r["field"]] = {
            "value": _jsonish(r["value"]) if r["presence"] == "populated" else None,
            "presence": r["presence"], "source": r["chosen_source"], "agreement": r["agreement"],
            "override": hub is not None, "evidence": json.loads(r["evidence"] or "[]"),
        }
    out: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for doc_id in sorted(docs):
        out[docs[doc_id]["doc_class"]].append(docs[doc_id])
    return dict(sorted(out.items()))


def from_hub(cell: dict[str, str]) -> bool:
    """The Hub v9.3 label already holds this value (the builder's field-aware vote grouped them)."""
    return HUB in cell["agreeing_sources"].split("|")


def is_override(cell: dict[str, str]) -> bool:
    """The staged label replaces a value the Hub v9.3 labels hold."""
    return not from_hub(cell) and HUB in json.loads(cell["votes"] or "{}")


def signoff_rows(prov: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for r in prov:
        if r["presence"] in LABELED and is_override(r):
            hub = json.loads(r["votes"])[HUB]
            out.append({"document_id": r["document_id"], "doc_class": r["doc_class"], "field": r["field"],
                        "hub_v9_3_value": hub, "staged_value": r["value"], "chosen_source": r["chosen_source"],
                        "evidence": r["evidence"], "decided_by": "", "decided_utc": ""})
    return out


BUILDER_PATH = "reports/datasets/mailroom-dataset-v9.3-label-repaired"


def verify_builder(commit: str, builder_dir: Path, script: Path) -> str:
    """The full builder commit, once every builder file is byte-identical to it there."""
    import subprocess

    def git(*args: str) -> bytes:
        res = subprocess.run(["git", *args], cwd=emc.ROOT, capture_output=True)
        if res.returncode:
            raise CacheError(f"builder commit {commit} is not in this clone (git fetch it first): "
                             f"{res.stderr.decode().strip()}")
        return res.stdout

    full = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    for name, path in [*((n, builder_dir / n) for n in BUILDER_FILES.values()), (BUILDER_SCRIPT, script)]:
        if git("show", f"{full}:{BUILDER_PATH}/{name}") != path.read_bytes():
            raise CacheError(f"{path} is not the {name} of builder commit {full[:12]}")
    return full


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(out: Path, version: str, builder_dir: Path, assist: Path, corpus: Path, *, builder_commit: str,
          builder_script: Path) -> dict[str, Any]:
    if out.is_symlink():
        raise CacheError(f"cache output must not be a symlink: {out}")
    out = out.parent.resolve() / out.name
    with emc._cache_lock(out):
        emc._check_output_owner(out)
        return _stage_locked(out, version, builder_dir, assist, corpus,
                             builder_commit=builder_commit, builder_script=builder_script)


def _stage_locked(out: Path, version: str, builder_dir: Path, assist: Path, corpus: Path, *, builder_commit: str,
                  builder_script: Path) -> dict[str, Any]:
    major, minor, _p, _pre = emc.parse_version(version)
    version = version.removeprefix("v")
    rel = Path(f"v{major}.{minor}.0") / "pre-release" / f"v{version}"
    builder = {}
    for key, name in BUILDER_FILES.items():
        path = builder_dir / name
        if not path.exists():
            raise CacheError(f"missing builder output {path}")
        builder[key] = json.loads(path.read_text()) if key == "summary" else _read_csv(path)
    summary = builder["summary"]
    if summary.get("revision") != emc.FAMILY_HF_REVISION:
        raise CacheError(f"builder output is on {summary.get('revision')}, not {emc.FAMILY_HF_REVISION}")
    builder_commit = verify_builder(builder_commit, builder_dir, builder_script)
    texts, shas = {}, {}
    with corpus.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            texts[row["id"]], shas[row["id"]] = row["doc_text"], row["content_sha256"]
    corpus_sha = _sha_bytes(corpus)
    want = summary.get("inputs_sha256", {})
    pinned = next((v for k, v in want.items() if k.endswith("ground_truth_all.jsonl")), None)
    if pinned and pinned != corpus_sha:
        raise CacheError(f"corpus sha256 {corpus_sha[:12]} is not the one the builder read ({pinned[:12]})")
    # The recompute must reproduce the builder's own table before anything is joined.
    _, comp = builder["completeness"]
    again = completeness_table(builder["provenance"][1], comp)
    if _csv_text(comp[0].keys(), comp) != _csv_text(comp[0].keys(), again):
        raise CacheError("completeness recompute does not reproduce the builder's table; refusing to join")
    _, assist_rows = _read_csv(assist)
    joined = join(builder, assist_rows, texts)
    columns, rows = joined["labels"]
    pcols, prov = joined["provenance"]
    prov, rows, magnitude_queue, magnitudes = repair_cells(prov, rows, texts)
    corrections_path = emc.ROOT / CORRECTIONS_FILE
    audit_path = emc.ROOT / INTERIM_AUDIT
    prov, rows, validation_queue, validation = validate_repairs(
        prov, rows, texts, read_corrections(corrections_path), shas=shas, decisions=open_decisions(audit_path),
        signing_policy=signing_date_policy(audit_path))
    headers = header_restoration(emc.ROOT / HEADER_SOURCE, rows)
    disputed = [{"document_id": r["document_id"], "doc_class": r["doc_class"], "field": r["field"],
                 "reason": "disputed_unresolved", "builder_value": r["value"], "assist_value": ""}
                for r in prov if r["needs_human"] == "True"]
    queue = disputed + joined["queue"] + magnitude_queue + validation_queue
    signoff = signoff_rows(prov)
    overlay = overlay_records(prov, shas)
    targeted = sum(1 for r in prov)
    labeled = sum(r["presence"] in LABELED for r in prov)

    target = out / rel
    # Reuse a commit this cut, or another cut, already recorded for the same labels tree.
    manifests = [target / "MANIFEST.json", *sorted(out.glob("v*/pre-release/*/MANIFEST.json"), reverse=True)]
    recorded = next((json.loads(m.read_text())["source"]["labels_commit"] for m in manifests
                     if m.exists() and emc._labels_tree(json.loads(m.read_text())["source"]["labels_commit"])
                     == emc._labels_tree("HEAD")), None)
    labels_commit = emc.labels_commit(prefer=recorded)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "stage"
        (dest / "master").mkdir(parents=True)
        (dest / "overlay").mkdir()
        (dest / "queues").mkdir()
        # The builder's outputs (data, never its code): the cut restages without the builder's branch.
        (dest / "builder").mkdir()
        for name in BUILDER_FILES.values():
            shutil.copyfile(builder_dir / name, dest / "builder" / name)
        name = f"mailroom_dataset_v{version}"
        (dest / "master" / f"{name}_labels.csv").write_text(_csv_text(columns, rows), encoding="utf-8")
        (dest / "master" / f"{name}_label_provenance.csv").write_text(_csv_text(pcols, prov), encoding="utf-8")
        # Recomputed from the validated provenance: validation can unlabel or dispute a cell the
        # join counted as labeled, and the report must agree with the provenance and summary.
        comp_rows = completeness_table(prov, builder["completeness"][1])
        listed = {(r["doc_class"], r["field"]) for r in comp_rows}
        reported = [r for r in prov if (r["doc_class"], r["field"]) in listed]
        if sum(int(r["disputed_unresolved"]) for r in comp_rows) != sum(r["presence"] == DISPUTED for r in reported) \
                or sum(int(r["labeled_repaired"]) for r in comp_rows) != sum(r["presence"] in LABELED for r in reported):
            raise CacheError("field completeness disagrees with the validated provenance; refusing to stage")
        (dest / "master" / f"{name}_field_completeness.csv").write_text(_csv_text(comp_rows[0].keys(), comp_rows),
                                                                         encoding="utf-8")
        new_summary = dict(summary, label_cells_targeted=targeted, label_cells_labeled_repaired=labeled,
                           label_cells_unlabeled=sum(r["presence"] == "unlabeled" for r in prov),
                           label_cells_disputed_unresolved=sum(r["presence"] == DISPUTED for r in prov),
                           assist_join=joined["counts"], magnitude_repair=magnitudes, validation_repair=validation,
                           needs_human=len(queue), builder_outputs_sha256=summary.get("outputs_sha256", {}),
                           outputs_sha256={p.name: _sha_bytes(p) for p in sorted((dest / "master").glob("*.csv"))},
                           chosen_source_counts=dict(collections.Counter(
                               r["chosen_source"] for r in prov if r["presence"] in LABELED).most_common()))
        emc._dump(dest / "master" / f"{name}_summary.json", new_summary)
        for cls, recs in overlay.items():
            (dest / "overlay" / f"{cls}.jsonl").write_text(
                "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        (dest / "queues" / "needs_human.csv").write_text(_csv_text(QUEUE_COLUMNS, queue), encoding="utf-8")
        (dest / "queues" / "gold_override_signoff.csv").write_text(_csv_text(SIGNOFF_COLUMNS, signoff), encoding="utf-8")
        (dest / "queues" / "header_restoration.csv").write_text(_csv_text(HEADER_COLUMNS, headers), encoding="utf-8")
        manifest = {
            "schema": emc.SCHEMA, "channel": "pre-release", "kind": "production-overlay",
            "version": version, "semver": f"{version}+hf.{emc.FAMILY_HF_REVISION[:8]}",
            "base_release": f"{emc.FAMILY_HF_TAG.removeprefix('v')}.0",
            "base_hf": {"dataset": emc.HF_DEFAULT_REPO, "hf_tag": emc.FAMILY_HF_TAG,
                        "tag_commit": emc.FAMILY_HF_REVISION, "data_revision": emc.FAMILY_HF_DATA_REVISION},
            "status": ("staged for the planned v10 release, not published: overlay/ is applied over the Hub "
                       "v9.3 labels for production scoring; overrides await sign-off in queues/"),
            "source": {"repo": emc.SOURCE_REPO, "labels_commit": labels_commit,
                       "builder": f"{BUILDER_PATH}/{BUILDER_SCRIPT}",
                       "builder_commit": builder_commit, "stager": "scripts/stage_label_overlay.py",
                       "builder_outputs": "builder/"},
            "inputs_sha256": {"builder_labels": _sha_bytes(builder_dir / BUILDER_FILES["labels"]),
                              "builder_provenance": _sha_bytes(builder_dir / BUILDER_FILES["provenance"]),
                              "builder_script": _sha_bytes(builder_script),
                              "assist": _sha_bytes(assist), "corpus": corpus_sha,
                              "validation_corrections": _sha_bytes(corrections_path) if corrections_path.exists() else "",
                              "header_source": _sha_bytes(emc.ROOT / HEADER_SOURCE),
                              "interim_audit": _sha_bytes(audit_path) if audit_path.exists() else ""},
            "coverage": {"cells_targeted": targeted, "cells_labeled": labeled,
                         "completeness": round(labeled / targeted, 4),
                         "cells_labeled_hub_v9_3": summary.get("label_cells_labeled_hub_v9_3")},
            "assist_join": joined["counts"],
            "magnitude_repair": magnitudes,
            "validation_repair": validation,
            "signing_date_policy": signing_date_policy(audit_path) or "",
            "header_restoration": {"documents": len(headers), "file": "queues/header_restoration.csv",
                                   "note": ("correspondence labels that quote the original Enron email header, "
                                            "which the corpus text lost in cleaning; the next release restores "
                                            "these header lines into doc_text")},
            "overlay": {cls: {"documents": len(recs), "labels": sum(len(r["labels"]) for r in recs),
                              "overrides": sum(v["override"] for r in recs for v in r["labels"].values())}
                        for cls, recs in overlay.items()},
            "queues": {"needs_human": len(queue), "gold_override_signoff": len(signoff),
                       "header_restoration": len(headers)},
        }
        manifest["files"] = emc._files(dest)
        emc._dump(dest / "MANIFEST.json", manifest)
        if target.exists():
            same = all((target / p.relative_to(dest)).is_file()
                       and (target / p.relative_to(dest)).read_bytes() == p.read_bytes()
                       for p in dest.rglob("*") if p.is_file())
            if not same:
                raise CacheError(f"v{version} is already cached with different bytes; cut the next rc instead")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dest, target)
    registry = emc.render_registry(out)
    emc._dump(out / "REGISTRY.json", registry)
    (out / "README.md").write_text(emc.render_readme(registry), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(emc.ROOT.parent / "mailroom-issues" / "mailroom_cache"))
    ap.add_argument("--version", required=True)
    ap.add_argument("--builder-dir", type=Path, required=True)
    ap.add_argument("--builder-commit", required=True, help="commit of build_label_repaired.py that wrote --builder-dir")
    ap.add_argument("--builder-script", type=Path, required=True,
                    help="the build_label_repaired.py at --builder-commit (cached in the cut)")
    ap.add_argument("--assist", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        m = stage(Path(args.out), args.version, args.builder_dir, args.assist, args.corpus,
                  builder_commit=args.builder_commit, builder_script=args.builder_script)
    except CacheError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: m[k] for k in ("version", "coverage", "assist_join", "magnitude_repair", "validation_repair",
                                        "overlay", "queues")},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
