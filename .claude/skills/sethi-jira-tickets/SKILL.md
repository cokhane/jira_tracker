---
name: sethi-jira-tickets
description: >-
  Turn a pasted user story OR a bug report — a screenshot, stack trace, or error text plus the
  operator's explanation — into STH Story tickets WITHOUT the operator first deciding which sethi
  repo owns it. Reads an image visually, extracts the four facts (symptom, error, location, repro),
  then classifies each item as frontend / backend / both across the two SETHI repos
  (sethi_enterprise_frontend = React/Vite/TS SPA, sethi_enterprise_backend = FastAPI/Python
  service), and delegates the grounding, drafting, and creation to the sibling skill that owns that
  repo — /sethi-frontend-jira-tickets or /sethi-backend-jira-tickets. A both-sides item becomes TWO
  tickets, backend first, with the frontend ticket depending on it. Adds only the input handling,
  the routing logic, and one batch-wide epic-disambiguation gate; it owns no ticket template and no
  Jira write path of its own. Use when the operator says "create sethi tickets", "create sethi jira
  tickets", "triage these stories into sethi tickets", "triage this bug into a sethi ticket", or
  "create sethi tickets epic '<name>'", followed by a pasted story, a screenshot, or an error — i.e.
  whenever the side is unknown or the batch is mixed. Go straight to the sibling skill instead when
  the side is already known.
---

# Sethi Jira tickets — classify the side, then delegate

**Goal:** one paste in, the right STH tickets out, without the operator routing by hand.

This skill is a **dispatcher, not a third ticket factory.** It adds exactly four things the two
sibling skills cannot do on their own:

1. **Input handling** — a bug report (screenshot, stack trace, error text) is read and normalized
   into a story, so the operator does not have to write one first.
2. **Classification** — is this frontend work, backend work, or both?
3. **Both-sides splitting** — one item that crosses the client/server boundary becomes two
   atomic tickets, correctly ordered and linked.
4. **One batch-wide epic gate** — the fuzzy-match hazard is resolved once for the batch instead of
   once per sibling invocation.

Everything else belongs elsewhere and is **never** reimplemented here: repo grounding, the
STORY-ID template and the drafting discipline belong to the sibling that owns the repo; the ADF
conversion, fixed assignee, Backlog placement, epic contract and the direct-API write belong to
**`/jira-scripts`**. This skill adds no `scripts/` directory of its own.

| | Always |
|---|---|
| Project | `STH` |
| Issue type | `Story` |
| Backend stories → | `/sethi-backend-jira-tickets` (grounds in `~/Documents/work/sethi/sethi_enterprise_backend`) |
| Frontend stories → | `/sethi-frontend-jira-tickets` (grounds in `~/Documents/work/sethi/sethi_enterprise_frontend`) |
| Assignee / placement / write path | owned by `/jira-scripts` via the delegate — rhidzkhan ahmad, Backlog (no Sprint field), direct Jira REST API |
| Epic | **always named in the trigger — no default**, exactly as both siblings require |

## Trigger

`create sethi tickets epic "<name>"` / `create sethi jira tickets epic "<name>"` /
`triage these stories into sethi tickets` / `triage this bug into a sethi ticket`, followed by
one or more pasted user stories, or by a bug report.

**Use a sibling directly, not this skill, when the side is already known** — "create sethi
*backend* tickets" and "create sethi *frontend* tickets" name their side and should not detour
through a classifier that can only agree with them.

## Input handling — a story, or a bug report

Two input kinds reach this skill. They differ only in how the ticket's raw material is obtained;
everything downstream — epic gate, classification, split, delegate, report — is identical, and both
produce a **Story** on this board. Issue type never changes.

**A user story** — inline text or a text file. Split it the siblings' way: **one story** (freeform
prose) or **several already delimited by `### ` headings** — split on those headings, one ticket
per block.

**A bug report** — an attached or pasted image (UI screenshot, stack trace, Slack grab), an image
file path, or an inline error description; in every case together with whatever the operator wrote
alongside it. Read an image visually with the Read tool and pull **the four facts**:

