# Weakness table: ar-mailroom-v1-r00-baseline

25 documents, mean utility -0.101. Lost utility is `1 - utility` per document, charged to one node (rules: `autoresearch/diagnose.py`).

| class | node | lost | docs | share | actionable | causes |
|:---|:---|---:|---:|---:|:---|:---|
| merger_agreement | merger_agreement_specialist | 8.00 | 4 | 39% | yes | extraction:maud_wrong x4 |
| contract | contracts_specialist | 4.06 | 3 | 20% | yes | extraction:cuad_missed x2, extraction:partial x1 |
| contract | judge | 2.50 | 2 | 12% | yes | judge:partial_exhausted x2 |
| correspondence | correspondence_specialist | 2.00 | 1 | 10% | yes | extraction:wrong_value x1 |
| correspondence | judge | 1.25 | 1 | 6% | yes | judge:partial_exhausted x1 |
| insurance_claim | judge | 1.25 | 1 | 6% | yes | judge:judge_rejected x1 |
| merger_agreement | judge | 1.25 | 1 | 6% | yes | judge:judge_rejected x1 |
| insurance_claim | insurance_claims_specialist | 0.22 | 4 | 1% | yes | extraction:partial x4 |

## By node

| node | lost |
|:---|---:|
| merger_agreement_specialist | 8.00 |
| judge | 6.25 |
| contracts_specialist | 4.06 |
| correspondence_specialist | 2.00 |
| insurance_claims_specialist | 0.22 |

Unscorable archives (no loss charged, no gold): corporate_record 4, correspondence 3
