"""Modal + vLLM GPU economics report for the mailroom-issues hub (SAND-032, Qwen3-8B-AWQ on Modal L4).

Called by ``export_hub_reports.py``; it writes ``MODAL-VLLM-GPU-REPORT.md`` and ``figures/gpu/*.svg``.
Every SAND-032 number comes from ``hub_data.json["fleet"]``: each serving export
(``reports/serving/sand032-*.serving.json``) cross-checked against its run report by
``hub_extract.sand032_fleet``. The two pre-SAND-032 2×L4 runs are read from their tracked serving
exports and checked against their run reports here.

Cost basis (as in every SAND-032 report):
- busy GPU $ = wall × replicas × L4 $/h — the basis for $/doc and $/token;
- billed GPU $ = (wall + cold boot) × replicas × L4 $/h — a lower bound on the Modal bill for the run.
"""
from __future__ import annotations

import json
import re

SAND = "reports/"  # run-report paths in the fleet data are relative to the sandbox reports/ dir

# Stage groups, in reading order. Labels are names only; every number is read from the fleet data.
GROUPS = [
    ("ladder", "1×L4 knob ladder · correspondence n = 20 · c8", [
        ("sand032-l0-baseline", "baseline"), ("sand032-l1-nothink", "+ thinking off"),
        ("sand032-l2-marlin", "+ awq_marlin (reverted)"), ("sand032-l5-graphs", "frozen config"),
        ("sand032-s4-corr20-bf16", "bf16 Qwen3-8B (quality arm)")]),
    ("scale", "Scale-out · correspondence n = 100 · same documents", [
        ("sand032-s2a-corr100-1rep", None), ("sand032-s2b-corr100-2rep", None),
        ("sand032-s7-corr100-seqs32", None), ("sand032-s9-corr100-bal", None)]),
    ("sweep", "Five-class sweep · 2×L4 · c32 · n = 50", [
        ("sand032-s3-corr50", "Correspondence"), ("sand032-s3-corr50-repeat", "Correspondence (repeat)"),
        ("sand032-s3-insurance50", "Insurance claims"), ("sand032-s3-corporate50", "Corporate records"),
        ("sand032-s3-contracts50", "Contracts"), ("sand032-s3-merger50", "Merger agreements"),
        ("sand032-s5-merger50-maud", "Merger agreements · MAUD prompt")]),
    ("c64", "Doubled admission · 2×L4 · c64 · n = 50", [
        ("sand032-s9-insurance50-bal", "Insurance claims"), ("sand032-s9-corporate50-bal", "Corporate records"),
        ("sand032-s9-contracts50-bal", "Contracts"), ("sand032-s7-insurance50-seqs32", "Insurance · max_inputs 64")]),
    ("v2", "v2 prompts · 1×L4 · c8 · n = 75", [
        ("sand032-s10-corr75-v2", "Correspondence"), ("sand032-s10-insurance75-v2", "Insurance claims"),
        ("sand032-s10-corporate75-v2", "Corporate records")]),
    ("sorter", "LLM sorter · 2×L4 · c32", [("sand032-s6-sorter1000", "LLM sorter")]),
]
SWEEP_BY_TASK = {"correspondence": "sand032-s3-corr50", "insurance claims": "sand032-s3-insurance50",
                 "corporate records": "sand032-s3-corporate50", "contracts": "sand032-s3-contracts50",
                 "merger agreements": "sand032-s3-merger50"}
# Pre-SAND-032 2×L4 runs (c8, max_num_seqs 6): serving exports are 1-replica basis; the reports bill 2 replicas.
EARLY_2X = [("run-20-correspondence-specialist-awq", "correspondence/RUN-20-CORRESPONDENCE-SPECIALIST-AWQ-REPORT.md"),
            ("run-50-correspondence-specialist-awq", "correspondence/RUN-50-CORRESPONDENCE-SPECIALIST-AWQ-REPORT.md")]


# ------------------------------------------------------------------ derived metrics
def tok(r):
    return r["prompt_tokens"] + r["completion_tokens"]


def per_mtok(r):
    return r["busy_usd"] / tok(r) * 1e6


def per_mout(r):
    return r["busy_usd"] / r["completion_tokens"] * 1e6


def tps_l4(r):
    return r["tps"] / r["replicas"]


def fleet_name(r):
    mi = f" · max_inputs {r['max_inputs']}" if r.get("max_inputs") else ""
    return f"{r['replicas']}×L4 · c{r['conc']} · seqs {r['seqs']}{mi}"


def busier_share(r):
    req = [s["requests"] for s in r["replica_split"]]
    return max(req) / sum(req) if len(req) > 1 else None


def code(rid):
    c = rid.split("-")[1]
    return c[0].upper() + c[1:]


def lcfirst(s):
    return s if s[:2].isupper() else s[0].lower() + s[1:]


def run_label(r, lab):
    """Table/figure label: stage code plus a name (the fleet, for the scale-out runs)."""
    if lab is None:
        mi = f", max_inputs {r['max_inputs']}" if r["conc"] > 16 else ""
        lab = f"{r['replicas']}×L4, c{r['conc']}{mi}"
    return f"{code(r['run'])} · {lab}"


def describe(F, rid):
    """Prose name for a run: 'S6 (LLM sorter, 2×L4 at c32)'."""
    r = F[rid]
    lab = next(lab for _, _, members in GROUPS for r_id, lab in members if r_id == rid) or "correspondence n = 100"
    return f"{code(rid)} ({lab}, {r['replicas']}×L4 at c{r['conc']})"


