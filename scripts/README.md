# Local Mailroom Sandbox scripts

Repository tools that are not `sandbox` subcommands. Run them from the repository
root with the project venv (`.venv/bin/python scripts/<name>.py --help`).
Scripts marked **spends** can start paid work (Modal deploys, `sandbox run start`
or OpenRouter calls); read them before running and expect a spend gate.

## Maintenance and generated files

| Script | What it does |
| --- | --- |
| `sync_requirements.py` | Generate `requirements/*.txt` from the `pyproject.toml` extras (`--check` in CI) |
| `check_cli_surface.py` | Generate or check `docs/cli-reference.md` from the parser (`--check` in CI) |
| `sync_vendor.py` | Refresh the vendor snapshots from monorepo workspace packages (see `/vendor-sync`) |
| `render_prompt_catalog.py` | Render `docs/prompts/`, the catalog of every eval-environment prompt version |
| `render_notebook_demos.py` | Execute the offline tour notebooks and write the demo copies |
| `sync_specialist_prompts.py` | Sync specialist production prompts into `config/prompts/` |
| `gen_maud_v2_prompt.py` | Generate the MAUD v2 merger specialist prompt (SAND-042 RCA) |
| `refresh_api_prices.py` | Refresh `config/api_prices.yaml` from OpenRouter's public catalog |
| `refresh_decision_models.py` | Refresh `config/decision_models.yaml` (Decisions-API models) |
| `refresh_provider_pins.py` | List OpenRouter providers for every model in `config/provider_pins.yaml` |
| `hf_tool.py` | Hugging Face helper tooling for the sandbox |
| `setup_t3.sh` | Guided local setup for a checkout, t3-code worktrees included |
| `mailroom-tui` | Launcher for the watch TUI and web viewer (`dev`, `web`, `score <run>`) |
| `monorepo/` | Digital-Mailroom package-sync hook and patch ([`INTEGRATION.md`](monorepo/INTEGRATION.md)) |

## Pre-flight and gates (offline)

| Script | What it does |
| --- | --- |
| `smoke_campaign.py` | Experiment-day pre-flight: mock specialist, `sand42` and pipeline campaigns must reach a 1.0 extraction headline ([guide](../docs/experiments.md#pre-flight-smoke-before-an-experiment-day)) |
| `check_hotfixes.py` | Check campaign hotfix fingerprints and installation, no models or network |
| `check_g0.py` | rb1 G0 checkpoint: run every Phase 0 gate, one line each |
| `check_r01_smoke.py` | rb1 R01 gate: every smoke model's calls went to its pinned provider and model |
| `estimate_spend.py` | Estimate planned runs' OpenRouter spend against the key's remaining limit |

## Labels, splits and datasets

| Script | What it does |
| --- | --- |
| `gold_labels.py` | Gold-label work queue, labeler batches, validation and catalog build |
| `interim_labels.py` | Build and check the interim label overlay (`data/labels/interim/`) |
| `stage_label_overlay.py` | Stage merged label repairs as a production-scoring overlay |
| `pull_staged_overlay.py` | Fetch a pinned staged overlay into the local label cache |
| `export_mailroom_cache.py` | Export the repaired label sets to the mailroom-issues `mailroom_cache` |
| `build_excluded_ids.py` | Build the committed held-out exclusion list from prompt-tuning runs |
| `build_split_exposure.py` | Build a split's exposure list |
| `build_gold_audit_sheet.py` | Build or summarise an R03 gold-label audit sheet |
| `build_scorer_handcheck.py`, `check_scorer_handcheck.py` | Build the R02 scorer hand-check sheet, then replay it through the scorers |
| `gt_label_ex10.py` | Label the v9.1 SEC EDGAR EX-10 gap in CUAD span form |
| `build_a100_manifest.py` | Per-leg A100 run manifest (DMR-078) |

## Analysis of finished runs (no model calls)

| Script | What it does |
| --- | --- |
| `calibrate_reviewer.py` | Pick each class's decision-reviewer cutoff from a finished calibration run |
| `compare_sorter_arms.py` | LLM sorter vs Decisions-API sorter, paired, with figures ([guide](../docs/experiment-figures.md)) |
| `compare_specialist_prompt.py` | Compare a specialist prompt run with its reference run |
| `compare_sorter_prompt.py` | Validate a new sorter prompt run against the saved V14 pass |
| `extraction_gate.py` | Build extraction-gate input rounds and calibrate a finished gate run against the Dojo |
| `export_sorter_handoff.py`, `patch_sorter_handoff.py` | Save a sorter pass as a reusable handoff; correct and score its targets |
| `ladder_pair_report.py` | Paired control/treatment report for two finished ladder runs |
| `rb1_build_form_controls.py`, `rb1_form_floor.py` | rb1 R13b document-form controls and the park-floor fit |

## Campaign scripts

`sand032/` (SAND-032 serving ladder) and `sand42/` (SAND-042 grid) hold the
scripts those campaigns still cite: report generators, the chart kit, re-scoring,
spend ledgers and the per-run drivers. `sand032/run_one.sh`,
`sand42/parallel-fleets.sh` and `sand42/topup-one-class.sh` **spend**.
`sand032/rerender.py --check` runs in CI. Retired campaign scripts are under
[`archive/`](archive/README.md).
