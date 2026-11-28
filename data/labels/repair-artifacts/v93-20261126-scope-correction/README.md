# v9.3 repair scope correction

The active catalog withdraws 38 corporate annotations added in `4d1b863c`: 35
inapplicable subsidiary-list fields and three indenture filing-number absences.
These fields do not belong to those subclasses' applicable core schema. The
corporate gold and supplementary rows now exactly match the prior `6003cf35`
checkpoint; no older annotation was changed.

Four source-reviewed correspondence absences remain in the active catalog. They
support hallucination checks; they are not populated field-level extraction
targets and must not be reported as that kind of coverage improvement.

`INDEX.json` binds preserved submissions to the immutable source revision and
records their disposition. Exported submissions retain label values and evidence;
local checkout prefixes are redacted. Original file digests are recorded alongside
export digests. `withdrawn-*.jsonl` preserves the withdrawn canonical rows.
`PRESERVATION.json` verifies that exactly those 38 provenance cells changed and
all other 48,650 provenance rows were preserved.

Submissions in this directory are recovery and audit artifacts, not active truth.
They include unfinished and unadmitted work. New annotation must use the actual
document text and the registered schema for its subclass. Existing near-gold
values remain protected from missing-field collection.
