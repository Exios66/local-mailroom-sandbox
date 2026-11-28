# Staged production label overlay

The planned v10 label repairs are staged in the mailroom-issues repository, under
`mailroom_cache/v9.3.0/pre-release/v9.3.1-rc.N/`, as a `production-overlay` pre-release. The
overlay is the merged master of the Hub, interim, near-gold and reviewed label layers, stored as
the per-document delta against the Hub v9.3 labels. Production scoring applies it from that
central cache, so every deployment scores against the same labels.

## Using it in a run

```yaml
dataset:
  name: family-corpus            # Hub v9.3 (ff4ca546); the overlay is a delta against it
  staged_overlay: 9.3.1-rc.10    # a version pinned in config/staged_overlays.yaml
```

Pull the pinned cut before preparing the dataset. This needs GitHub network access but involves
no spend:

```bash
python scripts/pull_staged_overlay.py --version 9.3.1-rc.10
```

**New production slice preparations select `9.3.1-rc.10`.** The cache PR
[mailroom-issues #253](https://github.com/LLM-Mailroom-Services/mailroom-issues/pull/253)
landed on 2026-11-26 as merge commit `acd2133ae615e77b521422b8fdba3fa097e87762`;
its pinned source `cfc351f6` remains reachable from main. All sixteen manifest-bound files
verify, and the rc.9 comparison changes no protected Hub, reviewed, near-gold or owner cells.
The seven production slice configs, their test and these instructions select rc.10 together.
The manifest pin is unchanged. This selects a verified prerelease cut; it does not publish a
stable release, launch or deploy a run, or promote machine annotations to human gold.

Existing run locks retain their approved cut. Resume must refuse a changed config/lock;
start a deliberately new preparation generation to use rc.10 rather than editing a frozen lock.
The later corporate repair and notebook in sandbox #425 are outside this immutable cut.

**`9.3.1-rc.11` is staged and pinned, and slices do not select it yet.** It is cut from the
label-repaired release at sandbox `0e083b71` (#453) and carries the corporate subclass fields.
Its pinned commit `2873354a` is on the mailroom-issues branch `stage-v9.3.1-rc.11`, and a fresh
pull verifies against the pin. As with rc.10, the production slice configs move to it together,
once the cache PR lands on mailroom-issues main with that commit kept reachable.

- **Pinned, never "latest".** `config/staged_overlays.yaml` names, for each version, the
  mailroom-issues commit and the sha256 of the cut's `MANIFEST.json`. That manifest pins every
  file's sha256, and every pinned file is checked. A cache whose bytes differ from the pin is
  refused when the labels are applied (`prepare_subset` draws first, then applies them), so
  nothing is scored against it.
  A new cut is a new pin entry; an existing entry is never edited.
- **Per-document text check.** A record applies only to the document whose text has its
  `content_sha256`. A changed document keeps its Hub labels and is counted as `stale_rows`.
- **Revision check.** On a Hub source, a resolved revision other than the overlay's
  `base_tag_commit` is refused. A local file source is bound by the per-document text check.
- **Instead of the other overlays, never on top of them.** `staged_overlay` together with
  `interim_labels` or `near_gold_labels` fails at parse.
- **Subclass.** The overlay's `subclass` labels are not applied. Subclass repairs stay with
  SHF-013 (`data/labels/review/subclass_corrections.jsonl`).
- **Corporate subclass fields.** A cut carries a corporate document's subclass fields (`trustee`,
  `registered_agent`, `certifying_officer`, …) once its builder targets them, which it does since
  2026-11-28. The Hub labels none of these fields, so near-gold labels are their only truth, and
  `9.3.1-rc.10` carries none of them. `9.3.1-rc.11` carries 534; a run that must score subclass
  fields needs it or a later cut.
- **Truth precedence.** In the builder, once a reviewed or near-gold label votes, the Hub and the
  sources computed from it (`hub_v9.3`, `interim_derived`, `generated_derived`) count for nothing
  (`rule: reviewed_over_hub` in the provenance), so a staged cut overrides a faulty Hub value
  wherever such a label exists. Independent evidence still counts: `cuad_span`, `interim_gate`
  and `generated_rule` (a verbatim rule match). A reviewed absence over a populated value, and
  independent evidence that beats a reviewed label, are queued in `needs_human.csv`.
- **Provenance.**
  - The spec hash records `{version, manifest_sha256}`.
  - The run lock's dataset metadata records `staged_overlay` (version, manifest sha256,
    mailroom-issues commit, rows and fields applied, Hub overrides, stale rows).
  - Each prepared row names the fields it took (`staged_overlay.fields`) and keeps every
    replaced Hub value and its presence code (`staged_overlay.overrides`).
  - `sandbox rescore` re-applies the pinned cut the run locked.
