import { STATUS, STATUS_ORDER, ACCENTS, bg, initials, epicCode } from "../lib.js";

// Renders one column per person, each with stats + ticket cards.
export default function Board({ people, epicColors, filtering, onSelect }) {
  if (people.length === 0) {
    return <div className="empty">No tickets match these filters.</div>;
  }
  return (
    <div className="board">
      {people.map((p, i) => {
        const acc = ACCENTS[i % ACCENTS.length];
        const active = p.tickets.filter((t) => t.status !== "Done").length;
        const mini = STATUS_ORDER.filter((s) => p.sc[s]).map((s) => (
          <span className="mb" key={s} style={{ color: STATUS[s].c, background: bg(STATUS[s].c) }}>
            {STATUS[s].ab}:{p.sc[s]}
          </span>
        ));
        return (
          <div className="column" key={p.name} style={{ "--acc": acc }}>
            <div className="col-head">
              <button className="row1 head-btn" onClick={() => onSelect?.(p.name)} title={`View ${p.name}'s movement stats`}>
                <span className="avatar" style={{ background: acc }}>{initials(p.name)}</span>
                <span className="nm">{p.name}</span>
                <span className="head-arrow">›</span>
              </button>
              <div className="stats">
                <b>{p.total}</b> tickets · <b>{active}</b> active
                {filtering && <> · <b>{p.shown}</b> shown</>}
              </div>
              <div className="mini">{mini}</div>
            </div>
            <div className="cards">
              {p.tickets.length === 0 ? (
                <div className="empty">No matching tickets</div>
              ) : p.tickets.map((t) => {
                const s = STATUS[t.status] || { c: "var(--todo)", ab: "?" };
                const epic = t.epic_name || "No Epic";
                const ec = epicColors[t.epic_name] || "var(--faint)";
                return (
                  <a className="tk" key={t.issue_key} href={t.web_url || "#"} target="_blank" rel="noreferrer">
                    <div className="l1">
                      <span className="key">{t.issue_key}</span>
                      <span className="ttl" title={t.summary}>{t.summary || "(no title)"}</span>
                    </div>
                    <div className="l2">
                      <span className="pill" style={{ color: ec, background: bg(ec) }} title={epic}>{epicCode(t.epic_name)}</span>
                      <span className="pill" style={{ color: s.c, background: bg(s.c) }}>{t.status}</span>
                      <span className="ty">{t.issue_type}</span>
                    </div>
                  </a>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
