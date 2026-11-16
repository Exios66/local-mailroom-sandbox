# Production slices: launch, gate, fix, step up

This runbook covers how a production run is approved. Each run is a CLI-launched pipeline run over a fixed, held-out slice of the Hugging Face mailroom dataset (pin `bc9eab28`, 3,302 rows), and it passes the **slice gate** before the next, larger slice runs.
- Design: [`docs/superpowers/specs/2026-11-16-production-slice-gate-design.md`](../superpowers/specs/2026-11-16-production-slice-gate-design.md)
- Tracker: Exios66/local-mailroom-sandbox#305
- Fix backlog: Exios66/local-mailroom-sandbox#306

This page is hand-written. It is not generated from `config/runbooks/catalog.yaml`.

## Slices

All slices share r3's settings:
- blind routing and interim labels;
- the adopted condensed specialist prompts;
- the Luna Decisions reviewer;
- `qwen/qwen3.7-flash` on OpenRouter;
- `sample_seed: 3302`, with per-class strata.

The draws are nested, so a smaller slice is a subset of the next. Every document listed in `config/production/excluded-ids.txt` (via `dataset.exclude_ids_file`) is dropped before the draw.

The list holds 147 documents: the 107 from the 11 ladder runs and the 40 of the correspondence v3 A/B.

The slices use `dataset.draw: ranked`. Each class bucket is ordered by a per-document hash rather than shuffled, so adding ids to the list keeps the rest of every slice in place. Only the documents that were removed are replaced, and the slices stay nested. The default `shuffle` draw would reshuffle the whole bucket.

| Config (`config/runs/production/`) | Documents | contract / corporate / correspondence / insurance / merger | `api_cost_cap_usd` | `max_wall_seconds` |
|---|---|---|---|---|
| `slice-0100.yaml` | 100 | 18 / 14 / 30 / 33 / 5 | 2 | 7,200 |
| `slice-0250.yaml` | 250 | 45 / 34 / 76 / 83 / 12 | 5 | 10,800 |
| `slice-0500.yaml` | 500 | 91 / 68 / 151 / 167 / 23 | 10 | 14,400 |
| `slice-full.yaml` | 3,064 (every remaining row) | 475 / 417 / 945 / 1,085 / 142 | 70 | 86,400 |

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
- **Contracts and mergers:** scored on CUAD and MAUD units.
- **Unscorable:** a document with fewer than 2 labelled fields. A gated pool that has archives but none scorable fails the slice. If more than 25% of the pool is unscorable, the gate only warns.
- **Per-class bars:** these apply from the 500-document slice onward. Below that they are diagnostic only.
- **Scorable minimum:** from the 500-document slice onward, a gated class with fewer than 20 scorable archives (`min_scorable_per_class`) fails the slice, because its per-class rates would not be evidence. Corporate records are the class at risk: slice 500 holds 26 scorable corporate documents at most.
- **Wilson bounds:** `gate.md` prints the Wilson 95% upper bound next to each rate, for information. The pass rule uses the point estimate.

## The loop, for slice N

