# Current experiment campaign contract

This is the runtime and scoring contract for new rb1 experiment generations. The
[research plan](superpowers/plans/2026-11-18-evaluation-runbook-plan.md) defines H1–H5,
sequential looks, calibration and the sealed confirmation. Historical SAND-032/037/040/042
grids retain their original pins and measurements. A patch passing offline tests is not
evidence of improved live quality.

Reviewers must consult the [campaign preparation regression checklist](campaign-preparation-regressions.md)
and cite the applicable `CP-*` IDs with their evidence and remaining acceptance.

## Dataset and truth

- New campaign templates use `Lucius-Morningstar/mailroom-dataset` v9.3, tag commit
  `ff4ca546d4346991628c2616ae014afc15e9fe04`, parquet parent
  `7fd99b406ab1b627f43602dd6a3af5fb5b7a3ac5`: 3,302 documents across five classes.
- New rb1 looks use `config/splits/runbook-v2/`. Its exposure list includes the old
  dev-look1, hand-check and smoke documents, and all 50 form-calibration draw-1 documents.
  One spent calibration document entered the initially proposed held-out set; the repaired
  split excludes it and every other exposed component. Never rebuild a split after use.
- Form-calibration draw 1 remains a v9.1 measurement. Draw 2 uses the v9.3 calibration
  complement plus the committed spent IDs. Both question sets receive the same fresh
  documents and the same constructed defects. Bundles have no scored class or subclass;
  fragments retain their source class. Report synthetic controls separately.
- Enable both `dataset.interim_labels` and `dataset.near_gold_labels` for the repaired
  extraction truth. Hub values win over ordinary gap fills. Reviewed corrections replace
  the specific Hub value they name. Near-gold supersedes eligible conflicting interim
  gap fills through SHF-010; original-header fills retain their distinct provenance.
- The field registry must match both the run's dataset revision and its split assignments.
  `gold_audit.resolve_inputs` selects the matching historical or current registry; a
  mismatched registry is refused. Iterate only fields supported by its verdicts.