| Fact | What to capture |
|---|---|
| Symptom | the observable wrong behaviour |
| Error | visible error text, HTTP status, stack trace — verbatim, not paraphrased |
| Location | the screen, route, or URL shown |
| Repro | reproduction hints, whether visible in the image or stated by the operator |

**The operator's explanation outranks the image wherever the two disagree** — a screenshot is one
frame, the operator knows the flow that produced it. Where the image carries a fact the explanation
omits, keep both.

Then normalize the four facts into a story before step 3, in the same `### STORY-ID` shape the
delegates draft into, with the behaviour to restore as the capability. The bug-ness survives as the
extra draft requirements the delegates apply (their step 3), not as a different issue type.

Empty or unintelligible input is a question, not a guess: ask for a clearer image or a description.

**Root cause is not this skill's job.** Grounding a ticket in real file paths — what the delegates
do in their step 2 — locates the code the ticket names; it does not diagnose why the bug happens.
When the operator wants the cause traced first, hand off to `/investigate` or `/rca` and come back
with the findings as input here.

## Procedure

### 1. Take the epic from the trigger — before anything else
No default epic, same as both sethi siblings. If the trigger carries no `epic "<name>"` clause,
**stop and ask** — do not classify first and ask later, because the answer changes nothing about
the routing and everything about whether the batch is fileable.

**One epic normally covers both sides.** STH's real epics are feature-scoped, not side-scoped —
`Interview Platform` (STH-600), `Dynamic Roles & Permissions` (STH-521), `Project Assignment
Management` (STH-564) each span client and server work. So a single `epic "<name>"` applies to
every ticket in the batch, frontend and backend alike.

Override per side only when the operator explicitly passes both clauses:

```
create sethi tickets epic-be "Interview Platform" epic-fe "FRONTEND"
```

A single `epic "..."` plus one override is an error — ask which epic the unnamed side takes rather
than silently reusing the other.

### 2. Resolve that name to a KEY — once, for the whole batch
Epic *names* are ambiguous on this board; epic *keys* are not. Resolve the name to a key here,
once, and pass the key to both delegates — that way the batch cannot half-file under one epic and
half under another.

`summary ~` is a fuzzy, case-insensitive substring match, so ask **`/jira-scripts`** what a name
actually matches before committing to it:

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py find-epic --project STH --name "<name>"
```

| Name given | Matches | Note |
|---|---|---|
| `frontend` / `FRONTEND` | STH-432 `FRONTEND-INTEGRATION`, STH-419 `FRONTEND`, STH-418 `frontend`, STH-417 `frontend` | four epics; a bare name can never settle this |
| `Dynamic Roles & Permissions` | STH-521 (exact) **and** STH-516 (longer, `Merged`) | pick the live one deliberately |
| `stale` | STH-478 `Stale`, STH-479 `STALE`, STH-480 `stale` | three case variants |
| `GRG` | STH-497 and STH-516 (`(GRG-internal)`) | matches inside a parenthetical |
| `Interview Platform` | STH-600 only | unambiguous — a name is fine |
| `Project Assignment Management` | STH-564 only | unambiguous — a name is fine |

- **One match** → the name is safe; carry it forward.
- **More than one** → show the operator the list and ask which, then carry the **key** forward as
  `--epic-key STH-###`. `/jira-scripts` refuses to file an ambiguous name rather than guessing, so
  this is not optional politeness — it is the only way the batch proceeds.
- **Zero** → stop. Never create the epic and never invent a key.

Do this **before** step 3, so no classification effort is spent on a batch that cannot be filed.
There is no undo: neither this API nor the MCP tools can delete a Jira issue.

### 3. Classify each item — frontend / backend / both
State the verdict **and a one-line reason** for every story or bug. Never file before the side is
resolved and shown.

| Repo | Identity | Owns |
|---|---|---|
| `sethi_enterprise_frontend` | React 18 + Vite + TypeScript + shadcn/ui + TanStack Query SPA | screens, components, routing, forms, UI state, styling, how the browser calls the API |
| `sethi_enterprise_backend` | FastAPI (Python) service — Postgres/Mongo/Redis, S3, SSO, meeting integrations, AI services | endpoints, business logic, DB queries + migrations, auth/RBAC enforcement, AI services, response shape |

