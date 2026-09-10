---
name: sethi-backend-jira-tickets
description: >-
  Turn a pasted user story (text or a text file) into one or more STH Story tickets for
  sethi_enterprise_backend work, grounded in that repo's actual code rather than invented file
  paths. Reads ~/Documents/work/sethi/sethi_enterprise_backend to source the Scope and Technical
  Context sections, drafts the team's standard STORY-ID format, then creates the ticket(s) by
  calling the shared /jira-scripts skill (jira_api.py create-stories --project STH) — the direct
  Jira REST API, not the Atlassian MCP tools. Every
  ticket is always assigned to rhidzkhan ahmad and always lands in the Backlog (no Sprint field
  set). Unlike the sibling nexus-api-jira-tickets skill, the Epic has NO default — STH has no
  generic backend catch-all epic (its epics are feature-specific: Interview Platform, Dynamic
  Roles & Permissions, RBAC, etc), so the epic name must always be given and is resolved by
  searching the board rather than guessed. Use when the operator says "create sethi backend
  tickets", "create sethi api tickets", or "create sethi backend tickets epic '<name>'", followed
  by a pasted user story — or by a bug report (screenshot, stack trace, error text) already known
  to be backend, which is read via /sethi-jira-tickets' Input handling section and then drafted
  with this skill's bug-source requirements.
---

# Sethi backend Jira tickets — code-grounded STORY tickets via the Jira API

Creates STH Story tickets for `sethi_enterprise_backend` work. A direct port of the sibling
`/nexus-api-jira-tickets` skill, repointed from the `NEX` board to the `STH` board — same STORY-ID
format, same code-grounding discipline, same direct-API write path. The distinguishing choices,
all fixed by the operator rather than inferred per run:

| | Always |
|---|---|
| Project | `STH` |
| Repo the ticket is grounded in | `~/Documents/work/sethi/sethi_enterprise_backend` |
| Issue type | `Story` |
| Assignee | rhidzkhan ahmad (`712020:525b78f1-26da-462d-b8cd-91b3598ad495`) |
| Placement | Backlog — created with **no Sprint field**, so it never lands on the active board |
| Epic | **always named in the trigger — no default.** STH has no generic backend catch-all epic (unlike `LAMBDA` on `NEX`); resolved by searching the board, never guessed |
| Write path | **`/jira-scripts`** → `jira_api.py create-stories --project STH`, **not** `mcp__claude_ai_Atlassian_*` |

## Trigger

`create sethi backend tickets epic "<name>"` / `create sethi api tickets epic "<name>"`, followed
by one or more pasted user stories (inline text or a text file). Extract `<name>` from the quoted
string after `epic`. **Unlike the nexus siblings, there is no fallback epic** — if the trigger has
no `epic "..."` clause, stop and ask which epic to file under rather than guessing or defaulting.

