#!/usr/bin/env python3
"""Push a weekly worklog's per-developer TICKET COUNTS into the Capacity Tracker grid.

The other half of the worklog run. `build_worklog_xlsx.py` turns a /git-list-merge-pr
report into a timesheet measured in HOURS; this turns the same report into the one number
the dashboard's capacity grid is actually planned in — the count of distinct Jira tickets
a developer shipped in the sprint — and writes it to `PUT /api/{board}/capacity/actual`.

Three things make it more than a loop over an HTTP call:

1. **Hours are the wrong unit and must not leak here.** The Timesheet's hours are estimates
   sized from commit volume; the grid's Capacity column is a ticket count against
   `dev_target_default` (10/sprint). Writing hours into it would silently redefine the
   column. Only distinct ticket keys are counted, and a PR carrying no `STH-`/`NEX-` key
   contributes nothing — it is counted separately and reported, never rounded in.

2. **Names do not match across the two systems.** The report is keyed by GitHub login, the
   grid by a board-specific developer string, and `developers.json` (the Timesheet's
   display names) disagrees with the grid on most of the roster. `capacity_map.json` is the
   bridge; an unmapped login is reported, never guessed into a write.

3. **The cell being written may hold a hand-typed number.** Actuals are human input, so
   every write is a potential overwrite. Nothing is sent without `--apply`; the default run
   prints the `current -> new` diff and exits, which is the only view that shows what a real
   run would destroy.

Sectioning, env-sync dropping, and ticket grouping are NOT reimplemented — they are imported
from `build_worklog_xlsx` so the counts here can never drift from the sheet built beside them.

    # see what would be written (default — writes nothing)
    /git-list-merge-pr | python3 reference/push_capacity.py

    # actually write it
    /git-list-merge-pr | python3 reference/push_capacity.py --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from build_worklog_xlsx import (
    filter_developers,
    group_work_items,
    parse_report,
)

MAP_PATH = Path(__file__).with_name("capacity_map.json")
DEFAULT_BASE = "http://localhost:8000"
TIMEOUT_SECONDS = 30
# group_work_items keys a ticketless PR as `~pr:<repo>#<number>` so it still gets a
# timesheet row. The grid counts tickets, so that prefix is what gets excluded here.
NO_TICKET_PREFIX = "~pr:"


def load_map():
    """The login -> per-board grid-name bridge. Absent file is fatal: guessing names writes
    to the wrong developer, and a 404 is the *lucky* outcome of a wrong guess."""
    if not MAP_PATH.exists():
        sys.exit(f"error: {MAP_PATH.name} not found beside this script.")
    with open(MAP_PATH, encoding="utf-8") as handle:
        boards = json.load(handle).get("boards", {})
    if not boards:
        sys.exit(f"error: {MAP_PATH.name} declares no boards.")
    return boards


def ticket_counts(people):
    """`{(login, section): (ticket_count, ticketless_pr_count)}` from grouped work items.

    `people` arrives already sectioned per work item and already stripped of env-sync PRs,
    because it comes straight from the generator's own grouping.
    """
    counts = {}
    for (login, section), items in people.items():
        tickets = [key for key in items if not key.startswith(NO_TICKET_PREFIX)]
        counts[(login, section)] = (len(tickets), len(items) - len(tickets))
    return counts


def monday_of(day):
    """The Monday of `day`'s week — the same week the output filename is named for."""
    return day - dt.timedelta(days=day.weekday())


def fetch_grid(base, board):
    """This board's live capacity grid, or None when the board cannot be read."""
    url = f"{base}/api/{board}/capacity"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ! cannot read {board} grid at {url}: {exc}", file=sys.stderr)
        return None


def sprint_for(grid, day):
    """The grid's sprint whose window contains `day`, or None if the day is off the grid.

    Matched by date range rather than by `is_current` so re-running a past week lands on
    the sprint that week belonged to instead of on today's.
    """
    stamp = day.isoformat()
    for sprint in grid.get("sprints", []):
        if sprint["start"] <= stamp <= sprint["end"]:
            return sprint
    return None


def stored_actual(grid, developer, sprint_number):
    """The cell's current value, and whether the cell exists at all.

    Returns `(exists, value)`. The distinction matters: a developer who is not on the grid
    cannot be written to (the API answers 404), while one whose cell is merely blank can.
    """
    for row in grid.get("developers", []):
        if row["developer"] != developer:
            continue
        for cell in row["cells"]:
            if cell["sprint_number"] == sprint_number:
                return True, cell.get("actual")
        return False, None
    return False, None


