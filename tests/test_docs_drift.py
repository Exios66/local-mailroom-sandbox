"""The docs keep up with the tree: every page is indexed, every hotfix and command is documented.

Network-free. Each check names the file to update when it fails.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import pytest

from mailroom_sandbox.paths import repo_root

ROOT = repo_root()
_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE = re.compile(r"```.*?```", re.DOTALL)

# Generated or self-indexed trees: reaching their index page is enough.
_INDEX_EXEMPT = ("docs/runbooks/", "docs/prompts/", "docs/releases/", "docs/assets/")


def _tracked(*patterns: str) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", *patterns], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout")
    return [line for line in out.stdout.splitlines() if line]


def _links(path: Path) -> list[Path]:
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    found = []
    for target in _LINK.findall(text):
        target = target.strip("<>").split("#", 1)[0]
        if not target or re.match(r"^[a-z]+:", target):
            continue
        found.append((path.parent / target).resolve())
    return found


def test_every_doc_is_reachable_from_the_docs_index():
    """docs/README.md links every page, directly or through pages it links. Add new pages there."""
    docs = (ROOT / "docs").resolve()
    start = docs / "README.md"
    seen, queue = {start}, [start]
    while queue:
        page = queue.pop()
        for target in _links(page):
            # Crawl only inside docs/: a page linked from the root README or AGENTS.md is not indexed.
            if target.suffix == ".md" and target.is_file() and target not in seen and docs in target.parents:
                seen.add(target)
                queue.append(target)
    missing = [
        rel for rel in _tracked("docs/*.md", "docs/**/*.md")
        if not rel.startswith(_INDEX_EXEMPT) and (ROOT / rel).resolve() not in seen
    ]
    assert missing == [], "docs pages not reachable from docs/README.md:\n" + "\n".join(missing)


def _doc_rows(doc: str, prefix: str) -> dict[str, str]:
    """Hotfix id → the rest of its table row."""
    rows = {}
    for line in (ROOT / "docs" / doc).read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^\|\s*({prefix}-\d{{3}})\s*\|(.*)$", line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


@pytest.mark.parametrize(("module", "doc", "prefix"), [
    ("mailroom_sandbox.vendor_hotfixes", "vendor-hotfixes.md", "HF"),
    ("mailroom_sandbox.scoring_hotfixes", "scoring-hotfixes.md", "SHF"),
])
def test_every_hotfix_has_a_doc_row_with_its_status(module, doc, prefix):
    """A registered hotfix has a row in its doc; a row marked retired is no longer registered."""
    import importlib

    registered = {fix.id for fix in importlib.import_module(module).HOTFIXES}
    rows = _doc_rows(doc, prefix)
    retired = {fid for fid, rest in rows.items() if re.search(r"\|\s*retired\s*\|", f"|{rest}", re.I)}
    assert registered - set(rows) == set(), f"hotfixes without a row in docs/{doc}"
    assert registered & retired == set(), f"docs/{doc} marks registered hotfixes retired"
    assert set(rows) - registered - retired == set(), f"docs/{doc} lists hotfixes the registry no longer has; mark them retired"


@pytest.mark.parametrize("module", ["mailroom_sandbox.vendor_hotfixes", "mailroom_sandbox.scoring_hotfixes"])
def test_every_hotfix_id_is_registered_once(module):
    """Two open PRs once used HF-021 for different fixes; a merged head must never carry both."""
    import collections
    import importlib

    ids = collections.Counter(fix.id for fix in importlib.import_module(module).HOTFIXES)
    assert [fid for fid, n in ids.items() if n > 1] == [], "renumber per docs/numbering-reservations.md"


def test_critical_regression_rows_are_numbered_once_in_order():
    """Each row number is used once, 1..N with no gap (open PRs take numbers from the reservations page)."""
    numbers = [int(m.group(1)) for line in (ROOT / "docs" / "critical-regressions.md").read_text(encoding="utf-8")
               .splitlines() if (m := re.match(r"^\|\s*(\d+)\s*\|", line))]
    assert numbers == list(range(1, len(numbers) + 1)), "renumber per docs/numbering-reservations.md"


def test_the_reservations_page_lists_every_registered_hotfix_range_it_reserves():
    """A reserved id that is registered on this head is marked landed, so the page cannot go stale silently."""
    import importlib

    page = (ROOT / "docs" / "numbering-reservations.md").read_text(encoding="utf-8")
    registered = {fix.id for fix in importlib.import_module("mailroom_sandbox.vendor_hotfixes").HOTFIXES}
    for line in page.splitlines():
        if not line.startswith("| `HF-"):
            continue
        ids = re.findall(r"HF-(\d{3})", line.split("|")[1])
        span = range(int(ids[0]), int(ids[-1]) + 1)
        landed = any(f"HF-{n:03d}" in registered for n in span)
        assert landed == ("landed" in line.split("|")[3].lower()), line



def test_the_next_free_hotfix_ids_follow_every_registered_and_reserved_id():
    """The page's next free HF/SHF ids sit above every id registered here or reserved for open work,
    so a PR that lands a range cannot leave its own id listed as free."""
    import importlib

    page = (ROOT / "docs" / "numbering-reservations.md").read_text(encoding="utf-8")
    for prefix, module in (("HF", "mailroom_sandbox.vendor_hotfixes"), ("SHF", "mailroom_sandbox.scoring_hotfixes")):
        [free] = re.findall(rf"next free\s+(?:vendor\s+hotfix\s+)?ID\s+is\s+`{prefix}-(\d{{3}})`", page)
        used = {int(fix.id.split("-")[1]) for fix in importlib.import_module(module).HOTFIXES
                if fix.id.startswith(f"{prefix}-")}
        used |= {int(n) for line in page.splitlines() if line.startswith(f"| `{prefix}-")
                 for n in re.findall(rf"{prefix}-(\d{{3}})", line.split("|")[1])}
        assert int(free) == max(used) + 1, f"{prefix}: next free is {prefix}-{max(used) + 1:03d}, page says {free}"

def test_readme_names_every_top_level_command():
    """The README CLI block names each `sandbox` command; flags live in docs/cli-reference.md."""
    from mailroom_sandbox.cli import build_parser

    commands = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)).choices
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [name for name in sorted(commands) if not re.search(rf"\bsandbox(?: [a-z-]+\|?)* {re.escape(name)}\b|\| {re.escape(name)}\b|\b{re.escape(name)} \|", readme)]
    assert missing == [], "README CLI block is missing: " + ", ".join(missing)


def test_layout_contract_lists_every_top_level_directory():
    """docs/setting-up/LAYOUT.md's top-level table names every tracked top-level directory."""
    layout = (ROOT / "docs" / "setting-up" / "LAYOUT.md").read_text(encoding="utf-8")
    table = layout.split("## Top level", 1)[1].split("\n## ", 1)[0]
    listed = set()
    for row in table.splitlines():
        if row.startswith("| `"):
            first_cell = row.split("|")[1]
            listed |= {path.split("/", 1)[0] for path in re.findall(r"`([^`]+)`", first_cell)}
    tops = sorted({rel.split("/", 1)[0] for rel in _tracked() if "/" in rel})
    missing = [top for top in tops if top not in listed]
    assert missing == [], "LAYOUT.md top-level table is missing: " + ", ".join(missing)


