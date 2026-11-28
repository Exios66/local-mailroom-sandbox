---
name: sand-board-lifecycle
description: >-
  Complete the SAND board card cycle (allocate → todo → in_progress →
  needs_attention → review → done/cancelled) for sandbox-isolated work in
  local-mailroom-sandbox. Use
  whenever starting, taking, reviewing, merging, closing, or handing off a
  SAND-* card, PR, or issue; when the user mentions the board, governance,
  TASKS.md, Next ID, or card status; and before claiming work is finished so
  the card does not stay stale in review or in_progress.
---

# SAND board card lifecycle

The local board is [`governance/TASKS.md`](../../../governance/TASKS.md). Rules:
[`governance/README.md`](../../../governance/README.md),
[`governance/PREFIX.md`](../../../governance/PREFIX.md). Guards:
`tests/test_governance_sand.py`.

Read this skill whenever sandbox work needs a card, or a card's lane must move.
For open-card triage and stale hygiene (no specific card in hand), use
[sand-board-hygiene](../sand-board-hygiene/SKILL.md) instead.

## Binding rules

- **Prefix:** only `SAND-NNN` / `SAND-NNN-k` on this board. Never open `DMR-*`
  here. Cross-family work belongs on the Digital-Mailroom hub; cite
  `Related: DMR-NNN` in notes when a SAND card tracks family-driven work.
- **Numbering authority:** allocate the next ID in `TASKS.md` **first** and
  push that row before opening a tracking issue. Two branches can take the
  same Next ID; if the id is already on main or another open card, take the
  new Next ID and do not open a second issue for the old one. The **Next ID**
  line must stay strictly greater than every listed primary `SAND-NNN`
  (`tests/test_governance_sand.py`).
- **Lanes:** `todo` → `in_progress` → `needs_attention` → `review` → `done`
  (or `cancelled` with a one-line reason). Bold the Status cell (`**done**`).
- **Evidence over vibes:** Notes carry PR numbers, squash SHAs, issue links,
  and what remains open. Do not invent initials, spend, or CI results.
- **PR / issue text:** executive summary only — no requester quotes, names,
  handles, credentials, or a `User description` section (AGENTS.md).

## Cycle checklist

### 1. Start (allocate or claim)

1. Open `governance/TASKS.md`. If no card exists, take **Next ID**, bump it
   (e.g. `SAND-112` → next `SAND-113`), and add a row under **Open / in progress**.
2. Set Status to **`todo`** (queued) or **`in_progress`** (work begins now).
3. Set Owner (agent or human handle) and a UTC date when useful.
4. Notes: one-line scope, linked issue if any, related SAND/DMR ids.
5. Open the tracking issue only after the board row exists; put `SAND-NNN` in
   the issue title.

### 2. In progress

1. Move Status to **`in_progress`** when implementation starts (branch cut,
   first substantive commit, or live investigation).
2. Keep Notes current: branch name, blocked-on items, spend gates still needed.
3. If blocked on a human/spend/upstream decision, move to **`needs_attention`**
   and name the blocker — do not leave a silent `in_progress` card.

### 3. Review

1. When a PR is opened for the card's scope, move Status to **`review`**.
2. Notes must name every PR (`#NNN`), branch, and what hosted gates or human
   acceptance still remain. "Local tests passed" alone is not closeout.
3. Stacked PRs: list each; the card stays in **review** until the accepted
   stack has merged (or the remaining stack is explicitly out of scope).

### 4. Done (or cancelled)

Move to **`done`** only when **all** of these hold:

1. The shipping PR(s) are merged (record squash commit SHAs).
2. Required hosted gates on the merge head are green (or the card explicitly
   scopes out a named gate as follow-up work / a new card).
3. The tracking issue is closed with the same evidence trail, or the Notes say
   why the issue stays open (and ideally spawn a follow-up SAND id).

Then:

- Status → **`done`**; Notes summarize final scope + SHAs + issue disposition.
- Prefer a small governance-only follow-up commit/PR when the shipping PRs
  already merged without the board row update (keeps product diffs clean).
- **`cancelled`:** only with a factual reason (superseded, not needed, duplicate).
  Point at the replacement card or issue when there is one.

### 5. Handoff / merge gate for agents

Before saying the work is finished, verify:

| Check | Passes when |
| --- | --- |
| Card row exists | `SAND-NNN` appears in `TASKS.md` |
| Lane matches reality | open PR ⇒ **review**; merged, required hosted gates green, and issue closed ⇒ **done** |
| Next ID | greater than max listed primary |
| Prefix | no `DMR-*` / `SANDBOX-*` in the active table |
| Evidence | Notes name PR/SHA/issue; no secrets or requester quotes |
| Tests | `pytest -q -n 0 --no-cov tests/test_governance_sand.py` |

## Anti-patterns

- Shipping a PR with no board row, or leaving a card in **review** after merge.
- Marking **done** while the tracking issue is open with no follow-up card.
- Reusing a DMR number as a SAND id, or filing family work only on this board.
- Editing `vendor/` or lowering coverage to "finish" a card.
- Closing cards from memory — re-read `gh pr view` / `gh issue view` evidence.

## Minimal verification

```bash
pytest -q -n 0 --no-cov tests/test_governance_sand.py
npx --yes markdownlint-cli2@0.18.1 governance/TASKS.md
```
