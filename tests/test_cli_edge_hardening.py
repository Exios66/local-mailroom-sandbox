"""Edge inputs found by fuzzing every CLI leaf: each must end in one short line, never a traceback."""
from __future__ import annotations

import pytest

from mailroom_sandbox import cli


@pytest.mark.parametrize('command', ['up', 'down'])
@pytest.mark.parametrize('value', ['', 'nope', '/etc'])
def test_unknown_compose_profile_is_a_usage_error_listing_the_choices(command, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([command, '--compose-profile', value])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert 'invalid choice' in err and 'langfuse' in err


@pytest.mark.parametrize(('command', 'missing', 'hint'), [
    ('watcher', 'langfuse', "pip install -e '.[observability]'"),
    ('api', 'fastapi', 'pip install fastapi'),
])
def test_pipeline_services_name_a_missing_dependency_before_launching(command, missing, hint, monkeypatch, capsys):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *a: None if name == missing else real(name, *a))
    monkeypatch.setattr(cli.subprocess, 'call', lambda *a, **k: pytest.fail('launched without its dependency'))
    monkeypatch.setattr(cli, 'activate', lambda *a, **k: pytest.fail('activated before the dependency check'))
    assert cli.main(['pipeline', command]) == 1
    err = capsys.readouterr().err
    assert 'Traceback' not in err
    assert f'pipeline {command} needs {missing}' in err and hint in err


@pytest.mark.parametrize('argv', [
    ['--profile', '', 'agents', 'list'], ['agents', 'list', '--profile', '  '],
    ['--model', '', 'agents', 'list'], ['eval', 'sorter', '--prompt', ''],
])
def test_an_empty_global_flag_is_rejected_not_silently_defaulted(argv, capsys):
    # `--profile "$UNSET"` used to run on the default profile without a word.
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(argv)
    assert exc.value.code == 2
    assert 'empty' in capsys.readouterr().err


def test_an_unknown_profile_is_an_error_not_a_missing_command(capsys):
    assert cli.main(['--profile', 'nope', 'agents', 'list']) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: Unknown profile 'nope'") and 'modal-vllm' in err
    assert 'command unavailable' not in err
