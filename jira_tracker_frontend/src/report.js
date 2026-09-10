// Builds self-contained, printable HTML sprint reports, styled to match the
// "Alfa Kinetic" deck (brown/orange). Everything is inlined — no external assets —
// so a report opens in a new tab, prints/saves to PDF cleanly, and can be saved as
// a standalone .html file.
//
// Two builders share one stylesheet:
//   buildReportHtml(r)        — single-sprint deck (from /api/reports/sprint)
//   buildCompareReportHtml(c) — two-sprint closure/kickoff deck (from /api/reports/sprint-compare)

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtDay = (d) =>
  d ? new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";

function statCard(label, value, note) {
  return `<div class="card">
    <div class="card-label">${esc(label)}</div>
    <div class="card-num">${esc(value)}</div>
    <div class="card-note">${esc(note || "")}</div>
  </div>`;
}

function bar(pct) {
  return `<div class="bar"><span style="width:${Math.max(2, Math.min(100, pct))}%"></span></div>`;
}

// Shared stylesheet (inner CSS only — wrapped in <style> by each builder).
const STYLE = `
  :root {
    --ink: #2E1A0E; --cream: #FBF6EF; --card: #F7ECE4; --card-line: #ECD9C9;
    --accent: #B5531F; --accent-soft: #C9702F; --muted: #8A6A54;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--cream); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  .wrap { max-width: 960px; margin: 0 auto; padding: 40px 48px 64px; }
  .toolbar {
    position: sticky; top: 0; background: var(--ink); color: #fff;
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 20px; font-size: 13px;
  }
  .toolbar button {
    background: var(--accent); color: #fff; border: 0; border-radius: 8px;
    padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  .toolbar button:hover { background: var(--accent-soft); }
  .eyebrow { color: var(--accent); font-weight: 700; letter-spacing: 2px; font-size: 12px; text-transform: uppercase; }
  h1 { font-size: 40px; margin: 6px 0 4px; font-family: Georgia, "Times New Roman", serif; }
  h2 { font-size: 24px; margin: 40px 0 14px; font-family: Georgia, "Times New Roman", serif; }
  .sub { color: var(--muted); margin: 2px 0; font-size: 15px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin-top: 20px; }
  .card { background: var(--card); border: 1px solid var(--card-line); border-radius: 12px; padding: 18px; }
  .card-label { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; }
  .card-num { font-size: 40px; font-weight: 700; font-family: Georgia, serif; line-height: 1.1; margin: 6px 0; }
  .card-note { color: var(--muted); font-size: 13px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }
  th { background: var(--accent); color: #fff; text-align: left; padding: 10px 12px; font-size: 12px; letter-spacing: .5px; }
  td { padding: 9px 12px; border-bottom: 1px solid var(--card-line); }
  tr:nth-child(even) td { background: #fdf7f1; }
  tr.total td { font-weight: 700; background: #f2e4d8; }
  .mono { font-variant-numeric: tabular-nums; }
  .barcell { width: 30%; }
  .bar { background: #ecd9c9; border-radius: 6px; height: 10px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); }
  .banner { background: var(--ink); color: #fff; border-radius: 12px; padding: 18px 22px; margin-top: 20px; }
  .banner .t { color: var(--accent-soft); font-size: 12px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; }
  .banner .n { font-size: 22px; font-family: Georgia, serif; margin-top: 4px; }
  .foot { margin-top: 48px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--card-line); padding-top: 16px; }
  .cols { display: grid; grid-template-columns: 2fr 1fr; gap: 28px; align-items: start; }
  .rcards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 16px; }
  .rcard { background: var(--card); border: 1px solid var(--card-line); border-radius: 12px; padding: 18px; }
  .rcard .rid { display: inline-block; background: var(--accent); color: #fff; font-weight: 700; font-size: 12px; border-radius: 999px; padding: 4px 10px; }
  .rcard h3 { font-family: Georgia, serif; margin: 12px 0 8px; font-size: 18px; }
  .rcard p { margin: 6px 0; font-size: 13px; color: var(--muted); }
  .bullets { margin: 12px 0 0; padding-left: 20px; }
  .bullets li { margin: 8px 0; font-size: 14px; }
  .section { page-break-inside: avoid; }
  @media print { .toolbar { display: none; } .wrap { padding: 0 12px; } h2 { page-break-after: avoid; } tr { page-break-inside: avoid; } }
  @media (max-width: 720px) { .cols { grid-template-columns: 1fr; } .wrap { padding: 24px; } }
`;

