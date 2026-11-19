#!/usr/bin/env python3
"""Evaluation runbook R01 gate: did every smoke model's calls go to its pinned provider and model?

Reads the served-provider ledger(s) that ``SANDBOX_SERVED_LOG`` wrote during the R01 smoke
runs (``mailroom_sandbox.provider_pins``) and the run configs that produced them. For each
model a config exercises, the gate fails when the ledger holds:

* no rows for the model,
* fewer rows than the expected calls (the config's ``dataset.limit`` documents times the
  model's per-document agents), or
* any row whose ``status`` is not ``verified`` (``unverified``, ``mismatch`` or missing;
  ``mismatch: false`` alone is not evidence).

Per-document agents are counted on the path every document takes: ``task: pipeline`` runs
the sorter and one specialist per document (2 when both are on the model; judge, reviewer
and arbiter calls are conditional and count only as extra rows); a sorter-only
(``sorter``/``isolated``), specialist or single-agent task runs 1; a Decisions-API reviewer
calibration (``task: sorter_reviewer``, ``reviewer.backend: decisions``) runs 1 decision per
document. A document the graph parks before extraction therefore fails the gate on count,
which is deliberate: the gate cannot tell a skipped call from an unrecorded one.
``--per-doc N`` overrides the count for every config. Rows for a model no config names fail
the gate too (something else served calls in the run) unless ``--allow-extra-models``.

Ledger counts alone pass trivially when one agent makes many calls (R01 i01: windowed sorter
reads filled the per-path minimum while two merger documents never reached a specialist), so
the gate also reads each run's item records (``--run-dir``, default the run store of the
config's ``run_id``). Every drawn document needs an ok, error-free item; on a pipeline run
the sorter and the specialist for the class the document was routed to must each have made
a call on it (``usage_by_agent``), and no agent may make more than ``--max-agent-calls``
(default 6) calls on one document, which flags windowed reads and retry loops.

Offline: no network, no spend. Nothing is written unless ``--write-docs`` files the JSON result
as ``docs/<run_id>-<iNN>.r01-gate.json`` in each run's campaign tree. Exit 0 when every model
passes, 1 when any fails, 2 on unreadable input.

    python scripts/check_r01_smoke.py --ledger data/runtime/rb1-r01/served-qwen3.7-flash.jsonl \\
        --config config/runs/rb1-r01-smoke-qwen3.7-flash.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SPECIALIST_TASKS = {"specialist"}
#: The specialist agent (``usage_by_agent`` name) the pipeline sends each class to.
CLASS_SPECIALIST = {"contract": "contracts_specialist", "merger_agreement": "merger_agreement_specialist",
                    "corporate_record": "corporate_records_specialist",
                    "correspondence": "correspondence_specialist",
                    "insurance_claim": "insurance_claims_specialist"}
MAX_AGENT_CALLS = 6
SINGLE_CALL_TASKS = {"sorter", "isolated"}
# Which ledger call path each agent's requests take: the vendored LangChain agents (the sorter
# and the contracts and merger specialists) through the pinned ChatOpenAI subclass, the other
# specialists through the wrapped retry_chat_completion, Decisions models through the Decisions API.
LANGCHAIN_SPECIALIST_CLASSES = {"contract", "merger_agreement"}
LANGCHAIN, RETRY, DECISIONS = "langchain", "retry_chat_completion", "decisions"


def _class_counts(spec: Any) -> dict[str, int] | None:
    """Documents per class when the config draws by ``strata`` buckets, else ``None``."""
    strata = getattr(spec.dataset, "strata", None)
    buckets = strata.get("buckets") if isinstance(strata, dict) else getattr(strata, "buckets", None)
    if not buckets:
        return None
    counts: dict[str, int] = {}
    for bucket in buckets:
        cls = getattr(bucket, "doc_class", None) if not isinstance(bucket, dict) else bucket.get("doc_class")
        n = getattr(bucket, "count", None) if not isinstance(bucket, dict) else bucket.get("count")
        if not cls or not isinstance(n, int):
            return None
        counts[str(cls)] = counts.get(str(cls), 0) + n
    return counts


class GateInputError(ValueError):
    """A ledger or config the gate cannot read."""


def read_ledger(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise GateInputError(f"cannot read ledger {path}: {exc}") from exc
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise GateInputError(f"{path}:{number}: not JSON ({exc})") from exc
            if not isinstance(row, dict) or not row.get("requested_model"):
                raise GateInputError(f"{path}:{number}: not a served-provider ledger row")
            rows.append(row)
    return rows


def _assignments(spec: Any) -> dict[str, dict[str, str]]:
    from mailroom_sandbox.agent_routes import describe

    return describe(spec)


def _specialist_paths(classes: dict[str, int] | None) -> dict[str, int] | None:
    """Specialist calls per path for a per-class draw (``None`` without one: only totals are checked)."""
    if classes is None:
        return None
    lc = sum(n for c, n in classes.items() if c in LANGCHAIN_SPECIALIST_CLASSES)
    return {LANGCHAIN: lc, RETRY: sum(classes.values()) - lc}


def _one_model(spec: Any, routed: dict[str, str], names: list[str], what: str) -> str | None:
    models = {routed.get(name) for name in names}
    if len(models) != 1:
        raise GateInputError(f"{spec.run_id or 'config'}: {what} are split across models {sorted(map(str, models))}; "
                             "pass --per-doc to state the expected calls")
    return models.pop()


def _task_calls(spec: Any, table: dict[str, dict[str, str]], docs: int) -> list[tuple[str | None, str, dict[str, int] | None]]:
    """(model, agent, calls per path) for every agent the task runs on each document."""
    routed = {name: a["model"] for name, a in table.items() if a.get("provider") == "openrouter"}
    specialists = sorted(name for name in table if name.endswith("_specialist"))
    counts = _class_counts(spec)
    if spec.task == "pipeline":
        return [(routed.get("sorter"), "sorter", {LANGCHAIN: docs}),
                (_one_model(spec, routed, specialists, "specialists"), "specialist (one per document)",
                 _specialist_paths(counts))]
    if spec.task in SINGLE_CALL_TASKS:
        return [(routed.get("sorter"), "sorter", {LANGCHAIN: docs})]
    if spec.task in SPECIALIST_TASKS:
        target = spec.target
        names = [n for n in specialists if not target or n == target or n.startswith(str(target))] or specialists
        cls = next(iter(counts)) if counts and len(counts) == 1 else None
        path = (LANGCHAIN if cls in LANGCHAIN_SPECIALIST_CLASSES else RETRY) if cls else None
        return [(_one_model(spec, routed, names, "specialists"), "specialist", {path: docs} if path else None)]
    if spec.task in table:
        return [(routed.get(spec.task), spec.task, None)]
    raise GateInputError(f"{spec.run_id or 'config'}: task {spec.task!r} has no R01 call count; pass --per-doc")


def expected_calls(spec: Any, *, per_doc: int | None = None,
                   assignments: dict[str, dict[str, str]] | None = None) -> dict[str, dict[str, Any]]:
    """``{model: {"docs", "per_doc", "agents", "paths"}}`` for the models one run config exercises on every document."""
    docs = spec.dataset.limit
    if not isinstance(docs, int) or docs <= 0:
        raise GateInputError(f"{spec.run_id or 'config'}: dataset.limit must name the document count")
    reviewer = spec.reviewer
    if spec.task == "sorter_reviewer" and reviewer is not None and reviewer.backend == "decisions":
        return {reviewer.model: {"docs": docs, "per_doc": per_doc or 1, "agents": ["sorter_reviewer (decisions)"],
                                 "paths": {} if per_doc else {DECISIONS: docs}}}
    table = assignments if assignments is not None else _assignments(spec)
    out: dict[str, dict[str, Any]] = {}
    for model, agent, paths in _task_calls(spec, table, docs):
        if not model:
            raise GateInputError(f"{spec.run_id or 'config'}: {agent} is not served over OpenRouter, so no ledger row is written")
        entry = out.setdefault(model, {"docs": docs, "per_doc": 0, "agents": [], "paths": {}})
        entry["per_doc"] += 1
        entry["agents"].append(agent)
        for path, n in (paths or {}).items():
            if n:
                entry["paths"][path] = entry["paths"].get(path, 0) + n
    if per_doc:
        for entry in out.values():
            entry["per_doc"] = per_doc
            entry["paths"] = {}  # an override states the total only
    return out


def gate(rows: list[dict[str, Any]], expected: dict[str, dict[str, Any]], *,
         allow_extra_models: bool = False, run_ids: set[str] | None = None) -> dict[str, Any]:
    """Per-model verdicts plus the overall result.

    With ``run_ids``, only rows stamped with one of those runs count; rows from another run or
    with no ``run_id`` (an earlier launch appending to the same ledger file) are set aside.
    """
    by_model: dict[str, list[dict[str, Any]]] = {}
    other_runs = Counter()
    for row in rows:
        if run_ids is not None and row.get("run_id") not in run_ids:
            other_runs[str(row.get("run_id"))] += 1
            continue
        by_model.setdefault(str(row["requested_model"]), []).append(row)
    models: dict[str, dict[str, Any]] = {}
    for model, want in sorted(expected.items()):
        got = by_model.get(model, [])
        need = want["docs"] * want["per_doc"]
        status = Counter(str(r.get("status") or "missing") for r in got)
        reasons = []
        if not got:
            reasons.append("no ledger rows")
        elif len(got) < need:
            reasons.append(f"{len(got)} rows < {need} expected ({want['docs']} docs x {want['per_doc']} per-doc agents)")
        paths = Counter(str(r.get("call_path") or RETRY) for r in got)
        for path, n_need in sorted((want.get("paths") or {}).items()):
            if paths.get(path, 0) < n_need:
                reasons.append(f"{paths.get(path, 0)} {path} rows < {n_need} expected on that call path")
        not_verified = sum(n for s, n in status.items() if s != "verified")
        if not_verified:
            reasons.append(f"{not_verified} row(s) not verified: {dict(sorted((s, n) for s, n in status.items() if s != 'verified'))}")
        models[model] = {
            "ok": not reasons,
            "rows": len(got),
            "expected_min": need,
            "agents": want["agents"],
            "status": dict(sorted(status.items())),
            "providers": dict(sorted(Counter(str(r.get("served_provider")) for r in got).items())),
            "served_models": dict(sorted(Counter(str(r.get("served_model")) for r in got).items())),
            "call_paths": dict(sorted(paths.items())),
            "expected_paths": dict(sorted((want.get("paths") or {}).items())),
            "pinned_orders": sorted({json.dumps(r.get("pinned_order") or []) for r in got}),
            "reasons": reasons,
        }
    extra = {m: len(r) for m, r in sorted(by_model.items()) if m not in expected}
    ok = all(m["ok"] for m in models.values()) and (allow_extra_models or not extra)
    return {"ok": ok, "models": models, "extra_models": extra, "other_run_rows": dict(sorted(other_runs.items()))}


def run_dir_for(run_id: str) -> Path:
    """The run store a config's ``run_id`` writes (``data/runtime/runs/<run_id>``)."""
    from mailroom_sandbox.job.spec import run_dir

    return Path(run_dir(run_id))


