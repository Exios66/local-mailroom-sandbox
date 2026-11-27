"""Phase 5 part 2: a deterministic section locator for merger agreements (no model call).

Group reads and the gap retry send only the sections a question or field needs, never the whole
agreement (HF-030). The locator finds:

* **section anchors**: a numbered section title followed by a period (``Section 6.2 No Solicitation.``,
  ``6.2 No Solicitation.``), anywhere in the text. An anchor counts only when at least
  ``_MIN_BODY`` characters of body follow it before the next candidate, which skips a table of
  contents (titles packed together) and keeps cross references (``Section 6.2 of the …``) out,
  because a reference has no capitalised title and period. A title holding an article heading,
  another section number or a page number is a contents line, never an anchor, and a repeated
  section number keeps its longest-bodied occurrence (the body, not its contents entry);
* **defined terms**: ``"<Term>" means`` (straight or curly quotes), running to the next defined
  term or section anchor;
* **the preamble**: the opening of the agreement.

Matching rules (``config/extraction/merger_section_rules.json``) map each MAUD question, from the
Dojo's ``MaudQuestion.sections`` hints, to section keys. An excerpt is capped at
:data:`EXCERPT_CAP` characters, cut at a paragraph boundary and marked. A key the locator cannot
find is absent: the caller keeps the main read's answer and never falls back to the whole document.

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md (part 2).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from mailroom_sandbox import merger_tables
from mailroom_sandbox.paths import repo_root

RULES_PATH = repo_root() / "config" / "extraction" / "merger_section_rules.json"
EXCERPT_CAP = 24_000
PREAMBLE_CHARS = 10_000
_MIN_BODY = 400
_CUT_MARK = "\n[excerpt cut at {cap} characters]\n"

_ANCHOR = re.compile(
    r"(?:(?<=\s)|^)(?:(?:SECTION|Section|section|§)\s*)?(\d{1,2}\.\d{1,2}[A-Za-z]?)\.?\s+"
    r"([A-Z][^.\n;:]{2,140}?(?:;[^.\n]{1,80}?)*)\.(?=\s)", re.M)
# "<Term>" means … ; words may sit between the term and "means" ("Knowledge" of the Company, with
# respect to any matter, means …), never a quote or a sentence end.
_TERM = re.compile(r"[“\"]\s?([A-Za-z][^”\"\n]{1,80}?)\s?[”\"][^“”\".\n]{0,90}?\s(?:shall\s+)?means?\b")
# A definition in a parenthesis: "(each such event, an "Intervening Event")"; the excerpt starts at
# the sentence that holds it.
_PAREN_TERM = re.compile(r"\((?:[^()\n]{0,60}?\s)?(?:an?|the)\s[“\"]\s?([A-Z][^”\"\n]{1,80}?)\s?[”\"]\)")
_SENTENCE_BACK = 1_500
# A contents entry swallowed into a title: "Further Action 8 ARTICLE II", "Closing 7 Section 1.9 …",
# "Termination Fees 53".
_CONTENTS_TITLE = re.compile(r"\bARTICLE\b|\bArticle\s+[IVXL\d]+\b|\b\d{1,2}\.\d{1,2}\b|\s\d{1,3}$")


@dataclass(frozen=True)
class Excerpt:
    key: str
    heading: str
    start: int
    end: int
    text: str
    cut: bool


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _compiled() -> dict[str, tuple[tuple[re.Pattern[str], ...], frozenset[str]]]:
    """Per key: its title patterns in priority order (listed first wins) and its defined terms."""
    out = {}
    for key, rule in rules()["sections"].items():
        patterns = tuple(re.compile(r"\b(?:" + title + r")", re.I) for title in rule.get("titles") or ())
        out[key] = (patterns, frozenset(t.casefold() for t in rule.get("terms") or ()))
    return out


def _contents_like(title: str) -> bool:
    """A table-of-contents line read as a title: it names an article, another section or a page."""
    return bool(_CONTENTS_TITLE.search(title))


def _anchors(text: str) -> list[tuple[int, str, str]]:
    """Body section anchors ``(position, number, title)``, in order, first occurrence per number.

    A title that reads like a contents line is never an anchor. A later occurrence of a number is a
    cross reference or an exhibit's own numbering, never the body section (calibration mergers), so
    the first occurrence with a body wins.
    """
    # Titles are matched with single ASCII spaces (EDGAR text carries no-break and narrow spaces).
    candidates = [(m.start(), m.group(1), " ".join(m.group(2).split())) for m in _ANCHOR.finditer(text)]
    kept: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for index, (pos, number, title) in enumerate(candidates):
        nxt = candidates[index + 1][0] if index + 1 < len(candidates) else len(text)
        if nxt - pos < _MIN_BODY or number in seen or _contents_like(title):
            continue
        seen.add(number)
        kept.append((pos, number, title))
    return kept


def _terms(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1)) for m in _TERM.finditer(text)]


def _sentence_start(text: str, pos: int) -> int:
    floor = max(0, pos - _SENTENCE_BACK)
    window = text[floor:pos]
    cut = max(window.rfind(". "), window.rfind(".\n"), window.rfind("\n\n"), window.rfind("; "))
    return floor + cut + 2 if cut >= 0 else floor


def _paren_terms(text: str) -> list[tuple[int, str]]:
    return [(_sentence_start(text, m.start()), m.group(1)) for m in _PAREN_TERM.finditer(text)]


def _cap(text: str) -> tuple[str, bool]:
    if len(text) <= EXCERPT_CAP:
        return text, False
    mark = _CUT_MARK.format(cap=EXCERPT_CAP)
    room = EXCERPT_CAP - len(mark)
    head = text[:room]
    cut = max(head.rfind("\n\n"), head.rfind("\n"))
    if cut < room * 0.7:
        cut = head.rfind(". ") + 1 if head.rfind(". ") > room * 0.7 else room
    return head[:cut].rstrip() + mark, True


def _excerpt(key: str, heading: str, text: str, start: int, end: int) -> Excerpt:
    body, cut = _cap(text[start:end])
    return Excerpt(key=key, heading=heading, start=start, end=end, text=body, cut=cut)


def locate(doc_text: str) -> dict[str, Excerpt]:
    """Every rule key the locator finds in ``doc_text`` (absent keys were not found)."""
    text = doc_text or ""
    anchors = _anchors(text)
    terms = _terms(text)
    paren = _paren_terms(text)
    stops = sorted({pos for pos, _, _ in anchors} | {pos for pos, _ in terms} | {len(text)})

    def next_stop(pos: int) -> int:
        return next((s for s in stops if s > pos), len(text))

    found: dict[str, Excerpt] = {}
    for key, (patterns, wanted) in _compiled().items():
        # A key's titles are tried in their listed order: a specific title ("termination fees") wins
        # over a general one ("effect of termination") wherever each sits; within one title, the
        # first anchor in the document.
        for pattern in patterns:
            hit = next(((pos, number, title) for pos, number, title in anchors if pattern.search(title)), None)
            if hit is not None:
                pos, number, title = hit
                nxt = next((p for p, _, _ in anchors if p > pos), len(text))
                found[key] = _excerpt(key, f"Section {number} {title}", text, pos, nxt)
                break
        if key not in found and wanted:
            for pos, term in terms:
                if term.casefold() in wanted:
                    found[key] = _excerpt(key, f"“{term}”", text, pos, next_stop(pos))
                    break
        if key not in found and wanted:
            for pos, term in paren:
                if term.casefold() in wanted:
                    found[key] = _excerpt(key, f"“{term}”", text, pos, next_stop(pos))
                    break
    if text:
        found["preamble"] = _excerpt("preamble", "Preamble", text, 0, min(len(text), PREAMBLE_CHARS))
    return found


def _collect(doc_text: str, wanted: Iterable[tuple[str, list[str]]]) -> tuple[list[Excerpt], list[str]]:
    found = locate(doc_text)
    fallback = rules().get("fallback") or {}
    excerpts: dict[str, Excerpt] = {}
    missed: list[str] = []
    for name, keys in wanted:
        hits = [found[k] for k in keys if k in found]
        if not hits:
            missed.append(name)
        if fallback.get(name):  # an ordered preference: the first key found, not every key
            hits = hits[:1]
        for hit in hits:
            excerpts.setdefault(hit.key, hit)
    return sorted(excerpts.values(), key=lambda e: e.start), missed


def question_excerpts(doc_text: str, questions: Iterable[str]) -> tuple[list[Excerpt], list[str]]:
    """The deduplicated excerpts for ``questions`` (in document order) and the questions with none."""
    table = rules()["questions"]
    return _collect(doc_text, [(q, list(table.get(q) or ())) for q in questions])


def entity_excerpts(doc_text: str, fields: Iterable[str]) -> tuple[list[Excerpt], list[str]]:
    """The excerpts for entity ``fields`` (``merger_tables.entity_sections``) and the fields with none."""
    return _collect(doc_text, [(f, [k] if (k := merger_tables.entity_section(f)) else []) for f in fields])
