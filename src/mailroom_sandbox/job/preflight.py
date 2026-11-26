"""Preflight: confirm, prepare, and lock a job run (DMR-027).

Writes ``spec.lock.json`` (immutable) LAST — it is the commit point. Resume
refuses on spec drift unless ``--force`` (which archives the old generation,
re-preps, and re-locks) — except that a store locked to a DIFFERENT Modal app
is refused outright, even under ``--force``: see ``_foreign_app``
(``SANDBOX_TAKEOVER_FOREIGN_STORE=1`` is the deliberate override). Live
engine/sink probes are opt-in (``live=True``) so the default is network-free
and CI-safe.
"""

from __future__ import annotations

import ipaddress
from copy import deepcopy
import logging
import os
import time
import uuid
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import llm_dojo_scoring
from llm_dojo_scoring.experiment import git_snapshot

from mailroom_sandbox import __version__ as sandbox_version
from mailroom_sandbox.corpus import prepare_subset
from mailroom_sandbox.job import checkpoint
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.otel import resolve_sink
from mailroom_sandbox.job.spec import (
    RunSpec,
    core_hash,
    engine_base_url,
    resolve_run_id,
    run_dir,
    spec_core,
)
from mailroom_sandbox.prompt_registry import prompt_lock_block
from mailroom_sandbox.prompt_versions import PromptSelectionError, selection_from_lock


_log = logging.getLogger(__name__)


def _versions() -> dict[str, Any]:
    out: dict[str, str] = {
        "mailroom_sandbox": sandbox_version,
        "llm_dojo_scoring": getattr(llm_dojo_scoring, "__version__", "?"),
    }
    from mailroom_sandbox import dojo_source

    choice = dojo_source.current()
    if choice is not None:
        # installed (the release) or vendored (the fallback snapshot): which one scored this run.
        out["llm_dojo_scoring_source"] = choice.source
    try:
        import opentelemetry  # type: ignore

        out["opentelemetry"] = getattr(opentelemetry, "__version__", "?")
    except Exception:
        pass
    return out


def _effective_model(spec: RunSpec, agent: str) -> str:
    """The model activation installs for ``agent``: ``agent_models`` wins, then its route, then the engine."""
    route = spec.agent_routes.get(agent)
    return spec.agent_models.get(agent) or (route.model if route else spec.engine.model)


def _in_house_url(spec: RunSpec, base_url: str) -> bool:
    """Whether a ``vllm`` route's URL is one the run controls, not any OpenAI-compatible host.

    Loopback, private and link-local addresses (a local server or SSH tunnel),
    the run's own engine host (unless that engine is OpenRouter), and this Modal
    workspace's apps qualify.
    """
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return address.is_loopback or address.is_private or address.is_link_local
    workspace = os.environ.get("MODAL_WORKSPACE", "").strip().lower()
    if workspace and host.endswith(".modal.run") and host.startswith(f"{workspace}--"):
        return True
    if spec.engine.kind == "openrouter":
        return False  # the engine itself is a third party, so its host proves nothing
    try:
        engine_host = (urlparse(engine_base_url(spec)).hostname or "").lower()
    except Exception:  # noqa: BLE001 - an unresolvable engine proves nothing about the route
        return False
    return host == engine_host


def _local_reviewer_errors(spec: RunSpec) -> list[str]:
    """The in-house reviewer must be a second model, on a route the run controls."""
    model = spec.reviewer.model
    errs = []
    reviewer_model = _effective_model(spec, "sorter_reviewer")
    if model == _effective_model(spec, "sorter") or (
            spec.agent_routes.get("sorter_reviewer") and reviewer_model == _effective_model(spec, "sorter")):
        errs.append("decision reviewer backend local must use a different model from the sorter, or it only repeats its answer")
    if spec.job.mock:
        return errs
    route = spec.agent_routes.get("sorter_reviewer")
    if route is None:
        errs.append("decision reviewer backend local needs an agent_routes.sorter_reviewer entry serving its model")
    elif route.provider not in {"modal-vllm", "vllm"}:
        errs.append(f"decision reviewer backend local must stay in-house; agent route provider {route.provider!r} is a third party")
    else:
        if route.provider == "vllm" and not _in_house_url(spec, route.base_url or ""):
            errs.append(f"decision reviewer backend local must stay in-house; vllm route {route.base_url!r} is not a "
                        "loopback/private address, the run's engine host or this MODAL_WORKSPACE (use provider modal-vllm)")
        if reviewer_model != model:
            errs.append(f"decision reviewer model {model!r} differs from the sorter_reviewer agent's effective model "
                        f"{reviewer_model!r}")
    return errs


def _api_reviewer_errors(spec: RunSpec) -> list[str]:
    """The API reviewer must be a second model on an OpenRouter route with a token cap."""
    model = spec.reviewer.model
    errs = []
    # A sorter_reviewer calibration never runs the sorter (the engine model IS the reviewer), so the
    # same-model guard applies to a pipeline, where the reviewer would only repeat the sorter's answer.
    if spec.task != "sorter_reviewer" and model == _effective_model(spec, "sorter"):
        errs.append("decision reviewer backend api must use a different model from the sorter, or it only repeats its answer")
    if spec.job.mock:
        return errs
    route = spec.agent_routes.get("sorter_reviewer")
    if route is None:
        errs.append("decision reviewer backend api needs an agent_routes.sorter_reviewer entry serving its model")
    elif route.provider != "openrouter":
        errs.append(f"decision reviewer backend api needs provider openrouter; agent route provider is {route.provider!r}")
    elif _effective_model(spec, "sorter_reviewer") != model:
        errs.append(f"decision reviewer model {model!r} differs from the sorter_reviewer agent's effective model "
                    f"{_effective_model(spec, 'sorter_reviewer')!r}")
    if spec.job.mode == "modal":
        errs.append("decision reviewer backend api is not supported for modal jobs (use job.mode endpoint)")
    return errs