def put_actual(base, board, sprint_number, developer, value):
    """Write one cell. Returns None on success, or the error text on failure."""
    payload = json.dumps(
        {"sprint_number": sprint_number, "developer": developer, "value": value}
    ).encode()
    request = urllib.request.Request(
        f"{base}/api/{board}/capacity/actual",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read()
        return None
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
    except (urllib.error.URLError, OSError) as exc:
        return str(exc)


def plan_board(section, board_cfg, counts, base, day):
    """Everything this board would have written, as `(writes, notes)`.

    Resolving the grid once per board keeps the pass to one read per board plus one write
    per developer, and lets every skip be decided against real grid state rather than
    against an assumption about who is on it.
    """
    board = board_cfg["key"]
    logins = board_cfg.get("logins", {})
    notes = []

    grid = fetch_grid(base, board)
    if grid is None:
        return [], [f"{board}: grid unreadable — nothing planned for this board."]

    sprint = sprint_for(grid, day)
    if sprint is None:
        return [], [f"{board}: {day.isoformat()} falls outside the grid's sprint range."]

    writes = []
    for (login, item_section), (tickets, ticketless) in sorted(counts.items()):
        if item_section != section:
            continue
        if ticketless:
            notes.append(
                f"{board}: {login} has {ticketless} PR(s) with no ticket key — not counted."
            )
        developer = logins.get(login)
        if not developer:
            notes.append(
                f"{board}: {login} is not in capacity_map.json — {tickets} ticket(s) NOT written."
            )
            continue
        exists, current = stored_actual(grid, developer, sprint["number"])
        if not exists:
            notes.append(
                f"{board}: '{developer}' ({login}) has no cell in sprint {sprint['number']} "
                f"— {tickets} ticket(s) NOT written."
            )
            continue
        writes.append(
            {"board": board, "sprint": sprint["number"], "developer": developer,
             "login": login, "current": current, "value": tickets}
        )
    return writes, notes


def render(writes, notes, applying):
    """Print the plan, then the notes. Notes are never swallowed — each one is a developer's
    work that the grid will not show."""
    verb = "WRITING" if applying else "would write"
    if not writes:
        print("No capacity cells to write.")
    for write in writes:
        was = "blank" if write["current"] is None else write["current"]
        print(
            f"  {verb}  {write['board']} sprint {write['sprint']}  "
            f"{write['developer']:<24} {was} -> {write['value']}"
        )
    sys.stdout.flush()   # notes go to stderr; without this they interleave above the plan
    for note in notes:
        print(f"  ! {note}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Push per-developer ticket counts from a git-list-merge-pr report "
                    "into the Capacity Tracker. Writes nothing without --apply.")
    parser.add_argument("--report", default="",
                        help="Read the report from a file instead of stdin.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually PUT the values. Without it this is a dry run.")
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help=f"Tracker API base URL (default {DEFAULT_BASE}).")
    parser.add_argument("--sprint-date", default="",
                        help="YYYY-MM-DD inside the target sprint (default: this week's Monday).")
    parser.add_argument("--only", default="",
                        help="Comma-separated logins to keep, as in build_worklog_xlsx.py.")
    parser.add_argument("--exclude", default="",
                        help="Comma-separated logins to drop.")
    parser.add_argument("--all-states", action="store_true",
                        help="Count OPEN/CLOSED PRs too (default: MERGED only).")
    args = parser.parse_args(argv)

    if args.sprint_date:
        day = dt.date.fromisoformat(args.sprint_date)
    else:
        day = monday_of(dt.date.today())

    # Printed before the report is read so every warning below it lands under the header.
    print(f"Capacity push — sprint containing {day.isoformat()}"
          f"{'' if args.apply else '  (DRY RUN — nothing will be written)'}", flush=True)

    if args.report:
        with open(args.report, encoding="utf-8") as handle:
            rows = parse_report(handle)
    elif sys.stdin.isatty():
        parser.error("no report on stdin — pipe `git-list-merge-pr` in, or pass --report <file>")
    else:
        rows = parse_report(sys.stdin)

    if not args.all_states:
        rows = [row for row in rows if row["state"] == "MERGED"]
    if not rows:
        sys.exit("error: no PRs parsed from the report — nothing to push.")

    wanted = [w.strip() for w in args.only.split(",") if w.strip()]
    excluded = [e.strip() for e in args.exclude.split(",") if e.strip()]
    rows, unmatched = filter_developers(rows, wanted, excluded)
    for name in unmatched:
        print(f"  ! '{name}' authored no PR in this report — filter had no effect.",
              file=sys.stderr)

    counts = ticket_counts(group_work_items(rows))
    boards = load_map()

    all_writes, all_notes = [], []
    for section, board_cfg in boards.items():
        writes, notes = plan_board(section, board_cfg, counts, args.base, day)
        all_writes.extend(writes)
        all_notes.extend(notes)

    render(all_writes, all_notes, args.apply)

    if not args.apply:
        print("\nRe-run with --apply to write these values.")
        return 0

    failures = 0
    for write in all_writes:
        error = put_actual(args.base, write["board"], write["sprint"],
                           write["developer"], write["value"])
        if error:
            failures += 1
            print(f"  ! FAILED {write['board']} {write['developer']}: {error}",
                  file=sys.stderr)
    print(f"\nWrote {len(all_writes) - failures}/{len(all_writes)} cells.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
