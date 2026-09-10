"""ORM models — our own clean domain shape, decoupled from Jira's wire format."""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Issue(Base):
    """One row per Jira issue. `key` (e.g. NEX-960) is the natural primary key."""

    __tablename__ = "issues"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    jira_id: Mapped[str | None] = mapped_column(String, index=True)

    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    issue_type: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str | None] = mapped_column(String, index=True)
    status_category: Mapped[str | None] = mapped_column(String, index=True)
    priority: Mapped[str | None] = mapped_column(String, index=True)

    assignee: Mapped[str | None] = mapped_column(String, index=True)
    reporter: Mapped[str | None] = mapped_column(String, index=True)

    epic_key: Mapped[str | None] = mapped_column(String, index=True)
    epic_name: Mapped[str | None] = mapped_column(String, index=True)

    labels: Mapped[list | None] = mapped_column(JSON)
    components: Mapped[list | None] = mapped_column(JSON)
    resolution: Mapped[str | None] = mapped_column(String)

    created: Mapped[str | None] = mapped_column(String)  # Jira ISO timestamp
    updated: Mapped[str | None] = mapped_column(String, index=True)
    web_url: Mapped[str | None] = mapped_column(String)

    raw: Mapped[dict | None] = mapped_column(JSON)  # full Jira payload, future-proofing
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StatusTransition(Base):
    """One row per status change in an issue's Jira changelog.

    This is the history the snapshot `Issue` table can't provide — it's what powers
    the weekly/daily per-assignee scorecard and per-column movement reports. We store
    *both* `moved_by` (who clicked the transition) and `assignee_at` (who owned the
    ticket at that moment) so reports can attribute work either way.
    """

    __tablename__ = "status_transitions"
    __table_args__ = (
        # A Jira changelog history id is unique per issue — makes re-sync idempotent.
        UniqueConstraint("issue_key", "changelog_id", name="uq_transition_issue_history"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(String, index=True)
    changelog_id: Mapped[str] = mapped_column(String)

    from_status: Mapped[str | None] = mapped_column(String)
    from_category: Mapped[str | None] = mapped_column(String)
    to_status: Mapped[str | None] = mapped_column(String)
    to_category: Mapped[str | None] = mapped_column(String)

    moved_by: Mapped[str | None] = mapped_column(String, index=True)
    assignee_at: Mapped[str | None] = mapped_column(String, index=True)

    changed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    change_date: Mapped[date | None] = mapped_column(Date, index=True)  # local-tz calendar day
    week_start: Mapped[date | None] = mapped_column(Date, index=True)  # Monday of that week


class Worklog(Base):
    """One row per Jira worklog entry — a chunk of time a person logged on an issue.

    Attribution is by the worklog **author** (who clocked the time), which can differ
    from the issue's assignee. `summary`/`web_url` are denormalized off the issue so the
    per-person time-log view stays intact even after the `issues` table is pruned to the
    current sprint.
    """

    __tablename__ = "worklogs"
    __table_args__ = (
        # A Jira worklog id is unique per issue — makes re-sync idempotent.
        UniqueConstraint("issue_key", "worklog_id", name="uq_worklog_issue_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(String, index=True)
    worklog_id: Mapped[str] = mapped_column(String)

    author: Mapped[str | None] = mapped_column(String, index=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    started: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # naive UTC
    comment: Mapped[str | None] = mapped_column(Text)

    # Denormalized issue fields (survive a prune of the issues table).
    summary: Mapped[str | None] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(String)

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DailySnapshot(Base):
    """One row per issue per day — a saved picture of the board on `snapshot_date`.

    Clicking "sync today" refreshes issues from Jira and writes one of these rows for
    every issue, so you can later pick a date and see exactly what the board looked like
    (which column each ticket sat in, who owned it) on that day.
    """

    __tablename__ = "daily_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    issue_key: Mapped[str] = mapped_column(String, primary_key=True)

    summary: Mapped[str | None] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str | None] = mapped_column(String, index=True)
    status_category: Mapped[str | None] = mapped_column(String)
    issue_type: Mapped[str | None] = mapped_column(String)
    epic_key: Mapped[str | None] = mapped_column(String, index=True)
    epic_name: Mapped[str | None] = mapped_column(String, index=True)
    web_url: Mapped[str | None] = mapped_column(String)

    # The actual Jira sprint this snapshot was pulled from (what's on the board).
    sprint_name: Mapped[str | None] = mapped_column(String, index=True)
    sprint_start: Mapped[date | None] = mapped_column(Date)
    sprint_end: Mapped[date | None] = mapped_column(Date)

    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SprintCapacity(Base):
    """One row per developer per sprint — the team's rolling capacity plan.

    This is `Rolling_Sprint_Capacity.xlsx` turned into data. Only two numbers are ever
    entered by a human: a developer's FIRST `capacity` (seeded from the workbook) and each
    sprint's `actual`. Every later `capacity` is derived from the rolling rule in
    app/capacity.py and written back whenever an actual changes, so the stored table always
    matches the sheet cell for cell and reading the grid stays a plain SELECT.

    Rows are board-scoped like everything else — each board's DB holds only the developers
    on its own `report_assignees` roster. Sprint dates aren't stored: `sprint_number` is
    the board's own sprint calendar (`ProjectConfig.sprint_window`), so a changed anchor
    can never leave stale ranges behind.
    """

    __tablename__ = "sprint_capacity"

    sprint_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer: Mapped[str] = mapped_column(String, primary_key=True)

    capacity: Mapped[int | None] = mapped_column(Integer)
    actual: Mapped[int | None] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class SyncLog(Base):
    """Audit row written on every sync run (success or failure)."""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, default="running")  # running|success|error
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    transitions_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
