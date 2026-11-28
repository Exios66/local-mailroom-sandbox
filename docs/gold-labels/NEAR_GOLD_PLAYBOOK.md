# Near-gold label playbook

This is the orientation page for an agent joining the long-running label expansion and repair
campaign. It covers how a near-gold label is verified, how it advances into production truth,
the quick commands that show where the data stands, and how to pick the next targets. The
skill [`near-gold-labels`](../../.cursor/skills/near-gold-labels/SKILL.md) is the short
checklist version of this page.

Detailed rules live elsewhere, and this page links to them instead of repeating them:

| Topic | Authority |
| --- | --- |
| How to write a label: ground rules, submission format, gate checks, fields per class | [Labeling guide](LABELING_GUIDE.md) |
| The brief handed to each label or check pass | [Pass brief template](PASS_BRIEF_TEMPLATE.md) |
| Coverage, gaps, row pulls and focus lists | [Label EDA](../label-eda.md) |
| The merged release every staged cut is built from | [Label-repaired release README](../../reports/datasets/mailroom-dataset-v9.3-label-repaired/README.md) |
| Staged production cuts, pins and truth precedence | [Staged label overlay](../staged-label-overlay.md) |
| Scoring fixes that read the labels (SHF-013 subclass corrections, SHF-019 header truth) | [Scoring hotfixes](../scoring-hotfixes.md) |

## Truth policy

- Where the Hub v9.3 ground truth is faulty or missing, reviewed labels, near-gold labels and
  interim labels are the truth. The repairs reach production now through the staged overlay;
  the next official release (v10) adopts them.
- Near-gold labels are machine labels (`use_as_truth: false` in the catalog). They never become
  human gold without a person's sign-off, and an agent never writes a human's initials.
- Every label is bound to its document's text by `content_sha256` and to the dataset revision
  (`ff4ca546…` for v9.3). A label whose text changed does not apply.

## The lifecycle at a glance

```text
 1 orient      label_eda.py summary / focus            where production truth is thin
 2 target      label_eda.py rows --tier gate ...       the exact open cells, as a queue
 3 batch       gold_labels.py batch                    document text + target fields
 4 two passes  label pass + check pass (independent)   submission JSONL, never committed raw
 5 validate    gold_labels.py validate                 quote, date and money gate
 6 disputes    gold_labels.py disputes + review file   a reviewer settles disagreements
 7 admit       gold_labels.py add [--missing-fields]   catalog records become near_gold
 8 archive     data/labels/repair-artifacts/<name>/    every pass, review and sha256
 9 rebuild     registry, judge pool, then the release  derived files, the release last
10 stage, pin  stage_label_overlay.py + pin entry      a new rc cut in mailroom-issues
11 advance     slice configs select the new cut        only after the cut lands on its main
```

Steps 1 to 9 happen in this repository, on a feature branch, and end in a PR. Step 10 writes
into a mailroom-issues checkout and needs the owner's go-ahead to push there. Step 11 is a
separate PR after the cache commit is on mailroom-issues main.

## Quick commands: get acquainted with the data

All offline, read-only and free. Run them from the repository root. In a git worktree whose
`.venv` links to another checkout, prefix `PYTHONPATH=src` and use `python -P` so the worktree's
own `src` is imported.

