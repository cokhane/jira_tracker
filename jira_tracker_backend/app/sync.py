"""Service / domain layer — orchestrates a sync run.

Responsibilities: build the JQL, call the Jira client, normalize each issue from
Jira's wire format into our `Issue` model, upsert by key, capture status-transition
history from the changelog, and audit the run in `SyncLog`. A failure is *recorded*,
never crashed.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ProjectConfig
from app.jira_client import DEFAULT_FIELDS, JiraClient, JiraError
from app.models import DailySnapshot, Issue, StatusTransition, SyncLog, Worklog

logger = logging.getLogger(__name__)


class PastSnapshotError(Exception):
    """Raised when a snapshot is attempted for a day earlier than today."""

# Maps a Jira status name to its board category. Mirrors the values already in the
# `issues` table; anything unknown defaults to "In Progress" (an active column).
_STATUS_CATEGORY = {
    "To Do": "To Do",
    "In Progress": "In Progress",
    "Code Review": "In Progress",
    "Merged": "In Progress",
    "QA Testing": "In Progress",
    "Deployment": "In Progress",
    "Blocked": "In Progress",
    "Done": "Done",
}


def _category_for(status: str | None) -> str | None:
    if status is None:
        return None
    return _STATUS_CATEGORY.get(status, "In Progress")


# ---------- normalization helpers (Jira wire format -> our domain) ----------

def _adf_to_text(node: object) -> str:
    """Best-effort flatten of Atlassian Document Format (ADF) JSON to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = _adf_to_text(node.get("content"))
        # Add a newline after block-level nodes for readability.
        if node.get("type") in {"paragraph", "heading", "listItem", "blockquote"}:
            parts += "\n"
        return parts
    return ""


def _name(obj: dict | None, key: str = "name") -> str | None:
    return obj.get(key) if isinstance(obj, dict) else None


def _normalize(raw: dict, base_url: str) -> dict:
    """Turn one raw Jira issue into kwargs for the Issue model."""
    fields = raw.get("fields", {}) or {}
    status = fields.get("status") or {}
    parent = fields.get("parent") or {}
    parent_fields = parent.get("fields") or {}
    return {
        "key": raw.get("key"),
        "jira_id": raw.get("id"),
        "summary": fields.get("summary"),
        "description": _adf_to_text(fields.get("description")).strip() or None,
        "issue_type": _name(fields.get("issuetype")),
        "status": _name(status),
        "status_category": _name(status.get("statusCategory"), "name"),
        "priority": _name(fields.get("priority")),
        "assignee": _name(fields.get("assignee"), "displayName"),
        "reporter": _name(fields.get("reporter"), "displayName"),
        "epic_key": parent.get("key"),
        "epic_name": parent_fields.get("summary"),
        "labels": fields.get("labels") or [],
        "components": [c.get("name") for c in (fields.get("components") or [])],
        "resolution": _name(fields.get("resolution")),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "web_url": f"{base_url.rstrip('/')}/browse/{raw.get('key')}",
        "raw": raw,
    }


# ---------- changelog -> status transitions ----------

