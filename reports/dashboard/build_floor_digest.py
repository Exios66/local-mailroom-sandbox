#!/usr/bin/env python3
"""Rebuild the pipeline-floor digest of ALL previous runs from on-disk artifacts.

Reads (never writes) run directories under ``$BASE/runtime/runs/*`` (live) and
``$BASE/run-history/*`` (archived attempts), plus the vendored LangGraph wiring in
``vendor/llm-mailroom/src/graph/build_graph.py`` (with the edge table in ``route_spec.py``
beside it when ``build_graph()`` calls ``wire_edges``, llm-mailroom #286), and emits:

* ``floor_digest.json`` — the frozen digest contract consumed by ``floor.template.html``
* ``floor_digest.js``   — ``window.DIGEST=<same json>;`` twin for file:// viewing

Usage::

    python build_floor_digest.py [--base DIR] [--out DIR] [--print-summary]

``$BASE`` is ``--base``, else ``$MAILROOM_BASE_DIR``, else ``./data``. ``--out`` defaults
to this script's directory. ``$FLOOR_DIGEST_GRAPH`` overrides the build_graph.py path
(used by the selftest to point at a stub).

Exit codes: 0 ok, 2 no runs found, 3 build_graph.py unparseable, 4 write failure.
Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_GRAPH = REPO_ROOT / "vendor" / "llm-mailroom" / "src" / "graph" / "build_graph.py"

EXIT_NO_RUNS, EXIT_GRAPH, EXIT_WRITE = 2, 3, 4

# Terminal stage vocabulary -> outcome bucket. Anything else is "open" (mid-graph),
# never an error: an unknown stage must not crash the build.
SHIP_STAGES = {"archived", "archive", "ship", "shipped", "done"}
HELD_STAGES = {"review", "human_review", "pending", "pending_review", "held"}
FAIL_STAGES = {"failed", "fail", "error", "aborted"}

# Review-trigger attribution. A parked document is NOT a failure: keep the routed count
# per pipeline stage whose uncertainty sent it to human review. Item-level canonical
# cause tokens (real run artifacts) win; ordered node visits (replay/demo artifacts)
# fall back to the node the document was visiting on the way to human_review. Both
# vocabularies come from the pipeline: cause tokens are vendor llm-mailroom's
# pipeline.reconsideration, nodes are build_graph.py's registered node names.
CAUSE_TRIGGER_STAGE = {
    "class_miss": "classification", "subclass_miss": "classification",
    "sorter_low_confidence": "classification", "reviewer_unavailable": "classification",
    "reviewer_no_text": "classification", "reviewer_ineligible_label": "classification",
    "reviewer_disagreement": "classification", "reviewer_low_confidence": "classification",
    "extraction_miss": "extraction", "hollow_extraction": "extraction",
    "schema_invalid": "extraction", "guardrail": "extraction", "parse_error": "extraction",
    "judge_miss": "judgment", "judge_partial": "judgment", "needs_judge_review": "judgment",
    "reporting_incomplete": "reporting",
}
NODE_TRIGGER_STAGE = {
    "classify": "classification", "retry_classify": "classification",
    "review_classify": "classification", "classification_arbiter": "classification",
    "extract": "extraction", "retry_extract": "extraction",
    "judge_verify": "judgment", "arbiter": "judgment", "boss_escalation": "judgment",
    "compile_report": "reporting",
}

TRAY_LABEL = "(tray)"
CODE_LABEL = "(code)"
LANE_LABEL = "(abort terminal)"
SPECIALIST_LABEL = "specialists (fan inside node)"

GRAPH_NOTE = (
    "Parsed from build_graph.py and, when it calls wire_edges, route_spec.py (read-only): add_edge "
    "pairs plus add_conditional_edges / RouteSpec route "
    "maps whose values name registered nodes; START entry routes are included. Transient "
    "self-loops (edges where source==target) are EXCLUDED from the drawn set; their fires "
    "still count toward the node, never toward an edge. A route key that maps to END (e.g. "
    "human_review -> {'failed': END}) is drawn as a terminal lane node named after the key; "
    "a literal END target is the graph terminal and is not a node box. Run-budget aborts are "
    "additionally attributed by aborts_by_last_node. audit_events mirror _emit_stage_audit "
    "call sites inside node handlers: side effects written to the hash-chained stage audit "
    "log (A-1), drawn as dashed arrows that are not graph edges."
)


class DigestError(Exception):
    """A builder failure with the process exit code the CLI returns."""

    def __init__(self, message: str, code: int = 1):
        """Carry the message and exit code to ``main``."""
        super().__init__(message)
        self.code = code


# ── graph topology ──────────────────────────────────────────────────────────────


def _sym(node: ast.AST | None) -> str | None:
    """A graph symbol: a string constant or the START/END names."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        return {"__start__": "START", "__end__": "END"}.get(value, value)
    if isinstance(node, ast.Name) and node.id in ("START", "END"):
        return node.id
    return None


