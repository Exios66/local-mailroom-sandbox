"""Cause buckets for the production slice gate: one primary cause per review, wrong archive and crash.

Offline and deterministic. ``primary_cause`` reads the document (dataset row, latest item) and its
``gate.doc_status`` and returns ``<family>:<type>`` (or the bare ``label_suspect``), by this
precedence:

1. ``mechanism``: ``judge_error``, ``crashed``, ``transient``;
1b. ``input:near_empty``, reviews only: the document text is under ``NEAR_EMPTY_CHARS`` characters (an
   Enron cover note whose attachment was stripped, for example), so no reviewer can do better than
   abstain. A wrong archive of such a document keeps its classification or extraction cause;
2. ``classification``: ``wrong_class`` (the archived or reviewed class is not the expected one),
   ``reviewer_unknown``, ``reviewer_disagreement``, ``arbiter_escalated`` (the classification
   arbiter's ``classification_arbiter_escalated``). The reviewer's own doubt (low confidence,
   ineligible label) ranks last of these: once the extraction arbiter has ruled, the class was
   settled past that doubt, so the doubt is stale. When the item records that the classification
   arbiter accepted a class (``classification_arbiter_decision`` ``accept_sorter`` or
   ``accept_reviewer``), every reviewer cause (``reviewer_unknown``, ``reviewer_disagreement``, the doubt)
   is settled: the judge and extraction lanes below decide first, and a reviewer cause names the park
   only when nothing there does. An item that does not carry the decision keeps the order above;
3. ``judge``: ``arbiter_escalated`` (the extraction arbiter's ``arbiter_escalated``: it ruled last on
   the judge lane, so it wins over the verdict beside it), ``partial_exhausted`` (partial verdict,
   retries spent), ``judge_rejected``;
4. ``extraction``: the type of the lowest-scoring labelled field (see ``extraction_miss``), or for
   contracts and mergers, scored on one label field, ``cuad_missed`` / ``cuad_false`` / ``maud_wrong``;
5. ``label_suspect``: the lowest field is a heuristic ``intent`` label and the document text states
   the predicted value, so the label is the likelier error. Checked ahead of the extraction type,
   which it replaces. It never applies to contracts and mergers, nor to an ``intent`` an overlay
   supplied (see ``label_suspect``).

Review causes are the pipeline's ``review_causes`` tokens (``vendor/llm-mailroom``
``pipeline/reconsideration.py``). Tokens this module does not map are never bucketed by guess:
a review none of whose causes maps lands in ``mechanism:unmapped:<first raw cause>`` (``none`` when
the item carries no cause at all), so a new pipeline cause shows up as its own bucket.

A Dojo scorer failure while typing an extraction miss is never folded into an extraction type: it
raises ``ScorerError`` internally and the document lands in ``mechanism:scorer_error``.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Mapping

from mailroom_sandbox.eval.extraction_scope import scope_extraction_pair
from mailroom_sandbox.job.gate import _NOT_LABELS, _UNIT_FIELD, _blank, _unit_labels, cuad_unlabeled, is_wrong_class
from mailroom_sandbox.job.pair_report import TEMPLATED_FIELDS, _fields

_MECHANISM = {"judge_error": "judge_error", "transient_exhausted": "transient"}
# reviewer_doc_type "unknown" or a reviewer that gave no usable answer
_REVIEWER_UNKNOWN = frozenset({"reviewer_unavailable", "reviewer_no_text", "unknown_class"})
_REVIEWER_DISAGREEMENT = frozenset({"reviewer_disagreement"})
_ARBITER = frozenset({"classification_arbiter_escalated"})
# the extraction arbiter (judge lane); the classification arbiter has its own token above
_EXTRACTION_ARBITER = frozenset({"arbiter_escalated"})
# the reviewer's own doubt, weaker than an outright disagreement or arbiter escalation
_REVIEWER_DOUBT = frozenset({"reviewer_ineligible_label", "reviewer_low_confidence"})
_WRONG_CLASS_TOKENS = frozenset({"class_miss"})
# a classification arbiter answer that let the document on to extraction (anything else leaves its own token)
_CLASSIFICATION_ACCEPTED = frozenset({"accept_sorter", "accept_reviewer"})
_JUDGE_REJECTED = frozenset({"judge_partial", "judge_miss", "judge_incomplete"})
_EXTRACTION = frozenset({"extraction_miss", "low_extraction_confidence", "hollow_extraction"})
# Below this many characters of stripped text a document carries too little content to classify or
# extract (Exios66/Mailroom-Corpus-EDA, near-empty correspondence); its review is an input finding.
NEAR_EMPTY_CHARS = 200


class ScorerError(RuntimeError):
    """The Dojo scorer failed (raised, or returned no field scores) while typing an extraction miss."""


def _pred(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    item = doc.get("item") or {}
    return item.get("pred") or {}


def _vocabulary(doc_class: str, field: str) -> tuple[str, ...] | None:
    """The Dojo's closed vocabulary of ``doc_class.field``, or None when the field has none."""
    try:
        from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS

        entry = SCORED_ENUM_FIELDS.get(doc_class, {}).get(field)
        if entry:
            return tuple(entry[0])
        if (doc_class, field) == ("corporate_record", "record_type"):
            from llm_dojo_scoring.schemas.corporate_record_schema import RECORD_TYPES

            return tuple(RECORD_TYPES)
    except ImportError:
        return None
    return None


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _in_vocabulary(doc_class: str, field: str, value: Any, vocabulary: tuple[str, ...]) -> bool:
    if _compact(value) in {_compact(token) for token in vocabulary}:
        return True
    from llm_dojo_scoring.schemas.scored_enums import SCORED_ENUM_FIELDS, canonical_label

    # the scorer's own folding (intent aliases, subclass spellings) for the fields it covers
    return field in SCORED_ENUM_FIELDS.get(doc_class, {}) and bool(canonical_label(doc_class, field, value))


