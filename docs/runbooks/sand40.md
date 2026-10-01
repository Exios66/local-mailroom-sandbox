<!-- Generated from config/runbooks/catalog.yaml. Edit the catalog, then: sandbox runbook write -->

# SAND-40 launcher — 32K short phase, redeploy, 64K long phase

**id:** `sand40` · **family:** `grid` · **serving:** `grid-awq-2l4`

Operator launcher for the SAND-40 scale run. Activates the Hermes Modal profile, deploys the 32K 2×L4 engine and runs the three short classes at n=100, then redeploys with YaRN at 65536 and runs contracts n=100 and merger n=50. The validation probe is sand40-probe and is not part of this script.

Edit [`config/runbooks/catalog.yaml`](../../config/runbooks/catalog.yaml), then `sandbox runbook write`. Print this card: `sandbox runbook show sand40`.

## Phases

The launcher redeploys (`modal deploy --strategy recreate`) between phases. One process cannot serve both context windows.

### short (`grid-awq-2l4`)

- `config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-insurance-claims-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-corporate-records-specialist-awq-2l4.yaml`

| Knob | Value |
| --- | --- |
| Model | `Qwen/Qwen3-8B-AWQ` |
| GPU | `L4` |
| Image | `v0.29.0` |
| max_model_len | `32768` |
| max_num_seqs | `16` |
| max_containers | `2` |
| min_containers | `2` |
| scaledown_seconds | `120` |
| quantization | `awq_marlin` |
| prefix caching / eager | `1 / 0` |

### long (`grid-awq-2l4-64k`)

- `config/runs/sand40-100-contracts-specialist-awq-2l4-64k.yaml`
- `config/runs/sand40-50-merger-specialist-awq-2l4-64k.yaml`

| Knob | Value |
| --- | --- |
| Model | `Qwen/Qwen3-8B-AWQ` |
| GPU | `L4` |
| Image | `v0.29.0` |
| max_model_len | `65536` |
| max_num_seqs | `16` |
| max_containers | `2` |
| min_containers | `2` |
| scaledown_seconds | `120` |
| quantization | `awq_marlin` |
| prefix caching / eager | `1 / 0` |

## Per-cell posture (live)

| Run | Task | Conc. | max_tokens | max_input_chars | cost_cap | max_wall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `sand40-100-correspondence-specialist-awq-2l4` | `correspondence_specialist` | 32 | 8192 | 12000 | $1.00 | 3600s |
| `sand40-100-insurance-claims-specialist-awq-2l4` | `insurance_claims_specialist` | 32 | 8192 | 13500 | $1.20 | 3600s |
| `sand40-100-corporate-records-specialist-awq-2l4` | `corporate_records_specialist` | 32 | 8192 | 15000 | $1.20 | 3600s |
| `sand40-100-contracts-specialist-awq-2l4-64k` | `contracts_specialist` | 32 | 6144 | 128000 | $2.40 | 6000s |
| `sand40-50-merger-specialist-awq-2l4-64k` | `merger_agreement_specialist` | 32 | 6144 | 128000 | $2.50 | 7200s |

Source: `src/mailroom_sandbox/job/specialist_posture.py`.

## Notes

- The phases step exports each serving variant, runs modal deploy --strategy recreate, cutover, and health, then the phase configs. Do not skip the second deploy.
- Probe (sand40-probe) is a separate spend gate of about $0.30–$0.80. Run it before this launcher once spend is approved.
- Sampling settings reach the vLLM endpoint as ordinary chat-completion fields (top_p, presence_penalty, extra_body.top_k). This deploy does not use LangChain.

## Do not

- Share one Modal token / ~/.modal.toml profile across operators
- Tear down or modal deploy --strategy recreate between classes on one track
- Set MODAL_VLLM_GPU=L4:2 + TP for Qwen3-8B (use MAX_CONTAINERS=2 instead)
- Edit run-30-*-specialist.yaml for a one-off model swap

## Operator script

