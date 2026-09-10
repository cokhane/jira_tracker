#!/usr/bin/env python3
"""Build an XLSX worklog from a git-list-merge-pr report.

Consumes the git-list-merge-pr report on STDIN (pipe the skill's output straight
in) — no intermediate file required. Parses the report (repo markers
`=== <short> ===`, developer markers `### <login> — <N> PRs`, PR lines
`- PR #<n> [<STATE>] <title>` each followed by a URL line that may carry
`(commits: N)`), then emits a three-sheet workbook: a per-PR Worklog, a
per-developer Summary, and a Timesheet. MERGED-only by default.

The workbook path is optional: name it to get all three sheets, or omit it and pass
--timesheet alone to emit only the timesheet.

Usage:
    git-list-merge-pr | python3 build_worklog_xlsx.py --timesheet ~/Desktop/timesheet.xlsx
    git-list-merge-pr | python3 build_worklog_xlsx.py <out.xlsx> [--window "<text>"]
    python3 build_worklog_xlsx.py <out.xlsx> --report report.txt   # optional file fallback
    ... --tsv ~/Desktop/timesheet.tsv
    ... --only "Alfa-Jc,Alfa-Dan"   |   --exclude "anervea-mark,Alfa-Shane"

The report source is STDIN unless --report <path> is given.
"""
import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from itertools import product
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_FULL = {
    "sef": "sethi_enterprise_frontend",
    "seb": "sethi_enterprise_backend",
    "nexus_api": "nexus_api",
    "nexus_panel": "nexus_panel_frontend",
}
TICKET_RE = re.compile(r"\b((?:STH|NEX)-\d+)\b")
PR_RE = re.compile(r"^- PR #(\d+)\s+\[([A-Z]+)\]\s*(.*)$")
# git-list-merge-pr Step 4 emits `### <login> — <N> PRs`; keep only the login. Leaving
# the suffix on splits one developer into a separate identity per repo.
DEV_RE = re.compile(r"^(.*?)(?:\s*[—–-]\s*\d+\s+PRs?)?$")
INLINE_COMMITS_RE = re.compile(r"(\d+)\s+commits")   # env-sync "…, 52 commits — omitted…"
URL_COMMITS_RE = re.compile(r"\(commits:\s*(\d+)\)")
# A leading run of ticket keys — `STH-546, STH-547 : …` renders as `STH-546 / STH-547 : …`
TICKET_RUN_RE = re.compile(r"^\s*((?:STH|NEX)-\d+(?:\s*[,/]\s*(?:STH|NEX)-\d+)*)\s*:\s*")

# Env-sync PRs roll up commits already counted under the individual feature PRs, so they
# stay worklog rows but are never timesheet work items.
ENV_SYNC_REPOS = {"sethi_enterprise_frontend", "sethi_enterprise_backend"}
ENV_SYNC_PREFIXES = ("develop to staging", "develop to uat", "develop to prod")

# Timesheet hour model. Hours are ESTIMATES sized from commit volume — sqrt-damped so a
# 40-commit PR reads bigger than a 4-commit one but not ten times bigger. The team is then
# scaled by ONE global factor pinning the busiest developer at BUSIEST_TOTAL_HOURS, so
# totals stay honest relative to each other: a light week reads light rather than being
# padded up to a 40h target. See SKILL.md — MIN_ITEM_HOURS and BUSIEST_TOTAL_HOURS pull
# against each other, and the floor wins.
UNIT = 0.5
HOUR_BASE = 0.4
HOUR_SCALE = 1.1
MIN_ITEM_HOURS = 1.5              # no work item bills less than this, however small
MAX_ITEM_HOURS = 8.0              # nor more than one working day
BUSIEST_TOTAL_HOURS = 80.0        # the report window spans ten working days

# The light-week floor. Commit volume is a proxy for effort, and it systematically misses the
# work that leaves no PR behind — review, ops, pairing, debugging, meetings — so a developer
# who was on the payroll all window can read as an 8h week. A whole-window total under
# FLOOR_THRESHOLD_HOURS is therefore lifted into [FLOOR_MIN_HOURS, FLOOR_THRESHOLD_HOURS).
# Per DEVELOPER, across every section: flooring each section on its own would bump a
# two-product developer twice and bill them a 60h week.
# The draw is SEEDED from the developer and the window, so re-running the same week rebuilds
# an identical timesheet — a number that moved on every run would be unauditable.
# MAX_ITEM_HOURS caps what is reachable: a developer with N work items cannot exceed N * 8h,
# so a very short item list lands below the floor and says so on stderr.
FLOOR_MIN_HOURS = 30.0
FLOOR_THRESHOLD_HOURS = 40.0
SETTLE_LIMIT = 400                # bounds the drift walk; far above any real item count

