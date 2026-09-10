#!/usr/bin/env python3
"""The one Jira REST API entry point for this repo's skills — no MCP, no duplication.

Consolidates what used to be four near-identical copies of `create_ticket.py` (one each
under nexus-api / nexus-frontend / sethi-backend / sethi-frontend-jira-tickets). Those
copies differed only in PROJECT_KEY, a default epic name, and docstrings — and they had
already drifted: the `epic_summary` disambiguation field existed in the two sethi copies
and was missing from the two nexus ones. Board identity is now a `--project` argument, so
there is one implementation to fix.

Subcommands — the caller picks the API call it needs:

  create-stories  POST /rest/api/3/issue      create Story tickets under a resolved epic
  find-epic       POST /rest/api/3/search/jql resolve an epic by name, ALL matches shown
  get-issue       GET  /rest/api/3/issue/KEY  fetch one issue back in confirmation shape

Credentials come from jira_tracker_backend/.env (JIRA_BASE_URL / JIRA_EMAIL /
JIRA_API_TOKEN) — the same token and the same Jira site (team-anervea.atlassian.net) that
hosts both the NEX and STH boards.

Stdlib only, on purpose: these run under a bare `python3` with no virtualenv. The app's
own app/jira_client.py is a separate, httpx-based READ client for product code — do not
merge the two (see this skill's SKILL.md, "Why this is not app/jira_client.py").
"""
import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# rhidzkhan ahmad — the ticket skills all assign here (resolved once via
# /rest/api/3/user/search and pinned; re-resolve if the account is ever recreated).
DEFAULT_ASSIGNEE_ACCOUNT_ID = "712020:525b78f1-26da-462d-b8cd-91b3598ad495"

# Deliberately well above any plausible number of same-named epics. The old copies used 5,
# which cannot distinguish "5 matches" from "5 of 40" — and silently taking issues[0] of a
# truncated page is exactly how a ticket lands under the wrong epic.
EPIC_SEARCH_MAX_RESULTS = 50

RETRYABLE_STATUS = (429, 500, 502, 503, 504)
RETRY_ATTEMPTS = 3


class JiraApiError(Exception):
    """Any unrecoverable step. Never partially create a ticket silently."""


class AmbiguousEpicError(JiraApiError):
    """More than one epic matched the name — refuse rather than guess which was meant."""


def _default_env_file() -> Path:
    # scripts/ -> jira-scripts/ -> skills/ -> .claude/ -> jira_tracker_backend/
    return Path(__file__).resolve().parents[4] / ".env"


def load_env(path: Path) -> dict:
    """Parse the .env at `path`, requiring the three JIRA_* credentials to be present."""
    if not path.is_file():
        raise JiraApiError(f"No .env at {path}")
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    for required in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        if not env.get(required):
            raise JiraApiError(f"{required} missing/empty in {path}")
    return env


