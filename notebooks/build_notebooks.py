#!/usr/bin/env python3
"""Regenerate the offline demonstration notebooks (stdlib + nbformat)."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def md(text: str) -> dict:
    src = text.lstrip("\n")
    if not src.endswith("\n"):
        src += "\n"
    return {"cell_type": "markdown", "metadata": {}, "source": src}


def code(text: str) -> dict:
    src = text.lstrip("\n")
    if not src.endswith("\n"):
        src += "\n"
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": src,
    }


def notebook(*cells: dict) -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "cells": [
            {**cell, "id": f"c{i:02d}"}
            for i, cell in enumerate(cells)
        ],
    }


BOOT = '''
import sys
from pathlib import Path

def find_repo_root() -> Path:
    for cand in [Path.cwd(), *Path.cwd().parents, Path("__file__" if False else ".").resolve()]:
        pass
    here = Path.cwd()
    seeds = [here, *(here.parents)]
    try:
        seeds.append(Path(__file__).resolve().parent)  # noqa: F821 — only in .py
    except NameError:
        pass
    seen = set()
    for seed in seeds:
        for cand in [seed, *seed.parents]:
            resolved = cand.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "pyproject.toml").is_file() and (resolved / "reports").is_dir():
                return resolved
    raise RuntimeError("repo root not found")

ROOT = find_repo_root()
sys.path.insert(0, str(ROOT / "notebooks"))
sys.path.insert(0, str(ROOT / "src"))

from _lib import bootstrap, isolate_outputs

ROOT = bootstrap(ROOT)
OUT = isolate_outputs(ROOT)
print("repo root :", ROOT)
print("outputs   :", OUT)
'''

# The NameError path is messy. Use a cleaner bootstrap cell that matches tests
# (find_repo_root + pyproject.toml) and then imports _lib.

BOOT = '''
import sys
from pathlib import Path

def find_repo_root() -> Path:
    """Walk up from cwd (hostile kernels start in notebooks/)."""
    for cand in [Path.cwd(), *Path.cwd().parents]:
        if (cand / "pyproject.toml").is_file() and (cand / "reports").is_dir():
            return cand
    raise RuntimeError("repo root not found")

ROOT = find_repo_root()
sys.path.insert(0, str(ROOT / "notebooks"))
sys.path.insert(0, str(ROOT / "src"))

from _lib import bootstrap, isolate_outputs

ROOT = bootstrap(ROOT)
OUT = isolate_outputs(ROOT)
print("repo root :", ROOT)
print("sys.path[0]:", sys.path[0])
print("notebook outputs ->", OUT)
'''


N1 = notebook(
    md(
        """# 01 — Activate, overlay, and cutover

This notebook is the **config story** of the local mailroom sandbox. The
sandbox does **not** fork the 13-node LangGraph pipeline. It rewrites every
taxonomy agent onto a local serving tag, writes
[`data/runtime/taxonomy.yaml`](../data/runtime/taxonomy.yaml), and
monkeypatches mailroom's hardcoded `CONFIG_PATH`.

Canonical code:

- [`src/mailroom_sandbox/runtime.py`](../src/mailroom_sandbox/runtime.py) — `activate()`
- [`src/mailroom_sandbox/overlay.py`](../src/mailroom_sandbox/overlay.py) — merge, map, rewrite
- [`config/profiles/ollama.yaml`](../config/profiles/ollama.yaml)
- [`config/models.yaml`](../config/models.yaml)
- [`config/taxonomy.overlay.yaml`](../config/taxonomy.overlay.yaml)
- [`config/components.yaml`](../config/components.yaml)

**Offline / LLM-free.** Mock machinery only. Live Ollama is
`sandbox cutover --local` after `sandbox up` — not this notebook.
"""
    ),
    code(BOOT),
    md(
        """## Why `DEFAULT_PROVIDER=ollama` is not enough