def labelled(F):
    """(group key, group title, [(label, record)]) in reading order."""
    return [(key, title, [(run_label(F[rid], lab), F[rid]) for rid, lab in members]) for key, title, members in GROUPS]


def early_2x(X) -> list[dict]:
    """Pre-SAND-032 2×L4 runs from their tracked serving exports, checked against their run reports."""
    out = []
    for rid, rep_path in EARLY_2X:
        d = X.serving(rid)
        text = (X.ROOT / "reports" / rep_path).read_text()
        if "2× L4 (data-parallel, one replica per L4)" not in text:
            raise SystemExit(f"{rep_path}: expected a 2×L4 engine row")
        billed = float(re.search(r"estimated GPU cost \(billed, 2 replicas\) \| \*\*\$([\d.]+)\*\*", text).group(1))
        seqs = int(re.search(r"max_num_seqs=(\d+)", text).group(1))
        if abs(billed - 2 * d["estimated_gpu_cost_usd"]) > 2e-6:
            raise SystemExit(f"{rep_path}: billed ${billed} is not 2 × the 1-replica export")
        out.append({"run": rid, "report": rep_path, "n": d["n"], "conc": d["concurrency"], "seqs": seqs, "replicas": 2,
                    "wall": d["wall_seconds"], "tps": d["tokens_per_second"], "slot": d["slot_utilization"],
                    "busy_usd": 2 * d["wall_seconds"] * X.L4_USD_PER_HOUR / 3600,
                    "prompt_tokens": d["prompt_tokens"], "completion_tokens": d["completion_tokens"]})
    return out


def spend_parts(D):
    F, sp = D["fleet"], D["spend"]
    busy = sum(r["busy_usd"] for r in F.values())
    idle = sum(r["idle_usd"] for r in F.values())
    billed = sum(r["billed_usd"] for r in F.values())
    parts = [("Slots with a request in flight", busy - idle), ("Idle slots inside runs", idle),
             ("Cold boots", billed - busy), ("Aborted sorter run (incident)", sp["incident"]),
             ("Fleet time outside any run", sp["sand032"] - billed - sp["incident"])]
    if parts[-1][1] < 0:
        raise SystemExit("spend ledger below the runs' billed GPU $ — hub check should have caught this")
    return parts, busy, idle, billed


def api_tokens(D, X):
    """Hosted-API legs that logged token counts, per task (eval-environment, n = 20)."""
    out = {}
    for task, models in D["api"]["tasks"].items():
        rows = [r for r in models.values() if r.get("prompt_tokens") and r.get("completion_tokens")]
        out[task] = [{"name": X.api_name(r), "n": r["n"], "run": r["run"], "usd_mtok": r["cost"] / (r["prompt_tokens"] + r["completion_tokens"]) * 1e6,
                      "usd_mout": r["cost"] / r["completion_tokens"] * 1e6,
                      "out_share": r["completion_tokens"] / (r["prompt_tokens"] + r["completion_tokens"])} for r in rows]
    return out


# ------------------------------------------------------------------ figures
def fig_spend(parts, ledger, X):
    return X.viz.hbar("Where the SAND-032 GPU spend went",
                      f"fleet-window ledger ${ledger:.2f} at close · the five parts sum to the ledger",
                      [{"label": lab, "value": round(v, 4), "emphasis": i == 0,
                        "note": f"{v / ledger * 100:.0f}% of the ledger"} for i, (lab, v) in enumerate(parts)],
                      fmt=lambda v: f"${v:.2f}", label_w=230)


def fig_cost_mtok(groups, X):
    top = max(per_mtok(r) for _, _, rows in groups for _, r in rows)
    panels = [X.viz.hbar(title, "busy-window GPU $ per 1M tokens (prompt + completion) · lower is better",
                         [{"label": lab, "value": round(per_mtok(r), 4), "emphasis": r["replicas"] == 2,
                           "note": f"{tps_l4(r):,.0f} tok/s per L4 · ${per_mout(r):.2f} per 1M output tokens"}
                          for lab, r in rows], fmt=lambda v: f"${v:.3f}", width=560, label_w=200, domain_max=top)
              for _, title, rows in groups]
    return X.viz.small_multiples("Modal L4 cost per 1M tokens, every SAND-032 run (emphasis = 2×L4; one scale)", panels, cols=2)


def fig_occupancy(groups, X):
    panels = [X.viz.hbar(title, "client-slot occupancy = Σ request latency ÷ (concurrency × wall) · higher is better",
                         [{"label": lab, "value": round(r["slot"], 4), "emphasis": r["replicas"] == 2,
                           "note": f"{X.usd(r['idle_usd'])} of {X.usd(r['busy_usd'])} busy-window GPU $ spent on idle slots"}
                          for lab, r in rows], fmt=lambda v: f"{v * 100:.0f}%", domain_max=1.0,
                         width=560, label_w=200)
              for _, title, rows in groups]
    return X.viz.small_multiples("How full the fleet was: client-slot occupancy per run (emphasis = 2×L4)", panels, cols=2)


