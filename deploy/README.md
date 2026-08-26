# Modal + local compose

## Compose

```bash
sandbox up                       # langfuse + ollama (from the ollama profile)
sandbox up --compose-profile phoenix --compose-profile vllm
sandbox down
```

Profiles: `langfuse`, `phoenix`, `ollama`, `vllm`, `llamacpp`.

Langfuse 3 (`langfuse-web` + `langfuse-worker`) is the default tracing sink.
Phoenix is optional. Headless project keys are `pk-lf-sandbox` / `sk-lf-sandbox`
(see `config/.env.example`).

vLLM needs an NVIDIA GPU on the host. Ollama runs on CPU for smoke models
(`llama3.2:3b`); use a GPU host for `qwen3:8b`.

## Modal vLLM

Same knobs as llm-mailroom KANBAN-064 / entity-extraction KANBAN-096.

```bash
pip install -e ".[deploy]"
modal token new
export MODAL_VLLM_MODEL=Qwen/Qwen3-8B
export MODAL_VLLM_GPU=L4
export MODAL_VLLM_API_TOKEN="$(openssl rand -hex 24)"
cd deploy && modal deploy modal_vllm.py
```

Flip the sandbox:

```
SANDBOX_PROFILE=modal-vllm
DEFAULT_PROVIDER=vllm
VLLM_BASE_URL=https://<workspace>--sandbox-vllm-serve.modal.run/v1
VLLM_API_KEY=<MODAL_VLLM_API_TOKEN>
```

Tear down: `modal app stop sandbox-vllm`.
