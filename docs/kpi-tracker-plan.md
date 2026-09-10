# Developer KPI Tracker — Plan & Spec

_Status: **BUILT as a view** (2026-08-27) — live `GET /reports/dev-kpi` and a **KPI Tracker**
side-panel route. Deliberately **NOT in any report**: an earlier build put a KPI table into the
generated report and it was removed on purpose (see the tombstone in `app/report_render.py`), so this
rebuild is the view only. A per-developer rating is a conversation to have with a developer, not a
slide to hand around._
_Owner: rhidzkhan.ahmad@anervea.ai_

> **The view now has TWO modes** (2026-09-01). The original per-sprint scorecard, and an
> **all-sprints** mode — `GET /reports/dev-kpi/overall` — that answers "what has this developer done
> over the whole run?" with one TOTAL row per developer, openable into the per-sprint rows it was
> summed from. See §9. The `This sprint | All sprints` switch lives in the view; picking all-sprints
> hides the sprint tabs, because a sprint selector that changes nothing is worse than no selector.

> **Target comes from the Capacity Tracker, not from the workbook.** §4 below predates
> `app/capacity_store.py`. The grid is now the team's live plan — they type actuals into it and every
> later capacity rolls forward — so `_sprint_targets` reads `SprintCapacity` for the sprint containing
> the sprint start, and the workbook only ever *seeds* that grid. A developer the grid doesn't cover
> falls back to `dev_target_default` (10) and is flagged `target_is_default`, shown as an **ASSUMED**
> badge, so Delivery % against a guess is never mistaken for Delivery % against a plan.
> **As of 2026-08-27 that is 7 of NEX's 10 roster developers** — only Dan Denver, Deinielle and Dan
> Rudolf have cells. Add the rest via the Capacity Tracker to make those Targets real.

