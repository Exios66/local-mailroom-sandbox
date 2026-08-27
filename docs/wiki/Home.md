# Home

**local-mailroom-sandbox** is a **local-first experiment harness** around the
governed LLM-Mailroom family. It overlays config, serving, eval, scoring, and
Langfuse v4 traces onto the pipeline. It does **not** reimplement the 13-node
LangGraph graph.

| | |
| --- | --- |
| Code | [`README.md`](../../README.md) · [`AGENTS.md`](../../AGENTS.md) |
| Package | [`src/mailroom_sandbox/`](../../src/mailroom_sandbox) |
| CLI | [`src/mailroom_sandbox/cli.py`](../../src/mailroom_sandbox/cli.py) |
| Scoring | [`llm-dojo-scoring` @ v0.11.0](https://github.com/Exios66/llm-dojo-scoring) |
| Pipeline source | [`llm-mailroom`](https://github.com/Exios66/llm-mailroom) `v0.5.0` via `sandbox fetch-deps` |
| Visualizer | [`The-Mailroom`](https://github.com/Exios66/The-Mailroom) (Langfuse-only) |

## Start here

```bash
pip install -e ".[dev]"
cp config/.env.example .env
sandbox fetch-deps
sandbox eval sorter --mock
sandbox eval pipeline --mock
```

Offline Jupyter (no LLM, no Docker):

- [`notebooks/01_activate_overlay.ipynb`](../../notebooks/01_activate_overlay.ipynb)
- [`notebooks/03_isolated_agent_evals.ipynb`](../../notebooks/03_isolated_agent_evals.ipynb)
- [`notebooks/04_pipeline_and_scoring.ipynb`](../../notebooks/04_pipeline_and_scoring.ipynb)

Full table: [Notebooks](Notebooks.md).

<details>
<summary>What this repo is</summary>

- A **profile overlay**: [`runtime.activate()`](../../src/mailroom_sandbox/runtime.py) rewrites every taxonomy agent onto a local tag and writes [`data/runtime/taxonomy.yaml`](../../data/runtime/taxonomy.yaml).
- An **eval harness**: isolated agents + connected pipeline, mock or `--local`.
- A **scoring client** of dojo v0.11.0 (typed extraction, not exact-match-on-fields).
- A **trace producer** that matches llm-mailroom's Langfuse v4 contract (`document-pipeline`, `mailroom` tag) so The-Mailroom can observe local runs.
- A **Compose wrapper** for Langfuse 3 + Ollama (`sandbox up`).

</details>

<details>
<summary>What this repo is not</summary>

- Not a fork of the 13-node graph ([`llm-mailroom`](https://github.com/Exios66/llm-mailroom)).
- Not a second kanban board (cross-family work stays on llm-entity-extraction).
- Not a replacement for The-Mailroom (this repo *writes* traces; the visualizer *reads* them).
- Not a prompt-experiment loop (that is [`llm-entity-extraction`](https://github.com/Exios66/llm-entity-extraction)).

</details>

<details>
<summary>One-command local path (LLM)</summary>

1. `pip install -e ".[dev]"` and `cp config/.env.example .env`
2. `sandbox fetch-deps` — clones [`vendor/llm-mailroom`](../../vendor/README.md) @ v0.5.0
3. `sandbox up` — compose profiles `langfuse` + `ollama` ([`deploy/docker-compose.yml`](../../deploy/docker-compose.yml))
4. `sandbox pull-models` then `sandbox health`
5. `sandbox pilot --mock` then `sandbox pilot --local`

CPU-only smoke: `llama3.2:3b` + `sandbox cutover --profile ollama --model llama3.2:3b`. GPU recommended for Qwen 8B.

</details>

## Wiki map

| Page | Jump |
| --- | --- |
| [Architecture](Architecture.md) | Overlay + activate + honesty |
| [CLI](CLI.md) | Command atlas with flags |
| [Overlay and Cutover](Overlay-and-Cutover.md) | Model map, `--agent-model` |
| [Evals](Evals.md) | Isolated vs connected |
| [Scoring](Scoring.md) | Dojo v0.11.0 |
| [Tracing](Tracing.md) | Langfuse v4 / The-Mailroom |
| [Providers](Providers.md) | Ollama … OpenRouter |
| [Notebooks](Notebooks.md) | Six offline `.ipynb`s |
| [FAQ](FAQ.md) | Pins and failure modes |

How-tos next to the code: [`docs/providers.md`](../providers.md), [`docs/evals.md`](../evals.md), [`docs/tracing.md`](../tracing.md), [`docs/sister-repos.md`](../sister-repos.md).
