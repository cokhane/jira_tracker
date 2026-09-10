"""API / presentation layer — FastAPI app, routing, CORS, request validation.

This layer is thin: it parses requests, calls the service/integration layers, and
shapes responses with Pydantic schemas. No business logic or JQL lives here.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from datetime import date, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, case, distinct, func, or_
from sqlalchemy.orm import Session

from app import capacity_store, schemas
from app.config import ProjectConfig, get_settings, reload_settings
from app.database import dispose_engines, get_cfg, get_db, get_engine, init_db
from app.jira_client import JiraClient, JiraError
from app.models import DailySnapshot, Issue, SprintCapacity, StatusTransition, SyncLog, Worklog
from app.projects import get_registry, reload_registry, resolve_cfg
from app.sync import PastSnapshotError, run_sync, sync_and_snapshot
from app.sync_health import board_health, schedule as sync_schedule


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create + migrate every configured board's DB on startup
    yield


app = FastAPI(
    title="Jira Tracker API",
    description="Pulls issues from multiple Jira boards into per-board SQLite DBs and serves them.",
    version="2.0.0",
    lifespan=lifespan,
)

# All board-scoped endpoints live under /api/{project}; the get_db / get_cfg dependencies
# resolve the board from the path and bind the right per-board DB. Global endpoints
# (health, ping, projects list, sync-all) stay on `app` directly.
router = APIRouter(prefix="/api/{project}")

# CORS is configured once at startup from the current .env. (Unlike the token and
# report settings, which are re-read per request, changing CORS_ORIGINS still needs a
# restart — allowed origins are baked into the middleware here.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- health & connection ----------

@app.get("/health", tags=["meta"])
def health():
    """Liveness — proves the server runs. Needs no Jira token."""
    return {"status": "ok", "jira_configured": get_settings().jira_configured}


@app.post("/api/config/reload", tags=["meta"])
def config_reload():
    """Force a re-read of .env AND projects.yaml without restarting.

    Settings/registry are re-read automatically when their file timestamps change; this
    is the manual escape hatch (rotated token, unchanged mtime, env-var-only deploy).
    Disposes cached board engines so a changed db_file in the registry takes effect.
    """
    s = reload_settings()
    reload_registry()
    dispose_engines()
    return {"reloaded": True, "jira_configured": s.jira_configured, "projects": len(get_registry())}


@app.get("/api/jira/ping", response_model=schemas.PingOut, tags=["meta"])
def jira_ping():
    """Test the Jira token against /myself before syncing anything."""
    try:
        me = JiraClient(get_settings()).myself()
        return schemas.PingOut(
            ok=True,
            account_id=me.get("accountId"),
            display_name=me.get("displayName"),
            email=me.get("emailAddress"),
        )
    except JiraError as exc:
        return schemas.PingOut(ok=False, detail=str(exc))


# ---------- projects (board registry) ----------

@app.get("/api/projects", response_model=list[schemas.ProjectOut], tags=["meta"])
def list_projects():
    """Configured boards (key + display name) — powers the UI board switcher."""
    return [schemas.ProjectOut(key=e.key, name=e.name) for e in get_registry()]


def _run_for_all_boards(work):
    """Run `work(entry, cfg, db)` for every board concurrently, one session per board.

    Boards are fully isolated (one engine + SQLite file each, see app/database.py), so the
    per-board pulls run in parallel threads with no shared DB — cutting the all-boards wall
    time toward the slowest single board instead of the sum of all three.

    `work` must catch its own per-board errors and return a result dict, so one board never
    aborts the others. Engines are resolved on the calling thread (already warmed by
    init_db) so the non-thread-safe first-call engine creation never races between workers.
    Results come back in registry order.
    """
    prepared = [
        (e, resolve_cfg(e.key), get_engine(e.key, e.db_file)[1])
        for e in get_registry()
    ]

    def _one(entry, cfg, maker):
        db = maker()
        try:
            return work(entry, cfg, db)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=len(prepared) or 1) as pool:
        futures = [pool.submit(_one, e, cfg, maker) for e, cfg, maker in prepared]
        return [f.result() for f in futures]  # order preserved


@app.post("/api/sync-all", tags=["sync"])
def sync_all(
    full: bool = Query(True, description="Full pull (True) or incremental (False)."),
):
    """Sync every configured board into its own DB, in parallel. One board's failure is
    recorded but never aborts the others (this is the cron entrypoint)."""
    def work(entry, cfg, db):
        try:
            log = run_sync(db, cfg, full=full)
            return {
                "key": entry.key, "status": log.status,
                "fetched": log.fetched, "created": log.created_count,
                "updated": log.updated_count, "error": log.error,
            }
        except Exception as exc:  # noqa: BLE001 — never let one board abort the others
            return {"key": entry.key, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return {"projects": _run_for_all_boards(work)}


@app.post("/api/snapshot-all", tags=["snapshots"])
def snapshot_all(
    target: date | None = Query(None, description="Day to snapshot; defaults to today."),
    force: bool = Query(False, description="Required to overwrite a past day's snapshot."),
):
    """Sync + snapshot every configured board into its own DB, in parallel. Per-board errors
    are recorded (a past-day snapshot without force → that board reports a 409-style error)
    without aborting the others."""
    def work(entry, cfg, db):
        try:
            result = sync_and_snapshot(db, cfg, snapshot_date=target, force=force)
            return {
                "key": entry.key, "status": "success",
                "snapshot_date": str(result["snapshot_date"]), "issues": result["issues"],
            }
        except PastSnapshotError as exc:
            return {"key": entry.key, "status": "conflict", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"key": entry.key, "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return {"projects": _run_for_all_boards(work)}


@app.get("/api/sync-health", tags=["sync"])
def sync_health(
    days: int = Query(14, ge=1, le=90, description="How many local days to report."),
):
    """Health of the nightly sync across every board — the Sync Health dashboard's feed.

    Reports each board's recent runs AND the nights the cron was expected to fire but
    never did. A job that never starts writes no sync_logs row, so a view built only on
    the rows that exist would stay green while the schedule was silently dead; see
    app/sync_health.py for how the expected nights are reconstructed.
    """
    def work(entry, cfg, db):
        try:
            return {"key": entry.key, "name": entry.name, **board_health(db, days)}
        except Exception as exc:  # noqa: BLE001 — one board's DB never hides the others
            return {
                "key": entry.key, "name": entry.name, "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "last_run": None, "days": [], "missed_days": [], "failed_days": [],
                "unscheduled_days": [],
            }

    return {"schedule": sync_schedule(), "projects": _run_for_all_boards(work)}


# ---------- sync ----------

@router.post("/sync", response_model=schemas.SyncLogOut, tags=["sync"])
def trigger_sync(
    full: bool = Query(True, description="Full pull (True) or only issues changed since last sync (False)."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Manual sync — pull this board from Jira and upsert into its DB. Idempotent."""
    log = run_sync(db, cfg, full=full)
    if log.status == "error":
        raise HTTPException(status_code=502, detail=log.error or "Sync failed")
    return log


@router.get("/sync/history", response_model=list[schemas.SyncLogOut], tags=["sync"])
def sync_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return (
        db.query(SyncLog).order_by(SyncLog.id.desc()).limit(limit).all()
    )


# ---------- issues ----------

@router.get("/issues", response_model=schemas.IssueListOut, tags=["issues"])
def list_issues(
    status: str | None = None,
    assignee: str | None = None,
    issue_type: str | None = None,
    label: str | None = None,
    q: str | None = Query(None, description="Text search in key/summary/description."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(Issue)
    if status:
        query = query.filter(Issue.status == status)
    if assignee:
        query = query.filter(Issue.assignee == assignee)
    if issue_type:
        query = query.filter(Issue.issue_type == issue_type)
    if label:
        # labels is a JSON array; match rows whose JSON array contains the label.
        query = query.filter(Issue.labels.contains([label]))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Issue.key.ilike(like),
                Issue.summary.ilike(like),
                Issue.description.ilike(like),
            )
        )

    total = query.count()
    items = (
        query.order_by(Issue.updated.desc()).offset(offset).limit(limit).all()
    )
    return schemas.IssueListOut(total=total, limit=limit, offset=offset, items=items)


