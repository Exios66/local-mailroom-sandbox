# Offline sandbox notebooks

A guided, **network-free** tour of the sandbox: set up the environment, prepare the
fixture corpora, run a mock smoke eval and browse the results. None of these notebooks
launches paid or remote work, and none needs a model server.

| # | Notebook | What it does | Writes (all gitignored) | Time |
| --- | --- | --- | --- | --- |
| 01 | [`01_offline_environment_setup`](01_offline_environment_setup.ipynb) | Versions, `.env`, profile activation, Dockerfile/Compose/fixture checklist, opt-in provider probe | `.env` (only if missing), `data/runtime/taxonomy.yaml` | ~5 s |
| 02 | [`02_load_clean_prepare_data`](02_load_clean_prepare_data.ipynb) | Load, clean and validate the fixture catalog, HF slice and agent gold; check gold grounding; overview charts | `data/runtime/prepared/` | ~5 s |
| 03 | [`03_offline_sandbox_smoke`](03_offline_sandbox_smoke.ipynb) | Dry-run plans, mock sorter eval, mock pipeline pilot through the vendored graph | `data/` run store, `data/runtime/notebooks/experiment_log.jsonl` | ~10 s |
| 04 | [`04_experiment_log_explorer`](04_experiment_log_explorer.ipynb) | Read-only table, summary and charts of experiment-log records | nothing | ~2 s |

Run them in order. 02 and 03 each recreate what they need if an earlier notebook was
skipped, but 01 is where setup problems are explained.

## Run them

**On the host** (Python 3.11+):

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,notebooks]"
```

```bash
.venv/bin/jupyter lab notebooks/
```

Choose that venv's kernel. Jupyter starts kernels in `notebooks/`, and the shared
bootstrap finds the checkout from there.

**In Docker** (the image already has the `[notebooks]` extra):

```bash
sandbox up -d --compose-profile jupyter
```

Then open <http://127.0.0.1:8888/lab>. Add `--compose-profile ollama` (and
`--compose-profile langfuse`) to run the local model and trace stacks alongside it. See
[`docs/setting-up/docker-offline.md`](../docs/setting-up/docker-offline.md).

**Headless**, for example to check that they still run after a change:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --output-dir /tmp/nb-out notebooks/0*.ipynb
```

The same check runs in `tests/test_notebooks.py`. Without `nbclient` (part of the
`[notebooks]` extra) only the structure checks run.

## What every notebook does first

The first code cell calls `mailroom_sandbox.notebook.bootstrap()`, which:

- finds the checkout from the kernel's working directory and sets `SANDBOX_ROOT`.
- makes `MAILROOM_BASE_DIR` **absolute**. The `./data` from `.env` is relative, so left
  as is it would put run stores in `notebooks/data/`. Delete that folder if an older
  notebook version created it.
- uses the **`ollama`** profile unless the kernel was started with `SANDBOX_PROFILE`
  (Compose's `jupyter` service sets it). `.env`'s `modal-vllm` default is ignored.
- sets mock mode, `OBSERVABILITY_PROVIDER=none` and `LOG_LEVEL=WARNING`.

Eval records from notebook 03 go to `data/runtime/notebooks/experiment_log.jsonl`, not
`reports/experiment_log.jsonl`, so mock rows never mix with real runs.

## Environment switches

Set these before starting Jupyter (or in the Compose environment):

| Variable | Default | Effect |
| --- | --- | --- |
| `SANDBOX_PROFILE` | `ollama` | Profile that the notebooks activate |
| `SANDBOX_NOTEBOOK_LOG` | notebook log | `reports` appends to `reports/experiment_log.jsonl`; any other value is a JSONL path |
| `SANDBOX_NOTEBOOK_LOG_VIEW` | `notebook` | Log that notebook 04 reads: `notebook`, `reports` or a path |
| `SANDBOX_NOTEBOOK_OBSERVABILITY` | `none` | Trace sink for notebook runs, e.g. `langfuse` with the Compose stack up |
| `SANDBOX_NOTEBOOK_PROBE` | unset | `1` runs notebook 01's provider probe (local endpoints only) |
| `LOG_LEVEL` | `WARNING` | Pipeline log level inside notebooks |

## Reading the results

- **Mock scores are 1.0 by construction.** The mock sorter echoes each row's gold class,
  and the mock pipeline uses a fake LLM with oracle routing. They check plumbing, not
  model quality.
- Compliance fixtures stop at `review` (`compliance_filing` is not in the taxonomy,
  because the compliance specialist is retired). They lower the pipeline's
  `extraction_overall` and `schema_valid_rate`.
- Notebook 02's grounding cell fails if an extractive gold value does not appear in its
  document. Fix such a row in `data/fixtures/manifest.csv`.

For a real local model, run `sandbox pilot --local --profile ollama` on the host with
Ollama running. Paid work (Modal GPUs, OpenRouter) goes only through
`sandbox run preflight` and `sandbox run start`. See `CLAUDE.md`.

## Editing the notebooks

- Commit them **without outputs** (`jupyter nbconvert --clear-output --inplace notebooks/*.ipynb`).
  `tests/test_notebooks.py` checks this and that every cell has an id.
- Put reusable logic in `src/mailroom_sandbox/notebook.py` (with tests in
  `tests/test_notebook.py`), not in cells.
- `ruff check notebooks` lints them with the repo's correctness rules.
- Keep the file names: `tests/test_prep.py` and the docs refer to them.