Mailroom's shipped taxonomy still names OpenRouter champion ids such as
`qwen/qwen3.7-flash`. Pointing the base URL at Ollama without rewriting the
`model` field makes Ollama try to pull a slash-id it does not have.
[`overlay.map_model`](../src/mailroom_sandbox/overlay.py) is the map.
"""
    ),
    code(
        '''
from mailroom_sandbox.overlay import (
    list_profiles,
    load_profile,
    map_model,
    serving_family,
    build_merged_taxonomy,
    agent_assignments,
    parse_agent_models,
)
from mailroom_sandbox.providers import endpoints_for

print("profiles:", list_profiles())
ollama = load_profile("ollama")
openrouter = load_profile("openrouter")
print("ollama provider / default_model:", ollama.get("provider"), ollama.get("default_model"))
print("openrouter is opt-in:", openrouter.get("provider") == "openrouter")
print("endpoints ollama:", endpoints_for(ollama).base_url)
print()
print("champion qwen/qwen3.7-flash -> ollama tag:", map_model("qwen/qwen3.7-flash", "ollama"))
print("same champion -> vllm tag   :", map_model("qwen/qwen3.7-flash", "vllm"))
print("serving family(ollama)      :", serving_family(ollama))
'''
    ),
    md(
        """## `activate()` writes the runtime taxonomy

`activate("ollama")` deep-merges the vendored/base taxonomy + overlay +
component routing, rewrites agents, then writes
`data/runtime/taxonomy.yaml`. Isolated evals call this for you; notebooks
and tests call it explicitly **before** importing mailroom graph code.
"""
    ),
    code(
        '''
from mailroom_sandbox.runtime import activate, active

act = activate("ollama", load_env_file=False)
print("profile        :", act.profile_name)
print("taxonomy path  :", act.taxonomy_path)
print("patched config :", act.patched_config, "(False until vendored mailroom is on sys.path)")
print("n agents       :", len(act.assignments))
print()
print(f"{'agent':32s} {'provider':12s} model")
for name, provider, model in act.assignments[:12]:
    print(f"{name:32s} {provider:12s} {model}")
print("...")
judge = next(row for row in act.assignments if row[0] == "judge")
sorter = next(row for row in act.assignments if row[0] == "sorter")
print("sorter ->", sorter)
print("judge  ->", judge)
assert sorter[1] == "ollama"
assert "/" not in sorter[2], "local tags must not keep the OpenRouter slash-id"
print("active() is the same object:", active() is act)
'''
    ),
    md(
        """## Surgical `--agent-model` wins last

`--model qwen3:8b` rewrites **every** agent. `--agent-model judge=qwen3:14b`
is the cutover knob that only touches one name. Same merge order as
[`overlay.build_merged_taxonomy`](../src/mailroom_sandbox/overlay.py):
profile rewrite → overlay knobs → surgical models.
"""
    ),
    code(
        '''
surgical = parse_agent_models(["judge=qwen3:14b"])
tax = build_merged_taxonomy(ollama, agent_models=surgical)
by_name = {n: m for n, _p, m in agent_assignments(tax)}
print("judge after surgical override:", by_name["judge"])
print("sorter unchanged            :", by_name["sorter"])
assert by_name["judge"] == "qwen3:14b"
assert by_name["sorter"] != "qwen3:14b"

# Overlay knobs (temperature / max_tokens) survive the rewrite.
from mailroom_sandbox.overlay import load_yaml
from mailroom_sandbox.paths import config_dir
overlay = load_yaml(config_dir() / "taxonomy.overlay.yaml")
print("overlay sorter.max_tokens:", (overlay.get("agents") or {}).get("sorter", {}).get("max_tokens"))
print("runtime sorter.max_tokens:", (tax.get("agents") or {}).get("sorter", {}).get("max_tokens"))
'''
    ),
    md(
        """## Component gates (not a graph fork)

[`config/components.yaml`](../config/components.yaml) enables/disables
isolated evals and overlays confidence routing. It does **not** add or
remove LangGraph nodes.
"""
    ),
    code(
        '''
from mailroom_sandbox.components import load_components, is_enabled, routing_overlay

cfg = load_components()
print("retired_agents:", cfg.get("retired_agents"))
print("sorter enabled:", is_enabled("agents", "sorter"))
print("court_opinions_specialist enabled:", is_enabled("agents", "court_opinions_specialist"))
print("routing overlay fragment:")
import json
print(json.dumps(routing_overlay(cfg), indent=2))
print()
print("HONEST GAP: live 13-node topology still lives in llm-mailroom.")
print("This sandbox overlays config; it does not reimplement graph/routing.py.")
'''
    ),
)


N2 = notebook(
    md(
        """# 02 — Fixture catalog (offline gold)

