# Modal + local compose + offline Dockerfile

## Compose

```bash
sandbox up                       # langfuse + ollama (from the ollama profile)
sandbox up --compose-profile phoenix --compose-profile vllm
sandbox up --compose-profile jupyter   # builds deploy/Dockerfile → Lab :8888
sandbox down
```

Profiles: `langfuse`, `phoenix`, `ollama`, `vllm`, `llamacpp`, `jupyter`.

Langfuse 3 (`langfuse-web` + `langfuse-worker`) is the default tracing sink.
Phoenix is optional. Headless project keys are `pk-lf-sandbox` / `sk-lf-sandbox`
(see `config/.env.example`).

vLLM needs an NVIDIA GPU on the host. Ollama runs on CPU for smoke models
(`llama3.2:3b`); use a GPU host for `qwen3:8b`.

## Offline Dockerfile + Jupyter notebooks

[`Dockerfile`](Dockerfile) builds `mailroom-sandbox:offline` (Python 3.11 + sandbox +
Jupyter Lab). Full walkthrough: [`docs/docker-offline.md`](../docs/docker-offline.md).

```bash
# Image alone
docker build -f deploy/Dockerfile -t mailroom-sandbox:offline .

# Or via compose (mounts the repo at /workspace)
sandbox up --compose-profile langfuse --compose-profile ollama --compose-profile jupyter
# → http://127.0.0.1:8888/lab  (notebooks/01…03)
sandbox datasets prepare         # same cleaners the notebooks call
```

Dedicated notebooks:

1. `notebooks/01_offline_environment_setup.ipynb` — `.env`, profile activate, checklist  
2. `notebooks/02_load_clean_prepare_data.ipynb` — load/clean/write `data/runtime/prepared/`  
3. `notebooks/03_offline_sandbox_smoke.ipynb` — mock sorter/pipeline smoke

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
