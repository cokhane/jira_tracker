---
name: create-develop-capacity
description: >-
  Generate or update the team's "Rolling Sprint Capacity" Excel workbook — the per-developer
  planned-vs-actual ticket tracker that rolls each sprint's capacity forward as
  ROUND(average(previous capacity, previous actual)). Use when the user asks to build, edit,
  or add a developer to the developer capacity / sprint capacity spreadsheet, change sprint
  dates, mark the current sprint, or says "developer_capacity_weekly.xlsx", "capacity sheet",
  "rolling sprint capacity", or "sprint capacity workbook". Produces a clean white-background
  .xlsx with live formulas.
---

# Rolling Sprint Capacity Sheet

Builds `developer_capacity_weekly.xlsx` — a per-developer capacity vs. actual tracker across
four sprints. Everything is driven from a small JSON config; a bundled script renders the
workbook with live Excel formulas so totals recompute when actuals are typed in.

## The rolling rule (the whole point)

Each sprint's **capacity** is computed, never typed:

```
sprint capacity = ROUND( AVERAGE(previous sprint capacity, previous sprint actual), 0 )
```

- Only **Sprint 1** capacity and actual are entered per developer. Sprints 2-4 capacities are
  formulas. Later-sprint actuals stay blank for manual entry; the formulas pick them up the
  moment they're filled in (`=IF(actual="",prev_capacity,ROUND(AVERAGE(...),0))`).
- Excel's `ROUND` rounds halves **away from zero**, so `4.5 → 5`. This matches the team's
  convention — do NOT reproduce it in Python with `round()`, which rounds half-to-even
  (`round(4.5)==4`) and will report wrong numbers.

## Layout & formatting conventions

- **White background**, gridlines off. Structure comes from borders + bold + dark-blue text
  (`#1F3864`), not fills. Never reintroduce colored fills.
- Row 1 title · Row 2 rule · Row 4 sprint headers (merged over each sprint's columns) ·
  Row 5 sprint date ranges (italic grey) · Row 6 column headers.
- Per sprint: `Capacity` + `Actual` columns, except the final sprint which is
  `Capacity (proj.)` only.
- **TOTAL** row = `SUM` of each column (equals the sum of the visible rounded values).
- **SUMMARY** block: team totals per sprint, avg capacity/dev, and Sprint 1 utilization
  (actual ÷ plan, shown as a percentage).
- Integers display with number format `0` (no trailing dot); averages `0.0`; utilization `0.0%`.
- **Current sprint** (`"current": true`) is accented in green (`#2E7D32`): a "● CURRENT" tag
  on its header and a medium green border running down its column(s). Only one sprint should
  be current.

## How to run

1. Write/adjust a config JSON (see `scripts/example_config.json`). To **add a developer**,
   append `{"name": "...", "capacity": N, "actual": N-or-null}`. To **edit dates** or **move
   the current marker**, change the `sprints` entries.
2. Regenerate the whole workbook (idempotent — always rebuilds from config):

   ```bash
   python .claude/skills/sprint-capacity-sheet/scripts/build_capacity_sheet.py <config.json>
   ```

3. Default output is `~/Desktop/developer_capacity_weekly.xlsx`; override with the config's
   `output` key. Per team convention, finished sprint decks/reports live in
   `~/Documents/sprint_report/`.

## Notes & gotchas

- Requires `openpyxl` (`pip install openpyxl`).
- `data_only=True` reads return `None` for formula cells until Excel has opened and cached the
  workbook once — that's expected, not a bug. Read with `data_only=False` to see formulas.
- `capacity` sums are live; a stated "Total" that disagrees with the per-dev sum means a
  developer was added/removed — trust the formula, flag the mismatch.
- The generator rebuilds the file from scratch each run, so hand-entered later-sprint actuals
  in the .xlsx are NOT preserved. Capture those actuals back into the config before
  regenerating, or edit the .xlsx directly for one-off actual entry.
