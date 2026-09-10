#!/usr/bin/env python
"""Render the combined All-Boards sprint closure/kickoff report as a PPTX.

Mirrors the enriched Markdown (AllBoards_Sprint_Report_<date>.md) slide-for-slide, using the
same Alfa Kinetic theme and python-pptx helpers as the reference NEX_Sprint2_vs_Sprint3.pptx.

For each board (NEX, STH) it recomputes the compare data from the tracker DBs (same
pipeline as generate_compare_decks.py) and pulls the two prose sections — Key Achievements and
Roadblocks — from the pre-authored <key>_narrative.json in the scratchpad. No API key needed.

    python scripts/build_allboards_deck.py
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from pptx import Presentation  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.database import get_engine  # noqa: E402
from app.main import _compute_sprint_compare  # noqa: E402
from app.models import DailySnapshot  # noqa: E402
from app.projects import resolve_cfg  # noqa: E402
from app.report_render import (  # noqa: E402
    ACCENT, ACCENT_SOFT, CARD, CREAM, EMU_H, EMU_W, INK, MARGIN, MUTED, WHITE,
    _bg, _eyebrow_title, _fill, _footer, _stat_cards, _table, _text,
)
from pptx.dml.color import RGBColor  # noqa: E402

BOARDS = ["NEX", "STH"]
NOTE_DARK = RGBColor(0xC9, 0xB8, 0xA8)
SUBTITLE = RGBColor(0xD8, 0xC8, 0xBA)

OUTPUT_DIR = os.path.expanduser("~/Documents/sprint_report")
# Stable working dir shared with generate_compare_decks.py (compare markdown + narratives).
SCRATCH = os.path.join(OUTPUT_DIR, ".work")


def _pick_sprints(db) -> tuple[str, str]:
    rows = (
        db.query(DailySnapshot.sprint_name, func.max(DailySnapshot.snapshot_date))
        .filter(DailySnapshot.sprint_name.isnot(None), DailySnapshot.sprint_name != "")
        .group_by(DailySnapshot.sprint_name)
        .order_by(func.max(DailySnapshot.snapshot_date).desc())
        .all()
    )
    if len(rows) < 2:
        raise SystemExit(f"Need two sprints; found {len(rows)}")
    return rows[1][0], rows[0][0]


def _compute(key: str):
    cfg = resolve_cfg(key)
    _, maker = get_engine(cfg.key, cfg.db_file)
    db = maker()
    try:
        closing, kickoff = _pick_sprints(db)
        compare = _compute_sprint_compare(db, cfg, closing, kickoff, assignees=None)
    finally:
        db.close()
    return cfg, compare


def _date_range(sp) -> str:
    if sp.sprint_start and sp.sprint_end:
        return f"{sp.sprint_start.isoformat()} – {sp.sprint_end.isoformat()}"
    return "dates n/a"


# ---------- slide builders ----------


def _slide(prs, color):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s, color)
    return s


def title_slide(prs, entries, gen_on):
    s = _slide(prs, INK)
    _text(s, MARGIN, Inches(0.85), EMU_W - 2 * MARGIN, Inches(0.5),
          [("ANERVEA", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(1.35), EMU_W - 2 * MARGIN, Inches(1.2),
          [("Engineering Sprint Report", 44, WHITE, True)])
    _text(s, MARGIN, Inches(2.55), EMU_W - 2 * MARGIN, Inches(0.4),
          [("ALL BOARDS  ·  SPRINT CLOSURE & KICKOFF", 14, ACCENT_SOFT, True)])
    board_line = "     ".join(
        f"{e['cfg'].name}:  {e['compare'].closing.sprint_name} → {e['compare'].kickoff.sprint_name}"
        for e in entries
    )
    _text(s, MARGIN, Inches(3.05), EMU_W - 2 * MARGIN, Inches(0.6),
          [(board_line, 12, SUBTITLE, False)])
    total_completed = sum(e["compare"].completed for e in entries)
    total_carry = sum(e["compare"].carry_over for e in entries)
    total_new = sum(e["compare"].new_work for e in entries)
    _stat_cards(s, [
        ("Boards", len(entries), "reporting"),
        ("Completed", total_completed, "all sprints closed"),
        ("Carry-over", total_carry, "into kickoff"),
        ("New work", total_new, "committed"),
    ], Inches(4.4), on_dark=True)
    _footer(s, f"CONFIDENTIAL · {gen_on.strftime('%d %B %Y').upper()}", on_dark=True)


def overview_slide(prs, entries):
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Portfolio · all boards", "Sprint Overview")
    rows = []
    tc = tk = tn = 0
    for e in entries:
        c = e["compare"]
        rows.append((e["cfg"].name,
                     f"{c.closing.sprint_name} → {c.kickoff.sprint_name}",
                     c.completed, c.carry_over, c.new_work))
        tc += c.completed; tk += c.carry_over; tn += c.new_work
    rows.append(("TOTAL", f"{len(entries)} boards", tc, tk, tn))
    _table(s, ["Board", "Closing → Kickoff", "Completed", "Carry-over", "New work"], rows,
           Inches(2.0),
           col_widths=[Inches(2.6), Inches(4.3), Inches(2.0), Inches(2.0), Inches(2.0)],
           height=Inches(2.6))
    _text(s, MARGIN, Inches(5.4), EMU_W - 2 * MARGIN, Inches(1.4),
          [("Across the three boards, {} tickets were completed this cycle. {} items carried "
            "into the kickoff sprints against {} items of genuinely new work, making carry-over "
            "the primary pressure on next-cycle capacity.".format(tc, tk, tn), 14, MUTED, False)])
    _footer(s, "CONFIDENTIAL · ENGINEERING LEADERSHIP")


def board_divider(prs, e):
    c = e["compare"]
    s = _slide(prs, INK)
    _text(s, MARGIN, Inches(1.0), EMU_W - 2 * MARGIN, Inches(0.5),
          [("ANERVEA", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(1.5), EMU_W - 2 * MARGIN, Inches(1.2),
          [(e["cfg"].name, 48, WHITE, True)])
    _text(s, MARGIN, Inches(2.7), EMU_W - 2 * MARGIN, Inches(0.4),
          [(f"{c.closing.sprint_name} CLOSURE  ·  {c.kickoff.sprint_name} KICKOFF", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(3.15), EMU_W - 2 * MARGIN, Inches(0.8),
          [(f"{c.closing.sprint_name}:  {_date_range(c.closing)}", 13, SUBTITLE, False),
           (f"{c.kickoff.sprint_name}:  {_date_range(c.kickoff)}", 13, SUBTITLE, False)])
    _stat_cards(s, [
        ("Completed", c.completed, c.closing.sprint_name),
        ("Carry-over", c.carry_over, f"into {c.kickoff.sprint_name}"),
        ("New work", c.new_work, c.kickoff.sprint_name),
        ("Projects", c.projects_covered, "covered"),
    ], Inches(4.4), on_dark=True)
    _footer(s, f"CONFIDENTIAL · {c.closing.sprint_name}", on_dark=True)


def committed_slide(prs, e):
    c = e["compare"]
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Sprint kickoff", f"{c.kickoff.sprint_name} — Committed Work ({c.kickoff.total} tickets)")
    cards = [(t.type, t.count, "tickets") for t in c.kickoff.types]
    _stat_cards(s, cards, Inches(2.2), height=Inches(1.9))
    _text(s, MARGIN, Inches(4.7), EMU_W - 2 * MARGIN, Inches(1.4),
          [(f"Of the {c.kickoff.total} tickets scoped into {c.kickoff.sprint_name}, "
            f"{c.carry_over} carried over from {c.closing.sprint_name} and "
            f"{c.new_work} are new this sprint.", 14, MUTED, False)])
    _footer(s, f"CONFIDENTIAL · {c.kickoff.sprint_name}")


def kickoff_breakdown_slide(prs, e):
    """Per-assignee assignment breakdown for the kickoff sprint. Skipped if no roster
    developer holds committed work yet."""
    c = e["compare"]
    if not c.kickoff.breakdown or all(x.assigned == 0 for x in c.kickoff.breakdown):
        return
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Team · kickoff assignments",
                   f"{c.kickoff.sprint_name} — Assignment Breakdown")
    rows = []
    ta = tc = ti = 0
    for x in c.kickoff.breakdown:
        rows.append((x.name, x.assigned, x.completed, x.incomplete))
        ta += x.assigned; tc += x.completed; ti += x.incomplete
    rows.append(("TOTAL", ta, tc, ti))
    _table(s, ["Team Member", "Assigned", "Completed", "Incomplete"], rows, Inches(1.9),
           col_widths=[Inches(5.9), Inches(2.0), Inches(2.0), Inches(2.0)], height=Inches(3.3))
    _text(s, MARGIN, Inches(5.5), EMU_W - 2 * MARGIN, Inches(1.2),
          [(f"Committed roster load for {c.kickoff.sprint_name} — assignments as of kickoff; "
            "completion accrues as the sprint progresses.", 14, MUTED, False)])
    _footer(s, f"CONFIDENTIAL · {c.kickoff.sprint_name}")


def breakdown_slide(prs, e):
    c = e["compare"]
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Team · ticket breakdown", f"{c.closing.sprint_name} — Ticket Breakdown")
    rows = []
    ta = tc = ti = 0
    for x in c.closing.breakdown:
        rows.append((x.name, x.assigned, x.completed, x.incomplete))
        ta += x.assigned; tc += x.completed; ti += x.incomplete
    rows.append(("TOTAL", ta, tc, ti))
    rate = round(tc / ta * 100, 1) if ta else 0.0
    _table(s, ["Team Member", "Assigned", "Completed", "Incomplete"], rows, Inches(1.7),
           col_widths=[Inches(5.9), Inches(2.0), Inches(2.0), Inches(2.0)], height=Inches(3.5))
    _stat_cards(s, [
        ("Assigned", ta, ""),
        ("Completed", tc, ""),
        ("Incomplete", ti, ""),
        ("Completion", f"{rate}%", ""),
    ], Inches(5.5), height=Inches(1.2))
    if c.completed != tc:
        _text(s, MARGIN, Inches(6.85), EMU_W - 2 * MARGIN, Inches(0.5),
              [(f"Roster-only view · sprint-wide {c.completed} completed; "
                f"{c.completed - tc} closed by non-roster or unattributed contributors.",
                9, MUTED, False)])


def delivery_slide(prs, e):
    c = e["compare"]
    total = sum(d.total for d in c.closing.delivery)
    if total == 0:
        return
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Developer delivery · furthest stage reached",
                   f"{c.closing.sprint_name} — What Each Developer Delivered")
    rows = []
    t = [0, 0, 0, 0, 0, 0]
    for d in c.closing.delivery:
        if d.total == 0:
            continue
        rows.append((d.name, d.code_review, d.qa_testing, d.merged, d.deployment, d.done, d.total))
        t = [t[0] + d.code_review, t[1] + d.qa_testing, t[2] + d.merged,
             t[3] + d.deployment, t[4] + d.done, t[5] + d.total]
    rows.append(("TOTAL", *t))
    _table(s, ["Developer", "Code Review", "QA", "Merged", "Deploy", "Done", "Total"], rows,
           Inches(1.8),
           col_widths=[Inches(3.5), Inches(1.6), Inches(1.3), Inches(1.5), Inches(1.5),
                       Inches(1.3), Inches(1.2)], height=Inches(3.5))
    _text(s, MARGIN, Inches(5.7), EMU_W - 2 * MARGIN, Inches(0.9),
          [("Each ticket is credited to the developer who moved it out of In Progress, counted "
            "once at the furthest stage it reached this sprint.", 11, MUTED, False)])
    _footer(s, f"CONFIDENTIAL · {c.closing.sprint_name}")


def achievements_slide(prs, e):
    c = e["compare"]
    narrative = e["narrative"]
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Sprint closure", f"{c.closing.sprint_name} — Key Achievements")
    top_proj = c.closing.projects[0].name if c.closing.projects else e["cfg"].name
    _stat_cards(s, [
        ("Tickets completed", c.completed, c.closing.sprint_name),
        ("Projects covered", c.projects_covered, top_proj),
        ("Completion", f"{c.closing.completion_rate}%", "of the sprint"),
    ], Inches(1.9), height=Inches(1.3))
    bullets = narrative.get("achievements", []) or ["—"]
    runs = [(f"•  {b}", 13, INK, False) for b in bullets]
    _text(s, MARGIN, Inches(3.5), EMU_W - 2 * MARGIN, Inches(3.7), runs)


def roadblocks_slide(prs, e):
    c = e["compare"]
    roadblocks = e["narrative"].get("roadblocks", [])
    s = _slide(prs, CREAM)
    _eyebrow_title(s, "Risks & blockers", f"{c.closing.sprint_name} — Roadblocks & Next Steps")
    if not roadblocks:
        _text(s, MARGIN, Inches(2.4), EMU_W - 2 * MARGIN, Inches(0.6),
              [("No roadblocks recorded this sprint.", 16, MUTED, False)])
        return
    n = len(roadblocks)
    top0 = Inches(1.9)
    gap = Inches(0.2)
    avail = EMU_H - top0 - Inches(0.5)
    h = int((avail - gap * (n - 1)) / n)
    for i, rb in enumerate(roadblocks):
        top = top0 + i * (h + gap)
        rect = s.shapes.add_shape(1, MARGIN, top, EMU_W - 2 * MARGIN, h)
        _fill(rect, CARD)
        runs = [(f"{rb.get('id', 'R')} — {rb.get('concern', '')}", 13, ACCENT, True),
                (f"Impact:  {rb.get('impact', '')}", 10.5, INK, False),
                (f"Mitigation:  {rb.get('mitigation', '')}", 10.5, INK, False),
                (f"Help needed:  {rb.get('help_needed', '')}", 10.5, MUTED, False)]
        _text(s, MARGIN + Inches(0.3), top + Inches(0.12), EMU_W - 2 * MARGIN - Inches(0.6),
              h - Inches(0.24), runs)


def closing_slide(prs, gen_on):
    s = _slide(prs, INK)
    _text(s, MARGIN, Inches(2.3), EMU_W - 2 * MARGIN, Inches(0.5),
          [("ANERVEA", 14, ACCENT_SOFT, True)])
    _text(s, MARGIN, Inches(2.8), EMU_W - 2 * MARGIN, Inches(1.0),
          [("Engineering Leadership", 40, WHITE, True)])
    _text(s, MARGIN, Inches(4.0), EMU_W - 2 * MARGIN, Inches(0.4),
          [("DISTRIBUTION   Engineering Team · Product Lead · CTO · QA · DevOps", 12, ACCENT_SOFT, True)])
    _footer(s, f"Generated from Jira · {gen_on.strftime('%d %B %Y')} · "
               "Confidential — not for external distribution", on_dark=True)


def main():
    entries = []
    for key in BOARDS:
        cfg, compare = _compute(key)
        with open(os.path.join(SCRATCH, f"{key}_narrative.json"), encoding="utf-8") as fh:
            narrative = json.load(fh)
        entries.append({"key": key, "cfg": cfg, "compare": compare, "narrative": narrative})

    gen_on = entries[0]["compare"].generated_on

    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H

    title_slide(prs, entries, gen_on)
    overview_slide(prs, entries)
    for e in entries:
        board_divider(prs, e)
        committed_slide(prs, e)
        breakdown_slide(prs, e)
        kickoff_breakdown_slide(prs, e)
        delivery_slide(prs, e)
        achievements_slide(prs, e)
        roadblocks_slide(prs, e)
    closing_slide(prs, gen_on)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, f"AllBoards_Sprint_Report_{gen_on.isoformat()}.pptx")
    prs.save(out)
    print(f"Saved {len(prs.slides._sldIdLst)} slides -> {out}")


if __name__ == "__main__":
    main()
