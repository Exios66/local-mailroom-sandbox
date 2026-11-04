# Spec: floor-digest builder (productionize the scratch analytics)

## Goal
Promote the scratch pipeline-floor analytics into the repo as a reproducible builder.
A single command rebuilds a digest of ALL previous runs from on-disk artifacts only.
The existing validated HTML view (`floor-v10.html`, provided) consumes the emitted
digest WITHOUT modification — the output schema is frozen (see Contract).

## Deliverables (touch ONLY these paths)
1. `reports/dashboard/build_floor_digest.py` — the builder (stdlib only).
2. `reports/dashboard/floor.template.html` — copy of the provided floor-v10.html.
3. `reports/dashboard/selftest_floor_digest.py` — deterministic gate (see Tests).
4. Outputs (generated, not hand-written): `reports/dashboard/floor_digest.json`,
   `reports/dashboard/floor_digest.js`.

## Forbidden
- Do NOT modify anything under `vendor/`, `config/`, `src/`, `data/`, or the
  live run directories. The builder READS artifacts; it never writes outside
  `reports/dashboard/`.
- No third-party deps: Python 3.10+ stdlib only (`json, os, re, sys, pathlib,
  collections, statistics, datetime`).
- No hard-coded run names or counts anywhere in the builder or template.

## Inputs the builder must read
Base dir resolution: `MAILROOM_BASE_DIR` env var if set, else `./data`.
- Run locations: every dir under `$BASE/runtime/runs/*` (live runs) AND every
  dir under `$BASE/run-history/*` (archived attempts). Auto-discovered; a run
  dir is any dir containing `items.jsonl`. Missing sibling files degrade to
  empty/zero honestly (e.g. archived attempt without `dataset.jsonl` ->
  `total: null`), never fabricated.
- Per run: `items.jsonl`, `nodes.jsonl`, `checkpoint.json`,
  `spec.lock.json`, `prompt.lock.json`, `dataset.jsonl` (may be absent).
- Engine/profile labels: parse from the run's `spec.lock.json` (engine kind,
  model, profile) — do not hard-code `qwen3.5-9b`.

## Topology (the key upgrade)
Derive `graph_reference` by PARSING `vendor/llm-mailroom/src/graph/build_graph.py`
(read-only) instead of hand transcription:
- Edges: every `add_edge("A","B")` pair, plus every `add_conditional_edges`
  mapping whose route dict values name graph nodes. `START` entry maps included.
  Filter `END` (graph terminal) out of node boxes.
- Node agent attribution: from the node-registration block (the wrap calls map
  node name -> agent/role name); nodes whose handler is pure code keep
  `(code)`-style attribution. If the file shape can't be parsed, FAIL LOUDLY
  with a clear error rather than emitting a partial topology.
- Note fields in `graph_reference.note`: transient self-loops (edges where
  source==target) are excluded from the drawn set; document that.

## Digest contract (schema is FROZEN — floor-v10.html renders from this)
```json
{
  "generated_utc": "...", "classes": ["<sorted expected_doc_class names>"],
  "graph_reference": {"edges": [["a","b"], ...], "node_agents": {"node": "agent"}, "note": "..."},
  "runs": [{
    "name": "...", "state": "...", "cursor": 0, "total": 0,
    "items_attempted": 0, "items_ok": 0,
    "engine": {"kind": "...", "model": "..."}, "profile": "...",
    "spec_hash": "...", "dataset_hash": "...", "prompt_default": "...",
    "tokens": {"prompt": 0, "completion": 0},
    "node_fires": {"node": n}, "edge_fires": {"a>b": n},
    "node_agents": {"node": {"agent": n}}, "node_ms_p50": {"node": ms},
    "aborts_by_last_node": {"node": n},
    "outcomes": {"<matter_id or item key>": {"ship": n, "held": n, "failed": n, "open": n, "n": n}},
    "per_class": {"<class>": {"nodes": {"node": n}, "edges": {"a>b": n},
                               "outcomes": {"ship": n,"held": n,"failed": n,"open": n,"n": n}}}
  }]
}
```
Derivation rules (from the scratch builder's proven semantics):
- node_fires: count of docs that visited a node = distinct doc/item ids per
  node from `nodes.jsonl` (not raw line count).
- edge_fires: for each item, ordered sequence of visited nodes from nodes.jsonl;
  each consecutive pair (within the parsed topology's edge set) gets +1 per doc
  traversal. Self-transients count toward the node, never toward an edge.
- node_ms_p50: median duration field per node from nodes.jsonl (fallback: 0).
- tokens: summed token fields from nodes.jsonl per run; honest zeros if absent.
- outcomes: per run, group items.jsonl by final stage -> ship (archived),
  held (human_review/pending), failed, open (mid-graph), n.
- per_class: same counting restricted to docs whose `expected_doc_class` comes
  from dataset.jsonl (or spec.lock when dataset absent); when dataset is missing,
  `per_class` for that run must be `{}` (honest gap, no fabrication).
- Also emit `floor_digest.js` = `window.DIGEST=<json>;` twin of the JSON,
  byte-identical payload.

## CLI surface (builder only — NOT a sandbox CLI subcommand)
`python build_floor_digest.py [--base DIR] [--out DIR] [--print-summary]`
Prints a one-line-per-run summary (name, state, attempted, ok, top-3 nodes).
Exit non-zero with a clear message on: no runs found, build_graph.py unparseable,
schema write failure.

## Tests (selftest_floor_digest.py — deterministic gate, stdlib assert only)
1. Runs the builder with `--base` pointed at a TEMP fixture it creates itself:
   two synthetic run dirs (items/nodes/checkpoint/spec/dataset fixtures, one
   without dataset.jsonl) + a stub build_graph.py containing add_edge /
   add_conditional_edges examples.
2. Asserts: graph_reference edges parsed from stub (incl. conditional map),
   node_fires distinct-doc semantics, edge_fires traversal counting, outcomes
   grouping, per_class empty when dataset absent, floor_digest.js twin parses
   back to the same object, unknown stage never crashes.
3. If the real `$BASE/runtime/runs` exists, additionally run against it and
   assert every run's sum(outcomes.n) == items_attempted and all edge_fires
   keys exist in graph_reference edges (cross-consistency).
4. Prints `SELFTEST <pass>/<total> PASS` and exits 0; else exit 1.

## Acceptance for the human reviewer
- `python reports/dashboard/selftest_floor_digest.py` passes in WSL with the
  repo venv (`/home/gemooslin/sandbox-venv/bin/python`) OR plain python3.
- Against the real sandbox-data base, regenerated digest shows the SAME numbers
  as the provided reference digest (frozen copy at
  `reports/dashboard/reference_digest_scratch.json`, copied from the validated
  scratch run) for runs present in both; new/changed runs may only differ by
  growth.
- No git diff to any path outside `reports/dashboard/`.
