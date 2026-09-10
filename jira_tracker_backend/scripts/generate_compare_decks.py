#!/usr/bin/env python
"""Generate ONE combined sprint closure/kickoff report (Markdown) for all boards (NEX, STH).

Drives the tracker's compare pipeline outside FastAPI. For each board it auto-picks the two most
recent sprints (closing = 2nd-latest, kickoff = latest by snapshot date) and computes the compare
data, then — in two passes — renders a single combined Markdown report: an org roll-up followed by
a full per-board section each. The two prose sections (Key Achievements, Roadblocks) are authored
directly in the narrative JSONs, so NO ANTHROPIC_API_KEY is needed.

Usage (run from anywhere with the repo .venv):

    # Pass A — write the deterministic data markdown for each board to the scratchpad.
    #          Claude reads these, authors <key>_narrative.json alongside them.
    python scripts/generate_compare_decks.py --pass a

    # Pass B — render the combined report from the authored narratives, save to sprint_report/.
    python scripts/generate_compare_decks.py --pass b

Optional per-board accomplishments notes: drop a `<key>_accomplishments.txt` in the
scratchpad (one bullet per line). Pass B prepends those lines to that board's
achievements ahead of the ticket-derived bullets (belt-and-suspenders — Claude also
weaves them into the narrative JSON directly).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# --- bootstrap: run as if from the repo root so ./data and projects.yaml resolve ---
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from sqlalchemy import func  # noqa: E402

from app.database import get_engine  # noqa: E402
from app.main import _compute_sprint_compare  # noqa: E402
from app.models import DailySnapshot  # noqa: E402
from app.projects import resolve_cfg  # noqa: E402
from app.report_render import render_combined_markdown, render_markdown  # noqa: E402

BOARDS = ["NEX", "STH"]

OUTPUT_DIR = os.path.expanduser("~/Documents/sprint_report")
# Stable working dir for the intermediate compare markdown + authored narrative JSONs,
# so the two passes always agree regardless of which session runs them.
SCRATCH = os.path.join(OUTPUT_DIR, ".work")


def _pick_sprints(db) -> tuple[str, str]:
    """(closing, kickoff) = the two most recent distinct sprints by latest snapshot date.

    kickoff = latest, closing = 2nd-latest. Raises if fewer than two sprints exist.
    """
    rows = (
        db.query(DailySnapshot.sprint_name, func.max(DailySnapshot.snapshot_date))
        .filter(DailySnapshot.sprint_name.isnot(None), DailySnapshot.sprint_name != "")
        .group_by(DailySnapshot.sprint_name)
        .order_by(func.max(DailySnapshot.snapshot_date).desc())
        .all()
    )
    if len(rows) < 2:
        raise SystemExit(f"Need at least two sprints; found {len(rows)}: {[r[0] for r in rows]}")
    kickoff, closing = rows[0][0], rows[1][0]
    return closing, kickoff


def _slug(sprint_name: str) -> str:
    """'NEX Sprint 3' -> 'Sprint3' for the filename."""
    return sprint_name.split(" ", 1)[-1].replace(" ", "") if " " in sprint_name else sprint_name


def _compute(key: str):
    """Resolve cfg, open a session, auto-pick sprints, return (cfg, closing, kickoff, compare)."""
    cfg = resolve_cfg(key)
    if cfg is None:
        raise SystemExit(f"Unknown board '{key}'.")
    _, maker = get_engine(cfg.key, cfg.db_file)
    db = maker()
    try:
        closing, kickoff = _pick_sprints(db)
        compare = _compute_sprint_compare(db, cfg, closing, kickoff, assignees=None)
    finally:
        db.close()
    return cfg, closing, kickoff, compare


def run_pass_a() -> None:
    os.makedirs(SCRATCH, exist_ok=True)
    for key in BOARDS:
        cfg, closing, kickoff, compare = _compute(key)
        md = render_markdown(compare)
        path = os.path.join(SCRATCH, f"{key}_compare.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"[{key}] closing={closing!r} kickoff={kickoff!r} -> {path}")


def _load_notes(key: str) -> list[str]:
    path = os.path.join(SCRATCH, f"{key}_accomplishments.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [ln.strip().lstrip("-• ").strip() for ln in fh if ln.strip()]


def run_pass_b() -> None:
    """Build ONE combined Markdown report: an org roll-up + each board's full section."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    entries = []
    for key in BOARDS:
        cfg, closing, kickoff, compare = _compute(key)

        narrative_path = os.path.join(SCRATCH, f"{key}_narrative.json")
        if not os.path.exists(narrative_path):
            raise SystemExit(
                f"Missing {narrative_path}. Run pass A, author the narrative JSON, then re-run pass B."
            )
        with open(narrative_path, "r", encoding="utf-8") as fh:
            narrative = json.load(fh)

        # Prepend any day-of accomplishments ahead of the ticket-derived bullets.
        notes = _load_notes(key)
        if notes:
            narrative["achievements"] = notes + list(narrative.get("achievements", []))

        entries.append({"name": cfg.name, "compare": compare, "narrative": narrative})
        print(f"[{key}] closing={closing!r} kickoff={kickoff!r} -> section added")

    md = render_combined_markdown(entries)
    gen_on = entries[0]["compare"].generated_on.isoformat()
    out = os.path.join(OUTPUT_DIR, f"AllBoards_Sprint_Report_{gen_on}.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"\nCombined report ({len(entries)} boards) -> {out} ({len(md)} chars)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pass", dest="phase", choices=["a", "b"], required=True,
                    help="a = write compare markdown; b = build decks from narratives")
    args = ap.parse_args()
    if args.phase == "a":
        run_pass_a()
    else:
        run_pass_b()


if __name__ == "__main__":
    main()
