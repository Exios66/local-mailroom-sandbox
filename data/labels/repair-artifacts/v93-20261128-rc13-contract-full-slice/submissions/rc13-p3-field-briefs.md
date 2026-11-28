# Field briefs: rc.13 phase 3 (open contract entity cells in the full production slice). Contract target fields: the nine below.

Label only the fields each document lists in its `batch.jsonl` `fields`.

## Contract fields (Dojo `ContractExtraction` v2; guide section "Contract fields")

| Field | Type | Definition | Where to look |
|---|---|---|---|
| `party_roles` | list | One `"<party>: <role>"` line per party. Role is exactly one of `licensor`, `licensee`, `supplier`, `customer`, `distributor`, `reseller`, `franchisor`, `franchisee`, `service_provider`, `client`, `sponsor`, `agent`, `principal`, `partner`, `lender`, `borrower`, `other`. Use the party's legal name as printed. | Preamble, defined terms ("the \"Distributor\""), recitals. |
| `signatories` | list | Persons who sign the contract, names as printed (no titles). | "IN WITNESS WHEREOF", "By:", "/s/", "Name:". A blank signature line is not a signatory. |
| `agreement_date` | date | The "dated as of" or signature date, `YYYY-MM-DD`. | Preamble, signature blocks. |
| `expiration_date` | date | End of the initial term when the text states it as a date; else null. Never compute it from a term length. | "Term", "expire", "until", "through". |
| `termination_notice_period` | free text | Notice needed to terminate the contract or to stop a renewal, as stated. Keep it short and include every stated kind (for convenience, non-renewal). | "terminate", "notice", "non-renewal". |
| `contract_value` | money (text) | Monetary consideration as a plain dollar figure Dojo parses ("$2,000,000"): a scale word written out, no currency code, no rate ("per month"). $0 is a stated amount. Never computed, never summed. Another currency: leave the field out with a note. | "fee", "price", "pay", "$". |
| `payment_terms` | free text | How and when the consideration is paid, as stated, in one short sentence. | "payable", "invoice", "within … days", "Net". |
| `territory` | free text | The stated territory of the grant, distribution or service ("worldwide", "the United States"). | "Territory", "throughout", "in the … region". |
| `dispute_forum` | name | Courts or arbitral seat for disputes, kept separate from governing law. A governing-law clause alone is not a forum. | "courts of", "jurisdiction", "venue", "arbitration", "AAA", "ICC". |

Conventions already in the catalog (follow them):

- `signatories` evidence is the signature line, e.g. `"By:  /s/ Robert W. Stallings"` or `"Name: John J. Lofquist"`.
- `party_roles` evidence is the preamble clause naming the party and its defined role.
- Exhibit or schedule-only contracts with blanks (`[•]`, `____`, `[***]` redactions): a blank is not a value.
- Absent reasons are short: `"not found in full read"` or `"not found by search"`, with a qualifier if useful
  (`"no territory stated; not found in full read"`).
