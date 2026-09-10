// Tiny fetch wrapper around the FastAPI backend.
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

// ---- Active board (per TAB) ----------------------------------------------------------
// The selected board lives in the tab's URL (?project=NEX), NOT localStorage — localStorage
// is shared across tabs, so it couldn't hold a different board per tab. Reading from the URL
// makes each tab independent, survive reload, and be bookmarkable. A localStorage "last used"
// value only seeds a brand-new tab that opened without ?project=.
const LAST_USED_KEY = "jiraTracker.lastProject";

export function getProject() {
  const fromUrl = new URLSearchParams(window.location.search).get("project");
  if (fromUrl) return fromUrl;
  try {
    return localStorage.getItem(LAST_USED_KEY) || "";
  } catch {
    return "";
  }
}

export function setProject(key) {
  const url = new URL(window.location.href);
  url.searchParams.set("project", key);
  window.history.replaceState({}, "", url); // update this tab's URL, no reload
  try {
    localStorage.setItem(LAST_USED_KEY, key); // seed for future brand-new tabs
  } catch {}
}

// Board-scoped path prefix, e.g. "/api/NEX".
function P() {
  return `/api/${encodeURIComponent(getProject())}`;
}

function qs(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.append(k, v);
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function get(path, params = {}) {
  const res = await fetch(`${BASE}${path}${qs(params)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post(path) {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function put(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  // Global: the configured boards for the switcher (not board-scoped).
  listProjects: () => get("/api/projects"),

  // target = day to snapshot (defaults to today); force = overwrite a past day
  takeSnapshot: (target, force) => post(`${P()}/snapshot${qs({ target, force })}`),
  // Sync + snapshot EVERY board (parallel on the backend). Returns { projects: [...] }.
  snapshotAll: (target, force) => post(`/api/snapshot-all${qs({ target, force })}`),
  // Global: health of the nightly sync cron for EVERY board (not board-scoped — the job
  // syncs all boards in one run, so its health is only meaningful across all of them).
  syncHealth: (days) => get("/api/sync-health", { days }),
  snapshotDates: () => get(`${P()}/snapshots`),
  board: (date, assignee) => get(`${P()}/snapshots/${date}`, { assignee }),
  // day-by-day count of a person's tickets sent to Code Review / QA Testing / Done
  assigneeMovement: (name, granularity = "day", by = "assignee") =>
    get(`${P()}/reports/assignee/${encodeURIComponent(name)}/movement`, { granularity, by }),
  // per-person time log: tickets they logged hours on (+ owned tickets w/ no log = n/a)
  assigneeWorklog: (name) =>
    get(`${P()}/reports/assignee/${encodeURIComponent(name)}/worklog`),
  // aggregated sprint deck report for the given day's board snapshot
  sprintReport: (date) => get(`${P()}/reports/sprint`, { date }),
  // two-board comparison (closing vs kickoff sprint) behind the 9-slide deck
  sprintCompare: (closing, kickoff, assignees) =>
    get(`${P()}/reports/sprint-compare`, { closing, kickoff, assignees }),
  // URL that downloads the comparison as a Markdown deck (no API key needed)
  sprintCompareMdUrl: (closing, kickoff, assignees) =>
    `${BASE}${P()}/reports/sprint-compare.md${qs({ closing, kickoff, assignees })}`,
  // URL that downloads the comparison as a .pptx (LLM-authored, python-pptx built)
  sprintComparePptxUrl: (closing, kickoff, assignees) =>
    `${BASE}${P()}/reports/sprint-compare.pptx${qs({ closing, kickoff, assignees })}`,
  // per-developer KPI scorecard for one sprint (omit `sprint` for the current one).
  // Target comes from the capacity grid below, so the two views never disagree.
  devKpi: (sprint, assignees) => get(`${P()}/reports/dev-kpi`, { sprint, assignees }),
  // the same scorecard over EVERY sprint the board has data for — one total row per
  // developer, each carrying the per-sprint rows it was summed from (`history`)
  devKpiOverall: (assignees) => get(`${P()}/reports/dev-kpi/overall`, { assignees }),
  // rolling per-developer capacity grid, seeded once from Rolling_Sprint_Capacity.xlsx
  // and stored per board from then on
  capacity: () => get(`${P()}/capacity`),
  // save one sprint's Actual for one developer (null clears it). The response is the WHOLE
  // grid — the rolling rule moves every later Capacity, not just the edited cell.
  setCapacityActual: (sprint_number, developer, value) =>
    put(`${P()}/capacity/actual`, { sprint_number, developer, value }),

  // weekly QA activity report (moved-forward / sent-back / blocked + per engineer)
  weeklyActivity: (week_start, assignees, asks) =>
    get(`${P()}/reports/weekly-activity`, { week_start, assignees, asks }),
  weeklyActivityMdUrl: (week_start, assignees, asks) =>
    `${BASE}${P()}/reports/weekly-activity.md${qs({ week_start, assignees, asks })}`,
  weeklyActivityPptxUrl: (week_start, assignees, asks) =>
    `${BASE}${P()}/reports/weekly-activity.pptx${qs({ week_start, assignees, asks })}`,
};
