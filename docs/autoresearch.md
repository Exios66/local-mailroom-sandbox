# Autoresearch: a greedy, config-only lever search

`sandbox autoresearch` improves a run spec the way a careful operator would, one change at a time, and
keeps an auditable record. It changes **no pipeline code**: every candidate is the current champion spec plus
ONE lever (a dotted-path patch), validated as a `RunSpec`, then run through the existing locked-run
lifecycle (`sandbox run preflight`, `sandbox run start`, the production gate).

## Commands

```bash
sandbox autoresearch plan    --study PATH               # weakness table + the next lever; runs nothing
sandbox autoresearch step    --study PATH [--initials XX]   # baseline and replicate if missing, then one round
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

## Baseline, replicate, noise floor

The first call runs the champion (`base.yaml`) as round 0, then **the identical spec again** as round `replicate`
(run id `ar-<study>-replicate`, tag `lever:replicate`, same draw). The paired difference between the two baseline runs is the
measured run-to-run noise (sampling runs at production temperatures, so it is real). The study's **effective noise floor** is

    max(noise_floor in the study file, |mean paired delta|, CI half-width)

of those two runs. It is recorded in the replicate's ledger row (`noise`), shown in `status`, `plan` and `report.md`, and it
is the threshold of the keep rule's first test (CI low above the floor). **No lever runs or is kept before the replicate
exists**; a failed replicate stops the study (the next call re-runs it). The replicate also gives a measured cost per round
(`noise.measured_round_cost_usd`).

## One round

1. **Diagnose.** Every document's lost utility (`1 - utility`) is charged to one node and class by the rules in
   `autoresearch/diagnose.py` (written to `weakness.md`). Input, label, scoring and pipeline losses are not
   actionable: no lever is attached to them.
2. **Propose.** The first untried lever attached to the worst actionable node, unlocked by its `requires`,
   with its `requires_env` set, lowest `tier` first, then catalog order.
3. **Run.** The candidate is the champion plus the lever's patch, on the same frozen draw (the loop refuses a
   run that drew different documents). The study sets `job.api_cost_cap_usd` (the round's own cap, see below) and
   `job.max_wall_seconds`, and adds the tags `autoresearch`, the study name and `lever:<id>`. Run id: `ar-<study>-r<NN>-<lever id>`.
4. **Score.** Per-document utility and the paired difference with a stratified percentile bootstrap
   (`paired_delta(champ, cand, by_class, n_boot=2000, seed=0, ci=0.90)`, pure Python, deterministic).
5. **Keep or revert** (`autoresearch/keep.py`), then append a row to `ledger.jsonl`.

It stops on the study budget, the key's remaining limit, an exhausted catalog, or 3 consecutive reverts
(a lever's error counts as a revert; a skip, an `aborted_cap` round and a warning count as neither, and the
baseline, replicate and holdout rows, errors included, are not lever rounds: they are ignored, and the count never
reaches back past the baseline or replicate row). A lever whose round **errored** is proposed once more (at most 2 attempts
in all); a second error settles it without a verdict. A key with no spend limit
(`limit_remaining` null) cannot bound anything: the loop writes a `warning` row to the ledger (shown in `status` and
`report.md`) and continues under the study budget alone.

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

All of: the CI low is above `max(0, effective noise floor)` (the replicate's, see above); no gated class drops more than 0.05; the wrong-archive
count is not higher; cost per document is at most 1.25x the champion's unless the mean gain is at least 0.05.
A `goal: cost` lever (the derived per-role placements) is kept when it is not worse (CI low above -0.02) and
costs at most 0.9x. The configured `noise_floor` is a minimum: the measured one raises it, never lowers it.

## Files

State is under `reports/autoresearch/<study>/` (override with `state_dir`):

| file | content |
|:---|:---|
| `ledger.jsonl` | append-only, one row per round and per skipped lever: lever, run id and directory, spec sha256, metrics, delta and CI, decision (`baseline`, `replicate`, `keep`, `revert`, `error`, `aborted_cap`, `skipped`, `holdout`, `warning`) and reasons, cost, round cap, estimate (both figures), `patch_before`, `usd_per_utility_point`, dependency sources, pipeline source |
| `champion.yaml` | a convenience copy of the current champion's run spec, written before its ledger row and never read back |
| `specs/`, `scores/` | every candidate spec (`<run_id>.yaml`), and the per-document utility and cost of every run. The champion is loaded from `specs/<champion run_id>.yaml` and checked against the ledger row's `spec_sha256`; a missing or edited spec is a clear error |
| `weakness.md`, `report.md`, `holdout.md` | the views; the report ends with the production-parity section |

The loop resumes from the ledger: re-run the same command after a stop, a crash or a changed budget. The ledger row is
the commit point: `champion.yaml` is written just before it, and the champion's spec is read from `specs/`, so a crash
between the two files leaves a consistent state. `status` says so plainly when nothing has run yet (`message`).

## The study file (`schema: sandbox.autoresearch/v1`)

`study`, `base_run`, `levers`, `budget` (`study_usd`, `round_api_cap_usd`, `round_wall_seconds`,
`min_key_remaining_usd`, `max_round_cap_usd` default 4.0), `noise_floor`, `max_consecutive_reverts`, `utility`, `holdout_dataset`; optional
`bootstrap`, `guard_classes`, `estimate_safety` (default 1.0), `state_dir`. Paths are relative to the study file.

## Levers (`config/autoresearch/levers.yaml`)

A lever is `{id, node, classes, description, patch}` (optional `round_cap_usd`, `round_cap_auto`, `estimate_safety`, below);
`patch` maps dotted paths to values and `null` deletes a key. A lever may not patch the draw, `task`, `run_id`, or the study's own caps. `validate_catalog` checks every
lever against the base before any spend (invalid patched spec, a patch that changes nothing, an unknown
`requires`, a reviewer request larger than the model's context).

| group | what it tries |
|:---|:---|
| reviewer | Decisions-API models only, from `config/decision_models.yaml` (Luna with question sets v2, v3.1.0, v3.2.0, v4.0.0; `typesafe/jev-1.14`, `jev-1.13`, `liquid/d1.2`, `perplexity/pplx-decider-v1.2`, `upstage/solar-decide`, `google/gemini-decision-1`). The champion's reviewer is the chat reviewer. |
| workers | `deepseek/deepseek-v4.1-flash-1017` for the sorter and each specialist; specialist prompts; one narrower merger window |
| routing | judge every in-band extraction per class, `judge_rejudge_retry`, `judge_max_passes` (each carries `estimate_safety: 2.0`) |
| supervisor | tiers 1 to 3 of stronger models routed to judge, arbiter and boss (`classification_arbiter` is a node of the `arbiter` agent); each carries `estimate_safety: 1.5` for a reasoning or verbose model |
| diagnostic | the Luna extraction gate v1.3.0 (advisory, never changes routing) |
| pipeline source | `repair-283` |

**Reviewer cutoffs are uncalibrated.** Every reviewer lever uses `reviewer_decisions_v2`'s per-class cutoffs,
which were tuned for Luna on question set v2. They are reused for the other question sets and models; the study
measures them, it does not calibrate them. **Context caps:** a reviewer's input is capped only by its question
set's `max_input_chars` (no per-run override exists), so the long question sets only fit Luna's context.

**Input windows.** After `context_fit` the baseline's specialists on the 1M-context `qwen/qwen3.7-flash` read the whole
document (up to ~2.37M chars) in one window, so no window lever can widen it. The only one left is
`merger-agreement-window-400k`, a *narrower* window that tests whether chunking long mergers helps; E1 found chunking
hurt contracts, so the whole-document baseline is the control.

**Reviewer guard.** A paid study (`job.mock: false`) refuses, in `validate_catalog` and again when a candidate is stamped,
any patched spec whose `reviewer` block is not backend `decisions`, or sets `allow_chat_model: true`, or names a model that
is not a Decisions-API model (`decision_backends.is_decisions_model`). The baseline has no `reviewer` block, so the chat
`sorter_reviewer` runs; that stays allowed. The `jev`, `local`, `api` and `mock` backends are refused.

### Ordering: `tier`, `group`, `requires`

Tier 2 supervisors open when a tier-1 lever was kept, or when **every** tier-1 lever is *decided* and **at least one** was
reverted with a positive mean delta. Decided means: a revert with a positive mean delta, `aborted_cap` (no verdict), `skipped`
(over the round cap, a no-op), or an `error` on its second attempt (decided without a verdict). A revert with a negative mean
keeps the tier closed; so does a lever not run yet or one that errored only once (it is retried). `aborted_cap` and skips
alone never open a dearer tier: the ladder needs one positive direction to spend more. Tier 3 opens when a tier-2 lever was kept and the remaining study budget is at
least 3 round caps. After a supervisor wins, the `placements:` block derives `<winner>@<roles>` cost levers (the winner on
fewer roles), judged on cost. A derived patch is absolute and comes from the winner's own ledger row, never from the
champion's current state: the roles it keeps are set to the winner's own routes, the roles it restores to what the champion
had just before the winner was kept (`patch_before` in the row; the base spec's value for an older row). So it stays right
after a kept placement, and a winner a later kept supervisor has replaced derives nothing (that supervisor derives its own,
restoring to the tier before it).

### Cost, and what it is not

Cost per document is **estimated from recorded tokens** priced per model (`config/api_prices.yaml`; the
Decisions API bills input only). It is not the provider's bill. The ledger and report split it by role
(worker, oversight, reviewer) and report `oversight_cost_share` and `usd_per_utility_point` (extra USD per
document for each +0.01 of mean utility). The split needs `usage_by_agent` in `items.jsonl`, which runs write
from this version on; older runs are totals only and the report says so. A model a run recorded but `api_prices.yaml`
does not price is listed in `unpriced` (the run's metrics) and its tokens are not charged: it is never repriced at the
engine model's rate.

### Round caps

Every round runs with `job.api_cost_cap_usd`, and the run's own `ApiBudget` (`job/api_budget.py`) enforces it by pricing
**every token of the run at the dearest API model in it**. A supervisor round is therefore dear: the workers' tokens are
charged at the supervisor's price. Before each round the loop estimates two figures from the champion's measured tokens
(ledger `estimate`): `usd`, each agent's tokens at its own model, and `runtime_bound_usd`, the `ApiBudget`'s view
(`price_bound(spec_api_models(spec))` over the champion's total prompt and completion tokens; a decisions reviewer or gate adds
its input tokens). **The cap decision uses the runtime bound.** `estimate_safety` (study) times a lever's own
`estimate_safety` scales both figures; the levers that add calls carry 2.0, the supervisors 1.5. The model set the bound
prices is the one the run's lock will carry (`api_budget.api_models`): engine, agent models and routes, the reviewer model
(backends `decisions`, `local`, `api`, `jev`) and the extraction gate model.

The lever's cap is the study's `round_api_cap_usd`, unless it carries `round_cap_usd` (an explicit override) or
`round_cap_auto: true` (every supervisor lever, and the placements derived from one): the runtime-bound estimate x 1.2,
rounded up to $0.25, within `[round_api_cap_usd, budget.max_round_cap_usd]`; without a champion token measurement the tier
default (1.5 / 3 / 4 USD for tier 1 / 2 / 3). The cap is stamped on the run and recorded as `round_cap_usd`.

- `skipped: over_round_cap` when the runtime bound exceeds the lever's cap (a bound above `max_round_cap_usd` cannot run);
- `skipped: over_study_budget` when the remaining study budget cannot reserve a cap above the standard one (a cheaper lever
  still runs; when not even a standard round fits, the study stops with `study_budget`);
- `aborted_cap` when the run's own cap aborted it (checkpoint `last_error.type == api_cost_cap`): no verdict, not a revert,
  charged its **full cap** in `cost_usd`, never retried, and it counts as decided for the tier ladder.

A failed round without scored documents is charged its full round cap only when its run directory shows that model calls
started (an `items.jsonl` row, or a checkpoint of `running`, `paused`, `failed` or `done`): what it spent is then unknown. A
preflight or config failure (no run directory, or a `prepared` checkpoint) never reached a model and costs 0; a failed round with scored
documents is charged its recorded cost.

## Pipeline source lever

`repair-283` runs a round with `MAILROOM_SRC` pointing at a checkout of llm-mailroom PR 283 (commit
`090991b34c0e4e56658a1c38f98c9d9fc414b0d4`). It is never proposed unless `AUTORESEARCH_PR283_SRC` names a
directory, and a checkout at any other commit is skipped. The variable is set for that round's child process
only; `vendor/` is never touched, and the run lock records the tree hash (`dependency_sources`). The ledger
records the variable's name and the commit, never the local path. A kept source carries into later rounds.

## Production parity

The `mailroom-v1` base is `config/runs/production/slice-0100.yaml` with only these changes: 5 documents per
class (25), no `reviewer` block (the chat reviewer; `reviewer: {backend: local}` is refused on OpenRouter), and the
study's caps and tags. **No `temperature` override anywhere:** every agent samples at its production temperature, so the
baseline is comparable with a production slice; production comparability wins over determinism, and the replicate baseline
measures the resulting noise (above). Everything else is inherited and listed in the base file's header. `report.md` ends
with a **Production parity** section: the vendored pipeline and Dojo commits, the baseline run lock's sources, every setting
that differs from `slice-0100.yaml`, the inherited settings, and what the kept levers changed.

**Pipeline source.** The baseline uses the **vendored pipeline snapshot** (`vendor/llm-mailroom`, the v0.30.0 branch tip
`f83e398`, the same commit production slice-0100 runs). The unmerged llm-mailroom #283 repairs are **not** in the baseline:
they are the opt-in `repair-283` lever (above), proposed only with `AUTORESEARCH_PR283_SRC` set.

## Holdout

`holdout` runs the champion once on a draw disjoint from the dev draw: the same production settings (ranked, seed
3302, same strata) with `config/production/excluded-ids.txt` plus every dev document id excluded
(`holdout-excluded-ids.txt`), so it is the next ranked block. The loop locks the draw first (`sandbox run
preflight`, no model call) and asserts there is no overlap before spending, and again after the run. A second
holdout is refused: it confirms, it does not tune. The holdout row records the champion it confirmed (`champion_run_id`); if a
later keep changes the champion, `status` (`holdout_stale: true`) and `report.md` flag the holdout as **stale**: it describes the earlier champion. Add the dev ids to `config/production/excluded-ids.txt` before
the next production slice if they should not be re-drawn.

## Secrets

The OpenRouter key is read from the environment only to check its remaining limit. It is never printed, logged,
written to the ledger or a report, and child-process output is scrubbed before it is stored.
