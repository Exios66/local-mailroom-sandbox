---
name: modal
description: Deploy and cut over to explicitly selected Modal-hosted vLLM for local-mailroom-sandbox (sandbox-vllm app). Use for requested GPU inference, SANDBOX_PROFILE=modal-vllm, modal deploy/token, or MODAL_VLLM_* knobs. OpenRouter is the experimental default; use Ollama for offline/CPU inference.
---

# Modal vLLM (remote GPU serve)

**When:** GPU inference is requested and no suitable local GPU is available, or
the selected profile is `modal-vllm`. OpenRouter remains the default experimental
provider; missing API credentials do not authorize a Modal deployment.
`sandbox runbook show serve` prints the explicit GPU deploy → verify → teardown
script. Use [ollama](../ollama/SKILL.md) for offline/CPU smoke. Local NVIDIA
compose uses profile `vllm-local` + compose `vllm`.

Repository-declared pins: Modal SDK **1.6.4** (`[deploy]` extra) + vLLM **v0.29.0**
(`vllm/vllm-openai:v0.29.0`, matching the local compose pin). Full workflow:
[`deploy/README.md`](../../../deploy/README.md).

## Deploy

```bash
pip install -e ".[deploy]"
modal token new
export MODAL_VLLM_MODEL=Qwen/Qwen3.5-9B
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_API_TOKEN="$(openssl rand -hex 24)"
# Remote HF auth uses the named Modal secret huggingface-secret (HF_TOKEN).
# A local HF_TOKEN does not configure that remote secret.

modal run deploy/modal_vllm.py::download_model   # pre-warm weights (CPU-only)
modal deploy deploy/modal_vllm.py                # prints the modal.run URL
```

### Through the sandbox CLI (guarded passthrough)

```bash
sandbox modal deploy --model Qwen/Qwen3-8B-AWQ --dry-run   # prints the exact argv + MODAL_VLLM_* row, spends nothing
sandbox modal prewarm        # CPU-only weight download
sandbox modal deploy         # prints the endpoint + export lines
sandbox vllm probe --profile modal-vllm  # models + chat + /health + /metrics (wakes a billed GPU)
sandbox modal status         # is sandbox-vllm deployed (billing)?
sandbox modal stop           # idempotent teardown, verified via `modal app list --json`
sandbox modal raw -- <modal args>    # anything else, unchanged
```

A missing `modal` binary is one `error:` line with the install hint. `sandbox vllm command`
prints the `vllm serve` line the app launches (from `build_vllm_command`).

App name: **`sandbox-vllm`** (sandbox-scoped; Volumes `sandbox-hf-cache` +
`sandbox-vllm-cache`). Source: `deploy/modal_vllm.py`.

Tear down: `modal app stop sandbox-vllm` (Volumes persist).

## Cut over the sandbox

```bash
# .env
SANDBOX_PROFILE=modal-vllm
DEFAULT_PROVIDER=vllm
VLLM_BASE_URL=https://<workspace>--sandbox-vllm-serve.modal.run/v1
VLLM_API_KEY=<same as MODAL_VLLM_API_TOKEN>
```

```bash
sandbox cutover --profile modal-vllm
sandbox health --profile modal-vllm     # 401 = VLLM_API_KEY mismatch
sandbox pilot --local --profile modal-vllm
```

Compose for Modal profile only starts **langfuse** (no local vLLM container).

## Knobs

