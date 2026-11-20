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
| [`models.yaml`](models.yaml) | Serving/model catalog (providers, quantization, GPU) — and the **Modal experimental-model ledger** (`modal_models:`) |
| [`api_prices.yaml`](api_prices.yaml) | **CORE OpenRouter cost ledger**: verified price sheets for every experimental chat candidate (refresh: `python scripts/refresh_api_prices.py [--add MODEL]`, `--check` shows drift) |
| [`decision_models.yaml`](decision_models.yaml) | **CORE Decisions cost ledger**: every Decisions-API model under consideration, pinned id + canonical slug + input price (refresh: `python scripts/refresh_decision_models.py [--check]`) |
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
> Both run-spec trees use `sandbox.run/v1` and the shared loader/preflight;
> choose the entry point for its registration and reporting workflow.
> See
> [`../docs/setting-up/LAYOUT.md`](../docs/setting-up/LAYOUT.md).

## Candidate model ledgers — one entry point each

Three ledgers name every model under consideration; a new candidate is one
command or one row, and the ledgers are enforced (a candidate with no verified
price or no serve posture fails the suite):

1. **OpenRouter chat candidates — `config/api_prices.yaml`.** Refresh every
   sheet from the live catalog and add a candidate in one step:
   `python scripts/refresh_api_prices.py --add <org/model>` (`--check` shows
   drift; no workflow runs it, so run it before a paid run). The built-in
   fallback sheets in `src/mailroom_sandbox/job/metrics.py` mirror the file —
   keep both in the same commit.
2. **Decisions-API candidates — `config/decision_models.yaml`.** The catalog is
   OpenRouter's decisions endpoint; refresh with
   `python scripts/refresh_decision_models.py` (`--check` for drift,
   `--from-json` offline). A decision reviewer may name only ids this file
   lists, pinned (no moving aliases).
3. **Modal candidates — `config/models.yaml` `modal_models:`.** One row per
   candidate with `gpu`, `quantization`, `max_model_len`, `tp_size` and
   deployment notes; pair it with the twin OpenRouter id priced in
   `api_prices.yaml` where the weights are the same (e.g. the SAND-027 Granite
   pair). The invariants live in `tests/test_api_prices.py`
   (`test_every_models_yaml_openrouter_id_is_priced_or_a_decisions_model`,
   `test_every_modal_models_row_carries_a_serve_posture`).

The api-evals harness (separate tree) resolves its cost fallback from the CORE
`api_prices.yaml` — it carries no second price pin — and its run specs resolve
the lineage frontrunner prompt at preflight, so they never run a superseded
stem. See [`api-evals/README.md`](../api-evals/README.md).

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