export function buildReportHtml(r) {
  const range =
    r.sprint_start && r.sprint_end ? `${fmtDay(r.sprint_start)} – ${fmtDay(r.sprint_end)}` : "";
  const asOfNote =
    r.as_of_date !== r.requested_date
      ? `Requested ${fmtDay(r.requested_date)} · nearest snapshot used`
      : "";

  const domainRows = r.domains
    .map(
      (d) => `<tr>
        <td>${esc(d.name)}</td>
        <td class="mono">${d.count}</td>
        <td class="mono">${d.pct}%</td>
        <td class="barcell">${bar(d.pct)}</td>
      </tr>`
    )
    .join("");

  const typeCards = r.types.map((t) => statCard(t.type, t.count, "tickets")).join("");

  const statusRows = r.statuses
    .map(
      (s) => `<tr><td>${esc(s.status)}</td><td class="mono">${s.count}</td></tr>`
    )
    .join("");

  const topContributor = r.assignees[0];
  const assigneeRows = r.assignees
    .map(
      (a, i) => `<tr>
        <td class="mono">${i + 1}</td>
        <td>${esc(a.name)}</td>
        <td class="mono">${a.total}</td>
        <td class="mono">${a.completed}</td>
        <td class="mono">${a.pct}%</td>
      </tr>`
    )
    .join("");

  const generatedOn = new Date().toLocaleDateString("en-US", {
    day: "2-digit", month: "long", year: "numeric",
  });

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Sprint Report · ${esc(r.sprint_name || "")}</title>
<style>${STYLE}</style>
</head>
<body>
  <div class="toolbar">
    <span>Anervea · Alfa Kinetic — sprint report</span>
    <button onclick="window.print()">🖨 Print / Save as PDF</button>
  </div>
  <div class="wrap">
    <div class="eyebrow">Anervea · Sprint Report</div>
    <h1>${esc(r.sprint_name || "Sprint Report")}</h1>
    <p class="sub">${esc(range)}</p>
    <p class="sub">Board as of <b>${esc(fmtDay(r.as_of_date))}</b>${asOfNote ? ` · <i>${esc(asOfNote)}</i>` : ""}</p>

    <div class="cards">
      ${statCard("Total Tickets", r.total, "on the board")}
      ${statCard("Completed", r.completed, "Done")}
      ${statCard("In Progress", r.in_progress, "active")}
      ${statCard("To Do", r.todo, "not started")}
      ${statCard("Completion", r.completion_rate + "%", "of the sprint")}
    </div>

    <h2>Work by Domain</h2>
    <table>
      <thead><tr><th>Domain</th><th>Tickets</th><th>%</th><th></th></tr></thead>
      <tbody>${domainRows || `<tr><td colspan="4">No domains</td></tr>`}</tbody>
    </table>

    <h2>Work by Type</h2>
    <div class="cards">${typeCards}</div>

    <h2>Team Performance</h2>
    ${
      topContributor
        ? `<div class="banner"><div class="t">Top Contributor</div><div class="n">${esc(
            topContributor.name
          )} · ${topContributor.total} tickets (${topContributor.completed} done)</div></div>`
        : ""
    }
    <table>
      <thead><tr><th>#</th><th>Engineer</th><th>Tickets</th><th>Completed</th><th>% Total</th></tr></thead>
      <tbody>${assigneeRows || `<tr><td colspan="5">No assignees</td></tr>`}</tbody>
    </table>

    <div class="cols">
      <div></div>
      <div>
        <h2>Status Breakdown</h2>
        <table>
          <thead><tr><th>Status</th><th>Tickets</th></tr></thead>
          <tbody>${statusRows}</tbody>
        </table>
      </div>
    </div>

    <div class="foot">
      Generated from Jira · ${esc(generatedOn)} · Confidential — not for external distribution
    </div>
  </div>
</body>
</html>`;
}

// ---- Two-sprint closure/kickoff deck: 9 sections, 1:1 with the reference PDF ----

export function buildCompareReportHtml(c) {
  const closeRange =
    c.closing.sprint_start && c.closing.sprint_end
      ? `${fmtDay(c.closing.sprint_start)} – ${fmtDay(c.closing.sprint_end)}`
      : "";
  const kickRange =
    c.kickoff.sprint_start && c.kickoff.sprint_end
      ? `${fmtDay(c.kickoff.sprint_start)} – ${fmtDay(c.kickoff.sprint_end)}`
      : "";

  const projRows = c.closing.projects
    .map(
      (p) => `<tr>
        <td>${esc(p.name)}</td>
        <td class="mono">${p.count}</td>
        <td class="mono">${p.pct}%</td>
        <td class="barcell">${bar(p.pct)}</td>
      </tr>`
    )
    .join("");
  const projCards = c.closing.projects
    .map((p) => statCard(p.name, p.count, `${p.pct}% of sprint`))
    .join("");

  const typeCards = c.kickoff.types.map((t) => statCard(t.type, t.count, "tickets")).join("");

  const top = c.closing.assignees[0];
  const teamRows = c.closing.assignees
    .map(
      (a, i) => `<tr>
        <td class="mono">${i + 1}</td>
        <td>${esc(a.name)}</td>
        <td class="mono">${a.total}</td>
        <td class="mono">${a.completed}</td>
        <td class="mono">${a.pct}%</td>
      </tr>`
    )
    .join("");

  const b = c.closing.breakdown;
  const totAssigned = b.reduce((s, x) => s + x.assigned, 0);
  const totCompleted = b.reduce((s, x) => s + x.completed, 0);
  const totIncomplete = b.reduce((s, x) => s + x.incomplete, 0);
  const rate = totAssigned ? Math.round((totCompleted / totAssigned) * 1000) / 10 : 0;
  const breakdownRows = b
    .map(
      (x) => `<tr>
        <td>${esc(x.name)}</td>
        <td class="mono">${x.assigned}</td>
        <td class="mono">${x.completed}</td>
        <td class="mono">${x.incomplete}</td>
      </tr>`
    )
    .join("");

  const doneItems = c.closing.completed_items || [];
  const doneList = doneItems
    .map((it) => `<li><b>${esc(it.key)}</b> — ${esc(it.title)} <span style="color:var(--muted)">(${esc(it.developer)})</span></li>`)
    .join("");
  const blockedItems = c.closing.blocked_items || [];
  const blockedList = blockedItems
    .map((it) => `<li><b>${esc(it.key)}</b> — ${esc(it.title)} <span style="color:var(--muted)">(${esc(it.developer)})</span></li>`)
    .join("");
  const achievements = (c.achievements || []).map((a) => `<li>${esc(a)}</li>`).join("");
  const roadblocks = (c.roadblocks || [])
    .map(
      (r) => `<div class="rcard section">
        <span class="rid">${esc(r.id || "R")}</span>
        <h3>${esc(r.concern || "Main Concern")}</h3>
        <p><b>Impact:</b> ${esc(r.impact || "")}</p>
        <p><b>Mitigation:</b> ${esc(r.mitigation || "")}</p>
        <p><b>Help needed:</b> ${esc(r.help_needed || "")}</p>
      </div>`
    )
    .join("");

  const topProject = c.closing.projects[0] ? c.closing.projects[0].name : "Nexus";
  const generatedOn = new Date().toLocaleDateString("en-US", {
    day: "2-digit", month: "long", year: "numeric",
  });

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${esc(c.project_name)} · ${esc(c.closing.sprint_name)} → ${esc(c.kickoff.sprint_name)}</title>
<style>${STYLE}</style>
</head>
<body>
  <div class="toolbar">
    <span>Anervea · ${esc(c.project_name)} — closure & kickoff</span>
    <button onclick="window.print()">🖨 Print / Save as PDF</button>
  </div>
  <div class="wrap">
    <!-- 1. Overview -->
    <div class="section">
      <div class="eyebrow">Anervea</div>
      <h1>${esc(c.project_name)}</h1>
      <p class="sub"><b>${esc(c.closing.sprint_name)}</b> closure · <b>${esc(c.kickoff.sprint_name)}</b> kickoff</p>
      <p class="sub">${esc(c.closing.sprint_name)}: ${esc(closeRange)}</p>
      <p class="sub">${esc(c.kickoff.sprint_name)}: ${esc(kickRange)}</p>
      <div class="cards">
        ${statCard("Completed", c.completed, c.closing.sprint_name)}
        ${statCard("Carry-over", c.carry_over, "into " + c.kickoff.sprint_name)}
        ${statCard("New work", c.new_work, c.kickoff.sprint_name)}
        ${statCard("Projects", c.projects_covered, "covered")}
      </div>
    </div>

    <!-- 2. Closure at a glance -->
    <h2>${esc(c.closing.sprint_name)} — Closure at a Glance</h2>
    <div class="cards">
      ${statCard("Tickets completed", c.completed, c.closing.sprint_name)}
      ${statCard("Carry-over", c.carry_over, "into " + c.kickoff.sprint_name)}
      ${statCard("New sprint work", c.new_work, c.kickoff.sprint_name)}
    </div>
    <div class="cards">${projCards || statCard("Nexus", 0, "tickets")}</div>
    <div class="banner"><div class="t">Note</div><div class="n">Team velocity: ${c.completed} tickets closed in ${esc(c.closing.sprint_name)}. ${c.carry_over} carry-overs into ${esc(c.kickoff.sprint_name)}.</div></div>

    <!-- 3. Completed work by project -->
    <h2>${esc(c.closing.sprint_name)} — Completed Work by Project</h2>
    <table>
      <thead><tr><th>Project</th><th>Tickets</th><th>%</th><th></th></tr></thead>
      <tbody>${projRows || `<tr><td colspan="4">No projects</td></tr>`}</tbody>
    </table>

    <!-- 4. Committed work (kickoff) -->
    <h2>${esc(c.kickoff.sprint_name)} — Committed Work (${c.kickoff.total} tickets)</h2>
    <div class="cards">${typeCards}</div>

    <!-- 5. Team performance -->
    <h2>Team Performance — ${esc(c.closing.sprint_name)}</h2>
    ${
      top
        ? `<div class="banner"><div class="t">Top Contributor</div><div class="n">${esc(top.name)} · ${top.completed} completed of ${top.total}</div></div>`
        : ""
    }
    <table>
      <thead><tr><th>#</th><th>Engineer</th><th>Tickets</th><th>Completed</th><th>% Total</th></tr></thead>
      <tbody>${teamRows || `<tr><td colspan="5">No assignees</td></tr>`}</tbody>
    </table>

    <!-- 6. Ticket breakdown -->
    <h2>Ticket Breakdown</h2>
    <table>
      <thead><tr><th>Team Member</th><th>Assigned</th><th>Completed</th><th>Incomplete</th></tr></thead>
      <tbody>
        ${breakdownRows}
        <tr class="total"><td>TOTAL</td><td class="mono">${totAssigned}</td><td class="mono">${totCompleted}</td><td class="mono">${totIncomplete}</td></tr>
      </tbody>
    </table>
    <div class="cards">
      ${statCard("Total assigned", totAssigned, "")}
      ${statCard("Total completed", totCompleted, "")}
      ${statCard("Total incomplete", totIncomplete, "")}
      ${statCard("Completion rate", rate + "%", "")}
    </div>

    <!-- 7. Key achievements -->
    <h2>${esc(c.closing.sprint_name)} — Key Achievements</h2>
    <div class="cards">
      ${statCard("Tickets completed", c.completed, c.closing.sprint_name)}
      ${statCard("Projects covered", c.projects_covered, topProject)}
      ${statCard("Completion", c.closing.completion_rate + "%", "of the sprint")}
    </div>
    ${achievements ? `<ul class="bullets">${achievements}</ul>` : ""}
    <h3 style="font-family:Georgia,serif;margin:18px 0 6px;font-size:16px;">Completed tickets (${doneItems.length})</h3>
    <ul class="bullets">${doneList || "<li>—</li>"}</ul>

    <!-- 8. Roadblocks and next steps (compiled from blocked tickets) -->
    <h2>Roadblocks and Next Steps</h2>
    ${roadblocks ? `<div class="rcards">${roadblocks}</div>` : ""}
    <h3 style="font-family:Georgia,serif;margin:18px 0 6px;font-size:16px;">Blocked tickets (${blockedItems.length})</h3>
    <ul class="bullets">${blockedList || "<li>None blocked 🎉</li>"}</ul>

    <!-- 9. Ending -->
    <div class="foot">
      Engineering Leadership · Engineering Team · Product Lead · CTO · QA · DevOps<br/>
      Generated from Jira · ${esc(generatedOn)} · Confidential — not for external distribution
    </div>
  </div>
</body>
</html>`;
}

