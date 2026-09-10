"""Integration layer — talks to the Jira Cloud REST API.

This is the only module that knows about Jira's wire format and HTTP. It does pure
I/O (no DB knowledge) and acts as an anti-corruption boundary: callers get plain
Python dicts/lists, never httpx objects.
"""
import time

import httpx

from app.config import Settings

# Fields we ask Jira for — explicit list avoids over-fetching every custom field.
DEFAULT_FIELDS = [
    "summary",
    "description",
    "issuetype",
    "status",
    "priority",
    "labels",
    "components",
    "assignee",
    "reporter",
    "created",
    "updated",
    "resolution",
    "parent",  # the Epic (or parent issue) — powers the team/epic grouping
    "worklog",  # time-log entries (inline; up to 20 — full set via get_worklog fallback)
]

# Enhanced JQL search endpoint (legacy /rest/api/3/search was removed in 2025).
_SEARCH_PATH = "/rest/api/3/search/jql"
_MYSELF_PATH = "/rest/api/3/myself"
# Per-issue changelog (the enhanced /search/jql does not return changelog inline).
_CHANGELOG_PATH = "/rest/api/3/issue/{key}/changelog"
# Per-issue worklog — only needed as a fallback when the inline `worklog` field is
# truncated (Jira caps the inline list at 20 entries per issue).
_WORKLOG_PATH = "/rest/api/3/issue/{key}/worklog"


class JiraError(Exception):
    """Raised on any non-2xx Jira response, with a human-readable message."""


class JiraClient:
    def __init__(self, settings: Settings):
        if not settings.jira_configured:
            raise JiraError(
                "Jira is not configured. Set JIRA_EMAIL and JIRA_API_TOKEN in .env."
            )
        self._base_url = settings.jira_base_url.rstrip("/")
        self._auth = (settings.jira_email, settings.jira_api_token)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            auth=self._auth,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def _request(self, client: httpx.Client, method: str, path: str, **kwargs):
        """Single request with a small retry/backoff on 429 / 5xx."""
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:  # network-level failure
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise JiraError(
                    f"Jira {method} {path} -> {resp.status_code}: {resp.text[:400]}"
                )
            return resp
        raise JiraError(f"Jira {method} {path} failed after retries: {last_exc}")

    def active_sprints(self, project: str) -> list[dict]:
        """Active (open) sprint(s) for the project's board(s) — what's on the board now.

        Returns sprint dicts with id/name/startDate/endDate. Empty list if the board
        has no sprints (e.g. a kanban board).
        """
        sprints: list[dict] = []
        with self._client() as client:
            boards = self._request(
                client, "GET", "/rest/agile/1.0/board",
                params={"projectKeyOrId": project},
            ).json().get("values", [])
            for b in boards:
                try:
                    resp = self._request(
                        client, "GET", f"/rest/agile/1.0/board/{b['id']}/sprint",
                        params={"state": "active"},
                    )
                    sprints.extend(resp.json().get("values", []))
                except JiraError:
                    continue  # board may not support sprints
        return sprints

    def myself(self) -> dict:
        """Return the authenticated account — used by /api/jira/ping to test the token."""
        with self._client() as client:
            resp = self._request(client, "GET", _MYSELF_PATH)
            return resp.json()

    def get_changelog(self, issue_key: str) -> list[dict]:
        """Return all changelog history entries for one issue, oldest first.

        Follows `startAt`/`maxResults`/`isLast` pagination. Each entry has an `id`,
        an `author`, a `created` timestamp, and an `items` list of field changes.
        """
        path = _CHANGELOG_PATH.format(key=issue_key)
        histories: list[dict] = []
        start_at = 0

        with self._client() as client:
            while True:
                resp = self._request(
                    client, "GET", path,
                    params={"startAt": start_at, "maxResults": 100},
                )
                data = resp.json()
                values = data.get("values", [])
                histories.extend(values)

                if data.get("isLast", True) or not values:
                    break
                start_at += len(values)
                if start_at >= data.get("total", start_at):
                    break

        return histories

    def get_worklog(self, issue_key: str) -> list[dict]:
        """Return all worklog entries for one issue (paginated).

        Used only when an issue's inline `worklog` field is truncated (> 20 entries).
        Each entry has an `id`, an `author`, `timeSpentSeconds`, and a `started` time.
        """
        path = _WORKLOG_PATH.format(key=issue_key)
        worklogs: list[dict] = []
        start_at = 0

        with self._client() as client:
            while True:
                resp = self._request(
                    client, "GET", path,
                    params={"startAt": start_at, "maxResults": 100},
                )
                data = resp.json()
                values = data.get("worklogs", [])
                worklogs.extend(values)

                if not values:
                    break
                start_at += len(values)
                if start_at >= data.get("total", start_at):
                    break

        return worklogs

    def search_issues(self, jql: str, fields: list[str] | None = None) -> list[dict]:
        """Return all issues matching `jql`, following nextPageToken pagination."""
        fields = fields or DEFAULT_FIELDS
        issues: list[dict] = []
        next_token: str | None = None

        with self._client() as client:
            while True:
                payload: dict = {
                    "jql": jql,
                    "fields": fields,
                    "maxResults": 100,
                }
                if next_token:
                    payload["nextPageToken"] = next_token

                resp = self._request(client, "POST", _SEARCH_PATH, json=payload)
                data = resp.json()

                issues.extend(data.get("issues", []))

                next_token = data.get("nextPageToken")
                if data.get("isLast", True) or not next_token:
                    break

        return issues
