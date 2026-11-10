# Named datasets and reproducible selections

[`config/datasets.yaml`](../../config/datasets.yaml) lets run specs refer to a
shared source without committing a machine's absolute path. The run resolves
the entry before validation; explicit fields in the run spec override the
entry. A registry name is provenance, not a content hash.

```yaml
# Registry (config/datasets.yaml or $SANDBOX_DATASETS_REGISTRY)
datasets:
  reviewed-local:
    provider: file
    local_path: ${MAILROOM_BASE_DIR}/datasets/reviewed.jsonl
    # Optional sha256: insert the verified 64-character lowercase source hash.
    pull:
      source: family-corpus
      note: Describe the actual preparation and selection recipe here.
```

```yaml
# Inside a complete config/runs/<name>.yaml
dataset:
  name: reviewed-local
  limit: 50
  sample_seed: 42
  require_task_gt: true
```

Materialize and inspect the source first, then compute its SHA-256 and add
`sha256` to the registry if the bytes should be pinned. A mismatched source
fails preflight. Run `sandbox run preflight --config <file>` to inspect and
lock the exact selection before starting a job. See [job locks and
generations](../jobs.md#dataset-identity) for the resulting artifacts and
relock rules. Preflight for a Hub source may access the network; a local-file
source is offline.

## Registry fields

| Field | Contract |
| --- | --- |
| `provider` | `huggingface` (default) or `file`. A supplied `local_path` also selects local-file loading. |
| `repo`, `config`, `split`, `revision` | Hub source. Defaults are the family repository, `ground_truth`, `test`, and the frozen family revision at lock time. The committed `family-corpus` entry explicitly uses split `all`. Preserve explicit experiment revisions. |
| `local_path` | Nonempty path or `file://` path; supports environment templates and `~`. |
| `sha256` | Optional 64-character lowercase hexadecimal source-file pin; resolved to `source_sha256` in the run spec and verified against the bytes parsed at preparation. |
| `limit` | Positive maximum row count, applied after filtering and selection. |
| `sample_seed` | Seed for supported stratified draws; a seed alone does not shuffle an unstratified source. |
| `strata` | Filters or stratified selection. Supports legacy `expected` / `expected_subclass` lists, `buckets`, or `field` + `values` + optional `counts`. See the selection examples below. |
| `exclude_expected` | Document classes to exclude before the draw. |
| `require_task_gt` | Default false; true removes rows lacking task-native ground truth before selection, including empty CUAD/MAUD labels. |
| `interim_labels` | Default false; opt into the interim ground-truth overlay. Its fingerprint enters the request hash and its provenance stays distinct from Hub ground truth. |
| `pull` | Optional mapping describing provenance. It is recorded, not executed or independently verified. |
| `columns`, `expected_fields` | Accepted declarations; the current corpus-selection path does not use them to remap or filter rows. Do not rely on them to change the runnable subset. |

Unknown registry keys and duplicate YAML mapping keys are rejected, including
duplicates inside entries. YAML merge keys (`<<`) are unsupported. The top-level
`datasets`, when present, must be a nonempty mapping. `name` belongs in the run
spec, rather than inside a registry entry.

Examples of alternative `strata` blocks:

```yaml
# Filter to one class
strata:
  expected: [contract]
```

```yaml
# Draw a count from each named subclass
strata:
  field: expected_subclass
  values: [bylaws, board_resolution]
  counts: [10, 10]
```

```yaml
# Class/subclass buckets
strata:
  buckets:
    - doc_class: corporate_record
      sub_buckets:
        - subclass: bylaws
          count: 10
```

These are alternative selection modes. Counted draws require `sample_seed`
when sampling fewer rows than the available candidates, and insufficient
candidates fail rather than silently filling from another stratum. Buckets
also support nested `sub_buckets` with `subclass` and `count`. Inspect
`strata_actual` after preflight to confirm the achieved counts. The implementation is
[`corpus.select_rows`](../../src/mailroom_sandbox/corpus.py); filter and draw
details also appear in [eval guidance](../evals.md).

## Paths, environment and caches

The CLI loads `.env` before parsing a run spec. Start from
[`config/.env.example`](../../config/.env.example), copied to the repository
root as `.env`. Exported environment variables can supply lane-specific paths.

- `${VAR}` requires a nonempty value; `${VAR:-fallback}` uses the fallback
  when unset or empty. Expansion happens once at spec validation.
- `MAILROOM_BASE_DIR` is special: unset or empty resolves through
  `paths.data_dir()` to `<repo>/data`, even if the template supplies another
  fallback. Set an absolute value for predictable operation from any directory.
- Other relative local paths resolve from the process's working directory,
  not from the registry's directory. `~` is expanded when opening the path.
- `SANDBOX_DATASETS_REGISTRY` selects a different registry file; its default
  is `<repo>/config/datasets.yaml`.
- `MAILROOM_BASE_DIR` changes run data locations. Normalized corpus caches
  remain under `<repo>/data/cache/`; raw Hub snapshots use `HF_HOME`, defaulted
  to `<repo>/data/cache/hf` only when unset.

Use the appropriate operation:

```bash
sandbox datasets prepare                    # offline fixtures -> data/runtime/prepared/
sandbox datasets pull                       # live, pinned normalized full corpus -> data/cache/
sandbox datasets sample --per-class 20 --seed 42 --out data/datasets/ground_truth_all_perclass20.jsonl
sandbox hf download --sandbox-cache         # raw Hub files; not the normalized corpus
```

The sampler is offline and needs an existing full cache (or `--from <jsonl>`).
A bounded `datasets pull --max-rows ...` does not replace the full cache.
The frozen defaults live in
[`job/spec.py`](../../src/mailroom_sandbox/job/spec.py); they do not assert
anything about current Hub HEAD. Keep network/model calls out of default tests.

## Identity, selection and migration

Rows are normalized, filtered, canonically sorted and selected before the
global limit. Shuffling source-file lines alone does not control run order.
Verify IDs in the locked `dataset.jsonl` when reproducing a draw.

| Evidence | Identifies |
| --- | --- |
| Registry name and `pull` | Optional declared provenance, stored as metadata only when supplied. |
| Local `dataset.metadata.sha256` in `spec.lock.json` | Original source bytes, before normalization and selection. |
| Locked `dataset.sha256`, `rows`, `strata_actual` | Exact prepared `dataset.jsonl` bytes, size and achieved strata. |
| `spec_core.dataset` and `spec_hash` | Source request and selection settings used for drift detection. |

Local request identity uses the filename and source SHA-256 when the file
exists, plus selection settings. An identical same-named file hashes alike
across directories; renaming the file changes identity. The registry alias,
pull recipe and declared SHA pin do not enter the hash. A missing file can
produce a request hash without source bytes, but cannot establish a valid
prepared selection.

The filename-based scheme changes older path-based local spec hashes. Hub
hashes are unaffected by that migration. Separately, `require_task_gt: true`
now enters both local and Hub hashes, so previously filtered specs drift;
the false default remains omitted to preserve unfiltered hashes. Toggling
the filter must not reuse an old subset. Use a new run or inspect drift and
the eligible generation archive before an intentional `--force` relock.
Do not edit old locks or hashes to force a resume.

## LM Studio demonstration source

[`pipeline-lmstudio-even50-demo.yaml`](../../config/runs/pipeline-lmstudio-even50-demo.yaml)
uses `pipeline-even100-shuffled2` with limit 50. Its registry recipe records
a historical 20-per-class draw and an external seed-2 shuffle; no source SHA
pin or shuffled file is committed. A name or reconstructed recipe does not
prove equivalence to the historical file, and the canonical limit does not
select its first 50 physical lines. Inspect source bytes and locked IDs.

The demonstration requires the local dataset file under `MAILROOM_BASE_DIR`,
an LM Studio OpenAI-compatible endpoint on port 1234 with `qwen3.5-9b`, and
the run's configured 65,536-token context. Set `MAILROOM_JSON_MODE=off` as
documented in the spec and disable reasoning in LM Studio. Inspect its
concurrency, wall-time and cost settings before starting; it is a real local
model run. The default serving profile remains Modal vLLM. For a UI-only
demonstration use the [offline floor replay](../floor.md#bundled-replay-and-ownership).
