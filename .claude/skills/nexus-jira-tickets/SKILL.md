---
name: nexus-jira-tickets
description: >-
  Turn a pasted user story (text or a text file) into NEX Story tickets WITHOUT the operator first
  deciding which nexus repo owns it. Classifies each story as frontend / backend / both across the
  two NEXUS repos (nexus_panel_frontend = React 18/Vite/TS admin SPA, nexus_api = Python AWS Lambda
  service — API endpoints, collectors, MongoDB), then delegates the grounding, drafting, and
  creation to the sibling skill that owns that repo — /nexus-frontend-jira-tickets or
  /nexus-api-jira-tickets. A both-sides story becomes TWO tickets, backend first, with the frontend
  ticket depending on it. Adds only the routing logic and one batch-wide epic gate; it owns no
  ticket template and no Jira write path of its own. Unlike the sethi router, NEX has per-side
  pinned default epics (NEX-754 LAMBDA for backend, NEX-755 FRONTEND for frontend), so a trigger
  with no epic clause files against those defaults instead of stopping to ask. Use when the operator
  says "create nexus tickets", "create nexus jira tickets", "triage these stories into nexus
  tickets", or "create nexus tickets epic '<name>'", followed by a pasted user story — i.e. whenever
  the side is unknown or the batch is mixed. Go straight to the sibling skill instead when the side
  is already known.
---

# Nexus Jira tickets — classify the side, then delegate

**Goal:** one paste in, the right NEX tickets out, without the operator routing by hand.

This skill is a **dispatcher, not a third ticket factory.** It adds exactly three things the two
sibling skills cannot do on their own:

1. **Classification** — is this story frontend work, backend work, or both?
2. **Both-sides splitting** — one story that crosses the client/server boundary becomes two
   atomic tickets, correctly ordered and linked.
3. **One batch-wide epic gate** — a trigger-supplied epic *name* is resolved to a key once for the
   batch, instead of once per sibling invocation.

Everything else belongs elsewhere and is **never** reimplemented here: repo grounding, the
STORY-ID template and the drafting discipline belong to the sibling that owns the repo; the ADF
conversion, fixed assignee, Backlog placement, epic contract and the direct-API write belong to
**`/jira-scripts`**. This skill adds no `scripts/` directory of its own.

| | Always |
|---|---|
| Project | `NEX` |
| Issue type | `Story` |
| Backend stories → | `/nexus-api-jira-tickets` (grounds in `~/Documents/work/nexus_api`) |
| Frontend stories → | `/nexus-frontend-jira-tickets` (grounds in `~/Documents/work/nexus_panel_frontend`) |
| Assignee / placement / write path | owned by `/jira-scripts` via the delegate — rhidzkhan ahmad, Backlog (no Sprint field), direct Jira REST API |
| Epic | trigger's `epic "<name>"` applies batch-wide; **with no clause, each side takes its own pinned default key** — `NEX-754` (backend) / `NEX-755` (frontend) |

## Trigger

`create nexus tickets` / `create nexus jira tickets` / `create nexus tickets epic "<name>"` /
`triage these stories into nexus tickets`, followed by one or more pasted user stories (inline
text or a text file).

**Use a sibling directly, not this skill, when the side is already known** — "create nexus *api*
tickets" and "create nexus *frontend* tickets" name their side and should not detour through a
classifier that can only agree with them.

Splitting a paste into stories follows the siblings' rule: **one story** (freeform prose) or
**several already delimited by `### ` headings** — split on those headings, one ticket per block.

## Procedure

### 1. Settle the epic — before anything else

**This is where NEX diverges from the sethi router, and the divergence is deliberate.** STH has no
generic side-scoped epics, so its router stops and asks. NEX has exactly those two catch-alls, and
both siblings already pin them **as keys**:

| Trigger | Backend group files under | Frontend group files under |
|---|---|---|
| no `epic` clause | `--epic-key NEX-754` (`LAMBDA`) | `--epic-key NEX-755` (`FRONTEND`) |
| `epic "<name>"` | resolved key (step 2) | same resolved key |
| `epic-be "<a>" epic-fe "<b>"` | resolved key for `<a>` | resolved key for `<b>` |

**A bare trigger is complete — do not ask which epic.** Falling through to the pinned defaults is
the contract both siblings already hold; asking anyway just re-opens a question the operator
already answered by pinning them.

A single `epic "..."` **overrides both** defaults and applies batch-wide — NEX's feature epics
(`Data Quality` NEX-989, `AI chat panel` NEX-1638, `Knowledge Graph — Live Data Integration`
NEX-1135) span client and server work exactly as STH's do. A single `epic "..."` plus one
`epic-be`/`epic-fe` override is an error — ask which epic the unnamed side takes rather than
silently reusing the other.

### 2. Resolve a trigger-supplied NAME to a KEY — once, for the whole batch

