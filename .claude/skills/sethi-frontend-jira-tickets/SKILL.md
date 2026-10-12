---
name: sethi-frontend-jira-tickets
description: >-
  Turn a pasted user story (text or a text file) into one or more STH Story tickets for
  sethi_enterprise_frontend work, grounded in that repo's actual code rather than invented file
  paths. Reads ~/Documents/work/sethi/sethi_enterprise_frontend to source the Scope and Technical
  Context sections, drafts the team's standard STORY-ID format, then creates the ticket(s) by
  calling the shared /jira-scripts skill (jira_api.py create-stories --project STH) — the direct
  Jira REST API, not the Atlassian MCP tools. Every
  ticket is always assigned to rhidzkhan ahmad and always lands in the Backlog (no Sprint field
  set). Like the sibling sethi-backend-jira-tickets skill, the Epic has NO default — STH's
  frontend epics are themselves ambiguous (FRONTEND at STH-419, plus two separately-cased
  "frontend" epics at STH-418 and STH-417), so a fuzzy match would risk filing under the wrong
  one; the epic name must always be given and is resolved by searching the board rather than
  guessed. Use when the operator says "create sethi frontend tickets", "create sethi fe
  tickets", or "create sethi frontend tickets epic '<name>'", followed by a pasted user story — or
  by a bug report (screenshot, console error, error text) already known to be frontend, which is
  read via /sethi-jira-tickets' Input handling section and then drafted with this skill's
  bug-source requirements.
---

# Sethi frontend Jira tickets — code-grounded STORY tickets via the Jira API

Creates STH Story tickets for `sethi_enterprise_frontend` work. A direct port of the sibling
`/sethi-backend-jira-tickets` skill (itself ported from `/nexus-frontend-jira-tickets`) — same
STORY-ID format, same code-grounding discipline, same direct-API write path. The distinguishing
choices, all fixed by the operator rather than inferred per run:

| | Always |
|---|---|
| Project | `STH` |
| Repo the ticket is grounded in | `~/Documents/work/sethi/sethi_enterprise_frontend` |
| Issue type | `Story` |
| Assignee | rhidzkhan ahmad (`712020:525b78f1-26da-462d-b8cd-91b3598ad495`) |
| Placement | Backlog — created with **no Sprint field**, so it never lands on the active board |
| Epic | **always named in the trigger — no default.** STH's frontend epics are ambiguous — `FRONTEND` (STH-419) and two separately-cased `frontend` epics (STH-418, STH-417) all coexist — so a fuzzy default would risk the wrong one; resolved by searching the board, never guessed |
| Write path | **`/jira-scripts`** → `jira_api.py create-stories --project STH`, **not** `mcp__claude_ai_Atlassian_*` |

## Trigger

`create sethi frontend tickets epic "<name>"` / `create sethi fe tickets epic "<name>"`, followed
by one or more pasted user stories (inline text or a text file). Extract `<name>` from the quoted
string after `epic`. **There is no fallback epic** — if the trigger has no `epic "..."` clause,
stop and ask which epic to file under rather than guessing. This matters more here than on the
backend sibling: STH has three separate, similarly-named frontend epics (`FRONTEND`, and two
distinct `frontend`), so even a "closest match" heuristic could silently pick the wrong one.

