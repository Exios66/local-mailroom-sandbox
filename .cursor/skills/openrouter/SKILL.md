---
name: openrouter
description: Configure OpenRouter, the default experimental/deployment provider for local-mailroom-sandbox. Use for API-only or hybrid experiment configuration, per-agent API routes, credential selection, and API budget preflight. For saved-log viewing use the floor guidance; no provider connection is needed.
---

# OpenRouter experiments

Read [sandbox-tool-router](../sandbox-tool-router/SKILL.md) first. OpenRouter is
the default for new experiment creation and CLI profile selection. Explicit
profiles, existing environment selections, run YAMLs and immutable locks retain
their provider; the legacy run schema still supplies Modal defaults to old
specs with omitted fields. Never migrate a locked run by changing its provider.

## Configuration and identity

The owning profile is `config/profiles/openrouter.yaml`: provider `openrouter`,
base URL `https://openrouter.ai/api/v1`, credential variable
`OPENROUTER_API_KEY`, and optional `OPENROUTER_BASE_URL` override. Read its
`default_model`, `judge_model` and `api_models` alongside `config/models.yaml`
instead of copying model names from an old experiment. These are declared
configuration values, not proof of current provider availability or pricing.

Set credentials privately in the environment or the gitignored `.env`. Do not
print them, place them in run specs, or substitute another provider's key.
Per-agent routes can select their own `api_key_env`; preserve that routing.
Activate the chosen profile before importing the vendored graph or agents.

```bash
sandbox profiles
sandbox experiment create pipeline-api --task pipeline --provider openrouter --samples 10
sandbox experiment review --config config/experiments/pipeline-api/experiment.yaml
```

Creation and review do not call a model or deploy a GPU. Preflight may fetch
the pinned dataset unless it is local/cached. A failed API key or model check
does not authorize fallback to Modal, Ollama, another model, or another account.

## Live execution and budgets

Use the existing lifecycle: preflight, review the locked configuration, then
launch only with authorized human initials. Initials belong to the operator;
never invent them. Every paid run needs `job.max_wall_seconds`; OpenRouter
routes also need `job.api_cost_cap_usd` and a known token price for every API
model. A hybrid run that warms Modal GPUs additionally needs its GPU cost cap.
The GPU cap does not cap API spend. New experiment creation recommends budgets;
recommendations are estimates, not measured charges.

Before paid execution, verify model/provider identity and the price sheet
against the owning service with a check date. Keep explicit experiment pins,
provider constraints and locked question hashes. A Decisions-API reviewer uses
`reviewer.backend: decisions` and `config/decision_models.yaml`; it is a
different contract from a chat-model route. Follow
[experiments](../../../docs/experiments.md) and
[provider guidance](../../../docs/setting-up/providers.md) for the commands.

## Offline review and saved logs

Floor viewing needs no API key, model endpoint, tracing sink or inference call:

```bash
sandbox floor --register-run /path/to/previous/run
sandbox floor --replay-run /path/to/previous/run --base /path/to/scratch-data
```

Registration references the original run artifacts without modifying them.
Replay materializes a separately labelled timeline; never cite replay timing,
tokens or scores as a new model measurement. See
[floor operation](../../../docs/floor.md). Langfuse remains the default tracing
sink; selecting OpenRouter does not select a different trace backend.