def _is_iso_date(value: Any) -> bool:
    text = str(value).strip()
    for parse in (datetime.date.fromisoformat, datetime.datetime.fromisoformat):
        try:
            parse(text)
            return True
        except ValueError:
            continue
    return False


def _field_scores(row: Mapping[str, Any], pred: Mapping[str, Any]) -> dict[str, float]:
    """Dojo per-field scores of the labelled fields (templated and metadata keys dropped), as the gate scores.

    Scored with the current scoring hotfixes on (``scoring_hotfixes.hotfixed``), so the per-field
    scorer fixes (SHF-002 names, SHF-003 money, SHF-004 identifiers) type a miss the way the run
    headline scores it: a ``claim_number`` the headline counts right is never the lowest field. The
    stale-label drop (SHF-015) is not applied here: a heuristic ``intent`` stays a candidate lowest
    field so that ``label_suspect`` can name it. A correspondence header label SHF-019 leaves out
    (the text does not show it) is skipped, as the headline skips it.
    """
    from mailroom_sandbox import scoring_hotfixes as sh
    from mailroom_sandbox.eval.scoring import suite_for_doc_type

    doc_class = str(row.get("expected_doc_class"))
    drop = set(TEMPLATED_FIELDS.get(doc_class, ()))
    if sh.enabled("SHF-019"):  # header truth the text does not show is not scored on the headline
        drop.update(sh.drop_unseen_header_truth(doc_class, row.get("id"), _fields(row), row.get("doc_text"))[1])
    _, expected = scope_extraction_pair(doc_class, {}, _fields(row))
    expected = {k: v for k, v in expected.items() if k not in drop and k not in _NOT_LABELS and not _blank(v)}
    if not expected:
        return {}
    predicted, _ = scope_extraction_pair(doc_class, pred.get("extracted_data") or {}, {})
    sub = str(row.get("expected_subclass") or "").strip()
    # SHF-013: the headline scores a reviewed subclass correction, so the diagnosis does too.
    from mailroom_sandbox.eval.scoring import corrected_subclass_truth
    corrected = corrected_subclass_truth(row.get("id"), doc_class, sub) if sub else None
    if corrected:  # the derived truth (record_type, intent, cuad_family, ...) follows it, as on the headline
        expected = sh.corrected_derived_truth(doc_class, sub, corrected, expected)[0]
        sub = corrected
    kwargs: dict[str, Any] = {"doc_subclass": sub} if sub else {}
    detailed = bool(sub or doc_class == "corporate_record")
    try:
        suite = suite_for_doc_type(doc_class)
        with sh.hotfixed():
            if sh.is_active("SHF-018"):
                expected, predicted, _notes = sh.apply_subclass_score_scope(
                    doc_class, sub or None, expected, predicted, row.get("doc_text"))
                if not expected:
                    return {}
            result = (suite.score(expected, predicted, doc_text=row.get("doc_text"), detailed=True, **kwargs)
                      if detailed else suite.score(expected, predicted, doc_text=row.get("doc_text")))
    except Exception as exc:  # noqa: BLE001 - surfaced as mechanism:scorer_error, never as an extraction type
        raise ScorerError(f"{doc_class}: {type(exc).__name__}: {exc}") from exc
    nested = result.get("extraction") if isinstance(result, dict) else result
    scores = getattr(nested, "field_scores", None)
    if not scores:
        raise ScorerError(f"{doc_class}: the scorer returned no field scores for labelled fields")
    return {k: float(v) for k, v in scores.items() if k in expected and isinstance(v, (int, float))}


