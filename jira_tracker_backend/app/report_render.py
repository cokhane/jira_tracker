"""Report rendering for the sprint-compare and weekly-QA reports.

Two report families live here:

- **Sprint-compare (Markdown)** — `render_combined_markdown` builds one all-boards report
  (org roll-up + a per-board section each) directly as Markdown. `render_markdown` /
  `render_deck_markdown` are the single-board data summaries it and the API endpoints reuse.
  The two prose sections (achievements, roadblocks) come from pre-authored narrative JSON, so
  no API key is required.
- **Weekly QA deck (PPTX)** — `build_weekly_pptx` renders the weekly QA activity deck via
  python-pptx, with Claude authoring its prose sections through structured outputs.

Every number/table is rendered deterministically from the report data so the figures are
always faithful; the LLM only ever writes prose.
"""
from __future__ import annotations

import json

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from app import schemas


class LlmNotConfigured(RuntimeError):
    """Raised when no Anthropic API key is available for the PPTX step."""


# ---- Alfa Kinetic palette (mirrors src/report.js) ----
INK = RGBColor(0x2E, 0x1A, 0x0E)
CREAM = RGBColor(0xFB, 0xF6, 0xEF)
CARD = RGBColor(0xF7, 0xEC, 0xE4)
CARD_LINE = RGBColor(0xEC, 0xD9, 0xC9)
ACCENT = RGBColor(0xB5, 0x53, 0x1F)
ACCENT_SOFT = RGBColor(0xC9, 0x70, 0x2F)
MUTED = RGBColor(0x8A, 0x6A, 0x54)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

EMU_W = Inches(13.333)
EMU_H = Inches(7.5)
MARGIN = Inches(0.7)


# ---------- sprint-compare markdown ----------


def render_markdown(c: schemas.SprintCompareOut) -> str:
    """Deterministic markdown summary of the two boards — the grounding for the narrative."""
    lines: list[str] = []
    lines.append(f"# {c.project_name} — Sprint Closure & Kickoff")
    lines.append("")
    lines.append(f"- Closing sprint: {c.closing.sprint_name}")
    lines.append(f"- Kickoff sprint: {c.kickoff.sprint_name}")
    lines.append(f"- Completed (closing): {c.completed}")
    lines.append(f"- Carry-over into kickoff: {c.carry_over}")
    lines.append(f"- New work (kickoff): {c.new_work}")
    lines.append(f"- Projects covered: {c.projects_covered}")
    lines.append("")
    lines.append("## Closing — completed by project")
    for p in c.closing.projects:
        lines.append(f"- {p.name}: {p.count} ({p.pct}%)")
    lines.append("")
    lines.append("## Kickoff — committed by type")
    for t in c.kickoff.types:
        lines.append(f"- {t.type}: {t.count}")
    lines.append("")
    lines.append("## Closing — team performance")
    for a in c.closing.assignees:
        lines.append(f"- {a.name}: {a.total} tickets, {a.completed} completed ({a.pct}%)")
    lines.append("")
    lines.append("## Closing — developer delivery (furthest stage by hand-off)")
    for d in c.closing.delivery:
        lines.append(f"- {d.name}: {d.total} tickets (CR {d.code_review}, QA {d.qa_testing}, "
                     f"Merged {d.merged}, Deploy {d.deployment}, Done {d.done})")
    lines.append("")
    lines.append("## Closing — completed ticket titles (source for achievements)")
    for it in c.closing.completed_items:
        lines.append(f"- {it.key}: {it.title} ({it.developer})")
    lines.append("")
    lines.append("## Closing — blocked ticket titles (source for roadblocks)")
    for it in c.closing.blocked_items:
        lines.append(f"- {it.key}: {it.title} ({it.developer})")
    return "\n".join(lines)