// ---- Weekly QA activity deck (from /api/reports/weekly-activity) ----
export function buildWeeklyReportHtml(r) {
  const range = `${fmtDay(r.week_start)} – ${fmtDay(r.week_end)}`;
  const generatedOn = new Date().toLocaleDateString("en-US", {
    day: "2-digit", month: "long", year: "numeric",
  });

  const engineerRows = (r.engineers || [])
    .map(
      (e) => `<tr>
        <td>${esc(e.name)}</td>
        <td class="mono">${e.moved_forward}</td>
        <td class="mono">${e.sent_back}</td>
        <td class="mono">${e.blocked}</td>
      </tr>`
    )
    .join("");

  const accompRows = (r.accomplishments || [])
    .map(
      (it) => `<tr>
        <td class="mono">${esc(it.key)}</td>
        <td>${esc(it.title)}</td>
        <td>${esc(it.engineer)}</td>
      </tr>`
    )
    .join("");

  const askRows = (r.asks || [])
    .map(
      (a) => `<tr>
        <td>${esc(a.ask)}</td>
        <td>${esc(a.owner)}</td>
        <td>${esc(a.why)}</td>
        <td>${esc(a.needed_by)}</td>
      </tr>`
    )
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Weekly QA Activity · ${esc(range)}</title>
<style>${STYLE}</style>
</head>
<body>
  <div class="toolbar">
    <span>Anervea · Weekly QA Activity Report</span>
    <button onclick="window.print()">🖨 Print / Save as PDF</button>
  </div>
  <div class="wrap">
    <div class="eyebrow">Anervea · ${esc(r.project_name || "Nexus")} — Weekly QA</div>
    <h1>Weekly QA Activity Report</h1>
    <p class="sub">${esc(range)}</p>

    <div class="cards">
      ${statCard("Moved Forward", r.moved_forward, "closed / deployed / passed")}
      ${statCard("Sent Back to Dev", r.sent_back, "failed QA")}
      ${statCard("Moved to Blocked", r.blocked, "awaiting resolution")}
    </div>

    <h2>Per-Engineer Breakdown</h2>
    <table>
      <thead><tr><th>Engineer</th><th>Moved Forward</th><th>Sent Back</th><th>Blocked</th></tr></thead>
      <tbody>${engineerRows || `<tr><td colspan="4">No engineer activity this week</td></tr>`}</tbody>
    </table>

    <h2>Accomplishments</h2>
    <table>
      <thead><tr><th>Ticket</th><th>Summary</th><th>Engineer</th></tr></thead>
      <tbody>${accompRows || `<tr><td colspan="3">No tickets moved forward this week</td></tr>`}</tbody>
    </table>

    ${
      askRows
        ? `<h2>What We Need From Leadership</h2>
    <table>
      <thead><tr><th>Ask</th><th>Owner</th><th>Why It Matters</th><th>Needed By</th></tr></thead>
      <tbody>${askRows}</tbody>
    </table>`
        : ""
    }

    <div class="foot">
      Generated from Jira · ${esc(generatedOn)} · Confidential — not for external distribution
    </div>
  </div>
</body>
</html>`;
}

function openHtml(html, filename) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const win = window.open(url, "_blank");
  if (!win) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

// Open the single-sprint report in a new tab (print / save as PDF).
export function openReport(report) {
  openHtml(buildReportHtml(report), `alfa_kinetic_sprint_report_${report.as_of_date}.html`);
}

// Open the two-sprint closure/kickoff deck in a new tab.
export function openCompareReport(compare) {
  openHtml(
    buildCompareReportHtml(compare),
    `alfa_kinetic_${compare.closing.sprint_name}_vs_${compare.kickoff.sprint_name}.html`.replace(/\s+/g, "_")
  );
}

// Open the weekly QA activity deck in a new tab (print / save as PDF).
export function openWeeklyReport(report) {
  openHtml(buildWeeklyReportHtml(report), `weekly_qa_${report.week_start}.html`);
}