def fig_second_l4(scale, X):
    def panel(title, sub, val, fmt):
        return X.viz.hbar(title, sub, [{"label": lab, "value": round(val(r), 6),
                                        "emphasis": r["replicas"] == 2 and (busier_share(r) or 0) < 0.75,
                                        "note": fleet_name(r)} for lab, r in scale], fmt=fmt, width=560, label_w=250)
    return X.viz.small_multiples("Adding the second L4 · correspondence n = 100, same documents (grey = one L4 or one replica doing the work)", [
        panel("Wall time", "seconds for the batch · lower is better", lambda r: r["wall"], lambda v: f"{v:.1f} s"),
        panel("Throughput per L4", "tokens per second per GPU · higher is better", tps_l4, lambda v: f"{v:,.0f}"),
        panel("Cost per 1M tokens", "busy-window GPU $ · lower is better", per_mtok, lambda v: f"${v:.3f}"),
        panel("p95 request latency", "seconds · lower is better", lambda r: r["p95"], lambda v: f"{v:.1f} s"),
    ], cols=2)


def fig_split(two, X):
    return X.viz.hbar("Load balance across the two L4 replicas",
                      "share of the run's requests on the busier replica (vLLM /metrics) · 50% = even · lower is better",
                      [{"label": lab, "value": round(busier_share(r), 4), "emphasis": busier_share(r) < 0.75,
                        "note": " / ".join(str(s["requests"]) for s in r["replica_split"]) + f" requests · {fleet_name(r)}"}
                       for lab, r in two], fmt=lambda v: f"{v * 100:.0f}%", refs=[(0.5, "even split")], label_w=250)


def fig_api(D, X, api):
    top = max([per_mtok(D["fleet"][rid]) for rid in SWEEP_BY_TASK.values()]
              + [a["usd_mtok"] for rows in api.values() for a in rows])
    panels = []
    for task, rid in SWEEP_BY_TASK.items():
        r = D["fleet"][rid]
        rows = [{"label": "Modal · Qwen3-8B-AWQ (2×L4 c32)", "value": round(per_mtok(r), 4), "emphasis": True,
                 "note": f"n = {r['ok']} · {rid}"}]
        rows += [{"label": f"API · {a['name'].split(' · ')[0]}" + (" (frozen prompts)" if "filed as" in a["name"] else ""),
                  "value": round(a["usd_mtok"], 4), "emphasis": False, "note": f"{a['name']} · n = {a['n']} · {a['run']}"} for a in sorted(api.get(task, []), key=lambda a: a["usd_mtok"])]
        rows.sort(key=lambda x: x["value"])
        panels.append(X.viz.hbar(task.capitalize(), "$ per 1M tokens (prompt + completion) · lower is better",
                                 rows, fmt=lambda v: f"${v:.3f}", width=560, label_w=250, domain_max=top))
    return X.viz.small_multiples("Cost per 1M tokens on the same tasks: Modal L4 (busy-window) vs hosted API · one scale", panels, cols=2)