def lowest_field(row: Mapping[str, Any], pred: Mapping[str, Any]) -> tuple[str | None, float | None]:
    """The lowest-scoring labelled field of a per-field class and its score; ties go to the field name.

    ``(None, None)`` when no labelled field is compared; raises ``ScorerError`` when the scorer fails.
    """
    scores = _field_scores(row, pred)
    if not scores:
        return None, None
    field = min(scores, key=lambda name: (scores[name], name))
    return field, scores[field]


def extraction_miss(row: Mapping[str, Any], pred: Mapping[str, Any]) -> str:
    """The type of the extraction miss: ``missing_field``, ``out_of_enum``, ``date_format`` or ``wrong_value``.

    Per-field classes use the lowest-scoring labelled field. Contracts and mergers are scored on one
    label field, so there is no lowest field: a contract is ``cuad_missed`` when the gold CUAD
    categories it missed are at least as many as the categories it predicted without gold, else
    ``cuad_false``; a merger is ``maud_wrong``. A contract whose CUAD map names no category is
    scored on its field labels (SHF-016), so it takes the per-field path. Raises ``ScorerError``
    when the Dojo scorer fails.
    """
    doc_class = str(row.get("expected_doc_class"))
    if doc_class == "merger_agreement":
        return "maud_wrong"
    if doc_class == "contract" and not cuad_unlabeled(row, doc_class):  # SHF-016 rows score on fields
        from mailroom_sandbox.eval.cuad_scoring import score_cuad

        labels = _unit_labels(_fields(row).get(_UNIT_FIELD["contract"]))
        predicted, _ = scope_extraction_pair(doc_class, pred.get("extracted_data") or {}, {})
        try:
            scored = score_cuad(predicted, labels)
        except Exception as exc:  # noqa: BLE001 - surfaced as mechanism:scorer_error
            raise ScorerError(f"contract: {type(exc).__name__}: {exc}") from exc
        return "cuad_missed" if (scored.get("cuad_fn") or 0) >= (scored.get("cuad_fp") or 0) else "cuad_false"
    field, _ = lowest_field(row, pred)
    if field is None:
        return "wrong_value"
    value = (pred.get("extracted_data") or {}).get(field)
    if value is None or _blank(value):
        return "missing_field"
    vocabulary = _vocabulary(doc_class, field)
    if vocabulary is not None and not _in_vocabulary(doc_class, field, value, vocabulary):
        return "out_of_enum"
    from mailroom_sandbox.eval.scoring import suite_for_doc_type

    try:
        kind = (getattr(suite_for_doc_type(doc_class), "field_types", None) or {}).get(field)
    except Exception as exc:  # noqa: BLE001 - surfaced as mechanism:scorer_error
        raise ScorerError(f"{doc_class}: {type(exc).__name__}: {exc}") from exc
    if kind == "date" and not _is_iso_date(value):
        return "date_format"
    return "wrong_value"


def _words(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text).lower().replace("_", " ")).strip()


def _overlay_supplied(row: Mapping[str, Any], field: str) -> bool:
    """An overlay (interim, staged or near-gold) supplied this field's label on this row.

    An interim ``correction`` and the staged overlay replace a Hub label but leave ``intent_source``
    as it was; near-gold fills only an unlabelled field. The marker each one writes
    (``interim_labels``, ``near_gold_labels``, ``staged_overlay``, each listing the fields it
    applied) is the provenance. A staged row marked ``stale`` applied nothing and lists no field.
    Reads the row only; it never changes it, so no hash, lock or score depends on it.
    """
    from mailroom_sandbox.gold_audit import label_source

    return label_source(row, field) != "hub"


def label_suspect(row: Mapping[str, Any], pred: Mapping[str, Any], field: str | None) -> bool:
    """The lowest field's label is heuristic and the document text states the predicted value.

    Only ``intent`` carries a label source (``intent_source == "heuristic"``). Contracts and mergers
    are scored on CUAD/MAUD labels, never on that intent, so they never qualify. An ``intent`` that an
    overlay supplied (``_overlay_supplied``) never qualifies either: an interim correction or the
    staged overlay leaves ``intent_source`` as ``heuristic`` while replacing the value, so the
    marker, not the source tag, says the label was reviewed. The predicted value must be in the
    intent vocabulary, must not be ``other`` (a catch-all, too common to be evidence), and must
    appear in the text as whole words (underscores read as spaces).
    """
    if field != "intent" or str(row.get("expected_doc_class")) in _UNIT_FIELD:
        return False
    if _fields(row).get("intent_source") != "heuristic" or _overlay_supplied(row, "intent"):
        return False
    value = (pred.get("extracted_data") or {}).get("intent")
    if value is None or _blank(value) or not isinstance(value, str) or _words(value) == "other":
        return False
    doc_class = str(row.get("expected_doc_class"))
    vocabulary = _vocabulary(doc_class, "intent")
    if vocabulary is None or not _in_vocabulary(doc_class, "intent", value, vocabulary):
        return False
    pattern = r"\b" + r"[\s_]+".join(re.escape(word) for word in _words(value).split(" ")) + r"\b"
    return re.search(pattern, str(row.get("doc_text") or ""), flags=re.IGNORECASE) is not None