def _snake(class_name: str) -> str:
    """Convert a class name to lowercase snake case, dropping a trailing _agent."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    return re.sub(r"_agent$", "", snake)


def _call_name(call: ast.Call) -> str | None:
    """Return the called name or final attribute, if the call has either shape."""
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _handler_name(expr: ast.AST, funcs: dict[str, ast.AST]) -> str | None:
    """The node handler inside wrap calls like traced_node("x")(_bounded(handler))."""
    wrappers = {id(n.func) for n in ast.walk(expr) if isinstance(n, ast.Call)}
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and id(n) not in wrappers and n.id in funcs:
            return n.id
    return None


def _attribute(func: ast.AST | None) -> str:
    """Agent/role behind a handler, read from its body; pure-code handlers keep (code)."""
    if func is None:
        return CODE_LABEL
    agents: list[str] = []
    calls: set[str] = set()
    for n in ast.walk(func):
        if isinstance(n, ast.ImportFrom):
            for alias in n.names:
                if re.search(r"(Agent|Judge)$", alias.name):
                    role = _snake(alias.name)
                    if role not in agents:
                        agents.append(role)
        elif isinstance(n, ast.Call):
            name = _call_name(n)
            if name:
                calls.add(name)
    if agents:
        return "+".join(agents)
    if any("specialist" in c.lower() for c in calls):
        return SPECIALIST_LABEL
    if "interrupt" in calls:
        return TRAY_LABEL
    return CODE_LABEL


def _route_spec_edges(path: Path) -> tuple[list[tuple[str | None, list[tuple[str | None, str | None]]]],
                                             list[tuple[str | None, str | None]]] | None:
    """Conditional and plain edges declared in a sibling ``route_spec.py``.

    llm-mailroom #286 moved the edge topology out of ``build_graph()`` into
    ``graph/route_spec.py``: ``ROUTE_SPECS`` holds ``RouteSpec(node, router, destinations)``
    (``destinations`` a dict literal or ``_same("a", "b")``, which maps each name to
    itself) and ``PLAIN_EDGES`` a tuple of ``(source, target)`` pairs. Returns None when
    the file is absent or declares neither table, and raises DigestError for a table
    or ``RouteSpec`` entry it cannot read literally, so a partial topology never ships.
    """
    spec_path = Path(path).with_name("route_spec.py")
    if not spec_path.is_file():
        return None
    try:
        tree = ast.parse(spec_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise DigestError(f"cannot parse {spec_path}: {exc}", EXIT_GRAPH) from exc
    tables: dict[str, ast.AST] = {}
    for n in tree.body:
        target = n.target if isinstance(n, ast.AnnAssign) else (n.targets[0] if isinstance(n, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id in ("ROUTE_SPECS", "PLAIN_EDGES") and n.value is not None:
            tables[target.id] = n.value
    if not tables:
        return None
    def unreadable(what: str) -> DigestError:
        return DigestError(f"{spec_path}: cannot read {what} literally; update build_floor_digest._route_spec_edges",
                           EXIT_GRAPH)

    for name, value in tables.items():
        if not isinstance(value, (ast.Tuple, ast.List)):
            raise unreadable(name)
    conditional: list[tuple[str | None, list[tuple[str | None, str | None]]]] = []
    for call in getattr(tables.get("ROUTE_SPECS"), "elts", []):
        if not (isinstance(call, ast.Call) and _call_name(call) == "RouteSpec" and len(call.args) >= 3):
            raise unreadable("a ROUTE_SPECS entry")
        dest = call.args[2]
        if isinstance(dest, ast.Dict):
            pairs = [(_sym(k), _sym(v)) for k, v in zip(dest.keys, dest.values)]
        elif isinstance(dest, ast.Call) and _call_name(dest) == "_same":
            pairs = [(_sym(a), _sym(a)) for a in dest.args]
        else:
            raise unreadable("a RouteSpec destination map")
        conditional.append((_sym(call.args[0]), pairs))
    plain: list[tuple[str | None, str | None]] = []
    for t in getattr(tables.get("PLAIN_EDGES"), "elts", []):
        if not (isinstance(t, ast.Tuple) and len(t.elts) == 2):
            raise unreadable("a PLAIN_EDGES entry")
        plain.append((_sym(t.elts[0]), _sym(t.elts[1])))
    return conditional, plain


def parse_graph(path: Path) -> dict:
    """Derive graph edges and node labels from a Python graph definition.

    Self-loops are excluded, and conditional routes to END may become named
    terminal lanes. Raises DigestError for read or syntax errors, or if no
    registered nodes or usable edges can be derived. Other unsupported shapes
    may be ignored; decoding errors propagate.
    """
    try:
        source = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DigestError(f"cannot read {path}: {exc}", EXIT_GRAPH) from exc
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise DigestError(f"{path} is not parseable Python: {exc}", EXIT_GRAPH) from exc

    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    calls = sorted(
        (n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)),
        key=lambda n: (n.lineno, n.col_offset),
    )

    registered: dict[str, str | None] = {}
    for c in calls:
        if c.func.attr == "add_node" and c.args and _sym(c.args[0]):
            handler = _handler_name(c.args[1], funcs) if len(c.args) > 1 else None
            registered[_sym(c.args[0])] = handler

    edges: list[tuple[str, str]] = []
    lanes: list[str] = []

    def add(a: str | None, b: str | None) -> None:
        """Record one non-self edge once; unknown/empty endpoints are ignored."""
        if not a or not b or a == b:  # transient self-loops are not drawn
            return
        if (a, b) not in edges:
            edges.append((a, b))

    def known_source(s: str | None) -> bool:
        """True when an edge may start at START or a registered node."""
        return s == "START" or s in registered

    def plain(a: str | None, b: str | None) -> None:
        if known_source(a) and (b == "END" or b in registered):
            add(a, b)

    def conditional(src: str | None, pairs: list[tuple[str | None, str | None]]) -> None:
        if not known_source(src):
            return
        for key, val in pairs:
            if val in registered:
                add(src, val)
            elif val == "END":
                if key and key not in registered and key not in ("END", "START"):
                    if key not in lanes:
                        lanes.append(key)
                    add(src, key)
                else:
                    add(src, "END")

    for c in calls:
        kind = c.func.attr
        if kind == "add_edge" and len(c.args) >= 2:
            plain(_sym(c.args[0]), _sym(c.args[1]))
        elif kind == "add_conditional_edges" and c.args:
            mapping = c.args[2] if len(c.args) > 2 else next(
                (k.value for k in c.keywords if k.arg == "path_map"), None)
            if isinstance(mapping, ast.Dict):
                conditional(_sym(c.args[0]), [(_sym(k), _sym(v)) for k, v in zip(mapping.keys, mapping.values)])

    if any(isinstance(n, ast.Call) and _call_name(n) == "wire_edges" for n in ast.walk(tree)):
        # llm-mailroom #286: build_graph() registers the nodes, route_spec.py declares the edges.
        declared = _route_spec_edges(path)
        if declared is None:
            raise DigestError(f"{path}: wire_edges() is called but no readable route_spec.py sits beside it",
                              EXIT_GRAPH)
        else:
            for src, pairs in declared[0]:
                conditional(src, pairs)
            for a, b in declared[1]:
                plain(a, b)

    if not registered or not edges:
        raise DigestError(
            f"{path}: could not derive a topology (found {len(registered)} add_node and "
            f"{len(edges)} edge calls); refusing to emit a partial graph — the file shape "
            "changed, update build_floor_digest.parse_graph",
            EXIT_GRAPH,
        )
    for a, b in edges:
        for n in (a, b):
            if n not in ("START", "END") and n not in registered and n not in lanes:
                raise DigestError(f"{path}: edge endpoint {n!r} is not a registered node", EXIT_GRAPH)

    node_agents = {n: _attribute(funcs.get(h)) for n, h in registered.items()}
    node_agents.update({lane: LANE_LABEL for lane in lanes})
    # stage-audit emissions (audit A-1): an arrow per _emit_stage_audit call site inside
    # a registered node's handler — side effects the compliance log records, not edges
    audits: dict[str, str] = {}
    for hname, fn in funcs.items():
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_emit_stage_audit" and len(n.args) >= 2):
                event = _sym(n.args[1])
                if event and hname not in audits:
                    audits[hname] = event
    audit_events = {node: audit_events_event for node, handler in registered.items()
                    if (audit_events_event := audits.get(handler))}
    return {
        "edges": [list(e) for e in edges],
        "node_agents": node_agents,
        "audit_events": dict(sorted(audit_events.items())),
        "note": GRAPH_NOTE,
    }


# ── artifact readers (tolerant: missing / torn files degrade, never fabricate) ──


def read_jsonl(path: Path) -> list[dict]:
    """Read object rows, skipping blank, malformed, and non-object lines.

    Missing or unreadable files yield the rows read so far; invalid UTF-8 is
    replaced before parsing.
    """
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def read_json(path: Path) -> dict:
    """Read a JSON object, returning an empty dict for invalid or unreadable data."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _num(value) -> float | None:
    """Convert finite numeric values to float; booleans, NaN, ±Infinity and others give None.

    ``json.loads`` accepts ``NaN``/``Infinity``, and passing them through would crash
    ``int()`` in the token sum and the p50 rounding.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except OverflowError:  # an int too large for a float
            return None
        return f if math.isfinite(f) else None
    return None


def _int_if_whole(x: float):
    """Round to one decimal place and return an integer when the result is whole."""
    x = round(x, 1)
    return int(x) if x == int(x) else x


def discover_runs(base: Path) -> list[tuple[str, Path]]:
    """(source, dir) for every dir containing items.jsonl; history first, names sorted."""
    found: list[tuple[str, Path]] = []
    for source, parent in (("history", base / "run-history"), ("live", base / "runtime" / "runs")):
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir(), key=lambda p: p.name):
            if child.is_dir() and (child / "items.jsonl").is_file():
                found.append((source, child))
    return found


# ── per-run digest ──────────────────────────────────────────────────────────────


def _stage_bucket(stage, ok) -> str:
    """Map a stage to an outcome; unknown stages fail only when ok is False."""
    s = str(stage or "").strip().lower()
    if s in SHIP_STAGES:
        return "ship"
    if s in HELD_STAGES:
        return "held"
    if s in FAIL_STAGES:
        return "failed"
    # unknown / missing stage: an item that errored is failed, anything else is still open
    return "failed" if ok is False else "open"


def _item_stage(item: dict):
    """Return the first truthy stage from the item, pred, or prediction, or None."""
    for holder in (item, item.get("pred"), item.get("prediction")):
        if isinstance(holder, dict) and holder.get("stage"):
            return holder["stage"]
    return None


def _review_trigger(item: dict, records: list[dict]) -> str | None:
    """The pipeline stage whose uncertainty routed a document to human review, else None.

    Item-level canonical review causes win — read from the item root and its
    ``pred`` / ``prediction`` blocks, since job-runner rows pool them there;
    without any causes the ordered node visit right before the first
    human_review record attributes the route. A routed document with no
    mappable precedent records as "unknown"; None means the doc was never
    routed (no causes, no human_review visit).
    """
    for holder in (item, item.get("pred"), item.get("prediction")):
        if not isinstance(holder, dict):
            continue
        causes = holder.get("review_causes")
        if isinstance(causes, (list, tuple)):
            for cause in (str(c) for c in causes):
                if cause in CAUSE_TRIGGER_STAGE:
                    return CAUSE_TRIGGER_STAGE[cause]
    for idx, rec in enumerate(records):
        if rec.get("node") != "human_review":
            continue
        prev = next((r.get("node") for r in reversed(records[:idx])
                     if r.get("node") not in (None, "human_review")), None)
        return NODE_TRIGGER_STAGE.get(str(prev), "unknown")
    return None


def _empty_outcome() -> dict:
    """A zeroed outcome bucket (ship/held/failed/open/n)."""
    return {"ship": 0, "held": 0, "failed": 0, "open": 0, "n": 0}


def _tokens(nodes: list[dict], items: list[dict]) -> dict:
    """Sum prompt and completion tokens from node records.

    Use item-level token fields only when no node record has numeric usage.
    Missing counts contribute zero.
    """
    prompt = completion = 0
    seen = False
    for r in nodes:
        nested = r.get("tokens") if isinstance(r.get("tokens"), dict) else r.get("usage")
        nested = nested if isinstance(nested, dict) else {}
        p = _num(r.get("prompt_tokens", nested.get("prompt", nested.get("prompt_tokens"))))
        c = _num(r.get("completion_tokens", nested.get("completion", nested.get("completion_tokens"))))
        if p is not None or c is not None:
            seen = True
            prompt += int(p or 0)
            completion += int(c or 0)
    if not seen:  # node records carry no usage: fall back to the per-item usage block
        for it in items:
            prompt += int(_num(it.get("prompt_tokens")) or 0)
            completion += int(_num(it.get("completion_tokens")) or 0)
    return {"prompt": prompt, "completion": completion}


def _inflight(nodes: list[dict]) -> dict[str, list[dict]]:
    """Docs currently mid-node: the latest record (file order) for a doc+node is ``running``.

    ``since`` is the first nonempty string or finite numeric timestamp in ``ts``,
    ``time``, ``started``, or ``started_at``, or None if none qualifies. Nodes
    with no entry are absent. Records missing ``doc``/``node`` are skipped.
    """
    latest: dict[tuple[str, str], dict] = {}
    for r in nodes:
        doc, node = r.get("doc"), r.get("node")
        if doc is None or node is None:
            continue  # torn/partial rows degrade, never crash a build
        latest[(str(doc), str(node))] = r  # a later done/error/complete replaces the running row
    out: dict[str, list[dict]] = {}
    for (doc, node), r in latest.items():
        if r.get("status") != "running":
            continue
        since = None
        for key in ("ts", "time", "started", "started_at"):
            v = r.get(key)
            if isinstance(v, str) and v:
                since = v
            elif _num(v) is not None:
                since = _num(v)
            if since is not None:
                break
        out.setdefault(node, []).append({"doc": doc, "since": since})
    return dict(sorted(out.items()))


def _avg_doc_ms(items: list[dict]):
    """Mean finite ``latency_ms`` values in milliseconds, rounded to one decimal.

    Return None when no item has a finite numeric latency. Item status is not checked;
    an overflow while computing or rounding the mean propagates.
    """
    ms = [v for v in (_num(it.get("latency_ms")) for it in items) if v is not None]
    return _int_if_whole(sum(ms) / len(ms)) if ms else None


def _pred_class(item: dict) -> str | None:
    """The doc_type the run recorded for an item, if any.

    Pipeline rows carry it in ``pred``; job-runner sorter rows store the class as the
    top-level ``predicted`` string (``expected`` alongside), so read that too.
    """
    for holder in (item.get("pred"), item.get("prediction"), item):
        if isinstance(holder, dict) and holder.get("doc_type"):
            return str(holder["doc_type"])
    predicted = item.get("predicted")
    return predicted if isinstance(predicted, str) and predicted else None


def _routing(items: list[tuple[str, dict]], ds_class: dict[str, str]) -> dict[str, dict]:
    """Count expected, predicted, and matching classes for items with both labels.

    Nonempty dataset labels take precedence over item-level expected labels. Each class
    maps to ``gt``, ``pred``, and ``match`` counts, including predicted-only classes.
    """
    routing: dict[str, dict] = {}
    for item_id, it in items:
        exp = ds_class.get(item_id) or str(it.get("expected_doc_class") or it.get("expected") or "")
        pred = _pred_class(it)
        if not exp or not pred:
            continue
        routing.setdefault(exp, {"gt": 0, "pred": 0, "match": 0})["gt"] += 1
        routing.setdefault(pred, {"gt": 0, "pred": 0, "match": 0})["pred"] += 1
        if exp == pred:
            routing[exp]["match"] += 1
    return dict(sorted(routing.items()))



# ── analysis helpers (per-document flow, scores against ground truth) ───────────

# A document table is kept per run for the viewer's Documents tab; bigger runs keep the
# first DOC_ROW_CAP rows (by item order) and say so in ``docs_truncated``.
DOC_ROW_CAP = 5000
# A run whose checkpoint still says ``running`` but whose artifacts have not changed for
# this long is shown as ``stalled`` (a killed process never rewrites its checkpoint).
# ``$FLOOR_STALL_SECONDS`` overrides it.
STALL_AFTER_S = 900.0
# Label tiers in precedence order (Hub > interim > near_gold): the tier a document's
# extraction score rests on is the LOWEST tier that filled any of its fields. Rows from the
# repo's own fixture manifest (``dataset: sandbox-fixtures``) are hand-written test labels,
# not Hub ground truth, and get their own ``fixture`` tier.
LABEL_TIERS = ("hub", "fixture", "interim", "near_gold")
FIXTURE_DATASETS = {"sandbox-fixtures"}
# A document with a GT class but no predicted class counts as a miss under this label
# once it reached a terminal outcome (an open document is still undecided).
UNKNOWN_CLASS = "unknown"


def _score_value(item: dict) -> float | None:
    """The item's headline extraction score (``score.overall_extraction_score``), if numeric."""
    score = item.get("score") if isinstance(item.get("score"), dict) else {}
    value = _num(score.get("overall_extraction_score"))
    return value if value is not None and 0.0 <= value <= 1.0 else None


