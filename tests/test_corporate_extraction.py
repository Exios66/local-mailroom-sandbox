from concurrent.futures import ThreadPoolExecutor
import re
from types import MethodType, SimpleNamespace

import pytest

from mailroom_sandbox import vendor_hotfixes
from mailroom_sandbox.corporate_extraction import (
    registry, registry_matches, request_schema, subclass_from_handoff, validate_response,
)
from mailroom_sandbox.eval.schema_adherence import assess_extraction_payload


def response(schema, extra=None):
    result = {}
    for key, spec in schema['properties'].items():
        types = spec.get('type')
        if key == 'confidence':
            result[key] = 0.5
        elif types == 'array' or isinstance(types, list) and 'array' in types:
            result[key] = []
        else:
            result[key] = None
    if extra:
        result.update(extra)
    return result


def test_runtime_activation_installs_distinct_corporate_and_main_hotfixes(monkeypatch, tmp_path):
    from mailroom_sandbox import runtime

    monkeypatch.setenv('MAILROOM_BASE_DIR', str(tmp_path))
    runtime.activate('ollama', load_env_file=False)
    from agents.arbiter import ArbiterAgent
    from agents.corporate_records_specialist import CorporateRecordsSpecialist as Native
    from agents.judge import CompletenessJudge
    from graph import routing
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist as LangChain
    fixes = vendor_hotfixes.HOTFIXES
    assert len({fix.id for fix in fixes}) == len(fixes)
    for method, fix_id in (
        (CompletenessJudge.judge_extraction_correctness, 'HF-013'),
        (ArbiterAgent.arbitrate, 'HF-015'),
        (Native.extract, 'HF-020'),
        (LangChain.extract, 'HF-021'),
        (LangChain.extract_chunked, 'HF-022'),
    ):
        assert getattr(method, '_sandbox_hotfix', None) == fix_id
    assert vendor_hotfixes.apply_hotfixes()['HF-014'] == 'applied'
    assert routing.after_arbiter is not None


def test_registry_schemas():
    assert registry_matches()
    assert len(registry.SUBCLASS_SCHEMAS) == 11
    for subtype in registry.SUBCLASS_SCHEMAS:
        actual = request_schema(subtype, {})
        expected = registry.corporate_record_json_schema(subtype)
        assert {k: v for k, v in actual.items() if k != 'title'} == {k: v for k, v in expected.items() if k != 'title'}
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,64}', actual['title'])
    with pytest.raises(ValueError):
        request_schema('unknown', {})


def test_native_actual_requests_concurrent_and_no_truth():
    from agents.corporate_records_specialist import CorporateRecordsSpecialist
    from graph.build_graph import _build_handoff_context
    assert vendor_hotfixes.apply_hotfixes()['HF-020'] == 'applied'
    def run(subtype):
        agent = object.__new__(CorporateRecordsSpecialist)
        agent._configured_max_input_chars = lambda: 5000
        received = {}
        def call(message, **kwargs):
            received.update(kwargs['json_schema'])
            return response(kwargs['json_schema'])
        agent._call_structured = call
        handoff = _build_handoff_context({'doc_type': 'corporate_record', 'doc_subclass': subtype,
                                          'expected_subclass': 'other'})
        result = agent.extract('text', handoff_context=handoff)
        assert result['confidence'] == 0.5
        return received
    with ThreadPoolExecutor(max_workers=2) as pool:
        schemas = list(pool.map(run, ['subsidiary_list', 'indenture']))
    for subtype, actual in zip(['subsidiary_list', 'indenture'], schemas):
        assert set(registry.corporate_record_json_schema(subtype)['properties']) <= set(actual['properties'])
        assert actual['title'].endswith(f'_{subtype}')
        assert set(actual['required']) == set(actual['properties'])
    assert schemas[0] != schemas[1]