A single paste may contain **one story** (freeform prose — draft the full ticket from it) or
**several stories already delimited by `### `** headings (the team's STORY-ID format) — split on
those headings and produce one ticket per block.

## Procedure

### 1. Read the pasted input
Identify one or more stories per the splitting rule above. For each: extract the role,
capability, and outcome (or, if already in STORY-ID format, take its fields as given — never
overwrite content the operator already wrote).

**A bug report is a valid input here too** — a screenshot, stack trace, or error text plus the
operator's explanation, when the work is already known to be backend. Reading it is owned by
**`/sethi-jira-tickets` → "Input handling"**: read the image with the Read tool, pull the four facts
(symptom, error, location, repro), and normalize them into the STORY-ID shape below. That section is
the single source for those rules — follow it rather than improvising an extraction here. Carry the
four facts forward into step 3, which draft sections depend on them.

**Exception: the `**Epic:**` line, if the pasted text has one, is never taken as given.**
A pasted draft's `**Epic:**` line is often just descriptive context the drafter wrote — not an
instruction for which epic to file under. The epic comes **only** from the trigger command's
`epic "<name>"` clause (see step 4); ignore whatever the story body says and overwrite that line
once the real epic resolves. (This bug surfaced live in `nexus-api-jira-tickets` — a story that
named a wrong epic in its own body got misfiled — and is guarded against here from the start.)

### 2. Ground it in the real repo — no invented paths
For each story, search `~/Documents/work/sethi/sethi_enterprise_backend` (Read/Glob/Grep) for the
router(s), endpoint(s), model(s), helper(s), or module(s) the story actually touches (this repo is
FastAPI/Python — `router/`, `helper/`, `model/`, `schema/`, `alembic/`). Confirm every file path
named in Scope actually exists; pull real symbol/function/class names for Technical Context. If
the story is too vague to locate real files, ask **one** targeted question rather than inventing a
path.

### 3. Draft each ticket in the team's STORY-ID format
Same structure as `/jira-user-story`'s Artifact A — every section present, `None` if genuinely
empty:

```
### STORY-ID

**Title:** [concise, action-oriented]
**Epic:** [resolved epic name — filled in after step 4]
**Repo:** `sethi_enterprise_backend`
**Type:** [Feature | Technical | Infrastructure] | **Role:** Backend | **SP:** [1–3]

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
[Real file paths, function/class/endpoint names, before→after — grounded in step 2.]

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
| **Scope** | the router, helper, or model that *produces* the wrong behaviour — confirmed by step 2, never inferred from the screen the operator photographed |
| **Technical Context** | the error verbatim — status code, exception, stack frame — beside the real symbol names step 2 found |
| **Acceptance Criteria** | the API-observable criteria **plus the regression guard: `the reported symptom no longer occurs`** |

The regression guard is not optional and not a rewording of the other criteria — it is the one
criterion that fails if the fix addresses a neighbouring problem instead of the reported one.

`Type:` stays `Technical` for a bug unless the fix ships user-visible new behaviour, and `SP ≤ 3`
holds exactly as it does for a story: a bug too large for 3 points is more than one bug.

### 4. Resolve the epic
Take the name **only from the trigger command's `epic "<name>"` clause** — this skill has no
default, so a trigger without one means step 0 should already have stopped to ask. The lookup and
its safety contract belong to **`/jira-scripts`**; that skill is the authority, and this section
only states what it means here.

`summary ~` is a fuzzy, case-insensitive substring match, and on this board several names collide
(`frontend` matches four separate epics; `Dynamic Roles & Permissions` matches two). `/jira-scripts`
therefore **refuses to file when a name matches more than one epic**, printing every match with its
key and status, rather than silently taking the first. When that happens:

- read the listed matches, pick the intended one, and re-run with **`--epic-key STH-###`** — the
  exact, validated escape hatch (a key that isn't an Epic, or is on another project, is refused);
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
  --epic "<name-from-trigger>"        # or --epic-key STH-### per step 4
```

**This skill has no `scripts/` directory of its own** — the write path, credentials, retries,
markdown→ADF conversion, Backlog placement (no Sprint field), fixed assignee, and the fetch-back
confirmation all belong to **`/jira-scripts`**. Read that skill for the mechanics; the only thing
this one contributes to the call is `--project STH` and the epic.

Add `--dry-run` to resolve the epic and render the ADF without creating anything — worth doing
whenever the epic name is not provably unique, or to sanity-check a draft's rendering first.

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
- **The epic is always askable, and always required** — the opposite of the nexus siblings. Never
  fall back to a guessed or "closest match" epic; if none is named, stop and ask.
- **The epic source is the trigger command only, never the pasted story body.** An `**Epic:**`
  line inside a pasted draft is descriptive text the drafter wrote, not a selection — reading it
  as one files the ticket under the wrong epic (see step 1's exception).
- If a story is too vague to ground in real code, ask one focused question rather than
  fabricating Scope/Technical Context.
- `SP` stays 1–3; split anything larger into multiple tickets.

## Related skills

- **`/jira-scripts`** — the API layer this skill calls for every Jira write. It owns the
  credentials, the retries, the markdown→ADF conversion, the epic-ambiguity contract, and the
  fetch-back confirmation. Read it before changing anything about how tickets get created.
- `/nexus-api-jira-tickets` — the skill this was copied from (same STORY-ID format, same
  `/jira-scripts` write path, targets `NEX`/`nexus_api`).
- `/sethi-frontend-jira-tickets` — the sibling for `sethi_enterprise_frontend` work (same
  STORY-ID format, same no-default-epic rule, `Role: Frontend`).
- `/sethi-jira-tickets` — the router above both siblings. Use it when the story's side is
  **unknown or mixed**: it classifies frontend/backend/both, splits a both-sides story into two
  linked tickets, resolves the epic once for the batch, then delegates here for the backend half.
  Reach for this skill directly only when the work is already known to be backend.
- `/nexus-frontend-jira-tickets` — the nexus-side frontend sibling (`FRONTEND` epic default).
- `/jira-user-story` — the general-purpose version of this (any repo, any assignee, MCP
  write path, interactive project/epic choice). This skill is a fixed-parameter specialization
  of the same STORY-ID format, pointed at one repo and one write mechanism.
- `/jira-status-move` — transition a ticket's status after creation, if it ever needs to move
  out of Backlog.