def _error_text(doc: Mapping[str, Any]) -> str:
    item = doc.get("item") or {}
    pred = _pred(doc)
    return " ".join(str(v) for v in (item.get("error"), pred.get("error"), pred.get("error_message")) if v)


def primary_cause(doc: Mapping[str, Any], status: Mapping[str, Any]) -> str:
    """The single cause of a review, wrong archive or crash; ``""`` for any other outcome."""
    outcome = status.get("outcome")
    if outcome not in ("review", "wrong_archive", "crashed"):
        return ""
    row, pred = doc["row"], _pred(doc)
    causes = [str(c) for c in (pred.get("review_causes") or [])]
    have = set(causes)
    if outcome == "crashed":
        return "mechanism:transient" if "transient" in _error_text(doc).lower() else "mechanism:crashed"
    stop = pred.get("governor_stop")
    if outcome == "review" and isinstance(stop, Mapping) and stop.get("reason"):
        # The loop governor sent it (phase 2): its budget, not the last node, ended the document.
        # A near-empty input keeps the input cause it always had.
        reason = str(stop["reason"])
        return "input:near_empty" if reason == "near_empty" else f"governor:{reason}"
    for token, kind in _MECHANISM.items():
        if token in have or (token == "judge_error" and status.get("judge_error")):
            return f"mechanism:{kind}"
    doc_class = str(status.get("class") or row.get("expected_doc_class"))
    # A review of a near-empty input is an input finding: there is nothing to classify. A wrong ARCHIVE of
    # one is not: the pipeline was confidently wrong, so it keeps its classification/extraction cause.
    # Only a row that carries its text is judged (dataset rows always do); a row without the key says nothing.
    if (outcome == "review" and "doc_text" in row
            and len(str(row.get("doc_text") or "").strip()) < NEAR_EMPTY_CHARS):
        return "input:near_empty"
    if is_wrong_class(doc_class, pred) or have & _WRONG_CLASS_TOKENS:
        return "classification:wrong_class"
    # A classification arbiter that accepted a class let the document on to extraction, so whatever the
    # reviewer doubted (disagreement, no answer, an unknown class, low confidence) is settled: the judge
    # and extraction lanes that ran after it are the likelier cause. Without the recorded decision the reviewer causes
    # keep their precedence.
    settled = str(pred.get("classification_arbiter_decision") or "") in _CLASSIFICATION_ACCEPTED
    reviewer = ""
    if str(pred.get("reviewer_doc_type") or "").strip().lower() == "unknown" or have & _REVIEWER_UNKNOWN:
        reviewer = "classification:reviewer_unknown"
    elif have & _REVIEWER_DISAGREEMENT:
        reviewer = "classification:reviewer_disagreement"
    if reviewer and not settled:
        return reviewer
    if have & _ARBITER:
        return "classification:arbiter_escalated"
    # The extraction arbiter only runs after extraction, and the vendored routes reach extraction past
    # reviewer doubt in one way: the classification arbiter accepted a class (one that did not accept
    # would have left its own token, handled above). Reviewer doubt beside it is stale, so the
    # extraction arbiter's park outranks it, whether or not the decision was recorded.
    if have & _EXTRACTION_ARBITER:
        return "judge:arbiter_escalated"
    if have & _REVIEWER_DOUBT and not settled:
        return "classification:reviewer_unknown"
    if "judge_partial" in have and "retries_exhausted" in have:
        return "judge:partial_exhausted"
    if have & _JUDGE_REJECTED:
        return "judge:judge_rejected"
    if outcome == "wrong_archive" or have & _EXTRACTION:
        try:
            unit_scored = doc_class in _UNIT_FIELD and not cuad_unlabeled(row, doc_class)
            field = None if unit_scored else lowest_field(row, pred)[0]
            if label_suspect(row, pred, field):
                return "label_suspect"
            return f"extraction:{extraction_miss(row, pred)}"
        except ScorerError:
            return "mechanism:scorer_error"
    if settled and (reviewer or have & _REVIEWER_DOUBT):  # nothing in the judge or extraction lane explains the park
        return reviewer or "classification:reviewer_unknown"
    return f"mechanism:unmapped:{causes[0] if causes else 'none'}"
