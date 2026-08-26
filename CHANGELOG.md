# Changelog

## [Unreleased]

### Added

- Local-first LLM-Mailroom experiment sandbox: provider profiles (Ollama, vLLM
  local, Modal vLLM, llama.cpp, LM Studio, opt-in OpenRouter), taxonomy overlay
  with OpenRouter→local model map, Docker Compose (Phoenix / Ollama / vLLM /
  llama.cpp / optional Langfuse), Modal deploy wrapper (`sandbox-vllm`),
  fixture catalog + tiny HF / LegalBench slices, eval runners (sorter /
  extract / chained / pipeline / legalbench), provider×model×prompt matrix,
  llm-dojo-scoring emission, Phoenix-first tracing, append-only
  `reports/experiment_log.jsonl`, and a `sandbox` CLI.
- Scoring is pinned to `llm-dojo-scoring @ v0.9.0`. Mailroom **v0.5.0** (source
  via `sandbox fetch-deps`) still listed dojo v0.7.0 as a pip pin; the sandbox
  follows the current family scoring engine. `pip install -e ".[pipeline]"`
  installs mailroom *main* (same dojo pin).
