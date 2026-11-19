# G0 checkpoint digest: not passed

Written by `python scripts/check_g0.py --write-digest`; rerun it to refresh.

| gate | status | exit | missing evidence |
| --- | --- | --- | --- |
| R00 split audit | pass | 0 |  |
| R00 schemas registry | pass | 0 |  |
| R01 smoke deepseek-v4.1-flash-1017 | missing | — | ledger data/runtime/rb1-r01/served-deepseek-v4.1-flash-1017.jsonl (launch the smoke run) |
| R01 smoke glm-5.3-flashx-legal | missing | — | ledger data/runtime/rb1-r01/served-glm-5.3-flashx-legal.jsonl (launch the smoke run) |
| R01 smoke gpt-6-luna-decisions | missing | — | ledger data/runtime/rb1-r01/served-gpt-6-luna-decisions.jsonl (launch the smoke run) |
| R01 smoke jev-1.14 | missing | — | ledger data/runtime/rb1-r01/served-jev-1.14.jsonl (launch the smoke run) |
| R01 smoke qwen3.5-9b | missing | — | ledger data/runtime/rb1-r01/served-qwen3.5-9b.jsonl (launch the smoke run) |
| R01 smoke qwen3.7-flash | missing | — | ledger data/runtime/rb1-r01/served-qwen3.7-flash.jsonl (launch the smoke run) |
| R02 scorer hand-check | fail | 3 |  |
| R03 gold audit sorter | missing | — | sheet data/labels/review/r03-sorter-audit.csv (v0 pass, then adjudication) |
| R03 gold audit correspondence | missing | — | sheet data/labels/review/r03-correspondence-audit.csv (v0 pass, then adjudication) |
| R03 gold audit insurance | missing | — | sheet data/labels/review/r03-insurance-audit.csv (v0 pass, then adjudication) |
| R03 gold audit corporate | missing | — | sheet data/labels/review/r03-corporate-audit.csv (v0 pass, then adjudication) |
| R03 gold audit contracts | missing | — | sheet data/labels/review/r03-contracts-audit.csv (v0 pass, then adjudication) |
| R03 gold audit merger | missing | — | sheet data/labels/review/r03-merger-audit.csv (v0 pass, then adjudication) |
