"""Phase 5 part 2: the generated merger tables (subclass fields, MAUD groups, near-universal questions).

Plan: docs/design/plans/2026-11-27-phase5-merger-maud.md (Task 2).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mailroom_sandbox import merger_tables

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location("build_merger_tables", ROOT / "scripts" / "build_merger_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _questions():
    merger_tables._ensure_dojo()
    from llm_dojo_scoring.schemas.maud_schema import maud_questions

    return [q.name for q in maud_questions()]


def test_cash_drops_the_exchange_ratio_and_stock_drops_the_cash_amount():
    assert merger_tables.dropped_fields("all_cash") == {"exchange_ratio"}
    assert merger_tables.dropped_fields("all_stock") == {"per_share_cash_amount"}
    for sub in ("mixed_cash_stock", "mixed_cash_stock_election", "other", "unknown", ""):
        assert merger_tables.dropped_fields(sub) == frozenset()


def test_every_question_has_exactly_one_owner_for_every_group_count():
    names = _questions()
    assert len(names) == 22
    for n in (1, 2, 3):
        groups = merger_tables.group_questions(n)
        assert set(groups) == {str(i) for i in range(1, n + 1)}
        owned = [q for qs in groups.values() for q in qs] + list(merger_tables.load()["main_owned"])
        assert sorted(owned) == sorted(names)
        assert all(merger_tables.owner(q, n) in {"main", *groups} for q in names)


def test_the_main_read_owns_general_knowledge_mae_and_remedies():
    assert set(merger_tables.load()["main_owned"]) == {"Type of Consideration", "Knowledge Definition",
                                                       "MAE Definition", "Specific Performance"}
    assert merger_tables.owner("MAE Definition", 3) == "main"
    assert merger_tables.owner("No-Shop", 3) == "1"
    assert merger_tables.owner("FTR Triggers", 3) == "2"
    assert merger_tables.owner("Ordinary course covenant", 3) == "3"
    assert merger_tables.owner("Ordinary course covenant", 1) == "1"


def test_the_near_universal_list_is_built_from_calibration_mergers_only():
    calibration = [("DOC-c%d" % i, {"MAE Definition": {"answer": "x"}, "No-Shop": {"answer": "y"} if i < 9 else {}})
                   for i in range(10)]
    leaky = [("DOC-dev", {"Breach of No Shop": {"answer": "z"}}), ("DOC-held", {"Breach of No Shop": {"answer": "z"}})]
    sets = {**{doc: "calibration" for doc, _ in calibration}, "DOC-dev": "dev", "DOC-held": "heldout"}
    block = merger_tables.near_universal_from(calibration + leaky, sets)
    assert block["calibration_n"] == 10
    assert block["questions"] == ["MAE Definition", "No-Shop"]   # 100% and 90%
    assert "Breach of No Shop" not in block["counts"]


def test_near_universal_matches_the_spec_on_todays_labels():
    near = merger_tables.near_universal()
    assert len(near) == 11 and {"MAE Definition", "No-Shop", "Superior Offer Definition"} <= near
    assert merger_tables.load()["near_universal"]["calibration_n"] == 34


def test_the_committed_tables_are_fresh():
    assert _builder().main(["--check"]) == 0


def test_required_entities_add_the_subclass_amount():
    base = ("document_name", "parties", "acquirer", "target", "governing_law", "outside_date")
    assert merger_tables.required_entities("all_cash") == (*base, "per_share_cash_amount")
    assert merger_tables.required_entities("all_stock") == (*base, "exchange_ratio")
    assert merger_tables.required_entities("mixed_cash_stock")[-2:] == ("per_share_cash_amount", "exchange_ratio")


def test_entity_sections_cover_every_required_entity():
    sections = merger_tables.load()["entity_sections"]
    assert set(sections) >= set(merger_tables.required_entities("mixed_cash_stock"))


def test_the_tables_file_has_its_schema_id_and_a_sha():
    data = json.loads(merger_tables.TABLES_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == "mailroom.merger_tables/v1"
    assert len(merger_tables.sha256()) == 64


def test_a_merger_spec_locks_the_tables_sha():
    from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, spec_core

    def spec(**job):
        return RunSpec(run_id="r-mt", task="pipeline", dataset=DatasetSpec(local_path="file:///x.jsonl"),
                       engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})

    assert "merger_tables_sha256" not in spec_core(spec())["job"]
    assert spec_core(spec(merger={"subclass_fields": True}))["job"]["merger_tables_sha256"] == merger_tables.sha256()


@pytest.mark.parametrize("groups", [0, 4])
def test_an_unknown_group_count_is_refused(groups):
    with pytest.raises(ValueError):
        merger_tables.group_questions(groups)