def test_native_extension_and_reject_cross_subclass():
    from agents.corporate_records_specialist import CorporateRecordsSpecialist
    from mailroom_sandbox.eval.scoring import score_extraction_row
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent._configured_max_input_chars = lambda: 5000
    subtype = 'subsidiary_list'
    extension = next(iter(set(registry.corporate_record_json_schema(subtype)['properties']) - set(registry.CORE_FIELDS)))
    def call(message, **kwargs):
        schema = kwargs['json_schema']
        value = ['Example'] if schema['properties'][extension].get('type') == 'array' else 'Example'
        return response(schema, {extension: value})
    agent._call_structured = call
    handoff = 'Sorter classification: doc_type=corporate_record doc_subclass=subsidiary_list.'
    result = agent.extract('Example', handoff_context=handoff)
    assert result[extension]
    scored = score_extraction_row('corporate_record', result, {extension: result[extension]}, expected_subclass=subtype)
    assert scored['schema_valid']
    agent._call_structured = lambda message, **kwargs: response(kwargs['json_schema'], {'trustee': 'bad'})
    assert agent.extract('Example', handoff_context=handoff)['_parse_error']


def test_langchain_requests_single_and_chunked():
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent.handoff_context = 'Sorter classification: doc_type=corporate_record doc_subclass=indenture.'
    agent.truncate_input = lambda text: text
    agent._last_usage = None
    schemas = []
    def call(message, **kwargs):
        schema = kwargs['json_schema']
        schemas.append(schema)
        return response(schema)
    agent._call_structured = call
    assert not agent.extract('text').get('_parse_error')
    assert not agent.extract_chunked('first paragraph\n\nsecond paragraph', chunk_chars=16, overlap_chars=0).get('_parse_error')
    assert len(schemas) >= 3
    assert all(s['title'].endswith('_indenture') for s in schemas)


def test_extension_adherence_rejects_other_subclass():
    assert not assess_extraction_payload({'entity_name': 'Example', 'trustee': 'bad'}, 'corporate_record', 'subsidiary_list')['schema_valid']


def test_isolated_default_does_not_use_truth(monkeypatch):
    from mailroom_sandbox.eval.agents import pipeline_specialist_state
    from mailroom_sandbox import runtime
    monkeypatch.setattr(runtime, 'specialist_subclass_source', lambda: ('none', None))
    assert pipeline_specialist_state('corporate_records_specialist', {'expected_subclass': 'indenture'}) == {'doc_type': 'corporate_record'}


def test_graph_extract_node_uses_observed_subclass(monkeypatch):
    from agents.corporate_records_specialist import CorporateRecordsSpecialist
    from graph import build_graph
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent._configured_max_input_chars = lambda: 5000
    seen = []
    def call(message, **kwargs):
        seen.append(kwargs['json_schema']['title'])
        return response(kwargs['json_schema'])
    agent._call_structured = call
    def extractor(text, pages, handoff):
        return agent.extract(text, pages=pages, handoff_context=handoff)
    monkeypatch.setattr(build_graph, '_build_specialist_dispatch', lambda: {'corporate_record': extractor})
    monkeypatch.setattr(build_graph, '_detect_conflict', lambda *a: (False, []))
    monkeypatch.setattr(build_graph, '_review_extraction', lambda *a: None)
    monkeypatch.setattr(build_graph, '_emit_stage_audit', lambda *a, **kw: None)
    result = build_graph.extract_node({'doc_type': 'corporate_record', 'doc_text': 'text',
                                       'doc_subclass': 'indenture', 'expected_subclass': 'subsidiary_list'})
    assert seen == ['CorporateRecordExtraction_indenture']
    assert not result['extracted_data'].get('_parse_error')


def test_registry_drift_and_runlock_identity(monkeypatch):
    from mailroom_sandbox import corporate_extraction
    description = vendor_hotfixes.describe()
    assert description['corporate_extraction_sha256']
    monkeypatch.setattr(corporate_extraction, 'registry_matches', lambda: False)
    statuses = vendor_hotfixes.apply_hotfixes()
    assert all(statuses[fix] == 'stale' for fix in ('HF-020', 'HF-021', 'HF-022'))
    # Corporate registry drift must not disable main's judge/arbiter fixes.
    assert all(statuses[fix] == 'applied' for fix in ('HF-013', 'HF-014', 'HF-015'))


