# Providers

The sandbox never hardcodes a model inside agent code. `runtime.activate(profile)`
rewrites every `taxonomy.yaml` agent to the profile's provider + local tag, then
points mailroom at `data/runtime/taxonomy.yaml`.

| Profile | Mailroom provider | Default base URL | Default model |
| --- | --- | --- | --- |
| `ollama` (default) | `ollama` | `http://localhost:11434/v1` | `qwen3:8b` |
| `vllm-local` | `vllm` | `http://localhost:8000/v1` | `Qwen/Qwen3-8B` |
| `modal-vllm` | `vllm` | Modal `*.modal.run/v1` | `Qwen/Qwen3-8B` |
| `llamacpp` | `generic` | `http://localhost:8080/v1` | `qwen3-8b` |
| `lmstudio` | `generic` | `http://localhost:1234/v1` | `qwen3-8b` |
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `qwen/qwen3.7-flash` |

OpenRouter is **opt-in**. The default `.env` does not set `OPENROUTER_API_KEY`.

## Why an overlay

`DEFAULT_PROVIDER=ollama` alone still sends Ollama the OpenRouter id
`qwen/qwen3.7-flash`. `config/models.yaml` maps champion ids onto local tags.
`sandbox cutover` prints the effective table.

## Health

`sandbox health` GETs `{base}/models` and posts a 1-token `json_object` chat.
If the engine rejects structured output, the probe reports `json_object_ok: false`.

## Compose / Modal

See [`deploy/README.md`](../deploy/README.md). GPU is required for the `vllm`
compose profile; Ollama can run on CPU for tiny models.
