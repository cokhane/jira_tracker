---
name: create-md-report
description: >-
  Generate the combined all-boards Engineering Sprint Report (Markdown) for NEX and STH —
  an org roll-up plus a per-board closing-vs-kickoff section (shipped-this-sprint velocity, in-QA
  backlog, committed work, per-dev Team Load & Delivery, full Key Achievements, condensed
  Roadblocks). Use when the user asks to create/generate/regenerate the sprint report, the
  all-boards report, the MD report, or says "create-md-report", "sprint report", or "AllBoards
  report". Auto-picks each board's latest two sprints from the snapshot data; Claude authors the
  prose sections, so NO ANTHROPIC_API_KEY is needed.
---

# Create the All-Boards Sprint Report (Markdown)

Produces `~/Documents/sprint_report/AllBoards_Sprint_Report_<date>.md` — one combined report covering
both boards (Nexus / SETHI). Every number is computed deterministically from the
tracker DBs; Claude writes only the prose (achievements + roadblocks).

## How it works — a two-pass flow
The driver is [scripts/generate_compare_decks.py](../../../jira_tracker_backend/scripts/generate_compare_decks.py). It
auto-picks, per board, the two most recent sprints by snapshot date (`closing` = 2nd-latest,
`kickoff` = latest). Intermediate files live in the stable work dir `~/Documents/sprint_report/.work/`.

Run every step from the repo root with the project venv (`.venv/bin/python`).

### Step 1 — Pass A: dump the per-board data
```
.venv/bin/python scripts/generate_compare_decks.py --pass a
```
Writes `<KEY>_compare.md` (NEX / STH) into `~/Documents/sprint_report/.work/` and prints the
chosen `closing`/`kickoff` sprint for each board. These files contain the deterministic numbers plus
the **completed** and **blocked** ticket titles — the grounding for the narrative.

### Step 2 — Author the narrative JSON (Claude)
Read each `<KEY>_compare.md`, then write `~/Documents/sprint_report/.work/<KEY>_narrative.json` for
every board. Ground everything strictly in that board's ticket titles — never invent tickets or numbers.

Schema:
```json
{
  "achievements": ["<5-7 full-sentence bullets, grouped by theme, naming the outcome>"],
  "roadblocks": [
    {"id": "R01", "concern": "<short title>", "impact": "...", "mitigation": "...", "help_needed": "..."}
  ]
}
```
- **achievements** — 5-7 bullets, each a complete sentence compiled from the *completed ticket titles*
  (group related tickets into a theme, name the outcome, not the ticket id). These render in full.
- **roadblocks** — 3 cards (R01/R02/R03) compiled from the *blocked ticket titles*; if a board has no
  blocked tickets, infer plausible risks from carry-over volume, completion rate, and delivery
  concentration. Each needs `concern`, `impact`, `mitigation`, `help_needed`.
- Optional: if the user gives **accomplishments received for the day**, drop them (one per line) in
  `~/Documents/sprint_report/.work/<KEY>_accomplishments.txt`; Pass B prepends them to that board's
  achievements.

### Step 3 — Pass B: build the combined report
```
.venv/bin/python scripts/generate_compare_decks.py --pass b
```
Reads the narratives and writes `~/Documents/sprint_report/AllBoards_Sprint_Report_<date>.md`.

## Metric definitions (keep consistent)
Rendering lives in [app/report_render.py](../../../jira_tracker_backend/app/report_render.py); metrics in
`_compute_sprint_compare` ([app/main.py](../../../jira_tracker_backend/app/main.py)).

- **Shipped this sprint** — tickets that newly reached a *shipped* status (Merged / Deployment / Done)
  during the closing sprint, measured by diffing the closing snapshot against the prior sprint's. True
  weekly velocity — NOT the cumulative count still tagged to the board.
- **In QA at close** — dev-done but not yet shipped on the closing board (waiting in QA Testing).
- **Committed** — the real kickoff commitment = carry-over (unfinished, pulled forward) + new work.
- **Team Load & Delivery** (per board, closing + kickoff) — one row per roster developer:
  Assigned / Completed / Incomplete (cumulative board-state credited to them) · → Code Review / → QA
  Testing / → Merged / → Other (decompose Assigned by the dev's *last action*; they sum to Assigned) ·
  Delivered (tickets pushed out of In Progress *this sprint*).
- **Dev-done** = QA Testing, Merged, Deployment, Done. **Shipped** = Merged, Deployment, Done.
  Configured via `report_done_statuses` / `report_shipped_statuses` in `projects.yaml`.

## Report structure
Overview table (all boards) → per-board sections (header, Team Load & Delivery for closing then
kickoff, full Key Achievements, condensed Roadblocks as `**concern** — impact`) → closing note
`Committed = Carry-over + New`.

**No Developer KPI Scorecard.** This report deliberately carries no per-developer KPI/rating table
(Target / Done / Delivery % / Reopened / Blocked / WIP / Rating). The KPI scorecard is a *separate*
deliverable rendered on demand by `render_dev_kpi_markdown` (the `/reports/dev-kpi.md` body) — do not
add it back into the combined report.

## Prerequisites & notes
- The tracker DBs under `data/` must be synced first (each board needs ≥ 2 sprints of snapshots).
- Rosters come from `projects.yaml` (`report_assignees` per board) — no `assignees` override needed.
- Save location is fixed at `~/Documents/sprint_report/` (per team convention).
- A PPTX variant of the same report exists via
  [scripts/build_allboards_deck.py](../../../jira_tracker_backend/scripts/build_allboards_deck.py) (reuses the same
  narratives) — only build it if the user explicitly wants slides.

## Verify
Open the generated `.md` and confirm each board shows non-zero Shipped/Committed and populated
Team Load & Delivery tables, and that the Overview Total row reconciles
(`Committed == Carry-over + New`).