The sandbox ships a tiny, attributed catalog so every runner can execute
without Hub, OpenRouter, or a GPU. This notebook walks the catalog the
same way [`datasets.py`](../src/mailroom_sandbox/datasets.py) does.

Sources:

- [`data/fixtures/manifest.csv`](../data/fixtures/manifest.csv)
- [`data/fixtures/ATTRIBUTION.md`](../data/fixtures/ATTRIBUTION.md)
- [`data/fixtures/hf/docclass_mini.jsonl`](../data/fixtures/hf/docclass_mini.jsonl)
- [`data/fixtures/legalbench/contract_qa.jsonl`](../data/fixtures/legalbench/contract_qa.jsonl)
- [`data/fixtures/agents/*.jsonl`](../data/fixtures/agents)
- [`data/fixtures/intake/hello.pdf`](../data/fixtures/intake/hello.pdf)
"""
    ),
    code(BOOT),
    md("## Manifest rows and class mix"),
    code(
        '''
from collections import Counter
from mailroom_sandbox.datasets import (
    load_manifest,
    fixture_file,
    parse_expected_fields,
    dataset_fingerprint,
    load_hf_fixtures,
    load_legalbench_fixtures,
    load_agent_fixtures,
    agent_fixture_path,
)
from mailroom_sandbox.paths import fixtures_dir

rows = load_manifest()
print("n manifest rows:", len(rows))
print("fingerprint    :", dataset_fingerprint(rows))
print("classes        :", dict(Counter(r["expected_doc_class"] for r in rows)))
print("stages         :", dict(Counter(r.get("expected_stage") for r in rows)))
print()
print(f"{'id':24s} {'class':20s} {'stage':10s} file")
for row in rows:
    path = fixture_file(row)
    print(f"{row['id']:24s} {row['expected_doc_class']:20s} {row.get('expected_stage','?'):10s} {path.name} exists={path.is_file()}")
'''
    ),
    md("## One contract fixture + typed expected fields"),
    code(
        '''
msa = next(r for r in rows if r["id"] == "contract_msa")
text = fixture_file(msa).read_text(encoding="utf-8")
fields = parse_expected_fields(msa)
print("id:", msa["id"])
print("path:", fixture_file(msa))
print("--- first 400 chars ---")
print(text[:400])
print("--- expected_fields (gold for extraction evals) ---")
print(fields)
print()
amb = next(r for r in rows if r["id"] == "ambiguous_01")
print("ambiguous_01 expected class:", amb["expected_doc_class"], "stage:", amb.get("expected_stage"))
print("(the mock LLM assigns confidence 0.40 to this id so routing evals have a REVIEW case)")
'''
    ),
    md("## HF mini-slice, LegalBench Yes/No, per-agent gold"),
    code(
        '''
hf = load_hf_fixtures()
lb = load_legalbench_fixtures()
print("HF mini rows:", len(hf), "keys sample:", sorted(hf[0]) if hf else None)
print("HF classes :", sorted({r.get("expected_hf_class") or r.get("doc_type") for r in hf}))
print("LegalBench n:", len(lb), "task answers:", [r.get("answer") for r in lb])
print()
for agent in ("intake", "pdf_transcriber", "image_extractor", "judge", "arbiter", "boss"):
    gold = load_agent_fixtures(agent)
    print(f"agents/{agent}.jsonl -> {len(gold):2d} rows  ({agent_fixture_path(agent).name})")
'''
    ),
    md("## Provenance and honest gaps"),
    code(
        '''
attr = (fixtures_dir() / "ATTRIBUTION.md").read_text(encoding="utf-8")
print(attr[:900])
print()
png = fixtures_dir() / "intake" / "hello.png"
pdf = fixtures_dir() / "intake" / "hello.pdf"
print("hello.pdf exists:", pdf.is_file(), "size", pdf.stat().st_size if pdf.is_file() else 0)
print("hello.png exists:", png.is_file(), "— image_extractor live path wants a PNG; mock uses agents/image_extractor.jsonl")
print()
print("HONEST GAP: this catalog is synthetic / attributed snippets, not CUAD or")
print("docclass-merged scale. `sandbox datasets pull` is the Hub path (network).")
'''
    ),
)


N3 = notebook(
    md(
        """# 03 — Isolated agent evals (mock)

