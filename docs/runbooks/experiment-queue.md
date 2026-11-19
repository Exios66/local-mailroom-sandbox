# Experiment queue: 2026-11-17

This is the ordered list of runs that follow the 2026-11-16 fixes. A human launches every paid step with their own initials; agents only preflight. Each step says what it needs merged first and what result decides the next one.

Status of the fixes:

| Fix | Where | State |
|---|---|---|
| Gate counts only fields the Dojo scores | #318 | Merged (`787d61e`) |
| Re-vendor: null-`choices` judge fix, reviewer error recording, correspondence typed by content | #319 | Merged |
| Insurance `claim_type` is the product line (#174 §2) | Exios66/llm-mailroom#280 | Open upstream; blocks the v5 A/B |
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

- **Result (2026-11-17):** v4 is adopted but not deployed.
  - Mean 0.874 → 0.880, with 22 wins, 6 ties and 12 losses, and no parse errors.
  - Part D NDC: 0/5 → 5/5.
  - `claim_type` did not move: 20 of 21 CMS rows kept a table token in every arm. The pipeline's structured-output schema asks for those tokens and outweighs the prompt; only Exios66/llm-mailroom#280 changes it.
  - The handoff note helps: v3 without it scores 0.856, v3 with it 0.874.
  - v4 is folded into v5 (v4 plus the #280 wording), and the slices stay on v3 until v5 passes. The A/B's 40 documents are now in `excluded-ids.txt`.

### Q2. Judge audit (llm-mailroom #278)

- **Cost:** $0.75 cap, on 26 documents that pair with r2.
- **Config:** `config/runs/production/judge-audit-0026.yaml`. The offline preflight passes except for the key check.
- **Question:** when the judge sees the corporate, correspondence and insurance extractions the router skipped in r2, does it reject the wrong ones?

```bash
.venv/bin/sandbox run start --config config/runs/production/judge-audit-0026.yaml --initials <XX>
.venv/bin/sandbox run gate --run-id judge-audit-0026 --prev-run-id production-slice-0100-r2
```

- **Result (2026-11-17):** routing stays as it is.
  - Of r2's 6 wrong archives in the 26 documents, the judge sent 1 to review. It passed 5, three of them the `claim_type` table token.
  - It also sent 2 correct and 3 unscorable archives to review. One of the correct ones was a provider connection error.
  - Review went from 1/26 to 7/26, tokens rose 1.4× to 3× per class, and field scores did not improve.
  - The remaining work is extraction (#280) and labels: 11 of the 19 audit archives are unscorable.

## Free: after merges

### Q3. Re-score r2 on the merged code

- **Cost:** none.
- **Steps:**
  1. Re-gate `production-slice-0100-r2` under the corrected count.
  2. Once Exios66/llm-dojo-scoring#173 and Exios66/llm-mailroom#280 merge, re-vendor again with `/vendor-sync`. llm-mailroom must first re-pin its Dojo dependency to the #173 merge.
  3. Re-score the stored r2 and insurance runs (Exios66/llm-mailroom#183). Do not compare runs locked on different pins without re-scoring them.
  4. **Insurance v5 A/B** ($0.10 cap per arm, the v4 A/B's 40 documents, on the new pins): `config/runs/specialist-condensed-v5-insurance-claim-qwen-{v4arm,v5arm}.yaml`, then `scripts/compare_specialist_prompt.py --reference specialist-condensed-v5-insurance-claim-qwen-v4arm --candidate specialist-condensed-v5-insurance-claim-qwen-v5arm`. If v5 passes, make it the lineage frontrunner and point `insurance_claims_specialist` at it in `config/runs/production/slice-*.yaml` (`tests/test_production_slices.py` requires the two to match).

## Next paid slice: only after Q1 to Q3

### Q4. Slice 100 r3

- **Cost:** $2 cap, 100 documents.
- **Needs:**
  - the second re-vendor (#280 and #173);
  - the v5 A/B decision (Q3 step 4);
  - the Q2 routing decision (done: routing unchanged).
- **Why it waits:** run before #280 lands, the slice pays to see the insurance `out_of_enum` failure we already know about.

```bash
.venv/bin/sandbox run preflight --config config/runs/production/slice-0100.yaml --run-id production-slice-0100-r3
.venv/bin/sandbox run start --config config/runs/production/slice-0100.yaml --run-id production-slice-0100-r3 --initials <XX>
.venv/bin/sandbox run gate --run-id production-slice-0100-r3 --prev-run-id production-slice-0100-r2
```

- **Label revision:** r2 ran on Hub tag v9.1, and `slice-0100.yaml` now pins v9.3. Both draw the same 100 documents in the same order, but the 14 corporate records carry repaired labels (`keywords`, `subject_matter`, `entity_name`, `gt_presence`, `record_type`). So `run gate --prev-run-id production-slice-0100-r2` always fails its re-run check (`re-run labels differ on 14 document(s)`), and its pooled rates include those 14. Pick one before launching: (a) gate r3 as a fix re-run of r2 on a copy of `slice-0100.yaml` pinned to v9.1 (`bc9eab280044befb51e19dda3071d290a8677f42`), as `judge-audit-0026` does; or (b) run r3 on v9.3 as the first v9.3 baseline, gated on its own (`sandbox run gate --run-id production-slice-0100-r3`), with no `--prev-run-id`.
- **What to expect:** even with every fix layered on, the r2 counterfactual stays near 0.40 wrong archives. That is far above the 0.02 bar. What remains is contract clause recall and insurance free-text fields just under 0.90, so r3 measures progress; it will not pass.

## Blocked on other work

- **Contract clause recall (compact contracts specialist lineage):** this is the largest gap left. Its session did not start because the disk was full. Free about 2.5 GB and restart it.
- **Slices 250 and 500:** each runs only after the slice below it passes.
- **Modal job-host parity (#308):** deploy `sandbox-job` on the `exios66` profile, then run the `slice-0100-modal-host.yaml` twin of a slice that passed locally. It is blocked until a local slice passes.