- **Overrides.** Hub values the repairs replace are marked `override: true`. They are expected
  (many Hub rows needed repair) and are applied. They also wait in
  `queues/gold_override_signoff.csv` for a person's initials before the v10 release.

## Deployments and remote job workers

Run `scripts/pull_staged_overlay.py` at image build time, with `$SANDBOX_LABEL_CACHE` pointing
at the bundled cache, so scoring never reaches the network. Accept a remote result only when
its lock's `staged_overlay.manifest_sha256` equals the pin. This is the same provenance rule as
for dependency snapshots (`docs/dependency-snapshots.md`).

## Cutting a new version

`scripts/stage_label_overlay.py` writes the cut into a mailroom-issues checkout. It:

- verifies that the builder outputs and script are byte-identical to the named builder commit;
- caches the outputs (data) under `builder/` in the cut, so the cut restages without the
  builder's branch. The script's sha256 and commit are recorded in the manifest; the script
  itself stays in this repository, because mailroom-issues holds no code;
- joins the assist CSV. A cell where the assist differs from the builder goes to
  `queues/needs_human.csv`, except a reviewed duplicate keeper and a reviewed subclass correction
  (`subclass`, `subclass_changed` and the `cuad_family` derived from it), which the assist
  predates;
- rewrites cut-off magnitudes ("eighty (180) days" from a builder grammar that keeps one number
  word) with the document's own spelling, and queues any it cannot ground;
- validates the merged staged (non-Hub) labels against the document text (rc.4 on;
  `validation_repair` in the manifest). Hub-backed cells are not date-, name- or clause-checked;
  only their correspondence `keywords` are cleaned:
  - it keeps only whole ISO dates, maps `cuad_family` to the canonical key the scorer compares,
    and reduces a whole governing-law clause to the jurisdiction it names (found in the text,
    otherwise queued);
  - it drops defined-term aliases, clause fragments, bare defined terms ("the Company") and
    suffix-only captures ("Inc.") from `parties`, unlabels and queues a `name` field holding only
    such a capture (rc.5 on), and de-duplicates entity lists;
  - it trims a describing lead-in from party, advisor and counsel names ("the retention of X",
    "Subsidiary of Y, and X" become X), keeping the evidence quote (rc.6 on);
  - it drops party-role words ("the Customer", "Licensee", "Member"), descriptions of a party
    ("an individual", "your", "the party named above") and alias clauses ("d/b/a X") from
    `parties`, unlabels and queues a party, advisor or counsel name holding only one, and trims a
    role label before a name ("the Supplier: X" becomes X) (rc.7 on). Other name fields, such as
    correspondence `sender`, keep the narrower rc.5 check;
  - it follows the owner's recorded answer on merger signing dates (rc.7 on). A merger
    `effective_date` that is only the signing date (the date the agreement is "dated as of" or
    "made", with no effective-date wording) is held back as `disputed_unresolved` and queued
    while any `signing_date_as_effective_date` row in `interim_audit.jsonl` still says
    `owner_decides`. When those rows say `clear`, the stager records it as a documented absence;
    when they say `keep`, the date stays. The manifest records the policy it applied as
    `signing_date_policy`. This covers the 23 audited interim dates and the 90 generated ones;
  - it holds back, as `disputed_unresolved` and queued, an interim value whose audit row still
    waits for the owner (`action: owner_decides` in `data/labels/review/interim_audit.jsonl`) and
    the conflicting values of documents that share the same text (rc.5 on);
  - it strips maildir user, folder and timestamp tokens from Hub correspondence `keywords`,
    which makes them Hub overrides for sign-off;
- applies reviewed corrections from `data/labels/review/validation_corrections.jsonl`. Every
  correction needs a note. A populated correction also needs a quote, and the stager refuses
  one whose quote is not in the text. An unlabeled or documented-absence correction may omit the
  quote. A correction that matches no cell is refused;
- writes `queues/header_restoration.csv`: the correspondence documents whose labels (basis
  `original_header`) quote the Enron email header that the cleaned corpus text dropped. Those
  labels stay as truth. The next official release restores the listed header lines into
  `doc_text`, so a model sees what it is scored on. Until then, a miss on those fields can
  reflect the missing header rather than the model.

Commit the cut in mailroom-issues, then add its pin here.