```bash
# where truth stands, per class and tier, and which source won each labelled cell
.venv/bin/python scripts/label_eda.py summary
.venv/bin/python scripts/label_eda.py summary --split dev

# the ranked work list: unscorable documents first, then gate gaps, suite gaps, human queue
.venv/bin/python scripts/label_eda.py focus --split dev
.venv/bin/python scripts/label_eda.py focus --slice slice-0100      # what production scores first

# completeness below 95%, by subclass and field
.venv/bin/python scripts/label_eda.py coverage --class corporate_record --by subclass,field \
    --tier gate --below 0.95

# open gate cells grouped by class, subclass and field
.venv/bin/python scripts/label_eda.py gaps --split dev --tier gate --top 20

# one document: every cell, its votes and evidence, and the raw near-gold and interim records
.venv/bin/python scripts/label_eda.py doc DOC-15b2776e13be1937

# cells a human must settle, and values the reviewed-over-Hub rule chose
.venv/bin/python scripts/label_eda.py rows --needs-human --votes --format json --out /tmp/needs-human.json
.venv/bin/python scripts/label_eda.py rows --rule reviewed_over_hub --conflict --votes --limit 20

# catalog integrity (the near_gold invariant)
.venv/bin/python scripts/gold_labels.py check
```

`--slice` needs the cached corpus (`.venv/bin/sandbox datasets pull`, no spend); every other
command reads only committed files. The [Label EDA page](../label-eda.md) lists every filter and
more recipes.

## Choosing the next targets

Label only what moves a production number. `label_eda.py` gives each cell a tier:

| Tier | What it is | Priority |
| --- | --- | --- |
| `gate` | A field of a gated class (corporate record, correspondence, insurance claim) that counts toward `min_labelled` and the headline, including corporate subclass fields | First |
| `unit` | A contract entity field, which counts only in the suite F1 (contracts gate and headline on CUAD) | After `gate` |
| `reported` | A merger field (merger is reported, never gated) | After `gate` |
| `unscored` | A field nothing scores, a templated field the gate drops, or a field the subclass registry marks `not_applicable` | Never |

Then rank within the tier:

1. **Unscorable documents** (`focus` section `1_unscorable_docs`): gated documents below
   `min_labelled` stated labels. Each label there adds a scored document.
2. **Production slices before splits.** `--slice slice-0100` first, then `slice-0250` and up.
3. **Dev before calibration.** Never label `heldout` documents for tuning; calibration labels are
   in-sample for calibration and must be reported as such.
4. **Fields with many open cells in one subclass**, so one brief covers a whole batch.

Known traps:

- A contract with an empty CUAD map is unscorable, and production slices draw with
  `require_task_gt`, which leaves it out. Entity labels on it change no production number; only
  CUAD labels, or an owner change to the draw rule, would.
- The reviewed subclass (SHF-013, `data/labels/review/subclass_corrections.jsonl`) decides which
  fields a corporate document has. `label_eda.py --subclass` and `gold_labels.py` both use it.
- `gate_labelled` in the EDA output is computed before the SHF-015 and SHF-019 drops, which can
  only lower it. A document just above the bar may still be unscorable in production.

## Running a labeling round

### Build the queue and batches

`focus --ids-out` writes the document ids with open gate work. For a precise queue, turn the
open cells into one queue line per document carrying exactly its open fields:

```bash
.venv/bin/python scripts/label_eda.py rows --split dev --tier gate \
    --presence unlabeled,disputed_unresolved --format json --out data/runtime/gold/open.json
```

A queue line is
`{"content_sha256", "doc_class", "doc_id", "fields": [...], "filename", "revision", "subclass"}`;
`gold_labels.py queue` writes the full queue for a corpus, and the open cells say which fields to
keep. Then cut batches:

```bash
.venv/bin/python scripts/gold_labels.py batch --queue data/runtime/gold/focus-queue.jsonl \
    --corpus <pinned corpus dir> --doc-class corporate_record --size 10 \
    --max-batch-chars 400000 --out data/runtime/gold/batches
```

The corpus directory holds the `ground_truth_{train,test}.parquet` and `default_{train,test}.parquet`
files of one revision. Batches carry document text: keep them under `data/runtime/` (gitignored)
or a scratch directory, never in a commit.

### Dispatch two independent passes

Each batch gets a **label** pass and a **check** pass by separate agents. Fill in the
[pass brief template](PASS_BRIEF_TEMPLATE.md) once per round and give each agent only its role,
batches, batch name, output file and private work directory.

