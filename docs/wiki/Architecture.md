# Architecture

The sandbox is an **orchestrator**. Canonical pipeline code stays in
llm-mailroom. This repo:

1. Loads a provider [profile](../../config/profiles).
2. Deep-merges [base taxonomy](../../config/mailroom.taxonomy.base.yaml) +
   [overlay](../../config/taxonomy.overlay.yaml) +
   [component routing](../../config/components.yaml).
3. Rewrites every `agents.*` `provider` / `model` for the serving family
   ([`config/models.yaml`](../../config/models.yaml)).
4. Writes [`data/runtime/taxonomy.yaml`](../../data/runtime/taxonomy.yaml) (gitignored).
5. Monkeypatches `pipeline.config.CONFIG_PATH` when mailroom is importable.

```python
from mailroom_sandbox.runtime import activate

act = activate("ollama")  # before importing mailroom graph/agents
print(act.taxonomy_path)
for name, provider, model in act.assignments:
    print(name, provider, model)
```

Implementation: [`src/mailroom_sandbox/runtime.py`](../../src/mailroom_sandbox/runtime.py),
[`src/mailroom_sandbox/overlay.py`](../../src/mailroom_sandbox/overlay.py).

<details>
<summary>Activate sequence (what actually runs)</summary>

1. Load `.env` from repo root or `config/.env` ([`config/.env.example`](../../config/.env.example)).
2. `load_profile(name)` from [`config/profiles/<name>.yaml`](../../config/profiles).
3. `apply_profile_env()` sets `DEFAULT_PROVIDER`, base URL, observability, `MAILROOM_BASE_DIR`.
4. Prepend vendored `vendor/llm-mailroom/src` to `sys.path` when present.
5. `build_merged_taxonomy()` — overlay knobs win after rewrite; `--agent-model` wins last.
6. `write_runtime_taxonomy()` → `data/runtime/taxonomy.yaml`.
7. `patch_mailroom_config()` points mailroom at that file and clears `load_config` cache.
8. Optional `patch_managed_prompt()` for `--prompt sorter_local_v0`.

Demo: [`notebooks/01_activate_overlay.ipynb`](../../notebooks/01_activate_overlay.ipynb).

</details>

<details>
<summary>13-node honesty</summary>

The live graph (ingest → classify / Lane A review → extract → judge / Lane B
arbiter → report → catalog → archive, plus vision/intake) lives in
llm-mailroom `graph/routing.py`. [`config/components.yaml`](../../config/components.yaml)
**gates isolated evals** and overlays confidence numbers. It does not add or
remove LangGraph nodes.

Retired specialists (`court_opinions_specialist`, `due_diligence_specialist`)
are listed, not runnable.

</details>

<details>
<summary>Package map</summary>

| Module | Role |
| --- | --- |
| [`runtime.py`](../../src/mailroom_sandbox/runtime.py) | `activate()` |
| [`overlay.py`](../../src/mailroom_sandbox/overlay.py) | merge / map / rewrite |
| [`components.py`](../../src/mailroom_sandbox/components.py) | gates + routing overlay |
| [`providers.py`](../../src/mailroom_sandbox/providers.py) | OpenAI-compatible URLs |
| [`prompts.py`](../../src/mailroom_sandbox/prompts.py) | local variants |
| [`datasets.py`](../../src/mailroom_sandbox/datasets.py) | fixtures |
| [`mock_llm.py`](../../src/mailroom_sandbox/mock_llm.py) | `--mock` client |
| [`eval/agents.py`](../../src/mailroom_sandbox/eval/agents.py) | isolated registry |
| [`eval/runners.py`](../../src/mailroom_sandbox/eval/runners.py) | mock/local runners |
| [`eval/scoring.py`](../../src/mailroom_sandbox/eval/scoring.py) | dojo sink |
| [`eval/tracing.py`](../../src/mailroom_sandbox/eval/tracing.py) | Langfuse v4 |
| [`cli.py`](../../src/mailroom_sandbox/cli.py) | `sandbox` entry |

</details>
