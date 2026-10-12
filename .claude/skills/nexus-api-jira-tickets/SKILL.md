---
name: nexus-api-jira-tickets
description: >-
  Turn a pasted user story (text or a text file) into one or more NEX Story tickets for nexus_api
  work, grounded in that repo's actual code rather than invented file paths. Reads
  ~/Documents/work/nexus_api to source the Scope and Technical Context sections, drafts the team's
  standard STORY-ID format, then creates the ticket(s) by calling the shared /jira-scripts skill
  (jira_api.py create-stories --project NEX) — the direct Jira REST API, not the Atlassian MCP
  tools. Every ticket is always assigned to rhidzkhan ahmad, always lands in the Backlog (no
  Sprint field set), and is always linked to an Epic — the one named in the trigger, or the pinned
  default epic NEX-754 (LAMBDA) if none is given. Epic names are resolved by /jira-scripts, which
  refuses to file when a name matches more than one epic rather than taking the first. Use when
  the operator says "create nexus api tickets", "create nexus backend tickets", or "create nexus
  api tickets epic '<name>'", followed by a pasted user story.
---

# Nexus API Jira tickets — code-grounded STORY tickets via the Jira API

Creates NEX Story tickets for `nexus_api` work. The distinguishing choices, all fixed by
the operator rather than inferred per run:

| | Always |
|---|---|
| Project | `NEX` |
| Repo the ticket is grounded in | `~/Documents/work/nexus_api` |
| Issue type | `Story` |
| Assignee | rhidzkhan ahmad (`712020:525b78f1-26da-462d-b8cd-91b3598ad495`) |
| Placement | Backlog — created with **no Sprint field**, so it never lands on the active board |
| Epic | named in the trigger, else the **pinned default `--epic-key NEX-754`** (`LAMBDA`). A default *name* is what caused the misfiling this family was refactored to stop — see step 4 |
| Write path | **`/jira-scripts`** → `jira_api.py create-stories --project NEX`, **not** `mcp__claude_ai_Atlassian_*` |

## Trigger

`create nexus api tickets epic "<name>"` / `create nexus backend tickets epic "<name>"` /
`create nexus api tickets` (epic omitted → defaults to `--epic-key NEX-754`), followed by one or
more pasted user stories (inline text or a text file). Extract `<name>` from the quoted
string after `epic`; if the phrase has no `epic "..."` clause, pass `--epic-key NEX-754`
rather than the bare name `LAMBDA` (step 4 explains why the distinction matters).

A single paste may contain **one story** (freeform prose — draft the full ticket from it) or
**several stories already delimited by `### `** headings (the team's STORY-ID format) — split
on those headings and produce one ticket per block.

## Procedure

### 1. Read the pasted input
Identify one or more stories per the splitting rule above. For each: extract the role,
capability, and outcome (or, if already in STORY-ID format, take its fields as given — never
overwrite content the operator already wrote).

**Exception: the `**Epic:**` line, if the pasted text has one, is never taken as given.**
A pasted draft's `**Epic:**` line is often just descriptive context the drafter wrote (e.g. "this
backend story unblocks *frontend* work, so I labeled it FRONTEND") — not an instruction for which
epic to file under. The epic comes **only** from the trigger command's `epic "<name>"` clause (see
step 4); ignore whatever the story body says and overwrite that line once the real epic resolves.

### 2. Ground it in the real repo — no invented paths
For each story, search `~/Documents/work/nexus_api` (Read/Glob/Grep) for the collector(s),
endpoint(s), Lambda(s), or module(s) the story actually touches. Confirm every file path
named in Scope actually exists; pull real symbol/function/class names for Technical Context.
If the story is too vague to locate real files, ask **one** targeted question rather than
inventing a path.

### 3. Draft each ticket in the team's STORY-ID format
Same structure as `/jira-user-story`'s Artifact A — every section present, `None` if genuinely
empty:

```
### STORY-ID

**Title:** [concise, action-oriented]
**Epic:** [resolved epic name — filled in after step 4]
**Repo:** `nexus_api`
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

### 4. Resolve the epic
Take the name **only from the trigger command's `epic "<name>"` clause** — or the pinned default
`--epic-key NEX-754` if the trigger had none. Never take it from an `**Epic:**` line inside the
pasted story body, even when the story is already in full STORY-ID format with that field filled
in (see step 1's exception) — that field describes the story, it doesn't select the epic.

The lookup and its safety contract belong to **`/jira-scripts`**. `summary ~` is a fuzzy,
case-insensitive substring match, so a *name* can match several epics; `/jira-scripts` refuses
to file in that case, listing every match with its key and status. Re-run with
**`--epic-key NEX-###`** to settle it — the key is exact and validated (a key that isn't an
Epic, or belongs to another project, is refused).

