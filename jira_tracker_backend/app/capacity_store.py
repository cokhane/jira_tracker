"""Persistence for the Capacity Tracker — the workbook, kept as data instead of a file.

One `SprintCapacity` row per developer per sprint. Only two numbers are human-entered: a
developer's FIRST capacity (seeded from `Rolling_Sprint_Capacity.xlsx`) and each sprint's
actual, which the UI writes back cell by cell. Every later capacity is derived by the
rolling rule in app/capacity.py and re-persisted on each edit, so the table always matches
the sheet and reading the grid stays a plain ordered SELECT.

Board scoping falls out of the schema: each board has its own SQLite file, and only
developers on that board's `report_assignees` roster are imported into it. A name in the
sheet that no board rosters is reported as skipped rather than silently dropped.

The grid always runs one sprint past the current one, so there is a column to plan into.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app import capacity
from app.config import ProjectConfig
from app.models import SprintCapacity
from app.projects import get_registry, resolve_cfg

# How far past the current sprint the grid keeps an editable column.
_LOOKAHEAD_SPRINTS = 1


def load_grid(db: Session, cfg: ProjectConfig) -> tuple[list[SprintCapacity], list[str]]:
    """This board's cells (sprint-major, then developer) plus any sheet names it skipped.

    Imports the workbook the first time the board's table is empty, so the view is
    populated without anyone having to trigger an import by hand.
    """
    skipped: list[str] = []
    if not _rows(db):
        skipped = import_sheet(db, cfg)
    _extend_to_current(db, cfg)
    return _rows(db), skipped


def import_sheet(db: Session, cfg: ProjectConfig, replace: bool = False) -> list[str]:
    """Seed this board's grid from the capacity workbook; returns the names it skipped.

    Only sheet rows naming someone on this board's roster are kept — the rest belong to
    another board (or to nobody) and are returned for the caller to surface. Roster
    developers the sheet doesn't cover are seeded at `dev_target_default` with no actuals.

    WHO is on the grid is decided once, at the seeding import, and is the table's own
    business from then on: a later import refreshes the developers already there and adds
    nobody, so someone dropped via `remove_developer` stays dropped instead of coming back
    every time the sheet is re-read. `add_developer` is how one person joins; `replace`
    wipes the board and re-seeds the whole roster, at the cost of every actual typed since
    the last import.
    """
    if replace:
        db.query(SprintCapacity).delete()
        db.flush()

    sheet = _read_sheet(cfg)
    numbers = _sprint_numbers(cfg, sheet)
    by_name = _sheet_actuals(cfg, sheet, numbers)
    onboard = {row.developer for row in _rows(db)}

    for developer in cfg.report_assignee_list:
        if onboard and developer not in onboard:
            continue  # off this grid on purpose — an import must not put them back
        actuals = by_name.get(developer, {})
        seed = _seed_capacity(sheet, developer, cfg.dev_target_default)
        _write_developer(db, developer, numbers, seed, actuals)
    db.commit()
    return _skipped_names(sheet)


def add_developer(db: Session, cfg: ProjectConfig, developer: str) -> bool:
    """Put one developer onto this board's grid without disturbing anyone else's numbers.

    The counterpart to `remove_developer`, and the reason a mid-season joiner doesn't need
    `import_sheet(replace=True)`: they get a row across the sprints the grid already holds,
    seeded from the workbook where it covers them and from `dev_target_default` where it
    doesn't, while every actual typed so far stays exactly where it is. Returns False when
    they already have a row — re-adding would reset the seed they were given.
    """
    rows = _rows(db)
    if any(row.developer == developer for row in rows):
        return False
    sheet = _read_sheet(cfg)
    numbers = sprint_numbers(rows) or _sprint_numbers(cfg, sheet)
    _write_developer(db, developer, numbers,
                     _seed_capacity(sheet, developer, cfg.dev_target_default),
                     _sheet_actuals(cfg, sheet, numbers).get(developer, {}))
    db.commit()
    return True


def remove_developer(db: Session, developer: str) -> bool:
    """Drop one developer from this board's grid, capacities and actuals alike.

    Scoped to the Capacity Tracker: their `report_assignees` membership is untouched, so
    the sprint reports and comparison decks still count them. Returns False when they
    weren't on the grid to begin with.
    """
    deleted = (
        db.query(SprintCapacity)
        .filter(SprintCapacity.developer == developer)
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)


def set_actual(db: Session, sprint_number: int, developer: str, value: int | None) -> bool:
    """Record one sprint's actual for one developer and roll the change forward.

    Returns False when that cell isn't on this board's grid (unknown developer, or a
    sprint outside the stored range) so the caller can answer 404 rather than invent a row.
    """
    row = _cell(db, sprint_number, developer)
    if row is None:
        return False
    row.actual = value
    _recompute(db, developer)
    db.commit()
    return True


def sprint_numbers(rows: list[SprintCapacity]) -> list[int]:
    """The grid's sprint columns, ascending — derived from the rows so the two can't drift."""
    return sorted({row.sprint_number for row in rows})


def _rows(db: Session) -> list[SprintCapacity]:
    return (
        db.query(SprintCapacity)
        .order_by(SprintCapacity.sprint_number, SprintCapacity.developer)
        .all()
    )


def _cell(db: Session, sprint_number: int, developer: str) -> SprintCapacity | None:
    return (
        db.query(SprintCapacity)
        .filter(SprintCapacity.sprint_number == sprint_number,
                SprintCapacity.developer == developer)
        .one_or_none()
    )


def _read_sheet(cfg: ProjectConfig) -> capacity.CapacitySheet | None:
    """The capacity workbook, parsed against the year this board's sprint numbering starts in."""
    return capacity.read_sheet(
        cfg.capacity_workbook_path,
        dt.date.fromisoformat(cfg.sprint_anchor_date).year,
    )


