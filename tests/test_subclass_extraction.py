"""job.subclass_schemas (phase 3, X1): the predicted subclass picks the extraction schema."""

from __future__ import annotations

import copy

import pytest

from mailroom_sandbox import runtime
from mailroom_sandbox import subclass_extraction as sx
from mailroom_sandbox import subclass_fields as sf


@pytest.fixture(scope="module")
def schemas():
    runtime.activate(load_env_file=False)
    from langchain_agents import specialist_agents as sa

    return sa.SPECIALIST_SCHEMAS


@pytest.fixture(scope="module")
def lists():
    return sf.load_field_lists()


def _choose(schemas, lists, cls, sub, confidence=0.99, *, low=0.5, guide=False):
    return sx.choose_schema(cls, sub, confidence, schemas[cls], lists, low=low, guide=guide)


def test_a_listed_subclass_gets_its_narrowed_schema(schemas, lists):
    base = schemas["corporate_record"]
    before = copy.deepcopy(base)
    schema, reason = _choose(schemas, lists, "corporate_record", "subsidiary_list")
    assert reason == "subclass"
    assert "filing_number" not in schema["properties"]
    assert "filing_number" not in schema["required"]
    assert base == before and "filing_number" in base["properties"]


def test_each_listed_subclass_schema_matches_the_committed_list(schemas, lists):
    for cls, subs in lists["classes"].items():
        base = set(schemas[cls]["properties"])
        for sub, entry in subs.items():
            if sub in sx.FALLBACK_SUBCLASSES:
                continue
            schema, reason = _choose(schemas, lists, cls, sub)
            assert reason == "subclass", (cls, sub)
            assert set(schema["properties"]) == (base - set(entry["drop"])) | set(entry["add"]), (cls, sub)


@pytest.mark.parametrize("sub", [None, "", "unknown", "other", "not_a_subclass"])
def test_an_unknown_or_other_subclass_gets_the_class_schema(schemas, lists, sub):
    schema, reason = _choose(schemas, lists, "corporate_record", sub)
    assert schema is schemas["corporate_record"]
    assert reason == "fallback:unknown"


@pytest.mark.parametrize(
    ("confidence", "reason"),
    [(0.59, "fallback:low_confidence"), (None, "fallback:low_confidence"), (0.6, "subclass")],
)
def test_a_low_or_missing_confidence_falls_back(schemas, lists, confidence, reason):
    schema, got = _choose(schemas, lists, "merger_agreement", "all_cash", confidence, low=0.6)
    assert got == reason
    assert (schema is schemas["merger_agreement"]) == (reason != "subclass")


def test_an_added_field_is_requested(schemas, lists):
    synthetic = copy.deepcopy(lists)
    synthetic["classes"]["corporate_record"]["bylaws"]["add"] = {"certifying_officer": {"type": "name"}}
    schema, _ = _choose(schemas, synthetic, "corporate_record", "bylaws")
    assert schema["properties"]["certifying_officer"] == {"type": ["string", "null"]}
    assert "certifying_officer" in schema["required"]
    list_lists = copy.deepcopy(lists)
    list_lists["classes"]["corporate_record"]["bylaws"]["add"] = {"amendments": {"type": "date_list"}}
    schema, _ = _choose(schemas, list_lists, "corporate_record", "bylaws")
    assert schema["properties"]["amendments"] == {"type": ["array", "null"], "items": {"type": "string"}}


def test_the_curated_schema_guide_text_wins_over_the_registry_guide(schemas, lists):
    from mailroom_sandbox.schema_guide import GUIDE_DESCRIPTIONS

    curated = set(GUIDE_DESCRIPTIONS["contract"])
    entry = lists["classes"]["contract"]["license"]
    overlap = curated & set(entry["guide"])
    assert overlap
    guided, _ = _choose(schemas, lists, "contract", "license", guide=True)
    for field in overlap:
        assert guided["properties"][field].get("description") == schemas["contract"]["properties"][field].get(
            "description"), field


