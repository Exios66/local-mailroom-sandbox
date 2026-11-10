---
name: sandbox-tool-router
description: Choose the correct local-mailroom-sandbox tool for serving, tracing, datasets, and deploy. Use at the start of any sandbox, eval, observability, Ollama, Modal, Langfuse, Braintrust, Phoenix, Hugging Face, or provider task so only the most appropriate skill/stack is used.
---

# Sandbox tool router

Read this skill **first** when the task touches providers, tracing, datasets, Docker, or deploys. Then open exactly one specialty skill below. Do not invent a second tracing backend or cloud LLM path when the default already fits.

Apply the [routine instruction validation](../../../AGENTS.md#instruction-validation-routine)
at task start/resume, after long experiments or feature/configuration updates,
and before handoff or merge. Verify this router's and the selected skill's
versions, pins, references and defaults against current evidence; correct stale
guidance without silently upgrading dependencies or changing experiment locks.

For environment checks, coding-agent dispatch, recovery and synchronization,
follow [the shared contract](../../../docs/agent-dispatch.md). Discover the current
harness's capabilities before choosing a dispatch path; machine topology examples
must be checked locally. Suppress quota-only review notifications.

## Decision table

| Job | Use | Skill | Do **not** use |
| --- | --- | --- | --- |
| Offline / CPU-only inference | Ollama (`--profile ollama`) | [ollama](../ollama/SKILL.md) | OpenRouter, Modal, vLLM (unless GPU/Modal requested) |
| Default live serving; GPU / remote OpenAI-compatible serve | Modal vLLM (`modal-vllm`, the default; drive it with `sandbox modal …` / `sandbox vllm …`) or compose `vllm` | [modal](../modal/SKILL.md) | Ollama for 70B-class / long-context GPU work |
| Default tracing + The-Mailroom | Langfuse 3 / SDK v4 | [langfuse](../langfuse/SKILL.md) | Phoenix as the only sink if The-Mailroom is required |
| Optional OTEL / Arize UI sidecar | Apache Phoenix compose profile | [apache-phoenix](../apache-phoenix/SKILL.md) | Phoenix as The-Mailroom input |
| Hosted eval / experiment logs (opt-in) | Braintrust | [braintrust](../braintrust/SKILL.md) | Braintrust as the default offline sink |
| Stable family code snapshots | `sandbox deps fetch --check` / `--component dojo --version TAG`; explicit snapshot lock selection before process startup | [snapshot guide](../../../docs/dependency-snapshots.md) | HF weight downloads for Python code; floating latest inside a frozen run; editing vendor files |
| Hub datasets / model cards / HF cache | Hugging Face Hub + `sandbox datasets pull` / `sandbox hf …` | [huggingface](../huggingface/SKILL.md) | Live Hub pulls in default pytest |
| Offline fixture prep / cached subset draw | `sandbox datasets prepare` / `sandbox datasets sample` | [huggingface](../huggingface/SKILL.md) | Hub network in CI; treating fixture prep as a Hub pull |
| Named dataset / file pin / subset provenance | `config/datasets.yaml` + `sandbox run preflight` | [huggingface](../huggingface/SKILL.md) | Machine paths in committed run specs; guessing a sample from its name |
| Floor viewer / offline replay | `sandbox floor [TARGET]` / `sandbox floor --replay` | [huggingface](../huggingface/SKILL.md) for sample provenance | Model calls for a UI demo; quoting simulated results as measurements |
| Code verification / CI runtime evidence | Local lint/config checks and focused regressions; CircleCI for the full suite/coverage; separately scoped hosted jobs for needed campaigns/benchmarks | [AGENTS.md tests](../../../AGENTS.md#tests) | Repeated full local suites or local parallel/coverage benchmarks; assuming campaign/benchmark jobs already exist; weakening merge gates |
| Decision-reviewer calibration (paid OpenRouter `sorter_reviewer` runs) | `reviewer: {backend: decisions, model: openai/gpt-6-luna-decisions, questions: <stem>}` + `sandbox run preflight` → `sandbox run start --initials XX` → `scripts/calibrate_reviewer.py --run <id>` | `config/decisions/*.yaml`, `reports/reviewer-calibration/` | The chat model `openai/gpt-6-luna` as the reviewer; hand-picked cutoffs; `-latest` / `~` model ids |
| Sandbox-isolated tasks / governance | Local **`SAND-*`** board (`governance/TASKS.md`) | (this router + `governance/PREFIX.md`) | Family **`DMR-*`** MESSAGE_BOARD (cross-repo only) |

## Observability precedence (`OBSERVABILITY_PROVIDER`)

Canonical default in `.env`: **`langfuse`**.

When `auto`:

1. Langfuse if `LANGFUSE_SECRET_KEY` is set  
2. else Braintrust if `BRAINTRUST_API_KEY` is set  
3. else Phoenix if `PHOENIX_TRACING` ≠ `disabled`  
4. else `none`

Sandbox evals implement the Langfuse v4 `document-pipeline` contract in `mailroom_sandbox.eval.tracing`. Phoenix/Braintrust are alternate sinks — they do **not** replace that family schema for The-Mailroom.

## Serving precedence

1. **`--mock` / offline prep** — no live LLM  
2. **Modal vLLM** — the default (`modal-vllm`): remote GPU; `pip install -e ".[deploy]"` + `sandbox runbook show serve` (see [modal](../modal/SKILL.md))
3. **Ollama** — offline/CPU fallback (`--profile ollama`; `sandbox up -d --compose-profile ollama`, `sandbox pull-models --profile ollama`)
4. **vLLM local** — NVIDIA host + compose profile `vllm`  
5. **llama.cpp / LM Studio** — generic OpenAI base URL profiles  
6. **OpenRouter** — opt-in only (`OPENROUTER_API_KEY`); never the sandbox default  

Always `mailroom_sandbox.runtime.activate(profile)` before importing mailroom graph/agents. Rewrite models via overlay / `--agent-model`; do not hardcode OpenRouter ids into Ollama.

## Dataset and floor protocol

- Read the pins in `src/mailroom_sandbox/job/spec.py` and the selected run lock.
  `FAMILY_HF_REVISION` is the default pull, not a claim about Hub HEAD or every
  experiment. Preserve a run's explicit revision; do not silently update it.
- A registry name resolves fields; it is provenance, not a content identifier.
  Verify the prepared `dataset.jsonl` against `spec.lock.json`'s `dataset.sha256`.
  For local sources, `dataset.metadata.sha256` identifies the source bytes;
  `metadata.name` and `metadata.pull` exist only when supplied. See
  [Hugging Face guidance](../huggingface/SKILL.md#dataset-identity-and-run-locks).
- A `limit` selects after normalization, filtering and canonical sorting. A
  shuffle of input lines alone does not define execution order. Inspect locked
  row IDs and selection settings before claiming which documents were used.
- `sandbox floor` serves the digest on `127.0.0.1:8769`. With no runs and no
  selected target it starts the bundled replay; `--replay` requests that sample
  alongside history. Use a scratch `--base` for disposable demos. Replay writes
  a labeled run into that base and uses simulated results, never inference.
  A foreign or symlinked replay directory is refused; do not delete it to bypass
  the ownership check. See [sample provenance](../../../data/fixtures/floor/replay/README.md).

## Gotchas

- **Keep CPU-heavy verification in CI.** Use one worker and no coverage for
  narrow local reproductions. Inspect hosted logs, JUnit, coverage and timing
  artifacts instead of rerunning the full suite locally. Merge only after the
  required checks pass on the current head; see [test policy](../../../AGENTS.md#tests).
- **The decision reviewer is a Decisions-API model, not a chat model.** `openai/gpt-6-luna-decisions` is served at `POST https://openrouter.ai/api/alpha/decisions` (no chat route): it takes `state` plus typed `questions` and returns a probability for every option, with no output tokens. `openai/gpt-6-luna` is the plain chat model. On 2026-11-01 a whole calibration ran on the chat model by mistake (about $2.50). Preflight now refuses a paid `sorter_reviewer` run without a `reviewer:` block, and `backend: api` (chat) needs `allow_chat_model: true`. Before a paid reviewer run, confirm the model id in the lock ends in `-decisions`.
- **Spend initials belong to the operator.** `sandbox run start` on a paid run needs `--initials` (2–6 capital letters). An agent asks for them and never signs on its own.
- **Price check before a paid OpenRouter run.** The cost comes from `SANDBOX_MODEL_PRICES` (`src/mailroom_sandbox/job/metrics.py`) and the live model endpoints list (`https://openrouter.ai/api/v1/models/<id>/endpoints`; Decisions models are missing from the plain `/models` list). Luna Decisions bills input only ($0.10/M); the document is billed once per request however many questions it carries.
- **Full `task: pipeline` runs are slow on long documents.** A contract or merger takes minutes, since the specialist reads it in chunks. A shell or tool timeout kills the process, not the run: the checkpoint stays `running`, and `sandbox run resume --config <file> --initials XX` continues from the cursor.
- **A reviewer run is fast.** On the Decisions model (`openai/gpt-6-luna-decisions`) a document takes p50 0.5 s and p95 0.9 s at concurrency 16 (`reviewer-calibration-luna-decisions.md`). The 735 documents in 100 s figure was the superseded chat-model run (`openai/gpt-6-luna`, 2026-11-01).
- **A calibration only fixes thresholds, not taxonomy confusion.** Confidently wrong answers (≥0.94) at a class boundary need a prompt or catalog fix, not a cutoff. Check `top_confidence_wrong` and the confusion matrix before trusting a cutoff.

## Repo anchors

| Concern | Path |
| --- | --- |
| Profiles | `config/profiles/*.yaml` |
| Env template | `config/.env.example` |
| Compose + Dockerfile | `deploy/docker-compose.yml`, `deploy/Dockerfile` |
| Modal app | `deploy/modal_vllm.py` |
| Tracing | `docs/tracing.md`, `src/mailroom_sandbox/eval/tracing.py` |
| Providers | `docs/setting-up/providers.md` |
| Offline Docker + notebooks | `docs/setting-up/docker-offline.md` |
| Project skills (this tree) | `.cursor/skills/*/SKILL.md` |
| Dataset registry / run locks | `config/datasets.yaml` / `docs/datasets/named-datasets.md` / `docs/jobs.md` |
| Floor operation / sample / verification | `docs/floor.md` / `data/fixtures/floor/replay/README.md` / `tests/test_floor_app.py` |
| CI scheduling / caches / runtime evidence | `.circleci/README.md` |

## Quick commands

```bash
sandbox profiles
sandbox cutover --profile ollama
sandbox up -d                                       # langfuse only (default modal-vllm); select both profiles for Ollama + Langfuse
sandbox up -d --compose-profile phoenix             # optional sidecar
sandbox health
sandbox doctor                                      # offline status of modal/hf/docker/ollama/ssh/git/vllm…; --live probes, --publish feeds the board strip
sandbox datasets prepare                            # offline
sandbox datasets pull                               # Hub (network)
```
