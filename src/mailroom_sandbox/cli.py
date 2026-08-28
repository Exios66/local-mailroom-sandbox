"""CLI: sandbox up/down/health/pilot/eval/matrix/..."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from mailroom_sandbox.overlay import list_profiles, load_profile
from mailroom_sandbox.paths import repo_root, vendor_dir
from mailroom_sandbox.runtime import activate, resolve_mailroom_src


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    return int(args.handler(args) or 0)


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--profile", default=os.environ.get("SANDBOX_PROFILE") or "ollama")
    shared.add_argument("--model", default=None, help="Override every agent's model tag")
    shared.add_argument("--prompt", default=None, help="Local prompt variant stem (e.g. sorter_local_v0)")
    shared.add_argument(
        "--agent-model",
        action="append",
        default=[],
        dest="agent_models",
        metavar="NAME=TAG",
        help="Surgical per-agent model override (repeatable)",
    )

    parser = argparse.ArgumentParser(
        prog="sandbox",
        description="Local-first LLM-Mailroom experiment sandbox.",
        parents=[shared],
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("up", help="Start compose profiles (langfuse + provider)", parents=[shared])
    p.add_argument("--compose-profile", action="append", dest="compose_profiles")
    p.add_argument("-d", "--detach", action="store_true", default=True)
    p.set_defaults(handler=_cmd_up)

    p = sub.add_parser("down", help="Stop compose stack", parents=[shared])
    p.add_argument("--compose-profile", action="append", dest="compose_profiles")
    p.set_defaults(handler=_cmd_down)

    p = sub.add_parser("health", help="Probe the active provider + Langfuse", parents=[shared])
    p.set_defaults(handler=_cmd_health)

    p = sub.add_parser("pull-models", help="Pull Ollama (or listed) weights", parents=[shared])
    p.add_argument("models", nargs="*")
    p.set_defaults(handler=_cmd_pull_models)

    p = sub.add_parser("fetch-deps", help="Clone llm-mailroom @ v0.5.0 into vendor/", parents=[shared])
    p.add_argument("--entity", action="store_true", help="Also clone llm-entity-extraction")
    p.add_argument("--visualizer", action="store_true", help="Also clone The-Mailroom (Langfuse observer)")
    p.set_defaults(handler=_cmd_fetch_deps)

    p = sub.add_parser("cutover", help="Show effective agent→provider/model assignments", parents=[shared])
    p.set_defaults(handler=_cmd_cutover)

    agents_p = sub.add_parser("agents", help="List or show pipeline agents", parents=[shared])
    agents_sub = agents_p.add_subparsers(dest="agents_cmd")
    al = agents_sub.add_parser("list", parents=[shared])
    al.set_defaults(handler=_cmd_agents_list)
    ash = agents_sub.add_parser("show", parents=[shared])
    ash.add_argument("name")
    ash.set_defaults(handler=_cmd_agents_show)
    agents_p.set_defaults(handler=_cmd_agents_list)

    pipe = sub.add_parser("pipeline", help="Run mailroom watcher or API", parents=[shared])
    pipe_sub = pipe.add_subparsers(dest="pipeline_cmd")
    w = pipe_sub.add_parser("watcher", parents=[shared])
    w.set_defaults(handler=_cmd_watcher)
    a = pipe_sub.add_parser("api", parents=[shared])
    a.set_defaults(handler=_cmd_api)

    p = sub.add_parser("pilot", help="Run the fixture pilot (--mock or --local)", parents=[shared])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--mock", action="store_true", default=False)
    g.add_argument("--local", action="store_true", default=False)
    p.add_argument("--sample", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=_cmd_pilot)

    p = sub.add_parser("hf-pilot", help="HF docclass mini-pilot", parents=[shared])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--mock", action="store_true")
    g.add_argument("--local", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=_cmd_hf_pilot)

    p = sub.add_parser("legalbench", help="LegalBench Yes/No fixture harness", parents=[shared])
    p.add_argument("--task", default="contract_qa")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--n", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=_cmd_legalbench)

    from mailroom_sandbox.eval.agents import EVAL_TASKS

    p = sub.add_parser("eval", help="Run a scoring eval (isolated agent or connected pipeline)", parents=[shared])
    p.add_argument("task", choices=tuple(EVAL_TASKS))
    p.add_argument("--mock", action="store_true", default=False)
    p.add_argument("--local", action="store_true", default=False)
    p.add_argument("--sample", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--name", dest="experiment_name")
    p.add_argument(
        "--connected",
        action="store_true",
        default=False,
        help="Score class + stage + extraction + routing (pipeline default; flag is accepted on pipeline)",
    )
    p.add_argument(
        "--from-log",
        action="store_true",
        dest="from_log",
        help="For local_vs_api: compare experiment_log.jsonl instead of serving fixtures",
    )
    p.set_defaults(handler=_cmd_eval)

    p = sub.add_parser("matrix", help="provider × model × prompt grid", parents=[shared])
    p.add_argument("--task", default="sorter")
    p.add_argument("--providers", default="ollama")
    p.add_argument("--models", default="qwen3:8b")
    p.add_argument("--prompts", default="mailroom-default")
    p.add_argument("--sample", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--mock", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=_cmd_matrix)

    p = sub.add_parser("datasets", help="Dataset helpers", parents=[shared])
    ds = p.add_subparsers(dest="datasets_cmd")
    pull = ds.add_parser("pull", parents=[shared])
    pull.add_argument("--dataset", default="Lucius-Morningstar/docclass-merged")
    pull.add_argument("--max-rows", type=int, default=50)
    pull.set_defaults(handler=_cmd_datasets_pull)
    prep = ds.add_parser(
        "prepare",
        help="Load/clean fixtures into data/runtime/prepared/ (offline, no network)",
        parents=[shared],
    )
    prep.set_defaults(handler=_cmd_datasets_prepare)
    p.set_defaults(handler=_cmd_datasets_help)

    p = sub.add_parser("traces", help="Trace helpers", parents=[shared])
    tr = p.add_subparsers(dest="traces_cmd")
    exp = tr.add_parser("export", parents=[shared])
    exp.set_defaults(handler=_cmd_traces_export)
    p.set_defaults(handler=_cmd_traces_help)

    p = sub.add_parser("profiles", help="List provider profiles", parents=[shared])
    p.set_defaults(handler=_cmd_profiles)

    return parser


def _agent_models(args: argparse.Namespace) -> dict[str, str]:
    from mailroom_sandbox.overlay import parse_agent_models

    return parse_agent_models(getattr(args, "agent_models", None) or [])


def _print(obj: object) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(obj)


def _cmd_up(args: argparse.Namespace) -> int:
    from mailroom_sandbox.compose import default_profiles_for, run_compose

    profiles = args.compose_profiles or default_profiles_for(args.profile)
    extra = ["up", "-d"] if args.detach else ["up"]
    run_compose(profiles, *extra)
    return 0


def _cmd_down(args: argparse.Namespace) -> int:
    from mailroom_sandbox.compose import default_profiles_for, run_compose

    profiles = args.compose_profiles or default_profiles_for(args.profile)
    run_compose(profiles, "down")
    return 0


def _cmd_health(args: argparse.Namespace) -> int:
    from mailroom_sandbox.health import health_check, probe_models
    from mailroom_sandbox.overlay import load_profile as _lp

    result = health_check(args.profile)
    host = os.environ.get("LANGFUSE_HOST") or "http://localhost:3000"
    langfuse = probe_models(
        {
            "name": "langfuse",
            "base_url": host,
            "health": {"models_url": f"{host.rstrip('/')}/api/public/health"},
        }
    )
    result["langfuse"] = langfuse.as_dict()
    phoenix = probe_models(
        {
            "name": "phoenix",
            "base_url": os.environ.get("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces").rsplit("/v1", 1)[0],
            "health": {"models_url": "http://localhost:6006/healthz"},
        }
    )
    result["phoenix"] = phoenix.as_dict()
    _print(result)
    return 0 if result.get("ok") else 1


def _cmd_pull_models(args: argparse.Namespace) -> int:
    from mailroom_sandbox.compose import pull_ollama_models

    profile = load_profile(args.profile)
    models = list(args.models) or list(profile.get("pull_models") or [])
    return pull_ollama_models(models)


def _cmd_fetch_deps(args: argparse.Namespace) -> int:
    vendor_dir().mkdir(parents=True, exist_ok=True)
    rc = _clone(
        "https://github.com/Exios66/llm-mailroom.git",
        vendor_dir() / "llm-mailroom",
        "v0.5.0",
    )
    if args.entity:
        rc = rc or _clone(
            "https://github.com/Exios66/llm-entity-extraction.git",
            vendor_dir() / "llm-entity-extraction",
            "v0.20.0",
        )
    if getattr(args, "visualizer", False):
        dest = vendor_dir() / "The-Mailroom"
        if dest.is_dir() and (dest / ".git").exists():
            subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"], check=False)
        else:
            rc = rc or subprocess.run(
                ["git", "clone", "--depth", "1", "https://github.com/Exios66/The-Mailroom.git", str(dest)]
            ).returncode
    return rc


def _clone(url: str, dest: Path, tag: str) -> int:
    if dest.is_dir() and (dest / ".git").exists():
        subprocess.run(["git", "-C", str(dest), "fetch", "--tags"], check=False)
        return subprocess.run(["git", "-C", str(dest), "checkout", tag], check=False).returncode
    dest.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(["git", "clone", "--branch", tag, "--depth", "1", url, str(dest)]).returncode


def _cmd_cutover(args: argparse.Namespace) -> int:
    activation = activate(
        args.profile,
        model=args.model,
        prompt_variant=args.prompt,
        agent_models=_agent_models(args),
    )
    print(f"profile={activation.profile_name} taxonomy={activation.taxonomy_path}")
    print(f"{'Agent':<35} {'Provider':<15} {'Model'}")
    print("-" * 80)
    for name, provider, model in activation.assignments:
        print(f"{name:<35} {provider:<15} {model}")
    return 0


def _cmd_agents_list(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.agents import RETIRED_AGENTS, SPECS
    from mailroom_sandbox.overlay import agent_roster, load_yaml

    activation = activate(
        args.profile,
        model=args.model,
        prompt_variant=args.prompt,
        agent_models=_agent_models(args),
    )
    roster = agent_roster(load_yaml(activation.taxonomy_path))
    evals = sorted(SPECS)
    _print(
        {
            "profile": activation.profile_name,
            "agents": roster,
            "eval_tasks": evals,
            "retired": list(RETIRED_AGENTS),
        }
    )
    return 0


def _cmd_agents_show(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.agents import SPECS
    from mailroom_sandbox.overlay import agent_roster, load_yaml

    activation = activate(
        args.profile,
        model=args.model,
        prompt_variant=args.prompt,
        agent_models=_agent_models(args),
    )
    roster = {row["agent"]: row for row in agent_roster(load_yaml(activation.taxonomy_path))}
    spec = SPECS.get(args.name)
    payload = roster.get(args.name, {"agent": args.name, "enabled": False})
    if spec:
        payload["observation"] = spec.observation
        payload["eval_task"] = spec.name
        payload["dojo_profile"] = spec.dojo_profile
    _print(payload)
    return 0


def _mailroom_env() -> dict[str, str]:
    env = os.environ.copy()
    parts = [str(repo_root() / "src")]
    src = resolve_mailroom_src()
    if src is not None:
        parts.insert(0, str(src))
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(parts + ([existing] if existing else []))
    env.setdefault("OBSERVABILITY_ENVIRONMENT", os.environ.get("OBSERVABILITY_ENVIRONMENT") or "pilot")
    return env


def _cmd_watcher(args: argparse.Namespace) -> int:
    activate(args.profile, model=args.model, prompt_variant=args.prompt, agent_models=_agent_models(args))
    return subprocess.call([sys.executable, "-m", "pipeline.watcher"], env=_mailroom_env())


def _cmd_api(args: argparse.Namespace) -> int:
    activate(args.profile, model=args.model, prompt_variant=args.prompt, agent_models=_agent_models(args))
    return subprocess.call([sys.executable, "-m", "api.main"], env=_mailroom_env())


def _cmd_pilot(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.runners import run_pipeline_eval

    mock = args.mock or not args.local
    os.environ["SANDBOX_RUN_MODE"] = "mock" if mock else "local"
    result = run_pipeline_eval(
        mock=mock,
        sample=args.sample,
        dry_run=args.dry_run,
        experiment_name="sandbox_pilot",
        profile=args.profile,
        model=args.model,
        prompt_version=args.prompt,
    )
    _print(result)
    return 0


def _cmd_hf_pilot(args: argparse.Namespace) -> int:
    from mailroom_sandbox.datasets import load_hf_fixtures

    rows = load_hf_fixtures()
    if args.check or args.dry_run:
        _print({"ok": True, "n": len(rows), "classes": sorted({r.get("doc_type") for r in rows})})
        return 0 if rows else 1
    from mailroom_sandbox.eval.runners import run_sorter_eval

    mock = args.mock or not args.local
    result = run_sorter_eval(
        mock=mock,
        sample=len(rows) or None,
        experiment_name="sandbox_hf_pilot",
        profile=args.profile,
        model=args.model,
        prompt_version=args.prompt,
    )
    _print(result)
    return 0


def _cmd_legalbench(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.runners import run_legalbench_eval

    mock = args.mock or not args.local
    result = run_legalbench_eval(
        mock=mock,
        sample=args.n,
        dry_run=args.dry_run,
        experiment_name=f"sandbox_legalbench_{args.task}",
        profile=args.profile,
        model=args.model,
    )
    _print(result)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval import runners
    from mailroom_sandbox.eval.agents import SPECS

    mock = args.mock or not args.local
    os.environ["SANDBOX_RUN_MODE"] = "mock" if mock else "local"
    kwargs = {
        "mock": mock,
        "sample": args.sample,
        "dry_run": args.dry_run,
        "experiment_name": args.experiment_name or f"sandbox_{args.task}",
        "profile": args.profile,
        "model": args.model,
        "agent_models": _agent_models(args),
    }
    if args.task in SPECS:
        result = runners.run_isolated_eval(args.task, prompt_version=args.prompt, **kwargs)
    elif args.task == "pipeline":
        result = runners.run_pipeline_eval(
            prompt_version=args.prompt, connected=True, **kwargs
        )
    elif args.task == "extract":
        result = runners.run_extract_eval(prompt_version=args.prompt, **kwargs)
    elif args.task == "chained":
        result = runners.run_chained_eval(prompt_version=args.prompt, **kwargs)
    elif args.task == "local_vs_api":
        result = runners.run_local_vs_api_eval(
            prompt_version=args.prompt,
            from_log=bool(getattr(args, "from_log", False)),
            **kwargs,
        )
    else:
        result = runners.run_legalbench_eval(**kwargs)
    _print(result)
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.matrix import run_matrix

    mock = args.mock or not args.local
    result = run_matrix(
        task=args.task,
        providers=[p.strip() for p in args.providers.split(",") if p.strip()],
        models=[m.strip() for m in args.models.split(",") if m.strip()],
        prompts=[x.strip() for x in args.prompts.split(",") if x.strip()],
        sample=args.sample,
        seed=args.seed,
        mock=mock,
        dry_run=args.dry_run,
    )
    _print(result)
    return 0


def _cmd_datasets_help(args: argparse.Namespace) -> int:
    print("Use: sandbox datasets pull | sandbox datasets prepare")
    return 0


def _cmd_datasets_pull(args: argparse.Namespace) -> int:
    from mailroom_sandbox.datasets import pull_hf_dataset

    path = pull_hf_dataset(args.dataset, max_rows=args.max_rows)
    print(path)
    return 0


def _cmd_datasets_prepare(args: argparse.Namespace) -> int:
    from mailroom_sandbox.prep import prepare_offline_datasets

    activate(args.profile, model=args.model, prompt_variant=args.prompt, agent_models=_agent_models(args))
    summary = prepare_offline_datasets()
    _print(summary)
    return 0 if summary.get("counts", {}).get("fixtures", 0) else 1


def _cmd_traces_help(args: argparse.Namespace) -> int:
    print("Use: sandbox traces export")
    return 0


def _cmd_traces_export(args: argparse.Namespace) -> int:
    from mailroom_sandbox.eval.tracing import export_traces

    print(export_traces())
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    _print(list_profiles())
    return 0


if __name__ == "__main__":
    sys.exit(main())