def render_deck_markdown(c: schemas.SprintCompareOut) -> str:
    """Full 9-slide deck content as Markdown — for pasting into another LLM context
    (or a slides skill) to build the .pptx without this backend calling any API."""
    L: list[str] = []
    a = L.append

    a(f"# {c.project_name} — {c.closing.sprint_name} Closure · {c.kickoff.sprint_name} Kickoff")
    a("")
    a("> **Instruction for the assistant reading this:** turn the content below into an "
      "**11-slide PowerPoint deck**, one slide per `## Slide N` section, in this exact order. "
      "Use the Alfa Kinetic theme — ink `#2E1A0E`, cream background `#FBF6EF`, cards `#F7ECE4`, "
      "accent `#B5531F`, muted `#8A6A54`; serif (Georgia) headings; stat cards for the number "
      "grids; tables where shown. Keep every figure exactly as written.")
    a("")
    a(f"- Closing sprint: **{c.closing.sprint_name}** ({_md_range(c.closing)})")
    a(f"- Kickoff sprint: **{c.kickoff.sprint_name}** ({_md_range(c.kickoff)})")
    a(f"- Generated: {c.generated_on.isoformat()}")
    a("")

    # 1. Overview
    a("## Slide 1 — Overview (title)")
    a(f"- Header: ANERVEA / **{c.project_name}** / "
      f"{c.closing.sprint_name} CLOSURE · {c.kickoff.sprint_name} KICKOFF")
    a("- Stat cards:")
    a(f"  - Completed: **{c.completed}** ({c.closing.sprint_name})")
    a(f"  - Carry-over: **{c.carry_over}** (into {c.kickoff.sprint_name})")
    a(f"  - New work: **{c.new_work}** ({c.kickoff.sprint_name})")
    a(f"  - Projects: **{c.projects_covered}** (covered)")
    a("")

    # 2. Closure at a glance
    a("## Slide 2 — Closure at a Glance")
    a(f"- Tickets completed: **{c.completed}**")
    a(f"- Carry-over: **{c.carry_over}** into {c.kickoff.sprint_name}")
    a(f"- New sprint work: **{c.new_work}**")
    a("- Projects covered:")
    for p in c.closing.projects:
        a(f"  - {p.name}: {p.count} tickets")
    a(f"- Note: Team velocity — {c.completed} tickets closed in {c.closing.sprint_name}, "
      f"{c.carry_over} carry-overs into {c.kickoff.sprint_name}.")
    a("")

    # 3. Completed work by project
    a(f"## Slide 3 — {c.closing.sprint_name}: Completed Work by Project")
    a("")
    a("| Project | Tickets | % of sprint |")
    a("|---|---|---|")
    for p in c.closing.projects:
        a(f"| {p.name} | {p.count} | {p.pct}% |")
    a("")

    # 4. Committed work (kickoff)
    a(f"## Slide 4 — {c.kickoff.sprint_name}: Committed Work ({c.kickoff.total} tickets)")
    a("- Stat cards:")
    for t in c.kickoff.types:
        a(f"  - {t.type}: **{t.count}** tickets")
    a("")

    # 5. Team performance
    a(f"## Slide 5 — Team Performance ({c.closing.sprint_name})")
    if c.closing.assignees:
        top = max(c.closing.assignees, key=lambda x: (x.completed, x.total))
        if top.completed:
            a(f"- Most completed: **{top.name}** — {top.completed} completed of "
              f"{top.total} assigned")
        else:
            a("- No tickets were completed by the monitored roster this sprint.")
    a("")
    a("| # | Engineer | Assigned | Completed | % of Sprint |")
    a("|---|---|---|---|---|")
    for i, x in enumerate(c.closing.assignees, 1):
        a(f"| {i} | {x.name} | {x.total} | {x.completed} | {x.pct}% |")
    a("")
    if c.closing.assignees:
        a(f"- **% of Sprint** = share of all **{c.closing.total}** tickets in "
          f"{c.closing.sprint_name} (every contributor), so the column sums to under 100%.")
        a("")

    # 6. Ticket breakdown
    a("## Slide 6 — Ticket Breakdown")
    a("")
    a("| Team Member | Assigned | Completed | Incomplete |")
    a("|---|---|---|---|")
    ta = tc = ti = 0
    for x in c.closing.breakdown:
        a(f"| {x.name} | {x.assigned} | {x.completed} | {x.incomplete} |")
        ta += x.assigned; tc += x.completed; ti += x.incomplete
    a(f"| **TOTAL** | **{ta}** | **{tc}** | **{ti}** |")
    rate = round(tc / ta * 100, 1) if ta else 0.0
    a("")
    a(f"- Overview: Total assigned **{ta}** · Total completed **{tc}** · "
      f"Total incomplete **{ti}** · Completion rate **{rate}%**")
    a("")

    # 7-8. Developer delivery funnel (closing + kickoff)
    def _delivery_md(slide_no, sp):
        a(f"## Slide {slide_no} — {sp.sprint_name}: Developer Delivery (furthest stage by hand-off)")
        a("")
        a("| Developer | Code Review | QA Testing | Merged | Deployment | Done | Total |")
        a("|---|---|---|---|---|---|---|")
        t = [0, 0, 0, 0, 0, 0]
        for d in sp.delivery:
            a(f"| {d.name} | {d.code_review} | {d.qa_testing} | {d.merged} | "
              f"{d.deployment} | {d.done} | {d.total} |")
            t = [t[0] + d.code_review, t[1] + d.qa_testing, t[2] + d.merged,
                 t[3] + d.deployment, t[4] + d.done, t[5] + d.total]
        a(f"| **TOTAL** | **{t[0]}** | **{t[1]}** | **{t[2]}** | **{t[3]}** | **{t[4]}** | **{t[5]}** |")
        a("- Each ticket is credited to the developer who moved it out of In Progress, counted "
          "once at the furthest stage it reached this sprint.")
        a("")

    _delivery_md(7, c.closing)
    _delivery_md(8, c.kickoff)

    # 9. Key achievements (to be written by the converting context)
    top_proj = c.closing.projects[0].name if c.closing.projects else c.project_name
    a(f"## Slide 9 — {c.closing.sprint_name}: Key Achievements")
    a(f"- Stat cards: Tickets completed **{c.completed}** · Projects covered "
      f"**{c.projects_covered}** ({top_proj}) · Completion **{c.closing.completion_rate}%**")
    items = c.closing.completed_items
    a(f"- Completed tickets ({len(items)}) — **compile these titles into 5–7 concise "
      "achievement bullets** (group related work, name the outcome, not the ticket id):")
    for it in items:
        a(f"  - {it.key} — {it.title} ({it.developer})")
    if not items:
        a("  - (no completed tickets credited to the roster)")
    a("")

    # 10. Roadblocks — compiled from the blocked tickets
    blocked = c.closing.blocked_items
    a("## Slide 10 — Roadblocks and Next Steps")
    a(f"- Blocked tickets ({len(blocked)}) — **turn these into roadblock cards**; group "
      "related blockers, then for each give Impact · Mitigation · Help needed:")
    for it in blocked:
        a(f"  - {it.key} — {it.title} ({it.developer})")
    if not blocked:
        a("  - (no blocked tickets on the board)")
    a("")

    # 11. Ending
    a("## Slide 11 — Ending")
    a("- Engineering Leadership")
    a("- Distribution: Engineering Team · Product Lead · CTO · QA · DevOps")
    a(f"- Footer: Generated from Jira · {c.generated_on.strftime('%d %B %Y')} · "
      "Confidential — not for external distribution")
    a("")
    return "\n".join(L)


