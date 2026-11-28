# Field briefs: rc.12 phase 2 (corporate record gate gaps, calibration split)

Label only the fields each document lists in its `batch.jsonl` `fields`. Subclass fields are
defined by the Dojo `SUBCLASS_SCHEMAS` (type, definition, where to look); core fields by the
subclass registry and the labeling guide's "Corporate record fields" section. The brief's value
rules also apply.

## articles_of_incorporation (Articles / Certificate of Incorporation): Charter that creates a corporation (name, purpose, share structure, agent).

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `authorized_capital` | free_text | Authorized share classes and counts, as written. | Capital stock article |
| `filing_number` | core | id: The official filing or document reference number printed on the record (for example an SEC File No. or a state charter/document number), transcribed exactly as written: keep leading zeros and punctuation (`0-1234`, `0012345`). `0` is a stated number. Never use an SEC exhibit number, a form label ("Form 10-K"), a mailing address or the document's year. Null only after the full read (and the long-document search below) finds no official number; when the candidate number is ambiguous, leave the field out and record it in `supplementary` instead of guessing. | see the brief and the guide |
| `incorporators` | entity_list:name | Persons who signed to form the corporation. | Signature block / 'Incorporator' line |
| `registered_agent` | name | Registered agent for service of process. | 'Registered Agent' / 'Resident Agent' article |

## bylaws (Bylaws): Internal operating rules of the corporation (meetings, board, officers, indemnification, amendment).

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `certifying_officer` | name | Secretary/officer who certifies the bylaws as adopted. | Secretary's certificate or closing attestation |
| `last_amended_date` | date | Date of the most recent amendment/restatement stated. | Title block, 'Amended and Restated as of', or adoption legend |

## charter_amendment (Certificate of Amendment / Restated Charter): Filing that amends or restates an existing charter.

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `amended_provisions` | entity_list:free_text | Each charter article/section amended and what changes (one item per provision). | 'Article X is hereby amended to read' |
| `approval_date` | date | Date the board/stockholders adopted the amendment. | Adoption recital |
| `effective_date` | core | date: The date the record takes effect, or its adoption or filing date when no effective date is stated. | see the brief and the guide |
| `filing_number` | core | id: The official filing or document reference number printed on the record (for example an SEC File No. or a state charter/document number), transcribed exactly as written: keep leading zeros and punctuation (`0-1234`, `0012345`). `0` is a stated number. Never use an SEC exhibit number, a form label ("Form 10-K"), a mailing address or the document's year. Null only after the full read (and the long-document search below) finds no official number; when the candidate number is ambiguous, leave the field out and record it in `supplementary` instead of guessing. | see the brief and the guide |
| `jurisdiction` | core | name: The state or country under whose law the entity is organised (for example "Delaware"). | see the brief and the guide |
| `prior_entity_name` | name | Former legal name when the amendment changes the name. | Name-change article |
| `signatories` | core | list of names: People who sign the record (officers, directors, incorporators, grantors), as printed in the execution block. `[]` when there is no execution block. | see the brief and the guide |

## indenture (Indenture / Debt Instrument): Contract between an issuer and a trustee governing a debt issue.

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `effective_date` | core | date: The date the record takes effect, or its adoption or filing date when no effective date is stated. | see the brief and the guide |
| `guarantors` | entity_list:name | Guarantors of the notes. | Guarantor signature pages |
| `maturity_date` | date | Stated maturity. | Terms of the securities |
| `principal_amount` | money | Aggregate principal amount, as written. | Terms of the securities |
| `securities_series` | name | Designation of the notes, e.g. '5.25% Senior Notes due 2030'. | Title and Section 2.01 |
| `signatories` | core | list of names: People who sign the record (officers, directors, incorporators, grantors), as printed in the execution block. `[]` when there is no execution block. | see the brief and the guide |
| `trustee` | name | Indenture trustee. | Preamble, 'as Trustee' |

## officer_certificate (Officer / Secretary Certificate): Certificate by an officer attesting to facts or attaching governing documents.

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `addressee` | name | Party relying on the certificate (trustee, lender, agent). | 'delivered pursuant to' recital |
| `certified_matter` | free_text | What is certified (charter, bylaws, resolutions, incumbency). | Certification recital |
| `certifying_officer` | name | Officer who signs the certificate. | Signature block |
| `effective_date` | core | date: The date the record takes effect, or its adoption or filing date when no effective date is stated. | see the brief and the guide |
| `officer_title` | name | That officer's title. | Signature block |

## powers_of_attorney (Power of Attorney): Grant of authority from a principal to an attorney-in-fact (often to sign SEC filings).

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `attorneys_in_fact` | entity_list:name | Persons empowered to act. | 'hereby constitutes and appoints' |
| `authority_scope` | free_text | What the attorney-in-fact may do. | Grant clause |
| `expiration_date` | date | Date authority lapses, when stated. | Term clause |
| `principal` | name | Person or entity granting the authority. | 'The undersigned' / signature block |

## rights_instrument (Rights / Warrant / Preferred / Specimen-Stock Instrument): Instrument that grants securities holders rights (warrants, stockholder rights, preferred designations, registration rights, specimen certificates).

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `exercise_price` | money | Exercise/strike price, as written. | Exercise clause |
| `holder` | name | Registered holder or beneficiary, when a named party. | Face of warrant / schedule |
| `instrument_kind` | name | Kind of instrument: warrant / rights plan / preferred stock / registration rights / specimen stock. | Title and first recital |
| `rights_agent` | name | Rights/warrant/transfer agent. | Agent signature block |
| `securities_covered` | free_text | Class and number of securities, as written. | Operative grant |

## subsidiary_list (List of Subsidiaries): Schedule of the registrant's subsidiaries (typically Exhibit 21).

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `subsidiaries` | entity_list:name | Each listed subsidiary, legal name as written. | Subsidiary table, first column |
| `subsidiary_jurisdictions` | entity_list:name | Distinct jurisdictions of organization listed for subsidiaries. | Subsidiary table, jurisdiction column |