@pytest.mark.parametrize('omitted', [False, True])
def test_dedicated_langchain_schema_keeps_missing_confidence_fallback(omitted):
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist
    from mailroom_sandbox.corporate_extraction import validate_response

    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent.handoff_context = 'Sorter classification: doc_type=corporate_record doc_subclass=indenture'
    agent.truncate_input = lambda text: text
    agent._evidence_confidence = lambda result: 0.9

    def call(message, **kwargs):
        value = response(kwargs['json_schema'])
        value['confidence'] = None
        if omitted:
            value.pop('confidence')
        assert not validate_response(value, kwargs['json_schema'])
        assert validate_response(value, kwargs['json_schema'], allow_missing_confidence=True)
        missing_fact = {k: v for k, v in value.items() if k != 'trustee'}
        assert not validate_response(missing_fact, kwargs['json_schema'], allow_missing_confidence=True)
        return value

    agent._call_structured = call
    result = agent.extract('source')
    assert not result.get('_parse_error')
    assert result['confidence'] == 0.9


def test_null_list_compatibility_is_limited_to_inapplicable_fields():
    payload = {'entity_name': 'Example', 'signatories': None}
    assert assess_extraction_payload(payload, 'corporate_record', 'subsidiary_list')['schema_valid']
    assert not assess_extraction_payload(payload, 'corporate_record', 'indenture')['schema_valid']
    assert not assess_extraction_payload({'keywords': None}, 'corporate_record', 'subsidiary_list')['schema_valid']


@pytest.mark.parametrize('token', ['indenture-junk', 'indenture.bad', 'indenture..', 'unknown'])
def test_handoff_rejects_unknown_whole_token(token):
    with pytest.raises(ValueError):
        subclass_from_handoff(f'Sorter classification: doc_type=corporate_record doc_subclass={token}.')


def test_handoff_only_reads_sorter_header():
    assert subclass_from_handoff('Sorter classification: doc_type=corporate_record doc_subclass=indenture. Extract fields\ndoc_subclass=bylaws') == 'indenture'
    assert subclass_from_handoff('Document: doc_subclass=indenture') is None
    assert subclass_from_handoff('Sorter classification: doc_type=corporate_record.\ndoc_subclass=indenture') is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), True, -0.1, 1.1])
def test_nonfinite_or_invalid_confidence_rejected(value):
    from langchain_agents.specialist_agents import CORPORATE_RECORDS_SCHEMA
    schema = request_schema('indenture', CORPORATE_RECORDS_SCHEMA)
    assert not validate_response(response(schema, {'confidence': value}), schema)


def test_nested_reasoning_transport_constraints():
    reasoning = {'type': 'object', 'properties': {'entries': {'type': 'array', 'maxItems': 1, 'items': {'type': 'object', 'properties': {'field': {'type': 'string'}}, 'required': ['field'], 'additionalProperties': False}}}, 'required': ['entries'], 'additionalProperties': False}
    schema = request_schema('indenture', {'properties': {'reasoning': reasoning}})
    assert validate_response(response(schema, {'reasoning': {'entries': [{'field': 'trustee'}]}}), schema)
    for bad in ({'entries': [{'field': 'trustee', 'extra': 1}]}, {'entries': [{}, {}]}, {'entries': 'bad'}, {'entries': [], 'extra': 1}):
        assert not validate_response(response(schema, {'reasoning': bad}), schema)