A single paste may contain **one story** (freeform prose — draft the full ticket from it) or
**several stories already delimited by `### `** headings (the team's STORY-ID format) — split on
those headings and produce one ticket per block.

## Procedure

### 1. Read the pasted input
Identify one or more stories per the splitting rule above. For each: extract the role,
capability, and outcome (or, if already in STORY-ID format, take its fields as given — never
overwrite content the operator already wrote).

**A bug report is a valid input here too** — a screenshot, console error, or error text plus the
operator's explanation, when the work is already known to be frontend. Reading it is owned by
**`/sethi-jira-tickets` → "Input handling"**: read the image with the Read tool, pull the four facts
(symptom, error, location, repro), and normalize them into the STORY-ID shape below. That section is
the single source for those rules — follow it rather than improvising an extraction here. Carry the
four facts forward into step 3, which draft sections depend on them.

**A screenshot landing here does not confirm the side.** The browser is the only surface a user can
photograph, so a UI symptom whose cause is a bad or absent API response belongs to
`/sethi-jira-tickets`, which splits it into a backend ticket and this one. Check the four facts for
a 4xx/5xx, a stack trace, or wrong data in the payload before drafting a frontend-only ticket.

**Exception: the `**Epic:**` line, if the pasted text has one, is never taken as given.**
A pasted draft's `**Epic:**` line is often just descriptive context the drafter wrote — not an
instruction for which epic to file under. The epic comes **only** from the trigger command's
`epic "<name>"` clause (see step 4); ignore whatever the story body says and overwrite that line
once the real epic resolves.

### 2. Ground it in the real repo — no invented paths
For each story, search `~/Documents/work/sethi/sethi_enterprise_frontend` (Read/Glob/Grep) for
the page(s), component(s), hook(s), or module(s) the story actually touches (this repo is
React 18 / Vite / TypeScript — `src/pages/`, `src/components/` (with `shared/`, `dialogs/`,
`search/`, `shortlist/` sub-areas), `src/hooks/`, `src/lib/service.ts`, `src/lib/queries/`).
Confirm every file path named in Scope actually exists; pull real component/prop/hook names for
Technical Context. If the story is too vague to locate real files, ask **one** targeted question
rather than inventing a path.

### 3. Draft each ticket in the team's STORY-ID format
Same structure as `/jira-user-story`'s Artifact A — every section present, `None` if genuinely
empty:

```
### STORY-ID

**Title:** [concise, action-oriented]
**Epic:** [resolved epic name — filled in after step 4]
**Repo:** `sethi_enterprise_frontend`
**Type:** [Feature | Technical | Infrastructure] | **Role:** Frontend | **SP:** [1–3]

---

**User Story**
As a [role], I want [capability] so that [business outcome].

**Business Context**
[1–3 plain-language sentences — the problem or risk, no jargon.]

**Scope**
*Single change: [one-line description]*
- [real file path] — [new | modify | new file]

**Out of Scope**
- [tempting-but-excluded adjacent work]

**Technical Context**
[Real file paths, component/prop/hook names, before→after — grounded in step 2.]

**Dependencies:** [STORY-IDs or "None"]

**Acceptance Criteria**
- [ ] [Specific, testable, observable]

**Definition of Ready**
- [ ] This story read end to end
- [ ] Acceptance Criteria reviewed and understood
- [ ] File paths in Scope confirmed to exist in repo

**Definition of Done**
- [ ] [Implementation checklist only]
- [ ] Linters pass
- [ ] PR reviewed and merged to `develop`

**QA Test Cases**
- [ ] QA: [scenario → expected result]

**Story Points:** [1 | 2 | 3]
```

`SP > 3` means the story isn't atomic — split it into more than one ticket rather than
inflating the estimate. Use `STORY-ID` as a placeholder heading; the real key comes back from
Jira after creation.

**When the source was a bug report**, four sections take the four facts rather than freeform prose:

| Section | What the bug source puts there |
|---|---|
| **Business Context** | the symptom and who it affects, then an `Observed:` / `Expected:` pair |
| **Scope** | the component, page, hook, or query that *produces* the wrong render — confirmed by step 2, not just the screen the operator photographed |
| **Technical Context** | the error verbatim — console message, failed request, stack frame — beside the real component/hook names step 2 found |
| **Acceptance Criteria** | the UI-observable criteria **plus the regression guard: `the reported symptom no longer occurs`** |

The regression guard is not optional and not a rewording of the other criteria — it is the one
criterion that fails if the fix addresses a neighbouring problem instead of the reported one.

`Type:` stays `Technical` for a bug unless the fix ships user-visible new behaviour, and `SP ≤ 3`
holds exactly as it does for a story: a bug too large for 3 points is more than one bug.

### 4. Resolve the epic
Take the name **only from the trigger command's `epic "<name>"` clause** — this skill has no
default, so a trigger without one means step 0 should already have stopped to ask. The lookup and
its safety contract belong to **`/jira-scripts`**; that skill is the authority, and this section
only states what it means here.

**This repo is the worst case on the board.** `summary ~` is a fuzzy, case-insensitive substring
match, and `frontend` matches **four** separate epics — STH-432 `FRONTEND-INTEGRATION`, STH-419
`FRONTEND`, STH-418 `frontend`, STH-417 `frontend`. The old per-skill script silently took the
first, which is how `--epic "FRONTEND"` landed on `FRONTEND-INTEGRATION`.

`/jira-scripts` now **refuses to file** in that situation, printing every match with its key and
status. When it does:

- read the listed matches, pick the intended one, and re-run with **`--epic-key STH-###`** — the
  exact, validated escape hatch (a key that isn't an Epic, or is on another project, is refused);
- on this repo, expect to need `--epic-key` for any frontend-ish epic name. That is the normal
  path here, not a failure;
- do **not** re-word the name hoping for a single match, and do **not** invent an epic key.

Zero matches is likewise an error, not licence to create the epic. Fill the resolved epic's
key/name into each draft's `**Epic:**` line once step 6 confirms it.

### 5. Confirm before creating
Show the draft ticket(s) (title + summary of Scope + Epic it'll link to) and confirm — creating
a Jira issue is outward-facing and there is no delete path available (neither this API nor the
MCP tools can delete an issue, so a mistake has to be corrected by hand in the Jira UI). Skip
the confirmation only if the operator already said "just create it" / "go ahead" for this batch.

### 6. Create via `/jira-scripts`
Write the confirmed stories to a JSON file — `[{"summary": "...", "body": "<everything from
### STORY-ID down, minus the summary line>"}, ...]` — to the scratchpad directory, then call the
shared API skill with this board's key:

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py create-stories \
  --project STH \
  --stories <path-to-stories.json> \
  --epic-key STH-###                  # a bare --epic "<name>" rarely resolves here; see step 4
```

**This skill has no `scripts/` directory of its own** — the write path, credentials, retries,
markdown→ADF conversion, Backlog placement (no Sprint field), fixed assignee, and the fetch-back
confirmation all belong to **`/jira-scripts`**. Read that skill for the mechanics; the only thing
this one contributes to the call is `--project STH` and the epic.

Add `--dry-run` to resolve the epic and render the ADF without creating anything. Use
`find-epic --project STH --name frontend` to see all four candidates before choosing a key.

### 7. Report
Parse the script's JSON stdout and report each created ticket:

```
STH-#### — <summary>
  https://team-anervea.atlassian.net/browse/STH-####
  Epic: STH-### (<name>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)
```

This is the **fetched-back** confirmation (step 6's `GET`), not just an echo of what was sent —
if Jira silently dropped or altered a field, this is where it would show up.

**The browse URL is mandatory, not optional formatting.** Report the full
`https://team-anervea.atlassian.net/browse/STH-####` link for **every** ticket created, on **every**
run, unprompted — the script already returns it as `url`, so it is never unavailable. A bare key is
not a report: the operator's next action is to open the ticket, and making them ask for the link or
rebuild it from the key is a defect in this skill's output. If the report is ever condensed, the URL
is the last thing dropped, never the first.

## Constraints

- **Never report a created ticket without its browse URL** — see step 7. This holds for every ticket
  in the batch, including when the report is shortened or folded into a larger summary.

- **Never invent** a file path, an epic key, or an acceptance criterion — derive everything
  from the actual repo and the operator's pasted story.
- **Never** use the `mcp__claude_ai_Atlassian_*` tools for the create/write step here — that's
  the whole point of this skill existing separately from `/jira-user-story`. Reading via MCP to
  cross-check something is fine; writing is not.
- **Never add a `scripts/` directory to this skill.** The API layer is `/jira-scripts`, and it is
  the single copy on purpose: this skill used to carry its own `create_ticket.py`, and the four
  near-identical copies drifted until half of them were missing the epic-disambiguation fix.
- **Assignee is not askable** — fixed by this skill's contract (always rhidzkhan ahmad). Don't
  prompt for it.
- **The epic is always askable, and always required.** Never fall back to a guessed or
  "closest match" epic — STH's three near-duplicate frontend epic names make that especially
  dangerous here; if none is named, or the match looks ambiguous, stop and ask.
- **The epic source is the trigger command only, never the pasted story body.** An `**Epic:**`
  line inside a pasted draft is descriptive text the drafter wrote, not a selection — reading it
  as one files the ticket under the wrong epic (see step 1's exception).
- If a story is too vague to ground in real code, ask one focused question rather than
  fabricating Scope/Technical Context.
- `SP` stays 1–3; split anything larger into multiple tickets.

## Related skills

- `/sethi-backend-jira-tickets` — the sibling for `sethi_enterprise_backend` work (same
  STORY-ID format, same no-default-epic rule, `Role: Backend`).
- `/sethi-jira-tickets` — the router above both siblings. Use it when the story's side is
  **unknown or mixed**: it classifies frontend/backend/both, splits a both-sides story into two
  linked tickets, resolves the epic once for the batch, then delegates here for the frontend half.
  Reach for this skill directly only when the work is already known to be frontend.
- `/nexus-frontend-jira-tickets` — the nexus-side origin this was ported from (targets
  `NEX`/`nexus_panel_frontend`, defaults to the `FRONTEND` epic — nexus's board has only one).
- `/jira-user-story` — the general-purpose version of this (any repo, any assignee, MCP
  write path, interactive project/epic choice). This skill is a fixed-parameter specialization
  of the same STORY-ID format, pointed at one repo and one write mechanism.
- `/jira-status-move` — transition a ticket's status after creation, if it ever needs to move
  out of Backlog.