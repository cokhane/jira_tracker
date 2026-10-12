---
name: upgrade-resume
description: >-
  Take an existing resume/CV — .docx, .pdf, .md, .txt, .rtf — and upgrade it: rewrite weak bullets
  into the "verb + what you built + specifics + measurable outcome" form, strip filler phrases,
  rebalance length toward the last five years, fix ATS-hostile formatting, and recompute derived
  numbers (years of experience, repeated totals) against the actual dates. Keeps a plain-Markdown
  master at ~/Documents/resume/master.md as the source of truth and renders a clean, ATS-safe,
  selectable-text PDF through headless Chrome — no pandoc, LaTeX, or Word needed. NEVER invents
  metrics: any bullet missing its impact number becomes a highlighted [[TODO: ...]] marker that
  blocks the final render until the user supplies the real figure. Every run keeps the original
  untouched, writes a dated version folder, and reports what changed and what still needs a human.
  Use when the user says "upgrade my resume", "improve my resume/CV", "make my resume better",
  "rewrite my resume bullets", "my resume is too long", "make my resume ATS-friendly", or hands
  over a resume file and asks for a stronger version.
---

# Upgrade a resume

**Goal:** Take one existing resume and return a materially stronger version of the *same person's
real history* — better written, better proportioned, ATS-clean — plus a plain-text master that
makes every future edit a diff instead of a rewrite.

This skill improves what is already there. It does not invent a career, and it does not tailor to a
specific job posting.

---

## Where things live

```
~/Documents/resume/
├── master.md                  # source of truth — edit this, never the PDF
├── Rhidzkhan_Ahmad_Resume.pdf # current render
├── source/                    # untouched originals, copied in as-is
└── versions/YYYY-MM-DD/       # dated snapshot: master.md, .pdf, CHANGES.md
```

The original file is **copied, never modified**. Every run snapshots into `versions/` first, so a
rewrite is always reversible.

---

## Procedure

### Step 1 — Get the source in

Locate the resume: the path the user gave, else the newest resume-shaped file in
`~/Documents/resume/`, `~/Downloads`, or `~/Desktop`. Confirm the file with the user if more than
one plausible candidate turns up.

Copy it to `~/Documents/resume/source/` before reading it, then extract the text:

```bash
python3 .claude/skills/upgrade-resume/scripts/extract_text.py ~/Downloads/<file>.docx
```

`.docx` / `.rtf` / `.html` / `.md` / `.txt` go through the script. **PDF is the exception** — read
it with the **Read tool** and its `pages` parameter, which parses PDFs natively; the script will
refuse a `.pdf` on purpose.

### Step 2 — Normalise into master.md

Convert the extracted text into the Markdown subset in `reference/master-format.md`, faithfully and
with **no rewriting yet**. This step is pure structure: sections, entries, dates, bullets.

Then render it and read the page count — that is the length budget you are working against:

```bash
python3 .claude/skills/upgrade-resume/scripts/render_resume.py ~/Documents/resume/master.md
```

### Step 3 — Audit before editing

Read `reference/rubric.md` in full, then report to the user, *before* changing prose:

- **Page count vs. budget** (§3 — 2 pages for 10+ years).
- **Derived-number disagreements** (§7) — recompute years of experience from the earliest role to
  today; check repeated totals; list date gaps or overlaps. Report these, do not silently fix them.
- **Bullets with no measurable outcome**, counted per role.
- **Banned phrases** present (§2).
- **ATS hazards** — nonstandard section names, mixed date formats, tables, images.

### Step 4 — Rewrite against the rubric

Apply `reference/rubric.md` section by section: the bullet formula, verb discipline, the recency
budget, summary, skills block, ATS mechanics, consistency sweep.

**The truth lock (§0) governs everything.** Reordering, tightening, sharpening, and merging are in
scope. Adding a fact the source does not contain is not. Every missing impact number becomes:

```markdown
- Rebuilt the authentication system, fixing a defect affecting 20% of users [[TODO: how long had it been live? support tickets deflected?]]
```

Work top-down so the strongest material is settled first, and cut from the bottom of the document
upward when over length.

### Step 5 — Render and check the length

```bash
python3 .claude/skills/upgrade-resume/scripts/render_resume.py ~/Documents/resume/master.md \
  -o ~/Documents/resume/Rhidzkhan_Ahmad_Resume.pdf --density normal
```

The script prints the page count. Over budget → try `--density compact`, then cut the oldest roles
to one line each. Never solve length by thinning the recent roles.

`compact` is the normal landing spot for a 10+ year history — reaching for it is not a failure. In
practice the cuts that actually buy pages, in order: collapsing pre-last-decade roles into a
one-line-per-role **Early Career** block, deleting a Key Achievements section that restates bullets
already in the roles, folding per-project `Stack:`/`Arch:` prose into a single italic meta line, and
trimming exhaustive cloud-service enumerations out of the skills block.

### Step 6 — Snapshot and report

Copy `master.md` and the PDF into `versions/<today>/` and write `CHANGES.md` there containing:

- **Rewrites** — a before → after table for every bullet that changed materially.
- **Cuts** — what was removed or compressed, and why.
- **Flags** — derived-number disagreements and anything questionable that was left alone (§9).
- **Open TODOs** — every `[[TODO: ...]]`, as a numbered list of questions for the user.

Then tell the user, in the reply: the new page count, the headline changes, and the TODO list as
actual questions. The TODOs are the handoff — they are the facts only the user knows.

### Step 7 — Close the TODOs

When the user supplies the real numbers, fold them in and re-render with `--final`, which refuses
to build while any marker remains:

```bash
python3 .claude/skills/upgrade-resume/scripts/render_resume.py ~/Documents/resume/master.md \
  -o ~/Documents/resume/Rhidzkhan_Ahmad_Resume.pdf --final
```

A clean `--final` render is the definition of done.

---

## Notes & gotchas

- **Stdlib only.** No pip installs. PDF generation is headless Chrome
  (`/Applications/Google Chrome.app/...`), which is already on this machine; Chromium, Edge, and
  Brave work as fallbacks. `--html-only` skips the PDF if no browser is available.
- **Headless Chrome writes the PDF and then does not reliably exit.** The renderer therefore polls
  for the output file, waits for its size to settle, and stops the process itself — the PDF on disk
  is the verdict, never the exit code. A render takes ~1.5s. If you ever call Chrome directly
  (`--print-to-pdf`, `--dump-dom`, `--screenshot`), bound it yourself or it will hang the turn.
  `--timeout` (default 45s) is the upper bound.
- **Chrome PDFs keep a real text layer**, which is the whole ATS requirement. Do not "improve" the
  pipeline into an image-based or LaTeX render without checking text extraction still works.
- **There is no PDF rasteriser on this machine** (`pdftoppm`/poppler is absent), so the PDF cannot
  be eyeballed page by page. The printed page count is the length check — trust it; it reads the
  PDF's own `/Count` field. Inspect layout by grepping the emitted `.html` instead.
- **The heading row is flexbox, not a table** — the extracted text still reads in order. Keep it
  that way; a real `<table>` is an ATS parse hazard.
- `master.md` is the source of truth. Edits made directly to the `.pdf` or `.html` are lost on the
  next render — the renderer rebuilds both from the Markdown every time.
- **Do not touch employer names, titles, dates, or degrees** (rubric §9). If one looks wrong, ask.
- Density below `compact` is not offered on purpose: past that point the page is a grey wall and
  the real fix is cutting content.
- The skill is deliberately *not* job-posting-aware. Tailoring to a specific role is a different
  job with a different failure mode (keyword stuffing) — build it as a sibling skill if wanted.
