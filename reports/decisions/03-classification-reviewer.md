# Classification reviewer experiments

The Decisions-model reviewer checks the sorter's class and subclass for every document before extraction. Work ran
2026-11-01 under SAND-085 (issue #208). Sources: `reports/reviewer-calibration/`, `config/decisions/LINEAGE.yaml`,
`reports/sorter-handoff/sorter-qwen3.7-flash-audit.md`.

## 1. The model mix-up, and what it cost

Every reviewer run before the Decisions work used `openai/gpt-6-luna`, the plain chat model, through the `api` backend.
The model writes its own confidence into JSON. The Decisions model (`openai/gpt-6-luna-decisions`, OpenRouter
`POST /api/alpha/decisions`) returns a probability for every option and bills input tokens only. About **$2.50** went
to chat-model runs. Their findings carried into the question sets; their cutoffs do not apply. Guards now in the code
refuse a Decisions model on a chat backend, a chat model on the Decisions backend, and a paid reviewer run with no
`reviewer:` block.

## 2. Class accuracy across runs

![Class accuracy by run](figures/f06-accuracy.svg)

| Run | Split | n | Correct | Accuracy |
| --- | --- | ---: | ---: | ---: |
| Qwen agent (the sorter) | test | 323 | 309 | 95.7% |
| Chat · default prompt | train | 735 | 709 | 96.5% |
| Chat · default prompt | test | 317 | 303 | 95.6% |
| Chat · `decision_v1` prompt | train (in-sample) | 735 | 733 | 99.7% |
| Chat · `decision_v1` prompt | test | 317 | 311 | 98.1% |
| Chat · v3 prompt | test | 323 | – | 98.8% (as reported) |
| Decisions · question set v1 | train | 735 | 723 | 98.4% |
| Decisions · question set v2 | train (in-sample) | 735 | 735 | 100.0% |
| **Decisions · question set v2** | **test** | 323 | **318** | **98.5%** |
| Decisions · question set v3.0.0 | test | 323 | 318 | 98.5% |

Hollow dots in the figure are train runs, where the prompt or question set was tuned on the same documents. They are
not evidence of how the reviewer will do on new documents. **The honest numbers are the filled dots**: about 98.5% on
held-out documents for both reviewer models, against 95.7% for the Qwen agent alone.

The single misroute in both held-out Decisions runs is a "LIMITED POWER OF ATTORNEY" labelled contract / Service. The
reviewer says corporate_record / powers_of_attorney at 1.0, which reads as a label error, and the sorter audit moved the
label. The other test miss at 1.0 is an accounting standard (EITF 96-13) that the reviewer calls `unknown`; `unknown`
is not a decision class, so it parks for a person.

## 3. Does confidence separate right from wrong?

A cutoff only helps if wrong answers sit below it.

![Wrong answers at high confidence](figures/f07-wrong-conf.svg)

| Run | Wrong at confidence 0.90 or higher |
| --- | --- |
| Qwen agent, train (0.95 threshold) | 122 of 127 |
| Chat default prompt, test | 14 of 14 |
| Chat default prompt, train | 25 of 26 |
| Chat `decision_v1`, test | 3 of 6 |
| Decisions v2, test | 2 of 5 |
| Decisions v1, train | **0 of 12** (all at 0.52 to 0.84) |

The chat model compresses its confidence: 549 of its 709 correct answers on train sit at 0.99. No cutoff separates its
errors from its right answers; the only contract cutoff that reached 95% was 1.0, which kept 21% of contracts. The Decisions
probabilities spread, and the v1 errors all fell below any sensible cutoff. On the small test split the two models look
alike. The plain reading is that the Decisions advantage is *in the confidence*, shown on the train draw, and not yet
confirmed on test.

## 4. Cutoffs

![Cutoffs by calibration](figures/f08-cutoffs.svg)

Cutoffs come from five-fold cross-fit at a 95% held-out accuracy target with Wilson 95% intervals.

| Class | Chat default | Chat `decision_v1` | Chat v3, full train | Decisions v1 | Decisions v2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| contract | 1.00 | 0.91 | 0.79 | 0.62 | 0.78 |
| corporate record | 0.86 | 0.90 | 0.88 | 0.66 | 0.96 |
| correspondence | 0.71 | 0.57 | 0.54 | 0.52 | 0.64 |
| insurance claim | 0.61 | 0.90 | 0.78 | 0.41 | 0.70 |
| merger agreement | 0.98 | 0.93 | 0.90 | 0.99 | 0.99 |

Two things to take from it:

- **Cutoffs are unstable.** Corporate record goes 0.66 to 0.96 between Decisions v1 and v2; insurance claim 0.41 to
  0.70. With no wrong answers in a class, the cutoff is just the lowest confidence of a right answer, so a 150-document
  draw sets it. Use the cutoffs from the full-train run before the pilot goes live. Issue #208 keeps them provisional.
- **The 95% target was missed only twice**, both for the chat model with the default prompt: contract (88.2%, 20.6% of
  documents accepted at the one cutoff that gets close) and corporate record (98.5% with a lower bound of 94.7%).
  Decisions v1 missed correspondence (lower bound 91.8%) because of First Notice of Loss errors, fixed in v2.

## 5. The v1 to v2 improvement loop

v1 made 12 class errors on the train draw, all at probability 0.52 to 0.84:

| Error | Count | v2 change |
| --- | ---: | --- |
| insurance claim (First Notice of Loss) read as correspondence or unknown | 8 | FNOL forms named in the insurance criterion; correspondence excludes claim paperwork |
| corporate record (untitled subsidiary table) read as unknown | 2 | A bare table of company names and jurisdictions is a subsidiary list |
| merger agreement ("Transaction Agreement" with merger subsidiaries) read as contract | 2 | Transaction and business-combination agreements that merge through a Merger Sub are mergers |

![Subclass accuracy, v1 to v2](figures/f09-dumbbell.svg)

Six of seven weak subclasses improved; `correspondence / meeting_request` fell from 18 of 21 to 14 of 21 as the
correspondence markers became yes/no questions. Train subclass accuracy rose from 78.0% to 82.6%, and to 88.0%
(604 of 686) once the 49 merger documents labelled `other` are excluded.

**What limits subclass accuracy now is the labels**, not the reviewer:

1. Merger `other` means "unannotated" (no MAUD Type of Consideration), so no reader can predict it. On the 86 annotated
   mergers v2 is right on 84 (97.7%).
2. Correspondence subclasses are keyword labels. An ordinary email that mentions demand letters is labelled `demand`.
3. Corporate records carry label noise: 9 "Certificate of Amendment" documents labelled `board_resolution`, bylaws labelled
   `articles_of_incorporation`.

The sorter audit applied 28 train and 4 test label corrections; 49 train and 8 test merger `other` rows are scored for
class only.

## 6. Question set v3.0.0: the verdict question

v3.0.0 added the sorter's answer to the request and a verdict question (continue, correct the subclass, reclassify, or
human review). On the held-out test it kept class accuracy and added people-work:

![Verdict given, by what the handoff needed](figures/f10-verdict.svg)

| What the sorter handoff needed | Documents | Verdict: continue | Correct subclass | Reclassify | Multiple docs | Human review |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sorter was right | 174 | **170** | 2 | 0 | 1 | 1 |
| Subclass was wrong | 135 | 125 | **4** | 2 | 3 | 1 |
| Class was wrong | 14 | 10 | 0 | **1** | 0 | 3 |

The verdict does not follow the model's own `doc_type` answer: with the class wrong on 14 documents it said "continue"
10 times, and with only the subclass wrong on 135 it said "continue" 125 times. Subclass accuracy slipped from 265 to
263 of 323.

![Documents parked for a person, v2 against v3.0.0](figures/f11-human-by-class.svg)

| Class | v2 parked | v2 rate | v3.0.0 parked | v3.0.0 rate |
| --- | ---: | ---: | ---: | ---: |
| contract | 1 / 59 | 1.7% | 1 / 60 | 1.7% |
| corporate record | 1 / 48 | 2.1% | 5 / 48 | 10.4% |
| correspondence | 1 / 83 | 1.2% | 7 / 81 | 8.6% |
| insurance claim | 0 / 114 | 0.0% | 2 / 114 | 1.8% |
| merger agreement | 0 / 17 | 0.0% | 5 / 17 | 29.4% |
| unknown | 2 / 2 | 100% | 3 / 3 | 100% |
| **all** | **5 / 323** | **1.5%** | **23 / 323** | **7.1%** |

Four of nine human verdicts were email forwards called `multiple_documents`. v3.0.0 is cheaper per call (about 20%) and
sends nearly five times as many documents to a person. **It is not an improvement.** `LINEAGE.yaml` already marks 3.1.0
(insurance subclasses cover the whole taxonomy; a forward is not `multiple_documents`) as the frontrunner, and proposes
deriving the verdict *in code* from the doc_type and subclass answers for 4.0.0, keeping only the human edge cases as a
model question. This report agrees with that plan.

## 7. The sorter the reviewer checks

![Sorter class errors by pattern](figures/f12-sorter-errors.svg)

The Qwen sorter gets 95.7% of classes right on train (2,852 of 2,979) and 69 to 72% of subclasses. Its 127 class errors
are three patterns, and the Decisions reviewer had already agreed with the label on 33 of them. They are sorter errors,
not label errors. Sorter prompt V15 (llm-mailroom #135) encodes the fixes and has not yet been validated by a run.

## 8. Pipeline smoke

`pipeline-luna-decisions-qwen-smoke`: ten documents through the full pipeline, Qwen3.7 Flash on every node, the
Decisions reviewer on all five classes with v2 cutoffs. All ten classified correctly; the reviewer accepted nine at 0.98
to 1.0 and sent a property claim at 0.65 (cutoff 0.70) to a person as `reviewer_low_confidence`, which is the routing the
cutoff is for. 176 s wall; the longest document (a 442,000-token merger) took 173 s end to end.
