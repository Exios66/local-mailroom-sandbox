# Repository layout contract

**Audience:** anyone asking "which folder do I put this in / edit?" — and the
next agent auditing the tree. This file records *why* the tree looks the way it
does, so a future restructure does not have to re-derive it.

Scope note: this document describes the **local-mailroom-sandbox** repo only. The
org-owned `LLM-Mailroom-Services/eval-environment` repo is a separate tree with
its own layout, and `api-evals/` deliberately mirrors its *structure* (see
[Two config trees](#two-config-trees) below).

## Top level

| Path | Purpose | Owner / stability |
| :--- | :--- | :--- |
| `src/mailroom_sandbox/` | The installed package (`pyproject.toml` `[tool.setuptools.packages.find] where = ["src"]`) | **Frozen path.** Editable-installed; `sandbox` entry point lives here. |
| `tests/` | Network-free suite; opt-in `local_llm` tests need `SANDBOX_LOCAL_LLM=1` | **Frozen path.** Full-suite/coverage execution belongs in hosted CI. |
| `vendor/` | Byte-identical tracked snapshots of the family code | **Frozen tree.** See [Frozen surfaces](#frozen-surfaces-dont-move-these). |
| `config/` | Serving profiles, run specs, named-dataset registry, runbook catalog, prompts, model catalog, subagent roster | **Frozen paths.** See [Frozen surfaces](#frozen-surfaces-dont-move-these). |
| `.circleci/` | Hosted checks, caches, explicit pytest worker scheduling; [CI guide](../../.circleci/README.md) | CI configuration and operator documentation. |
| `deploy/` | Dockerfile, compose profiles, Modal vLLM + Modal job worker, htcondor, conda | **Frozen path** — `deploy/modal_vllm.py`, `deploy/teardown_vllm.sh` etc. are cited by runbooks, docs, and the board. |
| `docs/` | Guides (`setting-up/` onboarding, `pretty-logging/` Tray TUI watch, runbooks, modal) | **Frozen path** (add freely; keep the nested trees). |
| `scripts/` | Repo tooling (`sync_vendor.py` and friends) | **Frozen path.** |
| `governance/` | `SAND-*` board + prefix cheat-sheet + archives | **Governed surface** — asserted by `tests/test_governance_sand.py`. |
| `reports/` | Offline experiment log (`experiment_log.jsonl` / `.md`) + hand-written run reports; `reports/dashboard/` builds the source-verified reports hub (`build_hub.py`) and the [pipeline floor](../floor.md) (`build_floor_digest.py`, `floor.template.html`) | Sandbox-local; **not** a sister-repo mirror (the hub pins sibling-repo figures in `external_snapshot.json`). |
| `data/` | `fixtures/` tracked; `cache/` (including [verified dependency snapshots](../dependency-snapshots.md)), `runtime/`, `memory/`, `*.db` gitignored runtime state | Layout is stable by design. |
| `notebooks/` | Offline env setup + data prep + mock smoke | **Frozen path.** |
| `api-evals/` | Self-contained OpenRouter API cost harness (own config tree + own CLI) | See [Two config trees](#two-config-trees). |
| `.cursor/skills/`, `.opencode/agents/` | Agent skill + subagent surfaces | **Frozen** — see [Frozen surfaces](#frozen-surfaces-dont-move-these). |

## Two config trees

There are **two** run-spec trees and **two** CLIs. They are deliberately
separate; the split is architecture, not accident.

| | Main sandbox | `api-evals/` |
| :--- | :--- | :--- |
| Run specs | `config/runs/*.yaml` (+ `config/runs/suites/`) | `api-evals/config/runs/api-*.yaml` |
| Engine kinds | `vllm-local`, `vllm-remote`, `modal-vllm`, `openrouter`; hybrid per-agent routes | `openrouter` only |
| Cost model | `cost_cap_usd` for GPU-wall estimates; separate `api_cost_cap_usd` for API token spend | `cost_cap_usd: null` by design; real cost = tokens × live OpenRouter list price |
| CLI | `sandbox run …` (`pyproject.toml` console script) | `python api-evals/run_api_evals.py …` |
| Outputs | `reports/` | `api-evals/reports/<stamp>-<model>/` |
| Packaged in the wheel | Python package under `src/`; run/config trees remain checkout assets | **no** — repo-local harness |
| Shipped in the offline image | yes (`COPY config ./config`) | **no** — `deploy/Dockerfile` never copies `api-evals/` |

**Which do I use?** Sandbox pipeline, specialist, reviewer and hybrid runs use
`config/runs/` and the `sandbox` CLI, including paid OpenRouter routes with
their [API budget gates](../jobs.md). Use `api-evals/` for its separate API
task harness (`api-*` run ids and `run_api_evals.py`). Both trees declare
`schema: sandbox.run/v1` and use the same
[`load_run_spec`](../../src/mailroom_sandbox/job/spec.py). The API harness
also calls the shared preflight and job runner in
[`invoke.py`](../../api-evals/api_evals/invoke.py). The separation concerns
task registration, report paths and the operator workflow, rather than an
incompatible schema. Inspect model, dataset and current budget settings
before moving a spec between workflows.

**Why the three reasons above matter:**

1. **Spend surface.** `api-evals/config/runs/*.yaml` sets `cost_cap_usd: null`
   — it is not a cap on API token spend. These historical specs still pass
   through shared preflight: paid API execution needs `api_cost_cap_usd`,
   `max_wall_seconds` and model pricing under the current
   [budget rules](../jobs.md). A schema-valid YAML or a null GPU cap does not
   prove that live execution is ready.
2. **Distribution.** `api-evals/` is not in the installed package and not in the
   offline image. Its task registry, CLI and reporting helpers remain
   checkout-only. The installed sandbox itself supports OpenRouter and reads
   `OPENROUTER_API_KEY`; the separate harness directory does not define that
   provider's availability.
3. **Fidelity.** `api-evals/` mirrors the org `eval-environment` structure
   (task registry + case loader + live invoker + scoring + report) so the two
   repos read alike. Its path assumptions are explicit and deliberate in
   `api-evals/api_evals/registry.py` (`CONFIG_DIR`, `RUNS_DIR`, `REPORTS_DIR`).

Note: `spec_hash` covers only behavioral content — task, profile, engine, job,
trace, prompt, dataset — and **not** the spec's file path
(`src/mailroom_sandbox/job/spec.py`, `spec_core()`), and the immutable
`data/runtime/runs/<run_id>/spec.lock.json` records no source path either. So
relocating a run YAML is hash-neutral; *editing* one is not.

## Frozen surfaces (don't move these)

Each of these is load-bearing for a test or a tool, not a style preference:

| Surface | Enforced by |
| :--- | :--- |
| `vendor/llm-mailroom/`, `vendor/llm-dojo-scoring/` | `tests/test_vendor_drift.py` (byte-identity + `VENDOR.md` pin); `src/mailroom_sandbox/__init__.py` puts their `src/` trees on `sys.path` |
| `governance/{README,PREFIX,TASKS}.md`, `governance/archive/SANDBOX-050.md` | `tests/test_governance_sand.py` |
| `.cursor/skills/` | `tests/test_skills.py` |
| `.opencode/agents/**` | `sandbox subagents sync` / `materialize` |
| `config/prompts/` | Prompt **stems** are referenced by name from `config/runs/*.yaml` and `job/specialist_posture.py`; `eval_environment_lineage.json` sha256-locks the five specialist stems to eval-environment frozen v1. Frozen lineage — never rename or rewrite. |
| `config/models.yaml`, `config/profiles/`, `config/runs/`, `config/runbooks/`, `config/subagents/` | Read by `modal_matrix`, `overlay`, `job/suite.py`, `job/runbooks.py`, `job/specialist_posture.py` |
| `src/mailroom_sandbox/`, `pyproject.toml`, `tests/` | Editable install + test discovery |

Stale-pin hygiene is itself a test: `tests/test_vendor.py` sweeps every tracked
`.py/.md/.yaml/.yml/.sh` file and fails on superseded vendor version claims — so
keep version numbers out of prose that isn't about the current pin.

## Junk sweep

Build detritus is **gitignored and safe to delete**:
`__pycache__/`, `.pytest_cache/`, `*.pyc`, `src/mailroom_sandbox.egg-info/`
(regenerated by any `pip install -e`), and empty dirs under `data/runtime/`
(`prep.py`'s `prepared_dir()` re-creates its own dir with `mkdir(parents=True,
exist_ok=True)`).

**Not junk — do not delete:** `.env` (gitignored secrets), `data/mailroom.db`
and `data/cache/` (runtime state), `reports/experiment_log.*` (the
reproducibility record behind `run_api_evals.py report --from-log`; see
`SAND-027-9`), and the tracked report archives under `reports/archive/`.
History value → propose on a board card, never sweep.
