---
name: product-report
description: >-
  Turn a worklog-tracker Timesheet into one Product Status Report XLSX per product — the weekly
  manager-facing report with sections for what the product is, current scope, who is doing what
  (roster, hours, hours/day, cross-product splits), timelines, go-live, blockers, and escalations.
  Use when the operator says "product report", "product status report", "status report for SETHI",
  "build the product report", or "check this report before I send it". Prefills ONLY what the
  timesheet can source and carries the slow-moving answers forward from last week's report, marking
  every carried cell; everything else is left an explicit TODO rather than guessed. Its `check` mode
  audits a filled-in report for the mistakes that reach a manager — leftover template EXAMPLE rows,
  an Hours/Day divisor that contradicts the stated week, implausible days, missing split notes, and
  internal contradictions. Fed by /worklog-tracker, which is fed by /git-list-merge-pr; run by the
  product-report agent, which is invoked SEPARATELY from the time-tracker agent, never chained to it.
---

# Product Report — Timesheet → one status report per product

**Goal:** a Product Status Report a tech lead can fill in in five minutes and send without
embarrassment — not a report an agent pretends to have written.

The organising idea is **sourced**. The timesheet honestly sources exactly one thing: §3's roster,
its hours, and who split time across products. It sources nothing else in the document. So this
skill prefills what is sourced, **carries** what last week already answered, and leaves everything
else an explicit `TODO — needs input`. A guessed §4 date or an invented §1 is worse than a blank
one, because a blank gets filled and a guess gets sent.

Read-only with respect to git and Jira. Its only writes are the report files.

---

## Step 1 — Build

Input is a **worklog-tracker Timesheet** — the `Developer | Hours | Title` sheet, sectioned
`NEXUS` / `SETHI`. Do not re-derive hours; /worklog-tracker owns the hour model.

`.xlsx` is what /worklog-tracker emits, and `.numbers` is accepted for one specific reason: that
skill's hours are estimates it explicitly expects to be **hand-corrected**, and correcting them on a
Mac means opening the sheet in Numbers, which resaves it as `.numbers`. A corrected timesheet is the
better input, so taking it is deliberate, not speculative generality — it is converted through
Numbers.app on the way in, exactly as a carried `.numbers` report is.

```bash
python3 reference/build_product_report.py build \
    --timesheet ~/Desktop/worklog_tracker_<MMDDYY>_<MMDDYY>.xlsx \
    --out-dir ~/Desktop
```

One file per product section found: `Product_Status_Report_<PRODUCT>_<start>_<end>.xlsx`. The
template is one product per report, so two product sections mean two files — never two sheets.

| Flag | Effect |
|---|---|
| `--product SETHI` | only that section; default is every section in the timesheet |
| `--working-days N` | override the Hours/Day divisor |
| `--week "August 31 - September 4, 2026"` | override the Reporting Week text |
| `--no-carry` | start clean, ignoring last week's report |

**Completion criterion:** every product section in the timesheet has a file on disk, and the run
printed each file's developer count, total hours, and what it carried from.

### The Hours/Day divisor is derived, not assumed

`Hours / Day` is written as a live formula `=D<row>/<days>`, so correcting an hours figure moves the
day figure with it. `<days>` counts **Mon–Fri days in the timesheet's own window**, skipping a start
day whose window opens after midday — the worklog's Thursday-18:00 anchor is an evening cutoff, not
a day of work. An Aug 27 18:00 → Sep 6 window is therefore **6** working days, not 5 and not 10.

This matters because the two are routinely different: the timesheet's window is ~10 days while the
report's "Reporting Week" reads as a normal week. Dividing a 10-day window's hours by 5 inflates
every row. Pass `--working-days` only when you are deliberately re-basing onto a different week, and
change `--week` to match.

---

## Step 2 — Hand it to the human, and say what only they can answer

The generated file is a **draft with holes, by design**. Report exactly which cells need a person:

- **§2 (current scope)** — always `TODO`. It is this week's in-flight work, and last week's answer
  is actively wrong. The timesheet's ticket titles are tempting here; they describe what *merged*,
  not what is *in flight*.