# ------------------------------------------------------------------ report
def report(D, X, shas) -> tuple[str, dict[str, str]]:
    F, sp, rate = D["fleet"], D["spend"], D["l4_usd_per_hour"]
    groups = labelled(F)
    by = {k: rows for k, _, rows in groups}
    parts, busy, idle, billed = spend_parts(D)
    api = api_tokens(D, X)
    early = early_2x(X)
    usd, pct, table = X.usd, X.pct, X.table

    def d2(v):
        return f"${v:,.2f}"
    all_runs = list(F.values())
    tokens = sum(tok(r) for r in all_runs)
    docs = sum(r["ok"] for r in all_runs)
    cheapest = min(all_runs, key=per_mtok)
    dearest = max(all_runs, key=per_mtok)
    coeff = 1e6 * rate / 3600

    a, b = F["sand032-s2a-corr100-1rep"], F["sand032-s2b-corr100-2rep"]
    s7, s9 = F["sand032-s7-corr100-seqs32"], F["sand032-s9-corr100-bal"]
    one_l4 = [r for r in all_runs if r["replicas"] == 1]
    two = [(lab, r) for _, _, rows in groups for lab, r in rows if r["replicas"] == 2 and r["replica_split"]]
    sweep = [r for _, r in by["sweep"]]
    c64 = [r for _, r in by["c64"]] + [s7, s9]
    boots = [r["cold_boot"] for r in all_runs if r["cold_boot"] >= 60]  # cold fleets; warm runs probe in < 1 s
    lad_boot = {r["rung"]: r["boot"] for r in D["ladder"]}
    boot_usd = billed - busy
    preempt = sum(s["preempt"] for r in all_runs for s in r["replica_split"])
    prefix = [s["prefix"] for r in all_runs for s in r["replica_split"]]
    l0, l5 = F["sand032-l0-baseline"], F["sand032-l5-graphs"]
    s2_boot_2x = lad_boot["l5-graphs"] * 2 * rate / 3600  # the L5 posture's deploy→ready boot on both L4s
    largest = max(sp["legacy"], key=lambda x: x["v"])
    ins_gain = tps_l4(F["sand032-s9-insurance50-bal"]) / tps_l4(F["sand032-s3-insurance50"]) - 1

    # Modal vs API per token, per task
    api_rows, beat, lose = [], [], []
    for task, rid in SWEEP_BY_TASK.items():
        r = F[rid]
        hosted = sorted(api.get(task, []), key=lambda x: x["usd_mtok"])
        if not hosted:
            continue
        cheap = hosted[0]
        (beat if per_mtok(r) < cheap["usd_mtok"] else lose).append(task)
        api_rows.append([task.capitalize(), f"${per_mtok(r):.3f}", f"{r['completion_tokens'] / tok(r) * 100:.0f}%",
                         f"{cheap['name']} ${cheap['usd_mtok']:.3f}", f"{cheap['out_share'] * 100:.0f}%",
                         " · ".join(f"{x['name']} ${x['usd_mtok']:.3f}" for x in hosted[1:]) or "—",
                         f"{cheap['usd_mtok'] / per_mtok(r):.1f}×"])
    qwen_api = [x["usd_mtok"] for t in api.values() for x in t if x["name"] == "Qwen3-8B"]
    load = sp["sand032"] / busy  # ledger ÷ busy-window GPU $: what boot, idle and warm time added on this program
    beat_loaded = [task for task, rid in SWEEP_BY_TASK.items() if api.get(task)
                   and per_mtok(F[rid]) * load < min(x["usd_mtok"] for x in api[task])]

    figs = {
        "figures/gpu/gpu-spend.svg": fig_spend(parts, sp["sand032"], X),
        "figures/gpu/cost-per-mtok.svg": fig_cost_mtok(groups, X),
        "figures/gpu/slot-occupancy.svg": fig_occupancy(groups, X),
        "figures/gpu/second-l4.svg": fig_second_l4(by["scale"], X),
        "figures/gpu/replica-split.svg": fig_split(two, X),
        "figures/gpu/modal-vs-api-per-token.svg": fig_api(D, X, api),
    }

    run_rows = []
    for _, title, rows in groups:
        for lab, r in rows:
            run_rows.append([f"{lab}", fleet_name(r), f"{r['ok']}/{r['n']}", f"{tok(r):,}",
                             f"{r['completion_tokens'] / tok(r) * 100:.0f}%", f"{tps_l4(r):,.0f}", usd(r["busy_usd"]),
                             f"${per_mtok(r):.3f}", f"${per_mout(r):.2f}", usd(r["busy_usd"] / r["ok"])])
    util_rows = []
    for _, title, rows in groups:
        for lab, r in rows:
            split = r["replica_split"]
            util_rows.append([lab, fleet_name(r), pct(r["slot"], 0), f"{r['lat_sum'] / r['wall']:.1f}× of {r['conc']}",
                              f"{tps_l4(r):,.0f}", pct(r["idle_usd"] / r["busy_usd"], 0),
                              f"{r['cold_boot']:.0f} s" if r["cold_boot"] >= 1 else "warm",
                              " / ".join(f"{s['prefix'] * 100:.0f}%" for s in split) or "—",
                              " / ".join(f"{s['ttft']:.1f}" for s in split) or "—"])
    split_rows = [[lab, fleet_name(r), " / ".join(str(s["requests"]) for s in r["replica_split"]), pct(busier_share(r), 0),
                   " / ".join(f"{s['ttft']:.1f} s" for s in r["replica_split"]),
                   " / ".join(f"{s['prefix'] * 100:.0f}%" for s in r["replica_split"]), f"{tps_l4(r):,.0f}"] for lab, r in two]
    spend_rows = [[lab, d2(v), pct(v / sp["sand032"], 0)] for lab, v in parts]
    legacy_rows = [[x["b"], usd(x["v"]), x["d"]] for x in sp["legacy"]]
    modal_legacy = sum(x["v"] for x in sp["legacy"] if not x["b"].startswith("API"))
    group_rows = []
    for key, title, rows in groups:
        rs = [r for _, r in rows]
        group_rows.append([title, str(len(rs)), f"{sum(r['ok'] for r in rs):,}", f"{sum(tok(r) for r in rs):,}",
                           usd(sum(r["busy_usd"] for r in rs)), usd(sum(r["billed_usd"] - r["busy_usd"] for r in rs)),
                           usd(sum(r["billed_usd"] for r in rs))])

    def ab(name, f):
        return [name, f(a), f(b), f(s7), f(s9)]
    ab_rows = [
        ab("Fleet", fleet_name),
        ab("Wall time", lambda r: f"{r['wall']:.1f} s"),
        ab("Throughput", lambda r: f"{r['tps']:,.0f} tok/s"),
        ab("Throughput per L4", lambda r: f"{tps_l4(r):,.0f} tok/s"),
        ab("Busy-window GPU $", lambda r: usd(r["busy_usd"])),
        ab("$ per 1M tokens", lambda r: f"${per_mtok(r):.4f}"),
        ab("$ per document", lambda r: usd(r["busy_usd"] / r["ok"])),
        ab("p50 / p95 latency", lambda r: f"{r['p50']:.1f} / {r['p95']:.1f} s"),
        ab("Client-slot occupancy", lambda r: pct(r["slot"], 0)),
        ab("Requests per replica", lambda r: " / ".join(str(s["requests"]) for s in r["replica_split"])),
        ab("Mean TTFT per replica", lambda r: " / ".join(f"{s['ttft']:.2f} s" for s in r["replica_split"])),
        ab("Prefix-cache hit per replica", lambda r: " / ".join(f"{s['prefix'] * 100:.1f}%" for s in r["replica_split"])),
    ]
    ins3, ins7, ins9 = F["sand032-s3-insurance50"], F["sand032-s7-insurance50-seqs32"], F["sand032-s9-insurance50-bal"]
    adm_rows = [[lab, fleet_name(r), f"{r['wall']:.1f} s", f"{tps_l4(r):,.0f}", f"${per_mtok(r):.3f}",
                 " / ".join(str(s["requests"]) for s in r["replica_split"]), f"{r['p50']:.1f} / {r['p95']:.1f} s"]
                for lab, r in [("Correspondence n = 100", b), ("Correspondence n = 100", s7), ("Correspondence n = 100", s9),
                               ("Insurance n = 50", ins3), ("Insurance n = 50", ins7), ("Insurance n = 50", ins9)]]
    early_rows = [[e["run"], f"2×L4 · c{e['conc']} · seqs {e['seqs']}", f"{e['n']}", f"{e['tps'] / 2:,.0f}",
                   pct(e["slot"], 0), f"${e['busy_usd'] / (e['prompt_tokens'] + e['completion_tokens']) * 1e6:.3f}"]
                  for e in early]

    sweep_slot = [r["slot"] for r in sweep]
    one_slot = [r["slot"] for r in one_l4]
    long_docs = [lab for lab, r in by["sweep"] if r["slot"] < 0.6]
    spd = a["wall"] / b["wall"]
    s7_vs_b = per_mtok(s7) / per_mtok(b)
    s9_gain = tps_l4(s9) / tps_l4(b) - 1
    ladder_cut = 1 - per_mtok(l5) / per_mtok(l0)
    occupied = busy - idle

    md = f"""# Modal + vLLM GPU economics — SAND-032

_Qwen3-8B-AWQ on vLLM v0.29.0, Modal L4 GPUs at ${rate:.2f}/h each · {len(all_runs)} runs, {docs:,} documents, {tokens:,} tokens · generated by sandbox `reports/dashboard/export_hub_reports.py` from the cross-checked reports hub ({D['text']['n_figures']} source-quoted figures, {D['text']['n_checks']} automated cross-checks) · sources: {shas}_

This report covers what the self-hosted leg cost and how well it used the GPUs. It answers four questions: what a token costs on a Modal L4, where the GPU money went, how busy the GPUs were, and what adding a second L4 did. Its companions are [COST-COMPARISON-MODAL-VS-API.md](COST-COMPARISON-MODAL-VS-API.md) (cost per document against the hosted API) and [MASTER-REPORT.md](MASTER-REPORT.md).

## Summary

- **Spend.** SAND-032 used {d2(sp['sand032'])} of its {d2(sp['cap'])} cap (fleet-window ledger at close; it stood at {d2(sp['stage5'])} after stages 1–5). The runs themselves bill at least {d2(billed)}: {d2(busy)} while the batch ran and {d2(boot_usd)} of cold boots. The aborted sorter run cost {d2(sp['incident'])}. The remaining {d2(parts[-1][1])} ({pct(parts[-1][1] / sp['sand032'], 0)}) is fleet time outside any run: warm replicas waiting between runs and deploy windows. Only {d2(occupied)} ({pct(occupied / sp['sand032'], 0)} of the ledger) paid for GPU slots with a request in flight.
- **Cost per token.** A token costs ${per_mtok(cheapest):.3f} to ${per_mtok(dearest):.3f} per million on the busy-window basis. At a fixed L4 price the only variable is throughput per L4: $ per 1M tokens = {coeff:.1f} ÷ (tok/s per L4). The cheapest run is {describe(F, cheapest['run'])}: {pct(cheapest['prompt_tokens'] / tok(cheapest), 0)} of its tokens are input, and it ran at {tps_l4(cheapest):,.0f} tok/s per L4. The dearest is {describe(F, dearest['run'])}, at {tps_l4(dearest):,.0f} tok/s per L4 with long decodes and a long-document tail. Per million *output* tokens the range is ${min(map(per_mout, all_runs)):.2f}–${max(map(per_mout, all_runs)):.2f}.
- **Against the hosted API, per token.** On the same tasks, Modal at 2×L4 c32 is cheaper per token than every hosted model that logged tokens for {X.and_list(beat) or 'no task'}{'' if not lose else ', and dearer for ' + X.and_list(lose)}. Those are busy-window figures. This program's ledger was {load:.1f}× its busy-window GPU $ (boots, idle slots and warm time); at that load Modal is cheaper per token only for {X.and_list(beat_loaded) or 'no task'}. Hosted Qwen3-8B, the same model family, costs ${min(qwen_api):.3f}–${max(qwen_api):.3f} per 1M tokens.
- **Utilization.** GPU compute (SM) utilization was never sampled. The measured proxy is client-slot occupancy, the share of admitted request slots holding a request. It is {pct(min(one_slot), 0)}–{pct(max(one_slot), 0)} on one L4 at c8, {pct(min(sweep_slot), 0)}–{pct(max(sweep_slot), 0)} across the 2×L4 c32 sweep, and lowest on {X.and_list(lcfirst(l.split(' · ', 1)[1]) for l in long_docs)}, where one slow document holds the batch open while the other slots drain. Idle slots inside runs cost {d2(idle)} ({pct(idle / busy, 0)} of busy-window GPU $). {'vLLM recorded no preemptions on any scraped replica, so KV cache was never the constraint.' if preempt == 0 else f'vLLM recorded {preempt} preemptions across the scraped replicas.'}
- **The second L4.** On the same 100 documents, two L4s at c16 finished in {b['wall']:.1f} s against {a['wall']:.1f} s on one L4 at c8 ({spd:.2f}× faster). Throughput per L4 held ({tps_l4(a):,.0f} → {tps_l4(b):,.0f} tok/s), so cost per token moved from ${per_mtok(a):.4f} to ${per_mtok(b):.4f} and cost per document stayed flat. p95 latency rose from {a['p95']:.1f} s to {b['p95']:.1f} s. The second L4 pays only if Modal's router spreads the load. With `max_inputs` 64, it sent {max(s['requests'] for s in s7['replica_split'])} of 100 requests to one replica: throughput per L4 fell to {tps_l4(s7):,.0f} tok/s and cost per token rose {s7_vs_b:.1f}×. With `max_inputs` 32 at c64 the split was {' / '.join(str(s['requests']) for s in s9['replica_split'])}, and throughput per L4 reached {tps_l4(s9):,.0f} tok/s ({s9_gain * 100:+.0f}% on c16).
- **Boot.** {len(boots)} runs started on a cold fleet; each waited {min(boots):.0f}–{max(boots):.0f} s for the engine to answer its first request. CUDA-graph capture is most of the difference: deploy → ready went from {lad_boot['l1-nothink']:.0f} s at L1 to {lad_boot['l5-graphs']:.0f} s at L5. Boots cost {d2(boot_usd)}, {pct(boot_usd / billed, 0)} of the runs' billed GPU $; one cold 2×L4 start at L5 costs {usd(s2_boot_2x)}.

## 1. Setup and method

| | |
| --- | --- |
| Model / engine | `Qwen/Qwen3-8B-AWQ` (one bf16 `Qwen/Qwen3-8B` arm), vLLM `v0.29.0`, `max_model_len` 32768, prefix caching on |
| Frozen serving posture (L5) | `awq_marlin`, fp8 KV cache, thinking off, CUDA graphs, `max_num_seqs` 16 (32 on the c64 runs) |
| Fleet | Modal L4 (24 GB), one vLLM replica per container, `min = max` containers pinned for each batch, scaledown 120 s |
| Price | ${rate:.2f} per L4-hour (`docs/RUN-COST-DERIVATION.md` in the sandbox) |
| Data | public `Lucius-Morningstar/mailroom-dataset` @ `ed7576b`, seed 42, nested draws (20 ⊂ 50 ⊂ 100) |

**Definitions.**

- **Busy-window GPU $** = wall time of the batch × replicas × ${rate:.2f}/h. Every $/doc and $/token here uses it, as every SAND-032 run report does.
- **Billed GPU $** = (wall + cold boot) × replicas × ${rate:.2f}/h. It is a lower bound on what Modal bills for the run: warm time before and after the batch is not in it.
- **$ per 1M tokens** = busy-window GPU $ ÷ (prompt + completion tokens) × 10⁶. Because the GPU bills by time, this equals {coeff:.1f} ÷ (tokens per second per L4).
- **Client-slot occupancy** = Σ request latency ÷ (client concurrency × wall). 100% means every admitted slot held a request for the whole batch. The unused share, priced at the busy-window rate, is **idle-slot $**.
- **Effective parallelism** = Σ request latency ÷ wall: how many requests were in flight on average.
- **Per-replica vLLM figures** come from each replica's `/metrics` endpoint. Request counts are deltas over the run; TTFT means and prefix-cache hit rates are cumulative since the replica started.

**Not measured.** No run sampled GPU SM utilization, memory bandwidth or power (no DCGM or `nvidia-smi` sampling), and KV-cache usage was only scraped at idle, where it reads 0%. Occupancy and throughput per L4 are therefore the utilization evidence. See section 6.

## 2. GPU spend

![Where the SAND-032 GPU spend went](figures/gpu/gpu-spend.svg)

{table(["Part of the ledger", "USD", "Share"], spend_rows, "lrr")}

The five parts sum to the {usd(sp['sand032'])} ledger. The first three come from the runs' serving exports; the incident is the aborted sorter run; the last is the ledger minus everything attributable to a run. The fleet-window ledger itself under-counts Modal billing (the program summary's finding), so treat {usd(sp['sand032'])} as a floor and reconcile it against the Modal usage page.

**By stage.**

{table(["Stage", "Runs", "Docs", "Tokens", "Busy $", "Boot $", "Billed $"], group_rows, "lrrrrrr")}

**Before SAND-032.** Tracked spend from 16–27 Sep totals {usd(sp['legacy_total'])}, of which {usd(modal_legacy)} was Modal GPU time; the largest item was "{largest['b']}" at {usd(largest['v'])}. With SAND-032, tracked Modal GPU spend is at least {usd(modal_legacy + sp['sand032'])}.

{table(["Bucket", "USD", "Detail"], legacy_rows, "lrl")}

## 3. Cost per token

![Modal L4 cost per 1M tokens, every SAND-032 run](figures/gpu/cost-per-mtok.svg)

{table(["Run", "Fleet", "Docs ok", "Tokens", "Output share", "tok/s per L4", "Busy GPU $", "$ / 1M tokens", "$ / 1M output", "$ / doc"], run_rows, "llrrrrrrrr")}

**What drives it.**

- **Throughput per L4 is the whole story.** Cost per token is {coeff:.1f} ÷ (tok/s per L4), so every lever is a throughput lever. The L0 → L5 ladder raised throughput from {tps_l4(l0):,.0f} to {tps_l4(l5):,.0f} tok/s on the same 20 documents and cut cost per token {pct(ladder_cut, 0)}.
- **Prompt-heavy work is cheap.** Prefill is fast and prefix caching skips shared system prompts, so tasks dominated by input tokens run at high throughput. The LLM sorter ({pct(F['sand032-s6-sorter1000']['prompt_tokens'] / tok(F['sand032-s6-sorter1000']), 0)} input) reaches {tps_l4(F['sand032-s6-sorter1000']):,.0f} tok/s per L4.
- **Long documents are expensive.** Contracts and mergers run at {tps_l4(F['sand032-s3-contracts50']):,.0f} and {tps_l4(F['sand032-s3-merger50']):,.0f} tok/s per L4 at c32. Long decodes are slow, and the last long document holds both GPUs while the other slots have drained (section 4).
- **The bf16 arm costs more for no quality gain.** Unquantised `Qwen/Qwen3-8B` ran at {tps_l4(F['sand032-s4-corr20-bf16']):,.0f} tok/s per L4, {per_mtok(F['sand032-s4-corr20-bf16']) / per_mtok(F['sand032-l1-nothink']):.1f}× the cost per token of the L1 AWQ rung on the same documents.

### Against the hosted API, per token

![Cost per 1M tokens on the same tasks: Modal L4 vs hosted API](figures/gpu/modal-vs-api-per-token.svg)

{table(["Task", "Modal $ / 1M", "Modal output share", "Cheapest API (per 1M)", "API output share", "Other API models", "Cheapest API ÷ Modal"], api_rows, "lrrlrlr")}

Hosted rows are the eval-environment n = 20 legs that logged token counts (list price × tokens). Modal rows are busy-window only; scaled by this program's ledger-to-busy ratio ({load:.1f}×), Modal stays cheaper per token for {X.and_list(beat_loaded) or 'no task'}. Each leg counts tokens with its own prompts and tokenizer, and the API charges output tokens several times more than input, so the output share matters: Modal's GPU-time price does not care about the mix. The per-document comparison, with break-even volumes, is in [COST-COMPARISON-MODAL-VS-API.md](COST-COMPARISON-MODAL-VS-API.md).

## 4. GPU utilization

![How full the fleet was: client-slot occupancy per run](figures/gpu/slot-occupancy.svg)

{table(["Run", "Fleet", "Slot occupancy", "Effective parallelism", "tok/s per L4", "Idle-slot share of busy $", "Cold boot", "Prefix-cache hit per replica", "Mean TTFT per replica (s)"], util_rows, "llrrrrrrr")}

**Findings.**

- **One L4 at c8 stays full.** Occupancy is {pct(min(one_slot), 0)}–{pct(max(one_slot), 0)} on the single-L4 runs: eight client slots feed one engine, so a straggler idles one slot in eight rather than most of 32.
- **Wide fleets idle on long tails.** At c32 on two L4s, occupancy drops to {pct(min(sweep_slot), 0)}–{pct(max(sweep_slot), 0)}. On {X.and_list(lcfirst(l.split(' · ', 1)[1]) for l in long_docs)}, one slow document is still decoding after the other slots have emptied, so both GPUs bill while mostly idle. Across all runs idle slots cost {d2(idle)}, {pct(idle / busy, 0)} of busy-window GPU $.
- **Doubling admission lowers occupancy.** At c64 (`max_num_seqs` 32) occupancy is {pct(min(r['slot'] for r in c64), 0)}–{pct(max(r['slot'] for r in c64), 0)}: requests queue inside vLLM, latency rises, and wall time falls by less than the extra admission.
- **KV cache was never the limit.** {'vLLM reported no preemptions on any scraped replica, including the contracts runs at 32 sequences per replica with fp8 KV.' if preempt == 0 else f'vLLM reported {preempt} preemptions across the scraped replicas.'} Prefix-cache hit rates were {pct(min(prefix), 0)}–{pct(max(prefix), 0)} per replica.
- **Boot is the other idle.** {len(boots)} runs started on a cold fleet and waited {min(boots):.0f}–{max(boots):.0f} s for the engine. At L5 the boot was {l5['cold_boot']:.0f} s for an {l5['wall']:.0f} s batch: {pct(l5['cold_boot'] / l5['gpu_seconds'], 0)} of that run's billed GPU time.

## 5. Adding the second L4

### 5.1 Same documents, one L4 vs two

![Adding the second L4](figures/gpu/second-l4.svg)

{table(["Metric", "1×L4 · c8", "2×L4 · c16", "2×L4 · c64, max_inputs 64", "2×L4 · c64, max_inputs 32"], ab_rows, "lrrrr")}

- **Near-linear scale-out.** With per-replica admission held at 8, the second L4 cut wall time {spd:.2f}× and held throughput per L4, so cost per token and per document stayed flat. The extra GPU buys time, not cost.
- **Tail latency got worse.** p95 rose from {a['p95']:.1f} s to {b['p95']:.1f} s while p50 fell from {a['p50']:.1f} s to {b['p50']:.1f} s. The prefix cache is per replica ({' / '.join(f"{s['prefix'] * 100:.1f}%" for s in b['replica_split'])} hit rates, against {a['replica_split'][0]['prefix'] * 100:.1f}% on one L4), so shared prompt prefixes are cached once per replica.
- **Routing decides whether the second L4 works.** Modal's `@web_server` router fills a container up to `max_inputs` before using the next. At `max_inputs` 64 and c64, one replica got {max(s['requests'] for s in s7['replica_split'])} of 100 requests, its mean TTFT reached {max(s['ttft'] for s in s7['replica_split']):.1f} s, and the batch took {s7['wall']:.1f} s. At `max_inputs` 32 the same load split {' / '.join(str(s['requests']) for s in s9['replica_split'])} and took {s9['wall']:.1f} s.

### 5.2 Admission on two L4s

{table(["Task", "Fleet", "Wall", "tok/s per L4", "$ / 1M tokens", "Requests per replica", "p50 / p95"], adm_rows, "llrrrrr")}

Once the router is balanced, doubling admission (c32 → c64, `max_num_seqs` 16 → 32) buys a modest gain and costs median latency: on insurance claims throughput per L4 rose {ins_gain * 100:.0f}% while p50 went from {ins3['p50']:.1f} s to {ins9['p50']:.1f} s. The program summary's reading is that one L4 saturates at around 16 concurrent sequences for these prompts.

### 5.3 Load balance on every 2×L4 run

![Load balance across the two L4 replicas](figures/gpu/replica-split.svg)

{table(["Run", "Fleet", "Requests per replica", "Busier replica", "Mean TTFT per replica", "Prefix-cache hit", "tok/s per L4"], split_rows, "llrrrrr")}

Even with `max_inputs` = `max_num_seqs`, short batches split unevenly; the program summary attributes this to Modal's router, not vLLM. The imbalance matters most on long-document classes, where the busier replica's last document sets the wall time.

### 5.4 The first second-L4 attempt (before SAND-032)

{table(["Run", "Fleet", "Docs", "tok/s per L4", "Slot occupancy", "$ / 1M tokens"], early_rows, "llrrrr")}

The 25 Sep correspondence runs added a second L4 without raising admission: c8 across two replicas with `max_num_seqs` 6 and eager mode (no CUDA graphs). Each L4 held about four requests at a time. Their prompts differ from SAND-032's, so this is not a paired comparison, but throughput per L4 was a small fraction of the {tps_l4(b):,.0f} tok/s SAND-032 later reached on two L4s. The lesson carried into the runbook: raise client concurrency with the replica count.

### 5.5 What the second L4 costs

- **Per batch, nothing extra while it runs.** Busy-window cost scales with wall × replicas, and wall halves.
- **Boot doubles.** Each cold replica boots separately; at the L5 posture's {lad_boot['l5-graphs']:.0f} s, a 2×L4 cold start costs {usd(s2_boot_2x)}, half of it for the second L4.
- **Warm idle doubles.** A pinned 2×L4 fleet costs ${2 * rate:.2f}/h whether or not it has work, which is how {usd(parts[-1][1])} of this program's ledger was spent outside any run.
- **Verdict.** Add the second L4 when wall time matters and the fleet is fed: client concurrency = replicas × `max_num_seqs`, and `max_inputs` = `max_num_seqs`. For a latency-insensitive batch it gains nothing per token, and it doubles boot and idle exposure.

## 6. Recommendations

1. **Keep the frozen L5 posture and the routing rule.** `max_inputs` = `max_num_seqs` per container, client concurrency = replicas × `max_num_seqs`. This is the largest cost lever measured here.
2. **Match fleet width to document length.** Short documents fill two L4s; long contracts and mergers leave them idle behind one straggler. Split long-document classes into their own batch, or cap their decode budget, before adding replicas.
3. **Stop paying for warm time between runs.** {pct(parts[-1][1] / sp['sand032'], 0)} of the ledger bought no run. Queue runs back-to-back against one warm fleet; when the gap to the next run is longer than a cold boot (about {lad_boot['l5-graphs']:.0f} s at L5), scaling to zero is cheaper than staying warm.
4. **Cut sorter input, not sorter GPUs.** The LLM sorter is prefill-bound and already the cheapest work per token; head-truncating its input is what moves its cost per document.
5. **Measure real GPU utilization before the next spend.** Sample `nvidia-smi` or DCGM (SM %, memory bandwidth, power) and scrape vLLM KV usage under load. Slot occupancy shows when the fleet is starved; it cannot show how hard a busy GPU is working.
6. **Reconcile the ledger.** Compare {usd(sp['sand032'])} against the Modal usage page for 27–28 Sep.

## 7. Source notes

- The SAND-032 program summary headed its spend line with the stage 1–5 figure ({usd(sp['stage5'])}) while its closing ledger read {usd(sp['sand032'])}. The runs alone bill {usd(billed)}, so {usd(sp['stage5'])} could not be the program total. The summary is corrected in the sandbox, and the hub now checks the header against the closing ledger and against the runs' billed GPU $.
- The S6 sorter report quotes {usd(F['sand032-s6-sorter1000']['billed_usd'] / F['sand032-s6-sorter1000']['ok'])}/doc on the billed basis (it includes the {F['sand032-s6-sorter1000']['cold_boot']:.0f} s cold boot). This report and the hub use the busy-window figure, {usd(F['sand032-s6-sorter1000']['busy_usd'] / F['sand032-s6-sorter1000']['ok'])}/doc, like every other run.
- The two pre-SAND-032 2×L4 serving exports are on a one-replica basis; their run reports bill both replicas. Section 5.4 uses both replicas and checks the report's billed figure against 2 × the export.

## Sources

| Source | What it gives |
| --- | --- |
| `local-mailroom-sandbox/reports/serving/sand032-*.serving.json` | per-run wall, boot, tokens, throughput, latency, slot occupancy, GPU $ |
| `local-mailroom-sandbox/reports/*/SAND032-*-REPORT.md` | engine flags, busy-window GPU $, per-replica vLLM `/metrics` |
| `local-mailroom-sandbox/reports/serving/QWEN3-L4-LADDER-SUMMARY.md` | spend ledger, incident, runbook findings |
| `local-mailroom-sandbox/reports/dashboard/hub_data.json` | the cross-checked extract every number here is read from |
| `eval-environment/reports/api-comparisons/` (via the hub) | hosted-API legs with token counts and cost |

{shas}
"""
    return md, figs