def _md_range(sp) -> str:
    if sp.sprint_start and sp.sprint_end:
        return f"{sp.sprint_start.isoformat()} – {sp.sprint_end.isoformat()}"
    return "dates n/a"



# ---------- combined all-boards markdown report ----------


def _board_markdown(name: str, c: schemas.SprintCompareOut, narrative: dict) -> str:
    """One board's section of the combined report — tables mirroring the deck slides plus the
    pre-authored achievement bullets and roadblock cards. Figures come straight from ``c``."""
    L: list[str] = []
    a = L.append

    a(f"# {name} — {c.closing.sprint_name} Closure · {c.kickoff.sprint_name} Kickoff")
    a("")
    a(f"- Closing sprint: **{c.closing.sprint_name}** ({_md_range(c.closing)})")
    a(f"- Kickoff sprint: **{c.kickoff.sprint_name}** ({_md_range(c.kickoff)})")
    a("")

    # Team Load & Delivery — one combined per-dev table per sprint: board load, the
    # last-action decomposition of Assigned (→ Code Review / QA / Merged / Other), and
    # this-sprint delivery velocity. Rendered identically for the closing and kickoff sprints.
    def _team_table(sp):
        a(f"## {sp.sprint_name} — Team Load & Delivery")
        a("")
        a("_**Assigned / Completed / Incomplete** = cumulative board-state credited to each roster "
          "developer (Completed = dev-done, incl. QA). **→ Code Review / → QA Testing / → Merged / "
          "→ Other** decompose Assigned by where each dev's *last action* left the ticket (→ Merged = "
          "shipped; → Other = In Progress / To Do / Blocked) — they sum to Assigned. **Delivered** = "
          "tickets the dev pushed out of In Progress *this sprint* (velocity)._")
        a("")
        bd = {x.name: x for x in sp.breakdown}
        la = {x.name: x for x in sp.last_action}
        deliv = {d.name: d for d in sp.delivery}
        names = [x.name for x in sp.breakdown]
        names += [d.name for d in sp.delivery if d.name not in bd]
        a("| Developer | Assigned | Completed | Incomplete | → Code Review | → QA Testing | "
          "→ Merged | → Other | Delivered |")
        a("|---|---|---|---|---|---|---|---|---|")
        tot = [0] * 8
        for name in names:
            b = bd.get(name)
            l = la.get(name)
            d = deliv.get(name)
            vals = [
                b.assigned if b else 0, b.completed if b else 0, b.incomplete if b else 0,
                l.code_review if l else 0, l.qa_testing if l else 0, l.merged if l else 0,
                l.other if l else 0, d.total if d else 0,
            ]
            a(f"| {name} | " + " | ".join(str(v) for v in vals) + " |")
            tot = [tot[i] + vals[i] for i in range(8)]
        a(f"| **TOTAL** | " + " | ".join(f"**{v}**" for v in tot) + " |")
        rate = round(tot[1] / tot[0] * 100, 1) if tot[0] else 0.0
        a("")
        a(f"- Total assigned **{tot[0]}** · Total completed **{tot[1]}** · Completion rate **{rate}%**")
        a("")
        if sp.completed != tot[1]:
            a(f"- Scope: counts only tickets credited to a monitored roster developer. Sprint-wide, "
              f"**{sp.completed}** tickets were dev-done in {sp.sprint_name}; the difference of "
              f"**{sp.completed - tot[1]}** is work closed by non-roster or unattributed contributors.")
            a("")

    _team_table(c.closing)
    _team_table(c.kickoff)

    # No Developer KPI scorecard — per-developer KPI/rating tables are not part of any report.

    # Key achievements (pre-authored narrative) — full detail, one bullet each.
    a(f"## {c.closing.sprint_name} → {c.kickoff.sprint_name} — Key Achievements")
    a("")
    for bullet in narrative.get("achievements", []):
        a(f"- {bullet}")
    if not narrative.get("achievements"):
        a("- —")
    a("")

    # Roadblocks — every blocker, condensed to a one-line concern + impact.
    a("## Roadblocks")
    a("")
    roadblocks = narrative.get("roadblocks", [])
    for rb in roadblocks:
        a(f"- **{rb.get('concern', '')}** — {rb.get('impact', '')}")
    if not roadblocks:
        a("- (no roadblocks recorded)")
    a("")

    return "\n".join(L)


