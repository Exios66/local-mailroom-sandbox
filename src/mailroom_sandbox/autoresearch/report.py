"""``report.md``: the study report (ledger, cost split, kept levers, production parity)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mailroom_sandbox.autoresearch import parity

if TYPE_CHECKING:  # pragma: no cover
    from mailroom_sandbox.autoresearch.loop import Loop, State


def _f(value: Any, spec: str = ".3f", dash: str = "-") -> str:
    return dash if value is None else format(value, spec)


def _cell(text: Any, limit: int = 110) -> str:
    text = str(text).replace("|", "/").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(loop: "Loop", state: "State") -> str:
    study, rows = loop.study, state.rows
    status = loop.status()
    lines = [f"# Autoresearch study `{study.study}`", "",
             f"- mode: {'mock (no spend)' if study.mock else 'paid (OpenRouter)'}",
             f"- champion: `{status['champion']}`, mean utility {_f(status['champion_mean_utility'])}",
             f"- rounds run: {status['rounds']}; kept {len(status['kept'])}, reverted {len(status['reverted'])}, "
             f"errors {len(status['errors'])}, aborted by the API cap {len(status['aborted_cap'])}, skipped {len(status['skipped'])}",
             f"- noise floor (keep rule): {_f(status['noise_floor'], '.4f', 'not measured yet: no lever is kept before the replicate baseline')}",
             f"- estimated spend: {status['spent_usd']:.4f} of {study.budget.study_usd:g} USD "
             f"(round cap {study.budget.round_api_cap_usd:g} USD)",
             f"- consecutive reverts: {status['consecutive_reverts']} (stop at {study.max_consecutive_reverts})",
             f"- holdout: {'run' if status['holdout'] else 'not run'}", "",
             "Cost is an estimate from recorded tokens priced per model (`config/api_prices.yaml`), not the provider's bill.", ""]

    lines += ["## Ledger", "", "| # | round | lever | decision | delta (CI) | utility | USD/doc | cost USD | USD per +0.01 | reasons |",
              "|--:|--:|:---|:---|:---|--:|--:|--:|--:|:---|"]
    for r in rows:
        d, m = r.get("delta") or {}, r.get("metrics") or {}
        ci = f"{d['mean']:+.3f} [{d['ci_low']:+.3f}, {d['ci_high']:+.3f}]" if d else "-"
        lines.append(f"| {r.get('seq')} | {_f(r.get('round'), 'd')} | `{r.get('lever')}` | {r.get('decision')} | {ci} | "
                     f"{_f(m.get('mean_utility'))} | {_f(m.get('cost_per_doc'), '.5f')} | {_f(r.get('cost_usd'), '.4f')} | "
                     f"{_f(r.get('usd_per_utility_point'), '.4f')} | {_cell('; '.join(r.get('reasons') or []))} |")

    rep_row = state.replicate
    if rep_row:
        n = rep_row.get("noise") or {}
        lines += ["", "## Noise floor (replicate baseline)", "",
                  f"The baseline's identical spec was run twice on the same draw ({n.get('n')} documents). Paired difference "
                  f"between the two runs: |mean| {_f(n.get('abs_mean_delta'), '.4f')}, CI half-width {_f(n.get('ci_half_width'), '.4f')}; "
                  f"configured floor {_f(n.get('configured_floor'), '.4f')}. Effective floor {_f(n.get('effective_floor'), '.4f')}: a lever "
                  f"is kept only when its paired CI low is above it. One repeat of the champion cost "
                  f"{_f(n.get('measured_round_cost_usd'), '.4f')} USD (the measured cost of a round)."]
    if status["warnings"]:
        lines += ["", "## Warnings", "", *[f"- {w}" for w in status["warnings"]]]

    kept = [r for r in rows if r.get("decision") == "keep"]
    lines += ["", "## Kept levers", ""]
    if kept:
        lines += ["| lever | delta | USD per +0.01 utility | oversight cost share | cost split (USD) |", "|:---|:---|--:|--:|:---|"]
        for r in kept:
            m, d = r.get("metrics") or {}, r.get("delta") or {}
            lines.append(f"| `{r['lever']}` | {d.get('mean', 0):+.3f} | {_f(r.get('usd_per_utility_point'), '.4f')} | "
                         f"{_f(m.get('oversight_cost_share'), '.2f')} | {_cell(m.get('cost_by_role'))} |")
    else:
        lines.append("None yet.")

    champ = (state.champ_row or {}).get("metrics") or {}
    lines += ["", "## Champion cost split", ""]
    if champ.get("cost_split") == "by_agent":
        lines += [f"- per-document cost by role (USD, whole run): {champ.get('cost_by_role')}",
                  f"- oversight cost share (oversight / worker): {_f(champ.get('oversight_cost_share'), '.2f')}"]
    else:
        lines.append("Per-agent usage was not recorded for this run (totals only), so the worker / oversight / reviewer "
                     "split and the oversight cost share are unavailable.")

    if state.champ_scores:
        from mailroom_sandbox.autoresearch import diagnose

        lines += ["", "## Champion weakness table", "", diagnose.render_weakness_md(state.champ_scores).strip()]

    hold = next((r for r in rows if r.get("decision") == "holdout"), None)
    if hold:
        m = hold.get("metrics") or {}
        lines += ["", "## Holdout", "", f"- run `{hold['run_id']}`: {m.get('n')} documents, disjoint from the {hold.get('dev_ids')} dev documents",
                  f"- mean utility {_f(m.get('mean_utility'))}, outcomes {m.get('outcomes')}, cost {_f(hold.get('cost_usd'), '.4f')} USD"]

    baseline = next((r for r in rows if r.get("decision") == "baseline"), None)
    if state.champ_spec:
        try:
            lines += ["", parity.render_parity_md(loop.base, state.champ_spec,
                                                   dependency_sources=(baseline or {}).get("dependency_sources")).rstrip()]
        except Exception as exc:  # noqa: BLE001 - the parity section must not stop a ledger write
            lines += ["", "## Production parity", "", f"Unavailable: {type(exc).__name__}"]
    lines.append("")
    return "\n".join(lines)
