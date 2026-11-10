<div align="center">

# ⚙️ Sandbox Configuration

**Configuration files for the local-mailroom-sandbox package.**

</div>

---

## Structure

| Path | Contents |
| :--- | :--- |
| [`mailroom.taxonomy.base.yaml`](mailroom.taxonomy.base.yaml) | Document classes, agents, prompts |
| [`taxonomy.overlay.yaml`](taxonomy.overlay.yaml) | Overlay applied on top of the base |
| [`models.yaml`](models.yaml) | Serving/model catalog (providers, quantization, GPU) |
| [`components.yaml`](components.yaml) | Agent roster + retired/optional components |
| [`datasets.yaml`](datasets.yaml) | Named Hub/local sources, optional byte pins and pull provenance; [schema and migration](../docs/datasets/named-datasets.md) |
| [`profiles/`](profiles/) | Provider serving profiles |
| [`runbooks/`](runbooks/) | Operator runbook catalog (`catalog.yaml` — edit here, then `sandbox runbook write`) |
| [`runs/`](runs/) | Job-run spec examples |
| [`prompts/`](prompts/) | Prompt overrides/registry |
| [`subagents/`](subagents/) | Coding subagent roster (Cursor + OpenCode adapters) |

> **Two run-spec trees.** [`runs/`](runs/) holds the `sandbox run` specs
> (`vllm-local` / `vllm-remote` / `modal-vllm` / `openrouter`, including
> hybrid agent routes). The separate OpenRouter `api-*` harness specs live in
> [`../api-evals/config/runs/`](../api-evals/config/runs/)
> and run through `python api-evals/run_api_evals.py` from the repository root.
> Main sandbox API runs use their own API token budget; see [jobs](../docs/jobs.md).
> See
> [`../docs/setting-up/LAYOUT.md`](../docs/setting-up/LAYOUT.md).

## Profile selection

The default profile is **`modal-vllm`** (one Modal L4 behind OpenAI `/v1`;
`sandbox runbook show serve`). Profiles are selected with `--profile` or the
**`SANDBOX_PROFILE`** env var (`modal-vllm`, `ollama` for offline, `vllm-local`,
`vllm-remote`, `llamacpp`, `lmstudio`, `openrouter`) — see
[`profiles/README.md`](profiles/README.md).

## Environment

Copy [`config/.env.example`](.env.example) to `.env` at the repository root
and fill in provider keys. `sandbox` commands load it automatically.
`MAILROOM_BASE_DIR` selects the run store and resolves named-dataset path
templates; `SANDBOX_DATASETS_REGISTRY` selects an alternate registry. See
[path and cache rules](../docs/datasets/named-datasets.md#paths-environment-and-caches).

## Related Files

- `src/` — Source code
- `data/` — Test data
- [`config/.env.example`](.env.example) — Environment template