NAMES_PATH = Path(__file__).with_name("developers.json")
STANDING_PATH = Path(__file__).with_name("standing_work.json")
STANDING_ORDER = -1               # standing items sort to the top of a developer's block

# Standing work bills a DRAWN number of hours in [MIN, MAX] rather than one fixed figure, so a
# recurring block does not repeat the same suspiciously round total every week. These are the
# fallbacks for an entry that declares no range of its own; the draw is seeded per
# (developer, section, window), so re-running a week rebuilds the same numbers.
STANDING_MIN_HOURS = 6.0
STANDING_MAX_HOURS = 10.0

# The Timesheet groups developers under the product they mostly worked on.
SECTIONS = (
    ("NEXUS", {"nexus_api", "nexus_panel_frontend"}),
    ("SETHI", {"sethi_enterprise_frontend", "sethi_enterprise_backend"}),
)


def parse_report(source):
    """Return a list of PR dicts parsed from a git-list-merge-pr report.

    `source` is any iterable of text lines — a file object, `sys.stdin`, or a
    list of strings — so the report can arrive over a pipe with no file on disk.
    """
    rows = []
    repo = developer = None
    pending = None  # PR whose URL/commit line we still expect

    def flush(commits):
        if pending is not None:
            pending["commits"] = commits
            rows.append(pending)

    for raw in source:
        line = raw.rstrip("\n")
        if line.startswith("=== ") and line.endswith(" ==="):
            flush(pending["commits"] if pending else 0)
            pending = None
            repo = REPO_FULL.get(line[4:-4].strip(), line[4:-4].strip())
            continue
        if line.startswith("### "):
            flush(pending["commits"] if pending else 0)
            pending = None
            developer = DEV_RE.match(line[4:].strip()).group(1).strip()
            continue
        match = PR_RE.match(line)
        if match:
            flush(pending["commits"] if pending else 0)
            number, state, title = match.groups()
            title = title.strip()
            inline = INLINE_COMMITS_RE.search(title)
            ticket = TICKET_RE.search(title)
            pending = {
                "developer": developer,
                "repository": repo,
                "number": int(number),
                "state": state,
                "title": title,
                "ticket": ticket.group(1) if ticket else "",
                "url": "",
                "commits": int(inline.group(1)) if inline else 0,
            }
            continue
        if pending is not None and "https://" in line:
            url = line.strip().split()[0]
            pending["url"] = url
            found = URL_COMMITS_RE.search(line)
            if found:
                pending["commits"] = int(found.group(1))
    flush(pending["commits"] if pending else 0)
    return rows


def filter_developers(rows, wanted, excluded):
    """Apply the --only allowlist then the --exclude denylist, case-insensitively.

    Returns (kept rows, unmatched names). A name matching nobody is reported rather
    than applied silently — a typo'd login would otherwise erase a developer's whole
    week (for --only) or quietly fail to remove them (for --exclude).
    """
    present = {r["developer"].lower(): r["developer"] for r in rows}
    unmatched = [n for n in list(wanted) + list(excluded) if n.lower() not in present]
    if wanted:
        keep = {present[w.lower()] for w in wanted if w.lower() in present}
        rows = [r for r in rows if r["developer"] in keep]
    if excluded:
        drop = {present[e.lower()] for e in excluded if e.lower() in present}
        rows = [r for r in rows if r["developer"] not in drop]
    return rows, unmatched


def load_names():
    """Return the login -> display-name map; a blank value means 'use the login'."""
    if not NAMES_PATH.exists():
        return {}
    payload = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in payload.get("names", {}).items() if v}


def is_env_sync(repository, title):
    lowered = title.strip().lower()
    if repository not in ENV_SYNC_REPOS:
        return False
    return lowered == "develop" or lowered.startswith(ENV_SYNC_PREFIXES)


def timesheet_title(title):
    """Render a leading multi-ticket run as `NEX-1 / NEX-2 : …`; leave the rest alone."""
    run = TICKET_RUN_RE.match(title)
    if not run:
        return title
    tickets = " / ".join(TICKET_RE.findall(run.group(1)))
    return f"{tickets} : {title[run.end():].strip()}"


def section_of(repository):
    """The product section a repo belongs to, or None if it is in neither."""
    for section, repos in SECTIONS:
        if repository in repos:
            return section
    return None


