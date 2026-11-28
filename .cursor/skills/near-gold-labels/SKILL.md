---
name: near-gold-labels
description: >-
  Expand, repair, verify and advance near-gold labels in local-mailroom-sandbox: inspect label
  coverage, find the label gaps that move production scores, run two-pass labeling rounds,
  settle disputes, admit labels to the gold catalog, rebuild the label-repaired release and stage
  a production overlay cut. Use for any label expansion or repair task, label coverage or EDA
  question, "where should we label next", gold_labels.py or label_eda.py work, or a new
  near-gold labeling campaign.
---

# Near-gold labels

The long-term goal is a fully labeled, trustworthy truth set: where the Hub v9.3 labels are
faulty or missing, reviewed, near-gold and interim labels are the truth, and they reach production
scoring through the staged overlay until v10 adopts them. Full walkthrough:
[`docs/gold-labels/NEAR_GOLD_PLAYBOOK.md`](../../../docs/gold-labels/NEAR_GOLD_PLAYBOOK.md).

## 1. Get caught up (5 minutes, offline, free)

```bash
.venv/bin/python scripts/label_eda.py summary --split dev          # coverage by class and tier
.venv/bin/python scripts/label_eda.py focus --split dev            # ranked work list
.venv/bin/python scripts/label_eda.py focus --slice slice-0100     # production's first draw (needs the cached corpus)
.venv/bin/python scripts/label_eda.py gaps --split dev --tier gate --top 20
.venv/bin/python scripts/gold_labels.py check                      # catalog integrity
ls data/labels/repair-artifacts/                                    # earlier rounds, newest last
```

Read the newest `data/labels/repair-artifacts/*/README.md` and the open PRs that touch
`data/labels/` before starting, so you do not relabel work in flight.

In a git worktree whose `.venv` links to another checkout, run Python as
`PYTHONPATH=src .venv/bin/python -P …` so the worktree's own code is imported.

## 2. Pick targets that move a production number

- `gate` tier first (corporate, correspondence and insurance fields the gate counts, including
  corporate subclass fields), then `unit` (contract entity fields) and `reported` (merger). Never
  `unscored`.
- Within `gate`: the unscorable documents in `focus`'s `1_unscorable_docs` first, then
  `--slice slice-0100` before larger slices, then dev before calibration. Never label `heldout`
  for tuning.
- A contract with an empty CUAD map changes no production number (slices draw with
  `require_task_gt`), so its entity labels wait.

Pull the exact open cells:

```bash
.venv/bin/python scripts/label_eda.py rows --split dev --tier gate \
    --presence unlabeled,disputed_unresolved --format json --out data/runtime/gold/open.json
```

## 3. Run a round

1. **Branch.** One feature branch per round (`claude/<round-name>`), never on another round's
   branch.
2. **Queue and batches.** One queue line per document with exactly its open fields, then
   `gold_labels.py batch … --out data/runtime/gold/batches`. Batches hold document text: never
   commit them. Put long documents (over about 40,000 characters) in their own batches.
3. **Two independent passes per batch.** Fill in
   [`PASS_BRIEF_TEMPLATE.md`](../../../docs/gold-labels/PASS_BRIEF_TEMPLATE.md) once, then
   dispatch a label agent and a check agent per batch group, each with its own output file and
   private work directory. Run them in parallel and in the background. Neither may read the
   other's output.
4. **Validate.** `gold_labels.py validate --corpus $C --submissions label/*.jsonl check/*.jsonl`:
   no rejections.
5. **Disputes and review.** `gold_labels.py disputes … --out disputes.jsonl`. A reviewer reads the
   source around each disputed field and writes `accept`, `reject`, `correct` (with `entry`) or
   `accept_check`. Use a different model family from the passes when you can.
6. **Admit.** `gold_labels.py add` for new documents; `add --missing-fields` for new fields on
   documents the catalog holds. Then `gold_labels.py check` and `gold_labels.py overlay`.
7. **Archive.** `data/labels/repair-artifacts/v93-<YYYYMMDD>-<round>/` with a README, `INDEX.json`
   (sha256 of every file, and whether `add` read it) and every pass, dispute and review file.

## 4. Advance into production truth

Rebuild the derived files in this order. Each one hashes the one before it, so a file built
early pins stale bytes (hosted tests catch each case).

1. **Rebuild the subclass registry** after any catalog admission or `LABELING_GUIDE.md` edit,
   once `gold_labels.py overlay` has run:
   `.venv/bin/sandbox schemas build` and `.venv/bin/python scripts/build_subclass_fields.py`.
   Both record the overlay and guide sha256; a stale registry fails hosted
   `test_subclass_schemas.py`. In a git worktree, `sandbox` imports the main checkout: run
   `env PYTHONPATH=src .venv/bin/python -P -m mailroom_sandbox.cli schemas build` instead.
2. **Rebuild the judge reference pool** after any catalog change:
   `.venv/bin/python scripts/build_judge_reference_pool.py`. It is built from the interim and
   near-gold overlays; a stale pool fails hosted `test_judge_references.py`.
3. **Rebuild the release last:**
   `.venv/bin/python -I reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py --out <new dir>`.
   Replace the committed outputs. `summary.json` `values_moved_by_reviewed_precedence` must be
   empty or explained. Its `inputs_sha256` records the registry's bytes, so a release built before
   the registry pins stale bytes (`tests/test_label_repaired_builder.py` checks them). Offline, set
   `HF_HUB_OFFLINE=1` and `HF_HUB_CACHE` to a cache holding the pinned ground-truth metadata.
4. **Re-measure:** `label_eda.py summary` and `focus` on the new release; quote the gain in the
   PR.
5. **PR** with the template, Critical regressions filled, and focused tests
   (`-n 0 --no-cov` on `tests/test_gold_labels*.py`, `tests/test_label_eda.py` and the
   release-builder and staging tests touched). Hosted CircleCI must be green.
6. **Stage a cut** only when the owner asks: `scripts/stage_label_overlay.py` into a
   mailroom-issues checkout, a new pin entry in `config/staged_overlays.yaml` (never edit an
   existing one), then `scripts/pull_staged_overlay.py --version 9.3.1-rc.N --root <scratch>` to
   verify.
7. **Advance slices** in a separate PR, only after the cut's commit is on mailroom-issues main
   by a merge commit.

## Rules that bite

- Near-gold is machine truth (`use_as_truth: false`). Never promote it to human gold or write a
  person's initials into a sign-off queue.
- Never edit `vendor/`, `data/cache/` or `data/runtime/` by hand. Scoring changes are SHF hotfixes
  in `src/mailroom_sandbox/scoring_hotfixes.py`, with a row in `docs/scoring-hotfixes.md`.
- Never launch paid or live work to measure a round. Rescores of finished runs are offline.
- `add` never rewrites a record. Fix an existing label with a `review` line that names what it
  `supersedes`.
- No `claude.ai` links, session trailers or "Generated with Claude Code" footers in commits or PR
  text.
- Report what each round admitted, held out and left unresolved, with the commands that showed it.
