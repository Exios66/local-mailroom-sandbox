<!-- Generated from config/runbooks/catalog.yaml. Edit the catalog, then: sandbox runbook write -->

# SAND-40 long phase — contracts n=100 and merger n=50 · 64K YaRN

**id:** `sand40-long` · **family:** `grid` · **serving:** `grid-awq-2l4-64k`

Second serving phase of SAND-40. Redeploy onto the 64K YaRN window, then run contracts (n=100, containing the SAND-37 n=50) and merger (the same 50 agreements as grid-50-merger-specialist-awq-2l4) with the optimized long-document settings.

Edit [`config/runbooks/catalog.yaml`](../../config/runbooks/catalog.yaml), then `sandbox runbook write`. Print this card: `sandbox runbook show sand40-long`.

## Pins (from catalog serving variant)

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

## Configs

- `config/runs/sand40-100-contracts-specialist-awq-2l4-64k.yaml`
- `config/runs/sand40-50-merger-specialist-awq-2l4-64k.yaml`

## Per-cell posture (live)

| Run | Task | Conc. | max_tokens | max_input_chars | cost_cap | max_wall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `sand40-100-contracts-specialist-awq-2l4-64k` | `contracts_specialist` | 32 | 6144 | 128000 | $2.40 | 6000s |
| `sand40-50-merger-specialist-awq-2l4-64k` | `merger_agreement_specialist` | 32 | 6144 | 128000 | $2.50 | 7200s |

Source: `src/mailroom_sandbox/job/specialist_posture.py`.

## Notes

- Deploy with --strategy recreate after the 32K phase. MODAL_VLLM_MAX_MODEL_LEN=65536 and MODAL_VLLM_HF_OVERRIDES carry the YaRN rope parameters.
- Merger is the † cell: Qwen3 sampling, chunked extraction, 6144 cap, one length re-sample, MAUD v1 prompt. Sampling is posted as chat-completion fields on the native OpenAI client. The Modal app does not import LangChain.
- Cards land under reports/SAND-37/2L4/contracts/ and reports/SAND-37/2L4/merger_agreement/.

## Do not

- Share one Modal token / ~/.modal.toml profile across operators
- Tear down or modal deploy --strategy recreate between classes on one track
- Set MODAL_VLLM_GPU=L4:2 + TP for Qwen3-8B (use MAX_CONTAINERS=2 instead)
- Edit run-30-*-specialist.yaml for a one-off model swap

## Operator script

```bash
# SAND-40 long phase — contracts n=100 and merger n=50 · 64K YaRN
# sandbox runbook show sand40-long
set -euo pipefail

# serving variant: grid-awq-2l4-64k
# runbook: sand40-long
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

modal profile activate "${SANDBOX_MODAL_PROFILE_TRACK_A:-hermes-agent-jjb}"
modal profile current

sandbox run benchmark-check --config config/runs/sand40-100-contracts-specialist-awq-2l4-64k.yaml

modal run deploy/modal_vllm.py::download_model

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