def group_work_items(rows):
    """Collapse PRs into work items keyed by (developer, section, ticket).

    Sectioning is per ITEM, from the repo the work landed in — never per developer.
    Bucketing a whole developer under one section drags their other product's tickets
    along with them, which is how a lone NEX ticket ends up under the SETHI heading.
    """
    people = defaultdict(dict)
    for row in rows:
        section = section_of(row["repository"])
        if section is None or is_env_sync(row["repository"], row["title"]):
            continue
        key = row["ticket"] or f"~pr:{row['repository']}#{row['number']}"
        item = people[(row["developer"], section)].setdefault(
            key, {"title": "", "commits": 0, "number": row["number"]})
        item["commits"] += row["commits"]
        item["number"] = min(item["number"], row["number"])
        if len(row["title"]) > len(item["title"]):
            item["title"] = row["title"]      # the most descriptive of the shared titles
    return people


def clamp_item(value):
    """A single work item never bills outside the per-item band."""
    return min(MAX_ITEM_HOURS, max(MIN_ITEM_HOURS, value))


def load_standing_work():
    """Recurring work that leaves no PR behind — review, branch cleaning, board cleaning."""
    if not STANDING_PATH.exists():
        return {}
    with open(STANDING_PATH, encoding="utf-8") as handle:
        return json.load(handle).get("items", {})


def standing_bounds(entry):
    """The [low, high] hour range for one standing entry.

    A range (`hours_min` / `hours_max`) wins; a scalar `hours` pins both ends to the same
    figure, which is how an entry asks for a fixed number instead of a draw.
    """
    fixed = entry.get("hours")
    low = entry.get("hours_min", fixed if fixed is not None else STANDING_MIN_HOURS)
    high = entry.get("hours_max", fixed if fixed is not None else STANDING_MAX_HOURS)
    return float(low), float(high)


def draw_standing_hours(developer, section, window, low, high):
    """A reproducible draw in [low, high] INCLUSIVE, on the UNIT step.

    Seeded from the developer, the SECTION and the window — never from the clock. The section
    is in the seed so a developer carrying the same standing work on two products draws an
    independent number on each rather than the same figure twice, and both are stable across
    re-runs of the same week.
    """
    steps = int(round((high - low) / UNIT))
    if steps <= 0:
        return low                      # a pinned entry: low == high, nothing to draw
    seed = hashlib.sha256(f"{developer}|{section}|{window}|standing".encode("utf-8"))
    return low + random.Random(int(seed.hexdigest()[:16], 16)).randrange(steps + 1) * UNIT


def inject_standing_items(people, window):
    """Attach each developer's standing items to EVERY section they worked in.

    Recurring work like review and board cleaning is not confined to one product — a developer
    on both NEXUS and SETHI reviews on both — so the block lands once per section rather than
    only on the section where they did the most work.

    These bill a DECLARED number of hours rather than an inferred one, so nothing downstream
    is allowed to move them: the commit weighting skips them and the light-week floor stretches
    only the commit-derived items around them. Drawn or pinned, the figure is still declared.
    """
    standing = load_standing_work()
    if not standing:
        return
    by_developer = defaultdict(list)
    for key in people:
        by_developer[key[0]].append(key)
    for developer, entries in sorted(standing.items()):
        # No keys means nothing merged this window, so there is no block to attach to and
        # `product` yields nothing — a developer is never given a section they did not work in.
        keys = sorted(by_developer.get(developer, []))
        for key, (index, entry) in product(keys, enumerate(entries)):
            low, high = standing_bounds(entry)
            people[key][f"~standing:{index}"] = {
                "title": entry["title"],
                "commits": 0,
                "number": STANDING_ORDER + index,
                "declared_hours": draw_standing_hours(developer, key[1], window, low, high),
            }


def declared_slots(people):
    """The (key, ticket) pairs whose hours are declared and must never be rescaled."""
    return {(key, ticket)
            for key, items in people.items()
            for ticket, item in items.items() if "declared_hours" in item}


