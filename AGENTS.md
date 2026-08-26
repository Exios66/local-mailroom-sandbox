# AGENTS.md

Local-mailroom-sandbox: a **local-first experiment harness** around the governed
LLM-Mailroom family. It does **not** reimplement the 13-node LangGraph pipeline.
Pipeline code lives in [`llm-mailroom`](https://github.com/Exios66/llm-mailroom)
`v0.5.0`; scoring in [`llm-dojo-scoring`](https://github.com/Exios66/llm-dojo-scoring)
`v0.9.0`; prompt loops optionally in `llm-entity-extraction`.

Python 3.11+, no build step.

## Commands

```bash
pip install -e ".[dev]"
cp config/.env.example .env
sandbox profiles
sandbox cutover --profile ollama
sandbox up                          # phoenix + ollama compose profiles
sandbox pull-models                 # ollama pull qwen3:8b
sandbox health
sandbox pilot --mock                # no LLM
sandbox pilot --local               # real local provider
sandbox eval sorter --mock
sandbox matrix --providers ollama --models qwen3:8b --prompts sorter_local_v0 --mock --dry-run
pytest -v                           # network-free; live LLM tests need SANDBOX_LOCAL_LLM=1
```

- Config: `config/profiles/*.yaml` + `config/taxonomy.overlay.yaml` + `config/models.yaml`.
- Runtime taxonomy is written to `data/runtime/taxonomy.yaml` (gitignored).
- Experiment log: `reports/experiment_log.jsonl` (sandbox-local, not a sister-repo mirror).
- Tracing default: Phoenix (`OBSERVABILITY_PROVIDER=phoenix`). OpenRouter is opt-in.

## Architecture gotchas

- Activate **before** importing mailroom graph/agents: `mailroom_sandbox.runtime.activate(profile)`.
- Mailroom's `pipeline.config.CONFIG_PATH` is hardcoded; the sandbox monkeypatches it.
- `DEFAULT_PROVIDER` alone is not enough — OpenRouter model ids must be rewritten via the overlay.
- Scoring is pinned to `llm-dojo-scoring @ v0.9.0`. The `llm-mailroom` **v0.5.0 tag** still depends on dojo v0.7.0, so mailroom is not a core pip dependency (pip cannot satisfy both). `sandbox fetch-deps` clones the v0.5.0 source tree; `pip install -e ".[pipeline]"` installs current mailroom *main* (same dojo pin).
- `scripts/` and `legalbench/` are not in the installed `mailroom` wheel. `sandbox fetch-deps` supplies `PYTHONPATH` for `sandbox pipeline watcher` / `sandbox pipeline api`.
- No second kanban board in this repo. Cross-family work stays on llm-entity-extraction's MESSAGE_BOARD.

## Tests

No real LLM calls in the default suite. `@pytest.mark.local_llm` is skipped unless `SANDBOX_LOCAL_LLM=1`.
