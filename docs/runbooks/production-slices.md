# Production slices: launch, gate, fix, step up

This runbook covers how a production run is approved. Each run is a CLI-launched pipeline run over a fixed, held-out slice of the Hugging Face mailroom dataset (pin `ff4ca546`, Hub tag v9.3, 3,302 rows), and it passes the **slice gate** before the next, larger slice runs.

- Design: [`docs/design/specs/2026-11-16-production-slice-gate-design.md`](../design/specs/2026-11-16-production-slice-gate-design.md)
- Tracker: Exios66/local-mailroom-sandbox#305
- Fix backlog: Exios66/local-mailroom-sandbox#306
- Launch readiness: [the 2026-11-28 OpenRouter launch review](../audits/2026-11-28-openrouter-production-launch-review.md)
- Earlier state and next actions: [`production-readiness-handoff.md`](production-readiness-handoff.md) (2026-11-16; its run ids and counts predate the rc.10 draw)

This page is hand-written. It is not generated from `config/runbooks/catalog.yaml`.

## Slices

All slices keep r3's (`config/runs/pipeline-qwen-flash-25-fit-r3.yaml`) agent routes and knobs, confidence block and other prompts. They differ from r3 in:

- the label source: the pinned staged overlay instead of `interim_labels: true` (below);
- the dataset revision: `ff4ca546` (Hub `v9.3`, which the overlay is built on) instead of r3's `bc9eab28`;
- the correspondence prompt: `correspondence_specialist_condensed_v3` instead of r3's `condensed_v2`;
- `job.require_expanded_inputs: true`: preflight fails if a long-context reader is still on the short input budget;
- the draw (size, `sample_seed: 3302`, `draw: ranked`, the exclude list) and the caps.

The settings the slices run with:

- blind routing and the pinned staged label overlay (`dataset.staged_overlay: 9.3.1-rc.12`, which replaces r3's `interim_labels: true`; pull it first with `python scripts/pull_staged_overlay.py --version 9.3.1-rc.12`, see [the staged overlay guide](../staged-label-overlay.md); new preparations use the verified rc.12 cut, which carries the corporate subclass fields and the rc.12 contract and corporate label rounds; existing run locks retain their approved version);
- the adopted condensed specialist prompts;
- the Luna Decisions reviewer;
- `qwen/qwen3.7-flash` on OpenRouter;
- `sample_seed: 3302`, with per-class strata.

The draws are nested, so a smaller slice is a subset of the next. Every document listed in `config/production/excluded-ids.txt` (via `dataset.exclude_ids_file`) is dropped before the draw.

The list holds 187 documents; its header names the run each one came from (`scripts/build_excluded_ids.py`).

Contracts are drawn on either kind of truth (`dataset.task_gt_min_field_labels: 2`). A contract with
CUAD labels qualifies as before. A contract whose CUAD map is empty qualifies when the pinned staged
cut gives it at least 2 field labels, the gate's `min_labelled`. SHF-016 scores such a contract on
those field labels, and the gate counts them. So the contract labels from the label repair and
expansion campaign are measured, not left out of every slice. With `9.3.1-rc.10`, `9.3.1-rc.11` and `9.3.1-rc.12` alike (the same draw), all 91 CUAD-empty
contracts qualify, with 3 to 9 field labels each. They take 3 of the 18 contract places in slice 100,
7 of 45 in slice 250 and 14 of 91 in slice 500, and slice-full gains all 91. No other class changes,
and the slices still nest. The set follows the pinned cut, so a run locked before this change, or on
another cut, refuses resume rather than drawing a different set.

The slices use `dataset.draw: ranked`. Each class bucket is ordered by a per-document hash rather than shuffled, so adding ids to the list keeps the rest of every slice in place. Only the documents that were removed are replaced, and the slices stay nested. The default `shuffle` draw would reshuffle the whole bucket.

| Config (`config/runs/production/`) | Documents | contract / corporate / correspondence / insurance / merger | `api_cost_cap_usd` | `max_wall_seconds` |
|---|---|---|---|---|
| `slice-0100.yaml` | 100 | 18 / 14 / 30 / 33 / 5 | 2 | 7,200 |
| `slice-0250.yaml` | 250 | 45 / 34 / 76 / 83 / 12 | 5 | 10,800 |
| `slice-0500.yaml` | 500 | 91 / 68 / 151 / 167 / 23 | 10 | 14,400 |
| `slice-full.yaml` | 3,115 (every remaining row) | 566 / 417 / 945 / 1,045 / 142 | 70 | 86,400 |

Each of 100, 250 and 500 has a `*-modal-host.yaml` twin. A twin differs only in `run_id` and `job.mode: modal`: the Modal `sandbox-job` worker runs the job, and every model call still goes to OpenRouter. The worker gets `OPENROUTER_API_KEY` from its deploy Secret, so deploy it from a shell that has the key set (see "Modal job-host parity" below). A run that never calls OpenRouter has the key removed on the worker.

## Bars

The bars live in [`config/production/bars.yaml`](../../config/production/bars.yaml).

| Bar | Value | Scope |
|---|---|---|
| Correct archive | Dojo score ≥ 0.90 on the labelled fields, without the templated corporate/correspondence `keywords` and `subject_matter` (Exios66/llm-dojo-scoring#164) | per document |
| Wrong-archive rate | ≤ 2% of scorable archives (point estimate) | per slice, pooled over the gated classes |
| Review rate | ≤ 5% of documents (point estimate) | per slice, pooled over the gated classes |
| Crashes | 0 run errors and 0 `judge_error` | per slice, mergers included |

- **Gated classes:** contract, corporate_record, correspondence and insurance_claim.
- **Mergers:** outside the quality, wrong-archive and review-rate bars, so their scores never fail a slice. A merger crash or `judge_error` still fails it, like any other.
- **Contracts and mergers:** scored on CUAD and MAUD units. A contract with an empty CUAD map is scored on its field labels instead (SHF-016), and the gate counts those toward `min_labelled`.
- **Unscorable:** a document with fewer than 2 labelled fields. A gated pool that has archives but none scorable fails the slice. If more than 25% of the pool is unscorable, the gate only warns.
- **Per-class bars:** these apply from the 500-document slice onward. Below that they are diagnostic only.
- **Scorable minimum:** from the 500-document slice onward, a gated class with fewer than 20 scorable archives (`min_scorable_per_class`) fails the slice, because its per-class rates would not be evidence. Corporate records are the class at risk: with `9.3.1-rc.10`, slice 500 has 64 scorable corporate documents of 68.
- **Wilson bounds:** `gate.md` prints the Wilson 95% upper bound next to each rate, for information. The pass rule uses the point estimate.

## The loop, for slice N

0. **From a git worktree, set the environment first.** A worktree's `.venv` links to the main checkout, so without this every command below would run the main checkout's code and vendored trees. Preflight's `checkout` check now fails in that case (#312):

   ```bash
   export PYTHONPATH="$PWD/src"
   ```

   Then prepare the machine. Each item fails closed, but finding out at preflight wastes the slot:

   - **Install** `pip install -e ".[dev,observability]"`. The run mirrors every span to `data/traces/<run_id>.spans.jsonl.gz`, and the gate audit fails without it; the mirror needs the OpenTelemetry SDK from `[observability]`. Preflight refuses a run without it (`trace_sink`), and `sandbox doctor` reports it as `span-mirror`.
   - **Key.** `OPENROUTER_API_KEY` in the launching shell. Leave `OPENROUTER_BASE_URL` unset: a value that is not OpenRouter turns off the provider pins and the per-call spend guard.
   - **Label cut.** The slices select `9.3.1-rc.12`. Pull it (GitHub access to mailroom-issues), or import a bundle exported from a checkout that has it, then verify:

     ```bash
     python scripts/pull_staged_overlay.py --version 9.3.1-rc.12            # or: --import <bundle>.tar.gz
     python scripts/pull_staged_overlay.py --version 9.3.1-rc.12 --check    # ok: ... manifest cd3788c8c69f
     ```

   - **Doctor and hotfixes.** `sandbox doctor` with no `FAIL`, and `python scripts/check_hotfixes.py`.
   - **Prices.** `python scripts/refresh_api_prices.py --check`, since the sheet's prices are dated.
   - **A fresh run id.** `sandbox run list`. If `production-slice-0100` already exists from an earlier run (a different draw and labels), give this run a new `run_id` rather than resuming or forcing it, and never pair against that run (step 6).
   - **Served-model evidence.** Nothing to set. `run start` writes the served model, provider and pin status of every call to `data/runtime/runs/<run_id>/served.jsonl`, and each pipeline item records its own calls under `pred.served_calls`. A substitution has `status: mismatch` there (and a log warning). `SANDBOX_SERVED_LOG`, when set, receives a copy of every row; `sandbox report build` reads both files and counts a call once.
   - **One commit and one cut for the whole ladder.** A step-up compares runs, so do not change the checkout, the vendor pins or `staged_overlay` between slices.

1. **Preflight** (no spend). Every check must be `ok`. Plain preflight probes the Hub dataset but not the engine; `--live` adds the engine probe, and `--offline` skips the network probes, at the cost of leaving those checks unverified. Before a paid slice, run it with `--live` so a bad key or model id fails here, not on the first document:

   ```bash
   sandbox run preflight --config config/runs/production/slice-0100.yaml --live
   ```

   For slice 100, expect `rows=100`, dataset `sha256=48eee6163395…` and `excluded=187/187`.

2. **Start.** This is the spend gate. Only a human launches it, with their own initials:

   ```bash
   sandbox run start --config config/runs/production/slice-0100.yaml --initials <XX>
   ```

   After launch, check that `dependency_sources` in the run's `spec.lock.json` matches the checkout you launched from.

   **When a run stops before it finishes:**
   - **Cap or wall abort** (`api_cost_cap_usd`, `max_wall_seconds`): the run ends `failed`. The cap is part of the spec hash, so it cannot resume with a higher cap. Stop and diagnose before a new run id. `max_wall_seconds` is checked only between documents, so in-flight documents can run on to their own one-hour deadline.
   - **A document exception:** for `task: pipeline`, a document that raises runs again up to `job.max_retries` times (1 on the slices). A refusal by the API call guard (the run's cap or the 40-call ceiling) is never retried, and no retry starts once a wall, GPU or API cap is reached. The 40-call ceiling covers all of a document's attempts, not each one. A document that still raises becomes an error item row that carries the usage its attempts billed. With `job.fail_fast: false` (the slices) the run goes on. With `fail_fast: true` no new document starts, the documents already in flight finish, and the run fails. The run's gate counts error rows.
   - **A crash or an interrupt** (the checkpoint still says `running` or `paused`): a human resumes it with `sandbox run resume --run-id <id> --initials <XX>`. The resume replays finished items without re-billing them and re-runs the rest, error rows included: a document's new answer replaces its error row, and the error row's billed usage stays in the resume's budget.
   - **A run that ended `failed` or `done` is final.** That includes a `fail_fast` stop, a cap or wall abort, and a run that finished with error rows. `sandbox run resume` returns its stored summary and re-runs nothing, error rows included. Diagnose it, then start a new run id. A document that fails the same way twice is a fix-loop finding, not something to resume past.
   - **Spend guard missing:** `run start` refuses a run with `job.api_cost_cap_usd` when the provider-pin wrappers that guard each API call are not installed (`the per-call API spend guard is not installed`). The warning `provider pins not applied` above it names the cause; fix the install before starting the run.
3. **Gate.** This step is offline and writes only `gate.json` and `gate.md` into the run directory. It exits `0` on pass and `2` on fail. It exits `1`, with a JSON `failed` status, when the run is missing or never started (no `items.jsonl`), or when the gate itself errors (a bad bars file or a scorer failure):

   ```bash
   sandbox run gate --run-id production-slice-0100 --thresholds
   ```

4. **Read the buckets.** Each review and each wrong archive has exactly one primary cause, taken in this precedence order:

   | Order | Cause family | Causes |
   |---|---|---|
   | 1 | mechanism | `judge_error`, `crashed`, `transient` |
   | 2 | input | `input:near_empty` (reviews only: document text under 200 characters) |
   | 3 | classification | `wrong_class`, `reviewer_unknown`, `reviewer_disagreement`, `arbiter_escalated` (the classification arbiter) |
   | 4 | judge | `arbiter_escalated` (the extraction arbiter, which ruled last on the judge lane), `partial_exhausted`, `judge_rejected` |
   | 5 | label | `label_suspect` (a heuristic `intent` label only: never one an interim, staged or near-gold overlay supplied) |
   | 6 | extraction | `missing_field`, `out_of_enum`, `date_format`, `wrong_value`, `cuad_missed`, `cuad_false`, `maud_wrong` |

   A reviewer cause (`reviewer_unknown`, `reviewer_disagreement`, the reviewer's low confidence) is settled when the item records that the classification arbiter accepted a class (`classification_arbiter_decision` is `accept_sorter` or `accept_reviewer`): extraction ran only after that acceptance, so rows 4 to 6 decide first and the reviewer cause names the bucket only when none of them applies. An item without the decision keeps the order in the table, with one exception: the extraction arbiter outranks the reviewer's low-confidence doubt.

   Two mechanism buckets sit outside this order:
   - `mechanism:scorer_error`: a Dojo failure while typing the extraction miss.
   - `mechanism:unmapped:<raw>`: a review none of whose causes maps. It comes last.

   A wrong archive of a near-empty document keeps its classification or extraction cause, because the pipeline was confidently wrong about it.

   Every document row in `gate.json` links to three things:
   - `archive`: its archive directory, `data/archive/SANDBOX-sandbox_pipeline_<run_id>-<doc_id>/`. An archived document must have the `<class>` subdirectory of the class it was archived as.
   - `trace_id`: the run's trace id.
   - `span_id`: its own `job.item` span in `data/traces/<run_id>.spans.jsonl.gz`. A node span alone does not count.

   A missing or unreadable link fails the gate. `gate.md` lists every document in its **Documents** table, with class, outcome, score, labelled units, cause, archive link and span id.
5. **Fix the largest fixable bucket.** See "Where a fix lands" below. Record each fix on #306.
6. **Re-run the same slice and compare.** The paired check fails a re-run whose labels differ from the earlier run's (`re-run labels differ`). Pulling a new overlay does not change the labels an earlier run locked. So an earlier run scored on other labels (interim and near-gold, or an older overlay cut) is not a valid pair: first run the slice once on the current overlay as the baseline, then pair re-runs against that run. Give the re-run a new `run_id`, then gate it with the earlier run as its pair:

   ```bash
   sandbox run gate --run-id <rerun> --prev-run-id <earlier>
   ```

   When both runs drew the same documents, the gate runs a paired **re-run** check: both runs are gated on those documents. The fix is kept only if the re-run's pooled wrong-archive rate, review rate, crash count and `judge_error` count are all no higher than the earlier run's. Its reasons are prefixed `re-run:`. The re-run's own gate verdict still applies.
7. **Step up when the slice passes.** Launch the next slice, then gate it against the slice it contains. The command gates the whole new run first, as in step 3. It then adds the step-up check, which judges only the new documents, and prefixes its reasons `step-up:`. Either check can fail the verdict, so a step-up whose new documents pass can still FAIL on the whole run:

   ```bash
   sandbox run gate --run-id production-slice-0250 --prev-run-id production-slice-0100
   ```

**Thresholds.** `--thresholds` replays higher judge thresholds. For each candidate threshold, per class and pooled, it shows:

- the documents a higher threshold would send to the judge;
- the wrong archives it could catch and the correct archives it would disturb;
- the projected wrong-archive and review rates, next to the current ones. These assume every caught wrong archive goes to review. A worst-case review rate also assumes the judge rejects every other judged document.

It is an upper bound. A threshold change is adopted only on new documents, and only when it holds the wrong-archive bar.

## Where a fix lands

| Cause | Where |
|---|---|
| Specialist prompt wording | **Here.** Add a new `config/prompts/<agent>_condensed_v<N>.txt` and a lineage entry in `specialist_condensed_lineage.yaml`. Adopt it only after a paired A/B on held-out documents (`scripts/compare_specialist_prompt.py`). |
| Schema descriptions, judge, retries, merge logic | **Upstream** in llm-mailroom, then re-vendor with `/vendor-sync`. Never hand-edit `vendor/**`. |
| Scoring, ground truth, templated labels | **Upstream** in llm-dojo-scoring. |
| Corpus content (stripped attachments, near-empty rows) | **Upstream** in Mailroom-Corpus-EDA. |

A document used by a separate tuning run must never be gated. The fix loop is the one exception: a re-run (step 6) confirms a fix on slice N's own documents, so those documents are tuned on, and because slices nest they stay in every later slice. That is why a step-up's held-out evidence is its new-document check (step 7); the whole-run numbers of slice N+1 are partly in-sample. When you add a tuning run:

1. Add it to the regenerate command in `scripts/build_excluded_ids.py`, then regenerate `config/production/excluded-ids.txt`.
2. Do this **before** the next slice launches. With the ranked draw, the slices that have not run yet keep every document except the newly excluded ones.
3. Never exclude documents from a slice that has already been gated. That would break its nesting with the next slice.

A tuning run that itself excludes the production list would exclude its own documents once they are added. So the correspondence A/B arms exclude the frozen ladder list, `config/production/excluded-ids-ladder.txt`.

## Known limits

- **Sorter accuracy is in-sample.** The sorter prompt lineage was developed on the sorter handoff's train split (2,979 of 3,302 documents). Excluding that split would leave too few documents for the 500 and full slices.
- **The specialist prompts are not fully held out either.** The adopted condensed specialist prompts (corporate v1, correspondence v2, insurance v3) were validated on `gate-train` handoff draws. Those draws' document ids were not recorded, because the compare reports keep only counts. So those documents cannot be excluded, and some may appear in slices.
  - Fully held out: the pipeline-level tuning (the 11 ladder runs) and the correspondence v3 A/B.
  - Partly in-sample: extraction quality on any document a specialist A/B used.
- **Insurance `claim_type`:** the vendored schema description and extract-node handoff still teach the CMS table tokens and override the prompt. The upstream fix is Exios66/llm-mailroom#174 §2 (PR Exios66/llm-mailroom#280). The vendored pin `8cebcd86` describes `claim_type` as the product line, a CMS row being `health`, so this should no longer recur. Report any `extraction:out_of_enum` on a CMS row.
- **`judge_error` from null `choices` (fixed):** OpenRouter sometimes returns a 200 response with `choices: null` when an upstream provider fails. Before llm-mailroom `63f6841`, the judge raised a non-transient `TypeError` on it, and the document parked instead of retrying (Exios66/llm-mailroom#260).
  - It is classed as transient since Exios66/llm-mailroom#261, which is vendored at `63f6841`. `tests/test_judge_second_pass.py` pins the fix.
  - Slices 100 and 100 r2 hit it on long contracts. Runs locked on an earlier pin still can.
- **Card-shaped numbers:** OpenRouter's Decisions endpoint refuses a document holding a 4-4-4-4 digit group (`403 content filter: [CREDIT_CARD]`). That includes the synthetic property-claim IBANs, which appear in 200 insurance claims.
  - The sandbox's Decisions backend masks that shape (`mask_card_numbers`) in the document text of every reviewer and extraction-gate request, and in every string of the extraction-gate handoff (an extracted IBAN field). The sorter handoff carries only class names and is sent unchanged.
  - Unbroken digit runs, such as EDGAR accession numbers and notice ids, are kept.
  - Since llm-mailroom `63f6841` (Exios66/llm-mailroom#271), the vendored reviewer records any other non-transient backend error as an error. Earlier pins recorded it as no answer (Exios66/llm-mailroom#268).
- **Near-empty documents:** some Enron cover notes lost their attachment, leaving only 32 to 56 characters of text (Exios66/Mailroom-Corpus-EDA#63).
  - The reviewer says `unknown` on them, and the gate buckets that review as `input:near_empty`, not as a reviewer fault.
  - They still count against the 5% review budget. With the 187-id list, slice 100 has none, slice 250 has 3, slice 500 has 10 and the full slice has 104.
  - Preflight's `context_plan` warns about them by id.
- **A few corporate records are unscorable.** Corporate rows can carry fewer than 2 labelled fields once the templated `keywords` and `subject_matter` are dropped (Exios66/llm-dojo-scoring#164). The near-gold corporate labels in the staged cut fill most of them.
  - With `9.3.1-rc.10`: slice 100 has 1 of 14 corporate documents unscorable, against 0 in the other classes; slice 250 has 1; slice 500 has 4 of 68; slice-full has 8. With `9.3.1-rc.11`: 0, 0, 0 and 3, on the same draw. These counts come from the 2026-11-28 launch review.
  - The pooled unscorable share stays under the 25% warning, so read the per-class unscorable count in `gate.md` before trusting a corporate pass.
  - Correspondence carries ground truth on only 3 of its 11 fields (Exios66/llm-dojo-scoring#94), but enough to score every slice document.

## Modal job-host parity

0. **Deploy the job worker once per code or vendor change** (a human step; it creates the `sandbox-runs` volume on first deploy). Select the Modal profile first, and load the key into the same shell. The key travels in the deploy Secret, never the image:

   ```bash
   export MODAL_PROFILE=<profile> PYTHONPATH="$PWD/src"
   set -a; . <path-to-openrouter.env>; set +a
   (cd deploy && modal deploy modal_job.py)
   ```

   The subshell leaves you at the repository root for step 1. Keep the key loaded there too: preflight and `sandbox run start` check it in the launching shell. A twin whose worker lacks the key fails before its first document with "this run calls OpenRouter but the worker has no OPENROUTER_API_KEY".
1. Run the `*-modal-host.yaml` twin of a slice that already passed locally.
2. Require the same `dependency_sources` in both run locks. Bundle the same selected snapshots when deploying the job worker, and reject results whose provenance differs.
3. Gate the twin. The verdict must match, and every per-class rate must fall within the local run's paired confidence interval.

## Out of scope here

Stage 2, the self-hosted Modal vLLM ladder under the same gate, gets its own plan once `production-slice-0500` passes on OpenRouter. The Docker VM path follows the same configs once the job host has parity.