def render_combined_markdown(entries: list[dict]) -> str:
    """One combined all-boards Markdown report. Returns the full document as a string.

    ``entries`` = ``[{"name": str, "compare": SprintCompareOut, "narrative": dict}, ...]`` in
    display order. Renders an org roll-up (overview table with a Total row), then each board's
    full section via :func:`_board_markdown`, separated by ``---`` dividers. No API key needed —
    the two prose sections come from each entry's pre-authored ``narrative``.
    """
    if not entries:
        raise ValueError("render_combined_markdown requires at least one board entry.")

    L: list[str] = []
    a = L.append

    gen_on = entries[0]["compare"].generated_on
    total_shipped = sum(e["compare"].shipped_this_sprint for e in entries)
    total_qa = sum(e["compare"].in_qa_at_close for e in entries)
    total_carry = sum(e["compare"].carry_over for e in entries)
    total_new = sum(e["compare"].new_work for e in entries)
    total_committed = sum(e["compare"].committed for e in entries)

    a("# Engineering Sprint Report — All Boards")
    a("")
    a(f"_Generated {gen_on.strftime('%d %B %Y')} · Confidential — not for external distribution_")
    a("")

    # Org overview table
    a("## Overview — All Boards")
    a("")
    a("| Board | Closing → Kickoff | Shipped (sprint) | In QA | Carry-over | New | Committed |")
    a("|---|---|---|---|---|---|---|")
    for e in entries:
        c = e["compare"]
        a(f"| {e['name']} | {c.closing.sprint_name} → {c.kickoff.sprint_name} | "
          f"{c.shipped_this_sprint} | {c.in_qa_at_close} | {c.carry_over} | {c.new_work} | "
          f"{c.committed} |")
    a(f"| **Total** | **{len(entries)} boards** | **{total_shipped}** | **{total_qa}** | "
      f"**{total_carry}** | **{total_new}** | **{total_committed}** |")
    a("")

    # Per-board sections
    for e in entries:
        a("---")
        a("")
        a(_board_markdown(e["name"], e["compare"], e["narrative"]))

    # Closing note
    a("")
    a("---")
    a("")
    a("_**Note:** Committed = Carry-over + New._")
    a("")

    return "\n".join(L)


