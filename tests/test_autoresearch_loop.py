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
    return [(r["lever"], r["decision"]) for r in loop.ledger.rows()]


# ---- keep / revert ----------------------------------------------------------------------------------------

def test_keep_path_promotes_the_candidate_to_champion_and_records_everything(tmp_path):
    def script(spec, lever):
        docs = baseline_docs()
        return with_utils(docs, r1=1.0, r2=1.0) if lever == "fix" else docs
    loop, fake, out = make(tmp_path, {"levers": [reviewer_lever("fix")]}, script=script)
    rows, stop = loop.run(1)
    assert decisions(loop) == [("baseline", "baseline"), ("fix", "keep")]
    keep = loop.ledger.rows()[1]
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
    assert [r["decision"] for r in loop.ledger.rows()] == ["baseline", "revert", "revert", "revert"]
    assert len(fake.runs) == 4                         # baseline + 3 candidates, never a fourth


def test_a_keep_resets_the_revert_count(tmp_path):
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "n3" else baseline_docs()
    # n1, n2 (reverts) then n3 (keep) fix the reviewer weakness; m1..m4 then attach to the insurance specialist
    levers = {"levers": [*[reviewer_lever(f"n{i}", cutoff=0.1 * i) for i in range(1, 4)], *[ins_lever(f"m{i}", cutoff=0.1 + 0.01 * i) for i in range(1, 5)]]}
    loop, fake, _ = make(tmp_path, levers, script=script)
    _, stop = loop.run(10)
    verdicts = [r["decision"] for r in loop.ledger.rows()]
    assert verdicts == ["baseline", "revert", "revert", "keep", "revert", "revert", "revert"]    # the keep reset the count
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
    assert stop == "levers_exhausted" and len(fake.runs) == 1


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
    row = loop.ledger.rows()[1]
    assert row["decision"] == "error" and "boom" in row["reasons"][0] and KEY not in json.dumps(row)
    assert lp.consecutive_reverts(loop.ledger.rows()) == 1
    assert loop.state().champ_row["lever"] == "baseline"


def test_a_candidate_on_different_documents_is_refused(tmp_path):
    def script(spec, lever):
        return [d("zz", "contract")] if lever == "x" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("x")]}, script=script)
    loop.step()
    row = loop.ledger.rows()[1]
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
    # baseline: 6 documents x 0.05 = 0.30 spent; 0.30 + 1 cap > 1.2 -> stop before any candidate
    assert stop == "study_budget" and [r["decision"] for r in loop.ledger.rows()] == ["baseline"]


def test_budget_allows_rounds_while_spend_plus_cap_fits(tmp_path):
    over = {"budget": {"study_usd": 1.5, "round_api_cap_usd": 1, "round_wall_seconds": 600, "min_key_remaining_usd": 0}}
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a"), reviewer_lever("b", cutoff=0.2), reviewer_lever("c", cutoff=0.1)]},
                         study_over=over, cost=0.05)
    _, stop = loop.run(5)
    assert stop == "study_budget" and [r["lever"] for r in loop.ledger.rows()] == ["baseline", "a"]   # 0.6 + 1 > 1.5


