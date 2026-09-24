# Modal L4 Qwen benchmark kit (specialist 5×30)

Reproducible, stable Modal+vLLM **L4** runs of **Qwen/Qwen3-8B** for
specialist extract cost extrapolation to the full mailroom-dataset
(`FAMILY_CORPUS_SIZE=3302` at `FAMILY_HF_REVISION`).

## Pins (do not drift)

| Knob | Value |
| --- | --- |
| Model | `Qwen/Qwen3-8B` (bf16; AWQ only if you swap the whole suite) |
| GPU | `L4` (`max_containers=1`, `min_containers=0`) |
| Image | `v0.29.0` |
| `max_model_len` | `16384` |
| Job concurrency | `4` (DMR-072) |
| Scaledown | `600` s |
| Dataset | `Lucius-Morningstar/mailroom-dataset` @ `46a4d3c240a36671cde0182fff4960f6b8b73aca` |
| `sample_seed` | `42` |
| Modal account | Hermes Agent Gmail profile **`hermes-agent-jjb`** |

Run YAMLs: `config/runs/run-30-*-specialist.yaml` (150 docs total).

## Hermes Modal account

```bash
modal profile activate hermes-agent-jjb
modal profile current   # must print hermes-agent-jjb
# Tokens live only in ~/.modal.toml — never commit MODAL_TOKEN_* values.
```

## Loud gate

```bash
sandbox run benchmark-check --config config/runs/run-30-contracts-specialist.yaml
# exits 1 if wrong Modal profile / unpinned image / concurrency≠4 / revision drift
```

## Deploy → suite → teardown → extrapolate

```bash
export SANDBOX_PROFILE=modal-vllm
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_IMAGE_TAG=v0.29.0
export MODAL_VLLM_MAX_CONTAINERS=1
export MODAL_VLLM_SCALEDOWN_SECONDS=600
export MODAL_VLLM_API_TOKEN="$(openssl rand -hex 24)"

modal run deploy/modal_vllm.py::download_model
modal deploy deploy/modal_vllm.py
# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/run-30-contracts-specialist.yaml \
  config/runs/run-30-merger-specialist.yaml \
  config/runs/run-30-corporate-records-specialist.yaml \
  config/runs/run-30-correspondence-specialist.yaml \
  config/runs/run-30-insurance-claims-specialist.yaml
do
  sandbox run preflight --config "$cfg" --live
  sandbox run start --config "$cfg" --job-mode endpoint --watch
done

./deploy/teardown_vllm.sh

# Per-run cost → full corpus (3302) + industry scale
sandbox metrics extrapolate --run run-30-contracts-specialist --corpus-size 3302 --docs-per-day 10000
sandbox metrics compare --runs run-30-contracts-specialist,run-30-merger-specialist,run-30-corporate-records-specialist,run-30-correspondence-specialist,run-30-insurance-claims-specialist

# Optional: after a live sorter run, compare vs local ModernBERT
# export MAILROOM_ML_SRC=…/mailroom-ml
# export MODERNBERT_MODEL_PATH=$MAILROOM_ML_SRC/artifacts/run2-published
sandbox modernbert status
sandbox modernbert eval --sample 50 --json
```

## Cost honesty

- Prefer `MODAL_BILLED_GPU_SECONDS=<suite wall>` after the five runs for GPU $.
- Token $ needs OpenAI-compatible `usage` on items — missing tokens → fields
  omitted (never silent `$0`); extrapolate refuses if both token and GPU $/doc
  are absent.
- Linear extrapolation = `combined_$/doc × N`. `with_overhead` adds one
  cold-start + one scaledown window. Confidence notes always print.

## Merger note

`run-30-merger-specialist` uses **train** split (test has only ~17 merger
rows). Document that in any published scorecard.

## Specialist prompts (pinned local)

Each run-30 YAML pins the task agent's production text under
`config/prompts/` (not Langfuse floating `production`):

| Run | Agent | Local stem | Source |
| --- | --- | --- | --- |
| contracts / merger | `contracts_specialist` | `contracts_specialist_v33` | vendored `PROMPT_VERSIONS` (mailroom production) |
| corporate-records | `corporate_records_specialist` | `corporate_records_specialist_production` | vendored `SYSTEM_PROMPT` + doctrine |
| correspondence | `correspondence_specialist` | `correspondence_specialist_production` | vendored `SYSTEM_PROMPT` + doctrine |
| insurance-claims | `insurance_claims_specialist` | `insurance_claims_specialist_production` | vendored `SYSTEM_PROMPT` + doctrine |

Refresh: `python scripts/sync_specialist_prompts.py` (or `--check` after vendor sync).
Entity-extraction experimental `contracts_specialist_v34+` are **not** the
mailroom production pin — do not swap without an explicit scorecard decision.

## Advanced: swap model / GPU (not the default path)

Deploy knobs are entirely env-driven (`deploy/modal_vllm.py`). Catalog rows
live in `config/models.yaml` `modal_models:`. **Do not edit run-30 YAMLs**
for a one-off swap — those stay Qwen+L4 for the cost-eval suite.

```bash
sandbox modal-matrix list
sandbox modal-matrix show Qwen/Qwen3-8B-AWQ
eval "$(sandbox modal-matrix env Qwen/Qwen3-8B-AWQ)"          # L4 + AWQ + 32k
# eval "$(sandbox modal-matrix env Qwen/Qwen3-14B)"           # A100-40GB bf16
# eval "$(sandbox modal-matrix env Qwen/Qwen3-8B-FP8)"        # H100 FP8
# eval "$(sandbox modal-matrix env Qwen/Qwen3-8B --gpu A10G)" # GPU override
modal run deploy/modal_vllm.py::download_model
modal deploy deploy/modal_vllm.py --strategy recreate
# re-point VLLM_BASE_URL, then sandbox cutover/health --profile modal-vllm
```

Bare env (same effect):

```bash
export MODAL_VLLM_MODEL=Qwen/Qwen3-14B-AWQ
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_QUANTIZATION=awq
export MODAL_VLLM_MAX_MODEL_LEN=32768
export MODAL_VLLM_TP_SIZE=1
# multi-GPU: MODAL_VLLM_GPU=A100-80GB:2 MODAL_VLLM_TP_SIZE=2
```