@router.get("/issues/blocked", response_model=schemas.IssueListOut, tags=["issues"])
def list_blocked_issues(
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Only the tickets sitting in the board's **Blocked** column."""
    query = db.query(Issue).filter(Issue.status == "Blocked")
    total = query.count()
    items = query.order_by(Issue.updated.desc()).offset(offset).limit(limit).all()
    return schemas.IssueListOut(total=total, limit=limit, offset=offset, items=items)


@router.get("/issues/{key}", response_model=schemas.IssueOut, tags=["issues"])
def get_issue(key: str, db: Session = Depends(get_db)):
    issue = db.get(Issue, key.upper())
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {key} not found")
    return issue


# ---------- daily snapshots ----------

# Board columns in left-to-right order; anything unknown is appended after these.
_BOARD_ORDER = [
    "To Do", "In Progress", "Blocked", "Code Review",
    "Merged", "QA Testing", "Deployment", "Done",
]


@router.post("/snapshot", response_model=schemas.SnapshotResult, tags=["snapshots"])
def take_snapshot(
    target: date | None = Query(None, description="Day to snapshot; defaults to today."),
    force: bool = Query(False, description="Required to overwrite a past day's snapshot."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Sync button: pull the board from Jira and save it as `target`'s snapshot.

    Always deletes that day's rows and reinserts the fresh pull. Past days need `force`.
    """
    try:
        result = sync_and_snapshot(db, cfg, snapshot_date=target, force=force)
    except PastSnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except JiraError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return schemas.SnapshotResult(
        snapshot_date=result["snapshot_date"],
        issues=result["issues"],
        message=f"Saved {result['issues']} tickets for {result['snapshot_date']}.",
    )


@router.get("/snapshots", response_model=list[schemas.SnapshotDate], tags=["snapshots"])
def list_snapshot_dates(db: Session = Depends(get_db), cfg: ProjectConfig = Depends(get_cfg)):
    """Dates that have a saved snapshot, newest first (powers the date picker)."""
    rows = (
        db.query(
            DailySnapshot.snapshot_date.label("snapshot_date"),
            func.count().label("total"),
            func.max(DailySnapshot.sprint_name).label("sprint_name"),
            func.max(DailySnapshot.sprint_start).label("sprint_start"),
            func.max(DailySnapshot.sprint_end).label("sprint_end"),
        )
        .group_by(DailySnapshot.snapshot_date)
        .order_by(DailySnapshot.snapshot_date.desc())
        .all()
    )
    out = []
    for r in rows:
        name, start, end = r.sprint_name, r.sprint_start, r.sprint_end
        if not name:  # fallback for snapshots taken before sprint capture existed
            n, start, end = cfg.sprint_for(r.snapshot_date)
            name = f"Sprint {n}"
        out.append(schemas.SnapshotDate(
            snapshot_date=r.snapshot_date, total=r.total,
            sprint_name=name, sprint_start=start, sprint_end=end,
        ))
    return out


@router.get("/snapshots/{snapshot_date}", response_model=schemas.SnapshotBoardOut, tags=["snapshots"])
def get_snapshot(
    snapshot_date: date,
    assignee: str | None = Query(None, description="Filter the board to one assignee."),
    db: Session = Depends(get_db),
):
    """The board exactly as it looked on `snapshot_date`, optionally one assignee."""
    query = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == snapshot_date)
    if assignee:
        query = query.filter(DailySnapshot.assignee == assignee)

    items = query.all()
    if not items and not assignee:
        # Distinguish "no snapshot taken that day" from "assignee has nothing".
        exists = db.query(DailySnapshot).filter(
            DailySnapshot.snapshot_date == snapshot_date
        ).first()
        if not exists:
            raise HTTPException(status_code=404, detail=f"No snapshot saved for {snapshot_date}.")

    # Distinct assignees across the WHOLE day's snapshot (so the filter list is stable).
    all_assignees = sorted({
        a for (a,) in db.query(DailySnapshot.assignee)
        .filter(DailySnapshot.snapshot_date == snapshot_date)
        .distinct().all() if a
    })

    present = {i.status for i in items if i.status}
    statuses = [s for s in _BOARD_ORDER if s in present] + sorted(present - set(_BOARD_ORDER))

    epics = sorted({
        e for (e,) in db.query(DailySnapshot.epic_name)
        .filter(DailySnapshot.snapshot_date == snapshot_date)
        .distinct().all() if e
    })

    # Order items by board column then key, so the frontend can render columns directly.
    order = {s: n for n, s in enumerate(statuses)}
    items.sort(key=lambda i: (order.get(i.status, 999), i.issue_key))

    return schemas.SnapshotBoardOut(
        snapshot_date=snapshot_date,
        total=len(items),
        assignees=all_assignees,
        statuses=statuses,
        epics=epics,
        items=items,
    )


# ---------- reports ----------
#
# Counting model (see /api/reports docs): metrics count DISTINCT TICKETS per bucket,
# not raw transition events — so a ticket that bounces into a column 5× in a week
# counts once. Bot movers (settings.report_exclude_movers) are excluded so the
# numbers reflect human work, not Jira automation.

def _bucket_col(granularity: str):
    """Pick the grouping column: calendar day or Monday-of-week."""
    return (
        StatusTransition.change_date
        if granularity == "day"
        else StatusTransition.week_start
    )


def _exclude_bots(query, cfg: ProjectConfig):
    """Drop transitions performed by configured bot movers (keeps NULL movers)."""
    excluded_movers = cfg.excluded_movers
    if excluded_movers:
        query = query.filter(
            or_(
                StatusTransition.moved_by.is_(None),
                StatusTransition.moved_by.notin_(excluded_movers),
            )
        )
    return query


# The two movement predicates the scorecard and the dev-KPI both count. Named once here so
# the two surfaces can never disagree about what a send-back or a block IS — they were
# inline in the scorecard query, which made "reopened" mean one thing per caller.
def _qa_send_back():
    """A QA send-back: the ticket left QA Testing for anything that isn't Done."""
    return and_(
        StatusTransition.from_status == "QA Testing",
        StatusTransition.to_category != "Done",
    )


def _entered_blocked():
    """The ticket moved into the Blocked column."""
    return StatusTransition.to_status == "Blocked"


@router.get("/reports/scorecard", response_model=schemas.ScorecardOut, tags=["reports"])
def scorecard(
    granularity: str = Query("day", pattern="^(day|week)$"),
    by: str = Query("assignee", pattern="^(assignee|mover)$", description="Attribute to the task's assignee or to whoever performed the move."),
    assignee: str | None = Query(None, description="Limit to one person (matches the chosen attribution)."),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Per-person movement scorecard: the 5 metrics per assignee, as distinct tickets."""
    bucket = _bucket_col(granularity)
    person = (
        StatusTransition.assignee_at if by == "assignee" else StatusTransition.moved_by
    )

    def count_tickets(condition):
        # distinct issue keys (per bucket+person) where the condition holds
        return func.count(distinct(case((condition, StatusTransition.issue_key))))

    query = _exclude_bots(
        db.query(
            bucket.label("bucket"),
            person.label("person"),
            count_tickets(StatusTransition.from_status == "To Do").label("pulled_from_todo"),
            count_tickets(_qa_send_back()).label("sent_back_by_qa"),
            count_tickets(StatusTransition.to_status == "In Progress").label("to_in_progress"),
            count_tickets(_entered_blocked()).label("to_blocked"),
            count_tickets(StatusTransition.to_status.in_(["Deployment", "Done"])).label("to_done"),
        ).filter(person.isnot(None)),
        cfg,
    )

    if assignee:
        query = query.filter(person == assignee)
    if start:
        query = query.filter(StatusTransition.change_date >= start)
    if end:
        query = query.filter(StatusTransition.change_date <= end)

    rows = (
        query.group_by(bucket, person)
        .order_by(bucket.desc(), person)
        .all()
    )
    return schemas.ScorecardOut(
        granularity=granularity, by=by, start=start, end=end,
        rows=[schemas.MetricRow(**r._asdict()) for r in rows],
    )


@router.get("/reports/column-flow", response_model=schemas.ColumnFlowOut, tags=["reports"])
def column_flow(
    granularity: str = Query("day", pattern="^(day|week)$"),
    status: str | None = Query(None, description="Limit to one board column; omit for all columns."),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Per-column movement: tickets that entered / left / net per day or week."""
    bucket = _bucket_col(granularity)

    def date_filtered(q):
        q = _exclude_bots(q, cfg)
        if start:
            q = q.filter(StatusTransition.change_date >= start)
        if end:
            q = q.filter(StatusTransition.change_date <= end)
        return q

    # entered = moved INTO a column (to_status); left = moved OUT of a column (from_status).
    # Counted as distinct tickets per bucket, consistent with the scorecard.
    entered_q = date_filtered(
        db.query(
            bucket.label("bucket"),
            StatusTransition.to_status.label("status"),
            func.count(distinct(StatusTransition.issue_key)).label("n"),
        ).filter(StatusTransition.to_status.isnot(None))
    )
    left_q = date_filtered(
        db.query(
            bucket.label("bucket"),
            StatusTransition.from_status.label("status"),
            func.count(distinct(StatusTransition.issue_key)).label("n"),
        ).filter(StatusTransition.from_status.isnot(None))
    )
    if status:
        entered_q = entered_q.filter(StatusTransition.to_status == status)
        left_q = left_q.filter(StatusTransition.from_status == status)

    entered_q = entered_q.group_by(bucket, StatusTransition.to_status)
    left_q = left_q.group_by(bucket, StatusTransition.from_status)

    # Merge the two aggregations into one (bucket, status) row each.
    flows: dict[tuple, dict] = {}
    for r in entered_q.all():
        flows.setdefault((r.bucket, r.status), {"entered": 0, "left": 0})["entered"] = r.n
    for r in left_q.all():
        flows.setdefault((r.bucket, r.status), {"entered": 0, "left": 0})["left"] = r.n

    rows = [
        schemas.ColumnFlowRow(
            bucket=b, status=s,
            entered=v["entered"], left=v["left"], net=v["entered"] - v["left"],
        )
        for (b, s), v in flows.items()
    ]
    rows.sort(key=lambda x: (x.bucket, x.status), reverse=True)
    return schemas.ColumnFlowOut(granularity=granularity, start=start, end=end, rows=rows)


@router.get("/reports/assignee/{name}", response_model=schemas.ScorecardOut, tags=["reports"])
def assignee_report(
    name: str,
    days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week)$"),
    by: str = Query("assignee", pattern="^(assignee|mover)$"),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Convenience time-series: one person's scorecard for the last `days` days."""
    cutoff = date.today() - timedelta(days=days)
    bucket = _bucket_col(granularity)
    person = (
        StatusTransition.assignee_at if by == "assignee" else StatusTransition.moved_by
    )

    def count_tickets(condition):
        return func.count(distinct(case((condition, StatusTransition.issue_key))))

    rows = (
        _exclude_bots(
            db.query(
                bucket.label("bucket"),
                person.label("person"),
                count_tickets(StatusTransition.from_status == "To Do").label("pulled_from_todo"),
                count_tickets(
                    and_(
                        StatusTransition.from_status == "QA Testing",
                        StatusTransition.to_category != "Done",
                    )
                ).label("sent_back_by_qa"),
                count_tickets(StatusTransition.to_status == "In Progress").label("to_in_progress"),
                count_tickets(StatusTransition.to_status == "Blocked").label("to_blocked"),
                count_tickets(StatusTransition.to_status.in_(["Deployment", "Done"])).label("to_done"),
            ),
            cfg,
        )
        .filter(person == name, StatusTransition.change_date >= cutoff)
        .group_by(bucket)
        .order_by(bucket.desc())
        .all()
    )
    return schemas.ScorecardOut(
        granularity=granularity, by=by, start=None, end=None,
        rows=[schemas.MetricRow(**r._asdict()) for r in rows],
    )


@router.get("/reports/assignee/{name}/movement", response_model=schemas.MovementOut, tags=["reports"])
def assignee_movement(
    name: str,
    granularity: str = Query("day", pattern="^(day|week)$"),
    by: str = Query("assignee", pattern="^(assignee|mover)$", description="Attribute to the ticket's assignee at the time, or to whoever performed the move."),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Day-by-day count of one person's tickets sent to Code Review / QA Testing / Done.

    Counts DISTINCT tickets per bucket (a ticket bounced into a column twice in one day
    counts once), excludes bot movers, and self-transitions are already dropped at ingest.
    """
    bucket = _bucket_col(granularity)
    person = (
        StatusTransition.assignee_at if by == "assignee" else StatusTransition.moved_by
    )

    def count_tickets(to_status):
        return func.count(distinct(case((StatusTransition.to_status == to_status, StatusTransition.issue_key))))

    query = _exclude_bots(
        db.query(
            bucket.label("bucket"),
            count_tickets("Code Review").label("to_code_review"),
            count_tickets("QA Testing").label("to_qa_testing"),
            count_tickets("Done").label("to_done"),
        ).filter(person == name),
        cfg,
    )
    if start:
        query = query.filter(StatusTransition.change_date >= start)
    if end:
        query = query.filter(StatusTransition.change_date <= end)

    rows = query.group_by(bucket).order_by(bucket.desc()).all()
    out_rows = [
        schemas.MovementRow(**r._asdict())
        for r in rows
        if r.to_code_review or r.to_qa_testing or r.to_done  # skip days with no CR/QA/Done moves
    ]
    return schemas.MovementOut(
        name=name, granularity=granularity, by=by, start=start, end=end,
        total_code_review=sum(r.to_code_review for r in out_rows),
        total_qa_testing=sum(r.to_qa_testing for r in out_rows),
        total_done=sum(r.to_done for r in out_rows),
        rows=out_rows,
    )


def _fmt_duration(seconds: int | None) -> str | None:
    """Seconds → Jira-style time string ('1h 30m', '35m', '1h'). None → None (→ 'n/a')."""
    if not seconds:
        return None
    hours, mins = divmod(round(seconds / 60), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


@router.get("/reports/assignee/{name}/worklog", response_model=schemas.WorklogOut, tags=["reports"])
def assignee_worklog(name: str, db: Session = Depends(get_db)):
    """One person's time log: every ticket they either logged time on or currently own,
    with the hours they clocked (attributed by worklog author, matching Jira). Tickets
    they own but never logged time against show `n/a`.
    """
    # Hours this person logged, summed per ticket (author attribution).
    logged_rows = (
        db.query(
            Worklog.issue_key,
            func.sum(Worklog.time_spent_seconds).label("seconds"),
            func.max(Worklog.summary).label("summary"),
            func.max(Worklog.web_url).label("web_url"),
        )
        .filter(Worklog.author == name)
        .group_by(Worklog.issue_key)
        .all()
    )
    logged = {
        r.issue_key: {"seconds": int(r.seconds or 0), "summary": r.summary, "web_url": r.web_url}
        for r in logged_rows
    }

    # Tickets they currently own (latest snapshot) — surfaced with n/a when unlogged.
    latest_date = db.query(func.max(DailySnapshot.snapshot_date)).scalar()
    assigned = {}
    if latest_date:
        for s in (
            db.query(DailySnapshot)
            .filter(DailySnapshot.snapshot_date == latest_date, DailySnapshot.assignee == name)
            .all()
        ):
            assigned[s.issue_key] = {"summary": s.summary, "web_url": s.web_url}

    rows = []
    total = 0
    for key in logged.keys() | assigned.keys():
        info = logged.get(key)
        meta = assigned.get(key) or {}
        seconds = info["seconds"] if info else None
        if seconds:
            total += seconds
        rows.append(
            schemas.WorklogRow(
                key=key,
                summary=(info or {}).get("summary") or meta.get("summary"),
                web_url=(info or {}).get("web_url") or meta.get("web_url"),
                seconds=seconds,
                time_spent=_fmt_duration(seconds),
            )
        )

    # Logged tickets first (most time on top), then the n/a tickets by key.
    rows.sort(key=lambda r: (r.seconds is None, -(r.seconds or 0), r.key))
    return schemas.WorklogOut(
        name=name,
        total_seconds=total,
        total_time_spent=_fmt_duration(total),
        rows=rows,
    )


# Map Jira issue types onto the deck's four buckets (Stories / Tasks / Bugs / Other).
_TYPE_BUCKETS = ["Stories", "Tasks", "Bugs", "Other"]


def _type_bucket(issue_type: str | None) -> str:
    t = (issue_type or "").strip().lower()
    if t == "story":
        return "Stories"
    if t in ("task", "sub-task", "subtask"):
        return "Tasks"
    if t == "bug":
        return "Bugs"
    return "Other"


def _is_done(row: DailySnapshot, cfg: ProjectConfig) -> bool:
    # "Done" = status_category Done, or any status in the configured done-list
    # (default Done / Deployment / Merged — this team ships to Merged, not Done).
    return (row.status_category or "").lower() == "done" or row.status in cfg.done_statuses


def _is_shipped(row: DailySnapshot, cfg: ProjectConfig) -> bool:
    # "Shipped" = merged and beyond (Merged / Deployment / Done). Narrower than done:
    # QA Testing counts as dev-done but NOT shipped, so this measures the merge line.
    return row.status in cfg.shipped_statuses


@router.get("/reports/sprint", response_model=schemas.SprintReportOut, tags=["reports"])
def sprint_report(
    date_: date = Query(..., alias="date", description="Any day; the report covers that day's board snapshot."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Aggregate one day's snapshot into a sprint deck report (totals, domains, types, team)."""
    # Use the exact day if it has a snapshot, else the most recent snapshot on/before it.
    exact = (
        db.query(DailySnapshot.snapshot_date)
        .filter(DailySnapshot.snapshot_date == date_)
        .first()
    )
    if exact:
        use_date = date_
    else:
        row = (
            db.query(DailySnapshot.snapshot_date)
            .filter(DailySnapshot.snapshot_date <= date_)
            .order_by(DailySnapshot.snapshot_date.desc())
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"No snapshot on or before {date_}.")
        use_date = row[0]

    rows = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == use_date).all()
    total = len(rows)

    # Sprint context from the snapshot; fall back to the computed sprint if missing.
    sprint_name = next((r.sprint_name for r in rows if r.sprint_name), None)
    sprint_start = next((r.sprint_start for r in rows if r.sprint_start), None)
    sprint_end = next((r.sprint_end for r in rows if r.sprint_end), None)
    if not sprint_name:
        n, sprint_start, sprint_end = cfg.sprint_for(use_date)
        sprint_name = f"Sprint {n}"

    # Partition the board into three buckets that sum to `total`.
    completed = sum(1 for r in rows if _is_done(r, cfg))
    todo = sum(1 for r in rows if not _is_done(r, cfg) and (r.status_category or "").lower() == "to do")
    in_progress = total - completed - todo

    def pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    # By domain (epic)
    domain_counts: dict[str, int] = {}
    for r in rows:
        domain_counts[r.epic_name or "No Epic"] = domain_counts.get(r.epic_name or "No Epic", 0) + 1
    domains = [
        schemas.SprintReportDomain(name=name, count=c, pct=pct(c))
        for name, c in sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # By status, in board order then any extras
    status_counts: dict[str, int] = {}
    for r in rows:
        if r.status:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
    ordered = [s for s in _BOARD_ORDER if s in status_counts]
    ordered += sorted(s for s in status_counts if s not in _BOARD_ORDER)
    statuses = [schemas.SprintReportStatus(status=s, count=status_counts[s]) for s in ordered]

    # By type bucket (always the four, in deck order)
    type_counts = {b: 0 for b in _TYPE_BUCKETS}
    for r in rows:
        type_counts[_type_bucket(r.issue_type)] += 1
    types = [schemas.SprintReportType(type=b, count=type_counts[b]) for b in _TYPE_BUCKETS]

    # By assignee: total + completed
    agg: dict[str, dict[str, int]] = {}
    for r in rows:
        name = r.assignee or "Unassigned"
        a = agg.setdefault(name, {"total": 0, "completed": 0})
        a["total"] += 1
        if _is_done(r, cfg):
            a["completed"] += 1
    assignees = [
        schemas.SprintReportAssignee(name=name, total=v["total"], completed=v["completed"], pct=pct(v["total"]))
        for name, v in sorted(agg.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    ]

    return schemas.SprintReportOut(
        requested_date=date_,
        as_of_date=use_date,
        sprint_name=sprint_name,
        sprint_start=sprint_start,
        sprint_end=sprint_end,
        total=total,
        completed=completed,
        in_progress=in_progress,
        todo=todo,
        completion_rate=pct(completed),
        domains=domains,
        statuses=statuses,
        types=types,
        assignees=assignees,
    )


# ---------- sprint comparison (two boards → the 9-slide deck) ----------

def _project_of(issue_key: str | None, cfg: ProjectConfig) -> str:
    """Friendly board name for an issue key. Each DB holds one board, so a key whose
    prefix matches this board resolves to its display name; anything else keeps its prefix."""
    prefix = (issue_key or "").split("-")[0]
    if prefix == cfg.key:
        return cfg.name
    return prefix or "Unknown"


# Developer delivery funnel — furthest-stage ladder (board progression order).
_DELIVERY_STAGES = ["Code Review", "QA Testing", "Merged", "Deployment", "Done"]
# Rank IS the ladder order — derived, never hand-numbered, so the two cannot drift apart
# (a hand-written map once ranked Deployment below Merged, hiding every deployed ticket).
_DELIVERY_RANK = {stage: rank for rank, stage in enumerate(_DELIVERY_STAGES)}



def _compute_dev_delivery(db, cfg: ProjectConfig, roster, bots, start, end) -> list[schemas.DevDeliveryRow]:
    """Per-developer delivery funnel for a sprint.

    A ticket is credited to the developer who moved it OUT of 'In Progress' (the
    reliable dev hand-off — devs click In Progress→Code Review, whereas QA/PM click the
    later moves). Scoped to hand-offs dated in [start, end]. Each ticket is counted ONCE,
    in the FURTHEST stage it ever reached (Code Review→QA Testing→Merged→Deployment→Done),
    regardless of who clicked those later moves. Bots are excluded.
    """
    roster_set = set(roster)
    empty = [schemas.DevDeliveryRow(name=n) for n in roster]
    if start is None or end is None:
        return empty

    project = cfg.key
    rows = (
        db.query(StatusTransition)
        .filter(StatusTransition.issue_key.like(f"{project}-%"))
        .filter((StatusTransition.moved_by.is_(None)) | (StatusTransition.moved_by.notin_(bots)))
        .order_by(StatusTransition.changed_at)
        .all()
    )
    by_ticket: dict[str, list] = {}
    for t in rows:
        by_ticket.setdefault(t.issue_key, []).append(t)

    agg: dict[str, dict[str, int]] = {n: {s: 0 for s in _DELIVERY_STAGES} for n in roster}
    for ts in by_ticket.values():
        handoffs = [t for t in ts if t.from_status == "In Progress" and t.moved_by]
        pick = next((t for t in handoffs if t.to_status == "Code Review"), None) or (
            handoffs[-1] if handoffs else None
        )
        if not pick or pick.moved_by not in roster_set:
            continue
        if pick.change_date is None or not (start <= pick.change_date <= end):
            continue
        reached = [t.to_status for t in ts if t.to_status in _DELIVERY_RANK]
        if not reached:
            continue
        furthest = max(reached, key=lambda s: _DELIVERY_RANK[s])
        agg[pick.moved_by][furthest] += 1

    out = [
        schemas.DevDeliveryRow(
            name=n,
            code_review=agg[n]["Code Review"],
            qa_testing=agg[n]["QA Testing"],
            merged=agg[n]["Merged"],
            deployment=agg[n]["Deployment"],
            done=agg[n]["Done"],
            total=sum(agg[n].values()),
        )
        for n in roster
    ]
    out.sort(key=lambda r: (-r.total, r.name))
    return out


def _latest_snapshot_for_sprint(db: Session, sprint_name: str):
    """The last snapshot date captured for a given sprint (its end-of-sprint board)."""
    row = (
        db.query(func.max(DailySnapshot.snapshot_date))
        .filter(DailySnapshot.sprint_name == sprint_name)
        .first()
    )
    return row[0] if row and row[0] else None


def _prior_sprint_name(db: Session, sprint_name: str) -> str | None:
    """The sprint immediately before `sprint_name` — the one whose latest snapshot date is
    the greatest still older than this sprint's. Its board is the baseline for measuring
    what shipped DURING `sprint_name`. Returns None when this is the earliest sprint."""
    as_of = _latest_snapshot_for_sprint(db, sprint_name)
    if not as_of:
        return None
    rows = (
        db.query(DailySnapshot.sprint_name, func.max(DailySnapshot.snapshot_date).label("d"))
        .filter(DailySnapshot.sprint_name.isnot(None), DailySnapshot.sprint_name != "")
        .group_by(DailySnapshot.sprint_name)
        .having(func.max(DailySnapshot.snapshot_date) < as_of)
        .order_by(func.max(DailySnapshot.snapshot_date).desc())
        .first()
    )
    return rows[0] if rows else None


def _keys_on(db: Session, cfg: ProjectConfig, snapshot_date, predicate) -> set[str]:
    """Set of this board's issue keys at `snapshot_date` whose row satisfies `predicate`."""
    if not snapshot_date:
        return set()
    rows = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == snapshot_date).all()
    return {
        r.issue_key
        for r in rows
        if (r.issue_key or "").split("-")[0] == cfg.jira_project and predicate(r)
    }


def _build_compare_sprint(all_rows, attribution, sprint_name, as_of, start, end, cfg: ProjectConfig, delivery=None, last_status=None) -> schemas.SprintCompareSprint:
    """Sprint-wide totals (overview, by-project, by-type) count EVERYONE (`all_rows`);
    the per-developer slides (team performance, ticket breakdown) credit each ticket
    to one roster developer via `attribution` (issue_key -> developer name)."""
    total = len(all_rows)

    def pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    completed = sum(1 for r in all_rows if _is_done(r, cfg))
    todo = sum(1 for r in all_rows if not _is_done(r, cfg) and (r.status_category or "").lower() == "to do")
    in_progress = total - completed - todo

    # Completed work by project (only Nexus in our data) — counts everyone's
    # done+deployment tickets. % is of the completed count.
    def pct_done(n: int) -> float:
        return round(n / completed * 100, 1) if completed else 0.0

    proj_counts: dict[str, int] = {}
    for r in all_rows:
        if _is_done(r, cfg):
            p = _project_of(r.issue_key, cfg)
            proj_counts[p] = proj_counts.get(p, 0) + 1
    projects = [
        schemas.SprintReportDomain(name=name, count=c, pct=pct_done(c))
        for name, c in sorted(proj_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # By type bucket (always the four, in deck order) — sprint-wide.
    type_counts = {b: 0 for b in _TYPE_BUCKETS}
    for r in all_rows:
        type_counts[_type_bucket(r.issue_type)] += 1
    types = [schemas.SprintReportType(type=b, count=type_counts[b]) for b in _TYPE_BUCKETS]

    # Per-developer totals + completed — ROSTER only (the team slides). Each ticket
    # is credited to the latest roster developer who worked on it (from changelog
    # history; falls back to the current assignee). % is of the whole-sprint total.
    agg: dict[str, dict[str, int]] = {}
    for r in all_rows:
        dev = attribution.get(r.issue_key)
        if not dev:
            continue  # no roster developer worked this ticket
        a = agg.setdefault(dev, {"total": 0, "completed": 0})
        a["total"] += 1
        if _is_done(r, cfg):
            a["completed"] += 1
    ordered = sorted(agg.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    assignees = [
        schemas.SprintReportAssignee(name=n, total=v["total"], completed=v["completed"], pct=pct(v["total"]))
        for n, v in ordered
    ]
    breakdown = [
        schemas.SprintCompareBreakdown(
            name=n, assigned=v["total"], completed=v["completed"], incomplete=v["total"] - v["completed"]
        )
        for n, v in ordered
    ]

    # Per-developer breakdown of credited tickets by the status their LAST dev action left
    # the ticket in — decomposes each dev's "Assigned" total (Code Review / QA / Merged / Other).
    ship_set = set(cfg.shipped_statuses)
    ls = last_status or {}
    la_agg: dict[str, dict[str, int]] = {}
    for r in all_rows:
        dev = attribution.get(r.issue_key)
        if not dev:
            continue
        st = ls.get(r.issue_key, r.status)
        if st == "Code Review":
            bucket = "code_review"
        elif st == "QA Testing":
            bucket = "qa_testing"
        elif st in ship_set:
            bucket = "merged"
        else:
            bucket = "other"
        la = la_agg.setdefault(dev, {"code_review": 0, "qa_testing": 0, "merged": 0, "other": 0})
        la[bucket] += 1
    last_action = [
        schemas.SprintLastActionRow(
            name=n,
            code_review=v["code_review"], qa_testing=v["qa_testing"],
            merged=v["merged"], other=v["other"],
            total=v["code_review"] + v["qa_testing"] + v["merged"] + v["other"],
        )
        for n, v in sorted(la_agg.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    ]

    # Done tickets credited to a roster developer — the raw material for slide 7.
    completed_items = sorted(
        (
            schemas.SprintCompareDoneItem(
                key=r.issue_key, title=r.summary or "", developer=attribution[r.issue_key]
            )
            for r in all_rows
            if _is_done(r, cfg) and r.issue_key in attribution
        ),
        key=lambda x: (x.developer, x.key),
    )

    # Blocked tickets — the raw material for slide 8 (roadblocks). Owner = the roster
    # developer credited via history, else the current assignee.
    blocked_items = sorted(
        (
            schemas.SprintCompareDoneItem(
                key=r.issue_key,
                title=r.summary or "",
                developer=attribution.get(r.issue_key) or r.assignee or "Unassigned",
            )
            for r in all_rows
            if (r.status or "") == "Blocked"
        ),
        key=lambda x: (x.developer, x.key),
    )

    return schemas.SprintCompareSprint(
        sprint_name=sprint_name,
        as_of_date=as_of,
        sprint_start=start,
        sprint_end=end,
        total=total,
        completed=completed,
        in_progress=in_progress,
        todo=todo,
        completion_rate=pct(completed),
        projects=projects,
        types=types,
        assignees=assignees,
        breakdown=breakdown,
        completed_items=completed_items,
        blocked_items=blocked_items,
        delivery=delivery or [],
        last_action=last_action,
    )


def _attribute_roster(db: Session, all_rows, roster_set: set[str], bots: set[str]):
    """Credit each ticket to the latest roster developer who moved it (changelog), else the
    current assignee if they're on the roster. Returns (attr, last_status) keyed by issue."""
    keys = [r.issue_key for r in all_rows]
    latest: dict[str, tuple] = {}  # issue_key -> (changed_at, developer, to_status)
    if keys:
        trans = db.query(StatusTransition).filter(StatusTransition.issue_key.in_(keys)).all()
        for t in trans:
            mover = t.moved_by
            if mover in roster_set and mover not in bots and t.changed_at is not None:
                cur = latest.get(t.issue_key)
                if cur is None or t.changed_at > cur[0]:
                    latest[t.issue_key] = (t.changed_at, mover, t.to_status)
    attr: dict[str, str] = {}
    last_status: dict[str, str] = {}
    for r in all_rows:
        if r.issue_key in latest:
            attr[r.issue_key] = latest[r.issue_key][1]
            last_status[r.issue_key] = latest[r.issue_key][2]
        elif r.assignee in roster_set:
            attr[r.issue_key] = r.assignee
            last_status[r.issue_key] = r.status
    return attr, last_status


def _load_sprint(db: Session, cfg: ProjectConfig, roster, bots, sprint_name: str):
    """Load one sprint's closing board + roster attribution + delivery funnel.

    Returns (all_rows, attr, last_status, as_of, start, end, delivery). Raises 404 when the
    sprint has no snapshot. Shared by the sprint-compare and dev-kpi report paths."""
    as_of = _latest_snapshot_for_sprint(db, sprint_name)
    if not as_of:
        raise HTTPException(status_code=404, detail=f"No snapshot found for sprint '{sprint_name}'.")
    rows = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == as_of).all()
    all_rows = [
        r
        for r in rows
        if (r.issue_key or "").split("-")[0] == cfg.jira_project and r.sprint_name == sprint_name
    ]
    start = next((r.sprint_start for r in all_rows if r.sprint_start), None)
    end = next((r.sprint_end for r in all_rows if r.sprint_end), None)
    delivery = _compute_dev_delivery(db, cfg, roster, bots, start, end)
    attr, last_status = _attribute_roster(db, all_rows, set(roster), bots)
    return all_rows, attr, last_status, as_of, start, end, delivery



def _newest_sprint(db: Session) -> str | None:
    """The sprint name of the most recent snapshot captured (the current/active sprint)."""
    row = (
        db.query(DailySnapshot.sprint_name)
        .filter(DailySnapshot.sprint_name.isnot(None), DailySnapshot.sprint_name != "")
        .order_by(DailySnapshot.snapshot_date.desc())
        .first()
    )
    return row[0] if row else None


def _sprint_names(db: Session) -> list[str]:
    """Every sprint this board has snapshots for, oldest → newest.

    Ordered by each sprint's LATEST snapshot date — the same ordering `_prior_sprint_name`
    walks backwards — because sprint NAMES don't sort chronologically ("Sprint 10" lands
    before "Sprint 9"). Unnamed rows are dropped: "Unassigned sprint" is a bucket, not a
    period, so it has no window to measure anything over.
    """
    rows = (
        db.query(DailySnapshot.sprint_name)
        .filter(DailySnapshot.sprint_name.isnot(None), DailySnapshot.sprint_name != "")
        .group_by(DailySnapshot.sprint_name)
        .order_by(func.max(DailySnapshot.snapshot_date))
        .all()
    )
    return [r[0] for r in rows]



def _compute_sprint_compare(
    db: Session, cfg: ProjectConfig, closing: str, kickoff: str, assignees: str | None
) -> schemas.SprintCompareOut:
    """Aggregate two sprint boards into the SprintCompareOut the 9-slide deck needs.

    Sprint-wide numbers (overview, carry-over, new-work, by-project, by-type) count
    EVERY assignee on the board; team-performance and ticket-breakdown count only the
    report roster.
    """
    roster = (
        [a.strip() for a in assignees.split(",") if a.strip()]
        if assignees
        else cfg.report_assignee_list
    )
    bots = set(cfg.excluded_movers)

    c_all, c_attr, c_las, c_as_of, c_start, c_end, c_deliv = _load_sprint(db, cfg, roster, bots, closing)
    k_all, k_attr, k_las, k_as_of, k_start, k_end, k_deliv = _load_sprint(db, cfg, roster, bots, kickoff)

    closing_block = _build_compare_sprint(
        c_all, c_attr, closing, c_as_of, c_start, c_end, cfg, c_deliv, c_las
    )
    kickoff_block = _build_compare_sprint(
        k_all, k_attr, kickoff, k_as_of, k_start, k_end, cfg, k_deliv, k_las
    )

    # Cross-board deltas by issue key — whole board, regardless of assignee.
    closing_keys = {r.issue_key for r in c_all}
    closing_incomplete = {r.issue_key for r in c_all if not _is_done(r, cfg)}
    kickoff_keys = {r.issue_key for r in k_all}
    carry_over = len(closing_incomplete & kickoff_keys)
    new_work = len(kickoff_keys - closing_keys)

    # Shipped THIS sprint (velocity): tickets that newly reached a shipped status between
    # the prior sprint's board and this sprint's — not the cumulative count of shipped
    # tickets still tagged to the sprint. Baseline is empty for the earliest sprint.
    baseline = _prior_sprint_name(db, closing)
    baseline_as_of = _latest_snapshot_for_sprint(db, baseline) if baseline else None
    closing_shipped = _keys_on(db, cfg, c_as_of, lambda r: _is_shipped(r, cfg))
    baseline_shipped = _keys_on(db, cfg, baseline_as_of, lambda r: _is_shipped(r, cfg))
    shipped_this_sprint = len(closing_shipped - baseline_shipped)
    # In QA at close: dev-done but not yet shipped on the closing board (board-state).
    in_qa_at_close = len({r.issue_key for r in c_all if _is_done(r, cfg)} - closing_shipped)

    # Real kickoff commitment = the carry-over + new-work tickets only (not the whole
    # board, which still carries already-shipped tickets from prior sprints).
    committed_keys = (closing_incomplete & kickoff_keys) | (kickoff_keys - closing_keys)
    committed_type_counts = {b: 0 for b in _TYPE_BUCKETS}
    for r in k_all:
        if r.issue_key in committed_keys:
            committed_type_counts[_type_bucket(r.issue_type)] += 1
    committed_types = [
        schemas.SprintReportType(type=b, count=committed_type_counts[b]) for b in _TYPE_BUCKETS
    ]

    return schemas.SprintCompareOut(
        project_name=cfg.name,
        generated_on=date.today(),
        completed=closing_block.completed,
        shipped_this_sprint=shipped_this_sprint,
        in_qa_at_close=in_qa_at_close,
        carry_over=carry_over,
        new_work=new_work,
        committed=len(committed_keys),
        committed_types=committed_types,
        projects_covered=len(closing_block.projects),
        closing=closing_block,
        kickoff=kickoff_block,
    )


@router.get("/reports/sprint-compare", response_model=schemas.SprintCompareOut, tags=["reports"])
def sprint_compare(
    closing: str = Query(..., description="Closing sprint name (e.g. 'NEX Sprint 1')."),
    kickoff: str = Query(..., description="Kickoff sprint name (e.g. 'NEX Sprint 2')."),
    assignees: str | None = Query(None, description="Optional CSV override of the report roster."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Compare two sprint boards into the data behind the 9-slide closure/kickoff deck."""
    return _compute_sprint_compare(db, cfg, closing, kickoff, assignees)


@router.get("/reports/sprint-compare.md", tags=["reports"])
def sprint_compare_md(
    closing: str = Query(..., description="Closing sprint name (e.g. 'NEX Sprint 1')."),
    kickoff: str = Query(..., description="Kickoff sprint name (e.g. 'NEX Sprint 2')."),
    assignees: str | None = Query(None, description="Optional CSV override of the report roster."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """The full 9-slide deck content as Markdown — no API key needed. Paste into
    another LLM context (or a slides skill) to build the .pptx."""
    from fastapi import Response
    from app.report_render import render_deck_markdown

    compare = _compute_sprint_compare(db, cfg, closing, kickoff, assignees)
    md = render_deck_markdown(compare)
    filename = f"{cfg.key.lower()}_{closing}_vs_{kickoff}.md".replace(" ", "_")
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- developer KPI scorecard ----------
#
# Powers the KPI Tracker view ONLY. Deliberately not wired into any report: the generated
# sprint report and the decks carry no per-developer rating (see report_render.py), and that
# stays true — a rating is a conversation to have with a developer, not a slide to hand out.
#
# Three different attributions meet in one row, because the three questions have three
# different right answers:
#   Done     -> the developer who moved the ticket OUT of In Progress (_compute_dev_delivery)
#   Reopened -> the developer who OWNED the ticket when QA sent it back (assignee_at)
#   Blocked  -> same; whoever clicked Blocked is rarely whose work it is
#   WIP      -> the current assignee on the closing board (board state)

# Rating weights — what a sprint asks of a developer, in the order it asks it. Tunable on
# purpose: these are a judgement about the team, not a fact about the data.
_RATING_DELIVERY_WEIGHT = 0.50
_RATING_QUALITY_WEIGHT = 0.35
_RATING_FLOW_WEIGHT = 0.15
# Score -> stars, highest cut-off first; anything below the last one is a single star.
_STAR_CUTOFFS = [(85, 5), (70, 4), (50, 3), (30, 2)]


def _stars(score: float) -> int:
    """The 1-5 bucket of a 0-100 rating. One home for the cut-offs, so a per-sprint rating
    and an all-sprints rating can never wear a different number of stars for the same score."""
    return next((s for cutoff, s in _STAR_CUTOFFS if score >= cutoff), 1)


def _rating(done: int, target: int, reopened: int, blocked: int) -> tuple[float, int]:
    """A 0-100 composite of delivery, quality and flow, plus its 1-5 star bucket.

    Delivery is CAPPED at 100% of target, so a developer who ships 300% of their plan
    cannot buy their way out of a quality problem — the metric rewards delivering AND
    delivering cleanly, never raw volume. Quality is 0 when nothing was delivered, since
    "no send-backs" on no work is not evidence of quality.
    """
    delivery = min(done / target, 1.0) if target else 0.0
    quality = 1.0 - min(reopened / done, 1.0) if done else 0.0
    flow = 1.0 - min(blocked / max(done, 1), 1.0)
    score = 100 * (
        _RATING_DELIVERY_WEIGHT * delivery
        + _RATING_QUALITY_WEIGHT * quality
        + _RATING_FLOW_WEIGHT * flow
    )
    return round(score, 1), _stars(score)


def _sprint_targets(db: Session, cfg: ProjectConfig, roster, sprint_start) -> dict[str, int | None]:
    """Each roster developer's planned capacity for the sprint containing `sprint_start`.

    Read from the Capacity Tracker's stored grid rather than from the capacity workbook:
    the grid IS the team's live plan (they type actuals into it and every later capacity
    rolls forward), so Target here and Capacity there can never show two different numbers.
    A developer the grid doesn't cover maps to None — the caller substitutes the board
    default AND flags it, rather than passing off an assumption as a plan.
    """
    if sprint_start is None:
        return {name: None for name in roster}
    number = cfg.sprint_for(sprint_start)[0]  # same placement rule the grid is built with
    stored = {
        row.developer: row.capacity
        for row in db.query(SprintCapacity).filter(SprintCapacity.sprint_number == number).all()
        if row.capacity is not None
    }
    return {name: stored.get(name) for name in roster}


def _qa_and_block_counts(db: Session, cfg: ProjectConfig, roster, start, end):
    """Per-developer QA send-backs and Blocked entries inside the sprint window.

    Attributed to `assignee_at` — who OWNED the ticket when it moved — not to the mover:
    QA performs the send-back and anyone can block a ticket, so crediting whoever clicked
    would put both counts on the wrong person. Returns (reopened, blocked) by name.
    """
    if start is None or end is None:
        return {}, {}
    person = StatusTransition.assignee_at

    def count_tickets(condition):
        return func.count(distinct(case((condition, StatusTransition.issue_key))))

    rows = (
        _exclude_bots(
            db.query(
                person.label("person"),
                count_tickets(_qa_send_back()).label("reopened"),
                count_tickets(_entered_blocked()).label("blocked"),
            )
            .filter(person.in_(roster))
            .filter(StatusTransition.change_date >= start)
            .filter(StatusTransition.change_date <= end),
            cfg,
        )
        .group_by(person)
        .all()
    )
    return ({r.person: r.reopened for r in rows}, {r.person: r.blocked for r in rows})


def _wip_counts(all_rows, roster) -> dict[str, int]:
    """In-Progress tickets per developer on the sprint's closing board.

    Board state, so it reads the row's current assignee — unlike the movement metrics,
    "what is on someone's plate right now" is a question about ownership, not about moves.
    """
    counts = {name: 0 for name in roster}
    for row in all_rows:
        if row.status == "In Progress" and row.assignee in counts:
            counts[row.assignee] += 1
    return counts


def _compute_dev_kpi(
    db: Session, cfg: ProjectConfig, sprint_name: str, assignees: str | None
) -> schemas.DevKpiOut:
    """Assemble one sprint's KPI scorecard, one row per roster developer."""
    roster = (
        [a.strip() for a in assignees.split(",") if a.strip()]
        if assignees
        else cfg.report_assignee_list
    )
    bots = set(cfg.excluded_movers)
    all_rows, _attr, _last, as_of, start, end, delivery = _load_sprint(
        db, cfg, roster, bots, sprint_name
    )

    targets = _sprint_targets(db, cfg, roster, start)
    reopened, blocked = _qa_and_block_counts(db, cfg, roster, start, end)
    wip = _wip_counts(all_rows, roster)
    done_by = {row.name: row.total for row in delivery}

    rows = []
    for name in roster:
        planned, done = targets[name], done_by.get(name, 0)
        target = cfg.dev_target_default if planned is None else planned
        reopens, blocks = reopened.get(name, 0), blocked.get(name, 0)
        rating, stars = _rating(done, target, reopens, blocks)
        rows.append(
            schemas.DevKpiRow(
                name=name,
                target=target,
                target_is_default=planned is None,
                done=done,
                delivery_pct=round(done / target * 100, 1) if target else 0.0,
                reopened=reopens,
                reopen_pct=round(reopens / done * 100, 1) if done else 0.0,
                blocked=blocks,
                wip=wip.get(name, 0),
                rating=rating,
                stars=stars,
            )
        )
    rows.sort(key=lambda r: (-r.rating, r.name))
    return schemas.DevKpiOut(
        sprint_name=sprint_name,
        as_of_date=as_of,
        sprint_start=start,
        sprint_end=end,
        rows=rows,
    )


@router.get("/reports/dev-kpi", response_model=schemas.DevKpiOut, tags=["reports"])
def dev_kpi(
    sprint: str | None = Query(None, description="Sprint name; defaults to the current one."),
    assignees: str | None = Query(None, description="Optional CSV override of the report roster."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Per-developer KPI scorecard for one sprint — the KPI Tracker view's only source."""
    name = sprint or _newest_sprint(db)
    if not name:
        raise HTTPException(status_code=404, detail="No snapshots yet — sync this board first.")
    return _compute_dev_kpi(db, cfg, name, assignees)


# ---------- the same scorecard, over every sprint ----------
#
# "What has this developer done over the whole run?" — one TOTAL row per developer built by
# summing their per-sprint rows, each row kept alongside as `history` so the total can be
# opened up and checked against the sprints it came from. Built ON TOP of _compute_dev_kpi
# rather than beside it: an all-sprints number that disagreed with the sprint it came from
# would discredit both.


def _has_footprint(row: schemas.DevKpiRow) -> bool:
    """Whether a sprint is evidence about this developer at all.

    The roster is board-level config, not per-sprint, so every developer gets a row for
    every sprint — including the sprints before they joined the team. Averaging those in
    would score people for time they weren't here.

    A sprint with a real Capacity Tracker cell ALWAYS counts: a sprint that was planned and
    delivered nothing is a genuine zero, and hiding it would be the more flattering lie.
    Without a plan, the sprint counts only if the developer touched it — delivered, was sent
    back, was blocked, or held work in progress.
    """
    if not row.target_is_default:
        return True
    return bool(row.done or row.reopened or row.blocked or row.wip)


def _aggregate_kpi(name: str, history: list[schemas.DevKpiRow]) -> schemas.DevKpiRow:
    """Sum one developer's counted sprint rows into their all-sprints TOTAL row.

    Counts add up, and the two rates are recomputed FROM those totals rather than averaged —
    averaging percentages would weigh a 2-ticket sprint the same as a 20-ticket one. Two
    columns deliberately don't sum:

    **WIP** is the newest counted sprint's value. It is a point-in-time count of what sits on
    someone's plate; yesterday's plate plus today's plate is not a quantity.

    **Rating** is the MEAN of the per-sprint ratings, NOT `_rating` re-run on the totals.
    The formula's whole point is that delivery caps at target *per sprint*, so volume alone
    can't buy a score — re-running it on totals launders exactly that, letting four 0/10
    sprints and one 40/10 sprint read as a flawless 100%. The mean keeps every sprint's cap,
    and it makes the total the plain average of the history rows shown beneath it.

    `target_is_default` here means "at least one of these sprints had no plan", so a total
    resting partly on assumed targets still carries the badge.
    """
    target = sum(r.target for r in history)
    done = sum(r.done for r in history)
    reopened = sum(r.reopened for r in history)
    rating = round(sum(r.rating for r in history) / len(history), 1) if history else 0.0
    return schemas.DevKpiRow(
        name=name,
        target=target,
        target_is_default=any(r.target_is_default for r in history),
        done=done,
        delivery_pct=round(done / target * 100, 1) if target else 0.0,
        reopened=reopened,
        reopen_pct=round(reopened / done * 100, 1) if done else 0.0,
        blocked=sum(r.blocked for r in history),
        wip=history[-1].wip if history else 0,
        rating=rating,
        stars=_stars(rating),
        history=history,
    )


def _compute_dev_kpi_overall(
    db: Session, cfg: ProjectConfig, assignees: str | None
) -> schemas.DevKpiOverallOut:
    """One TOTAL row per roster developer, over every sprint this board has snapshots for."""
    names = _sprint_names(db)
    if not names:
        raise HTTPException(status_code=404, detail="No snapshots yet — sync this board first.")

    boards = [_compute_dev_kpi(db, cfg, name, assignees) for name in names]
    # Seed from the first board so a developer whose every sprint is uncounted still gets a
    # row — an empty history reads as "no data", which is the honest answer for them.
    history: dict[str, list[schemas.DevKpiRow]] = {row.name: [] for row in boards[0].rows}
    for board in boards:
        for row in board.rows:
            if _has_footprint(row):
                history.setdefault(row.name, []).append(
                    row.model_copy(update={"sprint_name": board.sprint_name})
                )

    rows = [_aggregate_kpi(name, hist) for name, hist in history.items()]
    rows.sort(key=lambda r: (-r.rating, r.name))
    return schemas.DevKpiOverallOut(
        sprint_names=names,
        as_of_date=boards[-1].as_of_date,
        first_start=next((b.sprint_start for b in boards if b.sprint_start), None),
        last_end=next((b.sprint_end for b in reversed(boards) if b.sprint_end), None),
        rows=rows,
    )


@router.get("/reports/dev-kpi/overall", response_model=schemas.DevKpiOverallOut, tags=["reports"])
def dev_kpi_overall(
    assignees: str | None = Query(None, description="Optional CSV override of the report roster."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Per-developer KPI over EVERY sprint this board has data for — the KPI Tracker's
    all-sprints mode. Each row carries its per-sprint `history`, so a total can be opened
    up and traced to the sprints that produced it."""
    return _compute_dev_kpi_overall(db, cfg, assignees)


# ---------- weekly QA activity report ----------
#
# A QA-framed weekly deck built from the movement history (status_transitions) plus
# the QA outcome labels (QA_PASSED / QA_FAILED) on the issues. Everything is gated to
# tickets that saw activity in the selected week, so labels — which carry no timestamp
# of their own — get a weekly anchor. Distinct-ticket counting + bot exclusion match
# the scorecard.

def _has_label(labels, name: str) -> bool:
    """Case-insensitive membership test against an issue's JSON labels array."""
    target = (name or "").strip().upper()
    return any((l or "").strip().upper() == target for l in (labels or []))


def _default_week_start(db: Session, cfg: ProjectConfig) -> date:
    """Most recent week present in the transition history (fallback: this week's Monday)."""
    row = db.query(func.max(StatusTransition.week_start)).first()
    return row[0] if row and row[0] else cfg.sprint_for(date.today())[1]


def _compute_weekly_qa(
    db: Session, cfg: ProjectConfig, week_start: date, assignees: str | None, asks: str | None
) -> schemas.WeeklyQAOut:
    settings = cfg
    week_end = week_start + timedelta(days=6)
    roster = (
        [a.strip() for a in assignees.split(",") if a.strip()]
        if assignees
        else settings.qa_report_assignee_list
    )
    roster_set = set(roster)
    done_set = set(settings.done_statuses)

    # All (bot-excluded) transitions inside the week — the activity window.
    wt = _exclude_bots(
        db.query(StatusTransition).filter(
            StatusTransition.change_date >= week_start,
            StatusTransition.change_date <= week_end,
        ),
        cfg,
    ).all()
    # Scope to this board's project (e.g. NEX-*).
    wt = [t for t in wt if (t.issue_key or "").split("-")[0] == settings.jira_project]

    active_keys = {t.issue_key for t in wt}

    # Candidate (changed_at, mover) pairs per ticket for attribution.
    movers_by_key: dict[str, list[tuple]] = {}
    for t in wt:
        if t.moved_by and t.changed_at is not None:
            movers_by_key.setdefault(t.issue_key, []).append((t.changed_at, t.moved_by))

    # Labels / summary / current assignee for the active tickets.
    meta_by_key: dict[str, dict] = {}
    if active_keys:
        for iss in db.query(Issue).filter(Issue.key.in_(active_keys)).all():
            meta_by_key[iss.key] = {
                "labels": iss.labels or [],
                "summary": iss.summary or "",
                "assignee": iss.assignee,
            }

    def labelled(key: str, name: str) -> bool:
        m = meta_by_key.get(key)
        return bool(m) and _has_label(m["labels"], name)

    # --- the three metric sets (distinct tickets) ---
    moved_forward = {t.issue_key for t in wt if t.to_status in done_set}
    moved_forward |= {k for k in active_keys if labelled(k, settings.qa_passed_label)}

    sent_back = {
        t.issue_key for t in wt
        if t.from_status == "QA Testing" and (t.to_category or "") != "Done"
    }
    sent_back |= {k for k in active_keys if labelled(k, settings.qa_failed_label)}

    blocked = {t.issue_key for t in wt if t.to_status == "Blocked"}

    def credit(key: str) -> str | None:
        """QA engineer credited with a ticket: latest roster mover in the week, else
        the current assignee. None only when a roster is set and no one qualifies."""
        cands = [
            (ts, m) for (ts, m) in movers_by_key.get(key, [])
            if not roster_set or m in roster_set
        ]
        if cands:
            return max(cands, key=lambda x: x[0])[1]
        a = (meta_by_key.get(key) or {}).get("assignee")
        if a and (not roster_set or a in roster_set):
            return a
        return None if roster_set else (a or "Unassigned")

    # --- per-engineer breakdown ---
    agg: dict[str, dict[str, int]] = {}
    for metric, keys in (("moved_forward", moved_forward), ("sent_back", sent_back), ("blocked", blocked)):
        for k in keys:
            name = credit(k)
            if not name:
                continue
            agg.setdefault(name, {"moved_forward": 0, "sent_back": 0, "blocked": 0})[metric] += 1
    engineers = [
        schemas.WeeklyQAEngineer(name=n, **v)
        for n, v in sorted(
            agg.items(),
            key=lambda kv: (-(kv[1]["moved_forward"] + kv[1]["sent_back"] + kv[1]["blocked"]), kv[0]),
        )
    ]

    # --- accomplishments (what moved forward) ---
    accomplishments = sorted(
        (
            schemas.WeeklyQAItem(
                key=k,
                title=(meta_by_key.get(k) or {}).get("summary", ""),
                engineer=credit(k) or "Unassigned",
            )
            for k in moved_forward
        ),
        key=lambda x: (x.engineer, x.key),
    )

    # --- operator-provided leadership asks ---
    ask_data = settings.qa_report_ask_list
    if asks:
        import json
        try:
            parsed = json.loads(asks)
            if isinstance(parsed, list):
                ask_data = parsed
        except (ValueError, TypeError):
            pass
    ask_rows = [
        schemas.WeeklyQAAsk(
            ask=str(a.get("ask", "")),
            owner=str(a.get("owner", "")),
            why=str(a.get("why", "")),
            needed_by=str(a.get("needed_by", "")),
        )
        for a in ask_data if isinstance(a, dict) and a.get("ask")
    ]

    return schemas.WeeklyQAOut(
        project_name=cfg.name,
        generated_on=date.today(),
        week_start=week_start,
        week_end=week_end,
        moved_forward=len(moved_forward),
        sent_back=len(sent_back),
        blocked=len(blocked),
        accomplishments=accomplishments,
        engineers=engineers,
        asks=ask_rows,
    )


@router.get("/reports/weekly-activity", response_model=schemas.WeeklyQAOut, tags=["reports"])
def weekly_activity(
    week_start: date | None = Query(None, description="Monday of the week; defaults to the latest week with activity."),
    assignees: str | None = Query(None, description="Optional CSV override of the QA roster."),
    asks: str | None = Query(None, description="Optional JSON array of leadership asks ({ask,owner,why,needed_by})."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Weekly QA activity: moved-forward / sent-back / blocked, per-engineer + accomplishments."""
    return _compute_weekly_qa(db, cfg, week_start or _default_week_start(db, cfg), assignees, asks)


@router.get("/reports/weekly-activity.md", tags=["reports"])
def weekly_activity_md(
    week_start: date | None = Query(None, description="Monday of the week; defaults to the latest week with activity."),
    assignees: str | None = Query(None),
    asks: str | None = Query(None),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """The weekly QA deck as Markdown — no API key needed."""
    from fastapi import Response
    from app.report_render import render_weekly_markdown

    report = _compute_weekly_qa(db, cfg, week_start or _default_week_start(db, cfg), assignees, asks)
    md = render_weekly_markdown(report)
    filename = f"weekly_qa_{cfg.key.lower()}_{report.week_start.isoformat()}.md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/weekly-activity.pptx", tags=["reports"])
def weekly_activity_pptx(
    week_start: date | None = Query(None, description="Monday of the week; defaults to the latest week with activity."),
    assignees: str | None = Query(None),
    asks: str | None = Query(None),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Render the weekly QA deck as a .pptx (Claude authors the narrative slides)."""
    from fastapi import Response
    from app.report_render import build_weekly_pptx, LlmNotConfigured

    report = _compute_weekly_qa(db, cfg, week_start or _default_week_start(db, cfg), assignees, asks)
    try:
        data = build_weekly_pptx(report, cfg.anthropic_api_key, cfg.report_llm_model)
    except LlmNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    filename = f"weekly_qa_{cfg.key.lower()}_{report.week_start.isoformat()}.pptx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- capacity tracker ----------

def _capacity_grid(db: Session, cfg: ProjectConfig,
                   skipped: list[str] | None = None) -> schemas.CapacityGridOut:
    """Shape this board's stored cells into the grid the Capacity Tracker renders.

    `skipped` overrides whatever the load reports: the import endpoint already holds the
    definitive list from the import it just ran, while a plain read only has one if that
    read is what seeded the board.
    """
    rows, auto_skipped = capacity_store.load_grid(db, cfg)
    numbers = capacity_store.sprint_numbers(rows)
    current = cfg.sprint_for(date.today())[0]

    by_developer: dict[str, list[schemas.CapacityCell]] = {}
    for row in rows:  # already ordered by sprint, so each developer's cells stay in order
        by_developer.setdefault(row.developer, []).append(
            schemas.CapacityCell(sprint_number=row.sprint_number,
                                 capacity=row.capacity, actual=row.actual)
        )

    return schemas.CapacityGridOut(
        sprints=[
            schemas.CapacitySprint(
                number=n, label=f"Sprint {n}",
                start=cfg.sprint_window(n)[0], end=cfg.sprint_window(n)[1],
                is_current=(n == current),
            )
            for n in numbers
        ],
        developers=[
            schemas.CapacityDeveloper(developer=name, cells=cells)
            for name, cells in sorted(by_developer.items())
        ],
        skipped=auto_skipped if skipped is None else skipped,
    )


@router.get("/capacity", response_model=schemas.CapacityGridOut, tags=["capacity"])
def capacity_grid(db: Session = Depends(get_db), cfg: ProjectConfig = Depends(get_cfg)):
    """The rolling capacity grid for this board — one Capacity/Actual pair per sprint.

    Seeds itself from `Rolling_Sprint_Capacity.xlsx` the first time a board is read, then
    lives in the DB: from that point the workbook is only a starting point, not the source.
    """
    return _capacity_grid(db, cfg)


@router.put("/capacity/actual", response_model=schemas.CapacityGridOut, tags=["capacity"])
def set_capacity_actual(
    body: schemas.CapacityActualIn,
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Save one developer's actual for one sprint and return the recomputed grid.

    Later sprints' capacities move with it — that's the rolling rule — so the whole grid
    comes back rather than just the edited cell.
    """
    if not capacity_store.set_actual(db, body.sprint_number, body.developer, body.value):
        raise HTTPException(
            status_code=404,
            detail=f"No capacity cell for {body.developer} in sprint {body.sprint_number}.",
        )
    return _capacity_grid(db, cfg)


@router.post("/capacity/developer", response_model=schemas.CapacityGridOut, tags=["capacity"])
def add_capacity_developer(
    developer: str = Query(..., description="Full Jira name, exactly as report_assignees spells it."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Put one roster developer onto this board's capacity grid.

    The non-destructive way in for someone who joined after the board was seeded: they get
    a row across the sprints already on the grid, and nobody else's typed actuals move.
    Roster-scoped like the seeding import, so a misspelt name is rejected here rather than
    becoming a row that no ticket will ever match.
    """
    if developer not in cfg.report_assignee_list:
        raise HTTPException(
            status_code=404,
            detail=f"{developer} isn't on this board's report roster.",
        )
    if not capacity_store.add_developer(db, cfg, developer):
        raise HTTPException(
            status_code=409,
            detail=f"{developer} is already on this capacity grid.",
        )
    return _capacity_grid(db, cfg)


@router.delete("/capacity/developer", response_model=schemas.CapacityGridOut, tags=["capacity"])
def remove_capacity_developer(
    developer: str = Query(..., description="Full Jira name, exactly as the grid shows it."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Take one developer off this board's capacity grid.

    Capacity-only: their `report_assignees` membership is untouched, so the sprint reports
    and comparison decks go on counting them. A later import won't re-add them either —
    that takes the POST above, or `POST /capacity/import?replace=true` to re-seed the
    whole roster.
    """
    if not capacity_store.remove_developer(db, developer):
        raise HTTPException(status_code=404, detail=f"{developer} isn't on this capacity grid.")
    return _capacity_grid(db, cfg)


@router.post("/capacity/import", response_model=schemas.CapacityGridOut, tags=["capacity"])
def import_capacity(
    replace: bool = Query(False, description="Wipe stored cells first — DISCARDS typed actuals."),
    db: Session = Depends(get_db),
    cfg: ProjectConfig = Depends(get_cfg),
):
    """Re-read the capacity workbook into this board's grid.

    Without `replace` this only fills gaps; with it, the sheet wins and anything typed in
    the app since the last import is lost.
    """
    return _capacity_grid(db, cfg, skipped=capacity_store.import_sheet(db, cfg, replace=replace))


@router.get("/meta", response_model=schemas.MetaOut, tags=["issues"])
def meta(db: Session = Depends(get_db)):
    """Distinct values for filter dropdowns (powers the React UI)."""
    def col(c):
        return [
            v[0]
            for v in db.query(distinct(c)).filter(c.isnot(None)).order_by(c).all()
            if v[0]
        ]

    # labels live inside JSON arrays — flatten across all issues.
    label_set: set[str] = set()
    for (labels,) in db.query(Issue.labels).filter(Issue.labels.isnot(None)).all():
        for lbl in labels or []:
            label_set.add(lbl)

    return schemas.MetaOut(
        statuses=col(Issue.status),
        assignees=col(Issue.assignee),
        issue_types=col(Issue.issue_type),
        labels=sorted(label_set),
    )


# Mount every board-scoped endpoint under /api/{project}.
app.include_router(router)
