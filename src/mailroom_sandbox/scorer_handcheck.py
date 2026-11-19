"""R02 scorer hand-check: 20 dev documents, perturbed predictions, a sheet a person scores.

The evaluation runbook's R02 gate is "scorers reproduce hand-checked results on 20 docs".
This module builds that check and replays it, offline and deterministically:

* :func:`select_docs` picks 4 scorable dev documents per class (20 in all), spread over
  score units (subclasses / ``families.yaml`` families), ranked by a seeded hash. The sorter
  answer is a saved real v0 pass (``data/handoff/sorter-qwen3.7-flash``): each class takes,
  where dev has one, a document the pass got the wrong class, one with the right class but the
  wrong unit, and two it got right.
* :func:`perturb` builds the extraction for each document from its truth in one of four known
  ways (``exact``, ``normalised`` format edge cases that must still match, ``mismatch`` values
  that must not, ``missing`` labelled values). Contracts get CUAD clause lines and mergers MAUD
  answers the same way.
* :func:`sheet_rows` writes one row per check (class, subclass unit, each scored field, the
  document score and the production-gate outcome, plus five pooled statistics) with an empty
  ``hand_score``. ``draft=True`` pre-fills the rows whose answer the labeling guide and the
  documented scorer rules settle without judgment, marked ``hand_scored_by=agent-draft``.
* :func:`score_case` runs the scorers real runs use: ``eval.agents._score_class`` (sorter),
  :func:`experiment_splits.unit_correct` (subclass at its unit), the Dojo extraction suite
  through ``eval.agents._score_extract`` (field scores, CUAD presence F1, MAUD accuracy) and
  ``job.gate.doc_status`` (review / wrong-archive outcome). :func:`compare` sets each row's
  scorer value beside its hand score.

The gate passes only when every row has a hand score confirmed by a person (initials in
``hand_scored_by``) and all of them match. An ``agent-draft`` score is never a confirmation.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "mailroom.scorer_handcheck/v1"
# The runbook names this commit for the field scorer; it is a gold-label commit (plan finding 3).
LABELS_COMMIT = "e90ac8b9469d29fa0c24447ab260a4840b1f9eee"
SEED = "r02-handcheck-20261118"
CLASSES = ("contract", "corporate_record", "correspondence", "insurance_claim", "merger_agreement")
PER_CLASS = 4
PROFILES = ("exact", "normalised", "mismatch", "missing")
ROUTES = {"exact": "archive", "normalised": "archive", "mismatch": "review", "missing": "archive"}
ROLES = ("v0_class_error", "v0_unit_error", "v0_correct", "v0_correct")
DRAFT = "agent-draft"
INITIALS_RE = re.compile(r"^[A-Z]{2,6}$")
SCORE_TOL = 0.005
SHEET_COLUMNS = (
    "row_id", "doc_id", "doc_class", "truth_subclass", "truth_unit", "v0_role", "profile", "route",
    "check", "field_type", "perturbation", "truth", "prediction", "hand_score", "hand_scored_by",
    "hand_note",
)
STAT_CHECKS = ("stat:class_accuracy", "stat:class_macro_f1", "stat:unit_accuracy",
               "stat:review_rate", "stat:wrong_archive_rate")


class HandcheckError(ValueError):
    """The inputs cannot produce a faithful hand-check (drift, missing pass, too few docs)."""


# ---------------------------------------------------------------- inputs


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def expected_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    from mailroom_sandbox.datasets import parse_expected_fields

    return dict(parse_expected_fields(dict(row)) or {})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_sorter_pass(handoff_dir: Path) -> dict[str, dict[str, Any]]:
    """``{doc_id: saved sorter answer}`` from a handoff directory's ``<split>.jsonl`` files."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(handoff_dir).glob("*.jsonl")):
        if path.name.endswith(".targets.jsonl"):
            continue
        for row in read_jsonl(path):
            out[str(row["id"])] = row
    if not out:
        raise HandcheckError(f"no saved sorter pass under {handoff_dir}")
    return out


