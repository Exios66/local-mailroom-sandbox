# Label EDA: coverage, gaps and row pulls

`scripts/label_eda.py` inspects the merged label truth: what is labelled, what is not, which
source each value rests on, and where the next label work moves production numbers. It is
offline and read-only. It reads committed files and, for `--slice` and the contract count in
`focus`, the cached corpus and the production slices' pulled staged cut.
Library: `src/mailroom_sandbox/label_eda.py`. For the whole label round (targets, passes,
review, admission and advancing into production), see the
[near-gold label playbook](gold-labels/NEAR_GOLD_PLAYBOOK.md). For charts, notebook
`notebooks/05_label_coverage_eda.ipynb` covers the same ground.

```bash
.venv/bin/python scripts/label_eda.py <command> [filters] [output options]
.venv/bin/python scripts/label_eda.py <command> --help      # every flag
```

The recipes below shorten the first part to `scripts/label_eda.py`.

## What it reads

| Input | Path | Holds |
| --- | --- | --- |
| Label-repaired release | `reports/datasets/mailroom-dataset-v9.3-label-repaired/` | One provenance row per (document, field) target cell: value, presence, winning source, every source's vote and evidence. It already merges the Hub, the interim overlay, the near-gold catalog, reviewed subclass corrections and the owner's decisions. Staged cuts are built from it. |
| Near-gold catalog | `data/labels/gold/*.jsonl` | The raw two-pass and reviewed labels (`catalog`, `doc`). |
| Interim overlay | `data/labels/interim/*.jsonl` | The raw interim labels (`interim`, `doc`). |
| Splits | `config/splits/runbook-v2/assignments.jsonl` | `dev`, `calibration`, `heldout`, `pool`. |
| Subclass registry | `config/extraction/subclass_schemas.json` | Which fields a subclass does not apply. |
| Gate bars | `config/production/bars.yaml` | Gated classes and `min_labelled`. |
| Cached corpus (`--slice`, `focus`) | `data/cache/Lucius-Morningstar__mailroom-dataset__ff4ca546d434/` | The production slice draw, made with `prepare_subset`, the function the runs use, and the contract rows `focus` counts. |
| Staged cut (`--slice`, `focus`) | `data/cache/mailroom_cache/` (`$SANDBOX_LABEL_CACHE`) | The slice's `staged_overlay`, which the draw applies before it counts a CUAD-empty contract's field labels (`scripts/pull_staged_overlay.py --version <cut>`). |

The release reflects the labels as of its last rebuild. After you admit new labels, rebuild it
(`build_label_repaired.py --out <new dir>`, see its README) before trusting the counts here.

## Tiers: what a label is worth

Every cell gets a tier from what production scoring does with it:

| Tier | Meaning | Worth labelling? |
| --- | --- | --- |
| `gate` | The field of a gated class (corporate record, correspondence, insurance claim) that the gate counts toward `min_labelled` and the headline scores. This includes corporate subclass fields such as `trustee` and `registered_agent`. | First. |
| `unit` | A contract entity field. Contracts are gated and headlined on CUAD, so the entity label counts only in the suite F1. It stands in only where the CUAD universe is empty (SHF-016). | After `gate`. |
| `reported` | A merger field. Merger is reported, never gated. | After `gate`. |
| `unscored` | Not scored at all: a field the Dojo does not score, a templated field the gate drops (`keywords`, `subject_matter` on corporate and correspondence), or a field the registry marks `not_applicable` for the subclass (for example corporate `filing_number` on an indenture or bylaws). | No. |

