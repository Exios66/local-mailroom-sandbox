"""Sandbox scoring hotfixes: fingerprinted, dual-reported corrections to how runs are scored.

The scorer is the vendored Dojo pin (``vendor/llm-dojo-scoring``, never edited) plus the sandbox
code that calls it. A scoring defect the experiments cannot wait for is corrected here, under an
id (``SHF-001`` ...), and never silently:

- **Bound to the code it corrects.** Each fix lists its targets (``module:qualname``) with the
  sha256 of the target's source (``inspect.getsource``) it was validated against,
  ``file:<repo path>`` with the sha256 of a reviewed data file the fix reads, or
  ``value:<module>:<name>`` with the sha256 of a module constant's value (a regex, a set of
  tokens, a dispatch table: it has no source text to hash). When a vendor
  refresh or an edit changes a target, the fix is ``stale``: it is not applied, and
  ``sandbox run preflight`` fails on the ``scoring_hotfixes`` check until the fix is re-validated
  or retired.
- **Dual reported.** A scoring entrypoint scores each row twice, once with every fix off (the raw
  Dojo-pin value, under ``raw_dojo``) and once with the current fixes on (the headline).
  ``scoring_hotfixes`` names the fixes that were on and ``scoring_hotfixes_changed`` the headline
  keys whose value differs, so no number changes without the record saying why.
  A report built on the headline also records :func:`headline_basis`.
- **Recorded in every run lock** (``scoring_hotfixes``: this module's sha256 and each fix's id and
  target fingerprints). A resume refuses a lock whose set differs, and so does the executing
  process; any edit here changes the sha, so a new run locks the new set and an older lock needs
  ``--force`` to re-lock.
- **Tracked upstream.** Each fix names the upstream it belongs to (an llm-dojo-scoring issue,
  D-1 to D-5 filed as Exios66/llm-dojo-scoring#188 to #192, see ``docs/scoring-hotfixes.md``, or
  ``sandbox`` when the defect is in this repository's own scoring code).

Outside a :func:`hotfixed` block every per-row scoring-call fix is off, so a scorer that does not
opt in gets the Dojo pin's behaviour unchanged. The switch is a ``ContextVar``: concurrent scoring
threads never see each other's mode. The other fixes act outside a scoring call and are on whenever
they are current: the run aggregation fixes (SHF-005/006/007/008/011), SHF-010 during truth
preparation (``gold_labels.apply_near_gold``), SHF-009 in the Decisions routing contract
(``decision_backends``), SHF-012 in subclass scoring, SHF-013 in isolated and pipeline subclass
scoring and sorter-arm comparisons, and SHF-015's gate label count. See ``docs/scoring-hotfixes.md``.
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
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

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
             "a5b4378e11861c07c7218913056f7120c280b7a51f985a27669ab68de76fbd1c"),
        ),
        upstream="sandbox (extraction_scope); Dojo D-1, Exios66/llm-dojo-scoring#188",
        summary="a value predicted on a field the truth documents as absent (gt_presence "
                "schema_documented_absence) is a false positive on every class, not only "
                "corporate_record, and is counted as a hallucination",
    ),
    ScoringHotfix(
        id="SHF-002",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_name_field",
                  "2858ef5f4d580f3e7f0f2f4ab220d12b423b299072b595bd306bece00c07787e"),),
        upstream="llm-dojo-scoring D-2, Exios66/llm-dojo-scoring#189",
        summary="a name whose tokens are a strict subset or superset of the truth's (after "
                "legal-suffix, 'the', honorific and initial removal) is a partial match "
                "(token Jaccard), not an exact 1.0",
    ),
    ScoringHotfix(
        id="SHF-003",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_money_field",
                  "25ea35162ccef237c2c7f9aa655c810176305270ac279dcc101c636f1c9b087f"),),
        upstream="llm-dojo-scoring D-3, Exios66/llm-dojo-scoring#190",
        summary="two amounts that state different currencies (code, symbol or name in words) "
                "do not match",
    ),
    ScoringHotfix(
        id="SHF-004",
        layer="dojo",
        targets=(("llm_dojo_scoring.scoring.field_scoring:score_id_field",
                  "4ed5c2db371ebf14f322810f44d6828721e293482a4f9e0badf3bbbcfdbac1c3"),),
        upstream="llm-dojo-scoring D-4, Exios66/llm-dojo-scoring#191",
        summary="identifiers equal once every non-alphanumeric character is removed match "
                "(CLM12345 = CLM-12345)",
    ),
    ScoringHotfix(
        id="SHF-005",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.runners:_isolated_headline",
                  "60bb19972b6a93aa7979413306c914c037dd1fb384995769e52e657f1747717e"),
                 ("mailroom_sandbox.job.runner:_scored_pairs",
                  "7f917c03e3b9b11a0d56bd2c385e877f15bff91ad645bf221c4f0b1b97e78ce0"),
                 ("mailroom_sandbox.rescore:run_scores", "a4a04eb263e02eb2dddd93a8334f3dd1c52b71b5aa0e5f8ea43ee7729345a0a1")),
        upstream="sandbox",
        summary="a row that errored (timeout, parse failure, crash) scores 0 in the run "
                "headline instead of leaving the denominator (isolated evals, the job-runner "
                "sorter and a rescore's scores.json)",
    ),
    ScoringHotfix(
        id="SHF-006",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.runners:_isolated_headline",
                  "60bb19972b6a93aa7979413306c914c037dd1fb384995769e52e657f1747717e"),
                 ("mailroom_sandbox.job.runner:_scored_pairs", "7f917c03e3b9b11a0d56bd2c385e877f15bff91ad645bf221c4f0b1b97e78ce0")),
        upstream="sandbox",
        summary="a row with no truth to score is left out of the run mean and counted "
                "(n_no_truth) instead of averaging in as 0 (isolated evals and the job-runner "
                "sorter)",
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
                  "63b7b99518c62b86292eb7d05deac93cce40123b36a43dffac28dab40e796984"),
                 # the job-runner sorter scores folded labels and leaves no-truth rows out
                 ("mailroom_sandbox.job.runner:_scored_pairs", "7f917c03e3b9b11a0d56bd2c385e877f15bff91ad645bf221c4f0b1b97e78ce0")),
        upstream="sandbox",
        summary="class labels compare case-, hyphen- and whitespace-folded; a row without a "
                "truth class is unscored, not a match; an abstention is its own outcome "
                "(abstain=True, scored wrong, routed to review); the job-runner sorter "
                "folds and leaves no-truth rows out the same way",
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
                  "5126802652669b3987eceb3e33ebc40c4d2c95492c3247e8c26fc0c8e2f25d61"),),
        upstream="sandbox (decision_backends.decide)",
        summary="question set 4.0.0's document_form, abstain, subclass_gate and "
                "truncation_notice keys are applied: an abstention parks the document "
                "(route_to_human), keep_sorter parks when no same-class sorter subclass is "
                "available, and the forced-choice answer is kept under forced_choice",
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
        # Phase 2 moved the item dict (with the subclass fields) out of _run_pipeline_doc_once into
        # _pipeline_item, unchanged; both are pinned. Re-validated for Phase 5 part 1, which adds the
        # attempt-history keys (ATTEMPT_FIELDS) to the item and leaves the subclass fields as they were.
        targets=(("mailroom_sandbox.eval.runners:_run_pipeline_doc_once",
                  "d70b7b72372c0b96721ffe72a1b4ec75d1ae09869bffeeefd2824497ba6e3104"),
                 ("mailroom_sandbox.eval.runners:_pipeline_item",
                  "8b59b3414d32158d7c4e715d4df15fd2a047e3eb37d0f5b5b1c65b18a7569385"),
                 ("mailroom_sandbox.eval.scoring:predicted_subclass",
                  "f692ca8d94ccdf8cc04ec35b8a40e3508c4ace9da0c3a5dbc5ab3b521d059451"),
                 ("mailroom_sandbox.eval.scoring:score_subclass",
                  "323799a47d90bc2bc648aac98bf5d218e3e13fcfced074f67efacfaa3c2100ed")),
        upstream="sandbox (the Dojo's pipeline_subclass_match ignores the class: D-5, "
                 "Exios66/llm-dojo-scoring#192)",
        summary="pipeline items record the final sorter/reviewer subclass and score it joint with the "
                "class on the canonical subclass token (normalize_corpus_subclass), not the Dojo's "
                "class-blind raw-string match",
    ),
    ScoringHotfix(
        id="SHF-013",
        layer="sandbox",
        targets=(("mailroom_sandbox.eval.scoring:sorter_subclass_row",
                  "37caf94d1d496885350500ac13164b5c94125ceb3eb7df6b626a974c52649ad0"),
                 ("mailroom_sandbox.eval.scoring:sorter_subclass_scores",
                  "bd8cf8c068f34108b2bca7dfc2eeb0110c4183cbec29797feb791df72d925b9f"),
                 # the pipeline item and run-level subclass scores take the same corrections
                 ("mailroom_sandbox.eval.scoring:corrected_subclass_truth", "27cf68dd20c665c87e7f56948570a3748c7b345435a99de0d60e7114c0dc6cfc"),
                 ("mailroom_sandbox.eval.scoring:subclass_correct", "630d2adcfe049b3b9004dc69854298bfb2415d7a2b4eeedbec21339f40bfbcd5"),
                 ("mailroom_sandbox.eval.scoring:score_subclass", "323799a47d90bc2bc648aac98bf5d218e3e13fcfced074f67efacfaa3c2100ed"),
                 # the reviewed truth corrections are part of what the fix scores against
                 ("file:data/labels/review/subclass_corrections.jsonl",
                  "266304cedebadb469c1c212f0328da9c5852d9558705114f4a0a8a06210baaa3")),
        upstream="sandbox (isolated sorter / sorter_reviewer runs scored doc_type only; reviewed "
                 "subclass corrections in data/labels/review/subclass_corrections.jsonl)",
        summary="isolated sorter and sorter_reviewer runs score the subclass joint with the class on the "
                "canonical subclass token (subclass_scored, subclass_match, subclass_by_class); a reviewed "
                "subclass correction replaces the Hub truth for subclass and unit scoring, and for the "
                "pipeline's per-item subclass_correct and run-level subclass scores (SHF-012 side), the "
                "Hub-truth figures stay under raw_dojo and the corrected documents are counted "
                "(subclass_corrections_applied)",
    ),
    ScoringHotfix(
        id="SHF-015",
        layer="sandbox",
        targets=(
            # the seam that strips intent_source, so the Dojo suite never sees a heuristic label
            ("mailroom_sandbox.eval.extraction_scope:applicable_expected_fields", "44f03a946787e5fb19ba817fd2df4c22e32afab23c268b93944f9e8d5ee4dd15"),
            ("mailroom_sandbox.eval.scoring:score_extraction_row", "71d73e914c9fd31ec17a82313c6819b4b4290df7d0d27dcd64ff00961c2f517f"),
            # the Dojo's label policy decides which Hub labels are stale, and what it calls is pinned too:
            # a function by its source, a constant by its value (a refresh or SANDBOX_DOJO_SNAPSHOT that
            # changes one of them makes the fix stale). A live monkeypatch of a function is not source
            # drift and is not seen. tests/test_scoring_hotfix_fingerprint.py walks the call graph and
            # fails when a callee is missing here.
            ("llm_dojo_scoring.schemas.corporate_record_schema:_keywords", "a651ec0dc05054218d9ad7e47bcb1dfd9ed9f8606062095ce29cec40b764d440"),
            ("llm_dojo_scoring.schemas.correspondence_gt_audit:_keyword_list", "86679982c9b3fca87449aa953b8a7f3ab1a5b3e6aaa0628febd4c25f01b012ce"),
            ("llm_dojo_scoring.schemas.correspondence_gt_audit:_norm_token", "3250fe41754b808b2ebeafb264b42d6a84822a1451494da87daf451a9281438d"),
            ("llm_dojo_scoring.schemas.correspondence_gt_audit:is_templated_subject_matter", "13c32d90add368aa1428a526c0647c8000f153085eb30c0837a2bdb32bea1a98"),
            ("llm_dojo_scoring.schemas.correspondence_gt_audit:metadata_keyword_kind", "e50d0a4959fe4891083fbf64a9c134921b2274f4f71db8c54a77f2a6acbebd66"),
            ("llm_dojo_scoring.schemas.gt_metadata:is_empty_value", "2ce53a21d97504cd3d23be843be571f270e7dfaa0c4e806c15f6feeedfcbe0cf"),
            ("llm_dojo_scoring.schemas.gt_metadata:parse_gt_fields", "2110f6425b2a6a2fe9dcedf40215c629e481d9e7e9839cd4b7fe090eebe007bd"),
            ("llm_dojo_scoring.schemas.gt_metadata:parse_json_container", "7659a64ece4fa57f9b88caa33744e0aa2b90a845d2e24ab9f759df0a2b0d7885"),
            ("llm_dojo_scoring.schemas.label_policy:_class", "45d438fc79c5f28cda61df07b3aedd2c7aa25277523ceda6e2b743d7867ba9d6"),
            ("llm_dojo_scoring.schemas.label_policy:_corporate_stale", "65de264759beb5b282dc79cbe69d2dc1a5c3fdba7a5ae52ca83a1526d7d0fe6c"),
            ("llm_dojo_scoring.schemas.label_policy:_correspondence_stale", "af434deecfe68e0153549d06011e14220217ea9605f7c7010bac0f7040f92990"),
            ("llm_dojo_scoring.schemas.label_policy:_fields", "1330ec0d50c6e371283a5c9d18675abe5136742ffb3ba4ffbc0d6680265d41f1"),
            ("llm_dojo_scoring.schemas.label_policy:stale_hub_labels", "3e8141ca126dcf8df58defa78e18f0f1a35ee833cfe53c0d9828333b7301fdbd"),
            ("value:llm_dojo_scoring.schemas.corporate_record_schema:_CIK_KEYWORD", "b1f91ef1f1f428b9abaee509679408bc66032a725c57399978514e89acf1114f"),
            ("value:llm_dojo_scoring.schemas.corporate_record_schema:_ID_KEYWORD", "72cb0568e72cbff1ac05e07a287146a167e2a205896716de6111af98b6e07fb2"),
            ("value:llm_dojo_scoring.schemas.corporate_record_schema:_TEMPLATE_MARK", "928549eb271fe98a6f8c6cae549c63684e262f38eb182ff191fe0532529dfe71"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_COMMUNICATION_TYPES", "59c43d6a5942ff13a11cc71b1538dcbe603c29db8da3854985bfdce78e02e72c"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_CONTENT_LIKE_FOLDERS", "cf7c116d050f34ff98ca388870da85ccd59b34bab20d0d9211d02514f007fffc"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_DATE_OR_TIME", "c8415f3aef32a226981c44bb4c985aa62e9b2a0f0ec6aa63df8aa88c03e5ef58"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_EMAIL", "750d61faddfa542c367f4cc505c9dced6846b9ae488eaef30346899c00df9575"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_FOLDER_NAMES", "4b48410321f98f66b09562e0bd8898368f16a92a8c95338d960ea617814d4f2f"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_MAILBOX_ID", "5e92ca8075beb1a6eb7be6d695dab38913c868c1e8907a5b8aad40b858b73d23"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_SNAKE_TOKEN", "a7cf2b12dd54a86bb54dab12dbeeb0a834225dd1f9ef80921a27e3d0261620fd"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_TEMPLATE_FRAME", "1ee500b686d47bad993ce9f84e37ce0a2a15bb97eadc6c6026475d7dedf9ba0e"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_TIMESTAMP", "f1649d013d3d3c075f889fbeb709f03383f67a740e5bbbbe4bc4ee564319adf7"),
            ("value:llm_dojo_scoring.schemas.correspondence_gt_audit:_TOPIC_KEYS", "0968d3d06ffcbeb417935bc920c2c03c8a8064e203d47aba3ef1b9eb74babed0"),
            ("value:llm_dojo_scoring.schemas.gt_metadata:_NULL_TOKENS", "bf830f6ef10243a290dd314059c18cf88f3e63dbbfffb0596141e0305a9575c1"),
            ("value:llm_dojo_scoring.schemas.label_policy:_CLASS_STALE", "12804f1a0436320192b191eb25de0fdb78f9618c2fc3a9345702ce46b428a8a9"),
            ("llm_dojo_scoring.schemas.label_policy:drop_stale_hub_labels", "b6a53e1612a658f6a9a1d25f0a386a02a968f9aed304aaeb841a0cb4f963211c"),
            # the gate counts toward min_labelled only the labels the headline scores
            ("mailroom_sandbox.job.gate:labelled_count", "b3bc1a48335464a5f08cbae2e07573cba79e0d97259a79a2661a881a8b0742a8"),
        ),
        upstream="sandbox (the sandbox seam bypasses the Dojo label policy, llm-dojo-scoring #164 / #171 / "
                 "#94, shipped in the pin as label_policy.drop_stale_hub_labels)",
        summary="the headline drops the Hub labels the Dojo's label policy calls stale (a heuristic intent; "
                "templated correspondence and corporate subject_matter / metadata keywords) from both sides, "
                "so a correct answer is not scored against a template; an overlay keeps a heuristic intent "
                "(a reviewed intent leaves intent_source heuristic) and does not keep a value the policy "
                "still calls a template or metadata keywords; a corporate title that is exactly one keyword "
                "of the other is dropped too; the dropped fields are named (stale_hub_labels); the gate "
                "does not count a dropped label toward min_labelled",
    ),
    ScoringHotfix(
        id="SHF-016",
        layer="sandbox",
        targets=(
            ("mailroom_sandbox.eval.scoring:_score_extraction_row_once", "58a46935f75805f9b6da6475982e169e1efd01e5fa8ced2e32acf0aa6c660165"),
            # the Dojo reader decides the row's labeled universe; a refresh that changes it
            # makes the fix stale
            ("llm_dojo_scoring.pipeline.sandbox_scoring:gt_categories", "fe6ed3ae11a363c4da325c197442db393bbc052bb6ec3707cd1b263d48feb716"),
            ("llm_dojo_scoring.pipeline.sandbox_scoring:score_cuad", "8c30a637efbf0139bd12bf6283dff62507223ce7e8d90183692854d16a07f106"),
        ),
        upstream="sandbox",
        summary="a contract row whose CUAD label map names no category keeps the suite field "
                "headline (the reviewed interim / near-gold field labels merged at truth prep "
                "stand in where the Hub supplied none) instead of the empty-universe CUAD F1 "
                "that left the row unscoreable; the row is marked cuad_unlabeled and the "
                "raw side keeps the Dojo pin's None",
    ),
)

_BY_ID = {fix.id: fix for fix in HOTFIXES}
#: The fixes a row extraction score can depend on.
EXTRACTION_FIXES = frozenset({"SHF-001", "SHF-002", "SHF-003", "SHF-004", "SHF-010", "SHF-015", "SHF-016"})
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


FILE_TARGET = "file:"
_PACKAGE_PREFIX = "src/mailroom_sandbox/"


def data_path(rel: str) -> Path | None:
    """A repository data file a fix reads (``file:`` targets): the source checkout, else ``SANDBOX_ROOT``.

    The checkout copy is found next to this package (``src/mailroom_sandbox``); the Modal job worker
    bundles the file under its ``SANDBOX_ROOT`` (``deploy/modal_job.py``). A target inside the package
    itself (``src/mailroom_sandbox/...``) is also looked up relative to the imported package, because
    the worker image and a wheel install ship the package with no ``src/`` directory around it.
    """
    from mailroom_sandbox.paths import repo_root

    package = Path(__file__).resolve().parent
    candidates = [package.parents[1] / rel, repo_root() / rel]
    if rel.startswith(_PACKAGE_PREFIX):
        candidates.append(package / rel[len(_PACKAGE_PREFIX):])
    return next((path for path in candidates if path.is_file()), None)


VALUE_TARGET = "value:"


def _canonical(value: Any) -> str:
    """A stable text form of a constant: sets and mappings sorted, a regex as pattern plus flags."""
    if isinstance(value, re.Pattern):
        return f"re({value.pattern!r}, {int(value.flags)})"
    if isinstance(value, (set, frozenset)):
        return "set(" + ",".join(sorted(_canonical(v) for v in value)) + ")"
    if isinstance(value, Mapping):
        return "map(" + ",".join(sorted(f"{_canonical(k)}:{_canonical(v)}" for k, v in value.items())) + ")"
    if isinstance(value, (list, tuple)):
        return type(value).__name__ + "(" + ",".join(_canonical(v) for v in value) + ")"
    if callable(value):  # a dispatch table lists functions: name them, never print an address
        return f"callable({getattr(value, '__module__', '')}:{getattr(value, '__qualname__', repr(value))})"
    return repr(value)


def value_sha(value: Any) -> str:
    """sha256 of :func:`_canonical` ``(value)``: what a ``value:`` target records."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def target_sha(target: str) -> str:
    if target.startswith(VALUE_TARGET):
        # The live value, not file text: a constant has no source of its own and may be derived from
        # another module's data (``frozenset(CORRESPONDENCE_TOPICS)``), so its value is what decides.
        return value_sha(_resolve(target[len(VALUE_TARGET):]))
    if target.startswith(FILE_TARGET):
        path = data_path(target[len(FILE_TARGET):])
        if path is None:
            raise FileNotFoundError(target)
        return hashlib.sha256(path.read_bytes()).hexdigest()
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