The full v9.3 evidence audit on 2026-11-19 checked 7,852 overlay labels: 6,921 grounded and
931 vocabulary-validated, with no unsupported labels or merge-precedence violations. It
also exposed 30 unsettled Hub/overlay conflicts. These remain visible for adjudication;
they are not automatically converted into corrections. Grounding verifies the admission
rule, not the semantic correctness of every label. The review tracker still has one
`needs_human` verdict and separate catalog/policy work (#328).

Never pair v9.1 and v9.3 scores as one experiment. Preserve old locks, reports and label
snapshots. A new baseline, prompt, label revision or hotfix generation requires a new
lock/iteration and explicit comparison provenance.

## Patches that must run

The complete implementations and upstream retirement conditions live in
[vendor hotfixes](vendor-hotfixes.md) and [scoring hotfixes](scoring-hotfixes.md).

| Layer | Required behavior | Regression evidence |
| --- | --- | --- |
| HF-001 | Fill a missing corporate record type from every registered subclass | `test_vendor_hotfixes.py` |
| HF-002 | A judge parse failure is an error and review route, never a genuine incomplete verdict | `test_scoring_hotfixes.py` |
| HF-003 | Refuse intake cleaning that drops source length or ordered content | `test_vendor_hotfixes.py` |
| HF-004 | Price each returned call once; refuse later calls at spend/call ceilings. Decisions responses are priced in the transport, not again by the usage wrapper. Isolated decision tasks use the per-document ceiling | `test_call_guard.py` |
| HF-005 | Hold files at saturated filesystem bins without dropping them; bound inbox waits and unfinished uploads | `test_backpressure.py` |
| HF-006 | Preserve explicit zero confidence in single and chunked specialist extraction | `test_vendor_hotfixes.py` |
| HF-013 | The same for the accuracy judge: a correctness parse failure is a judge error, never an "inaccurate" answer that reads as incomplete | `test_vendor_hotfixes.py` |
| HF-014 | On a context-fitted route, an arbiter acceptance from a whole-source reading archives with a visible `arbiter_caveats` marker once the extraction confidence reaches `confidence.arbiter_full_source_min_confidence` (unset: the class `low`, so no route changes); lost chunks, conflicts and 16k-excerpt routes still park | `test_arbiter_full_source.py`, `test_gate.py` |
| HF-015 | On a context-fitted route, an arbiter with no re-extraction budget left is never offered a retry | `test_arbiter_full_source.py`, `test_arbiter_termination.py` |
| SHF-001–004 | Count documented absences and correct name, currency and identifier matching | `test_scoring_hotfixes.py` |
| SHF-005–008 | Keep failed rows in denominators; count missing truth and abstentions; refuse invented verdict truth | `test_scoring_hotfixes.py` |
| SHF-009–010 | Apply decision-form abstention and reviewed truth precedence | `test_scoring_hotfixes.py` |
| SHF-011–013 | Score failed paired items correctly and score subclasses jointly with class, retaining raw Hub truth | `test_scoring_hotfixes.py`, `test_scoring_hotfixes_shf013.py` |

Pipeline fixes install at activation. Required unavailable or stale fixes fail preflight;
the executing local or Modal worker also checks its hotfix identities against the lock.
HF-005 may be unavailable in a dev installation without the observability extra, where the
watcher cannot import. Watcher execution requires the stricter check below. Scoring-call
fixes operate inside `hotfixed()` scopes and retain raw Dojo values; truth preparation and
decision-routing fixes apply at their documented boundaries.

The sandbox also supplies whole-document context fitting and source-window restoration,
provider credential routing, served-model/provider ledgers, call usage capture, schema-guide
descriptions and isolated run stores. These helpers are part of the experiment conditions:
record their settings and actual source identity. Context fit widens judge/arbiter excerpts
only to the fitted budget; it does not implement arbitrary-length multi-window adjudication.

`vendor/` remains byte-identical to reviewed standalone pins. When an upstream release
replaces a workaround, review the owning source, refresh through the sanctioned vendor
workflow, and retire or revalidate its fingerprint and tests in the same change. A newer
version number alone never proves a fix is incorporated.

## Cost and readiness

The context plan reports input-only upper bounds, not a full-run quote. The worst extraction
path includes confidence retries plus arbiter-requested retries. Every judge pass budgets two
LLM calls: completeness and, for a complete verdict, source correctness. A separate high-confidence
retry scenario shows the extra judge call from `judge_rejudge_retry`, respecting the class
override and judge pass cap; a cap of one leaves no retry scenario. `keep_best_attempt` selects stored attempts and adds no calls.
Output tokens, intake, classification and transport retries are outside this input estimate;
compare measured per-class costs before the 500-document and full slices (#330).

From the intended checkout and its own environment, run these offline checks after caching
the pinned corpus once:

```bash
export PYTHONPATH="$PWD/src"
python scripts/check_hotfixes.py
python scripts/check_hotfixes.py --require-watcher  # needs pipeline + observability dependencies
HF_HUB_OFFLINE=1 sandbox splits audit --name runbook-v2
HF_HUB_OFFLINE=1 sandbox schemas build --check
sandbox runbook check
HF_HUB_OFFLINE=1 python scripts/check_g0.py
```

G0 includes the hotfix check and still fails when smoke ledgers, human hand-checks or gold
adjudications are missing. Hosted tests, lint, generated artifacts and the 84% coverage floor
must pass on the exact PR head before merge. Before paid work, preflight the actual run
config, review its lock, then have the operator supply initials and the appropriate GPU/API
caps. Redeploy a Modal job worker when its bundled source or hotfix identities differ.

Remaining validation is explicit: full long-document adjudication (#213), recorded
per-window confidence and measured merge-policy comparisons (#214), confidence-band
calibration (#215), frozen corporate-prompt policy (#216), Modal host/topology parity
(#308/#217), and spend-gated re-smokes (#212). These issues cannot close on offline patches
alone. The same-generation cross-client Modal dispatch race (#154) also remains open;
serialize same-run control operations until a source-owned distributed guard is verified.