class Jira:
    """Thin authenticated transport — one place for auth, retries, and error shape."""

    def __init__(self, env: dict):
        self.base_url = env["JIRA_BASE_URL"].rstrip("/")
        self.auth = base64.b64encode(
            f"{env['JIRA_EMAIL']}:{env['JIRA_API_TOKEN']}".encode()
        ).decode()

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET `path`, returning the decoded JSON body."""
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict) -> dict:
        """POST `body` to `path`, returning the decoded JSON body."""
        return self.request("POST", path, body=body)

    def request(self, method: str, path: str,
                params: dict | None = None, body: dict | None = None) -> dict:
        """Issue one authenticated request, retrying 429/5xx up to RETRY_ATTEMPTS times."""
        url = f"{self.base_url}{path}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Basic {self.auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        last_exc: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                with urllib.request.urlopen(req) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                if exc.code in RETRYABLE_STATUS and attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                detail = exc.read().decode(errors="replace")[:500]
                raise JiraApiError(f"Jira {method} {path} -> {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise JiraApiError(f"Jira {method} {path} failed after retries: {last_exc}")


# ---- epic resolution -----------------------------------------------------------------
# `summary ~` is a fuzzy, case-insensitive substring match. On the STH board that means
# "frontend" hits four separate epics and "Dynamic Roles & Permissions" hits two. The old
# copies returned issues[0] with no signal that anything else matched, which is how a
# ticket gets parented to FRONTEND-INTEGRATION when FRONTEND was asked for. Here every
# match is returned and >1 is a hard error the caller must resolve with --epic-key.


def find_epics(jira: Jira, project: str, name: str) -> list[dict]:
    """Return EVERY epic in `project` whose summary fuzzy-matches `name`, newest first."""
    escaped = name.replace('"', '\\"')
    data = jira.post("/rest/api/3/search/jql", {
        "jql": f'project = {project} AND issuetype = Epic AND summary ~ "{escaped}"',
        "fields": ["summary", "status"],
        "maxResults": EPIC_SEARCH_MAX_RESULTS,
    })
    return [
        {
            "key": issue["key"],
            "summary": issue["fields"]["summary"],
            "status": (issue["fields"].get("status") or {}).get("name"),
        }
        for issue in data.get("issues", [])
    ]


def get_epic_by_key(jira: Jira, project: str, key: str) -> dict:
    """Fetch `key` and confirm it really is an Epic on `project` before parenting to it."""
    data = jira.get(f"/rest/api/3/issue/{key}",
                    params={"fields": "summary,status,issuetype,project"})
    fields = data["fields"]
    issue_type = (fields.get("issuetype") or {}).get("name")
    if issue_type != "Epic":
        raise JiraApiError(f"{key} is a {issue_type!r}, not an Epic — refusing to parent to it.")
    actual_project = (fields.get("project") or {}).get("key")
    if actual_project != project:
        raise JiraApiError(f"{key} belongs to project {actual_project}, not {project}.")
    return {
        "key": data["key"],
        "summary": fields["summary"],
        "status": (fields.get("status") or {}).get("name"),
    }


def resolve_epic(jira: Jira, project: str,
                 name: str | None, epic_key: str | None) -> dict:
    """An exact key wins outright; a name must match exactly one epic or this raises."""
    if epic_key:
        return get_epic_by_key(jira, project, epic_key)
    if not name:
        raise JiraApiError("Either --epic <name> or --epic-key <KEY> is required.")

    matches = find_epics(jira, project, name)
    if not matches:
        raise JiraApiError(
            f'No Epic matching "{name}" in project {project}. Never inventing an epic '
            "link — create the epic first, or fix the name."
        )
    if len(matches) > 1:
        listed = "\n".join(
            f'    {m["key"]}  {m["summary"]!r}  [{m["status"]}]' for m in matches
        )
        raise AmbiguousEpicError(
            f'"{name}" matched {len(matches)} epics in {project} — refusing to guess '
            f"which one you meant:\n{listed}\n"
            "    Re-run with --epic-key <KEY> to name the epic exactly."
        )
    return matches[0]


# ---- minimal markdown -> Atlassian Document Format (ADF) -----------------------------
# Supports exactly what the team's STORY template uses: headings (#/##/###), bullet
# lists (- item), task lists (- [ ] item), a horizontal rule (---), and inline **bold** /
# `code` spans. Not a general markdown parser — deliberately scoped to this input shape.

_INLINE_RE = re.compile(r"\*\*(.+?)\*\*|`(.+?)`")


def _inline_nodes(text: str) -> list:
    """Split `text` into ADF text nodes, marking **bold** and `code` spans."""
    nodes = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            nodes.append({"type": "text", "text": text[pos:m.start()]})
        if m.group(1) is not None:
            nodes.append({"type": "text", "text": m.group(1), "marks": [{"type": "strong"}]})
        else:
            nodes.append({"type": "text", "text": m.group(2), "marks": [{"type": "code"}]})
        pos = m.end()
    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})
    return nodes or [{"type": "text", "text": text}]


def _list_item(line: str, checkbox: bool) -> dict:
    """Build one taskItem (checkbox) or listItem (bullet) node from `line`."""
    if checkbox:
        checked = line[:6].lower() == "- [x] "
        text = line[6:] if len(line) > 6 else ""
        return {
            "type": "taskItem",
            "attrs": {"localId": f"t{abs(hash(line)) % 100000}",
                      "state": "DONE" if checked else "TODO"},
            "content": _inline_nodes(text),
        }
    return {"type": "listItem",
            "content": [{"type": "paragraph", "content": _inline_nodes(line[2:])}]}


def _is_checkbox(line: str) -> bool:
    """True when `line` opens a task-list item (`- [ ] ` / `- [x] `)."""
    return line.startswith("- [ ] ") or line.startswith("- [x] ")


def _heading_block(hashes: str, text: str) -> dict:
    """Build an ADF heading node whose level is the count of leading `#`."""
    return {"type": "heading", "attrs": {"level": len(hashes)},
            "content": _inline_nodes(text)}


def _gather_list(lines: list[str], start: int) -> tuple[dict, int]:
    """Consume one run of same-kind list items from `start`.

    Returns the list node and the index of the first line that is not part of it. A
    checkbox run and a bullet run are different kinds, so one ends where the other begins.
    """
    checkbox = _is_checkbox(lines[start])
    items = []
    i = start
    while i < len(lines):
        cur = lines[i]
        if not cur.startswith("- ") or _is_checkbox(cur) != checkbox:
            break
        items.append(_list_item(cur, checkbox=checkbox))
        i += 1
    node = {"type": "taskList" if checkbox else "bulletList", "content": items}
    if checkbox:
        node["attrs"] = {"localId": f"l{abs(hash(str(items))) % 100000}"}
    return node, i


def _gather_paragraph(lines: list[str], start: int) -> tuple[dict, int]:
    """Consume contiguous plain lines from `start` into ONE paragraph joined by hardBreaks.

    A ticket's header block is four stacked "**Label:** value" lines, not one run-on
    sentence, so every source line keeps its own visual line.
    """
    i = start + 1
    while i < len(lines) and lines[i].strip() and lines[i].strip() != "---" \
            and not re.match(r"^#{1,6}\s", lines[i]) \
            and not lines[i].startswith("- "):
        i += 1
    content = []
    for offset, para_line in enumerate(lines[start:i]):
        if offset:
            content.append({"type": "hardBreak"})
        content.extend(_inline_nodes(para_line))
    return {"type": "paragraph", "content": content}, i


def text_to_adf(text: str) -> dict:
    """Convert the team's STORY-ID markdown into an Atlassian Document Format doc."""
    blocks: list = []
    lines = [ln.rstrip() for ln in text.strip("\n").split("\n")]
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not line.strip():
            i += 1
        elif line.strip() == "---":
            blocks.append({"type": "rule"})
            i += 1
        elif heading:
            blocks.append(_heading_block(heading.group(1), heading.group(2)))
            i += 1
        elif line.startswith("- "):
            node, i = _gather_list(lines, i)
            blocks.append(node)
        else:
            node, i = _gather_paragraph(lines, i)
            blocks.append(node)
    return {"type": "doc", "version": 1, "content": blocks}


