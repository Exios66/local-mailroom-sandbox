# Subclass field note for the promoted specialist prompts

**Goal.** Every promoted specialist prompt works with the subclass schema the sorter's subclass selects
(HF-023), so a specialist asks for, and fills, the fields of that subclass. Nothing changes for a run that
does not opt in.

**Spec.** This page is the design and the plan. It builds on the
[Phase 3 plan](2026-11-26-phase3-subclass-schemas.md) (HF-023 and HF-024; `job.subclass_schemas`, always on
for pipeline runs).

## What the audit found (2026-11-27, main at `ceb2aed`)

**The wiring holds.**

- The sorter's subclass reaches the specialist in the handoff (`doc_subclass=`, or `contract_subtype=` for
  contracts).
- HF-023 sends that subclass's narrowed schema on every structured call: LangChain specialists use it as the
  strict `json_schema` response format, and the legacy `agents/` specialists put it in the user message.
- Every sorter subclass token has a field list, except four insurance lines that fall back to the class
  schema by design: `health`, `liability`, `life` and `workers_comp` (FNOL forms, not yet labeled).

**The promoted prompts are class-level, frozen text.** They were written before subclass schemas existed,
so some of their instructions name fields a subclass schema no longer requests.

| Agent | Promoted prompt | Conflict with the subclass schemas |
| --- | --- | --- |
| merger | `merger_agreement_specialist_maud_v2` | Sends consideration and exchange-ratio language to `subject_matter` or `keywords`, "never in maud_clauses". The four non-fallback subclasses (all but `other`, which keeps the class schema) drop `intent`, `keywords` and `subject_matter`, so that text has nowhere to go but `maud_clauses`, the only scored merger field. |
| corporate | `corporate_records_specialist_condensed_v1` | Names `filing_number`, dropped for `bylaws`, `indenture`, `rights_instrument` and `subsidiary_list`; names `jurisdiction` and `signatories`, dropped for `subsidiary_list`. |
| insurance | `insurance_claims_specialist_condensed_v3` | Names `adjuster` and `denial_reasons`, dropped for 5 of 6 subclasses. |
| contracts | `contracts_specialist_v33_simplified` | Names `merger_consideration` and `maud_clauses` (set them null and `[]`), dropped for all 25 subclasses. Harmless. |
| correspondence | `correspondence_specialist_condensed_v3` | None. |

The strict schema stops a model from writing a dropped field. It does not stop the model from moving that
field's content into a field it can still write, which is the merger risk.

## Decision

- **Do not edit the frozen prompts.** A new prompt version needs its own lineage entry and a paid A/B,
  multiplied across five agents, and it would drift from the committed field lists.
- **Add one deterministic note, generated from the chosen schema.** With `job.subclass_field_note: true`, a
  specialist sent a narrowed subclass schema also gets a short block appended to its system prompt. The
  block names the class and subclass. It lists the fields this subclass does not request ("leave that
  content out; never move it into another field") and any fields it adds.
  - The promoted prompt stays the head of the system prompt, byte for byte.
  - A fallback to the class schema, or a subclass whose field set equals the class's, gets no note.
  - A corporate specialist whose `extract` another hotfix wraps (a corporate schema composer, as in #425)
    keeps that hotfix's schema and gets no note.
  - The note is added to that one specialist instance's default prompt method, never to the call's
    arguments, because the floor-read observer measures a caller-passed `system_prompt` as request text.
- **Off by default, hashed only when set**, like `job.schema_guide`, so no baseline changes silently.
  Adoption is an A/B the owner launches: `config/runs/sx-note-s1-on.yaml` against the Phase 4 stage 1
  baseline `config/runs/p4-s1-verify-gov-off.yaml`. They use the same 300 dev-look1 documents and differ
  only in the note.
- **Not a vendor hotfix.** It patches nothing new in `vendor/`: it rides on HF-023's per-instance
  `_call_structured` wrapper, and it is recorded in `spec_hash` and the lock like `schema_guide`. No hotfix ID
  is taken.
- **Out of scope.** The per-subclass `guide` descriptions in the field lists still apply only with
  `job.schema_guide: true`, which is a separate lever.

## Tasks

1. **Guard tests (no behaviour change).**
   - `test_every_listed_subclass_sends_its_own_schema`: every listed (class, subclass) pair, through the real
     handoff and the real extractor, sends `choose_schema`'s narrowed schema and none of its dropped fields.
   - `test_every_sorter_subclass_token_has_a_field_list_or_a_documented_fallback`: every token
     `doc_inventories.valid_sorter_subclasses` accepts is listed, a fallback token, or one of the four
     insurance FNOL lines.
2. **`job.subclass_field_note`.**
   - Spec: `StrictBool`, default `false`. Refused unless `task: pipeline`, because only pipeline runs have
     subclass schemas. Hashed only when set.
   - Runtime: the lock activates it through `subclass_extraction.activate(..., note=...)`. Unlocked evals
     stay off.
   - `subclass_extraction.field_note(doc_class, subclass, base, schema) -> str | None` builds the note;
     `bind_choice` appends it to the instance's default system prompt method:
     `augmented_system_prompt()` for LangChain specialists, `system_prompt()` for legacy agents.
   - Tests:
     - `test_the_note_names_every_dropped_and_added_field`;
     - `test_no_note_for_a_fallback_or_an_unchanged_subclass`;
     - `test_the_promoted_prompt_stays_the_head_and_the_note_follows`, with the promoted merger prompt and
       `all_cash`;
     - `test_off_sends_no_note`;
     - `test_the_note_flag_is_hashed_only_when_set`;
     - `test_the_note_requires_a_pipeline_task`;
     - `test_the_lock_activates_the_note`.
   - Promoted-prompt guard: `test_every_promoted_prompt_field_a_subclass_drops_is_named_in_its_note`, over
     the production slice's resolved prompts (`with_lineage_defaults`).
3. **A/B config and docs.**
   - `config/runs/sx-note-s1-on.yaml`, preflighted offline.
   - Docs: `docs/jobs.md`, `docs/critical-regressions.md` row 1 (guard names), `CHANGELOG.md` and the
     `docs/README.md` index row.

## Verification

- Named tests run with `-n 0 --no-cov`.
- `ruff`, plus every generated-file check.
- An offline `sandbox run preflight` of the new config.
- No paid run. The owner launches the A/B with their initials.
