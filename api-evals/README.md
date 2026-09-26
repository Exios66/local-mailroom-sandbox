# api-evals — OpenRouter API cost comparisons

A self-contained subdirectory that runs **comparable specialist evals through
the OpenRouter API** — the same samples and the same prompts the sandbox runs
on Modal vLLM, but with **real API costs** per run.

Mirrors the org-owned
[`LLM-Mailroom-Services/eval-environment`](https://github.com/LLM-Mailroom-Services/eval-environment)
structure (task registry + case loader + live invoker + scoring + report), but
scoped to this sandbox repo and coded for OpenRouter only.

## What runs

| Task | Agent | N docs | Prompt stem (same as Modal runs) |
| --- | --- | --- | --- |
| `api-contracts-20` | `contracts_specialist` | 20 | `contracts_specialist_v33_simplified` |
| `api-contracts-40` | `contracts_specialist` | 40 | `contracts_specialist_v33_simplified` |
| `api-contracts-100` | `contracts_specialist` | 100 | `contracts_specialist_v33_simplified` |
| `api-correspondence-20` | `correspondence_specialist` | 20 | `correspondence_specialist_simplified` |
| `api-correspondence-40` | `correspondence_specialist` | 40 | `correspondence_specialist_simplified` |
| `api-correspondence-100` | `correspondence_specialist` | 100 | `correspondence_specialist_simplified` |

Every run spec (`api-evals/config/runs/*.yaml`) is **byte-comparable** to the
sandbox Modal specialist YAMLs:

- the dataset block is the same draw method — `split: all`, class bucket
  `count: N`, `sample_seed: 42`, pinned revision `46a4d3c2…` (the
  `run-20-contracts*` / `run-20-correspondence*` draw);
- the prompt pin is the same local stem (SAND-026 simplified);
- the only difference is the engine: `profile: openrouter`, `model:
  qwen/qwen3.7-flash` — the OpenRouter champion the sandbox maps the Modal
  `Qwen/Qwen3-8B` workhorse onto (`config/models.yaml`), so cost numbers are
  like-for-like against the Modal rows.

## Cost honesty

- **Real API cost** = per-item tokens × the **live OpenRouter list price**
  (refreshed from `GET /api/v1/models` at run time; verified against a real
  response's `usage.cost` on 2026-09-25: 17×$0.03 + 5×$0.13 per 1M = $1.16e-6).
- If the live refresh fails, the registry pin (`$0.03/$0.13 per 1M`) is used;
  if neither resolves, cost fields are `None` with an honest gap — never $0.
- `cost_cap_usd` is deliberately **disabled** on these run specs: that cap is
  a Modal GPU-wall estimate and would be meaningless (and wrong) for an API
  run. The wall cap (`max_wall_seconds`) remains the safety guard.

## Usage

```bash
# 0. one-time: API key (gitignored .env — never commit)
#    OPENROUTER_API_KEY=sk-or-v1-...  SANDBOX_PROFILE=openrouter

cd api-evals

# list registered tasks
python run_api_evals.py list

# run ONE task live (real OpenRouter spend, ~document-count x sub-cent)
python run_api_evals.py run api-contracts-20

# run all six
python run_api_evals.py run-all

# rebuild the report from reports/experiment_log.jsonl (no new spend)
python run_api_evals.py report --from-log
```

Outputs land in `api-evals/reports/<stamp>-<model>/` (`report.json`,
`report.md`, `costs.csv`) and per-item rows also append to the sandbox
experiment log (`reports/experiment_log.jsonl`) via the existing whole-run
path.

## Same-sample guarantee

The draw is deterministic per spec (`sample_seed: 42`, canonical sort,
per-stratum sub-seeded draws — `mailroom_sandbox.corpus.select_rows`), so the
20-doc API draw is the **exact same 20 docs** the Modal `run-20-*` YAMLs
score. The dataset lock records the sha256 + `strata_actual` per run.

## Why a separate engine kind

The run specs use `engine.kind: openrouter` (added to
`mailroom_sandbox.job.spec.EngineSpec`), so an API eval declares itself
honestly instead of masquerading as a vLLM profile in the spec hash.
