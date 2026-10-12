---
name: worklog-tracker
description: >-
  Consume a git-list-merge-pr report (the weekly per-developer merged-PR list across the four team
  repos) and emit a structured worklog as an XLSX workbook — a per-PR Worklog sheet, a per-developer
  Summary sheet, and a Timesheet sheet (Developer | Hours | Title, grouped by ticket, with a TOTAL
  row closing each developer), then push each developer's TICKET COUNT into the dashboard's Capacity
  Tracker. Use when the operator says "worklog", "worklog-tracker", "timesheet",
  "log report", "turn the PR list into a worklog", "export the merged-PR report to Excel/XLSX",
  "update the capacity tracker", or wants the git-list-merge-pr output as a spreadsheet. Pairs with
  and is normally fed by /git-list-merge-pr.
---

# Worklog Tracker — merged-PR list → XLSX worklog + timesheet

**Goal:** Take the output of [/git-list-merge-pr](../../developer/git-list-merge-pr/SKILL.md) — the weekly
per-developer, per-repo list of PRs with commits bundled — and turn it into a clean **XLSX workbook**
a tech lead can file or share, including a **timesheet** view.

Runs on the report /git-list-merge-pr **emits** — consumed directly, **not** from an intermediate
`.txt` file — and it does **not** re-query `gh` itself. Read-only with respect to git.

---

## Step 1 — Obtain the input list

> ## ⚠️ Run THIS copy of the generator — check before you pipe
>
> This skill is distributed to several trees, and on 2026-08-27 one of them
> (`jira_tracker_backend/.claude/skills/worklog-tracker/`) was **months stale**: it had no
> `--timesheet` and no `--only`. `install.py` auto-discovers project roots only under
> `~/Documents/work`, and `jira_tracker` lives under `~/anervea/jira_tracker` — so it was never
> reached and silently rotted.
>
> The result: a run that followed the "use the project-scoped skill" instruction produced the
> **per-PR workbook** (`Worklog` + `Summary`) instead of a timesheet — the exact artifact the
> "one file only" rule forbids — and nobody noticed until the sheet was opened.
>
> **Before piping, confirm the copy you are about to run supports the flag:**
>
> ```bash
> grep -c '\-\-timesheet' reference/build_worklog_xlsx.py    # 0 means you are on a stale copy
> ```
>
> If it prints `0`, re-sync from the canonical tree
> (`~/Documents/work/anervea-claude-skills/skills/pm/worklog-tracker/`) before doing anything else.
> **A copy that cannot produce a timesheet must never be worked around by emitting the workbook
> instead** — fix the copy.

Consume the /git-list-merge-pr **output directly by piping it into the generator on stdin** — there is
no intermediate `.txt` file to locate or pass around:

### The output filename

**Always `worklog_tracker_<MMDDYY>_<MMDDYY>.xlsx`** — the Monday and the Sunday of the week containing
today. For the week of 2026-08-13 that is `worklog_tracker_081026_081626.xlsx`.

```bash
DOW=$(date +%u)                                        # 1=Mon … 7=Sun
MON=$(date -v-$((DOW-1))d +%m%d%y)                     # Monday of this week
SUN=$(date -v-$((DOW-1))d -v+6d +%m%d%y)               # Sunday of this week
NAME="worklog_tracker_${MON}_${SUN}.xlsx"              # -> worklog_tracker_081026_081626.xlsx
```

> **The filename week is NOT the data window.** The name spans Monday–Sunday, while the report's
> window opens the *previous* Thursday at 18:00 (/git-list-merge-pr Step 1) — so
> `worklog_tracker_081026_081626.xlsx` contains work merged from 08-06 18:00 onward. That is
> intended; do not "fix" the name to match the window. The window itself is stated in cell `A1` of
> the sheet, which is where a reader should look for the exact bounds.

**The timesheet alone is the usual deliverable** — the workbook path is optional, so omit it:

```bash
/git-list-merge-pr  |  python3 reference/build_worklog_xlsx.py \
    --timesheet ~/Desktop/worklog_tracker_<MMDDYY>_<MMDDYY>.xlsx \
    --window "<window>" \
    --only "<the tracked roster>"
```

Name a workbook path only when the per-PR Worklog and Summary sheets are actually wanted; add `--tsv`
only when a paste-able text copy is. **Do not emit files nobody asked for** — the default deliverable
is one timesheet XLSX:

```bash
/git-list-merge-pr  |  python3 reference/build_worklog_xlsx.py ~/Desktop/worklog_<date>.xlsx \
    --window "<window>" --timesheet ~/Desktop/timesheet_<date>.xlsx --tsv ~/Desktop/ts.tsv
```