def _extraction_gate_lock(spec: RunSpec) -> dict[str, Any]:
    """The pipeline extraction-gate block as locked: the question set frozen by content and hash."""
    import hashlib

    from mailroom_sandbox.decision_backends import EXTRACTION_GATE, decisions_dir, load_question_set

    gate = spec.extraction_gate
    qset = load_question_set(gate.questions)
    if qset.get("kind") != EXTRACTION_GATE:
        raise ValueError(f"extraction_gate.questions {gate.questions!r} is not an extraction_gate question set")
    path = decisions_dir() / f"{gate.questions}.yaml"
    return {**gate.model_dump(), "questions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "question_set": qset}


def vendored_decision_slots() -> Any:
    """The vendored llm-mailroom ``graph/decision_slots.py``, loaded by path, or ``None`` when absent.

    Its top level imports only the standard library and structlog, so ``parse_slots`` runs
    without the pipeline on ``sys.path``.
    """
    import importlib.util

    from mailroom_sandbox.runtime import resolve_mailroom_src

    src = resolve_mailroom_src()
    path = src / "graph" / "decision_slots.py" if src is not None else None
    if path is None or not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_sandbox_vendored_decision_slots", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _decision_slots_errors(spec: RunSpec) -> list[str]:
    """A non-baseline ``decision_slots`` block needs a vendored llm-mailroom that has the slots,
    a block that llm-mailroom's own ``parse_slots`` accepts, and a loadable resolver set."""
    slots = spec.decision_slots
    if slots is None:
        return []
    errs: list[str] = []
    try:
        module = vendored_decision_slots()
    except Exception as exc:  # noqa: BLE001 - a broken vendored module is a preflight error
        return [f"decision_slots: the vendored llm-mailroom graph/decision_slots.py does not load: {exc!r}"]
    if module is None:
        # An all-baseline block changes nothing, so an older vendor may run it.
        return [] if slots.is_baseline() else [
            "decision_slots: the vendored llm-mailroom has no decision slots (graph/decision_slots.py); "
            "re-vendor llm-mailroom at a commit that includes them"]
    try:
        module.parse_slots(slots.slots())
    except ValueError as exc:
        errs.append(str(exc))
    if slots.resolver is not None:
        from mailroom_sandbox.decision_backends import CLOSED_FIELD_RESOLVER, load_question_set
        from mailroom_sandbox.runtime import resolve_mailroom_src

        try:
            if load_question_set(slots.resolver.questions).get("kind") != CLOSED_FIELD_RESOLVER:
                errs.append(f"decision_slots.resolver.questions {slots.resolver.questions!r} is not a "
                            "closed_field_resolver question set")
        except ValueError as exc:
            errs.append(f"decision_slots.resolver.questions: {exc}")
        src = resolve_mailroom_src()
        if src is None or not (src / "agents" / "closed_field_resolver.py").is_file():
            errs.append("decision_slots.resolver: the vendored llm-mailroom has no agents.closed_field_resolver; "
                        "re-vendor llm-mailroom")
    decisions_calls = slots.resolver is not None or spec.extraction_gate is not None
    if decisions_calls and not spec.job.mock and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        errs.append("decision_slots call Decisions-API models: set OPENROUTER_API_KEY")
    return errs


_ARCHIVE_CHECK_FLAGS = ("judge_complete_archives", "arbiter_accept_archives", "judge_clears_low_confidence")


def _archive_check_errors(spec: RunSpec) -> list[str]:
    """llm-mailroom's archive-check flags need a vendored mailroom that reads them.

    They ship with the decision slots (llm-mailroom #309); an older vendor ignores them, so a
    "checks on" arm and a "checks off" arm would run the same route while the lock says otherwise.
    """
    blocks = [("confidence", spec.confidence)]
    blocks += [(f"confidence.by_class.{name}", b) for name, b in (spec.confidence.get("by_class") or {}).items()]
    named = [f"{where}.{key}" for where, block in blocks for key in _ARCHIVE_CHECK_FLAGS if key in block]
    if not named:
        return []
    try:
        module = vendored_decision_slots()
    except Exception:  # noqa: BLE001 - _decision_slots_errors reports a broken module
        module = None
    if module is not None:
        return []
    return [f"{', '.join(named)}: the vendored llm-mailroom has no archive checks and would ignore "
            "this; re-vendor llm-mailroom at a commit that includes them"]


def _decision_slots_lock(spec: RunSpec) -> dict[str, Any]:
    """The ``decision_slots`` block as locked: the slots verbatim, the resolver's question set frozen."""
    import hashlib

    from mailroom_sandbox.decision_backends import decisions_dir, load_question_set

    block: dict[str, Any] = {"slots": spec.decision_slots.slots()}
    resolver = spec.decision_slots.resolver
    if resolver is not None:
        path = decisions_dir() / f"{resolver.questions}.yaml"
        block["resolver"] = {**resolver.model_dump(), "questions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "question_set": load_question_set(resolver.questions)}
    return block


def _routing_identity_drift(existing: Mapping[str, Any]) -> str | None:
    """Refuse resume when a locked 4.2.0 routing fingerprint no longer matches this checkout.

    Locks that never recorded ``routing_sha256`` (published sets, older drafts) resume.
    """
    locked = (existing.get("reviewer") or {}).get("routing_sha256")
    if not locked:
        return None
    from mailroom_sandbox.decision_backends import v42_routing_sha256

    if locked != v42_routing_sha256():
        return ("4.2.0 routing code changed since this run was locked; "
                "pass --force to re-lock")
    return None


def _reviewer_lock(spec: RunSpec) -> dict[str, Any]:
    """The reviewer block as locked; a Decisions question set is frozen by content and hash."""
    block = spec.reviewer.model_dump()
    if spec.reviewer.backend == "decisions" and spec.reviewer.questions:
        import hashlib

        from mailroom_sandbox.decision_backends import (
            decisions_dir,
            load_question_set,
            uses_v42_routing,
            v42_routing_sha256,
        )

        path = decisions_dir() / f"{spec.reviewer.questions}.yaml"
        block["questions_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        block["question_set"] = load_question_set(spec.reviewer.questions)
        # YAML hash does not cover apply_v42_rules. Lock that source when the set uses it.
        if uses_v42_routing(block["question_set"]):
            block["routing_sha256"] = v42_routing_sha256()
    if spec.reviewer.handoff_run:
        # Freeze the handoff (by document id) so a resumed run sees the same answers: the
        # sorter's on a reviewer calibration, the specialist's extraction on a gate run.
        block["handoff"] = (extraction_handoff_map(spec.reviewer.handoff_run) if spec.task == "extraction_gate"
                            else sorter_handoff_map(spec.reviewer.handoff_run))
    return block


def extraction_handoff_map(run_id: str | list[str]) -> dict[str, dict[str, Any]]:
    """``{doc_id: extraction handoff}`` from finished specialist runs (task: <class>_specialist).

    Each item's prediction is the specialist's real extraction; the class is the run's
    specialist class. A list merges several runs (one per class), later runs winning.
    """
    import json

    from mailroom_sandbox.decision_backends import extraction_handoff
    from mailroom_sandbox.eval.agents import SPECIALIST_CLASS
    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    out: dict[str, dict[str, Any]] = {}
    for rid in [run_id] if isinstance(run_id, str) else list(run_id):
        store = RunStore(run_dir(str(rid)))
        lock = store.read_lock() or {}
        doc_type = SPECIALIST_CLASS.get(str(lock.get("task") or ""))
        if not doc_type:
            raise ValueError(f"handoff_run {rid!r} is not a specialist run (task {lock.get('task')!r})")
        if (lock.get("job") or {}).get("mock", True):
            raise ValueError(f"handoff_run {rid!r} is a mock run; the gate calibrates on real extractions only")
        state = (store.read_checkpoint() or {}).get("state")
        if state != "done":
            raise ValueError(f"handoff_run {rid!r} is not a finished run (state {state!r})")
        found = 0
        for item in store.load_items():
            pred = item.get("pred")
            if item.get("ok") and isinstance(pred, dict) and pred and not pred.get("_parse_error"):
                out[str(item.get("item_id"))] = extraction_handoff(doc_type, pred)
                found += 1
        if not found:
            raise ValueError(f"handoff_run {rid!r} has no usable extractions")
    json.dumps(out)
    return out


def _committed_handoff(path: str) -> dict[str, dict[str, Any]]:
    """A sorter pass saved by scripts/export_sorter_handoff.py (repo-relative .jsonl path)."""
    import json
    from pathlib import Path

    from mailroom_sandbox.paths import repo_root

    file = Path(path)
    file = file if file.is_absolute() else repo_root() / file
    if not file.is_file():
        raise ValueError(f"handoff_run file {path!r} not found")
    out: dict[str, dict[str, Any]] = {}
    with file.open(encoding="utf-8", newline="\n") as handle:
        for line in handle.read().split("\n"):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("ok") and row.get("sorter_doc_type"):
                out[str(row["id"])] = {
                    "sorter_doc_type": row["sorter_doc_type"],
                    "sorter_doc_subclass": row.get("sorter_doc_subclass"),
                    "sorter_confidence": row.get("sorter_confidence"),
                }
    if not out:
        raise ValueError(f"handoff_run file {path!r} has no usable sorter answers")
    return out


def sorter_handoff_map(run_id: str | list[str]) -> dict[str, dict[str, Any]]:
    """``{doc_id: sorter answer}`` from finished sorter runs (isolated or per-item sorter task).

    A list merges several runs, the later run winning on overlap. A run stopped by its API
    cost cap counts as finished: every persisted item is a complete sorter answer, and the
    run that sorts the documents it did not reach goes later in the list.
    """
    import json

    from mailroom_sandbox.job.checkpoint import RunStore
    from mailroom_sandbox.job.spec import run_dir

    out: dict[str, dict[str, Any]] = {}
    for rid in [run_id] if isinstance(run_id, str) else list(run_id):
        if str(rid).endswith(".jsonl"):
            out.update(_committed_handoff(rid))
            continue
        store = RunStore(run_dir(rid))
        checkpoint = store.read_checkpoint() or {}
        state = checkpoint.get("state")
        capped = state == "failed" and "api_cost_cap_usd" in str((checkpoint.get("last_error") or {}).get("message"))
        if state != "done" and not capped:
            raise ValueError(f"handoff_run {rid!r} is not a finished run (state {state!r})")
        found = 0
        for item in store.load_items():
            pred = item.get("pred") or {}
            if not item.get("ok") or not isinstance(pred, dict) or not pred.get("doc_type"):
                continue
            found += 1
            out[str(item.get("item_id"))] = {
                "sorter_doc_type": pred.get("doc_type"),
                "sorter_doc_subclass": pred.get("doc_subclass") or pred.get("contract_subtype"),
                "sorter_confidence": pred.get("confidence"),
            }
        if not found:
            raise ValueError(f"handoff_run {rid!r} has no usable sorter answers")
    json.dumps(out)  # must serialise into the lock
    return out


def _reviewer_route_bills_tokens(spec: RunSpec) -> bool:
    """Whether the sorter_reviewer chat agent would call a token-billed API.

    Its own route decides when it has one (a paid route can sit on a local engine); otherwise
    it runs on the engine.
    """
    from mailroom_sandbox.job.api_budget import API_PROVIDERS

    route = spec.agent_routes.get("sorter_reviewer")
    provider = route.provider if route is not None else spec.engine.kind
    return str(provider) in API_PROVIDERS


def _decisions_reviewer_errors(spec: RunSpec) -> list[str]:
    """The Decisions reviewer: a loadable question set, an OpenRouter key, and on a calibration
    run the engine model must be the reviewer model (the run's model label and price)."""
    from mailroom_sandbox.decision_backends import decision_questions, load_question_set

    from mailroom_sandbox.decision_backends import EXTRACTION_GATE

    errs: list[str] = []
    gate = spec.task == "extraction_gate"
    try:
        qset = load_question_set(spec.reviewer.questions or "")
        if (qset.get("kind") == EXTRACTION_GATE) != gate:
            raise ValueError("an extraction_gate run needs a kind: extraction_gate question set, and only it may use one")
        if not gate:
            decision_questions(qset)
    except Exception as exc:  # noqa: BLE001 - every shape error is a preflight error
        errs.append(f"decision reviewer questions: {exc}")
    # Modal job mode is supported (#308): the question set travels in the lock, and the worker
    # receives OPENROUTER_API_KEY through its deploy Secret.
    if not spec.job.mock and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        errs.append("decision reviewer backend decisions needs OPENROUTER_API_KEY")
    if spec.reviewer.handoff_run:
        try:
            (extraction_handoff_map if gate else sorter_handoff_map)(spec.reviewer.handoff_run)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"decision reviewer handoff_run: {exc}")
    elif gate:
        errs.append("an extraction_gate run needs reviewer.handoff_run: the finished specialist runs it reviews")
    if spec.task in ("sorter_reviewer", "extraction_gate") and spec.engine.model != spec.reviewer.model:
        errs.append(f"{spec.task} calibration: engine.model {spec.engine.model!r} must equal reviewer.model "
                    f"{spec.reviewer.model!r}, so the run is labelled and priced as the model it calls")
    return errs


def _named_agent_errors(spec: RunSpec) -> list[str]:
    if not spec.agent_models and not spec.agent_knobs:
        return []
    from mailroom_sandbox.agent_routes import known_agents

    unknown = (set(spec.agent_models) | set(spec.agent_knobs)) - known_agents()
    if not unknown:
        return []
    return [f"unknown or retired agents: {sorted(unknown)}"]


def _confidence_class_errors(spec: RunSpec) -> list[str]:
    named = spec.confidence.get("by_class")
    if not named:
        return []
    from mailroom_sandbox.overlay import live_doc_classes

    unknown = set(named) - set(live_doc_classes())
    if not unknown:
        return []
    return [f"confidence.by_class: unknown or retired doc classes {sorted(unknown)}"]


def _agent_route_errors(spec: RunSpec) -> list[str]:
    if not spec.agent_routes:
        return []
    from mailroom_sandbox.agent_routes import validate
    from mailroom_sandbox.services._exec import ServiceError

    try:
        validate(spec.agent_routes, credentials=not spec.job.mock)
    except (ValueError, ServiceError) as exc:
        return [str(exc)]
    return []


def _reviewer_class_errors(spec: RunSpec) -> list[str]:
    if spec.reviewer is None:
        return []
    from mailroom_sandbox.overlay import live_doc_classes

    live = live_doc_classes()
    unknown = sorted(set(spec.reviewer.classes) - set(live))
    if not unknown:
        return []
    return [f"decision reviewer classes {unknown} are not live taxonomy classes; valid: {sorted(live)}"]


def _jev_backend_errors(spec: RunSpec) -> list[str]:
    """Return the first Jev refusal in priority order; its conditions can coexist."""
    reviewer = spec.reviewer
    if reviewer is None or reviewer.backend != "jev":
        return []
    if spec.job.mock:
        # A mock pipeline run patches the LLM clients but not the decision backend.
        return ["decision reviewer backend jev would make live Jev calls in a mock run; use backend mock"]
    if spec.job.mode == "modal":
        # The Modal worker image excludes the decision extra.
        return ["decision reviewer backend jev is not supported for modal jobs "
                "(the Modal worker image has no decision extra); use endpoint mode or backend mock"]
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return ["decision reviewer backend jev needs TYPESAFE_API_KEY set (offline runs should use backend mock)"]
    return []


def _reviewer_backend_errors(spec: RunSpec) -> list[str]:
    reviewer = spec.reviewer
    if reviewer is None:
        return []
    if reviewer.backend == "local":
        return _local_reviewer_errors(spec)
    if reviewer.backend == "api":
        return _api_reviewer_errors(spec)
    if reviewer.backend == "decisions":
        return _decisions_reviewer_errors(spec)
    return []


def _present_reviewer_task_errors(spec: RunSpec) -> list[str]:
    reviewer = spec.reviewer
    errs: list[str] = []
    if reviewer is not None and spec.task == "pipeline" and not reviewer.classes:
        errs.append("decision reviewer on a pipeline run needs at least one class with a cutoff")
    if reviewer is not None and spec.task == "extraction_gate" and not spec.job.mock and reviewer.backend != "decisions":
        errs.append("a live extraction_gate run needs reviewer backend decisions; "
                    f"{reviewer.backend!r} has no extraction-gate path")
    return errs


def _missing_reviewer_errors(spec: RunSpec) -> list[str]:
    if spec.reviewer is not None or spec.job.mock:
        return []
    if spec.task == "extraction_gate":
        return ["a live extraction_gate run needs a reviewer block: backend decisions with a Decisions-API "
                "model, a kind: extraction_gate question set and reviewer.handoff_run"]
    if spec.task == "sorter_reviewer" and _reviewer_route_bills_tokens(spec):
        # A paid reviewer calibration must name its reviewer: without a reviewer block the
        # sorter_reviewer chat agent runs, which is how chat Luna was calibrated by mistake.
        return ["a paid sorter_reviewer run needs a reviewer block: backend decisions with a Decisions-API model "
                "(e.g. openai/gpt-6-luna-decisions) and questions, or backend api with allow_chat_model: true"]
    return []


def _openrouter_key_error(spec: RunSpec) -> list[str]:
    # Without this, a keyless run fails soft on every document (review, ok) and spends nothing.
    needs_key = spec.engine.kind == "openrouter" and not spec.job.mock
    if needs_key and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        return ["engine kind openrouter needs OPENROUTER_API_KEY set in this shell"]
    return []


def _vllm_bound_errors(spec: RunSpec) -> list[str]:
    vllm = spec.engine.vllm
    errs: list[str] = []
    if vllm.max_model_len < 1:
        errs.append("max_model_len must be >= 1")
    if not 0.0 < vllm.gpu_memory_utilization <= 1.0:
        errs.append("gpu_memory_utilization must be in (0, 1]")
    if vllm.max_num_seqs < 1:
        errs.append("max_num_seqs must be >= 1")
    return errs


def _modal_admission_error(spec: RunSpec) -> str | None:
    # Mock runs call no vLLM endpoint, so admission cannot serialize billed GPU time.
    modal = spec.engine.modal
    if modal is None or spec.job.mock or spec.engine.kind != "modal-vllm":
        return None
    if spec.job.concurrency <= 1 or spec.engine.vllm.max_inputs >= 1:
        return None
    return (f"job.concurrency {spec.job.concurrency} needs engine.vllm.max_inputs >= 1: "
            "with 0 Modal serves one request at a time while the GPU bills")


def _modal_engine_errors(spec: RunSpec) -> list[str]:
    modal = spec.engine.modal
    if modal is None:
        return []
    errs: list[str] = []
    if modal.image_tag == "latest":
        errs.append("modal image_tag must be pinned (never 'latest')")
    if modal.max_containers < 1:
        errs.append("modal max_containers must be >= 1 (cost guard)")
    admission = _modal_admission_error(spec)
    if admission:
        errs.append(admission)
    return errs


def _engine_errors(spec: RunSpec) -> list[str]:
    """Engine, route, and reviewer refusals, in the order preflight prints them."""
    return [
        *_named_agent_errors(spec),
        *_confidence_class_errors(spec),
        *_agent_route_errors(spec),
        *_decision_slots_errors(spec),
        *_archive_check_errors(spec),
        *_reviewer_class_errors(spec),
        *_jev_backend_errors(spec),
        *_reviewer_backend_errors(spec),
        *_present_reviewer_task_errors(spec),
        *_missing_reviewer_errors(spec),
        *_openrouter_key_error(spec),
        *_vllm_bound_errors(spec),
        *_modal_engine_errors(spec),
    ]


def _engine_summary(spec: RunSpec) -> str:
    v = spec.engine.vllm
    modal = spec.engine.modal
    parts = [
        f"kind={spec.engine.kind} model={spec.engine.model}",
        f"max_model_len={v.max_model_len} gpu_util={v.gpu_memory_utilization} "
        f"max_num_seqs={v.max_num_seqs} "
        f"prefix_caching={'on' if v.enable_prefix_caching else 'off'} "
        f"enforce_eager={'on' if v.enforce_eager else 'off'}",
    ]
    if v.quantization:
        parts[1] += f" quantization={v.quantization}"
    if modal:
        modal_part = f"modal app={modal.app} gpu={modal.gpu} image={modal.image_tag} max_containers={modal.max_containers}"
        parts.append(modal_part)
    return ", ".join(parts)


def _probe_timeout_seconds(spec: RunSpec) -> float:
    """Timeout for the live engine probe.

    A scale-to-zero Modal app accepts the request and holds it open until the
    container is up (minutes), so the old hard 10 s would misreport a *booting*
    app as unreachable and fail the preflight (SAND-018). Modal probes get the
    boot budget; every other profile keeps the short CI-safe default. Override
    with ``SANDBOX_ENGINE_PROBE_TIMEOUT_SECONDS``.
    """
    env = os.environ.get("SANDBOX_ENGINE_PROBE_TIMEOUT_SECONDS", "").strip()
    if env:
        return float(env)
    if spec.engine.kind == "modal-vllm":
        return float(os.environ.get("MODAL_VLLM_STARTUP_TIMEOUT_SECONDS", "1200"))
    return 10.0


def _probe_engine(spec: RunSpec) -> dict[str, Any]:
    base = engine_base_url(spec)
    from mailroom_sandbox.overlay import load_profile
    profile = load_profile(spec.profile)
    api_key_env = str(profile.get("api_key_env") or "VLLM_API_KEY")
    # ``engine_base_url`` resolves VLLM_BASE_URL BEFORE the profile base for
    # every non-OpenRouter kind. The probe must then use the vLLM credential:
    # an ``openrouter`` profile pointed at a vLLM endpoint would otherwise
    # send OPENROUTER_API_KEY to that host.
    if spec.engine.kind != "openrouter" and os.environ.get("VLLM_BASE_URL", "").strip():
        api_key_env = "VLLM_API_KEY"
    api_key = os.environ.get(api_key_env, "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    detail: dict[str, Any] = {"base_url": base}
    import httpx

    timeout = _probe_timeout_seconds(spec)
    detail["probe_timeout_seconds"] = timeout
    # URL-seam normalization: VLLM_BASE_URL / profile base_url carry the
    # OpenAI-style "/v1" suffix (deploy README + .env.example contract) —
    # appending "/v1/models" to an already-seamed base yields
    # ".../v1/v1/models" and a 404 from vLLM. Only add the seam when the
    # base does not already end with it.
    base = base.rstrip("/")
    models_path = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"

    started = time.perf_counter()
    deadline = started + timeout
    last_reason = "no response from /v1/models"
    while True:
        attempt_timeout = max(1.0, deadline - time.perf_counter())
        try:
            resp = httpx.get(models_path, headers=headers, timeout=attempt_timeout)
        except httpx.ConnectError as exc:
            # Connection refused = wrong / dead endpoint (e.g. the localhost
            # fallback when VLLM_BASE_URL is unset) — fail fast, never retry.
            return {
                "ok": False,
                "reason": f"unreachable: {type(exc).__name__}: {exc}",
                "cold_boot_seconds": round(time.perf_counter() - started, 3),
                **detail,
            }
        except Exception as exc:  # noqa: BLE001 — boot can drop the held request
            last_reason = f"unreachable: {type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 401:
                return {
                    "ok": False,
                    "reason": f"401 — set {api_key_env} to the configured provider token",
                    "cold_boot_seconds": round(time.perf_counter() - started, 3),
                    **detail,
                }
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "reason": f"HTTP {resp.status_code} from /v1/models",
                    "cold_boot_seconds": round(time.perf_counter() - started, 3),
                    **detail,
                }
            try:
                ids = [
                    str(m.get("id"))
                    for m in (resp.json().get("data") or [])
                    if isinstance(m, dict)
                ]
            except Exception as exc:  # noqa: BLE001
                # A booting Modal web_server can answer 2xx with an empty body
                # before vLLM is ready — retry until the boot budget elapses
                # (SAND-018: this is what misreported a boot as "wrong API").
                last_reason = (
                    f"/v1/models returned unparseable JSON (not a models payload): "
                    f"{type(exc).__name__}: {str(resp.text)[:160]!r} — the endpoint may be "
                    f"answering the wrong API"
                )
            else:
                detail["served_models"] = ids
                if spec.engine.model not in ids:
                    return {
                        "ok": False,
                        "reason": f"served {sorted(ids)} lacks spec.model={spec.engine.model}",
                        "cold_boot_seconds": round(time.perf_counter() - started, 3),
                        **detail,
                    }
                detail["cold_boot_seconds"] = round(time.perf_counter() - started, 3)
                return {"ok": True, **detail}
        if time.perf_counter() >= deadline:
            detail["cold_boot_seconds"] = round(time.perf_counter() - started, 3)
            return {"ok": False, "reason": last_reason, **detail}
        time.sleep(1.0)


def probe_engine(spec: RunSpec) -> dict[str, Any]:
    """Live engine probe: /v1/models at the resolved base URL vs the spec model.

    Public wrapper around the preflight live check so ``run start --job-mode
    modal`` can verify the endpoint BEFORE firing (DMR-048) without re-running
    the whole preflight.
    """
    return _probe_engine(spec)


def probe_timeout_seconds(spec: RunSpec) -> float:
    """Public boot budget for direct probes (CLI and per-agent route checks)."""
    return _probe_timeout_seconds(spec)


def record_cold_boot(store: RunStore, probe: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any] | None:
    """Persist a successful live-probe measurement as the run's cold boot.

    Direct probes (``sandbox run preflight --live`` / ``run start``) bypass
    ``preflight(live=True)``, so the runner and metrics never saw the measured
    boot time. Only successful measurements are recorded; a failed probe must
    not overwrite an existing measurement.
    """
    boot_seconds = probe.get("cold_boot_seconds") if probe.get("ok") else None
    if boot_seconds is None:
        return None
    measurement = {
        "cold_boot_seconds": float(boot_seconds),
        "base_url": probe.get("base_url"),
        "served_models": probe.get("served_models"),
        "probe_timeout_seconds": probe.get("probe_timeout_seconds"),
        "measured_at": checkpoint.utc_now(),
        "run_id": run_id or store.run_id,
    }
    store.write_cold_boot(measurement)
    store.append_event("cold_boot", "info", **measurement)
    return measurement


def _extracts(spec: RunSpec) -> bool:
    return spec.task in ("pipeline", "specialist") or spec.task.endswith("_specialist")


def _run_knobs(spec: RunSpec, run_id: str | None) -> dict[str, Any]:
    """The run ``agent_knobs`` snapshot: one resolution shared by the plan and the lock."""
    from mailroom_sandbox.job.length_fix import with_length_fix_defaults
    from mailroom_sandbox.job.specialist_posture import agent_knobs_for_run
    from mailroom_sandbox.runtime import resolve_agent_knobs

    knobs = resolve_agent_knobs(spec.agent_knobs or agent_knobs_for_run(run_id))
    # #214: a pipeline run on self-hosted Qwen3 vLLM defaults the length-fix
    # sampling for the chunked specialists it configured nothing for. Explicit
    # or posture knobs always win; the merged map freezes into the lock.
    return with_length_fix_defaults(knobs, spec)


def _record_context_plan(report: dict[str, Any], spec: RunSpec, store: RunStore, knobs: dict[str, Any]) -> None:
    """Attach the informational context plan; it never fails preflight.

    ``knobs`` is the exact snapshot the lock holds (or will be written with).
    """
    if not _extracts(spec):
        return
    from mailroom_sandbox.job.context_plan import plan_for_spec

    try:
        rows = store.dataset_rows()
        if spec.target:  # plan only what the runner will execute
            from mailroom_sandbox.eval.primary import rows_for_class

            rows = rows_for_class(rows, spec.target)
        cp = plan_for_spec(spec, rows, knobs=knobs)
    except Exception as exc:  # noqa: BLE001 — advisory only
        _log.debug("context plan skipped", exc_info=exc)
        report["checks"].append({"name": "context_plan", "ok": True, "detail": f"skipped: {exc}"})
        return
    report["context_plan"] = cp
    warnings = cp["warnings"]
    detail = f"{len(warnings)} warning(s): " + " | ".join(warnings) if warnings else "budgets fit every document"
    report["checks"].append({"name": "context_plan", "ok": True, "detail": detail})


#: Decision-model tasks: the engine is the reviewer itself (see the engine/reviewer check above).
_DECISION_MODEL_TASKS = ("sorter_reviewer", "extraction_gate")


def _blocking_gaps(spec: RunSpec, gaps: list[str]) -> list[str]:
    """Gaps that fail preflight without ``require``: an API reader this run calls, left short.

    Only readers the task calls count (:func:`_task_readers`); a pipeline task calls them all.

    A decision-model task on a non-chat backend (Decisions, Jev) calls no pipeline reader,
    so the readers' unfitted budgets cannot truncate anything there.
    """
    reviewer = getattr(spec, "reviewer", None)
    if spec.task in _DECISION_MODEL_TASKS and reviewer is not None and reviewer.backend != "api":
        return []
    excused = _explicit_input_knobs(spec)
    return [gap for gap in _called_gaps(spec, gaps) if not _knob_excuses(gap, excused)]


def _called_gaps(spec: RunSpec, gaps: list[str]) -> list[str]:
    """The gaps of readers ``spec.task`` calls (every gap when it may call any reader)."""
    called = _task_readers(spec.task)
    return [gap for gap in gaps if called is None or gap.split(":", 1)[0] in called]


#: Readers an isolated task calls. A task not listed (pipeline, chained, isolated,
#: local_vs_api, specialist, extract, ...) may call any reader, so every gap blocks there.
_SORTER_READERS = frozenset({"intake", "sorter", "sorter_reviewer"})
_TASK_READERS: dict[str, frozenset[str]] = {
    "sorter": _SORTER_READERS,
    "sorter_vs_modernbert": _SORTER_READERS,
    "sorter_reviewer": frozenset({"sorter", "sorter_reviewer"}),
}


def _task_readers(task: str) -> frozenset[str] | None:
    """The readers ``task`` calls, or ``None`` when it may call any of them.

    An agent-registered task (``eval.agents.SPECS``: ``judge``, ``contracts_specialist``, ...)
    runs that one agent, so only its own gaps can truncate anything.
    """
    if task in _TASK_READERS:
        return _TASK_READERS[task]
    try:
        from mailroom_sandbox.eval.agents import SPECS
    except Exception:  # noqa: BLE001 - unknown: every reader may be called
        return None
    return frozenset({task}) if task in SPECS else None


_KNOB_FIXABLE_GAPS = ("max_input_chars=", "has no context_length")
_SOURCE_READERS = ("judge", "arbiter")  # context_fit._SOURCE_AGENTS: they read a source excerpt


def _knob_excuses(gap: str, excused: set[str]) -> bool:
    """An explicit ``max_input_chars`` knob excuses an input-budget gap, never a source window.

    The knob sets the reader's input length; the 16k sliding source window is a separate
    vendored constant the knob cannot widen, so that gap still blocks.
    """
    name = gap.split(":", 1)[0]
    if name not in excused:
        return False
    if name in _SOURCE_READERS and "has no context_length" in gap:
        # An unfitted judge/arbiter also keeps the 16k source excerpt; that gap is not
        # emitted separately when the context is unknown, so this one must still block.
        return False
    return any(marker in gap for marker in _KNOB_FIXABLE_GAPS)


def _explicit_input_knobs(spec: RunSpec) -> set[str]:
    """Agents whose ``max_input_chars`` the run YAML sets in ``agent_knobs`` (not a posture default)."""
    return {
        str(name) for name, knob in (spec.agent_knobs or {}).items()
        if isinstance(knob, dict) and knob.get("max_input_chars") is not None
    }


def _decision_blocks(spec: RunSpec) -> list[tuple[str, str, str]]:
    """``(lane, model, question-set stem)`` for every Decisions-API request the run makes."""
    out: list[tuple[str, str, str]] = []
    reviewer = getattr(spec, "reviewer", None)
    if reviewer is not None and reviewer.backend == "decisions" and reviewer.questions:
        out.append(("reviewer", reviewer.model, reviewer.questions))
    gate = getattr(spec, "extraction_gate", None)
    if gate is not None:
        out.append(("extraction_gate", gate.model, gate.questions))
    resolver = getattr(getattr(spec, "decision_slots", None), "resolver", None)
    if resolver is not None:
        out.append(("closed_field_resolver", resolver.model, resolver.questions))
    return out


def _reviewer_override(spec: RunSpec, wanted: int | None) -> int | None:
    """The reviewer's requested cap with a run's ``reviewer.max_input_chars`` applied.

    Mirrors ``decision_backends.classify_window_chars`` where a spec carries that field:
    the run's value raises the question set's cap and never lowers it, and it is the cap
    when the set has none. A spec without the field keeps the set's cap.
    """
    extra = getattr(getattr(spec, "reviewer", None), "max_input_chars", None)
    if not isinstance(extra, int) or isinstance(extra, bool) or extra < 1:
        return wanted
    return max(wanted, extra) if wanted else extra


def _record_decision_windows(report: dict[str, Any], spec: RunSpec) -> bool:
    """Record the model and input window of each Decisions lane (advisory).

    A swapped decision model (Jev 1.14, Gemini Decision, ...) reads at most its own context:
    ``decision_input_cap`` cuts a question set's ``max_input_chars`` to the model's window,
    and this check says where that happens so a smaller window is never a surprise. The
    reserve counts the lane's largest serialized questions, as execution does; the run's
    handoff is unknown here, so each ``window_chars`` is an estimate that execution can
    lower by the handoff's size.
    """
    blocks = _decision_blocks(spec)
    if not blocks:
        return True
    from mailroom_sandbox.decision_backends import (
        decision_input_cap,
        decision_model,
        lane_question_chars,
        load_question_set,
    )

    rows, cut, refused = [], [], []
    for lane, model, stem in blocks:
        try:
            qset = load_question_set(str(stem))
        except Exception as exc:  # noqa: BLE001 - advisory: the lock step reports a bad stem
            rows.append({"lane": lane, "model": model, "questions": stem, "error": str(exc)})
            continue
        try:
            question_chars = lane_question_chars(lane, qset)
        except Exception:  # noqa: BLE001 - questions that do not build: the default reserve still checks the window
            question_chars = 0
        caps = [qset.get("max_input_chars"), *((qset.get("max_input_chars_by_class") or {}).values())]
        wanted = max(int(c) for c in caps if c) if any(caps) else None
        if lane == "reviewer":
            wanted = _reviewer_override(spec, wanted)
        try:
            # Sized like execution: the questions are counted; the run's handoff is not known yet.
            window = decision_input_cap(model, wanted, question_chars=question_chars)
        except ValueError as exc:  # a window too small to read the document: no request may go out
            rows.append({"lane": lane, "model": model, "questions": stem, "question_chars": question_chars,
                         "error": str(exc)})
            refused.append(f"{lane}: {exc}")
            continue
        row = decision_model(model) or decision_model(str(model).split(":", 1)[0]) or {}
        rows.append({"lane": lane, "model": model, "questions": stem, "context_length": row.get("context_length"),
                     "max_input_chars": wanted, "question_chars": question_chars, "window_chars": window,
                     "window_estimate": "excludes the run's handoff"})
        if wanted and window < wanted:
            cut.append(f"{lane} {model}: {stem} max_input_chars {wanted:,} cut to {window:,} "
                       f"(the model's {row.get('context_length')}-token context)")
    report["decision_windows"] = rows
    if refused:
        report["status"] = "failed"
        report["checks"].append({"name": "decision_windows", "ok": False, "detail": "; ".join(refused)})
        return False
    detail = ("; ".join(cut) + " (longer documents are truncated; answers report truncated)") if cut else \
        ", ".join(f"{r['lane']}={r['model']} ({r.get('window_chars') or '?'} chars)" for r in rows)
    report["checks"].append({"name": "decision_windows", "ok": True, "detail": detail})
    return True


def _record_expanded_inputs(
    report: dict[str, Any], spec: RunSpec, knobs: dict[str, Any], *, require: bool,
) -> bool:
    """Record each reader's expanded input length. Return whether preflight may continue.

    A long-context API reader (OpenRouter) still on the short Modal/L4 budget fails the
    run before a lock is written: HF-009 reads whole documents on API routes, so an
    unfitted budget (say a model with no ``context_length`` on the price sheet) would
    reject every longer document mid-run instead of reading it. Only readers the task
    calls count (:func:`_task_readers`). The one exception is an input-budget gap of a
    reader whose ``max_input_chars`` the run YAML sets in ``agent_knobs`` on purpose
    (never a short source window, nor a judge or arbiter with no ``context_length``);
    that gap is recorded and fails only under ``require`` (``job.require_expanded_inputs``
    or ``sandbox run preflight --require-expanded-inputs``). A posture default is not a
    run choice and is never excused. A Modal or local route has nothing to swap and
    stays ok.
    """
    from mailroom_sandbox.context_fit import expansion_status
    from mailroom_sandbox.job.context_plan import taxonomy_for_spec

    try:
        status = expansion_status(taxonomy_for_spec(spec, knobs))
    except Exception as exc:  # noqa: BLE001 — the check must not hide a taxonomy error when required
        _log.debug("expanded-input check skipped", exc_info=exc)
        ok = not require
        if not ok:
            report["status"] = "failed"
        report["checks"].append({"name": "expanded_inputs", "ok": ok, "detail": f"skipped: {exc}"})
        return ok
    report["expanded_inputs"] = status
    gaps = status["gaps"]
    applicable = [row for row in status["agents"] if row["expanded"] is not None]
    if not applicable:
        detail, ok = "no long-context route; input lengths stay on the local budget", True
    elif require and (called := _called_gaps(spec, gaps)):
        detail, ok = "; ".join(called), False
    elif blocking := _blocking_gaps(spec, gaps):
        detail = (
            "API reader(s) would run on the short Modal/L4 budget (set the model's "
            "context_length in config/api_prices.yaml, or an explicit agent_knobs "
            "max_input_chars): " + "; ".join(blocking)
        )
        ok = False
    elif gaps:
        detail = f"not required; {len(gaps)} reader(s) on a run-set short budget: " + "; ".join(gaps)
        ok = True
    else:
        shown = ", ".join(f"{row['agent']}={row['max_input_chars']}" for row in applicable if row["expanded"])
        detail, ok = f"expanded input lengths on: {shown}", True
    if not ok:
        report["status"] = "failed"
    report["checks"].append({"name": "expanded_inputs", "ok": ok, "detail": detail})
    return ok


def _modal_check(spec: RunSpec) -> bool:
    modal = spec.engine.modal
    if modal is None:
        return True
    return modal.image_tag != "latest" and modal.max_containers >= 1


def _foreign_app(existing: Mapping[str, Any], spec: RunSpec) -> str | None:
    """The lock's Modal app when the store belongs to a DIFFERENT fleet, else None.

    The run store is the one writable resource the app name does not scope (the
    Modal cache volumes are app-scoped for exactly this reason), so ``--force``
    is how two fleets sharing a run_id would collide: ``archive_generation()``
    moves ``items.jsonl`` aside, but a LIVE writer reopens it by path
    (``RunStore.append_item`` opens ``"a"`` per item) and recreates it under the
    same name — both fleets then append to one ``items.jsonl``. A plain resume
    already refuses (``engine.modal`` is inside ``spec_hash``); this closes the
    ``--force`` door too.
    """
    locked = ((existing.get("engine") or {}).get("modal") or {}).get("app")
    current = spec.engine.modal.app if spec.engine.modal else None
    if locked and current and locked != current:
        return str(locked)
    return None


def _takeover_foreign_store() -> bool:
    """Deliberate override for ``_foreign_app`` — a human taking over a store."""
    return os.environ.get("SANDBOX_TAKEOVER_FOREIGN_STORE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _git(path: Path, *args: str) -> str | None:
    """One ``git -C path`` answer, or None when git or the checkout is unavailable."""
    import subprocess

    try:
        out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                             timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def package_checkout() -> dict[str, str | None]:
    """The checkout the imported ``mailroom_sandbox`` package lives in (SAND-104, #312).

    A worktree whose ``.venv`` links to another checkout's venv imports that
    checkout's code. ``git_snapshot()`` reads the cwd, so it cannot show this.
    ``SANDBOX_ROOT`` is deliberately ignored: this is where the code came from.
    """
    import mailroom_sandbox

    here = Path(mailroom_sandbox.__file__).resolve().parent
    root = next((p for p in here.parents if (p / "pyproject.toml").is_file() and (p / "src").is_dir()), here)
    return {"path": str(root), "commit": _git(root, "rev-parse", "HEAD")}


def _cwd_checkout() -> Path | None:
    """The git checkout the run is launched from, or None outside one."""
    top = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else None


def _allow_foreign_checkout() -> bool:
    return os.environ.get("SANDBOX_ALLOW_FOREIGN_CHECKOUT", "").strip().lower() in {"1", "true", "yes", "on"}


def _hotfix_identity() -> dict[str, Any]:
    from mailroom_sandbox import vendor_hotfixes

    return vendor_hotfixes.describe()


def _hotfix_check() -> dict[str, Any]:
    """Every sandbox hotfix still matches the vendored code it wraps (mailroom_sandbox.vendor_hotfixes)."""
    from mailroom_sandbox import vendor_hotfixes

    status = vendor_hotfixes.apply_hotfixes()
    stale = sorted(i for i, s in status.items() if s == "stale")
    unavailable = sorted(i for i, s in status.items() if s != "applied" and s != "stale"
                         and not (i == "HF-005" and s == "unavailable"))
    detail = ", ".join(f"{i} {s}" for i, s in sorted(status.items())) or "none"
    if stale:
        return {"name": "vendor_hotfixes", "ok": False,
                "detail": f"{detail}: the vendored target changed; re-validate or retire {', '.join(stale)} "
                          "(docs/vendor-hotfixes.md)"}
    if unavailable:
        return {"name": "vendor_hotfixes", "ok": False,
                "detail": f"{detail}: required hotfixes are not applied: {', '.join(unavailable)} "
                          "(install the pipeline dependencies; docs/vendor-hotfixes.md)"}
    return {"name": "vendor_hotfixes", "ok": True, "detail": detail}


def _scoring_hotfix_identity() -> dict[str, Any]:
    from mailroom_sandbox import scoring_hotfixes

    return scoring_hotfixes.describe()


def _scoring_hotfix_check() -> dict[str, Any]:
    """Every scoring hotfix still matches the code it corrects (mailroom_sandbox.scoring_hotfixes)."""
    from mailroom_sandbox import scoring_hotfixes

    status = scoring_hotfixes.status(refresh=True)
    stale = sorted(i for i, s in status.items() if s == "stale")
    # An unavailable target also disables its fix (current_ids()), so the run would lock and
    # report uncorrected metrics; it fails the check like a stale one.
    missing = sorted(i for i, s in status.items() if s == "unavailable")
    detail = ", ".join(f"{i} {s}" for i, s in sorted(status.items())) or "none"
    if stale or missing:
        why = []
        if stale:
            why.append(f"a scored target changed; re-validate or retire {', '.join(stale)}")
        if missing:
            why.append(f"a scored target could not be resolved for {', '.join(missing)}")
        return {"name": "scoring_hotfixes", "ok": False,
                "detail": f"{detail}: {'; '.join(why)} (docs/scoring-hotfixes.md)"}
    return {"name": "scoring_hotfixes", "ok": True, "detail": detail}


def _checkout_check(package: Mapping[str, Any]) -> dict[str, Any]:
    """Fail when the launch checkout and the imported code's checkout differ."""
    cwd = _cwd_checkout()
    code = Path(str(package["path"])).resolve()
    if cwd is None:
        return {"name": "checkout", "ok": True, "detail": f"code from {code} (cwd is not a git checkout)"}
    if cwd == code:
        return {"name": "checkout", "ok": True, "detail": f"code from {code}"}
    detail = (f"code is imported from {code}, but the run is launched from {cwd}; the lock's git "
              f"commit would name the wrong code. From a worktree, export PYTHONPATH=\"$PWD/src\"")
    if _allow_foreign_checkout():
        return {"name": "checkout", "ok": True, "detail": f"{detail} (accepted: SANDBOX_ALLOW_FOREIGN_CHECKOUT)"}
    return {"name": "checkout", "ok": False, "detail": detail}


def _prompt_summary(block: dict[str, Any]) -> str:
    agents = block.get("agents") or {}
    bits = [f"default={block.get('default', {}).get('source')}"]
    for agent, r in agents.items():
        bits.append(f"{agent}={r.get('key') or r.get('source')}" if r.get("source") == "eval-environment" else f"{agent}={r.get('source')}")
    return "; ".join(bits) if bits else "code-default"


def _dataset_lock(prov: dict[str, Any], spec: RunSpec) -> dict[str, Any]:
    """Combine requested dataset selection with prepared dataset provenance."""
    return {
        "repo": (spec.dataset.local_file().name if spec.dataset.local_file() else spec.dataset.repo),
        "config": spec.dataset.config,
        "split": spec.dataset.split,
        "revision": prov.get("revision_requested") or spec.effective_revision(),
        # DMR-049: the resolved 40-hex sha (branch/tag revisions resolve via
        # dataset_info; the default pin is already a full sha).
        "revision_resolved": prov.get("revision_resolved"),
        "limit": spec.dataset.limit,
        "sample_seed": spec.dataset.sample_seed,
        "selection": {"require_task_gt": spec.dataset.require_task_gt},
        "strata": spec.dataset.strata,
        # DMR-066: actual drawn (doc_class::subclass) distribution — the lock
        # now proves the requested strata were really drawn (no silent
        # single-class collapse), not just recorded as a spec.
        "strata_actual": prov.get("strata_actual"),
        "rows": prov.get("rows"),
        "sha256": prov.get("sha256"),
        "metadata": prov.get("metadata", {}),
    }


def _prompt_text_sha(block: dict[str, Any]) -> str:
    """Hash of the RESOLVED prompt texts (local/langfuse), not just refs.

    ``spec_hash`` covers prompt REFS; two identical refs whose file bodies
    changed hash the same, so a resume would replay with different prompt
    text. This sha lands in the lock and is checked on every preflight
    (DMR-049).
    """
    import hashlib

    agents = block.get("agents") or {}
    parts = []
    for agent in sorted(agents):
        ref = agents[agent]
        if not isinstance(ref, dict):
            continue
        parts.append(f"{agent}:{ref.get('sha256') or ''}:{ref.get('text') or ''}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _resolve_report_group(
    spec: RunSpec,
    *,
    run_id: str,
    config_path: str | Path | None,
) -> str | None:
    """Resolve the report group; fail if an explicit runbook id is unknown."""
    from mailroom_sandbox.report_paths import (
        experiment_prefix,
        report_group_for_config,
        report_group_for_runbook,
    )

    if spec.runbook_id:
        group = report_group_for_runbook(spec.runbook_id)
        if group is None:
            raise ValueError(
                f"unknown runbook_id {spec.runbook_id!r}: no report-group catalog entry"
            )
        return group
    return report_group_for_config(config_path) or experiment_prefix(run_id)


def preflight(
    spec: RunSpec,
    *,
    run_id: str = "",
    config_path: str | Path | None = None,
    offline: bool = False,
    force: bool = False,
    dry_run: bool = False,
    live: bool = False,
    require_expanded_inputs: bool = False,
) -> dict[str, Any]:
    """Prepare or validate a generation under the writer and control locks.

    Load dotenv configuration before resolving prompts and probes. Return
    the preflight report, or ``busy_refused`` when the writer lock is held.
    ``force`` requests archival and a new generation but refuses possibly
    active writers; ``offline`` avoids remote prompt/tracing requirements.
    ``live`` probes the engine for a new generation. ``dry_run`` checks
    lock readability and replay ownership without resolving or preparing artifacts;
    the run directory and lock files may still be created.
    ``require_expanded_inputs`` fails the run when a long-context reader is
    still on the short budget. The run's ``job.require_expanded_inputs`` does
    the same. Either one is enough.
    Uncaught configuration and file-access errors propagate.
    """
    # Dotenv supplies prompt credentials, endpoint and tracing configuration.
    # Loading it is independent of graph activation and preserves explicit env.
    from mailroom_sandbox.runtime import load_env_file

    load_env_file()
    run_id = run_id or resolve_run_id(spec)
    if dry_run:
        # Read-only: no run directory and no lock files for a dry run.
        if not run_dir(run_id).exists():
            return {"run_id": run_id, "status": "prepared", "checks": []}
        return _preflight(spec, run_id=run_id, config_path=config_path,
                          offline=offline, force=force, dry_run=True, live=live,
                          require_expanded_inputs=require_expanded_inputs)
    store = RunStore(run_dir(run_id))
    try:
        with store.acquire(blocking=False), store.control():
            return _preflight(spec, run_id=run_id, config_path=config_path,
                              offline=offline, force=force, dry_run=dry_run, live=live,
                              require_expanded_inputs=require_expanded_inputs)
    except BlockingIOError:
        return {"status": "busy_refused", "run_id": run_id,
                "detail": "run writer is active; cancel and wait for paused before resetting"}


class _OpenRun:
    """A generation that passed the early refusals and can be locked or resumed."""

    def __init__(self, store, existing, report, prompt_block, prompt_text_sha, report_group, package, run_id):
        self.store = store
        self.existing = existing
        self.report = report
        self.prompt_block = prompt_block
        self.prompt_text_sha = prompt_text_sha
        self.report_group = report_group
        self.package = package
        self.run_id = run_id


def _lock_read_failure(store, run_id: str):
    """``(existing lock, failure report)``. A corrupt lock is a loud failure."""
    try:
        existing = store.read_lock()
        store.refuse_replay()
    except RuntimeError as exc:
        # hub#41: a corrupt spec.lock.json is a LOUD preflight failure —
        # never a silent run with spec_hash: null.
        return None, {
            "status": "failed",
            "run_id": run_id,
            "checks": [{"name": "lock", "ok": False, "detail": str(exc)}],
        }
    return existing, None


def _heldout_failure(spec: RunSpec, run_id: str, report: dict[str, Any]):
    """Refuse a sealed held-out before anything is prepared, including a resume."""
    from mailroom_sandbox.heldout_seal import seal_errors

    sealed = seal_errors(spec, run_id)
    if sealed:
        report["status"] = "failed"
        report["checks"].append({"name": "heldout_seal", "ok": False, "detail": "; ".join(sealed)})
        return report
    return None


def _prompt_surface(spec: RunSpec, offline: bool, report: dict[str, Any]):
    """``(prompt block, text digest, failure)``. Drift hashing needs the resolved text."""
    try:
        # Unnamed agents run their lineage frontrunner, never the vendored prompt (prompt_lineage).
        from mailroom_sandbox.prompt_lineage import with_lineage_defaults

        prompt_block = prompt_lock_block(with_lineage_defaults(spec.prompt, spec.task), offline=offline)
    except (KeyError, PromptSelectionError) as exc:
        report["status"] = "failed"
        report["checks"] = [{"name": "prompt", "ok": False, "detail": str(exc)}]
        return None, None, report
    prompt_text_sha = _prompt_text_sha(prompt_block)
    report["checks"].append({"name": "prompt", "ok": True, "detail": _prompt_summary(prompt_block)})
    return prompt_block, prompt_text_sha, None


def _blind_routing_failure(spec: RunSpec, report: dict[str, Any]):
    """A live pipeline must not be handed the gold class (oracle routing)."""
    if spec.task == "pipeline" and spec.job.blind_routing is False and not spec.job.mock:
        report["status"] = "failed"
        report["checks"].append({"name": "blind_routing", "ok": False, "detail": (
            "job.blind_routing: false gives the pipeline graph the ground truth (oracle routing, "
            "llm-mailroom #207); a live run must be blind: drop the key or set it to true")})
        return report
    return None


def _identity_context(spec: RunSpec, report: dict[str, Any], run_id: str, config_path):
    """``(package, report group, failure)``. Checkout and hotfix checks share the report."""
    try:
        report_group = _resolve_report_group(spec, run_id=run_id, config_path=config_path)
    except ValueError as exc:
        report["status"] = "failed"
        report["checks"].append({"name": "report_group", "ok": False, "detail": str(exc)})
        return None, None, report
    # SAND-104 (#312): the code must come from the checkout the run is launched from,
    # both for a new lock and for a start that reuses one.
    package = package_checkout()
    report["checks"].append(_checkout_check(package))
    if not report["checks"][-1]["ok"]:
        report["status"] = "failed"
        return None, None, report
    report["checks"].append(_hotfix_check())
    if not report["checks"][-1]["ok"]:
        report["status"] = "failed"
        return None, None, report
    report["checks"].append(_scoring_hotfix_check())
    if not report["checks"][-1]["ok"]:
        report["status"] = "failed"
        return None, None, report
    return package, report_group, None


def _open_preflight(spec: RunSpec, *, run_id: str, config_path, offline: bool, dry_run: bool):
    """The early refusals. A dict is the finished report; an ``_OpenRun`` continues."""
    run_id = run_id or resolve_run_id(spec)
    store = RunStore(run_dir(run_id))
    existing, failed = _lock_read_failure(store, run_id)
    if failed is not None:
        return failed
    report: dict[str, Any] = {"run_id": run_id, "status": "prepared", "checks": []}
    if dry_run:
        return report
    failed = _heldout_failure(spec, run_id, report)
    if failed is not None:
        return failed
    prompt_block, prompt_text_sha, failed = _prompt_surface(spec, offline, report)
    if failed is not None:
        return failed
    failed = _blind_routing_failure(spec, report)
    if failed is not None:
        return failed
    package, report_group, failed = _identity_context(spec, report, run_id, config_path)
    if failed is not None:
        return failed
    return _OpenRun(store, existing, report, prompt_block, prompt_text_sha, report_group, package, run_id)


def _hotfix_drift_detail(existing: Mapping[str, Any], store) -> str | None:
    """Why a recorded hotfix set, or a pre-hotfix lock with completed work, cannot resume."""
    from mailroom_sandbox import vendor_hotfixes

    # Locks from before the hotfix layer carry no key and resume; a recorded set must match.
    if "vendor_hotfixes" in existing and existing["vendor_hotfixes"] != vendor_hotfixes.describe():
        return "vendor hotfix set changed since this run was locked; restore it or use --force to re-lock"
    from mailroom_sandbox import scoring_hotfixes

    if "scoring_hotfixes" in existing and existing["scoring_hotfixes"] != scoring_hotfixes.describe():
        return "scoring hotfix set changed since this run was locked; restore it or use --force to re-lock"
    # A lock from before the scoring hotfix layer with completed work would resume its pending
    # rows on the hotfixed basis next to rows scored raw: one run, two scoring bases.
    if "scoring_hotfixes" not in existing and store.read_checkpoint():
        return ("this run was locked before the scoring hotfixes and has completed work; resuming "
                "would mix scoring bases: use --force to re-lock and rerun it")
    return None


def _locked_task_gt(existing: Mapping[str, Any]):
    """The lock's task-GT flag, or None when an older lock does not prove it."""
    selection = (existing.get("dataset") or {}).get("selection") or {}
    locked_filter = selection.get("require_task_gt")
    if type(locked_filter) is not bool:
        # Post-filter locks that explicitly hashed True remain unambiguous.
        # Older omitted flags can mean either filtered or unfiltered: fail
        # closed instead of treating the old hash as proof of False.
        recorded = ((existing.get("spec_core") or {}).get("dataset") or {}).get("require_task_gt")
        return True if recorded is True else None
    return locked_filter


def _optional_lock_drifted(existing: Mapping[str, Any], key: str, current) -> bool:
    """A key absent on older locks resumes. A present key still drifts."""
    return key in existing and existing.get(key) != current


def _spec_fields_drifted(existing, spec: RunSpec, prompt_text_sha: str, report_group, locked_filter) -> bool:
    """Spec hash, prompt text, runbook, or report group moved since the lock."""
    if existing.get("spec_hash") != spec.spec_hash() or locked_filter != spec.dataset.require_task_gt:
        return True
    recorded_prompt = existing.get("prompt_text_sha")
    if recorded_prompt and recorded_prompt != prompt_text_sha:
        return True
    if _optional_lock_drifted(existing, "runbook_id", spec.runbook_id or None):
        return True
    return _optional_lock_drifted(existing, "report_group", report_group or None)


def _drift_refusal(existing, force: bool, spec: RunSpec, store, run_id: str, prompt_text_sha: str, report_group):
    """Refuse resume when the locked identity no longer matches this checkout."""
    if not existing or force:
        return None
    from mailroom_sandbox.dependency_sources import verify_locked

    try:
        verify_locked(existing)
    except ValueError as exc:
        return {"status": "drift_refused", "run_id": run_id, "detail": str(exc)}
    detail = _hotfix_drift_detail(existing, store)
    if detail:
        return {"status": "drift_refused", "run_id": run_id, "detail": detail}
    locked_filter = _locked_task_gt(existing)
    if locked_filter is None:
        return {"status": "drift_refused", "run_id": run_id,
                "detail": "Legacy lock does not prove task-GT selection; preserve it and use --force to archive/re-lock explicitly"}
    drifted = _spec_fields_drifted(existing, spec, prompt_text_sha, report_group, locked_filter)
    # A changed 4.2.0 routing digest refuses on its own. Spec, prompt, runbook,
    # or report-group drift keeps the broader message.
    routing_detail = _routing_identity_drift(existing)
    if not drifted and routing_detail:
        return {"status": "drift_refused", "run_id": run_id, "detail": routing_detail}
    fit_detail = _context_fit_drift(existing, spec) if not drifted else None
    if fit_detail:
        return {"status": "drift_refused", "run_id": run_id, "detail": fit_detail}
    if drifted:
        return {
            "status": "drift_refused",
            "run_id": run_id,
            "spec_hash": spec.spec_hash(),
            "locked_spec_hash": existing.get("spec_hash"),
            "detail": (
                "spec, resolved prompt text, runbook, or report group drifted "
                "since the lock; pass --force to re-lock"
            ),
        }
    return None


def _fit_mismatch(locked: Any, taxonomy: Mapping[str, Any]) -> str | None:
    """Why fitted windows no longer match, or None for a match or a legacy lock."""
    if not isinstance(locked, dict) or not locked.get("sha256"):
        return None
    from mailroom_sandbox.context_fit import identity

    if identity(taxonomy)["sha256"] == locked["sha256"]:
        return None
    return (
        "context fit changed since this run was locked (model window or overlay); "
        "pass --force to re-lock"
    )


def _lock_spec_view(lock: Mapping[str, Any]):
    """The profile, model, routes and knobs a lock froze, as ``taxonomy_for_spec`` reads them."""
    from types import SimpleNamespace

    engine = lock.get("engine") if isinstance(lock.get("engine"), Mapping) else {}
    return SimpleNamespace(
        profile=lock.get("profile") or "modal-vllm",
        engine=SimpleNamespace(model=engine.get("model")),
        agent_models=lock.get("agent_models") or {},
        agent_knobs=lock.get("agent_knobs") or {},
        agent_routes=lock.get("agent_routes") or {},
        confidence=lock.get("confidence") or {},
        run_id=lock.get("run_id"),
    )


def context_fit_resume_detail(lock: Mapping[str, Any]) -> str | None:
    """Refuse execution when this checkout would fit different windows than the lock.

    Run-id resume does not repeat preflight. Locks without ``context_fit.sha256``
    still run. A matching stamp runs. A mismatch must stop before any document.
    """
    if not isinstance(lock, Mapping):
        return None
    from mailroom_sandbox.job.context_plan import taxonomy_for_spec

    knobs = lock.get("agent_knobs") or {}
    return _fit_mismatch(lock.get("context_fit"), taxonomy_for_spec(_lock_spec_view(lock), knobs))


def _context_fit_drift(existing, spec: RunSpec) -> str | None:
    """Refuse a lock whose fitted windows no longer match this checkout.

    Locks written before the stamp have no ``context_fit`` key and still resume.
    """
    from mailroom_sandbox.job.context_plan import taxonomy_for_spec

    return _fit_mismatch(
        existing.get("context_fit"),
        taxonomy_for_spec(spec, existing.get("agent_knobs") or {}),
    )


def _foreign_store_refusal(existing, spec: RunSpec, force: bool, run_id: str):
    """Refuse a --force re-lock of a store that belongs to another Modal app."""
    if not existing or not force or _takeover_foreign_store():
        return None
    foreign = _foreign_app(existing, spec)
    if not foreign:
        return None
    current_app = spec.engine.modal.app if spec.engine.modal else None
    return {
        "status": "foreign_store_refused",
        "run_id": run_id,
        "lock_app": foreign,
        "spec_app": current_app,
        "detail": (
            f"this store is locked to modal app {foreign!r}, this fleet is "
            f"{current_app!r} — a --force re-lock would archive another "
            "fleet's items and both fleets would then append to the same "
            "items.jsonl. Run the cell on the fleet that owns the store, "
            "remove the store, or set SANDBOX_TAKEOVER_FOREIGN_STORE=1 to "
            "take it over deliberately."
        ),
    }


def _writer_still_live(store, force: bool, cp: Mapping[str, Any]) -> bool:
    """A forced re-lock must not archive a generation that may still be writing."""
    remote_call = (cp.get("remote") or {}).get("call_id")
    if force and remote_call:
        from mailroom_sandbox.job.remote import terminal_confirmed

        # A stale checkpoint or diagnostic call graph is not proof of death.
        remote_busy = not terminal_confirmed(store)
    else:
        remote_busy = False
    return bool(force and (remote_busy or (cp.get("state") == "running" and not remote_call)))


def _note_trace_reads_drift(spec: RunSpec, store, report: dict[str, Any]) -> None:
    """Say so when ``job.trace_reads`` differs from the prepared lock; the lock wins.

    The switch is observational and not part of ``spec_hash`` (hashing it would refuse resume for
    every existing lock), so a changed value is neither drift nor a new generation: the run keeps
    recording, or not recording, as it was locked. This is a note, not a refusal, because the only
    way to change it is ``--force``, which archives the whole generation (finished items included)
    for a setting that moves no route, score or cost.
    """
    if spec.task != "pipeline":  # only pipeline runs record read ranges
        return
    locked = (store.read_lock() or {}).get("job", {}).get("trace_reads", True)
    if locked is spec.job.trace_reads:
        return
    report["checks"].append({
        "name": "trace_reads",
        "ok": True,
        "detail": (
            f"job.trace_reads is {str(spec.job.trace_reads).lower()} in this spec but the prepared lock "
            f"keeps {str(bool(locked)).lower()}; the run uses the lock's value. It is not part of the spec "
            "hash, so a re-preflight does not change it; to apply the new value re-lock with --force "
            "(this archives the generation, finished items included)."
        ),
    })


def _reuse_existing_lock(spec: RunSpec, store, existing, force: bool, report: dict[str, Any], *, require_expanded_inputs: bool = False):
    """The existing generation's report, or None when preparation should continue."""
    if not existing:
        return None
    if _writer_still_live(store, force, store.read_checkpoint() or {}):
        return {"status": "busy_refused", "run_id": report["run_id"],
                "detail": "generation may still have a live writer; cancel and confirm termination first"}
    if force:
        return None
    # Existing lock is the generation's commit point. Validate its
    # artifacts, never recreate missing bytes under that identity.
    try:
        store.verify_generation()
    except RuntimeError as exc:
        report["status"] = "failed"
        report["checks"].append({"name": "generation", "ok": False, "detail": str(exc)})
        return report
    # Credentials live in the shell, not the lock: a lock prepared where
    # the key was set must not let `run start` proceed where it is not.
    eng_errors = _engine_errors(spec)
    if eng_errors:
        report["status"] = "failed"
        report["checks"].append({"name": "engine_spec", "ok": False, "detail": "; ".join(eng_errors)})
        return report
    report["checks"].append({"name": "engine_spec", "ok": True, "detail": _engine_summary(spec)})
    report.update({"spec_hash": existing["spec_hash"], "lock_path": str(store.lock_path)})
    _note_trace_reads_drift(spec, store, report)
    frozen = (store.read_lock() or {}).get("agent_knobs") or {}
    _record_context_plan(report, spec, store, frozen)  # same report shape as a fresh preparation
    if not _record_decision_windows(report, spec):
        return report
    require = require_expanded_inputs or bool(spec.job.require_expanded_inputs)
    if not _record_expanded_inputs(report, spec, frozen, require=require):
        return report
    return report


def _existing_generation(spec: RunSpec, opened: _OpenRun, *, force: bool, require_expanded_inputs: bool = False):
    """Drift, foreign-store, and reuse refusals. None means prepare a new generation."""
    failed = _drift_refusal(
        opened.existing, force, spec, opened.store, opened.run_id, opened.prompt_text_sha, opened.report_group,
    )
    if failed is not None:
        return failed
    failed = _foreign_store_refusal(opened.existing, spec, force, opened.run_id)
    if failed is not None:
        return failed
    return _reuse_existing_lock(
        spec, opened.store, opened.existing, force, opened.report,
        require_expanded_inputs=require_expanded_inputs,
    )


def _archive_replaced_generation(store, existing, force: bool, report: dict[str, Any]) -> None:
    """Archive a forced re-lock so new dataset bytes never sit under an old lock."""
    archived = store.archive_generation() if (existing and force) else None
    if archived is not None:
        report["archived"] = str(archived)


def _dataset_check(prov: Mapping[str, Any]) -> dict[str, Any]:
    excluded = ""
    if prov.get("excluded"):
        excluded = f" excluded={prov['excluded']['matched']}/{prov['excluded']['listed']}"
    return {
        "name": "dataset",
        "ok": True,
        "detail": (
            f"rows={prov['rows']} sha256={prov['sha256'][:12]} "
            f"revision={prov.get('revision_requested')}{excluded}"
        ),
    }


def _target_row_failure(spec: RunSpec, store, report: dict[str, Any]):
    """Zero matching rows for a level-2 target is a config error, not an empty run."""
    if not spec.target:
        return None
    from mailroom_sandbox.eval.primary import rows_for_class

    try:
        narrowed = len(rows_for_class(store.dataset_rows(), spec.target))
    except ValueError as exc:
        report["status"] = "failed"
        report["checks"].append({"name": "target", "ok": False, "detail": str(exc)})
        return report
    report["checks"].append({"name": "target", "ok": True, "detail": f"{spec.target}: {narrowed} row(s)"})
    return None


def _prepare_dataset_rows(spec: RunSpec, store, report: dict[str, Any]):
    """``(provenance, failure)``. The prepared file is removed when a held-out id leaks."""
    try:
        prov = prepare_subset(spec.dataset, store.dataset_path)
        report["checks"].append(_dataset_check(prov))
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["checks"].append({"name": "dataset", "ok": False, "detail": str(exc)})
        return None, report
    from mailroom_sandbox.heldout_seal import leak_errors

    if spec.dataset.exclude_ids_file:
        leaked = leak_errors(spec, (row.get("id") for row in store.dataset_rows()))
        if leaked:
            store.dataset_path.unlink(missing_ok=True)  # no held-out text stays behind unlocked
            report["status"] = "failed"
            report["checks"].append({"name": "heldout_seal", "ok": False, "detail": "; ".join(leaked)})
            return None, report
    failed = _target_row_failure(spec, store, report)
    if failed is not None:
        return None, failed
    return prov, None


def _engine_spec_failure(spec: RunSpec, report: dict[str, Any]):
    eng_errors = _engine_errors(spec)
    if eng_errors:
        report["status"] = "failed"
        report["checks"].append({"name": "engine_spec", "ok": False, "detail": "; ".join(eng_errors)})
        return report
    report["checks"].append({"name": "engine_spec", "ok": True, "detail": _engine_summary(spec)})
    return None


def _record_probe(store, report: dict[str, Any], run_id: str, probe: Mapping[str, Any]):
    """Attach a cold-boot measurement when the live probe reports one."""
    boot_seconds = probe.get("cold_boot_seconds")
    if boot_seconds is None:
        return
    measurement = record_cold_boot(store, probe, run_id=run_id)
    if measurement is None:
        return
    report["cold_boot_seconds"] = measurement["cold_boot_seconds"]
    report["cold_boot_path"] = str(store.cold_boot_path)
    report["checks"][-1]["detail"] += f" | cold_boot={measurement['cold_boot_seconds']:.2f}s"


def _live_probe_failure(spec: RunSpec, store, report: dict[str, Any], run_id: str, live: bool):
    if not live:
        return None
    probe = _probe_engine(spec)
    report["checks"].append(
        {"name": "engine_probe", "ok": probe["ok"], "detail": probe.get("reason", probe.get("detail", "ok"))}
    )
    if not probe["ok"]:
        report["status"] = "failed"
        report["checks"][-1]["detail"] = probe.get("reason", "probe failed")
        return report
    _record_probe(store, report, run_id, probe)
    return None


def _langfuse_failure(spec: RunSpec, sink, offline: bool, report: dict[str, Any]):
    """Missing Langfuse credentials or SDK. Other sinks are not checked here."""
    if spec.trace.sink != "langfuse" or offline:
        return None
    if not sink.headers.get("Authorization"):
        report["status"] = "failed"
        report["checks"].append(
            {"name": "trace_sink", "ok": False, "detail": "langfuse keys unset (LANGFUSE_PUBLIC_KEY/SECRET_KEY)"}
        )
        return report
    if find_spec("langfuse") is None:
        report["status"] = "failed"
        report["checks"].append(
            {"name": "trace_sink", "ok": False,
             "detail": "langfuse SDK missing: install mailroom-sandbox[observability] or set trace.sink: none"}
        )
        return report
    return None


def _trace_sink_failure(spec: RunSpec, report: dict[str, Any], run_id: str, offline: bool):
    try:
        sink = resolve_sink(
            sink=spec.trace.sink,
            otlp=spec.trace.otlp,
            endpoint=spec.trace.endpoint,
            environment=spec.trace.environment,
            service_name="sandbox-job",
            run_id=run_id,
            tags=spec.trace.tags,
        )
        failed = _langfuse_failure(spec, sink, offline, report)
        if failed is not None:
            return failed
        report["checks"].append(
            {"name": "trace_sink", "ok": True, "detail": f"{spec.trace.sink} -> {sink.endpoint or '(no exporter)'}"}
        )
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["checks"].append({"name": "trace_sink", "ok": False, "detail": str(exc)})
        return report
    return None


def _runtime_checks(spec: RunSpec, opened: _OpenRun, *, live: bool, offline: bool):
    """Engine, optional live probe, trace sink, and the Modal guard. None means continue."""
    failed = _engine_spec_failure(spec, opened.report)
    if failed is not None:
        return failed
    failed = _live_probe_failure(spec, opened.store, opened.report, opened.run_id, live)
    if failed is not None:
        return failed
    failed = _trace_sink_failure(spec, opened.report, opened.run_id, offline)
    if failed is not None:
        return failed
    opened.report["checks"].append(
        {"name": "modal_spec", "ok": _modal_check(spec),
         "detail": "modal guards ok" if _modal_check(spec) else "modal guard failed"}
    )
    return None


def _frozen_dataset_hashes(prov: Mapping[str, Any], spec: RunSpec):
    """Source, exclusion, and near-gold hashes of the bytes the draw actually used."""
    source_sha = (prov.get("metadata") or {}).get("sha256") if spec.dataset.is_local() else None
    exclude_sha = (prov.get("excluded") or {}).get("sha256")
    near_gold_sha = ((prov.get("metadata") or {}).get("near_gold_labels") or {}).get("overlay_sha256")
    return source_sha, exclude_sha, near_gold_sha


def _stamp_optional_lock(lock: dict[str, Any], spec: RunSpec, prompt_block, report_group) -> None:
    """Assignments, prompt versions, runbook, and report group, only when the run has them."""
    if spec.agent_routes or spec.agent_knobs or spec.agent_models:
        from mailroom_sandbox.agent_routes import describe

        lock["agent_assignments"] = describe(spec)
    selected = selection_from_lock(prompt_block)
    if selected:
        # The selected eval-environment keys + sha256 are part of the run's identity.
        lock["prompt_versions"] = selected.versions_stamp()
    if spec.runbook_id:
        lock["runbook_id"] = spec.runbook_id
    if report_group:
        lock["report_group"] = report_group


def _prepared_total(spec: RunSpec, store) -> int:
    total = len(store.dataset_rows())
    if spec.target:
        from mailroom_sandbox.eval.primary import rows_for_class

        total = len(rows_for_class(store.dataset_rows(), spec.target))
    return total


def _commit_prepared_lock(spec: RunSpec, opened: _OpenRun, prov: Mapping[str, Any], run_knobs) -> dict[str, Any]:
    """Write the prompt lock, the spec lock, and the prepared checkpoint."""
    from mailroom_sandbox.dependency_sources import describe

    report = opened.report
    store = opened.store
    # prepare_subset hashes the exact immutable byte buffer it normalized. Use
    # that provenance for every new identity, even if the source path changed
    # after preparation or while engine checks were running.
    source_sha, exclude_sha, near_gold_sha = _frozen_dataset_hashes(prov, spec)
    frozen_core = spec_core(spec, source_sha256=source_sha, exclude_ids_sha256=exclude_sha,
                            near_gold_sha256=near_gold_sha)
    frozen_hash = core_hash(frozen_core)
    store.write_prompt_lock(opened.prompt_block)
    lock = {
        "schema_version": 1,
        "lock_kind": "spec.lock",
        "run_id": opened.run_id,
        "created_at": checkpoint.utc_now(),
        "generation_id": uuid.uuid4().hex,
        "spec_hash": frozen_hash,
        "prompt_text_sha": opened.prompt_text_sha,
        "task": spec.task,
        **({"target": spec.target} if spec.target else {}),
        "profile": spec.profile,
        "agent_models": dict(spec.agent_models),
        **({"agent_routes": {name: route.model_dump() for name, route in spec.agent_routes.items()}} if spec.agent_routes else {}),
        **({"reviewer": _reviewer_lock(spec)} if spec.reviewer else {}),
        **({"extraction_gate": _extraction_gate_lock(spec)} if spec.extraction_gate else {}),
        **({"decision_slots": _decision_slots_lock(spec)} if spec.decision_slots else {}),
        **({"confidence": spec.confidence} if spec.confidence else {}),
        "prompt": opened.prompt_block,
        "engine": spec.engine.model_dump(),
        "job": spec.job.model_dump(),
        "trace": spec.trace.model_dump(),
        "dataset": _dataset_lock(prov, spec),
        "otel": {"sink": spec.trace.sink, "environment": spec.trace.environment},
        "versions": _versions(),
        "dependency_sources": describe(),
        "vendor_hotfixes": _hotfix_identity(),
        "scoring_hotfixes": _scoring_hotfix_identity(),
        "git": git_snapshot(),
        "package": dict(opened.package),
        "spec_core": frozen_core,
    }
    # Freeze the resolved per-agent generation knobs (max_tokens / max_input_chars /
    # chunk_chars / temperature). Without this the card can only read the LIVE posture
    # table, so editing a posture later silently rewrites what every historical card
    # claims the run was configured with — and the contracts whole-document change is
    # exactly such an edit.
    lock["agent_knobs"] = deepcopy(run_knobs)
    from mailroom_sandbox.context_fit import identity
    from mailroom_sandbox.job.context_plan import taxonomy_for_spec

    # Freeze the fitted windows. A later price sheet or overlay must not change
    # what a resumed run sends. Locks without this key still resume.
    lock["context_fit"] = identity(taxonomy_for_spec(spec, run_knobs))
    # Freeze the resolved confidence block (vendored taxonomy, overlay, then the run's own
    # overrides) so the routing audit reports the thresholds this run used; a later overlay
    # edit must not rewrite a finished run's settings.
    from mailroom_sandbox.job.routing_audit import effective_thresholds
    lock["effective_confidence"] = effective_thresholds(spec.confidence)
    # Freeze the resolved table for model-only runs too: otherwise runtime.activate()
    # rebuilds the remaining agents from the live profile/taxonomy, so a later
    # judge_model edit silently changes a resumed run without changing its lock.
    _stamp_optional_lock(lock, spec, opened.prompt_block, opened.report_group)
    # The lock is the commit point (docs/jobs.md). Publish it only after the
    # checkpoint carries the same spec and generation, so a crash cannot leave
    # a lock whose generation check has nothing to verify.
    store.write_checkpoint(
        state="prepared", cursor=0, total=_prepared_total(spec, store), remote=None,
        spec_hash=frozen_hash, generation_id=lock["generation_id"],
    )
    store.write_lock(lock)
    store.append_event("preflight_ok", "info", spec_hash=frozen_hash)
    report.update({"status": "prepared", "spec_hash": frozen_hash, "lock_path": str(store.lock_path)})
    return report


def _preflight(
    spec: RunSpec,
    *,
    run_id: str = "",
    config_path: str | Path | None = None,
    offline: bool = False,
    force: bool = False,
    dry_run: bool = False,
    live: bool = False,
    require_expanded_inputs: bool = False,
) -> dict[str, Any]:
    """Validate an existing generation or prepare artifacts and write a new lock.

    Return ``prepared``, ``failed``, ``drift_refused``, ``busy_refused``, or
    ``foreign_store_refused`` in the report's status. ``dry_run`` checks
    existing lock readability and replay ownership, without validating domains or writing artifacts.
    ``force`` archives an eligible existing generation before preparing its
    replacement. A legacy lock that cannot prove task-GT selection is refused.
    New local dataset identity uses the prepared source hash when available.
    Caught prompt, dataset, and tracing errors become failed
    reports; uncaught configuration and file-access errors propagate.
    """
    opened = _open_preflight(spec, run_id=run_id, config_path=config_path, offline=offline, dry_run=dry_run)
    if isinstance(opened, dict):
        return opened
    stopped = _existing_generation(
        spec, opened, force=force, require_expanded_inputs=require_expanded_inputs,
    )
    if stopped is not None:
        return stopped
    _archive_replaced_generation(opened.store, opened.existing, force, opened.report)
    prov, failed = _prepare_dataset_rows(spec, opened.store, opened.report)
    if failed is not None:
        return failed
    run_knobs = _run_knobs(spec, opened.run_id)
    _record_context_plan(opened.report, spec, opened.store, run_knobs)
    if not _record_decision_windows(opened.report, spec):
        return opened.report
    require = require_expanded_inputs or bool(spec.job.require_expanded_inputs)
    if not _record_expanded_inputs(opened.report, spec, run_knobs, require=require):
        return opened.report
    failed = _runtime_checks(spec, opened, live=live, offline=offline)
    if failed is not None:
        return failed
    return _commit_prepared_lock(spec, opened, prov, run_knobs)
