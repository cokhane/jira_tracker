---
name: jira-scripts
description: >-
  The single Jira REST API entry point for this repo's skills — one script, three subcommands
  (create-stories, find-epic, get-issue), no MCP and no duplication. Owns credentials, auth,
  retries, epic resolution, the markdown→ADF conversion, and the fetch-back confirmation, so the
  ticket-authoring skills own only their drafting discipline and board config. Called BY
  /sethi-backend-jira-tickets, /sethi-frontend-jira-tickets, /nexus-api-jira-tickets,
  /nexus-frontend-jira-tickets and the /sethi-jira-tickets router — the caller decides which
  subcommand it needs and passes --project. Refuses to file when an epic name matches more than
  one epic, listing every match, instead of silently taking the first. Use when a skill needs to
  create, resolve, or read back a Jira issue via the direct API path, when the operator says
  "call the jira api", "resolve this epic", or "which epic does '<name>' match", or when adding a
  new board's ticket skill (add config, never a new script).
---

# Jira API scripts — one write path, one place to fix it

**Goal:** every Jira API call this repo's skills make goes through
[`scripts/jira_api.py`](scripts/jira_api.py), so board identity is an *argument* and the
mechanics have exactly one implementation.

## Why this skill exists

There used to be **four** copies of `create_ticket.py` — one each under
`nexus-api-jira-tickets`, `nexus-frontend-jira-tickets`, `sethi-backend-jira-tickets`, and
`sethi-frontend-jira-tickets`, ~280 lines apiece. They differed only in `PROJECT_KEY`, a default
epic name, and docstrings. **And they had already drifted:** the `epic_summary` field — the one
thing that makes a wrong-epic resolution *visible* before filing — existed in the two sethi copies
and was missing from both nexus copies.

That drift was not cosmetic. Verified live on 2026-08-23, with the old nexus script:

```
$ create_ticket.py --stories … --dry-run          # nexus-api, documented default epic "LAMBDA"
resolved epic -> NEX-1679                          # "Lambda Graph Integration"
epic_summary field present? False                  # …and no way to see that
```

`NEX-754` is the epic actually named `LAMBDA`. Every nexus-api ticket filed on the default path
was being parented to a different epic, invisibly, because the fix that would have surfaced it
lived in a sibling copy. **One implementation, one fix.** That is the whole argument.

## The API surface — the caller picks the call

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py <subcommand> [args]
```

| Subcommand | Jira endpoint | Use it to |
|---|---|---|
| `create-stories` | `POST /rest/api/3/issue` | create Story tickets under a resolved epic, then fetch each back |
| `find-epic` | `POST /rest/api/3/search/jql` | see **every** epic a name matches, before committing to one |
| `get-issue` | `GET /rest/api/3/issue/{key}` | read issues back in confirmation shape (key, url, summary, status, assignee, epic) |

Everything shared sits behind them: credential resolution, basic auth, a 3-attempt retry on
429/5xx, epic resolution, markdown→ADF, and the confirmation shape.

**Credentials are environment-first, and a pair is taken WHOLE from one source.**
`resolve_credentials()` reads the `ATLASSIAN_EMAIL`/`ATLASSIAN_API_TOKEN` pair, else the
`JIRA_EMAIL`/`JIRA_API_TOKEN` pair, else `jira_tracker_backend/.env`. It never combines an email
from one source with a token from another — that names an account nobody holds, and
`rules/jira-rest-api-token.md` requires one named account per run. So a freshly-minted token in
the environment takes effect for every caller of this file without editing `.env`, and every
caller acts as the same account.

### `create-stories`

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py create-stories \
  --project STH \
  --stories <path-to-stories.json> \
  --epic "Interview Platform"          # or: --epic-key STH-600
  [--assignee <accountId>] [--dry-run]
```

`--stories` is `[{"summary": "...", "body": "<the STORY-ID markdown, minus the summary line>"}, …]`.
Each story is created as issue type **Story**, assigned to the pinned team account, parented to
the resolved epic, and — **because no `customfield_10020` (Sprint) is ever set** — lands in the
Backlog rather than the active board. Every created issue is then `GET`-fetched back, so the
printed result is what Jira *has*, not what was sent.

`--dry-run` resolves the epic and renders the ADF without creating anything. Its output carries
`epic`, `epic_summary`, and `epic_status` — use it whenever the epic name is not provably unique.

### `find-epic`

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py find-epic --project STH --name frontend
```

Returns **all** matches, not the first. `summary ~` is a fuzzy, case-insensitive substring match,
so this is the only honest way to see what a name means on a given board.

### `get-issue`

```bash
python3 .claude/skills/jira-scripts/scripts/jira_api.py get-issue STH-600 STH-601
```

## The epic contract — ambiguity is an error, never a guess

The old scripts took `issues[0]` of a 5-result page with no signal that anything else matched.
This one **refuses**:

```
ERROR: "LAMBDA" matched 3 epics in NEX — refusing to guess which one you meant:
    NEX-1679  'Lambda Graph Integration'  [To Do]
    NEX-1515  'GRAPH LAMBDA'  [To Do]
    NEX-754  'LAMBDA'  [To Do]
    Re-run with --epic-key <KEY> to name the epic exactly.