def _expected_fields(row: dict) -> dict:
    """A dataset row's ``expected_fields`` as a dict (it may be a JSON string); {} if absent."""
    exp = row.get("expected_fields")
    if isinstance(exp, str):
        try:
            exp = json.loads(exp)
        except ValueError:
            return {}
    return exp if isinstance(exp, dict) else {}


def _overlay_fields(row: dict, key: str) -> list[str]:
    """Field names an overlay (``interim_labels`` / ``near_gold_labels``) filled on a row."""
    block = row.get(key)
    fields = block.get("fields") if isinstance(block, dict) else None
    return sorted(str(f) for f in fields) if isinstance(fields, (list, tuple)) else []


def _label_provenance(row: dict | None) -> dict:
    """Which label tier supplied each field of a row's ground truth.

    ``tier`` is the lowest-precedence tier present (``near_gold`` beats ``interim`` beats
    ``hub``), so any score that leaned on a near-gold label is shown as such; ``none``
    means the row has a class label but no field labels, and None means no dataset row.
    """
    if row is None:
        return {"tier": None, "hub": 0, "interim": [], "near_gold": []}
    interim, near = _overlay_fields(row, "interim_labels"), _overlay_fields(row, "near_gold_labels")
    filled = set(interim) | set(near)
    hub = [k for k in _expected_fields(row) if k != "gt_presence" and k not in filled]
    base_tier = "fixture" if str(row.get("dataset") or "") in FIXTURE_DATASETS else "hub"
    tier = "near_gold" if near else "interim" if interim else base_tier if hub else "none"
    return {"tier": tier, "hub": len(hub), "interim": interim, "near_gold": near}


