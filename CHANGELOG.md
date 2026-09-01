# Changelog

## [Unreleased]

### Changed

- **HUB-015 — reduced agent profile + current-pipeline alignment**: the
  **reporter agent is retired** (moved to `retired_agents`; the compile stage
  is the computational procedural `compile_report` node — deterministic
  matter-record assembly, **zero LLM calls**, and the sandbox eval no longer
  acquires an LLM client for it). **Reviewers stay enabled.** Sandbox surfaces
  aligned to llm-mailroom **v0.6.0** (`fetch-deps`, docs) and dojo **v0.12.2**.
  HF fixtures (`data/fixtures/hf/docclass_mini.jsonl`) now carry full
  docclass-merged ground-truth targets: corpus-strata `expected_subclass` for
  all 5 doc types + `expected_fields` from the 27-key GT schema (correspondence
  intent + provenance; insurance claim entities), propagated into every eval
  row. Dockerfile gains a non-root user + HEALTHCHECK; all four `:latest`
  compose images pinned (ollama 0.33.2, vllm v0.28.0, phoenix version-20.4.0,
  minio RELEASE.2025-09-07…).

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
- Scoring is pinned to `llm-dojo-scoring @ v0.12.2` (local vs API serving
  table + scorecard + cost from [#10](https://github.com/Exios66/llm-dojo-scoring/pull/10);
  aligned with llm-mailroom v0.6.0's own pin). Mailroom **v0.6.0** is the
  `sandbox fetch-deps` source tree; `pip install -e ".[pipeline]"` installs
  mailroom *main*.
- `sandbox eval local_vs_api --mock` compares offline (Ollama/vLLM) vs API-key
  (OpenRouter) serving metrics via `get_suite("local_vs_api")` without needing
  `OPENROUTER_API_KEY`. The comparison returns a full T0/T1 **table** (missing
  stays `None`), a **scorecard** with identity tags, and token × price-table
  **cost**. Local and API values emit as separate scorecards (`run_id:local` /
  `run_id:api`). Sorter T0 stays `accuracy` + `f1_macro`; TTFT is never
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
