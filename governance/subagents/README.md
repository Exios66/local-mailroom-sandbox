# Family subagent roster (monorepo mirror)

The **canonical** manifest lives in the sandbox package at
[`config/subagents/family-roster.yaml`](../../config/subagents/family-roster.yaml)
and is copied here when you materialize the **`mailroom-dev`** hub:

```bash
# from local-mailroom-sandbox (or monorepo packages/local-mailroom-sandbox)
sandbox subagents materialize --package mailroom-dev --root /path/to/mailroom-dev
sandbox subagents sync --harness all --package mailroom-dev --root /path/to/mailroom-dev
```

Sibling packages (`packages/llm-mailroom`, `packages/llm-entity-extraction`, …)
receive the same manifest under their own `config/subagents/` plus filtered
OpenCode/Cursor stubs for agents listed under that package in the family roster.
