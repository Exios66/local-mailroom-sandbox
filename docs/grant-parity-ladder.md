# Modal ladder (operator runbook)

Short hold-until-go runbook for the contracts + correspondence ladder cells:
**N=20/40 × 1–2 L4 × contracts + correspondence**. Specs live under
`config/runs/run-{20,40}-*-specialist-modal*.yaml`. Ordered suite:
`config/runs/suites/grant-parity-contracts-correspondence.yaml`.

**This PR is YAML + docs only. Do not `modal deploy`, `modal run …::download_model`,
`sandbox run start`, or `sandbox run suite --execute` until an explicit go.**

## Cells

| Order | `run_id` | Task | N | L4 replicas | concurrency | `cost_cap_usd` | `max_wall_seconds` |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `run-20-contracts-specialist-modal` | `contracts_specialist` | 20 | 1 | 8 (Jack lock) | 0.55 | 2400 |
| 2 | `run-20-correspondence-specialist-modal` | `correspondence_specialist` | 20 | 1 | 8 (Jack lock) | 0.30 | 1800 |
| 3 | `run-20-contracts-specialist-modal-2xl4` | `contracts_specialist` | 20 | 2 | 8 | 0.90 | 1800 |
| 4 | `run-20-correspondence-specialist-modal-2xl4` | `correspondence_specialist` | 20 | 2 | 8 | 0.50 | 1500 |
| 5 | `run-40-contracts-specialist-modal` | `contracts_specialist` | 40 | 1 | 8 | 1.10 | 3600 |
| 6 | `run-40-correspondence-specialist-modal` | `correspondence_specialist` | 40 | 1 | 8 | 0.70 | 3000 |
| 7 | `run-40-contracts-specialist-modal-2xl4` | `contracts_specialist` | 40 | 2 | 8 | 1.80 | 3000 |
| 8 | `run-40-correspondence-specialist-modal-2xl4` | `correspondence_specialist` | 40 | 2 | 8 | 1.20 | 2400 |

Shared pins (every YAML): `schema: sandbox.run/v1`, `profile: modal-vllm`,
engine `kind: modal-vllm`, `Qwen/Qwen3-8B`, GPU `L4`, `image_tag: v0.29.0`,
`max_model_len: 16384`, `gpu_memory_utilization: 0.90`, `max_num_seqs: 256`,
`scaledown_seconds: 120`, `min_containers: 0`, `prewarm: true`, job
`mode: endpoint`, `mock: false`, `max_retries: 2`, `fail_fast: false`,
`sample_seed: 42`. Dataset: `split: all` (aliases `train+test` / `both` —
`expand_hf_splits` unions train+test; Hub `ground_truth` has **no**
validation split). Prompt pins: `contracts_specialist_v33` /
`correspondence_specialist_production` (same as the run-30 siblings).

**Concurrency is flat 8 on every ladder cell** (contracts and
correspondence) so client concurrency does not confound a fair
cross-class compare. DMR-078 short↑/long↓ (correspondence/insurance **5**,
corporate/contracts **4**, merger **3**) remains for the **run-30 spend
tracks only**. 2×L4 cells change **only** `max_containers: 2` (GPU
replicas); concurrency stays 8. Expect higher $/hr on 2×L4 until
scaledown.

## Corpus

Pinned dataset: `Lucius-Morningstar/mailroom-dataset` config `ground_truth`
split **`all`** (train+test union) revision
`46a4d3c240a36671cde0182fff4960f6b8b73aca` — confirmed Hub tip on 2026-09-24
and identical to sandbox `FAMILY_HF_REVISION`. Do not invent a newer SHA.

Hub README + `ground_truth` parquet (train 2979 + test 323 = **3302**):

| Class | Train | Test | **Full (`split: all`)** |
| --- | ---: | ---: | ---: |
| `contract` | 540 | 60 | **600** |
| `correspondence` | 915 | 85 | **1000** |

There is no `validation` split on this Hub config.

### Why not test-only

The Hub 90/10 split is an **evaluation partition for reproducible sampling**,
not ML train/test. Test is ~10% (323 rows) and **subclass-unbalanced**
(contracts test surfaces 19 families with tiny caps; correspondence test
drops `attorney_demand` entirely and skews the remaining seven). Sampling
ladder cells from test-only would over-weight scarce test families
and under-weight full-corpus majors (`license`, `consulting`, `email`).
The ladder therefore samples from the **full corpus** via
`dataset.split: all`.

