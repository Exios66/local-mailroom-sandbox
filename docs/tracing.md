# Tracing

Canonical sink: **Langfuse 3** (Python SDK v4 data model) on
`http://localhost:3000` (compose profile `langfuse`). This is the same
contract llm-mailroom writes and The-Mailroom reads.

```
OBSERVABILITY_PROVIDER=langfuse   # or auto | phoenix | braintrust | none
OBSERVABILITY_ENVIRONMENT=pilot   # mock for --mock, pilot for --local
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-sandbox
LANGFUSE_SECRET_KEY=sk-lf-sandbox
```

`sandbox up` (ollama profile) starts **langfuse + ollama**. Phoenix remains an
optional sidecar (`--compose-profile phoenix`) — The-Mailroom cannot plot
Phoenix spans.

`auto` follows mailroom's chain: Langfuse if its secret is set, else Braintrust,
else Phoenix, else none.

## Family data model

One document (or isolated agent eval) is one trace:

| Field | Value |
| --- | --- |
| root name | `document-pipeline` |
| root type | `chain` |
| children | verb-first names from `NODE_OBSERVATION_TYPES` |
| `session_id` | `sandbox-<task>-<utc>` for evals; `matter_id` for watcher/api |
| tags | `mailroom`, environment, `sandbox`, profile, `mock`/`local`, `source-*` |
| metadata | `{pipeline: mailroom, run_id, attempt, source}` |
| ground truth on the trace | `expected_hf_class`, `expected_doc_class`, `expected_subclass`, `expected` only |

Isolated evals still open the root chain and nest the one relevant observation
so The-Mailroom can draw a partial conveyor.

Score names follow llm-mailroom `SCORE_CONFIGS` / dojo aliases
(`extraction_overall_verified_precision` → `extraction_verified_precision`).

## The-Mailroom

```bash
sandbox fetch-deps --visualizer
# point The-Mailroom at the same project:
# LANGFUSE_HOST=http://localhost:3000
# MAILROOM_TRACE_NAMES=document-pipeline
# MAILROOM_TRACE_TAGS=mailroom
# MAILROOM_TRACE_ENVIRONMENTS=mock,pilot
```

## Export

```bash
sandbox traces export    # writes data/traces/export.json (host + last trace ids)
```

Inspect traces in the Langfuse UI. Durable scores also live in
`reports/experiment_log.jsonl` and `reports/scores/`.