def _parse_jira_dt(value: str | None) -> datetime | None:
    """Parse a Jira ISO timestamp (e.g. '2025-06-01T10:23:45.123+0800') to UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)  # py3.11 handles '+0800' / 'Z' offsets
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _assignee_timeline(histories: list[dict], current_assignee: str | None):
    """Return (initial_assignee, [(changed_at_utc, assignee), ...]) sorted by time.

    Lets us answer "who was the assignee at time T" by finding the last change at or
    before T. If the issue never had an assignee change, the assignee is whoever it
    is now, for all time.
    """
    changes: list[tuple[datetime, str | None]] = []
    initial: str | None = None
    seen_initial = False

    for h in sorted(histories, key=lambda x: x.get("created") or ""):
        for item in h.get("items", []) or []:
            if item.get("field") != "assignee":
                continue
            when = _parse_jira_dt(h.get("created"))
            if when is None:
                continue
            if not seen_initial:
                initial = item.get("fromString")  # who held it before the first change
                seen_initial = True
            changes.append((when, item.get("toString")))

    if not seen_initial:
        initial = current_assignee  # assignee never changed -> always the current one
    return initial, changes


def _assignee_at(initial, changes, when: datetime) -> str | None:
    """Assignee in effect at `when`, given the reconstructed timeline."""
    result = initial
    for changed_at, assignee in changes:
        if changed_at <= when:
            result = assignee
        else:
            break
    return result


def _local_dates(when_utc: datetime, tz: ZoneInfo) -> tuple[date, date]:
    """(calendar day, Monday of that week) for a UTC instant, in the report tz."""
    local = when_utc.astimezone(tz)
    day = local.date()
    week_start = day - timedelta(days=day.weekday())  # Monday
    return day, week_start


def _sync_transitions(
    db: Session, client: JiraClient, issue_key: str,
    current_assignee: str | None, tz: ZoneInfo,
) -> int:
    """Fetch one issue's changelog and upsert its status transitions. Idempotent."""
    histories = client.get_changelog(issue_key)
    if not histories:
        return 0

    initial, changes = _assignee_timeline(histories, current_assignee)

    # Existing changelog ids for this issue — skip them so re-sync doesn't duplicate.
    existing_ids = set(
        db.scalars(
            select(StatusTransition.changelog_id).where(
                StatusTransition.issue_key == issue_key
            )
        ).all()
    )

    added = 0
    for h in histories:
        history_id = str(h.get("id"))
        if history_id in existing_ids:
            continue
        status_item = next(
            (i for i in (h.get("items") or []) if i.get("field") == "status"), None
        )
        if status_item is None:
            continue

        to_status = status_item.get("toString")
        from_status = status_item.get("fromString")
        # Skip no-op self-transitions (e.g. automation re-firing 'Merged' -> 'Merged').
        # They represent no real column movement and only inflate the counts.
        if from_status == to_status:
            continue

        when = _parse_jira_dt(h.get("created"))
        if when is None:
            continue
        day, week_start = _local_dates(when, tz)

        db.add(
            StatusTransition(
                issue_key=issue_key,
                changelog_id=history_id,
                from_status=from_status,
                from_category=_category_for(from_status),
                to_status=to_status,
                to_category=_category_for(to_status),
                moved_by=(h.get("author") or {}).get("displayName"),
                assignee_at=_assignee_at(initial, changes, when),
                changed_at=when.replace(tzinfo=None),  # store naive UTC
                change_date=day,
                week_start=week_start,
            )
        )
        existing_ids.add(history_id)
        added += 1

    return added


# ---------- worklog -> time log ----------

def _sync_worklogs(
    db: Session, client: JiraClient, issue_key: str, raw: dict,
    summary: str | None, web_url: str | None, allow_fetch: bool = True,
) -> int:
    """Upsert one issue's worklog entries from the inline `worklog` field.

    Jira caps the inline list at 20 entries; if an issue has more, we fetch the full
    set via the worklog endpoint (only when `allow_fetch`, so the fast snapshot path
    doesn't pay for it). Idempotent by (issue_key, worklog_id) — an edited worklog
    (time changed) updates the existing row rather than duplicating it.
    """
    fields = raw.get("fields", {}) or {}
    wl = fields.get("worklog") or {}
    entries = wl.get("worklogs") or []
    total = wl.get("total", len(entries))
    if allow_fetch and total > len(entries):
        entries = client.get_worklog(issue_key)  # inline list was truncated

    if not entries:
        return 0

    existing = {
        w.worklog_id: w
        for w in db.scalars(select(Worklog).where(Worklog.issue_key == issue_key)).all()
    }

    changed = 0
    for e in entries:
        wid = str(e.get("id"))
        if not wid:
            continue
        started = _parse_jira_dt(e.get("started"))
        vals = {
            "author": (e.get("author") or {}).get("displayName"),
            "time_spent_seconds": e.get("timeSpentSeconds") or 0,
            "started": started.replace(tzinfo=None) if started else None,
            "comment": _adf_to_text(e.get("comment")).strip() or None,
            "summary": summary,
            "web_url": web_url,
        }
        row = existing.get(wid)
        if row:
            for field, value in vals.items():
                setattr(row, field, value)
        else:
            db.add(Worklog(issue_key=issue_key, worklog_id=wid, **vals))
        changed += 1

    return changed


# Time-log capture reaches back this far, independent of the sprint filter, so worklogs
# on tickets that have already left the open sprint (moved to Done/closed) are still
# captured — otherwise a per-person time log would silently drop that work.
WORKLOG_LOOKBACK_DAYS = 45


