<!-- Generated from config/runbooks/catalog.yaml. Edit the catalog, then: sandbox runbook write -->

# Qwen3-8B-AWQ specialist grid (SAND-037)

Generated family rollup. Canonical per-id cards live beside this file.

# Specialist grid — 1×L4 · C8 cells (n=20 and n=50, all five classes)

**id:** `grid-1l4` · **family:** `grid` · **serving:** `grid-awq-1l4`

SAND-037. The ten 1×L4 cells of the Qwen3-8B-AWQ specialist grid (5 classes × n=20/50) on one warm L4: awq, eager, max_num_seqs 8, thinking off, max_inputs 8, decode 8192. Replaces the legacy run-20-*-awq(-c8) legs and the first merger cell; none of the n=50 cells has a clean result yet. Deploy once, run short classes first, teardown after the last cell.

Edit [`config/runbooks/catalog.yaml`](../../config/runbooks/catalog.yaml), then `sandbox runbook write`. Print this card: `sandbox runbook show grid-1l4`.

## Pins (from catalog serving variant)

| Knob | Value |
| --- | --- |
| Model | `Qwen/Qwen3-8B-AWQ` |
| GPU | `L4` |
| Image | `v0.29.0` |
| max_model_len | `32768` |
| max_num_seqs | `8` |
| max_containers | `1` |
| min_containers | `1` |
| scaledown_seconds | `120` |
| quantization | `awq` |
| prefix caching / eager | `1 / 1` |

## Configs

- `config/runs/grid-20-correspondence-specialist-awq-1l4.yaml`
- `config/runs/grid-20-insurance-claims-specialist-awq-1l4.yaml`
- `config/runs/grid-20-corporate-records-specialist-awq-1l4.yaml`
- `config/runs/grid-20-contracts-specialist-awq-1l4.yaml`
- `config/runs/grid-20-merger-specialist-awq-1l4-rerun.yaml`
- `config/runs/grid-50-correspondence-specialist-awq-1l4.yaml`
- `config/runs/grid-50-insurance-claims-specialist-awq-1l4.yaml`
- `config/runs/grid-50-corporate-records-specialist-awq-1l4.yaml`
- `config/runs/grid-50-contracts-specialist-awq-1l4.yaml`
- `config/runs/grid-50-merger-specialist-awq-1l4.yaml`

## Per-cell posture (live)

| Run | Task | Conc. | max_tokens | max_input_chars | cost_cap | max_wall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `grid-20-correspondence-specialist-awq-1l4` | `correspondence_specialist` | 8 | 8192 | 12000 | $0.30 | 2400s |
| `grid-20-insurance-claims-specialist-awq-1l4` | `insurance_claims_specialist` | 8 | 8192 | 13500 | $0.40 | 2400s |
| `grid-20-corporate-records-specialist-awq-1l4` | `corporate_records_specialist` | 8 | 8192 | 15000 | $0.40 | 2400s |
| `grid-20-contracts-specialist-awq-1l4` | `contracts_specialist` | 8 | 8192 | 24000 | $0.70 | 3600s |
| `grid-20-merger-specialist-awq-1l4-rerun` | `merger_agreement_specialist` | 8 | 8192 | 30000 | $0.70 | 3600s |
| `grid-50-correspondence-specialist-awq-1l4` | `correspondence_specialist` | 8 | 8192 | 12000 | $0.40 | 3600s |
| `grid-50-insurance-claims-specialist-awq-1l4` | `insurance_claims_specialist` | 8 | 8192 | 13500 | $0.50 | 3600s |
| `grid-50-corporate-records-specialist-awq-1l4` | `corporate_records_specialist` | 8 | 8192 | 15000 | $0.50 | 3600s |
| `grid-50-contracts-specialist-awq-1l4` | `contracts_specialist` | 8 | 8192 | 24000 | $0.80 | 4800s |
| `grid-50-merger-specialist-awq-1l4` | `merger_agreement_specialist` | 8 | 8192 | 30000 | $1.00 | 5400s |

Source: `src/mailroom_sandbox/job/specialist_posture.py`.

## Notes

