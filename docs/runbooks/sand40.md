<!-- Generated from config/runbooks/catalog.yaml. Edit the catalog, then: sandbox runbook write -->

# SAND-40 scale run — five specialists · n=100 · 2×L4 · C32 · one 32K deploy

**id:** `sand40` · **family:** `grid` · **serving:** `grid-awq-2l4`

Fills the SAND-40 column of the master score & cost card. All five specialists at n=100 on the SAND-037 2×L4 engine (native 32768 window, aligned spec unchanged), one deploy, no redeploy. Each n=100 draw contains the n=50 documents scored by SAND-37 2×L4 and SAND-39.

Edit [`config/runbooks/catalog.yaml`](../../config/runbooks/catalog.yaml), then `sandbox runbook write`. Print this card: `sandbox runbook show sand40`.

## Pins (from catalog serving variant)

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

## Configs

- `config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-insurance-claims-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-corporate-records-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-contracts-specialist-awq-2l4.yaml`
- `config/runs/sand40-100-merger-specialist-awq-2l4.yaml`

## Per-cell posture (live)

| Run | Task | Conc. | max_tokens | max_input_chars | cost_cap | max_wall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `sand40-100-correspondence-specialist-awq-2l4` | `correspondence_specialist` | 32 | 8192 | 12000 | $1.00 | 3600s |
| `sand40-100-insurance-claims-specialist-awq-2l4` | `insurance_claims_specialist` | 32 | 8192 | 13500 | $1.20 | 3600s |
| `sand40-100-corporate-records-specialist-awq-2l4` | `corporate_records_specialist` | 32 | 8192 | 15000 | $1.20 | 3600s |
| `sand40-100-contracts-specialist-awq-2l4` | `contracts_specialist` | 32 | 8192 | 24000 | $1.20 | 3600s |
| `sand40-100-merger-specialist-awq-2l4` | `merger_agreement_specialist` | 32 | 8192 | 30000 | $1.20 | 3600s |

Source: `src/mailroom_sandbox/job/specialist_posture.py`.

## Notes

- Spend: likely ≈ $0.65 GPU at 2 × $0.80/GPU-hr (≈ 25 min busy: the SAND-37 2×L4 n=50 cells measured 724 s for 250 documents, doubled), plus one cold boot per replica. The five cost caps sum to $5.80 and are the abort guard. Needs spend approval before deploy.
- Settings are identical to the SAND-37 2×L4 n=50 cells except n: frozen v1 prompts, 8192 output cap, temperature 0.7 for contracts and merger (0.1 otherwise), head-plus-tail input caps. No 64K window, no chunking, no MAUD v1 prompt; those were validation-probe settings (sand40-probe) and stay out of the scale run.
- Cards land in reports/SAND-37/2L4/<specialist>/sand40-100-*.card.md + .card.json. The after step regenerates reports/SAND-37/SAND-37-MASTER-SCORE-COST-CARD.md; its SAND-40 column switches from pending to measured. Commit the SAND-37 tree.
- Record the teardown spend check (Metered Cost / Billed Cost) with sandbox run card --record-metered SAND-40 <metered> <billed> --master.
- Teardown follows the last cell. Do not leave the two-replica fleet warm: min_containers=2 bills both GPUs until teardown.

## Do not

- Share one Modal token / ~/.modal.toml profile across operators
- Tear down or modal deploy --strategy recreate between classes on one track
- Set MODAL_VLLM_GPU=L4:2 + TP for Qwen3-8B (use MAX_CONTAINERS=2 instead)
- Edit run-30-*-specialist.yaml for a one-off model swap

## Operator script

```bash
# SAND-40 scale run — five specialists · n=100 · 2×L4 · C32 · one 32K deploy
# sandbox runbook show sand40
set -euo pipefail

# serving variant: grid-awq-2l4
# runbook: sand40
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

modal profile activate "${SANDBOX_MODAL_PROFILE_TRACK_A:-hermes-agent-jjb}"
modal profile current

sandbox run benchmark-check --config config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml

modal run deploy/modal_vllm.py::download_model

modal deploy deploy/modal_vllm.py --strategy recreate

# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/sand40-100-correspondence-specialist-awq-2l4.yaml \
  config/runs/sand40-100-insurance-claims-specialist-awq-2l4.yaml \
  config/runs/sand40-100-corporate-records-specialist-awq-2l4.yaml \
  config/runs/sand40-100-contracts-specialist-awq-2l4.yaml \
  config/runs/sand40-100-merger-specialist-awq-2l4.yaml
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
