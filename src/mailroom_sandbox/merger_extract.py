"""Phase 5 part 2 (HF-030): merger reads after the one whole-document extraction read.

With ``job.merger`` set, the merger specialist's one-call read is followed by (in order):

* **group reads** (``question_groups``): each MAUD question group (:func:`merger_tables.group_questions`)
  is re-asked from its questions' located sections only (:mod:`merger_sections`), with a schema that has
  only ``maud_clauses``, constrained to the group's valid ``"<Question>: <answer>"`` lines. The owning
  read's valid answer wins (:func:`combine`); every entity field comes from the main read alone;
* **one gap retry** (``gap_retry``): the items still missing or invalid (:func:`gap_targets`), asked
  from their sections with only those fields' schema slice and those questions' answer lists;
* without ``gap_retry``, **the dropped consideration field** after a subclass disagreement
  (``subclass_fields``), in one small call from the share-conversion section.

No extra read ever sends the whole document: a question or field whose section the locator cannot
find keeps the main read's answer and is recorded. A failed extra read never fails the document.
Every call goes through the instance's ``_call_structured`` (HF-023's schema swap, the call guard,
the governor and the usage accumulator see it). A multi-window (chunked) read never reaches
``extract``; a field-only retry (HF-027) and a parse error are passed through untouched.

Design: docs/design/specs/2026-11-27-phase5-merger-maud-design.md (parts 1 to 3).
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from mailroom_sandbox import merger_reads, merger_sections, merger_tables

_log = logging.getLogger(__name__)

_FRAME = ("The text below is the relevant sections of this merger agreement, found by their headings "
          "(not the whole agreement). Answer only from these sections.")
_GROUP_TAIL = 'Return JSON with "maud_clauses" only.'
_META = ("confidence", "reasoning")


@dataclass(frozen=True)
class Targets:
    questions: tuple[str, ...]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class Choice:
    """The merger document's subclasses: the sorter's, and the one whose schema was sent (None: fallback)."""

    sorter_subclass: str | None
    schema_subclass: str | None


#: Set by ``subclass_extraction.record_choice`` for the extraction about to run (None: not a merger).
_CHOICE: contextvars.ContextVar[Choice | None] = contextvars.ContextVar("sandbox_merger_choice", default=None)


def note_choice(choice: Choice | None) -> None:
    _CHOICE.set(choice)


# --- Dojo MAUD vocabulary ---------------------------------------------------------------------

def _maud() -> Any:
    merger_tables._ensure_dojo()
    from llm_dojo_scoring.schemas import maud_schema

    return maud_schema


@lru_cache(maxsize=1)
def _names() -> tuple[str, ...]:
    return tuple(q.name for q in _maud().maud_questions())


@lru_cache(maxsize=1)
def _by_length() -> tuple[str, ...]:
    return tuple(sorted(_names(), key=len, reverse=True))


def _question_of(line: Any) -> str | None:
    """The MAUD question a line names, valid or not (longest name first: names can hold a colon)."""
    if not isinstance(line, str):
        return None
    text = line.strip()
    return next((name for name in _by_length() if text.startswith(f"{name}:")), None)


def _parse(lines: Any) -> tuple[dict[str, list[str]], set[str], dict[str, list[str]]]:
    """``(valid lines per question, questions with an invalid line, raw lines per question)``."""
    maud = _maud()
    valid: dict[str, list[str]] = {}
    invalid: set[str] = set()
    raw: dict[str, list[str]] = {}
    for line in lines if isinstance(lines, (list, tuple)) else ():
        parsed = maud.parse_maud_clause(line) if isinstance(line, str) else None
        if parsed:
            question, answer = parsed
            text = maud.maud_clause_line(question, answer)
            bucket = valid.setdefault(question, [])
            if text not in bucket:
                bucket.append(text)
            raw.setdefault(question, []).append(line)
            continue
        question = _question_of(line)
        if question:
            invalid.add(question)
            raw.setdefault(question, []).append(line)
    return valid, invalid, raw


def _sub_token(subclass: str | None) -> str | None:
    try:
        return _maud().consideration_subclass(subclass).token if subclass else None
    except (KeyError, ValueError, TypeError):
        return None


# --- pure pieces ---------------------------------------------------------------------------------

def group_message(handoff: str | None, excerpts: Sequence[merger_sections.Excerpt], subclass: str | None,
                  questions: Sequence[str]) -> str:
    """A section-only read: the main read's handoff opening, the excerpts, then the questions' block."""
    parts = [handoff] if handoff else []
    parts.append(_FRAME)
    parts += [f"=== {e.heading} ===\n{e.text}" for e in excerpts]
    if questions:
        parts.append(_maud().render_maud_question_block(_sub_token(subclass), shape="lines",
                                                        questions=list(questions), chunked=False))
    return "\n\n".join(parts)


def _clauses_property(questions: Sequence[str], *, enum: bool) -> dict[str, Any]:
    items: dict[str, Any] = {"type": "string"}
    if enum:
        maud = _maud()
        items["enum"] = [maud.maud_clause_line(q, c) for q in questions for c in maud.maud_question(q).valid_classes]
    return {"type": "array", "items": items,
            "description": "One '<Question>: <Answer>' line per answered question, the answer copied exactly."}


def group_schema(questions: Sequence[str], *, enum: bool) -> dict[str, Any]:
    return {"type": "object", "properties": {"maud_clauses": _clauses_property(questions, enum=enum)},
            "required": ["maud_clauses"], "additionalProperties": False}


def combine(main: Mapping[str, Any], group_answers: Mapping[str, Sequence[str]], groups: int
            ) -> tuple[list[str], list[str]]:
    """``(maud_clauses, questions left with no valid answer after an invalid one)``.

    Per question, in the Dojo's order: the owning group's valid lines, else the main read's valid
    lines, else the main read's lines unchanged (nothing valid anywhere: the baseline output stands).
    A group's line for a question it does not own is ignored. Lines naming no MAUD question are kept.
    """
    main_lines = main.get("maud_clauses")
    main_valid, main_invalid, main_raw = _parse(main_lines)
    owned_valid: dict[str, list[str]] = {}
    owned_invalid: set[str] = set()
    for key, lines in group_answers.items():
        valid, invalid, _ = _parse(lines)
        owned_valid.update({q: v for q, v in valid.items() if merger_tables.owner(q, groups) == key})
        owned_invalid |= {q for q in invalid if merger_tables.owner(q, groups) == key}
    out: list[str] = []
    still_invalid: list[str] = []
    for question in _names():
        if question in owned_valid:
            out += owned_valid[question]
        elif question in main_valid:
            out += main_valid[question]
        else:
            out += main_raw.get(question, [])
            if question in main_invalid or question in owned_invalid:
                still_invalid.append(question)
    out += [line for line in (main_lines if isinstance(main_lines, (list, tuple)) else ())
            if _question_of(line) is None]
    return out, still_invalid


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def disagreement_fields(extracted: Mapping[str, Any], subclass: str | None, sorter_subclass: str | None
                        ) -> tuple[str, ...]:
    """The fields ``subclass``'s schema dropped when the read's consideration disagrees with the sorter."""
    dropped = merger_tables.dropped_fields(subclass)
    read, sorted_as = _sub_token(extracted.get("merger_consideration")), _sub_token(sorter_subclass)
    if not dropped or read is None or sorted_as is None or read == sorted_as:
        return ()
    if read in _maud().MAUD_CONSIDERATION_EQUIVALENCES.get(sorted_as, ()):
        return ()
    return tuple(sorted(dropped))


def gap_targets(extracted: Mapping[str, Any], subclass: str | None, sorter_subclass: str | None,
                invalid: Sequence[str]) -> Targets:
    """The gap retry's items: invalid answers, unanswered near-universal questions, empty required fields
    valid for ``subclass`` (the schema's subclass; None on a fallback), and a disagreement's dropped field."""
    valid, _, _ = _parse(extracted.get("maud_clauses"))
    wanted, near = set(invalid), merger_tables.near_universal()
    questions = tuple(q for q in _names() if q in wanted or (q in near and q not in valid))
    fields = [f for f in merger_tables.required_entities(subclass) if _empty(extracted.get(f))]
    fields += [f for f in disagreement_fields(extracted, subclass, sorter_subclass) if f not in fields]
    return Targets(questions=questions, fields=tuple(fields))


def merge_answers(lines: Any, new_lines: Any, questions: Sequence[str]) -> list[str]:
    """``lines`` with each of ``questions`` that ``new_lines`` answers validly replaced by those answers."""
    current = list(lines) if isinstance(lines, (list, tuple)) else []
    fresh, _, _ = _parse(new_lines)
    answered = [q for q in questions if q in fresh]
    if not answered:
        return current
    kept = [line for line in current if _question_of(line) not in answered]
    return kept + [line for q in answered for line in fresh[q]]


def retry_schema(base: Mapping[str, Any], fields: Sequence[str], questions: Sequence[str], *, enum: bool
                 ) -> dict[str, Any]:
    """The gap retry's request: the class schema's slice for ``fields`` plus the questions' answer list."""
    from mailroom_sandbox.subclass_extraction import _restrict

    schema = _restrict(base, frozenset(fields))
    schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in _META}
    if questions:
        schema["properties"]["maud_clauses"] = _clauses_property(questions, enum=enum)
    schema["required"] = list(schema["properties"])
    return schema


