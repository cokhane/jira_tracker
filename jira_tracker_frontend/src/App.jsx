import { useEffect, useMemo, useState } from "react";
import { api, getProject, setProject as persistProject } from "./api";
import Board from "./components/Board.jsx";
import AssigneeStats from "./components/AssigneeStats.jsx";
import CapacityTracker from "./components/CapacityTracker.jsx";
import DevKpi from "./components/DevKpi.jsx";
import SyncHealth from "./components/SyncHealth.jsx";
import { openReport, openCompareReport } from "./report.js";
import { STATUS, STATUS_ORDER, bg, colorMap } from "./lib.js";

// Left side-panel routes. Only the label + icon differ; each sets the active `view`.
const NAV = [
  { key: "board", label: "Velocity Board", icon: "▦" },
  { key: "kpi", label: "KPI Tracker", icon: "★" },
  { key: "capacity", label: "Capacity Tracker", icon: "◫" },
  { key: "report", label: "Sprint Report", icon: "▤" },
  { key: "movement", label: "Movement", icon: "⇄" },
  { key: "timelog", label: "Time Log", icon: "◷" },
  { key: "synchealth", label: "Sync Health", icon: "⟳" },
];
const TITLES = {
  board: "Sprint Velocity Tracker",
  kpi: "Developer KPI Tracker",
  capacity: "Capacity Tracker",
  report: "Sprint Report",
  movement: "Developer Movement",
  timelog: "Time Log",
  synchealth: "Sync Health",
};
// Routes that are read PER SPRINT, so the sprint tabs stay on screen to switch between them.
const SPRINT_VIEWS = ["board", "kpi"];

const fmtDate = (d) =>
  new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const weekday = (d) =>
  new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short" });