def _rank(doc_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{doc_id}".encode()).hexdigest()


# ---------------------------------------------------------------- selection


@dataclass
class Case:
    row: dict[str, Any]
    role: str
    profile: str
    sorter: dict[str, Any]
    truth_unit: str | None
    fields: dict[str, Any] | None = None
    perturbations: dict[str, tuple[str, float | None]] | None = None
    doc_note: str = ""
    doc_draft: float | None = None

    @property
    def doc_id(self) -> str:
        return str(self.row["id"])

    @property
    def doc_class(self) -> str:
        return str(self.row["expected_doc_class"])

    @property
    def route(self) -> str:
        return ROUTES[self.profile]

    @property
    def pred_class(self) -> str:
        return str(self.sorter.get("sorter_doc_type") or "")

    @property
    def pred_subclass(self) -> str:
        return str(self.sorter.get("sorter_doc_subclass") or "")


def v0_role(row: Mapping[str, Any], sorter: Mapping[str, Any], table: Mapping[tuple[str, str], str]) -> str:
    from mailroom_sandbox.experiment_splits import unit_correct

    truth_cls, pred_cls = str(row["expected_doc_class"]), str(sorter.get("sorter_doc_type") or "")
    if pred_cls != truth_cls:
        return "v0_class_error"
    if not unit_correct(truth_cls, row.get("expected_subclass"), pred_cls, sorter.get("sorter_doc_subclass"), table):
        return "v0_unit_error"
    return "v0_correct"


def select_docs(
    rows: Sequence[Mapping[str, Any]],
    sorter: Mapping[str, Mapping[str, Any]],
    table: Mapping[tuple[str, str], str],
    *,
    min_labelled: int = 2,
    per_class: int = PER_CLASS,
    classes: Sequence[str] = CLASSES,
) -> list[Case]:
    """``per_class`` scorable documents per class, roles first, spread over units.

    Scorable: at least ``min_labelled`` labelled units by the production gate's count. A merger
    labelled ``other`` is skipped: it has no MAUD consideration annotation, so its subclass is
    not scored (``scripts/patch_sorter_handoff.py`` rule 2). The saved pass must cover each
    document with the same text (``content_sha256``).
    """
    from mailroom_sandbox.experiment_splits import unit_of
    from mailroom_sandbox.job.gate import labelled_count

    cases: list[Case] = []
    for cls in classes:
        pool = []
        for row in rows:
            if str(row.get("expected_doc_class")) != cls:
                continue
            if cls == "merger_agreement" and str(row.get("expected_subclass")) == "other":
                continue
            if labelled_count(row, cls) < min_labelled:
                continue
            pool.append(row)
        pool.sort(key=lambda r: _rank(str(r["id"])))
        roles = {}
        for row in pool:
            saved = sorter.get(str(row["id"]))
            if saved is None:
                continue
            if saved.get("content_sha256") and saved["content_sha256"] != row.get("content_sha256"):
                raise HandcheckError(f"{row['id']}: saved sorter pass read different text (content_sha256)")
            roles[str(row["id"])] = v0_role(row, saved, table)
        picked: list[Mapping[str, Any]] = []
        used_units: set[str | None] = set()

        def take(want: str | None, spread: bool) -> Mapping[str, Any] | None:
            for row in pool:
                rid = str(row["id"])
                if rid not in roles or row in picked or (want and roles[rid] != want):
                    continue
                if spread and unit_of(cls, row.get("expected_subclass"), table) in used_units:
                    continue
                return row
            return None

        for want in ROLES[:per_class]:
            row = (take(want, True) or take(want, False) or take("v0_correct", True)
                   or take(None, True) or take(None, False))
            if row is None:
                raise HandcheckError(f"{cls}: fewer than {per_class} scorable dev documents with a saved sorter answer")
            picked.append(row)
            used_units.add(unit_of(cls, row.get("expected_subclass"), table))
        for i, row in enumerate(picked):
            rid = str(row["id"])
            cases.append(Case(row=dict(row), role=roles[rid], profile=PROFILES[i % len(PROFILES)],
                              sorter=dict(sorter[rid]),
                              truth_unit=unit_of(cls, row.get("expected_subclass"), table)))
    return cases


# ---------------------------------------------------------------- perturbations

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def as_list(value: Any) -> list[Any] | None:
    """A list truth value: a list, or a JSON / Python-literal list string; None otherwise."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str) and value.strip().startswith("["):
        for parse in (json.loads, ast.literal_eval):
            try:
                parsed = parse(value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, list):
                return parsed
    return None


def _money(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    try:
        out = float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _upper_items(items: list[Any]) -> list[Any]:
    return [str(i).upper() if isinstance(i, str) else i for i in items]


def perturb_value(field_type: str, value: Any, profile: str, *, doc_class: str = "", field: str = "",
                  ) -> tuple[Any, str, float | None]:
    """``(prediction, perturbation, draft score)`` for one labelled field.

    Drafts come from the scorer's documented rules (``llm_dojo_scoring.scoring.field_scoring``):
    ids and names compare after upper-casing and stripping punctuation and whitespace, labels
    after compacting to lowercase alphanumerics, free text by lowercase token F1, money to the
    cent, full dates by calendar date (same month and day in another year scores 0.33), and a
    labelled field left empty scores 0. A wrong label is another token of the field's scored
    vocabulary (``intent`` folds free text onto a label it contains, so a decorated label would
    still match). An empty-list truth (stated absence) is always answered with an empty list.
    ``None`` means the outcome needs judgment.
    """
    base = field_type.split(":", 1)[0]
    if value is None or (isinstance(value, list) and not value):
        return value, EXPECTED_EMPTY, 1.0
    if profile == "exact":
        return value, "exact", 1.0
    if profile == "normalised":
        if base == "date" and isinstance(value, str) and _ISO.match(value.strip()):
            y, m, d = (int(p) for p in _ISO.match(value.strip()).groups())
            return f"{_MONTHS[m - 1]} {d}, {y}", "date_reformat", 1.0
        if base == "money" and _money(value) is not None:
            return f"${_money(value):,.2f}", "money_format", 1.0
        if base == "id" and isinstance(value, str):
            return f"  {value.lower()} ", "id_case_ws", 1.0
        if base == "name" and isinstance(value, str):
            return "  " + "  ".join(value.upper().split()) + " ", "name_case_ws", 1.0
        if base == "label" and isinstance(value, str):
            return value.upper(), "label_case", 1.0
        if base == "free_text" and isinstance(value, str):
            return "  ".join(value.upper().split()), "text_case_ws", 1.0
        if base == "entity_list" and as_list(value):
            return list(reversed(_upper_items(as_list(value) or []))), "list_reorder_case", 1.0
        return value, "exact", 1.0
    if profile == "mismatch":
        if base == "date" and isinstance(value, str) and _ISO.match(value.strip()):
            y, m, d = (int(p) for p in _ISO.match(value.strip()).groups())
            if not (m == 2 and d == 29):
                return f"{y + 1:04d}-{m:02d}-{d:02d}", "date_year_shift", 0.33
        if base == "money" and _money(value) is not None:
            return round(_money(value) + 1.0, 2), "money_off_by_one", 0.0
        if base == "id" and isinstance(value, str):
            return f"{value}-X9", "id_changed", 0.0
        if base == "label" and isinstance(value, str):
            other = _other_label(doc_class, field, value)
            if other is not None:
                return other, "label_changed", 0.0
            return f"zz_{value}", "label_decorated", None
        items = as_list(value) if base == "entity_list" else None
        if items and len(items) >= 2:
            return items[: len(items) // 2], "list_drop_half", None
        return value, "exact", 1.0
    if profile == "missing":
        if base in ("date", "money", "id", "label"):
            return None, "missing", 0.0
        return value, "exact", 1.0
    raise ValueError(f"unknown profile {profile!r}")


EXPECTED_EMPTY = "expected_empty"


def _is_blank_truth(value: Any) -> bool:
    from mailroom_sandbox.job.gate import _blank

    return _blank(value) or str(value).strip().lower() in ("none", "nan")


def scored_truth(doc_class: str, fields: Mapping[str, Any], subclass: Any = None) -> dict[str, tuple[str, Any]]:
    """``{field: (field_type, truth)}`` for the schema fields the row's truth names.

    Blank keys are left out: unlabelled ones are not scored, and a stated absence
    (:func:`stated_absences`) is answered empty, which the suite does not score either; the
    exception is a CMS insurance row's documented-absent ``adjuster`` / ``denial_reasons`` the
    truth names, listed with an empty truth because the suite scores them. A merger's
    ``maud_clauses`` and ``merger_consideration`` truth is what the Dojo derives from its MAUD
    labels (``maud_schema.hub_merger_expected_fields``), the way the suite scores it.
    """
    from llm_dojo_scoring import suite_for_doc_type

    from mailroom_sandbox.eval.extraction_scope import scope_extraction_pair

    field_types = dict(getattr(suite_for_doc_type(doc_class), "field_types", None) or {})
    _, scoped = scope_extraction_pair(doc_class, {}, dict(fields))
    if doc_class == "merger_agreement":
        from llm_dojo_scoring.schemas.maud_schema import hub_merger_expected_fields

        for key, value in hub_merger_expected_fields(dict(fields), subclass if isinstance(subclass, str) else None).items():
            if _is_blank_truth(scoped.get(key)):
                scoped[key] = value
    out = {f: (field_types[f], scoped[f]) for f in sorted(field_types)
           if f in scoped and not _is_blank_truth(scoped[f])}
    if doc_class == "insurance_claim":
        from llm_dojo_scoring.schemas.corpus import CMS_DOCUMENTED_ABSENT_FIELDS
        from llm_dojo_scoring.scoring.field_scoring import expected_cms_source_table

        if expected_cms_source_table(doc_class, dict(fields)) is not None:
            # A CMS row's documented-absent fields the truth names are scored: answering
            # empty is correct, a stated value is a false positive (Dojo field_scoring).
            for f in CMS_DOCUMENTED_ABSENT_FIELDS:
                if f in scoped and f in field_types and f not in out:
                    out[f] = (field_types[f], [] if field_types[f].startswith("entity_list") else None)
    return dict(sorted(out.items()))


STATED_ABSENCE = ("schema_documented_absence", "populated")


def stated_absences(doc_class: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """``{field: empty value}`` for blank schema keys whose ``gt_presence`` states an absence.

    Every prediction answers these empty (``[]`` for a list, ``None`` otherwise), as a model
    filling the whole schema would; the suite then leaves the field out of the score.
    """
    from llm_dojo_scoring import suite_for_doc_type

    field_types = dict(getattr(suite_for_doc_type(doc_class), "field_types", None) or {})
    presence = _presence(fields)
    return {f: ([] if t.startswith("entity_list") else None) for f, t in sorted(field_types.items())
            if presence.get(f) in STATED_ABSENCE and _is_blank_truth(fields.get(f))}


def _presence(fields: Mapping[str, Any]) -> dict[str, Any]:
    raw = fields.get("gt_presence")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _other_label(doc_class: str, field: str, value: str) -> str | None:
    """Another token of the field's scored vocabulary that folds onto a different label."""
    from llm_dojo_scoring.schemas.intents import INTENT_LABELS
    from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS, canonical_label

    vocab = INTENT_LABELS.get(doc_class, ()) if field == "intent" else \
        (SCORED_ENUM_FIELDS.get(doc_class, {}).get(field) or ((),))[0]
    truth = canonical_label(doc_class, field, value) or value
    compact = re.sub(r"[^a-z0-9]", "", str(value).lower())
    for token in vocab:
        tc = re.sub(r"[^a-z0-9]", "", token.lower())
        if token == "other" or not tc or tc in compact or compact in tc:
            continue
        if (canonical_label(doc_class, field, token) or token) != truth:
            return token
    return None


def _cuad(fields: Mapping[str, Any]) -> dict[str, list[str]]:
    from llm_dojo_scoring.sandbox_scoring import gt_categories

    return gt_categories(fields.get("cuad_clause_labels"))


def _maud(fields: Mapping[str, Any]) -> dict[str, str]:
    from llm_dojo_scoring.sandbox_scoring import gt_labels

    return gt_labels(fields.get("maud_clause_labels"))


def _cuad_draft(pred: Mapping[str, Any], gt: Mapping[str, list[str]]) -> float | None:
    """CUAD category-detection F1 by the documented rules, or None when a rule needs judgment.

    A ``cuad_clauses`` line credits the category its head names, inside the row's labelled
    universe (outside it is not a false positive); a filled metadata field credits its category
    (``FIELD_CATEGORY``); the recall-only date fields only where CUAD labels the category.
    An effective date that may be read off the Agreement Date is left to a person.
    """
    from llm_dojo_scoring.sandbox_scoring import FIELD_CATEGORY, RECALL_ONLY_FIELDS

    universe = set(gt)
    if not universe:
        return None
    present = {c for c, spans in gt.items() if spans}
    norm = {re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", c.lower())).strip(): c for c in universe}
    found = set()
    for line in pred.get("cuad_clauses") or []:
        head = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(line).split(":", 1)[0].lower())).strip()
        if head in norm:
            found.add(norm[head])
    for field, cat in FIELD_CATEGORY.items():
        value = pred.get(field)
        if cat in universe and value not in (None, "", [], {}):
            if field in RECALL_ONLY_FIELDS and cat not in present:
                continue
            found.add(cat)
    if "Effective Date" in found and pred.get("effective_date") not in (None, "", [], {}):
        return None
    tp, fp, fn = len(found & present), len(found - present), len(present - found)
    return round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0