def changed_keys(raw_payload: Mapping[str, Any], fixed_payload: Mapping[str, Any],
                 keys: Iterable[str]) -> list[str]:
    """The ``keys`` whose hotfixed value differs from the raw Dojo-pin value (NaN equals NaN)."""
    return sorted(k for k in keys if not _same(raw_payload.get(k), fixed_payload.get(k)))


def merge_dual(raw_payload: Mapping[str, Any], fixed_payload: Mapping[str, Any], active: Sequence[str],
               *, keys: Sequence[str] = HEADLINE_KEYS) -> dict[str, Any]:
    """The hotfixed payload with ``raw_dojo``, ``scoring_hotfixes`` and ``scoring_hotfixes_changed``."""
    out = dict(fixed_payload)
    present = [k for k in keys if k in raw_payload or k in fixed_payload]
    out["raw_dojo"] = {k: raw_payload.get(k) for k in present}
    out["scoring_hotfixes"] = sorted(active)
    out["scoring_hotfixes_changed"] = changed_keys(raw_payload, fixed_payload, present)
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


_ISO = r"USD|EUR|GBP|JPY|CAD|AUD|NZD|CHF|CNY|INR|HKD|SGD|MXN|BRL"


# Currency names a money string can state in words. A bare "pound(s)" is left out (a weight), and a
# bare "dollar(s)" means USD only when nothing else is stated, as a bare "$" does. A qualified dollar
# names its own currency: Canadian, Australian, Hong Kong, New Zealand and Singapore dollars, before
# or after the word ("1,000 dollars Canadian") and by abbreviation ("HK dollars").
_CURRENCY_WORDS = (
    (r"EUROS?", "EUR"), (r"(?:POUNDS?\s+)?STERLING|BRITISH\s+POUNDS?", "GBP"), (r"YEN", "JPY"),
    (r"U\.?S\.?\s+DOLLARS?", "USD"),
    (r"(?:CANADIAN|CA)\s+DOLLARS?|DOLLARS?\s+CANADIAN", "CAD"),
    (r"(?:AUSTRALIAN|AU)\s+DOLLARS?|DOLLARS?\s+AUSTRALIAN", "AUD"),
    (r"(?:HONG\s+KONG|HK)\s+DOLLARS?|DOLLARS?\s+HONG\s+KONG", "HKD"),
    (r"(?:NEW\s+ZEALAND|NZ)\s+DOLLARS?|DOLLARS?\s+NEW\s+ZEALAND", "NZD"),
    (r"(?:SINGAPORE|SG)\s+DOLLARS?|DOLLARS?\s+SINGAPORE", "SGD"),
)


