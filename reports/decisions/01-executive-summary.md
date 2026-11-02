# Executive summary: the decision-reviewer experiments

Experiments of 2026-11-01 (SAND-085, issue #208) tried the Decisions model, `openai/gpt-6-luna-decisions`, as a reviewer in
two places: checking the sorter's class and subclass, and gating the specialist's extraction. This report prices it
against **one Qwen 3.7 Flash call on OpenRouter as 1x** and sets the cost beside what it bought.

## The five findings

**1. A Decisions review costs about one Qwen call, not less.** Per document it is **0.76x** (question set v3.0.0) to
**0.95x** (v2) of the Qwen agent call. An agent plus a Decisions reviewer is **1.76x to 1.95x**, against **2.00x** for
an agent plus a second Qwen call. The saving is **2% to 12%**. [Detail](02-cost-and-effectiveness.md#2-cost-per-document-in-1x-units)

![Pipelines in multiples of one Qwen agent call](figures/f01-cost-stack.svg)

**2. The saving depends on Qwen's long-prompt tier.** Qwen's price triples at 32k prompt tokens. Seventeen merger
agreements, 5% of the test documents, are 53% of the Qwen agent bill. The Decisions model reads at most 120,000
characters, so one call is capped near $0.0028. Price every Qwen call at the lowest tier and the picture reverses: agent
plus Decisions costs **23% to 42% more** than agent plus a second Qwen call. [Detail](02-cost-and-effectiveness.md#3-when-the-saving-disappears)

**3. The money is repaid in people's time.** The Qwen agent alone sends 356 of every 1,000 documents to a person, because
its confidence does not separate its errors (122 of its 127 train errors sit at 0.95 or higher). A calibrated reviewer
cuts that to **15 per 1,000** (Decisions v2) or 19 (chat reviewer). Decisions v2 adds $0.743 per 1,000 documents and
avoids 341 person reviews; it pays back if a review costs more than **$0.0022**. [Detail](02-cost-and-effectiveness.md#4-what-the-money-buys-effectiveness)

![Documents needing a person, per 1,000](figures/f04-person-load.svg)

**4. On held-out documents the Decisions model is as accurate as the chat reviewer, not more.** 98.5% (318 of 323, one
misroute) against 98.1% (311 of 317, one misroute), and 95.7% for the Qwen agent alone. Where the Decisions model differs
is its confidence: on the same 735 train documents all 12 of its v1 errors sit at 0.84 or lower, while 25 of the chat
model's 26 sit at 0.90 or higher. That is supported on train and only suggestive on test. It decides whether cutoffs
work, so the full-train run matters. [Detail](03-classification-reviewer.md#3-does-confidence-separate-right-from-wrong)

**5. The Decisions extraction gate does not work.** Pooled over 910 documents its accept confidence ranks good
extractions below bad (AUROC 0.41), it accepts 26.8% of documents when 11.3% are good, and it says "retry" on 72.4%.
No class reaches the 90% precision target. Its cost cannot be compared to a 1x specialist call because no usage records
are committed, and acting on its verdicts would add up to 0.72 specialist calls per document. [Detail](04-extraction-gate.md)

![Gate accept rate against real quality](figures/f13-gate-accept.svg)

## Where the Decisions model wins and where it does not

| Dimension | Against | Result |
| --- | --- | --- |
| Per-document API cost | second Qwen call (modelled) | cheaper by 2% to 12% at the tiered price; dearer by 23% to 42% at the flat price |
| Per-document API cost | chat reviewer (Luna, measured) | **dearer** by 1.5x to 1.9x |
| Latency | Qwen agent, chat reviewer | faster: median 0.5 s against 2.5 s and 2.05 s (loads differ) |
| People-needed documents | Qwen agent alone | 15 against 356 per 1,000 |
| Held-out accuracy | chat reviewer | equal |
| Confidence usable for cutoffs | chat reviewer | better on train, unproven on test |
| Extraction gating | no gate | no useful signal |

## Decisions the data supports

1. **Use a Decisions review where a person's time costs more than a fraction of a cent**, which is everywhere in this
   pipeline. Do not sell it as a way to halve the API bill; against a Qwen reviewer it saves a few percent on a mixed
   corpus and more only on long documents.
2. **Keep question set v2's routing; do not adopt v3.0.0.** v3.0.0 is 20% cheaper per call and parks 23 test documents for a
   person against 5. Its verdict question mostly answers "continue" whatever the class. The lineage's next step, to derive
   the verdict in code (4.0.0), is the right one.
3. **Run the full-train calibration (v3.1.0, about $2.05) before turning on cutoffs.** Cutoffs moved by up to 0.30
   between calibrations on 150-document draws.
4. **Do not wire the extraction gate into a pipeline.** Redesign it around the per-field questions, one of which
   (`contract.renewal_terms`, AUROC 0.89) shows a real signal.
5. **Replace the modelled 1x reviewer with a measured one** for about $0.25: Qwen on the `sorter_reviewer` route over the
   323 test documents. It is the single measurement that would turn the 2.00x line from an assumption into a result.

Method, source inconsistencies and limits of the comparison are in [05](05-method-and-data-quality.md).