def test_guide_text_replaces_descriptions_only_with_schema_guide(schemas, lists):
    from mailroom_sandbox.schema_guide import GUIDE_DESCRIPTIONS

    # Today every registry guide entry names a curated field (the curated text wins), so the
    # registry text is pinned on a kept field schema_guide does not describe.
    lists = copy.deepcopy(lists)
    entry = lists["classes"]["corporate_record"]["bylaws"]
    curated = set(GUIDE_DESCRIPTIONS.get("corporate_record") or ())
    field = sorted(set(schemas["corporate_record"]["properties"]) - curated - set(entry["drop"])
                   - {"confidence", "reasoning"})[0]
    text = "Registry guide text for this subclass."
    entry["guide"][field] = text
    plain, _ = _choose(schemas, lists, "corporate_record", "bylaws", guide=False)
    guided, _ = _choose(schemas, lists, "corporate_record", "bylaws", guide=True)
    assert plain["properties"][field].get("description") == schemas["corporate_record"]["properties"][field].get(
        "description"
    )
    assert guided["properties"][field]["description"] == text


def test_low_band_reads_the_class_threshold():
    runtime.activate(load_env_file=False)
    from pipeline.config import get_confidence_thresholds

    assert sx.low_band("merger_agreement") == get_confidence_thresholds("merger_agreement").get("low")


# --- Task 3: the switch, the lock and HF-023 -------------------------------------------------

from pydantic import ValidationError  # noqa: E402

from mailroom_sandbox import vendor_hotfixes as vh  # noqa: E402
from mailroom_sandbox.job.spec import DatasetSpec, RunSpec, spec_core, spec_hash  # noqa: E402

_EXTRACTORS = {
    "contract": ("_extract_contracts", "license"),
    "merger_agreement": ("_extract_merger_agreement", "all_cash"),
    "corporate_record": ("_extract_corporate_records", "subsidiary_list"),
    "correspondence": ("_extract_correspondence", "email"),
    "insurance_claim": ("_extract_insurance_claims", "auto"),
}


def _spec(task="pipeline", **job):
    return RunSpec(run_id="r-sub", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job={"mock": True, **job})


@pytest.fixture
def switch_off():
    sx.deactivate()
    yield
    sx.deactivate()


def test_subclass_schemas_is_on_by_default_for_pipeline_runs():
    assert _spec().job.subclass_schemas is True
    on = spec_core(_spec(), source_sha256="0" * 64)["job"]
    assert on["subclass_schemas"] is True and on["subclass_fields_sha256"] == sf.field_lists_sha256()
    assert spec_hash(_spec()) == spec_hash(_spec(subclass_schemas=True))


def test_other_tasks_resolve_it_off_and_unhashed():
    spec = _spec(task="correspondence_specialist")
    assert spec.job.subclass_schemas is None  # unset, so a dumped spec re-validates for any task
    assert not any(key.startswith("subclass_") for key in spec_core(spec, source_sha256="0" * 64)["job"])


def test_a_dumped_spec_of_another_task_revalidates_as_a_pipeline_run():
    # sandbox experiment create dumps a spec and re-validates it with task: pipeline.
    data = _spec(task="correspondence_specialist").model_dump(mode="json")
    data["task"] = "pipeline"
    assert RunSpec.model_validate(data).job.subclass_schemas is True


def test_an_explicit_false_is_refused_for_pipeline_runs():
    with pytest.raises(ValidationError, match="always"):
        _spec(subclass_schemas=False)


def test_subclass_schemas_requires_a_pipeline_task():
    with pytest.raises(ValidationError, match="subclass_schemas"):
        _spec(task="correspondence_specialist", subclass_schemas=True)


def test_the_lock_changes_when_the_field_list_changes(tmp_path, monkeypatch):
    before = spec_hash(_spec())
    changed = sf.load_field_lists()
    changed["classes"]["contract"]["license"]["drop"] = ["territory"]
    path = tmp_path / "fields.json"
    path.write_text(sf.render(changed), encoding="utf-8")
    monkeypatch.setattr(sf, "FIELDS_PATH", path)
    assert spec_hash(_spec()) != before