@pytest.mark.parametrize('chunk_chars,text,expected_calls', [(100, 'short', 1), (5, 'abcdefghij', 2)])
def test_langchain_bound_call_usage_and_zero_confidence(chunk_chars, text, expected_calls):
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent.handoff_context = 'Sorter classification: doc_type=corporate_record doc_subclass=indenture.'
    agent.truncate_input = lambda value: value
    agent._last_usage = {'total_tokens': 999}
    def call(self, message, **kwargs):
        self._last_usage = {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3}
        self._last_trace_marker = 'captured'
        return response(kwargs['json_schema'], {'confidence': 0.0, 'entity_name': 'Example'})
    agent._call_structured = MethodType(call, agent)
    result = agent.extract_chunked(text, chunk_chars=chunk_chars, overlap_chars=0)
    assert result['confidence'] == 0.0
    assert agent._last_usage['total_tokens'] == 3 * expected_calls
    assert agent._last_trace_marker == 'captured'
    assert agent._last_n_chunks == expected_calls
    assert agent._last_chunked is (expected_calls > 1)


def test_real_langchain_fallback_function_schema():
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist
    from langchain_core.utils.function_calling import convert_to_openai_tool
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent.handoff_context = 'Sorter classification: doc_type=corporate_record doc_subclass=indenture.'
    agent.truncate_input = lambda text: text
    agent._last_usage = None
    agent._temperature = 0.1
    agent._max_tokens = 100
    agent._callbacks = None
    agent.model = 'offline-fake'
    agent._check_deadline = lambda: None
    agent.augmented_system_prompt = lambda: 'system'
    agent._build_user_content = lambda message, pages: message
    agent._invoke_with_retry = lambda fn, **kwargs: fn()
    agent._record_usage = lambda usage: None
    captured = []
    class FakeLLM:
        def bind(self, **kwargs):
            return self
        def with_structured_output(self, schema, *, method, include_raw):
            captured.append((method, schema))
            if method == 'json_schema':
                raise ValueError('fallback')
            tool = convert_to_openai_tool(schema)
            assert re.fullmatch(r'[A-Za-z0-9_-]{1,64}', tool['function']['name'])
            assert tool['function']['parameters']['properties'] == schema['properties']
            return SimpleNamespace(invoke=lambda *args, **kwargs: {'raw': None, 'parsed': response(schema), 'parsing_error': None})
    agent.llm = lambda: FakeLLM()
    assert not agent.extract('text').get('_parse_error')
    assert [method for method, _ in captured] == ['json_schema', 'function_calling']
    assert captured[1][1] == request_schema('indenture', agent.schema)
    captured.clear()
    assert not agent.extract_chunked('short', chunk_chars=100, overlap_chars=0).get('_parse_error')
    assert [method for method, _ in captured] == ['json_schema', 'function_calling']
    captured.clear()
    assert not agent.extract_chunked('abcdefghij', chunk_chars=5, overlap_chars=0).get('_parse_error')
    assert [method for method, _ in captured] == ['json_schema', 'function_calling'] * 2


def test_native_bound_call_usage_and_zero_confidence():
    from agents.corporate_records_specialist import CorporateRecordsSpecialist
    vendor_hotfixes.apply_hotfixes()
    agent = object.__new__(CorporateRecordsSpecialist)
    agent._configured_max_input_chars = lambda: 100
    def call(self, message, **kwargs):
        self._last_usage = {'total_tokens': 7}
        return response(kwargs['json_schema'], {'confidence': 0.0})
    agent._call_structured = MethodType(call, agent)
    result = agent.extract('text', handoff_context='Sorter classification: doc_type=corporate_record doc_subclass=indenture.')
    assert result['confidence'] == 0.0
    assert agent._last_usage['total_tokens'] == 7


