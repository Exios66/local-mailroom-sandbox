# local-mailroom-sandbox

A **local-first experiment sandbox** for the [LLM-Mailroom](https://github.com/Exios66/llm-mailroom) pipeline. Overlay config, serving, eval, and scoring around the governed family — **without forking** the 13-node LangGraph graph. Run classify → extract → report → archive offline on Ollama, vLLM, llama.cpp, or LM Studio. Swap in OpenRouter only when you mean to.

| At a glance | |
| --- | --- |
| Default provider | Ollama (`qwen3:8b`, fallback `qwen3:7b`) |
| Scoring | [`llm-dojo-scoring` @ v0.11.0](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.11.0) |
| Pipeline | [`llm-mailroom`](https://github.com/Exios66/llm-mailroom) (`fetch-deps` @ v0.5.0 source; `[pipeline]` extra = main) |
| Tracing | Langfuse 3 / SDK v4 (`document-pipeline`). Phoenix optional sidecar |
| Visualizer | [`The-Mailroom`](https://github.com/Exios66/The-Mailroom) reads the same Langfuse project |
| Storage | SQLite under `./data` (mailroom default) |
| Wiki | [`docs/wiki/Home.md`](docs/wiki/Home.md) |
| Notebooks | [`notebooks/`](notebooks/README.md) (offline, LLM-free) |

```python
from mailroom_sandbox.runtime import activate
from mailroom_sandbox.eval.runners import run_isolated_eval, run_pipeline_eval

activate("ollama")
print(run_isolated_eval("sorter", mock=True, sample=4)["scores"])
print(run_pipeline_eval(mock=True, sample=3, connected=True)["scores"])
```

## Quick start

```bash
pip install -e ".[dev]"
cp config/.env.example .env
sandbox fetch-deps                 # clones vendor/llm-mailroom @ v0.5.0 (source tree)
# optional: pip install -e ".[pipeline]"  # current mailroom main
sandbox eval sorter --mock         # no LLM, no Docker
sandbox eval pipeline --mock
```

With a local engine:

```bash
sandbox up                         # Langfuse + Ollama
sandbox pull-models                # ollama pull qwen3:8b
sandbox health
sandbox agents list
sandbox pilot --mock
sandbox pilot --local
sandbox eval sorter --local
```

CPU-only smoke: pull `llama3.2:3b` and `sandbox cutover --profile ollama --model llama3.2:3b`. GPU recommended for Qwen 8B.

<details>
<summary><strong>What this repo is / is not</strong></summary>

**Is**

- An orchestrator: [`runtime.activate()`](src/mailroom_sandbox/runtime.py) rewrites every taxonomy agent onto a local tag and writes [`data/runtime/taxonomy.yaml`](data/runtime/taxonomy.yaml).
- An eval harness for every live agent/node ([`eval/agents.py`](src/mailroom_sandbox/eval/agents.py)) plus connected pipeline scoring.
- A dojo v0.11.0 client ([`eval/scoring.py`](src/mailroom_sandbox/eval/scoring.py)) — typed extraction, never exact-match-on-fields.
- A Langfuse v4 producer ([`eval/tracing.py`](src/mailroom_sandbox/eval/tracing.py)) so The-Mailroom can observe local runs.

**Is not**

- A fork of the 13-node graph (that stays in llm-mailroom).
- A second kanban board (cross-family work stays on llm-entity-extraction).
- A replacement for The-Mailroom (this repo writes traces; the visualizer reads them).

Wiki: [Architecture](docs/wiki/Architecture.md) · [FAQ](docs/wiki/FAQ.md).

</details>

<details>
<summary><strong>Install variants</strong></summary>

```bash
pip install -e ".[dev]"             # pytest + notebooks
pip install -e ".[observability]"   # langfuse>=4,<5
pip install -e ".[pipeline]"        # mailroom *main* (conflicts with the v0.5.0 tag pin)
pip install -e ".[evals]"           # llm-entity-extraction @ v0.20.0
pip install -e ".[deploy]"          # Modal
```

Mailroom **v0.5.0** still lists dojo v0.7.0, so it is not a core pip dependency alongside dojo v0.11.0. Use `sandbox fetch-deps` for the source tree. See [`pyproject.toml`](pyproject.toml).

Env template: [`config/.env.example`](config/.env.example) → copy to `.env`.

</details>

<details>
<summary><strong>CLI atlas</strong> (<a href="src/mailroom_sandbox/cli.py"><code>cli.py</code></a>)</summary>

Global flags: `--profile` · `--model` · `--prompt` · `--agent-model NAME=tag` (repeatable). `--mock` is implied unless `--local`.

```bash
sandbox up | down | health | pull-models | fetch-deps | cutover | profiles | agents
sandbox pipeline watcher | pipeline api
sandbox pilot --mock|--local
sandbox hf-pilot --check|--mock|--local
sandbox legalbench --mock|--local
sandbox eval <agent>|extract|chained|pipeline|legalbench [--mock|--local]
sandbox matrix --providers ollama --models qwen3:8b --prompts sorter_local_v0 --mock --dry-run
sandbox datasets pull
sandbox traces export
```

```bash
sandbox cutover --agent-model judge=qwen3:14b
sandbox agents show judge
sandbox eval contracts_specialist --mock
sandbox eval pipeline --mock          # class + stage + extract + routing
```

Wiki: [CLI](docs/wiki/CLI.md).

</details>

<details>
<summary><strong>Overlay and cutover</strong> — why <code>DEFAULT_PROVIDER</code> is not enough</summary>

Mailroom's shipped taxonomy still names OpenRouter champion ids (`qwen/qwen3.7-flash`). Pointing the base URL at Ollama without rewriting `model` makes Ollama try to pull a slash-id it does not have.

```python
from mailroom_sandbox.overlay import map_model, load_profile, build_merged_taxonomy, agent_assignments

print(map_model("qwen/qwen3.7-flash", "ollama"))  # -> qwen3:8b
tax = build_merged_taxonomy(
    load_profile("ollama"),
    agent_models={"judge": "qwen3:14b"},  # CLI --agent-model, wins last
)
print([row for row in agent_assignments(tax) if row[0] in {"sorter", "judge"}])
```

| File | Role |
| --- | --- |
| [`config/profiles/ollama.yaml`](config/profiles/ollama.yaml) | Default local profile |
| [`config/models.yaml`](config/models.yaml) | Champion id → local tag |
| [`config/taxonomy.overlay.yaml`](config/taxonomy.overlay.yaml) | Per-agent temp / tokens |
| [`config/components.yaml`](config/components.yaml) | Eval gates + confidence routing |
| [`config/prompts/sorter_local_v0.txt`](config/prompts/sorter_local_v0.txt) | JSON-strict 7B/8B template |

`--model` rewrites **every** agent. `--agent-model judge=qwen3:14b` is surgical. Notebook: [`notebooks/01_activate_overlay.ipynb`](notebooks/01_activate_overlay.ipynb). Wiki: [Overlay and Cutover](docs/wiki/Overlay-and-Cutover.md).

</details>

<details>
<summary><strong>Offline evals</strong> (no LLM)</summary>

Isolated evals open a `document-pipeline` root and nest one observation. Connected `pipeline` scores the four public headlines together.

```python
from mailroom_sandbox.eval.runners import run_isolated_eval, run_pipeline_eval, run_legalbench_eval

run_isolated_eval("judge", mock=True, dry_run=True)
run_isolated_eval("intake", mock=True)           # dojo deterministic_normalize
run_isolated_eval("sorter_reviewer", mock=True, sample=2)
run_pipeline_eval(mock=True, sample=3, connected=True)
run_legalbench_eval(mock=True)
```

**Honesty:** mock predictors copy gold. `exact_match == 1.0` proves the harness, not a model. `ambiguous_01` gets confidence `0.40` so routing has a REVIEW case. Fixtures: [`data/fixtures/`](data/fixtures) ([`ATTRIBUTION.md`](data/fixtures/ATTRIBUTION.md)).

How-to: [`docs/evals.md`](docs/evals.md). Wiki: [Evals](docs/wiki/Evals.md). Notebooks: [03](notebooks/03_isolated_agent_evals.ipynb), [02](notebooks/02_fixtures_catalog.ipynb).

</details>

<details>
<summary><strong>Scoring</strong> (<code>llm-dojo-scoring @ v0.11.0</code>)</summary>

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.11.0
```

v0.11.0 is additive on v0.10.0 (formulas / T0 names unchanged) plus scoring docs and `llm_dojo_scoring.prompts`. Extraction is **typed** (id/date/money/name/lists). Pipeline mock emits `class_correct`, `stage_correct`, extraction overall, `routing_accuracy`.

```python
from mailroom_sandbox.eval import scoring
from mailroom_sandbox.datasets import load_manifest

rows = load_manifest()
labels = [r["expected_doc_class"] for r in rows[:8]]
print(scoring.score_classification(labels, labels)["exact_match"])
```

Sinks: `reports/experiment_log.jsonl` (sandbox-local, not a sister-repo mirror) and `reports/scores/`. Wiki: [Scoring](docs/wiki/Scoring.md). Notebook: [`04_pipeline_and_scoring.ipynb`](notebooks/04_pipeline_and_scoring.ipynb).

</details>

<details>
<summary><strong>Langfuse v4 traces / The-Mailroom</strong></summary>

```
OBSERVABILITY_PROVIDER=langfuse
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-sandbox
LANGFUSE_SECRET_KEY=sk-lf-sandbox
```

Root name `document-pipeline` (chain). Tags include **`mailroom`**. Public GT keys only — **`expected_fields` never go on the trace**. Isolated evals still open the root chain so The-Mailroom can draw a partial conveyor.

```bash
sandbox fetch-deps --visualizer
sandbox traces export    # data/traces/export.json
```

The-Mailroom filters: `MAILROOM_TRACE_NAMES=document-pipeline`, `MAILROOM_TRACE_TAGS=mailroom`, `MAILROOM_TRACE_ENVIRONMENTS=mock,pilot`. Phoenix is optional; The-Mailroom cannot plot it.

[`docs/tracing.md`](docs/tracing.md) · [wiki Tracing](docs/wiki/Tracing.md) · [notebook 05](notebooks/05_tracing_contract.ipynb).

</details>

<details>
<summary><strong>Notebooks</strong> (full offline demos)</summary>

| Notebook | Capability |
| --- | --- |
| [`01_activate_overlay.ipynb`](notebooks/01_activate_overlay.ipynb) | `activate()`, model map, `--agent-model`, component gates |
| [`02_fixtures_catalog.ipynb`](notebooks/02_fixtures_catalog.ipynb) | Manifest, typed gold, HF mini, LegalBench, attribution |
| [`03_isolated_agent_evals.ipynb`](notebooks/03_isolated_agent_evals.ipynb) | Every live agent mock eval |
| [`04_pipeline_and_scoring.ipynb`](notebooks/04_pipeline_and_scoring.ipynb) | Connected pipeline + dojo v0.11.0 |
| [`05_tracing_contract.ipynb`](notebooks/05_tracing_contract.ipynb) | Trace contract, public GT, export |
| [`06_prompts_matrix_log.ipynb`](notebooks/06_prompts_matrix_log.ipynb) | Local prompts, fake client, matrix, experiment log |

```bash
pip install -e ".[dev]"
jupyter notebook notebooks/01_activate_overlay.ipynb
pytest tests/test_notebooks.py -q
```

Kernel-cwd-proof bootstrap; writers isolated under `reports/notebooks/`. See [`notebooks/README.md`](notebooks/README.md) and [wiki Notebooks](docs/wiki/Notebooks.md).

</details>

<details>
<summary><strong>Providers</strong></summary>

| Profile | Mailroom provider | Default base URL | Default model |
| --- | --- | --- | --- |
| `ollama` (default) | `ollama` | `http://localhost:11434/v1` | `qwen3:8b` |
| `vllm-local` | `vllm` | `http://localhost:8000/v1` | `Qwen/Qwen3-8B` |
| `modal-vllm` | `vllm` | Modal `*.modal.run/v1` | `Qwen/Qwen3-8B` |
| `llamacpp` | `generic` | `http://localhost:8080/v1` | `qwen3-8b` |
| `lmstudio` | `generic` | `http://localhost:1234/v1` | `qwen3-8b` |
| `openrouter` | `openrouter` | `https://openrouter.ai/api/v1` | `qwen/qwen3.7-flash` |

OpenRouter is **opt-in**. [`docs/providers.md`](docs/providers.md) · [wiki Providers](docs/wiki/Providers.md) · [`deploy/README.md`](deploy/README.md).

</details>

<details>
<summary><strong>Layout</strong></summary>

```
config/profiles/          provider profiles (local-first defaults)
config/taxonomy.overlay.yaml
config/components.yaml    eval gates + routing knobs
config/models.yaml        OpenRouter champion → local tag map
config/prompts/           JSON-strict local variants
docs/wiki/                in-repo wiki (sync with docs/wiki/sync-wiki.sh)
notebooks/                offline Jupyter demos
deploy/                   compose + Modal vLLM
data/fixtures/            offline samples (see ATTRIBUTION.md)
src/mailroom_sandbox/     orchestrator package
reports/                  sandbox experiment log (not a sister-repo mirror)
vendor/                   fetch-deps clones (gitignored except README)
```

</details>

## Docs

| | |
| --- | --- |
| Wiki home | [`docs/wiki/Home.md`](docs/wiki/Home.md) |
| Providers | [`docs/providers.md`](docs/providers.md) |
| Evals | [`docs/evals.md`](docs/evals.md) |
| Tracing | [`docs/tracing.md`](docs/tracing.md) |
| Sister repos | [`docs/sister-repos.md`](docs/sister-repos.md) |
| Agent notes | [`AGENTS.md`](AGENTS.md) |

Family map: [llm-mailroom/docs/sister-repos.md](https://github.com/Exios66/llm-mailroom/blob/main/docs/sister-repos.md).