# --- the calls ------------------------------------------------------------------------------------

_REJECTED = re.compile(r"\b(?:400|422)\b|enum|response_format|json[_ ]schema|schema", re.I)


def _schema_rejected(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status in (400, 422) or bool(_REJECTED.search(str(exc)))


def _ask(agent: Any, message: str, schemas: Sequence[dict[str, Any]]) -> tuple[dict | None, int, str | None]:
    """``(reply, calls made, failure)``; the second schema (unconstrained) only after a schema rejection."""
    calls = 0
    for index, schema in enumerate(schemas):
        calls += 1
        try:
            reply = agent._call_structured(message, json_schema=schema, temperature=0.1, pages=None)
        except Exception as exc:  # noqa: BLE001 — an extra read never fails the document
            if index + 1 < len(schemas) and _schema_rejected(exc):
                continue
            return None, calls, type(exc).__name__
        if not isinstance(reply, dict) or reply.get("_parse_error"):
            return None, calls, "parse_error"
        return reply, calls, None
    return None, calls, "rejected"


def _group_reads(agent: Any, out: dict[str, Any], doc_text: str, cfg: Mapping[str, Any], subclass: str | None,
                 marks: dict[str, Any]) -> list[str]:
    groups = int(cfg["groups"])
    answers: dict[str, Sequence[str]] = {}
    missed_all: list[str] = []
    failed: list[str] = []
    for key, questions in merger_tables.group_questions(groups).items():
        excerpts, missed = merger_sections.question_excerpts(doc_text, questions)
        missed_all += missed
        asked = [q for q in questions if q not in missed]
        if not asked:
            continue
        message = group_message(agent.handoff_context, excerpts, subclass, asked)
        reply, calls, failure = _ask(agent, message, [group_schema(asked, enum=True), group_schema(asked, enum=False)])
        marks["group_calls"] += calls
        marks["group_chars"] += len(message) * calls
        if reply is None:
            failed.append(key)
            _log.warning("merger group read %s failed (%s); the main read's answers stand", key, failure)
            continue
        answers[key] = reply.get("maud_clauses") or []
    out["maud_clauses"], invalid = combine(out, answers, groups)
    if missed_all:
        out["_maud_section_missed"] = missed_all
    if failed:
        out["_maud_group_failed"] = failed
    return invalid


def _retry(agent: Any, out: dict[str, Any], doc_text: str, subclass: str | None, questions: Sequence[str],
           fields: Sequence[str], marks: dict[str, Any]) -> None:
    q_ex, q_missed = merger_sections.question_excerpts(doc_text, questions) if questions else ([], [])
    f_ex, f_missed = merger_sections.entity_excerpts(doc_text, fields) if fields else ([], [])
    questions = [q for q in questions if q not in q_missed]
    fields = [f for f in fields if f not in f_missed]
    marks["targets"] = {"questions": list(questions), "fields": list(fields), "unlocated": [*q_missed, *f_missed]}
    if not (questions or fields):
        return
    excerpts = sorted({e.key: e for e in [*q_ex, *f_ex]}.values(), key=lambda e: e.start)
    message = group_message(agent.handoff_context, excerpts, subclass, questions)
    if fields:
        message += "\n\nAlso fill these fields from the sections above: " + ", ".join(f"`{f}`" for f in fields) + "."
    base = type(agent).schema  # the class schema: a dropped field is not in the instance's subclass schema
    schemas = [retry_schema(base, fields, questions, enum=True)]
    if questions:
        schemas.append(retry_schema(base, fields, questions, enum=False))
    reply, calls, failure = _ask(agent, message, schemas)
    marks["retry_calls"] = calls
    marks["retry_chars"] += len(message) * calls
    if reply is None:
        marks["retry_failed"] = failure
        _log.warning("merger gap retry failed (%s); the earlier answers stand", failure)
        return
    for name in fields:
        if not _empty(reply.get(name)) and _empty(out.get(name)):
            out[name] = reply[name]
    if questions:
        out["maud_clauses"] = merge_answers(out.get("maud_clauses"), reply.get("maud_clauses"), questions)


def _merger_reads(agent: Any, result: dict[str, Any], doc_text: str, cfg: Mapping[str, Any], choice: Choice
                  ) -> dict[str, Any]:
    out = dict(result)
    marks: dict[str, Any] = {"group_calls": 0, "group_chars": 0, "retry_chars": 0, "targets": {}}
    sorter, schema_sub = choice.sorter_subclass, choice.schema_subclass
    invalid: list[str] = []
    if cfg.get("question_groups"):
        invalid = _group_reads(agent, out, doc_text, cfg, sorter, marks)
    elif cfg.get("gap_retry"):
        invalid = combine(out, {}, int(cfg["groups"]))[1]
    if cfg.get("gap_retry"):
        targets = gap_targets(out, schema_sub, sorter, invalid)
        _retry(agent, out, doc_text, sorter, targets.questions, targets.fields, marks)
    else:
        dropped = disagreement_fields(out, schema_sub, sorter)
        if dropped:
            _retry(agent, out, doc_text, sorter, (), dropped, marks)
    out["_merger_reads"] = marks
    return out


def extract(agent: Any, original: Callable[..., dict], doc_text: str, pages: list[str] | None) -> dict:
    """HF-030: the vendored one-call read, then the merger reads ``job.merger`` switches on."""
    result = original(agent, doc_text, pages=pages)
    cfg = merger_reads.config()
    if cfg is None or not cfg.get("subclass_fields"):
        return result
    from mailroom_sandbox.subclass_extraction import _ONLY

    if (_ONLY.get() is not None or getattr(agent, "_last_chunked", False) or not isinstance(result, dict)
            or result.get("_parse_error") or not isinstance(doc_text, str)):
        return result
    try:
        return _merger_reads(agent, result, doc_text, cfg, _CHOICE.get() or Choice(None, None))
    except Exception:  # noqa: BLE001 — never fail (or re-run) the main read over an extra one
        _log.warning("HF-030 merger reads failed; the main read passes through", exc_info=True)
        return result
