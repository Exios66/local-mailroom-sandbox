# HUB-229 — Correspondence quality close-gap (SPEND-GATED)

**Hub issue:** [mailroom-issues#229](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/229)  
**Proposed busy-window cap:** `$0.75`  
**Modal app:** `sandbox-vllm-hub229`  
**Priority:** P0 — Modal corr ~0.30 vs API Flash ~0.493; v2 already +0.0415 paired.

> **SPEND-GATED — do not run until Jack go.**

## Goal

Push Modal `overall_extraction_score` toward diagnostic **≥0.40** and document distance to API **0.493**. Prompt axis only — **scale-out methodology stays in #224** (do not conflate 1→N replica sweeps here).

## Frozen L5 serving

- **2×L4:** `max_containers=min_containers=2`, `concurrency` 32, `max_inputs` 32, `max_num_seqs` 16 (same as `sand032-s3-corr50`).
- **1×L4 control:** parity with `sand032-s10-corr75-v2` (`max_inputs` 16, `concurrency` 8).

## Lineage (not DoD)

| Reference | Role |
| --- | --- |
| [mailroom-issues#213](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/213) | Historical correspondence experiment lineage |
| [mailroom-issues#76](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/76) | Earlier corr quality thread |
| `sand032-s10-corr75-v2` | Promoted v2 control cell |

## Cross-links

| Card | Note |
| --- | --- |
| [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) | Scale-out axis **out of scope** for this issue |
| [mailroom-issues#205](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/205) | Related cost/quality tradeoff context |

## Run cells

| Config | n | Fleet | Prompt |
| --- | ---: | --- | --- |
| `hub229-corr50-prod.yaml` | 50 | 2×L4 | `correspondence_specialist_production` |
| `hub229-corr75-v2.yaml` | 75 | 1×L4 | `correspondence_specialist_v2_evalenv` (≡ s10) |
| `hub229-corr50-v2-2xl4.yaml` | 50 | 2×L4 | v2 evalenv |
| `hub229-corr50-variant-a.yaml` | 50 | 2×L4 | stub variant A |
| `hub229-corr50-variant-b.yaml` | 50 | 2×L4 | stub variant B |

## Operator outline

1. Re-run v2 control (`hub229-corr75-v2`) before burning new variants.
2. Offline prompt iteration first; Modal only for finalists after Jack go.
3. Report wall, tok/s, $/doc, $/1M, score, schema %; API Flash 0.493 in a **separate column** (draw caveat).
4. Hub comment + sandbox report; update COST verdict if crossing useful band.
