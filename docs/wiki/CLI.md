# CLI

Entry point: [`src/mailroom_sandbox/cli.py`](../../src/mailroom_sandbox/cli.py)
(`sandbox` / `mailroom-sandbox` scripts in [`pyproject.toml`](../../pyproject.toml)).

Global flags (every subcommand): `--profile`, `--model`, `--prompt`,
repeatable `--agent-model NAME=tag`.

```bash
sandbox --help
sandbox eval sorter --mock
sandbox eval pipeline --mock
sandbox cutover --agent-model judge=qwen3:14b
sandbox agents list
sandbox agents show judge
```

`--mock` is the default unless `--local` is passed.

<details>
<summary>Lifecycle</summary>

| Command | What |
| --- | --- |
| `sandbox up` | Compose. Default profiles `langfuse` + `ollama`. `--compose-profile phoenix` optional. |
| `sandbox down` | Tear down. |
| `sandbox health` | GET `{base}/models` + 1-token `json_object` chat. |
| `sandbox pull-models` | `ollama pull` (default `qwen3:8b`). |
| `sandbox fetch-deps` | Clone mailroom @ v0.5.0 into `vendor/`. `--visualizer` also clones The-Mailroom. `--entity` optional. |
| `sandbox profiles` | List [`config/profiles/*.yaml`](../../config/profiles). |
| `sandbox cutover` | Print agent → provider/model after overlay. |

Compose file: [`deploy/docker-compose.yml`](../../deploy/docker-compose.yml).

</details>

<details>
<summary>Evals and data</summary>

| Command | What |
| --- | --- |
| `sandbox eval TASK` | Isolated agent, `extract`, `chained`, `pipeline`, `legalbench`. `--sample`, `--dry-run`, `--name`. |
| `sandbox pilot` | Fixture walk `--mock` / `--local`. |
| `sandbox hf-pilot` | Mini HF slice `--check` / `--mock` / `--local`. |
| `sandbox legalbench` | `--task contract_qa` (default). |
| `sandbox matrix` | `--providers` `--models` `--prompts` grid. |
| `sandbox datasets pull` | Hub head into `data/cache/` (**network**). |
| `sandbox traces export` | [`data/traces/export.json`](../../data/traces) bookmark. |
| `sandbox pipeline watcher` / `api` | Needs vendored mailroom `scripts/` on `PYTHONPATH`. |

Task names: [`eval/agents.py` `EVAL_TASKS`](../../src/mailroom_sandbox/eval/agents.py).

</details>

<details>
<summary>Surgical model override</summary>

```bash
# every agent
sandbox cutover --model qwen3:8b

# one agent, last writer wins
sandbox eval judge --mock --agent-model judge=qwen3:14b
```

Parser: [`overlay.parse_agent_models`](../../src/mailroom_sandbox/overlay.py).
Notebook: [`notebooks/01_activate_overlay.ipynb`](../../notebooks/01_activate_overlay.ipynb).

</details>
