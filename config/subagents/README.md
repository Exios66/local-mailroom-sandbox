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
sandbox subagents sync --harness opencode-global
sandbox subagents doctor
sandbox subagents doctor --apply-framework
sandbox subagents materialize --package digital-mailroom --root /path/to/Digital-Mailroom
sandbox subagents propagate
```

Monorepo workflow: [`docs/subagents-family-sync.md`](../../docs/subagents-family-sync.md).

Shared agent operating law: [`AGENT_FRAMEWORK.md`](AGENT_FRAMEWORK.md).

Every agent must follow the package's
[routine instruction validation](../../AGENTS.md#instruction-validation-routine)
and [maintenance procedure](../../docs/agent-instruction-maintenance.md).
At startup/resume and after long experiments or feature/configuration updates,
verify relevant facts in `AGENTS.md`, `CLAUDE.md`, scoped rules, canonical prompts
and skills. Recheck before handoff or merge; report stale or unverified guidance
with source evidence instead of passing it to the next agent as current fact.

Use the current package's tool guidance before applying a family prompt's
commands. In this sandbox, read the [tool router](../../.cursor/skills/sandbox-tool-router/SKILL.md)
and then the selected specialty skill. The `corpus-curator` prompt belongs to
`eval-environment`; its `evals.cases` probes and `.opencode/skills/mailroom-corpus`
path refer to that package, not this checkout. Sandbox dataset work follows the
[Hugging Face skill](../../.cursor/skills/huggingface/SKILL.md), `corpus.py` and run locks.

After editing a canonical OpenCode prompt, preview project-only synchronization
with `--harness opencode --dry-run` and `--harness cursor --dry-run`, then run those
explicit targets and inspect the diff. `--harness all` also writes global profiles;
use it only for an intended machine-wide refresh. Follow the
[dispatch and recovery contract](../../docs/agent-dispatch.md).

Durable eve agent (machine-wide doctor UI/tools): `~/Downloads/agent-harness-doctor`.
