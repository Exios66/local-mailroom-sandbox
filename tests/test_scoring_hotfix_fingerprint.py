"""SHF-015's fingerprint covers what decides which Hub labels are stale, not only the wrappers.

The verdicts come from ``label_policy.stale_hub_labels`` and every helper and module constant it
reaches (the correspondence topic keys and folder names, the corporate template mark and id
patterns, the empty-value tokens). A vendor refresh or a ``SANDBOX_DOJO_SNAPSHOT`` that changes
only one of those must make SHF-015 ``stale``, so the headline never moves with the flag still
``current``. Network-free; no LLM calls.
"""
from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from mailroom_sandbox import scoring_hotfixes as sh

POLICY = ("llm_dojo_scoring.schemas.label_policy", "stale_hub_labels")
_PACKAGE = "llm_dojo_scoring"
VALUE = "value:"  # the target kind that fingerprints a module constant by its value
#: Names the walk reaches that are type annotations, not behaviour.
_ANNOTATION_ONLY = {"KeywordKind"}


def _module_tree(modname: str) -> tuple[ast.Module, dict, dict, dict]:
    module = importlib.import_module(modname)
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    consts: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            consts.update({t.id: node for t in node.targets if isinstance(t, ast.Name)})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consts[node.target.id] = node
    return tree, funcs, consts, _imports(modname, tree)


def _imports(modname: str, scope: ast.AST) -> dict[str, tuple[str, str]]:
    """``{local name: (module, name)}`` for every ``from x import y`` under ``scope``."""
    module = importlib.import_module(modname)
    package = modname if hasattr(module, "__path__") else modname.rpartition(".")[0]
    out: dict[str, tuple[str, str]] = {}
    for node in ast.walk(scope):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = node.module or ""
        if node.level:
            parts = package.split(".")
            base = ".".join([*parts[:len(parts) - (node.level - 1)], *([node.module] if node.module else [])])
        out.update({(a.asname or a.name): (base, a.name) for a in node.names})
    return out


def _behaviour_names(node: ast.AST) -> set[str]:
    """Names loaded in a function body or default, leaving out annotations."""
    skip: set[int] = set()
    for sub in ast.walk(node):
        for ann in (getattr(sub, "returns", None), getattr(sub, "annotation", None)):
            if ann is not None:
                skip.update(id(n) for n in ast.walk(ann))
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in skip}


def dependency_closure(modname: str, name: str) -> dict[tuple[str, str], str]:
    """Every Dojo function (source) and constant (value) the verdict of ``modname:name`` depends on.

    Follows names a function body loads: module functions, imports from the Dojo package (also
    function-local ones) and, for a constant such as a dispatch table, the functions it lists. A
    constant is a leaf: it is pinned by its value, whatever it was derived from.
    """
    seen: dict[tuple[str, str], str] = {}
    stack = [(modname, name)]
    while stack:
        mod, nm = stack.pop()
        if (mod, nm) in seen or nm in _ANNOTATION_ONLY:
            continue
        _, funcs, consts, imports = _module_tree(mod)
        if nm in funcs:
            seen[(mod, nm)] = "function"
            local = {**imports, **_imports(mod, funcs[nm])}
            for ref in _behaviour_names(funcs[nm]):
                if ref in local and local[ref][0].startswith(_PACKAGE):
                    stack.append(local[ref])
                elif ref in funcs or ref in consts:
                    stack.append((mod, ref))
        elif nm in consts:
            seen[(mod, nm)] = "constant"
            stack.extend((mod, ref) for ref in _behaviour_names(consts[nm]) if ref in funcs)
        elif nm in imports:
            stack.append(imports[nm])
        else:
            raise AssertionError(f"{mod}:{nm} is neither a function nor a constant")
    return seen


CLOSURE = dependency_closure(*POLICY)
FUNCTIONS = sorted(k for k, v in CLOSURE.items() if v == "function")
CONSTANTS = sorted(k for k, v in CLOSURE.items() if v == "constant")


def _shf015() -> sh.ScoringHotfix:
    return next(f for f in sh.HOTFIXES if f.id == "SHF-015")


def _fresh_status(monkeypatch) -> str:
    monkeypatch.setattr(sh, "_STATUS", {})
    return sh.status(refresh=True)["SHF-015"]


def test_the_closure_walk_finds_the_helpers_and_constants_the_verdicts_use():
    """Guards the walk itself: a loose walk would make the coverage test below vacuous."""
    names = {n for _, n in CLOSURE}
    assert {"is_templated_subject_matter", "metadata_keyword_kind", "_keyword_list", "_keywords",
            "is_empty_value", "_corporate_stale", "_correspondence_stale"} <= names
    assert {"_TEMPLATE_MARK", "_ID_KEYWORD", "_CIK_KEYWORD", "_TOPIC_KEYS", "_NULL_TOKENS"} <= names


