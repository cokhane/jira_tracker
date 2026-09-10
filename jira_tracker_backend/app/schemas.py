"""Pydantic response schemas — the API's public contract (what React consumes)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    jira_id: str | None = None
    summary: str | None = None
    description: str | None = None
    issue_type: str | None = None
    status: str | None = None
    status_category: str | None = None
    priority: str | None = None
    assignee: str | None = None
    reporter: str | None = None
    labels: list[str] = []
    components: list[str] = []
    resolution: str | None = None
    created: str | None = None
    updated: str | None = None
    web_url: str | None = None
    synced_at: datetime | None = None


class IssueListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[IssueOut]


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str
    fetched: int
    created_count: int
    updated_count: int
    transitions_count: int = 0
    error: str | None = None


class MetaOut(BaseModel):
    statuses: list[str]
    assignees: list[str]
    issue_types: list[str]
    labels: list[str]


class ProjectOut(BaseModel):
    """One configured board — powers the UI board switcher."""
    key: str
    name: str


class PingOut(BaseModel):
    ok: bool
    account_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    detail: str | None = None


# ---------- reporting ----------

class MetricRow(BaseModel):
    """One person's 5 movement counts for a single day/week bucket."""

    bucket: date  # day (granularity=day) or week-start Monday (granularity=week)
    person: str
    pulled_from_todo: int = 0
    sent_back_by_qa: int = 0
    to_in_progress: int = 0
    to_blocked: int = 0
    to_done: int = 0


class ScorecardOut(BaseModel):
    granularity: str
    by: str  # "assignee" | "mover"
    start: date | None = None
    end: date | None = None
    rows: list[MetricRow]


class ColumnFlowRow(BaseModel):
    """Movement in/out of one board column for a single day/week bucket."""

    bucket: date
    status: str
    entered: int = 0
    left: int = 0
    net: int = 0  # entered - left


class ColumnFlowOut(BaseModel):
    granularity: str
    start: date | None = None
    end: date | None = None
    rows: list[ColumnFlowRow]


class MovementRow(BaseModel):
    """One person's 'sent to' counts (distinct tickets) for a day/week bucket."""

    bucket: date
    to_code_review: int = 0
    to_qa_testing: int = 0
    to_done: int = 0


class MovementOut(BaseModel):
    name: str
    granularity: str
    by: str  # "assignee" | "mover"
    start: date | None = None
    end: date | None = None
    total_code_review: int = 0
    total_qa_testing: int = 0
    total_done: int = 0
    rows: list[MovementRow]


# ---------- worklog (per-person time log) ----------

class WorklogRow(BaseModel):
    """One ticket on a person's time-log view: hours they logged + the outcome."""

    key: str
    summary: str | None = None
    web_url: str | None = None
    seconds: int | None = None       # total the person logged on this ticket; None = n/a
    time_spent: str | None = None    # Jira-style "1h 30m", or None → rendered as "n/a"


class WorklogOut(BaseModel):
    name: str
    total_seconds: int = 0
    total_time_spent: str | None = None  # formatted sum across logged rows
    rows: list[WorklogRow]


# ---------- daily snapshots ----------

class SnapshotItem(BaseModel):
    """One ticket as it appeared on the board on a snapshot date."""

    model_config = ConfigDict(from_attributes=True)

    issue_key: str
    summary: str | None = None
    assignee: str | None = None
    status: str | None = None
    status_category: str | None = None
    issue_type: str | None = None
    epic_key: str | None = None
    epic_name: str | None = None
    web_url: str | None = None


class SnapshotBoardOut(BaseModel):
    snapshot_date: date
    total: int
    assignees: list[str]  # distinct assignees in this snapshot (for the filter)
    statuses: list[str]   # board columns present, in board order
    epics: list[str]      # distinct epic names present (for the filter)
    items: list[SnapshotItem]


class SnapshotDate(BaseModel):
    snapshot_date: date
    total: int
    sprint_name: str | None = None      # the real Jira sprint this snapshot came from
    sprint_start: date | None = None
    sprint_end: date | None = None


class SnapshotResult(BaseModel):
    snapshot_date: date
    issues: int
    message: str


# ---------- sprint report ----------

class SprintReportDomain(BaseModel):
    """One domain (epic) row of the sprint report."""

    name: str
    count: int
    pct: float  # share of the sprint's tickets, 0-100


class SprintReportStatus(BaseModel):
    status: str
    count: int


class SprintReportType(BaseModel):
    """Ticket-type bucket (Stories / Tasks / Bugs / Other)."""

    type: str
    count: int


