# Failure-mode audit: `pipeline-qwen-flash-25` (2026-11-15)

**Run:** `config/runs/pipeline-qwen-flash-25.yaml`. Full pipeline, every agent on
`qwen/qwen3.7-flash` via OpenRouter, Decisions-API reviewer. 25 documents, 5 per
class, Hub revision `bc9eab28`. **Status:** done, 25/25 rows, 0 runtime errors,
0 failed nodes. 18 archived, 7 parked for review.
**Evidence:** `data/runtime/runs/pipeline-qwen-flash-25/` (`items.jsonl`,
`nodes.jsonl`, `dataset.jsonl`). The offline reproduction is
`sandbox run preflight --config config/runs/pipeline-qwen-flash-25.yaml --offline`
→ `context_plan`.

## 1. Why every merger agreement archived with a low score

Classification was not the problem: all 5 were classified correctly, the reviewer
accepted them, and `stage_correct = 1`. Extraction quality was. MAUD accuracy was
7/79 questions over the 5 documents (best document 4/16, two at 0). Those 5
documents used 74% of the run's tokens and had a p50 latency of 459 s.

| Document | Chars | Path | MAUD |
|---|---|---|---|
| DOC-d554890e | 343,818 | extract → judge → arbiter → retry ×2 → archive | 4/16 |
| DOC-f4e726a7 | 260,092 | same | 2/15 |
| DOC-52f9a5be | 386,890 | same | 1/17 |
| DOC-5fa0ba13 | 404,118 | same | 0/15 |
| DOC-1e016055 | 418,669 | extract → archive (judge skipped) | 0/16 |

Four causes compound:

1. **16k-window budgets on a 1M-context run (sandbox; fixed by config).**
   `config/taxonomy.overlay.yaml` sizes `merger_agreement_specialist.max_input_chars`
   at 36,008 for the L4 16k-token window. The run's `agent_knobs` widened only
   sorter and intake. The graph therefore cut each merger into about 14 windows
   (`min(90000, 36008 − 4501) = 31,507` chars) per pass, three passes per
   document. That is roughly 40 specialist calls, each with its own prompt
   overhead. The per-chunk merge produced 9 MAUD answer conflicts.
2. **The judge and arbiter see only the start of the document (upstream).**
   `agents/judge.py` truncates the source to `JUDGE_SOURCE_CHARS = 16000`, and
   `agents/arbiter.py` to `SOURCE_CHARS = 16000`. That is 4–6% of a merger
   agreement. The judge flags correct facts from later pages as fabrications.
   The arbiter then orders re-extraction against the visible excerpt (one
   arbiter note said the visible text was "pages 1-6 of 97"), so retries do not
   improve the answers. Two retries cost 270–380 s per document and did not
   lift MAUD accuracy above the judge-skipped document's 0/16 baseline. The
   overlay's `judge.max_input_chars: 80000` has no effect on this window.
3. **The final gate trusts self-reported confidence (upstream).**
   `after_retry_extraction_gated` sends an extraction to `compile_report` when
   its self-reported confidence is at least `judge_band_high` (0.97 for
   mergers). After the last arbiter-ordered retry, the specialist reported at
   least 0.97, so the result archived without a final judge pass. On
   DOC-1e016055 the first extraction already reported at least 0.97 and skipped
   the judge entirely.
4. **Merger ground truth is MAUD-only (scoring, known).** `expected_fields`
   populates only `maud_clause_labels`. The sandbox sets the headline to MAUD
   accuracy (SAND-032), but `extraction_f1/precision/recall` stay at 0 by
   construction and are pinned in `tests/fixtures/scoring_golden`. Read
   `maud_accuracy`, not F1, for this class.

## 2. Other failure modes in this run