def raw_item_hours(people):
    """Hours per work item BEFORE the light-week floor.

    Commit volume is sqrt-damped so a 40-commit PR reads bigger than a 4-commit one but not
    ten times bigger, then the team is scaled by ONE global factor pinning the busiest
    developer at BUSIEST_TOTAL_HOURS, so totals stay honest relative to each other.
    """
    weights = {
        key: {t: HOUR_BASE + HOUR_SCALE * (i["commits"] ** 0.5)
              for t, i in items.items() if "declared_hours" not in i}
        for key, items in people.items()
    }
    per_developer = defaultdict(float)
    for (developer, _), weight in weights.items():
        per_developer[developer] += sum(weight.values())
    scale = BUSIEST_TOTAL_HOURS / (max(per_developer.values(), default=0) or 1)
    hours = {
        key: {t: clamp_item(round(w * scale / UNIT) * UNIT) for t, w in weight.items()}
        for key, weight in weights.items()
    }
    # Declared hours land verbatim — outside the per-item clamps, which describe inferred work.
    for key, items in people.items():
        for ticket, item in items.items():
            if "declared_hours" in item:
                hours[key][ticket] = item["declared_hours"]
    return hours


def draw_target_hours(developer, window):
    """A reproducible draw in [FLOOR_MIN_HOURS, FLOOR_THRESHOLD_HOURS), on the UNIT step.

    Seeded from the developer and the report window, never from the clock: the same week
    re-run must rebuild the same timesheet.
    """
    digest = hashlib.sha256(f"{developer}|{window}".encode("utf-8")).hexdigest()[:16]
    steps = int((FLOOR_THRESHOLD_HOURS - FLOOR_MIN_HOURS) / UNIT)
    return FLOOR_MIN_HOURS + random.Random(int(digest, 16)).randrange(steps) * UNIT


def next_slot_with_headroom(hours, slots, start, step):
    """Index of the first slot at/after `start` that can absorb `step`, or None if none can."""
    for offset in range(len(slots)):
        index = (start + offset) % len(slots)
        key, ticket = slots[index]
        if MIN_ITEM_HOURS <= hours[key][ticket] + step <= MAX_ITEM_HOURS:
            return index
    return None


def settle(hours, keys, target, declared):
    """Walk off the rounding drift in UNIT steps, spreading it round-robin over the items."""
    slots = [(key, ticket) for key in keys for ticket in sorted(hours[key])
             if (key, ticket) not in declared]
    if not slots:
        return
    cursor = 0
    for _ in range(SETTLE_LIMIT):
        drift = target - sum(sum(hours[k].values()) for k in keys)
        if abs(drift) < UNIT:
            return
        step = UNIT if drift > 0 else -UNIT
        cursor = next_slot_with_headroom(hours, slots, cursor, step)
        if cursor is None:
            return                  # every item sits on a clamp; the target is unreachable
        key, ticket = slots[cursor]
        hours[key][ticket] += step
        cursor = (cursor + 1) % len(slots)


def lift_developer(hours, keys, current, target, declared):
    """Scale one developer's INFERRED items toward `target`; declared hours never move.

    Declared hours still count toward the target, so a standing 8h item plus 27h of commit
    work reaches a 35h target by stretching the 27h alone — never by inflating the 8h.
    """
    fixed = sum(hours[k][t] for k in keys for t in hours[k] if (k, t) in declared)
    earned, room = current - fixed, target - fixed
    if earned <= 0 or room <= 0:
        return
    ratio = room / earned
    for key in keys:
        hours[key] = {
            t: h if (key, t) in declared else clamp_item(round(h * ratio / UNIT) * UNIT)
            for t, h in hours[key].items()
        }
    settle(hours, keys, target, declared)


def apply_light_week_floor(hours, window, declared):
    """Lift every developer whose whole-window total reads under the threshold. Mutates `hours`."""
    by_developer = defaultdict(list)
    for key in hours:
        by_developer[key[0]].append(key)
    for developer, keys in sorted(by_developer.items()):
        current = sum(sum(hours[k].values()) for k in keys)
        if current >= FLOOR_THRESHOLD_HOURS or current <= 0:
            continue
        inferred = sum(1 for k in keys for t in hours[k] if (k, t) not in declared)
        fixed = sum(hours[k][t] for k in keys for t in hours[k] if (k, t) in declared)
        reachable = fixed + inferred * MAX_ITEM_HOURS
        target = min(draw_target_hours(developer, window), reachable)
        if target > current:                    # the floor lifts; it never lowers
            lift_developer(hours, keys, current, target, declared)
        # Report against what the items ACTUALLY sum to, not against the target: a developer
        # already pinned at the per-item ceiling never enters the lift, and reporting the
        # target there would claim a floor that was never applied.
        landed = sum(sum(hours[k].values()) for k in keys)
        if landed < FLOOR_MIN_HOURS:
            print(f"note: {developer} has too few work items to reach the "
                  f"{FLOOR_MIN_HOURS:g}h floor — capped at {landed:g}h", file=sys.stderr)