```

- **`--epic <name>`** resolves only when the name matches **exactly one** epic. More than one and
  the run aborts, listing every match with its status; zero and it aborts too (never invent an epic).
- **`--epic-key <KEY>`** is the exact, unambiguous escape hatch, and it is **validated** — a key
  that is not an `Epic`, or belongs to another project, is refused rather than parented to.
- The search cap is 50, not 5, so "3 matched" cannot actually mean "3 of 40".

Known collisions, verified live on 2026-08-23:

| Board | Name | Matches |
|---|---|---|
| `STH` | `frontend` / `FRONTEND` | STH-432 `FRONTEND-INTEGRATION`, STH-419 `FRONTEND`, STH-418 `frontend`, STH-417 `frontend` |
| `STH` | `Dynamic Roles & Permissions` | STH-521 (exact) and STH-516 (longer, `Merged`) |
| `STH` | `stale` | STH-478, STH-479, STH-480 — three case variants |
| `NEX` | `LAMBDA` | NEX-1679 `Lambda Graph Integration`, NEX-1515 `GRAPH LAMBDA`, NEX-754 `LAMBDA` |
| `NEX` | `FRONTEND` | NEX-755 only — unambiguous |

**This is why no default epic is safe on either board.** A default is a name resolved without
anyone looking, which is exactly the condition the `LAMBDA` bug needed.

## Callers

| Skill | Passes |
|---|---|
| `/sethi-backend-jira-tickets` | `--project STH`, epic from the trigger |
| `/sethi-frontend-jira-tickets` | `--project STH`, epic from the trigger |
| `/nexus-api-jira-tickets` | `--project NEX`, epic from the trigger |
| `/nexus-frontend-jira-tickets` | `--project NEX`, epic from the trigger |
| `/sethi-jira-tickets` (router) | `find-epic` for its batch-wide epic gate, then delegates to a sibling |

Each caller owns its **repo grounding, its STORY-ID drafting, and its board config** — and nothing
else. None of them owns a `scripts/` directory.

## Why this is not `app/jira_client.py`

The app has its own Jira client at [app/jira_client.py](../../../jira_tracker_backend/app/jira_client.py) — deliberately
kept separate:

| | `app/jira_client.py` | `jira-scripts/scripts/jira_api.py` |
|---|---|---|
| Consumer | product code (FastAPI app) | skills, run as a CLI |
| Transport | `httpx` + pydantic `Settings` | stdlib `urllib`, own `.env` reader |
| Direction | **read only** — sprints, changelog, worklog, JQL search | **write** — creates issues |
| Runtime | the app's virtualenv | bare `python3`, no install step |

Merging them would drag the app's dependency graph and settings objects into every skill
invocation, to share an auth header. **Do not unify them.** If the app ever needs to *create*
issues, give `JiraClient` its own method — do not import this script into product code.

## Adding a new board or a new ticket skill

Add **config, not code**:

1. Write the new ticket skill with its repo path, `Repo:`/`Role:` fields, and epic policy.
2. Have it call `jira_api.py create-stories --project <KEY>`.
3. Run `find-epic` against the new board once and record its name collisions in that skill.

If a genuinely new *operation* is needed (a transition, a worklog, an issue link), add a
**subcommand here** — never a second script in the calling skill.

## Constraints

- **One copy of this script, forever.** No calling skill gets a `scripts/` directory. Four copies
  is how the `epic_summary` fix went missing from half of them.
- **`url` is part of the contract — every caller must surface it.** `create-stories` and `get-issue`
  both return a `url` field (`https://team-anervea.atlassian.net/browse/<KEY>`) in the confirmation
  shape, so the browse link is *always* available to the calling skill and there is never a reason to
  report a bare key. Callers report it for every ticket, every run, unprompted; if a caller ever
  condenses its report, the URL is the last field dropped, never the first. Do not remove `url` from
  the output shape — the calling skills' reports depend on it.
- **Never** use the `mcp__claude_ai_Atlassian_*` tools for a write in this family — the direct API
  path is the point. Reading via MCP to cross-check is fine.
- **Never invent an epic key.** Zero matches is an error, not a reason to create the epic.
- **Stdlib only.** No third-party imports — these run under a bare `python3`.
- **A Jira issue cannot be deleted** via this API or the MCP tools. A misfiled ticket is fixed by
  hand in the UI, which is why the epic gate is strict rather than advisory.
- `localId` values in the ADF come from `hash()` and so differ between runs. That is pre-existing
  and harmless (they need only be unique within one document) — don't "fix" it by seeding hashes.

## Related skills

- `/sethi-jira-tickets` — the frontend/backend classifier and router that sits above the sethi pair.
- `/sethi-backend-jira-tickets` · `/sethi-frontend-jira-tickets` · `/nexus-api-jira-tickets` ·
  `/nexus-frontend-jira-tickets` — the four callers.
- `/jira-user-story` — the general-purpose, MCP-based story author. Different write path on purpose.
- `/jira-status-move` — transitions a ticket's status (MCP path); this skill does not do transitions.