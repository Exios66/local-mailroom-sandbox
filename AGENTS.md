# AGENTS.md

Local-mailroom-sandbox: a **local-first experiment harness** around the governed
LLM-Mailroom family. It does **not** reimplement the 13-node LangGraph pipeline.
Pipeline code lives in [`llm-mailroom`](https://github.com/Exios66/llm-mailroom)
`v0.5.0`; scoring in [`llm-dojo-scoring`](https://github.com/Exios66/llm-dojo-scoring)
`v0.12.0`; prompt loops optionally in `llm-entity-extraction`.

Python 3.11+, no build step.

## Skills (tool selection)

Committed under `.cursor/skills/`. **Read `sandbox-tool-router` first** for any
provider, tracing, dataset, or deploy task, then open exactly one specialty skill.

| Skill | Appropriate for |
| --- | --- |
| `sandbox-tool-router` | Choosing among the stacks below |
| `ollama` | Default local LLM (prefer over OpenRouter/Modal) |
| `modal` | Remote GPU vLLM (`sandbox-vllm`) |
| `langfuse` | Default tracing + The-Mailroom (Langfuse 3 / SDK v4) |
| `apache-phoenix` | Optional Arize Phoenix OTEL sidecar only |
| `braintrust` | Opt-in hosted Braintrust (never default offline) |
| `huggingface` | Hub pulls / weights; offline fixtures first |

Do not use Phoenix or Braintrust as the The-Mailroom sink. Do not use OpenRouter
unless explicitly opted in.

## Commands

```bash
pip install -e ".[dev]"
cp config/.env.example .env
sandbox profiles
sandbox agents list
sandbox cutover --profile ollama --agent-model judge=qwen3:14b
sandbox up                          # langfuse + ollama compose profiles
sandbox pull-models                 # ollama pull qwen3:8b
sandbox health
sandbox fetch-deps                  # vendor/llm-mailroom @ v0.5.0
sandbox fetch-deps --visualizer     # also clone The-Mailroom
sandbox pilot --mock                # no LLM
sandbox eval sorter --mock
sandbox eval judge --mock
sandbox eval pipeline --mock        # connected graph scores
sandbox eval local_vs_api --mock    # Ollama vs OpenRouter serving (no API key)
sandbox matrix --providers ollama --models qwen3:8b --prompts sorter_local_v0 --mock --dry-run
pytest -v                           # network-free; live LLM tests need SANDBOX_LOCAL_LLM=1
sandbox datasets prepare            # offline JSONL under data/runtime/prepared/
sandbox up --compose-profile jupyter  # Lab on :8888 (deploy/Dockerfile)
```

- Config: `config/profiles/*.yaml` + `config/taxonomy.overlay.yaml` + `config/components.yaml` + `config/models.yaml`.
- Runtime taxonomy is written to `data/runtime/taxonomy.yaml` (gitignored).
- Prepared fixtures: `data/runtime/prepared/` via notebooks or `sandbox datasets prepare`.
- Experiment log: `reports/experiment_log.jsonl` (sandbox-local, not a sister-repo mirror).
- Tracing default: Langfuse 3 / SDK v4 (`OBSERVABILITY_PROVIDER=langfuse`). Phoenix is an optional sidecar. OpenRouter is opt-in.
- Docker: `deploy/Dockerfile` + Compose profiles including `jupyter` — see `docs/docker-offline.md`.
- Agent skills: `.cursor/skills/` (router + Langfuse / Braintrust / Phoenix / Ollama / Modal / Hugging Face).

## Architecture gotchas

- Activate **before** importing mailroom graph/agents: `mailroom_sandbox.runtime.activate(profile)`.
- Mailroom's `pipeline.config.CONFIG_PATH` is hardcoded; the sandbox monkeypatches it.
- `DEFAULT_PROVIDER` alone is not enough — OpenRouter model ids must be rewritten via the overlay.
- `--model` overrides every agent; `--agent-model NAME=tag` is surgical and wins last.
- Scoring is pinned to `llm-dojo-scoring @ v0.12.0`. The `llm-mailroom` **v0.5.0 tag** still depends on dojo v0.7.0, so mailroom is not a core pip dependency (pip cannot satisfy both). `sandbox fetch-deps` clones the v0.5.0 source tree; `pip install -e ".[pipeline]"` installs current mailroom *main*. Importable `get_suite("local_vs_api")` compares offline vs API-key serving metrics (TTFT never inferred; GPU/KV stripped on API records).
- Isolated evals call vendored agent classes when present; otherwise they mock and set `offline_fallback`.
- `scripts/` and `legalbench/` are not in the installed `mailroom` wheel. `sandbox fetch-deps` supplies `PYTHONPATH` for `sandbox pipeline watcher` / `sandbox pipeline api`.
- No second kanban board in this repo. Cross-family work stays on llm-entity-extraction's MESSAGE_BOARD.

## Tests

No real LLM calls in the default suite. `@pytest.mark.local_llm` is skipped unless `SANDBOX_LOCAL_LLM=1`.