def timesheet_rows(rows, names, window=""):
    """Yield (display name, hours, title); section headers arrive as (name, None, None)."""
    people = group_work_items(rows)
    if not people:
        return
    inject_standing_items(people, window)
    declared = declared_slots(people)
    hours = raw_item_hours(people)
    apply_light_week_floor(hours, window, declared)
    totals = {key: sum(items.values()) for key, items in hours.items()}
    for section, _ in SECTIONS:
        blocks = [k for k in totals if k[1] == section]
        if not blocks:
            continue
        yield section, None, None
        for key in sorted(blocks, key=lambda k: (-totals[k], names.get(k[0], k[0]).lower())):
            developer = key[0]
            items = people[key]
            for ticket in sorted(items, key=lambda t, block=items: block[t]["number"]):
                yield (names.get(developer, developer), hours[key][ticket],
                       timesheet_title(items[ticket]["title"]))
            yield "TOTAL", round(totals[key], 1), ""


def autosize(worksheet, max_width=80):
    for column in worksheet.columns:
        letter = get_column_letter(column[0].column)
        longest = max((len(str(c.value)) for c in column if c.value is not None), default=10)
        worksheet.column_dimensions[letter].width = min(longest + 2, max_width)


def build(rows, out_path, window):
    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(bold=True, color="FFFFFF")
    link_font = Font(color="2563EB", underline="single")

    workbook = Workbook()
    work = workbook.active
    work.title = "Worklog"

    if window:
        work.append([f"Merged-PR worklog — {window}"])
        work["A1"].font = Font(bold=True, size=13)
        work.append([])
    header_row = work.max_row + 1
    headers = ["Developer", "Repository", "PR #", "Ticket", "Title", "Commits", "Status", "PR URL"]
    work.append(headers)
    for cell in work[header_row]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    work.freeze_panes = work.cell(row=header_row + 1, column=1)

    ordered = sorted(rows, key=lambda r: (r["repository"], r["developer"], -r["number"]))
    for row in ordered:
        work.append([
            row["developer"], row["repository"], row["number"], row["ticket"],
            row["title"], row["commits"], row["state"], row["url"],
        ])
        cell = work.cell(row=work.max_row, column=8)
        if row["url"]:
            cell.hyperlink = row["url"]
            cell.font = link_font
    autosize(work)

    summary = workbook.create_sheet("Summary")
    summary.append(["Developer", "Repository", "Merged PRs", "Total commits"])
    for cell in summary[1]:
        cell.fill = header_fill
        cell.font = header_font
    summary.freeze_panes = "A2"
    agg = {}
    for row in ordered:
        key = (row["developer"], row["repository"])
        bucket = agg.setdefault(key, [0, 0])
        bucket[0] += 1
        bucket[1] += row["commits"]

    bold = Font(bold=True)
    for dev in sorted({person for person, _ in agg}):
        repos = sorted(repo for person, repo in agg if person == dev)
        for repo in repos:
            count, commits = agg[(dev, repo)]
            summary.append([dev, repo, count, commits])
        if len(repos) > 1:                # a grand total only earns a row when it differs
            summary.append([dev, "— all repos —",
                            sum(agg[(dev, r)][0] for r in repos),
                            sum(agg[(dev, r)][1] for r in repos)])
            for cell in summary[summary.max_row]:
                cell.font = bold
    autosize(summary)

    write_timesheet(workbook.create_sheet("Timesheet"), ordered, window)
    workbook.save(out_path)
    return len(ordered), len({r["developer"] for r in ordered})


