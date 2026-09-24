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

## Workflow

### One command (recommended)

From a sandbox checkout with sibling `mailroom-dev/` (or set `MAILROOM_DEV_ROOT`):

```bash
sandbox subagents propagate
```

This runs **materialize + sync** for every entry in
[`checkout-map.yaml`](../config/subagents/checkout-map.yaml) (`mailroom-dev`,
`packages/llm-mailroom`, `packages/llm-entity-extraction`,
`packages/local-mailroom-sandbox`).

### Monorepo automation

After a one-time hook in `mailroom-dev` `scripts/sync_packages.py` (see
[`scripts/monorepo/INTEGRATION.md`](../scripts/monorepo/INTEGRATION.md)), each
successful **`pull`** / **`push`** runs:

```bash
python3 packages/local-mailroom-sandbox/scripts/monorepo/after_packages_sync.py
```

### Manual per-checkout

```bash
sandbox subagents materialize --package llm-mailroom --root ../mailroom-dev/packages/llm-mailroom
sandbox subagents sync --harness all --package llm-mailroom --root ../mailroom-dev/packages/llm-mailroom
```

After editing prompts in `.opencode/agents/`, re-run **`propagate`** or sync for
the affected packages (`sandbox subagents list --package llm-mailroom`).

## Harness adapters

| Harness | Output | What sync does |
| --- | --- | --- |
| **OpenCode** | `.opencode/agents/<id>.md` | Merges roster frontmatter (`mode`, `title`, `tags`, `home_package`, `roster_id`) while preserving the prompt body |
| **Cursor** | `.cursor/agents/<id>.md` | Generates `name` + `description` stubs pointing at the OpenCode canonical prompt |

Default CLI sync target is **`--harness all`**.

## Environment

Set `SUBAGENT_PACKAGE` to override the default package filter
(`local-mailroom-sandbox`) for list/show/sync without passing `--package`.
