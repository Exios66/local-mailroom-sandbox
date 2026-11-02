# Cost and effectiveness against a 1x Qwen call

**Question.** Take the Qwen 3.7 Flash call on OpenRouter as the base cost, 1x, for each task. What does the
Decisions model cost as a reviewer next to one more LLM call, and what does that money buy?

**Short answer.** At the Qwen price sheet's real tiers, a Decisions review costs **0.76x to 0.95x** of one Qwen agent
call. An agent plus a Decisions reviewer is **1.76x to 1.95x**, against **2.00x** for an agent plus a second Qwen call.
That is a saving of **2% to 12%** per document, not a halving. The saving is conditional (section 3), and the
bigger effect is in people's time (section 4). Against the chat-model reviewer the sandbox measured, the Decisions
model is *dearer* per document.

All figures rebuild with `python reports/decisions/build_decisions_report.py`. Source data and the arithmetic are in
[`data/summary.json`](data/summary.json).

---

## 1. How 1x is defined

| Term | Definition | Source |
| --- | --- | --- |
| **1x agent call** | One `qwen/qwen3.7-flash` call that reads a whole document (the sorter task). Priced per call with the OpenRouter sheet's long-prompt tiers: $0.03 / $0.13 per 1M tokens below 32k prompt tokens, $0.10 / $0.40 from 32k, $0.20 / $0.80 from 256k. | `config/api_prices.yaml` |
| **Measured tokens** | The saved Qwen pass: 323 test documents, 4,132,455 prompt tokens and 45,021 completion tokens. Per-document tokens, so each call lands in its own tier. | `data/handoff/sorter-qwen3.7-flash/test.jsonl` |
| **1x unit** | **$0.000778 per document** ($0.778 per 1,000), tiered. The handoff manifest records $0.1298 for the same pass because it prices every call at the lowest tier; section 3 shows both. | computed |
| **1x LLM reviewer** | A second Qwen call over the same document, so 1.00x. This is **modelled**: no Qwen-as-reviewer run exists. It is the only way to apply "Qwen as the base cost" to the reviewer task. | assumption |
| **Decisions reviewer** | `openai/gpt-6-luna-decisions`: $0.10 per 1M input tokens, nothing for output. Cost is the recorded run cost over the same test documents. | calibration reports, `LINEAGE.yaml` |

The test split is the held-out one (323 documents), so every arm below is priced and scored on the same documents
unless a row says otherwise.

## 2. Cost per document, in 1x units

![Pipelines in multiples of one Qwen agent call](figures/f01-cost-stack.svg)

| Pipeline | Basis | Agent | Reviewer | Total | USD per 1,000 docs | vs 2.00x |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Qwen agent alone | measured | 1.00x | – | 1.00x | $0.78 | – |
| **Agent + Qwen reviewer (traditional)** | modelled | 1.00x | 1.00x | **2.00x** | $1.56 | base |
| Agent + chat reviewer (Luna, `decision_v1` prompt) | measured, 317 docs | 1.00x | 0.49x | 1.49x | $1.16 | -25% |
| **Agent + Decisions, question set v2** | measured | 1.00x | 0.95x | **1.95x** | $1.52 | **-2%** |
| **Agent + Decisions, question set v3.0.0** | measured | 1.00x | 0.76x | **1.76x** | $1.37 | **-12%** |

What the table says:

- **Against a second Qwen call, Decisions is cheaper**, by 2% (v2) or 12% (v3.0.0). The v3.0.0 set reads fewer
  tokens per document because its criteria are compact (`config/decisions/LINEAGE.yaml`).
- **Against the chat model the sandbox actually measured, Decisions is dearer.** Luna chat at $0.10 / $0.50 per 1M
  tokens cost $0.122 for 317 test documents; Decisions cost $0.24 (v2) or $0.1905 (v3.0.0) for 323. Per document that
  is 1.5x to 1.9x the chat reviewer. The Decisions request carries about 3,100 tokens of questions on every call.
