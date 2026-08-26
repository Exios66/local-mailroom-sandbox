# local-mailroom-sandbox

A **local-first experiment sandbox** for the [LLM-Mailroom](https://github.com/Exios66/llm-mailroom) pipeline. Run the full classify → extract → report → archive graph offline on Ollama, vLLM (local or Modal), llama.cpp, or LM Studio. Swap in OpenRouter when you need an API provider. This repo does **not** fork the pipeline — it overlays config, serving, eval, and scoring around the governed family.

| At a glance | |
| --- | --- |
| Default provider | Ollama (`qwen3:8b`, fallback `qwen3:7b`) |
| Scoring | [`llm-dojo-scoring` @ v0.9.0](https://github.com/Exios66/llm-dojo-scoring) |
| Pipeline | [`llm-mailroom`](https://github.com/Exios66/llm-mailroom) (`fetch-deps` @ v0.5.0 source; `[pipeline]` extra = main) |
| Tracing | Arize Phoenix (local). Langfuse / Braintrust opt-in |
| Storage | SQLite under `./data` (mailroom default) |

## Quick start

```bash
pip install -e ".[dev]"
cp config/.env.example .env
sandbox fetch-deps                 # clones vendor/llm-mailroom @ v0.5.0 (source tree)
# optional: pip install -e ".[pipeline]"  # current mailroom main (dojo v0.9.0)
sandbox up                         # Phoenix + Ollama
sandbox pull-models                # ollama pull qwen3:8b
sandbox health
sandbox pilot --mock               # machinery only, no LLM
sandbox pilot --local              # real local model
sandbox eval sorter --mock
```

CPU-only smoke: pull `llama3.2:3b` and `sandbox cutover --profile ollama --model llama3.2:3b`. GPU recommended for Qwen 8B.

## One-command local path

1. Install
2. `sandbox up` (compose profiles `phoenix` + `ollama`)
3. `sandbox pull-models`
4. `sandbox pilot --mock`
5. `sandbox pilot --local`

## CLI

```
sandbox up | down | health | pull-models | fetch-deps | cutover | profiles
sandbox pipeline watcher | pipeline api
sandbox pilot --mock|--local
sandbox hf-pilot --check|--mock|--local
sandbox legalbench --mock|--local
sandbox eval sorter|extract|chained|pipeline|legalbench [--mock|--local]
sandbox matrix --providers ollama --models qwen3:8b --prompts sorter_local_v0
sandbox datasets pull
sandbox traces export
```

## Docs

- [Providers](docs/providers.md) — Ollama, vLLM, Modal, llama.cpp, LM Studio, OpenRouter
- [Evals](docs/evals.md) — runners, matrix, scoring, experiment log
- [Tracing](docs/tracing.md) — Phoenix-first, tags, export
- [Sister repos](docs/sister-repos.md) — family map

## Layout

```
config/profiles/     provider profiles (local-first defaults)
config/taxonomy.overlay.yaml
config/models.yaml   OpenRouter champion → local tag map
deploy/              compose + Modal vLLM
data/fixtures/       offline samples (see ATTRIBUTION.md)
src/mailroom_sandbox/
reports/             sandbox experiment log (not a sister-repo mirror)
```
