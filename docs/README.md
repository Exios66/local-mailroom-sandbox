# Sandbox documentation

This is the index for everything under `docs/`. Each page sits in one place:
how-to guides and references at this level, design records under
[`design/`](#design-records), point-in-time reviews under [`audits/`](#audits),
and superseded material under [`archive/`](#archive). The root
[README](../README.md) is the overview; [`AGENTS.md`](../AGENTS.md) is the full
command and rule reference for contributors and coding agents.

Generated pages are never edited by hand: [`cli-reference.md`](cli-reference.md)
(`python scripts/check_cli_surface.py`), [`runbooks/`](runbooks/README.md)
(`config/runbooks/catalog.yaml` → `sandbox runbook write`) and
[`prompts/`](prompts/README.md) (the prompt catalog).

## Start here

| Page | What it covers |
| --- | --- |
| [Quickstart](setting-up/QUICKSTART.md) | Install, first mock and live run, the canonical workflows |
| [Sandbox guide](SANDBOX-GUIDE.md) | Long-form walkthrough of the offline sandbox |
| [Layout contract](setting-up/LAYOUT.md) | Which folder owns what, frozen surfaces, junk policy |
| [Providers](setting-up/providers.md) | OpenRouter (default), Modal vLLM, Ollama, local vLLM, llama.cpp, LM Studio |
| [Remote serving](setting-up/remote-serving.md) | Modal, SSH-tunnelled vLLM, CHTC, conda |
| [Docker offline](setting-up/docker-offline.md) | Dockerfile, Compose profiles, prep notebooks |
| [Sister repos](setting-up/sister-repos.md) | The Mailroom family map |
| [CLI reference](cli-reference.md) | Every command, subcommand and flag (generated) |

## Running experiments

| Page | What it covers |
| --- | --- |
| [Experiment workflow](experiments.md) | Paired designs, agent models, initials-gated spend, smoke, reports |
| [Campaign contract](EXPERIMENT-CAMPAIGN-CONTRACT.md) | The current rules every rb1 campaign run follows |
| [Jobs](jobs.md) | Preflight, immutable locks, execution, resume and dataset identity |
| [Evals](evals.md) | Runners, matrix, scoring and the experiment log |
| [Rescore](rescore.md) | Re-score a finished run against new truth, no model calls |
| [Autoresearch](autoresearch.md) | Config-only greedy lever search over locked runs |
| [Run cost derivation](RUN-COST-DERIVATION.md) | How a run is priced: OpenRouter tokens, Modal container time, caps |
| [Experiment figures](experiment-figures.md) | Per-run and sorter-vs-decision figures, the figure linter |
| [Runbooks](runbooks/README.md) | Operator runbooks generated from the catalog |
| [Modal serving ops](modal/modal-serving-ops.md) | Warm once, no waste: the Modal serving lifecycle |
| [Modal L4 benchmark kit](modal/benchmark-l4.md) | The Modal L4 Qwen benchmark |

## Data, labels and scoring

| Page | What it covers |
| --- | --- |
| [Named datasets](datasets/named-datasets.md) | Registry schema, paths, subset hashes, lock migration |
| [Datasets](datasets/README.md) and [dataset card](datasets/mailroom-dataset.card.md) | The mailroom-dataset corpus |
| [Staged label overlay](staged-label-overlay.md) | Production label overlay (rc.10 for slices; rc.11 with corporate subclass fields staged) |
| [Labeling guide](gold-labels/LABELING_GUIDE.md) | How gold labels are written |
| [Label EDA](label-eda.md) | `scripts/label_eda.py`: coverage, gaps, row pulls and where to label next |
| [Pain-point composites](pain-point-composites.md) | Per-document and per-experiment pain-point scores |
| [Decision model inputs](decision-model-inputs.md) | Decisions API reference, request formats, calibration splits |
| [Decision model input design](decision-model-input-design.md) | Draft 4.2.0 question set and its locked routing digest |
| [Extraction gate vetting](EXTRACTION_GATE_VETTING.md) | Question set 1.3.0 and the interim labels it was vetted on |
| [Dependency snapshots](dependency-snapshots.md) | Verified release caches, source selection, frozen provenance |

## Hotfixes

Fixes the sandbox needs before the owning repository ships them. They are
wrappers in `src/`, never edits to `vendor/`; each one is recorded in the run
lock, and preflight checks it.

| Page | What it covers |
| --- | --- |
| [Vendor hotfixes](vendor-hotfixes.md) | `HF-*`: pipeline fixes over the vendored llm-mailroom (`src/mailroom_sandbox/vendor_hotfixes.py`) |
| [Scoring hotfixes](scoring-hotfixes.md) | `SHF-*`: scoring fixes over the vendored Dojo (`src/mailroom_sandbox/scoring_hotfixes.py`), including retired ones |

## Watching and tracing runs

| Page | What it covers |
| --- | --- |
| [Pipeline floor](floor.md) | Live run history, simulated replay, document panel, troubleshooting |
| [Themed logging and live watch](pretty-logging/mailroom-themed-logging.md) | `sandbox watch` / `--web`, Modal log tail, verbosity |
| [Watch cheat sheet](pretty-logging/mailroom-watch-web.md) | Terminal TUI and browser UI keys |
| [Themed run logs](snippets/pretty_logs.md) | Log snippet conventions |
| [Tracing](tracing.md) | Langfuse data model, tags, The-Mailroom |

## Review, safety and agents

| Page | What it covers |
| --- | --- |
| [Critical regressions](critical-regressions.md) | Silent wrong scores, draws, models or costs: check every diff |
| [Campaign preparation regressions](campaign-preparation-regressions.md) | `CP-*` rows for rb1 campaign changes |
| [PR review lanes](pr-review-lanes.md) | Domain reviewer vs CodeRabbit, CodeAnt and CodeFactor |
| [Agent dispatch](agent-dispatch.md) | Execution identity, delegation, recovery, durable handoffs |
| [Instruction maintenance](agent-instruction-maintenance.md) | Routine validation of instructions, versions and references |
| [Subagent family sync](subagents-family-sync.md) | Roster sync across family checkouts |
| [Docs audit router](../.cursor/skills/docs-audit-tool-router/SKILL.md) | The full docs staleness sweep |
| [CI verification](../.circleci/README.md) | Required checks, artifacts, caches and runtime evidence |

## Design records

Plans, protocols and designs for a specific experiment or feature. They record
what was decided at the time; the guides above say how things work now.

| Ticket | Records |
| --- | --- |
| rb1 (SAND-108) | [Evaluation design v2](design/rb1/evaluation-design-v2.md), [original runbook plan](design/rb1/2026-11-18-evaluation-runbook-plan.md), [R13b smoke review](rb1-r13b-smoke-review.md) |
| SAND-042 | [Experiment design](design/sand42/experiment-design.md), [follow-up design](design/sand42/followup-design.md), [schema-adherence RCA](design/sand42/schema-adherence-rca.md) |
| SAND-043 | [Benchmark program](design/sand043/benchmark-program.md) (historical) |
| SAND-037 | [Specialist grid plan](design/sand037/specialist-grid-plan.md) |
| SAND-034 | [Prompt enhancement plan v2](design/sand034/prompt-enhancement-plan-v2.md) |
| DMR-068 | [L4 scale matrix protocol](design/dmr068/scale-matrix.md) |
| DMR-059 | [Modal doc-pipeline job queue](modal/modal-doc-jobs.md) |
| SAND-032 | [Serving ladder design](design/specs/2026-09-27-qwen3-l4-serving-ladder-design.md) and [plan](design/plans/2026-09-27-qwen3-l4-serving-ladder.md) |
| Job beacon | [Design](design/specs/2026-09-28-mailroom-job-beacon-design.md) |
| Decision reviewer | [Design](design/specs/2026-10-30-decision-model-reviewer-design.md) and [proof-of-concept plan](design/plans/2026-10-30-decision-reviewer-poc.md) |
| Production slice gate | [Design](design/specs/2026-11-16-production-slice-gate-design.md) and [plan](design/plans/2026-11-16-production-slice-gate.md) |
| Floor read ranges | [Design](design/specs/2026-11-25-floor-read-ranges-design.md) and [plan](design/plans/2026-11-25-floor-read-ranges.md) |
| Correspondence header truth | [Design](design/specs/2026-11-27-correspondence-header-truth-design.md) (approved; SHF-019) |
| Phase 1 spend safety | [Plan](design/plans/2026-11-26-phase1-spend-safety.md) |
| Phase 2 loop governor | [Plan](design/plans/2026-11-26-phase2-governor.md) |
| Phase 3 subclass extraction schemas | [Plan](design/plans/2026-11-26-phase3-subclass-schemas.md) |
| Phase 4 correcting judge | [Plan](design/plans/2026-11-26-phase4-correcting-judge.md) |
| Subclass field note for promoted specialist prompts | [Plan](design/plans/2026-11-27-subclass-field-note.md) |
| Correcting judge | [Design](design/specs/2026-11-26-correcting-judge-design.md) (draft) |
| Correcting judge upstream issues | [Drafts](design/specs/2026-11-26-correcting-judge-upstream-issues.md) for `llm-mailroom`, for the owner to file |
| Phase 5 attempt hygiene (OpenRouter route) | [Design](design/specs/2026-11-27-phase5-attempt-hygiene-design.md) and [plan](design/plans/2026-11-27-phase5-attempt-hygiene.md) |
| Numbering reservations | [Hotfix IDs and critical-regression rows](numbering-reservations.md) claimed by open PRs |

New design records go in `design/<ticket>/`, or in `design/plans/` and
`design/specs/` with a date prefix. Plans a tool writes to its own default
folder (the superpowers plugin uses one under `docs/`) move here before merging.

## Research

| Page | What it covers |
| --- | --- |
| [Modal vLLM measurement priorities](research/modal-vllm-measurement-priorities/summary.md) | Which Modal vLLM measurements to take first, with [measurements](research/modal-vllm-measurement-priorities/measurements.md), [deployment pipeline](research/modal-vllm-measurement-priorities/modal_pipeline.md), [model survey](research/modal-vllm-measurement-priorities/models.md) and a [2026-11-20 hotfix snapshot](research/modal-vllm-measurement-priorities/hotfixes.md) |

## Audits

Point-in-time reviews, named `YYYY-MM-DD-<topic>.md`. Their findings are not
revised later; an outcome is appended as a dated section.

| Date | Audit |
| --- | --- |
| 2026-11-26 | [Docs and repository layout](audits/2026-11-26-docs-and-layout-audit.md) |
| 2026-11-25 | [OpenRouter deployment and recent-main integration](audits/2026-11-25-openrouter-deployment.md) |
| 2026-11-25 | [Post-merge integration review](audits/2026-11-25-postmerge-review.md) |
| 2026-11-22 | [Main landing integrity](audits/2026-11-22-main-landing-integrity.md) |
| 2026-11-21 | [SAND-214 window learnings](audits/2026-11-21-sand214-window-learnings.md) |
| 2026-11-19 | [Experiment hotfix wiring follow-up](audits/2026-11-19-hotfix-followup.md) |
| 2026-11-16 | [Pre-E2 architecture review](audits/2026-11-16-pre-e2-architecture-review.md) |
| 2026-11-15 | [Contract recall routing ladder](audits/2026-11-15-contract-recall-routing-ladder.md) |
| 2026-11-15 | [`pipeline-qwen-flash-25` failure modes](audits/2026-11-15-pipeline-qwen-flash-25-failure-modes.md) |
| 2026-11-11 | [PR stack and open-issue audit](audits/2026-11-11-pr-stack-issue-audit.md) |
| 2026-11-10 | [Landed PR audit](audits/2026-11-10-landed-pr-audit.md) |

## Archive

Superseded pages, kept for their history.

| Page | Note |
| --- | --- |
| [Prompt enhancement plan v1](archive/prompt-enhancement-plan-v1.md) | Discussion draft; superseded by [v2](design/sand034/prompt-enhancement-plan-v2.md) |
| [SAND-042 issue updates](archive/sand42-issue-updates.md) | Paste-ready issue text; the issues are the record |
| [Correspondence extraction diagnosis](archive/extraction-quality-diagnosis.md) | Offline diagnosis for issue #21 |
| [OpenRouter sunset audit](archive/openrouter-sunset-audit.md) | SAND-024 call-site inventory, cited by `config/models.yaml` |

Release notes live in [`releases/`](releases/); the full history is the
[CHANGELOG](../CHANGELOG.md).
