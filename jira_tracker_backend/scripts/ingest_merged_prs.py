"""Ingest a weekly merged-PR collection into the PR store (data/prs.db).

This is the final step of the /git-list-merge-pr skill: the git-operator subagent collects PRs
with `gh` and writes them as JSON, then this script upserts that JSON — so every week's report
becomes queryable history instead of a scratchpad file that disappears with the session.

Usage (runs from anywhere — it chdirs to the backend root itself):

    python scripts/ingest_merged_prs.py --json <path> \
        [--window-start 2026-08-20T10:00:00Z] [--window-end 2026-08-30T15:59:59Z] \
        [--state MERGED] [--dry-run]

Expected JSON — the collector's own shape, i.e. `gh pr list --json` field names:

    {"window": {"start": "2026-08-20T10:00:00Z", "end": "2026-08-30T15:59:59Z"},
     "prs": [{"repo": "nexus_api", "number": 2835, "title": "NEX-2060 : ...",
              "author": {"login": "Alfa-Axe"}, "state": "MERGED",
              "createdAt": "2026-08-25T02:11:03Z", "mergedAt": "2026-08-26T07:42:19Z",
              "url": "https://github.com/Anervea-AI/nexus_api/pull/2835",
              "commitCount": 16,
              "commits": [{"sha": "abc1234def", "subject": "..."}]}]}

`--window-start`/`--window-end` are recorded on the run row for audit; they do NOT filter what
is stored. Every PR in the file is kept with its real `merged_at`, so the reporting window stays
a `BETWEEN` at query time (see app/pr_models.py:MergedPr). Idempotent: re-running a week updates
the rows it already has instead of doubling them.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# Config reads ".env", "projects.yaml" and "./data" relative to the working directory, so the
# script anchors itself to the backend root and works no matter where it is invoked from.
os.chdir(_ROOT)

from app.config import get_settings
from app.database import get_pr_engine
from app.pr_models import MergedPr, PrCommit, PrIngestRun
from app.projects import get_registry, resolve_cfg


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _jira_key_re() -> re.Pattern:
    """Regex matching any configured board's ticket key in a PR title (e.g. "STH-935").

    Built from the board registry rather than a hardcoded list, so adding a board to
    projects.yaml is all it takes for its keys to be recognized here.
    """
    keys = "|".join(re.escape(entry.key) for entry in get_registry())
    if not keys:
        return re.compile(r"(?!x)x")  # no boards configured — match nothing
    return re.compile(rf"\b({keys})-(\d+)\b", re.IGNORECASE)


def _parse_ts(raw: str | None) -> datetime | None:
    """A `gh` UTC timestamp ("2026-08-26T07:42:19Z") as a naive-UTC datetime.

    Naive UTC matches how the Jira tables store time (see models.Worklog.started), so the two
    stores compare without a timezone dance.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _repo_board_map() -> dict[str, str]:
    """repo name (lower-case) -> board key, from each board's `github_repos` in projects.yaml."""
    mapping: dict[str, str] = {}
    for entry in get_registry():
        cfg = resolve_cfg(entry.key)
        if cfg is None:
            continue
        for repo in cfg.github_repo_list:
            mapping[repo.strip().lower()] = entry.key
    return mapping


def _repo_name(raw: str | None) -> str:
    """Bare repo name from either "nexus_api" or "Anervea-AI/nexus_api"."""
    return str(raw or "").strip().split("/")[-1]


def _author_login(pr: dict) -> str | None:
    """GitHub login, tolerating both `gh`'s nested {"author":{"login":..}} and a flat string."""
    author = pr.get("author")
    if isinstance(author, dict):
        return author.get("login") or None
    return str(author).strip() or None


def _jira_key(title: str | None, pattern: re.Pattern) -> str | None:
    """The ticket key in a PR title, upper-cased ("sth-935" -> "STH-935"), or None."""
    match = pattern.search(title or "")
    if match is None:
        return None
    return f"{match.group(1).upper()}-{match.group(2)}"


def _is_env_sync(title: str | None, fragments: list[str]) -> bool:
    """True when the title marks an environment promotion rather than substantive work."""
    lowered = (title or "").lower()
    return any(fragment in lowered for fragment in fragments)


def _commit_rows(pr: dict) -> list[dict]:
    """The PR's commits as {"sha", "subject"} dicts, tolerating `gh`'s messageHeadline field."""
    rows = []
    for commit in pr.get("commits") or []:
        if not isinstance(commit, dict):
            continue
        sha = str(commit.get("sha") or commit.get("oid") or "").strip()
        if not sha:
            continue
        subject = commit.get("subject") or commit.get("messageHeadline") or ""
        rows.append({"sha": sha, "subject": str(subject).splitlines()[0] or None})
    return rows