Skip this step entirely when the trigger carried no epic clause: the defaults are already keys, and
a key never goes through fuzzy matching. This gate exists only for a name the operator typed.

`summary ~` is a fuzzy, case-insensitive **substring** match, so ask **`/jira-scripts`** what a name
actually matches before committing to it:

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py find-epic --project NEX --name "<name>"
```

Verified against the board's 27 epics on 2026-08-24:

| Name given | Matches | Note |
|---|---|---|
| `LAMBDA` | NEX-754 `LAMBDA`, NEX-1679 `Lambda Graph Integration`, NEX-1515 `GRAPH LAMBDA` | **three** — the live misfiling bug; see the warning below |
| `COLLECTOR` | NEX-630, NEX-1128, NEX-1127, NEX-933, **NEX-1728** | five; NEX-1728 matches only inside `Collector-Health` |
| `GRAPH` | NEX-1679, NEX-1515, NEX-1135 | three |
| `MONGO` | NEX-1128, NEX-1127, NEX-951 | three |
| `AI` | NEX-2090, NEX-1638, **NEX-1728** | three — NEX-1728 matches on the `ai` inside `Detail`. A two-letter name is never safe |
| `API` | NEX-1067 `OPTIMIZE API`, NEX-933 | two |
| `Indication Registry` | NEX-1764, NEX-1728 | two |
| `FRONTEND` | NEX-755 only | unambiguous — a name would be fine, but the default is still pinned as a key |
| `Data Quality` | NEX-989 only | unambiguous |
| `SOLUTION` | NEX-1701 only | unambiguous |

- **One match** → the name is safe; carry it forward.
- **More than one** → show the operator the list and ask which, then carry the **key** forward as
  `--epic-key NEX-###`. `/jira-scripts` refuses to file an ambiguous name rather than guessing, so
  this is not optional politeness — it is the only way the batch proceeds.
- **Zero** → stop. Never create the epic and never invent a key.

> ⚠ **Why the defaults are keys.** Verified live 2026-08-23: resolving the documented default *name*
> `LAMBDA` landed on **NEX-1679 `Lambda Graph Integration`**, not NEX-754 `LAMBDA` — three epics
> match that word and the old script silently took the first. Every default-path ticket was
> mis-parented, invisibly. Never re-introduce a default epic *name* anywhere in this family.

Do this **before** step 3, so no classification effort is spent on a batch that cannot be filed.
There is no undo: neither this API nor the MCP tools can delete a Jira issue.

### 3. Classify each story — frontend / backend / both

State the verdict **and a one-line reason** for every story. Never file before the side is
resolved and shown.

| Repo | Identity | Owns |
|---|---|---|
| `nexus_panel_frontend` | `alfakinetic-nexus-admin` — React 18 + Vite + TypeScript SPA, Radix/shadcn + Tailwind, react-router-dom 6, sonner toasts, zod, vitest | screens, drawers, tabs, tables, filters, routing, forms, UI state, styling, how the browser calls the API |
| `nexus_api` | Python AWS Lambda service — 127 endpoints under `lambdas/api/<endpoint>/main.py`, collectors under `lambdas/collectors/<domain>/<id>/`, shared layer `lambdas/shared/**`, MongoDB, Terraform in `infra/` | endpoints, query/filter logic, response + export shape, collectors and their scheduling, DB queries, auth, registries in `infra/*_registry.json` |

Story-shaped heuristics — read what the story **asks to be built**, not where the symptom appears:

- **Backend** — a new or changed endpoint, query parameter, response field, export format, collector,
  Mongo query, or registry entry. Tell: the outcome is invisible in a browser until something
  renders it.
- **Frontend** — a new screen, drawer, tab, table column, filter, empty state, or toast built on data
  the API **already returns**. Tell: no server change is needed for the story to be demoable.
- **Both** — a user-facing capability whose data, parameter, or export does not exist server-side yet.
  Tell: the frontend half is unbuildable until the backend half ships. **This is the common case for
  feature stories** — expect it, don't treat it as the exception.

Cheap grounding beats guessing: Glob/Grep the named screen under `src/components/` in the frontend
repo and the named endpoint under `lambdas/api/` in the backend repo. If the story stays genuinely
ambiguous, ask **one** focused question — do not split a story into two tickets just to avoid
deciding.

**A symptom seen in the UI is not a frontend story.** The two are routinely confused, and the
distinguishing question is where the *fix* lands, not where QA noticed it. A filter that visibly
works on screen but not in the exported file is backend work, even though every observation of it
was made in the browser.

**Flag a shared-layer landing at classification time.** If a backend story's fix would land in
`lambdas/shared/**` or `lambdas/collectors/workers/**`, say so in the routing report — those trees
are `COPY`'d into every collector and API image, so a one-line edit rebuilds the whole fleet. The
ticket should scope the change to the one collector's own folder unless it deliberately intends the
fan-out. The redirect ladder belongs to `/shared-layer-guard`; this skill only raises the flag.

