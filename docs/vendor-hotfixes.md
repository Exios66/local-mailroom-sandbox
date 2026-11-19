# Vendor hotfixes

`vendor/` holds byte-identical snapshots of the pinned family repos (`tests/test_vendor_drift.py`),
so it is never edited. A pipeline fix an experiment needs before llm-mailroom ships it lives in
[`src/mailroom_sandbox/vendor_hotfixes.py`](../src/mailroom_sandbox/vendor_hotfixes.py): each
hotfix wraps one vendored function at activation, and every run that starts from this checkout
gets it. Scoring is never patched here; the scorer is the Dojo pin.

## How a hotfix stays honest

- **Bound to the code it fixes.** A hotfix records the sha256 of the target's source. After a
  vendor refresh changes that function, the hotfix is not installed (`stale`) and
  `sandbox run preflight` fails on the `vendor_hotfixes` check until it is re-validated against
  the new code or retired.
- **Recorded in every run lock.** `vendor_hotfixes` in `run.lock.json` holds the module sha256
  and each fix's id and target fingerprint. A resume refuses a lock whose hotfix set differs;
  locks from before the layer carry no key and resume as before.
- **Tracked upstream.** Each hotfix names the llm-mailroom issue or PR that will make it
  unnecessary. When the fix is vendored, the fingerprint no longer matches: delete the hotfix,
  its tests and this table row in the same change as the vendor refresh.

## Active hotfixes

| Id | Target | Fix | Upstream |
| --- | --- | --- | --- |
| HF-001 | `langchain_agents.doc_inventories.enrich_extraction` | A null corporate `record_type` is filled from every corporate subclass through Dojo's subclass → `record_type` map. Upstream fills it only for the five Hub tokens, so indenture, board_resolution, officer_certificate, subsidiary_list, charter_amendment and certificate_of_formation left it null. | Exios66/llm-mailroom (issue pending) |

## Adding one

1. Reproduce the defect against the vendored code in a test.
2. Add a `Hotfix` to `HOTFIXES` with the target's current source sha256
   (`hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()`), an upstream reference and a
   wrapper that changes only the defect.
3. Add a row above and a CHANGELOG entry, and open the upstream issue.

## Isolated specialist runs and the subclass

The pipeline's extract node names the sorter's subclass in the specialist handoff and derives
fields from it (insurance `cms_source_table`, corporate `record_type`). An isolated specialist
run sees no subclass unless `job.specialist_subclass` names one (it needs
`job.pipeline_handoff: true`):

| Value | Subclass in the handoff | Use |
| --- | --- | --- |
| `none` (default) | none | prompt lineages written for "no subclass is given" |
| `gold` | the row's expected subclass (contracts: the CUAD family; refused for the merger specialist, whose subclass is its scored answer) | the specialist behind a correct sorter; derived fields copy the truth, so report them apart |
| `sorter` | a saved sorter pass (`job.specialist_subclass_file`, hashed by content) | the specialist behind that sorter, as the pipeline runs it |
