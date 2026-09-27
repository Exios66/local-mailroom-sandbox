# Family subagent roster sync

One manifest drives OpenCode and Cursor across the mailroom family.

## Canonical file

[`config/subagents/family-roster.yaml`](../config/subagents/family-roster.yaml) lists every
coding subagent, its **home package**, and which packages **materialize** it.

| Package | Typical path | Roster install path |
| --- | --- | --- |
| `local-mailroom-sandbox` | this repo | `config/subagents/family-roster.yaml` |
| `mailroom-dev` | monorepo hub | `governance/subagents/family-roster.yaml` |
| `llm-mailroom` | `packages/llm-mailroom` | `config/subagents/family-roster.yaml` |
| `llm-entity-extraction` | `packages/llm-entity-extraction` | `config/subagents/family-roster.yaml` |
| `eval-environment` | eval runner repo | `config/subagents/family-roster.yaml` |

## Workflow

From a sandbox checkout (prompt snapshots live under `.opencode/agents/`):

```bash
# 1) Install manifest + missing prompts into a sibling checkout
sandbox subagents materialize --package llm-mailroom --root ../mailroom-dev/packages/llm-mailroom
sandbox subagents materialize --package mailroom-dev --root ../mailroom-dev
sandbox subagents materialize --package eval-environment --root ../eval-environment

# 2) Merge roster metadata into OpenCode frontmatter + refresh Cursor stubs
sandbox subagents sync --harness all --package llm-mailroom --root ../mailroom-dev/packages/llm-mailroom
sandbox subagents sync --harness all --package mailroom-dev --root ../mailroom-dev
```

After editing prompts in `.opencode/agents/`, re-run sync for the packages that
include that subagent (`sandbox subagents list --package llm-mailroom`).

## Harness adapters

| Harness | Output | What sync does |
| --- | --- | --- |
| **OpenCode** | `.opencode/agents/<id>.md` | Merges roster frontmatter (`mode`, `title`, `tags`, `home_package`, `roster_id`) while preserving the prompt body |
| **Cursor** | `.cursor/agents/<id>.md` | Generates `name` + `description` stubs pointing at the OpenCode canonical prompt |
| **OpenCode global** | `~/.config/opencode/agents/<id>.md` | Same frontmatter merge for machine-wide profiles (`--harness opencode-global`) |

Default CLI sync target is **`--harness all`** (includes global).

Health: `sandbox subagents doctor` and optional `--also-root <checkout>`.
Framework v2: [`config/subagents/AGENT_FRAMEWORK.md`](../config/subagents/AGENT_FRAMEWORK.md).

## Environment

Set `SUBAGENT_PACKAGE` to override the default package filter
(`local-mailroom-sandbox`) for list/show/sync without passing `--package`.