def doc_agents(task: str, item: dict[str, Any]) -> list[str] | None:
    """The agents that must each have called on this document (None: the task's ledger count is per document)."""
    if task == "pipeline":
        cls = str((item.get("pred") or {}).get("doc_type") or "")
        return ["sorter", CLASS_SPECIALIST.get(cls, f"a specialist (routed class {cls or 'none'})")]
    if task in SINGLE_CALL_TASKS:
        return ["sorter"]
    return None


def _items(run: Path) -> list[dict[str, Any]] | None:
    path = run / "items.jsonl"
    if not path.is_file():
        return None
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise GateInputError(f"{path}: {exc}") from exc


def coverage(spec: Any, run: Path, *, max_agent_calls: int = MAX_AGENT_CALLS) -> dict[str, Any]:
    """Per-document agent coverage of one smoke run from its item records."""
    docs = spec.dataset.limit
    items = _items(run)
    if items is None:
        return {"ok": False, "docs": docs, "items": 0, "max_calls": {},
                "reasons": [f"no item records at {run} (pass --run-dir)"]}
    latest: dict[str, dict[str, Any]] = {}
    for item in items:  # a resumed run may append a document again; its last record counts
        latest[str(item.get("item_id"))] = item
    reasons: list[str] = []
    if len(latest) < docs:
        reasons.append(f"{len(latest)} of {docs} documents have an item record")
    max_calls: dict[str, int] = {}
    for doc_id, item in sorted(latest.items()):
        if not item.get("ok") or item.get("error"):
            reasons.append(f"{doc_id}: not ok ({str(item.get('error') or 'ok=false')[:80]})")
            continue
        by_agent = item.get("usage_by_agent") or {}
        calls = {str(a): int((v or {}).get("calls") or 0) for a, v in by_agent.items()} if isinstance(by_agent, dict) else {}
        for agent, n in calls.items():
            max_calls[agent] = max(max_calls.get(agent, 0), n)
            if n > max_agent_calls:
                reasons.append(f"{doc_id}: {agent} made {n} calls (> {max_agent_calls}: windowed reads or a retry loop)")
        for agent in doc_agents(str(spec.task), item) or []:
            if calls.get(agent, 0) < 1:
                reasons.append(f"{doc_id}: {agent} made no call")
    return {"ok": not reasons, "docs": docs, "items": len(latest), "max_calls": dict(sorted(max_calls.items())),
            "reasons": reasons[:20] + ([f"... {len(reasons) - 20} more"] if len(reasons) > 20 else [])}


