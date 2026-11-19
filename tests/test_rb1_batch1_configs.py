"""Campaign rb1 batch 1 (runbook R11, R12, R14, R15 and the R41 prompt A/Bs): launch-ready configs.

Offline checks only: the naming grammar, spend caps and prices, provider pins, the frozen dataset
revision and label overlays, the document selections (no held-out or calibration document can be
drawn), A/B pairs that differ only in their prompt, look 1 inside look 2, the launch script's run
list, and the promotion rule of scripts/rb1_promote.py on synthetic run stores.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
RUNS = ROOT / "config" / "runs"
SPLIT = ROOT / "config" / "splits" / "runbook-v1"
CONFIGS = sorted(RUNS.glob("rb1-r1[1245]-*.yaml")) + sorted(RUNS.glob("rb1-r41-*.yaml"))
KEYS = {"rb1-r11", "rb1-r12", "rb1-r14", "rb1-r15", "rb1-r41"}
RUN_ID = re.compile(r"^(rb1-r\d\d[a-z]?)-[a-z0-9][a-z0-9.-]*[a-z0-9]$")
REVISION = "bc9eab280044befb51e19dda3071d290a8677f42"
CLASSES = {"contracts_specialist": "contract", "corporate_records_specialist": "corporate_record",
           "correspondence_specialist": "correspondence", "insurance_claims_specialist": "insurance_claim",
           "merger_agreement_specialist": "merger_agreement"}

sys.path.insert(0, str(ROOT / "scripts"))
import rb1_build_selections  # noqa: E402
import rb1_promote  # noqa: E402


def _raw(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ids(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


ASSIGN = {r["id"]: r for r in rb1_build_selections.assignments()}
HELDOUT, CALIBRATION = _ids(SPLIT / "heldout.ids"), _ids(SPLIT / "calibration.ids")


def _selectable(raw: dict) -> set[str]:
    """Every document the spec can draw: the corpus minus its exclusion file, inside its strata class."""
    pool = set(ASSIGN) - _ids(ROOT / raw["dataset"]["exclude_ids_file"])
    buckets = ((raw["dataset"].get("strata") or {}).get("buckets")) or []
    if buckets:
        classes = {b["doc_class"] for b in buckets}
        pool = {i for i in pool if ASSIGN[i]["doc_class"] in classes}
    return pool


def test_batch_is_complete():
    names = {p.stem for p in CONFIGS}
    assert len(names) == 37
    assert Counter(RUN_ID.match(n).group(1) for n in names) == {"rb1-r11": 1, "rb1-r12": 5, "rb1-r14": 10, "rb1-r15": 5, "rb1-r41": 16}


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_naming_grammar_and_launch_header(path):
    raw = _raw(path)
    run_id = raw["run_id"]
    assert path.stem == run_id
    match = RUN_ID.match(run_id)
    assert match and match.group(1) in KEYS and len(run_id) <= 64
    key = match.group(1)
    text = path.read_text(encoding="utf-8")
    ledger = f"SANDBOX_SERVED_LOG=data/runtime/{key}/served-{run_id}.jsonl"
    cfg = f"config/runs/{run_id}.yaml"
    assert f"#   {ledger} sandbox run preflight --config {cfg} && \\" in text
    assert f"#   {ledger} sandbox run start --config {cfg} --initials <XX>" in text
    assert re.search(r"^# Cost: \d+ calls, about \$\d+\.\d{3} list", text, re.M)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_caps_prices_and_pins(path):
    from mailroom_sandbox.job.api_budget import spec_api_models, unpriced
    from mailroom_sandbox.job.spec import load_run_spec

    spec = load_run_spec(path)
    assert spec.profile == "openrouter" and spec.engine.kind == "openrouter" and spec.job.mock is False
    assert spec.job.max_wall_seconds and spec.job.max_wall_seconds >= 60
    assert spec.job.api_cost_cap_usd and spec.job.cost_cap_usd == spec.job.api_cost_cap_usd
    text = path.read_text(encoding="utf-8")
    estimate = float(re.search(r"about \$(\d+\.\d+) list", text).group(1))
    assert spec.job.api_cost_cap_usd >= max(0.05, 1.5 * estimate) - 0.005
    models = spec_api_models(spec)
    assert spec.engine.model in models and not unpriced(models)
    pins = yaml.safe_load((ROOT / "config" / "provider_pins.yaml").read_text())["models"]
    assert pins[spec.engine.model]["order"] and pins[spec.engine.model]["allow_fallbacks"] is False


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_dataset_revision_overlays_and_selection(path):
    raw = _raw(path)
    d = raw["dataset"]
    r03 = next(RUNS.glob("*r03-sorter-v0-dev.yaml"))   # runbook-r03-* or its rb1-r03-* rename
    assert d["revision"] == _raw(r03)["dataset"]["revision"] == REVISION
    assert d["draw"] == "ranked" and d["split"] == "all" and d["config"] == "ground_truth"
    assert d["interim_labels"] is True and d["near_gold_labels"] is True
    key = RUN_ID.match(raw["run_id"]).group(1)
    expected_file = {
        "rb1-r11": "config/splits/runbook-v1/pool.exclude.ids",
        "rb1-r14": "config/splits/runbook-v1/pool.exclude.ids",
        "rb1-r12": "config/splits/runbook-v1/dev-look1.exclude.ids",
        "rb1-r15": "config/splits/rb1/r15-long.exclude.ids",
    }.get(key) or f"config/splits/runbook-v1/dev-{raw['run_id'].rsplit('-', 1)[1]}.exclude.ids"
    assert d["exclude_ids_file"] == expected_file
    selectable = _selectable(raw)
    assert d["limit"] <= len(selectable)
    if key in ("rb1-r11", "rb1-r14"):
        assert d["limit"] == 300 and d["sample_seed"] == 20261118
    if key == "rb1-r15":
        assert d["limit"] == len(selectable) == 298
    buckets = (d.get("strata") or {}).get("buckets")
    if buckets:   # one class, every document of it in the look
        assert len(buckets) == 1 and buckets[0]["doc_class"] == CLASSES[raw["task"]]
        assert buckets[0]["count"] == d["limit"] == len(selectable)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_no_heldout_or_calibration_document_can_be_drawn(path):
    selectable = _selectable(_raw(path))
    assert not selectable & HELDOUT
    assert not selectable & CALIBRATION
    assert {ASSIGN[i]["set"] for i in selectable} <= {"dev", "pool"}


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_the_heldout_seal_covers_every_draw(path):
    from mailroom_sandbox.heldout_seal import leak_errors, seal_errors
    from mailroom_sandbox.job.spec import load_run_spec

    spec = load_run_spec(path)
    exclude = spec.dataset.exclude_ids_path()
    heldout = exclude.parent / "heldout.ids"
    assert heldout.is_file(), f"{exclude} has no heldout.ids beside it, so the seal's leak check skips it"
    assert not seal_errors(spec, spec.run_id)
    a_heldout_id = next(x for x in heldout.read_text(encoding="utf-8").splitlines() if x and not x.startswith("#"))
    assert leak_errors(spec, [a_heldout_id]), "the seal must refuse a held-out row in this draw"


#: Longest dev + pool document per class (chars, measured on the bc9eab28 locked rows on 2026-11-18);
#: a cap at or above its class maximum never cuts a document the run can draw.
LONGEST_BY_CLASS = {"contract": 616_016, "corporate_record": 376_830, "correspondence": 42_304,
                    "insurance_claim": 22_364, "merger_agreement": 739_511}


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_api_readers_take_the_whole_document_in_one_call(path):
    """Owner rule: no windowed or capped reads on an API route; only R15 sweeps the cap on purpose."""
    raw, text = _raw(path), path.read_text(encoding="utf-8")
    assert "chunking" not in (raw.get("job") or {}), "batch-1 configs never set job.chunking"
    assert "Estimate is provisional" in text
    knobs = raw.get("agent_knobs") or {}
    for agent, k in knobs.items():
        assert "chunk_chars" not in k and "overlap_chars" not in k, agent
    if path.stem.startswith("rb1-r15-"):
        assert "Deliberate input-cap sweep" in text
        return
    classes = {ASSIGN[i]["doc_class"] for i in _selectable(raw)}
    buckets = (raw["dataset"].get("strata") or {}).get("buckets") or []
    if buckets and all("doc_class" in b for b in buckets):
        classes &= {b["doc_class"] for b in buckets}
    longest = max(LONGEST_BY_CLASS[c] for c in classes)
    for agent, k in knobs.items():
        cap = k.get("max_input_chars")
        if cap is not None:
            assert cap >= longest, f"{agent} max_input_chars {cap} can cut a {longest}-char document"


def test_r15_selection_is_current_and_long_only():
    for name, text in rb1_build_selections.render().items():
        assert (ROOT / "config" / "splits" / "rb1" / name).read_text(encoding="utf-8") == text
    long_ids = set(rb1_build_selections.r15_long_ids())
    assert len(long_ids) == 298
    assert {ASSIGN[i]["band"] for i in long_ids} == {"<=16k", "<=32k", ">32k"}
    assert Counter(ASSIGN[i]["set"] for i in long_ids) == {"dev": 294, "pool": 4}


def _pair_body(raw: dict) -> dict:
    body = json.loads(json.dumps(raw))
    for key in ("run_id", "prompt"):
        body.pop(key)
    body["trace"].pop("tags")
    return body


def test_ab_pairs_differ_only_in_the_prompt():
    for agent in rb1_promote.PAIRS:
        for look in (1, 2):
            base_id, cand_id = rb1_promote.run_ids(agent, look)
            base, cand = _raw(RUNS / f"{base_id}.yaml"), _raw(RUNS / f"{cand_id}.yaml")
            assert _pair_body(base) == _pair_body(cand), (base_id, cand_id)
            assert base["task"] == agent and base["job"]["schema_guide"] is True
            assert base["job"]["pipeline_handoff"] is True and base["job"]["specialist_subclass"] == "gold"
            assert base["prompt"]["agents"] == {agent: {"source": "local", "file": rb1_promote.PAIRS[agent][1]}}
            assert cand["prompt"]["agents"] == {agent: {"source": "local", "file": rb1_promote.PAIRS[agent][3]}}
            assert base["prompt"]["default"] == cand["prompt"]["default"]


def test_r11_pairs_with_the_r14_v0_arm():
    v01, v0 = _raw(RUNS / "rb1-r11-sorter-v0.1-pool.yaml"), _raw(RUNS / "rb1-r14-qwen3.7-flash-t0-rnone-rep1.yaml")
    assert _pair_body(v01) == _pair_body(v0)
    assert v01["prompt"]["agents"] == {"sorter": {"source": "local", "file": "sorter_condensed_v6"}}
    assert "agents" not in v0["prompt"]   # v0 = the production sorter (code-default)


def test_r12_matches_the_r03_v0_settings():
    for lineage in ("insurance", "correspondence", "corporate", "contracts", "merger"):
        r12 = _raw(RUNS / f"rb1-r12-{lineage}-v0-look1.yaml")
        r03 = _raw(next(RUNS.glob(f"*r03-{lineage}-v0-dev.yaml")))
        for section in ("task", "prompt", "agent_knobs", "engine"):
            assert r12[section] == r03[section], (lineage, section)
        for knob in ("pipeline_handoff", "specialist_subclass", "schema_guide"):
            assert r12["job"].get(knob) == r03["job"].get(knob), (lineage, knob)
    assert sum(_raw(p)["dataset"]["limit"] for p in RUNS.glob("rb1-r12-*.yaml")) == 300


def test_look1_documents_are_inside_look2():
    look1, look2 = _ids(SPLIT / "dev-look1.ids"), _ids(SPLIT / "dev-look2.ids")
    assert len(look1) == 300 and len(look2) == 600 and look1 < look2
    for agent in rb1_promote.PAIRS:
        for arm in (0, 1):
            one = _selectable(_raw(RUNS / f"{rb1_promote.run_ids(agent, 1)[arm]}.yaml"))
            two = _selectable(_raw(RUNS / f"{rb1_promote.run_ids(agent, 2)[arm]}.yaml"))
            assert one < two and one <= look1 and two <= look2


def test_launch_script_lists_every_config_once():
    text = (ROOT / "scripts" / "rb1_launch_batch1.sh").read_text(encoding="utf-8")
    order = re.findall(r"^  (rb1-\S+)$", text, re.M)
    assert len(order) == len(set(order)) and set(order) == {p.stem for p in CONFIGS}
    assert order.index("rb1-r14-qwen3.7-flash-t0-rnone-rep1") < order.index("rb1-r11-sorter-v0.1-pool")
    assert "^[A-Z]{2,6}$" in text and '"$answer" == "yes"' in text and "--dry-run" in text


def test_sorter_v0_1_is_v5_with_one_b2_clause():
    prompts = ROOT / "config" / "prompts"
    v5 = (prompts / "sorter_condensed_v5.txt").read_text(encoding="utf-8")
    v6 = (prompts / "sorter_condensed_v6.txt").read_text(encoding="utf-8")
    old = "an automated notice, a calendar entry"
    new = "an automated notice or system/scheduling log message, a pasted data table, a calendar entry"
    assert v5.count(old) == 1 and v6 == v5.replace(old, new)
    lineage = yaml.safe_load((prompts / "sorter_condensed_lineage.yaml").read_text(encoding="utf-8"))
    row = next(v for v in lineage["versions"] if v["version"] == "sorter_condensed_v6")
    assert row["status"] == "candidate" and row["parent"].startswith("sorter_condensed_v5")


# ── scripts/rb1_promote.py ───────────────────────────────────────────────────────────────────
def _write_run(runs: Path, run_id: str, scores: list[float], halluc: list[int], *, mock=False, state="done",
               model="qwen/qwen3.7-flash", file="x"):
    d = runs / run_id
    d.mkdir(parents=True)
    ids = [f"DOC-{i:04d}" for i in range(len(scores))]
    core = {"task": "t", "engine": {"model": model}, "prompt": {"agents": {"t": {"file": file}}}, "trace": {"tags": [run_id]}}
    (d / "spec.lock.json").write_text(json.dumps({"run_id": run_id, "spec_core": core, "job": {"mock": mock},
                                                  "dataset": {"sha256": "abc"}}))
    (d / "checkpoint.json").write_text(json.dumps({"state": state}))
    (d / "dataset.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in ids))
    items = [{"item_id": i, "ok": True, "score": {"extraction_f1": s, "fields": {"entity_list_audit": {
        "a": {"hallucinated": h, "n_predicted": 4}}}}} for i, s, h in zip(ids, scores, halluc)]
    (d / "items.jsonl").write_text("".join(json.dumps(x) + "\n" for x in items))


def _family(runs: Path, look: int, cand_gain: float, *, halluc_up=False, mock=False, model="qwen/qwen3.7-flash"):
    import random

    rng = random.Random(7)
    for agent in rb1_promote.PAIRS:
        base = [rng.uniform(0.3, 0.7) for _ in range(120)]
        cand = [min(1.0, b + cand_gain + rng.uniform(-0.01, 0.01)) for b in base]
        base_id, cand_id = rb1_promote.run_ids(agent, look)
        _write_run(runs, base_id, base, [0] * 120, mock=mock, file="old")
        _write_run(runs, cand_id, cand, [1 if halluc_up else 0] * 120, mock=mock, model=model, file="new")


def _verdicts(runs, look, **kw):
    return rb1_promote.verdicts(runs, look, target=0.03, alpha=0.05, n_perm=500, seed=1, allow_mock=kw.pop("allow_mock", False))


def test_promote_rule_promotes_only_a_clean_significant_gain(tmp_path):
    _family(tmp_path, 2, 0.05)
    rows = _verdicts(tmp_path, 2)["pairs"]
    assert {r["verdict"] for r in rows.values()} == {"PROMOTE"}
    assert all(r["holm_p"] < 0.05 and r["keep_rule"] == "keep" for r in rows.values())


def test_promote_rule_never_promotes_at_look1_or_on_more_hallucination(tmp_path):
    _family(tmp_path / "a", 1, 0.05)
    assert {r["verdict"] for r in _verdicts(tmp_path / "a", 1)["pairs"].values()} == {"SCREEN: run look 2"}
    _family(tmp_path / "b", 2, 0.05, halluc_up=True)
    rows = _verdicts(tmp_path / "b", 2)["pairs"].values()
    assert all(r["verdict"] == "KEEP FRONTRUNNER" and not r["checks"]["hallucination_not_up"] for r in rows)
    _family(tmp_path / "c", 2, 0.0)
    assert "PROMOTE" not in {r["verdict"] for r in _verdicts(tmp_path / "c", 2)["pairs"].values()}


def test_promote_refuses_mock_mismatched_or_missing_runs(tmp_path):
    _family(tmp_path / "m", 2, 0.05, mock=True)
    rows = _verdicts(tmp_path / "m", 2)["pairs"].values()
    assert all(r["verdict"] == "NO VERDICT" and any("mock" in p for p in r["problems"]) for r in rows)
    assert {r["verdict"] for r in _verdicts(tmp_path / "m", 2, allow_mock=True)["pairs"].values()} == {"PROMOTE"}
    _family(tmp_path / "x", 2, 0.05, model="deepseek/deepseek-v4.1-flash-1017")
    rows = _verdicts(tmp_path / "x", 2)["pairs"].values()
    assert all(any("beyond the prompt" in p for p in r["problems"]) for r in rows)
    rows = _verdicts(tmp_path / "empty", 2)["pairs"].values()
    assert all(r["verdict"] == "NO VERDICT" and r["holm_p"] == 1.0 for r in rows)


def test_apply_moves_the_frontrunner_and_keeps_the_lineage_valid(tmp_path):
    _family(tmp_path, 2, 0.05)
    rows = _verdicts(tmp_path, 2)["pairs"]
    lineage_path = ROOT / "config" / "prompts" / "specialist_condensed_lineage.yaml"
    text = lineage_path.read_text(encoding="utf-8")
    for row in rows.values():
        text = rb1_promote.apply_promotion(text, row, initials="QA", today="2026-11-18")
    data = yaml.safe_load(text)
    for agent, row in rows.items():
        block = data["agents"][agent]
        assert block["frontrunner"] == row["candidate"] and not block.get("frontrunner_outside_lineage")
        version = next(v for v in block["versions"] if v["version"] == row["candidate"])
        assert version["status"] == "adopted" and version["promotion"]["initials"] == "QA"
        old = [v for v in block["versions"] if v["version"] == row["frontrunner"]]
        assert all(v["status"] == "superseded" for v in old)
        assert not any(v["status"] == "candidate" for v in block["versions"] if v["version"] == row["candidate"])
    assert lineage_path.read_text(encoding="utf-8") != text   # the committed file is untouched


def test_apply_needs_initials_and_never_runs_on_mocks(capsys):
    for argv in (["--apply"], ["--apply", "--initials", "jb"], ["--apply", "--initials", "JB", "--allow-mock"],
                 ["--apply", "--initials", "JB", "--look", "1"]):
        with pytest.raises(SystemExit):
            rb1_promote.main(argv)
