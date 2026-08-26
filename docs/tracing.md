# Tracing

Default sink: **Arize Phoenix** on `http://localhost:6006` (compose profile
`phoenix`). No cloud quota.

```
OBSERVABILITY_PROVIDER=phoenix   # or auto | langfuse | braintrust | none
OBSERVABILITY_ENVIRONMENT=sandbox
PHOENIX_TRACING=enabled
PHOENIX_ENDPOINT=http://localhost:6006/v1/traces
PHOENIX_PROJECT=mailroom-sandbox
```

`auto` follows mailroom's chain: Langfuse if its secret is set, else Braintrust,
else Phoenix, else none.

## Tags

Every sandbox run is tagged `sandbox`, the profile name, `mock` or `local`, and
a source tag (`source-fixtures`, `source-legalbench`, …).

## Export

```bash
sandbox traces export    # writes data/traces/export.json (sink pointer + health)
```

Inspect spans in the Phoenix UI, then delete the Phoenix working dir to discard
a batch. Durable scores live in `reports/experiment_log.jsonl` and
`reports/scores/`.

Optional local Langfuse: `sandbox up --compose-profile langfuse` (port 3000).
The-Mailroom visualizer remains Langfuse-only by its own contract; this stack
is the hook if you want it later.
