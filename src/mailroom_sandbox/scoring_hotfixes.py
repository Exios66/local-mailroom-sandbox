"""Sandbox scoring hotfixes: fingerprinted, dual-reported corrections to how runs are scored.

The scorer is the vendored Dojo pin (``vendor/llm-dojo-scoring``, never edited) plus the sandbox
code that calls it. A scoring defect the experiments cannot wait for is corrected here, under an
id (``SHF-001`` ...), and never silently:

- **Bound to the code it corrects.** Each fix lists its targets (``module:qualname``) with the
  sha256 of the target's source (``inspect.getsource``) it was validated against. When a vendor
  refresh or an edit changes a target, the fix is ``stale``: it is not applied, and
  ``sandbox run preflight`` fails on the ``scoring_hotfixes`` check until the fix is re-validated
  or retired.
- **Dual reported.** A scoring entrypoint scores each row twice, once with every fix off (the raw
  Dojo-pin value, under ``raw_dojo``) and once with the current fixes on (the headline).
  ``scoring_hotfixes`` names the fixes that were on and ``scoring_hotfixes_changed`` the headline
  keys whose value differs, so no number changes without the record saying why.
- **Recorded in every run lock** (``scoring_hotfixes``: this module's sha256 and each fix's id and
  target fingerprints). A resume refuses a lock whose set differs.
- **Tracked upstream.** Each fix names the upstream it belongs to (a drafted, unfiled
  llm-dojo-scoring issue in ``docs/scoring-hotfixes.md``, or ``sandbox`` when the defect is in
  this repository's own scoring code).

Outside a :func:`hotfixed` block every scoring-call fix is off, so a scorer that does not opt in
gets the Dojo pin's behaviour unchanged. The switch is a ``ContextVar``: concurrent scoring
threads never see each other's mode. Two fixes act outside a scoring call and are on whenever
they are current: SHF-010 during truth preparation (``gold_labels.apply_near_gold``) and SHF-009
in the Decisions routing contract (``decision_backends``). See ``docs/scoring-hotfixes.md``.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import importlib
import inspect
import json
import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

_log = logging.getLogger("mailroom_sandbox.scoring_hotfixes")

_MARK = "_sandbox_scoring_hotfix"
DOCUMENTED_ABSENCE = "schema_documented_absence"


@dataclass(frozen=True)
class ScoringHotfix:
    id: str
    layer: str  # "dojo": corrects the vendored scorer; "sandbox": corrects sandbox scoring code
    targets: tuple[tuple[str, str], ...]  # (module:qualname, sha256 of its source when validated)
    upstream: str
    summary: str


HOTFIXES: tuple[ScoringHotfix, ...] = (
    ScoringHotfix(
        id="SHF-001",
        layer="sandbox",
        targets=(
            ("mailroom_sandbox.eval.extraction_scope:applicable_expected_fields",
             "44f03a946787e5fb19ba817fd2df4c22e32afab23c268b93944f9e8d5ee4dd15"),
            ("llm_dojo_scoring.scoring.extraction_metrics:extraction_binary_metrics",
             "a5003c2a8b7137457848b0fa5c9c662d1e048b7623d856874c94acb8bc537015"),
        ),
        upstream="sandbox (extraction_scope); Dojo draft issue D-1 in docs/scoring-hotfixes.md",
        summary="a value predicted on a field the truth documents as absent (gt_presence "
                "schema_documented_absence) is a false positive on every class, not only "
                "corporate_record, and is counted as a hallucination",
    ),
    ScoringHotfix(
        id="SHF-002",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_name_field",
                  "2858ef5f4d580f3e7f0f2f4ab220d12b423b299072b595bd306bece00c07787e"),),
        upstream="llm-dojo-scoring draft issue D-2 (docs/scoring-hotfixes.md), not filed",
        summary="a name whose tokens are a strict subset or superset of the truth's (after "
                "legal-suffix, 'the', honorific and initial removal) is a partial match "
                "(token Jaccard), not an exact 1.0",
    ),
    ScoringHotfix(
        id="SHF-003",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_money_field",
                  "25ea35162ccef237c2c7f9aa655c810176305270ac279dcc101c636f1c9b087f"),),
        upstream="llm-dojo-scoring draft issue D-3 (docs/scoring-hotfixes.md), not filed",
        summary="two amounts that state different currencies do not match",
    ),
    ScoringHotfix(
        id="SHF-004",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_id_field",
                  "4ed5c2db371ebf14f322810f44d6828721e293482a4f9e0badf3bbbcfdbac1c3"),),
        upstream="llm-dojo-scoring draft issue D-4 (docs/scoring-hotfixes.md), not filed",
        summary="identifiers equal once every non-alphanumeric character is removed match "
                "(CLM12345 = CLM-12345)",
    ),
    ScoringHotfix(
        id="SHF-005",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.runners:_isolated_headline",
                  "60bb19972b6a93aa7979413306c914c037dd1fb384995769e52e657f1747717e"),
                 ("mailroom_sandbox.job.runner:_scored_pairs",
                  "f0337d2c98e3ac779c2dcfb0202e886151f57200a5c96ce34bdd25a07130bd7e")),
        upstream="sandbox",
        summary="a row that errored (timeout, parse failure, crash) scores 0 in the run "
                "headline instead of leaving the denominator",
    ),
    ScoringHotfix(
        id="SHF-006",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.runners:_isolated_headline",
                  "60bb19972b6a93aa7979413306c914c037dd1fb384995769e52e657f1747717e"),),
        upstream="sandbox",
        summary="a row with no truth to score is left out of the run mean and counted "
                "(n_no_truth) instead of averaging in as 0",
    ),
    ScoringHotfix(
        id="SHF-007",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.agents:_score_class",
                  "fc038e9b4d1f9a4b51c0191be894c9f89a7daa88f7cc973a1b3e7797b7fa6004"),
                 # the folding and the answer reading decide which labels match
                 ("mailroom_sandbox.eval.agents:_fold",
                  "c332fba81b273d2b661944556f62bbc6fa6271ae132b6ef38ea5b75a991164e4"),
                 ("mailroom_sandbox.eval.agents:_class_answer",
                  "63b7b99518c62b86292eb7d05deac93cce40123b36a43dffac28dab40e796984")),
        upstream="sandbox",
        summary="class labels compare case- and whitespace-folded; a row without a truth "
                "class is unscored, not a match; an abstention is its own outcome "
                "(abstain=True, scored wrong, routed to review)",
    ),
    ScoringHotfix(
        id="SHF-008",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.agents:_score_verdict",
                  "fffe11dc169fd7a1ff52840d9ae4a2bf8f8952bada93f88d9909c7e39bc58f2e"),),
        upstream="sandbox",
        summary="judge / arbiter / boss rows without a truth verdict are unscored instead of "
                "1.0 for any output, and a judge parse failure scores 0 with parse_error",
    ),
    ScoringHotfix(
        id="SHF-009",
        layer="sandbox",
        targets=(("mailroom_sandbox.decision_backends:apply_question_set_contract",
                  "c2c16b90d935e51d308a9206184866e4325ee86ea3b0fd751693e75634a8e8af"),),
        upstream="sandbox (decision_backends.decide)",
        summary="question set 4.0.0's document_form, abstain, subclass_gate and "
                "truncation_notice keys are applied: an abstention parks the document "
                "(route_to_human) and the forced-choice answer is kept under forced_choice",
    ),
    ScoringHotfix(
        id="SHF-010",
        layer="sandbox",
        targets=(("mailroom_sandbox.gold_labels:supersede_interim_gap_fills",
                  "708f35c78dd7bdb9dcdcd69a0102b2d408ec94ddfbf19aa02a57869edc5f0ec2"),),
        upstream="sandbox (owner decision: reviewed gold supersedes interim gap fills; "
                 "data/labels/review/INTERIM_AUDIT.md step 2)",
        summary="a near-gold label supersedes a conflicting interim gate gap fill (not an "
                "original_header fill, which the owner adopted over near-gold); the replaced "
                "interim value is kept on the row under truth_overrides and scored as raw",
    ),
    ScoringHotfix(
        id="SHF-011",
        layer="sandbox",
        targets=(("mailroom_sandbox.job.pair_report:_arm_score",
                  "1b3a8928f5620383dfab186021eb3232b90fdb83b0d2c751ce19c0459d570ac9"),),
        upstream="sandbox",
        summary="a paired A/B report scores a failed document 0 instead of crediting its "
                "partial extraction, and counts the failed documents per arm",
    ),
    ScoringHotfix(
        id="SHF-012",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.runners:_run_pipeline_doc",
                  "65352e761fa35d2464623d23f15786c27eb8d81eb233162a73a5a61513e30229"),
                 ("mailroom_sandbox.eval.scoring:predicted_subclass",
                  "f692ca8d94ccdf8cc04ec35b8a40e3508c4ace9da0c3a5dbc5ab3b521d059451"),
                 ("mailroom_sandbox.eval.scoring:score_subclass",
                  "e5bcf80dfa6598718cba4b7fd363f016e21d15cd73d8b5f0d530171824427f59")),
        upstream="sandbox (the Dojo's pipeline_subclass_match ignores the class: draft issue D-5)",
        summary="pipeline items record the final sorter/reviewer subclass and score it joint with the "
                "class on the canonical subclass token (normalize_corpus_subclass), not the Dojo's "
                "class-blind raw-string match",
    ),
)

_BY_ID = {fix.id: fix for fix in HOTFIXES}
#: The fixes a row extraction score can depend on.
EXTRACTION_FIXES = frozenset({"SHF-001", "SHF-002", "SHF-003", "SHF-004", "SHF-010"})
_ACTIVE: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "sandbox_scoring_hotfixes_active", default=frozenset())
_STATUS: dict[str, str] = {}

#: The run-level and row-level keys whose raw Dojo-pin value is kept beside the hotfixed one.
HEADLINE_KEYS: tuple[str, ...] = (
    "overall_extraction_score", "extraction_precision", "extraction_recall", "extraction_f1",
    "extraction_f2", "entity_list_f1", "tp", "fp", "fn", "maud_accuracy", "cuad_presence_f1",
    "n_hallucinated", "n_documented_absent", "hallucination_rate",
    "match", "exact_match", "accuracy", "f1_macro", "n_scored", "n_no_truth", "abstain",
    "error_count", "extraction_overall", "extraction_f1_micro", "extraction_f1_mean",
    "class_correct", "routing_accuracy",
)


# --- fingerprints and status ------------------------------------------------------------------

def _resolve(target: str) -> Any:
    module, _, qual = target.partition(":")
    obj: Any = importlib.import_module(module)
    for part in qual.split("."):
        obj = getattr(obj, part)
    return obj


def source_sha(obj: Any) -> str:
    """sha256 of the (unwrapped) source of ``obj``: what a fix's fingerprint records."""
    return hashlib.sha256(inspect.getsource(inspect.unwrap(obj)).encode("utf-8")).hexdigest()


