import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { STATUS, initials } from "../lib.js";

const fmtDay = (d) =>
  new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

// The three movements we track, in board order, with their column colors.
const COLS = [
  { key: "to_code_review", label: "Code Review", c: STATUS["Code Review"].c },
  { key: "to_qa_testing", label: "QA Testing", c: STATUS["QA Testing"].c },
  { key: "to_done", label: "Done", c: STATUS["Done"].c },
];

// Per-assignee drill-down: movement stats (columns) and time log (hours per ticket).
// `onBack` is optional — omitted when mounted as a standalone route (the sidebar navigates).
export default function AssigneeStats({ name, onBack, initialTab = "movement" }) {
  const [tab, setTab] = useState(initialTab); // "movement" | "timelog"

  return (
    <div className="stats-view">
      {onBack && <button className="back" onClick={onBack}>← Back to board</button>}

      <div className="stats-head">
        <span className="avatar" style={{ background: "var(--accent)" }}>{initials(name)}</span>
        <div>
          <h2>{name}</h2>
          <p className="sub">
            {tab === "movement"
              ? "Tickets sent to each column"
              : "Time logged per ticket (from Jira worklogs)"}
          </p>
        </div>
      </div>

      <div className="seg tab-seg">
        <button className={tab === "movement" ? "on" : ""} onClick={() => setTab("movement")}>Movement</button>
        <button className={tab === "timelog" ? "on" : ""} onClick={() => setTab("timelog")}>Time Log</button>
      </div>

      {tab === "movement" ? <Movement name={name} /> : <TimeLog name={name} />}
    </div>
  );
}

// ---- Movement tab (day/week counts of tickets sent to CR / QA / Done) ----
function Movement({ name }) {
  const [gran, setGran] = useState("day");
  const [by, setBy] = useState("assignee");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true); setError(null);
    api.assigneeMovement(name, gran, by)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [name, gran, by]);

  const rows = data?.rows || [];
  const peak = useMemo(
    () => Math.max(1, ...rows.flatMap((r) => COLS.map((c) => r[c.key]))),
    [rows]
  );

  return (
    <>
      <p className="sub sub-tight">{gran === "day" ? "day by day" : "week by week"}</p>
      <div className="stats-controls">
        <div className="seg">
          <button className={gran === "day" ? "on" : ""} onClick={() => setGran("day")}>Day</button>
          <button className={gran === "week" ? "on" : ""} onClick={() => setGran("week")}>Week</button>
        </div>
        <div className="seg">
          <button className={by === "assignee" ? "on" : ""} onClick={() => setBy("assignee")} title="Moves while this person owned the ticket">As assignee</button>
          <button className={by === "mover" ? "on" : ""} onClick={() => setBy("mover")} title="Moves this person performed">As mover</button>
        </div>
      </div>

      {data && (
        <div className="totals">
          {COLS.map((c) => (
            <div className="total-card" key={c.key} style={{ "--tc": c.c }}>
              <div className="tc-n">{data[`total_${c.key.slice(3)}`]}</div>
              <div className="tc-l">→ {c.label}</div>
            </div>
          ))}
        </div>
      )}

      {loading && <div className="loading">Loading stats…</div>}
      {error && <div className="error">{error}</div>}

      {!loading && data && rows.length === 0 && (
        <div className="empty">No Code Review / QA / Done movements recorded for {name}.</div>
      )}

      {!loading && rows.length > 0 && (
        <table className="stats-table">
          <thead>
            <tr>
              <th className="th-day">{gran === "day" ? "Day" : "Week of"}</th>
              {COLS.map((c) => (
                <th key={c.key} style={{ color: c.c }}>→ {c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.bucket}>
                <td className="td-day">{fmtDay(r.bucket)}</td>
                {COLS.map((c) => (
                  <td key={c.key} className="mono">
                    {r[c.key] > 0 ? (
                      <span className="cell">
                        <span className="bar" style={{ width: `${(r[c.key] / peak) * 100}%`, background: c.c }} />
                        <b style={{ color: c.c }}>{r[c.key]}</b>
                      </span>
                    ) : <span className="zero">·</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ---- Time Log tab (hours logged per ticket, from Jira worklogs) ----
function TimeLog({ name }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true); setError(null);
    api.assigneeWorklog(name)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [name]);

  const rows = data?.rows || [];
  const logged = rows.filter((r) => r.seconds);

  function exportCSV() {
    const out = [["Name of the Dev", "Hours", "Outcome Achieved"]];
    rows.forEach((r, i) =>
      out.push([i === rows.length - 1 ? name : "", r.time_spent || "n/a", `${r.key}: ${r.summary || ""}`]));
    const csv = out.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `timelog_${name.replace(/\s+/g, "_")}.csv`;
    a.click();
  }

  return (
    <>
      {data && (
        <div className="totals">
          <div className="total-card" style={{ "--tc": "var(--accent)" }}>
            <div className="tc-n">{data.total_time_spent || "0m"}</div>
            <div className="tc-l">total logged</div>
          </div>
          <div className="total-card" style={{ "--tc": "var(--prog)" }}>
            <div className="tc-n">{logged.length}</div>
            <div className="tc-l">tickets with time</div>
          </div>
        </div>
      )}

      {loading && <div className="loading">Loading time log…</div>}
      {error && <div className="error">{error}</div>}

      {!loading && data && rows.length === 0 && (
        <div className="empty">No worklogs or owned tickets for {name}. (Re-sync the board to pull worklogs.)</div>
      )}

      {!loading && rows.length > 0 && (
        <>
          <div className="stats-controls stats-controls-end">
            <button className="excel" onClick={exportCSV}>↓ Excel</button>
          </div>
          <table className="stats-table timelog-table">
            <thead>
              <tr>
                <th className="th-hours">Hours</th>
                <th>Outcome Achieved</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="mono td-hours">
                    {r.time_spent
                      ? <b>{r.time_spent}</b>
                      : <span className="zero">n/a</span>}
                  </td>
                  <td>
                    <a className="wl-link" href={r.web_url || "#"} target="_blank" rel="noreferrer">
                      <span className="key">{r.key}</span>
                      <span className="wl-sum" title={r.summary}>{r.summary || "(no title)"}</span>
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
