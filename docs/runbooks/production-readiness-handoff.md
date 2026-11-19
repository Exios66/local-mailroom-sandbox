# Production readiness handoff: 2026-11-16

This is where the production slice gate stood when the agent's goal was paused. Everything an agent could do without spend or owner-only steps is done. The rest is listed under [Next actions](#next-actions), in order, with the gate each one waits on.

- Runbook: [`production-slices.md`](production-slices.md)
- Tracker: Exios66/local-mailroom-sandbox#305
- Fix backlog: Exios66/local-mailroom-sandbox#306

In this page, **measured** means read from a stored run, **counterfactual** means a stored run re-scored with patched predictions, and **pending** means it has not run.

## State

| Item | State |
|---|---|
| `main` | `b28a7a9` (merge of #315) |
| Vendor pins | llm-mailroom `63f6841`, Dojo `116da0b` (`v0.30.1`) |
| Next re-vendor | After Exios66/llm-mailroom#280 (insurance `claim_type`, #174 §2) and Exios66/llm-dojo-scoring#173 (CUAD dates, #167) merge |
| Latest slice | `production-slice-0100-r2`: **failed** the gate (measured) |
| Modal job host | Code merged in #314. The worker is not deployed. |

### Slice 100 r2 (measured)

| Bar | Value | Required |
|---|---|---|
| Wrong-archive rate | 0.727 (40/55 scorable) | ≤ 0.02 |
| Review rate | 0.095 (9/95) | ≤ 0.05 |

These rates use the corrected label count. A label now counts only if it is a field the Dojo scores. Earlier gate reports counted corpus annotations as labels (`content_topic`, `sentiment_label`, `sentiment_score`), but the Dojo never scores those. That made 23 correspondence rows that are scored on `intent` alone look scorable, and those rows gave 0.615 (48/78). Under the corrected count, 23 of 30 correspondence rows and 8 of 14 corporate rows are unscorable, and the gate warns about both.

The wrong archives fall into three buckets: `out_of_enum` 18, `wrong_value` 18 and `cuad_missed` 9.

### Causes and where each is fixed

| Cause | Fixed? | Where |
|---|---|---|
| Insurance `claim_type` gets CMS table tokens: the schema description and the extract-node handoff teach them | **PR open** | Exios66/llm-mailroom#280 (#174 §2), against `v0.30.0`. Not vendored yet. |
| Insurance Part D `supporting_documents` left empty | Sandbox prompt candidate only | The insurance condensed v4 prompt (#315). Its A/B is pending. |
| Correspondence `communication_type` set to `email` for any inbox item | **Yes**, vendored | Exios66/llm-mailroom#271 and #273, Exios66/llm-dojo-scoring#166, at `63f6841` / `116da0b` |
| `judge_error` from a 200 response with `choices: null` | **Yes**, vendored | Exios66/llm-mailroom#261, at `63f6841` |
| Decision-reviewer backend error recorded as no answer | **Yes**, vendored | Exios66/llm-mailroom#268, via #271, at `63f6841` |
| CUAD Agreement Date never scored | **PR open** | Exios66/llm-dojo-scoring#173 (#167): recall-only, so an unlabelled date is never a false positive. Not vendored yet. |
| Correspondence `intent` label ceiling | No | Exios66/llm-dojo-scoring#171. Of the 12 misses, 4 are extraction errors, 4 have questionable labels and 4 are ambiguous. |
| Contract CUAD recall | No | A compact contracts lineage is proposed as its own task |

**Layered counterfactual on r2** (corrected count; each layer adds to the ones above; the review rate stays 9/95 throughout):

| Layer | Wrong archives | Contract | Corporate | Correspondence | Insurance |
|---|---|---|---|---|---|
| As run | 40/55 = 0.727 | 10/12 | 2/6 | 6/7 | 22/30 |
| + `claim_type` = product line (#174 §2) | 28/55 = 0.509 | | | | 10/30 |
| + Part D NDC (insurance v4) | 24/55 = 0.436 | | | | 6/30 |
| + `communication_type` by content (#271) | 22/55 = 0.400 | | | 4/7 | |
| + CUAD dates as Dojo #167 proposes | 23/55 = 0.418 | 11/12 | | | |
| Upper bound: every `intent` correct | 20/55 = 0.364 | | | 1/7 | |

The CUAD-date layer makes the result worse. The fold penalises a correct date wherever the gold has no date category, as noted on Exios66/llm-dojo-scoring#167. Dropping heuristic `intent` labels makes no difference under the corrected count, so no label allowance was added to the bars.

None of these layers comes near the 0.02 bar. What remains:

- 11 contracts on CUAD recall (0.67 to 0.83)
- 6 insurance claims just under the bar (0.82 to 0.90) on `supporting_documents`, `damages_description` and `subject_matter`
- 3 or 4 correspondence documents
- 2 corporate records

In r2, every contract went through the judge, but 34 of the 36 corporate, correspondence and insurance wrong archives reported confidence ≥ 0.95 and skipped it (Exios66/llm-mailroom#278).

## Next actions

The ordered run list, with what each step needs merged first, is [`experiment-queue.md`](experiment-queue.md).

**Steps 0 and 1 ran on 2026-11-17** (results in the queue, Q1 and Q2):

- The judge audit leaves routing alone: it caught 1 of r2's 6 wrong archives.
- Insurance v4 is adopted and folded into a v5 candidate, whose A/B waits for Exios66/llm-mailroom#280.
- The slices stay on v3 until v5 passes.

Every step from 1 on spends money or is reserved for the owner, so a human starts it.

0. **Judge audit** (OpenRouter, $0.75 cap, 26 documents that pair with r2). This tests whether the judge catches the wrong archives the router never sends it. The offline preflight passes except for the key check.

   ```bash
   export PYTHONPATH="$PWD/src"
   sandbox run preflight --config config/runs/production/judge-audit-0026.yaml
   sandbox run start --config config/runs/production/judge-audit-0026.yaml --initials <XX>
   sandbox run gate --run-id judge-audit-0026 --prev-run-id production-slice-0100-r2
   ```

   If the judge rejects most of r2's wrong archives, widen the judge band for those classes. If it passes them, judge routing cannot fix the gate, and the work moves to extraction and labels.
1. **Insurance v4 A/B** (OpenRouter, $0.10 cap per arm, 40 shared insurance documents). The arms are disjoint from slice 500 and from the tuning list. Run this and step 0 from a checkout of `787d61e`, the #318 merge on r2's pins (see the queue), with `OPENROUTER_API_KEY` set:

   ```bash
   export PYTHONPATH="$PWD/src"
   for a in v3arm-plain v3arm v4arm; do sandbox run preflight --config config/runs/specialist-condensed-v4-insurance-claim-qwen-$a.yaml; done
   for a in v3arm-plain v3arm v4arm; do sandbox run start --config config/runs/specialist-condensed-v4-insurance-claim-qwen-$a.yaml --initials <XX>; done
   python scripts/compare_specialist_prompt.py --reference specialist-condensed-v4-insurance-claim-qwen-v3arm --candidate specialist-condensed-v4-insurance-claim-qwen-v4arm
   ```

   Then:
   - Set the v4 status in `config/prompts/specialist_condensed_lineage.yaml` to `adopted` or `rejected`.
   - Add the arm ids to `config/production/excluded-ids.txt` with `scripts/build_excluded_ids.py`.

   The `v3arm-plain` vs `v3arm` pair measures what the pipeline handoff itself costs. The A/B stays valid before or after the re-vendor, because the handoff code and the insurance note are byte-identical at `63f6841`.
2. **Re-vendor to llm-mailroom `63f6841` and Dojo `116da0b`:** done in this re-vendor PR, with the #260 xfail removed. Runs locked on the old pins keep their `dependency_sources`. Do not compare them with new runs without re-scoring.
3. **Slice 100 r3:** waits for step 5's second re-vendor and the step 0 and step 1 decisions. Run it as `production-slice-0100-r3` and gate it against r2 (queue Q4). Run before #174 §2 lands, it pays to see the known insurance `out_of_enum` failure.
4. **Modal job-host parity** (#308):
   - Deploy `sandbox-job` on the `exios66` profile, from a shell that has the key loaded (runbook, "Modal job-host parity").
   - Then run the `slice-0100-modal-host.yaml` twin of a slice that passed locally.
5. **After Exios66/llm-mailroom#280 and Exios66/llm-dojo-scoring#173 merge:**
   - Re-vendor again. llm-mailroom also needs to re-pin its Dojo dependency to the #173 merge.
   - Re-score the stored insurance runs (Exios66/llm-mailroom#183).
   - Re-run slice 100, then step up to 250 and 500 as each one passes.

## Constraints that still apply

- Never hand-edit `vendor/**`, and never invent initials.
- Modal work uses the `exios66` profile. The owner sets its token.
- The OpenRouter key is never written to the repo, to `.env`, to issues or to PRs.
- From a worktree, set `PYTHONPATH="$PWD/src"` before every command (#312).