def _file_source(target: str) -> str | None:
    """The target's source as written in its module file (decorators included), or None.

    Read from the file, not the live attribute, so a test or caller that patches the target
    (``monkeypatch.setattr``) does not change the fingerprint of the code the fix corrects.
    Same text as ``inspect.getsource`` on the unpatched function.
    """
    import ast

    module, _, qual = target.partition(":")
    path = getattr(importlib.import_module(module), "__file__", None)
    if not path or not str(path).endswith(".py"):
        return None
    text = Path(path).read_text(encoding="utf-8")
    nodes: list[Any] = ast.parse(text).body
    node: Any = None
    for part in qual.split("."):
        node = next((n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and n.name == part), None)
        if node is None:
            return None
        nodes = node.body
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return "".join(text.splitlines(keepends=True)[start - 1:node.end_lineno])


def target_sha(target: str) -> str:
    source = _file_source(target)
    if source is not None:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
    return source_sha(_resolve(target))


def module_sha256() -> str:
    """sha256 of this module: the scoring-hotfix code identity a run lock records."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _fix_status(fix: ScoringHotfix) -> str:
    """``stale`` when any readable target changed, else ``unavailable`` when one is unreadable."""
    unavailable = False
    for target, sha in fix.targets:
        try:
            current = target_sha(target)
        except Exception as exc:  # noqa: BLE001 — optional module (pipeline extra)
            _log.debug("%s: %s unavailable: %s", fix.id, target, exc)
            unavailable = True
            continue
        if current != sha:
            _log.warning("%s not applied: %s changed since the fix was validated "
                         "(re-validate it or retire it; docs/scoring-hotfixes.md)", fix.id, target)
            return "stale"
    return "unavailable" if unavailable else "current"


def status(fixes: Sequence[ScoringHotfix] | None = None, *, refresh: bool = False) -> dict[str, str]:
    """``{id: current | stale | unavailable}``; cached per process (``refresh`` recomputes)."""
    fixes = HOTFIXES if fixes is None else fixes
    out: dict[str, str] = {}
    for fix in fixes:
        if not any(fix is f for f in HOTFIXES):  # a caller's candidate never touches the cache
            out[fix.id] = _fix_status(fix)
            continue
        if refresh or fix.id not in _STATUS:
            _STATUS[fix.id] = _fix_status(fix)
        out[fix.id] = _STATUS[fix.id]
    return out


def current_ids() -> frozenset[str]:
    """The fixes whose every target still matches its fingerprint."""
    return frozenset(i for i, s in status().items() if s == "current")


def stale() -> list[str]:
    return sorted(i for i, s in status(refresh=True).items() if s == "stale")


def describe() -> dict[str, Any]:
    """Portable scoring-hotfix identity for run locks: module sha and each fix's fingerprints."""
    return {
        "module_sha256": module_sha256(),
        "fixes": [{"id": f.id, "layer": f.layer,
                   "targets": [{"target": t, "source_sha256": s} for t, s in f.targets]}
                  for f in HOTFIXES],
    }


