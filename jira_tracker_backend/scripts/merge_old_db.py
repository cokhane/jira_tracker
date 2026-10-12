#!/usr/bin/env python
"""Merge a previous machine's board DB into this one — real history beats reconstruction.

The databases are gitignored (`*.db`, `data/`), so cloning this repo onto a new machine
brings the code but no data: SQLAlchemy's create_all() then makes empty files with the
right schema, which is why a fresh checkout looks populated but holds zero rows. The
previous machine's files are the only copy of what the nightly job actually captured.

What each side is better at, and therefore how the merge resolves:

  daily_snapshots   OLD WINS. Every old row is a real capture -- a photograph of the board
                    including tickets whose changelog we no longer hold, Jira's true sprint
                    names, and the summary/epic as they read THAT DAY. Reconstruction can
                    never reproduce those. Any reconstructed row for a day the old DB
                    covers is deleted first, so a measured day is never half-derived.

  status_transitions, worklogs
                    UNION. Both sides fetched changelogs at different times against a
                    moving project, so each holds entries the other lacks. Merged on the
                    natural unique key; the surrogate id is reassigned to avoid collisions.
                    Worklogs matter especially: a current-sprint-only sync never stored
                    them for older tickets, so this is usually a pure gain.

  sprint_capacity   OLD WINS WHERE IT HAS AN ACTUAL. Actuals are typed in by hand and
                    cannot be derived -- verified: computed delivery matched the stored
                    actuals zero times out of 18. A hand-entered number is evidence; an
                    empty cell here is not. Capacity rides along with its actual so the
                    rolling rule (capacity = avg(prev capacity, prev actual)) stays
                    self-consistent.

  issues            CURRENT WINS. This side has the full-project pull; the old machine ran
                    current_sprint_only and holds a small subset. Only keys missing here
                    are taken, so nothing regresses.

  sync_logs         UNION, for an honest Sync Health history. No natural key, so rows are
                    matched on (started_at, status) to stay idempotent across re-runs.

Idempotent: re-running merges nothing new. Back up before the first run anyway.

    .venv/bin/python scripts/merge_old_db.py --old ../nexus.db --board NEX
    .venv/bin/python scripts/merge_old_db.py --old ../nexus.db --board NEX --dry-run
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from app.projects import get_registry  # noqa: E402


def _cols(con: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({table})")]


def _shared(con: sqlite3.Connection, table: str) -> list[str]:
    """Columns present in BOTH files. Column ORDER differs between machines because
    _migrate_columns appended them in whatever order each DB needed, so every statement
    names its columns explicitly instead of relying on SELECT *."""
    new, old = set(_cols(con, table)), set(_cols(con, table, "old"))
    return [c for c in _cols(con, table) if c in new & old]


def merge(db_path: str, old_path: str, dry: bool) -> None:
    con = sqlite3.connect(db_path)
    con.execute("ATTACH DATABASE ? AS old", (old_path,))
    con.execute("BEGIN")
    report: list[str] = []

    def count(sql: str, *a) -> int:
        return con.execute(sql, a).fetchone()[0]

    # ---- daily_snapshots: real captures replace reconstruction for the days they cover
    days = [r[0] for r in con.execute("SELECT DISTINCT snapshot_date FROM old.daily_snapshots")]
    dropped = count(
        "SELECT COUNT(*) FROM daily_snapshots WHERE reconstructed=1 AND snapshot_date IN "
        "(SELECT DISTINCT snapshot_date FROM old.daily_snapshots)")
    cols = _shared(con, "daily_snapshots")
    collist = ", ".join(cols)
    incoming = count("SELECT COUNT(*) FROM old.daily_snapshots")
    if not dry:
        con.execute("DELETE FROM daily_snapshots WHERE snapshot_date IN "
                    "(SELECT DISTINCT snapshot_date FROM old.daily_snapshots)")
        con.execute(f"INSERT INTO daily_snapshots ({collist}, reconstructed) "
                    f"SELECT {collist}, 0 FROM old.daily_snapshots")
    report.append(f"daily_snapshots: +{incoming} real rows over {len(days)} days "
                  f"(replaced {dropped} reconstructed rows)")

    # ---- transitions + worklogs: union on the natural key, surrogate id reassigned
    for table, key in (("status_transitions", "issue_key, changelog_id"),
                       ("worklogs", "issue_key, worklog_id")):
        cols = [c for c in _shared(con, table) if c != "id"]
        collist = ", ".join(cols)
        match = " AND ".join(f"n.{k.strip()} = o.{k.strip()}" for k in key.split(","))
        added = count(
            f"SELECT COUNT(*) FROM old.{table} o WHERE NOT EXISTS "
            f"(SELECT 1 FROM {table} n WHERE {match})")
        if not dry:
            con.execute(
                f"INSERT INTO {table} ({collist}) SELECT {collist} FROM old.{table} o "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table} n WHERE {match})")
        report.append(f"{table}: +{added} rows")

    # ---- sprint_capacity: a hand-entered actual is evidence; an empty cell is not
    filled = count(
        "SELECT COUNT(*) FROM old.sprint_capacity o WHERE o.actual IS NOT NULL")
    if not dry:
        con.execute("""
            INSERT INTO sprint_capacity (sprint_number, developer, capacity, actual, updated_at)
            SELECT o.sprint_number, o.developer, o.capacity, o.actual, o.updated_at
              FROM old.sprint_capacity o WHERE o.actual IS NOT NULL
            ON CONFLICT(sprint_number, developer) DO UPDATE
               SET actual = excluded.actual, capacity = excluded.capacity,
                   updated_at = excluded.updated_at""")
    report.append(f"sprint_capacity: {filled} cells with a hand-entered actual applied")

    # ---- issues: only keys this side is missing (current holds the full-project pull)
    cols = _shared(con, "issues")
    collist = ", ".join(cols)
    added = count("SELECT COUNT(*) FROM old.issues o "
                  "WHERE NOT EXISTS (SELECT 1 FROM issues n WHERE n.key = o.key)")
    if not dry:
        con.execute(f"INSERT INTO issues ({collist}) SELECT {collist} FROM old.issues o "
                    f"WHERE NOT EXISTS (SELECT 1 FROM issues n WHERE n.key = o.key)")
    report.append(f"issues: +{added} rows (current pull kept where both have the key)")

    # ---- sync_logs: no natural key, so match on the instant a run started
    cols = [c for c in _shared(con, "sync_logs") if c != "id"]
    collist = ", ".join(cols)
    added = count("SELECT COUNT(*) FROM old.sync_logs o WHERE NOT EXISTS "
                  "(SELECT 1 FROM sync_logs n WHERE n.started_at = o.started_at "
                  "AND n.status = o.status)")
    if not dry:
        con.execute(f"INSERT INTO sync_logs ({collist}) SELECT {collist} FROM old.sync_logs o "
                    f"WHERE NOT EXISTS (SELECT 1 FROM sync_logs n "
                    f"WHERE n.started_at = o.started_at AND n.status = o.status)")
    report.append(f"sync_logs: +{added} runs")

    con.execute("ROLLBACK" if dry else "COMMIT")
    con.close()
    for line in report:
        print(("  [dry] " if dry else "  ") + line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", required=True, help="Path to the previous machine's .db file.")
    ap.add_argument("--board", required=True, help="Board key this file belongs to (e.g. NEX).")
    ap.add_argument("--dry-run", action="store_true", help="Report changes, write nothing.")
    args = ap.parse_args()

    entry = next((e for e in get_registry() if e.key == args.board.upper()), None)
    if entry is None:
        print(f"Unknown board {args.board!r}"); return 1
    if not os.path.exists(args.old):
        print(f"No such file: {args.old}"); return 1

    target = os.path.join("data", entry.db_file)
    print(f"=== {entry.key}: {args.old} -> {target} ===")
    merge(target, os.path.abspath(args.old), args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
