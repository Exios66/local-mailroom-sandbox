"""``sandbox autoresearch plan|step|run|status|holdout``."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {n}")
    return n


def _loop(args, *, need_executor: bool):
    from mailroom_sandbox.autoresearch.loop import CliExecutor, Loop, Study

    from mailroom_sandbox.autoresearch.loop import AutoresearchError

    ignored = [flag for flag, value in (("--model", _override_given(args, "model", "--model", "--mo")),
                                        ("--prompt", _override_given(args, "prompt", "--prompt", "--prom")),
                                        ("--agent-model", _override_given(args, "agent_models", "--agent-model", "--a")),
                                        ("--profile", _profile_given(args))) if value]
    if ignored:
        # The study's frozen run spec sets every model and prompt; a shared override would be accepted and not take effect.
        raise AutoresearchError(f"autoresearch does not apply {', '.join(ignored)}: the study's base run spec sets the "
                                "provider, models and prompts (edit its `agent_models` / `agent_routes`, or add a lever)")
    study = Study.load(args.study)
    initials = getattr(args, "initials", None)
    if need_executor and not study.mock and not (initials or "").strip():
        # Before any network call: a paid study never starts without a human's initials.
        raise AutoresearchError(f"study {study.study!r} is a paid run: pass --initials XX (2-6 letters, yours; never defaulted)")
    executor = CliExecutor(initials=initials) if need_executor else None
    return Loop(study, executor)


def _typed(raw, flag: str, shortest: str) -> bool:
    """Whether ``flag`` (or an abbreviation of at least ``shortest``, as argparse accepts) is among ``raw``."""
    names = (tok.split("=", 1)[0] for tok in raw if tok.startswith("--"))
    return any(len(name) >= len(shortest) and flag.startswith(name) for name in names)


def _override_given(args, dest: str, flag: str, shortest: str) -> bool:
    """Whether a shared ``--model`` / ``--prompt`` / ``--agent-model`` override reached this command.

    With the raw arguments (``main`` sets them from what the operator typed) a value the TUI shell injected as a
    session default does not count: the shell prepends it to every command, so refusing it would refuse every
    autoresearch command typed in ``sandbox tui``. Without them, any value counts.
    """
    raw = getattr(args, "raw_argv", None)
    value = getattr(args, dest, None)
    return bool(value) and (raw is None or _typed(raw, flag, shortest))


def _profile_given(args) -> bool:
    """Whether ``--profile`` was typed: argparse always fills in its default, so read the raw arguments."""
    raw = getattr(args, "raw_argv", None)
    if raw is None:   # called without `main` (no raw arguments): only a non-default value shows an override
        from mailroom_sandbox.providers import default_profile

        return bool(getattr(args, "profile", None)) and args.profile != default_profile()
    # Any unambiguous abbreviation argparse accepts (`--prof`, `--profile=x`) counts too.
    return _typed(raw, "--profile", "--prof")


def _guarded(fn):
    def handler(args) -> int:
        from mailroom_sandbox.autoresearch.levers import LeverError
        from mailroom_sandbox.autoresearch.loop import AutoresearchError
        from mailroom_sandbox.cli import CLIUsageError

        try:
            return int(fn(args) or 0)
        except (AutoresearchError, LeverError) as exc:
            raise CLIUsageError(str(exc)) from None

    return handler


def _show(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        d = r.get("delta") or {}
        delta = f" delta {d['mean']:+.3f} [{d['ci_low']:+.3f}, {d['ci_high']:+.3f}]" if d else ""
        print(f"  {r.get('decision'):8} {r.get('lever')}{delta}  {'; '.join(r.get('reasons') or [])[:160]}")


def _plan(args) -> int:
    out = _loop(args, need_executor=False).plan()
    if args.json:
        print(json.dumps({k: v for k, v in out.items() if k != "weakness_md"}, indent=2, default=str))
        return 0
    print(out.get("weakness_md") or f"next: {out.get('next')}")
    if out.get("weakness_md") and out.get("next"):
        print(f"next: {out['next']}")
    print(f"next lever: {out.get('lever')}  (attached to {out.get('attached_to')})" if "lever" in out else "")
    print(f"spent {out['spent_usd']} USD; consecutive reverts {out['consecutive_reverts']}; "
          f"noise floor {out['noise_floor'] if out['noise_floor'] is not None else 'not measured (the replicate runs first)'}")
    return 0


def _step(args) -> int:
    result = _loop(args, need_executor=True).step()
    _show(result.rows)
    if result.stop:
        print(f"stop: {result.stop}")
    return 0


def _run(args) -> int:
    rows, stop = _loop(args, need_executor=True).run(args.max_rounds)
    _show(rows)
    print(f"stop: {stop}")
    return 0


def _status(args) -> int:
    status = _loop(args, need_executor=False).status()
    if status.get("message"):
        print(status["message"], file=sys.stderr)
    print(json.dumps(status, indent=2, default=str))
    return 0


def _holdout(args) -> int:
    row = _loop(args, need_executor=True).holdout()
    m = row.get("metrics") or {}
    print(f"holdout {row['run_id']}: n={m.get('n')} mean utility {m.get('mean_utility')} outcomes {m.get('outcomes')}")
    return 0


def register(sub, leaf) -> None:
    group = sub.add_parser("autoresearch", parents=[leaf],
                           help="greedy config-only search: diagnose, one lever per round, paired bootstrap, keep or revert")
    cmds = group.add_subparsers(dest="autoresearch_cmd")

    def add(name: str, handler, help_text: str, *, initials: bool = False):
        p = cmds.add_parser(name, parents=[leaf], help=help_text)
        p.add_argument("--study", required=True, metavar="PATH", help="study file (schema sandbox.autoresearch/v1)")
        if initials:
            p.add_argument("--initials", default=None, metavar="XX",
                           help="your 2-6 capital-letter initials; required for a paid (non-mock) study, never defaulted")
        p.set_defaults(handler=_guarded(handler))
        return p

    p = add("plan", _plan, "show the champion's weakness table and the next lever; runs nothing")
    p.add_argument("--json", action="store_true", help="print the plan as JSON (without the weakness table text) instead of text")
    add("step", _step, "run the baseline if missing, then one candidate round", initials=True)
    p = add("run", _run, "run candidate rounds until budget, levers or consecutive reverts stop it", initials=True)
    p.add_argument("--max-rounds", type=_positive_int, default=3, metavar="N", help="candidate rounds to run in this call (default 3)")
    add("status", _status, "ledger summary: kept, reverted, spend, champion")
    add("holdout", _holdout, "confirm the champion once on a draw disjoint from the dev draw", initials=True)
    group.set_defaults(handler=lambda args: group.print_help() or 0)
