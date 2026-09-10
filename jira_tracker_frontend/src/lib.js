// Status display: color + short badge, in board order.
export const STATUS = {
  "Blocked":     { c: "var(--block)",  ab: "BL" },
  "In Progress": { c: "var(--prog)",   ab: "IP" },
  "Code Review": { c: "var(--review)", ab: "CR" },
  "QA Testing":  { c: "var(--qa)",     ab: "QA" },
  "To Do":       { c: "var(--todo)",   ab: "TD" },
  "Deployment":  { c: "var(--deploy)", ab: "DEP" },
  "Merged":      { c: "var(--merged)", ab: "MG" },
  "Done":        { c: "var(--done)",   ab: "DN" },
};
export const STATUS_ORDER = ["Blocked", "In Progress", "Code Review", "QA Testing", "To Do", "Deployment", "Merged", "Done"];

// Palette cycled across people and epics.
export const ACCENTS = ["#E5A93C", "#B07CE6", "#EC5B52", "#39B5C9", "#3FB57C", "#4F8DF0", "#4FD2C2", "#E37BB0", "#8A99B8"];

// Faint translucent background derived from any CSS color.
export const bg = (c) => `color-mix(in srgb, ${c} 15%, transparent)`;

export const initials = (name) =>
  (name || "?").split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

// Short epic code: acronym for multi-word, first 3 letters otherwise.
export function epicCode(name) {
  if (!name) return "—";
  const words = name.trim().split(/\s+/);
  if (words.length > 1) return words.slice(0, 3).map((w) => w[0]).join("").toUpperCase();
  return name.slice(0, 3).toUpperCase();
}

// Stable color per epic name (by its index in the sorted epic list).
export function colorMap(names) {
  const m = {};
  names.forEach((n, i) => { m[n] = ACCENTS[i % ACCENTS.length]; });
  return m;
}