def test_a_field_list_changed_after_the_lock_refuses_to_activate(switch_off):
    with pytest.raises(RuntimeError, match="field list"):
        sx.activate(sf.load_field_lists(), sha256="0" * 64, guide=False)
    assert not sx.active()


def test_the_lock_activates_subclass_schemas(monkeypatch, switch_off):
    monkeypatch.setenv("VLLM_BASE_URL", "https://example.invalid/v1")
    lock = {"profile": "modal-vllm", "job": {"subclass_schemas": True},
            "spec_core": {"job": {"subclass_fields_sha256": sf.field_lists_sha256()}}}
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert sx.active()
    with runtime.locked_runtime({"profile": "modal-vllm", "job": {}}, {}):  # a lock from before phase 3
        runtime.activate("modal-vllm", load_env_file=False)
    assert not sx.active()


@pytest.fixture
def captured(monkeypatch, schemas):
    """Apply HF-023 and record the json_schema every specialist structured call is sent."""
    from agents import base as agents_base
    from langchain_agents import base_agent as lc_base

    assert vh.apply_hotfixes()["HF-023"] == "applied"
    calls: list[tuple[str, dict]] = []

    def stub(self, user_message, json_schema, *args, **kwargs):
        calls.append((type(self).__name__, json_schema))
        return {"confidence": 0.9}

    monkeypatch.setattr(agents_base.BaseAgent, "_call_structured", stub)
    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", stub)
    return calls


def _state(cls, sub, confidence=0.99):
    key = "contract_subtype" if cls == "contract" else "doc_subclass"
    return {"doc_id": "d1", "doc_type": cls, key: sub, "classification_confidence": confidence}


def _extract(cls, sub, text="A short document body for extraction.", confidence=0.99):
    import graph.build_graph as bg

    name, _ = _EXTRACTORS[cls]
    handoff = bg._build_handoff_context(_state(cls, sub, confidence))
    return getattr(bg, name)(text, [], handoff)


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_an_extraction_requests_the_subclass_schema(cls, captured, schemas, lists, switch_off):
    sub = _EXTRACTORS[cls][1]
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract(cls, sub)
    assert captured, cls
    expected, reason = sx.choose_schema(cls, sub, 0.99, schemas[cls], lists, low=sx.low_band(cls), guide=False)
    assert reason == "subclass"
    for _, sent in captured:
        assert sent is not schemas[cls]
        assert sent == expected
        assert not set(lists["classes"][cls][sub]["drop"]) & set(sent["properties"])


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_off_sends_the_class_schema_unchanged(cls, captured, schemas, switch_off):
    _extract(cls, _EXTRACTORS[cls][1])
    assert captured and all(sent is schemas[cls] for _, sent in captured)