# ---------- weekly QA activity deck ----------

_QA_NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "accomplishments": {"type": "array", "items": {"type": "string"}},
        "whats_working": {"type": "array", "items": {"type": "string"}},
        "needs_a_look": {"type": "array", "items": {"type": "string"}},
        "roadmap": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["accomplishments", "whats_working", "needs_a_look", "roadmap"],
    "additionalProperties": False,
}


def _weekly_summary(r: schemas.WeeklyQAOut) -> str:
    """Compact deterministic summary of the week — grounding for the LLM narrative."""
    L: list[str] = []
    a = L.append
    a(f"# {r.project_name} — Weekly QA Activity ({r.week_start.isoformat()} to {r.week_end.isoformat()})")
    a("")
    a(f"- Moved forward (closed/deployed/QA-passed): {r.moved_forward}")
    a(f"- Sent back to Dev (failed QA): {r.sent_back}")
    a(f"- Moved to Blocked: {r.blocked}")
    a("")
    a("## Per-engineer")
    for e in r.engineers:
        a(f"- {e.name}: {e.moved_forward} moved forward, {e.sent_back} sent back, {e.blocked} blocked")
    a("")
    a("## Moved-forward ticket titles (source for accomplishments)")
    for it in r.accomplishments:
        a(f"- {it.key}: {it.title} ({it.engineer})")
    return "\n".join(L)