The report the skill emits carries, per PR: repo · developer (GitHub login) · `#number` · `[STATE]` ·
title · URL · commit count — exactly the fields the generator parses off stdin.

If no list exists yet, invoke /git-list-merge-pr first and pipe its output in. (A `--report <file>`
fallback exists for a report already saved to disk, but stdin is the default and preferred path.)

> **The parser tracks the report format.** /git-list-merge-pr Step 4 emits developer markers as
> `### <login> — <N> PRs`; the generator strips that `— <N> PRs` suffix to recover the bare login.
> If you ever change that marker, change `DEV_RE` with it — an unstripped suffix silently splits one
> developer into a separate identity per repo, which corrupts the Summary and Timesheet sheets.

---

## Step 2 — Normalize each PR into a worklog row

For every PR, derive:

| Column | Source / rule |
|--------|---------------|
| Developer | the `### <login>` group it sits under |
| Repository | full repo name (`sef`→`sethi_enterprise_frontend`, `seb`→`sethi_enterprise_backend`, `nexus_api`, `nexus_panel`→`nexus_panel_frontend`) |
| PR # | the `#number` |
| Ticket | first `STH-\d+` or `NEX-\d+` found in the title (blank if none) |
| Title | PR title, with any leading `TICKET :` prefix kept as-is |
| Commits | bundled commit count for that PR |
| Status | `MERGED` / `OPEN` / `CLOSED` |
| PR URL | the PR link |

