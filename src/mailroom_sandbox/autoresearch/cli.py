"""``sandbox autoresearch plan|step|run|status|holdout``."""
from __future__ import annotations

import json
from typing import Any


def _loop(args, *, need_executor: bool):
    from mailroom_sandbox.autoresearch.loop import CliExecutor, Loop, Study

    from mailroom_sandbox.autoresearch.loop import AutoresearchError

    study = Study.load(args.study)
    initials = getattr(args, "initials", None)
    if need_executor and not study.mock and not (initials or "").strip():
        # Before any network call: a paid study never starts without a human's initials.
        raise AutoresearchError(f"study {study.study!r} is a paid run: pass --initials XX (2-6 letters, yours; never defaulted)")
    executor = CliExecutor(initials=initials) if need_executor else None
    return Loop(study, executor)


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
    print(f"next lever: {out.get('lever')}  (attached to {out.get('attached_to')})" if "lever" in out else "")
    print(f"spent {out['spent_usd']} USD; consecutive reverts {out['consecutive_reverts']}")
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
    print(json.dumps(_loop(args, need_executor=False).status(), indent=2, default=str))
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
    p.add_argument("--json", action="store_true")
    add("step", _step, "run the baseline if missing, then one candidate round", initials=True)
    p = add("run", _run, "run candidate rounds until budget, levers or consecutive reverts stop it", initials=True)
    p.add_argument("--max-rounds", type=int, default=3, metavar="N", help="candidate rounds to run in this call (default 3)")
    add("status", _status, "ledger summary: kept, reverted, spend, champion")
    add("holdout", _holdout, "confirm the champion once on a draw disjoint from the dev draw", initials=True)
    group.set_defaults(handler=lambda args: group.print_help() or 0)
