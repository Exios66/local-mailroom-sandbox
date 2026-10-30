"""Experiment design, paired data, spend gates and smoke-before-launch contracts."""
import json

import pytest
import yaml

from mailroom_sandbox import cli, experiments as ex
from mailroom_sandbox.job.checkpoint import RunStore
from mailroom_sandbox.job.spec import run_dir
from mailroom_sandbox.services._exec import ServiceError


@pytest.fixture(autouse=True)
def environment(monkeypatch, job_data_dir):
    monkeypatch.setattr('mailroom_sandbox.runtime.dotenv_files', lambda: [])
    monkeypatch.setattr('mailroom_sandbox.paths.dotenv_files', lambda: [])
    monkeypatch.setenv('MODAL_WORKSPACE', 'test-workspace')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake-for-offline-tests')


@pytest.fixture
def design(tmp_path):
    source = tmp_path / 'docs.jsonl'
    source.write_text(''.join(json.dumps({'id': f'c{i}', 'doc_text': 'Email from Jane to John: meeting tomorrow.',
        'expected_doc_class': 'correspondence', 'expected_subclass': 'email', 'expected_stage': 'archived',
        'expected_fields': {'sender': 'Jane'}}) + '\n' for i in range(3)))
    def create(*options):
        root = tmp_path / ('design-' + str(len(list(tmp_path.glob('design-*')))))
        args = ['experiment', 'create', root.name, '--doc-class', 'correspondence', '--samples', '3', '--subclass', 'email',
                '--local-dataset', str(source), '--trace-sink', 'none', '--output', str(root), *options]
        assert cli.main(args) == 0
        return root / 'experiment.yaml'
    return create


def test_sand42_creates_paired_2x2_grid_without_network(design, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: pytest.fail('create cannot fetch'))
    config = design('--design', 'sand42', '--mock')
    _, plan, runs = ex._load(config)
    assert len(runs) == 4
    assert {(spec.engine.modal.max_containers, spec.job.concurrency) for _, spec in runs} == {(1,8),(1,16),(2,8),(2,16)}
    assert len({json.dumps(spec.dataset.model_dump(), sort_keys=True) for _, spec in runs}) == 1
    assert len({spec.engine.modal.app for _, spec in runs}) == 4
    assert cli.main(['experiment', 'preflight', '--config', str(config)]) == 0
    assert len({RunStore(run_dir(spec.run_id)).read_lock()['dataset']['sha256'] for _, spec in runs}) == 1


def test_smoke_and_full_run_are_separate_locked_subsets(design):
    config = design('--mock')
    assert cli.main(['experiment', 'launch', '--config', str(config)]) == 0
    report = json.loads((config.parent / 'report.json').read_text())
    assert report['complete'] and report['runs'][0]['ok'] == 3
    main_store = RunStore(run_dir(report['runs'][0]['run_id']))
    smoke_id = next(event['detail']['smoke_run_id'] for event in (json.loads(line) for line in main_store.events_path.read_text().splitlines()) if event.get('event') == 'experiment_smoke_passed')
    assert len(RunStore(run_dir(smoke_id)).dataset_rows()) == 1
    assert len(main_store.dataset_rows()) == 3


def _fake_execute(store):
    for row in store.dataset_rows():
        store.append_item({'item_id': row['id'], 'ok': True, 'score': {'match': 1.0}})
    store.write_checkpoint(state='done', cursor=len(store.dataset_rows()), total=len(store.dataset_rows()))
    return store.summary()


