import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { initials } from "../lib.js";

// KPI Tracker — the per-developer scorecard, in two modes.
//
//   THIS SPRINT  (/reports/dev-kpi)          one sprint, one row per developer
//   ALL SPRINTS  (/reports/dev-kpi/overall)  every sprint summed, one TOTAL row per
//                                            developer, openable into the sprints behind it
//
// Every number is decided server-side, including the rating: a metric the API and a chart
// could disagree about is a metric nobody trusts. This file only arranges what it is handed,
// and its one derived value is the team footer, which sums the same rows the table shows.

const STAR_TOTAL = 5;

// Delivery % reads as a traffic light: on plan, most of the way there, or short.
function deliveryColor(pct) {
  if (pct >= 90) return "var(--done)";
  if (pct >= 60) return "var(--prog)";
  return "var(--block)";
}

const pct = (n) => `${n.toFixed(n % 1 ? 1 : 0)}%`;

const fmtDate = (d) =>
  new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

function Stars({ n }) {
  return (
    <span className="kpi-stars" title={`${n} of ${STAR_TOTAL}`}>
      {"★".repeat(n)}
      <span className="kpi-star-off">{"★".repeat(STAR_TOTAL - n)}</span>
    </span>
  );
}

// A count cell that greys out at zero — zero is the good outcome for reopens and blocks,
// so it should recede rather than compete with the numbers that need attention.
function Count({ value, color }) {
  if (!value) return <td className="kpi-num kpi-zero">0</td>;
  return <td className="kpi-num" style={{ color }}>{value}</td>;
}

// One line of the scorecard. A single sprint, an all-sprints total, and one sprint inside a
// total are the same nine numbers, so they share one renderer instead of three that could
// drift on what a column means. `label` is the only thing that differs, so the caller owns it.
function KpiRow({ label, row, className, onClick }) {
  return (
    <tr className={className} onClick={onClick}>
      <td className="kpi-dev">{label}</td>
      <td className="kpi-num">
        {row.target}
        {row.target_is_default && (
          <span className="kpi-assumed" title="No Capacity Tracker cell — board default">
            assumed
          </span>
        )}
      </td>
      <td className="kpi-num kpi-done">{row.done}</td>
      <td className="kpi-delcol">
        <span className="kpi-bar-cell">
          <span className="kpi-bar-track">
            <span
              className="kpi-bar"
              style={{
                width: `${Math.min(row.delivery_pct, 100)}%`,
                background: deliveryColor(row.delivery_pct),
              }}
            />
          </span>
          <b style={{ color: deliveryColor(row.delivery_pct) }}>{pct(row.delivery_pct)}</b>
        </span>
      </td>
      <Count value={row.reopened} color="var(--qa)" />
      <td className={"kpi-num" + (row.reopened ? "" : " kpi-zero")}>{pct(row.reopen_pct)}</td>
      <Count value={row.blocked} color="var(--block)" />
      <Count value={row.wip} color="var(--prog)" />
      <td className="kpi-ratecol">
        <Stars n={row.stars} />
        <span className="kpi-score">{row.rating.toFixed(1)}</span>
      </td>
    </tr>
  );
}