def sync_recent_worklogs(db: Session, client: JiraClient, project: str, base_url: str) -> int:
    """Upsert worklogs for every issue with time logged in the last N days.

    Decoupled from `sprint in openSprints()` so time logged on tickets that since left
    the sprint is still captured. Only touches the `worklogs` table (no Issue upsert,
    no prune). Idempotent via `_sync_worklogs`.
    """
    since = (date.today() - timedelta(days=WORKLOG_LOOKBACK_DAYS)).isoformat()
    jql = f'project = {project} AND worklogDate >= "{since}" ORDER BY updated ASC'
    raw_issues = client.search_issues(jql, ["summary", "worklog"])

    changed = 0
    for raw in raw_issues:
        key = raw.get("key")
        if not key:
            continue
        summary = (raw.get("fields") or {}).get("summary")
        web_url = f"{base_url.rstrip('/')}/browse/{key}"
        changed += _sync_worklogs(db, client, key, raw, summary, web_url, allow_fetch=True)
    return changed


# ---------- sync orchestration ----------

def _build_jql(
    project: str, incremental_since: str | None, current_sprint_only: bool = False
) -> str:
    jql = f"project = {project}"
    if current_sprint_only:
        jql += " AND sprint in openSprints()"
    if incremental_since:
        jql += f' AND updated >= "{incremental_since}"'
    return jql + " ORDER BY updated ASC"


def run_sync(db: Session, cfg: ProjectConfig, full: bool = True, with_transitions: bool = True) -> SyncLog:
    """Pull issues from Jira and upsert them (into `cfg`'s board DB). Returns the SyncLog row.

    `with_transitions=False` skips the (slow) per-issue changelog fetch — used by the
    daily-snapshot button, which only needs the current board state, not history.
    """
    settings = cfg
    log = SyncLog(status="running")
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        # Incremental: only pull issues changed since the last successful sync.
        since: str | None = None
        if not full:
            last = (
                db.query(SyncLog)
                .filter(SyncLog.status == "success", SyncLog.id != log.id)
                .order_by(SyncLog.finished_at.desc())
                .first()
            )
            if last and last.finished_at:
                since = last.finished_at.strftime("%Y-%m-%d %H:%M")

        client = JiraClient(settings)
        jql = _build_jql(settings.jira_project, since, settings.current_sprint_only)
        raw_issues = client.search_issues(jql, DEFAULT_FIELDS)
        tz = ZoneInfo(settings.report_timezone)

        # A full current-sprint pull that returns nothing usually means the board is
        # *between sprints* (no open sprint) — not a real error, but snapshots taken now
        # would carry stale data, so make it loud instead of a silent "success, 0 rows".
        if full and settings.current_sprint_only and not raw_issues:
            logger.warning(
                "Sync pulled 0 issues for JQL %r — the board likely has no open sprint. "
                "Existing issues are kept (not pruned) to avoid wiping the DB.", jql
            )

        excluded = set(settings.excluded_assignees)
        monitored = set(settings.monitored_assignees)  # allow-list; empty = keep all
        kept_keys: list[str] = []
        created = updated = transitions = 0
        for raw in raw_issues:
            data = _normalize(raw, settings.jira_base_url)
            if not data["key"]:
                continue
            assignee = data.get("assignee")
            if monitored:
                if assignee not in monitored:
                    continue  # only monitored people are kept
            elif assignee in excluded:
                continue  # permanently excluded assignee — never store
            kept_keys.append(data["key"])
            existing = db.get(Issue, data["key"])
            if existing:
                for field, value in data.items():
                    setattr(existing, field, value)
                existing.synced_at = datetime.now(timezone.utc)
                updated += 1
            else:
                db.add(Issue(**data))
                created += 1

            # Capture this issue's movement history from its changelog.
            if with_transitions:
                transitions += _sync_transitions(
                    db, client, data["key"], data.get("assignee"), tz
                )

        # Prune stale rows: on a full current-sprint pull, `kept_keys` is the complete
        # authoritative board, so any Issue not in it (old-sprint leftovers, people who
        # left the allow-list) is deleted — otherwise it leaks into every snapshot.
        deleted = 0
        if full and settings.current_sprint_only and kept_keys:
            deleted = (
                db.query(Issue)
                .filter(Issue.key.notin_(kept_keys))
                .delete(synchronize_session=False)
            )

        # Capture time logged on tickets that have left the sprint (see the function).
        sync_recent_worklogs(db, client, settings.jira_project, settings.jira_base_url)

        log.fetched = len(raw_issues)
        log.created_count = created
        log.updated_count = updated
        log.transitions_count = transitions
        log.status = "success"
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(log)
        return log

    except Exception as exc:  # record failure, don't crash the server
        # Jira/API failures are expected; anything else is a real bug — log the full
        # traceback to the server so it isn't masked as a plain "sync error" string.
        if not isinstance(exc, JiraError):
            logger.exception("Unexpected error during sync run %s", log.id)
        db.rollback()
        log.status = "error"
        log.error = f"{type(exc).__name__}: {exc}"
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(log)
        return log


