# Experiment queue: 2026-11-17

This is the ordered list of runs that follow the 2026-11-16 fixes. A human launches every paid step with their own initials; agents only preflight. Each step says what it needs merged first and what result decides the next one.

Status of the fixes:

| Fix | Where | State |
|---|---|---|
| Gate counts only fields the Dojo scores | #318 | Merged (`787d61e`) |
| Re-vendor: null-`choices` judge fix, reviewer error recording, correspondence typed by content | #319 | Merged |
| Insurance `claim_type` is the product line (#174 §2) | Exios66/llm-mailroom#280 | Open upstream |
| CUAD dates count toward recall only (#167) | Exios66/llm-dojo-scoring#173 | Open upstream |

## Now: on the current pins, about $1.05 in total

Run both from a checkout of `787d61e`, the #318 merge on `main` and the last commit before #319. It has the judge-audit config, the corrected gate and the insurance A/B arms on r2's pins, so both runs pair cleanly with r2. The `mailroom-readiness-handoff` worktree (branch `fix/gate-scored-fields`) holds the same code. Do not update it before these runs. A `main` checkout after #319 runs on the new pins and does not pair with r2.

```bash
git worktree add ../mailroom-q1q2 787d61e   # or reuse the mailroom-readiness-handoff worktree
cd ../mailroom-q1q2 && ln -s ../local-mailroom-sandbox/.venv .venv
```

```bash
export PYTHONPATH="$PWD/src"   # also load OPENROUTER_API_KEY from your own secret store; never paste it into a file
```

### Q1. Insurance prompt v4 A/B

- **Cost:** 3 arms × $0.10 cap, on 40 shared insurance documents.
- **Configs:** `config/runs/specialist-condensed-v4-insurance-claim-qwen-{v3arm-plain,v3arm,v4arm}.yaml`. The offline preflight passes except for the key check.
- **Question:** does v4 fill the Part D NDC and keep `claim_type` a product line? And what does the pipeline handoff alone cost? That second question is the `v3arm-plain` vs `v3arm` pair.

```bash
for a in v3arm-plain v3arm v4arm; do .venv/bin/sandbox run start --config config/runs/specialist-condensed-v4-insurance-claim-qwen-$a.yaml --initials <XX>; done
.venv/bin/python scripts/compare_specialist_prompt.py --reference specialist-condensed-v4-insurance-claim-qwen-v3arm --candidate specialist-condensed-v4-insurance-claim-qwen-v4arm
```

- **Then:** set v4 to `adopted` or `rejected` in `config/prompts/specialist_condensed_lineage.yaml`. If it is adopted, point `insurance_claims_specialist` at v4 in `config/runs/production/slice-*.yaml`. Add the arm ids to `config/production/excluded-ids.txt` with `scripts/build_excluded_ids.py`.

### Q2. Judge audit (llm-mailroom #278)

- **Cost:** $0.75 cap, on 26 documents that pair with r2.
- **Config:** `config/runs/production/judge-audit-0026.yaml`. The offline preflight passes except for the key check.
- **Question:** when the judge sees the corporate, correspondence and insurance extractions the router skipped in r2, does it reject the wrong ones?

```bash
.venv/bin/sandbox run start --config config/runs/production/judge-audit-0026.yaml --initials <XX>
.venv/bin/sandbox run gate --run-id judge-audit-0026 --prev-run-id production-slice-0100-r2
```

- **Then:** if the judge rejects most of r2's wrong archives, set `judge_band_high` for those classes in the slice configs. If it passes them, leave routing alone. The remaining work is then extraction and labels.

## Free: after merges

### Q3. Re-score r2 on the merged code

- **Cost:** none.
- **Steps:**
  1. Re-gate `production-slice-0100-r2` under the corrected count.
  2. Once Exios66/llm-dojo-scoring#173 and Exios66/llm-mailroom#280 merge, re-vendor again with `/vendor-sync`. llm-mailroom must first re-pin its Dojo dependency to the #173 merge.
  3. Re-score the stored r2 and insurance runs (Exios66/llm-mailroom#183). Do not compare runs locked on different pins without re-scoring them.

## Next paid slice: only after Q1 to Q3

### Q4. Slice 100 r3

- **Cost:** $2 cap, 100 documents.
- **Needs:**
  - the second re-vendor (#280 and #173);
  - the Q1 prompt decision;
  - the Q2 routing decision.
- **Why it waits:** run before #280 lands, the slice pays to see the insurance `out_of_enum` failure we already know about.

```bash
.venv/bin/sandbox run preflight --config config/runs/production/slice-0100.yaml --run-id production-slice-0100-r3
.venv/bin/sandbox run start --config config/runs/production/slice-0100.yaml --run-id production-slice-0100-r3 --initials <XX>
.venv/bin/sandbox run gate --run-id production-slice-0100-r3 --prev-run-id production-slice-0100-r2
```

- **What to expect:** even with every fix layered on, the r2 counterfactual stays near 0.40 wrong archives. That is far above the 0.02 bar. What remains is contract clause recall and insurance free-text fields just under 0.90, so r3 measures progress; it will not pass.

## Blocked on other work

- **Contract clause recall (compact contracts specialist lineage):** this is the largest gap left. Its session did not start because the disk was full. Free about 2.5 GB and restart it.
- **Slices 250 and 500:** each runs only after the slice below it passes.
- **Modal job-host parity (#308):** deploy `sandbox-job` on the `exios66` profile, then run the `slice-0100-modal-host.yaml` twin of a slice that passed locally. It is blocked until a local slice passes.
