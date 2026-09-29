# HUB-231 — Long-doc completion reliability (SPEND-GATED)

**Hub issue:** [mailroom-issues#231](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/231)  
**Proposed busy-window cap:** `$1.20` (split across cells; see YAML `cost_cap_usd`).  
**Modal app:** `sandbox-vllm-hub231`  
**Priority:** P1 — LengthFinish / completion wall on contracts + mergers.

> **SPEND-GATED — do not run until Jack go.**

## Goal

≥98% completion on contracts n=50 and mergers n=50 at frozen L5 2×L4 **without** changing serving knobs (#224 axis). Sweep decode budget / chunking hypotheses via run-scoped `SANDBOX_AGENT_KNOBS` — not engine block edits.

## Frozen serving

Same block as `sand032-s3-contracts50.yaml` / `sand032-s3-merger50.yaml` (L5 winner). Long-doc batch only — **do not mix correspondence** in the same Modal app session.

## Dataset

`ed7576b676343e0b402ec5412cded301e629bdee`, seed 42, `ground_truth` / `all`, n=50 per class.

## Cross-links

| Card | Note |
| --- | --- |
| [sandbox#41](https://github.com/Exios66/local-mailroom-sandbox/issues/41) | Contracts extraction GT caveat — serving/completion metrics still valid |
| [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) | Keep serving-knob axis separate |
| [mailroom-issues#228](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/228) | Merger quality ladder — interpret scores only after completion fixes |

## Run cells

| Config | Class | Variant |
| --- | --- | --- |
| `hub231-contracts50-baseline.yaml` | contract | Baseline (overlay default max_tokens 4096) |
| `hub231-merger50-baseline.yaml` | merger | Baseline |
| `hub231-contracts50-maxtok8192.yaml` | contract | Raise decode budget (export knobs below) |
| `hub231-merger50-maxtok8192.yaml` | merger | Raise decode budget |
| `hub231-contracts50-maxtok16384.yaml` | contract | High decode budget — watch LengthFinish vs score |
| `hub231-merger50-maxtok16384.yaml` | merger | High decode budget |
| `hub231-contracts50-chunked-stub.yaml` | contract | **YAML stub** — two-pass/chunking needs harness flag (not in RunSpec yet) |
| `hub231-merger50-chunked-stub.yaml` | merger | **YAML stub** — document approach in hub comment before implementation |

### Run-scoped knobs (baseline posture unchanged in YAML)

```bash
# contracts 8192 decode
export SANDBOX_AGENT_KNOBS='{"contracts_specialist":{"max_tokens":8192,"max_input_chars":24000}}'

# merger 8192 decode
export SANDBOX_AGENT_KNOBS='{"merger_agreement_specialist":{"max_tokens":8192,"max_input_chars":24000}}'

# merger 16384 decode (tight against 32768 window — verify context_fit in specialist_posture follow-up)
export SANDBOX_AGENT_KNOBS='{"merger_agreement_specialist":{"max_tokens":16384,"max_input_chars":14000}}'
```

## Operator outline

1. Baseline LengthFinish rates from `sand032-s3-contracts50` / `sand032-s3-merger50` artifacts.
2. Deploy `sandbox-vllm-hub231` once; run contracts batch, then mergers batch.
3. For each variant: set `SANDBOX_AGENT_KNOBS`, `deploy-env`, preflight, start.
4. Publish completed/errored, score, wall, tok/s, slot occupancy, $/doc.
