"""Operator-visible defects found by the SAND-066 Terra command audit."""
from __future__ import annotations

import argparse

import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.eval import matrix, runners


@pytest.mark.parametrize('argv', [
    ['--agent-model', 'sorter=a', 'eval', 'sorter', '--agent-model', 'judge=b'],
    ['--agent-model', 'sorter=a', 'run', '--agent-model', 'judge=b', 'start', '--agent-model', 'sorter=c'],
])
def test_repeatable_models_accumulate_across_command_levels(argv):
    args = cli.build_parser().parse_args(argv)
    expected = {'sorter': 'c', 'judge': 'b'} if 'run' in argv else {'sorter': 'a', 'judge': 'b'}
    assert cli._agent_models(args) == expected


@pytest.mark.parametrize('command', [['eval', 'sorter'], ['matrix']])
def test_mock_and_live_are_exclusive(command):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([*command, '--mock', '--local'])
    assert exc.value.code == 2


@pytest.mark.parametrize('argv', [
    ['eval', 'sorter', '--sample', '0'], ['eval', 'sorter', '--sample', '-3'],
    ['pilot', '--sample', '0'],
    ['matrix', '--sample', '0'], ['modernbert', 'eval', '--sample', '-1'],
    ['datasets', 'sample', '--per-class', '-1'], ['datasets', 'pull', '--max-rows', '-1'],
    ['metrics', 'estimate-suite', '--gpu-usd-per-hour', '-1'],
    ['metrics', 'estimate-suite', '--gpu-usd-per-hour', 'nan'],
    ['metrics', 'estimate-suite', '--sec-per-doc', '0'],
    ['metrics', 'estimate-suite', '--gen-tok-per-s', '-1'],
    ['metrics', 'estimate-suite', '--corpus-size', '0'],
    ['metrics', 'extrapolate', '--run', 'x', '--concurrency', '0'],
    ['metrics', 'extrapolate', '--run', 'x', '--cold-start-seconds', 'inf'],
    ['run', 'start', '--max-items', '0'], ['matrix', '--task', 'nonexistent'],
])
def test_invalid_numeric_and_task_choices_rejected(argv):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize('argv', [
    ['run', 'resume', '--run-id', 'x'], ['run', 'cancel', '--run-id', 'x'],
    ['run', 'dispose', '--run-id', 'x', '--report', 'x.md'],
    ['run', 'scrape-metrics', '--run-id', 'x', '--label', 'mid'],
    ['run', 'card', '--run-id', 'x'], ['run', 'export-bt', '--run-id', 'x'],
    ['run', 'status', '--run-id', 'x'],
])
def test_unsupported_dry_run_never_dispatches(argv, monkeypatch):
    def unexpected(*a, **k):
        pytest.fail('action dispatched under unsupported --dry-run')
    for name in ('_cmd_run_resume', '_cmd_run_cancel', '_cmd_run_dispose', '_cmd_run_scrape_metrics', '_cmd_run_card', '_cmd_run_export_bt', '_cmd_run_status'):
        monkeypatch.setattr(cli, name, unexpected)
    with pytest.raises(SystemExit) as exc:
        cli.main([*argv, '--dry-run'])
    assert exc.value.code == 2


@pytest.mark.parametrize('argv', [
    ['eval', 'sorter', '--from-log'], ['eval', 'sorter', '--connected'],
    ['eval', 'local_vs_api', '--group', '1'],
    ['matrix', '--providers', ','], ['matrix', '--models', ','], ['matrix', '--prompts', ','],
    ['pilot', '--agent-model', 'invalid'], ['hf-pilot', '--agent-model', 'invalid'],
])
def test_misleading_ignored_options_return_usage_error(argv, capsys):
    assert cli.main([*argv, '--mock', '--dry-run']) == 2
    assert 'error:' in capsys.readouterr().err


def test_pilot_forwards_agent_overrides(monkeypatch):
    seen = {}
    monkeypatch.setattr(runners, 'run_pipeline_eval', lambda **kw: seen.update(kw) or {})
    assert cli.main(['pilot', '--mock', '--dry-run', '--agent-model', 'sorter=custom']) == 0
    assert seen['agent_models'] == {'sorter': 'custom'}


@pytest.mark.parametrize('live', [False, True])
def test_hf_pilot_scores_hf_text_and_labels(live, monkeypatch, tmp_path):
    from mailroom_sandbox import datasets
    from mailroom_sandbox.eval import experiment_log
    rows = [{'id': 'hf-unique', 'doc_type': 'correspondence', 'text': 'Unique HF document text'}]
    monkeypatch.setattr(datasets, 'load_hf_fixtures', lambda: rows)
    monkeypatch.setattr(experiment_log, 'append', lambda r: None)
    monkeypatch.setattr(runners, 'emit', lambda r: None)
    monkeypatch.setenv('MAILROOM_BASE_DIR', str(tmp_path))
    seen = []
    def predict(row, **kw):
        seen.append(row)
        return {'doc_type': 'correspondence'}
    monkeypatch.setattr(runners, '_run_pipeline_doc', predict)
    monkeypatch.setattr(cli, '_print', lambda result: seen.append(result))
    assert cli.main(['hf-pilot', '--local' if live else '--mock', '--profile', 'ollama']) == 0
    result = seen[-1]
    normalized = [{**rows[0], 'expected_doc_class': 'correspondence'}]
    assert result['fingerprint'] == datasets.dataset_fingerprint(normalized)
    assert result['n'] == 1 and result['scores']['accuracy'] == 1
    if live:
        assert seen[0] == normalized[0]
        queued = runners._materialize_row(seen[0], tmp_path)
        assert queued.read_text() == rows[0]['text']


def test_matrix_forwards_seed_and_models(monkeypatch):
    seen = []
    monkeypatch.setattr(runners, 'run_pipeline_eval', lambda **kw: seen.append(kw) or {})
    matrix.run_matrix(task='pipeline', providers=['ollama'], models=['qwen3:8b'], prompts=['mailroom-default'], sample=2, seed=99, agent_models={'judge': 'custom'})
    assert seen[0]['sample_seed'] == 99
    assert seen[0]['agent_models'] == {'judge': 'custom'}


def test_seeded_pipeline_draw_is_shared_across_cells_and_changes_with_seed():
    rows = [{'id': str(i), 'expected_doc_class': 'contract'} for i in range(50)]
    def fingerprint(seed):
        return runners.run_pipeline_eval(rows=rows, sample=5, sample_seed=seed, dry_run=True)['fingerprint']
    assert fingerprint(12) == fingerprint(12)
    assert fingerprint(12) != fingerprint(13)


@pytest.mark.parametrize('argv', [['legalbench', '--mock'], ['eval', 'legalbench', '--mock'], ['matrix', '--task', 'legalbench', '--mock']])
def test_legalbench_is_not_a_sandbox_task(argv, capsys):
    """LegalBench is not a primary operation; the vendored package stays, the CLI surface does not."""
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2 and 'invalid choice' in capsys.readouterr().err


def test_legalbench_run_spec_is_rejected():
    from mailroom_sandbox.job.spec import RunSpec, known_tasks

    assert 'legalbench' not in known_tasks()
    with pytest.raises(ValueError, match='unknown task'):
        RunSpec(run_id='x', task='legalbench')