# Adjectives that qualify a dollar sign when they stand right before it ("Canadian $5,000").
_DOLLAR_ADJECTIVES = (
    (r"U\.?S\.?", "USD"), (r"CANADIAN", "CAD"), (r"AUSTRALIAN", "AUD"), (r"HONG\s+KONG", "HKD"),
    (r"NEW\s+ZEALAND", "NZD"), (r"SINGAPORE", "SGD"),
)


def currencies(text: Any) -> set[str]:
    """Explicit currencies a money string states (ISO code, symbol or name); empty when none.

    A ``$`` takes the currency of a prefix attached to it (``C$``, ``HK$``) or of an adjective right
    before it (``US $``, ``Canadian $``, ``Hong Kong $``). Any other ``$``, and a bare "dollars",
    reads as USD only when the string states no other currency: beside one it adds nothing
    (``CAD $1,000`` and ``$1,000 CAD`` are CAD, ``$1,000 (approx. EUR 900)`` is EUR).
    """
    t = str(text or "").upper()
    found = set(re.findall(rf"(?<![A-Z])({_ISO})(?![A-Z])", t))
    for symbol, code in (("€", "EUR"), ("£", "GBP"), ("¥", "JPY")):
        if symbol in t:
            found.add(code)
    for word, code in _CURRENCY_WORDS:
        if re.search(rf"(?<![A-Z])(?:{word})(?![A-Z])", t):
            found.add(code)
    for prefix, code in (("US", "USD"), ("C", "CAD"), ("CA", "CAD"), ("A", "AUD"), ("AU", "AUD"),
                         ("HK", "HKD"), ("NZ", "NZD"), ("S", "SGD")):
        if re.search(rf"(?<![A-Z]){prefix}\$", t):
            found.add(code)
    # A currency adjective right before the sign names the dollar, with up to two spaces between:
    # "US $5,000", "Canadian $5,000". Only the whole word, never a single letter or a state code
    # ("Plan A $5,000", "San Jose, CA $5,000" stay a plain dollar).
    for adjective, code in _DOLLAR_ADJECTIVES:
        if re.search(rf"(?<![A-Z])(?:{adjective})\s{{0,2}}\$", t):
            found.add(code)
    # A bare "$" or "dollars" means USD only when the string states no other currency ("CAD $1,000" is CAD).
    if not found and re.search(r"(?<![A-Z])\$|(?<![A-Z])DOLLARS?(?![A-Z])", t):
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


