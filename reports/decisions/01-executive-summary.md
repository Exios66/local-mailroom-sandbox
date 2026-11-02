# Executive summary: the decision-reviewer experiments

Experiments of 2026-11-01 (SAND-085, issue #208) tried the Decisions model, `openai/gpt-6-luna-decisions`, as a reviewer in
two places: checking the sorter's class and subclass, and gating the specialist's extraction. This report prices it
against **one Qwen 3.7 Flash call on OpenRouter as 1x** and sets the cost beside what it bought.

## The five findings

**1. A Decisions review costs about one Qwen review, not less.** The Qwen reviewer was measured on 2026-11-02 (Qwen 3.7 Flash,
the same 323 test documents, OpenRouter): **0.84x** of the agent call. A Decisions review is **0.91x (v3.0.0) to 1.14x (v2)** of
that. Agent plus Decisions is **1.76x to 1.95x**, against **1.84x** for agent plus a Qwen reviewer: **4% cheaper or 7%
dearer**. The 2% to 12% saving in the first version of this report came from a modelled 2.00x and does not survive the
measurement. [Detail](02-cost-and-effectiveness.md#2-cost-per-document-in-1x-units)

![Pipelines in multiples of one Qwen agent call](figures/f01-cost-stack.svg)

**2. Cost is not where the Decisions model wins, and Qwen's long-prompt tier decides even the narrow cost result.** Qwen's price
triples at 32k prompt tokens. Seventeen merger agreements, 5% of the test documents, are 53% of the Qwen agent bill. The
Decisions model reads at most 120,000 characters, so one call is capped near $0.0028. Price every Qwen call at the lowest tier
and agent plus Decisions costs **42% to 64% more** than agent plus a Qwen reviewer. [Detail](02-cost-and-effectiveness.md#3-when-the-saving-disappears-and-when-it-never-appeared)

**3. Qwen as a reviewer does not review.** On the same 323 documents it got **93.8%** of classes right (the Qwen agent alone:
95.7%; Decisions v2: **98.5%**), and **all 20 of its wrong answers carry confidence of 0.90 or higher**, so no cutoff catches
them. About **25 wrong documents per 1,000** are routed with no person, against **3** for Decisions. For $0.093 more per 1,000
documents (Decisions v2), 22 fewer wrong documents get through: **$0.0043 per wrong document avoided**.
[Detail](02-cost-and-effectiveness.md#4-what-the-money-buys-effectiveness)

![Wrong documents routed with no person, per 1,000](figures/f15-silent-errors.svg)

**4. A calibrated reviewer is repaid in people's time.** The Qwen agent alone sends 356 of every 1,000 documents to a person,
because its confidence does not separate its errors (122 of its 127 train errors sit at 0.95 or higher). Decisions v2 cuts that to **15
per 1,000**; it pays back against the agent alone if a review costs more than **$0.0022**. On held-out accuracy it ties the
Qwen reviewer (98.5% against 93.8%): its confidence advantage is shown on train and only suggestive on test. [Detail](03-classification-reviewer.md#3-does-confidence-separate-right-from-wrong)

![Documents needing a person, per 1,000](figures/f04-person-load.svg)

**5. The Decisions extraction gate does not work.** Pooled over 910 documents its accept confidence ranks good
extractions below bad (AUROC 0.41), it accepts 26.8% of documents when 11.3% are good, and it says "retry" on 72.4%.
No class reaches the 90% precision target. No usage records are committed to price it, and acting on its verdicts would add up
to 0.72 specialist calls per document. [Detail](04-extraction-gate.md)

![Gate accept rate against real quality](figures/f13-gate-accept.svg)

## Where the Decisions model wins and where it does not

| Dimension | Against | Result |
| --- | --- | --- |
| Per-document API cost | Qwen reviewer (measured) | 4% cheaper (v3.0.0) to 7% dearer (v2) at the tiered price; 42% to 64% dearer at the flat price |
| Latency | Qwen agent, Qwen reviewer | faster: median 0.5 s against 2.5 s and 2.7 s (loads differ) |
| People-needed documents | Qwen agent alone | 15 against 356 per 1,000 |
| Held-out accuracy | Qwen reviewer | **better**: 98.5% against 93.8% |
| Wrong documents routed with no person | Qwen reviewer | **better**: 3 against 25 per 1,000 |
| Confidence usable for cutoffs | Qwen reviewer | **better**: all 20 Qwen errors sit at 0.90+; 2 of Decisions' 5 test errors do |
| Extraction gating | no gate | no useful signal |

## Decisions the data supports

1. **Use a Decisions review instead of a Qwen reviewer for accuracy and confidence, not for cost.** Cost is a wash (-4% to
   +7%); 22 fewer wrong documents per 1,000 reach no person for about $0.09 per 1,000. Do not describe it as a saving.
2. **Keep question set v2's routing; do not adopt v3.0.0.** v3.0.0 is 20% cheaper per call and parks 23 test documents for a
   person against 5. Its verdict question mostly answers "continue" whatever the class. The lineage's next step, to derive
   the verdict in code (4.0.0), is the right one.
3. **Run the full-train calibration (v3.1.0, about $2.05) before turning on cutoffs.** Cutoffs moved by up to 0.30
   between calibrations on 150-document draws.
4. **Do not wire the extraction gate into a pipeline.** Redesign it around the per-field questions, one of which
   (`contract.renewal_terms`, AUROC 0.89) shows a real signal.
5. **Test whether a better-prompted Qwen reviewer closes the gap.** The Qwen reviewer ran once, on the default prompt and without the
   sorter's answer. A prompt that states the corpus conventions targets the two boundaries behind 19 of its 20 errors
   (mailbox fragments as correspondence, corporate records against contracts). About $0.2 per variant.

Method, source inconsistencies and limits of the comparison are in [05](05-method-and-data-quality.md).