0. **From a git worktree, set the environment first.** A worktree's `.venv` links to the main checkout, so without this every command below, preflight included, runs the main checkout's code and vendored trees (#312):
   ```bash
   export PYTHONPATH="$PWD/src"
   ```
1. **Preflight** (no spend). Every check must be `ok` except `engine_spec` when no key is loaded. It makes network probes (the engine and a Hub dataset); add `--offline` to skip them, at the cost of leaving those checks unverified:
   ```bash
   sandbox run preflight --config config/runs/production/slice-0100.yaml
   ```
2. **Start.** This is the spend gate. Only a human launches it, with their own initials:
   ```bash
   sandbox run start --config config/runs/production/slice-0100.yaml --initials <XX>
   ```
   After launch, check that `dependency_sources` in the run's `spec.lock.json` matches the checkout you launched from.
3. **Gate.** This step is offline and writes only `gate.json` and `gate.md` into the run directory. It exits `0` on pass and `2` on fail. It exits `1`, with a JSON `failed` status, when the run is missing or never started (no `items.jsonl`), or when the gate itself errors (a bad bars file or a scorer failure):
   ```bash
   sandbox run gate --run-id production-slice-0100 --thresholds
   ```
4. **Read the buckets.** Each review and each wrong archive has exactly one primary cause, taken in this precedence order:

   | Order | Cause family | Causes |
   |---|---|---|
   | 1 | mechanism | `judge_error`, `crashed`, `transient` |
   | 2 | input | `input:near_empty` (reviews only: document text under 200 characters) |
   | 3 | classification | `wrong_class`, `reviewer_unknown`, `reviewer_disagreement`, `arbiter_escalated` |
   | 4 | judge | `partial_exhausted`, `judge_rejected` |
   | 5 | label | `label_suspect` |
   | 6 | extraction | `missing_field`, `out_of_enum`, `date_format`, `wrong_value`, `cuad_missed`, `cuad_false`, `maud_wrong` |

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
6. **Re-run the same slice and compare.** Give the re-run a new `run_id`, then gate it with the earlier run as its pair:
   ```bash
   sandbox run gate --run-id <rerun> --prev-run-id <earlier>
   ```
   When both runs drew the same documents, the gate runs a paired **re-run** check: both runs are gated on those documents. The fix is kept only if the re-run's pooled wrong-archive rate, review rate, crash count and `judge_error` count are all no higher than the earlier run's. Its reasons are prefixed `re-run: `. The re-run's own gate verdict still applies.
7. **Step up when the slice passes.** Launch the next slice, then gate it against the slice it contains. The command gates the whole new run first, as in step 3. It then adds the step-up check, which judges only the new documents, and prefixes its reasons `step-up: `. Either check can fail the verdict, so a step-up whose new documents pass can still FAIL on the whole run:
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
- **Insurance `claim_type`:** the vendored schema description still teaches the CMS table tokens and overrides the prompt (Exios66/llm-mailroom#174 §2). Expect `extraction:out_of_enum` until a re-vendor lands.
- **`judge_error` from null `choices`:** OpenRouter sometimes returns a 200 response with `choices: null` when an upstream provider fails. The vendored judge then raises a non-transient `TypeError`, and the document parks instead of retrying (Exios66/llm-mailroom#260).
  - The repro is `tests/test_judge_second_pass.py`, a strict xfail. Remove the xfail when the fix is vendored.
  - Until then a slice can fail on one such document. Re-run the slice. The fix is merged upstream (Exios66/llm-mailroom#261) and lands here with the next re-vendor.
  - Slice 100 hit it on 1 contract, then on 2 other contracts in its re-run, so expect it on long contracts.
- **Card-shaped numbers:** OpenRouter's Decisions endpoint refuses a document holding a 4-4-4-4 digit group (`403 content filter: [CREDIT_CARD]`). That includes the synthetic property-claim IBANs, which appear in 200 insurance claims.
  - The sandbox's Decisions backend masks that shape (`mask_card_numbers`) in the document text of every reviewer and extraction-gate request, and in every string of the extraction-gate handoff (an extracted IBAN field). The sorter handoff carries only class names and is sent unchanged.
  - Unbroken digit runs, such as EDGAR accession numbers and notice ids, are kept.
  - The vendored reviewer records any other non-transient backend error as no answer (Exios66/llm-mailroom#268).
- **Near-empty documents:** some Enron cover notes lost their attachment, leaving only 32 to 56 characters of text (Exios66/Mailroom-Corpus-EDA#63).
  - The reviewer says `unknown` on them, and the gate buckets that review as `input:near_empty`, not as a reviewer fault.
  - They still count against the 5% review budget. With the 147-id list, slice 100 has none, slice 250 has 3, slice 500 has 10 and the full slice has 104.
  - Preflight's `context_plan` warns about them by id.
- **Corporate records are mostly unscorable.** Many corporate rows carry fewer than 2 labelled fields once the templated `keywords` and `subject_matter` are dropped (Exios66/llm-dojo-scoring#164).
  - Slice 100: 8 of 14 corporate documents are unscorable, against 0 in the other classes. Slice 500: 42 of 68.
  - The pooled unscorable share stays under the 25% warning, so read the per-class unscorable count in `gate.md` before trusting a corporate pass.
  - Correspondence carries ground truth on only 3 of its 11 fields (Exios66/llm-dojo-scoring#94), but enough to score every slice document.

## Modal job-host parity

0. **Deploy the job worker once per code or vendor change** (a human step; it creates the `sandbox-runs` volume on first deploy). Select the Modal profile first, and load the key into the same shell. The key travels in the deploy Secret, never the image:
   ```bash
   export MODAL_PROFILE=<profile> PYTHONPATH="$PWD/src"
   set -a; . <path-to-openrouter.env>; set +a
   cd deploy && modal deploy modal_job.py
   ```
   A twin whose worker lacks the key fails before its first document with "this run calls OpenRouter but the worker has no OPENROUTER_API_KEY".
1. Run the `*-modal-host.yaml` twin of a slice that already passed locally.
2. Require the same `dependency_sources` in both run locks. Bundle the same selected snapshots when deploying the job worker, and reject results whose provenance differs.
3. Gate the twin. The verdict must match, and every per-class rate must fall within the local run's paired confidence interval.

## Out of scope here

Stage 2, the self-hosted Modal vLLM ladder under the same gate, gets its own plan once `production-slice-0500` passes on OpenRouter. The Docker VM path follows the same configs once the job host has parity.
