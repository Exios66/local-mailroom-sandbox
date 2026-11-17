# Autoresearch: a greedy, config-only lever search

`sandbox autoresearch` improves a run spec the way a careful operator would, one change at a time, and
keeps an auditable record. It changes **no pipeline code**: every candidate is the current champion spec plus
ONE lever (a dotted-path patch), validated as a `RunSpec`, then run through the existing locked-run
lifecycle (`sandbox run preflight`, `sandbox run start`, the production gate).

## Commands

```bash
sandbox autoresearch plan    --study PATH               # weakness table + the next lever; runs nothing
sandbox autoresearch step    --study PATH [--initials XX]   # baseline if missing, then one round
sandbox autoresearch run     --study PATH [--initials XX] --max-rounds N
sandbox autoresearch status  --study PATH               # kept, reverted, spend, champion
sandbox autoresearch holdout --study PATH [--initials XX]   # one confirmation run, once
```

Offline check, no spend, no key, no initials:

```bash
.venv/bin/sandbox autoresearch run --study config/autoresearch/mock-smoke/study.yaml --max-rounds 3
```

**A paid study** (`job.mock: false` in the base) needs `--initials XX` (2-6 letters, yours). They are never
defaulted or invented; without them the command refuses before any network call. Launching the paid
`mailroom-v1` study is your decision: `plan` is safe to run first.

## One round

1. **Diagnose.** Every document's lost utility (`1 - utility`) is charged to one node and class by the rules in
   `autoresearch/diagnose.py` (written to `weakness.md`). Input, label, scoring and pipeline losses are not
   actionable: no lever is attached to them.
2. **Propose.** The first untried lever attached to the worst actionable node, unlocked by its `requires`,
   with its `requires_env` set, lowest `tier` first, then catalog order.
3. **Run.** The candidate is the champion plus the lever's patch, on the same frozen draw (the loop refuses a
   run that drew different documents). The study sets `job.api_cost_cap_usd` and `job.max_wall_seconds`, and
   adds the tags `autoresearch`, the study name and `lever:<id>`. Run id: `ar-<study>-r<NN>-<lever id>`.
4. **Score.** Per-document utility and the paired difference with a stratified percentile bootstrap
   (`paired_delta(champ, cand, by_class, n_boot=2000, seed=0, ci=0.90)`, pure Python, deterministic).
5. **Keep or revert** (`autoresearch/keep.py`), then append a row to `ledger.jsonl`.

It stops on the study budget, the key's remaining limit, an exhausted catalog, or 3 consecutive reverts
(an error counts as a revert; a skip counts as neither).

### Utility

| outcome | utility |
|:---|---:|
| correct archive | its extraction score (0 to 1) |
| unscorable archive | 0 |
| review | -0.25 |
| wrong archive | -1.0 |
| crash or `judge_error` | -1.0 |

Weights are configurable under `utility:` in the study file. A wrong archive costs four reviews, so a lever
that trades reviews for wrong archives is reverted. The production quality bar (0.90 per scorable document) is a
cliff the mean utility does not model: read `ledger.jsonl` and `sandbox run gate` beside it.

### Keep rule

All of: the CI low is above `max(0, noise_floor)`; no gated class drops more than 0.05; the wrong-archive
count is not higher; cost per document is at most 1.25x the champion's unless the mean gain is at least 0.05.
A `goal: cost` lever (the derived per-role placements) is kept when it is not worse (CI low above -0.02) and
costs at most 0.9x. Set `noise_floor` to the measured run-to-run noise once it is known.

## Files

State is under `reports/autoresearch/<study>/` (override with `state_dir`):

| file | content |
|:---|:---|
| `ledger.jsonl` | append-only, one row per round and per skipped lever: lever, run id and directory, spec sha256, metrics, delta and CI, decision and reasons, cost, `usd_per_utility_point`, dependency sources, pipeline source |
| `champion.yaml` | the current champion's run spec |
| `specs/`, `scores/` | every candidate spec, and the per-document utility and cost of every run |
| `weakness.md`, `report.md`, `holdout.md` | the views; the report ends with the production-parity section |

The loop resumes from the ledger: re-run the same command after a stop, a crash or a changed budget.

## The study file (`schema: sandbox.autoresearch/v1`)

`study`, `base_run`, `levers`, `budget` (`study_usd`, `round_api_cap_usd`, `round_wall_seconds`,
`min_key_remaining_usd`), `noise_floor`, `max_consecutive_reverts`, `utility`, `holdout_dataset`; optional
`bootstrap`, `guard_classes`, `estimate_safety` (default 1.0), `state_dir`. Paths are relative to the study file.

