---
name: sand-board-hygiene
description: >-
  Triage and hygiene for the SAND board in local-mailroom-sandbox: find stale
  open cards, lane drift vs GitHub PRs/issues, Next ID gaps, and cancelled or
  done rows that still look active. Use when auditing governance/TASKS.md,
  sweeping stale SAND cards, reconciling the board with issues/PRs, or when the
  user asks for board hygiene, triage, stale cards, or open-card cleanup.
---

# SAND board hygiene

Use this for **board-wide** triage. For moving one card through
allocate → progress → review → done, use
[sand-board-lifecycle](../sand-board-lifecycle/SKILL.md).

Authority: [`governance/TASKS.md`](../../../governance/TASKS.md) ·
[`governance/README.md`](../../../governance/README.md) ·
[`governance/PREFIX.md`](../../../governance/PREFIX.md).

## When to run

- User asks to triage, sweep, or clean the board.
- Before a long campaign or multi-PR stack, so active work is visible.
- After several merges landed without governance follow-ups.
- When **Next ID**, issue titles, and board rows disagree.

## Procedure

### 1. Digest the open surface

Prefer one script over many tool calls ([code-mode](../../../.claude/rules/code-mode.md)):

```bash
python .cursor/skills/sand-board-hygiene/scripts/board_digest.py
python .cursor/skills/sand-board-hygiene/scripts/board_digest.py --json
```

The digest groups non-`done` / non-`cancelled` rows by status and prints
**Next ID**, max primary id, and crude stale hints (empty notes, missing PR/issue
tokens, `in_progress`/`review` without a `#NNN` reference).

### 2. Reconcile with GitHub (read-only first)

```bash
gh issue list --state all --limit 100 --json number,title,updatedAt,labels,state
gh pr list --state all --limit 100 --json number,title,updatedAt,headRefName,state
```

An open-only list hides the merged PRs and closed issues the table below
uses. If a board row's `#NNN` is not in the first page, look that number up
directly.

Match `SAND-NNN` in issue/PR titles to board rows. Record:

| Signal | Likely action |
| --- | --- |
| Board **review**, PR merged, gates green, issue closed | Move to **done** (lifecycle skill); note squash SHAs |
| Board **review**, PR merged, issue still open | Close issue with evidence or split a follow-up SAND card |
| Board **in_progress**, no open PR and no recent notes | Ask owner or move to **needs_attention** with blocker |
| Board **todo**, tracking issue already closed as done | Confirm landing; move to **done** or **cancelled** |
| Open issue with `SAND-NNN` in title, no board row | Add the row (allocate if the id was never boarded) |
| Board row with no issue and no PR for months | Flag for human keep/cancel; do not delete history |
| **Next ID** ≤ max listed primary | Bump **Next ID** (test fails otherwise) |
| `DMR-*` or `SANDBOX-*` in the active table | Remove/migrate per PREFIX.md (legacy → `archive/`) |

### 3. Propose edits, then apply with evidence

1. List proposed lane moves as a short table: ID · current · proposed · evidence.
2. Apply only rows you verified. Paraphrase; no requester quotes in Notes.
3. Do not rewrite historical Notes to erase mistakes — append a dated correction.
4. Large sweeps get their own SAND card (lifecycle skill) so the hygiene work
   itself completes the cycle.

### 4. Verify

```bash
pytest -q -n 0 --no-cov tests/test_governance_sand.py tests/test_skills.py
npx --yes markdownlint-cli2@0.18.1 governance/TASKS.md
```

## Stale heuristics (not automatic closes)

These are **prompts for review**, not license to mass-close:

- **review** + merged PR + green required hosted gates + closed issue → overdue **done** move (highest priority).
- **in_progress** / **needs_attention** with no `#` PR/issue and owner inactive →
  confirm abandon vs. still blocked.
- **todo** marked "mission critical" with a closed upstream issue → re-read scope
  before cancelling.
- Cards whose only evidence is a floor replay or mock run → do not treat as
  measured closeout ([critical regressions](../../../docs/critical-regressions.md)).

Never launch paid runs, Modal deploys, or live LLM work as part of hygiene.
Never cite simulated/replay scores as completion evidence.

## Report shape

When reporting triage results, use:

```text
Board hygiene — <UTC date>
Next ID: SAND-NNN (max primary on board: SAND-MMM)
Open by lane: todo=… in_progress=… needs_attention=… review=…
Moves proposed:
- SAND-…: review → done (PR #… squash …; issue #… closed)
Left open (needs human):
- SAND-…: …
Checks: test_governance_sand …
```
