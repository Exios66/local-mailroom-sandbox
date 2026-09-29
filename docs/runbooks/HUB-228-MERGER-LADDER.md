# HUB-228 — Merger prompt + scorer ladder (SPEND-GATED)

**Hub issue:** [LLM-Mailroom-Services/mailroom-issues#228](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/228)  
**Priority:** P0 — largest unsolved Modal merger quality gap.  
**Proposed busy-window cap:** `$1.50` per n=50 cell (`job.cost_cap_usd` in YAML).  
**Modal app:** `sandbox-vllm-hub228` (isolated from `sandbox-vllm-sand032`).

> **SPEND-GATED — do not run until Jack go.** YAML-only PRs are fine; no `modal deploy` / `sandbox run start` without explicit approval.

## Goal

Raise Modal merger extraction toward API-comparable usefulness under frozen SAND-032 L5 serving (2×L4, c32, Qwen3-8B-AWQ). Do **not** bar-chart Modal MAUD micro-accuracy against API pipeline Flash **0.521** as one series until scorer alignment is explicit.

## Frozen serving (do not drift)

Mirror `sand032-s5-merger50-maud.yaml` engine block: `awq_marlin`, fp8 KV, thinking off, CUDA graphs, `max_num_seqs` 16, `max_inputs` 32, 2×L4 warm fleet.

## Dataset pin

- Revision: `ed7576b676343e0b402ec5412cded301e629bdee`
- Split: `ground_truth` / `all`, seed **42**, nested draw 20 ⊂ 50

## Known confounders (cross-link)

| Card | Why it matters |
| --- | --- |
| [Exios66/local-mailroom-sandbox#62](https://github.com/Exios66/local-mailroom-sandbox/issues/62) | MAUD dataset defect — depresses MAUD micro-accuracy; cite in every merger MAUD report |
| [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) | Serving-knob vs scale-out methodology — **out of scope** for this ladder |
| [mailroom-issues#231](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/231) | LengthFinish on long merger docs — fix completion before over-interpreting prompt deltas |

## Run cells

| Config | n | Prompt | Notes |
| --- | ---: | --- | --- |
| `config/runs/hub228-merger50-prod.yaml` | 50 | `merger_agreement_specialist_production` | Cell (A) baseline |
| `config/runs/hub228-merger50-maud.yaml` | 50 | `merger_agreement_specialist_maud_v1` | Cell (B) MAUD control ≡ `sand032-s5-merger50-maud` |
| `config/runs/hub228-merger50-variant-a.yaml` | 50 | `merger_agreement_specialist_hub228_variant_a` | Cell (C) stub — see `config/prompts/HUB-228-merger-variant-a.TODO.md` |
| `config/runs/hub228-merger20-prod.yaml` | 20 | production | Cheap iterate |
| `config/runs/hub228-merger20-maud.yaml` | 20 | MAUD v1 | Cheap iterate |
| `config/runs/hub228-merger20-variant-a.yaml` | 20 | variant A stub | Cheap iterate |

## Operator outline (after Jack go)

1. Confirm draw IDs match SAND-032 merger cells (`sandbox datasets prepare` + row-id diff).
2. `sandbox run deploy-env` → source exports → deploy **one** app (`sandbox-vllm-hub228`).
3. Run A → B → C with full serving export + artifacts.
4. Report wall, tok/s, $/doc, $/1M, MAUD + pipeline rubric (separate columns), LengthFinish rate, schema %.
5. Diff vs `sand032-s5-merger50-maud`; hub comment — **no “solved” claim** until owner-locked gate.

## Preflight (no spend)

```bash
sandbox run benchmark-check --config config/runs/hub228-merger50-maud.yaml --modal-profile exios66 --dry-run 2>/dev/null || \
  sandbox run benchmark-check --config config/runs/hub228-merger50-maud.yaml --modal-profile exios66
python -c "from mailroom_sandbox.job.spec import load_run_spec; load_run_spec('config/runs/hub228-merger50-maud.yaml')"
```