Every live pipeline agent/node has a sandbox eval task. Isolated runners
open a `document-pipeline` root chain and nest **one** observation so
The-Mailroom can still draw a partial conveyor.

Canonical code:

- [`src/mailroom_sandbox/eval/agents.py`](../src/mailroom_sandbox/eval/agents.py) — `SPECS`
- [`src/mailroom_sandbox/eval/runners.py`](../src/mailroom_sandbox/eval/runners.py) — `run_isolated_eval`
- [`docs/evals.md`](../docs/evals.md)

**Honesty:** mock predictors copy gold labels / fields. `exact_match == 1.0`
proves the harness, scoring sink, and experiment log — **not** model quality.
"""
    ),
    code(BOOT),
    md("## Roster vs retired specialists"),
    code(
        '''
from mailroom_sandbox.eval.agents import SPECS, RETIRED_AGENTS, EVAL_TASKS, spec_for
from mailroom_sandbox.eval import tracing

print("retired (no runners):", RETIRED_AGENTS)
print("composite tasks     :", [t for t in EVAL_TASKS if t not in SPECS])
print()
print(f"{'task':32s} {'observation':24s} type")
for name, spec in SPECS.items():
    print(f"{name:32s} {spec.observation:24s} {tracing.observation_type_for(spec.observation)}")
assert "court_opinions_specialist" not in SPECS
assert "pipeline" in EVAL_TASKS
'''
    ),
    md("## Dry-run then mock `judge` / `sorter` / `intake`"),
    code(
        '''
from mailroom_sandbox.eval.runners import run_isolated_eval

plan = run_isolated_eval("judge", mock=True, dry_run=True)
print("dry-run plan:", plan)

judge = run_isolated_eval("judge", mock=True, sample=2, experiment_name="nb03_judge")
sorter = run_isolated_eval("sorter", mock=True, sample=4, experiment_name="nb03_sorter")
intake = run_isolated_eval("intake", mock=True, experiment_name="nb03_intake")
print("judge  scores:", judge["scores"])
print("sorter scores:", sorter["scores"])
print("intake scores:", intake["scores"])
print("sorter observation:", sorter.get("observation") or spec_for("sorter").observation)
assert judge["scores"]["exact_match"] == 1.0
assert sorter["scores"]["n"] == 4
'''
    ),
    md("## Reviewer, arbiter, and a specialist extract"),
    code(
        '''
reviewer = run_isolated_eval("sorter_reviewer", mock=True, sample=2, experiment_name="nb03_reviewer")
arbiter = run_isolated_eval("arbiter", mock=True, experiment_name="nb03_arbiter")
contracts = run_isolated_eval(
    "contracts_specialist", mock=True, sample=2, experiment_name="nb03_contracts"
)
print("reviewer :", reviewer["scores"])
print("arbiter  :", arbiter["scores"])
print("contracts:", contracts["scores"])
print("contracts per-row ids:", [r["id"] for r in contracts.get("per_row") or []])
print()
print("CLI equivalent:")
print("  sandbox eval judge --mock")
print("  sandbox eval sorter --mock --sample 4")
print("  sandbox eval contracts_specialist --mock")
'''
    ),
    md("## What mock is *not*"),
    code(
        '''
print("HONEST GAP: mock exact_match=1.0 is a harness smoke test.")
print("A local model is `sandbox eval sorter --local` after `sandbox pull-models`.")
print("Vendored mailroom (`sandbox fetch-deps`) is required for live agent classes.")
print("If live_predict raises, runners fall back to mock and set offline_fallback.")
'''
    ),
)


N4 = notebook(
    md(
        """# 04 — Connected pipeline + dojo scoring

