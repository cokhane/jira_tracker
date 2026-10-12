#!/usr/bin/env python
"""One-time history backfill — fills the gap the nightly job was never running to fill.

Two phases, each independently skippable:

  1. PULL     Re-syncs each board with `current_sprint_only` forced OFF, so the WHOLE
              project lands in `issues` + `status_transitions` instead of only the open
              sprint. projects.yaml is deliberately NOT modified — the override is applied
              to a copy of the ProjectConfig — so the nightly job keeps its fast
              current-sprint pull instead of re-fetching thousands of changelogs every
              night. This phase is slow (one changelog request per issue) and only needs
              to be run once; everything it writes is permanent.

  2. REBUILD  Derives a `daily_snapshots` row-set for every past day from the changelog
              already stored in `status_transitions`, so the Velocity Board's day picker
              reaches back before the first real capture.

Why phase 2 is a RECONSTRUCTION and not a recovery
--------------------------------------------------
Jira has no "board as of date" API; the nightly capture is what normally records it, and
for the days before this tracker ran, nothing did. What the changelog does give us is
every status change with its timestamp, so an issue's status on day D is the `to_status`
of its last transition at or before D — exact, and likewise for `assignee_at`. Everything
else is weaker, and the weaknesses are worth stating plainly:

  - An issue whose changelog we never fetched is simply absent from that day.
  - `summary`, `issue_type`, `epic_*` and `web_url` are copied from the issue as it looks
    TODAY. If a ticket was renamed or moved between epics, the old day shows today's value.
  - Sprint tagging is DERIVED, not recovered. Jira's changelog does not record sprint
    membership, so a rebuilt day is labelled from the board's own weekly sprint calendar
    (`sprint_anchor_date` / `sprint_anchor_number` / `sprint_length_days`) via
    cfg.sprint_for(). This is the identical label GET /snapshots already synthesizes for
    any row without a stored name, so the picker, the KPI tracker and this script all
    agree -- but it is a calendar label, NOT Jira's actual sprint membership. A ticket
    Jira carried over into a later sprint is labelled here by the date it sat on.
    Real captures keep their true Jira sprint name ("NEX Sprint 12") and are untouched,
    so the two appear as separate entries rather than one overwriting the other.

One difference from a live capture is deliberate rather than a defect. Roster filtering
here uses the assignee AS OF THAT DAY (`assignee_at`), while a live capture can only use
the assignee as it stands at capture time. A ticket owned by someone off the roster in
June and reassigned to a roster member in September therefore appears in the live
September capture but not in the reconstructed June days -- which is the historically
truthful answer. Validated against the one real capture we hold (2026-09-14): status
agreed on 146/149 NEX and 346/346 STH rows with zero mismatches, the 3 differences being
exactly this reassignment case.

So every row written by phase 2 carries `reconstructed = 1`, and a chart that needs
measured-only history can filter on it. Real captures are never touched: a day that
already holds a live snapshot is skipped whole, and only reconstructed rows are ever
deleted on a re-run (which makes this script idempotent).

Usage — from the repo root, because app/config.py reads a RELATIVE .env and projects.yaml:

    .venv/bin/python scripts/backfill_history.py                 # both boards, both phases
    .venv/bin/python scripts/backfill_history.py --boards NEX    # one board
    .venv/bin/python scripts/backfill_history.py --skip-pull     # rebuild from what's stored
    .venv/bin/python scripts/backfill_history.py --dry-run       # count rows, write nothing
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# Config reads ".env", "projects.yaml" and "./data" relative to the working directory, so the
# script anchors itself to the backend root and works no matter where it is invoked from.
os.chdir(_ROOT)

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import ProjectConfig  # noqa: E402
from app.database import get_engine  # noqa: E402
from app.models import DailySnapshot, Issue, StatusTransition  # noqa: E402
from app.projects import get_registry, resolve_cfg  # noqa: E402
from app.sync import _parse_jira_dt, run_sync  # noqa: E402


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _each_day(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


# ---------- phase 1: pull the whole project ----------

def pull_full_history(db: Session, cfg: ProjectConfig, key: str) -> None:
    """Sync one board with the current-sprint filter lifted.

    `overrides` is the same dict projects.yaml populates, so forcing the flag on a copy is
    exactly equivalent to having set it in the YAML — without persisting that choice.
    """
    full_cfg = replace(cfg, overrides={**cfg.overrides, "current_sprint_only": False})
    _log(f"{key}: pulling ENTIRE project — one changelog request per issue, expect minutes")
    log = run_sync(db, full_cfg, full=True, with_transitions=True)
    if log.status == "error":
        raise RuntimeError(f"{key}: sync failed: {log.error}")
    _log(f"{key}: fetched={log.fetched} created={log.created_count} updated={log.updated_count}")


# ---------- phase 2: rebuild past days from the changelog ----------

def rebuild_snapshots(
    db: Session, cfg: ProjectConfig, key: str, since: date | None = None, dry_run: bool = False
) -> int:
    """Write a reconstructed snapshot for every past day we can derive. Returns rows written."""
    today = datetime.now(ZoneInfo(cfg.report_timezone)).date()

    first_tr = db.query(func.min(StatusTransition.change_date)).scalar()
    if first_tr is None:
        _log(f"{key}: no transitions stored — nothing to rebuild")
        return 0

    start = since or first_tr
    end = today - timedelta(days=1)  # today belongs to the live capture, not to us
    if start > end:
        _log(f"{key}: nothing to rebuild ({start} is not before {end})")
        return 0

    # Days already holding a REAL capture are off-limits — a measured day always wins.
    real_days = {
        d for (d,) in db.query(DailySnapshot.snapshot_date)
        .filter(DailySnapshot.reconstructed.is_(False)).distinct()
    }

    issues = {i.key: i for i in db.query(Issue).all()}
    # `Issue.created` is Jira's raw ISO string, carrying the REPORTER's offset (often
    # +0530), while a snapshot day is a calendar day in the board's report timezone
    # (+0800). Slicing the first 10 characters would compare an India-local date against a
    # Manila-local day and place ~13-18% of issues on the board one day before they
    # existed. Convert through the same parser the sync uses, then into the report tz.
    tz = ZoneInfo(cfg.report_timezone)
    created_on: dict[str, str] = {}
    for k, i in issues.items():
        dt = _parse_jira_dt(i.created)
        created_on[k] = dt.astimezone(tz).date().isoformat() if dt else ""

    # Ascending, so one forward sweep applies each transition exactly once across all days
    # instead of re-querying per day (which would be days x transitions work).
    trs = db.query(StatusTransition).order_by(StatusTransition.changed_at.asc()).all()

    # An issue's state BEFORE its first move is the `from_*` side of that move.
    initial: dict[str, tuple] = {}
    for t in trs:
        initial.setdefault(t.issue_key, (t.from_status, t.from_category, t.assignee_at))

    monitored = set(cfg.monitored_assignees)
    excluded = set(cfg.excluded_assignees)

    state: dict[str, tuple] = {}
    idx = 0
    written = 0
    rebuilt_days = 0

    for day in _each_day(start, end):
        while idx < len(trs) and trs[idx].change_date <= day:
            t = trs[idx]
            state[t.issue_key] = (t.to_status, t.to_category, t.assignee_at)
            idx += 1

        if day in real_days:
            continue

        iso = day.isoformat()
        # The KPI/report path resolves a sprint by NAME and reads its window off the rows
        # themselves, so a row with no sprint_start/sprint_end yields an empty funnel even
        # when the name matches. Stamp all three from the same calendar GET /snapshots uses.
        sprint_no, sprint_start, sprint_end = cfg.sprint_for(day)
        sprint_label = f"Sprint {sprint_no}"
        rows = []
        for k, issue in issues.items():
            if created_on[k] and created_on[k] > iso:
                continue  # the ticket did not exist yet on this day
            st = state.get(k) or initial.get(k) or (issue.status, issue.status_category, issue.assignee)
            status, category, assignee = st
            assignee = assignee or issue.assignee

            if cfg.snapshot_exclude_done and status == "Done":
                continue
            # Mirrors capture_snapshot's filtering, but on the assignee AS OF THAT DAY:
            # an allow-list drops unassigned tickets, a deny-list keeps them.
            if monitored:
                if assignee not in monitored:
                    continue
            elif assignee in excluded:
                continue

            rows.append({
                "snapshot_date": day, "issue_key": k, "summary": issue.summary,
                "assignee": assignee, "status": status, "status_category": category,
                "issue_type": issue.issue_type, "epic_key": issue.epic_key,
                "epic_name": issue.epic_name, "web_url": issue.web_url,
                "sprint_name": sprint_label,
                "sprint_start": sprint_start, "sprint_end": sprint_end,
                "captured_at": datetime.now(timezone.utc), "reconstructed": True,
            })

        if not dry_run:
            # Idempotent: drop only what a previous run of THIS script wrote for the day.
            db.query(DailySnapshot).filter(
                DailySnapshot.snapshot_date == day,
                DailySnapshot.reconstructed.is_(True),
            ).delete(synchronize_session=False)
            if rows:
                db.bulk_insert_mappings(DailySnapshot, rows)
            db.commit()

        written += len(rows)
        rebuilt_days += 1

    verb = "would write" if dry_run else "wrote"
    _log(f"{key}: {verb} {written} rows across {rebuilt_days} days ({start} -> {end}), "
         f"{len(real_days)} real capture day(s) left untouched")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--boards", help="Comma-separated board keys (default: every board).")
    ap.add_argument("--since", type=date.fromisoformat, help="Earliest day to rebuild (YYYY-MM-DD).")
    ap.add_argument("--skip-pull", action="store_true", help="Skip phase 1.")
    ap.add_argument("--skip-snapshots", action="store_true", help="Skip phase 2.")
    ap.add_argument("--dry-run", action="store_true", help="Phase 2 counts rows without writing.")
    args = ap.parse_args()

    wanted = {k.strip().upper() for k in args.boards.split(",")} if args.boards else None
    entries = [e for e in get_registry() if wanted is None or e.key in wanted]
    if not entries:
        _log(f"No board matches {sorted(wanted or [])} — check projects.yaml")
        return 1

    _log(f"=== backfill start: {', '.join(e.key for e in entries)} ===")
    for entry in entries:
        cfg = resolve_cfg(entry.key)
        _, maker = get_engine(entry.key, entry.db_file)
        db = maker()
        try:
            if not args.skip_pull:
                pull_full_history(db, cfg, entry.key)
            if not args.skip_snapshots:
                rebuild_snapshots(db, cfg, entry.key, since=args.since, dry_run=args.dry_run)
        finally:
            db.close()
    _log("=== backfill done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
