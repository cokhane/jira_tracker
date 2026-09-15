---
name: git-list-merge-pr
description: >-
  Generate a weekly merged-PR report across the team's four repos (sethi_enterprise_frontend,
  sethi_enterprise_backend, nexus_api, nexus_panel_frontend), grouped by repository then by developer,
  with each PR's commits bundled underneath. The window is NOT a plain Mon–Sun week: it opens at the
  PREVIOUS week's Thursday 18:00 (+08:00) — the last report's cutoff — and closes at the current
  Sunday 23:59:59. Defaults to MERGED-only (OPEN and CLOSED PRs dropped).
  Use when the operator says "list merged PRs this week", "weekly PR report", "PRs by developer",
  "git-list-merge-pr", or wants a per-developer breakdown of what shipped across the repos. Delegates
  the raw `gh` collection to the git-operator subagent (read-only), formats the digest, and ALWAYS
  ends by persisting the run to the PR store (jira_tracker_backend `data/prs.db`) so each week
  becomes queryable history rather than a scratchpad file.
---

# Git List Merge PR — weekly per-developer PR report

**Goal:** Produce a clean report of pull requests active in the reporting window (Step 1 — previous
Thursday 18:00 through the current Sunday), across the four team repos,
grouped **by repository → by developer**, each PR line-itemed, with commits bundled per PR. The
default deliverable is **MERGED-only** (OPEN/CLOSED removed), but the raw pass collects all states so
the operator can ask for a wider or narrower view.

This skill mirrors the exact steps below — follow them in order.

