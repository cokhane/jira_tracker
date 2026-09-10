import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

// Labels for the night states produced by app/sync_health.py. The COLOURS live in
// index.css as .sh-<state>, so the strip cells and the legend swatches read from one
// definition and cannot drift apart; `off` and `pending` are muted there, because a night
// the cron was never scheduled for must not read as a problem.
const STATES = {
  ok: "Synced",
  running: "In progress",
  failed: "Failed",
  missed: "Never ran",
  unscheduled: "Off-schedule only",
  pending: "Not due yet",
  off: "Not scheduled",
};

// `warn` is a board that is fine RIGHT NOW but has a bad night behind it in the window.
// It stays distinct from healthy so a failure that fixed itself doesn't vanish unseen.
const BOARD_STATUS = { ok: "Healthy", warn: "Recent gap", error: "Needs attention" };

const DOW = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WINDOWS = [14, 30, 60];

// "Mon–Sat" when the scheduled days run contiguously, "Mon, Wed, Fri" when they don't.
function weekdayLabel(days = []) {
  if (!days.length) return "never";
  const contiguous = days.every((d, i) => i === 0 || d === days[i - 1] + 1);
  return contiguous && days.length > 2
    ? `${DOW[days[0]]}–${DOW[days[days.length - 1]]}`
    : days.map((d) => DOW[d]).join(", ");
}

const clock = (iso) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
const day = (iso) =>
  new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

// Tooltip text for one cell — the whole point of the strip is hovering a bad night to
// find out what happened, so the runs' own numbers and error go in here.
function cellTitle(d) {
  const head = `${day(d.date + "T00:00:00")} · ${STATES[d.state] || d.state}`;
  if (!d.runs.length) return head;
  const lines = d.runs.map((r) => {
    const counts = `${r.fetched} fetched · ${r.created} new · ${r.updated} updated`;
    const tail = r.error ? `\n    ${r.error}` : "";
    return `  ${clock(r.started_at)} ${r.status} (${duration(r.duration_seconds)}) — ${counts}${tail}`;
  });
  return [head, ...lines].join("\n");
}

function LastRun({ run }) {
  if (!run) return <p className="sh-last sh-none">No sync has ever been recorded.</p>;
  // An in-flight run has its counters still at zero. Printing them would read as a
  // finished sync that did nothing, so say what is actually happening instead.
  const inFlight = run.status === "running";
  return (
    <div className="sh-last">
      <span className="sh-last-when">
        {day(run.started_at)} at {clock(run.started_at)}
      </span>
      {!inFlight && <span className="sh-last-dur mono">{duration(run.duration_seconds)}</span>}
      {run.status === "error" && (
        <span className="sh-err">{run.error || "errored with no message"}</span>
      )}
      {inFlight && <span className="sh-last-dur">syncing now…</span>}
      {run.status === "success" && (
        <span className="sh-counts mono">
          {run.fetched} fetched · {run.created} new · {run.updated} updated ·{" "}
          {run.transitions} transitions
        </span>
      )}
    </div>
  );
}

function BoardCard({ board }) {
  const verdict = "sh-st-" + (BOARD_STATUS[board.status] ? board.status : "error");
  // A night the cron skipped counts as a problem even when a manual sync refreshed the
  // data that day — otherwise the one failure worth catching is the one that stays hidden.
  const bad = [
    ...(board.failed_days || []),
    ...(board.missed_days || []),
    ...(board.unscheduled_days || []),
  ].sort();
  return (
    <div className="sh-card">
      <div className="sh-card-head">
        <span className={"sh-dot " + verdict} />
        <b className="sh-key">{board.key}</b>
        <span className="sh-name">{board.name}</span>
        <span className={"sh-status " + verdict}>
          {BOARD_STATUS[board.status] || BOARD_STATUS.error}
        </span>
      </div>

      {board.error ? (
        <p className="sh-err">{board.error}</p>
      ) : (
        <>
          <LastRun run={board.last_run} />
          <div className="sh-strip">
            {(board.days || []).map((d) => (
              <span key={d.date} className={"sh-cell sh-" + d.state} title={cellTitle(d)} />
            ))}
          </div>
          {bad.length > 0 && (
            <p className="sh-bad">
              {bad.length} problem {bad.length === 1 ? "night" : "nights"}:{" "}
              {bad.map((d) => day(d + "T00:00:00")).join(", ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default function SyncHealth() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .syncHealth(days)
      .then((res) => {
        setData(res);
        setFetchedAt(new Date());
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(load, [load]);

  const schedule = data?.schedule;
  const boards = data?.projects || [];
  // The strip legend only lists states actually on screen — a legend for states that
  // never appear is just noise to scan past.
  const shown = new Set(boards.flatMap((b) => (b.days || []).map((d) => d.state)));

  return (
    <div className="sh-view">
      <div className="sh-bar">
        {schedule && (
          <span className="sh-sched">
            Scheduled{" "}
            <b>
              {String(schedule.hour).padStart(2, "0")}:00, {weekdayLabel(schedule.weekdays)}
            </b>{" "}
            · {schedule.timezone}
            {schedule.live_since && <> · live since {day(schedule.live_since + "T00:00:00")}</>}
          </span>
        )}
        <span className="spacer" />
        {WINDOWS.map((w) => (
          <button
            key={w}
            className={"daypill" + (days === w ? " active" : "")}
            onClick={() => setDays(w)}
          >
            {w}d
          </button>
        ))}
        <button className="sync-btn" onClick={load} disabled={loading}>
          {loading ? "Checking…" : "Refresh"}
        </button>
      </div>

      {error && <p className="sh-err sh-err-block">{error}</p>}
      {!error && !data && loading && <p className="empty">Checking sync health…</p>}

      <div className="sh-cards">
        {boards.map((b) => (
          <BoardCard key={b.key} board={b} />
        ))}
      </div>

      {boards.length > 0 && (
        <div className="sh-legend">
          {Object.entries(STATES)
            .filter(([state]) => shown.has(state))
            .map(([state, label]) => (
              <span key={state} className="sh-leg">
                <span className={"sh-cell sh-" + state} />
                {label}
              </span>
            ))}
          <span className="spacer" />
          {fetchedAt && <span className="refreshed">checked {clock(fetchedAt.toISOString())}</span>}
        </div>
      )}
    </div>
  );
}