def perturb(case: Case) -> Case:
    """Fill ``case.fields`` (the extraction), per-field perturbations and the document draft."""
    fields = expected_fields(case.row)
    truth = scored_truth(case.doc_class, fields, case.row.get("expected_subclass"))
    pred: dict[str, Any] = dict(stated_absences(case.doc_class, fields))
    marks: dict[str, tuple[str, float | None]] = {}
    for name, (ftype, value) in truth.items():
        if isinstance(value, str) and ftype.startswith("entity_list") and as_list(value) is not None:
            value = as_list(value)
        pv, kind, draft = perturb_value(ftype, value, case.profile, doc_class=case.doc_class, field=name)
        pred[name] = pv
        marks[name] = (kind, draft)
    doc_draft: float | None = None
    note = ""
    if case.doc_class == "contract":
        gt = _cuad(fields)
        present = sorted(c for c, spans in gt.items() if spans)
        absent = sorted(c for c in gt if not gt[c])
        lines = {c: f"{c}: {gt[c][0][:160]}" for c in present}
        if case.profile == "normalised":
            lines = {c: f"{c.upper()}:  {gt[c][0][:160]}" for c in present}
        note = f"CUAD: {len(present)} labelled present of {len(gt)} in the universe"
        if case.profile == "mismatch":
            if len(present) >= 2:
                lines.pop(present[0])
                note += f"; dropped {present[0]!r}"
            if absent:
                lines[absent[0]] = f"{absent[0]}: invented clause text"
                note += f"; added absent {absent[0]!r}"
        if case.profile == "missing":
            lines["Bogus Category"] = "Bogus Category: outside the universe"
            note += "; added an out-of-universe head"
        pred["cuad_clauses"] = list(lines.values())
        doc_draft = _cuad_draft(pred, gt)
    elif case.doc_class == "merger_agreement":
        gt = _maud(fields)
        qs = sorted(gt)
        answers = dict(gt)
        if case.profile == "normalised":
            answers = {q: a.upper() for q, a in gt.items()}
        if case.profile == "mismatch" and qs:
            answers[qs[0]] = "zz not an answer option"
        if case.profile == "missing":
            for q in qs[:2]:
                answers.pop(q, None)
        pred["maud_clauses"] = [f"{q}: {a}" for q, a in sorted(answers.items())]
        correct = sum(1 for q in qs if q in answers and (case.profile != "mismatch" or q != qs[0]))
        doc_draft = round(correct / len(qs), 4) if qs else None
        note = f"MAUD: {len(qs)} labelled questions; {case.profile}"
        if "maud_clauses" in truth:
            # The field holds the same answers; its truth skips questions the MAUD scorer calls
            # ambiguous, so the share is only settled when no question was skipped.
            derived = as_list(truth["maud_clauses"][1]) or []
            marks["maud_clauses"] = (f"maud_{case.profile}", doc_draft if len(derived) == len(qs) else None)
    else:
        drafts = [d for _, d in marks.values()]
        # The Dojo document score is the unweighted mean of the field scores.
        doc_draft = round(sum(drafts) / len(drafts), 4) if drafts and None not in drafts else None
    case.fields, case.perturbations, case.doc_note, case.doc_draft = pred, marks, note, doc_draft
    return case


