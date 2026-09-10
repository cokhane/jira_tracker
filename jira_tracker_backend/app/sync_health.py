"""Health of the nightly all-boards sync — the data behind the Sync Health dashboard.

A `sync_logs` row exists only for a sync that actually STARTED. When the scheduled job
never fires at all — the Mac was asleep at 20:00, the LaunchAgent was unloaded, or the
driver script died before it reached `run_sync` — nothing is written anywhere. A view
built purely on the rows that exist would therefore show an unbroken run of green while
the cron was silently dead, which is the failure mode most worth catching.

So this module does not just report the rows. It reconstructs the nights the job was
EXPECTED to fire (from `sync_schedule_*` in Settings, which mirrors the plist) and reports
a night with no row as `missed`. "Never ran" and "ran and failed" are different problems
with different fixes, so they stay distinct states rather than collapsing into "not ok".

Times are bucketed by LOCAL day (`report_timezone`), because that is how the schedule is
expressed and how someone reading the dashboard thinks about "last night". Stored values
are naive UTC (see `models._utcnow` + SQLite's DATETIME), so every one is stamped UTC on
the way out of the DB and converted once, here.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SyncLog

# How late a scheduled run may be before its night counts as `missed`. The pull itself
# takes ~5 minutes, and launchd runs a job it slept through once on the next wake, so a
# short grace keeps a late-but-fine run from flashing red the moment the clock ticks over.
_MISSED_GRACE = timedelta(hours=1)

# One night's outcome, from the dashboard's point of view.
STATE_OK = "ok"            # at least one run succeeded
STATE_RUNNING = "running"  # a run is in flight and none has succeeded yet
STATE_FAILED = "failed"    # runs happened, every one of them errored
STATE_MISSED = "missed"    # expected, overdue, and nothing ever started
STATE_PENDING = "pending"  # expected but not due yet (tonight, before the fire time)
STATE_OFF = "off"          # not a scheduled night, and nothing ran
# Expected and overdue, and a sync DID run — just never the scheduled one. Distinct from
# `missed` because the fix differs: data is fresh, but the cron behind it is dead.
STATE_UNSCHEDULED = "unscheduled"

# Rolled-up board verdicts.
STATUS_OK = "ok"
STATUS_WARN = "warn"    # currently fine, but the window holds a failure or a missed night
STATUS_ERROR = "error"  # the latest night that was due did not succeed

# The night states that mean the schedule did not do its job. Named once so `_roll_up` and
# the caller's day lists cannot disagree about what counts as a bad night.
_BAD_STATES = (STATE_FAILED, STATE_MISSED, STATE_UNSCHEDULED)


def _tz() -> ZoneInfo:
    """The timezone the schedule is expressed in — the same one the reports bucket by."""
    return ZoneInfo(get_settings().report_timezone)


def _scheduled_weekdays() -> set[int]:
    """ISO weekdays (1=Mon … 7=Sun) the nightly sync is expected to fire."""
    raw = get_settings().sync_schedule_weekdays
    return {int(p) for p in (part.strip() for part in raw.split(",")) if p.isdigit()}


def _live_since() -> date | None:
    """The day the schedule went live. Nights before it were never armed, so they are not
    missed runs — they are simply outside the cron's history."""
    raw = (get_settings().sync_schedule_since or "").strip()
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:  # a malformed date must not take the whole dashboard down
        return None


def schedule() -> dict:
    """The cron's expected fire time, for the dashboard to display back to the reader."""
    settings = get_settings()
    live_since = _live_since()
    return {
        "hour": settings.sync_schedule_hour,
        "weekdays": sorted(_scheduled_weekdays()),
        "timezone": settings.report_timezone,
        "live_since": live_since.isoformat() if live_since else None,
    }


