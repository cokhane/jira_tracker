# Feature: Daily Board Snapshots & Sprint Comparison

*Jira Tracker — feature reference. Last verified against live Jira on 2026-07-03.*

## What it does

The Jira Tracker turns the live **NEX / Nexus Project** board (`team-anervea.atlassian.net`)
into a **date-stamped history** you can browse day by day and compare sprint over sprint.

One button — **⟳ Sync today's board** — pulls the current sprint from Jira, refreshes the
local copy, and freezes a picture of the board for that day. Every day you sync becomes an
immutable, browsable snapshot. Because each day is stored separately, the tool can answer
"what did the board look like on the 30th?" and "what changed between Sprint 1 and Sprint 2?"
without any Jira history calls.

- **Manual sync** — no webhooks, no polling. You trigger it.
- **Current sprint only** — never the whole backlog.
- **Monitored people only** — a fixed allow-list of the team being tracked.
- **Local + private** — everything lives in `jira_tracker.db` (SQLite); the Jira token
  in `.env` is never committed.

## The two things it produces

| Output | What it is | Where |
|---|---|---|
| **Daily board view** | The board exactly as it looked on a chosen date, grouped by column, filterable by assignee. | React app → `GET /api/snapshots/{date}` |
| **Sprint closure/kickoff deck** | A 9-slide comparison of a closing sprint vs a kickoff sprint (completed / carry-over / new work, by project, by type, per developer). | `GET /api/reports/sprint-compare[.md|.pptx]` |

The Markdown deck (`alfa_kinetic_<closing>_vs_<kickoff>.md`) is the no-API-key path — it
renders the full deck content as text to paste into a slides step. The `.pptx` path has
Claude author the narrative and builds the file with `python-pptx` (needs `ANTHROPIC_API_KEY`).

## How a sync works

Clicking the button calls `POST /api/snapshot` → `sync_and_snapshot()`, which runs two steps:

1. **Refresh current state** (`run_sync`, changelog skipped so it's fast, ~15s)
   - JQL: `project = NEX AND sprint in openSprints()`
   - Keep only the **monitored allow-list**; drop everyone else.
   - Upsert kept tickets into the `issues` table.
   - **Prune**: delete any `issues` row not in this fresh pull — so old-sprint leftovers
     and people who left the roster can't leak into future snapshots.
2. **Freeze today's picture** (`capture_snapshot`)
   - Copy every kept `issues` row into `daily_snapshots`, stamped with today's date and the
     active sprint's name/start/end.
   - Re-running the same day **replaces** that day's block (idempotent per day).

```
Jira (open sprint) ──pull──▶ filter to allow-list ──▶ upsert + prune `issues`
                                                          │
                                                          ▼
                                       copy → `daily_snapshots` (dated, append-only)
```

## The rules that keep it clean

These are enforced in code (`app/sync.py`, `app/config.py`) and are the core of the feature:

- **Allow-list (`MONITOR_ASSIGNEES` in `.env`)** — only these people are ever stored.
  As of 2026-07-02 the roster is **8 people**: Dan Denver De Leon, Dan Rudolf, Deinielle Cruz,
  Shane Michael Singwa, Allen Mathew Cordero, Jonas Ballesteros, Renzo.Manzano,
  Vermidio Pollisco Jr. Names must match Jira `displayName` exactly (note the dotted
  `Renzo.Manzano`). The allow-list takes precedence over `EXCLUDE_ASSIGNEES`.
- **Pruning** — a full current-sprint pull is authoritative; anything not in it is deleted
  from `issues`. Without this, `daily_snapshots` would accumulate stale tickets forever.
- **Current sprint only** (`CURRENT_SPRINT_ONLY=true`) — the JQL scopes to `openSprints()`.
- **Past-day guard** — resyncing a *past* date overwrites that day's saved board with today's
  live board, so it requires `force=true` (the UI confirms first; the API returns `409`).

> **Operational gotcha:** `get_settings()` is `@lru_cache`d, so a running backend keeps the
> old roster until restarted. After editing `.env`, restart the backend for changes to apply.

## Data model

| Table | Purpose |
|---|---|
| `issues` | Current state of each tracked ticket. Overwritten (upsert) and pruned every pull. |
| `daily_snapshots` | One row per ticket **per day** — the saved board picture. Append-only history. PK `(snapshot_date, issue_key)`. |
| `sync_logs` | Audit row per pull (fetched / created / updated counts, status, errors). |
| `status_transitions` | From the earlier changelog approach; still feeds the sprint-compare developer attribution, otherwise legacy. |

`issues` = "right now"; `daily_snapshots` = "on this date." The second is the time machine
that makes day-by-day browsing and sprint comparison possible.

## API surface (this feature)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/snapshot` | Sync button: pull current sprint, save today's snapshot. `?target=` for a specific day, `?force=true` to overwrite a past day. |
| GET | `/api/snapshots` | Dates that have a snapshot, newest first (with sprint label). Powers the date picker. |
| GET | `/api/snapshots/{date}?assignee=` | The board as it looked on that date, grouped by column. |
| GET | `/api/reports/sprint` | Aggregate one day's snapshot into a single-sprint report (totals, domains, types, team). |
| GET | `/api/reports/sprint-compare` | Closing vs kickoff comparison as JSON. Params: `closing`, `kickoff`, `assignees?`. |
| GET | `/api/reports/sprint-compare.md` | Same comparison as a 9-slide Markdown deck (no key). |
| GET | `/api/reports/sprint-compare.pptx` | Same comparison as a `.pptx` (needs `ANTHROPIC_API_KEY`; `503` without). |

## Counting model (how numbers are decided)

- **Distinct tickets, not events** — a ticket that bounces into a column several times in a
  bucket counts once.
- **Done = reaching `Done` or `Deployment`** (the terminal columns).
- **Carry-over** = tickets incomplete at the close of the closing sprint that reappear in the
  kickoff sprint. **New work** = kickoff tickets that weren't in the closing sprint at all.
- **Sprint-wide totals** count every assignee on the board; **per-developer** slides credit
  each ticket to the latest roster developer who moved it (from changelog history, falling
  back to the current assignee).
- **Snapshot caveat:** snapshots compare *end-of-day* states. An intra-day round trip
  (`In Progress → QA → In Progress`) shows only where the ticket landed.

## Verified behavior (2026-07-03)

A live cross-check against Jira confirmed the sync is healthy:

- `openSprints()` → 473 raw issues → 117 non-monitored dropped → **356 kept** for the 8-person roster.
- **0 Done** tickets in the open sprint (work sits in Merged / QA Testing).
- **Exactly one** open sprint (`NEX Sprint 2`), so snapshots are labeled correctly.
- DB keys == live sprint keys (0 stale, 0 missing) — pruning is working.

## Running it

```bash
# backend
cd jira_tracker && uvicorn app.main:app --reload --port 8000

# frontend
cd jira_tracker_frontend && npm run dev -- --port 5174
```

Open the frontend → **Sync today's board** → pick a date and (optionally) an assignee.

## Related docs

- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — layered design, DB schema diagrams, comparison SQL.
- [`README.md`](../README.md) — setup, token, full API reference.
- [`COMPARISON.md`](../COMPARISON.md) — the 9-slide deck spec.