def gate_draft(case: Case, quality: float = 0.90) -> str | None:
    """The production-gate outcome by its documented rules (``job/gate.py``), or None.

    Review routes are ``review``; a wrong-class archive is ``wrong_archive`` whatever the
    extraction scores; otherwise the archive is correct at or above ``quality``, scored as the
    mean field score without the templated fields (``keywords`` / ``subject_matter`` on corporate
    records and correspondence), or the CUAD / MAUD document score for contracts and mergers.
    """
    from mailroom_sandbox.job.pair_report import TEMPLATED_FIELDS

    if case.route == "review":
        return "review"
    if case.pred_class != case.doc_class:
        return "wrong_archive"
    if case.doc_class in ("contract", "merger_agreement"):
        score = case.doc_draft
    else:
        drop = set(TEMPLATED_FIELDS.get(case.doc_class, ()))
        drafts = [d for f, (_, d) in (case.perturbations or {}).items() if f not in drop]
        score = round(sum(drafts) / len(drafts), 4) if drafts and None not in drafts else None
    if score is None:
        return None
    return "correct_archive" if score >= quality else "wrong_archive"


# ---------------------------------------------------------------- sheet


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fmt(score: float | None) -> str:
    return "" if score is None else f"{score:g}"


def _macro_f1_by_hand(truth: Sequence[str], pred: Sequence[str]) -> float:
    classes = sorted(set(truth))
    total = 0.0
    for c in classes:
        tp = sum(1 for t, p in zip(truth, pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(truth, pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(truth, pred) if t == c and p != c)
        total += 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return round(total / len(classes), 4) if classes else 0.0


def unit_hand(case: Case, table: Mapping[tuple[str, str], str]) -> tuple[str | None, str]:
    """``(predicted unit, hand reading)``: families.yaml groups subclasses into units; another class is 0."""
    from mailroom_sandbox.experiment_splits import unit_of

    pred_unit = unit_of(case.pred_class, case.pred_subclass, table)
    if case.pred_class != case.doc_class:
        return pred_unit, "0"
    return pred_unit, "1" if case.truth_unit is not None and pred_unit == case.truth_unit else "0"


def sheet_rows(cases: Sequence[Case], table: Mapping[tuple[str, str], str], *, draft: bool = False,
               gated: Sequence[str] = ()) -> list[dict[str, str]]:
    """One row per check; ``hand_score`` empty unless ``draft`` pre-fills the settled ones."""
    rows: list[dict[str, str]] = []

    def add(case: Case | None, check: str, *, field_type: str = "", perturbation: str = "", truth: Any = None,
            prediction: Any = None, hand: str = "", note: str = "") -> None:
        base = {
            "doc_id": case.doc_id if case else "*", "doc_class": case.doc_class if case else "*",
            "truth_subclass": str(case.row.get("expected_subclass") or "") if case else "",
            "truth_unit": (case.truth_unit or "") if case else "", "v0_role": case.role if case else "",
            "profile": case.profile if case else "", "route": case.route if case else "",
        }
        filled = bool(draft and hand != "")
        rows.append({**base, "row_id": f"R{len(rows) + 1:03d}", "check": check, "field_type": field_type,
                     "perturbation": perturbation, "truth": _cell(truth), "prediction": _cell(prediction),
                     "hand_score": hand if filled else "", "hand_scored_by": DRAFT if filled else "",
                     "hand_note": note})

    unit_hands: list[str] = []
    for case in cases:
        add(case, "class", field_type="label", perturbation="v0_pass", truth=case.doc_class,
            prediction=case.pred_class, hand="1" if case.pred_class == case.doc_class else "0")
        pred_unit, hand = unit_hand(case, table)
        unit_hands.append(hand)
        add(case, "subclass_unit", field_type="unit", perturbation="v0_pass",
            truth=f"{case.row.get('expected_subclass')} -> {case.truth_unit}",
            prediction=f"{case.pred_class}/{case.pred_subclass} -> {pred_unit}", hand=hand,
            note="1 when the class is right and the predicted subclass falls in the truth's unit")
        truth = scored_truth(case.doc_class, expected_fields(case.row), case.row.get("expected_subclass"))
        for name, (ftype, value) in truth.items():
            kind, d = (case.perturbations or {}).get(name, ("exact", 1.0))
            add(case, f"field:{name}", field_type=ftype, perturbation=kind, truth=value,
                prediction=(case.fields or {}).get(name), hand=_fmt(d))
        headline = {"contract": "cuad_presence_f1", "merger_agreement": "maud_accuracy"}.get(
            case.doc_class, "overall_extraction_score")
        add(case, "doc_score", field_type=headline, perturbation=case.profile,
            prediction=(case.fields or {}).get("cuad_clauses") or (case.fields or {}).get("maud_clauses"),
            hand=_fmt(case.doc_draft), note=case.doc_note)
        add(case, "gate_outcome", field_type="outcome", perturbation=f"route={case.route}",
            truth=case.doc_class, prediction=f"{case.pred_class} ({case.route})", hand=gate_draft(case) or "",
            note="correct_archive / wrong_archive / review / unscorable_archive (job/gate.py)")

    truth_cls = [c.doc_class for c in cases]
    pred_cls = [c.pred_class for c in cases]
    gated_cases = [c for c in cases if c.doc_class in set(gated)]
    outcomes = [gate_draft(c) for c in gated_cases]
    archives = [o for o in outcomes if o != "review"]
    acc = sum(1 for t, p in zip(truth_cls, pred_cls) if t == p) / len(cases) if cases else 0.0
    stat_hands = {
        "stat:class_accuracy": _fmt(round(acc, 4)),
        "stat:class_macro_f1": _fmt(_macro_f1_by_hand(truth_cls, pred_cls)),
        "stat:unit_accuracy": _fmt(round(sum(float(u) for u in unit_hands) / len(cases), 4)) if cases else "",
        "stat:review_rate": _fmt(round(outcomes.count("review") / len(gated_cases), 4)) if gated_cases else "",
        "stat:wrong_archive_rate": (_fmt(round(archives.count("wrong_archive") / len(archives), 4))
                                    if archives and None not in archives else ""),
    }
    notes = {
        "stat:class_accuracy": "share of the documents with the right class",
        "stat:class_macro_f1": "mean over truth classes of 2TP/(2TP+FP+FN)",
        "stat:unit_accuracy": "share of the documents with class and unit right",
        "stat:review_rate": "gated classes only: reviews / documents",
        "stat:wrong_archive_rate": "gated classes only: wrong / (wrong + correct) archives",
    }
    for check in STAT_CHECKS:
        add(None, check, field_type="stat", hand=stat_hands[check], note=notes[check])
    return rows


def write_sheet(rows: Sequence[Mapping[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(SHEET_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in SHEET_COLUMNS})
    path.write_text(buf.getvalue(), encoding="utf-8")


def read_sheet(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = set(SHEET_COLUMNS) - set(rows[0] if rows else SHEET_COLUMNS)
    if missing:
        raise HandcheckError(f"{path}: sheet lacks columns {sorted(missing)}")
    return rows


def human_scored(rows: Iterable[Mapping[str, str]]) -> list[str]:
    """Row ids a person has scored (``hand_scored_by`` holds initials, not the agent draft)."""
    return [r["row_id"] for r in rows if r.get("hand_score", "").strip() and INITIALS_RE.match(r.get("hand_scored_by", "").strip())]


def case_record(case: Case) -> dict[str, Any]:
    """The replayable prediction for one document (no document text)."""
    return {
        "doc_id": case.doc_id, "doc_class": case.doc_class, "content_sha256": case.row.get("content_sha256"),
        "expected_fields_sha256": canonical_sha(expected_fields(case.row)),
        "expected_subclass": case.row.get("expected_subclass"), "truth_unit": case.truth_unit,
        "v0_role": case.role, "profile": case.profile, "route": case.route,
        "prediction": {"doc_type": case.pred_class, "doc_subclass": case.pred_subclass,
                       "confidence": case.sorter.get("sorter_confidence"), "fields": case.fields},
    }


# ---------------------------------------------------------------- scoring


def score_case(record: Mapping[str, Any], row: Mapping[str, Any], table: Mapping[tuple[str, str], str],
               bars: Any) -> dict[str, Any]:
    """Scorer values for every per-document check of one case, from the run scorers."""
    from mailroom_sandbox.eval.agents import _score_class, _score_extract
    from mailroom_sandbox.experiment_splits import unit_correct
    from mailroom_sandbox.job.gate import doc_status

    pred = record["prediction"]
    fields = dict(pred.get("fields") or {})
    out: dict[str, Any] = {}
    out["class"] = _score_class(dict(row), {"doc_type": pred["doc_type"]})["match"]
    out["subclass_unit"] = float(unit_correct(str(row["expected_doc_class"]), row.get("expected_subclass"),
                                              pred["doc_type"], pred.get("doc_subclass"), table))
    scored = _score_extract(dict(row), dict(fields), field_scores=True)
    for name, value in (scored.get("field_scores") or {}).items():
        out[f"field:{name}"] = value
    out["doc_score"] = scored.get("overall_extraction_score")
    stage = "review" if record["route"] == "review" else "archive"
    item = {"ok": True, "pred": {"doc_type": pred["doc_type"], "stage": stage, "extracted_data": fields}}
    status = doc_status({"row": dict(row), "item": item, "nodes": []}, bars)
    out["gate_outcome"] = status["outcome"]
    out["_status"] = status
    out["_scored"] = scored
    return out


def stat_values(records: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]],
                per_doc: Mapping[str, Mapping[str, Any]], bars: Any) -> dict[str, Any]:
    """The pooled statistics over the cases, from the run scorers (Dojo sorter suite, gate rates)."""
    from mailroom_sandbox.eval.scoring import score_classification
    from mailroom_sandbox.job.gate import _class_rates, _counts

    truth = [str(rows[r["doc_id"]]["expected_doc_class"]) for r in records]
    pred = [str(r["prediction"]["doc_type"]) for r in records]
    cls = score_classification(truth, pred)
    gated = [per_doc[r["doc_id"]]["_status"] for r in records
             if str(rows[r["doc_id"]]["expected_doc_class"]) in set(bars.gated)]
    rates = _class_rates(_counts(gated)) if gated else {}
    units = [per_doc[r["doc_id"]]["subclass_unit"] for r in records]
    return {
        "stat:class_accuracy": cls.get("accuracy"),
        "stat:class_macro_f1": cls.get("f1_macro"),
        "stat:unit_accuracy": round(sum(units) / len(units), 4) if units else None,
        "stat:review_rate": rates.get("review_rate"),
        "stat:wrong_archive_rate": rates.get("wrong_archive_rate"),
        "_classification": cls,
    }


def matches(hand: str, scorer: Any) -> bool:
    hand = hand.strip()
    if scorer is None:
        return hand.lower() in ("", "none", "null")
    if isinstance(scorer, str):
        return hand == scorer
    try:
        return abs(float(hand) - float(scorer)) <= SCORE_TOL
    except ValueError:
        return False


@dataclass
class Comparison:
    rows: list[dict[str, Any]]
    blank: list[str]
    draft: list[str]
    confirmed: list[str]
    mismatched: list[dict[str, Any]]
    missing_checks: list[str]
    unlisted: list[tuple[str, str]]

    @property
    def exit_code(self) -> int:
        """0 the gate passes; 1 a filled score disagrees or the sheet and the scorer list different
        checks; 2 some rows are blank; 3 everything filled matches but not every row is confirmed."""
        if self.mismatched or self.missing_checks or self.unlisted:
            return 1
        if self.blank:
            return 2
        if self.draft:
            return 3
        return 0


def compare(sheet: Sequence[Mapping[str, str]], values: Mapping[tuple[str, str], Any]) -> Comparison:
    """Each sheet row beside its scorer value (``values[(doc_id, check)]``).

    A check the scorer reports for a sheet document but the sheet does not list (a field the
    scorer scores that the sheet never shows a person) is ``unlisted`` and fails the check.
    """
    out, blank, draft, confirmed, mismatched, missing = [], [], [], [], [], []
    listed = {(r["doc_id"], r["check"]) for r in sheet}
    for row in sheet:
        key = (row["doc_id"], row["check"])
        scorer: Any = values.get(key, "<not scored>")
        if key not in values:
            missing.append(row["row_id"])
        hand = row.get("hand_score", "").strip()
        rec = {**row, "scorer_value": scorer}
        if not hand:
            blank.append(row["row_id"])
        else:
            (confirmed if INITIALS_RE.match(row.get("hand_scored_by", "").strip()) else draft).append(row["row_id"])
            if key in values and not matches(hand, scorer):
                mismatched.append(rec)
        out.append(rec)
    docs = {d for d, _ in listed}
    unlisted = sorted(k for k in values if k[0] in docs and k not in listed)
    return Comparison(out, blank, draft, confirmed, mismatched, missing, unlisted)
