---
name: bug-triage-story
description: >-
  Turn a raw bug report — an image (UI screenshot, stack trace, Slack grab) or a text description —
  into a JIRA user story, without the operator first deciding which codebase owns it. It reads the
  input, classifies the bug as frontend / backend / both across the two SETHI repos
  (sethi_enterprise_frontend = React/Vite/TS UI, sethi_enterprise_backend = FastAPI/Python service),
  resolves the target repo(s), drafts a story in the team STORY format, files it on the JIRA board
  (project STH, issue type Story) by delegating to the jira-operator agent, and saves the story as a
  markdown file under the classified repo's docs/user-story/. A both-repo bug yields TWO cross-linked
  stories, one per repo. Use when the operator says "triage this bug", "classify this bug and make a
  story", "here's a bug — file a story", or hands over a screenshot/error to turn into a ticket.
---

# Bug triage → user story

**Goal:** Take one bug report (image or text) and, in a single pass, decide which SETHI codebase owns it, then produce a well-formed JIRA user story for that codebase — filed on the board and saved as a markdown artifact — so the operator never has to route the bug by hand.

This skill adds only the *new* logic (reading the input, classifying it, resolving the repo, writing the docs artifact). It does **not** own the story template or the JIRA-creation mechanics — those belong to `/jira-user-story`, which it reuses via the `jira-operator` agent.

---

## The two repos (how to classify)

| Repo | Identity | Owns |
|------|----------|------|
| `sethi_enterprise_frontend` | React 18 + Vite + TypeScript + shadcn/ui + TanStack Query SPA | rendering, components, routing, forms, UI state, styling, how the browser calls the API |
| `sethi_enterprise_backend` | FastAPI (Python) service — Postgres/Mongo/Redis, S3, SSO, meeting integrations, AI services | API endpoints, business logic, DB queries/migrations, auth/RBAC, AI services, data serialization |

Both share **one JIRA project: `STH`**. Repo choice is decided by the *nature* of the bug, not by the project key.

---

## Input handling

Accept any one of: an attached/pasted image, an image file path, or an inline text description.

- **Image** — read it visually with the Read tool. Extract: the observable symptom, any visible error text / HTTP status / stack trace, the screen or URL shown, and any reproduction hints.
- **Text** — read the description as given; pull the same four facts out of it.

If the input is empty or unintelligible, ask the operator for a description or a clearer image — do not guess.

---

## Procedure

### Step 1 — Classify: frontend / backend / both

State the verdict **and** a one-line reason. Heuristics:

- **Frontend** — UI screenshot; visual / layout / styling glitch; broken or blank component; client-side routing or navigation; form validation display; browser-console error; correct data rendered wrongly.
- **Backend** — API error response (5xx / 4xx JSON); Python / FastAPI stack trace; DB / query / migration error; auth or RBAC failure at the API; AI-service failure; wrong or missing data in the response payload.
- **Both** — a UI symptom whose root cause is a bad or absent API response, or a feature broken end-to-end across the client/server boundary.

If it is genuinely ambiguous after reading the input, ask **one** focused question. Otherwise proceed and note the assumption.

### Step 2 — Resolve the repo(s)

- frontend → `sethi_enterprise_frontend`
- backend → `sethi_enterprise_backend`
- both → both repos

Ground the verdict where cheap: Read/Glob the referenced screen or endpoint in the target repo to confirm the file(s) the story's **Scope** should name. Do not open a fix — this skill stops at the ticket.

### Step 3 — Draft the story

Draft it in the **exact STORY format owned by `/jira-user-story`** — do **not** re-copy that template here; open `/jira-user-story` and follow its template as the single source (header `Title / Epic / Repo / Type / Role / SP`, then User Story, Business Context, Scope, Out of Scope, Technical Context, Dependencies, Acceptance Criteria, Definition of Ready, Definition of Done, QA Test Cases, Story Points — every section, in that order, `None` where empty).

Bug-specific requirements for the draft:

- `Repo:` = the classified repo's exact name (backticked).
- **Acceptance Criteria** must include the regression guard: *"the reported symptom no longer occurs."*
- Keep it atomic: `SP ≤ 3`. If the fix is clearly more than one shippable increment, split it into separate stories.

### Step 4 — File on JIRA (reuse — do not reimplement)

Delegate creation to the **`jira-operator` agent**: intent = *user story*, raw material = the drafted story. It runs `/jira-user-story` (project `STH`, issue type **Story**, cloudId resolved at runtime, draft-then-confirm gate). Capture the returned `STH-###` key + URL.

Do not call the Atlassian MCP directly from this skill — the JIRA mechanics live in `/jira-user-story`.

### Step 5 — Save the markdown artifact

Write the finalized story — with its real `STH-###` key as the top heading — to:

```
<classified-repo>/docs/user-story/STH-###-<slug>.md
```

`<slug>` is a 3–5 word kebab-case description of the bug. Create `docs/user-story/` if it does not exist.

---

## Both-repo bugs

When the verdict is **both**, produce **two** stories — one frontend-scoped, one backend-scoped — each with its own `Repo:`, Scope, Technical Context, and Acceptance Criteria (the frontend AC covers the UI symptom; the backend AC covers the server root cause).

**Cross-link them:**

- Set each story's `Dependencies:` (and, where the operator wants a formal link, a JIRA issue link) to the other story's key.
- In each markdown file, note the sibling key near the top.

Save the frontend story under `sethi_enterprise_frontend/docs/user-story/` and the backend story under `sethi_enterprise_backend/docs/user-story/`.

Because the second story needs the first story's key to cross-link, file them in order: create story A, capture its key, create story B referencing A, then edit A to reference B.

---

## Reuse (lazy-senior-developer ladder — do not rebuild what exists)

- **`/jira-user-story`** — owns the STORY template and the `createJiraIssue` mechanics. Reference it; never duplicate its template into this file.
- **`jira-operator` agent** — the delegation path for every JIRA write. This skill classifies and writes the docs artifact; the agent files the ticket.
- **`/investigate` / `/rca`** — if the operator wants the *root cause* traced before a story is written, hand off there first, then return here with the findings.

---

## Rules

- Classify first, and always state the reason for the verdict — never file a story before the repo is resolved.
- Stop at the ticket. This skill never opens a branch or writes a fix (that's `/jira-implement` / `/bug-fix`).
- One story = one shippable increment (`SP ≤ 3`); split anything larger.
- Never invent epic links, assignees, or a ticket key — only set what's given or returned by `/jira-user-story`.
- Respect the draft-then-confirm gate: filing a JIRA issue is outward-facing, so confirm the draft unless the operator already said "file it".
- The markdown artifact carries the real `STH-###` key; write it only after the ticket is created.
