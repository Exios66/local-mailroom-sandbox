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

| Config (`config/runs/production/`) | Documents | contract / corporate / correspondence / insurance / merger | `api_cost_cap_usd` | `max_wall_seconds` |
|---|---|---|---|---|
| `slice-0100.yaml` | 100 | 18 / 14 / 30 / 33 / 5 | 2 | 7,200 |
| `slice-0250.yaml` | 250 | 45 / 34 / 76 / 83 / 12 | 5 | 10,800 |
| `slice-0500.yaml` | 500 | 91 / 68 / 151 / 167 / 23 | 10 | 14,400 |
| `slice-full.yaml` | 3,104 (every remaining row) | 475 / 417 / 985 / 1,085 / 142 | 70 | 86,400 |

Each of 100, 250 and 500 has a `*-modal-host.yaml` twin. A twin differs only in `run_id` and `job.mode: modal`. **The twins cannot launch yet** (#308): the Modal worker refuses the `decisions` reviewer and carries no OpenRouter key.

## Bars

The bars live in [`config/production/bars.yaml`](../../config/production/bars.yaml).

| Bar | Value | Scope |
|---|---|---|
| Correct archive | Dojo score ≥ 0.90 on the labelled fields, without the templated corporate/correspondence `keywords` and `subject_matter` (Exios66/llm-dojo-scoring#164) | per document |
| Wrong-archive rate | ≤ 2% of archived (Wilson upper bound) | per slice, pooled over the gated classes |
| Review rate | ≤ 5% of documents (Wilson upper bound) | per slice, pooled over the gated classes |
| Crashes | 0 run errors and 0 `judge_error` | per slice, mergers included |

- **Gated classes:** contract, corporate_record, correspondence and insurance_claim.
- **Mergers:** run and reported, but they never fail a slice.
- **Contracts and mergers:** scored on CUAD and MAUD units.
- **Unscorable:** a document with fewer than 2 labelled fields. A gated pool that has archives but none scorable fails the slice. If more than 25% of the pool is unscorable, the gate only warns.
- **Per-class bars:** these apply from the 500-document slice onward. Below that they are diagnostic only.

## The loop, for slice N

1. **Preflight** (offline, no spend). Every check must be `ok` except `engine_spec` when no key is loaded:
   ```bash
   sandbox run preflight --config config/runs/production/slice-0100.yaml
   ```
2. **Start.** This is the spend gate. Only a human launches it, with their own initials:
   ```bash
   sandbox run start --config config/runs/production/slice-0100.yaml --initials <XX>
   ```
3. **Gate.** This step is offline and read-only. It writes `gate.json` and `gate.md` into the run directory and exits `0` on pass, `2` on fail and `1` when the run is missing:
   ```bash
   sandbox run gate --run-id production-slice-0100 --thresholds
   ```
4. **Read the buckets.** Each review and each wrong archive has exactly one primary cause, taken in this precedence order:

   | Order | Cause family | Causes |
   |---|---|---|
   | 1 | mechanism | `judge_error`, `crashed`, `transient`, `scorer_error`, `unmapped:<raw>` |
   | 2 | input | `input:near_empty` (document text under 200 characters) |
   | 3 | classification | `wrong_class`, `reviewer_unknown`, `reviewer_disagreement`, `arbiter_escalated` |
   | 4 | judge | `partial_exhausted`, `judge_rejected` |
   | 5 | label | `label_suspect` |
   | 6 | extraction | `missing_field`, `out_of_enum`, `date_format`, `wrong_value`, `cuad_missed`, `cuad_false`, `maud_wrong` |

   Every document row links to three things:
   - its archive directory, `data/archive/SANDBOX-sandbox_pipeline_<run_id>-<doc_id>/`;
   - the run's trace id;
   - its own `job.item` span id in `data/traces/<run_id>.spans.jsonl.gz`.

   A missing or unreadable link fails the gate.
5. **Fix the largest fixable bucket.** See "Where a fix lands" below. Record each fix on #306.
6. **Re-run the same slice and compare.** Give the re-run a new `run_id`, then gate it with the earlier run as its pair:
   ```bash
   sandbox run gate --run-id <rerun> --prev-run-id <earlier>
   ```
   A fix is kept only if the wrong-archive rate does not rise and the review rate holds.
7. **Step up when the slice passes.** Launch the next slice, then gate it against the slice it contains. The step-up verdict judges only the new documents, and every step-up reason is prefixed `step-up: `:
   ```bash
   sandbox run gate --run-id production-slice-0250 --prev-run-id production-slice-0100
   ```

**Thresholds.** `--thresholds` replays higher judge thresholds. The replay is an upper bound: it shows how many wrong archives a higher threshold could catch and how many correct archives it would disturb. A threshold change is adopted only on new documents, and only when it holds the wrong-archive bar.

## Where a fix lands

| Cause | Where |
|---|---|
| Specialist prompt wording | **Here.** Add a new `config/prompts/<agent>_condensed_v<N>.txt` and a lineage entry in `specialist_condensed_lineage.yaml`. Adopt it only after a paired A/B on held-out documents (`scripts/compare_specialist_prompt.py`). |
| Schema descriptions, judge, retries, merge logic | **Upstream** in llm-mailroom, then re-vendor with `/vendor-sync`. Never hand-edit `vendor/**`. |
| Scoring, ground truth, templated labels | **Upstream** in llm-dojo-scoring. |
| Corpus content (stripped attachments, near-empty rows) | **Upstream** in Mailroom-Corpus-EDA. |

After a tuning run, add its documents to the held-out list. Add the run to `scripts/build_excluded_ids.py`, then regenerate `config/production/excluded-ids.txt`. A document used to tune must never be gated.

## Known limits

- **Sorter accuracy is in-sample.** The sorter prompt lineage was developed on the sorter handoff's train split (2,979 of 3,302 documents). Excluding that split would leave too few documents for the 500 and full slices, so only extraction and routing quality are held out.
- **Insurance `claim_type`:** the vendored schema description still teaches the CMS table tokens and overrides the prompt (Exios66/llm-mailroom#174 §2). Expect `extraction:out_of_enum` until a re-vendor lands.
- **`judge_error` from null `choices`:** OpenRouter sometimes returns a 200 response with `choices: null` when an upstream provider fails. The vendored judge then raises a non-transient `TypeError`, and the document parks instead of retrying (Exios66/llm-mailroom#260).
  - The repro is `tests/test_judge_second_pass.py`, a strict xfail. Remove the xfail when the fix is vendored.
  - Until then a slice can fail on one such document. Re-run the slice.
- **Near-empty documents:** some Enron cover notes lost their attachment, leaving only 32 to 56 characters of text. The reviewer says `unknown` on them, and the gate buckets them as `input:near_empty`, not as a reviewer fault (Exios66/Mailroom-Corpus-EDA#63). Preflight's `context_plan` warns about them by id.
- **Unscorable correspondence:** only 3 of the 11 correspondence fields carry ground truth (Exios66/llm-dojo-scoring#94), so many correspondence documents are unscorable.

## Modal job-host parity (after #308)

1. Run the `*-modal-host.yaml` twin of a slice that already passed locally.
2. Require the same `dependency_sources` in both run locks. Bundle the same selected snapshots when deploying the job worker, and reject results whose provenance differs.
3. Gate the twin. The verdict must match, and every per-class rate must fall within the local run's paired confidence interval.

## Out of scope here

Stage 2, the self-hosted Modal vLLM ladder under the same gate, gets its own plan once `production-slice-0500` passes on OpenRouter. The Docker VM path follows the same configs once the job host has parity.