def write_timesheet(sheet, rows, window):
    """Fill a Developer | Hours | Title sheet, with a bold TOTAL closing each developer."""
    sheet.append([f"Timesheet — {window} (MERGED only, grouped by ticket)"])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([f"Hours are ESTIMATES sized from commit volume — not measured time. "
                  f"A developer's TOTAL is the sum of their items. Totals reading under "
                  f"{FLOOR_THRESHOLD_HOURS:g}h are lifted to a {FLOOR_MIN_HOURS:g}h floor to "
                  f"cover work that leaves no PR behind, so a lifted week is a floor, not an "
                  f"observation."])
    sheet["A2"].font = Font(italic=True, color="6B7280")
    sheet.append([])

    header_row = sheet.max_row + 1
    sheet.append(["Developer", "Hours", "Title"])
    for cell in sheet[header_row]:
        cell.fill = PatternFill("solid", fgColor="1F2937")
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    bold = Font(bold=True)
    section_fill = PatternFill("solid", fgColor="E5E7EB")
    block_start = None
    for developer, hours, title in timesheet_rows(rows, load_names(), window):
        if hours is None:                       # a section header, not a work item
            sheet.append([developer])
            for cell in sheet[sheet.max_row]:
                cell.fill = section_fill
                cell.font = bold
            block_start = None
            continue
        if developer != "TOTAL":
            sheet.append([developer, hours, title])
            block_start = block_start or sheet.max_row
            continue
        # A live SUM, never a frozen number: the hours are estimates meant to be
        # hand-corrected, and a hardcoded total goes stale the moment one is edited.
        end = sheet.max_row
        sheet.append([developer, f"=SUM(B{block_start}:B{end})" if block_start else hours, ""])
        for cell in sheet[sheet.max_row]:
            cell.font = bold
        block_start = None

    for column, width in (("A", 22), ("B", 9), ("C", 110)):
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=header_row + 1, min_col=2, max_col=2):
        row[0].number_format = "0.0"
        row[0].alignment = Alignment(horizontal="right")


def write_standalone_timesheet(rows, window, xlsx_path, tsv_path):
    """Emit the Timesheet on its own — an XLSX and/or a TSV — beside the workbook."""
    if xlsx_path:
        workbook = Workbook()
        workbook.active.title = "Timesheet"
        write_timesheet(workbook.active, rows, window)
        workbook.save(xlsx_path)
    if not tsv_path:
        return
    with open(tsv_path, "w", encoding="utf-8") as handle:
        for developer, hours, title in timesheet_rows(rows, load_names(), window):
            cells = "\t\t" if hours is None else f"\t{hours:.1f}\t{title}"
            handle.write(f"{developer}{cells}\n")


def main(argv):
    parser = argparse.ArgumentParser(
        description="Build an XLSX worklog from a git-list-merge-pr report read on stdin.",
    )
    parser.add_argument("out", nargs="?", default="",
                        help="output workbook .xlsx path; omit to emit only --timesheet/--tsv")
    parser.add_argument(
        "--report", default="-",
        help="report source; default '-' reads the git-list-merge-pr output from stdin",
    )
    parser.add_argument("--all-states", action="store_true")
    parser.add_argument("--window", default="")
    parser.add_argument("--timesheet", default="",
                        help="also write the Timesheet on its own to this .xlsx path")
    parser.add_argument("--tsv", default="",
                        help="also write the Timesheet as tab-separated text to this path")
    parser.add_argument("--only", default="",
                        help="comma-separated developer logins to keep (case-insensitive)")
    parser.add_argument("--exclude", default="",
                        help="comma-separated developer logins to drop (case-insensitive)")
    args = parser.parse_args(argv)
    if not (args.out or args.timesheet or args.tsv):
        parser.error("nothing to write — give an output workbook path, --timesheet, or --tsv")

    if args.report == "-":
        if sys.stdin.isatty():
            parser.error("no report on stdin — pipe `git-list-merge-pr` output in, or pass --report <file>")
        rows = parse_report(sys.stdin)
    else:
        with open(args.report, encoding="utf-8") as handle:
            rows = parse_report(handle)

    if not args.all_states:
        rows = [r for r in rows if r["state"] == "MERGED"]
    wanted = [w.strip() for w in args.only.split(",") if w.strip()]
    excluded = [e.strip() for e in args.exclude.split(",") if e.strip()]
    rows, unmatched = filter_developers(rows, wanted, excluded)
    for name in unmatched:
        print(f"WARNING: '{name}' authored no PR in this report — filter had no effect.",
              file=sys.stderr)
    if not rows:
        print("No rows parsed — check the report format.", file=sys.stderr)
        return 1

    prs, devs = len(rows), len({r["developer"] for r in rows})
    if args.out:
        build(rows, args.out, args.window)
        print(f"Wrote {args.out}: {prs} PRs across {devs} developers.")
    if args.timesheet or args.tsv:
        write_standalone_timesheet(rows, args.window, args.timesheet, args.tsv)
        for path in (args.timesheet, args.tsv):
            if path:
                print(f"Wrote {path}: {prs} PRs across {devs} developers.")
    unnamed = sorted({r["developer"] for r in rows} - set(load_names()))
    if unnamed:
        print("Timesheet shows these as raw GitHub logins — add them to developers.json: "
              + ", ".join(unnamed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
