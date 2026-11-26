"""Offline harness: one document through the real compiled graph, with the judge and arbiters real.

Network-free and model-free. The sorter and specialist nodes are scripted. The judge
(``judge_verify``), the extraction arbiter (``arbiter``) and the classification arbiter
(``classification_arbiter``) nodes run as vendored, with their agents' model call
(``_call_structured``) answered by a per-call policy, so their prompts, schemas, guardrails and
the sandbox hotfixes all take part. Intake, human review, report, catalog, archive and the
SQLite checkpoint are real. A decision reviewer can be registered with its HTTP transport down,
so the decision lane's retry loop (``decision_backends._post_decision``) runs for real.

Used by the ``test_arbiter_*`` modules. Each applies ``pytestmark = pytest.mark.usefixtures("arbiter_harness_state")``
(imported from here): ``activate_profile`` and ``run`` rebuild the process-wide compiled graph and widen the
vendored source windows, and neither is undone by ``monkeypatch``, so the fixture puts both back after every test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

MODEL_NODES = ("classify", "retry_classify", "review_classify", "extract", "retry_extract", "boss_escalation")
REAL_NODES = ("intake", "judge_verify", "arbiter", "classification_arbiter", "human_review",
              "compile_report", "catalog_write", "archive")
#: No document may visit more nodes than this, whatever the judge and the arbiter answer.
VISIT_BOUND = 40
HIGH = 0.995
DATA = {"entity_name": "Cedar Sample Ltd", "record_type": "minutes", "confidence": 0.99}
_LINE = "Cedar Sample Ltd board minutes, item {n}: the directors adopt the annual budget.\n"
SHORT = _LINE.format(n=1)
#: Over the vendored 16k judge/arbiter excerpts, inside every fitted OpenRouter window.
LONG = "".join(_LINE.format(n=n) for n in range(3000))
REVIEWER = {"backend": "decisions", "model": "openai/gpt-6-luna-decisions",
            "questions": "reviewer_decisions_v4.2.0", "classes": {"corporate_record": 0.9}}


@pytest.fixture
def arbiter_harness_state(monkeypatch):
    """Leave the compiled graph and the vendored source windows as the test found them.

    ``monkeypatch`` undoes ``bg.<node>_node``, but the module-level compiled graph keeps the scripted
    wrappers it was built from, and ``apply_source_windows`` rewrites vendored constants directly.
    Without this, a later test in the same process (``test_mock_llm``) runs the scripted graph.
    """
    import graph.build_graph as bg

    from mailroom_sandbox import source_windows

    bg.reset_compiled_graph()
    yield
    bg.reset_compiled_graph()
    source_windows.apply_source_windows({})


class Blip(RuntimeError):
    """A transient provider error (the harness marks it retryable)."""


@dataclass
class Script:
    doc: str = SHORT
    sorter: float | None = HIGH          # None: medium band, so the reviewer runs
    confs: list[float] = field(default_factory=lambda: [0.95])
    extract_extra: dict[str, Any] = field(default_factory=dict)  # merged into every extraction update
    # per judge pass: (completeness_label, accuracy_label), "parse_c", "parse_a" or "blip"
    judge: list[Any] = field(default_factory=lambda: [("complete", "accurate")])
    arbiter: list[str] = field(default_factory=list)   # per call: a decision or "blip"
    carb: tuple[str, float] | None = None              # classification arbiter answer
    decisions_down: bool = False                       # registered decision reviewer, transport down
    deadline_passed: bool = False                      # the run deadline has already passed
    # The sorter / specialist refuses the document (HF-010 / HF-009 on an API route): the real
    # classify / extract nodes run and meet this error from the reader they call.
    classify_raises: Exception | None = None
    extract_raises: Exception | None = None
    # Every extraction reports a matter conflict, which the Boss adjudicates:
    # "approve" (fingerprinted approval), "reject", or "blip" (a transient error each time).
    conflict: bool = False
    boss: str = "approve"
    # HF-014 confidence floor, as a run's confidence block would set it (None: the class ``low``).
    floor: float | None = None


def activate_profile(monkeypatch, tmp_path, profile: str, *, reviewer: bool = False):
    """Activate ``profile`` as a run would (``modal-vllm`` or ``openrouter``); return graph.build_graph."""
    from mailroom_sandbox.runtime import activate

    monkeypatch.setattr("mailroom_sandbox.runtime._load_dotenv", lambda: None)
    monkeypatch.setenv("MAILROOM_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    monkeypatch.setenv("MAILROOM_CHECKPOINTER", "sqlite")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER", "none")
    for flag in ("MAILROOM_RELATIONS", "MAILROOM_RELATIONS_EMBEDDINGS", "MAILROOM_BERT_INTAKE",
                 "MAILROOM_LLM_INTAKE", "MAILROOM_LLM_CACHE"):
        monkeypatch.setenv(flag, "0")
    activate(profile, load_env_file=False, reviewer=REVIEWER if reviewer else None)
    import graph.build_graph as bg

    bg.reset_compiled_graph()
    return bg


def run(bg, monkeypatch, script: Script) -> dict[str, Any]:
    """Run one document under ``script``; return what happened (stage, path, calls, prompts, state)."""
    import llm.retry as retry
    from agents.arbiter import ArbiterAgent
    from agents.judge import CompletenessJudge
    from pipeline.bins import inbox_dir
    from pipeline.config import oracle_routing_override

    monkeypatch.setattr("agents.base.get_llm", lambda *a, **k: (MagicMock(), "harness-model"))
    original_transient = retry.is_transient_error
    monkeypatch.setattr(retry, "is_transient_error",
                        lambda exc: isinstance(exc, Blip) or original_transient(exc))
    calls: dict[str, Any] = {"judge_c": 0, "judge_a": 0, "arbiter": 0, "carb": 0, "decisions_posts": 0, "boss": 0,
                             "arbiter_prompts": [], "arbiter_schemas": []}
    passes = {"n": 0}

    def pick(policy: list[Any], i: int) -> Any:
        return policy[min(i, len(policy) - 1)]

    def judge_call(self, user_message, *a, **k):
        if user_message.startswith("Evaluate extraction completeness"):
            calls["judge_c"] += 1
            passes["n"] += 1
            policy = pick(script.judge, passes["n"] - 1)
            if policy == "blip":
                raise Blip("provider blip")
            if policy == "parse_c":
                return {"_raw": "garbage", "_parse_error": True}
            label = "complete" if policy == "parse_a" else policy[0]
            return {"completeness": 0.9, "completeness_label": label, "reasoning": "harness"}
        calls["judge_a"] += 1
        policy = pick(script.judge, passes["n"] - 1)
        if policy == "parse_a":
            return {"_raw": "garbage", "_parse_error": True}
        return {"extraction_correctness": 0.9, "extraction_correctness_label": policy[1] or "inaccurate",
                "reasoning": "harness"}

    def arbiter_call(self, user_message, schema=None, *a, **k):
        if "SORTER ANSWER" in user_message:
            calls["carb"] += 1
            decision, conf = script.carb or ("human_review", 0.0)
            return {"decision": decision, "confidence": conf, "reasoning": "harness"}
        i = calls["arbiter"]
        calls["arbiter"] += 1
        calls["arbiter_prompts"].append(user_message)
        calls["arbiter_schemas"].append(schema)
        decision = pick(script.arbiter or ["human_review"], i)
        if decision == "blip":
            raise Blip("provider blip")
        return {"decision": decision, "fields_to_fix": ["entity_name"], "reasoning": "harness",
                "handoff_summary": "harness"}

    monkeypatch.setattr(CompletenessJudge, "_call_structured", judge_call)
    monkeypatch.setattr(ArbiterAgent, "_call_structured", arbiter_call)
    if script.decisions_down:
        import httpx

        def post(*a, **k):
            calls["decisions_posts"] += 1
            raise httpx.ConnectError("decisions transport down")

        monkeypatch.setattr(httpx, "post", post)
        monkeypatch.setattr("time.sleep", lambda s: None)

    medium = _medium()
    confs = iter(script.confs)
    last_conf = {"v": script.confs[-1] if script.confs else 0.95}

    def classify(state, attempt=1):
        conf = script.sorter if script.sorter is not None else medium
        return {"doc_type": "corporate_record", "doc_subclass": "minutes", "classification_confidence": conf,
                "classification_attempts": attempt, "stage": "classified", "transient_error": False}

    conflict = {"field": "entity_name", "values": ["Cedar Sample Ltd", "Cedar Sample Limited"]}

    def extract(state):
        conf = next(confs, last_conf["v"])
        return {"extracted_data": dict(DATA), "extraction_confidence": conf,
                "extraction_attempts": int(state.get("extraction_attempts") or 0) + 1,
                "stage": "extracted", "transient_error": False,
                **({"conflict_detected": True, "conflict_details": conflict} if script.conflict else {}),
                **script.extract_extra}

    def boss(state):
        from graph.routing import conflict_fingerprint

        calls["boss"] += 1
        if script.boss == "approve":
            return {"review_decision": "approved", "transient_error": False,
                    "boss_conflict_fingerprint": conflict_fingerprint(state.get("conflict_details"))}
        if script.boss == "blip":
            n = int(state.get("transient_retries_boss_escalation") or 0) + 1
            return {"transient_error": True, "transient_retries_boss_escalation": n, "error_message": "boss blip"}
        return {"review_decision": "rejected", "transient_error": False}

    scripted = {"classify": classify, "retry_classify": lambda s: classify(s, attempt=2),
                "extract": extract, "retry_extract": extract,
                "boss_escalation": boss if script.conflict else (lambda s: pytest.fail("boss unexpected"))}
    if script.classify_raises is not None:
        from agents.sorter import SorterAgent

        def refuse(*a, **k):
            raise script.classify_raises

        monkeypatch.setattr(SorterAgent, "classify_json", refuse)
        del scripted["classify"], scripted["retry_classify"]
    if script.extract_raises is not None:
        def refuse_extract(*a, **k):
            raise script.extract_raises

        monkeypatch.setattr(bg, "_run_chunked_extraction", refuse_extract)
        del scripted["extract"], scripted["retry_extract"]
    if not script.decisions_down:
        scripted["review_classify"] = lambda s: {
            "review_verdict": "decision_parks", "review_route": "human_review", "reviewer_confidence": 0.4,
            "reviewer_doc_type": "corporate_record", "reviewer_doc_subclass": "minutes",
            "reviewer_causes": ["reviewer_low_confidence"], "transient_error": False}
    visited: list[str] = []

    def wrap(name, fn):
        def node(state):
            visited.append(name)
            if len(visited) > VISIT_BOUND:
                pytest.fail(f"over {VISIT_BOUND} node visits: {visited}")
            return fn(state)
        return node

    for name in MODEL_NODES:
        fn = scripted.get(name) or getattr(bg, f"{name}_node")
        monkeypatch.setattr(bg, f"{name}_node", wrap(name, fn))
    for name in REAL_NODES:
        monkeypatch.setattr(bg, f"{name}_node", wrap(name, getattr(bg, f"{name}_node")))
    if script.floor is not None:
        import graph.routing as routing

        original = routing._thresholds_for  # the key a run's ``confidence`` block would carry
        monkeypatch.setattr(routing, "_thresholds_for",
                            lambda state: {**original(state), "arbiter_full_source_min_confidence": script.floor})
    if script.deadline_passed:
        from pipeline import limits

        monkeypatch.setattr(limits, "get_run_deadline", lambda: 1.0)  # 1970: already passed
    bg.reset_compiled_graph()
    inbox_dir().mkdir(parents=True, exist_ok=True)
    source = inbox_dir() / "exhibit.txt"
    source.write_text(script.doc)
    with oracle_routing_override(False):
        result = bg.run_pipeline(source, "ARBITER-HARNESS")
    return {"stage": result.get("stage"), "path": visited, "visits": len(visited), "state": dict(result),
            "extract_calls": visited.count("extract") + visited.count("retry_extract"),
            "judge_passes": calls["judge_c"], **calls}


def _medium() -> float:
    from pipeline.config import get_confidence_thresholds

    limits = get_confidence_thresholds("corporate_record")
    return (limits["low"] + limits["high"]) / 2
