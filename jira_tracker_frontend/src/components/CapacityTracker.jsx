import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api";

// Capacity Tracker — the team's rolling sprint capacity, one Capacity/Actual pair per sprint.
//
// Capacity is DERIVED server-side (each sprint's plan is the average of the previous sprint's
// plan and result), so only Actual is editable here. Every save returns the whole recomputed
// grid rather than one cell, because one actual moves every capacity after it.

const cellKey = (sprint, developer) => `${sprint}:${developer}`;

const fmtRange = (start, end) => {
  const short = (d) =>
    new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${short(start)} – ${short(end)}`;
};

// "" clears the cell; anything that isn't a whole number ≥ 0 is not a ticket count.
function parseActual(text) {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null };
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < 0) return { error: `"${trimmed}" is not a ticket count.` };
  return { value };
}

export default function CapacityTracker() {
  const [grid, setGrid] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [savingCell, setSavingCell] = useState(null);
  const [drafts, setDrafts] = useState({}); // cell -> text mid-edit, dropped once saved

  useEffect(() => {
    api.capacity()
      .then(setGrid)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Per-sprint column sums, so the TOTAL row never re-derives what the cells already hold.
  const totals = useMemo(() => {
    const sums = {};
    for (const dev of grid?.developers || []) {
      for (const cell of dev.cells) {
        const t = (sums[cell.sprint_number] ||= { capacity: 0, actual: 0, hasActual: false });
        t.capacity += cell.capacity || 0;
        if (cell.actual !== null && cell.actual !== undefined) {
          t.actual += cell.actual;
          t.hasActual = true;
        }
      }
    }
    return sums;
  }, [grid]);

  async function commit(sprint, developer, text) {
    const key = cellKey(sprint, developer);
    const { value, error: invalid } = parseActual(text);
    setDrafts((d) => { const next = { ...d }; delete next[key]; return next; });
    if (invalid) { setError(invalid); return; }

    setSavingCell(key);
    setError(null);
    try {
      setGrid(await api.setCapacityActual(sprint, developer, value));
    } catch (e) {
      setError(e.message);
    } finally {
      setSavingCell(null);
    }
  }

  if (loading) return <div className="loading">Loading capacity…</div>;
  if (error && !grid) return <div className="error">{error}</div>;
  if (!grid?.developers.length) {
    return <div className="empty">No developers on this board's report roster yet.</div>;
  }

  const { sprints, developers } = grid;

  return (
    <div className="cap-view">
      <p className="sub sub-tight">
        Each sprint's capacity is the average of the previous sprint's capacity and actual.
        Capacity is computed — type the <b>Actual</b> ticket counts and everything after them rolls forward.
      </p>
      {grid.skipped.length > 0 && (
        <div className="notice cap-note">
          In the capacity sheet but on no board's roster, so not shown: {grid.skipped.join(", ")}.
        </div>
      )}
      {error && <div className="error">{error}</div>}

      <div className="cap-wrap">
        <table className="cap-table">
          <thead>
            <tr>
              <th className="cap-dev" rowSpan={2}>Developer</th>
              {sprints.map((s) => (
                <th key={s.number} colSpan={2} className={"cap-head" + (s.is_current ? " now" : "")}>
                  <span className="cap-sn">{s.label}{s.is_current && <em> ● now</em>}</span>
                  <span className="cap-sd">{fmtRange(s.start, s.end)}</span>
                </th>
              ))}
            </tr>
            <tr>
              {sprints.map((s) => (
                <Fragment key={s.number}>
                  <th className="cap-sub">Cap</th>
                  <th className="cap-sub">Act</th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {developers.map((dev) => {
              const cells = new Map(dev.cells.map((c) => [c.sprint_number, c]));
              return (
                <tr key={dev.developer}>
                  <td className="cap-dev">{dev.developer}</td>
                  {sprints.map((s) => {
                    const cell = cells.get(s.number);
                    const key = cellKey(s.number, dev.developer);
                    const stored = cell?.actual ?? "";
                    return (
                      <Fragment key={s.number}>
                        <td className={"cap-cap" + (s.is_current ? " now" : "")}>
                          {cell?.capacity ?? "—"}
                        </td>
                        <td className={"cap-act" + (s.is_current ? " now" : "")}>
                          <input
                            className="cap-input"
                            inputMode="numeric"
                            value={drafts[key] ?? String(stored)}
                            disabled={savingCell === key}
                            placeholder="—"
                            aria-label={`${dev.developer}, ${s.label} actual`}
                            onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
                            onBlur={(e) => {
                              if (drafts[key] === undefined) return; // untouched — nothing to save
                              commit(s.number, dev.developer, e.target.value);
                            }}
                            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                          />
                        </td>
                      </Fragment>
                    );
                  })}
                </tr>
              );
            })}
            <tr className="cap-total">
              <td className="cap-dev">TOTAL</td>
              {sprints.map((s) => (
                <Fragment key={s.number}>
                  <td className={"cap-cap" + (s.is_current ? " now" : "")}>{totals[s.number]?.capacity ?? 0}</td>
                  <td className={"cap-act" + (s.is_current ? " now" : "")}>
                    {totals[s.number]?.hasActual ? totals[s.number].actual : "—"}
                  </td>
                </Fragment>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
