# SAND-214 window runs — interpretation and pipeline application

The three window runs that were executed on Modal for #214 (contracts r1,
contracts r2 with the length fix, merger `maud_v2`; n=30 each on the
runbook-v2 calibration split, Qwen3-8B-AWQ on one L4 at client concurrency 16)
are committed under `reports/SAND-214/2026-11-21/`. The two follow-up
experiments they configured — the window-length suite
(`sand214-window-length`, arms 28k/16k) and the full-pipeline confidence
cutoffs (`sand214-pipeline-150-calibration-judge-all`) — have **not** run: the
window arms' starts stopped at the Modal engine probe (HTTP 404, app not
deployed, no GPU billed), and the cutoff run is gated on the owner's go-ahead.
The analysis below therefore covers the executed runs only.

## Re-derived results

Every headline number re-derives from the committed per-document data
(`figures/sand214-windows.figure-data.csv`, `*.serving.json`,
`routing/*.routing.json`) and matches the run README:

| Claim | Re-derived value |
| --- | --- |
| r1 / r2 / merger mean score | 0.6158 / 0.6523 / 0.0911 |
| Paired r1→r2 delta | +0.0365, 15 wins / 13 losses, same 30 documents |
| r1 lost windows | 6 windows on 5 documents (one document lost two) |
| r1 lost-window documents | 0.467 → 0.661 mean after the fix |
| Confidence ≥ 0.85 vs < 0.85 (r1 / r2) | 0.584 vs 0.644 / 0.665 vs 0.644 |
| Confidence–quality correlation | r1 −0.227, r2 +0.118, merger +0.162 |
| r2 score by window count | 2w 0.636 (13), 3w 0.638 (7), 4w 0.694 (7) |
| window_rules AUROC (r2) | min 0.47, max 0.59, length-weighted 0.61; adopted rule unchanged (`min`) |
| GPU cost | r1 $0.331 (393 s idle), r2 $0.621 (1,930 s idle), merger $0.840 |

Two refinements beyond the run README (now corrected in the README itself):

- r1 dropped **six** windows across the five affected documents (one document
  dropped two); the README originally counted documents.
- r2 recorded a stated confidence of `0.0` on two documents that scored 0.714
  and 0.482, and merger's 13 zero-confidence documents (mean 0.081) do not
  separate from its 17 confident ones (0.099). Self-reported confidence has no
  usable signal in either direction.

## No aggregate per-document signal works either

Every per-document signal recorded by the executed runs was scored against the
0.7 quality target (AUROC, committed figure data plus the reports' per-document
token and latency tables):

| Signal | r1 | r2 |
| --- | --- | --- |
| Self-reported confidence | 0.357 | 0.471 |
| Document characters | 0.447 | 0.543 |
| Window count | 0.534 | 0.613 |
| Failed windows | 0.503 | 0.500 |
| Latency | 0.478 | 0.611 |
| Completion tokens | 0.565 | 0.606 |
| Prompt tokens | 0.491 | 0.548 |
| Completion tokens / char | 0.578 | 0.493 |

Self-reported confidence is not merely uninformative — it ranks **below
chance** on r1. The other aggregates hover at noise level and flip direction
between runs, so none is a routing basis. (Merger met the target on 0 of 30
documents, so nothing is measurable there until its extraction is fixed.)

## The measure with a basis in model behavior: cross-window agreement

Self-consistency between independent reads of overlapping text is the one
signal class none of these aggregates captures: two windows that read the same
clauses and assert the same values are evidence about the extraction that no
single-call number carries. The HF-008 merge wrapper now computes and records
it at merge time (`_window_agreement`: mean pairwise agreement over the fields
two or more windows both assert — Jaccard for list fields, exact on a
whitespace/casefolded comparable form for scalars). Two normalization facts
shape it, both caught in review: the vendored `normalize_extraction` fills
every schema key, so `None`/`[]`/`{}` mean "not seen in this window" — a value
is never scored against a window's fill, and two fills are not scored as
agreement either; and `reasoning` (the per-field trace contracts and merger
emit) plus the per-window `confidence` are excluded, because a trace and a
self-report are not asserted content. A field only one window asserts is
skipped, not scored as a conflict. The routing audit's `window_rules` block
ranks it (`auroc.agreement`) beside min/max/length-weighted, so the
150-document confidence-cutoff run — which judges every first pass — measures
whether agreement predicts judged quality where confidence does not.

Deliberate scope: agreement is only recorded where windows exist (a
single-window extraction takes the plain path and records nothing), and it is
a routing input under test, not yet a gate — no band, cutoff or archive
decision reads it until the cutoff run's labelled comparison justifies one.

## Interpretation

1. **The length fix is the one change worth propagating.** A chunk window's
   decode can run to the output cap; vLLM raises
   `LengthFinishReasonError`, the vendored chunked pass records
   `chunk_call_failed`, and the window is silently absent from the merge. The
   Qwen3 non-thinking sampling (top_p 0.8, top_k 20, presence_penalty 1.0)
   plus one length re-sample removed the failure entirely on the same
   documents, and the recovered windows carry most of the +0.036 paired gain.
2. **No merge-rule switch is justified at n=30.** The adopted
   weakest-window rule stays; AUROC 0.47–0.61 across rules is noise-level.
3. **Specialist confidence cannot set judge bands.** The band has to be fitted
   on judged pipeline outcomes, which is exactly what the committed
   `sand214-pipeline-150-calibration-judge-all.yaml` run measures.
4. **Merger quality (0.091) is an extraction/prompt failure, not a merging
   one** — no agreement reached 0.7 and no rule or band is measurable there
   until that is fixed.
5. **Window count barely moves contracts quality** (0.636 → 0.694 from 2 to 4
   windows); the committed 28k/16k arms will measure whether shorter windows
   hold that while cutting per-window decode length.

## Applied to the pipeline

- **Length-fix default for chunked specialists** (`job/length_fix.py`,
  wired into preflight's `_run_knobs`): a `task: pipeline` run on a
  self-hosted vLLM engine (`modal-vllm`, `vllm-local`, `vllm-remote`) with a
  Qwen3-family model now defaults the length-fix sampling for the five
  specialist agents it did not configure, because the vendored graph chunks
  long documents for every one of them. Explicit `agent_knobs` and posture
  rows always win; an explicit `length_retries: 0` opts an agent out. The
  merged knobs freeze into the run lock at preflight, so the locked run
  executes exactly what preflight disclosed, and API (OpenRouter) runs are
  untouched — they never chunk.
- Already landed by the window work itself: the routing audit reads live
  extraction confidence on every class with window-rule AUROC and
  failed-window exclusions (#396), and preflight warns on a chunked agent
  with no `length_retries` — a warning the new default satisfies for
  pipeline runs.
- Deliberately unchanged: the merge rule (stays weakest-window), the
  confidence bands (they move only after a judged pipeline run fits them,
  with ≥ 5 scored documents above a band), and every API-served
  configuration.

## Still gated

- The window-length arms and the confidence-cutoff run are paid work: they
  need the owner's initials at `sandbox run start` and, for the arms, a
  deployed Modal app first. Preflight passes offline for all three configs
  (the cutoff config additionally needs `OPENROUTER_API_KEY` in the shell,
  which is the spend gate working as designed).
- Merger extraction quality must be fixed before any window or band
  measurement on merger is meaningful.