> **Where this file lives — edit THIS one.** The canonical SKILL.md is
> `jira_tracker_backend/.claude/skills/git-list-merge-pr/SKILL.md`, in the repo it writes to
> (Step 6 calls that repo's `scripts/ingest_merged_prs.py`, `.venv` and `data/prs.db`).
> `~/.claude/skills/git-list-merge-pr/SKILL.md` is a **symlink** to it, so both the scoped
> (`jira_tracker_backend:git-list-merge-pr`) and unscoped names resolve to one file.
> **Never replace that symlink with a copy.** Two copies is exactly how a stale version carrying
> the truncating `gh pr list --limit 200` collection ended up shadowing the fixed one — the
> command still succeeds, so the resulting under-count is invisible.

---

## The four repositories

| Short | Repo | Known local checkout |
|-------|------|----------------------|
| sef | `sethi_enterprise_frontend` | `/Users/axeeeeee/Documents/work/sethi_enterprise_frontend` |
| seb | `sethi_enterprise_backend`  | `/Users/axeeeeee/Documents/work/sethi_enterprise_backend` |
| nexus_api | `nexus_api`            | `/Users/axeeeeee/Documents/work/nexus_api` |
| nexus_panel | `nexus_panel_frontend` | find under `/Users/axeeeeee/Documents/work/` or use the GitHub remote |

All are under the `Anervea-AI` GitHub org. `gh` must be installed and authenticated (`gh --version`,
`gh auth status`).

---

## Step 1 — Resolve the reporting window

The window is **not** a plain Monday–Sunday week. The report is cut on a **Thursday 18:00** cadence,
so the window opens at the previous report's cutoff — **the Thursday of the PREVIOUS week at 18:00,
local time (UTC+08:00)** — and closes at the **end of the current week's Sunday**. That leading
Thursday-evening → Sunday tail is work that landed after the last report closed; without it, those
PRs fall through the gap and appear in no report at all.

| Bound | Definition | Local (UTC+08:00) |
|-------|------------|-------------------|
| Start | Monday of the current week **− 4 days** (= previous week's Thursday), at 18:00 | `<Thu>T18:00:00+08:00` |
| End   | Monday of the current week **+ 6 days** (= current Sunday), at 23:59:59 | `<Sun>T23:59:59+08:00` |

**Worked example** — today `2026-08-13` (Thursday); current week is Mon `2026-08-10` – Sun `2026-08-16`:

- Start `2026-08-06 18:00 +08:00` → `2026-08-06T10:00:00Z`
- End   `2026-08-16 23:59:59 +08:00` → `2026-08-16T15:59:59Z`
- Days covered: **6 (from 6pm), 7, 8, 9, 10, 11, 12, 13, 14, 15, 16**

**Compute it — never hand-count the dates:**

```bash
DOW=$(date +%u)                                    # 1=Mon … 7=Sun
MON=$(date -v-$((DOW-1))d +%Y-%m-%d)               # Monday of the current week
START_L="$(date -j -f %Y-%m-%d -v-4d "$MON" +%Y-%m-%d)T18:00:00"
END_L="$(date -j -f %Y-%m-%d -v+6d "$MON" +%Y-%m-%d)T23:59:59"
START_Z=$(date -j -u -f "%Y-%m-%dT%H:%M:%S %z" "$START_L +0800" +%Y-%m-%dT%H:%M:%SZ)
END_Z=$(date -j -u -f "%Y-%m-%dT%H:%M:%S %z" "$END_L +0800" +%Y-%m-%dT%H:%M:%SZ)
echo "$START_L+08:00 -> $END_L+08:00   (UTC: $START_Z -> $END_Z)"
```

(BSD/macOS `date`. Note the `+0800` offset is parsed **without** a colon — `+08:00` fails `%z`.)

The **Thursday-18:00 anchor is fixed** — do not shift it per run, and do not fall back to Monday
00:00. The operator can still override the whole window by naming an explicit range ("last week",
"Aug 1–7"); such an override replaces **both** bounds.

State the resolved window — both bounds, with timezone — in the output.

---

## Step 2 — Delegate the collection to the git-operator subagent (read-only)

Spawn the **git-operator** agent with an explicit **read-only, collect-and-report** instruction (no
mutations). It runs, per repo:

```bash
# Union three date-range searches, so nothing falls off a single page (see the warning below)
for q in "created:<START>..<END>" "updated:<START>..<END>" "merged:<START>..<END>"; do
  gh pr list --repo Anervea-AI/<repo> --state all --limit 500 --search "$q" \
    --json number,title,author,createdAt,updatedAt,mergedAt,state,url
done

# Per PR, pull its commits
gh pr view <number> --repo Anervea-AI/<repo> --json commits
```

> **NEVER collect with a bare `gh pr list --limit 200`.** These repos are far larger than one page —
> `nexus_api` alone carries ~2,700 PRs — so a flat listing returns the 200 most recent and silently
> discards every older PR that was merged or updated inside the window. This is not hypothetical: the
> 2026-08-06→16 run under-counted by 10 merged PRs (`nexus_api` reported 139 instead of 149) and the
> loss is invisible — the command succeeds and the report looks complete. Drive the collection from
> the date range instead, union the three searches, then apply the exact `START_Z`/`END_Z` filter.

"Active in the window" = `createdAt` **or** `updatedAt` **or** `mergedAt` falls inside the Step 1
window (previous-Thursday 18:00 → current Sunday 23:59:59, +08:00). Compare in UTC against the
`START_Z`/`END_Z` bounds — the `gh` timestamps are UTC, so a naive date-only compare silently drops
the Thursday 18:00–24:00 slice, which is precisely the slice this window exists to capture.
(Note: `updatedAt` inflates counts by catching rebase/label touches — if the operator wants a stricter
view, re-filter on **created-or-merged only**.)

Tell the agent to write the full unabridged data (every PR, every commit) to a scratchpad file and
report the path back, so formatting in later steps never needs a second `gh` pass.

**Require TWO output files** — the markdown digest for formatting, and a JSON file for Step 6's
database ingest. The JSON keeps `gh`'s own field names, so the agent dumps what it already has:

```json
{"window": {"start": "<START_Z>", "end": "<END_Z>"},
 "prs": [{"repo": "nexus_api", "number": 2835, "title": "NEX-2060 : ...",
          "author": {"login": "Alfa-Axe"}, "state": "MERGED",
          "createdAt": "<isoZ>", "mergedAt": "<isoZ or null>",
          "url": "https://github.com/Anervea-AI/nexus_api/pull/2835",
          "commitCount": 16,
          "commits": [{"sha": "39a9de9", "subject": "feat(news_02): ..."}]}]}
```

`commitCount` is required and is the authoritative number — env-sync PRs and any PR past GitHub's
100-commit listing cap carry a count with a short (or empty) `commits` array, so the count must not
be re-derived from the array's length. Do NOT filter the JSON by state or window: hand over every PR
collected, and let Step 6 decide what to keep.

---

## Step 3 — Bundle commits per PR

For each PR keep: `#number`, `[STATE]`, title, URL, and the list of its commits (short SHA + subject).
Group PRs under their **author** (GitHub login, e.g. `Alfa-Axe`, `alfa-muskan`, `anervea-mark`), and
group authors under their **repository**.

**Environment-sync PRs** ("Develop to staging", "Develop" merge PRs in the two SETHI repos) roll up
commits already listed under the individual feature PRs. Collapse them to a one-line summary with just
the commit count — do NOT repeat their commits — to avoid hundreds of duplicate lines.

---

## Step 4 — Format the report

Layout, in this order:

```
# <Repo full name>

### <Developer login> — <N> PRs
- #<num> [<STATE>] <title>
  <url>  (commits: <k>)
    - <shortsha> <commit subject>
    - ...
```

- Group by **repository** (top-level heading), then by **developer** (sub-heading) with a PR count.
- List every PR as a line item; bundle its commits indented beneath.
- Collapse env-sync PRs to a single summary line (see Step 3).

For a **PR-only** view (no commits) — which is often what's wanted — extract just the structure lines
from the scratchpad file instead of re-querying:

```bash
grep -E '^(=== |### |- PR #)' <scratchpad-report-file>
```

---

## Step 4.5 — Apply the developer allowlist

**The report tracks only these seven developers.** Everyone else is out of scope:

| GitHub login | Name | Jira display name (verbatim) |
|--------------|------|------------------------------|
| `Alfa-Jc` | John Carlo Mandawe | `John Mandawe` |
| `Alfa-Dan` | Dan Denver De Leon | `Dan Denver De Leon` |
| `Alfa-Axe` | Rhidzkhan Ahmad | `rhidzkhan ahmad` |
| `Alfa-Deinielle` | Deinielle Cruz | `Deinielle Cruz` |
| `Alfa-Rudolf` | Dan Perez (= "Dan Rudolf" in Jira — same person) | `Dan Rudolf` |
| `alfa-muskan` | Muskan Dawar | `Muskan Dawar` |
| `Alfa-Roselle` | Roselle Tabuena | `Roselle.Tabuena` |

Match logins **case-insensitively** — GitHub casing is inconsistent across this team (`Alfa-Jc` not
`Alfa-JC`, `alfa-muskan` not `Alfa-muskan`), and an exact-match allowlist silently drops the ones
that differ.

### The three naming systems — never join people by name

The **GitHub login** is what PRs carry, the **Jira display name** is what `issues.assignee` /
`report_assignees` carry, and the middle column is the human's actual name. They are NOT the same
string, and only **3 of the 7** (`Alfa-Dan`, `Alfa-Deinielle`, `alfa-muskan`) are identical across
all three. The Jira column above is the exact string in `nexus.db` / `sethi.db` — verified against
`SELECT DISTINCT assignee FROM issues`, not transcribed by hand — because each differs in its own
way: `rhidzkhan ahmad` is lower-case (and `projects.yaml` says keep it verbatim), `John Mandawe`
drops the middle name, and `Roselle.Tabuena` uses a dot where her name has a space.

**So do not match a developer between the two stores by name — a naive exact join drops four of the
seven silently.** Use the **ticket key** (`STH-935`, `NEX-2060`) parsed out of the PR title; that is
why `merged_prs.jira_key` exists (Step 6) and why it, not a name, is the join to the Jira tables.

**`Alfa-Rudolf` — "Dan Perez" and "Dan Rudolf" are the SAME PERSON** (confirmed by the operator,
2026-08-27). Both strings are correct and both stay: *Dan Perez* is the name, *Dan Rudolf* is what
Jira displays and what NEX `report_assignees` matches on. **Do not "reconcile" them by editing either
one** — changing the Jira column breaks the roster match, and changing the name column loses the
person's actual name.

**There are still two different Dans**, so never merge them: `Alfa-Dan` is *Dan Denver De Leon*
(nexus_panel_frontend), `Alfa-Rudolf` is *Dan Perez / Dan Rudolf*. Three name-strings, two people.

**Never drop an allowlisted name silently.** If a name on this list authored no PR in the window,
say so explicitly — "authored no PR in this window" is a finding, not an empty result. Every failure
mode here is one this report has already hit, in the 2026-08-06→16 run: `Alfa-Denielle` was a typo
for `Alfa-Deinielle` and hid Deinielle Cruz entirely; `Alfa-Rudolf` (Dan Perez) authored nothing in
any of the four repos, which is worth reporting rather than swallowing; and `Alfa-Dan` was left off
an earlier allowlist, silently removing 27 merged PRs. The same omission hit `Alfa-Roselle` (Roselle
Tabuena) in the 2026-08-20→30 run — she was missing from the list entirely, so her 4 merged
`sethi_enterprise_backend` Lambda-conversion PRs were dropped into the "excluded authors" note and
only surfaced because the operator asked for her by name. **A login absent from this table is
indistinguishable from an untracked outsider**, so when a new developer joins the team, add them here
in the same change that onboards them.

The operator can widen this at any time ("all developers", "include anervea-mark") — the allowlist is
the default, not a hard limit. Pass it downstream verbatim:

```bash
build_worklog_xlsx.py ... --only "Alfa-Jc,Alfa-Dan,Alfa-Axe,Alfa-Deinielle,Alfa-Rudolf,alfa-muskan,Alfa-Roselle"
```

That generator also takes `--exclude "<logins>"` for the inverse (drop a few, keep the rest), and
warns on any name in either filter that matched nobody.

---

## Step 5 — Apply the state filter (default: MERGED-only)

**Default deliverable: drop every OPEN and CLOSED PR — keep only `[MERGED]`.** Recompute each
developer's PR count after filtering, and **omit any developer left with zero merged PRs** (call them
out in a closing note: "X dropped off — all their PRs this week were OPEN/CLOSED").

If the operator asks for all states, or open-only, or closed-only, filter accordingly instead.

---

## Step 6 — Persist the run to the PR store (ALWAYS, every run)

**Every run of this skill ends by writing its collection to the database.** The scratchpad file dies
with the session; the store is what makes week-over-week history possible, and it is what stops each
week's report from being rebuilt from nothing. This step is not optional and needs no asking about.

```bash
cd /Users/axeeeeee/anervea/jira_tracker/version_2/jira_tracker_backend
.venv/bin/python scripts/ingest_merged_prs.py \
  --json <scratchpad>/prs-<START>-<END>.json \
  --window-start "$START_Z" --window-end "$END_Z"
```

The script chdirs to the backend root itself, so any cwd works — but it must run under that repo's
`.venv/bin/python` (SQLAlchemy + pydantic-settings live there). Expect:

```
OK stored 208/256 PRs (+208 new, ~0 updated, 1834 commits) -> data/prs.db run_id=1
```

- **Where it lands:** `data/prs.db` — ONE cross-repo SQLite file, deliberately separate from the
  per-board `nexus.db` / `sethi.db`, because a PR belongs to a repo and every weekly report spans
  all four repos at once. Tables: `merged_prs`, `pr_commits`, `pr_ingest_runs` (`app/pr_models.py`).
- **It is idempotent.** PRs are keyed `(repo, number)` and commits `(repo, pr_number, sha)`, so
  re-running the same week updates in place instead of doubling it. Safe to re-run after a
  re-collect — a second pass on an unchanged file reports `+0 new, ~208 updated, 0 commits`.
- **Nothing is window-filtered at ingest.** Every PR is stored with its real `merged_at`, so the
  window stays a `BETWEEN` at query time. `--state MERGED` is the default; `--state ""` stores
  OPEN and CLOSED too.
- **Derived columns come free:** `board` (NEX/STH, from each board's `github_repos:` in
  projects.yaml), `jira_key` parsed out of the title, and `is_env_sync` matched against
  `pr_env_sync_titles` in app/config.py — which catches promotions the collector's own tagging
  misses (e.g. "chore(release): promote staging → uat"). A `WARNING unmapped repos` line means a
  repo is missing from a board's `github_repos:` — fix the YAML, never ignore it.
- **`--dry-run`** reports the counts and writes nothing.

Because `merged_at` is stored verbatim, the store settles the loose-vs-strict question the report
itself cannot. "What actually shipped this week" is a query, not a re-collection:

```sql
SELECT author, COUNT(*) AS prs, SUM(NOT is_env_sync) AS substantive
  FROM merged_prs
 WHERE merged_at BETWEEN '2026-08-20 10:00:00' AND '2026-08-30 15:59:59'
 GROUP BY author ORDER BY prs DESC;
```

That distinction is not academic: in the 2026-08-20→30 window, `created OR updated OR merged`
returned 120 PRs but only **100** had actually merged inside it — 20 belonged to the previous
report, 13 of them one developer's.

---

## Output checklist

- [ ] Window stated explicitly — both bounds with timezone, starting at the previous week's
      Thursday 18:00 (+08:00), not Monday 00:00.
- [ ] All four repos covered (or any that couldn't be reached called out explicitly — never guessed).
- [ ] Collection driven by date-range search, NOT a bare `--limit` page (which truncates silently).
- [ ] Developer allowlist applied (case-insensitive); any allowlisted name with no PRs called out.
- [ ] Grouped repository → developer, each with a PR count.
- [ ] Every PR line-itemed; commits bundled per PR (unless PR-only view requested).
- [ ] Env-sync "Develop to staging" PRs collapsed to a count line.
- [ ] State filter applied — MERGED-only by default; zero-merged developers omitted with a note.
- [ ] Read-only throughout — no branches, commits, or pushes.
- [ ] Collector wrote BOTH files — the markdown digest AND the Step 6 JSON (with `commitCount`).
- [ ] **Step 6 ran** — `scripts/ingest_merged_prs.py` reported `OK stored …  -> data/prs.db`, and
      any `WARNING unmapped repos` line was resolved rather than ignored.