- Spend: likely ≈ $3 GPU at $0.80/hr (≈ 3.6 h warm, from the legacy 1×L4 C8 walls scaled to n=50); the ten cost caps sum to $5.70 and are the abort guard. Needs spend approval before deploy.
- Canonical deploy knobs: set -a; eval "$(sandbox run deploy-env --config config/runs/grid-20-correspondence-specialist-awq-1l4.yaml)"; set +a. The export block below is identical; benchmark-check reports any shell drift.
- MODAL_VLLM_MAX_INPUTS must be 8, never 0: at 0 the Modal web server takes one request at a time (contracts-50 ran at Running:1, ~22 tok/s).
- preflight --force archives any earlier generation of the same run_id (the serialized grid-50-contracts-specialist-awq-1l4 attempt, locked on the pre-SAND-037 spec) and re-locks; start then resumes the fresh lock.
- Decode 8192 comes from the specialist_posture grid row via SANDBOX_AGENT_KNOBS at start; do not export SANDBOX_AGENT_KNOBS by hand.
- Leave grid-20-merger-specialist-awq-1l4 and its -retry leg untouched: the -rerun cell has its own run_id so both committed reports survive.
- Full cell status (keep / run / rerun) and the superseded records: docs/SPECIALIST-GRID-PLAN.md.

## Do not

- Share one Modal token / ~/.modal.toml profile across operators
- Tear down or modal deploy --strategy recreate between classes on one track
- Set MODAL_VLLM_GPU=L4:2 + TP for Qwen3-8B (use MAX_CONTAINERS=2 instead)
- Edit run-30-*-specialist.yaml for a one-off model swap

## Operator script

```bash
# Specialist grid — 1×L4 · C8 cells (n=20 and n=50, all five classes)
# sandbox runbook show grid-1l4
set -euo pipefail

# serving variant: grid-awq-1l4
# runbook: grid-1l4
export SANDBOX_PROFILE=modal-vllm
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B-AWQ
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_IMAGE_TAG=v0.29.0
export MODAL_VLLM_MAX_MODEL_LEN=32768
export MODAL_VLLM_MAX_NUM_SEQS=8
export MODAL_VLLM_GPU_MEMORY_UTILIZATION=0.90
export MODAL_VLLM_ENABLE_PREFIX_CACHING=1
export MODAL_VLLM_ENFORCE_EAGER=1
export MODAL_VLLM_MAX_CONTAINERS=1
export MODAL_VLLM_MIN_CONTAINERS=1
export MODAL_VLLM_SCALEDOWN_SECONDS=120
export MODAL_VLLM_QUANTIZATION=awq
export MODAL_VLLM_TP_SIZE=1
export MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
export MODAL_VLLM_MAX_INPUTS=8
export PHOENIX_TRACING=disabled
export MODAL_VLLM_API_TOKEN="${MODAL_VLLM_API_TOKEN:-$(openssl rand -hex 24)}"

modal profile activate "${SANDBOX_MODAL_PROFILE_TRACK_A:-hermes-agent-jjb}"
modal profile current

sandbox run benchmark-check --config config/runs/grid-20-correspondence-specialist-awq-1l4.yaml

modal run deploy/modal_vllm.py::download_model

modal deploy deploy/modal_vllm.py --strategy recreate

# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/grid-20-correspondence-specialist-awq-1l4.yaml \
  config/runs/grid-20-insurance-claims-specialist-awq-1l4.yaml \
  config/runs/grid-20-corporate-records-specialist-awq-1l4.yaml \
  config/runs/grid-20-contracts-specialist-awq-1l4.yaml \
  config/runs/grid-20-merger-specialist-awq-1l4-rerun.yaml \
  config/runs/grid-50-correspondence-specialist-awq-1l4.yaml \
  config/runs/grid-50-insurance-claims-specialist-awq-1l4.yaml \
  config/runs/grid-50-corporate-records-specialist-awq-1l4.yaml \
  config/runs/grid-50-contracts-specialist-awq-1l4.yaml \
  config/runs/grid-50-merger-specialist-awq-1l4.yaml
do
  sandbox run preflight --config "$cfg" --live --force
  sandbox run start --config "$cfg" --job-mode endpoint --watch
done

./deploy/teardown_vllm.sh   # ONLY after this run

sandbox metrics compare --runs grid-20-correspondence-specialist-awq-1l4,grid-20-insurance-claims-specialist-awq-1l4,grid-20-corporate-records-specialist-awq-1l4,grid-20-contracts-specialist-awq-1l4,grid-20-merger-specialist-awq-1l4-rerun
sandbox metrics compare --runs grid-50-correspondence-specialist-awq-1l4,grid-50-insurance-claims-specialist-awq-1l4,grid-50-corporate-records-specialist-awq-1l4,grid-50-contracts-specialist-awq-1l4,grid-50-merger-specialist-awq-1l4
```

