# Notebooks

Six **full** offline notebooks. No LLM, no Docker, no Hub. They import the
same modules the CLI uses.

Index: [`notebooks/README.md`](../../notebooks/README.md).

| Notebook | Capability |
| --- | --- |
| [01_activate_overlay.ipynb](../../notebooks/01_activate_overlay.ipynb) | Overlay, activate, surgical cutover |
| [02_fixtures_catalog.ipynb](../../notebooks/02_fixtures_catalog.ipynb) | Fixture catalog + attribution |
| [03_isolated_agent_evals.ipynb](../../notebooks/03_isolated_agent_evals.ipynb) | Mock isolated agent evals |
| [04_pipeline_and_scoring.ipynb](../../notebooks/04_pipeline_and_scoring.ipynb) | Connected pipeline + dojo v0.11.0 |
| [05_tracing_contract.ipynb](../../notebooks/05_tracing_contract.ipynb) | Langfuse v4 contract, public GT |
| [06_prompts_matrix_log.ipynb](../../notebooks/06_prompts_matrix_log.ipynb) | Prompts, fake client, matrix, experiment log |

```bash
pip install -e ".[dev]"
python -m jupyter execute notebooks/01_activate_overlay.ipynb
pytest tests/test_notebooks.py -q
```

<details>
<summary>Conventions</summary>

- First code cell: `find_repo_root()` walks up for `pyproject.toml` + `reports/` (works when the kernel cwd is `notebooks/`).
- [`notebooks/_lib.py`](../../notebooks/_lib.py) sets `OBSERVABILITY_PROVIDER=none` and redirects JSONL to `reports/notebooks/`.
- Mock `exact_match == 1.0` is **harness** proof. Model quality needs `--local`.
- Guard suite: [`tests/test_notebooks.py`](../../tests/test_notebooks.py) executes every notebook headlessly from a hostile cwd.

</details>
