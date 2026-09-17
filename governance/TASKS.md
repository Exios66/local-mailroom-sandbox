# Sandbox task board — local-mailroom-sandbox

Board for the sandbox's own mission work. Cross-family work stays on
llm-entity-extraction's MESSAGE_BOARD (AGENTS.md); this board tracks
sandbox-local cards only.

Lanes: `todo → in_progress → needs_attention → done` · Owner · UTC date.

## Mission: ACTUAL SORTER modal+vLLM — 50-subclass run (real, not mock)

Caller: human (mission brief, 2026-09-16). Goals: real Modal+vLLM run of the
DMR-066 subclass-stratified 50-row sorter eval, conservative credit burn,
contained in this repo until fully complete, then monorepo sync, then full
interpretation report.

Binding specs: `config/runs/run-50-subclass.yaml` (DMR-066; preflighted
14:21–14:25Z today, run never started), `deploy/README.md` (Modal vLLM
lifecycle, v0.29.0/L4/Qwen3-8B, DMR-062/063 evidence), `docs/jobs.md`
(run lifecycle), mission brief (GPU hard cap 2; real run; preflight/dry-run/
verify before spend; teardown after).

### Cards

| Card | Title | Owner | Status | Evidence |
|---|---|---|---|---|
| SANDBOX-050-1 | Verify stratified 50-subclass sample (counts/dups/schema/seed) | athena-database-agent protocol | **done** | DMR-072 nested sub_buckets strata (corpus.py + tests, 290 passed); QA: 10 per type × 5 types = 50, 35 subclass strata (insurance 6/6, contract 9/19, merger 4/4, correspondence 7/7, corporate 9/9), dups NONE, schema intact, lock sha 797b3e4d8aba == dataset.jsonl (preflight `rows=50`) |
| SANDBOX-050-2 | Amend run spec to caller GPU cap (max_containers 4→2) + lock | orchestrator (caller) | **done** | `config/runs/run-50-five-types.yaml` (DMR-072): max_containers 1 (cap 2), concurrency 8, scaledown 600, prewarm; preflight all checks ok, spec_hash da811d51…, modal_spec guard ok |
| SANDBOX-050-3 | Preflight + guards loud (HARD-fail paths, sim) | test-suite-auditor protocol | **in_progress** | preflight guards verified live (strata_guard/stata_draw_guard hard-fail; over-quota sub_bucket hard-fails — new unit tests); audit run-time gates next |
| SANDBOX-050-4 | Deploy sandbox-vllm (v0.29.0) + verify endpoint (models/401) | jarvis protocol + code-analyst | **in_progress** | pre-warm → deploy → /v1/models bearer probe → sandbox health |
| SANDBOX-050-5 | Run start → watch → completion (status polling, events) | test-suite-auditor protocol | todo | — |
| SANDBOX-050-6 | Teardown: app stop, zero containers verified, volumes persist | jarvis protocol | todo | — |
| SANDBOX-050-7 | Interpret: per-stratum accuracy, confusion, readiness | athena/lucius protocol | todo | — |
| SANDBOX-050-8 | Monorepo sync (contained, last step) + board close | atom protocol | todo | — |