`sandbox eval pipeline --mock` scores **class, stage, extraction, and
routing** together. Without vendored mailroom the runner uses an offline
fallback (fake client / gold copy) and still emits the same score keys.

Scoring is [`llm-dojo-scoring` @ v0.11.0](https://github.com/Exios66/llm-dojo-scoring)
via [`eval/scoring.py`](../src/mailroom_sandbox/eval/scoring.py). Extraction
is **typed** (id/date/money/name…) — never exact-match-on-extraction.

v0.11.0 formulas and T0 names match v0.10.0; the release adds scoring docs
and `llm_dojo_scoring.prompts`.
"""
    ),
    code(BOOT),
    md("## Connected pipeline mock"),
    code(
        '''
import llm_dojo_scoring as dojo
from mailroom_sandbox.eval.runners import (
    run_pipeline_eval,
    run_extract_eval,
    run_chained_eval,
    run_legalbench_eval,
)

print("dojo", getattr(dojo, "__version__", "pinned"))
pipe = run_pipeline_eval(mock=True, sample=3, connected=True, experiment_name="nb04_pipeline")
print("connected:", pipe.get("connected"))
print("scores   :", pipe["scores"])
assert pipe["scores"]["class_correct"] == 1.0
assert "stage_correct" in pipe["scores"]
assert "routing_accuracy" in pipe["scores"]
'''
    ),
    md("## Extract, chained sorter→extract, LegalBench Yes/No"),
    code(
        '''
extract = run_extract_eval(mock=True, sample=3, experiment_name="nb04_extract")
chained = run_chained_eval(mock=True, sample=3, experiment_name="nb04_chained")
legal = run_legalbench_eval(mock=True, experiment_name="nb04_legalbench")
print("extract :", extract["scores"])
print("chained :", chained["scores"])
print("legal   :", legal["scores"])
print("chained composite is 0.25*sorter + 0.75*extract (see runners.run_chained_eval)")
'''
    ),
    md("## Direct dojo calls (classification + typed extraction)"),
    code(
        '''
from mailroom_sandbox.datasets import load_manifest, parse_expected_fields
from mailroom_sandbox.eval import scoring

rows = load_manifest()
expected = [r["expected_doc_class"] for r in rows[:6]]
# Mock "model" copies gold — machinery proof.
cls = scoring.score_classification(expected, expected)
print("classification:", {k: cls[k] for k in ("exact_match", "n") if k in cls})
print("task keys     :", sorted((cls.get("task") or {}).keys())[:12])

msa = next(r for r in rows if r["id"] == "contract_msa")
gold = parse_expected_fields(msa) or {}
ext = scoring.score_extraction_row("contract", gold, gold, doc_text=None)
print("extraction overall:", ext.get("overall_extraction_score"), "doc_type=", ext.get("doc_type"))
print("HONEST GAP: scoring gold-against-gold is 1.0 by construction.")
print("Real extraction quality needs --local plus a specialist that can miss fields.")
'''
    ),
    md("## Prompt catalog (v0.11.0 additive surface)"),
    code(
        '''
try:
    from llm_dojo_scoring.prompts import get_prompt, list_prompts
    names = list_prompts()
    print("catalog size:", len(names))
    intake = get_prompt("intake")
    print("intake.kind (must be deterministic, empty text):", intake.kind, repr(intake.text[:20] if intake.text else ""))
    sorter = get_prompt("sorter")
    print("sorter.kind:", sorter.kind, "text chars:", len(sorter.text or ""))
    print("Sandbox overlay templates still live in config/prompts/*_local_v0.txt")
    print("and win for local 7B/8B JSON-strict runs (`--prompt sorter_local_v0`).")
except Exception as exc:
    print("prompts catalog unavailable:", type(exc).__name__, exc)
    print("HONEST GAP: install llm-dojo-scoring @ v0.11.0 to import llm_dojo_scoring.prompts")
'''
    ),
)


N5 = notebook(
    md(
        """# 05 — Langfuse v4 trace contract (offline)

The-Mailroom filters `MAILROOM_TRACE_NAMES=document-pipeline` and
`MAILROOM_TRACE_TAGS=mailroom`. Sandbox evals write that contract even
when Langfuse is down: `OBSERVABILITY_PROVIDER=none` makes the context
managers no-ops, which is what pytest and these notebooks use.

Canonical code: [`src/mailroom_sandbox/eval/tracing.py`](../src/mailroom_sandbox/eval/tracing.py),
[`docs/tracing.md`](../docs/tracing.md).
"""
    ),
    code(BOOT),
    md("## Family constants"),
    code(
        '''
from mailroom_sandbox.eval import tracing

print("root name :", tracing.PIPELINE_TRACE)
print("backend  :", tracing.tracing_backend())
print("env      :", tracing.observability_environment())
print("tags     :", tracing.default_tags("source-fixtures", "agent-sorter"))
print("session  :", tracing.session_id_for("sorter"))
print()
print("NODE_OBSERVATION_TYPES:")
for name, kind in tracing.NODE_OBSERVATION_TYPES.items():
    print(f"  {name:28s} {kind}")
'''
    ),
    md(
        """## Public ground truth (never dump `expected_fields`)

Traces may carry `expected_hf_class`, `expected_doc_class`,
`expected_subclass`, `expected`. Extraction gold stays off the wire.
"""
    ),
    code(
        '''
from mailroom_sandbox.datasets import load_manifest, parse_expected_fields

row = next(r for r in load_manifest() if parse_expected_fields(r))
public = tracing.public_ground_truth(row)
print("row keys   :", sorted(row.keys()))
print("public GT  :", public)
assert "expected_fields" not in public
assert parse_expected_fields(row), "fixture must have extraction gold in the CSV, not on the trace"
print("expected_fields stay in the CSV / experiment log, not on the Langfuse input")
'''
    ),
    md("## No-op root chain + child observation + export bookmark"),
    code(
        '''
with tracing.document_pipeline_trace(
    seed="nb05-demo",
    session_id="sandbox-notebook-demo",
    input={"filename": "sample_msa.txt", "matter_id": "SANDBOX-nb05"},
    metadata={"pipeline": "mailroom", "source": "sandbox-notebook", "attempt": 1},
    tags=tracing.default_tags("source-notebook"),
):
    with tracing.child_observation(
        "classify-document",
        as_type=tracing.observation_type_for("classify-document"),
        input=public,
    ) as span:
        span.update(output={"doc_type": "contract", "confidence": 0.97})
    with tracing.child_observation(
        "extract-fields",
        as_type="agent",
        input={"doc_type": "contract"},
    ):
        pass

tracing.emit_langfuse_score("class_correct", 1.0)
tracing.flush_traces()
exported = tracing.export_traces()
print("export path:", exported)
print("last ids   :", tracing.last_trace_ids())
print()
print("The-Mailroom needs Langfuse up (`sandbox up`) plus:")
print("  MAILROOM_TRACE_NAMES=document-pipeline")
print("  MAILROOM_TRACE_TAGS=mailroom")
print("  MAILROOM_TRACE_ENVIRONMENTS=mock,pilot")
print("Phoenix is an optional sidecar; The-Mailroom cannot plot Phoenix spans.")
'''
    ),
)


N6 = notebook(
    md(
        """# 06 — Prompts, fake client, matrix, experiment log

The last offline slice: local JSON-strict prompt variants, the
deterministic fake OpenAI client used by `--mock` pipeline runs, a
provider×model×prompt matrix **dry-run**, and the sandbox-local
experiment log (not a mirror of llm-entity-extraction).

Canonical code:

- [`src/mailroom_sandbox/prompts.py`](../src/mailroom_sandbox/prompts.py)
- [`config/prompts/`](../config/prompts)
- [`src/mailroom_sandbox/mock_llm.py`](../src/mailroom_sandbox/mock_llm.py)
- [`src/mailroom_sandbox/eval/matrix.py`](../src/mailroom_sandbox/eval/matrix.py)
- [`src/mailroom_sandbox/eval/experiment_log.py`](../src/mailroom_sandbox/eval/experiment_log.py)
"""
    ),
    code(BOOT),
    md("## Local prompt variants (7B/8B JSON-strict)"),
    code(
        '''
from mailroom_sandbox.prompts import list_variants, load_variant, variant_path

print("variants:", list_variants())
text = load_variant("sorter_local_v0")
print("path:", variant_path("sorter_local_v0"))
print("--- sorter_local_v0 (head) ---")
print(text[:500])
assert "json" in text.lower()
print()
print("CLI: sandbox eval sorter --mock --prompt sorter_local_v0")
'''
    ),
    md("## Fake client: classify vs extract vs ambiguous confidence"),
    code(
        '''
from mailroom_sandbox.mock_llm import fake_structured_payload

classify = fake_structured_payload(
    "Classify this legal document into one of the mailroom classes.",
    {"doc_type": "contract", "id": "contract_msa"},
)
amb = fake_structured_payload(
    "Classify this legal document into one of the mailroom classes.",
    {"doc_type": "correspondence", "id": "ambiguous_01"},
)
extract = fake_structured_payload(
    "Extract the parties and dates from this MSA.",
    {"doc_type": "contract", "expected_fields": {"parties": ["Acme"], "effective_date": "2024-01-01"}},
)
print("classify :", classify)
print("ambiguous confidence (routing REVIEW case):", amb["confidence"])
print("extract  :", extract)
assert amb["confidence"] == 0.40
assert classify["confidence"] == 0.97
'''
    ),
    md("## Matrix dry-run (no LLM, no writes except this notebook's log later)"),
    code(
        '''
from mailroom_sandbox.eval.matrix import plan_matrix, run_matrix

plan = run_matrix(
    task="sorter",
    providers=["ollama"],
    models=["qwen3:8b", "llama3.2:3b"],
    prompts=["mailroom-default", "sorter_local_v0"],
    sample=2,
    mock=True,
    dry_run=True,
)
print("n cells:", plan["n"])
for cell in plan["cells"]:
    print(" ", cell["experiment_name"], "model=", cell["model"], "prompt=", cell["prompt"])
assert plan["n"] == 4
print()
print("CLI: sandbox matrix --providers ollama --models qwen3:8b --prompts sorter_local_v0 --mock --dry-run")
'''
    ),
    md("## Experiment log (sandbox-local JSONL)"),
    code(
        '''
from mailroom_sandbox.eval.runners import run_isolated_eval
from mailroom_sandbox.eval import experiment_log

run_isolated_eval("sorter", mock=True, sample=2, experiment_name="nb06_log_probe")
records = experiment_log.load()
mine = [r for r in records if str(r.get("experiment_name", "")).startswith("nb06_")]
print("notebook log path:", experiment_log.jsonl_path())
print("nb06 records:", len(mine))
if mine:
    rec = mine[-1]
    print("keys:", sorted(rec.keys()))
    print("task/profile/mock:", rec.get("task"), rec.get("profile"), rec.get("mock"))
    print("scores:", rec.get("scores"))
    print("sandbox flag:", rec.get("sandbox"), "(this is NOT llm-entity-extraction's log)")
print()
print("Markdown sibling is regenerated on every append:", experiment_log.md_path())
'''
    ),
)


def write(name: str, nb: dict) -> None:
    path = HERE / name
    path.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    n_code = sum(1 for c in nb["cells"] if c["cell_type"] == "code")
    n_md = sum(1 for c in nb["cells"] if c["cell_type"] == "markdown")
    print(f"wrote {path.name:40s}  md={n_md} code={n_code}")


def main() -> None:
    write("01_activate_overlay.ipynb", N1)
    write("02_fixtures_catalog.ipynb", N2)
    write("03_isolated_agent_evals.ipynb", N3)
    write("04_pipeline_and_scoring.ipynb", N4)
    write("05_tracing_contract.ipynb", N5)
    write("06_prompts_matrix_log.ipynb", N6)


if __name__ == "__main__":
    main()