---

# Specialist grid — 2×L4 · C32 cells (n=20 and n=50, all five classes)

**id:** `grid-2l4` · **family:** `grid` · **serving:** `grid-awq-2l4`

SAND-037. The nine outstanding 2×L4 cells of the Qwen3-8B-AWQ specialist grid on one warm two-replica fleet: awq, CUDA graphs, fp8 KV, max_num_seqs 16 per replica, max_inputs 32, thinking off, decode 8192. Supersedes the SAND-032 S3 n=50 legs (production correspondence prompt, pre-grid decode) as grid cells. grid-50-contracts-specialist-awq-2l4 already ran clean and is kept.

Edit [`config/runbooks/catalog.yaml`](../../config/runbooks/catalog.yaml), then `sandbox runbook write`. Print this card: `sandbox runbook show grid-2l4`.

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
| quantization | `awq` |
| prefix caching / eager | `1 / 0` |

## Configs

- `config/runs/grid-20-correspondence-specialist-awq-2l4.yaml`
- `config/runs/grid-20-insurance-claims-specialist-awq-2l4.yaml`
- `config/runs/grid-20-corporate-records-specialist-awq-2l4.yaml`
- `config/runs/grid-20-contracts-specialist-awq-2l4.yaml`
- `config/runs/grid-20-merger-specialist-awq-2l4.yaml`
- `config/runs/grid-50-correspondence-specialist-awq-2l4.yaml`
- `config/runs/grid-50-insurance-claims-specialist-awq-2l4.yaml`
- `config/runs/grid-50-corporate-records-specialist-awq-2l4.yaml`
- `config/runs/grid-50-merger-specialist-awq-2l4.yaml`

## Per-cell posture (live)

| Run | Task | Conc. | max_tokens | max_input_chars | cost_cap | max_wall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `grid-20-correspondence-specialist-awq-2l4` | `correspondence_specialist` | 32 | 8192 | 12000 | $0.40 | 2400s |
| `grid-20-insurance-claims-specialist-awq-2l4` | `insurance_claims_specialist` | 32 | 8192 | 13500 | $0.50 | 2400s |
| `grid-20-corporate-records-specialist-awq-2l4` | `corporate_records_specialist` | 32 | 8192 | 15000 | $0.50 | 2400s |
| `grid-20-contracts-specialist-awq-2l4` | `contracts_specialist` | 32 | 8192 | 24000 | $0.80 | 3200s |
| `grid-20-merger-specialist-awq-2l4` | `merger_agreement_specialist` | 32 | 8192 | 30000 | $1.00 | 3600s |
| `grid-50-correspondence-specialist-awq-2l4` | `correspondence_specialist` | 32 | 8192 | 12000 | $0.60 | 2400s |
| `grid-50-insurance-claims-specialist-awq-2l4` | `insurance_claims_specialist` | 32 | 8192 | 13500 | $0.80 | 2400s |
| `grid-50-corporate-records-specialist-awq-2l4` | `corporate_records_specialist` | 32 | 8192 | 15000 | $0.80 | 2400s |
| `grid-50-merger-specialist-awq-2l4` | `merger_agreement_specialist` | 32 | 8192 | 30000 | $1.60 | 4000s |

Source: `src/mailroom_sandbox/job/specialist_posture.py`.

## Notes