def _as_utc(value: datetime) -> datetime:
    """Stamp a value read back from SQLite as UTC — stored naive, always UTC in fact."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _run_out(row: SyncLog, tz: ZoneInfo) -> dict:
    """One sync_logs row, rendered in local time with its duration precomputed."""
    started = _as_utc(row.started_at)
    finished = _as_utc(row.finished_at) if row.finished_at else None
    return {
        "id": row.id,
        "started_at": started.astimezone(tz).isoformat(),
        "finished_at": finished.astimezone(tz).isoformat() if finished else None,
        "status": row.status,
        "fetched": row.fetched,
        "created": row.created_count,
        "updated": row.updated_count,
        "transitions": row.transitions_count,
        "error": row.error,
        "duration_seconds": (
            round((finished - started).total_seconds(), 1) if finished else None
        ),
    }


def _day_state(
    runs: list[dict], on_schedule: list[dict], expected: bool, due: bool
) -> str:
    """Classify one local day.

    `on_schedule` is the subset of `runs` that started at or after the night's own fire
    time. On a night the cron was armed for, ONLY those can settle it: a hand-triggered
    sync at midday leaves the 20:00 job exactly as dead as no sync at all, and calling
    such a night green because the data happened to be fresh is what let a six-night
    outage hide behind the dashboard's "Sync all boards" button. Off a scheduled night
    every run counts, since there was no cron to satisfy in the first place.

    Within whichever set is being judged a success still wins over a failure, so a failed
    run followed by a successful retry is a healthy night rather than a failed one.
    """
    judged = on_schedule if expected else runs
    if any(r["status"] == "success" for r in judged):
        return STATE_OK
    if any(r["status"] == "running" for r in judged):
        return STATE_RUNNING
    if judged:
        return STATE_FAILED
    if not expected:
        return STATE_OFF
    if not due:
        return STATE_PENDING
    # Overdue with nothing on schedule: `runs` still tells us whether anything ran at all.
    return STATE_UNSCHEDULED if runs else STATE_MISSED


def _roll_up(days: list[dict]) -> str:
    """Board verdict: the latest DUE night decides ok/error; anything bad earlier in the
    window downgrades a healthy board to warn so a fixed-itself blip stays visible."""
    settled = [d for d in days if d["state"] not in (STATE_PENDING, STATE_OFF)]
    if not settled:
        return STATUS_OK
    if settled[-1]["state"] in _BAD_STATES:
        return STATUS_ERROR
    if any(d["state"] in _BAD_STATES for d in settled):
        return STATUS_WARN
    return STATUS_OK


def board_health(db: Session, days: int) -> dict:
    """One board's sync health over the last `days` local days, most recent day last."""
    tz = _tz()
    hour = get_settings().sync_schedule_hour
    weekdays = _scheduled_weekdays()

    live_since = _live_since()
    now_local = datetime.now(timezone.utc).astimezone(tz)
    window = [now_local.date() - timedelta(days=n) for n in range(days - 1, -1, -1)]

    # Naive UTC bound, matching how the column is stored.
    since = datetime.combine(window[0], time.min, tzinfo=tz).astimezone(timezone.utc)
    rows = (
        db.query(SyncLog)
        .filter(SyncLog.started_at >= since.replace(tzinfo=None))
        .order_by(SyncLog.started_at.asc())
        .all()
    )

    by_day: dict[date, list[dict]] = {}
    for row in rows:
        local_day = _as_utc(row.started_at).astimezone(tz).date()
        by_day.setdefault(local_day, []).append(_run_out(row, tz))

    day_rows = []
    for day in window:
        runs = by_day.get(day, [])
        armed = live_since is None or day >= live_since
        expected = armed and day.isoweekday() in weekdays
        fire_at = datetime.combine(day, time(hour), tzinfo=tz)
        due = now_local >= fire_at + _MISSED_GRACE
        # `started_at` went out as a local ISO string, so it parses back tz-aware and
        # compares directly against this night's fire time.
        on_schedule = [
            r for r in runs if datetime.fromisoformat(r["started_at"]) >= fire_at
        ]
        day_rows.append({
            "date": day.isoformat(),
            "weekday": day.isoweekday(),
            "expected": expected,
            "state": _day_state(runs, on_schedule, expected, due),
            "runs": runs,
        })

    last_run = next(
        (r for d in reversed(day_rows) for r in reversed(d["runs"])), None
    )
    return {
        "status": _roll_up(day_rows),
        "last_run": last_run,
        "days": day_rows,
        "missed_days": [d["date"] for d in day_rows if d["state"] == STATE_MISSED],
        "failed_days": [d["date"] for d in day_rows if d["state"] == STATE_FAILED],
        "unscheduled_days": [
            d["date"] for d in day_rows if d["state"] == STATE_UNSCHEDULED
        ],
    }
