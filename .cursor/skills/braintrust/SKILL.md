---
name: braintrust
description: Opt-in Braintrust observability/eval logging for local-mailroom-sandbox. Use only when BRAINTRUST_API_KEY is set, OBSERVABILITY_PROVIDER=braintrust|auto selects it, or the user explicitly asks for Braintrust experiments — never as the default offline sink.
---

# Braintrust (opt-in hosted)

**When:** Explicit Braintrust request, or `auto` with `BRAINTRUST_API_KEY` and no Langfuse secret.  
**Prefer Langfuse** for local compose + The-Mailroom. Braintrust is a **cloud** escape hatch, not the sandbox default.

## Enable

```bash
# config/.env (never commit secrets)
OBSERVABILITY_PROVIDER=braintrust   # or auto
BRAINTRUST_API_KEY=...
BRAINTRUST_PROJECT=mailroom-sandbox
# BRAINTRUST_PROJECT_ID=...      # wins over project name when supplied
```

`auto` order: Langfuse → **Braintrust** → Phoenix → none (`mailroom_sandbox.eval.tracing.tracing_backend`).

## Boundaries

| Do | Don't |
| --- | --- |
| Use for hosted experiment comparison when the user opts in | Start Braintrust in default `sandbox up` |
| Keep `reports/experiment_log.jsonl` as the durable local log | Assume The-Mailroom reads Braintrust |
| Disable in pytest (`OBSERVABILITY_PROVIDER=none`) | Put API keys in fixtures or compose YAML |

`mailroom_sandbox.eval.tracing` implements a native Braintrust adapter:
`document_pipeline_trace` and `child_observation` emit spans, score helpers attach scores, and
`flush_traces` flushes the logger. It requires both an API key and a project
name or ID. SDK initialization exceptions, span-start/end and flush failures are
logged and counted. A configured API key without either project variable only
warns and returns without recording spans or incrementing the initialization counter.
Span `log`, `update` and `score` calls can propagate SDK errors without incrementing
those counters; a selected sink or zero counter is not proof of delivery. Inspect
`tests/test_tracing_braintrust.py` and the export diagnostics before claiming
hosted evidence. Durable scores still go to `reports/` via Dojo/experiment log.

## Related

- Default sink: [langfuse](../langfuse/SKILL.md)  
- Router: [sandbox-tool-router](../sandbox-tool-router/SKILL.md)  
- Env template: `config/.env.example`