def render_weekly_markdown(r: schemas.WeeklyQAOut) -> str:
    """Full weekly QA deck as Markdown — paste into a slides context, or read as-is."""
    L: list[str] = []
    a = L.append

    a(f"# {r.project_name} — Weekly QA Activity Report")
    a("")
    a("> **Instruction for the assistant reading this:** turn the content below into a "
      "**PowerPoint deck**, one slide per `## Slide N` section, in order. Use the Alfa "
      "Kinetic theme — ink `#2E1A0E`, cream `#FBF6EF`, cards `#F7ECE4`, accent `#B5531F`, "
      "muted `#8A6A54`; serif (Georgia) headings; stat cards for number grids; tables "
      "where shown. Keep every figure exactly as written.")
    a("")
    a(f"- Week: **{r.week_start.isoformat()} – {r.week_end.isoformat()}**")
    a(f"- Generated: {r.generated_on.isoformat()}")
    a("")

    a("## Slide 1 — Overview (title)")
    a(f"- Header: ANERVEA / **{r.project_name}** / WEEKLY QA ACTIVITY")
    a("- Stat cards:")
    a(f"  - Moved forward: **{r.moved_forward}** (closed / deployed / QA-passed)")
    a(f"  - Sent back to Dev: **{r.sent_back}** (failed QA)")
    a(f"  - Moved to Blocked: **{r.blocked}**")
    a("")

    a("## Slide 2 — Tickets Moved This Week")
    a("")
    a("| Movement | Count | What it means |")
    a("|---|---|---|")
    a(f"| Moved forward (Closed/Deployed/QA-passed) | {r.moved_forward} | Passed QA and progressed |")
    a(f"| Sent back to Dev (failed QA) | {r.sent_back} | Failed testing, returned for rework |")
    a(f"| Moved to Blocked | {r.blocked} | Blocked and awaiting resolution |")
    a("")

    a("## Slide 3 — Per-Engineer Breakdown")
    a("")
    a("| Engineer | Moved forward | Sent back | Blocked |")
    a("|---|---|---|---|")
    for e in r.engineers:
        a(f"| {e.name} | {e.moved_forward} | {e.sent_back} | {e.blocked} |")
    if not r.engineers:
        a("| (no engineer activity this week) | 0 | 0 | 0 |")
    a("")

    a("## Slide 4 — Accomplishments")
    a(f"- Moved-forward tickets ({len(r.accomplishments)}) — **compile into 5–7 concise "
      "achievement bullets** (group related work, name the outcome, not the ticket id):")
    for it in r.accomplishments:
        a(f"  - {it.key} — {it.title} ({it.engineer})")
    if not r.accomplishments:
        a("  - (no tickets moved forward this week)")
    a("")

    a("## Slide 5 — Leadership Perspective")
    a("- **What's Working** / **Needs a Look** — write 3 bullets each, grounded in the "
      "numbers above (e.g. sent-back rate, concentration of work on one engineer).")
    a("")

    a("## Slide 6 — What We Need From Leadership")
    if r.asks:
        a("")
        a("| Ask | Owner | Why It Matters | Needed By |")
        a("|---|---|---|---|")
        for k in r.asks:
            a(f"| {k.ask} | {k.owner} | {k.why} | {k.needed_by} |")
    else:
        a("- (no asks provided this week)")
    a("")

    a("## Slide 7 — Roadmap")
    a("- 3–4 forward-looking bullets on QA process / automation / tooling next steps.")
    a("")

    a("## Slide 8 — Ending")
    a("- QA Team · ANERVEA")
    a(f"- Footer: Generated from Jira · {r.generated_on.strftime('%d %B %Y')} · "
      "Confidential — not for external distribution")
    a("")
    return "\n".join(L)