def render(result: dict[str, Any], *, allow_extra_models: bool = False) -> str:
    lines = []
    for model, m in result["models"].items():
        lines.append(f"{'PASS' if m['ok'] else 'FAIL'} {model}: {m['rows']} rows (>= {m['expected_min']} expected; "
                     f"{', '.join(m['agents'])})")
        lines.append(f"     status {m['status']}  providers {m['providers']}  served {m['served_models']}  "
                     f"paths {m['call_paths']} (need {m['expected_paths']})  pins {', '.join(m['pinned_orders'])}")
        lines.extend(f"     - {reason}" for reason in m["reasons"])
    for run_id, c in sorted((result.get("coverage") or {}).items()):
        lines.append(f"{'PASS' if c['ok'] else 'FAIL'} run {run_id}: {c['items']} item(s) for {c['docs']} document(s); "
                     f"max calls per agent per document {c['max_calls']}")
        lines.extend(f"     - {reason}" for reason in c["reasons"])
    if result.get("other_run_rows"):
        lines.append(f"note rows from other runs set aside: {result['other_run_rows']}")
    if result["extra_models"]:
        tag = "note" if allow_extra_models else "FAIL"
        lines.append(f"{tag} rows for models no config names: {result['extra_models']}")
    lines.append(f"R01 gate: {'PASS' if result['ok'] else 'FAIL'}")
    return "\n".join(lines)