def _sprint_numbers(cfg: ProjectConfig, sheet: capacity.CapacitySheet | None) -> list[int]:
    """Every sprint column the grid should hold: the sheet's blocks through the lookahead.

    Sheet blocks are placed by their week start on the BOARD's calendar, not by the sheet's
    own "SPRINT 1..8" labels — those are just captions and can sit a week off the board.
    """
    current = cfg.sprint_for(dt.date.today())[0]
    numbers = {current + step for step in range(_LOOKAHEAD_SPRINTS + 1)}
    numbers.update(cfg.sprint_for(start)[0] for start in _sheet_starts(sheet))
    return sorted(range(min(numbers), max(numbers) + 1))


def _sheet_starts(sheet: capacity.CapacitySheet | None) -> list[dt.date]:
    """The sheet's parsable block starts (blocks with an unreadable range are ignored)."""
    return [start for start in sheet.starts if start] if sheet else []


def _sheet_actuals(cfg: ProjectConfig, sheet: capacity.CapacitySheet | None,
                   numbers: list[int]) -> dict[str, dict[int, int]]:
    """`{developer: {sprint_number: actual}}` for the sheet's typed actuals.

    Blocks whose week range didn't parse, and blocks landing outside `numbers`, are
    dropped — an actual is only kept where it maps onto a real column of the grid.
    """
    if sheet is None:
        return {}
    columns = [(index, cfg.sprint_for(start)[0])
               for index, start in enumerate(sheet.starts) if start]
    grid = set(numbers)
    return {
        row.name: {
            number: row.actuals[index]
            for index, number in columns
            if number in grid and row.actuals[index] is not None
        }
        for row in sheet.developers
    }


def _seed_capacity(sheet: capacity.CapacitySheet | None, developer: str, default: int) -> int:
    """The developer's first-sprint capacity from the sheet, or the board's default."""
    if sheet is None:
        return default
    for row in sheet.developers:
        if row.name == developer:
            return row.seed_capacity
    return default


def _skipped_names(sheet: capacity.CapacitySheet | None) -> list[str]:
    """Sheet rows that no board rosters at all — capacity nobody's grid will ever show.

    Checked against EVERY board, not just this one: a developer the sheet shares with
    another board isn't lost, they're simply that board's row. Only a name missing from
    all `report_assignees` lists is a real gap worth reporting.
    """
    if sheet is None:
        return []
    rostered: set[str] = set()
    for entry in get_registry():
        board = resolve_cfg(entry.key)
        if board is not None:
            rostered.update(board.report_assignee_list)
    return sorted({row.name for row in sheet.developers} - rostered)


def _write_developer(db: Session, developer: str, numbers: list[int], seed: int,
                     actuals: dict[int, int]) -> None:
    """Upsert one developer's whole row of cells, then roll their capacities forward."""
    for number in numbers:
        row = _cell(db, number, developer)
        if row is None:
            row = SprintCapacity(sprint_number=number, developer=developer)
            db.add(row)
        row.actual = actuals.get(number, row.actual)
    db.flush()
    _seed_first(db, developer, seed)
    _recompute(db, developer)


def _seed_first(db: Session, developer: str, seed: int) -> None:
    """Set the earliest sprint's capacity — the one number the rolling rule can't derive."""
    rows = _developer_rows(db, developer)
    if rows:
        rows[0].capacity = seed


def _recompute(db: Session, developer: str) -> None:
    """Rewrite every derived capacity for one developer from their seed and their actuals."""
    rows = _developer_rows(db, developer)
    if not rows:
        return
    capacities = capacity.cascade(rows[0].capacity or 0, [row.actual for row in rows])
    for row, value in zip(rows, capacities):
        row.capacity = value


def _developer_rows(db: Session, developer: str) -> list[SprintCapacity]:
    return (
        db.query(SprintCapacity)
        .filter(SprintCapacity.developer == developer)
        .order_by(SprintCapacity.sprint_number)
        .all()
    )


def _extend_to_current(db: Session, cfg: ProjectConfig) -> None:
    """Add the columns that time has created since the last import, and recompute.

    Sprints keep arriving whether or not anyone re-imports, so an already-seeded board
    grows its own trailing columns rather than freezing at the sheet's last block.
    """
    rows = _rows(db)
    if not rows:
        return
    stored = sprint_numbers(rows)
    wanted = range(stored[-1] + 1, cfg.sprint_for(dt.date.today())[0] + _LOOKAHEAD_SPRINTS + 1)
    if not wanted:
        return
    for developer in sorted({row.developer for row in rows}):
        for number in wanted:
            db.add(SprintCapacity(sprint_number=number, developer=developer))
        db.flush()
        _recompute(db, developer)
    db.commit()