# --- the on/off switch ------------------------------------------------------------------------

def is_active(fix_id: str) -> bool:
    return fix_id in _ACTIVE.get()


def enabled(fix_id: str) -> bool:
    """A fix that applies outside a scoring call (truth preparation): on whenever it is current."""
    return fix_id in current_ids()


@contextlib.contextmanager
def hotfixed(ids: Sequence[str] | None = None) -> Iterator[frozenset[str]]:
    """Score with the current fixes on (or only ``ids`` among them); yields the ids that are on."""
    install()
    on = current_ids() if ids is None else current_ids() & frozenset(ids)
    token = _ACTIVE.set(on)
    try:
        yield on
    finally:
        _ACTIVE.reset(token)


@contextlib.contextmanager
def raw() -> Iterator[None]:
    """Score as the Dojo pin and the unpatched sandbox code do (every fix off)."""
    token = _ACTIVE.set(frozenset())
    try:
        yield None
    finally:
        _ACTIVE.reset(token)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def merge_dual(raw_payload: Mapping[str, Any], fixed_payload: Mapping[str, Any], active: Sequence[str],
               *, keys: Sequence[str] = HEADLINE_KEYS) -> dict[str, Any]:
    """The hotfixed payload with ``raw_dojo``, ``scoring_hotfixes`` and ``scoring_hotfixes_changed``."""
    out = dict(fixed_payload)
    present = [k for k in keys if k in raw_payload or k in fixed_payload]
    out["raw_dojo"] = {k: raw_payload.get(k) for k in present}
    out["scoring_hotfixes"] = sorted(active)
    out["scoring_hotfixes_changed"] = sorted(
        k for k in present if not _same(raw_payload.get(k), fixed_payload.get(k)))
    return out