# --- SHF-015: stale Hub labels are not truth ---------------------------------------------------

#: The row markers each label overlay writes, naming the fields it supplied (``interim_labels``,
#: ``gold_labels.apply_near_gold``, ``staged_overlay``); ``gold_audit.label_source`` reads the same.
OVERLAY_MARKERS: tuple[str, ...] = ("interim_labels", "near_gold_labels", "staged_overlay")
_PENDING = "pending_annotation"


def overlay_fields(row: Mapping[str, Any] | None) -> frozenset[str]:
    """The fields a label overlay (interim, near-gold or staged) supplied on this prepared row.

    Read from the markers the overlays write (a mapping, or the JSON string a parquet shard
    carries). A staged row marked ``stale`` lists no field. Same provenance as
    ``gold_audit.label_source`` / ``job.gate_causes._overlay_supplied``.
    """
    out: set[str] = set()
    for key in OVERLAY_MARKERS:
        marker = (row or {}).get(key)
        if isinstance(marker, str):
            try:
                marker = json.loads(marker) if marker.strip() else None
            except json.JSONDecodeError:
                marker = None
        if isinstance(marker, Mapping):
            fields = marker.get("fields") or ()
            if isinstance(fields, str):  # one field name, never its characters
                fields = (fields,)
            elif not isinstance(fields, (list, tuple, set, frozenset)):
                fields = ()
            out.update(str(f) for f in fields)
    return frozenset(out)