```bash
# SAND-40 launcher — 32K short phase, redeploy, 64K long phase
# sandbox runbook show sand40
set -euo pipefail

modal profile activate "${SANDBOX_MODAL_PROFILE_TRACK_A:-hermes-agent-jjb}"
modal profile current

modal run deploy/modal_vllm.py::download_model

# phase: short — redeploy serving variant grid-awq-2l4
# serving variant: grid-awq-2l4
# runbook: sand40:short
export SANDBOX_PROFILE=modal-vllm
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B-AWQ
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_IMAGE_TAG=v0.29.0
export MODAL_VLLM_MAX_MODEL_LEN=32768
export MODAL_VLLM_MAX_NUM_SEQS=16
export MODAL_VLLM_GPU_MEMORY_UTILIZATION=0.90
export MODAL_VLLM_ENABLE_PREFIX_CACHING=1
export MODAL_VLLM_ENFORCE_EAGER=0
export MODAL_VLLM_MAX_CONTAINERS=2
export MODAL_VLLM_MIN_CONTAINERS=2
export MODAL_VLLM_SCALEDOWN_SECONDS=120
export MODAL_VLLM_QUANTIZATION=awq_marlin
export MODAL_VLLM_TP_SIZE=1
export MODAL_VLLM_KV_CACHE_DTYPE=fp8
export MODAL_VLLM_CUDAGRAPH_CAPTURE_SIZES='1,2,4,8,16'
export MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
export MODAL_VLLM_MAX_INPUTS=32
export PHOENIX_TRACING=disabled
export MODAL_VLLM_API_TOKEN="${MODAL_VLLM_API_TOKEN:-$(openssl rand -hex 24)}"

sandbox run benchmark-check --config config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml

modal deploy deploy/modal_vllm.py --strategy recreate

# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml \
  config/runs/sand40-100-insurance-claims-specialist-awq-2l4.yaml \
  config/runs/sand40-100-corporate-records-specialist-awq-2l4.yaml
do
  sandbox run preflight --config "$cfg" --live --force
  sandbox run scrape-metrics --config "$cfg" --label before
  sandbox run start --config "$cfg" --job-mode endpoint --watch
  sandbox run scrape-metrics --config "$cfg" --label after
  sandbox run card --config "$cfg"
done

# phase: long — redeploy serving variant grid-awq-2l4-64k
# serving variant: grid-awq-2l4-64k
# runbook: sand40:long
export SANDBOX_PROFILE=modal-vllm
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B-AWQ
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_IMAGE_TAG=v0.29.0
export MODAL_VLLM_MAX_MODEL_LEN=65536
export MODAL_VLLM_MAX_NUM_SEQS=16
export MODAL_VLLM_GPU_MEMORY_UTILIZATION=0.90
export MODAL_VLLM_ENABLE_PREFIX_CACHING=1
export MODAL_VLLM_ENFORCE_EAGER=0
export MODAL_VLLM_MAX_CONTAINERS=2
export MODAL_VLLM_MIN_CONTAINERS=2
export MODAL_VLLM_SCALEDOWN_SECONDS=120
export MODAL_VLLM_QUANTIZATION=awq_marlin
export MODAL_VLLM_TP_SIZE=1
export MODAL_VLLM_KV_CACHE_DTYPE=fp8
export MODAL_VLLM_CUDAGRAPH_CAPTURE_SIZES='1,2,4,8,16'
export MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
export MODAL_VLLM_MAX_INPUTS=32
export MODAL_VLLM_HF_OVERRIDES='{"rope_parameters": {"factor": 2.0, "original_max_position_embeddings": 32768, "rope_theta": 1000000, "rope_type": "yarn"}}'
export PHOENIX_TRACING=disabled
export MODAL_VLLM_API_TOKEN="${MODAL_VLLM_API_TOKEN:-$(openssl rand -hex 24)}"

sandbox run benchmark-check --config config/runs/sand40-100-contracts-specialist-awq-2l4-64k.yaml

modal deploy deploy/modal_vllm.py --strategy recreate

# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/sand40-100-contracts-specialist-awq-2l4-64k.yaml \
  config/runs/sand40-50-merger-specialist-awq-2l4-64k.yaml
do
  sandbox run preflight --config "$cfg" --live --force
  sandbox run scrape-metrics --config "$cfg" --label before
  sandbox run start --config "$cfg" --job-mode endpoint --watch
  sandbox run scrape-metrics --config "$cfg" --label after
  sandbox run card --config "$cfg"
done

./deploy/teardown_vllm.sh   # ONLY after this run

sandbox run card --master
```
