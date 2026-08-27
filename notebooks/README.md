# Notebooks

Offline, LLM-free demonstrations of the **local mailroom sandbox**. Pattern
matches the family convention (thin notebook + importable modules, kernel
cwd-proof, hostile-cwd pytest).

| # | Notebook | What it proves |
| --- | --- | --- |
| 01 | [`01_activate_overlay.ipynb`](01_activate_overlay.ipynb) | `activate()`, OpenRouter→local map, surgical `--agent-model`, component gates |
| 02 | [`02_fixtures_catalog.ipynb`](02_fixtures_catalog.ipynb) | Manifest, typed gold, HF mini-slice, LegalBench, per-agent JSONL, attribution |
| 03 | [`03_isolated_agent_evals.ipynb`](03_isolated_agent_evals.ipynb) | Every live agent/node mock eval under a `document-pipeline` root |
| 04 | [`04_pipeline_and_scoring.ipynb`](04_pipeline_and_scoring.ipynb) | Connected pipeline scores + `llm-dojo-scoring` @ v0.11.0 |
| 05 | [`05_tracing_contract.ipynb`](05_tracing_contract.ipynb) | Langfuse v4 names/types, public GT (no `expected_fields`), export bookmark |
| 06 | [`06_prompts_matrix_log.ipynb`](06_prompts_matrix_log.ipynb) | Local prompt variants, fake client, matrix dry-run, sandbox experiment log |

## Conventions

- **Kernel-cwd-proof**: first code cell walks up for `pyproject.toml` + `reports/`.
- **Network-free & LLM-free**: code cells never call APIs. `--mock` / gold copy only.
- **Honest-gap doctrine**: mock `exact_match == 1.0` is harness proof, not model quality.
- Shared helper: [`_lib.py`](_lib.py) isolates JSONL writers under `reports/notebooks/`.
- Guard: [`tests/test_notebooks.py`](../tests/test_notebooks.py).

## Install / run

```bash
pip install -e ".[dev]"          # includes the notebooks extra
jupyter notebook notebooks/01_activate_overlay.ipynb
# or headless:
python -m jupyter execute notebooks/01_activate_overlay.ipynb
```

Regenerate sources (optional): `python notebooks/build_notebooks.py`.