# ---- issue operations ----------------------------------------------------------------


@dataclass(frozen=True)
class StoryTarget:
    """Where a batch of stories is filed — fixed once per run, identical for every story."""
    project: str
    epic_key: str
    assignee: str


def create_story(jira: Jira, target: StoryTarget, summary: str, description_adf: dict) -> str:
    """Create one Story under `target` and return its new issue key."""
    data = jira.post("/rest/api/3/issue", {
        "fields": {
            "project": {"key": target.project},
            "issuetype": {"name": "Story"},
            "summary": summary,
            "description": description_adf,
            "assignee": {"accountId": target.assignee},
            "parent": {"key": target.epic_key},
            # No `customfield_10020` (Sprint) set on purpose — an unsprinted issue is
            # exactly what shows up in the board's Backlog view.
        }
    })
    return data["key"]


def fetch_issue(jira: Jira, key: str) -> dict:
    """Read one issue back in the shape the skills report to the operator."""
    data = jira.get(f"/rest/api/3/issue/{key}",
                    params={"fields": "summary,status,assignee,parent"})
    fields = data["fields"]
    return {
        "key": data["key"],
        "url": f"{jira.base_url}/browse/{data['key']}",
        "summary": fields["summary"],
        "status": fields["status"]["name"],
        "assignee": (fields.get("assignee") or {}).get("displayName"),
        "epic": (fields.get("parent") or {}).get("key"),
    }


