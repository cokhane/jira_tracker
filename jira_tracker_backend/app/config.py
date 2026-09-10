"""Config layer — single source of truth for settings & secrets (12-factor style).

All values come from the environment / .env file. Nothing is hardcoded here so the
same code runs against any Jira site or project by changing .env only.
"""
import os
from datetime import date, timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict

# Path pydantic reads settings from (cwd-relative, matching SettingsConfigDict below).
_ENV_FILE = ".env"


class Settings(BaseSettings):
    # ---- Jira connection ----
    jira_base_url: str = "https://team-anervea.atlassian.net"
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project: str = "NEX"
    # When true, sync only pulls issues in the board's open (active) sprint(s).
    current_sprint_only: bool = True
    # Assignees permanently excluded — never fetched or stored (comma-separated).
    exclude_assignees: str = ""
    # Allow-list: if set, ONLY these assignees are kept (comma-separated). Takes
    # precedence over exclude_assignees. Empty = keep everyone (minus excludes).
    monitor_assignees: str = ""

    # ---- Storage ----
    database_url: str = "sqlite:///./jira_tracker.db"
    # Multi-board: each board gets its own SQLite file under this directory. The board
    # registry (per-board config) lives in the YAML file below. See app/projects.py.
    data_dir: str = "./data"
    projects_file: str = "projects.yaml"

    # ---- Merged-PR store (the weekly git-list-merge-pr report) ----
    # PR data is REPO-scoped, not board-scoped, and every weekly report spans all repos at
    # once, so it lives in ONE file under data_dir instead of being split per board like the
    # Jira tables. See app/pr_models.py for why it also gets its own declarative Base.
    pr_db_file: str = "prs.db"

    # GitHub repositories the PR report tracks. Set PER BOARD in projects.yaml
    # (`github_repos:`) — a repo belongs to exactly one board, so there is no sensible
    # global default; empty here means "this board tracks no repos".
    github_repos: str = ""

    # Title fragments that mark an environment-promotion PR. Their commits are already
    # counted under the feature PRs they came from, so reports exclude them from substantive
    # totals. Matched case-insensitively as a substring (comma-separated).
    pr_env_sync_titles: str = "develop to staging,staging to uat,uat to main,promote staging"

    # ---- CORS ----
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ---- Reporting ----
    # Day/week buckets for the movement reports are computed in this tz so that
    # day boundaries line up with the team's local calendar (default: Manila).
    report_timezone: str = "Asia/Manila"

    # Non-human movers (bots) excluded from the movement reports — their status
    # changes are real but shouldn't count toward a human scorecard.
    report_exclude_movers: str = "Automation for Jira"

    # Exclude "Done" tickets from daily snapshots. False = keep Done on the board.
    snapshot_exclude_done: bool = False

    # ---- Scheduled sync (the nightly all-boards cron) ----
    # The launchd job in scripts/ai.anervea.sync-all-boards.plist fires the all-boards sync
    # at this local hour on these days. Mirrored here ONLY so /api/sync-health can work out
    # which nights a run was expected and flag the ones that never happened — a job that
    # never fires writes no sync_logs row, so nothing else would notice it stopped.
    # KEEP IN STEP WITH THE PLIST: this is a description of the schedule, not its source.
    # The hour is read in `report_timezone` (Asia/Manila), matching launchd, which schedules
    # in the machine's local time.
    sync_schedule_hour: int = 20
    # ISO weekdays the job fires: 1=Monday … 7=Sunday. Default Mon-Sat (no Sunday run).
    sync_schedule_weekdays: str = "1,2,3,4,5,6"
    # The date the LaunchAgent was installed. Nights before it were never scheduled, so
    # they are not "missed" — without this the dashboard opens by blaming the cron for
    # every night in the window that predates it. Move this if the job is ever reinstalled.
    sync_schedule_since: str = "2026-09-02"

    # ---- Sprints ----
    # Sprints are weekly, Monday-Sunday (PH time). `sprint_anchor_date` is the Monday
    # that starts `sprint_anchor_number`; everything else is computed from it.
    sprint_anchor_date: str = "2026-06-22"   # Monday of Sprint 1
    sprint_anchor_number: int = 1
    sprint_length_days: int = 7

    # ---- Sprint-comparison report ----
    # Report-time allow-list: the sprint-compare deck only counts these people,
    # independent of the sync-time monitor_assignees list (comma-separated).
    # Empty = include everyone in the snapshots.
    report_assignees: str = (
        "Dan Denver De Leon,Dan Rudolf,Deinielle Cruz,"
        "Allen Mathew Cordero,Shane Michael Singwa,Sidney Buenaventura"
    )

    # Statuses that count as "completed/done" in the sprint reports. This team moves
    # finished dev work to "Merged" (not "Done"), so Merged counts. QA Testing also
    # counts — dev work is considered delivered once it's handed to QA. Comma-separated;
    # matched case-sensitively by status.
    report_done_statuses: str = "Done,Deployment,Merged,QA Testing"

    # Statuses that count as "shipped" — code merged and beyond (Merged / Deployment /
    # Done). Narrower than report_done_statuses: it EXCLUDES QA Testing, so "shipped"
    # measures work that actually crossed the merge line, not dev work handed to QA.
    report_shipped_statuses: str = "Done,Deployment,Merged"

    # ---- Developer KPI scorecard ----
    # Per-developer sprint target (planned capacity) used when the capacity workbook
    # has no match for a developer. Overridable per board in projects.yaml.
    dev_target_default: int = 10

    # Path to the "Rolling Sprint Capacity" workbook that SEEDS the Capacity Tracker grid.
    # Relative to the backend working directory. The KPI Target reads the grid, not this
    # file — the workbook is the starting point, the grid is the live plan — so a missing
    # or unreadable workbook leaves the grid (and every Target) on dev_target_default.
    capacity_workbook_path: str = "../Rolling_Sprint_Capacity.xlsx"

    # ---- Weekly QA activity report ----
    # Report-time allow-list of QA engineers for the weekly-activity deck. Empty =
    # include everyone who moved a ticket that week (minus bots). Comma-separated.
    qa_report_assignees: str = ""

    # Jira labels that flag a ticket's QA outcome (case-insensitive match against the
    # issue's `labels` array). A ticket carrying `qa_passed_label` counts as
    # moved-forward even before it reaches a done status; `qa_failed_label` marks a
    # ticket sent back to Dev after failing QA.
    qa_passed_label: str = "QA_PASSED"
    qa_failed_label: str = "QA_FAILED"

    # "What we need from leadership" asks — not derivable from data, so operator-provided.
    # A JSON array of {"ask","owner","why","needed_by"} objects rendered verbatim into
    # the deck. Empty = the slide lists no asks. Can be overridden per-request via `?asks=`.
    qa_report_asks: str = "[]"

    # ---- LLM (for PPTX slide authoring) ----
    anthropic_api_key: str = ""
    report_llm_model: str = "claude-opus-4-8"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def excluded_movers(self) -> list[str]:
        return [m.strip() for m in self.report_exclude_movers.split(",") if m.strip()]

    @property
    def excluded_assignees(self) -> list[str]:
        return [a.strip() for a in self.exclude_assignees.split(",") if a.strip()]

    @property
    def monitored_assignees(self) -> list[str]:
        """Allow-list of assignees to keep. Empty list = no allow-list (keep all)."""
        return [a.strip() for a in self.monitor_assignees.split(",") if a.strip()]

    @property
    def report_assignee_list(self) -> list[str]:
        """Report-time allow-list for the sprint-compare deck. Empty = everyone."""
        return [a.strip() for a in self.report_assignees.split(",") if a.strip()]

    @property
    def done_statuses(self) -> list[str]:
        """Statuses treated as completed in the sprint reports."""
        return [s.strip() for s in self.report_done_statuses.split(",") if s.strip()]

    @property
    def shipped_statuses(self) -> list[str]:
        """Statuses treated as shipped (merged and beyond) — narrower than done_statuses."""
        return [s.strip() for s in self.report_shipped_statuses.split(",") if s.strip()]

    @property
    def qa_report_assignee_list(self) -> list[str]:
        """QA-report allow-list for the weekly deck. Empty = everyone (minus bots)."""
        return [a.strip() for a in self.qa_report_assignees.split(",") if a.strip()]

    @property
    def qa_report_ask_list(self) -> list[dict]:
        """Operator-provided leadership asks (parsed from the JSON in qa_report_asks)."""
        import json
        try:
            data = json.loads(self.qa_report_asks or "[]")
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def pr_env_sync_title_list(self) -> list[str]:
        """Lower-cased title fragments that identify an environment-promotion PR."""
        return [t.strip().lower() for t in self.pr_env_sync_titles.split(",") if t.strip()]

    @property
    def jira_configured(self) -> bool:
        """True only when we have enough to actually call Jira."""
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)