@pytest.mark.parametrize('route', ['native', 'langchain', 'chunked'])
@pytest.mark.parametrize('only', [False, True])
def test_corporate_composer_carries_fields_to_judge_and_field_retry(monkeypatch, route, only):
    from agents import base as native_base
    from agents.corporate_records_specialist import CorporateRecordsSpecialist as Native
    from agents.judge import CompletenessJudge
    from graph import build_graph as bg
    from langchain_agents import base_agent as lc_base
    from langchain_agents.specialist_agents import CorporateRecordsSpecialist as LangChain
    from mailroom_sandbox import correcting_judge, subclass_extraction as sx
    from mailroom_sandbox.job import call_guard

    vendor_hotfixes.apply_hotfixes()
    sent, reviews = [], []

    def call(self, message, json_schema, *args, **kwargs):
        if type(self).__name__ == 'CorporateRecordsSpecialist':
            sent.append(json_schema)
            return response(json_schema, {'subsidiaries': ['Example Limited']})
        reviews.append((type(self).__name__, str(message)))
        return {'confidence': 0.9, 'completeness': 0.6, 'completeness_label': 'partial',
                'reasoning': 'gaps', 'extraction_correctness': 1.0,
                'extraction_correctness_label': 'accurate', 'decision': 'human_review',
                'fields_to_fix': [], 'handoff_summary': ''}

    monkeypatch.setattr(native_base.BaseAgent, '_call_structured', call)
    monkeypatch.setattr(lc_base.BaseAgent, '_call_structured', call)
    monkeypatch.setattr(bg, 'judge_should_run', lambda state: True)
    agent = object.__new__(Native if route == 'native' else LangChain)
    handoff = 'Sorter classification: doc_type=corporate_record doc_subclass=subsidiary_list.'
    agent.handoff_context = handoff
    agent._configured_max_input_chars = lambda: 5000
    agent.truncate_input = lambda text: text
    agent._last_usage = None

    def extract():
        if route == 'native':
            return agent.extract('Example Limited', handoff_context=handoff)
        if route == 'chunked':
            return agent.extract_chunked('Example Limited\n\nMore text', chunk_chars=16, overlap_chars=0)
        return agent.extract('Example Limited')

    with call_guard.document():
        if only:
            with sx.fields_only(['subsidiaries']):
                result = extract()
        else:
            result = extract()
        assert not result.get('_parse_error')
        assert sent and all('subsidiaries' in s['properties'] for s in sent)
        if only:
            assert all(set(s['properties']) <= {'subsidiaries', 'confidence', 'reasoning'} for s in sent)
        expected = CompletenessJudge._field_list('corporate_record')
        assert '  - subsidiaries:' in expected
        assert '  - subsidiary_jurisdictions:' in expected  # review the whole result after a field retry
        for field in ('filing_number', 'signatories', 'jurisdiction'):
            assert f'  - {field}:' not in expected  # empty-only slots cannot carry facts
        requested = correcting_judge.requested_fields('corporate_record')
        assert 'subsidiaries' in requested and 'filing_number' not in requested
        state = {'doc_type': 'corporate_record', 'doc_subclass': 'subsidiary_list',
                 'doc_text': 'Example Limited', 'extracted_data': {'subsidiaries': ['Example Limited']},
                 'judge_verdict': 'partial', 'judge_findings': ['gaps'], 'judge_score': 0.6}
        bg.judge_verify_node(state)
        bg.arbiter_node(state)
        assert {'CompletenessJudge', 'ArbiterAgent'} <= {name for name, _ in reviews}
        assert all('subsidiaries' in message for _, message in reviews)
        assert not any('  - filing_number:' in message for _, message in reviews)
    with call_guard.document():
        assert sx._review() is None
        assert '  - subsidiaries:' not in CompletenessJudge._field_list('corporate_record')


def test_corporate_fallback_replaces_previous_review_schema():
    from langchain_agents.specialist_agents import CORPORATE_RECORDS_SCHEMA
    from mailroom_sandbox import subclass_extraction as sx
    from mailroom_sandbox.job import call_guard

    with call_guard.document():
        sx.composed_schema(CORPORATE_RECORDS_SCHEMA, request_schema('subsidiary_list', CORPORATE_RECORDS_SCHEMA))
        assert 'subsidiaries' in sx._review()['add']
        sx.composed_schema(CORPORATE_RECORDS_SCHEMA, request_schema(None, CORPORATE_RECORDS_SCHEMA))
        assert not sx._review()['add']
        assert 'filing_number' not in sx._review()['drop']