def _author_qa_narrative(r: schemas.WeeklyQAOut, api_key: str, model: str) -> dict:
    """Ask Claude for the weekly deck's prose sections (structured), grounded in data."""
    if not api_key:
        raise LlmNotConfigured(
            "ANTHROPIC_API_KEY is not set. Add it to the backend .env to generate the PPTX."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "You are writing the prose sections of a WEEKLY QA activity report deck, grounded "
        "strictly in the data below. Do not invent numbers or ticket outcomes.\n\n"
        f"{_weekly_summary(r)}\n\n"
        "Produce JSON with:\n"
        "- `accomplishments`: 5-7 concise bullets compiled from the moved-forward ticket "
        "titles — group related tickets into themes, name the outcome. Each one sentence.\n"
        "- `whats_working`: exactly 3 short bullets on what went well this week.\n"
        "- `needs_a_look`: exactly 3 short bullets on risks/concerns (e.g. sent-back rate, "
        "work concentrated on one engineer, blocked tickets).\n"
        "- `roadmap`: 3-4 short forward-looking bullets on QA process/automation next steps."
    )
    resp = client.messages.create(
        model=model,
        max_tokens=3000,
        output_config={"format": {"type": "json_schema", "schema": _QA_NARRATIVE_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


# ---------- python-pptx helpers ----------


def _fill(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def _bg(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def _text(slide, left, top, width, height, runs, *, align=PP_ALIGN.LEFT,
          anchor=MSO_ANCHOR.TOP, wrap=True):
    """runs = list of (text, size_pt, color, bold). Each run is its own paragraph."""
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    for i, (txt, size, color, bold) in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.font.bold = bold
    return box


def _eyebrow_title(slide, eyebrow, title):
    _text(slide, MARGIN, Inches(0.45), EMU_W - 2 * MARGIN, Inches(0.4),
          [(eyebrow.upper(), 12, ACCENT, True)])
    _text(slide, MARGIN, Inches(0.8), EMU_W - 2 * MARGIN, Inches(0.9),
          [(title, 32, INK, True)])


def _stat_cards(slide, cards, top, *, height=Inches(1.9), on_dark=False):
    """cards = list of (label, value, note). Laid out in a row."""
    n = len(cards) or 1
    gap = Inches(0.25)
    usable = EMU_W - 2 * MARGIN - gap * (n - 1)
    w = int(usable / n)
    label_c = ACCENT_SOFT if on_dark else ACCENT
    value_c = WHITE if on_dark else INK
    note_c = RGBColor(0xC9, 0xB8, 0xA8) if on_dark else MUTED
    card_c = RGBColor(0x3A, 0x24, 0x16) if on_dark else CARD
    for i, (label, value, note) in enumerate(cards):
        left = MARGIN + i * (w + gap)
        rect = slide.shapes.add_shape(1, left, top, w, height)  # 1 = rectangle
        _fill(rect, card_c)
        _text(slide, left + Inches(0.25), top + Inches(0.2), w - Inches(0.5), height - Inches(0.4),
              [(str(label).upper(), 11, label_c, True),
               (str(value), 40, value_c, True),
               (str(note), 12, note_c, False)])


def _table(slide, headers, rows, top, *, col_widths=None, height=Inches(4.6)):
    n_rows = len(rows) + 1
    n_cols = len(headers)
    width = EMU_W - 2 * MARGIN
    tbl_shape = slide.shapes.add_table(n_rows, n_cols, MARGIN, top, width, height)
    table = tbl_shape.table
    if col_widths:
        for i, cw in enumerate(col_widths):
            table.columns[i].width = cw
    # header
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = ACCENT
        p = cell.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = str(h)
        r.font.size = Pt(12)
        r.font.bold = True
        r.font.color.rgb = WHITE
    # body
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = CREAM if i % 2 else CARD
            p = cell.text_frame.paragraphs[0]
            r = p.add_run()
            r.text = str(val)
            r.font.size = Pt(11)
            r.font.color.rgb = INK
    return table


def _footer(slide, text, *, on_dark=False):
    _text(slide, MARGIN, EMU_H - Inches(0.55), EMU_W - 2 * MARGIN, Inches(0.4),
          [(text, 10, RGBColor(0xC9, 0xB8, 0xA8) if on_dark else MUTED, False)])


def build_weekly_pptx(r: schemas.WeeklyQAOut, api_key: str, model: str) -> bytes:
    """Build the weekly QA activity deck as a .pptx. Returns raw bytes."""
    narrative = _author_qa_narrative(r, api_key, model)
    week_label = f"{r.week_start.isoformat()} – {r.week_end.isoformat()}"

    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H
    blank = prs.slide_layouts[6]

    # --- Slide 1: Overview (title) ---
    s = prs.slides.add_slide(blank)
    _bg(s, INK)
    _text(s, MARGIN, Inches(1.0), EMU_W - 2 * MARGIN, Inches(0.5),
          [("ANERVEA", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(1.5), EMU_W - 2 * MARGIN, Inches(1.2),
          [(f"{r.project_name} — Weekly QA Activity", 40, WHITE, True)])
    _text(s, MARGIN, Inches(2.9), EMU_W - 2 * MARGIN, Inches(0.4),
          [(week_label, 14, RGBColor(0xD8, 0xC8, 0xBA), False)])
    _stat_cards(s, [
        ("Moved forward", r.moved_forward, "closed / deployed / passed"),
        ("Sent back to Dev", r.sent_back, "failed QA"),
        ("Moved to Blocked", r.blocked, "awaiting resolution"),
    ], Inches(4.4), on_dark=True)
    _footer(s, f"CONFIDENTIAL · {r.generated_on.strftime('%d %B %Y').upper()}", on_dark=True)

    # --- Slide 2: Tickets moved this week ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "Movement", "Tickets Moved This Week")
    _table(s, ["Movement", "Count", "What it means"], [
        ("Moved forward (Closed/Deployed/Passed)", r.moved_forward, "Passed QA and progressed"),
        ("Sent back to Dev (failed QA)", r.sent_back, "Failed testing, returned for rework"),
        ("Moved to Blocked", r.blocked, "Blocked and awaiting resolution"),
    ], Inches(2.0), col_widths=[Inches(5.2), Inches(1.5), Inches(5.2)], height=Inches(2.4))

    # --- Slide 3: Per-engineer breakdown ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "Team · per engineer", "Per-Engineer Breakdown")
    rows = [(e.name, e.moved_forward, e.sent_back, e.blocked) for e in r.engineers] \
        or [("(no activity this week)", 0, 0, 0)]
    _table(s, ["Engineer", "Moved forward", "Sent back", "Blocked"], rows, Inches(1.7),
           col_widths=[Inches(5.9), Inches(2.2), Inches(1.9), Inches(1.9)])

    # --- Slide 4: Accomplishments (LLM) ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "This week", "Accomplishments")
    _stat_cards(s, [
        ("Moved forward", r.moved_forward, "tickets"),
        ("Sent back", r.sent_back, "failed QA"),
        ("Blocked", r.blocked, "tickets"),
    ], Inches(1.9), height=Inches(1.4))
    ach_runs = [(f"•  {a}", 14, INK, False) for a in narrative.get("accomplishments", [])]
    _text(s, MARGIN, Inches(3.6), EMU_W - 2 * MARGIN, Inches(3.4),
          ach_runs or [("•  —", 14, INK, False)])

    # --- Slide 5: Leadership perspective (LLM) ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "Leadership perspective", "What's Working · Needs a Look")
    gap = Inches(0.4)
    w = int((EMU_W - 2 * MARGIN - gap) / 2)
    for i, (title, key) in enumerate([("WHAT'S WORKING", "whats_working"), ("NEEDS A LOOK", "needs_a_look")]):
        left = MARGIN + i * (w + gap)
        rect = s.shapes.add_shape(1, left, Inches(1.9), w, Inches(4.6))
        _fill(rect, CARD)
        runs = [(title, 13, ACCENT, True)]
        runs += [(f"•  {b}", 13, INK, False) for b in narrative.get(key, [])]
        _text(s, left + Inches(0.25), Inches(2.05), w - Inches(0.5), Inches(4.3), runs)

    # --- Slide 6: What we need from leadership ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "Asks", "What We Need From Leadership")
    if r.asks:
        rows = [(k.ask, k.owner, k.why, k.needed_by) for k in r.asks]
        _table(s, ["Ask", "Owner", "Why It Matters", "Needed By"], rows, Inches(1.7),
               col_widths=[Inches(3.4), Inches(2.2), Inches(4.5), Inches(1.8)])
    else:
        _text(s, MARGIN, Inches(2.4), EMU_W - 2 * MARGIN, Inches(0.6),
              [("No asks provided for this week.", 16, MUTED, False)])

    # --- Slide 7: Roadmap (LLM) ---
    s = prs.slides.add_slide(blank)
    _bg(s, CREAM)
    _eyebrow_title(s, "Looking ahead", "Roadmap")
    road_runs = [(f"•  {b}", 15, INK, False) for b in narrative.get("roadmap", [])]
    _text(s, MARGIN, Inches(2.0), EMU_W - 2 * MARGIN, Inches(4.8),
          road_runs or [("•  —", 15, INK, False)])

    # --- Slide 8: Ending ---
    s = prs.slides.add_slide(blank)
    _bg(s, INK)
    _text(s, MARGIN, Inches(2.4), EMU_W - 2 * MARGIN, Inches(0.5),
          [("ANERVEA", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(2.9), EMU_W - 2 * MARGIN, Inches(1.0),
          [("QA Team", 40, WHITE, True)])
    _footer(s, f"Generated from Jira · {r.generated_on.strftime('%d %B %Y')} · "
               "Confidential — not for external distribution", on_dark=True)

    import io
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