# Cached Settings + the .env mtime it was built from. We re-read .env automatically
# when the file changes, so editing .env (e.g. rotating JIRA_API_TOKEN) takes effect
# on the next request WITHOUT a server restart. Previously this used @lru_cache, which
# froze the token at first use and made a rotated key look "still invalid" until restart.
_cache: dict = {"settings": None, "mtime": None}


def _env_mtime() -> float | None:
    try:
        return os.stat(_ENV_FILE).st_mtime
    except OSError:
        return None  # no .env file (pure-env deployment) — nothing to watch


def get_settings() -> Settings:
    """Return current settings, rebuilding them if .env changed since last read."""
    mtime = _env_mtime()
    if _cache["settings"] is None or _cache["mtime"] != mtime:
        _cache["settings"] = Settings()
        _cache["mtime"] = mtime
    return _cache["settings"]


def reload_settings() -> Settings:
    """Force an immediate re-read of .env (used by POST /api/config/reload)."""
    _cache["settings"] = Settings()
    _cache["mtime"] = _env_mtime()
    return _cache["settings"]


# ---- Per-board config (multi-board) ----------------------------------------------------
#
# A ProjectConfig merges the shared `Settings` (secrets/LLM/CORS from .env) with ONE board's
# block from projects.yaml, and re-exposes the exact property surface `Settings` had before
# multi-board — so sync/report code just takes a `cfg` in place of `get_settings()`. Any
# per-board value the YAML omits falls back to the matching `Settings` default; a value set
# to "" in the YAML is honored as an explicit empty (e.g. no roster). `jira_project` returns
# the board key, and the Jira-connection fields pass straight through to JiraClient.
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class ProjectConfig:
    settings: Settings
    key: str
    name: str
    db_file: str
    overrides: dict = field(default_factory=dict)

    def _ov(self, name: str, default):
        """Board override for `name`, or the shared-Settings default when omitted (None).

        An explicit "" (or any set value) in the YAML is returned as-is."""
        val = self.overrides.get(name)
        return default if val is None else val

    def _csv(self, name: str, default: str) -> list[str]:
        raw = self._ov(name, default)
        return [a.strip() for a in str(raw or "").split(",") if a.strip()]

    # ---- board identity ----
    @property
    def jira_project(self) -> str:
        return self.key

    # ---- scalar per-board settings ----
    @property
    def current_sprint_only(self) -> bool:
        return bool(self._ov("current_sprint_only", self.settings.current_sprint_only))

    @property
    def report_timezone(self) -> str:
        return self._ov("report_timezone", self.settings.report_timezone)

    @property
    def snapshot_exclude_done(self) -> bool:
        return bool(self._ov("snapshot_exclude_done", self.settings.snapshot_exclude_done))

    @property
    def sprint_anchor_date(self) -> str:
        return str(self._ov("sprint_anchor_date", self.settings.sprint_anchor_date))

    @property
    def sprint_anchor_number(self) -> int:
        return int(self._ov("sprint_anchor_number", self.settings.sprint_anchor_number))

    @property
    def sprint_length_days(self) -> int:
        return int(self._ov("sprint_length_days", self.settings.sprint_length_days))

    @property
    def qa_passed_label(self) -> str:
        return self._ov("qa_passed_label", self.settings.qa_passed_label)

    @property
    def qa_failed_label(self) -> str:
        return self._ov("qa_failed_label", self.settings.qa_failed_label)

    @property
    def dev_target_default(self) -> int:
        return int(self._ov("dev_target_default", self.settings.dev_target_default))

    # ---- sprint calendar ----
    # Sprints are fixed-length and anchored (see Settings.sprint_anchor_date), so a number
    # and a date convert into each other with arithmetic alone — no board lookup needed.

    def sprint_window(self, number: int) -> tuple[date, date]:
        """First and last day of sprint `number` on this board's calendar."""
        anchor = date.fromisoformat(self.sprint_anchor_date)
        offset = (number - self.sprint_anchor_number) * self.sprint_length_days
        start = anchor + timedelta(days=offset)
        return start, start + timedelta(days=self.sprint_length_days - 1)

    def sprint_for(self, day: date) -> tuple[int, date, date]:
        """Sprint number + its start/end range for the sprint containing `day`."""
        anchor = date.fromisoformat(self.sprint_anchor_date)
        index = (day - anchor).days // self.sprint_length_days  # floor → right for past days
        number = self.sprint_anchor_number + index
        return (number, *self.sprint_window(number))

    # ---- CSV list per-board settings (mirror Settings' list properties) ----
    @property
    def excluded_assignees(self) -> list[str]:
        return self._csv("exclude_assignees", self.settings.exclude_assignees)

    @property
    def monitored_assignees(self) -> list[str]:
        return self._csv("monitor_assignees", self.settings.monitor_assignees)

    @property
    def report_assignee_list(self) -> list[str]:
        return self._csv("report_assignees", self.settings.report_assignees)

    @property
    def done_statuses(self) -> list[str]:
        return self._csv("report_done_statuses", self.settings.report_done_statuses)

    @property
    def shipped_statuses(self) -> list[str]:
        return self._csv("report_shipped_statuses", self.settings.report_shipped_statuses)

    @property
    def excluded_movers(self) -> list[str]:
        return self._csv("report_exclude_movers", self.settings.report_exclude_movers)

    @property
    def qa_report_assignee_list(self) -> list[str]:
        return self._csv("qa_report_assignees", self.settings.qa_report_assignees)

    @property
    def github_repo_list(self) -> list[str]:
        """GitHub repos this board owns — the repo → board map for the merged-PR store."""
        return self._csv("github_repos", self.settings.github_repos)

    @property
    def qa_report_ask_list(self) -> list[dict]:
        import json
        raw = self._ov("qa_report_asks", self.settings.qa_report_asks)
        try:
            data = json.loads(raw or "[]") if isinstance(raw, str) else raw
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    # ---- shared passthrough (from .env; identical for every board) ----
    @property
    def jira_base_url(self) -> str:
        return self.settings.jira_base_url

    @property
    def jira_email(self) -> str:
        return self.settings.jira_email

    @property
    def jira_api_token(self) -> str:
        return self.settings.jira_api_token

    @property
    def jira_configured(self) -> bool:
        return self.settings.jira_configured

    @property
    def anthropic_api_key(self) -> str:
        return self.settings.anthropic_api_key

    @property
    def report_llm_model(self) -> str:
        return self.settings.report_llm_model

    @property
    def capacity_workbook_path(self) -> str:
        return self.settings.capacity_workbook_path