def test_paid_study_checks_the_keys_remaining_limit(tmp_path):
    loop, fake, _ = make(tmp_path, {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=lambda: 3.5)
    _, stop = loop.run(1)
    assert stop == "key_low" and fake.runs == []                       # 3.5 - 1 cap < 3 reserve
    loop2, fake2, _ = make(sub(tmp_path, "ok"), {"levers": [reviewer_lever("a")]}, mock=False, key_remaining=lambda: 10.0)
    loop2.run(1)
    assert [r["decision"] for r in loop2.ledger.rows()][:2] == ["baseline", "revert"]
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
    assert len(fake.runs) == 2


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
    assert [r["lever"] for r in loop.ledger.rows()] == ["baseline", "plain"] and stop == "levers_exhausted"
    ready, fake2, _ = make(sub(tmp_path, "b"), levers, env={"AR_TEST_MISSING": "1"})
    ready.run(5)
    assert "needs-env" in [r["lever"] for r in ready.ledger.rows()]


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
    order = [r["lever"] for r in loop.ledger.rows()]
    assert order[:3] == ["baseline", "t1", "t2"]
    t1_row = loop.ledger.rows()[1]
    assert t1_row["decision"] == "revert" and t1_row["delta"]["mean"] > 0


def test_tier_two_stays_locked_when_tier_one_reverts_with_a_negative_mean(tmp_path):
    t1 = reviewer_lever("t1", cutoff=0.2, tier=1, group="g")
    t2 = reviewer_lever("t2", cutoff=0.1, tier=2, group="g", requires=[{"kept": {"group": "g", "tier": 1}},
                                                                    {"all_reverted_positive": {"group": "g", "tier": 1}}])
    def script(spec, lever):
        return with_utils(baseline_docs(), c1=0.5) if lever == "t1" else baseline_docs()
    loop, fake, _ = make(tmp_path, {"levers": [t1, t2]}, script=script)
    _, stop = loop.run(5)
    assert stop == "levers_exhausted" and [r["lever"] for r in loop.ledger.rows()] == ["baseline", "t1"]


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
    rows = loop.ledger.rows()
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
    assert fake.envs[0] == {} and fake.envs[1] == {"MAILROOM_SRC": str(src.resolve())}     # only that round's process
    row = loop.ledger.rows()[1]
    assert row["pipeline_source"] == {"env": "AR_TEST_SRC", "commit": SHA, "lever": "repair", "commit_found": SHA}
    assert str(src) not in json.dumps(loop.ledger.rows()) and str(src) not in (loop.dir / "report.md").read_text()


def test_pipeline_source_at_the_wrong_commit_is_skipped_not_run(tmp_path):
    src = tmp_path / "pr-tree"
    src.mkdir()
    loop, fake, _ = make(tmp_path, {"levers": [src_lever()]}, env={"AR_TEST_SRC": str(src)}, git_head=lambda p: "f" * 40)
    loop.run(1)
    skipped = loop.ledger.rows()[1]
    assert skipped["decision"] == "skipped" and "expected " + SHA in skipped["reasons"][0]
    assert len(fake.runs) == 1


def test_a_kept_pipeline_source_carries_into_later_rounds(tmp_path):
    src = tmp_path / "pr-tree"
    src.mkdir()
    def script(spec, lever):
        return with_utils(baseline_docs(), r1=1.0, r2=1.0) if lever == "repair" else baseline_docs()
    levers = {"levers": [src_lever(), ins_lever("after", cutoff=0.1)]}
    loop, fake, _ = make(tmp_path, levers, script=script, env={"AR_TEST_SRC": str(src)}, git_head=lambda p: SHA)
    loop.run(2)
    assert decisions(loop)[:3] == [("baseline", "baseline"), ("repair", "keep"), ("after", "revert")]
    assert fake.envs[2] == {"MAILROOM_SRC": str(src.resolve())}        # the champion's source persists
    assert loop.ledger.rows()[2]["pipeline_source"]["commit"] == SHA


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
    assert [r["lever"] for r in rows] == ["baseline", "n1", "n2"]                  # n1 is not re-run, nor the baseline
    assert len(fake.runs) == before + 1 and fake.runs.count("ar-t1-r00-baseline") == 1
    assert again.state().champ_row["lever"] == "n1"                                 # the champion survived the restart
    assert again.status()["kept"] == ["n1"] and again.status()["reverted"] == ["n2"]
    assert rows[2]["round"] == 2 and rows[2]["champion_run_id"] == "ar-t1-r01-n1"


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
    assert fake.runs == ["ar-t1-r00-baseline", "ar-t1-r01-a"] and plan["lever"] is None      # exhausted after "a"
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
        assert study.budget.study_usd == 15 and study.budget.round_api_cap_usd == 1.0
        assert study.base_spec()["job"]["mock"] is False and "reviewer" not in study.base_spec()