def test_a_low_confidence_extraction_sends_the_class_schema(captured, schemas, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("merger_agreement", "all_cash", confidence=0.01)
    assert captured and all(sent is schemas["merger_agreement"] for _, sent in captured)


def test_a_reply_without_confidence_is_scored_on_the_narrowed_schema(monkeypatch, schemas, lists, switch_off):
    """Review Important 1: the evidence-confidence fallback counts only the requested fields."""
    from agents import base as agents_base
    from langchain_agents import base_agent as lc_base

    assert vh.apply_hotfixes()["HF-023"] == "applied"

    def filled(self, user_message, json_schema, *args, **kwargs):
        return {f: "x" for f in json_schema["properties"] if f not in ("confidence", "reasoning")}

    monkeypatch.setattr(agents_base.BaseAgent, "_call_structured", filled)
    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", filled)
    off = _extract("merger_agreement", "all_cash")
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    on = _extract("merger_agreement", "all_cash")
    assert on.get("confidence") == off.get("confidence")


def test_every_chunk_gets_the_narrowed_schema(captured, schemas, lists, switch_off, monkeypatch):
    import graph.build_graph as bg

    monkeypatch.setattr(bg, "_chunk_config", lambda: {"enabled": True, "chunk_chars": 1_000, "overlap_chars": 100})
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    result = _extract("merger_agreement", "all_cash", text="Section text. " * 400)
    assert len(captured) > 1
    assert all("intent" not in sent["properties"] and sent is not schemas["merger_agreement"] for _, sent in captured)
    assert isinstance(result, dict)


def test_the_narrowed_schema_ends_with_its_extraction(captured, schemas, lists, switch_off):
    from agents.corporate_records_specialist import CorporateRecordsSpecialist

    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("corporate_record", "subsidiary_list")
    captured.clear()
    agent = CorporateRecordsSpecialist()  # a later caller (the judge, the next document) builds its own agent
    agent._call_structured("again", json_schema=schemas["corporate_record"])
    assert captured[0][1] is schemas["corporate_record"]


def test_a_corporate_extract_another_hotfix_composes_is_left_to_it(captured, schemas, lists, switch_off, monkeypatch):
    """A hotfix on CorporateRecordsSpecialist.extract (PR #425's corporate composer) owns its schema."""
    import functools

    from agents.corporate_records_specialist import CorporateRecordsSpecialist

    original = CorporateRecordsSpecialist.extract

    @functools.wraps(original)
    def composed(self, *args, **kwargs):
        return original(self, *args, **kwargs)

    composed._sandbox_hotfix = "HF-020"
    monkeypatch.setattr(CorporateRecordsSpecialist, "extract", composed)
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("corporate_record", "subsidiary_list")
    assert captured and all(sent is schemas["corporate_record"] for _, sent in captured)
    captured.clear()
    _extract("merger_agreement", "all_cash")  # the other classes still get their subclass schema
    assert captured and all("intent" not in sent["properties"] for _, sent in captured)


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), "high", "", object()])
def test_a_nan_or_non_numeric_confidence_falls_back(schemas, lists, confidence):
    schema, reason = _choose(schemas, lists, "merger_agreement", "all_cash", confidence)
    assert schema is schemas["merger_agreement"] and reason == "fallback:low_confidence"