def _merge_expected(expected: dict[str, dict[str, Any]], model: str, want: dict[str, Any]) -> None:
    """Add one config's expectation for ``model``: two configs on one model add their documents up."""
    if model not in expected:
        expected[model] = want
        return
    have = expected[model]
    if have["per_doc"] != want["per_doc"]:
        raise GateInputError(f"{model}: configs disagree on per-document calls; gate them separately")
    have["docs"] += want["docs"]
    for path, n in want.get("paths", {}).items():
        have.setdefault("paths", {})[path] = have["paths"].get(path, 0) + n
    have["agents"] = sorted(set(have["agents"]) | set(want["agents"]))


def expectations(configs: list[Path], *, per_doc: int | None = None) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Expected calls per model over every config, and the run ids whose ledger rows count."""
    from mailroom_sandbox.job.spec import load_run_spec

    expected: dict[str, dict[str, Any]] = {}
    run_ids: set[str] = set()
    for path in configs:
        try:
            spec = load_run_spec(path)
        except Exception as exc:  # noqa: BLE001 — one line per unreadable config
            raise GateInputError(f"cannot load {path}: {exc}") from exc
        if not spec.run_id:
            raise GateInputError(f"{path}: the config needs a run_id, which ledger rows are matched on")
        run_ids.add(str(spec.run_id))
        for model, want in expected_calls(spec, per_doc=per_doc).items():
            _merge_expected(expected, model, want)
    return expected, run_ids


def run_coverage(configs: list[Path], run_dirs: list[Path] | None, *,
                 max_agent_calls: int = MAX_AGENT_CALLS) -> dict[str, dict[str, Any]]:
    """``{run_id: coverage}`` for every config; ``run_dirs`` are matched to configs by directory name."""
    from mailroom_sandbox.job.spec import load_run_spec

    given = {Path(d).name: Path(d) for d in run_dirs or []}
    out: dict[str, dict[str, Any]] = {}
    for path in configs:
        spec = load_run_spec(path)
        run_id = str(spec.run_id)
        run = given.get(run_id) or (Path(run_dirs[0]) if run_dirs and len(run_dirs) == len(configs) == 1
                                    else run_dir_for(run_id))
        out[run_id] = coverage(spec, run, max_agent_calls=max_agent_calls)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ledger", action="append", required=True, type=Path,
                    help="SANDBOX_SERVED_LOG JSONL (repeatable; rows are pooled)")
    ap.add_argument("--config", action="append", required=True, type=Path, nargs="+",
                    help="R01 smoke run config(s) whose models are gated")
    ap.add_argument("--per-doc", type=int, default=None, help="override the per-document call count for every config")
    ap.add_argument("--allow-extra-models", action="store_true",
                    help="report, but do not fail on, rows for models no config names")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--any-run", action="store_true",
                    help="count rows from any run (default: only rows whose run_id is a config's run_id)")
    ap.add_argument("--write-docs", action="store_true",
                    help="also file the JSON result as docs/<run_id>-<iNN>.r01-gate.json in each run's campaign tree")
    ap.add_argument("--iteration", default=None, help="with --write-docs: the iteration (default: the run store's latest)")
    ap.add_argument("--run-dir", action="append", type=Path, default=None,
                    help="a smoke run's store, holding items.jsonl (repeatable; default: each config's run store)")
    ap.add_argument("--max-agent-calls", type=int, default=MAX_AGENT_CALLS,
                    help=f"calls one agent may make on one document (default {MAX_AGENT_CALLS})")
    args = ap.parse_args(argv)
    if args.per_doc is not None and args.per_doc < 1:
        ap.error("--per-doc must be >= 1")
    configs = [path for group in args.config for path in group]
    try:
        rows = read_ledger(args.ledger)
        expected, run_ids = expectations(configs, per_doc=args.per_doc)
    except GateInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = gate(rows, expected, allow_extra_models=args.allow_extra_models,
                  run_ids=None if args.any_run else run_ids)
    try:
        result["coverage"] = run_coverage(configs, args.run_dir, max_agent_calls=args.max_agent_calls)
    except GateInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result["ok"] = result["ok"] and all(c["ok"] for c in result["coverage"].values())
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render(result, allow_extra_models=args.allow_extra_models))
    if args.write_docs:
        for path in write_docs(result, run_ids, ledgers=args.ledger, configs=configs, iteration=args.iteration):
            print(f"wrote {path}", file=sys.stderr)
    return 0 if result["ok"] else 1


def write_docs(result: dict[str, Any], run_ids: Iterable[str], *, ledgers: Iterable[Path], configs: Iterable[Path],
               iteration: str | None = None, root: Path | None = None) -> list[Path]:
    """File the gate result in each run's ``docs/`` and refresh the campaign indexes."""
    from mailroom_sandbox import report_campaigns as rc

    doc = {"schema": "sandbox.r01-gate/v1", "ok": result["ok"], "result": result,
           "ledgers": [{"path": Path(p).name, "sha256": rc.sha256_file(Path(p))} for p in ledgers if Path(p).is_file()],
           "configs": sorted(Path(c).name for c in configs)}
    written, campaigns = [], set()
    for run_id in sorted(run_ids):
        paths = rc.campaign_paths(run_id, iteration, root=root)
        dest = paths.file("docs", "r01-gate", "json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps({**doc, "run_id": run_id}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(dest)
        campaigns.add(paths.key.campaign)
    for campaign in sorted(campaigns):
        try:
            rc.build_campaign(campaign, root=root)
        except Exception as exc:  # noqa: BLE001 - the gate file is written; the index refresh is best-effort
            print(f"warning: campaign index not refreshed: {exc}", file=sys.stderr)
    return written


if __name__ == "__main__":
    sys.exit(main())
