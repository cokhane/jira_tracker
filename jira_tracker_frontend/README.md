# Jira Tracker — Movement Frontend

A small Vite + React dashboard for the `jira_tracker` FastAPI backend. Two views:

- **Per-column difference** — for each board column, how many tickets **entered**, **left**,
  and the **net** change, per day or week (chart + table). Backed by `/api/reports/column-flow`.
- **Per-assignee scorecard** — the 5 movement metrics (from To Do, QA sent-back, → In Progress,
  → Blocked, → Deploy/Done) per person. Backed by `/api/reports/scorecard`.

Shared controls: day/week toggle, date range, assignee/mover attribution, column & person filters.

### Sprint reports

The header report controls generate deck-styled sprint reports:

- **📄 Generate report** — single-sprint deck for the chosen sprint's closing snapshot.
- **Closing / Kickoff selectors** — pick two sprints (defaults to previous vs current), then:
  - **📄 HTML deck** — the 9-slide closure/kickoff deck in a new tab (print → Save as PDF).
  - **📝 Markdown** — downloads the same 9-slide deck as Markdown (no API key); paste it into
    another Claude context or a slides skill to build a `.pptx`.

Both compare outputs count only the report roster configured on the backend (`REPORT_ASSIGNEES`).
See `../jira_tracker/COMPARISON.md` for the comparison logic and slide structure.

## Run

```bash
npm install
npm run dev          # http://localhost:5173
```

The backend must be running on the URL in `.env` (`VITE_API_BASE`, default `http://localhost:8000`):

```bash
cd ../jira_tracker
uvicorn app.main:app --reload
```

Make sure a sync has populated the transition history first: `POST /api/sync?full=true`.
