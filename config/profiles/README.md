<div align="center">

# 🌐 Provider Profiles

**Serving profiles for the local-mailroom-sandbox package.**

</div>

---

## Files

| File | Purpose |
| :--- | :--- |
| [`modal-vllm.yaml`](modal-vllm.yaml) | **Default** — Modal-deployed vLLM endpoint |
| [`ollama.yaml`](ollama.yaml) | Offline/CPU fallback, local Ollama (`:11434/v1`) |
| [`vllm-local.yaml`](vllm-local.yaml) | Local vLLM (`:8000/v1`) |
| [`vllm-remote.yaml`](vllm-remote.yaml) | Remote vLLM (tunneled/SSH) |
| [`llamacpp.yaml`](llamacpp.yaml) | llama.cpp server (`:8080/v1`) |
| [`lmstudio.yaml`](lmstudio.yaml) | LM Studio local server |
| [`openrouter.yaml`](openrouter.yaml) | OpenRouter cloud API (opt-in) |

## Usage

The default profile is `modal-vllm` (one Modal L4 behind an OpenAI `/v1`
endpoint). `sandbox runbook show serve` is the deploy → point → verify →
teardown script; a fresh `.env` needs `VLLM_BASE_URL` (or `MODAL_WORKSPACE`)
after the first `modal deploy`.

Select another profile with **`--profile`** (after the subcommand) or the
**`SANDBOX_PROFILE`** environment variable:

```bash
SANDBOX_PROFILE=ollama sandbox up --compose-profile ollama
sandbox tunnel --profile vllm-remote plan
```

`sandbox profiles` lists the profiles and marks the active default.

See `docs/SANDBOX-GUIDE.md` (profiles + tunnel sections) for the full flow.

## Related Files

- `../` — Configuration root
- `../../src/` — Source code