"""SHF-010 and dual provenance on the ``run_extract_eval`` headline (``docs/scoring-hotfixes.md``).

A mock extract run predicts the prepared (near-gold) truth. The row says which interim value that
truth replaced (``truth_overrides``), so the raw Dojo-pin side must score against the interim value
and the run must name SHF-010 and record ``raw_dojo`` and ``headline_basis``. Network-free.
"""
from __future__ import annotations

import json

from mailroom_sandbox import scoring_hotfixes as sh
from mailroom_sandbox.eval import experiment_log, runners

def _rows():
    fields = {"sender": "Jane Roe", "recipient": "Bo Chu",
              "gt_presence": json.dumps({"sender": "populated", "recipient": "populated"})}
    return [{"id": "DOC-1", "expected_doc_class": "correspondence", "doc_text": "From: Jane Roe\nTo: Bo Chu\nHi.",
             "expected_fields": json.dumps(fields),
             "truth_overrides": {"SHF-010": {"sender": {"interim": "J. Roe Interim"}}}}]

def test_extract_eval_names_shf010_and_records_the_raw_side(tmp_path, monkeypatch):
    log = tmp_path / "experiment_log.jsonl"
    monkeypatch.setenv("EXPERIMENT_LOG_PATH", str(log))
    monkeypatch.setattr(experiment_log, "jsonl_path", lambda: log)
    monkeypatch.setattr(experiment_log, "md_path", lambda: tmp_path / "experiment_log.md")
    scores = runners.run_extract_eval(mock=True, rows=_rows())["scores"]
    assert scores["n"] == 1
    assert scores["overall_extraction_score"] == 1.0
    assert scores["raw_dojo"]["overall_extraction_score"] < 1.0  # the interim truth near-gold replaced
    assert "SHF-010" in scores["scoring_hotfixes"]
    assert scores["scoring_hotfixes_changed"] == ["overall_extraction_score"]
    assert scores["headline_basis"] == sh.headline_basis()