- **Independence is enforced.** `build` and `add` refuse a check identical to its label, the same
  file in both roles, and a label and check with the same batch and content. Never let a pass
  see the other's output or share a scratch directory: a pass that may have seen its check is
  withdrawn and relabeled.
- **Batch names** follow `<campaign>-g<NN>-<label|check>`, for example `corp-gate-dev-gA-label`.
- **Long documents** (over about 40,000 characters) are read head plus tail plus a search for the
  field anchors. Group them in their own batches so the short ones finish fast.
- Each pass runs `gold_labels.py validate` on its own file and fixes every gate failure before it
  reports.

### Validate, find disputes, review

```bash
C=<pinned corpus dir>
.venv/bin/python scripts/gold_labels.py validate --corpus $C --submissions label/*.jsonl check/*.jsonl
.venv/bin/python scripts/gold_labels.py disputes --corpus $C --label label/*.jsonl \
    --check check/*.jsonl --out disputes.jsonl
```

A reviewer, preferably a different model family from the passes, reads the source around each
disputed field and writes one review line per field (`accept`, `reject`, `correct` with an
`entry`, or `accept_check`), as in the guide's
[Review decisions](LABELING_GUIDE.md#review-decisions). Fields where the two passes agree need no
review.

### Admit into the catalog

```bash
# documents the catalog does not hold yet
.venv/bin/python scripts/gold_labels.py add --corpus $C --revision ff4ca546d4346991628c2616ae014afc15e9fe04 \
    --label label/*.jsonl --check check/*.jsonl --review review.jsonl
# new fields on documents it already holds
.venv/bin/python scripts/gold_labels.py add --corpus $C --revision ff4ca546d4346991628c2616ae014afc15e9fe04 \
    --missing-fields --label label/*.jsonl --check check/*.jsonl --review review.jsonl
.venv/bin/python scripts/gold_labels.py check
.venv/bin/python scripts/gold_labels.py overlay
```

`add` never rewrites an existing record; one collision refuses the whole call. Split the passes
into a new-document set and a missing-field set when a round has both. To fix an existing label,
use a `review` line with `supersedes`, not a second `add`.

### Archive the round

Copy every pass (raw and admitted), the disputes, the review file and a short README into
`data/labels/repair-artifacts/v93-<YYYYMMDD>-<campaign>/`, with an `INDEX.json` that lists each
file's sha256 and whether `add` read it. The README states what was admitted (populated and
documented absences), how disputes were settled, and what was held out and why. The archive of
`v93-20261128-corporate-subclass-dev` is a worked example.

## Advancing labels into production truth

### Rebuild order

After `gold_labels.py overlay`, rebuild the derived files in this order: the subclass registry,
the judge reference pool, then the release. Each one hashes inputs the one before it writes, so a
file built too early pins stale bytes, and a hosted test catches it.

### Rebuild the subclass registry

The subclass registry records the sha256 of the near-gold overlay and of `LABELING_GUIDE.md`.
After any catalog admission or any edit to the guide, rebuild both registry files and commit them
with the change, or hosted `test_subclass_schemas.py` fails:

```bash
.venv/bin/sandbox schemas build                       # config/extraction/subclass_schemas.json
.venv/bin/python scripts/build_subclass_fields.py     # config/extraction/subclass_extraction_fields.json
.venv/bin/sandbox schemas build --check && .venv/bin/python scripts/build_subclass_fields.py --check
```

In a git worktree, `sandbox` imports the main checkout and writes there. Run
`env PYTHONPATH=src .venv/bin/python -P -m mailroom_sandbox.cli schemas build` from the worktree
instead.

A rebuild changes `subclass_fields_sha256`, so run locks written against the old registry refuse
to resume. Say so in the PR (Critical regressions row 9). When two open branches both touch the
catalog or the guide, the one that lands second rebuilds the registry again after merging.

### Rebuild the judge reference pool

