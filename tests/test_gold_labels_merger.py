"""Merger label admission and actual per-field Dojo scoring, using synthetic text only."""
import importlib.util
from pathlib import Path

import pytest

from mailroom_sandbox import gold_labels as gl
from mailroom_sandbox.eval.scoring import score_extraction_row
from mailroom_sandbox.subclass_schemas import parse_guide
from llm_dojo_scoring.schemas.maud_schema import MergerAgreementExtraction

FIELDS = gl.TARGET_FIELDS['merger_agreement']['tier1']
MAUD = '{"No-Shop":{"answer":"Yes","valid_classes":[]}}'


def sample(name):
    t = MergerAgreementExtraction.field_types[name]
    if t.startswith('entity_list'):
        return ['Alpha Corp'], 'Alpha Corp'
    if t == 'date':
        return '2020-01-01', 'January 1, 2020'
    if t == 'money':
        return '$50', '$50'
    return 'Alpha Corp', 'Alpha Corp'


@pytest.mark.parametrize('name', FIELDS)
def test_admitted_value_produces_field_score_with_maud(name):
    value, quote = sample(name)
    result = gl.validate_submission({'doc_id': 'synthetic', 'fields': {name: {'value': value, 'evidence': [quote]}}}, quote, 'merger_agreement', 'all_cash')
    assert result.fields[name].ok, result.fields[name].reason
    scored = score_extraction_row('merger_agreement', {name: value}, {name: value, 'maud_clause_labels': MAUD}, field_scores=True)
    assert scored['field_scores'][name] == 1.0
    assert scored['overall_extraction_score'] == 0.0
    assert scored['scoring_method'].endswith('+maud')


def test_targets_and_guide():
    assert len(FIELDS) == 16
    assert set(FIELDS) == set(parse_guide()['merger_agreement'])
    assert set(FIELDS).isdisjoint({'merger_consideration', 'maud_clauses', 'intent', 'subject_matter', 'keywords'})


@pytest.mark.parametrize('name,value', [('parties', [True]), ('parties', [42]), ('parties', 'Alpha'), ('target', 12), ('target', False), ('target', ''), ('per_share_cash_amount', 50), ('per_share_cash_amount', '$5 million'), ('outside_date', '30 days after closing')])
def test_invalid_types_and_conditional_date(name, value):
    r = gl.validate_submission({'fields': {name: {'value': value, 'evidence': [str(value)]}}}, str(value), 'merger_agreement', 'all_cash')
    assert not r.fields[name].ok


def test_per_member_evidence_absence_and_excluded_fields():
    fields = {'parties': {'value': ['Alpha Corp', 'Beta LLC'], 'evidence': ['Alpha Corp Beta', 'LLC']},
              'target': {'value': None, 'absent': 'not found in full read'},
              'merger_consideration': {'value': 'all_cash', 'evidence': ['all cash']}}
    r = gl.validate_submission({'fields': fields}, 'Alpha Corp Beta LLC all cash', 'merger_agreement', 'all_cash')
    assert not r.fields['parties'].ok
    assert r.fields['target'].ok
    assert not r.fields['merger_consideration'].ok


@pytest.mark.parametrize('value,quotes,expected', [
    ('$50', ['€50'], False), ('$50', ['£50'], False),
    ('$50', ['GBP 50'], False), ('$50', ['pay 50'], False),
    ('$50', ['C$50'], False), ('$50', ['C $50'], False), ('$50', ['CAD $50'], False),
    ('$50', ['A$50'], False), ('$50', ['NZ $50'], False), ('$50', ['$50 CAD'], False),
    ('$50', ['$50 CHF'], False),
    ('$50', ['Canadian $50'], False), ('$50', ['€50 USD'], False),
    ('$50', ['$40 and €50'], False), ('$50', ['$40', 'pay 50'], False),
    ('$50', ['$50'], True), ('$50', ['a $50 payment'], True), ('$50', ['US$50'], True),
    ('$50', ['$50 AND other consideration'], True), ('$50', ['$50 FOR each share'], True),
    ('$50', ['THE $50 payment'], True),
    ('$50', ['USD 50'], True), ('$50', ['pay 50 USD'], True),
    ('$5,000,000', ['USD 5 million'], True),
    ('$50', ['$50 and €40'], True),
    ('$1', ['$.001'], False), ('$0.001', ['$.001'], True),  # the figure keeps its dollar sign
    ('$1', ['.001 USD'], False),
])
def test_merger_money_needs_same_figure_dollar_evidence(value, quotes, expected):
    name = 'per_share_cash_amount'
    text = ' '.join(quotes)
    result = gl.validate_submission({'fields': {name: {'value': value, 'evidence': quotes}}},
                                    text, 'merger_agreement', 'all_cash')
    assert result.fields[name].ok is expected, result.fields[name].reason
    assert gl.evidence_support('merger_agreement', name, value, quotes, 'all_cash')[0] is expected


def test_subclass_is_corpus_identity_not_submitted_value():
    for sub in (None, 'unknown', 'All Cash'):
        r = gl.validate_submission({'subclass': 'all_cash', 'fields': {'target': {'value': 'Alpha', 'evidence': ['Alpha']}}}, 'Alpha', 'merger_agreement', sub)
        assert not r.fields['target'].ok
    assert gl.validate_submission({'subclass': 'bogus', 'fields': {'target': {'value': 'Alpha', 'evidence': ['Alpha']}}}, 'Alpha', 'merger_agreement', 'other').fields['target'].ok
    with pytest.raises(KeyError):
        gl.work_queue([{'expected': 'merger_agreement', 'expected_subclass': None}])


def test_missing_field_source_binding_rejects_drift():
    spec = importlib.util.spec_from_file_location('gold_script', Path(__file__).parents[1] / 'scripts/gold_labels.py')
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    text = 'Alpha'
    doc = {'doc_id': 'd', 'doc_class': 'merger_agreement', 'subclass': 'all_stock', 'filename': 'f', 'content_sha256': 'sha'}
    record = {**doc, 'subclass': 'all_cash', 'doc_sha': gl.doc_sha(text)}
    result = gl.validate_submission({'fields': {'target': {'value': 'Alpha', 'evidence': ['Alpha']}}}, text, 'merger_agreement', 'all_stock')
    problems = script._missing_field_source_problems([(doc, {'fields': {'target': {}}}, result, text)], [], {'merger_agreement': [record]})
    assert any('subclass differs' in p for p in problems)
    record['subclass'] = None
    problems = script._missing_field_source_problems([(doc, {'fields': {'target': {}}}, result, text)], [], {'merger_agreement': [record]})
    assert any('subclass differs' in p for p in problems)
