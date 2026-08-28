# Changelog

## [Unreleased]

### Added

- Local-first LLM-Mailroom experiment sandbox: provider profiles (Ollama, vLLM
  local, Modal vLLM, llama.cpp, LM Studio, opt-in OpenRouter), taxonomy overlay
  with OpenRouter→local model map, Docker Compose (Phoenix / Ollama / vLLM /
  llama.cpp / optional Langfuse), Modal deploy wrapper (`sandbox-vllm`),
  fixture catalog + tiny HF / LegalBench slices, eval runners (sorter /
  extract / chained / pipeline / legalbench), provider×model×prompt matrix,
  llm-dojo-scoring emission, Langfuse v4 `document-pipeline` tracing, append-only
  `reports/experiment_log.jsonl`, and a `sandbox` CLI.
- Isolated evals for every live agent/node (`sandbox eval judge`,
  `contracts_specialist`, `arbiter`, …) plus connected pipeline scoring
  (class / stage / extraction / routing).
- Per-agent overlay knobs and `sandbox cutover --agent-model NAME=tag`.
- Langfuse 3 compose (web + worker + postgres + clickhouse + redis + minio)
  with headless `LANGFUSE_INIT_*` keys matching The-Mailroom filters.
- Scoring is pinned to `llm-dojo-scoring @ v0.12.0` (local vs API serving
  suite). Mailroom **v0.5.0** (source via `sandbox fetch-deps`) still listed
  dojo v0.7.0 as a pip pin; the sandbox follows the current family scoring
  engine. `pip install -e ".[pipeline]"` installs mailroom *main*.
- `sandbox eval local_vs_api --mock` compares offline (Ollama/vLLM) vs API-key
  (OpenRouter) serving metrics via `get_suite("local_vs_api")` without needing
  `OPENROUTER_API_KEY`. Sorter T0 stays `accuracy` + `f1_macro`; TTFT is never
  inferred from e2e / n_tokens. GPU/KV/VRAM stay `None` on API-key records.
- Offline Docker image (`deploy/Dockerfile` → `mailroom-sandbox:offline`) and
  Compose profile `jupyter` for Jupyter Lab on `:8888`, plus dedicated notebooks
  (`notebooks/01`–`03`) and `sandbox datasets prepare` to load/clean/write
  fixtures under `data/runtime/prepared/`.
- Project Agent Skills under `.cursor/skills/` for tool selection: router plus
  Langfuse, Braintrust, Apache Phoenix, Ollama, Modal, and Hugging Face
  (offline-first Hub usage).

### Fixed

- ClickHouse compose healthcheck no longer passes database credentials
  as CLI flags (GitGuardian generic CLI secret detector).