`config/judge/reference-pool-runbook-v2.jsonl` is built from the interim and near-gold overlays.
After any catalog change, rebuild it, or hosted `test_judge_references.py` fails:

```bash
.venv/bin/python scripts/build_judge_reference_pool.py
```

### Rebuild the release, last

```bash
.venv/bin/python -I reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py \
    --out reports/datasets/mailroom-dataset-v9.3-label-repaired/generated-YYYYMMDD
```

Then replace the committed outputs with the generated set (see the release README). The summary's
`inputs_sha256` records the registry's bytes, so a release built before the registry pins a
stale hash. Offline, set `HF_HUB_OFFLINE=1` and point `HF_HUB_CACHE` at a cache that holds the
pinned ground-truth metadata. Before you commit, check:

- `summary.json` `values_moved_by_reviewed_precedence` is empty, or every listed move is
  intended and explained in the PR;
- the provenance diff changes only cells that were unlabeled or that a reviewed label now holds;
- `label_eda.py summary` on the new release shows the gain you expect.

The builder's vote rule (`reviewed_over_hub`): once a reviewed or near-gold source votes, the Hub
and the sources computed from it count for nothing; `cuad_span`, `interim_gate` and
`generated_rule` still count. A reviewed absence over a populated value, and independent evidence
that beats a reviewed label, go to `needs_human.csv` instead of being settled silently.

### Stage and pin a cut

`scripts/stage_label_overlay.py` writes the next `9.3.1-rc.N` into a mailroom-issues checkout from
the builder outputs at a named builder commit. Commit it there, then add a new entry to
`config/staged_overlays.yaml` (never edit an existing one) and verify a fresh pull:

```bash
python scripts/pull_staged_overlay.py --version 9.3.1-rc.N --root /tmp/rc-check
```

Compare the new cut with the previous one: no overlay cell removed, and no reviewed, near-gold,
owner or Hub value changed except the ones the round intended. The
[staged overlay page](../staged-label-overlay.md#cutting-a-new-version) lists everything the
stager validates.

### Advance the production slices

Only after the cut's commit is on mailroom-issues main and still reachable (a merge commit keeps
it; a squash does not). Then one PR moves the seven production slice configs, their test and the
runbook together. Existing run locks keep their cut, and a resume over a changed cut is refused.

## Verification checklist (before a PR)

- [ ] Every pass validates with no rejections; the two passes are independent.
- [ ] Every dispute has a review line; `gold_labels.py check` passes.
- [ ] Nothing in `heldout` was labeled; calibration labels are marked in-sample.
- [ ] The round is archived with sha256 values; no document text is committed outside the
      release's own outputs.
- [ ] The subclass registry is rebuilt (`sandbox schemas build --check` and
      `build_subclass_fields.py --check` pass) after any catalog or `LABELING_GUIDE.md` change.
- [ ] The judge reference pool is rebuilt (`build_judge_reference_pool.py --check` passes).
- [ ] The release is rebuilt last and reproduces the committed outputs, and no protected value
      moved without a reason in the PR.
- [ ] Focused tests pass with `-n 0 --no-cov`: `tests/test_gold_labels*.py`,
      `tests/test_label_eda.py`, the release-builder and staged-overlay tests your change
      touches.
- [ ] The PR's Critical regressions section is filled (rows 1, 3, 15, 26, 27 and CP-04 to CP-07
      usually apply; see [critical regressions](../critical-regressions.md)).

## Never

- Edit `vendor/` to change scoring or truth handling. A scoring fix is an SHF hotfix in
  `src/mailroom_sandbox/scoring_hotfixes.py` with its row in the hotfix guide.
- Launch paid or live work (`sandbox run start`, `--real`, `--live`, Modal deploys) to measure a
  label round. Rescores of finished runs are offline.
- Promote near-gold to human gold, or write a person's initials into a sign-off queue.
- Commit raw document text, batches or scratch scripts.