class SprintReportAssignee(BaseModel):
    name: str
    total: int
    completed: int
    pct: float  # share of the sprint's tickets, 0-100


class SprintReportOut(BaseModel):
    """Everything the sprint deck needs, aggregated from one day's snapshot."""

    requested_date: date          # the day the user picked
    as_of_date: date              # snapshot actually used (== requested, or nearest earlier)
    sprint_name: str | None = None
    sprint_start: date | None = None
    sprint_end: date | None = None
    total: int
    completed: int
    in_progress: int
    todo: int
    completion_rate: float        # completed / total, 0-100
    domains: list[SprintReportDomain]
    statuses: list[SprintReportStatus]
    types: list[SprintReportType]
    assignees: list[SprintReportAssignee]


# ---------- sprint-compare (two boards → the 9-slide deck) ----------


class SprintCompareBreakdown(BaseModel):
    """One member's line on the ticket-breakdown slide."""

    name: str
    assigned: int
    completed: int
    incomplete: int  # assigned - completed


class SprintCompareDoneItem(BaseModel):
    """A ticket line (key + title + who it's on) — used for the Key Achievements
    (completed) and Roadblocks (blocked) slides."""

    key: str
    title: str
    developer: str  # the roster developer it's credited to (or current assignee)


class DevDeliveryRow(BaseModel):
    """One developer's delivery funnel for a sprint: each ticket they moved out of
    'In Progress' this sprint, counted once at the FURTHEST stage it reached."""

    name: str
    code_review: int = 0
    qa_testing: int = 0
    merged: int = 0
    deployment: int = 0
    done: int = 0
    total: int = 0


class SprintLastActionRow(BaseModel):
    """One developer's credited tickets bucketed by the STATUS their last dev action left
    the ticket in (cumulative board-state — decomposes the 'Assigned' total)."""

    name: str
    code_review: int = 0
    qa_testing: int = 0
    merged: int = 0     # shipped: Merged / Deployment / Done
    other: int = 0      # In Progress / To Do / Blocked / etc.
    total: int = 0



class SprintCompareSprint(BaseModel):
    """One board (a sprint's end-of-sprint / latest snapshot) after roster filtering."""

    sprint_name: str
    as_of_date: date | None = None
    sprint_start: date | None = None
    sprint_end: date | None = None
    total: int
    completed: int
    in_progress: int
    todo: int
    completion_rate: float
    projects: list[SprintReportDomain]     # by Jira project (only Nexus in our data)
    types: list[SprintReportType]          # Stories / Tasks / Bugs / Other
    assignees: list[SprintReportAssignee]  # team performance (total / completed / %)
    breakdown: list[SprintCompareBreakdown]
    completed_items: list[SprintCompareDoneItem] = []  # done tickets (for achievements)
    blocked_items: list[SprintCompareDoneItem] = []    # blocked tickets (for roadblocks)
    delivery: list[DevDeliveryRow] = []                # per-dev furthest-stage funnel
    last_action: list[SprintLastActionRow] = []        # per-dev credited tickets by last-move status


class SprintCompareOut(BaseModel):
    """Everything the two-board 9-slide deck needs."""

    project_name: str  # board display name (from the resolved ProjectConfig)
    generated_on: date

    # headline stats (slide 1 / 2)
    completed: int          # dev-complete board-state in the closing sprint (incl. QA)
    shipped_this_sprint: int = 0  # tickets that newly reached a shipped status this sprint
    in_qa_at_close: int = 0       # dev-done but not shipped on the closing snapshot (QA backlog)
    carry_over: int         # incomplete in closing AND present in kickoff
    new_work: int           # in kickoff, not in closing
    committed: int = 0                                    # real kickoff commitment = carry_over + new_work
    committed_types: list[SprintReportType] = []          # committed tickets bucketed by type
    projects_covered: int   # distinct Jira projects in the closing board

    closing: SprintCompareSprint
    kickoff: SprintCompareSprint


# ---- Developer KPI scorecard (the KPI Tracker view) -------------------------------------

