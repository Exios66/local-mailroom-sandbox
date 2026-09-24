# Subagent roster

| File | Role |
| --- | --- |
| [`family-roster.yaml`](family-roster.yaml) | **Canonical family manifest** (packages, harnesses, all subagents) |
| [`roster.yaml`](roster.yaml) | Pointer for this checkout (`package: local-mailroom-sandbox`) |

Commands:

```bash
sandbox subagents packages
sandbox subagents list [--package llm-mailroom]
sandbox subagents show harness-doctor
sandbox subagents sync --harness all
sandbox subagents materialize --package mailroom-dev --root /path/to/mailroom-dev
```

Monorepo workflow: [`docs/subagents-family-sync.md`](../../docs/subagents-family-sync.md).

After editing an OpenCode prompt, run `sandbox subagents sync --harness all`.