_DOC_CITE = re.compile(r"(?<![\w/.-])docs/[\w./-]+\.md")
# Paths that live in another repository, named in text written for that repository.
_OTHER_REPO_CITES = {
    ("reports/dashboard/export_hub_reports.py", "docs/PROMPTS.md"),  # mailroom-issues README
    ("src/mailroom_sandbox/eval/pain_points.py", "docs/contracts/PAIN_POINT_SCORING.md"),  # the Dojo's contract
}


def test_docs_paths_cited_in_code_and_config_resolve():
    """A `docs/....md` path named in a .py or .yaml file exists (upstream-repo citations excepted)."""
    broken = []
    for rel in _tracked("*.py", "*.yaml", "*.yml"):
        if rel.startswith(("vendor/", "tests/")):  # tests name retired paths on purpose
            continue
        for i, line in enumerate((ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "llm-mailroom" in line or "github.com/" in line or "{" in line:
                continue
            for cited in _DOC_CITE.findall(line):
                if (rel, cited) not in _OTHER_REPO_CITES and not (ROOT / cited.rstrip(".")).is_file():
                    broken.append(f"{rel}:{i}: {cited}")
    assert broken == [], "cited docs paths that do not exist:\n" + "\n".join(broken)


def test_claude_agent_wrappers_load_an_existing_canonical_prompt():
    """Each .claude/agents wrapper points at a prompt that exists under .opencode/agents/."""
    wrappers = sorted((ROOT / ".claude" / "agents").glob("*.md"))
    assert wrappers, "no .claude/agents wrappers found"
    for wrapper in wrappers:
        cited = set(re.findall(r"\.opencode/agents/[\w-]+\.md", wrapper.read_text(encoding="utf-8")))
        assert cited, f"{wrapper.name} names no .opencode/agents prompt"
        for path in cited:
            assert (ROOT / path).is_file(), f"{wrapper.name} -> {path} does not exist"