#: Stale reasons an overlay listing may keep. A reviewed intent still carries
#: ``intent_source: heuristic``, so that reason alone is not proof the value is the Hub template.
_OVERLAY_KEEP_REASONS = frozenset({"intent_heuristic"})


def _keyword_strings(value: Any) -> list[str]:
    """Keyword texts from a list or a JSON list string. Other strings stay one keyword."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return [text] if text else []
        else:
            return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _record_title_templates(doc_type: str, fields: Mapping[str, Any]) -> dict[str, str]:
    """Corporate titles that are exactly ``<keyword> of <keyword>`` and nothing else.

    The Dojo's corporate template mark is the SEC EDGAR exhibit note, so a Hub title such as
    ``Charter amendment of ARTES MEDICAL INC.`` with those two strings as its keywords stays
    scored. The production slice's corporate rows are all this shape. A real summary does not
    equal the two keywords joined by ``of``.
    """
    if str(doc_type or "").strip() != "corporate_record":
        return {}
    keywords = _keyword_strings(fields.get("keywords"))
    subject = str(fields.get("subject_matter") or "").strip()
    if len(keywords) != 2 or not subject:
        return {}
    left, right = keywords
    titles = {f"{left} of {right}", f"{left} of {right}.", f"{right} of {left}", f"{right} of {left}."}
    if subject not in titles:
        return {}
    return {"subject_matter": "subject_matter_record_title", "keywords": "keywords_record_title"}


def drop_stale_hub_truth(doc_type: str, expected: Mapping[str, Any] | None,
                         keep: Iterable[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """SHF-015: ``(expected, dropped)`` with the Hub labels the Dojo's label policy calls stale removed.

    The policy is the vendored ``llm_dojo_scoring.schemas.label_policy.stale_hub_labels``: a
    heuristic ``intent`` (``intent_source == "heuristic"``), and the templated ``subject_matter`` /
    metadata ``keywords`` of corporate records and correspondence. An overlay listing keeps a
    field only when its stale reason is ``intent_heuristic`` (a reviewed intent leaves that
    source flag). A template or metadata-keyword value the policy still names is dropped even
    if the overlay lists the field: the staged overlay often only strips a mailbox path and
    leaves the topic tag. A corporate record-title pair is dropped the same way. A dropped
    field's ``gt_presence`` code becomes ``pending_annotation`` (unlabelled), as
    ``drop_stale_hub_labels`` does, so SHF-001 never restores it as an expected-empty field.
    """
    from llm_dojo_scoring.schemas.label_policy import stale_hub_labels

    out = dict(expected or {})
    kept = set(keep)
    found = stale_hub_labels(doc_type, out)
    if not isinstance(found, Mapping):  # no stale labels (None or any other shape), never an error
        found = {}
    found = dict(found)
    found.update(_record_title_templates(doc_type, out))
    dropped = {f: why for f, why in found.items()
               if f not in kept or why not in _OVERLAY_KEEP_REASONS}
    if not dropped:
        return out, {}
    for name in dropped:
        out.pop(name, None)
    if "gt_presence" in out:
        original = out["gt_presence"]
        pres = presence_map(out)
        pres.update(dict.fromkeys(dropped, _PENDING))
        out["gt_presence"] = json.dumps(pres, sort_keys=True) if isinstance(original, str) else pres
    return out, dict(sorted(dropped.items()))


# --- SHF-013: reviewed subclass corrections ----------------------------------------------------

SUBCLASS_CORRECTIONS = "data/labels/review/subclass_corrections.jsonl"
_CORRECTIONS_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def _pinned_corrections_sha() -> str | None:
    """The sha256 SHF-013's fingerprint pins for the corrections file, or None."""
    target = f"file:{SUBCLASS_CORRECTIONS}"
    for fix in HOTFIXES:
        for name, sha in fix.targets:
            if name == target:
                return sha
    return None


