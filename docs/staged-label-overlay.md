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
  staged_overlay: 9.3.1-rc.3     # a version pinned in config/staged_overlays.yaml
```

Pull the pinned cut before preparing the dataset. This needs GitHub network access but involves
no spend:

```bash
python scripts/pull_staged_overlay.py --version 9.3.1-rc.3
```

- **Pinned, never "latest".** `config/staged_overlays.yaml` names, for each version, the
  mailroom-issues commit and the sha256 of the cut's `MANIFEST.json`. That manifest pins every
  overlay file's sha256. A cache whose bytes differ from the pin is refused before the draw.
  A new cut is a new pin entry; an existing entry is never edited.
- **Per-document text check.** A record applies only to the document whose text has its
  `content_sha256`. A changed document keeps its Hub labels and is counted as `stale_rows`.
- **Revision check.** On a Hub source, a resolved revision other than the overlay's
  `base_tag_commit` is refused. A local file source is bound by the per-document text check.
- **Instead of the other overlays, never on top of them.** `staged_overlay` together with
  `interim_labels` or `near_gold_labels` fails at parse.
- **Subclass.** The overlay's `subclass` labels are not applied. Subclass repairs stay with
  SHF-013 (`data/labels/review/subclass_corrections.jsonl`).
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
- joins the assist CSV;
- rewrites cut-off magnitudes ("eighty (180) days" from a builder grammar that keeps one number
  word) with the document's own spelling, and queues any it cannot ground.

Commit the cut in mailroom-issues, then add its pin here.
