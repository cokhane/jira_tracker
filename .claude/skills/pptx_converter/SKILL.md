---
name: pptx_converter
description: >-
  Convert an already-authored All-Boards sprint-report Markdown file into a themed PPTX deck,
  treating the .md as the source of truth (no DB, no API key, no narrative JSON). Use when the
  user hands you an AllBoards_Sprint_Report_*.md and wants "the deck", "a PPTX", "slides from
  this markdown", "convert this md to pptx", or "turn the sprint report into a presentation".
  Parses the Overview table, the per-board 9-column "Team Load & Delivery" funnel tables
  (Assigned / Completed / Incomplete / → Code Review / QA / Merged / Other / Delivered), Key
  Achievements, and Roadblocks, and renders them with the Alfa Kinetic theme. This is the
  markdown-driven path; use build_allboards_deck.py instead when you must recompute numbers
  from the tracker DBs.
---

# Sprint Deck from Markdown

Renders an `AllBoards_Sprint_Report_<date>.md` into a matching `.pptx`, slide-for-slide. The
Markdown you already reviewed/edited **is** the source of truth — whatever is in the file is what
lands in the deck. No database, no `ANTHROPIC_API_KEY`, no narrative files.

## When to use this vs. build_allboards_deck.py

- **This skill (`md_to_deck.py`)** — the `.md` already exists and is correct; just turn it into
  slides. Decoupled from the DB, so edits made to the `.md` by hand are honored exactly.
- **`scripts/build_allboards_deck.py`** — you need to (re)compute every number fresh from the
  tracker DBs + pre-authored `*_narrative.json`. That path owns the numbers; this one does not.

## What it parses

From the standard AllBoards layout:

- `_Generated …_` line → title/closing footer.
- `## Overview — All Boards` table → the Sprint Overview slide (rendered as-is, including the
  Total row).
- Each `# <Board> — … Closure · … Kickoff` section →
  - `- Closing sprint:` / `- Kickoff sprint:` lines → sprint names + date ranges on the divider.
  - each `## … — Team Load & Delivery` table → one funnel slide. Columns are mapped by header
    name onto the fixed 9-column order, so extra/renamed source columns still line up.
  - `## … — Key Achievements` bullets → achievements slide.
  - `## Roadblocks` bullets (`**Concern** — description`) → roadblock cards.

## Deck structure produced

Title (INK + portfolio stat cards) → Sprint Overview table → per board { divider → closing
funnel → kickoff funnel → Key Achievements → Roadblocks } → closing/distribution slide. For the
3-board report that is 18 slides.

## How to run

```bash
# Convert a specific report:
.venv/bin/python scripts/md_to_deck.py ~/Documents/sprint_report/AllBoards_Sprint_Report_2026-07-22.md

# Or omit the argument to convert the newest AllBoards_Sprint_Report_*.md in ~/Documents/sprint_report/:
.venv/bin/python scripts/md_to_deck.py
```

The canonical script lives at `scripts/md_to_deck.py` in the jira_tracker repo (alongside
`build_allboards_deck.py`); a copy is bundled under this skill's `scripts/` for portability. Both
locate the repo root by walking up to the folder holding `app/report_render.py`, so either runs
from anywhere. The `.pptx` is written next to the source `.md` (same basename) — i.e. into
`~/Documents/sprint_report/`, per team convention.

## Notes & gotchas

- Requires `python-pptx` (present in the repo `.venv`). Styling reuses the theme helpers exported
  from `app/report_render.py` (`_table`, `_stat_cards`, `_eyebrow_title`, `INK`, `CREAM`,
  `ACCENT`, …) — keep those exports stable or this skill breaks.
- Funnel headers are shortened (`Code Rev.`, `QA Test`) so 9 columns fit a 16:9 slide; the
  underlying numbers are untouched.
- Column mapping is by header substring, so it tolerates the older/newer table shapes. If a
  source column is renamed to something the matcher can't find, that cell renders blank — check
  `FUNNEL_HEADERS` / the `_cell()` lookups in the script.
- Idempotent: rerunning overwrites the same-named `.pptx`. It never edits the source `.md`.
- To verify output, extract table text with `python-pptx` and diff against the `.md` (numbers
  should match exactly).