## Levers (`config/autoresearch/levers.yaml`)

A lever is `{id, node, classes, description, patch}`; `patch` maps dotted paths to values and `null` deletes a
key. A lever may not patch the draw, `task`, `run_id`, or the study's own caps. `validate_catalog` checks every
lever against the base before any spend (invalid patched spec, a patch that changes nothing, an unknown
`requires`, a reviewer request larger than the model's context).

| group | what it tries |
|:---|:---|
| reviewer | Decisions-API models only, from `config/decision_models.yaml` (Luna with question sets v2, v3.1.0, v3.2.0, v4.0.0; `typesafe/jev-1.14`, `jev-1.13`, `liquid/d1.2`, `perplexity/pplx-decider-v1.2`, `upstage/solar-decide`, `google/gemini-decision-1`). The champion's reviewer is the chat reviewer. |
| workers | `deepseek/deepseek-v4.1-flash-1017` for the sorter and each specialist; specialist prompts; specialist input windows |
| routing | judge every in-band extraction per class, `judge_rejudge_retry`, `judge_max_passes` |
| supervisor | tiers 1 to 3 of stronger models routed to judge, arbiter and boss (`classification_arbiter` is a node of the `arbiter` agent) |
| diagnostic | the Luna extraction gate v1.3.0 (advisory, never changes routing) |
| pipeline source | `repair-283` |

**Reviewer cutoffs are uncalibrated.** Every reviewer lever uses `reviewer_decisions_v2`'s per-class cutoffs,
which were tuned for Luna on question set v2. They are reused for the other question sets and models; the study
measures them, it does not calibrate them. **Context caps:** a reviewer's input is capped only by its question
set's `max_input_chars` (no per-run override exists), so the long question sets only fit Luna's context.

### Ordering: `tier`, `group`, `requires`

Tier 2 supervisors open when a tier-1 lever was kept, or every tier-1 lever was reverted with a positive mean
delta. Tier 3 opens when a tier-2 lever was kept and the remaining study budget is at least 3 round caps.
After a supervisor wins, the `placements:` block derives `<winner>@<roles>` cost levers (the winner on fewer
roles, the rest back on the base routing), judged on cost.

### Cost, and what it is not

Cost per document is **estimated from recorded tokens** priced per model (`config/api_prices.yaml`; the
Decisions API bills input only). It is not the provider's bill. The ledger and report split it by role
(worker, oversight, reviewer) and report `oversight_cost_share` and `usd_per_utility_point` (extra USD per
document for each +0.01 of mean utility). The split needs `usage_by_agent` in `items.jsonl`, which runs write
from this version on; older runs are totals only and the report says so.

Before each round the loop estimates the worst case: the champion's measured tokens repriced at the
candidate's dearest tier. A lever whose estimate exceeds `round_api_cap_usd` is written as
`skipped: over_round_cap` and never run.

## Pipeline source lever

`repair-283` runs a round with `MAILROOM_SRC` pointing at a checkout of llm-mailroom PR 283 (commit
`090991b34c0e4e56658a1c38f98c9d9fc414b0d4`). It is never proposed unless `AUTORESEARCH_PR283_SRC` names a
directory, and a checkout at any other commit is skipped. The variable is set for that round's child process
only; `vendor/` is never touched, and the run lock records the tree hash (`dependency_sources`). The ledger
records the variable's name and the commit, never the local path. A kept source carries into later rounds.

## Production parity

The `mailroom-v1` base is `config/runs/production/slice-0100.yaml` with only these changes: 5 documents per
class (25), no `reviewer` block (the chat reviewer; `reviewer: {backend: local}` is refused on OpenRouter),
temperature 0 for the sampling agents, and the study's caps and tags. Everything else is inherited and listed in
the base file's header. `report.md` ends with a **Production parity** section: the vendored pipeline and Dojo
commits, the baseline run lock's sources, every setting that differs from `slice-0100.yaml`, the inherited
settings, and what the kept levers changed.

## Holdout

`holdout` runs the champion once on a draw disjoint from the dev draw: the same production settings (ranked, seed
3302, same strata) with `config/production/excluded-ids.txt` plus every dev document id excluded
(`holdout-excluded-ids.txt`), so it is the next ranked block. The loop locks the draw first (`sandbox run
preflight`, no model call) and asserts there is no overlap before spending, and again after the run. A second
holdout is refused: it confirms, it does not tune. Add the dev ids to `config/production/excluded-ids.txt` before
the next production slice if they should not be re-drawn.

## Secrets

The OpenRouter key is read from the environment only to check its remaining limit. It is never printed, logged,
written to the ledger or a report, and child-process output is scrubbed before it is stored.
