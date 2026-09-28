# Reports

Run reports, serving exports and the offline experiment log (JSONL + markdown written by `sandbox eval` / `sandbox matrix`).

## Reports hub

`dashboard/mailroom-reports.html` presents specialist, serving, hosted-API and ModernBERT results from this repo,
[eval-environment](https://github.com/LLM-Mailroom-Services/eval-environment) and
[mailroom-ml](https://github.com/LLM-Mailroom-Services/mailroom-ml). Every figure is read from a tracked file and
cross-checked; documented source defects are listed on its Data quality tab.

```bash
python reports/dashboard/build_hub.py sync      # re-pin eval-environment + mailroom-ml (sibling checkouts)
python reports/dashboard/build_hub.py           # rebuild the page
python reports/dashboard/build_hub.py --check   # fail if the page, data or snapshot is stale
```

| file | role |
| --- | --- |
| `dashboard/build_hub.py` | CLI: sync, build, check |
| `dashboard/hub_extract.py` | SAND-032, eval-environment and mailroom-ml extractors + cross-checks |
| `dashboard/legacy_runs.py` | 16–27 Sep specialist runs (pre-SAND-032) |
| `dashboard/external_snapshot.json` | pinned figures + provenance from the two sibling repos |
| `dashboard/hub.template.html` → `mailroom-reports.html` | page template → built page (`hub_data.json` is its data) |