### 4. Split the both-sides stories — backend first

A `both` verdict yields **two tickets, never one**, each atomic on its own side:

- The **backend** ticket owns the endpoint / parameter / export shape, and its Acceptance Criteria
  are observable at the API (status code, payload shape, exported bytes).
- The **frontend** ticket owns the rendering / interaction, and its Acceptance Criteria are
  observable in the UI.
- **Order: backend created first.** Its real `NEX-####` key goes into the frontend ticket's
  `**Dependencies:**` line before that ticket is drafted for creation.
- **The dependency is one-directional on purpose.** The frontend genuinely depends on the backend;
  the reverse is not true, and the create-only script has no update path, so a back-link would
  have to be added by hand for no gain. Do not invent one.

Each half must still hold `SP ≤ 3` on its own. If either half exceeds that after splitting, split
that half again — never inflate the estimate.

### 5. Delegate, one sibling per side

Hand each group to the skill that owns its repo and let it run its own procedure end to end
(grounding → STORY-ID draft → confirm → create → fetch-back):

- backend group → **`/nexus-api-jira-tickets`**, with the epic key settled in step 1/2
- frontend group → **`/nexus-frontend-jira-tickets`**, with the epic key settled in step 1/2

Pass the already-settled epic **key** (`--epic-key NEX-###`) so the delegate neither re-asks nor
re-runs a fuzzy name lookup that could land somewhere else, and pass the batch's confirmation state
so the operator is not asked to confirm the same tickets twice. **Backend group runs to completion
first** whenever the batch contains a split story — step 4 needs its keys.

Do not pre-draft the ticket bodies here. Grounding a story in real file paths is precisely what the
siblings exist to do, and a draft written before that grounding is a draft with invented paths.

### 6. Report once, for the whole batch

One consolidated report, grouped by side, using each delegate's fetched-back confirmation:

```
Classified: 3 stories → 1 backend, 1 frontend, 1 both (split)

BACKEND
  NEX-#### — <summary>
    https://team-anervea.atlassian.net/browse/NEX-####
    Epic: NEX-### (<name>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)

FRONTEND
  NEX-#### — <summary>   [depends on NEX-####]
    https://team-anervea.atlassian.net/browse/NEX-####
    Epic: NEX-### (<name>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)
```

State the classification verdict and its reason for each story alongside the keys — the routing
decision is the thing the operator most needs to audit, and it is invisible in the Jira output.
Say explicitly when the epic came from a **default** rather than the trigger, so a batch that
should have been feature-scoped is visible as one that landed in the catch-all.

**The browse URL is mandatory, not optional formatting.** Every ticket in the consolidated report
carries its full `https://team-anervea.atlassian.net/browse/NEX-####` link — every ticket, every run,
unprompted. The delegate already returns it, so consolidating a batch is never a reason to drop it;
a both-sides split means **two** links, not one. A bare key is not a report: the operator's next
action is to open the ticket. If the report is ever condensed, the URL is the last thing dropped,
never the first.

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
- **The epic comes from the trigger or the pinned defaults only** — never from a pasted story's
  `**Epic:**` line. That line is descriptive text the drafter wrote; reading it as an instruction
  has already misfiled a ticket on this board (a `nexus_api` story that said "FRONTEND" in its body
  because it unblocked frontend work got parented to the FRONTEND epic instead of LAMBDA).
- **Never invent** a file path, an epic key, or an acceptance criterion.
- **Story only.** Both delegates create `Issue type: Story`. This skill cannot file a **Bug** — see
  Related skills for that path.
- **Stop at the ticket.** This skill never opens a branch and never writes a fix — that is
  `/jira-implement`.

## Related skills

- **`/jira-scripts`** — the Jira API layer underneath the whole family. This skill calls its
  `find-epic` subcommand for the step-2 gate; the delegates call `create-stories`.
- `/nexus-api-jira-tickets` · `/nexus-frontend-jira-tickets` — the two delegates. They own the
  repo grounding and the STORY-ID template; this skill only chooses between them.
- `/sethi-jira-tickets` — the `STH` board equivalent of this router, and the file this one was
  ported from. Keep the two in step when either changes; the deliberate difference is step 1 (STH
  has no default epic and stops to ask, NEX falls through to its per-side pinned keys).
- `/jira-bug-ticket` — the path for a **Bug** rather than a Story. Note it sets **no epic and no
  assignee** and writes via MCP, so pass `parent` (NEX-754 for backend, NEX-755 for frontend) and
  the assignee explicitly, or the ticket lands bare — that is exactly how NEX-2410 was filed.
- `/shared-layer-guard` — owns the redirect ladder for a backend change that would land in
  `lambdas/shared/**`; step 3 only raises the flag.
- `/jira-user-story` — the general-purpose ancestor of the whole family (any repo, any assignee,
  MCP write path, interactive project/epic choice).