- **A Decisions call is not a cheaper way to do the same read.** It is a different request: no output tokens, a
  probability for every option, and class, subclass and verdict in one call.
- The Qwen reviewer row is an assumption, not a measurement. Its real cost depends on the reviewer prompt's length;
  a reviewer prompt shorter than the sorter's would make that row cheaper. The one run that would settle it
  (Qwen on the `sorter_reviewer` route over the 323 test documents) costs about $0.25. See
  [05](05-method-and-data-quality.md#what-to-measure-next).

### Where a Qwen bill comes from

![Qwen agent cost by class](figures/f03-qwen-by-class.svg)

| Class | Documents | Mean prompt tokens | Tiered USD | Flat USD | Share of bill |
| --- | ---: | ---: | ---: | ---: | ---: |
| merger agreement | 17 | 77,254 | $0.1323 | $0.0397 | **53%** |
| contract | 60 | 15,554 | $0.0464 | $0.0291 | 18% |
| corporate record | 47 | 12,308 | $0.0298 | $0.0182 | 12% |
| insurance claim | 114 | 6,530 | $0.0244 | $0.0244 | 10% |
| correspondence | 85 | 6,623 | $0.0184 | $0.0184 | 7% |

Seventeen merger agreements, 5% of the documents, are 53% of the Qwen agent bill, because 24 documents (7%) cross the
32k-token tier and are billed 3.3x per token. The Decisions model reads at most 120,000 characters of a document
(about 25,000 tokens, plus about 3,100 of questions), so a single call is capped near **$0.0028** and cannot cross a
price tier. The merger agreements average 77,254 prompt tokens in the Qwen pass. That cap is where a Decisions review can be cheaper than a Qwen call, and it only matters on long documents.

## 3. When the saving disappears

![Total cost under tiered and flat Qwen prices](figures/f02-sensitivity.svg)

| Pipeline | Tiered Qwen price | Saving vs 2.00x | Flat $0.03 / $0.13 | Saving vs 2.00x |
| --- | ---: | ---: | ---: | ---: |
| Agent + Decisions v3.0.0 | 1.76x | **+12.1%** | 2.47x | **-23.4%** |
| Agent + Decisions v2 | 1.95x | **+2.3%** | 2.85x | **-42.4%** |

If every Qwen call were billed at the lowest tier, the agent unit would be $0.000402 per document, a Decisions review
would be 1.5x to 1.8x of it, and the agent-plus-Decisions pipeline would cost 23% to 42% *more* than agent-plus-second-Qwen-call.

So the cost claim holds **only where Qwen is billed at its higher tiers**, which is to say on long documents. On the
92.6% of test documents under 32k tokens, a Qwen call is the cheaper call. A fair statement is:

> A Decisions reviewer costs about the same as one more Qwen call. It is cheaper only on long documents, and the
> saving on a mixed corpus is between 2% and 12%.

The manifest's flat figure ($0.1298) understates what OpenRouter bills for the pass by about half: the price sheet
puts it at $0.2513. This report uses the sheet.

## 4. What the money buys: effectiveness

Cost per call is the smaller story. The sorter alone cannot say which of its answers to trust: its 127 wrong classes
on the 2,979 train documents have a median confidence of 0.95, the same as its right answers, and 122 of the 127 sit at
0.95 or higher. A reviewer is worth buying if it separates the documents that need a person from those that do not.

![Documents needing a person, per 1,000](figures/f04-person-load.svg)

| Arm (held-out test) | Class accuracy | Needing a person, per 1,000 | Misrouted when routed unattended | Per document vs 1x |
| --- | ---: | ---: | --- | ---: |
| Qwen agent alone | 95.7% (309 / 323) | **356** | not separable by confidence | 1.00x |
| Chat reviewer, default prompt | 95.6% (303 / 317) | 208 | cutoffs: 0 / 0.4% | 0.39x |
| Chat reviewer, `decision_v1` prompt | 98.1% (311 / 317) | 19 | 0.3% (1 of 311) | 0.49x |
| **Decisions v2** | **98.5% (318 / 323)** | **15** | **0.3% (1 of 318)** | 0.95x |
| Decisions v3.0.0 | 98.5% (318 / 323) | 71 | 0.3% (1 of 300) | 0.76x |

### Reading the effectiveness table

1. **A reviewer cuts the people-needed load by about 95%.** From 356 per 1,000 for the Qwen agent alone to 15 to 19 per
   1,000 for a calibrated reviewer. This is the largest effect in the data.
2. **The money is repaid at a fraction of a cent.** Decisions v2 adds $0.743 per 1,000 documents and avoids 341 person
   reviews per 1,000. It pays for itself if a person review costs more than **$0.0022**. Decisions v3.0.0 adds $0.590 and
   avoids 285, which makes it $0.0021 per review. No human cost is assumed: these are break-even figures, not savings.
3. **On the held-out test, the chat reviewer and the Decisions model are indistinguishable.** 311 of 317 against 318 of
   323, one misroute each. The accuracy gap is under half a percentage point, well inside sampling noise for 320 documents. The test does not show Decisions as the more accurate reviewer.
4. **The difference is in the confidence, and the evidence is on the train draw.** On the same 735 documents, the
   chat model's wrong answers were all at 0.86 to 0.99, and 25 of 26 were at 0.90 or higher. The Decisions model's v1
   errors were all at 0.84 or lower, so a cutoff parks them.

   ![Wrong answers at high confidence](figures/f07-wrong-conf.svg)

   On the test split the gap narrows: 2 of 5 Decisions errors and 3 of 6 chat errors sit at 0.90 or above. Treat the
   confidence advantage as supported on train, suggestive on test, and unproven at scale until the full 2,979-document
   run (`reviewer-calibration-luna-decisions-v3.1.0-train`, planned, about $2.05).
5. **v3.0.0 costs less per call and more in people.** Its verdict question parked 23 test documents against 5 for
   v2, for a 20% lower API bill. See [03](03-classification-reviewer.md#question-set-v300-the-verdict-question).

### Latency

![Latency by call](figures/f05-latency.svg)

A Decisions call returns in a median 0.5 s (p95 0.9 s). The Qwen agent pass was 2.5 s (p95 7.6 s), and the chat
reviewer 2.05 s (p95 2.8 s). The load differs between the three runs (see the figure note), so read this as direction,
not a benchmark. A reviewer step that adds 0.5 s to a pipeline adds far less wall time than a second Qwen call.

## 5. The extraction task

The 1x for extraction is the Qwen 3.7 Flash specialist call. The Decisions model was tried there as a gate over the
specialist's extraction (`task: extraction_gate`). **Cost parity cannot be computed from tracked files**: the run
configs carry token and dollar *estimates* ($0.24 for 220 documents), not usage records. More to the point, the gate did
not work, so its price is moot:

- Pooled over 910 documents, the gate's accept confidence ranks good extractions *below* bad ones (AUROC 0.41).
- It says "accept" on 26.8% of documents; 11.3% of extractions really score 0.80 or higher.
- It says "retry" on 72.4% (659 of 910). Acting on that verdict would trigger up to 0.72 extra specialist calls per
  document, at 1x each, for no measured gain.

Details in [04](04-extraction-gate.md). **Do not wire the gate into a pipeline as it stands.**

## 6. Bottom line

| Claim | Holds? |
| --- | --- |
| Decisions as reviewer is cheaper than a second Qwen call | **Yes, narrowly**: 2% to 12% at the tiered price; no at the flat price |
| Decisions is cheaper than the chat reviewer | **No**: 1.5x to 1.9x per document |
| A Decisions call is faster than a Qwen call | **Yes**: median 0.5 s against 2.5 s (different loads) |
| A calibrated reviewer cuts people-needed documents | **Yes**: 356 to 15 per 1,000 (v2) |
| Decisions is more accurate than the chat reviewer on held-out documents | **Not shown** |
| Decisions' confidence is better calibrated | **Supported on train, suggestive on test** |
| The Decisions extraction gate is usable | **No** |