def load_stories(path: Path) -> list[dict]:
    """Read and validate the stories JSON: a non-empty list of {summary, body}."""
    stories = json.loads(path.read_text())
    if not isinstance(stories, list) or not stories:
        raise JiraApiError(f"{path} must hold a non-empty JSON list of stories.")
    for idx, story in enumerate(stories):
        missing = [k for k in ("summary", "body") if not story.get(k)]
        if missing:
            raise JiraApiError(f"story[{idx}] missing required key(s): {', '.join(missing)}")
    return stories


# ---- subcommands ---------------------------------------------------------------------


def cmd_create_stories(jira: Jira, args) -> list:
    """Resolve the epic once, then create (or preview) every story in the batch."""
    stories = load_stories(args.stories)
    epic = resolve_epic(jira, args.project, args.epic, args.epic_key)
    target = StoryTarget(project=args.project, epic_key=epic["key"],
                         assignee=args.assignee)

    results = []
    for story in stories:
        adf = text_to_adf(story["body"])
        if args.dry_run:
            results.append({
                "summary": story["summary"],
                "epic": epic["key"],
                # Surface WHICH epic the name actually resolved to. The whole point of the
                # dry run is catching a wrong-epic resolution before it is unfixable.
                "epic_summary": epic["summary"],
                "epic_status": epic["status"],
                "adf_preview": adf,
            })
            continue
        results.append(fetch_issue(jira, create_story(jira, target, story["summary"], adf)))
    return results


def cmd_find_epic(jira: Jira, args) -> list:
    """List every epic matching a name, so the caller can pick one deliberately."""
    return find_epics(jira, args.project, args.name)


def cmd_get_issue(jira: Jira, args) -> list:
    """Fetch one or more issues back by key."""
    return [fetch_issue(jira, key) for key in args.keys]


def build_parser() -> argparse.ArgumentParser:
    """Wire up the subcommands; each sets `func` to its cmd_* handler."""
    parser = argparse.ArgumentParser(
        description="Jira REST API entry point for this repo's ticket skills.")
    parser.add_argument("--env-file", type=Path, default=None,
                        help="Override the .env location (default: jira_tracker_backend/.env)")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-stories",
                            help="Create Story tickets under a resolved epic.")
    create.add_argument("--project", required=True,
                        help="Board key the tickets are created on, e.g. STH or NEX.")
    create.add_argument("--stories", required=True, type=Path,
                        help='JSON file: [{"summary": "...", "body": "..."}, ...]')
    create.add_argument("--epic", default=None,
                        help="Epic NAME to resolve. Must match exactly one epic, or the "
                             "run aborts listing every match — pass --epic-key instead.")
    create.add_argument("--epic-key", default=None,
                        help="Epic KEY (e.g. STH-600). Exact, unambiguous, and the way to "
                             "settle a name that matches more than one epic.")
    create.add_argument("--assignee", default=DEFAULT_ASSIGNEE_ACCOUNT_ID,
                        help="Assignee accountId (default: the pinned team account).")
    create.add_argument("--dry-run", action="store_true",
                        help="Resolve the epic and render ADF without creating anything.")
    create.set_defaults(func=cmd_create_stories)

    epic = sub.add_parser("find-epic",
                          help="List EVERY epic whose summary fuzzy-matches a name.")
    epic.add_argument("--project", required=True)
    epic.add_argument("--name", required=True)
    epic.set_defaults(func=cmd_find_epic)

    issue = sub.add_parser("get-issue", help="Fetch issues back in confirmation shape.")
    issue.add_argument("keys", nargs="+", help="One or more issue keys, e.g. STH-601.")
    issue.set_defaults(func=cmd_get_issue)

    return parser


def main() -> int:
    """Parse args, authenticate, run the chosen subcommand, print its JSON result."""
    args = build_parser().parse_args()
    env = load_env(args.env_file or _default_env_file())
    jira = Jira(env)
    print(json.dumps(args.func(jira, args), indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JiraApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
