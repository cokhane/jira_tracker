---
name: sethi-release-notes
description: >-
  Render a Jira status column as a standalone release-notes / UAT sheet — one HTML file for
  viewing and sharing, and a second whose markup survives a paste into Microsoft Outlook.
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
than becoming the fifth. Stdlib only; runs under a bare `python3` with no virtualenv.

## Run it

```bash
python3 .claude/skills/sethi-release-notes/scripts/build_release_notes.py \
  --project STH --client SETHI --version v0.0.3
```

Writes into `<client>_release_notes/` — `sethi_release_notes/` for the example above:

| File | For |
|---|---|
| `<client>-release-notes-<version>.html` | Viewing and sharing — light + dark themes, web fonts |
| `<client>-release-notes-<version>-outlook.html` | Pasting into Outlook |

Flags: `--status` (default `Deployment`), `--variant web|outlook|both`, `--out`.

There is deliberately no raw-JQL flag. The masthead states which column was released, and a
free-form query would let it name a status the run never actually asked for — a false heading
on a document someone signs.

To paste into Outlook: open the `-outlook.html` file in a browser, select all, copy, paste into
the compose window — choosing **Keep Source Formatting** if prompted.

Run the tests after touching either renderer:

```bash
python3 .claude/skills/sethi-release-notes/scripts/test_build_release_notes.py
```

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

## Why two renderers, and where the seam is

Outlook on Windows renders mail with the **Word** engine, which ignores nearly everything the web
sheet relies on: `<style>` blocks on paste, CSS custom properties, Google Fonts, `color-mix()`,
`clamp()`, `env()`, `@media` and `position: sticky`. The Outlook variant is built to a different
contract — every rule an inline `style` attribute, table layout, `bgcolor`/`cellpadding`
attributes, fonts that ship with Windows, and light-only so it does not invert unpredictably in a
dark reading pane.

**Styling is duplicated on purpose; content is not.** The `Sheet` view model settles the title,
the meta line, the band and footer wording, and the column set with its order — once, for both
renderers. Each renderer reads that and owns only markup and style, mapping a column's `Kind` to
its own presentation. So adding or reordering a column is one edit, while the two incompatible
style contracts stay apart.

Do not "simplify" this by giving the renderers a shared stylesheet or a shared template. That is
the merge that silently breaks the paste, and it is what `/code-dry`'s own "a little duplication
beats the wrong abstraction" is for. `test_both_renderers_read_the_same_column_set` guards the
content half; `test_outlook_avoids_every_construct_word_ignores` guards the style half.

## Versioning

`--version` is a label, not derived state — the operator sets it. Each run writes a new pair of
files rather than overwriting, so the output folder keeps the history of what was signed off.

## Publishing it as an artifact

The web variant publishes with the `Artifact` tool as-is. Published artifacts are **private** —
the business team cannot open the link until it is shared from the page's Share menu, so say so
when handing the link over.
