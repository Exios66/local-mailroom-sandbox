"""Modal-deployed vLLM for the local-mailroom-sandbox (KANBAN-064 sibling).

Same env-knob contract as llm-mailroom ``deploy/modal_vllm.py``. App name and
HF cache volume are sandbox-scoped so a workspace can host mailroom + sandbox
side by side, or one deployment can back both via VLLM_BASE_URL.

    pip install -e ".[deploy]"
    modal token new
    modal deploy deploy/modal_vllm.py

Then:

    SANDBOX_PROFILE=modal-vllm
    DEFAULT_PROVIDER=vllm
    VLLM_BASE_URL=https://<workspace>--sandbox-vllm-serve.modal.run/v1
    VLLM_API_KEY=<MODAL_VLLM_API_TOKEN>
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

APP_NAME = "sandbox-vllm"
SERVER_PORT = 8000
HF_CACHE_VOLUME_NAME = "sandbox-hf-cache"

MODEL = os.environ.get("MODAL_VLLM_MODEL", "Qwen/Qwen3-8B")
GPU = os.environ.get("MODAL_VLLM_GPU", "L4")
QUANTIZATION = os.environ.get("MODAL_VLLM_QUANTIZATION", "")
MAX_MODEL_LEN = os.environ.get("MODAL_VLLM_MAX_MODEL_LEN", "32768")
VLLM_IMAGE_TAG = os.environ.get("MODAL_VLLM_IMAGE_TAG", "latest")

_config_secret = modal.Secret.from_local(
    "MODAL_VLLM_MODEL",
    "MODAL_VLLM_QUANTIZATION",
    "MODAL_VLLM_MAX_MODEL_LEN",
    "MODAL_VLLM_API_TOKEN",
    "HF_TOKEN",
)

hf_cache = modal.Volume.from_name(HF_CACHE_VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.from_registry(f"vllm/vllm-openai:{VLLM_IMAGE_TAG}", add_python="3.12")
    .run_commands("pip install --no-cache-dir huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App(APP_NAME, image=image)


def _server_env() -> dict[str, str]:
    env: dict[str, str] = {}
    api_token = os.environ.get("MODAL_VLLM_API_TOKEN", "").strip()
    if api_token:
        env["VLLM_API_KEY"] = api_token
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if hf_token:
        env["HF_TOKEN"] = hf_token
    return env


def build_vllm_command(model: str) -> list[str]:
    cmd = [
        "vllm",
        "serve",
        model,
        "--host",
        "0.0.0.0",
        "--port",
        str(SERVER_PORT),
        "--max-model-len",
        MAX_MODEL_LEN,
    ]
    if QUANTIZATION:
        cmd += ["--quantization", QUANTIZATION]
    cmd += ["--disable-log-requests"]
    return cmd


@app.function(
    gpu=GPU,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[_config_secret],
    timeout=60 * 30,
    scaledown_window=15 * 60,
)
@modal.web_server(port=SERVER_PORT, startup_timeout=60 * 20)
def serve() -> None:
    model = os.environ.get("MODAL_VLLM_MODEL", MODEL)
    cmd = build_vllm_command(model)
    print("starting:", " ".join(cmd))
    subprocess.Popen(cmd, env={**os.environ, **_server_env()})


@app.local_entrypoint()
def main() -> None:
    print(f"Deploy with:  modal deploy {Path(__file__).name}")
    print(f"Serving model: {os.environ.get('MODAL_VLLM_MODEL', MODEL)} on GPU {GPU}")
    print(
        "Then point the sandbox at it:\n"
        "  SANDBOX_PROFILE=modal-vllm\n"
        "  DEFAULT_PROVIDER=vllm\n"
        f"  VLLM_BASE_URL=https://<workspace>--{APP_NAME}-serve.modal.run/v1\n"
        "  VLLM_API_KEY=<same value as MODAL_VLLM_API_TOKEN>"
    )
