---
name: modal
description: Deploy and cut over to Modal-hosted vLLM for local-mailroom-sandbox (sandbox-vllm app). Use when the user needs remote GPU inference, SANDBOX_PROFILE=modal-vllm, modal deploy/token, or MODAL_VLLM_* knobs — not for default CPU/Ollama work.
---

# Modal vLLM (remote GPU serve)

**When:** No suitable local GPU, user asks for Modal, or profile `modal-vllm`.  
**Prefer Ollama** for everyday local/CPU smoke ([ollama](../ollama/SKILL.md)). Local NVIDIA compose uses profile `vllm-local` + compose `vllm` (not Modal).

## Deploy

```bash
pip install -e ".[deploy]"
modal token new
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_API_TOKEN="$(openssl rand -hex 24)"
# optional: HF_TOKEN for gated weights
cd deploy && modal deploy modal_vllm.py
```

App name: **`sandbox-vllm`** (sandbox-scoped; HF volume `sandbox-hf-cache`). Source: `deploy/modal_vllm.py`.

Tear down: `modal app stop sandbox-vllm`.

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
sandbox health --profile modal-vllm
sandbox pilot --local --profile modal-vllm
```

Compose for Modal profile only starts **langfuse** (no local vLLM container).

## Knobs

| Env | Default |
| --- | --- |
| `MODAL_VLLM_MODEL` | `Qwen/Qwen3-8B` |
| `MODAL_VLLM_GPU` | `L4` |
| `MODAL_VLLM_MAX_MODEL_LEN` | `32768` |
| `MODAL_VLLM_QUANTIZATION` | empty |
| `MODAL_VLLM_IMAGE_TAG` | `latest` |
| `HF_TOKEN` | optional Hub auth |

## Boundaries

- Do not use Modal for default pytest or `--mock` paths.  
- Do not rename the Modal app to mailroom’s production name — keep `sandbox-vllm`.  
- Still activate via `runtime.activate("modal-vllm")` so taxonomy overlay rewrites agents.

## Related

- Local default: [ollama](../ollama/SKILL.md)  
- Hub weights: [huggingface](../huggingface/SKILL.md)  
- Docs: `deploy/README.md`, `docs/providers.md`
