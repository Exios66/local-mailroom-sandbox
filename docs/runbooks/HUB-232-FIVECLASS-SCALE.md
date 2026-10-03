# HUB-232 — Larger-N five-class L5 scale (SPEND-GATED)

**Hub issue:** [mailroom-issues#232](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/232)  
**Proposed busy-window cap:** `$3.00` (Jack locks which cells run — do not fire all YAMLs in one window).  
**Modal app:** `sandbox-vllm-hub232`  
**Priority:** P1 — AMFAM scale evidence at frozen L5 before heavier tiers (#225).

> **SPEND-GATED — do not run until Jack go.**

## Depends on protocol

Land or cite [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) (and draft #226 if still open) for the **#224 metric set** and separation of scale-out vs serving-knob axes. This issue adds **larger N only** — no `max_num_seqs`, quantization, or graph changes.

## Goal

Publishable five-class table: per-class quality, completion, wall, tok/s, $/doc, $/1M at **n=100** (budget default) and optional **n=200** cells extending nested SAND-032 draws (seed 42, revision `ed7576b…`).

## Frozen serving

Identical L5 block on every specialist cell: 2×L4, c32, Qwen3-8B-AWQ `awq_marlin`, fp8 KV, thinking off, CUDA graphs, `max_num_seqs` 16, `max_inputs` 32.

**Optional 1×L4 correspondence control:** `hub232-corr100-1xl4.yaml` (scale-out demo only — not a serving-knob change).

## Cross-links

| Card | Note |
| --- | --- |
| [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) | Required reporting protocol |
| [mailroom-issues#205](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/205) | COST / AMFAM narrative |
| [mailroom-issues#228–#231](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/228) | Quality/reliability first if budget tight |

## Run matrix

| Class | n=100 (2×L4) | n=200 (2×L4) |
| --- | --- | --- |
| correspondence | `hub232-corr100-2xl4.yaml` | `hub232-corr200-2xl4.yaml` |
| insurance_claim | `hub232-insurance100-2xl4.yaml` | `hub232-insurance200-2xl4.yaml` |
| corporate_record | `hub232-corporate100-2xl4.yaml` | `hub232-corporate200-2xl4.yaml` |
| merger_agreement | `hub232-merger100-2xl4.yaml` | `hub232-merger200-2xl4.yaml` |
| contract | `hub232-contracts100-2xl4.yaml` | `hub232-contracts200-2xl4.yaml` |

1×L4 corr control: `hub232-corr100-1xl4.yaml`.

## Operator outline

1. Confirm #224 protocol merged or explicitly cited in run report.
2. Deploy `sandbox-vllm-hub232` once per busy window; run specialists sequentially (five classes).
3. Export full Modal artifacts + per-class scorecard.
4. Append to AMFAM one-pager / hub comment.
