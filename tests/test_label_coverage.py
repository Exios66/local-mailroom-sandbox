"""Small offline checks of coverage semantics and overlay precedence."""
import json

from mailroom_sandbox import interim_labels as il
from mailroom_sandbox import label_coverage as lc


def test_effective_overlap_precedence_and_absence(monkeypatch):
    from mailroom_sandbox import scoring_hotfixes

    monkeypatch.setattr(scoring_hotfixes, 'enabled', lambda name: name == 'SHF-010')
    row = {'id': 'D1', 'doc_text': 'source', 'expected_doc_class': 'correspondence',
           'expected_subclass': 'email', 'expected_fields': {'sender': 'Hub'}}
    sha = il.doc_sha('source')
    interim = {'D1': {'doc_sha256': sha, 'labels': {
        'sender': {'status': 'gap_fill', 'basis': 'gate', 'use_as_truth': True, 'value': 'Ignored'},
        'recipient': {'status': 'gap_fill', 'basis': 'gate', 'use_as_truth': True, 'value': 'Interim'},
        'urgency': {'status': 'gap_fill', 'basis': 'original_header', 'use_as_truth': True, 'value': 'Keep'},
        'communication_date': {'status': 'disputed', 'use_as_truth': False, 'value': 'Not admitted'},
    }}}
    near = {'D1': {'doc_sha256': sha, 'labels': {
        k: {'basis': 'near_gold:two_pass_agree', 'value': v} for k, v in
        {'sender': 'Never overrides Hub', 'recipient': None, 'urgency': 'Replace?',
         'communication_date': '2020-01-01'}.items()}}}
    result = lc.stages([row], interim, near, 'i', 'n')
    before = il._expected(result['interim'][0])
    after = il._expected(result['near_gold'][0])
    assert before['sender'] == after['sender'] == 'Hub'
    assert before['recipient'] == 'Interim' and after['recipient'] is None
    assert after['urgency'] == 'Keep'
    assert after['communication_date'] == '2020-01-01'
    assert lc.presence(before, 'recipient') == 'populated'
    assert lc.presence(after, 'recipient') == 'absence'
    assert 'recipient' in result['near_gold'][0]['truth_overrides']['SHF-010']
    changed = dict(row, doc_text='different')
    assert il._expected(lc.stages([changed], interim, near, 'i', 'n')['near_gold'][0]) == row['expected_fields']


def test_presence_counts_zero_and_rejects_absence_with_placeholder():
    assert lc.presence({'amount': 0}, 'amount') == 'populated'
    assert lc.presence({'amount': 9, 'gt_presence': json.dumps({'amount': 'schema_documented_absence'})}, 'amount') == 'absence'
    assert lc.presence({'amount': []}, 'amount') == 'missing'


def test_corporate_subclass_applicability_and_request_intersection():
    subsidiary = lc.schema_fields('corporate_record', 'subsidiary_list')
    formation = lc.schema_fields('corporate_record', 'certificate_of_formation')
    assert subsidiary['subsidiaries']['registered'] and subsidiary['subsidiaries']['applicable']
    assert not subsidiary['jurisdiction']['applicable']
    assert not subsidiary['filing_number']['applicable']
    assert 'authorized_capital' not in formation or not formation['authorized_capital']['applicable']


def test_missing_cache_is_offline_and_keeps_catalog_available(monkeypatch):
    import huggingface_hub

    def missing(*args, **kwargs):
        assert kwargs['local_files_only'] is True
        raise FileNotFoundError('missing')

    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', missing)
    rows, sources, problem = lc.cached_corpus()
    assert rows == sources == []
    assert 'populate all' in problem and 'never downloads' in problem


def test_coverage_emits_one_pair_per_stage_and_marks_effective_source(monkeypatch):
    monkeypatch.setattr(lc, 'schema_fields', lambda cls, sub: {
        'sender': {'dojo_status': 'partial', 'registered': True, 'applicable': True, 'emittable': True},
        'recipient': {'dojo_status': 'pending_annotation', 'registered': True, 'applicable': True, 'emittable': True},
    })
    base = {'id': 'D1', 'expected_doc_class': 'correspondence', 'expected_subclass': 'email',
            'expected_fields': {'sender': 'A'}}
    final = {**base, 'expected_fields': {'sender': 'B', 'recipient': 'C'},
             'interim_labels': {'fields': ['sender']}, 'near_gold_labels': {'fields': ['sender', 'recipient']}}
    table = lc.coverage_rows({'hub': [base], 'near_gold': [final]})
    assert len(table) == 4
    assert len({(r['stage'], r['doc_id'], r['field']) for r in table}) == 4
    assert [r['source'] for r in table if r['stage'] == 'near_gold'] == ['near_gold', 'near_gold']


def test_snapshots_refuse_a_stale_near_gold_export(tmp_path, monkeypatch):
    import pytest

    interim, near, gold = [tmp_path / name for name in ('interim', 'near', 'gold')]
    for folder in (interim, near, gold):
        folder.mkdir()
        (folder / 'MANIFEST.json').write_text('{}')
    (near / 'MANIFEST.json').write_text(json.dumps({'catalog_manifest_sha256': 'old'}))
    monkeypatch.setattr(lc, 'repo_root', lambda: tmp_path)
    monkeypatch.setattr(lc.il, 'overlay_dir', lambda: interim)
    monkeypatch.setattr(lc.gl, 'gold_overlay_dir', lambda: near)
    monkeypatch.setattr(lc.gl, 'gold_dir', lambda: gold)
    monkeypatch.setattr(lc.il, 'overlay_snapshot', lambda: ({}, lc.digest(interim / 'MANIFEST.json'), []))
    monkeypatch.setattr(lc.gl, 'near_gold_snapshot', lambda: ({}, lc.digest(near / 'MANIFEST.json'), []))
    with pytest.raises(ValueError, match='stale relative to the catalog'):
        lc.snapshots()


def test_catalog_refuses_a_concurrent_file_change(tmp_path, monkeypatch):
    import pytest

    folder = tmp_path / 'data/labels/gold'
    folder.mkdir(parents=True)
    payload = folder / 'corporate_record.jsonl'
    payload.write_text('{"value": "original"}\n')
    (folder / 'MANIFEST.json').write_text(json.dumps({'files': {payload.name: lc.digest(payload)}}))
    monkeypatch.setattr(lc, 'repo_root', lambda: tmp_path)

    def verify(_):
        payload.write_text('{"value": "changed"}\n')
        return []

    monkeypatch.setattr(lc.gl, 'verify_catalog', verify)
    with pytest.raises(ValueError, match='changed during inspection'):
        lc.catalog()
