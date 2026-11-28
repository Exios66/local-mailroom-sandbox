# OpenRouter production launch review (2026-11-28)

Before the production slice ladder (`config/runs/production/slice-0100.yaml`, then 250, 500 and
full) ran on OpenRouter, two independent reviewers (`{"model": "claude-fable", "role": "review"}`)
checked it against `main` at `5425e375`. One read the code path, and the other checked operational
readiness: configs, pins, prices, the label cut, the draw and the runbook. Neither made a paid or
live call. Both returned **GO with fixes**.

Each item is tagged with how it was established:

- **ran:** verified by running a command offline;
- **read:** inferred from the code;
- **not verified:** could not be checked here.

## Verified as working

- **Tests (ran).** 26 focused test files: 967 passed and 2 skipped (sibling workspace packages
  absent). The files cover the call guard, API budget, provider pins, Decisions transport, job
  spec, spend authorisation, production slices, the ranked draw, exclusions, the staged overlay,
  vendor drift, vendor and scoring hotfixes, pipeline concurrency, the gate, the gate audit,
  tracing, preflight, the runner, agent routes, the context plan and the corpus.
- **Commands (ran).**
  - `sandbox pilot --mock`: exit 0.
  - `sandbox doctor`: its only failure is the unset `OPENROUTER_API_KEY`.
- **Specs and prices (ran).**
  - All four slice specs load. Every agent, including the routed judge and boss, resolves to
    `qwen/qwen3.7-flash` on OpenRouter, and the reviewer is `openai/gpt-6-luna-decisions`.
  - Both models are priced, the budget checks pass, and the call ceiling is 40.
  - The GPU `cost_cap_usd` is inert (no GPU fleet).
- **Hotfixes (ran).** HF-001 to HF-029 are applied; HF-005 is unavailable, which preflight
  allows. SHF-001 to SHF-019 are current; there is no SHF-014.
- **Staged cuts (ran).** `--check` passes for rc.9 (`a639ffbd368d`), rc.10 (`b7dc80a16037`) and
  rc.11 (`0221334254c3`).
- **The draw (ran), reproduced offline:**
  - 100, 250, 500 and 3,115 rows, with class counts equal to the configs;
  - all 187 excluded ids matched, and none is drawn;
  - the slices nest;
  - the Hub-cache path and the file path give the same ids and dataset sha (`48eee6163395` for
    slice 100).
- **Offline preflight (ran)** on 0100, 0250, 0500, full and the 0100 Modal twin. Every check is
  `ok` except `engine_spec`, which fails because no key is set here.
- **Spend estimate (ran).** From the drawn text at tier prices, against each slice's cap:

  | Slice | Estimate | Cap |
  |---|---|---|
  | 100 | $0.42–0.54 | $2 |
  | 250 | $1.05–1.35 | $5 |
  | 500 | $2.05–2.72 | $10 |
  | full | about $12.4 | $70 |

- **Unscorable documents under rc.10 (ran).** Only corporate records fall below 2 labelled
  fields: 1, 1, 4 and 8 per slice. Under rc.11 the counts are 0, 0, 0 and 3. rc.11 draws the same
  ids.

## Fixed in the same change

- **A run could spend and leave no span mirror (blocker; ran).**
  - `run start` mirrors every span to `data/traces/<run_id>.spans.jsonl.gz`, and
    `sandbox run gate` fails its audit without that file.
  - The mirror needs the OpenTelemetry SDK, which is in the `[observability]` extra, not
    `[dev]`. `otel.configure_tracing` only logged a warning when the SDK was missing.
  - Preflight now refuses a non-mock endpoint run without the SDK (check `trace_sink`), offline
    too, and `sandbox doctor` reports it as `span-mirror`.
- **The runbook's operator steps.** [`production-slices.md`](../runbooks/production-slices.md)
  now covers:
  - the install, key, overlay and doctor prerequisites;
  - a fresh run id;
  - `SANDBOX_SERVED_LOG` and the price check;
  - what to do when a run stops;
  - the corrected corporate unscorable counts, exclusion count, preflight probe behaviour and
    `claim_type` note.

## Open, not blocking slice 100

- **Cap race at concurrency 10 (ran; PR #441).**
  - `call_guard.settle` releases a success's hold before `after_call` prices it. A toy demo
    reached 1.66x its cap.
  - Exposure: at most one call per in-flight document escapes, and only once the run is already
    at its cap, which fails the gate anyway. The key's $3 reserve is a second bound.
  - #441's per-thread hold can leak when usage is never recorded. Land it after hosted CI, with
    a test for a success that is settled but never priced, before slices 500 and full.
- **A resume could under-count spend (read; fixed for job runs, see below).**
  - When several documents failed together, only the first one's billed usage was persisted
    (`eval/runners.py`, `job/runner.py`). A resume seeds its budget from persisted records.
  - Job runs now persist each failed document as an error row with its usage.
- **Fixed later the same day: `job.fail_fast` and `job.max_retries` did nothing for `task: pipeline`.**
  - Before: one document exception stopped new documents, and that document got no item row.
  - Now: a document that raises runs again up to `max_retries` times (never after a call-guard
    refusal or once a cap is reached). One that still raises is an error row carrying its billed
    usage, and only `fail_fast` stops the run. A resume re-runs it, and the answer replaces the row.
    Each failed document's usage is now on its own row, which also closes the resume under-count above
    for the job runner path.
- **Fixed later the same day: served-model evidence was kept only with `SANDBOX_SERVED_LOG`.**
  - Now every ledger row of a run goes to the run store's `served.jsonl` (archived and pulled from
    Modal), each pipeline item has `pred.served_calls`, and the report reads both logs and counts a
    call once (`call_id`).
  - Still open: the `qwen/qwen3.7-flash` pin has no `canonical_slug`, while the price sheet lists
    `qwen/qwen3.7-flash-20260727` (not verified live). A dated served model is therefore a
    `mismatch` row, visible but not fatal.
- **Fixed later the same day: a failed provider-pin activation left the per-call guard off.**
  - Now `run start` refuses a run with `job.api_cost_cap_usd` when any wrapper is not installed
    (`provider_pins.spend_guard_missing`).
- **Notes (read):**
  - `max_wall_seconds` is checked only between documents, so in-flight documents can run up to
    their own one-hour deadline.
  - The cap is part of the lock, so a capped run cannot resume with a higher cap.
  - `api_budget.spec_api_models` omits the reviewer, which affects advice only; the lock path
    includes it.
  - `budget_advice` sizes from `dataset.limit`, which strata draws leave unset.
  - A non-OpenRouter `OPENROUTER_BASE_URL` disables the pins and the per-call guard.
- **Modal twins (read).** The worker gets no label cache and the Modal steps do not ship one.
  This is not on the slice-100 path.

## Not verified here

- A full preflight that writes a lock (no OpenRouter key here).
- Real OpenRouter response shapes: the served `model` string, the Decisions `usage` keys and
  `usage.cost`.
- Whether the models exist on OpenRouter today. `preflight --live` and
  `scripts/refresh_api_prices.py --check` are the operator's checks.