Story-shaped heuristics — read what the story **asks to be built**, not where the symptom appears:

- **Backend** — a new or changed endpoint, request/response field, DB column or migration,
  permission/capability check, background job, integration, or AI call. Tell: the outcome is
  invisible in a browser until something renders it.
- **Frontend** — a new screen, dialog, column, filter, empty state, validation message, or
  navigation change built on data the API **already returns**. Tell: no server change is needed
  for the story to be demoable.
- **Both** — a user-facing capability whose data or permission does not exist server-side yet. Tell:
  the frontend half is unbuildable until the backend half ships. **This is the common case for
  feature stories** — expect it, don't treat it as the exception.

Bug-shaped tells are different — read where the wrong behaviour **originates**, not where it is
seen:

- **Frontend** — a visual, layout, or styling glitch; a blank or broken component; client-side
  routing or navigation; a form-validation display; a browser-console error; correct data rendered
  wrongly.
- **Backend** — a 4xx/5xx JSON response; a Python/FastAPI stack trace; a DB, query, or migration
  error; an auth or RBAC failure at the API; an AI-service failure; wrong or missing data in the
  payload.
- **Both** — a UI symptom whose root cause is a bad or absent API response.

**A screenshot is not evidence of a frontend bug.** The browser is the only surface a user can
photograph, so the image shows where the symptom *surfaced* — plenty of bug screenshots are backend
or both. Decide from the four facts, not from the fact that an image exists.

Cheap grounding beats guessing: Glob/Grep the named screen in the frontend repo and the named
endpoint in `router/` of the backend repo. If an item stays genuinely ambiguous, ask **one**
focused question — do not split it into two tickets just to avoid deciding.

### 4. Split the both-sides stories — backend first
A `both` verdict yields **two tickets, never one**, each atomic on its own side:

- The **backend** ticket owns the endpoint / field / permission, and its Acceptance Criteria are
  observable at the API (status code, payload shape, denial behaviour).
- The **frontend** ticket owns the rendering / interaction, and its Acceptance Criteria are
  observable in the UI.
- For a **bug**, that same seam splits cause from symptom: the backend ticket's Acceptance Criteria
  cover the server-side root cause, the frontend ticket's cover the UI symptom the operator
  reported. Both carry the regression guard for their own half.
- **Order: backend created first.** Its real `STH-####` key goes into the frontend ticket's
  `**Dependencies:**` line before that ticket is drafted for creation.
- **The dependency is one-directional on purpose.** The frontend genuinely depends on the backend;
  the reverse is not true, and the create-only script has no update path, so a back-link would
  have to be added by hand for no gain. Do not invent one.

Each half must still hold `SP ≤ 3` on its own. If either half exceeds that after splitting, split
that half again — never inflate the estimate.

### 5. Delegate, one sibling per side
Hand each group to the skill that owns its repo and let it run its own procedure end to end
(grounding → STORY-ID draft → confirm → create → fetch-back):

- backend group → **`/sethi-backend-jira-tickets`**, with the resolved epic key from step 2
- frontend group → **`/sethi-frontend-jira-tickets`**, with the resolved epic key from step 2

Pass the already-resolved epic **key** (`--epic-key STH-###`) so the delegate neither re-asks nor
re-runs a fuzzy name lookup that could land somewhere else, and pass the batch's confirmation
state so the operator is not asked to confirm the same tickets twice. **Backend group runs to
completion first** whenever the batch contains a split story — step 4 needs its keys.

**When the source was a bug report, hand the delegate the four facts alongside the normalized
story** — verbatim error text included. It needs them for the Business Context, the Technical
Context, and the regression-guard Acceptance Criterion its step 3 requires; a summary of the
symptom is not enough to write those.

Do not pre-draft the ticket bodies here. Grounding a story in real file paths is precisely what the
siblings exist to do, and a draft written before that grounding is a draft with invented paths.

### 6. Report once, for the whole batch
One consolidated report, grouped by side, using each delegate's fetched-back confirmation:

```
Classified: 3 stories → 1 backend, 1 frontend, 1 both (split)

BACKEND
  STH-#### — <summary>
    https://team-anervea.atlassian.net/browse/STH-####
    Epic: STH-### (<name>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)

FRONTEND
  STH-#### — <summary>   [depends on STH-####]
    https://team-anervea.atlassian.net/browse/STH-####
    Epic: STH-### (<name>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)
```