| # | Mode | Evidence | Owner |
|---|---|---|---|
| F1 | Contracts park on `judge_partial` despite good CUAD scores | 4/5 parked. CUAD presence F1 0.73–0.95. All 5 (22–39k chars) exceed the 16k judge window; the judge sees 41–72% | upstream (judge window); same root cause as §1.2 |
| F2 | Contracts also split at 18,000 chars | 3 windows per pass for 39k-character contracts. Same 16k posture as §1.1 | sandbox config |
| F3 | Wasted `retry_classify` | 10 runs, all contract or corporate. The sorter reports 0.95, below `high` (0.98 / 0.96), the retry returns the same 0.95, and the decision reviewer accepts anyway | upstream (`classification` and extraction share `high`) |
| F4 | Near-empty input | Correspondence DOC-16dfd03a has 56 chars. It parked with `extraction_miss` plus three `reviewer_*` causes | dataset curation |
| F5 | Low corporate/correspondence field F1 (0–0.18) | Ground truth for those rows is auto-labeled `intent` / `keywords` / `subject_matter` (heuristic `intent_source`), compared as free text | dataset / Dojo scorer |
| F6 | Insurance `judge_partial` (1/5) | DOC-4fd4cf5d. The arbiter ordered a retry for one field and the judge still parked it | watch at volume |
| F7 | Merger cost and latency | 74% of tokens, 154–563 s per document. At volume, mergers set wall time and spend | §1.1 config + §1.2 upstream |

No runtime errors, retries on transport errors, timeouts or cost-cap stops
occurred (`events.jsonl`: preflight_ok → spend_authorized → start → done).

## 3. What changed here (sandbox)

- **Context fit + source windows** (§4): chunking and judge/arbiter excerpts
  follow the routed model's real context window.
- **Preflight `context_plan`** (`src/mailroom_sandbox/job/context_plan.py`). It
  reports §1.1, §1.2, F1, F2 and F4 before any spend, using the taxonomy the run
  would activate. It is advisory and never fails preflight. For this config it
  prints the 14-window merger fan-out, the judge coverage per class (merger 4%,
  contract 41%, corporate 44%), the no-effect judge knob, and the 56-character row.

## 4. Context fit: chunk only when the model cannot take the document

`mailroom_sandbox.context_fit` resizes specialists, `judge` and `arbiter` routed
through OpenRouter to their model's `context_length` (`config/api_prices.yaml`):
`(context_length - max_tokens - 8000) * 2.4` characters. It raises the chunk cap
to match, and `mailroom_sandbox.source_windows` widens the vendored
judge/arbiter excerpts at activation. Modal, vLLM, Ollama and LM Studio routes
keep the 16k posture, and the windows are restored on their activation.

For this run's config, the plan now reads:

| Class | Windows per pass (before → after) | Judge coverage of longest doc |
|---|---|---|
| merger_agreement | 14 → 1 | 4% → 100% |
| contract | 3 → 1 | 41% → 100% |
| corporate_record | 2 → 1 | 44% → 100% |

The near-empty-row warning remains. **Not yet measured:** whether MAUD accuracy
and the contract `judge_partial` rate improve needs a paid rerun. The judge
and arbiter now read whole documents, so merger input tokens per judge/arbiter
call grow about 26× (16k → ~420k characters). Single-pass extraction drops the
chunk overlap and per-chunk prompt overhead. Fewer arbiter-ordered retries
should offset part of the judge growth. Re-check `job.api_cost_cap_usd`
before scaling up. Set `context_fit.enabled: false` in the overlay, or use run
`agent_knobs`, to keep the old posture.

## 5. Upstream handoff (llm-mailroom v0.30 / v0.31)

1. Make the judge and arbiter source windows configurable (the sandbox
   override in `source_windows.py` is a stopgap until then). Honour
   `agents.judge.max_input_chars` and give the arbiter an equivalent. Better
   still, judge per chunk or against the retrieved spans that the extraction
   cites. Do not let the arbiter order a re-extraction from an excerpt that
   omits the cited pages.
2. After an arbiter-ordered retry, require a judge pass or the arbiter's
   acceptance before archiving. Do not gate on the specialist's
   self-reported confidence.
3. Split classification thresholds from extraction thresholds, or skip
   `retry_classify` when Lane A review will run anyway (F3).
4. Dojo: report merger extraction P/R/F1 as unscored (null), not 0, when the
   ground truth has no schema fields. Today that 0 is a golden-pinned
   contract, so it needs a coordinated golden update.
5. Dataset: drop or flag rows under ~200 characters, and re-label the heuristic
   corporate/correspondence fields (F4, F5).