def test_shf015_pins_every_function_and_constant_the_stale_verdicts_depend_on():
    pinned = {t for t, _ in _shf015().targets}
    missing = [f"{m}:{n}" for m, n in FUNCTIONS if f"{m}:{n}" not in pinned]
    missing += [f"{VALUE}{m}:{n}" for m, n in CONSTANTS if f"{VALUE}{m}:{n}" not in pinned]
    assert not missing, f"SHF-015 does not fingerprint: {missing}"


@pytest.mark.parametrize("module,name", FUNCTIONS, ids=[f"{n}" for _, n in FUNCTIONS])
def test_a_changed_policy_function_makes_shf015_stale(monkeypatch, module, name):
    assert _fresh_status(monkeypatch) == "current"
    real = sh._file_source
    target = f"{module}:{name}"
    monkeypatch.setattr(sh, "_file_source", lambda t: (real(t) or "") + "\n# drift" if t == target else real(t))
    assert _fresh_status(monkeypatch) == "stale", f"a change to {target} left SHF-015 current"


def _drifted(value):
    if isinstance(value, re.Pattern):
        return re.compile(value.pattern + "|zzz", value.flags)
    if isinstance(value, (set, frozenset)):
        return type(value)([*value, "zzz-drift"])
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, dict):
        return {**value, "zzz-drift": next(iter(value.values()))}
    raise AssertionError(f"no drift rule for {type(value).__name__}")


@pytest.mark.parametrize("module,name", CONSTANTS, ids=[f"{n}" for _, n in CONSTANTS])
def test_a_changed_policy_constant_makes_shf015_stale(monkeypatch, module, name):
    assert _fresh_status(monkeypatch) == "current"
    owner = importlib.import_module(module)
    monkeypatch.setattr(owner, name, _drifted(getattr(owner, name)))
    assert _fresh_status(monkeypatch) == "stale", f"a change to {module}:{name} left SHF-015 current"


def test_a_value_target_that_cannot_be_read_is_unavailable_not_current(monkeypatch):
    fix = _shf015()
    missing = sh.ScoringHotfix(fix.id, fix.layer, (*fix.targets, (f"{VALUE}{POLICY[0]}:_NO_SUCH", "0" * 64)),
                               fix.upstream, fix.summary)
    assert sh.status([missing])["SHF-015"] == "unavailable"


def test_a_value_fingerprint_ignores_set_order_and_distinguishes_patterns_and_flags():
    assert sh.VALUE_TARGET == VALUE
    assert sh.value_sha(frozenset({"b", "a"})) == sh.value_sha(frozenset({"a", "b"}))
    assert sh.value_sha(re.compile("a", re.I)) != sh.value_sha(re.compile("a"))
    assert sh.value_sha(re.compile("a")) != sh.value_sha(re.compile("b"))
    assert sh.value_sha({"x": 1, "y": 2}) == sh.value_sha({"y": 2, "x": 1})
    assert sh.value_sha(("a", "b")) != sh.value_sha(("b", "a"))


def test_a_vendor_copy_with_one_changed_helper_turns_shf015_stale(tmp_path):
    """The real mechanism: a Dojo snapshot whose only change is a helper the wrappers call."""
    import llm_dojo_scoring

    snapshot = tmp_path / "snap"
    source = Path(llm_dojo_scoring.__file__).parent
    snapshot.mkdir()
    subprocess.run(["cp", "-r", str(source), str(snapshot)], check=True)
    helper = snapshot / "llm_dojo_scoring" / "schemas" / "correspondence_gt_audit.py"
    text = helper.read_text(encoding="utf-8")
    marker = '    """True when ``subject_matter`` is a topic-key template, not a summary."""\n'
    assert marker in text
    helper.write_text(text.replace(marker, marker + "    return True\n", 1), encoding="utf-8")
    probe = (
        "import mailroom_sandbox, llm_dojo_scoring as d; from mailroom_sandbox import scoring_hotfixes as sh;"
        "print(d.__file__); print(sh.status(refresh=True)['SHF-015'])"
    )
    root = Path(sh.__file__).resolve().parents[1]
    env = {**os.environ, "DOJO_SRC": str(snapshot), "PYTHONPATH": str(root)}
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True, env=env)
    where, verdict = run.stdout.split()[-2:]
    assert str(snapshot) in where, "the probe did not import the edited snapshot"
    assert verdict == "stale"
