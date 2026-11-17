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
| Wrong-archive rate | 0.615 | ≤ 0.02 |
| Review rate | 0.095 | ≤ 0.05 |

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

**Insurance counterfactual on r2:** wrong archives fall from 22/30 to 10/30 once `claim_type` carries the product line, and to 6/30 once Part D supporting documents are filled. The pooled rate falls from 0.615 to 0.462, then to 0.410. This alone does not pass the gate. Contracts and correspondence still need the fixes above.

## Next actions

Every step from 1 on spends money or is reserved for the owner, so a human starts it.

1. **Insurance v4 A/B** (OpenRouter, $0.10 cap per arm, 40 shared insurance documents). The arms are disjoint from slice 500 and from the tuning list. Run this from a checkout of `main` with `OPENROUTER_API_KEY` set:
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
3. **Slice 100 r3:** preflight, start (human initials), then `sandbox run gate --run-id production-slice-0100 --thresholds`. Expect `out_of_enum` on insurance until #174 §2 lands.
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
