# rb1 prompt promotion rule

Campaign rb1 tests four specialist prompt A/Bs (plan finding 16) under runbook row R41
("Specialist iteration"). This page states when a candidate prompt replaces its lineage
frontrunner, and how that change is recorded. The plan is
`docs/superpowers/plans/2026-11-18-evaluation-runbook-plan.md`.

| Lineage | Frontrunner (arm A) | Candidate (arm B) |
| --- | --- | --- |
| corporate | `corporate_records_specialist_condensed_v1` | `corporate_records_specialist_condensed_v2` |
| correspondence | `correspondence_specialist_condensed_v3` | `correspondence_specialist_condensed_v4` |
| contracts | `contracts_specialist_v33_simplified` | `contracts_specialist_condensed_v1` |
| insurance | `insurance_claims_specialist_condensed_v3` | `insurance_claims_specialist_condensed_v5` |

Each arm runs at two nested looks, dev-look1 (300 docs) and dev-look2 (600 docs). Each run
covers every document of the lineage's class in that look, with the interim and near-gold
overlays and `job.schema_guide: true`. The run ids are
`rb1-r41-<lineage>-<arm>-look<N>`, for example `rb1-r41-insurance-condensed-v5-look2`.
Within a pair the two configs differ only in the prompt (`tests/test_rb1_batch1_configs.py`
checks this). No held-out or calibration document can be selected.

## The rule

A candidate is **promoted** only when all of these hold at look 2:

1. **The pair is clean.** Both runs are `done` and neither is a mock. They locked the same
   dataset (`dataset.sha256` and the same ids). Their locked specs are equal except for the
   prompt, the run identity and the trace tags.
2. **The gain is significant after Holm.** The score is per-document field F1
   (`score.extraction_f1`). A failed or unscored document counts as 0. The test is the paired
   sign-flip permutation (`experiment_stats.paired_permutation`, 10,000 permutations, seed
   20261118). The p-values of the four pairs at the same look are Holm-adjusted together
   (`experiment_stats.holm`). A pair with no result enters the family at p = 1. The adjusted
   p must be below 0.05, and the mean gain must be positive.
3. **The keep rule says keep.** `experiment_stats.keep_at_look` is applied to the paired z of
   the same differences, against a target gain of 0.03 (`--target`; H2 is +3 to +4 points).
   Look 1 only screens. Look 2 keeps at z >= 2.45.
4. **Hallucination does not rise.** The hallucination rate is pooled over every document's
   field audits: hallucinated items divided by predicted items
   (`score.fields.<field>.entity_list_audit`). The candidate's rate must not be above the
   frontrunner's.

The verdicts are:

| Verdict | Meaning |
| --- | --- |
| `PROMOTE` | All four conditions hold. |
| `SCREEN: run look 2` | Look 1 result. Look 1 never promotes. |
| `HOLD: keep rule says continue` | Look 2 says continue. A full-dev look 3 is an owner decision. |
| `KEEP FRONTRUNNER` | The candidate failed the rule. |
| `NO VERDICT` | The pair is not clean or a run is missing. The script lists the reasons. |

## Running it

```bash
python scripts/rb1_promote.py --look 1        # after the look-1 runs: screen only
python scripts/rb1_promote.py --look 2        # after the look-2 runs: verdicts
python scripts/rb1_promote.py --look 2 --apply --initials XX   # a person moves the promoted ones
```

The script prints a table and a JSON verdict. It writes the verdict to `--out` when given.
Otherwise it writes to the rb1 campaign tree,
`experiment_paths("rb1-r41").file("promotion-look<N>", "json", subdir="analysis")`, once
`mailroom_sandbox.report_campaigns` is on main. Without that module it only prints.
`--allow-mock` scores mock runs to check the plumbing. It never writes and cannot be combined
with `--apply`.

The script never changes a default by itself. `--apply` requires look 2 and the initials of
the person applying (2 to 6 capital letters). It edits only the `PROMOTE` rows.

## How LINEAGE records a promotion

`--apply` edits `config/prompts/specialist_condensed_lineage.yaml` in place and keeps its
comments. For each promoted agent:

- `frontrunner:` names the candidate, with a comment giving the date, the initials and the old
  frontrunner. `frontrunner_outside_lineage` is dropped, because the new frontrunner is a
  lineage version.
- The candidate's `status: candidate` becomes `status: adopted`. Its comment carries the gain,
  the Holm p, z and both hallucination rates.
- A `promotion:` line is added under the candidate:
  `{campaign: rb1, experiment: rb1-r41, look: 2, frontrunner_run, candidate_run, decided, initials}`.
- If the old frontrunner is listed as a lineage version with `status: adopted`, it becomes
  `status: superseded` with a comment naming the candidate.

The script then lists the production slice configs (`config/runs/production/*.yaml`) that still
pin the old frontrunner. `tests/test_production_slices.py` ties those configs to the lineage
frontrunner, so moving them is a separate reviewed PR. Commit the lineage edit together with
the verdict JSON, and open that PR.
