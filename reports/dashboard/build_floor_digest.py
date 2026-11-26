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
    plain_edges: list[tuple[str, str]] = []
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
            if a and b and a != b and (a, b) not in plain_edges:
                plain_edges.append((a, b))

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
        "plain_edges": [list(e) for e in plain_edges],
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


# ── read ranges (numbers only; the text is served by the loopback endpoint) ─────


def _int_pair(value) -> list[int] | None:
    """A ``[start, end)`` pair of non-negative ints with start < end, else None."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    a, b = value
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (a, b)):
        return None
    return [a, b] if 0 <= a < b else None


def _clean_ranges(raw) -> list[list[int]]:
    """Valid range pairs only; anything else is dropped."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [pair for pair in (_int_pair(v) for v in raw) if pair is not None]


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Sort and merge overlapping or touching ``[start, end)`` pairs."""
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _last_call_sequence(records: list[dict]) -> list[dict]:
    """The last call sequence of one document's read records.

    Call numbers are assigned per document attempt, starting at 1. A resumed document re-appends
    ``call=1..n``, so a record with ``call == 1`` starts a new sequence that supersedes the earlier
    one. Any other record extends the current sequence, even when concurrent calls wrote their
    records out of order (call 3 before call 2). Records without an integer call extend it too.
    """
    sequence: list[dict] = []
    for rec in records:
        call = rec.get("call")
        if call == 1 and isinstance(call, int) and not isinstance(call, bool):
            sequence = []
        sequence.append(rec)
    return sequence


def _doc_reads(records: list[dict]) -> dict:
    """``debug.reads`` for one document: calls, per-agent merged ranges, working-text length. No text.

    ``doc_chars`` is the working text's length: the value on the last working-basis call of the
    kept sequence, or None when no such call recorded one. A raw-basis call measured the raw row
    text, which intake may have shortened, so its length never stands for the working text.
    """
    kept = _last_call_sequence(records)
    calls: list[dict] = []
    by_agent: dict[str, list[list[int]]] = {}
    doc_chars: int | None = None
    for rec in kept:
        agent = str(rec.get("agent") or "?")
        ranges = _clean_ranges(rec.get("ranges"))
        call = {
            "agent": agent,
            "node": rec.get("node") if isinstance(rec.get("node"), str) else None,
            "basis": rec.get("basis") if rec.get("basis") in ("working", "raw") else None,
            "ranges": ranges,
            "matched": int(_num(rec.get("matched_chars")) or 0),
            "request": int(_num(rec.get("request_chars")) or 0),
        }
        if isinstance(rec.get("skipped"), str) and rec["skipped"]:
            call["skipped"] = rec["skipped"]
        calls.append(call)
        by_agent.setdefault(agent, []).extend(ranges)
        if call["basis"] == "working" and (_num(rec.get("doc_chars")) or 0) > 0:
            doc_chars = int(_num(rec["doc_chars"]))
    return {
        "calls": calls,
        "union": {agent: _merge_ranges(rs) for agent, rs in by_agent.items()},
        "doc_chars": doc_chars,
    }


def read_ranges_by_doc(path: Path) -> dict[str, dict] | None:
    """``debug.reads`` per document id from a run's ``reads.jsonl``; None when the run has none.

    Torn or malformed lines are skipped (``read_jsonl``). Only offsets and counts are read
    out of each record, never any document text.
    """
    reads_path = path / "reads.jsonl"
    if not reads_path.is_file():
        return None
    per_doc: dict[str, list[dict]] = {}
    for rec in read_jsonl(reads_path):
        if rec.get("doc") is not None:
            per_doc.setdefault(str(rec["doc"]), []).append(rec)
    return {doc: _doc_reads(recs) for doc, recs in per_doc.items()}


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

# A document table is kept per run for the viewer's Documents tab. Past DOC_ROW_CAP,
# problem rows (held, failed, open, class miss, diverted, stuck) stay ahead of healthy
# archived rows. ``docs_truncated`` is every row left out. ``docs_omitted_healthy`` is
# how many of those left-out rows were not problems.
DOC_ROW_CAP = 5000
_PROBLEM_ISSUES = frozenset({"stuck", "held", "failed", "open", "miss", "diverted"})
_FIELD_NOTE_CAP = 8
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


def _stored_extraction(item: dict) -> dict:
    """The item's stored ``extracted_data`` map, or empty when none was recorded."""
    for holder in (item.get("pred"), item.get("prediction"), item):
        if isinstance(holder, dict) and isinstance(holder.get("extracted_data"), dict):
            return holder["extracted_data"]
    return {}