# ---------- daily board snapshots ----------

def _today_local(cfg: ProjectConfig) -> date:
    """Today's date in the team's report timezone (not the server's)."""
    tz = ZoneInfo(cfg.report_timezone)
    return datetime.now(tz).date()


def _active_sprint(client: JiraClient, project: str, tz: ZoneInfo) -> dict | None:
    """The board's active sprint as {name, start, end}, or None if there isn't one."""
    sprints = client.active_sprints(project)
    if not sprints:
        return None
    sp = sprints[0]  # board has a single active sprint in the normal case

    def _d(v):
        dt = _parse_jira_dt(v)
        return dt.astimezone(tz).date() if dt else None

    return {"name": sp.get("name"), "start": _d(sp.get("startDate")), "end": _d(sp.get("endDate"))}


def capture_snapshot(
    db: Session, cfg: ProjectConfig, snapshot_date: date | None = None,
    sprint: dict | None = None, force: bool = False,
) -> dict:
    """Save a picture of the board for `snapshot_date` (default: today, local tz).

    Tags every row with the Jira sprint the board is on. Re-running for the same date
    replaces that day's rows. Resyncing a *past* day overwrites it with the current
    board, so it requires `force=True` (the UI gates this behind a confirmation).
    """
    settings = cfg
    today = _today_local(cfg)
    snapshot_date = snapshot_date or today
    sprint = sprint or {}

    # Resyncing a past day overwrites history with today's board — require confirmation.
    if snapshot_date < today and not force:
        raise PastSnapshotError(
            f"{snapshot_date} is a past day. Resyncing it overwrites the saved snapshot "
            f"with today's live board. Confirm to proceed."
        )

    # Replace any existing snapshot for this date (idempotent per day).
    db.query(DailySnapshot).filter(
        DailySnapshot.snapshot_date == snapshot_date
    ).delete(synchronize_session=False)

    # The board tracks active work — optionally drop Done tickets.
    q = db.query(Issue)
    if settings.snapshot_exclude_done:
        q = q.filter(Issue.status != "Done")
    monitored = settings.monitored_assignees
    if monitored:
        q = q.filter(Issue.assignee.in_(monitored))  # allow-list: only monitored people
    else:
        for name in settings.excluded_assignees:
            q = q.filter((Issue.assignee != name) | (Issue.assignee.is_(None)))
    issues = q.all()
    for issue in issues:
        db.add(
            DailySnapshot(
                snapshot_date=snapshot_date,
                issue_key=issue.key,
                summary=issue.summary,
                assignee=issue.assignee,
                status=issue.status,
                status_category=issue.status_category,
                issue_type=issue.issue_type,
                epic_key=issue.epic_key,
                epic_name=issue.epic_name,
                web_url=issue.web_url,
                sprint_name=sprint.get("name"),
                sprint_start=sprint.get("start"),
                sprint_end=sprint.get("end"),
            )
        )
    db.commit()
    return {"snapshot_date": snapshot_date, "issues": len(issues), "sprint": sprint.get("name")}


def sync_and_snapshot(db: Session, cfg: ProjectConfig, snapshot_date: date | None = None, force: bool = False) -> dict:
    """Refresh issues from Jira, then save the snapshot for `snapshot_date` (default today).

    Resyncing always deletes that day's rows and reinserts the latest pull. Also fetches
    each issue's changelog so `status_transitions` stays current — this is what feeds the
    Developer Delivery funnel, so the board sync must keep it up to date (at the cost of a
    slower, per-issue pull).
    """
    settings = cfg
    # Guard past-day resync BEFORE hitting Jira, so an unconfirmed click is cheap.
    if snapshot_date and snapshot_date < _today_local(cfg) and not force:
        raise PastSnapshotError(
            f"{snapshot_date} is a past day. Resyncing it overwrites the saved snapshot "
            f"with today's live board. Confirm to proceed."
        )
    log = run_sync(db, cfg, full=True, with_transitions=True)
    if log.status == "error":
        raise JiraError(log.error or "Sync failed")
    tz = ZoneInfo(settings.report_timezone)
    sprint = _active_sprint(JiraClient(settings), settings.jira_project, tz)
    return capture_snapshot(db, cfg, snapshot_date=snapshot_date, sprint=sprint, force=force)
