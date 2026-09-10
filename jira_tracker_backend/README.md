# Jira Tracker API

A small local server that pulls issues from the Jira board **NEX / "Nexus Project"**
(`team-anervea.atlassian.net`) into a local SQLite database and serves them over HTTP,
ready for a React frontend to consume later.

- **Stack:** Python + FastAPI · SQLite · `httpx`
- **Sync:** manual (you trigger it) — no webhooks, no background polling
- **Architecture:** layered (API → service → integration → persistence → config)

```
Jira Cloud REST API ──pull──▶ FastAPI ──upsert──▶ SQLite (jira_tracker.db) ──serve──▶ React (later)
```

## 1. Setup

```bash
cd /Users/axeeeeee/Documents/work/jira_tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Get a Jira API token

1. Open https://id.atlassian.com/manage-profile/security/api-tokens
2. **Create API token**, label it (e.g. `local-tracker`), and copy the value (shown once).

> The token authenticates as **you**, so it can see every board your account can —
> but this app only queries the project set in `JIRA_PROJECT` (NEX).

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env` and set:

| Variable | Value |
|---|---|
| `JIRA_BASE_URL` | `https://team-anervea.atlassian.net` |
| `JIRA_EMAIL` | `rhidzkhan.ahmad@anervea.ai` |
| `JIRA_API_TOKEN` | *(the token from step 2)* |
| `JIRA_PROJECT` | `NEX` |

`.env` is gitignored — your token is never committed.

## 4. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive API docs (click-test everything): http://localhost:8000/docs

## 5. Test it (in order)

```bash
# a) server alive (no token needed)
curl localhost:8000/health

# b) token works — returns your Jira account
curl localhost:8000/api/jira/ping

# c) pull from Jira into SQLite
curl -X POST localhost:8000/api/sync

# d) read it back
curl "localhost:8000/api/issues?status=In%20Progress"
curl localhost:8000/api/issues/NEX-960
curl localhost:8000/api/meta
```

Re-running step (c) should report `updated`, not duplicate `created` — the sync is idempotent.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Liveness (no token). |
| GET  | `/api/jira/ping` | Verify the Jira token; returns your account. |
| POST | `/api/sync` | Pull from Jira and upsert. `?full=false` = only changes since last sync. |
| GET  | `/api/sync/history` | Recent sync runs (counts, errors). |
| GET  | `/api/issues` | List issues. Filters: `status`, `assignee`, `issue_type`, `label`, `q`, `limit`, `offset`. |
| GET  | `/api/issues/{key}` | One issue (e.g. `NEX-960`). |
| GET  | `/api/meta` | Distinct statuses / assignees / types / labels for filter dropdowns. |
| GET  | `/api/reports/scorecard` | Per-assignee movement metrics. Params: `granularity=day\|week`, `by=assignee\|mover`, `assignee`, `start`, `end`. |
| GET  | `/api/reports/column-flow` | Per-column entered/left/net per bucket. Params: `granularity`, `status`, `start`, `end`. |
| GET  | `/api/reports/assignee/{name}` | One person's scorecard time-series. Params: `days`, `granularity`, `by`. |
| GET  | `/api/reports/sprint` | One sprint's deck (from a day's snapshot). Param: `date`. |
| GET  | `/api/reports/sprint-compare` | **Two-board** closure/kickoff comparison (JSON). Params: `closing`, `kickoff`, `assignees?`. |
| GET  | `/api/reports/sprint-compare.md` | Same comparison as a **Markdown deck** (no API key). Params: `closing`, `kickoff`, `assignees?`. |

### Sprint closure/kickoff comparison

`/api/reports/sprint-compare*` compares two sprint boards (the **closing** sprint's last
snapshot vs the **kickoff** sprint's latest) and builds the 9-slide deck described in
[`COMPARISON.md`](COMPARISON.md): completed / carry-over / new-work headline, completed-by-project,
committed-by-type, team performance, and ticket breakdown. It counts only the report roster
(`REPORT_ASSIGNEES`). The `.md` output is the no-key path — paste it into another Claude context
to build the slides; the `.pptx` output has Claude author the narrative and renders it with
`python-pptx` (`REPORT_LLM_MODEL`, default `claude-opus-4-8`).

### Movement reports

The `issues` table is a *snapshot* (current status only). To track how tickets move between
columns over time, every sync also pulls each issue's **changelog** and records one row per status
change in `status_transitions` — capturing the from/to status, **who moved it** (`moved_by`), **who
owned it** at the time (`assignee_at`), and the local-tz day/week. The two `/api/reports/*` shapes
aggregate that table:

- **scorecard** — per person, per day/week: pulled from To Do, sent back by QA, → In Progress,
  → Blocked, → Deployment/Done.
- **column-flow** — per column, per day/week: how many tickets **entered**, **left**, and the **net**.

**Counting model (important):** metrics count **distinct tickets per bucket**, not raw transition
events — a ticket that bounces into a column 5× in one week counts once. No-op `X → X`
self-transitions (Jira automation re-firing) are never stored, and bot movers
(`REPORT_EXCLUDE_MOVERS`, default `Automation for Jira`) are excluded so numbers reflect human work.
A ticket reassigned mid-week is counted under each assignee that held it.

Run a `POST /api/sync?full=true` once to backfill transition history for existing issues (it fetches
a changelog per issue, so it's slower than a normal sync). The companion **`jira_tracker_frontend`**
React app visualizes both reports.

## Project layout

```
app/
  config.py       # settings & secrets from .env
  database.py     # SQLAlchemy engine + session (swap SQLite→Postgres here)
  models.py       # Issue, StatusTransition, SyncLog ORM models
  schemas.py      # Pydantic response models (the API contract)
  jira_client.py  # Jira REST client (pagination, auth, retry)
  sync.py         # sync orchestration: fetch → normalize → upsert → audit
  report_render.py # sprint-compare markdown report + weekly-QA python-pptx deck
  main.py         # FastAPI app + endpoints + CORS
```

## Frontend
The companion React app lives in the sibling **`jira_tracker_frontend`** directory (CORS is enabled
for `http://localhost:5173`). It renders the **Movement** dashboard — per-column difference and
per-assignee scorecard. Open `jira_tracker.code-workspace` to load both projects together.