def subclass_corrections() -> dict[str, dict[str, Any]]:
    """``{doc_id: entry}`` of the reviewed subclass corrections whose ``verdict`` is ``correct``.

    ``held`` and ``rejected`` entries are recorded but not applied. Empty when the file is missing
    (SHF-013 is then ``unavailable`` and not applied either). The bytes parsed are the bytes checked:
    the file is read once, its sha256 must equal SHF-013's pinned fingerprint, and the parsed table
    is cached by that hash. A file edited after SHF-013 was validated raises instead of feeding new
    truth to a run that reports the old fingerprint, and so does a file that disappears after
    SHF-013 was validated as current.
    """
    path = data_path(SUBCLASS_CORRECTIONS)
    if path is None or not path.is_file():
        if _STATUS.get("SHF-013") == "current":
            # validated as present, now gone: Hub truth here would disagree with the scores already
            # recorded under SHF-013, so stop rather than score silently without the corrections
            raise RuntimeError(f"{SUBCLASS_CORRECTIONS} disappeared after SHF-013 was validated; restore it")
        return {}
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pinned = _pinned_corrections_sha()
    if pinned is not None and digest != pinned:
        raise RuntimeError(f"{SUBCLASS_CORRECTIONS} changed since SHF-013 was validated "
                           f"(sha256 {digest[:12]}, pinned {pinned[:12]}); re-review it and update the fingerprint")
    if digest not in _CORRECTIONS_CACHE:
        entries: dict[str, dict[str, Any]] = {}
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("verdict") != "correct":
                continue
            if str(entry["doc_id"]) in entries:
                raise ValueError(f"{SUBCLASS_CORRECTIONS}: {entry['doc_id']} is corrected twice")
            entries[str(entry["doc_id"])] = entry
        _CORRECTIONS_CACHE.clear()
        _CORRECTIONS_CACHE[digest] = entries
    return _CORRECTIONS_CACHE[digest]


