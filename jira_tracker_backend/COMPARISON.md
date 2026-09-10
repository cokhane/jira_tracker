# Sprint Closure & Kickoff — Two-Board Comparison

This document analyses the reference deck (the "Alfa Kinetic" PDF) and specifies
exactly how the Jira Tracker builds the same report by **comparing two sprint boards**.

## What the reference deck is

A 9-slide "Sprint Closure + Kickoff" deck that puts a **closing** sprint (what just
finished) next to a **kickoff** sprint (the new one) and reports throughput, carry-over,
new work, per-project and per-type breakdowns, team performance, and narrative
(achievements + roadblocks).

> The reference PDF was made for a multi-client board, so it labels the grouping
> dimension **"Domain"** (Ipsen, Menarini, …). Our board is a single project, so we
> label it **"Project"** and slide 3 shows a single **Nexus** card. The PDF's numbers
> are template placeholders — our figures come live from the snapshots.

## What "a board" is here

A board = a sprint's **daily snapshot** (`daily_snapshots`), which stores one row per
issue per day with `assignee`, `status`, `status_category`, `issue_type`, `epic_name`,
and the `sprint_name/sprint_start/sprint_end` active at capture time.

- **Closing board** = the **latest** snapshot date whose `sprint_name` = the closing sprint.
- **Kickoff board** = the **latest** snapshot date whose `sprint_name` = the kickoff sprint.

Both boards are filtered to the **report roster** before any counting.

## How the two boards are compared

| Deck element | Computation |
|---|---|
| Completed (closing) | closing rows where `_is_done` (status_category=Done, or status ∈ `REPORT_DONE_STATUSES`, default {Done, Deployment, **Merged**}) |
| Carry-over | issue_keys **incomplete** in closing **and present** in kickoff (`closing_incomplete ∩ kickoff_keys`) |
| New work (kickoff) | issue_keys in kickoff **not** in closing (`kickoff_keys − closing_keys`) |
| Completed by project | **completed** closing rows grouped by project, % of the completed count (mirrors the PDF's "completed work by domain") |
| Projects covered | distinct Jira project among the completed rows (only **Nexus / NEX** in our data → 1) |
| Committed by type (kickoff) | kickoff rows bucketed Stories / Tasks / Bugs / Other |
| Team performance (closing) | per-developer total / completed / % of sprint, sorted — **roster only, history-attributed** |
| Ticket breakdown | per-developer assigned / completed / incomplete + roster totals + completion rate — **roster only, history-attributed** |

Sprint-wide rows (completed, carry-over, new work, completed-by-project, committed-by-type)
count **every assignee** on the NEX board; the two team rows count only the roster.

### Team attribution (who worked the ticket)

The team slides do **not** use the ticket's current assignee. Each ticket is credited to
the **latest roster developer who moved it**, from the Jira changelog (`status_transitions.moved_by`,
newest `changed_at` wins), excluding bots (`REPORT_EXCLUDE_MOVERS`). If no roster developer
appears in a ticket's history, it falls back to the current assignee; if neither is a roster
member, the ticket is left unattributed (it still counts in the sprint-wide overview).

> **Coverage:** changelog history is populated by the **full sync** (`POST /api/sync?full=true`),
> not the daily snapshot. Tickets without transition rows use the assignee fallback, so run a
> full sync to make attribution complete.

The project of an issue is derived from its key prefix (`NEX-123` → `NEX` → "Nexus").

## Scoping: sprint-wide vs. team

- **Sprint-wide numbers** (overview stats, carry-over, new-work, completed-by-project,
  committed-by-type, completion rate) count **every assignee** on the board, scoped to
  the configured project (`JIRA_PROJECT`, i.e. NEX / Nexus) so stray non-NEX tickets
  don't leak in.
- **Per-developer slides** (team performance, ticket breakdown) count only the
  **report roster** below.

> ⚠️ Because the overview counts everyone, it's only as clean as the closing snapshot.
> Snapshots captured before the roster/prune fix (e.g. the 2026-06-30 Sprint 1 board,
> ~700 rows) carry old-sprint leakage and will inflate the overview. Use a freshly
> captured closing snapshot for accurate whole-team totals.

## Roster scoping (team slides)

Team performance and ticket breakdown count a fixed **report roster** (`REPORT_ASSIGNEES`
in `.env`, independent of the sync-time `MONITOR_ASSIGNEES`), default:

`Dan Denver De Leon, Dan Rudolf ("Dan Perez"), Deinielle Cruz, Allen Mathew Cordero,
Shane Michael Singwa, Sidney Buenaventura`

> **Sidney Buenaventura** has no rows in the current snapshots. To make them appear:
> add the exact Jira `displayName` to `MONITOR_ASSIGNEES`, restart the backend, and
> take a fresh snapshot — past snapshots cannot gain their rows (Jira only returns
> today's board).

## The 9 slides (1:1 with the reference PDF)

1. **Overview** — title + 4 stat cards: Completed · Carry-over · New work · Projects.
2. **Closure at a glance** — the three totals + projects covered + velocity note.
3. **Completed work by project** — Nexus card(s) with count + %.
4. **Committed work** — kickoff Stories / Tasks / Bugs / Other.
5. **Team performance** — top-contributor banner + engineer table.
6. **Ticket breakdown** — per-member Assigned / Completed / Incomplete + totals + completion rate.
7. **Key achievements** — stats + the **completed ticket titles** (key — title — developer,
   roster-attributed); the LLM/converting context compiles these into 5–7 themed bullets.
8. **Roadblocks and next steps** — the **blocked tickets** (status = Blocked; key — title —
   owner) compiled into R01–R03 roadblock cards (impact / mitigation / help needed) by the
   LLM/converting context. Lists all blocked tickets on the board (owner = credited roster dev,
   else current assignee).
9. **Ending** — Engineering Leadership / distribution / generated-from-Jira footer.

## How to generate it

Three outputs, in order of what you'll reach for:

- **Markdown deck (no API key — recommended):** UI → pick Closing + Kickoff sprints →
  **📝 Markdown**, or `GET /api/reports/sprint-compare.md?closing=…&kickoff=…`. Produces
  the full 9-slide content (all numbers/tables) plus a header instruction, so you can
  paste it into any Claude context (or a slides skill) to build the `.pptx` there — the
  backend never calls an API.
- **HTML deck:** UI → **📄 HTML deck** (opens styled; print → Save as PDF).
- **Data (JSON):** `GET /api/reports/sprint-compare?closing=<sprint>&kickoff=<sprint>[&assignees=csv]`.
### The Markdown workflow (no API key)

`render_deck_markdown(compare)` (in `app/report_render.py`) emits one board's slide content as
Markdown for pasting into another context. The all-boards deliverable is a single combined
Markdown report built by `render_combined_markdown(entries)` (org roll-up + a per-board section
each), generated via `scripts/generate_compare_decks.py` — the two prose sections (achievements,
roadblocks) come from pre-authored narrative JSONs, so no `ANTHROPIC_API_KEY` is required.

## Key source files

- `app/main.py` — `_compute_sprint_compare`, `/api/reports/sprint-compare`, `…/sprint-compare.md`
- `app/report_render.py` — `render_combined_markdown` / `render_deck_markdown` (sprint-compare MD),
  plus the weekly-QA python-pptx deck
- `app/schemas.py` — `SprintCompareOut`
- `app/config.py` — `report_assignees`, `anthropic_api_key`, `report_llm_model`
- Frontend: `src/api.js`, `src/report.js` (`buildCompareReportHtml`), `src/App.jsx`