def _field_text(value) -> str:
    """Normalized scalar text for comparison. Nested values are skipped."""
    if value is None or isinstance(value, (dict, list, tuple)):
        return ""
    return " ".join(str(value).split()).lower()


def _show_field(text: str) -> str:
    """Quote clip. Equality uses the full normalized text, so a later difference still counts."""
    return text if len(text) <= 40 else text[:39] + "…"


def _score_notes(stored: dict) -> list[dict]:
    """Fields whose stored Dojo ``field_scores`` entry is below 1. A stored 0 stays 0."""
    notes = []
    for key, value in stored.items():
        number = _num(value)
        if number is None or number >= 1:
            continue
        notes.append({"field": str(key)[:40], "kind": "stored_score", "score": round(number, 4)})
        if len(notes) >= _FIELD_NOTE_CAP:
            break
    return notes


def _value_notes(expected: dict, predicted: dict) -> list[dict]:
    """Stored values that differ from the dataset row. Not a score."""
    notes = []
    for key, truth in expected.items():
        if key == "gt_presence":
            continue
        exp = _field_text(truth)
        if not exp:
            continue
        got = _field_text(predicted.get(key)) if key in predicted else ""
        if got == "":
            notes.append({"field": str(key)[:40], "kind": "missing", "expected": _show_field(exp)})
        elif got != exp:
            notes.append({
                "field": str(key)[:40], "kind": "value",
                "expected": _show_field(exp), "recorded": _show_field(got),
            })
        if len(notes) >= _FIELD_NOTE_CAP:
            break
    return notes


def _field_notes(item: dict, row: dict | None) -> list[dict]:
    """Disagreements to show beside the extraction score.

    A stored ``field_scores`` map is quoted as the Dojo already recorded it.
    Otherwise stored ``extracted_data`` is set beside the dataset row. Neither
    path computes a new score.
    """
    score = item.get("score") if isinstance(item.get("score"), dict) else {}
    stored = score.get("field_scores")
    if isinstance(stored, dict) and stored:
        return _score_notes(stored)
    expected = _expected_fields(row or {})
    predicted = _stored_extraction(item)
    if not expected or not predicted:
        return []
    return _value_notes(expected, predicted)


def _is_problem_row(row: dict) -> bool:
    """True when the row's debug tags include a problem, not a recovered loop alone."""
    issues = (row.get("debug") or {}).get("issues") or []
    return any(issue in _PROBLEM_ISSUES for issue in issues)


def _select_doc_rows(rows: list[dict], cap: int = DOC_ROW_CAP) -> tuple[list[dict], int, int]:
    """Keep problem rows ahead of healthy ones once the table passes ``cap``.

    Returns ``(kept, omitted, omitted_healthy)``. Scores are computed before this
    cut, so a dropped row still counts in the score tables.
    """
    if len(rows) <= cap:
        return rows, 0, 0
    problems = [row for row in rows if _is_problem_row(row)]
    healthy = [row for row in rows if not _is_problem_row(row)]
    kept = (problems + healthy)[:cap]
    kept_ids = {id(row) for row in kept}
    omitted_healthy = sum(1 for row in healthy if id(row) not in kept_ids)
    return kept, len(rows) - len(kept), omitted_healthy


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


# A debug hop list stays short enough to ship inside a 5,000-row digest.
_DEBUG_HOP_CAP = 16
_DEBUG_WHY = 220


