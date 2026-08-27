# Overlay and Cutover

`DEFAULT_PROVIDER=ollama` alone still sends Ollama the OpenRouter id
`qwen/qwen3.7-flash`. The overlay exists to rewrite **every** agent onto a
local tag.

```python
from mailroom_sandbox.overlay import map_model, load_profile, build_merged_taxonomy, agent_assignments

print(map_model("qwen/qwen3.7-flash", "ollama"))  # qwen3:8b
tax = build_merged_taxonomy(load_profile("ollama"), agent_models={"judge": "qwen3:14b"})
print([row for row in agent_assignments(tax) if row[0] == "judge"])
```

<details>
<summary>Files (in merge order)</summary>

1. Base taxonomy — vendored mailroom `taxonomy.yaml`, else [`config/mailroom.taxonomy.base.yaml`](../../config/mailroom.taxonomy.base.yaml)
2. [`config/taxonomy.overlay.yaml`](../../config/taxonomy.overlay.yaml) — vision, cost_models, per-agent temp/tokens
3. [`config/components.yaml`](../../config/components.yaml) `routing.confidence`
4. Profile rewrite from [`config/profiles/<name>.yaml`](../../config/profiles) + [`config/models.yaml`](../../config/models.yaml)
5. Overlay **agent knobs** again (win after rewrite)
6. CLI `--agent-model` (always last)

Code: [`overlay.build_merged_taxonomy`](../../src/mailroom_sandbox/overlay.py).

</details>

<details>
<summary>Profiles</summary>

| Profile | Provider | Default base URL | Default model |
| --- | --- | --- | --- |
| `ollama` | `ollama` | `http://localhost:11434/v1` | `qwen3:8b` |
| `vllm-local` | `vllm` | `http://localhost:8000/v1` | `Qwen/Qwen3-8B` |
| `modal-vllm` | `vllm` | Modal `*.modal.run/v1` | `Qwen/Qwen3-8B` |
| `llamacpp` | `generic` | `http://localhost:8080/v1` | `qwen3-8b` |
| `lmstudio` | `generic` | `http://localhost:1234/v1` | `qwen3-8b` |
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `qwen/qwen3.7-flash` |

OpenRouter is **opt-in**. [`config/.env.example`](../../config/.env.example) does not set `OPENROUTER_API_KEY`.

</details>

<details>
<summary>Local prompt variants</summary>

[`config/prompts/*_local_v0.txt`](../../config/prompts) are shorter JSON-strict
templates for 7B/8B models. `--prompt sorter_local_v0` monkeypatches
mailroom `get_managed_prompt` when importable
([`prompts.patch_managed_prompt`](../../src/mailroom_sandbox/prompts.py)).

Dojo v0.11.0 also ships `llm_dojo_scoring.prompts.get_prompt` (production +
docclass families). Sandbox local templates still win for 7B/8B JSON-strict
runs.

Notebook: [`notebooks/06_prompts_matrix_log.ipynb`](../../notebooks/06_prompts_matrix_log.ipynb).

</details>
