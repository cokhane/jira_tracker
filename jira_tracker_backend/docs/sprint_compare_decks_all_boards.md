# Generate Sprint-Compare Decks for NEX, AKV2, STH

## Context
The user has one existing deck — `~/Documents/sprint_report/NEX_Sprint2_vs_Sprint3.pptx` (11 slides,
Alfa-Kinetic theme) — produced by the tracker's existing pipeline. They want the **same deck for all
three boards** (NEXUS, AlfaKinetic-V2, SETHI), each comparing its **latest sprint vs the previous
week's sprint**, chosen automatically from the snapshot dates (today = 2026-07-14):

| Board | Closing (last week) | Kickoff (latest) |
|---|---|---|
| NEX  | NEX Sprint 3  | NEX Sprint 4  |
| AKV2 | AKV2 Sprint 2 | AKV2 Sprint 3 |
| STH  | STH Sprint 1  | STH Sprint 2  |

The generation machinery already exists and works — this task is mostly **driving it for 3 boards**,
plus two small adjustments (author the narrative without an API key; supply the AKV2/STH rosters).

## What already exists (reuse, do not rebuild)
- `_compute_sprint_compare(db, cfg, closing, kickoff, assignees)` → `SprintCompareOut`
  ([app/main.py:987](../app/main.py#L987)). Board-wide slides count every assignee; team / breakdown /
  delivery slides count only the roster.
- `build_compare_pptx(c, api_key, model)` → 11-slide `.pptx` bytes
  ([app/pptx_report.py:567](../app/pptx_report.py#L567)).
- `render_markdown(c)` → deterministic data summary incl. completed & blocked ticket titles
  ([app/pptx_report.py:68](../app/pptx_report.py#L68)) — the grounding for the narrative.
- `resolve_cfg(project)` + `get_engine(key, db_file)` to get a cfg + DB session outside FastAPI
  ([app/database.py:116](../app/database.py#L116), used by `get_db`/`get_cfg`).

## Constraints discovered
- **No `ANTHROPIC_API_KEY`** is set (not in `.env` or shell). Slides 9 (Key Achievements) and 10
  (Roadblocks) are the only LLM-authored parts. Decision: **Claude authors this prose directly** from
  each board's ticket data — no API key / API call. Requires a tiny signature change to
  `build_compare_pptx` (accept an optional pre-authored `narrative`).
- **AKV2 & STH rosters are empty** in `projects.yaml`; without a roster the team/delivery tables come
  out blank. Rosters are now known (below).
- **STH has 0 status transitions** synced → its Developer-Delivery funnel (slides 7–8) will be empty
  regardless of roster; team-performance still works via the current-assignee fallback in
  `_compute_sprint_compare`'s `attribute()`. This is a data limitation to note, not a bug.
- Every figure/table is rendered deterministically from the compare data; only the two narrative
  slides are prose. Numbers stay faithful.

## Rosters (exact DB assignee strings — verified against each board)
- **NEX**: `Dan Denver De Leon,Dan Rudolf,Deinielle Cruz,Pamela Denisse Sacdalan,Sidney Buenaventura,Allen Mathew Cordero,Shane Michael Singwa`
- **AKV2**: `Dan Rudolf,Deinielle Cruz,Sidney Buenaventura`
- **STH**: `John Mandawe,Muskan Dawar`  ⚠ user wrote "john carlo"; only John on the board is
  **John Mandawe** — assuming that mapping (verify with user during execution).

## Approach

### 1. Persist the rosters (durable) — `projects.yaml`
Update `report_assignees` for all three blocks so the config drives the reports going forward:
- NEX: add `Sidney Buenaventura` to the existing list.
- AKV2: set to the 3-name roster above.
- STH: set to the 2-name roster above.
(Leaves `report_done_statuses` at the default `Done,Deployment,Merged` — matches AKV2's Merged/Deployment
and STH's Deployment.)

### 2. Small code change — `app/pptx_report.py`
Change `build_compare_pptx(c, api_key, model)` →
`build_compare_pptx(c, api_key, model, narrative=None)`: if `narrative` is passed, use it and skip the
`_author_narrative(...)` LLM call; otherwise behave exactly as today. `narrative` shape is unchanged:
`{"achievements": [str,...], "roadblocks": [{id, concern, impact, mitigation, help_needed}, ...]}`.
No other rendering code changes.

### 3. New generator script — `scripts/generate_compare_decks.py`
A standalone script (run with the repo `.venv`) that, for each of `NEX, AKV2, STH`:
1. `cfg = resolve_cfg(key)`; open a session via `get_engine(cfg.key, <db_file>)`.
2. Auto-pick sprints: the two most recent distinct `sprint_name`s in `daily_snapshots`
   ordered by `MAX(snapshot_date)` → `closing` = 2nd-latest, `kickoff` = latest. (Confirms the table
   above without hardcoding — honors "consider the date".)
3. `c = _compute_sprint_compare(db, cfg, closing, kickoff, assignees=None)` (roster now comes from
   config).
4. Run in **two passes** so Claude can author the prose:
   - **Pass A**: write `render_markdown(c)` for each board to the scratchpad
     (`.../scratchpad/<key>_compare.md`). Claude reads all three.
   - Claude authors a `narrative` JSON per board from the completed/blocked ticket titles
     (5–7 achievement bullets grouped by theme; 3 roadblock cards), **weaving in any
     "accomplishments received for the day" the user provides** for that board. Saved as
     `.../scratchpad/<key>_narrative.json`.
   - **Pass B**: `build_compare_pptx(c, "", cfg.report_llm_model, narrative=<loaded json>)` and save.
5. Save to `~/Documents/sprint_report/{KEY}_{closing}_vs_{kickoff}.pptx`
   (spaces → `_`, e.g. `NEX_Sprint3_vs_Sprint4.pptx`; normalize the sprint labels when building the
   filename).

The script accepts an optional per-board accomplishments notes input (path or inline) so the user can
"input the accomplishments received for this day"; those notes are merged into that board's
achievements bullets ahead of the ticket-derived ones.

## Critical files
- `projects.yaml` — roster updates (step 1).
- `app/pptx_report.py` — optional `narrative` param on `build_compare_pptx` (step 2).
- `scripts/generate_compare_decks.py` — **new** driver (step 3).
- Reads only: `app/main.py` (`_compute_sprint_compare`), `app/database.py`, `app/projects.py`,
  `app/schemas.py`.

## Verification
1. Run the generator; confirm it prints the auto-selected sprint pair per board (matches the table).
2. For each `.pptx` in `~/Documents/sprint_report/`: open with `python-pptx`, assert **11 slides**.
3. Spot-check populated data (no all-zero decks): NEX & AKV2 team-performance and delivery tables
   have non-zero rows; STH team table populated (delivery expected empty — transitions not synced).
4. Compare the NEX deck's structure/theme against the existing `NEX_Sprint2_vs_Sprint3.pptx`
   (same 11-slide layout, colors, stat cards).
5. Confirm the "john carlo → John Mandawe" mapping and any day-of accomplishments with the user
   before finalizing STH.
