# Subagent roster

Canonical manifest: [`roster.yaml`](roster.yaml).

| Layer | Role |
| --- | --- |
| `config/subagents/roster.yaml` | IDs, titles, tags, harness membership, Cursor invoke hints |
| `.opencode/agents/<id>.md` | Full subagent prompts (OpenCode + source for sync) |
| `.cursor/agents/<id>.md` | Cursor-discoverable agents (generated) |

Commands:

```bash
sandbox subagents list
sandbox subagents show harness-doctor
sandbox subagents sync --harness cursor
```

After editing an OpenCode prompt or roster entry, re-run sync so Cursor stays aligned.