def dual(compute: Callable[[], Mapping[str, Any]], *, keys: Sequence[str] = HEADLINE_KEYS) -> dict[str, Any]:
    """Run ``compute`` raw and hotfixed; return the merged dual record."""
    with raw():
        raw_payload = compute()
    with hotfixed() as on:
        fixed_payload = compute()
    return merge_dual(raw_payload, fixed_payload, on, keys=keys)


def headline_basis() -> dict[str, Any]:
    """What a report states about which number is the headline."""
    return {"headline": "hotfixed", "raw_key": "raw_dojo", "fixes_key": "scoring_hotfixes",
            "doc": "docs/scoring-hotfixes.md"}


# --- SHF-002/003/004: field scorers inside the vendored Dojo ---------------------------------

_NAME_IGNORABLE = frozenset({"the", "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "ii", "iii"})


def _name_tokens(text: Any) -> set[str]:
    from llm_dojo_scoring.scoring import field_scoring as fs

    return {t for t in fs._tokenize(fs.normalize_text(text)) if len(t) > 1 and t not in _NAME_IGNORABLE}


def fixed_name_score(original: Callable[..., float], pred: Any, exp: Any, embedding: Any = None) -> float:
    """SHF-002: a strict token subset / superset is a partial match, not 1.0."""
    score = original(pred, exp, embedding=embedding)
    if score < 1.0:
        return score
    tp, te = _name_tokens(pred), _name_tokens(exp)
    if tp and te and tp != te and (tp < te or te < tp):
        return round(len(tp & te) / len(tp | te), 4)
    return score


_ISO = r"USD|EUR|GBP|JPY|CAD|AUD|CHF|CNY|INR|HKD|SGD|MXN|BRL"


def currencies(text: Any) -> set[str]:
    """Explicit currencies a money string states (ISO code or symbol); empty when none."""
    t = str(text or "").upper()
    found = set(re.findall(rf"(?<![A-Z])({_ISO})(?![A-Z])", t))
    for symbol, code in (("€", "EUR"), ("£", "GBP"), ("¥", "JPY")):
        if symbol in t:
            found.add(code)
    for prefix, code in (("US", "USD"), ("C", "CAD"), ("CA", "CAD"), ("A", "AUD"), ("AU", "AUD"),
                         ("HK", "HKD"), ("S", "SGD")):
        if re.search(rf"(?<![A-Z]){prefix}\$", t):
            found.add(code)
    # A bare "$" means USD only when the string states no other currency ("CAD $1,000" is CAD).
    if not found and re.search(r"(?<![A-Z])\$", t):
        found.add("USD")
    return found


def fixed_money_score(original: Callable[..., float], pred: Any, exp: Any, embedding: Any = None) -> float:
    """SHF-003: equal amounts in different stated currencies do not match."""
    score = original(pred, exp, embedding=embedding)
    if score >= 1.0:
        cp, ce = currencies(pred), currencies(exp)
        if cp and ce and cp.isdisjoint(ce):
            return 0.0
    return score


def _compact_id(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def fixed_id_score(original: Callable[..., float], pred: Any, exp: Any, embedding: Any = None) -> float:
    """SHF-004: identifiers equal after dropping punctuation and spacing match."""
    score = original(pred, exp, embedding=embedding)
    if score < 1.0 and _compact_id(pred) and _compact_id(pred) == _compact_id(exp):
        return 1.0
    return score


_FIELD_FIXES = (("score_name_field", "SHF-002", fixed_name_score),
                ("score_money_field", "SHF-003", fixed_money_score),
                ("score_id_field", "SHF-004", fixed_id_score))


def install() -> None:
    """Install the switchable Dojo field-scorer wrappers (idempotent; off unless active)."""
    try:
        from llm_dojo_scoring.scoring import field_scoring as fs
    except Exception as exc:  # noqa: BLE001
        _log.debug("field scorers unavailable: %s", exc)
        return
    with _INSTALL_LOCK:  # the scorer and its FIELD_SCORERS entries are swapped as one step
        _install_field_fixes(fs)


_INSTALL_LOCK = threading.Lock()


def _install_field_fixes(fs: Any) -> None:
    for name, fix_id, fixed in _FIELD_FIXES:
        original = getattr(fs, name)
        if getattr(original, _MARK, None) == fix_id:
            continue

        def make(orig: Callable[..., float], fid: str, fn: Callable[..., float]) -> Callable[..., float]:
            @functools.wraps(orig)
            def wrapper(pred: Any, exp: Any, embedding: Any = None) -> float:
                if is_active(fid):
                    return fn(orig, pred, exp, embedding)
                return orig(pred, exp, embedding=embedding)

            setattr(wrapper, _MARK, fid)
            return wrapper

        wrapper = make(original, fix_id, fixed)
        setattr(fs, name, wrapper)
        for key, value in list(fs.FIELD_SCORERS.items()):
            if value is original:
                fs.FIELD_SCORERS[key] = wrapper


# --- SHF-001: documented absences and hallucination -------------------------------------------

def presence_map(expected: Mapping[str, Any] | None) -> dict[str, str]:
    raw_presence = (expected or {}).get("gt_presence")
    if isinstance(raw_presence, str):
        try:
            raw_presence = json.loads(raw_presence) if raw_presence.strip() else {}
        except json.JSONDecodeError:
            return {}
    return {str(k): str(v) for k, v in (raw_presence or {}).items()} if isinstance(raw_presence, Mapping) else {}


def documented_absent_fields(doc_type: str, expected: Mapping[str, Any] | None) -> list[str]:
    """In-schema fields the truth states are absent (``gt_presence`` documented absence, empty value)."""
    from mailroom_sandbox.eval.extraction_scope import _allowed_fields, is_empty_gt

    allowed = _allowed_fields(doc_type)
    pres = presence_map(expected)
    return sorted(f for f, code in pres.items()
                  if code == DOCUMENTED_ABSENCE and (allowed is None or f in allowed)
                  and is_empty_gt((expected or {}).get(f)))


def restore_documented_absences(doc_type: str, raw_expected: Mapping[str, Any] | None,
                                scoped_expected: dict[str, Any]) -> dict[str, Any]:
    """SHF-001: put the documented-absent fields the scoping seam dropped back as labelled empty."""
    out = dict(scoped_expected)
    for f in documented_absent_fields(doc_type, raw_expected):
        out.setdefault(f, "")
    return out


def hallucination_counts(doc_type: str, raw_expected: Mapping[str, Any] | None,
                         scoped_predicted: Mapping[str, Any]) -> dict[str, Any]:
    """A hallucination is a stated value on a field the truth documents as absent."""
    from mailroom_sandbox.eval.extraction_scope import is_empty_gt

    absent = documented_absent_fields(doc_type, raw_expected)
    hits = [f for f in absent if not is_empty_gt(scoped_predicted.get(f))]
    return {"n_documented_absent": len(absent), "n_hallucinated": len(hits),
            "hallucinated_fields": hits,
            "hallucination_rate": round(len(hits) / len(absent), 4) if absent else None}


# --- SHF-010: truth precedence ----------------------------------------------------------------

def revert_truth_overrides(expected: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """The expected fields as they were before SHF-010 replaced interim values (the raw truth)."""
    out = dict(expected)
    cells = (overrides or {}).get("SHF-010") or {}
    if not cells:
        return out
    pres = presence_map(out)
    for field, cell in cells.items():
        out[field] = cell.get("interim")
        if "interim_presence" in cell:
            pres[field] = cell["interim_presence"]
    if pres:
        out["gt_presence"] = json.dumps(pres, sort_keys=True)
    return out


# --- run-level aggregation helpers ------------------------------------------------------------

def aggregate_extraction(rows: Sequence[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Run-level field F1 (micro over events, and the per-document mean) and hallucination rate."""
    scored = [r for r in rows if r]
    out: dict[str, Any] = {}
    counted = [r for r in scored if all(isinstance(r.get(k), (int, float)) for k in ("tp", "fp", "fn"))]
    if counted:
        tp = sum(int(r["tp"]) for r in counted)
        fp = sum(int(r["fp"]) for r in counted)
        fn = sum(int(r["fn"]) for r in counted)
        out["extraction_tp"], out["extraction_fp"], out["extraction_fn"] = tp, fp, fn
        out["extraction_counts_n"] = len(counted)
        # The Dojo's suite scorers (insurance_claim, contract, ...) return P/R/F1 without event
        # counts, so a micro F1 over the rows that do carry counts would silently cover only some
        # documents. It is reported only when every scored row is counted; the per-document mean
        # (extraction_f1_mean) is the headline otherwise.
        if len(counted) == len(scored):
            p = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            out["extraction_f1_micro"] = round(2 * p * rc / (p + rc), 4) if p + rc else 0.0
        else:
            out["extraction_f1_micro"] = None
            out["extraction_f1_micro_reason"] = f"event counts on {len(counted)} of {len(scored)} scored rows"
    f1s = [float(r["extraction_f1"]) for r in scored if isinstance(r.get("extraction_f1"), (int, float))]
    if f1s:
        out["extraction_f1_mean"] = round(sum(f1s) / len(f1s), 4)
        out["extraction_f1_n"] = len(f1s)
    absent = sum(int(r.get("n_documented_absent") or 0) for r in scored)
    if any("n_documented_absent" in r for r in scored):
        hall = sum(int(r.get("n_hallucinated") or 0) for r in scored)
        out["n_documented_absent"], out["n_hallucinated"] = absent, hall
        out["hallucination_rate"] = round(hall / absent, 4) if absent else None
    return out


def raw_rows(rows: Sequence[Mapping[str, Any] | None]) -> list[dict[str, Any] | None]:
    """Each dual row's raw side (its ``raw_dojo`` values over the hotfixed payload)."""
    out: list[dict[str, Any] | None] = []
    for r in rows:
        if not r:
            out.append(None)
            continue
        counts = ("n_documented_absent", "n_hallucinated", "hallucination_rate")
        base = {k: v for k, v in r.items() if k not in counts}
        # A count the raw pass did not produce stays absent (aggregate_extraction keys on presence).
        base.update({k: v for k, v in (r.get("raw_dojo") or {}).items() if not (k in counts and v is None)})
        out.append(base)
    return out


__all__ = [
    "HOTFIXES", "HEADLINE_KEYS", "ScoringHotfix", "aggregate_extraction", "current_ids", "currencies",
    "describe", "documented_absent_fields", "dual", "enabled", "hallucination_counts", "headline_basis",
    "hotfixed", "install", "is_active", "merge_dual", "module_sha256", "raw", "raw_rows",
    "restore_documented_absences", "revert_truth_overrides", "source_sha", "stale", "status",
]