def _mean(values: list[float]) -> float | None:
    """Mean rounded to 4 places, or None for no values."""
    return round(sum(values) / len(values), 4) if values else None


def _scores(docs: list[dict]) -> dict:
    """Run scores against ground truth from the per-document rows.

    Classification counts documents with a GT class that reached a terminal outcome; one
    with no predicted class is a miss recorded as ``unknown`` (precision/recall per class, a
    confusion matrix ``gt -> pred -> n``). Extraction
    means use documents with a numeric ``overall_extraction_score``, split by the label
    tier the GT came from, so near-gold-backed numbers are never read as Hub-GT ones.
    """
    labelled = [{**d, "pred": d["pred"] or UNKNOWN_CLASS} for d in docs if _classifiable(d)]
    confusion: dict[str, Counter] = {}
    for d in labelled:
        confusion.setdefault(d["gt"], Counter())[d["pred"]] += 1
    classes = sorted({d["gt"] for d in docs if d["gt"]}
                     | {d["pred"] for d in labelled if d["pred"] != UNKNOWN_CLASS})
    per_class: dict[str, dict] = {}
    for c in classes:
        gt_n = sum(1 for d in labelled if d["gt"] == c)
        pred_n = sum(1 for d in labelled if d["pred"] == c)
        tp = sum(1 for d in labelled if d["gt"] == c and d["pred"] == c)
        mine = [d for d in docs if d["gt"] == c]
        ext = [d["score"] for d in mine if d["score"] is not None]
        outcome = Counter(d["outcome"] for d in mine)
        per_class[c] = {
            "n": len(mine), "gt_n": gt_n, "pred_n": pred_n, "correct": tp,
            "precision": round(tp / pred_n, 4) if pred_n else None,
            "recall": round(tp / gt_n, 4) if gt_n else None,
            "extraction_mean": _mean(ext), "extraction_n": len(ext),
            "near_gold_docs": sum(1 for d in mine if d["labels"]["tier"] == "near_gold"),
            "outcomes": {k: outcome.get(k, 0) for k in ("ship", "held", "failed", "open")},
        }
    by_tier: dict[str, dict] = {}
    for d in docs:
        tier = d["labels"]["tier"]
        if tier is None:
            continue
        t = by_tier.setdefault(tier, {"docs": 0, "scored": 0, "_ext": []})
        t["docs"] += 1
        if d["score"] is not None:
            t["scored"] += 1
            t["_ext"].append(d["score"])
    for t in by_tier.values():
        t["extraction_mean"] = _mean(t.pop("_ext"))
    correct = sum(1 for d in labelled if d["gt"] == d["pred"])
    ext_all = [d["score"] for d in docs if d["score"] is not None]
    hub_only = [d["score"] for d in docs if d["score"] is not None and d["labels"]["tier"] == "hub"]
    return {
        "classification": {"n": len(labelled), "correct": correct,
                           "accuracy": round(correct / len(labelled), 4) if labelled else None},
        "extraction": {"n": len(ext_all), "mean": _mean(ext_all),
                       "hub_n": len(hub_only), "hub_mean": _mean(hub_only)},
        "per_class": per_class,
        "confusion": {g: dict(sorted(c.items())) for g, c in sorted(confusion.items())},
        "label_tiers": {k: by_tier[k] for k in (*LABEL_TIERS, "none") if k in by_tier},
        "near_gold_fields": sum(len(d["labels"]["near_gold"]) for d in docs),
        "interim_fields": sum(len(d["labels"]["interim"]) for d in docs),
    }


