# Qwen3-8B-AWQ specialist grid: cell status and rerun plan (SAND-037)

The specialist grid in `src/mailroom_sandbox/job/specialist_posture.py` (`_GRID_TABLE`) crosses
three factors:

| Factor | Levels |
| --- | --- |
| Document class | correspondence, insurance claims, corporate records, contracts, merger agreements |
| Sample size | n = 20, n = 50 |
| Fleet shape | 1×L4 · C8 (one replica) and 2×L4 · C32 (two replicas, 16 per replica) |

That is 20 cells. This page records which cells already have a result that fits the grid and which must
be run or rerun. The operator steps are the two catalog runbooks:

```bash
sandbox runbook show grid-1l4   # the ten 1×L4 cells, one warm L4
sandbox runbook show grid-2l4   # the nine outstanding 2×L4 cells, one warm 2-replica fleet
```

## What every cell holds fixed

| Condition | Value |
| --- | --- |
| Model / engine | `Qwen/Qwen3-8B-AWQ`, vLLM `v0.29.0`, `max_model_len` 32768, `gpu_memory_utilization` 0.90, prefix caching on |
| Quantization | `awq` |
| Thinking | off (`enable_thinking: false`) |
| Decode budget | 8192 completion tokens, applied at `sandbox run start` from the grid posture row |
| Prompts | `*_simplified` stems (contracts: `contracts_specialist_v33_simplified`) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` `ground_truth` @ `ed7576b6`, seed 42 |
| Modal app | `sandbox-vllm`, `min_containers` = `max_containers` (warm from deploy to teardown) |

The two fleet shapes differ in more than GPU count, as the grid YAMLs lay them out:

| Knob | 1×L4 · C8 | 2×L4 · C32 |
| --- | --- | --- |
| `max_num_seqs` per replica | 8 | 16 |
| CUDA graphs | off (`enforce_eager: true`) | on, capture sizes 1–16 |
| KV cache dtype | auto | fp8 |
| `max_inputs` | 8 | 32 |

Read the 1×L4 vs 2×L4 contrast as a comparison of two serving postures, not of GPU count alone. The
controlled GPU-count test is SAND-032 S2a vs S2b (same 100 correspondence documents, same engine,
1×L4 C8 vs 2×L4 C16).

## Cell status

**Keep** means the existing result fits the grid. **Rerun** means a result exists but breaks one of the
fixed conditions above. **Run** means the cell has never produced a result.

### n = 20

| Class | 1×L4 · C8 | 2×L4 · C32 |
| --- | --- | --- |
| Correspondence | **Rerun** → `grid-20-correspondence-specialist-awq-1l4` (new) | **Rerun** → `grid-20-correspondence-specialist-awq-2l4` (new) |
| Insurance claims | **Rerun** → `grid-20-insurance-claims-specialist-awq-1l4` (new) | **Run** → `grid-20-insurance-claims-specialist-awq-2l4` |
| Corporate records | **Rerun** → `grid-20-corporate-records-specialist-awq-1l4` (new) | **Run** → `grid-20-corporate-records-specialist-awq-2l4` |
| Contracts | **Rerun** → `grid-20-contracts-specialist-awq-1l4` (new) | **Run** → `grid-20-contracts-specialist-awq-2l4` |
| Merger agreements | **Rerun** → `grid-20-merger-specialist-awq-1l4-rerun` (new) | **Run** → `grid-20-merger-specialist-awq-2l4` |

### n = 50

| Class | 1×L4 · C8 | 2×L4 · C32 |
| --- | --- | --- |
| Correspondence | **Run** → `grid-50-correspondence-specialist-awq-1l4` | **Rerun** → `grid-50-correspondence-specialist-awq-2l4` |
| Insurance claims | **Run** → `grid-50-insurance-claims-specialist-awq-1l4` | **Rerun** → `grid-50-insurance-claims-specialist-awq-2l4` |
| Corporate records | **Run** → `grid-50-corporate-records-specialist-awq-1l4` | **Rerun** → `grid-50-corporate-records-specialist-awq-2l4` |
| Contracts | **Rerun** → `grid-50-contracts-specialist-awq-1l4` | **Keep** `grid-50-contracts-specialist-awq-2l4` (48/50 ok, 2026-09-30) |
| Merger agreements | **Run** → `grid-50-merger-specialist-awq-1l4` | **Rerun** → `grid-50-merger-specialist-awq-2l4` |

Totals: 1 keep, 11 reruns, 8 first runs.

## Why each existing record is superseded

| Existing record | Grid cell | What breaks the grid |
| --- | --- | --- |
| `run-20-correspondence-awq-c8` | correspondence · 20 · 1×L4 | Ran before `6dbf457`, so the pinned prompt was not sent; dataset rev `46a4d3c2`; `max_num_seqs` 256; decode 2048. |
| `run-20-contracts-awq-c8` | contracts · 20 · 1×L4 | Same unapplied prompt pin and `46a4d3c2` draw; `max_num_seqs` 256; 3 LengthFinish errors. |
| `run-20-insurance-claims-specialist-awq` | insurance · 20 · 1×L4 | Dataset rev `46a4d3c2` (a different draw from its 2×L4 sibling); `max_num_seqs` 6; decode 3072. |
| `run-20-corporate-records-specialist-awq` | corporate · 20 · 1×L4 | Dataset rev `46a4d3c2`; decode 4096; no serving export and no per-document rows in its report. |
| `grid-20-merger-specialist-awq-1l4` | merger · 20 · 1×L4 | Decode 4096 (1 LengthFinish) and thinking unset. Its `-retry` leg changed decode to 16384 and `max_retries` to 1, so neither leg is the grid posture. Both reports stay; the new `-rerun` id avoids overwriting them. |
| `run-20-correspondence-specialist-awq` | correspondence · 20 · 2×L4 | 2×L4 at C8 with `max_num_seqs` 6 and the `_production` prompt; the grid had no n = 20 2×L4 correspondence cell until now. |
| `grid-50-contracts-specialist-awq-1l4` (attempt) | contracts · 50 · 1×L4 | Deployed with `MODAL_VLLM_MAX_INPUTS=0`: the Modal web server took one request at a time (Running:1, ~22 tok/s). No result. |
| `sand032-s3-corr50` | correspondence · 50 · 2×L4 | `_production` prompt; decode 2048; `awq_marlin`; dedicated `sandbox-vllm-sand032` app. |
| `sand032-s3-insurance50` | insurance · 50 · 2×L4 | Decode 3072; `awq_marlin`. |
| `sand032-s3-corporate50` | corporate · 50 · 2×L4 | Decode 4096; `awq_marlin`. |
| `sand032-s3-merger50` | merger · 50 · 2×L4 | Decode 4096 (6 LengthFinish); `awq_marlin`. |

The S3 records remain the SAND-032 Stage 3 evidence. They are superseded only as grid cells.

## Config changes in SAND-037

- **Six new run YAMLs**: the four n = 20 1×L4 twins, `grid-20-correspondence-specialist-awq-2l4`, and
  `grid-20-merger-specialist-awq-1l4-rerun`. Each 1×L4 twin copies its 2×L4 sibling's `dataset` block,
  so a pair shares one draw. The n = 20 correspondence cells use one class bucket on `split: all`, so
  that draw nests inside the n = 50 correspondence draw.
- **The five n = 50 1×L4 YAMLs** gain `enable_thinking: false` and `max_inputs: 8`, matching the merger
  `-retry` leg's fix. Without `max_inputs`, `sandbox run deploy-env` leaves `MODAL_VLLM_MAX_INPUTS` unset
  and the deploy serializes requests.
- **`_GRID_TABLE`** gains the six new cells (cost caps and wall limits sized from the legacy runs).
- **`sandbox runbook check`** now fails if any config in a grid runbook implies a different deploy env
  from the runbook's export block, so each shape needs exactly one deploy.

## Known design choices to keep in mind when reading results

- At n = 20, insurance and corporate records draw stratified samples from `split: test`, while the
  n = 50 cells draw from `split: all`. Those n = 20 draws are not subsets of the n = 50 draws.
  Correspondence and contracts nest (same `split: all`, single class bucket). Merger n = 20 draws from
  `split: train`.
- Contracts and merger may still end some documents on LengthFinishReasonError at 8192. Record the
  count; do not raise `max_tokens` part-way through the grid.
- Contracts and merger ground truth is CUAD / MAUD labels, not the extraction schema, so their
  `overall_extraction_score` is near zero by construction. Score them with the CUAD clause F1 and MAUD
  accuracy scorers the SAND-032 reports use.

## Spend

Estimates only, from the nearest measured runs; the per-cell cost caps are the abort guards.

| Runbook | Warm GPU time (likely) | GPU $ (likely) | Sum of cost caps |
| --- | --- | ---: | ---: |
| `grid-1l4` | ≈ 3.6 h on one L4 (legacy 1×L4 C8 walls, n = 50 scaled ×2.5) | ≈ $3.00 | $5.70 |
| `grid-2l4` | ≈ 17 min on two L4s (S3 walls; n = 20 cells are tail-bound) | ≈ $0.55 | $7.00 |

Neither runbook authorizes spend; approve before `modal deploy`.