class DevKpiRow(BaseModel):
    """One developer's sprint scorecard: what they were planned for, what they delivered,
    and how cleanly they delivered it.

    Percentages are whole-number-friendly floats (one decimal), not ratios, so the view
    renders them without re-deriving anything the server already decided.
    """

    name: str
    target: int = 0          # planned capacity for this sprint (Capacity Tracker grid)
    # True when the Capacity Tracker has no cell for this developer and `target` is the
    # board default — flagged, not hidden, because Delivery % against an assumed target is
    # not the same claim as Delivery % against a plan the team actually made.
    target_is_default: bool = False
    done: int = 0            # delivered — the furthest-stage funnel total
    delivery_pct: float = 0.0
    reopened: int = 0        # QA send-backs landing on this developer
    reopen_pct: float = 0.0
    blocked: int = 0         # their tickets that entered Blocked this sprint
    wip: int = 0             # still In Progress on the closing board
    rating: float = 0.0      # 0-100 composite
    stars: int = 1           # 1-5 bucket of `rating`

    # ---- the two fields only the all-sprints view fills ---------------------------------
    # One model serves both KPI surfaces, because a KPI line is the same nine numbers
    # whether it covers one sprint or eleven — a near-identical second model is how the two
    # tables would drift apart on what a column means.
    #
    # Which sprint this line covers. None on a per-sprint row (the sprint is on DevKpiOut)
    # and on an all-sprints TOTAL row (it spans them all); set on a history row below.
    sprint_name: str | None = None
    # The sprints this total is made of, oldest → newest — empty on any single-sprint row.
    # Present so the view can show a developer's whole run without a request per sprint.
    history: list["DevKpiRow"] = []


class DevKpiOut(BaseModel):
    """The Developer KPI scorecard for one sprint of one board."""

    sprint_name: str
    as_of_date: date | None = None     # the snapshot the WIP column is read from
    sprint_start: date | None = None
    sprint_end: date | None = None
    rows: list[DevKpiRow] = []


class DevKpiOverallOut(BaseModel):
    """Every roster developer's KPI summed over every sprint this board has data for.

    `rows` carries one TOTAL row per developer, each with its per-sprint `history`.
    """

    sprint_names: list[str] = []       # the exact range aggregated, oldest → newest
    as_of_date: date | None = None     # newest sprint's snapshot — what WIP is read from
    first_start: date | None = None    # start of the oldest sprint counted
    last_end: date | None = None       # end of the newest sprint counted
    rows: list[DevKpiRow] = []


class WeeklyQAItem(BaseModel):
    """One ticket on the accomplishments list (what got moved forward this week)."""

    key: str
    title: str
    engineer: str  # crediting QA engineer (latest roster mover, else current assignee)


class WeeklyQAEngineer(BaseModel):
    """One QA engineer's line on the per-engineer breakdown."""

    name: str
    moved_forward: int  # tickets moved to a done status OR labelled QA_PASSED
    sent_back: int      # tickets failed QA (QA_FAILED / left QA Testing → not done)
    blocked: int        # tickets moved to Blocked


class WeeklyQAAsk(BaseModel):
    """One 'What we need from leadership' row — operator-provided, rendered verbatim."""

    ask: str
    owner: str = ""
    why: str = ""
    needed_by: str = ""


class WeeklyQAOut(BaseModel):
    """Everything the weekly QA activity deck needs, aggregated for one week."""

    project_name: str  # board display name (from the resolved ProjectConfig)
    generated_on: date
    week_start: date
    week_end: date

    # team totals (distinct tickets, gated to activity in the week)
    moved_forward: int
    sent_back: int
    blocked: int

    accomplishments: list[WeeklyQAItem] = []
    engineers: list[WeeklyQAEngineer] = []
    asks: list[WeeklyQAAsk] = []


# ---- Capacity Tracker (the Rolling Sprint Capacity grid) --------------------------------

class CapacityCell(BaseModel):
    """One developer's plan and result for one sprint.

    `capacity` is derived (the rolling rule) for every sprint but the first; `actual` is
    the number the team types in, and is None until they do.
    """

    sprint_number: int
    capacity: int | None = None
    actual: int | None = None


class CapacityDeveloper(BaseModel):
    """One row of the grid — the developer plus a cell per sprint, oldest sprint first."""

    developer: str
    cells: list[CapacityCell]


class CapacitySprint(BaseModel):
    """One column pair of the grid, dated from the board's own sprint calendar."""

    number: int
    label: str
    start: date
    end: date
    is_current: bool


class CapacityGridOut(BaseModel):
    """The whole Capacity Tracker view for one board."""

    sprints: list[CapacitySprint] = []
    developers: list[CapacityDeveloper] = []
    # Names in the workbook that aren't on this board's roster (reported, never dropped
    # silently) — populated on the import that seeds the grid.
    skipped: list[str] = []


class CapacityActualIn(BaseModel):
    """Write one cell's actual. `value` of None clears it back to blank."""

    sprint_number: int
    developer: str
    value: int | None = None
