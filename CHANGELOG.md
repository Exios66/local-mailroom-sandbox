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
- Scoring is pinned to `llm-dojo-scoring @ v0.10.0`. Mailroom **v0.5.0** (source
  via `sandbox fetch-deps`) still listed dojo v0.7.0 as a pip pin; the sandbox
  follows the current family scoring engine. `pip install -e ".[pipeline]"`
  installs mailroom *main* (matching dojo pin once mailroom lands `@v0.10.0`).

### Changed

- Scoring pin `llm-dojo-scoring @ v0.9.0` → `@v0.10.0` (tag target `3261cdd`).
  Additive: specialist field-micro P/R/F1/F2, `score_task("docclass")` now
  computes `f1_macro`, insurance `determination_consistency` is a real scorer.

### Fixed

- ClickHouse compose healthcheck no longer passes database credentials
  as CLI flags (GitGuardian generic CLI secret detector).