def _classifiable(d: dict) -> bool:
    """True when a document counts for classification: a GT class and a terminal outcome,
    or a predicted class even while open."""
    return bool(d["gt"]) and (d["pred"] is not None or d["outcome"] != "open")


def _node_outcomes(docs: list[dict]) -> dict[str, dict]:
    """Per node: where the documents that visited it ended up, and how many were classed right."""
    out: dict[str, dict] = {}
    for d in docs:
        for node in dict.fromkeys(d["path"]):
            o = out.setdefault(node, {"ship": 0, "held": 0, "failed": 0, "open": 0, "n": 0,
                                      "class_n": 0, "class_ok": 0})
            o[d["outcome"]] += 1
            o["n"] += 1
            if _classifiable(d):
                o["class_n"] += 1
                o["class_ok"] += int(d["gt"] == d["pred"])
    return dict(sorted(out.items()))


def _last_activity(path: Path) -> float | None:
    """Latest mtime (epoch s) of the run's progress artifacts, or None if none can be read."""
    times = []
    for name in ("items.jsonl", "nodes.jsonl", "checkpoint.json"):
        try:
            times.append((path / name).stat().st_mtime)
        except OSError:
            continue
    return max(times) if times else None


def _stall_after() -> float:
    """``$FLOOR_STALL_SECONDS`` when it is a positive finite number, else the default."""
    try:
        v = float(os.environ.get("FLOOR_STALL_SECONDS") or "")
    except ValueError:
        return STALL_AFTER_S
    return v if math.isfinite(v) and v > 0 else STALL_AFTER_S


