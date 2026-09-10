# Single Combined Sprint Report — All Boards, as **Markdown**

## Context
The deliverable is **one combined Markdown report** covering all three boards — an org roll-up
followed by a full per-board section each. We build the Markdown directly (no PPTX). Everything
upstream stays: per-board sprint auto-selection (NEX 3→4, AKV2 2→3, STH 1→2), the `projects.yaml`
rosters, the two-pass flow, the authored narrative JSONs, and the NEX day-of accomplishments
prepend. No API key is needed — the two prose sections come from the authored narrative JSONs.

Confirmed with the user:
- **Markdown only — remove the PPTX.** The sprint-compare PPTX builder chain and its `.pptx`
  endpoint are deleted, not left dormant.
- **Authored narrative only.** Each board section carries tables + the authored achievement bullets
  and roadblock cards. No raw completed/blocked ticket lists in the report.

**Scope note:** removal is limited to the *sprint-compare* PPTX path. The unrelated **Weekly QA
deck** (`build_weekly_pptx` + `/reports/weekly.pptx`) is a separate feature and stays intact — it
shares the low-level drawing helpers, which therefore also stay.

## What already exists (reuse, do not rebuild)
- `render_deck_markdown(c)` (`app/report_render.py`) — renders one board's full deck content as
  Markdown tables. It is shaped as an *LLM build instruction* (preamble + "compile these titles
  into bullets" placeholders on slides 9/10), so it is the **table-format reference**, not directly
  reusable for the final report. Still used by the `/reports/sprint-compare.md` endpoint — leave
  it untouched.
- `render_markdown(c)` — terse data summary (already used by Pass A). Keep as-is.
- `_compute_sprint_compare`, `resolve_cfg`, `get_engine` — already driven by the generator.
- Authored inputs already in the scratchpad: `NEX_narrative.json`, `AKV2_narrative.json`,
  `STH_narrative.json`, `NEX_accomplishments.txt`.
- The `SprintCompareOut` / `SprintCompareSprint` / `DevDeliveryRow` fields (`app/schemas.py`).

## Approach

### 1. Rename the module: `app/pptx_report.py` → `app/report_render.py`
Rename the file. Update the 5 Python import sites (all `from app.pptx_report import ...`):
`app/main.py` (lines 1092, 1114, 1307, 1329) and `scripts/generate_compare_decks.py` (line 42).
Update the module docstring to describe a report-render module (Markdown sprint-compare + Weekly QA
deck), not a pptx-only one. All steps below operate on the renamed `app/report_render.py`.

### 2. `app/report_render.py` — add a clean combined-Markdown renderer
Add `render_combined_markdown(entries)` where
`entries = [{"name": str, "compare": SprintCompareOut, "narrative": dict}, ...]` in board order.
It returns one Markdown string — a **final human-facing report**, not an LLM prompt (no "Slide N"
headings, no build-instruction preamble, no raw ticket dumps):

- **Header**: `# Engineering Sprint Report — All Boards` + generated date + confidential note.
- **Org overview table** across all boards, with a bold **Total** row:
  `| Board | Closing → Kickoff | Completed | Carry-over | New work |`
  (totals = per-board sums; matches the deck cover: 267 / 244 / 76).
- **Per-board section** (add a `_board_markdown(name, c, narrative)` helper), one `---` divider
  between boards, each with:
  - `# {name} — {closing} Closure · {kickoff} Kickoff` + sprint date ranges.
  - **Closure at a glance** (completed / carry-over / new work / projects) — mirror slide 2.
  - **Completed work by project** table — mirror slide 3.
  - **Committed work (kickoff) by type** list/table — mirror slide 4.
  - **Team performance** table (`# / Engineer / Tickets / Completed / % Total`) — mirror slide 5.
  - **Ticket breakdown** table (+ TOTAL + completion rate) — mirror slide 6.
  - **Developer delivery — closing** and **— kickoff** tables — mirror slides 7-8.
  - **Key achievements** — the authored `narrative["achievements"]` bullets (NEX already has the
    day-of notes prepended by the script).
  - **Roadblocks and next steps** — the authored `narrative["roadblocks"]` cards, each rendered as
    `**R0n — {concern}**` + Impact / Mitigation / Help needed bullets.

Reuse the exact table columns/labels from `render_deck_markdown` so figures stay 1:1 with the deck.

### 3. `app/report_render.py` — remove the sprint-compare PPTX chain
Delete these (all self-contained to the sprint-compare deck): `_NARRATIVE_SCHEMA`,
`_author_narrative`, `_delivery_slide`, `_add_compare_slides`, `_save_pptx`, `build_compare_pptx`,
`build_combined_compare_pptx`. **Keep:** the shared drawing helpers (`_bg`, `_text`, `_stat_cards`,
`_table`, `_eyebrow_title`, `_footer`, `_fill`), `LlmNotConfigured`, the Markdown renderers
(`render_markdown`, `render_deck_markdown`, `render_combined_markdown`), and the entire **Weekly QA
deck** (`build_weekly_pptx`, `_QA_NARRATIVE_SCHEMA`, `_author_qa_narrative`, `render_weekly_markdown`).

### 4. `app/main.py` — remove the `/reports/sprint-compare.pptx` endpoint
Delete the `sprint_compare_pptx` route (≈ lines 1104–1127) and its `build_compare_pptx` import.
Keep `/reports/sprint-compare` (JSON) and `/reports/sprint-compare.md`. The Weekly QA `.pptx`
endpoint is untouched (its import updates to `app.report_render` in step 1).

### 5. `scripts/generate_compare_decks.py` — Pass B writes one `.md`
- Import `render_combined_markdown` (from `app.report_render`) instead of the pptx builder.
- `run_pass_b()`: build the same `entries` list (compute each board, load narrative, prepend NEX
  notes), then `md = render_combined_markdown(entries)` and write
  `~/Documents/sprint_report/AllBoards_Sprint_Report_<generated_on>.md`.
- After the `.md` verifies, **delete** the superseded `AllBoards_Sprint_Report_<date>.pptx`.
- Pass A is unchanged.

### 6. Update doc references
Point `README.md` (line 138) and `COMPARISON.md` (lines 117, 135) at `app/report_render.py` and
reword the sprint-compare line to say Markdown export (no pptx). (`docs/sprint_compare_decks_all_boards.md`
is the original historical plan — leave as-is.)

## Critical files
- `app/pptx_report.py` → **`app/report_render.py`** (rename) — add `render_combined_markdown` +
  `_board_markdown`; remove the sprint-compare PPTX chain (steps 1–3).
- `app/main.py` — update imports to `app.report_render`; remove the `.pptx` sprint-compare endpoint
  (steps 1, 4).
- `scripts/generate_compare_decks.py` — import + Pass B render the combined `.md` (steps 1, 5).
- `README.md`, `COMPARISON.md` — doc references (step 6).
- Read-only: `app/schemas.py`, `app/main.py` (`_compute_sprint_compare`).

## Verification
1. `python -c "import app.main"` — app imports cleanly after the endpoint/builder removals (no
   dangling references to the deleted symbols).
2. `python scripts/generate_compare_decks.py --pass a` — reprints the auto-picked sprint pairs.
3. `python scripts/generate_compare_decks.py --pass b` — writes the single combined `.md`.
4. Read the `.md` and confirm: org overview table with Total row (267 / 244 / 76); three board
   sections in order (Nexus → AlfaKinetic-V2 → SETHI); team-performance and delivery tables
   populated for NEX & AKV2, STH team table populated with delivery zeroed; Key achievements show
   the authored bullets (NEX leads with the 5 day-of accomplishments); roadblock cards present.
5. Confirm the old `AllBoards_Sprint_Report_*.pptx` is removed and only the `.md` (plus the older
   untouched reference decks) remains in `~/Documents/sprint_report/`.
6. `grep -rn 'pptx_report\|build_compare_pptx\|build_combined_compare_pptx\|sprint-compare.pptx' app/ scripts/`
   returns nothing (module renamed + chain fully removed); the Weekly QA `.pptx` endpoint still resolves.
