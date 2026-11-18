# Weakness table: ar-mailroom-v2-r00-baseline

75 documents, mean utility -0.274. Lost utility is `1 - utility` per document, charged to one node (rules: `autoresearch/diagnose.py`).

| class | node | lost | docs | share | actionable | causes |
|:---|:---|---:|---:|---:|:---|:---|
| merger_agreement | merger_agreement_specialist | 28.00 | 14 | 37% | yes | extraction:maud_wrong x14 |
| insurance_claim | insurance_claims_specialist | 14.51 | 15 | 19% | yes | extraction:partial x8, extraction:missing_field x4, extraction:wrong_value x3 |
| contract | judge | 13.75 | 11 | 18% | yes | judge:partial_exhausted x10, judge:judge_rejected x1 |
| contract | contracts_specialist | 8.00 | 4 | 11% | yes | extraction:cuad_missed x3, extraction:cuad_false x1 |
| correspondence | correspondence_specialist | 8.00 | 4 | 11% | yes | extraction:wrong_value x4 |
| corporate_record | corporate_records_specialist | 2.00 | 1 | 3% | yes | extraction:wrong_value x1 |
| merger_agreement | reviewer | 1.25 | 1 | 2% | yes | classification:reviewer_unknown x1 |

## By node

| node | lost |
|:---|---:|
| merger_agreement_specialist | 28.00 |
| insurance_claims_specialist | 14.51 |
| judge | 13.75 |
| contracts_specialist | 8.00 |
| correspondence_specialist | 8.00 |
| corporate_records_specialist | 2.00 |
| reviewer | 1.25 |

Unscorable archives (no loss charged, no gold): corporate_record 9, correspondence 11