def corrected_subclass(doc_id: Any, doc_class: Any, hub_subclass: Any) -> str | None:
    """SHF-013: the reviewed subclass that replaces the Hub truth of one document, or None.

    Applied only when the correction names the row's class and the Hub value it was reviewed
    against (canonical tokens), so a Hub relabel or a different class never takes a stale fix.
    """
    from mailroom_sandbox.experiment_splits import _subclass_token

    entry = subclass_corrections().get(str(doc_id or ""))
    if not entry or str(entry.get("doc_class")) != str(doc_class or ""):
        return None
    cls = str(doc_class)
    if _subclass_token(cls, entry.get("hub_subclass")) != _subclass_token(cls, hub_subclass):
        return None
    return str(entry["subclass"])


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
    "HOTFIXES", "HEADLINE_KEYS", "SUBCLASS_CORRECTIONS", "ScoringHotfix", "aggregate_extraction",
    "corrected_subclass", "current_ids", "currencies", "data_path", "describe", "documented_absent_fields",
    "drop_stale_hub_truth", "dual", "enabled", "hallucination_counts", "headline_basis",
    "subclass_corrections", "hotfixed", "install", "is_active", "merge_dual", "module_sha256",
    "overlay_fields", "raw", "raw_rows", "restore_documented_absences", "revert_truth_overrides",
    "source_sha", "stale", "status",
]