> ⚠ **This is why the default is a key, not a name.** Verified live 2026-08-23: the old
> per-skill script resolved the documented default name `LAMBDA` to **NEX-1679 `Lambda Graph
> Integration`**, not NEX-754 `LAMBDA` — three epics match that word, and it silently took the
> first. The old script also omitted `epic_summary` from its dry-run output, so nothing showed
> it. Every default-path ticket was mis-parented, invisibly. Pass the key.

Zero matches is an error, not licence to create the epic — **never** invent an epic key. Fill
the resolved epic's key/name into each draft's `**Epic:**` line once step 6 confirms it.

### 5. Confirm before creating
Show the draft ticket(s) (title + summary of Scope + Epic it'll link to) and confirm — creating
a Jira issue is outward-facing and there is no delete path available (neither this API nor the
MCP tools can delete an issue, so a mistake has to be corrected by hand in the Jira UI). Skip
the confirmation only if the operator already said "just create it" / "go ahead" for this batch.

### 6. Create via `/jira-scripts`
Write the confirmed stories to a JSON file — `[{"summary": "...", "body": "<everything from
### STORY-ID down, minus the summary line>"}, ...]` — to the scratchpad directory, then call
the shared API skill with this board's key:

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py create-stories \
  --project NEX \
  --stories <path-to-stories.json> \
  --epic-key NEX-754                      # or --epic "<name-from-trigger>" per step 4
```

The script: resolves the epic, converts each `body` from markdown to Atlassian Document
Format, `POST /rest/api/3/issue` with the fixed assignee + resolved `parent` (epic) + **no**
`customfield_10020` (Sprint) — which is what keeps it in Backlog — then `GET`s each created
issue back and prints the confirmed result as JSON. Credentials come from
`jira_tracker_backend/.env` (`JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN`) — the same
token the rest of this app already uses to read Jira; this is what "API, not MCP" means here.

A `--dry-run` flag exists for testing the epic-resolution + ADF conversion without actually
calling `POST /issue` — use it if you need to sanity-check a draft's rendering before
committing to creating it for real.

### 7. Report
Parse the script's JSON stdout and report each created ticket:

```
NEX-#### — <summary>
  https://team-anervea.atlassian.net/browse/NEX-####
  Epic: <key> (<epic_summary as returned>) · Assignee: rhidzkhan ahmad · Status: To Do (Backlog)
```

This is the **fetched-back** confirmation (step 6's `GET`), not just an echo of what was sent —
if Jira silently dropped or altered a field, this is where it would show up.

**The browse URL is mandatory, not optional formatting.** Report the full
`https://team-anervea.atlassian.net/browse/NEX-####` link for **every** ticket created, on **every**
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
- **Assignee and the default epic are not askable** — they're fixed by this skill's contract
  (assignee always rhidzkhan ahmad; epic from the trigger, else `--epic-key NEX-754`). Don't
  prompt for either. **Never re-introduce a default epic *name*** — that is the exact shape of
  the bug in step 4's warning.
- **The epic source is the trigger command only, never the pasted story body.** An `**Epic:**`
  line inside a pasted draft is descriptive text the drafter wrote, not a selection — reading it
  as one files the ticket under the wrong epic (confirmed live: a nexus_api story that named
  "FRONTEND" in its own body because it unblocked frontend tickets got wrongly parented to the
  FRONTEND epic instead of the LAMBDA default; caught and re-parented after the fact).
- If a story is too vague to ground in real code, ask one focused question rather than
  fabricating Scope/Technical Context.
- `SP` stays 1–3; split anything larger into multiple tickets.

## Related skills

- **`/jira-scripts`** — the API layer this skill calls for every Jira write. It owns the
  credentials, the retries, the markdown→ADF conversion, the epic-ambiguity contract, and the
  fetch-back confirmation. Read it before changing anything about how tickets get created.
- `/nexus-frontend-jira-tickets` — the sibling skill for `nexus_panel_frontend` work
  (same STORY-ID format and write path, defaults to the `FRONTEND` epic instead).
- `/jira-user-story` — the general-purpose version of this (any repo, any assignee, MCP
  write path, interactive project/epic choice). This skill is a fixed-parameter specialization
  of the same STORY-ID format, pointed at one repo and one write mechanism.
- `/jira-status-move` — transition a ticket's status after creation, if it ever needs to move
  out of Backlog.
