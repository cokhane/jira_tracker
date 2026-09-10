"""ORM models for the merged-PR store — its own Base, its own SQLite file.

Deliberately NOT on `app/models.py`'s Base. Jira data is board-scoped (one DB per board, so
boards can never be confused), but a pull request belongs to a GitHub *repo* and every weekly
report spans all four repos at once — splitting PRs per board would turn each report into two
connections and a merge in Python. Sharing the Jira Base would also make `create_all()` build
empty `merged_prs` tables inside every board DB, and every Jira table inside prs.db.

The board a PR belongs to is still recorded (`MergedPr.board`), resolved from the repo via each
board's `github_repos` list in projects.yaml — so PR rows still join back to the Jira tables.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrBase(DeclarativeBase):
    pass


class MergedPr(PrBase):
    """One row per pull request, keyed by (repo, number) so re-ingesting a week is idempotent.

    Rows are **not** window-filtered. Whatever the collector hands over is stored with its real
    `merged_at`, and the reporting window becomes a plain `BETWEEN` at query time. That keeps
    "created-or-updated-or-merged in the window" vs "merged in the window" a reporting decision
    instead of baking one of them irreversibly into the data — the distinction that made 20 of
    120 PRs in the 2026-08-20→30 report belong to the previous week.
    """

    __tablename__ = "merged_prs"
    __table_args__ = (UniqueConstraint("repo", "number", name="uq_merged_pr_repo_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo: Mapped[str] = mapped_column(String, index=True)
    number: Mapped[int] = mapped_column(Integer)

    board: Mapped[str | None] = mapped_column(String, index=True)  # NEX / STH, from the repo
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String, index=True)  # GitHub login
    state: Mapped[str | None] = mapped_column(String, index=True)   # MERGED | OPEN | CLOSED

    # Ticket key parsed out of the title (e.g. STH-935). This is the real join to the Jira
    # tables — stronger than matching a GitHub login against a Jira display name.
    jira_key: Mapped[str | None] = mapped_column(String, index=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime)      # naive UTC
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # naive UTC

    commit_count: Mapped[int] = mapped_column(Integer, default=0)

    # Environment-promotion PR (Develop→staging, Staging→uat, Uat→main). Its commits are
    # already counted under the feature PRs they came from, so reports exclude these from
    # substantive totals — 32 of the 100 PRs in the 2026-08-20→30 window were env-sync.
    is_env_sync: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    url: Mapped[str | None] = mapped_column(String)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PrCommit(PrBase):
    """One row per commit in a PR.

    (repo, pr_number, sha) is unique, so re-ingesting a week adds nothing. Env-sync PRs carry
    a `commit_count` but no commit rows — their commits already belong to the feature PRs, and
    the GitHub API caps a PR commit listing at 100 anyway.
    """

    __tablename__ = "pr_commits"
    __table_args__ = (UniqueConstraint("repo", "pr_number", "sha", name="uq_pr_commit_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo: Mapped[str] = mapped_column(String, index=True)
    pr_number: Mapped[int] = mapped_column(Integer, index=True)
    sha: Mapped[str] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(Text)


class PrIngestRun(PrBase):
    """Audit row per ingest run — mirrors `models.SyncLog`, so a bad week stays traceable.

    `window_start`/`window_end` record the reporting window the collection was driven from,
    which is what makes a stored PR's membership in a given week's report reconstructable.
    """

    __tablename__ = "pr_ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    window_start: Mapped[datetime | None] = mapped_column(DateTime)  # naive UTC
    window_end: Mapped[datetime | None] = mapped_column(DateTime)    # naive UTC

    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, default="running")  # running|success|error

    prs_seen: Mapped[int] = mapped_column(Integer, default=0)
    prs_created: Mapped[int] = mapped_column(Integer, default=0)
    prs_updated: Mapped[int] = mapped_column(Integer, default=0)
    commits_created: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
