# Providers

The sandbox never hardcodes a model inside agent code.
[`runtime.activate(profile)`](../../src/mailroom_sandbox/runtime.py) rewrites
the taxonomy, then mailroom talks to an OpenAI-compatible `/v1`.

Full table: [`docs/providers.md`](../providers.md). Profiles:
[`config/profiles/`](../../config/profiles). Endpoints:
[`providers.py`](../../src/mailroom_sandbox/providers.py).

<details>
<summary>Health</summary>

`sandbox health` GETs `{base}/models` and posts a 1-token `json_object` chat.
If the engine rejects structured output, the probe reports `json_object_ok: false`.
Live test is `@pytest.mark.local_llm` (skipped unless `SANDBOX_LOCAL_LLM=1`).

</details>

<details>
<summary>Compose / Modal</summary>

- Default `sandbox up` starts **Langfuse + Ollama** ([`deploy/docker-compose.yml`](../../deploy/docker-compose.yml)).
- GPU is required for the `vllm` compose profile; Ollama can run tiny models on CPU.
- Modal: [`deploy/modal_vllm.py`](../../deploy/modal_vllm.py), [`deploy/README.md`](../../deploy/README.md).
- GitGuardian: compose healthchecks must **not** pass `--password` / `--requirepass`.

</details>

<details>
<summary>OpenRouter is opt-in</summary>

The default `.env` does not set `OPENROUTER_API_KEY`. Use profile `openrouter`
only when you intend to spend API budget. Overlay still maps champion ids so
local vs API matrix cells stay comparable ([`config/models.yaml`](../../config/models.yaml)).

</details>
