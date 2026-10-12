---
name: sethi-release-notes
description: >-
  Render a Jira status column as a release-notes / UAT sign-off package — an HTML sheet for
  viewing and sharing, a second whose markup survives a paste into Microsoft Outlook, and an
  .xlsx the business team fills in, with a Yes/No/On Hold dropdown and Jira hyperlinks. Each
  carries a generated covering message naming the version, the ticket count and the sign-off
  columns, so the note can never contradict the table under it.
  Use when the operator says "release notes", "deployment sheet", "UAT sign-off sheet",
  "what's ready to deploy", "make the release notes for STH", "release notes I can paste
  into Outlook", or asks to refresh an existing versioned sheet. Reads Jira through the REST
  API with the machine's Atlassian API token — never the MCP connector, and never the local
  tracker DBs, which go stale silently. Read-only against Jira; its only writes are the
  output files.
---

# Sethi release notes

Produces a sheet listing every ticket sitting in one Jira status column, addressed to the
business team who sign the release off rather than to the developers who built it.

- [scripts/build_release_notes.py](scripts/build_release_notes.py) — rendering and CLI only
- [scripts/test_build_release_notes.py](scripts/test_build_release_notes.py) — offline tests

Jira access is delegated whole to [/jira-scripts](../jira-scripts/scripts/jira_api.py), which
owns auth, retries, error shape, JQL escaping and the proven-exhaustive search. That file exists
because four copies of a Jira client had already drifted apart — this skill consumes it rather
than becoming the fifth. The HTML variants are stdlib only; the workbook needs `openpyxl`, which
three sibling skills in this repo already depend on.

## Run it

```bash
python3 .claude/skills/sethi-release-notes/scripts/build_release_notes.py \
  --project STH --client SETHI --version v0.0.3
```

Writes into `<client>_release_notes/<version>/` — `sethi_release_notes/v0-0-3/` for the
example above. **Every version gets its own folder**, so one release's sheets never sit loose
beside another's:

| File | For |
|---|---|
| `<client>-release-notes-<version>.html` | Viewing and sharing — light + dark themes, web fonts |
| `<client>-release-notes-<version>-outlook.html` | Pasting into Outlook |
| `<client>-release-notes-<version>.xlsx` | The copy reviewers fill in and send back |

Flags: `--status` (default `Deployment`), `--variant web|outlook|xlsx|all` (default `all`),
`--from` (who signs the covering note), `--out`.

There is deliberately no raw-JQL flag. The masthead states which column was released, and a
free-form query would let it name a status the run never actually asked for — a false heading
on a document someone signs.

To paste into Outlook: open the `-outlook.html` file in a browser, select all, copy, paste into
the compose window — choosing **Keep Source Formatting** if prompted.

Run the tests after touching either renderer:

```bash
python3 .claude/skills/sethi-release-notes/scripts/test_build_release_notes.py
```

## The covering message

Every sheet carries the note that goes out with it, above the table in both HTML variants and on
its own tab in the workbook. It is **generated, never typed**, because every fact in it is already
settled by the run — the client, the version, the ticket count, the status column, the two sign-off
column headers and the exact words the dropdown accepts. A covering note is the one part of the
package a reader trusts without checking, so a hand-typed count that has drifted from the table
under it is the worst defect this skill could ship.

It is signed by `--from`, defaulting to your git user — `Alfa-Axe` becomes `Axe` — and falling back
to the Jira display name.

One conditional: the sentence promising the attached spreadsheet appears **only** on a run that
actually writes one. `--variant web` produces a note that does not mention an attachment, because a
note promising a file that is not there sends the reviewer looking for it.

## The two sign-off columns

`Business Team Sign Off` and `Can this be deployed?` ship **empty** on every row — they are what the
reviewer fills in, and the sheet must never arrive looking as though someone already answered for
them. In the workbook the decision column is a **dropdown** (`Yes` / `No` / `On Hold`) with colour
rules, not free text: a column that accepts "yes pls" and "Y" alongside "Yes" cannot be counted
without a human re-reading all of it.

The dropdown finds its column by `Kind`, never by a hardcoded index, so reordering the columns in
`build_sheet` moves the validation with them. A validation left behind on a stale index is
invisible until a reviewer meets it.

## The four rules this skill exists to hold

**1. REST API with the machine's token. Never the MCP connector.** `resolve_credentials` takes a
complete pair from one source — the `ATLASSIAN_*` pair, else the `JIRA_*` pair, else
`jira_tracker_backend/.env` — because an email from one source with a token from another names an
account belonging to neither. The run prints the account it acts as before doing any work.
**A 401 is a blocker to report, not a reason to fall back**: the connector has switched Atlassian
accounts mid-session, which is unrepairable once a comment is authored. See
`rules/jira-rest-api-token.md`.

**2. Never read `sethi.db` / `nexus.db`.** When the tracker's token lapses, its syncs log
`success` while writing nothing, so the DBs go stale with no visible symptom. A sheet built from
them looks authoritative and is wrong. Always live REST.

**3. Census, not sample.** `search_all` may only stop on the server's own `isLast`. Running out
of `nextPageToken` without it is a truncated read and raises, because a short page looks exactly
like a complete result and a release sheet missing rows is worse than no sheet at all. Note this
is a hard proof, not a count comparison — `approximate-count` is approximate by name and would
false-positive whenever a ticket moves between two calls.

**4. Every row carries its own Status.** No flag to switch it off. The masthead already names the
column being released, but a heading is not a per-row guarantee: these sheets get filtered,
re-sorted and pasted into mail, where the heading parts company with the rows underneath it.

## Why three renderers, and where the seam is

Outlook on Windows renders mail with the **Word** engine, which ignores nearly everything the web
sheet relies on: `<style>` blocks on paste, CSS custom properties, Google Fonts, `color-mix()`,
`clamp()`, `env()`, `@media` and `position: sticky`. The Outlook variant is built to a different
contract — every rule an inline `style` attribute, table layout, `bgcolor`/`cellpadding`
attributes, fonts that ship with Windows, and light-only so it does not invert unpredictably in a
dark reading pane.

The workbook is a third contract again — not markup at all, and the only one that is *written into*
rather than read.

**Styling is duplicated on purpose; content is not.** The `Sheet` view model settles the title, the
meta line, the band and footer wording, the covering message, and the column set with its order —
once, for all three renderers. Each reads that and owns only presentation, mapping a column's `Kind`
to its own: a CSS class, an inline `style`, or a column width and fill. So adding or reordering a
column is one edit, while the three incompatible contracts stay apart.

Do not "simplify" this by giving the renderers a shared stylesheet or a shared template. That is
the merge that silently breaks the paste, and it is what `/code-dry`'s own "a little duplication
beats the wrong abstraction" is for. `test_both_renderers_read_the_same_column_set` guards the
content half; `test_outlook_avoids_every_construct_word_ignores` guards the style half.

## Versioning

`--version` is a label, not derived state — the operator sets it. Each run writes into its own
`<version>/` folder rather than overwriting, so the output folder keeps the history of what was
signed off, one release per directory.

Both the client and the version go through `slug()` on the way to a path — `v0.0.4` becomes
`v0-0-4`, matching the filenames inside it — because `--version` reaches a directory name and a
raw `../..` would walk straight out of the output folder.

## Publishing it as an artifact

The web variant publishes with the `Artifact` tool as-is. Published artifacts are **private** —
the business team cannot open the link until it is shared from the page's Share menu, so say so
when handing the link over.
