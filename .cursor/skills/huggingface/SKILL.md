---
name: huggingface
description: >-
  Sandbox dataset and weight guidance: pinned Hub pulls, offline fixtures and
  cached draws, named datasets, exact run-subset identity, HF cache, and floor
  replay provenance. Read sandbox-tool-router first. Use offline fixtures for
  tests; never infer a run's dataset from Hub HEAD or a registry name.
---

# Hugging Face (sandbox data + weights)

Use this after [sandbox-tool-router](../sandbox-tool-router/SKILL.md) for
sandbox datasets, model pulls, `HF_TOKEN`, and floor sample provenance. General
Hub administration may also use the installed `hf-cli` skill; it does not
replace the sandbox's selection and lock contracts. Default tests use fixtures
and mocks, with no Hub or model calls.

## Choose the data operation

| Need | Command or asset | Dataset network |
| --- | --- | --- |
| Synthetic test inputs | `data/fixtures/`, including `hf/docclass_mini.jsonl` | None |
| Clean offline fixtures | `sandbox datasets prepare` → `data/runtime/prepared/` | None |
| Normalized pinned corpus | `sandbox datasets pull` → `<repo>/data/cache/` | Live Hub path |
| Per-class draw from existing JSONL | `sandbox datasets sample --per-class N` | None |
| Exact runnable subset and immutable manifest | `sandbox run preflight --config <file>` | None for local files; Hub path for Hub specs |
| Floor UI sample | `sandbox floor --replay --base <scratch-data-dir>` | None; all results simulated |