- Spend: likely ≈ $0.55 GPU at 2 × $0.80/hr (≈ 17 min warm plus one cold boot of ~2–4 min on each replica); the nine cost caps sum to $7.00 and are the abort guard. Needs spend approval before deploy.
- Canonical deploy knobs: set -a; eval "$(sandbox run deploy-env --config config/runs/grid-20-correspondence-specialist-awq-2l4.yaml)"; set +a. The export block below is identical.
- MIN=MAX=2 pins both replicas warm from deploy to teardown; per-replica admission is 16 at client concurrency 32.
- Do not rerun grid-50-contracts-specialist-awq-2l4 (48/50 ok, 2026-09-30 report). The merger and contracts cells may still end on LengthFinishReasonError at 8192; record the count, do not raise max_tokens mid-grid.
- Full cell status (keep / run / rerun) and the superseded records: docs/SPECIALIST-GRID-PLAN.md.

## Do not

- Share one Modal token / ~/.modal.toml profile across operators
- Tear down or modal deploy --strategy recreate between classes on one track
- Set MODAL_VLLM_GPU=L4:2 + TP for Qwen3-8B (use MAX_CONTAINERS=2 instead)
- Edit run-30-*-specialist.yaml for a one-off model swap

## Operator script

```bash
# Specialist grid — 2×L4 · C32 cells (n=20 and n=50, all five classes)
# sandbox runbook show grid-2l4
set -euo pipefail

# serving variant: grid-awq-2l4
# runbook: grid-2l4
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
export MODAL_VLLM_QUANTIZATION=awq
export MODAL_VLLM_TP_SIZE=1
export MODAL_VLLM_KV_CACHE_DTYPE=fp8
export MODAL_VLLM_CUDAGRAPH_CAPTURE_SIZES='1,2,4,8,16'
export MODAL_VLLM_DEFAULT_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
export MODAL_VLLM_MAX_INPUTS=32
export PHOENIX_TRACING=disabled
export MODAL_VLLM_API_TOKEN="${MODAL_VLLM_API_TOKEN:-$(openssl rand -hex 24)}"

modal profile activate "${SANDBOX_MODAL_PROFILE_TRACK_A:-hermes-agent-jjb}"
modal profile current

sandbox run benchmark-check --config config/runs/grid-20-correspondence-specialist-awq-2l4.yaml

modal run deploy/modal_vllm.py::download_model

modal deploy deploy/modal_vllm.py --strategy recreate

# set VLLM_BASE_URL from deploy output + VLLM_API_KEY=$MODAL_VLLM_API_TOKEN
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm

for cfg in \
  config/runs/grid-20-correspondence-specialist-awq-2l4.yaml \
  config/runs/grid-20-insurance-claims-specialist-awq-2l4.yaml \
  config/runs/grid-20-corporate-records-specialist-awq-2l4.yaml \
  config/runs/grid-20-contracts-specialist-awq-2l4.yaml \
  config/runs/grid-20-merger-specialist-awq-2l4.yaml \
  config/runs/grid-50-correspondence-specialist-awq-2l4.yaml \
  config/runs/grid-50-insurance-claims-specialist-awq-2l4.yaml \
  config/runs/grid-50-corporate-records-specialist-awq-2l4.yaml \
  config/runs/grid-50-merger-specialist-awq-2l4.yaml
do
  sandbox run preflight --config "$cfg" --live
  sandbox run start --config "$cfg" --job-mode endpoint --watch
done

./deploy/teardown_vllm.sh   # ONLY after this run

sandbox metrics compare --runs grid-20-correspondence-specialist-awq-2l4,grid-20-insurance-claims-specialist-awq-2l4,grid-20-corporate-records-specialist-awq-2l4,grid-20-contracts-specialist-awq-2l4,grid-20-merger-specialist-awq-2l4
sandbox metrics compare --runs grid-50-correspondence-specialist-awq-2l4,grid-50-insurance-claims-specialist-awq-2l4,grid-50-corporate-records-specialist-awq-2l4,grid-50-contracts-specialist-awq-2l4,grid-50-merger-specialist-awq-2l4
```

---