### Strata (full-corpus Hamilton, never above avail)

Counted from `ground_truth` parquet at the pin, canonical snake_case via
the same CUAD folder normalizer the job loader uses (`License_Agreements`
→ `license`, etc.).

**Contracts — 9 largest families of 25** (pool 326 of 600):

| subclass | full avail | N=20 | N=40 |
| --- | ---: | ---: | ---: |
| `supply` | 47 | 3 | 6 |
| `license` | 43 | 3 | 5 |
| `consulting` | 38 | 2 | 5 |
| `ip` | 35 | 2 | 4 |
| `service` | 34 | 2 | 4 |
| `maintenance` | 34 | 2 | 4 |
| `distributor` | 32 | 2 | 4 |
| `strategic_alliance` | 32 | 2 | 4 |
| `sponsorship` | 31 | 2 | 4 |

**Correspondence — 7 largest of 8** (pool 997 of 1000):

| subclass | full avail | N=20 | N=40 |
| --- | ---: | ---: | ---: |
| `email` | 557 | 11 | 23 |
| `memo` | 83 | 2 | 3 |
| `notice` | 81 | 2 | 3 |
| `letter` | 79 | 2 | 3 |
| `press_release` | 78 | 1 | 3 |
| `demand` | 66 | 1 | 3 |
| `meeting_request` | 53 | 1 | 2 |

`attorney_demand` has 3 full-corpus rows; Hamilton remainder is 0 at both
N=20 and N=40, so it is omitted from the draw (still in the pool; not a
test-only exclusion).

## Hard hold

Until explicit go:

- Do not `modal run deploy/modal_vllm.py::download_model`.
- Do not `modal deploy deploy/modal_vllm.py`.
- Do not `sandbox run start` / `sandbox run suite --execute`.
- Offline estimates are fine: `sandbox metrics estimate-suite --suite grant-parity-contracts-correspondence`.
- `sandbox run suite --suite grant-parity-contracts-correspondence` **prints**
  the warm-once loop; do not add `--execute`.

`sandbox run benchmark-check` is the run-30 specialist gate (Hermes + 1×L4 +
limit 30). It is **not** the gate for this ladder.

## Auth (after go)

Use `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` (gitignored `.env` / shell only —
never commit values). Hermes `hermes-agent-jjb` is **not** required for this
ladder. Optional: `modal profile activate <your-profile>` if you use
`~/.modal.toml` instead of the token env pair.

Full-ladder deploy after go: one `sandbox-vllm` app, `MODAL_VLLM_MAX_CONTAINERS=2`
so 2×L4 cells can scale. Do not stop / redeploy between cells. Teardown only
after the last: `./deploy/teardown_vllm.sh`.

## Capture (after each live run)

Keep:

1. **Artifact dir** `data/runtime/runs/<run_id>/` (`spec.lock.json`,
   `items.jsonl`, `checkpoint.json`, `events.jsonl` — see `docs/jobs.md`).
2. **Compare JSON** from
   `sandbox metrics compare --runs <run_id> --json`.
   Persist the blob. Do **not** invent keys. Retain the existing table
   fields in `mailroom_sandbox.eval.serving_parity`
   (`serving_kind`, `e2e_latency_seconds`, `ttft_seconds`, `prompt_tokens`,
   `completion_tokens`, `total_tokens`, `estimated_cost_usd`,
   `cost_per_document`, `accuracy`, `f1_macro`) and the sandbox-only GPU
   fields in `SANDBOX_GPU_KEYS` (`gpu_seconds`, `estimated_gpu_cost_usd`,
   `gpu_cost_per_document`, `gpu`). Compare `--json` also emits bucket
   aggregates (`mean_e2e_s`, `mean_ttft_s`, `total_gpu_cost_usd`, …) from
   `job/metrics.compare` — keep those as emitted.
3. **Modal logs** for the `sandbox-vllm` app / function.
4. **CLI stdout/stderr** for preflight, start, and compare.
5. **Cost vs estimate** — pre-run `sandbox metrics estimate-suite` vs
   compare JSON GPU $ vs Modal billing for the window.
6. **Teardown evidence** that `./deploy/teardown_vllm.sh` ran after the
   last cell (zero remaining GPU containers; volumes may persist).