def _clip(text: str, limit: int = _DEBUG_WHY) -> str:
    """Collapse whitespace and cap a diagnosis sentence."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _review_causes(item: dict) -> list[str]:
    """Recorded review-cause tokens on the item, pred, or prediction, in first-seen order."""
    found: list[str] = []
    for holder in (item, item.get("pred"), item.get("prediction")):
        if not isinstance(holder, dict):
            continue
        causes = holder.get("review_causes")
        if not isinstance(causes, (list, tuple)):
            continue
        for cause in causes:
            text = str(cause).strip()[:60]
            if text and text not in found:
                found.append(text)
            if len(found) >= 8:
                return found
    return found


def _decision_bits(decisions: list) -> str:
    """One short phrase per recorded decision (question, answer, probability, expected)."""
    parts: list[str] = []
    for raw in decisions[:3]:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "?")[:40]
        answer = raw.get("answer")
        bit = question if answer is None or answer == "" else f"{question}={answer}"
        p = _num(raw.get("p"))
        if p is not None:
            bit += f" p={round(p, 2)}"
        expected = _num(raw.get("expected"))
        if expected is not None:
            bit += f" expected={round(expected, 2)}"
        parts.append(bit[:90])
    return "; ".join(parts)


def _visit_numbers(record: dict) -> tuple[float | None, float | None, float | None]:
    """Stored elapsed milliseconds and token counts on one node record. Missing stays None."""
    nested = record.get("tokens") if isinstance(record.get("tokens"), dict) else record.get("usage")
    nested = nested if isinstance(nested, dict) else {}
    prompt = _num(record.get("prompt_tokens", nested.get("prompt", nested.get("prompt_tokens"))))
    completion = _num(record.get(
        "completion_tokens", nested.get("completion", nested.get("completion_tokens")),
    ))
    return _num(record.get("ms", record.get("duration_ms"))), prompt, completion


def _kept_decisions(record: dict) -> list:
    """The decision fields a diagnosis is allowed to quote."""
    raw = record.get("decisions")
    if not isinstance(raw, list):
        return []
    kept = []
    for item in raw[:4]:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        kept.append({key: item.get(key) for key in ("question", "answer", "p", "expected")
                     if item.get(key) is not None or key == "question"})
    return kept


def _closed_visits(records: list[dict]) -> list[dict]:
    """One visit per node entry, closed by the matching done, error, or paused record.

    A ``running`` row opens a visit. A second ``running`` row for that same node
    while it is still open is the same visit, not a loop. The next non-running
    row for that node closes it and supplies decisions, stage, and error. A
    trace with no ``running`` rows treats every row as its own visit. Unclosed
    visits stay ``running``.
    """
    visits: list[dict] = []
    pending: dict | None = None

    def pack(record: dict, status: str) -> dict:
        stage = record.get("stage")
        error = record.get("error")
        packed = {
            "node": str(record.get("node")),
            "status": status,
            "stage": stage if isinstance(stage, str) and stage else None,
            "error": error.strip()[:120] if isinstance(error, str) and error.strip() else None,
            "decisions": _kept_decisions(record),
        }
        ms, prompt, completion = _visit_numbers(record)
        if ms is not None:
            packed["ms"] = _int_if_whole(ms)
        if prompt is not None:
            packed["prompt"] = int(prompt)
        if completion is not None:
            packed["completion"] = int(completion)
        return packed

    for record in records:
        if not record.get("node"):
            continue
        status = str(record.get("status") or "done")
        if status == "running":
            # A second start for the node already in flight is the same visit.
            if pending is not None and pending["node"] == str(record.get("node")):
                continue
            if pending is not None:
                visits.append(pending)
            pending = pack(record, "running")
            continue
        if pending is not None and pending["node"] == str(record.get("node")):
            visits.append(pack(record, status))
            pending = None
        else:
            if pending is not None:
                visits.append(pending)
                pending = None
            visits.append(pack(record, status))
    if pending is not None:
        visits.append(pending)
    return visits[:80]


def _loop_rows(visits: list[dict]) -> list[dict]:
    """Nodes entered more than once, tagged self (consecutive) or reentry (left and returned)."""
    counts = Counter(visit["node"] for visit in visits)
    loops = []
    for node, count in counts.items():
        if count < 2:
            continue
        indexes = [i for i, visit in enumerate(visits) if visit["node"] == node]
        reentry = any(indexes[i + 1] - indexes[i] > 1 for i in range(len(indexes) - 1))
        kind = "reentry" if reentry else "self"
        mine = [visit for visit in visits if visit["node"] == node]
        evidence = []
        for visit in mine:
            phrase = _decision_bits(visit["decisions"])
            if phrase:
                evidence.append(phrase)
            if visit.get("stage"):
                evidence.append(f"stage {visit['stage']}")
            if visit["error"] or visit["status"] in ("error", "paused"):
                evidence.append(visit["status"] + (f" {visit['error']}" if visit["error"] else ""))
        recorded = "; ".join(dict.fromkeys(evidence))
        if kind == "self":
            why = f"{node} ran {count} times without a different node between those visits."
        else:
            why = f"{node} was left and entered again ({count} visits)."
        if recorded:
            why += " Recorded on those visits: " + recorded + "."
        else:
            why += " No decision, stage, or error was stored on the repeated visits."
        row = {"node": node, "visits": count, "kind": kind, "why": _clip(why)}
        cost = _loop_cost(mine)
        if cost:
            row["cost"] = cost
        loops.append(row)
        if len(loops) >= 8:
            break
    return loops


def _hop_why(source: dict, dest: str, causes: list[str], plain: set[tuple[str, str]]) -> str:
    """Why the trace left ``source`` for ``dest``, citing only stored fields and plain edges."""
    phrase = _decision_bits(source["decisions"])
    named = next((d for d in source["decisions"]
                  if isinstance(d.get("answer"), str) and d.get("answer") == dest), None)
    if named:
        return _clip(f"Recorded {named.get('question')}={dest} at {source['node']}; the next visit is {dest}.")
    if dest == "human_review" and causes:
        extra = (f" Last decision at {source['node']}: {phrase}." if phrase
                 else f" No decision was recorded at {source['node']}.")
        return _clip(f"Item review causes {', '.join(causes)}; left {source['node']} for human_review.{extra}")
    if source["status"] == "error":
        err = f" ({source['error']})" if source["error"] else ""
        return _clip(f"{source['node']} ended status=error{err}; the next recorded visit is {dest}.")
    if source["status"] == "paused" and dest == "human_review":
        return _clip(f"{source['node']} paused; the next visit is human_review.")
    if (source["node"], dest) in plain:
        return _clip(f"Unconditional edge {source['node']} → {dest}; this hop stores no route decision.")
    stage = f" Stage at {source['node']}: {source['stage']}." if source["stage"] else ""
    if phrase:
        return _clip(f"Left {source['node']} for {dest}. Last decision at {source['node']}: {phrase}.{stage}")
    return _clip(
        f"Left {source['node']} for {dest}. No decision was recorded at {source['node']}.{stage}"
    )


def _mode_token(value: str) -> str:
    """A stable mode id fragment: letters, digits, and ``+ > - _`` only."""
    token = re.sub(r"[^A-Za-z0-9_+>-]+", "", str(value).replace(" ", ""))
    return (token or "unknown")[:48]


def _error_slug(note: str | None) -> str:
    """The leading exception or error token, so identical failures share a mode."""
    if not note:
        return "no-error"
    head = note.split(":", 1)[0].strip()
    word = head.split()[-1] if head else ""
    return _mode_token(word)


# Appended to every lever. The recorded run is not rewritten.
_PAST_RUN_UNCHANGED = " The past run is left unchanged."


def _loop_cost(visits: list[dict]) -> dict:
    """Sum of stored visit times and tokens. A number is included only when a visit stored it."""
    totals: dict[str, float] = {}
    for visit in visits:
        for key in ("ms", "prompt", "completion"):
            number = _num(visit.get(key))
            if number is None:
                continue
            totals[key] = totals.get(key, 0.0) + number
    cost = {}
    if "ms" in totals:
        cost["ms"] = _int_if_whole(totals["ms"])
    for key in ("prompt", "completion"):
        if key in totals:
            cost[key] = int(totals[key])
    return cost


def _answer_bits(visits: list[dict]) -> list[str]:
    """Stored decision phrases a viewer can search. Capped, and not a new inference."""
    bits: list[str] = []
    for visit in visits:
        phrase = _decision_bits(visit.get("decisions") or [])
        if phrase and phrase not in bits:
            bits.append(phrase)
        if len(bits) >= 12:
            break
    return bits


def _pack_mode(mode_id: str, label: str, lever: str, node: str) -> dict:
    """A mode id, a short label, the node to inspect, and a next-run lever."""
    return {
        "id": mode_id,
        "label": _clip(label, 180),
        "node": node,
        "lever": _clip(lever, 360),
    }


def _class_disagreement(gt: str | None, pred: str | None) -> bool:
    """True when both classes were stored and they differ."""
    return bool(gt and pred and gt != pred)


def _class_miss(gt: str | None, pred: str | None, outcome: str) -> bool:
    """The scores-panel miss: both classes disagree, or a finished document recorded none.

    An open document with no predicted class is still undecided, so it is not a miss.
    """
    if not gt:
        return False
    if pred:
        return pred != gt
    return outcome != "open"


def _class_note(gt: str | None, pred: str | None, outcome: str) -> str:
    """A label suffix for a class miss, or empty."""
    if _class_disagreement(gt, pred):
        return f" · class {gt} recorded as {pred}"
    if gt and not pred and outcome != "open":
        return f" · class {gt} with no recorded class"
    return ""


def _stop_node(stopped: str | None, last: dict | None) -> str:
    """The node a trace stopped on, else the last visit, else ``unknown``."""
    if stopped:
        return stopped
    if last:
        return last["node"]
    return "unknown"


def _loop_at(loops: list[dict], node: str) -> dict | None:
    """The repeat on ``node``, else the first repeat, else None."""
    for row in loops:
        if row["node"] == node:
            return row
    if loops:
        return loops[0]
    return None


def _stuck_mode(loop: dict | None, miss_bit: str) -> dict | None:
    """The still-open repeat, or None when this document has no repeat row."""
    if not loop:
        return None
    return _pack_mode(
        f"stuck:{_mode_token(loop['node'])}:{loop['kind']}",
        f"{loop['node']} repeated ({loop['kind']}) and is still open{miss_bit}",
        f"Next run: {loop['node']} is still repeating. Use the decisions stored on those "
        f"visits. A missing decision was not recorded, so do not guess a cutoff from this view."
        + _PAST_RUN_UNCHANGED,
        loop["node"],
    )


def _failed_mode(node: str, note: str | None, miss_bit: str) -> dict:
    """A technical failure, grouped by the node and the error token."""
    slug = _error_slug(note)
    shown = _clip(note, 120) if note else "no error text"
    return _pack_mode(
        f"failed:{_mode_token(node)}:{slug}",
        f"Failed at {node} · {slug}{miss_bit}",
        f"Next run: this is a technical failure at {node}, not a route. "
        f"The recorded error ({shown}) is the defect. "
        f"Fix that failure before rerunning the same documents." + _PAST_RUN_UNCHANGED,
        node,
    )


def _cause_stages(causes: list[str]) -> list[str]:
    """Known review-cause stages, in first-seen order."""
    stages: list[str] = []
    for cause in causes:
        stage = CAUSE_TRIGGER_STAGE.get(cause)
        if stage and stage not in stages:
            stages.append(stage)
    return stages


def _held_lever(node: str, causes: list[str], review: str | None,
                gt: str | None, pred: str | None) -> str:
    """Where a later run should look for a document parked in review."""
    stages = _cause_stages(causes)
    if causes and stages:
        lever = (f"Next run: recorded cause {', '.join(causes)}. "
                 f"That points at the {' and '.join(stages)} stage, not at a later node. "
                 f"Read the stored decision there before changing that prompt or band.")
    elif causes:
        lever = (f"Next run: recorded cause {', '.join(causes)} is not in the known "
                 f"cause list. Leave it as recorded and inspect the hop into {node}.")
    else:
        lever = (f"Next run: no review cause was stored. The park is attributed to "
                 f"{review or 'no stage'}. Inspect the hop into {node} before changing a prompt.")
    if _class_disagreement(gt, pred):
        lever += f" Ground truth is {gt}; the run recorded {pred}."
    elif gt and not pred:
        lever += f" Ground truth is {gt}; the run recorded no class."
    return lever + _PAST_RUN_UNCHANGED


def _held_mode(node: str, causes: list[str], review: str | None,
               gt: str | None, pred: str | None, miss_bit: str) -> dict:
    """A review park, grouped by the stop node and the recorded causes."""
    if causes:
        key = "+".join(causes)
    else:
        key = review or "unattributed"
    return _pack_mode(
        f"held:{_mode_token(node)}:{_mode_token(key)}",
        f"Held at {node} · {key}{miss_bit}",
        _held_lever(node, causes, review, gt, pred),
        node,
    )


def _archived_miss_mode(gt: str, pred: str) -> dict:
    """A class miss that still recorded archive."""
    return _pack_mode(
        f"miss:archived:{_mode_token(gt)}>{_mode_token(pred)}",
        f"Archived under the wrong class · {gt} recorded as {pred}",
        f"Next run: the document reached archive with ground truth {gt} and recorded class {pred}. "
        f"The classify decision is the disagreement. Do not treat that archive as a correct route."
        + _PAST_RUN_UNCHANGED,
        "classify",
    )


def _open_mode(node: str, miss_bit: str) -> dict:
    """A trace that is still open and did not repeat its last node."""
    return _pack_mode(
        f"open:{_mode_token(node)}",
        f"Still open at {node}{miss_bit}",
        f"Next run: the trace is still open at {node}. Resume or read that visit before "
        f"changing a prompt. This is not a completed routing decision." + _PAST_RUN_UNCHANGED,
        node,
    )


def _diverted_mode(node: str, miss_bit: str) -> dict:
    """A trace that stopped without recording archive."""
    return _pack_mode(
        f"diverted:{_mode_token(node)}",
        f"Stopped at {node} without archive{miss_bit}",
        f"Next run: the trace stopped at {node} and never recorded archive. "
        f"Use the hop into that node. Do not invent a router input that was not stored."
        + _PAST_RUN_UNCHANGED,
        node,
    )


def _recovered_loop_mode(loop: dict | None) -> dict | None:
    """A repeat that later recorded archive, or None when there is no repeat."""
    if not loop:
        return None
    return _pack_mode(
        f"loop:{_mode_token(loop['node'])}:{loop['kind']}",
        f"{loop['node']} repeated ({loop['kind']}) and then reached archive",
        f"This repeat reached archive, so it is not an open failure. A later run that stops "
        f"on {loop['node']} the same way is the same mode." + _PAST_RUN_UNCHANGED,
        loop["node"],
    )


def _first_mode(modes: list[dict | None]) -> dict | None:
    """The first mode that applied, in the fixed ranking."""
    for mode in modes:
        if mode:
            return mode
    return None


def _early_modes(issues: list[str], loop: dict | None, miss_bit: str, node: str,
                 note: str | None, causes: list[str], review: str | None,
                 gt: str | None, pred: str | None) -> list[dict | None]:
    """Stuck, then a technical failure, then a review park."""
    modes: list[dict | None] = []
    if "stuck" in issues:
        modes.append(_stuck_mode(loop, miss_bit))
    if "failed" in issues:
        modes.append(_failed_mode(node, note, miss_bit))
    if "held" in issues:
        modes.append(_held_mode(node, causes, review, gt, pred, miss_bit))
    return modes


def _archived_if(reached: bool, outcome: str, gt: str | None, pred: str | None) -> dict | None:
    """A class miss that reached archive, else None. A missing class is ``unknown``."""
    if not reached or not _class_miss(gt, pred, outcome):
        return None
    return _archived_miss_mode(str(gt), str(pred or UNKNOWN_CLASS))


def _late_modes(issues: list[str], node: str, miss_bit: str, loop: dict | None) -> list[dict | None]:
    """An open trace, a missed archive, then a repeat that did reach archive."""
    modes: list[dict | None] = []
    if "open" in issues:
        modes.append(_open_mode(node, miss_bit))
    if "diverted" in issues:
        modes.append(_diverted_mode(node, miss_bit))
    modes.append(_recovered_loop_mode(loop))
    return modes


def _failure_mode(issues: list[str], loops: list[dict], last: dict | None, stopped: str | None,
                  reached: bool, outcome: str, causes: list[str], review: str | None,
                  note: str | None, pred: str | None, gt: str | None) -> dict | None:
    """One stable failure mode for a document, or None when nothing went wrong.

    The id groups documents that failed the same way. The lever names the stage
    a later run should inspect. It does not rewrite this run. Ranking is stuck,
    failed, held, an archived class miss, open, diverted, then a recovered loop.
    """
    if not issues:
        return None
    miss_bit = _class_note(gt, pred, outcome)
    node = _stop_node(stopped, last)
    loop = _loop_at(loops, node)
    modes = _early_modes(issues, loop, miss_bit, node, note, causes, review, gt, pred)
    modes.append(_archived_if(reached, outcome, gt, pred))
    modes.extend(_late_modes(issues, node, miss_bit, loop))
    return _first_mode(modes)


def _hop_list(visits: list[dict], causes: list[str],
              plain: set[tuple[str, str]]) -> tuple[list[dict], int]:
    """Collapsed hops, and how many were dropped past the digest cap."""
    collapsed = [0]
    for index in range(1, len(visits)):
        if visits[index]["node"] != visits[index - 1]["node"]:
            collapsed.append(index)
    hops = []
    for index in range(len(collapsed) - 1):
        source = visits[collapsed[index + 1] - 1]
        dest = visits[collapsed[index + 1]]["node"]
        hops.append({"from": source["node"], "to": dest, "why": _hop_why(source, dest, causes, plain)})
    omitted = 0
    if len(hops) > _DEBUG_HOP_CAP:
        omitted = len(hops) - _DEBUG_HOP_CAP
        # The gap is not a hop. Joining the two slices would invent a route.
        hops = hops[:8] + [{"gap": omitted}] + hops[-8:]
    return hops, omitted


def _repeat_clause(loops: list[dict]) -> str:
    """The 'earlier repeats' sentence, or empty when the trace did not repeat."""
    if not loops:
        return ""
    body = ", ".join(f"{row['node']} ×{row['visits']} ({row['kind']})" for row in loops)
    return " Earlier repeats: " + body + "."


def _why_untraced(outcome: str, stage: str | None, note: str | None) -> str:
    """Archive cannot be confirmed because no node visit was stored."""
    text = f"No node trace was recorded. Outcome is {outcome}"
    if stage:
        text += f", stage {stage}"
    if note:
        text += f". {note}"
    else:
        text += "."
    return text + " Archive cannot be confirmed from visits."


def _why_ship_gap(stage: str | None) -> str:
    """A shipped item whose trace never recorded the archive node."""
    shown = stage or "archived"
    return (f"Item stage is {shown} but the node trace never recorded archive. "
            "Paths rebuilt from stage audits omit nodes that write no audit entry, "
            "including catalog_write and archive.")


def _review_handoff(hops: list[dict]) -> str:
    """The recorded reason for the hop into human review, or empty."""
    for hop in hops:
        if hop["to"] == "human_review":
            return hop["why"]
    return ""


def _why_held(stopped: str | None, stage: str | None, review: str | None,
              causes: list[str], hops: list[dict], repeat: str) -> str:
    """Why a parked document never recorded archive."""
    text = f"Held at {stopped or 'unknown'}"
    if stage:
        text += f" (stage {stage})"
    trigger = review or "unattributed"
    if causes:
        cause_text = ", ".join(causes)
    else:
        cause_text = "none recorded"
    text += f". Review trigger: {trigger}. Causes: {cause_text}. Archive was not visited."
    handoff = _review_handoff(hops)
    if handoff:
        text += f" {handoff}"
    return text + repeat


def _why_failed(stopped: str | None, stage: str | None, note: str | None) -> str:
    """Why a technical failure stopped before archive."""
    text = f"Failed at {stopped or 'unknown'}"
    if stage:
        text += f" (stage {stage})"
    detail = note or "No error text recorded."
    return text + f". {detail} The trace stops before archive."


def _open_loop(last: dict | None, loops: list[dict]) -> dict | None:
    """The repeat on the last visit, when the trace is still there."""
    if not last:
        return None
    for row in loops:
        if row["node"] == last["node"]:
            return row
    return None


def _why_open(stopped: str | None, last: dict | None, loops: list[dict]) -> str:
    """Why an unfinished trace has not recorded archive."""
    status = last["status"] if last else "unknown"
    text = (f"Still open at {stopped or 'unknown'} (last visit status {status}). "
            "Archive has not been recorded.")
    looping = _open_loop(last, loops)
    if looping:
        text += f" {looping['why']}"
    return text


def _archive_why(visits: list[dict], outcome: str, stage: str | None, review: str | None,
                 note: str | None, causes: list[str], hops: list[dict], loops: list[dict],
                 last: dict | None, stopped: str | None, reached: bool) -> str:
    """One sentence for whether archive was recorded."""
    repeat = _repeat_clause(loops)
    if not visits:
        return _why_untraced(outcome, stage, note)
    if reached:
        return "Reached archive." + repeat
    if outcome == "ship":
        return _why_ship_gap(stage)
    if outcome == "held":
        return _why_held(stopped, stage, review, causes, hops, repeat)
    if outcome == "failed":
        return _why_failed(stopped, stage, note)
    if outcome == "open":
        return _why_open(stopped, last, loops)
    return (f"Stopped at {stopped or 'unknown'} with outcome {outcome}. "
            f"Archive was not visited.{repeat}")


def _stuck_open(outcome: str, last: dict | None, loops: list[dict]) -> bool:
    """An open document whose last visit is also a repeat."""
    if outcome != "open" or not last:
        return False
    return _open_loop(last, loops) is not None


def _diverted_from_archive(reached: bool, outcome: str) -> bool:
    """The trace never recorded archive, and the item is not a ship outcome."""
    return not reached and outcome != "ship"


def _issue_tags(loops: list[dict], outcome: str, last: dict | None, reached: bool,
                gt: str | None, pred: str | None) -> list[str]:
    """Issue tags derived from the trace. Order is part of the digest contract."""
    issues: list[str] = []
    if loops:
        issues.append("loop")
    if _stuck_open(outcome, last, loops):
        issues.append("stuck")
    if outcome == "held":
        issues.append("held")
    if outcome == "failed":
        issues.append("failed")
    if outcome == "open":
        issues.append("open")
    if _class_miss(gt, pred, outcome):
        issues.append("miss")
    if _diverted_from_archive(reached, outcome):
        issues.append("diverted")
    return issues


def _diagnose(item: dict, records: list[dict], outcome: str, stage: str | None,
              review: str | None, note: str | None, pred: str | None, gt: str | None,
              plain: set[tuple[str, str]]) -> dict:
    """Explain a document's visits, repeats, and why it did or did not reach archive.

    Every sentence quotes a stored decision, review cause, status, or an
    unconditional edge. A missing router input is reported as absent; it is
    not reconstructed from the graph's conditional maps.
    """
    visits = _closed_visits(records)
    causes = _review_causes(item)
    loops = _loop_rows(visits)
    hops, omitted = _hop_list(visits, causes, plain)
    last = visits[-1] if visits else None
    reached = any(visit["node"] == "archive" for visit in visits)
    if reached:
        stopped = None
    elif last:
        stopped = last["node"]
    else:
        stopped = None
    why = _archive_why(visits, outcome, stage, review, note, causes, hops, loops, last, stopped, reached)
    issues = _issue_tags(loops, outcome, last, reached, gt, pred)
    return {
        "issues": issues,
        "loops": loops,
        "hops": hops,
        "hops_omitted": omitted,
        "causes": causes,
        "archive": {"reached": reached, "stopped": stopped, "why": _clip(why, 420)},
        "answers": _answer_bits(visits),
        "mode": _failure_mode(issues, loops, last, stopped, reached, outcome, causes, review, note, pred, gt),
    }


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


def build_run(name: str, path: Path, edge_set: set[tuple[str, str]],
              plain_edges: set[tuple[str, str]] | None = None) -> tuple[dict, set[str]]:
    """Summarize a run's artifacts and return the summary and observed classes.

    The last item record for an ID wins. Node counts are distinct documents;
    edge counts are traversals limited to edge_set. Per-class traffic requires
    dataset class labels, and node duration medians are in milliseconds. The summary
    also includes in-flight documents, mean item latency and routing counts. Each
    document row carries a ``debug`` trace (visits, repeats, hop reasons, and why
    archive was or was not reached) built only from stored fields and
    ``plain_edges``. Missing or invalid artifact data uses the reader fallbacks;
    errors reading dataset bytes for an absent hash propagate.
    """
    plain = plain_edges or set()
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
            "fields": _field_notes(it, ds_by_id.get(item_id)),
            "labels": _label_provenance(ds_by_id.get(item_id)),
            "review": _review_trigger(it, recs),
            "note": _error_text(it),
            "debug": _diagnose(it, recs, bucket, str(stage) if stage else None,
                               _review_trigger(it, recs), _error_text(it), _pred_class(it),
                               None if cls == "?" else cls, plain),
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
    kept_docs, docs_omitted, docs_omitted_healthy = _select_doc_rows(doc_rows)
    reads_by_doc = read_ranges_by_doc(path)
    if reads_by_doc is not None:  # absent file: the viewer says "not recorded"
        for row in kept_docs:
            if row["id"] in reads_by_doc:
                row["debug"]["reads"] = reads_by_doc[row["id"]]
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
        "docs": kept_docs,
        "docs_truncated": docs_omitted,
        "docs_omitted_healthy": docs_omitted_healthy,
    }
    classes = {c for c in outcomes if c != "?"} | set(ds_class.values())
    return run, classes


# ── build / output ──────────────────────────────────────────────────────────────


def resolve_base(arg: str | None) -> Path:
    """Choose a data directory from arg, MAILROOM_BASE_DIR, or ./data, in order."""
    return Path(arg or os.environ.get("MAILROOM_BASE_DIR") or "./data")


def named_runs(runs_found: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """``(digest run name, dir)`` for each discovered run; a repeated dir name gains ``(source)``."""
    named: list[tuple[str, Path]] = []
    used: set[str] = set()
    for source, path in runs_found:
        name = path.name if path.name not in used else f"{path.name} ({source})"
        used.add(name)
        named.append((name, path))
    return named


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
    plain_edges = {tuple(pair) for pair in graph.get("plain_edges") or []}
    runs: list[dict] = []
    classes: set[str] = set()
    for name, path in named_runs(runs_found):
        run, run_classes = build_run(name, path, edge_set, plain_edges)
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