def test_unsigned_launch_never_deploys_or_probes(design, monkeypatch):
    config = design()
    monkeypatch.setattr(ex.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(ex, '_deploy', lambda spec: pytest.fail('unsigned deploy'))
    monkeypatch.setattr(ex, '_probe', lambda spec: pytest.fail('unsigned probe'))
    assert cli.main(['experiment', 'launch', '--config', str(config)]) == 1


def test_signed_launch_smokes_before_full_run_and_tears_down(design, monkeypatch):
    config = design()
    events = []
    monkeypatch.setattr('mailroom_sandbox.services.modal_cli._is_deployed', lambda app: False)
    def deploy(spec):
        for _, run_spec in ex._load(config)[2]:
            receipt = json.loads((run_dir(run_spec.run_id) / 'spend-authorization.json').read_text())
            assert receipt['initials'] == 'JB'
            assert receipt['workflow']['smoke_rows'] == 1
        events.append('deploy')
    def execute(store):
        events.append(len(store.dataset_rows()))
        return _fake_execute(store)
    monkeypatch.setattr(ex, '_deploy', deploy)
    monkeypatch.setattr(ex, '_execute', execute)
    monkeypatch.setattr(ex, '_probe', lambda spec: events.append('probe'))
    monkeypatch.setattr(ex, '_teardown', lambda spec: events.append('stop'))
    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 0
    assert events == ['deploy', 'probe', 1, 3, 'stop']


def test_failed_smoke_blocks_full_run_and_stops_app(design, monkeypatch):
    config = design()
    calls = []
    monkeypatch.setattr('mailroom_sandbox.services.modal_cli._is_deployed', lambda app: False)
    monkeypatch.setattr(ex, '_deploy', lambda spec: None)
    monkeypatch.setattr(ex, '_probe', lambda spec: None)
    monkeypatch.setattr(ex, '_teardown', lambda spec: calls.append('stop'))
    def fail(store):
        calls.append(len(store.dataset_rows()))
        store.write_checkpoint(state='failed', cursor=0, total=len(store.dataset_rows()))
    monkeypatch.setattr(ex, '_execute', fail)
    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 1
    assert calls == [1, 'stop']
    assert json.loads((config.parent / 'report.json').read_text())['complete'] is False


def test_partial_deploy_failure_still_tears_down(design, monkeypatch):
    config = design()
    calls = []
    monkeypatch.setattr('mailroom_sandbox.services.modal_cli._is_deployed', lambda app: False)
    monkeypatch.setattr(ex, '_deploy', lambda spec: (_ for _ in ()).throw(ServiceError('image failed')))
    monkeypatch.setattr(ex, '_teardown', lambda spec: calls.append('stop'))
    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 1
    assert calls == ['stop']


def test_pipeline_supports_hybrid_routes_and_agent_models(design):
    config = design('--task', 'pipeline', '--agent-route', 'sorter=openrouter:api-sorter',
                    '--agent-route', 'contracts_specialist=modal-vllm:Qwen/Qwen3-8B',
                    '--agent-model', 'boss=api-boss', '--mock')
    spec = ex._load(config)[2][0][1]
    assert spec.task == 'pipeline'
    assert spec.agent_routes['sorter'].model == 'api-sorter'
    assert spec.agent_routes['contracts_specialist'].modal.app.startswith('sandbox-vllm-')
    assert spec.agent_models['boss'] == 'api-boss'
    assert len(ex._deployments(spec)) == 2
    assert 'sorter' in spec.agent_knobs and 'sorter_reviewer' in spec.agent_knobs


def test_unknown_setting_is_refused_without_writing(design):
    with pytest.raises(AssertionError):
        design('--set', 'engine.vllm.typo=1')


def test_unavailable_sample_refuses_before_spend(design, monkeypatch):
    config = design('--mock')
    run_path = ex._load(config)[2][0][0]
    data = yaml.safe_load(run_path.read_text())
    data['dataset']['limit'] = 4
    run_path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(ex, '_deploy', lambda spec: pytest.fail('insufficient rows must not deploy'))
    assert cli.main(['experiment', 'launch', '--config', str(config)]) == 1


def test_full_pipeline_mock_writes_observer_evidence(design):
    config = design('--task', 'pipeline', '--mock')
    assert cli.main(['experiment', 'launch', '--config', str(config)]) == 0
    spec = ex._load(config)[2][0][1]
    store = RunStore(run_dir(spec.run_id))
    assert len(store.load_items()) == 3
    assert store.summary()['state'] == 'done'
    assert 'sorter_reviewer' in store.read_lock()['agent_assignments']
    assert 'reporter' not in store.read_lock()['agent_assignments']
    report = json.loads((config.parent / 'report.json').read_text())
    assert report['complete'] and report['runs'][0]['scorer_aggregates']['connected']


def test_all_completed_jobs_are_not_redeployed(design, monkeypatch):
    config = design()
    path, plan, runs = ex._load(config)
    stores = ex._prepare(path, plan, runs)
    for store in stores:
        _fake_execute(store)
    monkeypatch.setattr(ex, '_deploy', lambda spec: pytest.fail('completed campaign must not deploy'))
    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 0


def test_hybrid_deployment_failure_cleans_every_attempted_app(design, monkeypatch):
    config = design('--task', 'pipeline', '--agent-route', 'sorter=modal-vllm:Qwen/Qwen3-8B')
    attempted, stopped = [], []
    monkeypatch.setattr('mailroom_sandbox.services.modal_cli._is_deployed', lambda app: False)
    def deploy(spec):
        attempted.append(spec.engine.modal.app)
        if len(attempted) == 2:
            raise ServiceError('second deployment failed')
    monkeypatch.setattr(ex, '_deploy', deploy)
    monkeypatch.setattr(ex, '_teardown', lambda spec: stopped.append(spec.engine.modal.app))
    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 1
    assert len(attempted) == 2 and stopped == list(reversed(attempted))


def test_route_can_replace_an_unused_default_deployment(design):
    config = design('--agent-route', 'correspondence_specialist=openrouter:api-model', '--mock')
    spec = ex._load(config)[2][0][1]
    assert ex._deployments(spec) == []


def _route_spec():
    from mailroom_sandbox.job.spec import AgentRoute, DatasetSpec, RunSpec
    return RunSpec(
        run_id='route-probe',
        task='sorter',
        profile='modal-vllm',
        dataset=DatasetSpec(provider='file', local_path='unused.jsonl'),
        engine={'kind': 'vllm-local', 'model': 'default-model', 'modal': None},
        agent_routes={'sorter': AgentRoute(provider='vllm', model='served-model', base_url='http://route.test/v1')},
        trace={'sink': 'none'},
    )


def test_route_models_probe_retries_while_the_route_boots(monkeypatch):
    """A scale-to-zero route holds /models open while booting; one 60 s GET
    used to fail verification and tear down a healthy app."""
    import httpx

    calls = {'get': 0}

    class _Resp:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, headers=None, timeout=None):
        calls['get'] += 1
        if calls['get'] == 1:
            raise httpx.ReadTimeout('container booting')
        return _Resp({'data': [{'id': 'served-model'}]})

    def fake_post(url, headers=None, timeout=None, json=None):
        assert json['model'] == 'served-model'
        return _Resp({'choices': [{'message': {'content': 'OK'}}]})

    monkeypatch.setattr('httpx.get', fake_get)
    monkeypatch.setattr('httpx.post', fake_post)
    monkeypatch.setenv('SANDBOX_ENGINE_PROBE_TIMEOUT_SECONDS', '5')

    ex._probe(_route_spec())

    assert calls['get'] == 2


def test_teardown_failure_preserves_the_original_failure(design, monkeypatch, capsys):
    config = design('--task', 'pipeline', '--agent-route', 'sorter=modal-vllm:Qwen/Qwen3-8B')
    monkeypatch.setattr('mailroom_sandbox.services.modal_cli._is_deployed', lambda app: False)

    def fail_deploy(spec):
        raise ServiceError('deployment failed first')

    def fail_teardown(spec):
        raise ServiceError('stop refused')

    monkeypatch.setattr(ex, '_deploy', fail_deploy)
    monkeypatch.setattr(ex, '_teardown', fail_teardown)

    assert cli.main(['experiment', 'launch', '--config', str(config), '--initials', 'JB']) == 1
    err = capsys.readouterr().err
    assert 'deployment failed first' in err
    assert 'teardown failed' in err and 'stop refused' in err