Presence is one of `populated`, `documented_absence` (labelled, the value is "not in the
document"), `unlabeled` and `disputed_unresolved`. Labelled means the first two. The gate counts
only `populated` cells toward `min_labelled`.

## Filters (every command)

| Flag | Example | Selects |
| --- | --- | --- |
| `--class` | `--class corporate_record` | one document class |
| `--subclass` | `--subclass indenture` | the reviewed subclass (SHF-013 corrections applied) |
| `--split` | `--split dev` | a runbook-v2 split |
| `--slice` | `--slice slice-0100` | the documents a production slice draws |
| `--doc`, `--ids-file` | `--doc DOC-15b2776e13be1937,DOC-…` | specific documents |
| `--field` | `--field trustee,guarantors` | specific fields |
| `--tier` | `--tier gate` | `gate`, `unit`, `reported`, `unscored` |
| `--presence` | `--presence unlabeled,disputed_unresolved` | cell presence |
| `--source` | `--source near_gold_two_pass` | cells a source backs (`hub_v9.3`, `interim_reviewed`, …) |
| `--rule` | `--rule reviewed_over_hub` | the vote rule that chose the value |
| `--needs-human`, `--conflict` | | cells queued for a human; cells whose sources disagreed |

Output options are `--format table|json|csv`, `--limit N` (the rows a table prints; 0 for all)
and `--out FILE` (the full result, never truncated). `csv` needs a row list, so `summary`,
`focus` and `doc` take `table` or `json`.

`catalog` and `interim` read raw label records, not release cells. They take `--class`,
`--subclass`, `--split`, `--slice`, `--doc`, `--ids-file` and `--field` (`--subclass` and
`--split` resolve through the release), and refuse the cell-only filters. An id filter that
matches nothing returns nothing.

## Recipes

### Current coverage

```bash
# per class, per tier, and which source won the labelled cells
scripts/label_eda.py summary
scripts/label_eda.py summary --split dev

# completeness by subclass or field; only the groups below 95%
scripts/label_eda.py coverage --class corporate_record --by subclass,field --tier gate --below 0.95
scripts/label_eda.py coverage --by doc_class,split
scripts/label_eda.py coverage --class correspondence --by chosen_source   # how much truth is Hub-only
```

### Where to focus next

```bash
# ranked work list: unscorable documents, gate gaps, suite and reported gaps, human queue
scripts/label_eda.py focus --split dev
scripts/label_eda.py focus --slice slice-0100          # the documents production scores first
scripts/label_eda.py focus --split dev --class corporate_record --ids-out /tmp/dev-corp-ids.txt
```

`focus` leaves `unscored` cells out on purpose and reports how many it skipped. Its
`1_unscorable_docs` lists gated documents with fewer than `min_labelled` stated gate labels.
The gate drops each of them, so a label there adds a scored document. A contract counts its CUAD
clause labels, which the release does not carry. A contract with no CUAD labels counts its field
labels instead (SHF-016). Production slices draw such a contract when it has at least
`dataset.task_gt_min_field_labels` of them after the label overlay. `focus` counts both kinds the
same way: the production `gate.labelled_count` on the cached corpus row, after the production
slices' label overlay. It says so under `unit_class_count`, or that it skipped them without the
cache or the pulled staged cut.

`--ids-out` writes the document ids with open gate work. To label exactly the open cells, narrow a
full `gold_labels.py queue` file with `queue`. It keeps one line per document that has an open
(unlabeled or disputed) cell under the filters, with its `fields` set to exactly those cells, and
names any document the full queue does not list. Then cut batches from it (see the
[labeling guide](gold-labels/LABELING_GUIDE.md)):

```bash
.venv/bin/python scripts/gold_labels.py queue --corpus <pinned corpus dir> --revision <revision> \
    --out data/runtime/gold/queue.jsonl
.venv/bin/python scripts/label_eda.py queue --queue data/runtime/gold/queue.jsonl --split dev \
    --class corporate_record --tier gate --out data/runtime/gold/focus-queue.jsonl
.venv/bin/python scripts/gold_labels.py batch --queue data/runtime/gold/focus-queue.jsonl \
    --corpus <pinned corpus dir> --doc-class corporate_record --size 25 --out data/runtime/gold/batches
```

```bash
# open cells grouped by class, subclass and field, with example documents
scripts/label_eda.py gaps --split dev --tier gate --top 20
```

### Pull rows that need inspection

```bash
# every open gate cell of dev charter amendments
scripts/label_eda.py rows --class corporate_record --subclass charter_amendment --split dev \
    --tier gate --presence unlabeled

# cells a human must settle, with every source's vote
scripts/label_eda.py rows --needs-human --votes --format json --out /tmp/needs-human.json

# values where sources disagreed and the reviewed label overrode the Hub
scripts/label_eda.py rows --rule reviewed_over_hub --conflict --votes --limit 20

# truth resting on the Hub alone, for a gated class
scripts/label_eda.py rows --class correspondence --source hub_v9.3 --presence populated --format csv \
    --out /tmp/corr-hub-only.csv

# one field's labels with their evidence quotes
scripts/label_eda.py rows --field trustee --presence populated --evidence --limit 10
```

### One document

```bash
# every cell (tiered, with votes and evidence), its gate count, and the raw near-gold and interim records
scripts/label_eda.py doc DOC-15b2776e13be1937
scripts/label_eda.py doc DOC-15b2776e13be1937 --format json --out /tmp/doc.json
```

### Raw label stores

```bash
scripts/label_eda.py catalog --class corporate_record --field trustee --format csv --out /tmp/trustee.csv
scripts/label_eda.py catalog --doc DOC-15b2776e13be1937
scripts/label_eda.py interim --class correspondence --field sender --limit 10
```

## Reading the results

- The release holds the Hub's own subclass under `subclass_hub_v9_3` and the reviewed one under
  `subclass`. `--subclass` and every grouping use the reviewed one.
- `gate_labelled` approximates `gate.labelled_count` from the release, before the SHF-015 and
  SHF-019 drops, which can only lower it. A document listed as unscorable is unscorable in
  production too. A document just above the bar can still drop under those fixes.
- A slice draw applies the slice's own staged cut, because the overlay decides which CUAD-empty
  contracts are drawn. `--slice` needs that cut pulled, and stops with an error naming the pull
  command when it is not.
