# Sister repos

This sandbox is an **orchestrator**. Canonical code stays in the governed family:

| Repository | Role | Pin |
| --- | --- | --- |
| [llm-mailroom](https://github.com/Exios66/llm-mailroom) | LangGraph pipeline, agents, prompts, SQLite catalog | `v0.5.0` source via `fetch-deps`; `[pipeline]` extra = main |
| [llm-dojo-scoring](https://github.com/Exios66/llm-dojo-scoring) | Deterministic scoring engine | `v0.9.0` |
| [llm-entity-extraction](https://github.com/Exios66/llm-entity-extraction) | Prompt experiment loop (optional `[evals]` extra) | `v0.20.0` |
| [The-Mailroom](https://github.com/Exios66/The-Mailroom) | Pixel-art visualizer (Langfuse-only) | observer |
| [Enron-Evaluation-Environment](https://github.com/Exios66/Enron-Evaluation-Environment) | Correspondence corpus feed | Hub datasets |

Umbrella map: [llm-mailroom/docs/sister-repos.md](https://github.com/Exios66/llm-mailroom/blob/main/docs/sister-repos.md).

Do not duplicate the 13-node graph here. Do not create a second kanban board;
cross-repo work stays on llm-entity-extraction's MESSAGE_BOARD.

Sandbox traces use the same Langfuse v4 contract as llm-mailroom
(`document-pipeline` chain, `NODE_OBSERVATION_TYPES`, `mailroom` tag) so
The-Mailroom can observe local evals. Clone it with `sandbox fetch-deps --visualizer`.