export default function App() {
  // Active board is per-tab (URL ?project=…). See api.js getProject/setProject.
  const [projects, setProjects] = useState([]);
  const [project, setProjectState] = useState(getProject());

  const [dates, setDates] = useState([]);
  const [date, setDate] = useState("");
  const [sprintKey, setSprintKey] = useState(null);  // selected sprint name
  const [board, setBoard] = useState(null);
  // KPI view mode. Lives here, not in DevKpi, because it decides whether the sprint tabs
  // below still mean anything — the chrome is this component's to own.
  const [kpiOverall, setKpiOverall] = useState(false);

  const [epic, setEpic] = useState(null);     // active epic filter
  const [status, setStatus] = useState(null); // active status filter
  const [hideDone, setHideDone] = useState(false);
  const [q, setQ] = useState("");             // free-text ticket search

  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [confirmDay, setConfirmDay] = useState(null); // past day pending resync confirmation
  const [detailPerson, setDetailPerson] = useState(null); // assignee drill-down (movement stats)
  const [view, setView] = useState("board"); // active side-panel route

  const todayStr = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD (local)

  async function loadDates(selectNewest = true) {
    const d = (await api.snapshotDates()) || [];
    setDates(d);
    if (selectNewest && d.length) { setDate(d[0].snapshot_date); setSprintKey(d[0].sprint_name); }
    return d;
  }

  // Resolve the board list on mount and pin an active board for this tab. If the tab
  // opened without (or with an unknown) ?project=, default to the first configured board
  // and write it into the URL so the selection is explicit and survives reload.
  useEffect(() => {
    api.listProjects().then((list) => {
      const ps = list || [];
      setProjects(ps);
      if (!ps.length) return;
      const current = getProject();
      const valid = ps.some((p) => p.key === current);
      if (!valid) {
        persistProject(ps[0].key);
        setProjectState(ps[0].key);
      }
    }).catch((e) => setError(e.message));
  }, []);

  // (Re)load the board whenever the active project changes.
  useEffect(() => {
    if (!project) return;
    loadDates().catch((e) => setError(e.message));
  }, [project]);

  function onSelectProject(key) {
    if (key === project) return;
    persistProject(key);            // updates this tab's URL (?project=key)
    setProjectState(key);           // triggers the [project] effect → reloads dates
    // Clear board/report state so nothing from the previous board lingers.
    setBoard(null); setDate(""); setSprintKey(null); setDetailPerson(null);
    setEpic(null); setStatus(null); setQ(""); setError(null); setNotice(null);
  }

  const activeProjectName = useMemo(
    () => projects.find((p) => p.key === project)?.name || project,
    [projects, project],
  );

  // group snapshot dates by their real Jira sprint (newest first)
  const sprints = useMemo(() => {
    const m = new Map();
    for (const d of dates) {
      const k = d.sprint_name || "Unassigned sprint";
      if (!m.has(k)) m.set(k, { name: k, start: d.sprint_start, end: d.sprint_end, dates: [] });
      m.get(k).dates.push(d);
    }
    // order by most recent snapshot date within each sprint
    return [...m.values()].sort((a, b) => (a.dates[0].snapshot_date < b.dates[0].snapshot_date ? 1 : -1));
  }, [dates]);
  const sprintDates = useMemo(() => dates.filter((d) => (d.sprint_name || "Unassigned sprint") === sprintKey), [dates, sprintKey]);

  function pickSprint(k) {
    setSprintKey(k);
    const inSprint = dates.filter((d) => (d.sprint_name || "Unassigned sprint") === k);
    if (inSprint.length) { setEpic(null); setStatus(null); setDate(inSprint[0].snapshot_date); }
  }

  useEffect(() => {
    if (!date) { setBoard(null); return; }
    setLoading(true); setError(null);
    api.board(date) // fetch the whole day; filter client-side so chip counts stay stable
      .then(setBoard)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [date]);

  async function doResync(target, force) {
    setSyncing(true); setError(null); setNotice(null); setConfirmDay(null);
    try {
      const res = await api.snapshotAll(target, force);   // all boards, parallel on the backend
      const rows = res.projects || [];
      const ok = rows.filter((r) => r.status === "success");
      const bad = rows.filter((r) => r.status !== "success");
      setNotice(
        (ok.map((r) => `${r.key} ${r.issues}`).join(" · ") || "No boards") + " tickets saved"
        + (bad.length ? ` — ${bad.map((r) => `${r.key}: ${r.status}`).join(", ")}` : "")
      );
      if (bad.length) setError(bad.map((r) => `${r.key}: ${r.error || r.status}`).join(" | "));

      const d = await loadDates(false);
      // pick the current board's snapshot_date (fall back to any success)
      const mine = rows.find((r) => r.key === project && r.snapshot_date);
      const snap = (mine || ok[0] || {}).snapshot_date;
      if (snap) {
        setDate(snap);
        const hit = d.find((x) => x.snapshot_date === snap);
        if (hit) setSprintKey(hit.sprint_name);
      }
    } catch (e) {
      setError(`Sync failed: ${e.message}`);
    } finally {
      setSyncing(false);
    }
  }

  // "Sync today" — always safe, no confirmation.
  const onSyncToday = () => doResync(undefined, false);
  // "Resync this day" — if today, just do it; if a past day, confirm first.
  function onResyncSelected() {
    if (!date || date >= todayStr) doResync(date || undefined, false);
    else setConfirmDay(date);
  }

  const items = board?.items || [];
  const epicColors = useMemo(() => colorMap(board?.epics || []), [board]);

  // counts for filter chips (whole day, unfiltered)
  const epicCounts = useMemo(() => {
    const m = {};
    for (const t of items) { const e = t.epic_name; if (e) m[e] = (m[e] || 0) + 1; }
    return m;
  }, [items]);
  const statusCounts = useMemo(() => {
    const m = {};
    for (const t of items) m[t.status] = (m[t.status] || 0) + 1;
    return m;
  }, [items]);

  const query = q.trim().toLowerCase();
  const match = (t) =>
    (!epic || t.epic_name === epic) &&
    (!status || t.status === status) &&
    (!hideDone || t.status !== "Done") &&
    (!query ||
      [t.issue_key, t.summary, t.assignee, t.epic_name]
        .some((v) => (v || "").toLowerCase().includes(query)));

  // group filtered items by assignee → people columns (most tickets first)
  const people = useMemo(() => {
    const totals = {}; // unfiltered total per person
    for (const t of items) {
      const a = t.assignee || "Unassigned";
      totals[a] = (totals[a] || 0) + 1;
    }
    const groups = {};
    for (const t of items) {
      if (!match(t)) continue;
      const a = t.assignee || "Unassigned";
      (groups[a] ||= { name: a, tickets: [], sc: {} });
      groups[a].tickets.push(t);
      groups[a].sc[t.status] = (groups[a].sc[t.status] || 0) + 1;
    }
    const filtering = !!(epic || status);
    let arr = Object.values(groups).map((g) => ({
      ...g, total: totals[g.name], shown: g.tickets.length,
    }));
    // keep board column order by sprint board: status order then key
    arr.forEach((g) => g.tickets.sort((a, b) => {
      const d = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
      return d !== 0 ? d : a.issue_key.localeCompare(b.issue_key);
    }));
    arr.sort((a, b) => b.shown - a.shown || a.name.localeCompare(b.name));
    return arr;
  }, [items, epic, status, hideDone, query]);

  const filtering = !!(epic || status || query);
  const shownTotal = people.reduce((n, p) => n + p.shown, 0);

  function exportCSV() {
    const rows = [["Key", "Summary", "Assignee", "Epic", "Status"]];
    items.filter(match).forEach((t) =>
      rows.push([t.issue_key, t.summary, t.assignee, t.epic_name || "No Epic", t.status]));
    const csv = rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nex_board_${date}.csv`;
    a.click();
  }

  function go(v) { setView(v); setDetailPerson(null); }
  // The KPI view's all-sprints mode spans every sprint, so the sprint tabs would be a
  // control that changes nothing — hide them rather than leave a dead selector on screen.
  const showSprintTabs =
    SPRINT_VIEWS.includes(view) && sprints.length > 0 && !(view === "kpi" && kpiOverall);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">S</span>
          <div className="brand-txt"><b>Sprint Tracker</b><span>Anervea Eng</span></div>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.key}
              className={"nav-item" + (view === n.key ? " active" : "")}
              onClick={() => go(n.key)}
            >
              <span className="nav-ico">{n.icon}</span>{n.label}
              {n.tag && <span className="nav-tag">{n.tag}</span>}
            </button>
          ))}
        </nav>
        <div className="side-foot"><span className="dot" />{activeProjectName}</div>
      </aside>

      <main className="app-main">
      <div className="top">
        <div>
          <h1>{TITLES[view]}</h1>
          <p className="sub">
            <select
              className="project-select"
              value={project}
              onChange={(e) => onSelectProject(e.target.value)}
              title="Switch board (this tab)"
            >
              {projects.map((p) => (
                <option key={p.key} value={p.key}>{p.key} · {p.name}</option>
              ))}
            </select>
            {" "}board
          </p>
        </div>
        <div className="top-right">
          <button className="sync-btn" onClick={onSyncToday} disabled={syncing}>
            {syncing ? "Syncing all boards…" : "⟳ Sync all boards"}
          </button>
          <div className="refreshed">{board ? `${board.total} tickets · ${fmtDate(date)}` : ""}</div>
        </div>
      </div>

      {showSprintTabs && (
        <div className="sprint-tabs">
          {sprints.map((s) => (
            <button
              key={s.name}
              className={"sprint-tab" + (s.name === sprintKey ? " active" : "")}
              onClick={() => pickSprint(s.name)}
            >
              <span className="st-name">{s.name}</span>
              <span className="st-range">
                {s.start && s.end ? `${fmtDate(s.start)} – ${fmtDate(s.end)}` : "—"}
              </span>
            </button>
          ))}
        </div>
      )}

      {view === "board" && detailPerson && (
        <AssigneeStats name={detailPerson} onBack={() => setDetailPerson(null)} />
      )}

      {(view === "movement" || view === "timelog") && (
        <RoutePerson assignees={board?.assignees || []} initialTab={view === "timelog" ? "timelog" : "movement"} />
      )}

      {view === "kpi" && (
        <DevKpi
          key={project}
          sprint={sprintKey}
          overall={kpiOverall}
          onOverallChange={setKpiOverall}
        />
      )}

      {view === "capacity" && <CapacityTracker key={project} />}

      {/* Cross-board by nature: one cron run syncs every board, so this view is NOT
          keyed on `project` and ignores the board switcher. */}
      {view === "synchealth" && <SyncHealth />}

      {view === "report" && (
        <SprintReportRoute date={date} sprints={sprints} sprintKey={sprintKey} />
      )}

      {view === "board" && !detailPerson && (<>
      <div className="dayrow">
        <span className="lab">DAY</span>
        {dates.length === 0 && <span className="daypill">none yet — click sync</span>}
        {sprintDates.map((d) => (
          <button
            key={d.snapshot_date}
            className={"daypill" + (d.snapshot_date === date ? " active" : "")}
            onClick={() => { setEpic(null); setStatus(null); setDate(d.snapshot_date); }}
          >
            {weekday(d.snapshot_date)} {fmtDate(d.snapshot_date)} ({d.total})
          </button>
        ))}
        {date && date < todayStr && (
          <button className="resync-day" onClick={onResyncSelected} disabled={syncing} title="Overwrite this past day for all boards with today's live board">
            ↻ Resync {fmtDate(date)}
          </button>
        )}
      </div>

      {board && (
        <div className="filters">
          <button className={"chip chip-all" + (!epic && !status ? " on" : "")}
            onClick={() => { setEpic(null); setStatus(null); }}>
            All <span className="ct">{board.total}</span>
          </button>
          {board.epics.map((e) => (
            <button key={e} className={"chip" + (epic === e ? " on" : "")}
              onClick={() => setEpic(epic === e ? null : e)}>
              <span className="dot" style={{ background: epicColors[e] }} />
              {e.length > 22 ? e.slice(0, 20) + "…" : e} <span className="ct">{epicCounts[e] || 0}</span>
            </button>
          ))}
          <span className="sep" />
          <button className={"chip" + (!status ? " on" : "")} onClick={() => setStatus(null)}>All Status</button>
          {STATUS_ORDER.filter((s) => statusCounts[s]).map((s) => (
            <button key={s} className={"chip" + (status === s ? " on" : "")}
              onClick={() => setStatus(status === s ? null : s)}>
              <span className="dot" style={{ background: STATUS[s].c }} />
              {s} <span className="ct">{statusCounts[s]}</span>
            </button>
          ))}
          {statusCounts["Done"] > 0 && (
            <button className={"chip" + (hideDone ? " on" : "")} onClick={() => setHideDone((v) => !v)}>
              {hideDone ? "Show Done" : "Hide Done"} <span className="ct">{statusCounts["Done"]}</span>
            </button>
          )}
          <span className="spacer" />
          <div className="search">
            <span className="search-ico">⌕</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search tickets…"
              spellCheck={false}
            />
            {q && <button className="search-x" onClick={() => setQ("")} title="Clear search">×</button>}
          </div>
          <button className="excel" onClick={exportCSV}>↓ Excel</button>
        </div>
      )}

      {notice && <div className="notice">{notice}</div>}
      {error && <div className="error">{error}</div>}
      {dates.length === 0 && !syncing && !error && (
        <div className="empty">No board saved yet. Click <b>Sync all boards</b> to capture today.</div>
      )}
      {confirmDay && (
        <div className="modal-overlay" onClick={() => setConfirmDay(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Resync a past day?</h3>
            <p>
              <b>{fmtDate(confirmDay)}</b> is in the past. Resyncing will <b>delete</b> that day's saved
              snapshot for <b>all boards</b> and replace it with <b>today's live board</b> from Jira — the
              tickets/statuses as they are right now, not how they were on {fmtDate(confirmDay)}. This
              can't be undone.
            </p>
            <div className="modal-actions">
              <button className="btn-ghost" onClick={() => setConfirmDay(null)}>Cancel</button>
              <button className="btn-danger" onClick={() => doResync(confirmDay, true)}>
                Yes, resync {fmtDate(confirmDay)}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading && <div className="loading">Loading board…</div>}

      {!loading && board && people.length === 0 && (
        <div className="empty">No tickets match your search.</div>
      )}

      {!loading && board && people.length > 0 && (
        <>
          <Board people={people} epicColors={epicColors} filtering={filtering} onSelect={setDetailPerson} />
          <div className="foot">
            {filtering ? `${shownTotal} of ${board.total}` : board.total} tickets ·
            {" "}{people.length} {people.length === 1 ? "person" : "people"} · live from the {project} board ·
            click an epic or status to filter, ↓ Excel exports the current view.
          </div>
        </>
      )}
      </>)}
      </main>
    </div>
  );
}

// Movement / Time Log routes: pick a developer, then reuse the AssigneeStats drill-down.
function RoutePerson({ assignees, initialTab }) {
  const [person, setPerson] = useState("");
  useEffect(() => {
    if (assignees.length && !assignees.includes(person)) setPerson(assignees[0]);
  }, [assignees]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!assignees.length) {
    return <div className="empty">Sync a board first, then pick a developer here.</div>;
  }
  return (
    <div>
      <div className="stats-controls">
        <label className="route-pick">
          Developer{" "}
          <select className="project-select" value={person} onChange={(e) => setPerson(e.target.value)}>
            {assignees.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>
      {person && <AssigneeStats key={person + initialTab} name={person} initialTab={initialTab} />}
    </div>
  );
}

// Sprint Report route: open the printable reports (report.js) for the selected sprint.
function SprintReportRoute({ date, sprints, sprintKey }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function openSprint() {
    setBusy(true); setErr(null);
    try {
      const r = await api.sprintReport(date);
      if (r) openReport(r); else setErr("No snapshot for this day — sync first.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function openCompare() {
    // sprints are newest-first: current sprint is the kickoff, the one before it is the closing.
    const idx = sprints.findIndex((s) => s.name === sprintKey);
    const kickoff = sprints[idx]?.name;
    const closing = sprints[idx + 1]?.name;
    if (!closing || !kickoff) { setErr("Need two sprints to build a closure vs kickoff deck."); return; }
    setBusy(true); setErr(null);
    try {
      const c = await api.sprintCompare(closing, kickoff);
      if (c) openCompareReport(c); else setErr("No data for those sprints.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="stats-view">
      <p className="sub sub-tight">Open a printable report in a new tab (print → Save as PDF).</p>
      <div className="report-actions">
        <button className="sync-btn" onClick={openSprint} disabled={busy}>Daily sprint report</button>
        <button className="sync-btn" onClick={openCompare} disabled={busy}>Closure → kickoff deck</button>
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  );
}
