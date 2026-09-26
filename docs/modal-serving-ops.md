# Modal serving ops runbook — warm-once, no-waste

**Owner:** SAND-028 · **Applies to:** every Modal+vLLM eval run in this sandbox.
**Companion:** [`SAND-028-SERVING-SPEND-REVIEW.md`](../governance/SAND-028-SERVING-SPEND-REVIEW.md)
(why each rule exists) · **Spend rules:** DMR-076/077/078 + `docs/benchmark-l4.md`.

## 0 · The one number that matters

**Token-proxy cost is ~2.4% of GPU cost. The L4 wall-clock is ~98% of the price.** Optimize GPU
*seconds*, not tokens. Rules below all reduce billed container time.

## 1 · Before you deploy (free checks)

```bash
# a. What will this model cost to serve? (no spend)
sandbox modal-matrix list
sandbox modal-matrix show ibm-granite/granite-4.2-8b-fp8
# b. What env will the deploy use? (no spend)
sandbox modal-matrix env ibm-granite/granite-4.2-8b-fp8
# c. How much will the whole suite cost? (no spend)
sandbox metrics estimate-suite --suite granite-track-a
# d. Is the run spec legal + does it fit the window? (no spend)
sandbox run preflight --config config/runs/<cfg>.yaml     # add --live only when you intend to spend
```

**Pre-warm the weights once (CPU-only function — no GPU billed):**
```bash
modal run deploy/modal_vllm.py::download_model     # no gpu= on this function → $0 GPU
```

## 2 · Deploy posture (the money knobs)

| Knob | Attended | Unattended/overnight | Why |
|---|---|---|---|
| `MODAL_VLLM_SCALEDOWN_SECONDS` | **120** | **600** | too low = container dies between batches → you re-pay the ~160-260s boot each time |
| `MODAL_VLLM_MAX_CONTAINERS` | **1** | 1 | >1 doubles $/hr; only raise if the probe shows queueing, not just latency |
| `MODAL_VLLM_MIN_CONTAINERS` | 0 | 1 (if a long unattended stretch) | min=1 during a matrix keeps it warm across your own pauses |
| `MODAL_VLLM_GPU` | **L4** | L4 | H100 is ~4.9× $/hr; it only pays if it cuts billed seconds >4.9× (it won't at n≤100) |

**Never `modal deploy --strategy recreate` mid-matrix** — a recreate re-pays image pull + weight
load. Deploy once, run everything, teardown once.

## 3 · Run the matrix warm-once (the O3 win)

Drive the whole class matrix through the suite runner, which chains configs against **one** warm
app and prints the teardown command for the end:

```bash
sandbox run suite --suite granite-track-a --execute     # contracts + corporate + correspondence
sandbox run suite --suite granite-track-b --execute     # merger + insurance
./deploy/teardown_vllm.sh                                # ONLY after the last track
```

Do **not** fire each config as an independent `sandbox run start` — that is how you pay a boot per
run (24% of the measured Qwen spend was cold boots).

## 4 · Granite specifics (SAND-027)

```bash
eval "$(sandbox modal-matrix env ibm-granite/granite-4.2-8b-fp8)"
export MODAL_VLLM_REASONING_PARSER=granite_thinking_parser \
       MODAL_VLLM_TOOL_CALL_PARSER=qwen3_coder MODAL_VLLM_ENABLE_AUTO_TOOL_CHOICE=1
# if the pinned image lacks the native parser (v0.29.0-era), fall back to IBM's plugin:
# export MODAL_VLLM_REASONING_PARSER_PLUGIN=/path/from/hf/granite_thinking_parser.py
modal deploy deploy/modal_vllm.py --strategy recreate
```

- The OpenRouter twin is `ibm-granite/granite-4.2-8b` (same string as the HF repo = first-party
  twin). The Modal leg serves the `-fp8` copy of those weights; reports must say so.
- **Deploy smoke before the matrix** (SAND-027-6): confirm boot at 32768, a real structured-output
  completion, and that thinking spans are separable.

## 5 · Same-subset rule (do not re-draw)

Draw **one bucket per class** (the 100) and score the 20/50 buckets as **prefixes of the locked
100-row set**. Re-drawing per size does NOT give nested subsets with the current sampler
(`corpus._draw_buckets` seeds per class, not per count — 50⊂100 holds only ~26% of seeds). Slice the
locked set; never re-draw.

## 6 · Cost caps: set them from measurement, not habit

- `job.cost_cap_usd` + `job.max_wall_seconds` are abort guards. A cap that aborts a *correct* run
  wastes the whole warm window; one that never trips overspends.
- After the N=20 probe, re-derive `sec_per_doc` and caps from **measured** per-class wall + decode
  for the actual model, and set `MODAL_BILLED_GPU_SECONDS` to the real Modal warm interval so caps
  match billing (`job/metrics.py` prefers it over the `wall + cold_boot` estimate).
- Read the per-run serving JSON (`reports/serving/*.serving.json`): if `wall` ≫
  `sum(per-doc latency)/concurrency`, the GPU is idling between batches — raise concurrency (never
  `max_num_seqs` blindly; it's the server-side admission).

## 7 · Teardown (the only place to stop paying)

```bash
./deploy/teardown_vllm.sh     # stops the app, frees the L4; volumes persist for next time
```

Teardown after the LAST run only. Every minute the app is up past the last request is billed.

## 8 · Anti-patterns (each one has cost us money or trust)

| Anti-pattern | Cost | Instead |
|---|---|---|
| Independent `run start` per config | a boot per run (~$0.036 each on L4) | `sandbox run suite` warm-once |
| `recreate` between runs | image+weight reload | deploy once per matrix |
| Raising `max_tokens` to "clear" LengthFinish | ~2× decode; cap moves, doesn't clear | guided JSON decode + fail-fast (SAND-028-2) |
| Concurrency 3-4 on light classes | 2.8× throughput left on the table (measured c5→c8) | re-derive per class (SAND-028-3) |
| scaledown 600 while actively iterating | container may die mid-matrix | 120 attended / 600 only overnight |
| H100 "for speed" | ~4.9× $/hr, won't repay at n≤100 | L4 (O9) |

## 9 · Evidence (this runbook's numbers)

- `reports/serving/*.serving.json` — 3 measured Modal runs ($0.5452 / 60 docs; boots 24% of spend;
  contracts $0.0188/doc vs correspondence $0.0028).
- `reports/RUN-20-CONTRACTS-AWQ-C8-REPORT.md` — LengthFinish/decode-cost analysis; token-proxy =
  2.44% of GPU cost.
- `src/mailroom_sandbox/job/metrics.py`, `job/specialist_posture.py`, `job/suite.py`,
  `deploy/modal_vllm.py`, `config/models.yaml`, `docs/benchmark-l4.md`.
- Changes made under SAND-028 (verified, 438-test suite green): Granite `modal_models` rows in
  `config/models.yaml`; env-gated reasoning/tool parser knobs in `deploy/modal_vllm.py`
  (Qwen default path byte-identical).