def _error_text(item: dict) -> str | None:
    """A short error / escalation note for the document table, or None."""
    for holder in (item, item.get("pred")):
        if not isinstance(holder, dict):
            continue
        for key in ("error", "error_message", "escalation_reason"):
            v = holder.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:200]
    return None


def build_run(name: str, path: Path, edge_set: set[tuple[str, str]]) -> tuple[dict, set[str]]:
    """Summarize a run's artifacts and return the summary and observed classes.

    The last item record for an ID wins. Node counts are distinct documents;
    edge counts are traversals limited to edge_set. Per-class traffic requires
    dataset class labels, and node duration medians are in milliseconds. The summary
    also includes in-flight documents, mean item latency and routing counts. Missing
    or invalid artifact data uses the reader fallbacks; errors reading dataset
    bytes for an absent hash propagate.
    """
    items_raw = read_jsonl(path / "items.jsonl")
    nodes = [r for r in read_jsonl(path / "nodes.jsonl") if r.get("node") and r.get("doc") is not None]
    checkpoint = read_json(path / "checkpoint.json")
    lock = read_json(path / "spec.lock.json")
    prompt_lock = read_json(path / "prompt.lock.json")
    ds_path = path / "dataset.jsonl"
    ds_present = ds_path.is_file()
    ds_rows = read_jsonl(ds_path) if ds_present else []

    # last record per item wins (a resumed run may re-append)
    items_by_id: dict[str, dict] = {}
    for i, it in enumerate(items_raw):
        items_by_id[str(it.get("item_id", it.get("id", f"#{i}")))] = it
    items = list(items_by_id.items())

    ds_class: dict[str, str] = {}
    ds_by_id: dict[str, dict] = {}
    for row in ds_rows:
        key = row.get("id") or row.get("filename")
        if key is not None:
            ds_by_id[str(key)] = row  # last row wins, like ds_class below
        if key is not None and row.get("expected_doc_class"):
            ds_class[str(key)] = str(row["expected_doc_class"])

    # nodes.jsonl: per-doc ordered visits
    per_doc_records: dict[str, list[dict]] = {}
    for r in nodes:
        per_doc_records.setdefault(str(r["doc"]), []).append(r)

    def visit_seq(records: list[dict]) -> list[str]:
        """Use running records as visits, or all records when none are running."""
        started = [r["node"] for r in records if r.get("status") == "running"]
        return started if started else [r["node"] for r in records]

    node_docs: dict[str, set[str]] = {}
    ms_by_node: dict[str, list[float]] = {}
    agents_by_node: dict[str, Counter] = {}
    for doc, recs in per_doc_records.items():
        for r in recs:
            node_docs.setdefault(r["node"], set()).add(doc)
            ms = _num(r.get("ms", r.get("duration_ms")))
            if ms is not None:
                ms_by_node.setdefault(r["node"], []).append(ms)
            if r.get("agent"):
                agents_by_node.setdefault(r["node"], Counter())[str(r["agent"])] += 1

    def doc_edges(doc: str) -> Counter:
        """Count consecutive allowed transitions for one document, excluding self-loops."""
        seq = visit_seq(per_doc_records.get(doc, []))
        return Counter(f"{a}>{b}" for a, b in pairwise(seq) if a != b and (a, b) in edge_set)

    edge_fires: Counter = Counter()
    for doc in per_doc_records:
        edge_fires.update(doc_edges(doc))

    def last_stage_from_nodes(doc: str):
        """The last stage any node recorded for a doc, or None."""
        for r in reversed(per_doc_records.get(doc, [])):
            if r.get("stage"):
                return r["stage"]
        return None

    outcomes: dict[str, dict] = {}
    class_outcomes: dict[str, dict] = {}
    aborts: Counter = Counter()
    ok_count = 0
    item_class: dict[str, str] = {}
    doc_rows: list[dict] = []
    for item_id, it in items:
        ok = it.get("ok")
        if ok:
            ok_count += 1
        stage = _item_stage(it) or last_stage_from_nodes(item_id)
        bucket = _stage_bucket(stage, ok if isinstance(ok, bool) else None)
        cls = ds_class.get(item_id) or str(it.get("expected_doc_class") or it.get("expected") or "") or "?"
        item_class[item_id] = cls
        recs = per_doc_records.get(item_id) or []
        seq = visit_seq(recs)
        doc_rows.append({
            "id": item_id,
            "gt": None if cls == "?" else cls,
            "pred": _pred_class(it),
            "outcome": bucket,
            "stage": str(stage) if stage else None,
            "path": [n for i, n in enumerate(seq) if i == 0 or seq[i - 1] != n],  # self-loops collapsed
            "ms": _num(it.get("latency_ms")),
            "score": _score_value(it),
            "labels": _label_provenance(ds_by_id.get(item_id)),
            "review": _review_trigger(it, recs),
            "note": _error_text(it),
        })
        for table, key in ((outcomes, cls), (class_outcomes, ds_class.get(item_id))):
            if key is None:
                continue
            o = table.setdefault(key, _empty_outcome())
            o[bucket] += 1
            o["n"] += 1
        if bucket == "failed":
            recs = per_doc_records.get(item_id)
            aborts[recs[-1]["node"] if recs else "unknown"] += 1

    # documents Routed to human review stay alive, never "failed": count them per
    # triggering stage (causes then node-visit attribution; unknown is still routed)
    routed: Counter = Counter()
    for item_id, it in items:
        trigger = _review_trigger(it, per_doc_records.get(item_id) or [])
        if trigger is not None:
            routed[trigger] += 1

    per_class: dict[str, dict] = {}
    if ds_present and ds_class:
        classes_seen = set(class_outcomes)
        for doc in per_doc_records:
            if doc in ds_class:
                classes_seen.add(ds_class[doc])
        for cls in sorted(classes_seen):
            docs = [d for d in per_doc_records if ds_class.get(d) == cls]
            pc_nodes: Counter = Counter()
            pc_edges: Counter = Counter()
            for d in docs:
                pc_nodes.update({r["node"] for r in per_doc_records[d]})
                pc_edges.update(doc_edges(d))
            per_class[cls] = {
                "nodes": dict(pc_nodes),
                "edges": dict(pc_edges),
                "outcomes": class_outcomes.get(cls, _empty_outcome()),
            }

    engine = lock.get("engine") if isinstance(lock.get("engine"), dict) else {}
    replay_meta = lock.get("replay") if isinstance(lock.get("replay"), dict) else {}
    prompt_default = prompt_lock.get("default") if isinstance(prompt_lock.get("default"), dict) else {}
    prompt_agents = prompt_lock.get("agents") if isinstance(prompt_lock.get("agents"), dict) else {}
    dataset_lock = lock.get("dataset") if isinstance(lock.get("dataset"), dict) else {}
    dataset_hash = dataset_lock.get("sha256")
    if not dataset_hash and ds_present:
        dataset_hash = hashlib.sha256(ds_path.read_bytes()).hexdigest()

    total = None
    if ds_present:
        cp_total = checkpoint.get("total")
        # a non-positive checkpoint total is not a dataset size (seen as 0 beside a full dataset): count rows
        cp_ok = isinstance(cp_total, int) and not isinstance(cp_total, bool) and cp_total > 0
        total = cp_total if cp_ok else len(ds_rows)

    cursor = checkpoint.get("cursor")
    routing = _routing(items, ds_class)
    state = checkpoint.get("state") or "unknown"
    last_activity = _last_activity(path)
    stalled_s = None
    if state == "running" and last_activity is not None:
        idle = datetime.now(UTC).timestamp() - last_activity
        if idle > _stall_after():
            state, stalled_s = "stalled", round(idle)
    run = {
        "name": name,
        "state": state,
        "checkpoint_state": checkpoint.get("state") or "unknown",
        "stalled_s": stalled_s,
        "last_activity_utc": (datetime.fromtimestamp(last_activity, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                              if last_activity is not None else None),
        "cursor": cursor if isinstance(cursor, int) and not isinstance(cursor, bool) else 0,
        "total": total,
        "items_attempted": len(items),
        "items_ok": ok_count,
        "engine": {"kind": engine.get("kind"), "model": engine.get("model")},
        "profile": lock.get("profile"),
        "replay": ({key: replay_meta.get(key) for key in
                    ("mode", "source_run_id", "engine_kind", "engine_model",
                     "synthetic_timing", "duration_s", "speed", "incomplete")}
                   if replay_meta else None),
        "spec_hash": lock.get("spec_hash") or checkpoint.get("spec_hash"),
        "dataset_hash": dataset_hash,
        "prompt_default": prompt_default.get("name") or prompt_default.get("source"),
        # post-hoc prompt identification: the label is the most discriminating
        # resolved identifier the lock kept — the eval-environment lineage key
        # for dojo prompts, the local file stem, then name/source fallbacks
        "prompts": dict(sorted(
            (str(agent), str(
                ref.get("key") or ref.get("file") or ref.get("name") or ref.get("source") or ""
            ))
            for agent, ref in prompt_agents.items() if isinstance(ref, dict)
        )),
        "review_routed": {"total": sum(routed.values()), "by_stage": dict(sorted(routed.items()))},
        "tokens": _tokens(nodes, [it for _, it in items]),
        "node_fires": {n: len(d) for n, d in sorted(node_docs.items())},
        "edge_fires": dict(sorted(edge_fires.items())),
        "node_agents": {n: dict(sorted(c.items())) for n, c in sorted(agents_by_node.items())},
        "node_ms_p50": {n: (_int_if_whole(statistics.median(ms_by_node[n])) if ms_by_node.get(n) else 0)
                        for n in sorted(node_docs)},
        "aborts_by_last_node": dict(sorted(aborts.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "per_class": per_class,
        "inflight": _inflight(nodes),
        "avg_doc_ms": _avg_doc_ms([it for _, it in items]),
        # per ground-truth class: items whose recorded doc_type differs from it (routing misses)
        "predicted": {c: v["gt"] - v["match"] for c, v in routing.items() if v["gt"]},
        "routing": routing,
        "scores": _scores(doc_rows),
        "node_outcomes": _node_outcomes(doc_rows),
        "docs": doc_rows[:DOC_ROW_CAP],
        "docs_truncated": max(0, len(doc_rows) - DOC_ROW_CAP),
    }
    classes = {c for c in outcomes if c != "?"} | set(ds_class.values())
    return run, classes


# ── build / output ──────────────────────────────────────────────────────────────


def resolve_base(arg: str | None) -> Path:
    """Choose a data directory from arg, MAILROOM_BASE_DIR, or ./data, in order."""
    return Path(arg or os.environ.get("MAILROOM_BASE_DIR") or "./data")


def build_digest(base: Path, graph_path: Path) -> dict:
    """Build a timestamped digest of discovered runs and their graph.

    Raises DigestError for graph read or syntax errors, an unusable topology,
    or no runs found. Decoding, directory traversal, and aggregation errors can
    also propagate.
    """
    graph = parse_graph(graph_path)
    runs_found = discover_runs(base)
    if not runs_found:
        raise DigestError(
            f"no runs found under {base}/runtime/runs/* or {base}/run-history/* "
            "(a run is any directory containing items.jsonl)",
            EXIT_NO_RUNS,
        )
    edge_set = {(a, b) for a, b in graph["edges"]}
    runs: list[dict] = []
    classes: set[str] = set()
    used: set[str] = set()
    for source, path in runs_found:
        name = path.name if path.name not in used else f"{path.name} ({source})"
        used.add(name)
        run, run_classes = build_run(name, path, edge_set)
        runs.append(run)
        classes |= run_classes
    return {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "classes": sorted(classes),
        "graph_reference": graph,
        "runs": runs,
    }


def write_outputs(digest: dict, out: Path) -> tuple[Path, Path]:
    """Write JSON and a window.DIGEST JavaScript twin, returning both paths.

    Each destination is replaced separately, so a write failure may leave one
    updated. Filesystem errors become DigestError; serialization errors propagate.
    """
    payload = json.dumps(digest, ensure_ascii=False, indent=1)
    json_path, js_path = out / "floor_digest.json", out / "floor_digest.js"
    try:
        out.mkdir(parents=True, exist_ok=True)
        for path, text in ((json_path, payload), (js_path, f"window.DIGEST={payload};\n")):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(text.encode("utf-8"))  # bytes: no platform newline translation
            os.replace(tmp, path)
    except OSError as exc:
        raise DigestError(f"failed to write digest to {out}: {exc}", EXIT_WRITE) from exc
    return json_path, js_path


def build(base: Path, out: Path, graph_path: Path | None = None) -> tuple[dict, Path, Path]:
    """Build the digest from ``base`` and write floor_digest.json/.js into ``out``.

    The programmatic twin of ``main`` (used by ``sandbox floor``): ``graph_path`` defaults
    to ``$FLOOR_DIGEST_GRAPH`` then the vendored build_graph.py. Returns
    ``(digest, json_path, js_path)``. Graph read, syntax or topology errors, no runs,
    and output filesystem errors raise DigestError; decoding, traversal, aggregation
    and serialization errors may also propagate. The two output files are replaced separately.
    """
    graph = Path(graph_path or os.environ.get("FLOOR_DIGEST_GRAPH") or DEFAULT_GRAPH)
    digest = build_digest(Path(base), graph)
    json_path, js_path = write_outputs(digest, Path(out))
    return digest, json_path, js_path


def summary_lines(digest: dict) -> list[str]:
    """Return one line per run with its three most frequently fired nodes."""
    lines = []
    for r in digest["runs"]:
        top = sorted(r["node_fires"].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        lines.append(
            f"{r['name']}  state={r['state']}  attempted={r['items_attempted']}  ok={r['items_ok']}  "
            f"top3={', '.join(f'{n}={c}' for n, c in top) or '-'}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Build and write the digest, optionally printing per-run summaries.

    DigestError is printed to stderr and its code returned; other errors
    propagate. Argument parsing may exit via SystemExit.
    """
    ap = argparse.ArgumentParser(description="Build floor_digest.json/.js from on-disk run artifacts.")
    ap.add_argument("--base", help="data base dir (default: $MAILROOM_BASE_DIR or ./data)")
    ap.add_argument("--out", help="output dir (default: this script's directory)")
    ap.add_argument("--print-summary", action="store_true", help="print one line per run")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else HERE
    try:
        digest, json_path, js_path = build(resolve_base(args.base), out)
    except DigestError as exc:
        print(f"build_floor_digest: error: {exc}", file=sys.stderr)
        return exc.code
    if args.print_summary:
        print("\n".join(summary_lines(digest)))
    print(f"wrote {json_path} and {js_path} ({len(digest['runs'])} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