def test_record_choice_fails_open_on_a_non_numeric_confidence(schemas, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    sx.record_choice(_state("merger_agreement", "all_cash", confidence="high"))  # no raise
    assert sx._PENDING.get() is None


@pytest.mark.parametrize("kind", ["list", "entity_list", "entity_list:name", "entity_list:free_text",
                                  "entity_list:cms_doc_ref"])
def test_an_added_registry_list_field_is_an_array(kind):
    assert sx._added_property({"type": kind})["type"] == ["array", "null"]


def test_a_reused_job_spec_is_not_changed_by_a_pipeline_run_spec():
    from mailroom_sandbox.job.spec import JobSpec

    job = JobSpec(mock=True)
    assert _spec_with(job, "pipeline").job.subclass_schemas is True
    assert job.subclass_schemas is None
    assert _spec_with(job, "correspondence_specialist").job.subclass_schemas is None


def _spec_with(job, task):
    return RunSpec(run_id="r-sub", task=task, dataset=DatasetSpec(local_path="file:///x.jsonl"),
                   engine={"kind": "vllm-local", "modal": None}, job=job)


def test_an_unlocked_activation_uses_the_committed_field_lists(switch_off):
    runtime.activate("modal-vllm", load_env_file=False)  # an ad-hoc pipeline eval holds no lock
    assert sx.active()


def test_activation_hashes_the_bytes_it_parses(tmp_path, monkeypatch, lists, switch_off):
    import hashlib
    import json

    data = (json.dumps(lists, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = tmp_path / "fields.json"
    path.write_bytes(data)
    monkeypatch.setattr(sf, "FIELDS_PATH", path)
    monkeypatch.setattr(sf, "load_field_lists", lambda *a, **k: pytest.fail("parsed separately"))
    monkeypatch.setattr(sf, "field_lists_sha256", lambda *a, **k: pytest.fail("hashed separately"))
    sx.activate(sha256=hashlib.sha256(data).hexdigest(), guide=False)
    assert sx._ACTIVE["lists"] == lists


# --- the judge and the arbiter see the fields the extraction was asked for -------------------

@pytest.fixture
def review_calls(monkeypatch):
    """Apply HF-023/HF-024; record every structured call's agent and user message."""
    from agents import base as agents_base
    from langchain_agents import base_agent as lc_base

    import graph.build_graph as bg

    status = vh.apply_hotfixes()
    assert status["HF-023"] == status["HF-024"] == "applied"
    calls: list[tuple[str, str]] = []

    def stub(self, user_message, *args, **kwargs):
        calls.append((type(self).__name__, str(user_message)))
        return {"confidence": 0.9, "completeness": 0.6, "completeness_label": "partial", "reasoning": "gaps",
                "extraction_correctness": 1.0, "extraction_correctness_label": "accurate",
                "decision": "human_review", "fields_to_fix": [], "handoff_summary": ""}

    monkeypatch.setattr(agents_base.BaseAgent, "_call_structured", stub)
    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", stub)
    monkeypatch.setattr(bg, "judge_should_run", lambda state: True)
    return calls


def _review(cls, sub, confidence=0.99):
    import graph.build_graph as bg
    from mailroom_sandbox.job import call_guard

    state = {**_state(cls, sub, confidence), "doc_text": "A short document body.",
             "extracted_data": {"document_name": "Plan of Merger", "intent": None, "keywords": None},
             "judge_verdict": "partial", "judge_findings": ["gaps"], "judge_score": 0.6}
    with call_guard.document() as scope:
        _extract(cls, sub, confidence=confidence)
        bg.judge_verify_node(state)
        bg.arbiter_node(state)
        cleaned = bg._clean_fields_for_judge(state["extracted_data"])
    return scope, cleaned


def _judge_and_arbiter(calls):
    return [m for agent, m in calls if agent in ("CompletenessJudge", "ArbiterAgent")]


def test_the_judge_and_arbiter_see_only_the_requested_fields(review_calls, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    scope, cleaned = _review("merger_agreement", "all_cash")
    messages = _judge_and_arbiter(review_calls)
    assert len(messages) >= 2
    assert all("intent" not in m and "keywords" not in m for m in messages)
    assert "document_name" in messages[0]
    assert cleaned == {"document_name": "Plan of Merger"}
    assert set(scope["subclass_schema"]["drop"]) == {"intent", "keywords", "subject_matter"}


def test_off_the_judge_lists_every_class_field(review_calls, switch_off):
    _, cleaned = _review("merger_agreement", "all_cash")
    judge = [m for agent, m in review_calls if agent == "CompletenessJudge"]
    assert any("  - intent:" in m for m in judge)
    assert "intent" in cleaned


def test_a_fallback_extraction_shows_the_judge_the_class_fields(review_calls, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    scope, cleaned = _review("merger_agreement", "all_cash", confidence=0.01)
    assert not scope.get("subclass_schema")
    assert "intent" in cleaned


# --- Task 4: scoring guards -------------------------------------------------------------------

_KEPT = {"merger_agreement": "document_name", "corporate_record": "entity_name", "contract": "document_name",
         "correspondence": "sender", "insurance_claim": "claim_number"}


def _score(cls, sub, predicted, expected):
    from mailroom_sandbox.eval.scoring import score_extraction_row

    out = score_extraction_row(cls, dict(predicted), dict(expected), doc_subclass=sub, field_scores=True)
    return out["overall_extraction_score"], out.get("field_scores")


def _drops(lists):
    return [(cls, sub, f) for cls, subs in lists["classes"].items() for sub, e in subs.items() for f in e["drop"]]


def test_a_dropped_field_never_changes_a_score(schemas, lists):
    runtime.activate(load_env_file=False)
    drops = _drops(lists)
    assert drops
    for cls, sub, field in drops:
        kept = _KEPT[cls]
        listy = "array" in str(schemas[cls]["properties"].get(field, {}).get("type"))
        blank = [] if listy else ""
        # The truth a dropped field carries: blank, and marked not applicable where the Hub says so.
        expected = {kept: "Acme Holdings Inc.", field: blank}
        if cls in ("corporate_record", "merger_agreement"):
            expected["gt_presence"] = {field: "not_applicable"}
        asked = _score(cls, sub, {kept: "Acme Holdings Inc.", field: None}, expected)
        dropped = _score(cls, sub, {kept: "Acme Holdings Inc."}, expected)
        assert dropped == asked, (cls, sub, field)
        stated = _score(cls, sub, {kept: "Acme Holdings Inc.", field: ["a stated value"] if listy else "a stated value"},
                        expected)
        assert dropped[0] >= stated[0], (cls, sub, field)  # dropping can only remove a false positive


def test_every_added_field_is_scoreable(lists):
    from mailroom_sandbox.eval.extraction_scope import applicable_expected_fields

    runtime.activate(load_env_file=False)
    added = [(cls, f) for cls, subs in lists["classes"].items() for e in subs.values() for f in e["add"]]
    added.append(("corporate_record", "certifying_officer"))  # the synthetic extension of Task 1
    for cls, field in added:
        assert field in applicable_expected_fields(cls, {field: "x"}), (cls, field)


# --- Promoted prompts and subclass schemas (docs/design/plans/2026-11-27-subclass-field-note.md) --

#: Sorter tokens with no field list yet, so they fall back to the class schema (FNOL forms, unlabeled).
_UNLISTED_FALLBACK = {"insurance_claim": {"health", "liability", "life", "workers_comp"}}


def _listed_pairs():
    return [(cls, sub) for cls, subs in sorted(sf.load_field_lists()["classes"].items())
            for sub in sorted(subs) if sub not in sx.FALLBACK_SUBCLASSES]


@pytest.mark.parametrize(("cls", "sub"), _listed_pairs())
def test_every_listed_subclass_sends_its_own_schema(cls, sub, captured, schemas, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract(cls, sub)
    expected, reason = sx.choose_schema(cls, sub, 0.99, schemas[cls], lists, low=sx.low_band(cls), guide=False)
    assert reason == "subclass" and captured
    for _, sent in captured:
        assert sent == expected
        assert not set(lists["classes"][cls][sub]["drop"]) & set(sent["properties"])
        assert set(lists["classes"][cls][sub]["add"]) <= set(sent["properties"])


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_every_sorter_subclass_token_has_a_field_list_or_a_documented_fallback(cls, schemas, lists):
    from langchain_agents import doc_inventories as di

    listed = set(lists["classes"][cls])
    tokens = set(di.valid_sorter_subclasses(cls))
    unlisted = tokens - listed - sx.FALLBACK_SUBCLASSES
    assert unlisted == _UNLISTED_FALLBACK.get(cls, set())
    assert listed - sx.FALLBACK_SUBCLASSES <= tokens  # no field list the sorter can never reach


@pytest.fixture
def prompts_sent(monkeypatch, schemas):
    """Like ``captured``, but records the system prompt each specialist structured call uses.

    Each entry is ``(agent, json_schema, system)``, where ``system`` is what the vendored call
    resolves when the caller passes none: ``augmented_system_prompt()`` (LangChain) or
    ``system_prompt()`` (legacy agents). The caller-passed ``system_prompt`` must stay unset, because
    the floor-read observer measures that argument as request text.
    """
    from agents import base as agents_base
    from langchain_agents import base_agent as lc_base

    assert vh.apply_hotfixes()["HF-023"] == "applied"
    calls: list[tuple[str, dict, str | None]] = []

    def stub(self, user_message, json_schema, *args, **kwargs):
        assert kwargs.get("system_prompt") is None and len(args) == 0, "the note must not ride in the call's arguments"
        augmented = getattr(self, "augmented_system_prompt", None)
        system = augmented() if isinstance(self, lc_base.BaseAgent) else self.system_prompt()
        calls.append((type(self).__name__, json_schema, system))
        return {"confidence": 0.9}

    monkeypatch.setattr(agents_base.BaseAgent, "_call_structured", stub)
    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", stub)
    return calls


def test_the_note_names_every_dropped_and_added_field(schemas, lists):
    for cls, sub in _listed_pairs():
        entry, base = lists["classes"][cls][sub], set(schemas[cls]["properties"])
        dropped = set(entry["drop"]) & base  # a derived field outside the request (cms_source_table) changes nothing
        added = set(entry["add"]) - base
        schema, _ = _choose(schemas, lists, cls, sub)
        note = sx.field_note(cls, sub, schemas[cls], schema)
        if not (dropped or added):
            assert note is None, (cls, sub)
            continue
        assert note and f"{cls} / {sub}" in note, (cls, sub)
        for name in dropped:
            assert f"`{name}`" in note.split("Not requested")[1].split("\n")[0], (cls, sub, name)
        for name in added:
            assert f"`{name}`" in note, (cls, sub, name)
        if dropped:
            assert "never move it into another field" in note


def test_no_note_for_a_fallback_or_an_unchanged_subclass(schemas, lists):
    base = schemas["merger_agreement"]
    assert sx.field_note("merger_agreement", "other", base, base) is None
    assert sx.field_note("merger_agreement", "all_cash", base, copy.deepcopy(base)) is None


def _promoted_stems():
    import yaml

    from mailroom_sandbox.prompt_lineage import with_lineage_defaults

    spec = yaml.safe_load(open("config/runs/production/slice-0250.yaml", encoding="utf-8"))
    agents = with_lineage_defaults(spec.get("prompt") or {}, "pipeline")["agents"]
    return {agent: row["file"] for agent, row in agents.items() if row.get("source") == "local"}


_SPECIALIST_AGENT = {"contract": "contracts_specialist", "corporate_record": "corporate_records_specialist",
                     "correspondence": "correspondence_specialist",
                     "insurance_claim": "insurance_claims_specialist",
                     "merger_agreement": "merger_agreement_specialist"}


def test_every_promoted_prompt_field_a_subclass_drops_is_named_in_its_note(schemas, lists):
    import re

    stems = _promoted_stems()
    assert set(_SPECIALIST_AGENT.values()) <= set(stems), stems
    for cls, sub in _listed_pairs():
        text = open(f"config/prompts/{stems[_SPECIALIST_AGENT[cls]]}.txt", encoding="utf-8").read()
        named = {f for f in lists["classes"][cls][sub]["drop"]
                 if re.search(rf"(?<![A-Za-z0-9_]){re.escape(f)}(?![A-Za-z0-9_])", text)}
        if not named:
            continue
        schema, _ = _choose(schemas, lists, cls, sub)
        note = sx.field_note(cls, sub, schemas[cls], schema) or ""
        assert all(f"`{f}`" in note for f in named), (cls, sub, named)


def test_the_promoted_prompt_stays_the_head_and_the_note_follows(prompts_sent, schemas, lists, switch_off,
                                                                 monkeypatch):
    import graph.build_graph as bg

    promoted = open(f"config/prompts/{_promoted_stems()['merger_agreement_specialist']}.txt",
                    encoding="utf-8").read()
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False, note=True)
    handoff = bg._build_handoff_context(_state("merger_agreement", "all_cash"))

    def head(self, *args, **kwargs):
        return promoted

    from langchain_agents import base_agent as lc_base

    monkeypatch.setattr(lc_base.BaseAgent, "augmented_system_prompt", head)
    bg._extract_merger_agreement("A short merger agreement body.", [], handoff)
    assert prompts_sent
    schema, _ = _choose(schemas, lists, "merger_agreement", "all_cash")
    note = sx.field_note("merger_agreement", "all_cash", schemas["merger_agreement"], schema)
    for _, sent, system in prompts_sent:
        assert sent == schema
        assert system == f"{promoted}\n\n{note}"
        for name in ("subject_matter", "keywords", "intent"):
            assert f"`{name}`" in note


def test_off_sends_no_note(prompts_sent, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False)
    _extract("merger_agreement", "all_cash")
    assert prompts_sent and all("SUBCLASS FIELDS" not in system for _, _, system in prompts_sent)


def test_a_fallback_extraction_gets_no_note(prompts_sent, lists, switch_off):
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False, note=True)
    _extract("insurance_claim", "health")
    _extract("merger_agreement", "all_cash", confidence=0.01)
    assert prompts_sent and all("SUBCLASS FIELDS" not in system for _, _, system in prompts_sent)


def test_the_note_stays_out_of_the_floor_read_request_text(monkeypatch, lists, switch_off):
    """The read-range observer measures the caller-passed system_prompt; the note must not appear there."""
    from langchain_agents import base_agent as lc_base

    from mailroom_sandbox.job import read_ranges as rr

    assert vh.apply_hotfixes()["HF-023"] == "applied"
    texts: list[str] = []

    def stub(self, user_message, json_schema, *args, **kwargs):
        texts.append(rr._request_text(self, {"user_message": user_message, **kwargs})[1])
        return {"confidence": 0.9}

    monkeypatch.setattr(lc_base.BaseAgent, "_call_structured", stub)
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False, note=True)
    _extract("merger_agreement", "all_cash")
    assert texts and all("SUBCLASS FIELDS" not in text for text in texts)


def test_the_note_is_scoped_to_one_specialist_instance(prompts_sent, lists, switch_off):
    from langchain_agents import base_agent as lc_base

    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False, note=True)
    _extract("merger_agreement", "all_cash")
    assert "SUBCLASS FIELDS" in prompts_sent[-1][2]
    assert "augmented_system_prompt" not in vars(lc_base.BaseAgent) or not getattr(
        lc_base.BaseAgent.augmented_system_prompt, "__wrapped__", None)
    _extract("merger_agreement", "other")  # the next document, a fallback: the class prompt, no note
    assert "SUBCLASS FIELDS" not in prompts_sent[-1][2]


@pytest.mark.parametrize("cls", sorted(_EXTRACTORS))
def test_every_specialist_family_gets_the_note_on_its_own_default_prompt(cls, prompts_sent, schemas, lists,
                                                                         switch_off):
    sub = _EXTRACTORS[cls][1]
    sx.activate(lists, sha256=sf.field_lists_sha256(), guide=False, note=True)
    _extract(cls, sub)
    schema, _ = _choose(schemas, lists, cls, sub)
    note = sx.field_note(cls, sub, schemas[cls], schema)
    for _, _, system in prompts_sent:
        if note is None:
            assert "SUBCLASS FIELDS" not in system
        else:
            assert system.endswith(f"\n\n{note}") and len(system) > len(note) + 2


def test_the_note_flag_is_hashed_only_when_set():
    assert "subclass_field_note" not in spec_core(_spec())["job"]
    assert spec_core(_spec(subclass_field_note=True))["job"]["subclass_field_note"] is True
    assert spec_hash(_spec()) != spec_hash(_spec(subclass_field_note=True))


def test_the_note_requires_a_pipeline_task():
    with pytest.raises(ValidationError, match="subclass_field_note"):
        _spec(task="sorter", subclass_field_note=True)


def test_the_lock_activates_the_note(monkeypatch, switch_off):
    sha = sf.field_lists_sha256()
    lock = {"profile": "modal-vllm", "task": "pipeline", "job": {"subclass_schemas": True, "subclass_field_note": True},
            "spec_core": {"job": {"subclass_fields_sha256": sha}}}
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert sx.active() and sx.note_active()
    lock["job"].pop("subclass_field_note")
    with runtime.locked_runtime(lock, {}):
        runtime.activate("modal-vllm", load_env_file=False)
    assert sx.active() and not sx.note_active()


def test_the_note_ab_arm_differs_from_its_baseline_only_in_the_note():
    import yaml

    def core(name):
        spec = RunSpec.model_validate(yaml.safe_load(open(f"config/runs/{name}.yaml", encoding="utf-8")))
        out = spec_core(spec)
        out.pop("trace", None)  # tags only
        return out

    on, off = core("sx-note-s1-on"), core("p4-s1-verify-gov-off")
    assert on["job"].pop("subclass_field_note") is True
    assert "subclass_field_note" not in off["job"]
    assert on == off