- **§6 (blockers)** — always empty. A blocker carried from last week is a blocker that reads as
  still-blocked when it was resolved on Tuesday.
- **Role**, on a developer who is new since last week's report.
- **Hours** — seeded, and meant to be overwritten. See the limits below.

---

## Step 3 — Check before it is sent

```bash
python3 reference/build_product_report.py check \
    ~/Desktop/Product_Status_Report_SETHI_<start>_<end>.xlsx
```

Exits non-zero when anything blocking remains. Findings are `ERROR` (must fix) or `WARN` (judge it):

| Finding | Why it matters |
|---|---|
| Template `EXAMPLE (delete this row)` still present | It sits under §6 Blockers and reads as a real blocker |
| A cell still reading `TODO — needs input` | An unanswered section shipped as-is |
| A cell still carrying `[carried — confirm]` | Last week's answer sent unreviewed |
| Inconsistent Hours/Day divisors across rows | Some rows on a 5-day week, others on 6 |
| A row above 10 h/day | Either a real escalation or a wrong number — both need a comment |
| A developer on another product's report for the same window, with no split in Notes | §3 asks for hours on THIS product only; an unsplit row claims their whole week |
| §4 "enterprise-level: yes" beside `TBD` / `Phase 0` | Directly contradictory; a manager will catch it |
| A date with no year, or a date written as arithmetic | "January 14" and "Aug 31 + 1 week" are not calendar entries |
| Date Submitted ≠ today | Stale header on a report being sent now |

**Completion criterion:** `check` returns zero blocking findings, and every `WARN` has been either
fixed or consciously accepted.

The three things `check` cannot judge — because they need a person — are whether §5's "if already
deployed" premise even holds, whether the report's several dates tell one coherent story, and
whether an hours figure is true. Raise those in your own words.

---

## Carry-forward — the previous report IS the store

There is no side-car state file. Carry-forward reads **the most recent
`Product_Status_Report_<PRODUCT>_*` on `--out-dir`**, `.xlsx` or `.numbers` alike (a `.numbers` is
converted through Numbers.app on the fly). The artifact you sent last week is the source of truth
for what was true last week, which keeps the two from drifting apart.

Carried: `Reported By` · §1 · §4's four timeline answers · §5 go-live and its work-item table · §7 ·
and the **Role** column, matched by developer name. Never carried: §2 and §6, per Step 2.

Every carried cell gets a visible `[carried — confirm]` suffix. It is deliberately ugly — you delete
it as you confirm the line, and `check` flags whatever you missed. Nothing stale ships silently.

---

## Know what the Hours cannot do

The seeded hours are /worklog-tracker's **commit-volume estimates**, carried through unchanged and
labelled `Estimate from commit volume (N items)` in Notes. §3's own instruction asks for *"real
hours on THIS product only"* — which these are not.

They are a starting point that saves retyping a roster, and they are wrong in a specific direction:
a developer who ships many small tickets scores above one who ships few large ones for the same
work. Expect the team to overwrite them. **Never present a generated Hours column to a manager as
tracked time** — either have each person correct their row, or clear the column and have them fill
it.

---

## Maintaining this skill

The template's row numbers are load-bearing — `S3_FIRST`, `S4_LABELS` and their siblings at the top
of the generator are the single source of truth for the cell map. If the `.numbers` template gains
or loses a row, re-export it to `reference/product_status_template.xlsx` and update those constants
together; nothing else in the generator hardcodes a row.

---

## Output checklist

- [ ] Input is a real /worklog-tracker Timesheet — hours are not re-derived here.
- [ ] One file per product section; never two products in one file.
- [ ] Hours/Day is a live formula over a divisor derived from the timesheet's own window.
- [ ] Cross-product developers carry a `Split with <PRODUCT> (N hrs)` note on every report.
- [ ] §2 and §6 left unanswered — never carried, never guessed from ticket titles.
- [ ] Every carried cell marked `[carried — confirm]`.
- [ ] Template EXAMPLE rows cleared from §5 and §6.
- [ ] Hours labelled as commit-volume estimates, never as tracked time.
- [ ] `check` run on the filled report before sending; zero blocking findings.
- [ ] The cells only a human can answer reported back by name.