| Env | Default |
| --- | --- |
| `MODAL_VLLM_MODEL` | `Qwen/Qwen3.5-9B` |
| `MODAL_VLLM_GPU` | `L4` |
| `MODAL_VLLM_MAX_MODEL_LEN` | `16384` (DMR-056: boot-valid cap for L4-bf16 8B rows — v0.29.0 raises at 32768; AWQ/FP8 rows set 32768) |
| `MODAL_VLLM_MAX_NUM_SEQS` | `6` (L4 long-prompt 4–6; cliff at ~8 × ~8k; scale-matrix overrides to 256) |
| `MODAL_VLLM_GPU_MEMORY_UTILIZATION` | `0.90` |
| `MODAL_VLLM_ENABLE_PREFIX_CACHING` | `1` (`--enable-prefix-caching`) |
| `MODAL_VLLM_ENFORCE_EAGER` | `1` (`--enforce-eager` — faster cold boot) |
| `MODAL_VLLM_ATTENTION_BACKEND` | empty (`flashinfer` for throughput runs — Modal vllm_throughput exemplar) |
| `MODAL_VLLM_ASYNC_SCHEDULING` | empty (`1` enables the async scheduler; not all vLLM features supported under it) |
| `MODAL_VLLM_QUANTIZATION` | model-dependent: `fp8` for the default Qwen3.5-9B; inspect `MODEL_SERVE_DEFAULTS` |
| `MODAL_VLLM_IMAGE_TAG` | `v0.29.0` (pin; never `latest`) |
| `MODAL_VLLM_REVISION` | empty (HF revision) |
| `MODAL_VLLM_TP_SIZE` | from GPU `:N` suffix (1 single-GPU) — only for models that won't fit one GPU; second L4 on 8B → raise `MAX_CONTAINERS` |
| `MODAL_VLLM_API_TOKEN` | empty (bearer) |
| `MODAL_HF_SECRET_NAME` | `huggingface-secret`, a named Modal secret requiring `HF_TOKEN` |
| `MODAL_VLLM_SCALEDOWN_SECONDS` | `120` (attended specialist default; set `600` unattended/overnight) |
| `MODAL_VLLM_MAX_CONTAINERS` | `1` (cost guard; `2` = data-parallel second L4, Modal round-robins) |
| `MODAL_VLLM_MIN_CONTAINERS` | `0` (scale-to-zero) |
| `MODAL_VLLM_STARTUP_TIMEOUT_SECONDS` | `1200` |

Historical specialist 5×30 runbooks pin **Qwen/Qwen3-8B** on 1×L4 (`max_containers=1`);
they are separate from the deployment default and keep their pins.
Operator cards: `sandbox runbook show l4-qwen3-8b` (catalog
`config/runbooks/catalog.yaml`). Improved configs (AWQ/c8, Granite FP8, second
L4): `sandbox runbook list --family improved`. Per-doc-type concurrency /
`cost_cap_usd` / `max_wall_seconds` still come from `job/specialist_posture.py`.

Use the run's locked GPU/app configuration and the current pricing check for
cost estimates; do not turn an old hourly rate into a current spend claim.
`download_model` is CPU-only but still invokes hosted work. Deploy, prewarm,
health/probe and paid runs retain the repository's live/spend authorization gates.

## Throughput runs

Choose a reviewed model/GPU row from `config/models.yaml` and the Modal matrix;
do not infer a published checkpoint or valid context window from its name.
Lock concurrency and serving knobs in the run spec before paid execution.
Changing replicas, attention or async scheduling is an experiment, not a safe
default upgrade. Keep async scheduling off when the run depends on structured
outputs. See `docs/jobs.md` and `deploy/README.md`.

## Pinned SDK usage

- `_config_secrets` in `deploy/modal_vllm.py` uses `Secret.from_name` for Hub
  credentials and `Secret.from_dict` for present serving overrides. Keep Hub
  auth separate; do not copy a local `HF_TOKEN` into those serving overrides.
- The serving function uses `@modal.web_server`; do not migrate decorators or
  enable memory snapshots as part of a docs/configuration correction. Check the
  pinned SDK and the deployment design before changing that lifecycle.

## Boundaries

- Do not use Modal for default pytest or `--mock` paths.  
- Do not rename the Modal app to mailroom's production name — keep `sandbox-vllm`.  
- Still activate via `runtime.activate("modal-vllm")` so taxonomy overlay rewrites agents.
- Never commit tokens; only variable names appear in the repo.

## Related

- Offline fallback: [ollama](../ollama/SKILL.md)  
- Hub weights: [huggingface](../huggingface/SKILL.md)  
- Docs: `deploy/README.md`, `docs/setting-up/remote-serving.md`, `docs/setting-up/providers.md`