def _upsert_pr(db, pr: dict, context: dict) -> str:
    """Insert or update one PR row. Returns "created" or "updated"."""
    repo = _repo_name(pr.get("repo"))
    number = int(pr["number"])
    title = pr.get("title")
    commits = _commit_rows(pr)

    row = db.query(MergedPr).filter_by(repo=repo, number=number).one_or_none()
    outcome = "updated"
    if row is None:
        row = MergedPr(repo=repo, number=number)
        db.add(row)
        outcome = "created"

    row.board = context["boards"].get(repo.lower())
    row.title = title
    row.author = _author_login(pr)
    row.state = str(pr.get("state") or "").upper() or None
    row.jira_key = _jira_key(title, context["key_re"])
    row.created_at = _parse_ts(pr.get("createdAt"))
    row.merged_at = _parse_ts(pr.get("mergedAt"))
    row.url = pr.get("url")
    row.is_env_sync = _is_env_sync(title, context["env_fragments"])
    # The collector reports a count even where it deliberately skips the commit list (env-sync
    # PRs, and any PR past GitHub's 100-commit listing cap), so trust it over len(commits).
    row.commit_count = int(pr.get("commitCount") or len(commits))
    return outcome


def _upsert_commits(db, pr: dict) -> int:
    """Insert the PR's not-yet-stored commits. Returns how many rows were added."""
    repo = _repo_name(pr.get("repo"))
    number = int(pr["number"])
    commits = _commit_rows(pr)
    if not commits:
        return 0

    known = {sha for (sha,) in
             db.query(PrCommit.sha).filter_by(repo=repo, pr_number=number).all()}
    added = 0
    for commit in commits:
        if commit["sha"] in known:
            continue
        db.add(PrCommit(repo=repo, pr_number=number,
                        sha=commit["sha"], subject=commit["subject"]))
        known.add(commit["sha"])
        added += 1
    return added


def _load_payload(path: str) -> tuple[list[dict], dict]:
    """The PR list and the window block from the collector's JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):  # a bare array of PRs is accepted too
        return data, {}
    return data.get("prs") or [], data.get("window") or {}


def _select(prs: list[dict], state: str | None) -> list[dict]:
    """PRs worth storing: those carrying a repo and number, narrowed to `state` when given."""
    wanted = (state or "").upper()
    kept = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("number") is None or not pr.get("repo"):
            continue
        if wanted and str(pr.get("state") or "").upper() != wanted:
            continue
        kept.append(pr)
    return kept


def _report_unmapped(prs: list[dict], boards: dict[str, str]) -> None:
    """Warn about repos with no board — a missing `github_repos:` entry, not a data error."""
    unmapped = sorted({_repo_name(pr.get("repo")) for pr in prs
                       if _repo_name(pr.get("repo")).lower() not in boards})
    if not unmapped:
        return
    print("WARNING unmapped repos (board=NULL) — add them to a board's github_repos: "
          f"{', '.join(unmapped)}", flush=True)


def _write_run(maker, window: dict, args, counts: dict, error: str | None) -> int | None:
    """Persist the audit row in its own transaction, so it survives a failed ingest."""
    db = maker()
    try:
        run = PrIngestRun(
            window_start=_parse_ts(args.window_start or window.get("start")),
            window_end=_parse_ts(args.window_end or window.get("end")),
            finished_at=_utcnow(),
            status="error" if error else "success",
            prs_seen=counts["seen"],
            prs_created=counts["created"],
            prs_updated=counts["updated"],
            commits_created=counts["commits"],
            error=error,
        )
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _ingest(db, selected: list[dict], context: dict, counts: dict) -> None:
    """Upsert every selected PR and its commits, accumulating counts in place."""
    for pr in selected:
        if _upsert_pr(db, pr, context) == "created":
            counts["created"] += 1
        else:
            counts["updated"] += 1
        counts["commits"] += _upsert_commits(db, pr)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest collected PRs into data/prs.db.")
    parser.add_argument("--json", required=True, dest="json_path",
                        help="Collector JSON file (see this script's module docstring).")
    parser.add_argument("--window-start", help="Reporting window start, ISO-8601 UTC (audit only).")
    parser.add_argument("--window-end", help="Reporting window end, ISO-8601 UTC (audit only).")
    parser.add_argument("--state", default="MERGED",
                        help='Only store PRs in this state. Pass "" to store every state.')
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change, then roll back.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    prs, window = _load_payload(args.json_path)
    selected = _select(prs, args.state)
    boards = _repo_board_map()
    _report_unmapped(selected, boards)

    context = {
        "boards": boards,
        "key_re": _jira_key_re(),
        "env_fragments": get_settings().pr_env_sync_title_list,
    }
    counts = {"seen": len(selected), "created": 0, "updated": 0, "commits": 0}

    _, maker = get_pr_engine()
    db = maker()
    try:
        _ingest(db, selected, context, counts)
    except Exception as exc:
        db.rollback()
        db.close()
        error = f"{type(exc).__name__}: {exc}"
        run_id = _write_run(maker, window, args, counts, error)
        print(f"ERROR {error} (run_id={run_id})", file=sys.stderr, flush=True)
        return 1

    summary = (f"{counts['seen']}/{len(prs)} PRs (+{counts['created']} new, "
               f"~{counts['updated']} updated, {counts['commits']} commits)")
    if args.dry_run:
        db.rollback()
        db.close()
        print(f"DRY-RUN would store {summary} — nothing written", flush=True)
        return 0

    db.commit()
    db.close()
    run_id = _write_run(maker, window, args, counts, None)
    print(f"OK stored {summary} -> data/{get_settings().pr_db_file} run_id={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
