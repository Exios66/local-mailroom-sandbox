"""Guided experimental designs composed from existing locked sandbox runs.

Create and review never deploy. Launch prepares every dataset/prompt first, obtains
initials, then deploys one cell at a time, smoke-tests a separate locked subset,
runs its jobs, and tears down that exact app even on failure.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mailroom_sandbox.job import preflight
from mailroom_sandbox.job.checkpoint import RunStore, _atomic_write
from mailroom_sandbox.job.deploy_env import spec_env
from mailroom_sandbox.job.spec import DatasetSpec, FAMILY_HF_REVISION, RunSpec, load_run_spec, run_dir
from mailroom_sandbox.job.spend import authorize, review_settings
from mailroom_sandbox.paths import repo_root
from mailroom_sandbox.services._exec import ServiceError, ToolFailed, stream_tool
from mailroom_sandbox.services._redact import redact_urls

CLASSES = {
    'contract': 'contracts-specialist', 'corporate_record': 'corporate-records-specialist',
    'correspondence': 'correspondence-specialist', 'insurance_claim': 'insurance-claims-specialist',
    'merger_agreement': 'merger-specialist',
}
DESIGNS = {'single': [(1, 8)], 'sand42': [(1, 8), (1, 16), (2, 8), (2, 16)]}


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_name: str = Field(default='sandbox.experiment/v1', alias='schema')
    study: str
    design: str
    runs: list[str] = Field(min_length=1)
    smoke_rows: int = Field(default=1, ge=1, le=5)
    smoke_cost_cap_usd: float = Field(default=0.10, gt=0, allow_inf_nan=False)
    smoke_wall_seconds: int = Field(default=120, ge=60)


def _load(path: str | Path) -> tuple[Path, Plan, list[tuple[Path, RunSpec]]]:
    path = Path(path).resolve()
    try:
        plan = Plan.model_validate(yaml.safe_load(path.read_text()))
        if plan.schema_name != 'sandbox.experiment/v1':
            raise ValueError('unsupported experiment schema')
        runs = [(path.parent / name, load_run_spec(path.parent / name)) for name in plan.runs]
        ids = [spec.run_id for _, spec in runs]
        if any(not name for name in ids) or len(set(ids)) != len(ids):
            raise ValueError('every run needs a distinct run_id')
        if any(spec.job.mode != 'endpoint' for _, spec in runs):
            raise ValueError('experiment launch currently requires job.mode: endpoint')
        if len({spec.job.mock for _, spec in runs}) != 1:
            raise ValueError('a design cannot mix mock and paid runs')
        return path, plan, runs
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise ServiceError(f'cannot load experiment: {exc}') from exc


def _quotas(buckets: list[dict], count: int) -> list[dict]:
    """Rescale published subclass quotas exactly, preserving each stratum when possible."""
    if count == sum(bucket['count'] for bucket in buckets):
        return copy.deepcopy(buckets)
    ordered = sorted(enumerate(buckets), key=lambda pair: (-pair[1]['count'], pair[0]))
    if count < len(buckets):
        return [{**bucket, 'count': 1} for _, bucket in ordered[:count]]
    weights = [bucket['count'] for bucket in buckets]
    available = count - len(buckets)
    raw = [available * weight / sum(weights) for weight in weights]
    counts = [1 + math.floor(value) for value in raw]
    for index in sorted(range(len(raw)), key=lambda i: (-(raw[i] % 1), i))[:count-sum(counts)]:
        counts[index] += 1
    return [{**bucket, 'count': n} for bucket, n in zip(buckets, counts)]


def _set(data: dict, assignment: str) -> None:
    name, sep, value = assignment.partition('=')
    if not sep:
        raise ServiceError('--set needs PATH=YAML_VALUE')
    parts = name.split('.')
    if parts[0] not in {'engine', 'job', 'trace', 'dataset', 'prompt', 'agent_knobs'}:
        raise ServiceError(f'unsupported setting {name!r}')
    target = data
    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            raise ServiceError(f'unknown configuration path {name!r}')
        target = target[part]
    if parts[-1] not in target:
        raise ServiceError(f'unknown configuration path {name!r}')
    try:
        target[parts[-1]] = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ServiceError(f'invalid YAML value for {name}: {exc}') from exc


def _create(args) -> int:
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,23}', args.study):
        raise ServiceError('study must be 1–24 lowercase letters/digits/hyphens')
    if args.max_tokens < 1 or not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2:
        raise ServiceError('max tokens must be positive; temperature must be finite in [0, 2]')
    if args.samples < 1 or not math.isfinite(args.cost_cap_usd) or args.cost_cap_usd <= 0:
        raise ServiceError('sample size and finite per-run cost cap must be positive')
    if not re.fullmatch(r'[a-fA-F0-9]{40}', args.revision):
        raise ServiceError('pin --revision to a full Hugging Face commit SHA')
    root = Path(args.output or repo_root() / 'config' / 'experiments' / args.study).resolve()
    if root.exists():
        raise ServiceError(f'{root} already exists; choose a new study/output (nothing overwritten)')
    cells = DESIGNS[args.design]
    if args.design == 'sand42' and (args.replicas is not None or args.concurrency is not None):
        raise ServiceError('sand42 fixes replica/concurrency axes at {1,2} × {8,16}; use single for custom values')
    selected = args.doc_class or list(CLASSES)
    generated = []
    from mailroom_sandbox.agent_routes import parse_routes, known_agents
    routes = parse_routes(args.agent_routes)
    from mailroom_sandbox.overlay import parse_agent_models
    try:
        agent_models = parse_agent_models(getattr(args, 'agent_models', None))
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    chosen_model = args.model or ('Qwen/Qwen3-8B-AWQ' if args.provider == 'modal-vllm' else 'qwen/qwen3.7-flash')
    for cell_index, (replicas, concurrency) in enumerate(cells):
        for doc_class in (selected if args.task == 'specialists' else [selected[0]]):
            template = repo_root() / 'config' / 'runs' / f'sand42-50-{CLASSES[doc_class]}-awq-1l4-c8.yaml'
            spec = load_run_spec(template)
            data = spec.model_dump(by_alias=True)
            label = f'{replicas}r-c{args.concurrency or concurrency}'
            data['run_id'] = f'{args.study}-{CLASSES[doc_class] if args.task == "specialists" else args.task}-{label}'
            data['runbook_id'] = None
            data['note'] = f'{args.design} design; paired class draws, seed {args.seed}; cell {cell_index+1}'
            data['profile'] = args.provider
            data['engine']['kind'] = args.provider
            data['engine']['model'] = chosen_model
            if args.provider == 'modal-vllm' and chosen_model != spec.engine.model:
                from mailroom_sandbox.modal_matrix import resolve_modal_row
                try:
                    row = resolve_modal_row(chosen_model, gpu_override=args.gpu)
                except (KeyError, ValueError) as exc:
                    raise ServiceError(str(exc)) from exc
                data['engine']['vllm'].update(max_model_len=int(row['env']['MODAL_VLLM_MAX_MODEL_LEN']), quantization=row['env']['MODAL_VLLM_QUANTIZATION'])
            if args.provider == 'modal-vllm':
                data['engine']['modal'].update(app=f'sandbox-vllm-{args.study}-{label}', gpu=args.gpu,
                    min_containers=0, max_containers=args.replicas or replicas)
            else:
                data['engine']['modal'] = None
            data['job'].update(mock=args.mock, mode='endpoint', concurrency=args.concurrency or concurrency,
                               cost_cap_usd=args.cost_cap_usd, max_wall_seconds=args.max_wall_seconds)
            ds = data['dataset']
            ds.update(repo=args.dataset, config=args.dataset_config, split=args.split, revision=args.revision,
                      limit=args.samples, sample_seed=args.seed, require_task_gt=True)
            bucket = ds['strata']['buckets'][0]
            bucket['count'] = args.samples
            if bucket.get('sub_buckets'):
                bucket['sub_buckets'] = _quotas(bucket['sub_buckets'], args.samples)
            if args.task != 'specialists':
                data['task'] = args.task
                ds['strata'] = {'buckets': [{'doc_class': name, 'count': args.samples} for name in selected]}
                ds['limit'] = args.samples * len(selected)
                data['prompt']['agents'] = {}
                for name in selected:
                    template_spec = load_run_spec(repo_root() / 'config' / 'runs' / f'sand42-50-{CLASSES[name]}-awq-1l4-c8.yaml')
                    data['prompt']['agents'].update(template_spec.prompt.get('agents', {}))
            if args.subclass:
                ds['strata'] = {'expected': selected if args.task != 'specialists' else [doc_class], 'expected_subclass': args.subclass}
            if args.local_dataset:
                ds.update(provider='file', local_path=str(Path(args.local_dataset).resolve()))
            data['job']['task'] = data['task']
            data['trace'].update(sink=args.trace_sink, otlp=args.trace_sink != 'none', endpoint=args.trace_endpoint,
                                 environment=args.study, tags=['sandbox', 'experiment', args.study, label])
            data['agent_knobs'] = {name: {'max_tokens': args.max_tokens, 'temperature': args.temperature} for name in (known_agents() if args.task == 'pipeline' else [data['task']])}
            data['agent_models'] = dict(agent_models)
            data['agent_routes'] = {name: route.model_dump() for name, route in routes.items()}
            for name, route in data['agent_routes'].items():
                if route['provider'] == 'modal-vllm' and route['modal']['app'].startswith('sandbox-vllm-route-'):
                    route_key = hashlib.sha256(json.dumps({'model': route['model'], 'gpu': args.gpu, 'vllm': route['vllm']}, sort_keys=True).encode()).hexdigest()[:8]
                    route['modal'].update(app=f'sandbox-vllm-{args.study}-{route_key}-{label}', gpu=args.gpu,
                                          max_containers=args.replicas or replicas)
                elif route['provider'] == 'modal-vllm' and args.design == 'sand42':
                    route['modal']['max_containers'] = replicas
                if name in data['agent_models']:
                    route['model'] = data['agent_models'][name]
            for setting in args.settings:
                _set(data, setting)
            try:
                # Unknown parameter names must fail rather than silently disappear.
                for section, model in [('engine', spec.engine), ('job', spec.job), ('trace', spec.trace), ('dataset', spec.dataset)]:
                    if set(data[section]) - set(type(model).model_fields):
                        raise ValueError(f'unknown {section} fields')
                result = RunSpec.model_validate(data)
                if result.job.mode != 'endpoint':
                    raise ValueError('experiment launch requires endpoint mode')
            except ValueError as exc:
                raise ServiceError(f'invalid experiment settings: {exc}') from exc
            generated.append(result)
    ids = [spec.run_id for spec in generated]
    if len(set(ids)) != len(ids):
        raise ServiceError('selected axes produce duplicate runs; remove --concurrency for the sand42 grid')
    try:
        plan = Plan(study=args.study, design=args.design, runs=[f'runs/{spec.run_id}.yaml' for spec in generated],
                    smoke_rows=args.smoke_rows, smoke_cost_cap_usd=args.smoke_cost_cap_usd)
    except ValueError as exc:
        raise ServiceError(f'invalid smoke settings: {exc}') from exc
    root.mkdir(parents=True)
    (root / 'runs').mkdir()
    for name, spec in zip(plan.runs, generated):
        (root / name).write_text(yaml.safe_dump(spec.model_dump(by_alias=True), sort_keys=False))
    manifest = root / 'experiment.yaml'
    manifest.write_text(yaml.safe_dump(plan.model_dump(by_alias=True), sort_keys=False))
    print(f'Created {manifest} ({len(generated)} runs; no downloads or paid actions).')
    print(f'Next: sandbox experiment preflight --config {manifest}')
    return 0


@contextmanager
def _environment(spec: RunSpec):
    """Use only reviewed deploy/model settings; restore the caller environment on exit."""
    overrides = spec_env(spec) if spec.engine.kind == 'modal-vllm' else {}
    overrides['VLLM_MODEL'] = spec.engine.model
    overrides['OBSERVABILITY_PROVIDER'] = spec.trace.sink if spec.trace.sink in {'langfuse', 'phoenix', 'none'} else 'none'
    overrides['OBSERVABILITY_ENVIRONMENT'] = spec.trace.environment
    if spec.engine.kind == 'modal-vllm' and os.environ.get('MODAL_VLLM_API_TOKEN'):
        overrides['VLLM_API_KEY'] = os.environ['MODAL_VLLM_API_TOKEN']
    if spec.engine.kind == 'modal-vllm' and spec.engine.modal:
        workspace = os.environ.get('MODAL_WORKSPACE', '').strip()
        if workspace:
            overrides['VLLM_BASE_URL'] = f'https://{workspace}--{spec.engine.modal.app}-serve.modal.run/v1'
    saved = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _prepare(path: Path, plan: Plan, runs: list[tuple[Path, RunSpec]]) -> list[RunStore]:
    from mailroom_sandbox.runtime import load_env_file
    load_env_file()
    stores = []
    paired = {}
    for config, spec in runs:
        with _environment(spec):
            report = preflight.preflight(spec, config_path=config, offline=spec.job.mock, live=False)
        if report.get('status') != 'prepared':
            raise ServiceError(f"preflight refused {spec.run_id}: {redact_urls(json.dumps(report))}")
        store = RunStore(run_dir(report['run_id']))
        lock = store.verify_generation()
        rows = store.dataset_rows()
        if not rows or (spec.dataset.limit and len(rows) != spec.dataset.limit):
            raise ServiceError(f'{spec.run_id}: requested {spec.dataset.limit} rows, prepared {len(rows)}; no spend authorized')
        fingerprint = hashlib.sha256(store.dataset_path.read_bytes()).hexdigest()
        if spec.task in paired and paired[spec.task] != fingerprint:
            raise ServiceError(f'{spec.task}: cells have different dataset bytes; paired comparison refused')
        paired[spec.task] = fingerprint
        if not spec.job.mock:
            from mailroom_sandbox.agent_routes import validate
            validate(spec.agent_routes, credentials=True)
            from mailroom_sandbox.job.spend import require_budget
            require_budget(lock)
            if _uses_default(spec) and spec.engine.kind == 'openrouter' and not os.environ.get('OPENROUTER_API_KEY', '').strip():
                raise ServiceError('set OPENROUTER_API_KEY before preparing an API experiment')
            if _uses_default(spec) and spec.engine.kind == 'modal-vllm' and not os.environ.get('MODAL_WORKSPACE', '').strip():
                raise ServiceError('experiment launch needs MODAL_WORKSPACE to address each scoped cell app')
            if spec.trace.sink != 'none':
                try:
                    from opentelemetry.sdk.trace import TracerProvider
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                except ImportError as exc:
                    raise ServiceError('selected trace sink requires pip install -e ".[observability]"') from exc
        _deployments(spec)
        stores.append(store)
    return stores


def _review(path: Path, plan: Plan, runs, stores=None) -> dict:
    rows = []
    for index, (config, spec) in enumerate(runs):
        with _environment(spec):
            settings = review_settings(stores[index]) if stores else spec.model_dump(by_alias=True)
        rows.append({'config': str(config), 'review': settings})
        rows[-1]['managed_deployments'] = [{'model': item.engine.model, 'modal': item.engine.modal.model_dump(),
            'vllm': item.engine.vllm.model_dump(), 'environment': spec_env(item)} for item in _deployments(spec)]
    return {'study': plan.study, 'design': plan.design, 'runs': rows,
            'smoke_rows_per_run': plan.smoke_rows, 'smoke_cost_cap_usd': plan.smoke_cost_cap_usd,
            'smoke_wall_seconds': plan.smoke_wall_seconds,
            'sum_run_and_smoke_caps_usd': sum(float(spec.job.cost_cap_usd or 0) + plan.smoke_cost_cap_usd for _, spec in runs),
            'spend': 'mock; no provider calls' if all(spec.job.mock for _, spec in runs) else 'Modal/OpenRouter: initials required before paid actions',
            'observer': f'sandbox experiment watch --config {path}',
            'reports': f'sandbox experiment report --config {path}'}


def _cmd_review(args) -> int:
    path, plan, runs = _load(args.config)
    print(redact_urls(json.dumps(_review(path, plan, runs), indent=2)))
    return 0


def _cmd_preflight(args) -> int:
    path, plan, runs = _load(args.config)
    stores = _prepare(path, plan, runs)
    print(redact_urls(json.dumps(_review(path, plan, runs, stores), indent=2)))
    print('Preflight prepared all locked datasets/prompts. No provider/deploy request made. Next: sandbox experiment launch --config ' + str(path))
    return 0


def _execute(store: RunStore) -> dict:
    from mailroom_sandbox import cli
    result = cli._run_endpoint(store, argparse.Namespace(watch=False, max_items=None))
    _atomic_write(store.dir / 'experiment-result.json', json.dumps({'generation_id': store.read_lock().get('generation_id'),
        'scores': result.get('scores', {}), 'summary': store.summary()}, default=str, indent=2))
    return result


def _smoke(spec: RunSpec, store: RunStore, plan: Plan) -> None:
    source = store.dir / 'smoke-input.jsonl'
    rows = store.dataset_rows()[:plan.smoke_rows]
    if spec.task == 'pipeline':
        counts = defaultdict(int)
        rows = []
        for row in store.dataset_rows():
            doc_class = row.get('expected_doc_class')
            if counts[doc_class] < plan.smoke_rows:
                rows.append(row)
                counts[doc_class] += 1
    _atomic_write(source, ''.join(json.dumps(row) + '\n' for row in rows))
    smoke = spec.model_copy(deep=True)
    smoke.run_id = spec.run_id[:53] + '-s' + hashlib.sha256(spec.run_id.encode()).hexdigest()[:8]
    smoke.dataset = DatasetSpec(provider='file', local_path=str(source), limit=len(rows))
    smoke.job.concurrency = min(spec.job.concurrency, len(rows))
    smoke.job.cost_cap_usd = min(float(spec.job.cost_cap_usd or plan.smoke_cost_cap_usd), plan.smoke_cost_cap_usd)
    smoke.job.max_wall_seconds = min(spec.job.max_wall_seconds or plan.smoke_wall_seconds, plan.smoke_wall_seconds)
    smoke.agent_knobs = copy.deepcopy((store.read_lock() or {}).get('agent_knobs') or {})
    report = preflight.preflight(smoke, offline=smoke.job.mock, live=False)
    if report.get('status') != 'prepared':
        raise ServiceError(f'smoke preflight refused: {report}')
    smoke_store = RunStore(run_dir(smoke.run_id))
    _execute(smoke_store)
    result = smoke_store.summary()
    # Whole-run summaries historically called every processed row successful;
    # the persisted per-document evidence is the authoritative smoke gate.
    if result.get('state') != 'done' or result.get('ok') != len(rows) or result.get('errors'):
        raise ServiceError(f'smoke failed for {spec.run_id}: {result}; full run was not started')
    store.append_event('experiment_smoke_passed', 'info', smoke_run_id=smoke.run_id, rows=len(rows))


def _route_model_ids(name: str, route, base: str, headers: dict[str, str], spec: RunSpec) -> list[str]:
    """Read ``/models`` for a route, waiting out a scale-to-zero boot.

    A managed Modal route holds the request open (minutes) while its container
    boots, so the old single 60 s GET failed verification and tore down a
    healthy app. Reuse the preflight boot budget; a refused connection still
    means a dead/wrong endpoint and fails fast.
    """
    import time

    import httpx

    budget_spec = spec.model_copy(deep=True)
    if route.provider == 'modal-vllm':
        budget_spec.engine.kind = 'modal-vllm'
    budget = preflight.probe_timeout_seconds(budget_spec)
    deadline = time.monotonic() + budget
    last_error: Exception | None = None
    while True:
        timeout = max(1.0, deadline - time.monotonic())
        try:
            models = httpx.get(base + '/models', headers=headers, timeout=timeout)
            models.raise_for_status()
            return [row.get('id') for row in models.json().get('data', [])]
        except httpx.ConnectError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise ServiceError(
                f'{name}: no /models response within the {budget:.0f}s probe budget: '
                + redact_urls(str(last_error))
            )
        time.sleep(1.0)


def _probe(spec: RunSpec) -> None:
    from mailroom_sandbox.health import probe_chat
    from mailroom_sandbox.overlay import load_profile
    if _uses_default(spec) and spec.engine.kind == 'modal-vllm':
        result = preflight.probe_engine(spec)
        if not result.get('ok'):
            raise ServiceError('engine verification failed: ' + redact_urls(json.dumps(result)))
    profile = load_profile(spec.profile)
    profile['default_model'] = spec.engine.model
    if _uses_default(spec):
        result = probe_chat(profile, timeout=60)
        if not result.ok:
            raise ServiceError('chat smoke failed: ' + redact_urls(result.detail))


    if spec.agent_routes:
        import httpx
        from mailroom_sandbox.agent_routes import endpoint, credential_env
        for name, route in spec.agent_routes.items():
            route = route.model_copy(deep=True)
            route.model = spec.agent_models.get(name) or route.model
            base = endpoint(route)
            key = os.environ.get(credential_env(route), '')
            headers = {'Authorization': f'Bearer {key}'} if key else {}
            try:
                if route.provider in {'modal-vllm', 'vllm'}:
                    ids = _route_model_ids(name, route, base, headers, spec)
                    if route.model not in ids:
                        raise ServiceError(f'{name}: endpoint does not serve {route.model}')
                response = httpx.post(base + '/chat/completions', headers=headers, timeout=60,
                    json={'model': route.model, 'messages': [{'role': 'user', 'content': 'Reply OK.'}], 'max_tokens': 8})
                response.raise_for_status()
                if not response.json().get('choices'):
                    raise ServiceError(f'{name}: chat smoke returned no choices')
            except (httpx.HTTPError, ValueError) as exc:
                raise ServiceError(f'{name}: route verification failed: {redact_urls(str(exc))}') from exc


def _uses_default(spec: RunSpec) -> bool:
    from mailroom_sandbox.agent_routes import known_agents
    agents = known_agents() if spec.task == 'pipeline' else {spec.task}
    return bool(agents - set(spec.agent_routes))


def _deployments(spec: RunSpec) -> list[RunSpec]:
    """Distinct managed engines in this cell, including per-agent Modal routes."""
    engines = []
    if _uses_default(spec) and spec.engine.kind == 'modal-vllm':
        engines.append(spec.model_copy(deep=True))
    for name, route in spec.agent_routes.items():
        if route.provider != 'modal-vllm':
            continue
        deployment = spec.model_copy(deep=True)
        deployment.profile = 'modal-vllm'
        deployment.engine.kind = 'modal-vllm'
        deployment.engine.model = (spec.agent_models or {}).get(name) or route.model
        deployment.engine.modal = route.modal.model_copy(deep=True)
        deployment.engine.vllm = route.vllm.model_copy(deep=True)
        engines.append(deployment)
    by_app = {}
    for engine in engines:
        app = engine.engine.modal.app
        if not app.startswith('sandbox-vllm-'):
            raise ServiceError('experiment apps must use a sandbox-vllm- scoped name')
        if app in by_app and spec_env(by_app[app]) != spec_env(engine):
            raise ServiceError(f'{app}: agents request incompatible models/parameters on one app')
        by_app[app] = engine
    return list(by_app.values())


def _deploy(spec: RunSpec) -> None:
    from mailroom_sandbox.services.modal_cli import INSTALL_HINT, PINNED_SDK, _is_deployed
    from mailroom_sandbox.services._exec import run_tool
    result = run_tool(['modal', '--version'], hint=INSTALL_HINT)
    if PINNED_SDK not in result.stdout:
        raise ServiceError(f'install verified Modal SDK {PINNED_SDK} before launching')
    commands = []
    if spec.engine.modal.prewarm:
        commands.append(['modal', 'run', 'deploy/modal_vllm.py::download_model'])
    commands.append(['modal', 'deploy', 'deploy/modal_vllm.py'])
    for command in commands:
        rc = stream_tool(command, cwd=repo_root(), hint=INSTALL_HINT)
        if rc:
            raise ToolFailed(command, rc)


def _teardown(spec: RunSpec) -> None:
    from mailroom_sandbox.services.modal_cli import _cmd_stop
    _cmd_stop(argparse.Namespace(app=spec.engine.modal.app, dry_run=False, no_verify=False))


def _cmd_launch(args) -> int:
    import fcntl
    from itertools import groupby
    from mailroom_sandbox.runtime import load_env_file
    load_env_file()
    path, plan, runs = _load(args.config)
    # Prevent two local launchers from spending against the same campaign.
    with (path.parent / '.launch.lock').open('a') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ServiceError('this experiment already has an active launcher') from exc
        stores = _prepare(path, plan, runs)
        review = _review(path, plan, runs, stores)
        workflow = {'plan_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'configs': {str(config): hashlib.sha256(config.read_bytes()).hexdigest() for config, _ in runs},
                    'smoke_rows': plan.smoke_rows, 'smoke_cost_cap_usd': plan.smoke_cost_cap_usd,
                    'smoke_wall_seconds': plan.smoke_wall_seconds}
        print(redact_urls(json.dumps(review, indent=2)), file=sys.stderr)
        if not all(spec.job.mock for _, spec in runs):
            initials = args.initials
            if initials is None:
                if not sys.stdin.isatty():
                    raise ServiceError('review every setting above and sign --initials YOUR_INITIALS; no paid action started')
                try:
                    initials = input('I reviewed ALL cells, samples, settings, caps and smoke costs and authorize Modal/OpenRouter spend. Sign initials (blank cancels): ')
                except (EOFError, KeyboardInterrupt) as exc:
                    raise ServiceError('authorization cancelled; no paid action started') from exc
            for (_, spec), store in zip(runs, stores):
                with _environment(spec):
                    authorize(store, initials=initials, extra=workflow)
        marker = path.parent / 'current-run'
        def group_key(pair):
            _, spec = pair[0]
            return json.dumps([spec_env(item) for item in _deployments(spec)], sort_keys=True)
        try:
            for _, group in groupby(zip(runs, stores), key=group_key):
                group = list(group)
                pending = []
                for entry in group:
                    store = entry[1]
                    status = store.summary()
                    if status.get('state') == 'done':
                        if status.get('errors') or status.get('ok') != len(store.dataset_rows()):
                            raise ServiceError(f'{store.run_id}: terminal evidence is incomplete; investigate before resetting/retrying')
                    else:
                        pending.append(entry)
                if not pending:
                    continue
                group = pending
                first = group[0][0][1]
                with _environment(first):
                    owned = []
                    try:
                        if not first.job.mock:
                            from mailroom_sandbox.services.modal_cli import _is_deployed
                            for deployment in _deployments(first):
                                if _is_deployed(deployment.engine.modal.app):
                                    raise ServiceError(f'{deployment.engine.modal.app} already deployed; no ownership taken')
                                owned.append(deployment)
                                with _environment(deployment):
                                    _deploy(deployment)
                        for (_, spec), store in group:
                            _atomic_write(marker, store.run_id + '\n')
                            if store.summary().get('state') == 'done':
                                continue
                            if not spec.job.mock:
                                _probe(spec)
                            _smoke(spec, store, plan)
                            _execute(store)
                            summary = store.summary()
                            if summary.get('state') != 'done' or summary.get('errors') or summary.get('ok') != len(store.dataset_rows()):
                                raise ServiceError(f'{spec.run_id} incomplete or failed: {summary}; later jobs were not started')
                    finally:
                        failures = []
                        for deployment in reversed(owned):
                            try:
                                with _environment(deployment):
                                    _teardown(deployment)
                            except Exception as exc:
                                failures.append(str(exc))
                        if failures:
                            cause = sys.exc_info()[1]
                            prefix = f'{cause}; ' if cause else ''
                            raise ServiceError(prefix + 'teardown failed: ' + '; '.join(failures))
        finally:
            _write_report(path, plan, runs)
    return 0


def _write_report(path: Path, plan: Plan, runs) -> dict:
    rows = []
    paired = defaultdict(list)
    for config, spec in runs:
        store = RunStore(run_dir(spec.run_id))
        if not store.read_lock():
            rows.append({'run_id': spec.run_id, 'state': 'not prepared', 'expected': spec.dataset.limit})
            continue
        store.verify_generation()
        summary = store.summary()
        summary['expected'] = len(store.dataset_rows())
        summary['task'] = spec.task
        summary['mock'] = spec.job.mock
        summary['config'] = str(config)
        summary['model'] = spec.engine.model
        summary['gpu'] = spec.engine.modal.gpu if spec.engine.modal else None
        summary['replicas'] = spec.engine.modal.max_containers if spec.engine.modal else None
        summary['concurrency'] = spec.job.concurrency
        summary['dataset_sha256'] = hashlib.sha256(store.dataset_path.read_bytes()).hexdigest()
        saved = store.dir / 'experiment-result.json'
        if saved.is_file():
            result = json.loads(saved.read_text())
            if result.get('generation_id') == store.read_lock().get('generation_id'):
                summary['scorer_aggregates'] = result.get('scores', {})
        # Summarize existing scorer outputs, without defining a new scoring engine.
        scores = defaultdict(list)
        for item in store.load_items():
            for key, value in (item.get('score') or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    scores[key].append(value)
        summary['stored_score_means'] = {key: sum(values)/len(values) for key, values in scores.items()}
        rows.append(summary)
        paired[spec.task].append(hashlib.sha256(store.dataset_path.read_bytes()).hexdigest())
    complete = all(row.get('state') == 'done' and row.get('ok') == row.get('expected') and not row.get('errors') for row in rows)
    report = {'schema': 'sandbox.experiment-report/v1', 'study': plan.study, 'complete': complete,
              'paired_dataset_bytes': all(len(set(values)) == 1 for values in paired.values()), 'runs': rows}
    comparisons = []
    baseline = {}
    for row in rows:
        if row.get('state') != 'done' or row.get('ok') != row.get('expected') or row.get('errors'):
            continue
        key = row.get('task')
        if key not in baseline:
            baseline[key] = row
            continue
        ref = baseline[key]
        if ref['dataset_sha256'] != row['dataset_sha256']:
            continue
        comparisons.append({'reference': ref['run_id'], 'run': row['run_id'], 'paired_n': row['ok'],
            'stored_score_mean_deltas': {metric: value-ref['stored_score_means'][metric]
                for metric, value in row['stored_score_means'].items() if metric in ref['stored_score_means']}})
    report['comparisons'] = comparisons
    _atomic_write(path.parent / 'report.json', json.dumps(report, indent=2, sort_keys=True))
    lines = [f'# {plan.study}', '', f'Complete: {complete}; paired dataset bytes: {report["paired_dataset_bytes"]}.', '',
             '| Run | State | Successful / expected | Errors |', '| --- | --- | --- | --- |']
    for row in rows:
        lines.append(f'| {row["run_id"]} | {row["state"]} | {row.get("ok", 0)} / {row.get("expected")} | {row.get("errors", 0)} |')
    lines += ['', 'Per-run scorer metrics and configuration links are in report.json; native quality/serving reports remain under reports/.',
              'A completed mock run validates orchestration only. Failed/missing documents are never counted as successful observations.', '']
    _atomic_write(path.parent / 'report.md', '\n'.join(lines))
    print(f'Report: {path.parent / "report.md"}')
    return report


def _cmd_report(args) -> int:
    path, plan, runs = _load(args.config)
    report = _write_report(path, plan, runs)
    return 0 if report['complete'] else 1


def _cmd_watch(args) -> int:
    from mailroom_sandbox import cli
    path, plan, runs = _load(args.config)
    marker = path.parent / 'current-run'
    if not marker.is_file():
        _atomic_write(marker, runs[0][1].run_id + '\n')
    return cli.main(['watch', '--web', '--follow', str(marker), *(['--no-browser'] if args.no_browser else [])])


def register(sub, leaf) -> None:
    group = sub.add_parser('experiment', parents=[leaf], help='design → paired sample → preflight → initials → smoke → launch → reports')
    commands = group.add_subparsers(dest='experiment_cmd')
    catalog = commands.add_parser('designs', help='list experiment designs and parameter selectors')
    catalog.set_defaults(handler=lambda args: print(json.dumps({'designs': DESIGNS, 'document_classes': CLASSES,
        'models': 'sandbox modal-matrix list', 'parameters': 'experiment create --help; --set engine.vllm.<name>=value'}, indent=2)) or 0)
    create = commands.add_parser('create', parents=[leaf], help='write a reviewable experiment; no Hub/provider calls')
    create.add_argument('study')
    create.add_argument('--task', choices=['specialists', 'pipeline', 'sorter'], default='specialists')
    create.add_argument('--agent-route', action='append', dest='agent_routes', default=[], metavar='NAME=PROVIDER:MODEL', help='per-agent provider/model; NAME=@route.yaml includes endpoint/GPU/vLLM settings')
    create.add_argument('--design', choices=DESIGNS, default='single')
    create.add_argument('--doc-class', action='append', choices=CLASSES)
    create.add_argument('--samples', type=int, default=50, help='documents per selected class, shared across every cell')
    create.add_argument('--seed', type=int, default=42)
    create.add_argument('--subclass', action='append', help='restrict the draw to corpus subclass tokens (repeatable)')
    create.add_argument('--dataset', default='Lucius-Morningstar/mailroom-dataset')
    create.add_argument('--dataset-config', default='ground_truth')
    create.add_argument('--split', default='all')
    create.add_argument('--revision', default=FAMILY_HF_REVISION)
    create.add_argument('--local-dataset', default=None, help='local JSONL instead of Hub (also useful for offline mock checks)')
    create.add_argument('--provider', choices=['modal-vllm', 'openrouter'], default='modal-vllm')
    create.add_argument('--gpu', default='L4', help='Modal GPU class, optionally :N for tensor parallel')
    create.add_argument('--replicas', type=int, default=None, help='override cell replica count')
    create.add_argument('--concurrency', type=int, default=None)
    create.add_argument('--max-tokens', type=int, default=8192)
    create.add_argument('--temperature', type=float, default=0.1)
    create.add_argument('--trace-sink', choices=['langfuse', 'otlp', 'phoenix', 'none'], default='langfuse')
    create.add_argument('--trace-endpoint', default=None)
    create.add_argument('--cost-cap-usd', type=float, default=1.0, help='per-run estimated GPU cap, reviewed before spend')
    create.add_argument('--max-wall-seconds', type=int, default=2400)
    create.add_argument('--smoke-rows', type=int, default=1)
    create.add_argument('--smoke-cost-cap-usd', type=float, default=0.10)
    create.add_argument('--mock', action='store_true', help='create an offline mock experiment; never deploys/calls providers')
    create.add_argument('--set', action='append', dest='settings', default=[], metavar='PATH=YAML_VALUE')
    create.add_argument('--output', default=None)
    create.set_defaults(handler=_create)
    for name, handler in [('review', _cmd_review), ('preflight', _cmd_preflight), ('launch', _cmd_launch), ('watch', _cmd_watch), ('report', _cmd_report)]:
        parser = commands.add_parser(name, parents=[leaf])
        parser.add_argument('--config', required=True, help='experiment.yaml created by experiment create')
        if name == 'launch':
            parser.add_argument('--initials', default=None, help='sign the displayed full configuration and spend review')
        if name == 'watch':
            parser.add_argument('--no-browser', action='store_true')
        parser.set_defaults(handler=handler)
    group.set_defaults(handler=lambda args: print('Use: sandbox experiment designs | create | review | preflight | launch | watch | report') or 0)