State the classification verdict and its reason for each story alongside the keys — the routing
decision is the thing the operator most needs to audit, and it is invisible in the Jira output.

**The browse URL is mandatory, not optional formatting.** Every ticket in the consolidated report
carries its full `https://team-anervea.atlassian.net/browse/STH-####` link — every ticket, every run,
unprompted. The delegate already returns it, so consolidating a batch is never a reason to drop it;
a both-sides split means **two** links, not one. A bare key is not a report: the operator's next
action is to open the ticket. If the report is ever condensed, the URL is the last thing dropped,
never the first.

### 7. Save the story artifact — only when asked
`/bug-triage-story`, the ancestor of this skill's bug-report handling, writes every story it files
to `<classified-repo>/docs/user-story/STH-###-<slug>.md`. This skill does not, by default: the sethi
family stops at the ticket and leaves the two product repos' working trees alone.

When the operator does ask for it ("save the story too", "write the markdown as well"), write it
there **after** creation, with the real `STH-###` key as the top heading and a `<slug>` of 3–5
kebab-case words. A both-sides split writes two files, one under each repo, each noting its sibling
key near the top.

## Constraints

- **Never report a created ticket without its browse URL** — see step 6. This holds for every ticket
  in the batch, on both sides of a split, including when the report is shortened.

- **This skill has no `scripts/` directory and never gets one.** All Jira API access in this
  family goes through **`/jira-scripts`**, which is the single copy on purpose — the four
  per-skill copies it replaced had already drifted apart.
- **Never reimplement the STORY-ID template here.** It is owned by the siblings (and upstream by
  `/jira-user-story`); duplicating it into a router is how the two copies drift apart.
- **Never** use the `mcp__claude_ai_Atlassian_*` tools for a write — the whole point of this family
  is the direct-API path. Reading via MCP to cross-check something is fine.
- **Always show the classification and its reason** before creating. A silently-routed story is a
  story the operator cannot check.
- **The epic comes from the trigger only** — never from a pasted story's `**Epic:**` line (that
  line is descriptive text the drafter wrote; reading it as an instruction has already misfiled a
  ticket on the nexus side), and never from a "closest match" guess.
- **Never invent** a file path, an epic key, or an acceptance criterion.
- **Stop at the ticket.** This skill never opens a branch and never writes a fix — that is
  `/jira-implement` for a story, `/bug-fix` for a bug. Reading a screenshot of a crash is not
  licence to go fix the crash.

## Related skills

- **`/jira-scripts`** — the Jira API layer underneath the whole family. This skill calls its
  `find-epic` subcommand for the step-2 gate; the delegates call `create-stories`.
- `/sethi-backend-jira-tickets` · `/sethi-frontend-jira-tickets` — the two delegates. They own the
  repo grounding and the STORY-ID template; this skill only chooses between them.
- `/bug-triage-story` — the ancestor this skill's bug-report input handling was folded in from. It
  runs the same frontend/backend/both classification, but files through the **MCP** path
  (`jira-operator` → `/jira-user-story`) and always writes the `docs/user-story/` artifact. **Prefer
  this skill for STH**: the direct-API path keeps the fixed assignee, the Backlog placement, and the
  epic-key gate that the MCP path does not enforce. Reach for `/bug-triage-story` when the
  `docs/user-story/` artifact is the point, or when the board is not STH.
- `/investigate` · `/rca` — trace a bug's root cause *before* a ticket is written, then bring the
  findings back here as input. This skill locates the code a ticket should name; it does not
  diagnose.
- `/nexus-api-jira-tickets` · `/nexus-frontend-jira-tickets` — the `NEX` board equivalents of the
  two delegates. A `nexus-jira-tickets` router does not exist yet; port this file the same way
  (swap the two delegate names, the repo identity table, and the epic-ambiguity table for NEX's
  own) if it is ever wanted.
- `/jira-user-story` — the general-purpose ancestor of the whole family (any repo, any assignee,
  MCP write path, interactive project/epic choice).