**Backend:** `app/config.py` (`dev_target_default`, `capacity_workbook_path`), `app/schemas.py`
(`DevKpiRow`/`DevKpiOut`), `app/main.py` (`_rating`, `_sprint_targets`, `_qa_and_block_counts`,
`_wip_counts`, `_compute_dev_kpi`, `GET /reports/dev-kpi`; `_qa_send_back`/`_entered_blocked`
extracted so the scorecard and the KPI can't drift on what a send-back IS). **Frontend:**
`src/components/DevKpi.jsx`, `src/api.js` (`devKpi`), `src/App.jsx` (nav entry + `SPRINT_VIEWS`),
`src/index.css`.

## 1. Goal

Give engineering leadership a per-developer sprint **KPI scorecard** — the columns from the
original mockup — surfaced as its own **"KPI Tracker"** route in the Sprint Tracker app, and added
to the generated sprint report:

```
Dev | Target | Done | Delivery % | Reopened | Reopen % | Blocked | WIP | Rating
```

"Rating" is a new composite metric designed here (see §3).

## 2. Current status — what exists today

- **Shipped**, per the status note above: the endpoint, the route, and the scorecard, on both boards.
- **UI draft (interactive prototype):** [`docs/kpi-tracker-prototype.html`](./kpi-tracker-prototype.html)
  — a self-contained page reading **real, synced data** (baked in as a JS `DATA` object). It was the
  visual target; the shipped view follows it apart from the charts (see below). Kept for reference —
  it does not update, so the app is the source of truth from here.
- **Charts: not recharts.** The prototype drew Delivery % and Rating as chart widgets. `recharts` is
  in `package.json` but **nothing in `src/` has ever imported it** — every chart in this app is a CSS
  bar (`.stats-table .bar`). The view follows the house idiom: an inline delivery bar per row and
  ★1–5 in the Rating column. Swapping in real recharts charts is a live option, just not a silent one.

## 3. Metric definitions (authoritative)

| Column | Definition | Source metric |
|---|---|---|
| **Target** | The developer's planned capacity for that sprint | Rolling capacity sheet (§4) |
| **Done** | Tickets the dev delivered this sprint — moved out of *In Progress*, counted once at the **furthest stage reached** (Code Review→QA→**Merged**→Deployment→Done) | `_compute_dev_delivery` / `sprint-compare` `closing.delivery[].total` |
| **Delivery %** | `Done / Target × 100` | derived |
| **Reopened** | QA send-backs — tickets moved `QA Testing → not Done` | `scorecard.sent_back_by_qa` |
| **Reopen %** | `Reopened / Done × 100` (0 when Done = 0) | derived |
| **Blocked** | Tickets moved to `Blocked` in the sprint | `scorecard.to_blocked` |
| **WIP** | Tickets in `In Progress` at the sprint's closing snapshot (the `asOf` date) | daily snapshot |
| **Rating** | Weighted composite → ⭐1–5 (below) | derived, server-side |

### Rating formula (the new KPI)

A 0–100 composite mapped to ⭐1–5 — rewards delivering **and** delivering cleanly, not raw volume:

```
D (Delivery, 0.50) = min(Done / Target, 1)            # capped so 300% ≠ runaway
Q (Quality,  0.35) = 1 − min(Reopened / Done, 1)      # 0 when Done = 0
F (Flow,     0.15) = 1 − min(Blocked / max(Done,1), 1)

rating = 100 × (0.50·D + 0.35·Q + 0.15·F)
stars  = 5 if ≥85, 4 if ≥70, 3 if ≥50, 2 if ≥30, else 1
```

Weights/thresholds are intentionally tunable — keep them as named constants.

## 4. Target from the rolling capacity sheet

Target comes from `Rolling_Sprint_Capacity.xlsx` (repo root). Two gotchas, already solved in the
prototype's data-gather and must be reproduced in the backend:

1. **Formula cells read as `None`** (`data_only=True`) because the workbook was generated by openpyxl
   and never opened in Excel. Reconstruct each sprint's capacity by cascading from Sprint-1 (literal)
   using the typed actuals: `cap[n] = ROUND_HALF_AWAY(mean(cap[n-1], actual[n-1]))`. Use
   round-half-**away-from-zero** (`math.floor(x+0.5)`), NOT Python's `round()` (half-to-even → wrong).
2. **Name mismatch** — the sheet uses short names; map them to Jira full names:
   `Sidney→Sidney Buenaventura, Denille→Deinielle Cruz, Dan→Dan Denver De Leon, Rudolf→Dan Rudolf,`
   `Allen→Allen Mathew Cordero, Shane→Shane Michael Singwa, PAM→Pamela Denisse Sacdalan, Muscan→Muskan Dawar`.
   Each Jira sprint is matched to the nearest capacity-week by start date. Unmatched dev → default (10).

## 5. Implementation — as built

### Backend (`jira_tracker_backend`)
1. **Schemas** (`app/schemas.py`): `DevKpiRow` (+ `target_is_default`) and `DevKpiOut`.
   `SprintCompareSprint` is deliberately left alone — the report does not carry KPI rows.
2. **Compute** (`app/main.py`), all beside `_compute_dev_delivery` and reusing it:
   - `_rating(...)` — the §3 formula, weights and star cut-offs as named constants.
   - `_sprint_targets(...)` — reads the `SprintCapacity` grid for `cfg.sprint_for(sprint_start)[0]`,
     the same placement rule `capacity_store` builds the grid with, so the two views agree by
     construction. Returns `None` for an uncovered developer; the caller substitutes the default
     and sets `target_is_default`.
   - `_qa_and_block_counts(...)` — one grouped query over the sprint window, attributed to
     `assignee_at` (QA does the send-back; anyone can block — the mover is the wrong person).
   - `_wip_counts(...)` — In Progress on the closing board, by current assignee.
   - `_compute_dev_kpi(...)` + `GET /reports/dev-kpi?sprint=&assignees=`; `sprint` defaults to
     `_newest_sprint`, the window and roster come from `_load_sprint`.
3. **Shared predicates**: `_qa_send_back()` / `_entered_blocked()` extracted out of `scorecard()` and
   used by both, so "reopened" cannot come to mean two different things on two surfaces.

### Frontend (`jira_tracker_frontend`)
1. `src/api.js`: `devKpi(sprint, assignees)`.
2. `src/components/DevKpi.jsx`: team tiles + the 9-column scorecard + a TEAM footer and a legend.
   All arithmetic bar the footer is server-side.
3. `src/App.jsx`: `KPI Tracker` nav entry and the `kpi` route; `SPRINT_VIEWS` now drives which routes
   keep the sprint tabs on screen, so the KPI view reuses the board switcher and sprint tabs.
4. `src/index.css`: `.kpi-*` block, alongside the Capacity Tracker styles it borrows from.

## 6. Decisions & caveats locked in the draft

- **Done = delivery incl. Merged.** The boards ship via a `Merged` status; the simple `scorecard.to_done`
  (only Done/Deployment) undercounts, so Done uses the delivery funnel. (If leadership prefers "closed
  only", swap to `to_done` — but then Merged work looks undelivered.)
- **Sprint window & "as of".** Movement metrics are computed over the sprint's week; WIP is the
  `In Progress` count on the sprint's latest snapshot (`asOf`). Current sprints read as of the sync day.
- **Current sprints are sparse by design.** A sprint that kicked off "yesterday" shows little Done —
  that's real, not a gap. The just-closed sprint is one click away.
- **Two real outliers to investigate (not bugs):** in some sprints a single dev shows very high WIP
  (Shane, 24–26 In Progress on NEX Sprint 9/10) or high reopens — straight from Jira; may be an
  attribution quirk worth tuning when the metrics are finalized.
- **Targets are rolling** — each sprint reads that sprint's capacity cell, so Delivery % is judged
  against the plan for that sprint, and editing an actual in the Capacity Tracker moves it.

## 7. Verifying it

Backend running (`uvicorn app.main:app --port 8000`), Jira configured, boards synced.

```bash
curl -X POST http://localhost:8000/api/snapshot-all           # sync + snapshot, ~3–4 min
curl "http://localhost:8000/api/NEX/reports/dev-kpi"          # current sprint
curl "http://localhost:8000/api/NEX/reports/dev-kpi?sprint=NEX%20Sprint%209"
```

Two invariants worth re-checking after any change to the delivery funnel or the capacity grid:

- **Done == the sprint-compare delivery total** for the same sprint and developer —
  `/reports/sprint-compare?closing=<sprint>` → `closing.delivery[].total`. They share
  `_compute_dev_delivery`, so a divergence means the reuse broke. Verified on both boards.
- **Target == the Capacity Tracker cell** for the same sprint — `/capacity` → the developer's cell
  at that sprint number — or `target_is_default` is true. Verified on both boards.

Rosters (`report_assignees` in `projects.yaml`): NEX 10 devs · STH 3. Both boards excluded
`rhidzkhan ahmad` from the roster on purpose — see the comments in `projects.yaml`.

## 8. Open questions for later

- Scheduled auto-sync (e.g. every morning) vs manual "Sync all boards"?
- ~~Should the scorecard support a **custom date range** in addition to per-sprint?~~ — answered
  in part by §9: the range on offer is *all sprints*, not an arbitrary from/to. A free date range
  would have to redefine Target (capacity is per sprint, so a half-sprint has no plan), which is why
  the sprint stays the atom and the all-sprints view sums whole sprints only.
- Confirm the Rating weights (50/35/15) and star thresholds with the team.
- **Should a developer who delivered nothing score 15/100?** With Done = 0 the flow term still pays
  out its full 0.15 (nothing delivered means nothing blocked). It buckets to ★1 either way, so it
  changes no verdict — but the floor is an artifact of the formula, not a judgement.
- **Fill in the missing capacity cells** so NEX Targets stop being the default 10 for 7 of 10 devs.

## 9. All-sprints mode (added 2026-09-01)

`GET /api/{board}/reports/dev-kpi/overall` → `DevKpiOverallOut`. One TOTAL row per roster developer
across **every sprint the board has a snapshot for**, each row carrying the per-sprint rows it was
built from in `history` (so a total can be opened up and traced, and the drill-down needs no second
request). Built by calling `_compute_dev_kpi` once per sprint and aggregating, deliberately **not**
by a parallel set of queries: an all-sprints number that disagreed with the sprint it came from would
discredit both. ~0.9s for NEX's 11 sprints.

**Sprint order** comes from `_sprint_names`, which orders by each sprint's latest snapshot date —
sprint *names* don't sort chronologically ("Sprint 10" lands before "Sprint 9").

### How each column aggregates

| Column | Rule |
|---|---|
| Target / Done / Reopened / Blocked | plain sums of the counted sprints |
| Delivery % / Reopen % | recomputed **from the totals**, never averaged — averaging percentages would weigh a 2-ticket sprint the same as a 20-ticket one |
| **WIP** | the **newest** counted sprint's value, not a sum. It's a point-in-time count of what's on someone's plate; yesterday's plate plus today's plate is not a quantity |
| **Rating** | the **mean of the per-sprint ratings**, *not* `_rating` re-run on the totals |
| `target_is_default` | true if **at least one** counted sprint had no Capacity Tracker cell |

**Why the rating is a mean.** The formula's whole point is that delivery caps at target *per
sprint*, so volume alone can't buy a score. Re-running it on the totals launders exactly that: four
0/10 sprints and one 40/10 sprint would read as a flawless 100%. The mean keeps every sprint's cap,
and it makes the total the plain average of the history rows shown underneath it — visibly checkable.

### Which sprints count for a developer (`_has_footprint`)

The roster is board-level config, not per-sprint, so every developer otherwise gets a row for every
sprint — including sprints before they joined. Averaging those in scores people for time they weren't
here. So a sprint counts if **either**:

- it has a **real Capacity Tracker cell** for them — a planned sprint that delivered nothing is a
  genuine zero, and hiding it would be the more flattering lie; **or**
- they **touched it** — delivered, were sent back, were blocked, or held work in progress.

An unplanned, zero-footprint sprint is dropped, which is why the per-row sprint count differs (NEX:
11 for the long-tenured, 3 for Anshul Pandey). A developer with no counted sprint at all still gets a
row, showing `no data` rather than a fabricated zero.

### The in-flight sprint

The newest sprint is usually **still running**, so it enters the average as a part-delivered sprint
and holds every rating down a little (NEX Sprint 11 cost Dan Denver ~7 points). It is **counted** —
"every sprint with data" is the contract — but the view marks that row `IN FLIGHT` and says so in the
sub-line, rather than quietly excluding it or quietly letting it distort the number. If the team would
rather judge on finished sprints only, that's a one-line filter in `_compute_dev_kpi_overall`, not a
redesign.

### Verifying it

```bash
curl "http://localhost:8000/api/NEX/reports/dev-kpi/overall"
```

The invariants (all verified on NEX and STH):

- **Every `history` row is byte-identical to `/reports/dev-kpi?sprint=<that sprint>`** for the same
  developer. They come from the same function, so a divergence means the reuse broke.
- **Counts equal the sum of `history`**; `delivery_pct` / `reopen_pct` equal the recomputed totals;
  `rating` equals the mean of the history ratings; `wip` equals the newest history row's `wip`.
- **No counted sprint is both unplanned and zero-footprint**, and `history` is in sprint order.

**Frontend:** `src/api.js` (`devKpiOverall`), `src/components/DevKpi.jsx` (the mode switch, the
shared `KpiRow` renderer used by all three row kinds, the expandable history), `src/App.jsx`
(`kpiOverall` state — it lives there because it decides whether the sprint tabs still mean anything),
`src/index.css` (`.kpi-mode`, `.kpi-sub`, `.kpi-caret`, `.kpi-span`, `.kpi-live`).