`datasets prepare` cleans fixtures; it does not pull Hub data, sample the full
corpus cache, or prepare a particular run's lock. `datasets pull --max-rows 50
--split test` materializes a bounded subset; it is not streaming and cannot
replace the full cache required by the default `datasets sample` command.

## Pins and offline draws

Read `src/mailroom_sandbox/job/spec.py` before changing a revision. At the PR
274 baseline (2026-11-09), the default family pull is:

- Repo: `Lucius-Morningstar/mailroom-dataset`.
- `FAMILY_HF_TAG`: `v9.1`; `FAMILY_HF_REVISION`:
  `bc9eab280044befb51e19dda3071d290a8677f42`.
- `FAMILY_HF_DATA_REVISION`: `ed7576b676343e0b402ec5412cded301e629bdee`
  (the data commit; distinct from the tag-recording commit).
- Config `ground_truth`, split `all` (train + test), 3,302 rows:
  contract 600, corporate_record 450, correspondence 1,000,
  insurance_claim 1,100, merger_agreement 152.

These are reproducibility defaults, not Hub HEAD. An experiment may pin a
different revision; preserve its config and lock. The full pull merges blind
text with ground truth by filename and checks `content_sha256`. Failures return
nonzero; never substitute fixtures and report a live pull as successful.

```bash
sandbox datasets pull                       # live; install .[hf] or .[dev] first
sandbox datasets sample --per-class 20 --seed 42 --out data/datasets/ground_truth_all_perclass20.jsonl
sandbox datasets sample --per-class 40 --seed 42  # offline, once the full cache exists
```

Default sample input is
`<repo>/data/cache/Lucius-Morningstar__mailroom-dataset__bc9eab280044/ground_truth_all.jsonl`.
`--from <jsonl>` selects another existing source; `--out` selects its destination.
The seed controls per-stratum draws. Rows are normalized, filtered, canonically
sorted and selected; a global limit is then applied. Without strata, a seed
alone does not shuffle rows. Use locked IDs to verify the selected documents;
changing input line order alone does not change canonical selection.

## Dataset identity and run locks

Run YAML may use `dataset: {name: pipeline-even100-shuffled2, limit: 50}`.
`config/datasets.yaml` supplies provider fields, `local_path`, optional `sha256`
and optional `pull` provenance. `$SANDBOX_DATASETS_REGISTRY` selects a different
registry. Explicit spec fields win. Duplicate YAML mapping keys are rejected.

Paths expand `${VAR}` / `${VAR:-default}` once at spec validation; an unset
variable without a default fails. `MAILROOM_BASE_DIR` is special: when unset or
empty it resolves through `paths.data_dir()` to `<repo>/data`, even if the
template contains a relative fallback. Keep machine paths out of committed run
specs and registry entries. The demo registry entry describes a historical
external shuffle and has no committed source SHA pin; its name alone does not
prove the file's identity or reproduce that historical draw.

Preflight reads a local source once, verifies any registered `source_sha256`,
and parses those same bytes. A mismatch is a failed `dataset` check. Successful
preflight locks the prepared rows in the run store:

| Evidence | Meaning |
| --- | --- |
| `dataset.jsonl` | Exact normalized, selected rows used by this run |
| `spec.lock.json` → `dataset.sha256`, `rows`, `strata_actual` | Prepared subset byte identity, size and class/subclass counts |
| `dataset.metadata.sha256` | Original local source-file byte identity; distinct from the prepared subset hash |
| `dataset.metadata.name`, `.pull` | Registry name and pull recipe, only when supplied |
| `dataset` revision/config/split and `spec_core.dataset` | Requested source and selection settings; inspect metadata to distinguish local from Hub provenance |

For local specs, `spec_hash` uses the **filename** (`local.name`) and source
SHA-256 when the file exists, plus `limit`, `sample_seed`, `strata` and
`exclude_expected`. `require_task_gt: true` is hashed for local and Hub specs:
it drops rows without task ground truth before the draw. The false default
stays absent so unfiltered hashes remain stable. Toggle it only with a new run
or an inspected relock; preflight must refuse to reuse the old subset.
Registry `name`, `pull`
and the declared SHA pin are provenance, not hashed identity. The same-named
file with the same bytes hashes alike across directories. A missing file can
still produce a spec hash without source bytes; that is not a successful
preflight or proof of a sample. Existing local-file locks from the older
path-based scheme drift under this scheme. Filename portability alone leaves
Hub hashes unchanged; the task-GT filter fix also changes previously filtered
spec hashes for either provider. Do not
use `--force` just to silence drift: it archives an eligible generation and
creates a replacement. Preserve historical artifacts and inspect the cause.

See [jobs](../../../docs/jobs.md) and
[registry tests](../../../tests/test_dataset_registry.py) for the lock contract.

## Cache, authentication and weights

Normalized corpus JSONL lives under `<repo>/data/cache/`. Raw Hub snapshots use
`HF_HOME`; the corpus loader defaults it to `<repo>/data/cache/hf` only when it
is unset. `MAILROOM_BASE_DIR` selects run data, not these repo-local cache paths.

```bash
sandbox hf whoami
sandbox hf download --dry-run
sandbox hf download --sandbox-cache   # raw Hub files, not the normalized corpus JSONL
sandbox hf cache --revisions --sandbox-cache
sandbox hf raw -- <hf arguments>
```

Use the maintained `hf` command. `sandbox hf download` defaults to the family
revision for the sandbox dataset only; an explicit `--revision` wins, and other
repos are not automatically pinned. It downloads raw files, so run
`sandbox datasets pull` to materialize the normalized full corpus before the
default cached sampler. `--sandbox-cache` explicitly sets the child process's
`HF_HOME`; otherwise the wrapper preserves the operator's cache.

Use existing `HF_TOKEN` / `hf auth login` for gated or private repos and never
log tokens. Modal weight downloads use the `sandbox-hf-cache` volume; consult
the router's serving lane for deployment work. The retired `hf_transfer` extra
and `HF_HUB_ENABLE_HF_TRANSFER` are not the Modal download path.

## Floor sample and boundaries

The bundled floor sample has 120 public document IDs and metadata, 24 per live
class, with pinned provenance and a scripted trace. It contains no document
text; it is not a runnable LLM corpus. Every decision, score, latency and token
count is simulated and must not be cited as experiment evidence.

`sandbox floor` serves on `127.0.0.1:8769`. `--replay` writes a labeled
`runtime/runs/replay-mailroom-sample` inside the selected base; the no-runs
fallback does so only when no target was selected. Replays persist beside
history. Reset requires a replay-owned run or an empty directory; foreign
content, invalid locks and symlinked run directories are refused. Use a scratch
base for disposable UI work. Keep review outcomes HELD, with technical errors
counted as FAILED. Refresh checks must cover missing/incomplete class labels
and selection reset as well as live-to-idle polling.

See [sample provenance](../../../data/fixtures/floor/replay/README.md) and
[floor tests](../../../tests/test_floor_app.py). Do not vendor full CUAD PDFs
or rewrite the scripted sample into measured output. Synthetic HF mini
fixtures are not Hub documents. For fixture attribution, see
[ATTRIBUTION.md](../../../data/fixtures/ATTRIBUTION.md).