export default function DevKpi({ sprint, overall, onOverallChange }) {
  // The payload is stored WITH the mode it answers for, so the render between flipping the
  // switch and the fetch resolving can't paint one mode's numbers under the other's headings.
  const [loaded, setLoaded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(() => new Set()); // developers whose history is expanded

  useEffect(() => {
    let live = true; // the two endpoints answer at different speeds — don't let the loser win
    setLoading(true);
    setError(null);
    (overall ? api.devKpiOverall() : api.devKpi(sprint))
      .then((d) => { if (live) setLoaded({ overall, data: d }); })
      .catch((e) => { if (live) setError(e.message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [sprint, overall]);

  const data = loaded?.overall === overall ? loaded.data : null;

  // A total's history is meaningless against per-sprint rows, so switching modes closes them.
  useEffect(() => setOpen(new Set()), [overall]);

  function toggle(name) {
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }

  const team = useMemo(() => {
    const rows = data?.rows || [];
    if (!rows.length) return null;
    const sum = (f) => rows.reduce((t, r) => t + f(r), 0);
    const target = sum((r) => r.target);
    const done = sum((r) => r.done);
    return {
      target,
      done,
      delivery_pct: target ? (done / target) * 100 : 0,
      reopened: sum((r) => r.reopened),
      blocked: sum((r) => r.blocked),
      wip: sum((r) => r.wip),
      rating: sum((r) => r.rating) / rows.length,
      assumed: rows.filter((r) => r.target_is_default).length,
    };
  }, [data]);

  const modes = (
    <div className="kpi-mode seg">
      <button
        className={overall ? "" : "on"}
        onClick={() => onOverallChange(false)}
        title="One sprint — the one selected above"
      >
        This sprint
      </button>
      <button
        className={overall ? "on" : ""}
        onClick={() => onOverallChange(true)}
        title="Every sprint this board has data for, summed per developer"
      >
        All sprints
      </button>
    </div>
  );

  if (error) return <>{modes}<div className="error">{error}</div></>;
  if (loading || !data) return <>{modes}<div className="loading">Loading KPIs…</div></>;
  if (!data.rows.length) {
    return <>{modes}<div className="empty">No roster developers on this board yet.</div></>;
  }

  const span = data.sprint_names?.length || 0;
  // The newest sprint hasn't finished yet if its end date is still ahead. It is counted like
  // any other (this view means EVERY sprint with data), but a part-delivered sprint averaged
  // into a rating pulls every developer down, so the row that does it is named.
  const inFlight =
    data.last_end && data.last_end >= new Date().toLocaleDateString("en-CA")
      ? data.sprint_names.at(-1)
      : null;

  return (
    <div className="kpi-view">
      {modes}

      {overall ? (
        <p className="sub sub-tight">
          {span} sprint{span === 1 ? "" : "s"}
          {data.first_start && data.last_end
            ? ` · ${fmtDate(data.first_start)} – ${fmtDate(data.last_end)}`
            : ""}
          {" "}· every sprint this board has data for. Counts are the per-sprint rows added
          up; Rating is the <b>average</b> of them, so one big sprint can't carry a whole run.
          WIP is as of {data.as_of_date ? fmtDate(data.as_of_date) : "the latest snapshot"} —
          a plate, not a total. <b>Click a developer</b> to see the sprints behind their row.
          {inFlight && (
            <>
              {" "}
              <b>{inFlight}</b> is still running, so it counts as a part-delivered sprint and
              holds every rating down a little — it's marked <i>in flight</i> in the rows.
            </>
          )}
        </p>
      ) : (
        <p className="sub sub-tight">
          {data.sprint_name} · delivery measured over the sprint, WIP as of{" "}
          {data.as_of_date || "the latest snapshot"}. Rating weights delivery (50%),
          quality (35%) and flow (15%) — capped at target, so volume alone can't buy it.
        </p>
      )}

      {team.assumed > 0 && (
        <div className="notice kpi-note">
          {overall ? (
            <>
              {team.assumed} developer{team.assumed > 1 ? "s have" : " has"} at least one
              sprint with no cell on the Capacity Tracker, so that sprint's Target is the
              board default — marked <span className="kpi-assumed">assumed</span> below.
              Open the row to see which sprints are measured against a guess.
            </>
          ) : (
            <>
              {team.assumed} developer{team.assumed > 1 ? "s have" : " has"} no cell on the
              Capacity Tracker for this sprint, so their Target is the board default —
              marked <span className="kpi-assumed">assumed</span> below. Their Delivery % is
              measured against a guess, not a plan.
            </>
          )}
        </div>
      )}

      <div className="kpi-tiles">
        <div className="kpi-tile">
          <span className="kpi-tile-v">{team.done}<em>/{team.target}</em></span>
          <span className="kpi-tile-l">Delivered / Target</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-tile-v" style={{ color: deliveryColor(team.delivery_pct) }}>
            {pct(team.delivery_pct)}
          </span>
          <span className="kpi-tile-l">Team delivery</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-tile-v" style={{ color: team.reopened ? "var(--qa)" : undefined }}>
            {team.reopened}
          </span>
          <span className="kpi-tile-l">Reopened by QA</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-tile-v" style={{ color: team.blocked ? "var(--block)" : undefined }}>
            {team.blocked}
          </span>
          <span className="kpi-tile-l">Blocked</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-tile-v" style={{ color: "var(--prog)" }}>{team.wip}</span>
          <span className="kpi-tile-l">In progress</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-tile-v">{team.rating.toFixed(1)}</span>
          <span className="kpi-tile-l">Avg rating</span>
        </div>
      </div>

      <div className="kpi-wrap">
        <table className="kpi-table">
          <thead>
            <tr>
              <th className="kpi-dev">Dev</th>
              <th>Target</th>
              <th>Done</th>
              <th className="kpi-delcol">Delivery %</th>
              <th>Reopened</th>
              <th>Reopen %</th>
              <th>Blocked</th>
              <th>WIP</th>
              <th className="kpi-ratecol">Rating</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const history = r.history || [];
              const expanded = open.has(r.name);
              return (
                <Fragment key={r.name}>
                  <KpiRow
                    row={r}
                    className={overall && history.length ? "kpi-openable" : undefined}
                    onClick={overall && history.length ? () => toggle(r.name) : undefined}
                    label={
                      <span className="kpi-who">
                        {overall && (
                          <span className={"kpi-caret" + (expanded ? " open" : "")}>
                            {history.length ? "▸" : "·"}
                          </span>
                        )}
                        <span className="avatar kpi-av">{initials(r.name)}</span>
                        {r.name}
                        {overall && (
                          <span className="kpi-span">
                            {history.length
                              ? `${history.length} sprint${history.length === 1 ? "" : "s"}`
                              : "no data"}
                          </span>
                        )}
                      </span>
                    }
                  />
                  {expanded &&
                    history.map((h) => (
                      <KpiRow
                        key={h.sprint_name}
                        row={h}
                        className="kpi-sub"
                        label={
                          <span className="kpi-sub-name">
                            {h.sprint_name}
                            {h.sprint_name === inFlight && (
                              <span className="kpi-live" title="Still running — partial numbers">
                                in flight
                              </span>
                            )}
                          </span>
                        }
                      />
                    ))}
                </Fragment>
              );
            })}
            <tr className="kpi-total">
              <td className="kpi-dev">TEAM</td>
              <td className="kpi-num">{team.target}</td>
              <td className="kpi-num">{team.done}</td>
              <td className="kpi-delcol">
                <b style={{ color: deliveryColor(team.delivery_pct) }}>{pct(team.delivery_pct)}</b>
              </td>
              <td className="kpi-num">{team.reopened}</td>
              <td className="kpi-num">{pct(team.done ? (team.reopened / team.done) * 100 : 0)}</td>
              <td className="kpi-num">{team.blocked}</td>
              <td className="kpi-num">{team.wip}</td>
              <td className="kpi-ratecol"><span className="kpi-score">{team.rating.toFixed(1)}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="kpi-legend">
        <b>Done</b> counts each ticket once at the furthest stage it reached, credited to
        whoever moved it out of In Progress. <b>Reopened</b> and <b>Blocked</b> are credited
        to whoever owned the ticket at the time, not to whoever clicked.{" "}
        {overall && (
          <>
            A sprint is only counted for a developer if it was <b>planned</b> for them on the
            Capacity Tracker or they touched it — nobody is scored for sprints before they
            joined, which is why the sprint counts differ per row.{" "}
          </>
        )}
        <span className="kpi-stars">★★★★★</span> ≥85 · ★★★★ ≥70 · ★★★ ≥50 · ★★ ≥30 · ★ below.
      </p>
    </div>
  );
}
