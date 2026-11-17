"""The autoresearch loop against a fake executor: keep, revert, stops, resume, skips, secrets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from mailroom_sandbox.autoresearch import estimate as est_mod
from mailroom_sandbox.autoresearch import loop as lp
from mailroom_sandbox.autoresearch import scoring
from mailroom_sandbox.autoresearch.scoring import DocScore, RunScores

_REAL_SCORE_RUN, _REAL_ESTIMATE = scoring.score_run, est_mod.estimate_round_cost
KEY = "sk-or-v1-0123456789abcdefSECRETKEY"
SHA = "0" * 39 + "1"


def d(i, cls, outcome="correct_archive", utility=1.0, cause="", **kw):
    return DocScore(id=i, doc_class=cls, outcome=outcome, utility=utility, cause=cause, **kw)


def baseline_docs() -> list[DocScore]:
    return [
        d("c1", "contract"), d("c2", "contract"),
        d("r1", "correspondence", "review", -0.25, "classification:reviewer_unknown"),
        d("r2", "correspondence", "review", -0.25, "classification:reviewer_unknown"),
        d("i1", "insurance_claim", utility=0.6, cause="extraction:wrong_value"),
        d("i2", "insurance_claim"),
    ]


def with_utils(docs: list[DocScore], **changes: float) -> list[DocScore]:
    out = []
    for doc in docs:
        if doc.id in changes:
            new = changes[doc.id]
            doc = DocScore(**{**doc.__dict__, "utility": new, "outcome": "correct_archive" if new > 0 else doc.outcome,
                              "cause": "" if new >= 1 else doc.cause})
        out.append(doc)
    return out


class Fake:
    """An ``Executor``: writes a run dir whose scores come from ``script(spec) -> docs`` (or raises)."""

    def __init__(self, root: Path, script: Callable[[dict[str, Any], str], list[DocScore] | Exception], cost: float = 0.01):
        self.root, self.script, self.cost = root, script, cost
        self.runs: list[str] = []
        self.envs: list[dict[str, str]] = []
        self.specs: dict[str, dict[str, Any]] = {}
        self.holdout_ids: list[str] | None = None

    @staticmethod
    def lever_of(spec: dict[str, Any]) -> str:
        return next((t.split(":", 1)[1] for t in spec["trace"]["tags"] if t.startswith("lever:")), "")

    def _write(self, spec: dict[str, Any], docs: list[DocScore]) -> Path:
        rd = self.root / "runs" / spec["run_id"]
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "dataset.jsonl").write_text("".join(json.dumps({"id": x.id}) + "\n" for x in docs))
        for x in docs:
            x.cost_usd = self.cost
            x.cost_by_role = {"worker": self.cost}
        scores = RunScores(run_id=spec["run_id"], run_dir=str(rd), docs=docs, split_available=True)
        (rd / "fake_scores.json").write_text(json.dumps(scores.to_dict()))
        return rd

    def prepare(self, spec_path: Path, *, env=None) -> Path:
        spec = yaml.safe_load(Path(spec_path).read_text())
        if self.holdout_ids is None:
            return self.root / "runs" / "unprepared"
        rd = self.root / "runs" / spec["run_id"]
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "dataset.jsonl").write_text("".join(json.dumps({"id": i}) + "\n" for i in self.holdout_ids))
        return rd

    def execute(self, spec_path: Path, *, env=None) -> Path:
        spec = yaml.safe_load(Path(spec_path).read_text())
        self.runs.append(spec["run_id"])
        self.envs.append(dict(env or {}))
        self.specs[spec["run_id"]] = spec
        out = self.script(spec, self.lever_of(spec))
        if isinstance(out, Exception):
            raise out
        return self._write(spec, out)


@pytest.fixture(autouse=True)
def _fake_scoring(monkeypatch):
    monkeypatch.setattr(scoring, "score_run", lambda run_dir, weights=None, **kw: RunScores.from_dict(
        json.loads((Path(run_dir) / "fake_scores.json").read_text())))
    monkeypatch.setattr(est_mod, "estimate_round_cost", lambda *a, **k: est_mod.Estimate(usd=0.05, basis="test", detail={}, unpriced=[]))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def lever_yaml(**kw):
    kw.setdefault("description", "d")
    return kw


def reviewer_lever(i, node="reviewer", cutoff=0.3, **kw):
    return lever_yaml(id=i, node=node, classes="all", patch={"reviewer.classes.correspondence": cutoff}, **kw)


def sub(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return path


def ins_lever(i, cutoff=0.3, **kw):
    """A lever attached to the insurance specialist (the weakness that is left once the reviewer is fixed)."""
    return reviewer_lever(i, node="insurance_claims_specialist", cutoff=cutoff, **kw)


def make(tmp_path, levers, *, mock=True, study_over=None, script=None, cost=0.01, **loop_kw):
    base = {
        "schema": "sandbox.run/v1", "run_id": "base", "task": "pipeline", "profile": "ollama",
        "dataset": {"provider": "file", "local_path": str(Path(__file__).resolve().parents[1] / "data/fixtures/hf/docclass_mini.jsonl"), "limit": 3},
        "engine": {"kind": "vllm-local", "model": "Qwen/Qwen3-8B", "modal": None},
        "reviewer": {"backend": "mock", "model": "mock", "classes": {"contract": 0.5, "correspondence": 0.6}},
        "job": {"mode": "endpoint", "mock": mock},
        "trace": {"sink": "none", "tags": ["t"]},
    }
    study = {"schema": "sandbox.autoresearch/v1", "study": "t1", "base_run": "base.yaml", "levers": "levers.yaml",
             "budget": {"study_usd": 5, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 3},
             "bootstrap": {"n_boot": 300, "seed": 0}, **(study_over or {})}
    if not mock:     # a paid study may only run a Decisions-API reviewer (or the chat reviewer a missing block means)
        base["reviewer"] = {"backend": "decisions", "model": "openai/gpt-6-luna-decisions", "questions": "reviewer_decisions_v2",
                            "classes": {"contract": 0.78, "correspondence": 0.64}}
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(base))
    (tmp_path / "levers.yaml").write_text(yaml.safe_dump({"schema": "sandbox.autoresearch.levers/v1", **levers}))
    (tmp_path / "study.yaml").write_text(yaml.safe_dump(study))
    state = lp.Study.load(tmp_path / "study.yaml")

    def default(spec, lever):
        return baseline_docs()
    fake = Fake(tmp_path, script or default, cost)
    out: list[str] = []
    loop = lp.Loop(state, fake, state_dir=tmp_path / "state", out=out.append, **loop_kw)
    return loop, fake, out


def decisions(loop):
    """(lever, decision) per ledger row, without the replicate baseline that follows the baseline (see its own tests)."""
    return [(r["lever"], r["decision"]) for r in loop.ledger.rows() if r["decision"] != "replicate"]


def verdicts(loop):
    return [r["decision"] for r in loop.ledger.rows() if r["decision"] != "replicate"]


def row_of(loop, lever):
    return next(r for r in loop.ledger.rows() if r["lever"] == lever)


def levers_in(loop):
    return [r["lever"] for r in loop.ledger.rows() if r["decision"] != "replicate"]


# ---- keep / revert ----------------------------------------------------------------------------------------

def test_keep_path_promotes_the_candidate_to_champion_and_records_everything(tmp_path):
    def script(spec, lever):
        docs = baseline_docs()
        return with_utils(docs, r1=1.0, r2=1.0) if lever == "fix" else docs
    loop, fake, out = make(tmp_path, {"levers": [reviewer_lever("fix")]}, script=script)
    rows, stop = loop.run(1)
    assert decisions(loop) == [("baseline", "baseline"), ("fix", "keep")]
    assert [r["decision"] for r in loop.ledger.rows()][:2] == ["baseline", "replicate"]
    keep = next(r for r in loop.ledger.rows() if r["lever"] == "fix")
    assert keep["run_id"] == "ar-t1-r01-fix" and keep["champion_run_id"] == "ar-t1-r00-baseline"
    assert keep["delta"]["mean"] == pytest.approx(2.5 / 6, abs=1e-5) and keep["delta"]["ci_low"] > 0
    assert keep["attached_to"]["node"] == "reviewer" and keep["attached_to"]["class"] == "correspondence"
    assert len(keep["spec_sha256"]) == 64 and keep["metrics"]["n"] == 6
    champ = yaml.safe_load((loop.dir / "champion.yaml").read_text())
    assert champ["run_id"] == "ar-t1-r01-fix" and champ["reviewer"]["classes"]["correspondence"] == 0.3
    # the study stamps caps and tags on every run
    spec = fake.specs["ar-t1-r01-fix"]
    assert spec["job"]["api_cost_cap_usd"] == 1 and spec["job"]["max_wall_seconds"] == 600
    assert {"autoresearch", "t1", "lever:fix"} <= set(spec["trace"]["tags"]) and spec["trace"]["tags"][0] == "t"
    assert (loop.dir / "weakness.md").is_file() and "# Autoresearch study `t1`" in (loop.dir / "report.md").read_text()
    assert (loop.dir / "scores" / "ar-t1-r01-fix.json").is_file() and (loop.dir / "specs" / "ar-t1-r01-fix.yaml").is_file()


def test_revert_path_leaves_the_champion_alone(tmp_path):
    def script(spec, lever):
        return with_utils(baseline_docs(), c1=-1.0, c2=-1.0, i2=-1.0) if lever == "bad" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("bad")]}, script=script)
    loop.step()
    assert decisions(loop) == [("baseline", "baseline"), ("bad", "revert")]
    assert yaml.safe_load((loop.dir / "champion.yaml").read_text())["run_id"] == "ar-t1-r00-baseline"
    assert loop.state().champ_row["lever"] == "baseline"


def test_three_consecutive_reverts_stop_the_loop(tmp_path):
    levers = {"levers": [reviewer_lever(f"n{i}", cutoff=0.1 * i) for i in range(1, 6)]}
    loop, fake, _ = make(tmp_path, levers)           # every candidate scores exactly as the champion: no gain
    rows, stop = loop.run(10)
    assert stop == "consecutive_reverts"
    assert verdicts(loop) == ["baseline", "revert", "revert", "revert"]
    assert len(fake.runs) == 5                         # baseline + replicate + 3 candidates, never a fourth


def test_a_keep_resets_the_revert_count(tmp_path):
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "n3" else baseline_docs()
    # n1, n2 (reverts) then n3 (keep) fix the reviewer weakness; m1..m4 then attach to the insurance specialist
    levers = {"levers": [*[reviewer_lever(f"n{i}", cutoff=0.1 * i) for i in range(1, 4)], *[ins_lever(f"m{i}", cutoff=0.1 + 0.01 * i) for i in range(1, 5)]]}
    loop, fake, _ = make(tmp_path, levers, script=script)
    _, stop = loop.run(10)
    got = verdicts(loop)
    assert got == ["baseline", "revert", "revert", "keep", "revert", "revert", "revert"]    # the keep reset the count
    assert lp.consecutive_reverts(loop.ledger.rows()) == 3 and stop == "consecutive_reverts"


def test_levers_exhausted(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("only")]})
    _, stop = loop.run(5)
    assert stop == "levers_exhausted" and decisions(loop) == [("baseline", "baseline"), ("only", "revert")]


def test_non_actionable_weakness_attracts_no_lever(tmp_path):
    def script(spec, lever):
        return [d("a", "contract"), d("b", "contract", "wrong_archive", -1.0, "input:near_empty")]
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]}, script=script)
    _, stop = loop.run(3)
    assert stop == "levers_exhausted" and len(fake.runs) == 2        # the baseline and its replicate, no candidate


def test_the_proposer_follows_the_worst_node_first(tmp_path):
    levers = {"levers": [reviewer_lever("on-insurance", node="insurance_claims_specialist"), reviewer_lever("on-reviewer")]}
    loop, fake, _ = make(tmp_path, levers)
    loop.step()
    assert decisions(loop)[1][0] == "on-reviewer"      # reviewer loses 2 x 1.25, insurance 0.4


# ---- errors and the frozen draw --------------------------------------------------------------------------

def test_a_failed_candidate_is_an_error_row_and_counts_as_a_revert(tmp_path):
    def script(spec, lever):
        return lp.ExecutionError(f"boom with {KEY} in it", spec["run_id"]) if lever == "x" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]}, script=script)
    loop.step()
    row = row_of(loop, "x")
    assert row["decision"] == "error" and "boom" in row["reasons"][0] and KEY not in json.dumps(row)
    assert lp.consecutive_reverts(loop.ledger.rows()) == 1
    assert loop.state().champ_row["lever"] == "baseline"


def test_a_candidate_on_different_documents_is_refused(tmp_path):
    def script(spec, lever):
        return [d("zz", "contract")] if lever == "x" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]}, script=script)
    loop.step()
    row = row_of(loop, "x")
    assert row["decision"] == "error" and "not the same frozen draw" in row["reasons"][0]


def test_a_failed_baseline_stops_with_an_error(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]}, script=lambda s, l: lp.ExecutionError("down", s["run_id"]))
    with pytest.raises(lp.AutoresearchError, match="baseline failed"):
        loop.step()
    assert [r["decision"] for r in loop.ledger.rows()] == ["error"]


# ---- budget -------------------------------------------------------------------------------------------------

def test_study_budget_stops_before_a_round_that_could_overspend(tmp_path):
    over = {"budget": {"study_usd": 1.2, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 0}}
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2)]}, study_over=over, cost=0.05)
    rows, stop = loop.run(5)
    # baseline: 6 documents x 0.05 = 0.30 spent; 0.30 + 1 cap > 1.2 -> not even the replicate runs
    assert stop == "study_budget" and [r["decision"] for r in loop.ledger.rows()] == ["baseline"]


def test_budget_allows_rounds_while_spend_plus_cap_fits(tmp_path):
    over = {"budget": {"study_usd": 1.8, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 0}}
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2), reviewer_lever("c", cutoff=0.1)]},
                         study_over=over, cost=0.05)
    _, stop = loop.run(5)
    # baseline and replicate 0.6, a 0.9; b would need 0.9 + 1 > 1.8
    assert stop == "study_budget" and [r["lever"] for r in loop.ledger.rows()] == ["baseline", "replicate", "a"]


def test_paid_study_checks_the_keys_remaining_limit(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=lambda: 3.5)
    _, stop = loop.run(1)
    assert stop == "key_low" and fake.runs == []                       # 3.5 - 1 cap < 3 reserve
    loop2, fake2, _ = make(sub(tmp_path, "ok"), {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=lambda: 10.0)
    loop2.run(1)
    assert verdicts(loop2)[:2] == ["baseline", "revert"]
    assert all(r["mock"] is False for r in loop2.ledger.rows())


def test_unreadable_key_fails_closed(tmp_path):
    def boom():
        raise RuntimeError(f"cannot reach with {KEY}")
    loop, fake, out = make(tmp_path, {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=boom)
    _, stop = loop.run(1)
    assert stop == "key_unreadable" and fake.runs == []
    assert KEY not in "\n".join(out)


def test_mock_study_needs_no_key_check(tmp_path):
    def forbidden():
        raise AssertionError("a mock study must not check the key")
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, key_remaining=forbidden)
    loop.run(1)
    assert len(fake.runs) == 3                      # baseline, replicate, one candidate


# ---- skips ----------------------------------------------------------------------------------------------------

def test_over_round_cap_estimate_writes_a_skipped_row_and_moves_on(tmp_path, monkeypatch):
    def estimate(champ, champ_spec, cand_spec, safety=1.0):
        pricey = "pricey" in json.dumps(cand_spec)
        return est_mod.Estimate(usd=2.5 if pricey else 0.05, basis="by_agent", detail={"judge": 2.5}, unpriced=[])
    monkeypatch.setattr(est_mod, "estimate_round_cost", estimate)
    levers = {"levers": [lever_yaml(id="dear", node="reviewer", classes="all", patch={"reviewer.model": "pricey"}),
                         reviewer_lever("cheap")]}
    # reviewer.model "pricey" is a mock backend model: valid for the mock backend
    loop, fake, _ = make(tmp_path, levers)
    loop.run(2)
    rows = loop.ledger.rows()
    skipped = [r for r in rows if r["decision"] == "skipped"]
    assert [(r["lever"], r["reasons"][0].split(":")[0]) for r in skipped] == [("dear", "over_round_cap")]
    assert skipped[0]["estimate"]["usd"] == 2.5 and skipped[0]["cost_usd"] == 0.0
    assert "ar-t1-r01-dear" not in fake.runs and "ar-t1-r01-cheap" in fake.runs     # the skip took no round number
    # a skip neither counts as a revert nor resets the count
    assert lp.consecutive_reverts(rows) == 1


def test_a_noop_lever_is_skipped_not_run(tmp_path):
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "first" else baseline_docs()
    # "first" is kept and sets the cutoff to 0.3; "same" then sets it to 0.3 again: a no-op on the CHAMPION
    # (the catalog check only refuses a lever that is a no-op on the base spec)
    levers = {"levers": [reviewer_lever("first", cutoff=0.3), ins_lever("same", cutoff=0.3), ins_lever("real", cutoff=0.2)]}
    loop, fake, _ = make(tmp_path, levers, script=script)
    loop.run(2)
    rows = {r["lever"]: r for r in loop.ledger.rows()}
    assert rows["first"]["decision"] == "keep"
    assert rows["same"]["decision"] == "skipped" and rows["same"]["reasons"][0].startswith("noop")
    assert rows["real"]["decision"] in ("keep", "revert") and "ar-t1-r02-real" in fake.runs     # the skip took no round number
    assert "ar-t1-r02-same" not in fake.runs


def test_requires_env_lever_is_never_proposed_without_its_variable(tmp_path):
    levers = {"levers": [lever_yaml(id="needs-env", node="reviewer", classes="all", requires_env="AR_TEST_MISSING",
                                    patch={"reviewer.classes.correspondence": 0.2}), reviewer_lever("plain", cutoff=0.4)]}
    loop, fake, _ = make(tmp_path, levers, env={"AR_TEST_MISSING": ""})
    _, stop = loop.run(5)
    assert levers_in(loop) == ["baseline", "plain"] and stop == "levers_exhausted"
    ready, fake2, _ = make(sub(tmp_path, "b"), levers, env={"AR_TEST_MISSING": "1"})
    ready.run(5)
    assert "needs-env" in levers_in(ready)


def test_unknown_or_unusable_catalog_is_refused_up_front(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [lever_yaml(id="bad", node="reviewer", classes="all",
                                                          patch={"reviewer.classes.correspondence": 7})]})
    with pytest.raises(lp.AutoresearchError, match="does not fit the base spec"):
        loop.step()
    assert fake.runs == []                              # refused before the baseline spent anything


# ---- tiers and placements --------------------------------------------------------------------------------------

def test_tier_two_waits_for_tier_one(tmp_path):
    def tier(i, n, **kw):
        return reviewer_lever(i, cutoff=0.1 * n, tier=n if "tier" not in kw else kw.pop("tier"), group="g", **kw)
    t1 = reviewer_lever("t1", cutoff=0.2, tier=1, group="g")
    t2 = reviewer_lever("t2", cutoff=0.1, tier=2, group="g",
                        requires=[{"kept": {"group": "g", "tier": 1}}, {"all_reverted_positive": {"group": "g", "tier": 1}}])
    # t1 raises only r1 by 0.5: the mean is positive, the CI includes zero, so it is reverted ... with a positive mean
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=0.25) if lever == "t1" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [t2, t1]}, script=script)        # t2 is listed first
    loop.run(3)
    order = levers_in(loop)
    assert order[:3] == ["baseline", "t1", "t2"]
    t1_row = row_of(loop, "t1")
    assert t1_row["decision"] == "revert" and t1_row["delta"]["mean"] > 0


def test_tier_two_stays_locked_when_tier_one_reverts_with_a_negative_mean(tmp_path):
    t1 = reviewer_lever("t1", cutoff=0.2, tier=1, group="g")
    t2 = reviewer_lever("t2", cutoff=0.1, tier=2, group="g", requires=[{"kept": {"group": "g", "tier": 1}},
                                                                    {"all_reverted_positive": {"group": "g", "tier": 1}}])
    def script(spec, lever):
        return with_utils(baseline_docs(), c1=0.5) if lever == "t1" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [t1, t2]}, script=script)
    _, stop = loop.run(5)
    assert stop == "levers_exhausted" and levers_in(loop) == ["baseline", "t1"]


def test_supervisor_win_derives_placement_cost_levers_judged_on_cost(tmp_path):
    sup_patch = {f"agent_routes.{r}": {"provider": "openrouter", "model": "m/strong"} for r in ("judge", "boss")}
    sup = lever_yaml(id="sup-a", node=["judge", "boss"], classes="all", tier=1, group="supervisor", patch=sup_patch)
    cat = {"levers": [sup], "placements": [{"group": "supervisor", "roles": ["judge", "boss"], "keep_on": [["judge"], ["boss"]]}]}

    def script(spec, lever):
        docs = [d("c1", "contract"), d("j1", "correspondence", "review", -0.25, "judge:rejected"),
                d("j2", "correspondence", "review", -0.25, "judge:rejected"), d("j3", "correspondence", "review", -0.25, "judge:rejected")]
        routes = spec.get("agent_routes") or {}
        strong = [r for r in ("judge", "boss") if (routes.get(r) or {}).get("model") == "m/strong"]
        if lever == "sup-a":
            docs = with_utils(docs, j1=1.0, j2=1.0)
        if lever.startswith("sup-a@"):                         # the cheaper placement keeps the gain
            docs = with_utils(docs, j1=1.0, j2=1.0)
        fake.cost = 0.02 if len(strong) == 2 else 0.01 if strong else 0.005
        return docs
    loop, fake, _ = make(tmp_path, cat, script=script)
    loop.run(3)
    rows = [r for r in loop.ledger.rows() if r["decision"] != "replicate"]
    assert [r["lever"] for r in rows][:2] == ["baseline", "sup-a"] and rows[1]["decision"] == "keep"
    assert rows[2]["lever"].startswith("sup-a@")
    placement = rows[2]
    assert placement["goal"] == "cost" and placement["decision"] == "keep"
    spec = fake.specs[placement["run_id"]]
    assert spec["agent_routes"]["judge"]["model"] == "m/strong" and "boss" not in {k for k, v in spec["agent_routes"].items() if v["model"] == "m/strong"}
    assert placement["run_id"].startswith("ar-t1-r02-sup-a-judge")        # "@" and "+" are slugged out of run ids


# ---- pipeline source ----------------------------------------------------------------------------------------------

def src_lever(**kw):
    return lever_yaml(id="repair", node="reviewer", classes="all", pipeline_source={"env": "AR_TEST_SRC", "commit": SHA}, **kw)


def test_pipeline_source_lever_runs_with_a_contained_source_and_records_no_path(tmp_path):
    src = tmp_path / "pr-tree"
    src.mkdir()
    loop, fake, out = make(tmp_path, {"levers": [src_lever()]}, env={"AR_TEST_SRC": str(src)}, git_head=lambda p: SHA)
    loop.run(1)
    assert decisions(loop) == [("baseline", "baseline"), ("repair", "revert")]
    assert fake.envs[:2] == [{}, {}] and fake.envs[2] == {"MAILROOM_SRC": str(src.resolve())}   # baseline, replicate: none; only that round's process
    row = row_of(loop, "repair")
    assert row["pipeline_source"] == {"env": "AR_TEST_SRC", "commit": SHA, "lever": "repair", "commit_found": SHA}
    assert str(src) not in json.dumps(loop.ledger.rows()) and str(src) not in (loop.dir / "report.md").read_text()


def test_pipeline_source_at_the_wrong_commit_is_skipped_not_run(tmp_path):
    src = tmp_path / "pr-tree"
    src.mkdir()
    loop, fake, _ = make(tmp_path, {"levers": [src_lever()]}, env={"AR_TEST_SRC": str(src)}, git_head=lambda p: "f" * 40)
    loop.run(1)
    skipped = row_of(loop, "repair")
    assert skipped["decision"] == "skipped" and "expected " + SHA in skipped["reasons"][0]
    assert len(fake.runs) == 2                       # baseline and replicate only


def test_a_kept_pipeline_source_carries_into_later_rounds(tmp_path):
    src = tmp_path / "pr-tree"
    src.mkdir()
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "repair" else baseline_docs()
    levers = {"levers": [src_lever(), ins_lever("after", cutoff=0.1)]}
    loop, fake, _ = make(tmp_path, levers, script=script, env={"AR_TEST_SRC": str(src)}, git_head=lambda p: SHA)
    loop.run(2)
    assert decisions(loop)[:3] == [("baseline", "baseline"), ("repair", "keep"), ("after", "revert")]
    assert fake.envs[3] == {"MAILROOM_SRC": str(src.resolve())}        # the champion's source persists
    assert row_of(loop, "after")["pipeline_source"]["commit"] == SHA


# ---- resume ----------------------------------------------------------------------------------------------------------

def test_a_new_loop_resumes_from_the_ledger(tmp_path):
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "n1" else baseline_docs()
    levers = {"levers": [reviewer_lever("n1", cutoff=0.1), *[ins_lever(f"n{i}", cutoff=0.1 * i) for i in range(2, 5)]]}
    loop, fake, _ = make(tmp_path, levers, script=script)
    loop.run(1)
    before = len(fake.runs)
    again = lp.Loop(loop.study, fake, state_dir=loop.dir, out=lambda s: None)
    again.run(1)
    rows = again.ledger.rows()
    assert [r["lever"] for r in rows] == ["baseline", "replicate", "n1", "n2"]     # n1, the baseline and its replicate are not re-run
    assert len(fake.runs) == before + 1 and fake.runs.count("ar-t1-r00-baseline") == 1 and fake.runs.count("ar-t1-replicate") == 1
    assert again.state().champ_row["lever"] == "n1"                                 # the champion survived the restart
    assert again.status()["kept"] == ["n1"] and again.status()["reverted"] == ["n2"]
    assert rows[3]["round"] == 2 and rows[3]["champion_run_id"] == "ar-t1-r01-n1"


def test_the_ledger_is_append_only(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2)]})
    loop.step()
    first = (loop.dir / "ledger.jsonl").read_text()
    loop.step()
    assert (loop.dir / "ledger.jsonl").read_text().startswith(first)


# ---- plan ---------------------------------------------------------------------------------------------------------------

def test_plan_runs_nothing_and_names_the_next_lever(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    assert "baseline" in loop.plan()["next"] and fake.runs == []
    loop.step()
    plan = loop.plan()
    assert fake.runs == ["ar-t1-r00-baseline", "ar-t1-replicate", "ar-t1-r01-a"] and plan["lever"] is None      # exhausted after "a"
    loop2, fake2, _ = make(sub(tmp_path, "p"), {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2)]})
    loop2.ensure_baseline(loop2.state())
    plan = loop2.plan()
    assert plan["lever"] == "a" and plan["attached_to"]["node"] == "reviewer" and plan["weakness"][0]["node"] == "reviewer"
    assert len(fake2.runs) == 1


# ---- holdout --------------------------------------------------------------------------------------------------------------

def test_holdout_excludes_production_ids_and_every_dev_document_and_runs_once(tmp_path):
    excl = tmp_path / "prod-excluded.txt"
    excl.write_text("# tuning documents\nx-old-1\nx-old-2\n")
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    base = yaml.safe_load((tmp_path / "base.yaml").read_text())
    base["dataset"]["exclude_ids_file"] = str(excl)
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(base))
    loop.run(1)
    fake.holdout_ids = ["h1", "h2"]
    fake.script = lambda spec, lever: [d("h1", "contract"), d("h2", "correspondence")]
    row = loop.holdout()
    lines = (loop.dir / "holdout-excluded-ids.txt").read_text().splitlines()
    ids = {x for x in lines if x and not x.startswith("#")}
    assert ids == {"x-old-1", "x-old-2", "c1", "c2", "r1", "r2", "i1", "i2"}
    spec = fake.specs["ar-t1-holdout"]
    assert spec["dataset"]["exclude_ids_file"].endswith("holdout-excluded-ids.txt")
    assert row["decision"] == "holdout" and row["disjoint"] is True and row["dev_ids"] == 6 and row["holdout_ids"] == 2
    assert (loop.dir / "holdout.md").is_file()
    with pytest.raises(lp.AutoresearchError, match="once already"):
        loop.holdout()


def test_holdout_overlap_is_a_hard_error_before_any_spend(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    loop.run(1)
    runs = len(fake.runs)
    fake.holdout_ids = ["h1", "c2"]                    # c2 is a dev document
    with pytest.raises(lp.AutoresearchError, match="overlaps the dev draw on 1 document"):
        loop.holdout()
    assert len(fake.runs) == runs                      # prepare() caught it; execute() never ran
    assert not any(r["decision"] == "holdout" for r in loop.ledger.rows())


def test_holdout_overlap_after_the_run_is_also_caught(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    loop.run(1)
    fake.holdout_ids = ["h1"]                                           # the locked draw looked disjoint ...
    fake.script = lambda spec, lever: [d("r1", "correspondence")]       # ... but a dev document slipped in
    with pytest.raises(lp.AutoresearchError, match="overlaps the dev draw"):
        loop.holdout()


def test_assert_disjoint_helper():
    lp.assert_disjoint({"a"}, {"b"})
    with pytest.raises(lp.AutoresearchError, match="a, b"):
        lp.assert_disjoint({"a", "b", "c"}, {"a", "b"})


def test_holdout_needs_a_champion(tmp_path):
    loop, _, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    with pytest.raises(lp.AutoresearchError, match="no champion yet"):
        loop.holdout()


# ---- initials and the key ---------------------------------------------------------------------------------------------------

class _Done:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def _spec_file(tmp_path, mock):
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump({"run_id": "ar-x-r01-y", "job": {"mock": mock, "max_wall_seconds": 100}}))
    return p


def test_a_paid_spec_is_refused_without_initials_and_nothing_runs(tmp_path):
    calls = []
    ex = lp.CliExecutor(runner=lambda *a, **k: calls.append(a) or _Done())
    for method in (ex.execute, ex.prepare):
        with pytest.raises(lp.AutoresearchError, match="--initials XX"):
            method(_spec_file(tmp_path, mock=False))
    assert calls == []


def test_initials_are_validated_not_invented():
    with pytest.raises(lp.AutoresearchError, match="2-6 letters"):
        lp.CliExecutor(initials="x")
    assert lp.CliExecutor(initials="ab").initials == "AB"
    assert lp.CliExecutor().initials is None


def test_paid_start_passes_the_initials_and_a_mock_start_does_not(tmp_path, job_data_dir):
    calls = []
    ex = lp.CliExecutor(initials="QZ", runner=lambda argv, **k: calls.append(argv) or _Done())
    ex.execute(_spec_file(tmp_path, mock=False))
    assert [c[4] for c in calls] == ["preflight", "start"] and calls[0][3] == "run"
    assert calls[1][-2:] == ["--initials", "QZ"] and "--initials" not in calls[0]
    calls.clear()
    lp.CliExecutor(runner=lambda argv, **k: calls.append(argv) or _Done()).execute(_spec_file(tmp_path, mock=True))
    assert "--initials" not in calls[1]


def test_a_failing_child_never_echoes_the_key(tmp_path, job_data_dir):
    ex = lp.CliExecutor(initials="QZ", runner=lambda argv, **k: _Done(1, "", f"401 Bearer {KEY} bad\nkey={KEY}"))
    with pytest.raises(lp.ExecutionError) as err:
        ex.execute(_spec_file(tmp_path, mock=False))
    assert KEY not in str(err.value) and "[redacted]" in str(err.value)


def test_cli_refuses_a_paid_study_without_initials_before_any_network_call(tmp_path, capsys, monkeypatch):
    make(tmp_path, {"levers": [reviewer_lever("a")]}, mock=False)
    from mailroom_sandbox.cli import main

    monkeypatch.setattr(lp, "openrouter_key_remaining", lambda: pytest.fail("the key was checked before the initials"))
    code = main(["autoresearch", "step", "--study", str(tmp_path / "study.yaml")])
    assert code == 2 and "--initials XX" in capsys.readouterr().err


def test_scrub_removes_the_key_and_bearer_tokens():
    assert KEY not in lp.scrub(f"x {KEY} y", {"OPENROUTER_API_KEY": KEY})
    assert "abcdefgh12345" not in lp.scrub("Authorization: Bearer abcdefgh12345", {})


def test_the_key_never_reaches_the_ledger_the_report_or_the_output(tmp_path, capsys):
    levers = {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2)]}
    def script(spec, lever):
        return lp.ExecutionError(f"provider said {KEY}", spec["run_id"]) if lever == "a" else baseline_docs()
    loop, fake, out = make(tmp_path, levers, script=script, key_remaining=lambda: 50.0, mock=False)
    loop.run(2)
    blob = "\n".join(out) + capsys.readouterr().out
    for path in loop.dir.rglob("*"):
        if path.is_file():
            blob += path.read_text(errors="replace")
    assert KEY not in blob and "SECRETKEY" not in blob


# ---- the real executor, offline (mock pipeline) -------------------------------------------------------------------------------

def test_the_mock_smoke_study_runs_end_to_end_with_a_real_disjoint_holdout(tmp_path, job_data_dir, monkeypatch):
    from mailroom_sandbox.paths import repo_root

    monkeypatch.setattr(scoring, "score_run", _REAL_SCORE_RUN)
    monkeypatch.setattr(est_mod, "estimate_round_cost", _REAL_ESTIMATE)
    study = lp.Study.load(repo_root() / "config/autoresearch/mock-smoke/study.yaml")
    loop = lp.Loop(study, lp.CliExecutor(), state_dir=tmp_path / "state", out=lambda s: None)
    rows, stop = loop.run(1)
    assert stop == "max_rounds" and [r["decision"] for r in loop.ledger.rows()][0] == "baseline"
    base = loop.ledger.rows()[0]
    assert base["metrics"]["n"] == 5 and base["dependency_sources"]["pipeline"]["source"]
    assert base["mock"] is True and base["cost_usd"] >= 0
    items = [json.loads(x) for x in (Path(base["run_dir"]) / "items.jsonl").read_text().splitlines() if x.strip()]
    assert any(item.get("usage_by_agent") for item in items)             # the per-agent split is persisted by the run
    assert base["metrics"]["cost_split"] == "by_agent"
    hold = loop.holdout()
    dev = {x.id for x in loop.state().champ_scores.docs}
    held = {json.loads(line)["id"] for line in (Path(hold["run_dir"]) / "dataset.jsonl").read_text().splitlines()}
    assert held and not (dev & held) and hold["disjoint"] is True
    ids = (loop.dir / "holdout-excluded-ids.txt").read_text()
    assert all(i in ids for i in dev)
    report = (loop.dir / "report.md").read_text()
    assert "## Production parity" in report and "vendored llm-mailroom" in report and "## Holdout" in report


@pytest.mark.parametrize("name", ["mailroom-v1", "mock-smoke"])
def test_committed_studies_load_and_plan_without_spending(name, capsys, tmp_path, monkeypatch):
    from mailroom_sandbox.cli import main
    from mailroom_sandbox.paths import repo_root

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    path = repo_root() / "config" / "autoresearch" / name / "study.yaml"
    study = lp.Study.load(path)
    assert study.study == name and study.base_path.is_file() and study.levers_path.is_file()
    assert study.mock is (name == "mock-smoke")
    monkeypatch.setattr(lp.Study, "state_path", property(lambda self: tmp_path / "state"))
    assert main(["autoresearch", "plan", "--study", str(path)]) == 0
    assert "baseline" in capsys.readouterr().out
    Loop = lp.Loop(study, None, state_dir=tmp_path / "state")
    assert Loop.catalog.levers and Loop.base["job"]["mock"] is study.mock       # the catalog fits the base spec
    if name == "mailroom-v1":
        assert study.budget.study_usd == 15 and study.budget.round_api_cap_usd == 1.0 and study.budget.max_round_cap_usd == 4.0
        assert study.base_spec()["job"]["mock"] is False and "reviewer" not in study.base_spec()


# ---- the replicate baseline and the measured noise floor ---------------------------------------------------------

def noisy_replicate(spec, lever):
    """The replicate differs from the baseline by one document: that is the run-to-run noise."""
    return with_utils(baseline_docs(), i1=1.0) if lever == "replicate" else baseline_docs()


def test_the_replicate_runs_right_after_the_baseline_and_records_the_noise_floor(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, script=noisy_replicate, cost=0.01)
    loop.step()
    rows = loop.ledger.rows()
    assert [r["decision"] for r in rows][:3] == ["baseline", "replicate", "revert"]
    assert fake.runs[:2] == ["ar-t1-r00-baseline", "ar-t1-replicate"]
    base, rep = fake.specs["ar-t1-r00-baseline"], fake.specs["ar-t1-replicate"]
    strip = lambda s: {k: v for k, v in s.items() if k not in ("run_id", "trace")}   # noqa: E731
    assert strip(base) == strip(rep) and "lever:replicate" in rep["trace"]["tags"]    # the identical champion spec
    row = rows[1]
    champ = loop.state().champ_scores
    expected = scoring.paired_delta({d.id: d.utility for d in champ.docs}, {d.id: (1.0 if d.id == "i1" else d.utility) for d in champ.docs},
                                    champ.classes(), n_boot=300, seed=0, ci=0.90)
    noise = row["noise"]
    assert noise["abs_mean_delta"] == pytest.approx(abs(expected.mean), abs=1e-5) and expected.mean == pytest.approx(0.4 / 6)
    assert noise["ci_half_width"] == pytest.approx((expected.ci_high - expected.ci_low) / 2, abs=1e-5)
    assert noise["effective_floor"] == pytest.approx(max(abs(expected.mean), (expected.ci_high - expected.ci_low) / 2), abs=1e-5)
    assert noise["effective_floor"] > 0 and row["champion_run_id"] == "ar-t1-r00-baseline" and row["round"] is None
    assert noise["measured_round_cost_usd"] == pytest.approx(0.06) and row["cost_usd"] == pytest.approx(0.06)   # a measured cost per round
    assert loop.noise_floor(loop.state()) == pytest.approx(noise["effective_floor"])
    assert row_of(loop, "a")["noise_floor"] == pytest.approx(noise["effective_floor"])             # the keep rule used it
    assert "Noise floor (replicate baseline)" in (loop.dir / "report.md").read_text()


def test_the_configured_floor_wins_when_it_is_larger(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, study_over={"noise_floor": 0.9}, cost=0.01)
    loop.step()
    assert row_of(loop, "replicate")["noise"]["abs_mean_delta"] == 0       # identical runs: no measured noise
    assert loop.noise_floor(loop.state()) == 0.9 and row_of(loop, "a")["noise_floor"] == 0.9


def test_a_gain_inside_the_measured_noise_is_reverted_that_zero_noise_would_keep(tmp_path):
    def noisy(spec, lever):          # the replicate wobbles by -0.1 on average; "small" gains +0.067 with a CI above zero
        docs = baseline_docs()
        if lever == "replicate":
            return with_utils(docs, c1=0.0, i1=1.0)
        return with_utils(docs, r1=-0.05, r2=-0.05) if lever == "small" else docs
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("small")]}, script=noisy)
    loop.step()
    row = row_of(loop, "small")
    floor = row_of(loop, "replicate")["noise"]["effective_floor"]
    assert floor >= 0.1 and 0 < row["delta"]["ci_low"] < floor      # |mean| 0.1, and the CI half-width is wider still
    assert row["decision"] == "revert" and any("gain is not established" in r for r in row["reasons"])    # a zero floor would keep it
    quiet, _, _ = make(sub(tmp_path, "q"), {"levers": [reviewer_lever("small")]},
                       script=lambda s, l: with_utils(baseline_docs(), r1=-0.05, r2=-0.05) if l == "small" else baseline_docs())
    quiet.step()
    assert row_of(quiet, "small")["decision"] == "keep" and row_of(quiet, "replicate")["noise"]["effective_floor"] == 0


def test_no_lever_is_kept_or_run_before_the_replicate_exists(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]})
    state = loop.state()
    assert loop.ensure_baseline(state) is None and loop.noise_floor(state) is None and state.replicate is None
    with pytest.raises(lp.AutoresearchError, match="replicate baseline"):
        loop._candidate_round(state, loop.catalog.levers[0], None, lp.RoundPlan(cap=1.0))
    assert fake.runs == ["ar-t1-r00-baseline"] and decisions(loop) == [("baseline", "baseline")]


def test_a_failed_replicate_stops_before_any_candidate_and_is_retried(tmp_path):
    state = {"fail": True}
    def script(spec, lever):
        if lever == "replicate" and state["fail"]:
            return lp.ExecutionError("down", spec["run_id"])
        return baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, script=script)
    with pytest.raises(lp.AutoresearchError, match="replicate failed"):
        loop.step()
    rows = loop.ledger.rows()
    assert [(r["lever"], r["decision"]) for r in rows] == [("baseline", "baseline"), ("replicate", "error")]
    assert rows[1]["cost_usd"] == 1.0                      # no dataset rows: charged its full round cap
    state["fail"] = False
    loop.step()                                             # the next call retries the replicate, then runs the lever
    assert [r["decision"] for r in loop.ledger.rows()] == ["baseline", "error", "replicate", "revert"]


def test_a_replicate_on_other_documents_is_refused(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, script=lambda s, l: [d("zz", "contract")] if l == "replicate" else baseline_docs())
    with pytest.raises(lp.AutoresearchError, match="different documents"):
        loop.step()


def test_plan_and_status_report_the_noise_floor(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, script=noisy_replicate)
    loop.ensure_baseline(loop.state())
    plan = loop.plan()
    assert plan["replicate"] is False and plan["noise_floor"] is None and "replicate" in plan["next"] and plan["lever"] == "a"
    loop.step()
    status = loop.status()
    assert status["replicate"] is True and status["noise_floor"] > 0 and status["rounds"] == 1


# ---- round caps: the runtime bound, per-lever overrides, the study reservation --------------------------------------

def bound_estimate(monkeypatch, bounds, *, usd=0.05, measured=True, seen=None):
    """Patch the estimator: ``bounds`` maps a lever tag to its runtime-bound USD (default 0.1)."""
    def estimate(champ, champ_spec, cand_spec, safety=1.0):
        tag = next((t.split(":", 1)[1] for t in cand_spec["trace"]["tags"] if t.startswith("lever:")), "")
        if seen is not None:
            seen[tag] = safety
        return est_mod.Estimate(usd=usd, basis="by_agent", detail={}, unpriced=[], runtime_bound_usd=bounds.get(tag, 0.1), measured=measured)
    monkeypatch.setattr(est_mod, "estimate_round_cost", estimate)


def tiered(i, tier, cutoff, **kw):
    return reviewer_lever(i, cutoff=cutoff, tier=tier, group="supervisor", **kw)


def test_a_tier_two_lever_over_the_round_cap_gets_its_derived_cap_and_runs(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {"sup2": 2.3})
    loop, fake, _ = make(tmp_path, {"levers": [tiered("sup2", 2, 0.2, round_cap_auto=True)]})
    loop.run(1)
    row = row_of(loop, "sup2")
    assert row["decision"] in ("keep", "revert") and row["round_cap_usd"] == 3.0       # ceil(2.3 x 1.2 / 0.25) x 0.25
    assert fake.specs["ar-t1-r01-sup2"]["job"]["api_cost_cap_usd"] == 3.0               # the run's own ApiBudget cap
    assert fake.specs["ar-t1-r00-baseline"]["job"]["api_cost_cap_usd"] == 1             # the baseline keeps the study's cap
    assert row["estimate"]["runtime_bound_usd"] == 2.3 and row["estimate"]["usd"] == 0.05   # both figures are reported


def test_the_runtime_bound_not_the_per_agent_figure_decides_a_plain_levers_skip(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {"plain": 1.4}, usd=0.05)
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("plain")]})
    loop.run(1)
    row = row_of(loop, "plain")
    assert row["decision"] == "skipped" and row["reasons"][0].startswith("over_round_cap") and row["round_cap_usd"] == 1
    assert row["estimate"] == {**row["estimate"], "usd": 0.05, "runtime_bound_usd": 1.4} and row["cost_usd"] == 0.0


def test_a_lever_whose_bound_exceeds_the_max_round_cap_is_skipped(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {"huge": 5.0, "ok": 3.0})
    levers = {"levers": [tiered("huge", 3, 0.2, round_cap_auto=True), tiered("ok", 3, 0.25, round_cap_auto=True)]}
    loop, fake, _ = make(tmp_path, levers, study_over={"budget": {"study_usd": 12, "round_api_cap_usd": 1, "round_wall_seconds": 600,
                                                                   "min_key_remaining_usd": 0, "max_round_cap_usd": 4.0}})
    loop.run(2)
    huge = row_of(loop, "huge")
    assert huge["decision"] == "skipped" and huge["reasons"][0].startswith("over_round_cap") and huge["round_cap_usd"] == 4.0
    assert "ar-t1-r01-huge" not in fake.runs and row_of(loop, "ok")["round_cap_usd"] == 3.75      # 3.0 x 1.2 = 3.6, rounded up to 3.75
    assert fake.specs["ar-t1-r01-ok"]["job"]["api_cost_cap_usd"] == 3.75


def test_an_explicit_round_cap_usd_is_used_and_clamped_to_the_maximum(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {"two": 1.5, "wide": 1.5})
    levers = {"levers": [reviewer_lever("two", cutoff=0.2, round_cap_usd=2.0), reviewer_lever("wide", cutoff=0.3, round_cap_usd=9.0)]}
    loop, fake, _ = make(tmp_path, levers)
    loop.run(2)
    assert row_of(loop, "two")["round_cap_usd"] == 2.0 and row_of(loop, "wide")["round_cap_usd"] == 4.0   # max_round_cap_usd default 4.0


def test_without_a_champion_measurement_the_tier_default_cap_applies(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {}, measured=False)
    levers = {"levers": [tiered("t1", 1, 0.2, round_cap_auto=True), tiered("t2", 2, 0.25, round_cap_auto=True),
                         tiered("t3", 3, 0.3, round_cap_auto=True)]}
    loop, fake, _ = make(tmp_path, levers, study_over={"budget": {"study_usd": 20, "round_api_cap_usd": 1, "round_wall_seconds": 600,
                                                                   "min_key_remaining_usd": 0}}, script=noisy_replicate)
    loop.run(3)
    assert [row_of(loop, i)["round_cap_usd"] for i in ("t1", "t2", "t3")] == [1.5, 3.0, 4.0]


def test_a_lever_that_the_study_budget_cannot_reserve_is_skipped_and_a_cheaper_one_runs(tmp_path, monkeypatch):
    bound_estimate(monkeypatch, {"sup": 2.3})
    levers = {"levers": [tiered("sup", 2, 0.2, round_cap_auto=True), reviewer_lever("plain", cutoff=0.4, node="insurance_claims_specialist")]}
    over = {"budget": {"study_usd": 2.5, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 0}}
    loop, fake, _ = make(tmp_path, levers, study_over=over)
    loop.run(2)
    sup = row_of(loop, "sup")
    # 0.12 spent by the baseline and its replicate; the 3.0 cap cannot be reserved from the remaining 2.38
    assert sup["decision"] == "skipped" and sup["reasons"][0].startswith("over_study_budget") and sup["cost_usd"] == 0.0
    assert row_of(loop, "plain")["decision"] in ("keep", "revert")


def test_a_lever_with_estimate_safety_scales_the_estimate_by_it_and_the_studys_factor(tmp_path, monkeypatch):
    seen: dict = {}
    bound_estimate(monkeypatch, {}, seen=seen)
    levers = {"levers": [reviewer_lever("calls", cutoff=0.2, estimate_safety=2.0), reviewer_lever("plain", cutoff=0.3)]}
    loop, fake, _ = make(tmp_path, levers, study_over={"estimate_safety": 1.5})
    loop.run(2)
    assert seen["calls"] == 3.0 and seen["plain"] == 1.5


# ---- aborted_cap --------------------------------------------------------------------------------------------------

CAP_MESSAGE = "api_cost_cap_usd=1.0 reached (est_api_usd=1.2000 at $0.4/$1.2 per 1M tokens) — aborting to protect spend"


def test_a_run_aborted_by_its_api_cap_is_recorded_charged_the_full_cap_and_not_a_revert(tmp_path):
    def script(spec, lever):
        return lp.ExecutionError(f"`sandbox run start` exited 1: {CAP_MESSAGE}", spec["run_id"]) if lever == "dear" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("dear"), reviewer_lever("next", cutoff=0.2)]}, script=script)
    loop.step()
    row = row_of(loop, "dear")
    assert row["decision"] == "aborted_cap" and row["cost_usd"] == 1.0 and row["round_cap_usd"] == 1
    assert "not a revert" in row["reasons"][0]
    assert lp.consecutive_reverts(loop.ledger.rows()) == 0                                 # neutral: neither a revert nor a keep
    assert loop.state().champ_row["lever"] == "baseline"
    assert loop.status()["aborted_cap"] == ["dear"] and loop.status()["reverted"] == []
    assert loop.state().spent == pytest.approx(0.06 + 0.06 + 1.0)                          # baseline + replicate + the full cap
    loop.step()
    assert "ar-t1-r02-next" in fake.runs and "ar-t1-r03-dear" not in fake.runs            # decided: not retried


def test_the_run_checkpoint_marks_an_api_cap_abort_even_when_the_child_exits_cleanly(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert not lp._aborted_by_cap(run_dir, None) and not lp._aborted_by_cap(None, "boom")
    (run_dir / "checkpoint.json").write_text(json.dumps({"state": "failed", "last_error": {"type": "api_cost_cap", "message": "x"}}))
    assert lp._aborted_by_cap(run_dir, None)
    (run_dir / "checkpoint.json").write_text(json.dumps({"state": "failed", "last_error": {"type": "max_wall"}}))
    assert not lp._aborted_by_cap(run_dir, None)
    assert lp._aborted_by_cap(None, CAP_MESSAGE)


def test_an_aborted_tier_one_lever_unblocks_tier_two_like_a_revert_does(tmp_path):
    def script(spec, lever):
        return lp.ExecutionError(CAP_MESSAGE, spec["run_id"]) if lever == "t1" else baseline_docs()
    t1 = reviewer_lever("t1", cutoff=0.2, tier=1, group="g")
    t2 = reviewer_lever("t2", cutoff=0.1, tier=2, group="g", requires=[{"kept": {"group": "g", "tier": 1}},
                                                                    {"all_reverted_positive": {"group": "g", "tier": 1}}])
    loop, fake, _ = make(tmp_path, {"levers": [t2, t1]}, script=script)
    loop.run(3)
    assert levers_in(loop)[:3] == ["baseline", "t1", "t2"] and row_of(loop, "t1")["decision"] == "aborted_cap"


def test_an_error_or_aborted_round_without_dataset_rows_is_charged_its_round_cap(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]},
                         script=lambda s, l: lp.ExecutionError("down", s["run_id"]) if l == "x" else baseline_docs())
    loop.step()
    row = row_of(loop, "x")
    assert row["decision"] == "error" and row["cost_usd"] == 1.0
    assert lp._charge(None, 2.5, False) == 2.5 and lp._charge(None, 2.5, True) == 2.5
    scored = RunScores(run_id="r", run_dir="/x", docs=[d("a", "contract", cost_usd=0.2)])
    assert lp._charge(scored, 2.5, False) == 0.2 and lp._charge(scored, 2.5, True) == 2.5
    assert lp._charge(RunScores(run_id="r", run_dir="/x", docs=[]), 2.5, False) == 2.5


# ---- a key without a limit ---------------------------------------------------------------------------------------------

def test_a_key_without_a_limit_warns_in_the_ledger_and_continues_under_the_study_budget(tmp_path):
    loop, fake, out = make(tmp_path, {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2)]}, mock=False, key_remaining=lambda: None)
    loop.run(2)
    warnings = [r for r in loop.ledger.rows() if r["decision"] == "warning"]
    assert len(warnings) == 1 and warnings[0]["lever"] == "key_check" and "no spend limit" in warnings[0]["reasons"][0]
    assert len(fake.runs) >= 3                                                           # the study went on
    assert sum("no spend limit" in line for line in out) == 1
    assert loop.status()["warnings"] == [warnings[0]["reasons"][0]]
    assert lp.consecutive_reverts(loop.ledger.rows()) == 2                              # the warning row is neutral
    assert "## Warnings" in (loop.dir / "report.md").read_text()
    # the study budget still binds
    tight, tfake, _ = make(sub(tmp_path, "t"), {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=lambda: None,
                           study_over={"budget": {"study_usd": 1.0, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 3}})
    assert tight.run(1)[1] == "study_budget" and tfake.runs == ["ar-t1-r00-baseline"]    # no room left for the replicate


# ---- the reviewer guard at stamp time -------------------------------------------------------------------------------------

@pytest.mark.parametrize("reviewer", [
    {"backend": "api", "model": "openai/gpt-4o", "allow_chat_model": True, "classes": {"contract": 0.5}},
    {"backend": "jev", "model": "jev-1.13.0", "classes": {"contract": 0.5}},
    {"backend": "local", "model": "Qwen/Qwen3-8B", "classes": {"contract": 0.5}},
])
def test_stamping_a_paid_candidate_with_a_non_decisions_reviewer_is_refused(tmp_path, reviewer):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, mock=False)
    spec = {**loop.base, "reviewer": reviewer}
    with pytest.raises(lp.AutoresearchError, match="refused in a paid study|allow_chat_model|not a Decisions-API"):
        loop._stamp(spec, run_id="ar-t1-x", lever_id="x")
    loop._stamp({**loop.base}, run_id="ar-t1-x", lever_id="x")           # the Decisions reviewer of the base is fine


# ---- supervisor placements through the loop ----------------------------------------------------------------------------------

def test_placement_sequence_winner_then_placement_a_then_placement_b(tmp_path):
    sup_patch = {f"agent_routes.{r}": {"provider": "openrouter", "model": "m/strong"} for r in ("judge", "boss")}
    sup = lever_yaml(id="sup-a", node=["judge", "boss"], classes="all", tier=1, group="supervisor", patch=sup_patch)
    cat = {"levers": [sup], "placements": [{"group": "supervisor", "roles": ["judge", "boss"], "keep_on": [["judge"], ["boss"]]}]}

    def script(spec, lever):
        routes = spec.get("agent_routes") or {}
        strong = [r for r in ("judge", "boss") if (routes.get(r) or {}).get("model") == "m/strong"]
        fake.cost = {2: 0.02, 1: 0.01, 0: 0.005}[len(strong)]
        docs = [d("c1", "contract"), d("j1", "correspondence", "review", -0.25, "judge:rejected"),
                d("j2", "correspondence", "review", -0.25, "judge:rejected"), d("j3", "correspondence", "review", -0.25, "judge:rejected")]
        return with_utils(docs, j1=1.0, j2=1.0) if strong else docs
    loop, fake, _ = make(tmp_path, cat, script=script)
    loop.run(4)
    winner = row_of(loop, "sup-a")
    assert winner["decision"] == "keep" and winner["patch_before"] == {"agent_routes.judge": None, "agent_routes.boss": None}
    a, b = row_of(loop, "sup-a@judge"), row_of(loop, "sup-a@boss")
    assert a["decision"] == "keep"                                          # cheaper, same quality: kept
    # B ran on top of champion A (judge strong, boss none), and its absolute patch moved the winner to the boss
    spec_b = fake.specs[b["run_id"]]["agent_routes"]
    assert spec_b["boss"]["model"] == "m/strong" and "judge" not in spec_b
    assert b["champion_run_id"] == a["run_id"]


def test_the_max_round_cap_cannot_be_below_the_round_cap():
    with pytest.raises(ValueError, match="max_round_cap_usd"):
        lp.Budget(study_usd=5, round_api_cap_usd=2, round_wall_seconds=600, max_round_cap_usd=1)
    assert lp.Budget(study_usd=5, round_api_cap_usd=1, round_wall_seconds=600).max_round_cap_usd == 4.0