**Default filter: MERGED-only** (matching /git-list-merge-pr's default). Env-sync "Develop to staging"
PRs keep their collapsed commit count.

**Restricting the roster** — two filters, both case-insensitive, `--only` applied before `--exclude`:

| Flag | Effect |
|------|--------|
| `--only "Alfa-Jc,Alfa-Dan,alfa-muskan"` | keep ONLY these developers |
| `--exclude "anervea-mark,Alfa-Shane"` | keep everyone EXCEPT these |

**A name matching nobody is reported as a warning, never applied silently.** Case matters more than
it looks: the real logins are `Alfa-Jc` (not `Alfa-JC`) and `alfa-muskan` (not `Alfa-muskan`), so an
exact-match filter drops people it was meant to keep. A typo'd `--only` erases a developer's entire
week; a typo'd `--exclude` leaves someone in who was meant to be out.

**Excluding does not rescale anyone else.** The hour model pins the busiest developer at
`BUSIEST_TOTAL_HOURS`, so removing someone who is not the busiest leaves every remaining total
untouched. Removing the busiest developer does rescale everyone.

---

## Step 3 — Build the XLSX workbook

Use `openpyxl`. Three sheets:

1. **`Worklog`** — one row per PR, columns in this order:
   `Developer | Repository | PR # | Ticket | Title | Commits | Status | PR URL`.
   Sort by Repository, then Developer, then PR # descending. Bold header row, frozen top row,
   auto-ish column widths, and the PR URL as a clickable hyperlink.
2. **`Summary`** — one row per (Developer, Repository) with a merged-PR count and total commits, plus
   a bold `— all repos —` grand-total row for any developer who worked in more than one repo.
3. **`Timesheet`** — see Step 4.

Write the file to a user-accessible location — `~/Desktop/`, named per the rule in Step 1. State the
window in the sheet's `A1` title cell.

Reference generator: [reference/build_worklog_xlsx.py](reference/build_worklog_xlsx.py) — reads a
git-list-merge-pr report on stdin and emits the workbook described above.

---

## Step 4 — The Timesheet sheet

Columns are `Developer | Hours | Title`. The shape:

```
NEXUS
Dan Denver De Leon      1.5   NEX-2147 : Reveal Ask Nexus AI emblem label on hover only
Dan Denver De Leon      2.0   NEX-2153 / NEX-2154 : Remove fullscreen toggle and hide empty panel
TOTAL                  42.0
SETHI
John Carlo Mandawe      2.5   STH-577 : report the organization on an activity log entry
TOTAL                  92.5
```

Rules:

- **Section headers.** `NEXUS` (nexus_api + nexus_panel_frontend) and `SETHI` (the two sethi repos),
  shaded and bold. **Sectioning is per WORK ITEM, from the repo the work landed in — never per
  developer.** Someone who shipped in both products appears under BOTH headings, each block with its
  own `TOTAL`. Bucketing a whole developer under their dominant section drags their other product's
  tickets along: it once put a lone `NEX-2030` under `SETHI` in Rhidzkhan Ahmad's block, because 26
  of his 27 items were STH. A `NEX-` row under `SETHI` (or `STH-` under `NEXUS`) means this rule has
  regressed.
- **One row per ticket, not per PR.** PRs sharing an `STH-`/`NEX-` key collapse into a single work
  item; the most descriptive of their titles wins. A PR with no ticket key keeps its own row.
- **Title separator is ` : `** — the raw PR title's own convention, preserved. A leading run of
  several keys renders joined with ` / `: `STH-546, STH-547 : …` → `STH-546 / STH-547 : …`.
- **Env-sync PRs are dropped entirely.** Their commits are already counted under the feature PRs they
  roll up, so billing them again would double-count.

  > **⚠️ The built-in drop is asymmetric — `ENV_SYNC_REPOS` covers only the two `sethi_*` repos.**
  > A `nexus_api` or `nexus_panel_frontend` env-sync PR ("Develop to staging", "promote staging →
  > uat") is **not** auto-dropped and will bill as real work. Until that constant is widened, filter
  > those out of the report *before* piping it in. Missing this is how a developer whose whole window
  > was env-sync merges shows up with a full workload.
- **A bold `TOTAL` row closes each developer**, as a live `=SUM()` over exactly that developer's rows
  — never a frozen number. These hours are estimates meant to be hand-corrected, and a hardcoded
  total silently goes stale the moment someone edits one.
- **Real names, not logins.** Sourced from [reference/developers.json](reference/developers.json) —
  edit that file, not the code. A login that is missing (or mapped to `""`) falls through to the raw
  GitHub login, and the generator prints those logins so you know what to fill in.

  > **This roster drifts behind `/git-list-merge-pr` Step 4.5, which is the real source of truth for
  > who is tracked.** They are two separate lists and nothing keeps them in sync. `Alfa-Roselle` →
  > `Roselle Tabuena` was tracked upstream for a full window before it was added here (2026-08-27),
  > and until it was, she rendered as a raw login. **Whenever the roster changes, edit both.**

### The hour model — and its honest limits

Hours are **ESTIMATES sized from commit volume, not measured time**, and the sheet says so in row 2.
Each work item is weighted `HOUR_BASE + HOUR_SCALE * sqrt(commits)` — sqrt-damped, so a 40-commit PR
reads bigger than a 4-commit one but not ten times bigger — then snapped to half-hour steps and
bounded by `MIN_ITEM_HOURS` (1.5h — nothing bills less, however small) and `MAX_ITEM_HOURS` (8h, one
working day). One global factor then pins the busiest developer at `BUSIEST_TOTAL_HOURS`, so
**totals stay honest relative to each other**.

### Standing work — the hours no PR can show

Some work never produces a commit: code review, branch cleaning, board cleaning, ops, meetings.
[reference/standing_work.json](reference/standing_work.json) declares it per developer, keyed by the
same GitHub logins as `developers.json`:

```json
{ "items": { "Alfa-Axe": [ { "hours_min": 6.0, "hours_max": 10.0,
                             "title": "Code review, Branch Cleaning, Board Cleaning" } ] } }
```

Each entry becomes a line item at the **top of EVERY section that developer worked in** — recurring
work is not confined to one product, so a developer with PRs on both NEXUS and SETHI carries the
block on **both**, not just on their largest block.

**Hours are drawn, not fixed.** `hours_min`/`hours_max` bound an inclusive draw on the `0.5h` step,
seeded from `(developer, section, window)`:

- **per section, independently** — the two blocks of a two-product developer draw different figures,
  so the same line does not read `10.0h` twice;
- **seeded, never from the clock** — re-running the same week rebuilds the identical timesheet, which
  is what makes the sheet auditable;
- a scalar `"hours": 8.0` instead of a range **pins** one fixed figure (`low == high`, no draw).
  Omit both and the entry falls back to the `STANDING_MIN_HOURS`/`STANDING_MAX_HOURS` defaults.

Drawn or pinned, these hours are **declared, not inferred**, and nothing downstream is allowed to
move them:

- the commit weighting skips them (they have no commits to weight),
- the per-item `1.5h`/`8h` clamps do not apply — a declared 8h item stays 8h,
- the light-week floor stretches only the commit-derived items **around** them, while still counting
  them toward the 40h threshold. A standing 8h plus 27h of commit work reaches a 35h target by
  stretching the 27h alone.

A developer with no merged PRs in the window is skipped — there is no block to attach the item to,
and they are never given a section they did not work in. Delete a developer's entry to drop their
standing line.

> Declared hours are an operator's assertion, not an observation. They are as trustworthy as whoever
> wrote the JSON — which is the point, and also the caveat.

### The light-week floor

Commit volume misses every kind of work that leaves no PR behind — review, ops, pairing, debugging,
meetings — so a developer who was on the payroll all window can read as an 8h week. After the
commit-weighted pass, any developer whose **whole-window total** lands under `FLOOR_THRESHOLD_HOURS`
(40h) is lifted to a seeded random target in `[FLOOR_MIN_HOURS, FLOOR_THRESHOLD_HOURS)` — 30h to
40h — and their items are rescaled proportionally so the live `=SUM()` still matches.

Four properties matter, and each exists for a reason:

- **Per DEVELOPER, never per section.** The lift sums a person's NEXUS *and* SETHI hours and bumps
  once. Flooring each `TOTAL` row on its own would bump a two-product developer twice and bill them
  a 60h+ week.
- **It lifts, it never lowers.** A developer already at 37.5h keeps 37.5h even if their draw comes
  in lower. The floor is a floor, not a re-roll.
- **The draw is seeded from `(developer, window)`, never the clock.** Re-running the same week
  rebuilds a byte-identical timesheet; only a new window redraws. A randomised number that moved on
  every run would be unauditable.
- **`MAX_ITEM_HOURS` caps what is reachable.** A developer with N work items cannot exceed `N * 8h`,
  so a very short item list lands below 30h — 4 items cap at 32h, 3 items at 24h. When the floor is
  genuinely unreachable the generator says so on stderr rather than faking it.

> **This is the one place the sheet stops being an observation.** A lifted total is an assumption
> about paid time, not a measurement of shipped work — row 2 of the Timesheet says so explicitly.
> Never hand a lifted sheet to a client as measured hours. If the numbers must be defensible rather
> than indicative, set `FLOOR_THRESHOLD_HOURS = 0` to disable the lift entirely and let light weeks
> read light.

> **`MIN_ITEM_HOURS` and `BUSIEST_TOTAL_HOURS` fight each other, and the floor wins.** A developer
> with N work items cannot total less than `N * MIN_ITEM_HOURS`, so once `N * MIN` approaches the
> ceiling there is no headroom left for the commit weighting to express anything — items pile up on
> the floor and the hours stop discriminating. At a 1.5h floor with the 2026-08-06→16 data, 215 of
> 251 items (86%) sat exactly on the floor and the busiest developer overshot the 80h ceiling to
> 92.5h. If you raise the floor, either raise `BUSIEST_TOTAL_HOURS` to match or group work items more
> coarsely — otherwise the sheet is a flat rate wearing an estimate's clothing.

**Know what this cannot do.** Commit count is a proxy for effort, not a measure of it — a developer
who ships many small PRs scores above one who ships few large ones for the same work. If the numbers
need to be defensible rather than indicative, hand the sheet to the developers to correct, or clear
the Hours column and have each person fill their own. Never present these hours as tracked time.

---

## Step 5 — Push the ticket counts into the Capacity Tracker

The timesheet is one of **two** things this report feeds. The other is the dashboard's Capacity
Tracker, whose Actual column the team otherwise types in by hand, cell by cell. This step fills it
from the same report:

```bash
# 1. dry run FIRST — prints `current -> new` per cell and writes nothing
/git-list-merge-pr  |  python3 reference/push_capacity.py

# 2. then commit the write
/git-list-merge-pr  |  python3 reference/push_capacity.py --apply
```

**The dry run is not optional ceremony.** Actuals are human input, so every write is a potential
overwrite of a number somebody typed deliberately — and the dry run's `current -> new` diff is the
only view that shows what a real run would replace. Read it before passing `--apply`.

### The unit is TICKETS, never the Timesheet's hours

The grid's Capacity column is planned in **distinct Jira tickets per sprint** (`dev_target_default`
= 10), so the Actual written beside it is a **count of distinct `STH-`/`NEX-` keys** the developer
shipped in the window. The Timesheet's Hours are commit-derived *estimates* and belong to a
different sheet — pushing them here would silently redefine the column into a unit nobody planned
in. Two PRs against `NEX-2147` are **one** ticket, matching the Timesheet's own one-row-per-ticket
grouping; env-sync PRs are dropped exactly as they are there.

A PR with **no** ticket key is counted separately and reported, never rounded in — the grid counts
Jira tickets, and a PR without one has no ticket to count.

### Board routing and the name bridge

Sections route to boards — `NEXUS` → **NEX**, `SETHI` → **STH** — per work item, so a developer who
shipped in both products updates both grids. Someone's NEX tickets never land on the STH grid.

**The grid keys on developer names that do NOT match `developers.json`.** That file holds the
Timesheet's display names; the grid holds its own strings, and the two genuinely disagree —
`John Carlo Mandawe` vs the grid's `John Mandawe`, `Roselle Tabuena` vs `Roselle.Tabuena`. A write is
keyed by grid name, so a near-miss is a 404, not a mistyped cell.
[reference/capacity_map.json](reference/capacity_map.json) is the bridge; **edit that file, not the
code.** Verify any new entry against the grid itself, which is the only source of truth:

```bash
curl -s http://localhost:8000/api/NEX/capacity | python3 -m json.tool | grep '"developer"'
```

An unmapped login, or one with no cell in that sprint, is **reported and skipped** — never guessed
into a write against the wrong person.

### What else can stop a cell being written

| Flag / condition | Effect |
|---|---|
| `--base <url>` | Tracker API root (default `http://localhost:8000`) — the backend must be running. |
| `--sprint-date YYYY-MM-DD` | Target a past week; default is **this week's Monday**, matching the filename rule. |
| `--only` / `--exclude` | Same login filters as the generator, same case-sensitivity trap. |
| `--report <file>` | Read a saved report instead of stdin. |
| Board unreachable | That board is skipped wholesale and reported; the other board still writes. |
| Date outside the grid | Reported; nothing written for that board. |

Sprints are matched **by date range, not by `is_current`**, so re-running a past week lands on the
sprint that week belonged to rather than on today's.

> **Writing an actual moves later capacities.** The grid's rolling rule recomputes every subsequent
> sprint as `ROUND(AVERAGE(prev capacity, prev actual))`, so a pushed actual changes the *plan*
> ahead of it, not just the cell. That is the intended behaviour of the grid — but it means a wrong
> push is not confined to one cell, which is the second reason to read the dry run.

---

## Step 6 — Report

Report the saved XLSX path, the row count (PRs), the developer count, and the week window. Do not
paste the whole table back as text — the spreadsheet is the deliverable. Surface any `--only` /
`--exclude` warnings and any unmapped logins verbatim; both mean the sheet is missing something a
reader expects.

Then report the capacity push separately: **how many cells were written, on which boards and sprint,
and every skip verbatim**. A skipped developer is someone whose week the dashboard will not show —
that is exactly the thing a silent success would hide.

---

## Output checklist

- [ ] Input sourced from a real /git-list-merge-pr run, piped on stdin (not re-queried here).
- [ ] One worklog row per PR; ticket key extracted; commit count carried.
- [ ] MERGED-only by default; state filter honored if the operator asked for a wider view.
- [ ] `--only` / `--exclude` misses reported as warnings, never applied silently.
- [ ] Three sheets (Worklog + Summary + Timesheet); header bold + frozen; URLs hyperlinked.
- [ ] Summary carries the `— all repos —` grand total for multi-repo developers.
- [ ] Timesheet grouped by ticket, sectioned NEXUS/SETHI, ` : ` separator, live `=SUM()` TOTALs.
- [ ] No `NEX-` ticket under `SETHI` and no `STH-` ticket under `NEXUS` — sectioning is per item.
- [ ] Timesheet hours labelled as estimates — never presented as measured time.
- [ ] Generator copy verified non-stale (`grep -c '--timesheet'` > 0) BEFORE piping.
- [ ] Light-week floor applied per developer across sections — no one bumped twice.
- [ ] Standing items from standing_work.json present, at declared hours, never rescaled.
- [ ] Standing items on EVERY section the developer worked in, drawn per section within
      `hours_min`–`hours_max` — not one fixed figure repeated, and not only the largest block.
- [ ] Any "too few work items to reach the floor" stderr note surfaced, not swallowed.
- [ ] Env-sync PRs dropped — including `nexus_*` ones, which the built-in filter does NOT catch.
- [ ] Unmapped logins reported so developers.json can be completed.
- [ ] ONLY the requested files written — timesheet alone by default, workbook/TSV only if asked.
- [ ] Named `worklog_tracker_<MMDDYY>_<MMDDYY>.xlsx` from this week's Monday and Sunday.
- [ ] Saved to a user-accessible path; path + counts + window reported.
- [ ] Capacity push dry-run READ before `--apply` — the `current -> new` diff shows what it overwrites.
- [ ] Capacity values are distinct TICKET COUNTS, never the Timesheet's hours.
- [ ] Sections routed per item — NEXUS→NEX, SETHI→STH; a both-product developer updates both grids.
- [ ] Grid names sourced from capacity_map.json and verified against `GET /api/<key>/capacity`.
- [ ] Every unmapped login / missing cell / skipped board reported, never silently dropped.
- [ ] Cells written + skips reported separately from the XLSX path.
