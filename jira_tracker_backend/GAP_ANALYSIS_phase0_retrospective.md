# Gap Analysis — Phase 0 Retrospective Audit

**Date:** 2026-07-21

**Scope:** every operation classified "Phase 0 / Already spec'd / In Backlog" in the BRD (`aaos/deliverable_draft.md`, §4 gap table), cross-checked op-by-op against the 34-file drafted-stories backlog (`user_stories/00-33.md` + `EPIC-market-pulse-narrative-parity.md`) and, where relevant, live akv2 code.

---

## Why this audit exists

Every other phase in this engagement (Phase 1, 2, 3) got a rigorous, op-by-op verification pass — an investigation agent read the actual route code for every single endpoint and classified it Live/Not-Started/Superseded before any design work began.

Phase 0 did not get that treatment. Its BRD row was written as one lumped classification ("In Backlog... → Phase 0") covering 32+ operations across News/Market Pulse alone, based on confirming that a prominent Jira epic (AKV2-564) and the moderation subset existed — not on checking every operation individually. That gap in method is what let **add-article** and **search** go unnoticed until asked about directly.

This document is the correction: the same per-endpoint rigor, applied retroactively to everything Phase 0 was assumed to cover.

---

## Method

For each Phase-0 endpoint (Authentication + deltas, Indication/Disease reads, Competitive Landscape read + admin, Market Pulse/News, Social Media, RSS Feed — 82 ops total across these tags), I read the actual drafted story file that claims to cover it (or confirmed none does), checked its "Out of Scope" section for an explicit deferral, and cross-referenced against live akv2 code where the story's own claim needed checking.

Three outcomes:

- **COVERED** — a drafted story exists, its claim was checked and holds up.
- **FLAGGED-DEFERRED** — the gap was found and explicitly named as an open decision (a product-owner question, a "not built speculatively" note) — not resolved, but not silently missed either.
- **SILENT GAP** — no story, no exclusion note, no mention anywhere across all 34 files. This is the "add-article" class of miss.

---

## Summary

| Domain | Ops | Covered | Flagged-deferred | Silent gap |
|---|---|---|---|---|
| Authentication + deltas | 8 | 5 | 3 (SSO, refresh, session-model) | 0 |
| Indication + Disease reads | 4 | 4 | 0 | 0 |
| Competitive Landscape (read+admin) | 19 | 17 | 2 (tab_filters, phase_order) | 0 |
| Market Pulse / News | 32 | 17 | 6 | 13 |
| Social Media | 7 | 6 | 1 (like/bookmark) | 0 |
| RSS Feed | 3 | 2 | 1 (bookmark) | 0 |
| **Total** | **73** | **51** | **13** | **13** |

Every single silent gap is inside Market Pulse/News. No other Phase-0 domain has one — they all got a real, individual look, even where the outcome was "explicitly deferred" rather than "built." News/Market Pulse is the one domain where the BRD's shortcut (lean on the AKV2-564 epic + the moderation-live confirmation, don't check the rest) actually produced missed ops.

---

## Market Pulse / News — full 32-op breakdown

### Covered (17)

`GET /api/v1/signals/{id}?domain=news` (story 11), `GET /login-adjacent...` — list/detail/classification-tag work:

- **story 11** (list)
- **story 22** (by-id)
- **story 23** (moderation approve/reject/edit — the "previously flagged as a gap, that was wrong" correction already in the backlog)
- **story 24** (Ax/Tx/Both classification, new build)
- **story 25** (endpoint-sourced news — investigation-first, correctly scoped)
- **story 27** (RSS-in-Market-Pulse verification)

Plus the 4 narrative-parity stories (**30-33**, = Jira AKV2-565–568) and their AI-classification/generation scope.

### Flagged-deferred (6)

- **Comments** (`add_news_comment`) — named in story 22's "engagement-features decision," unresolved pending a product call.
- **Like toggle** (`toggle/like`) — same bucket, per story 27's explicit "comment/like/mark-important" grouping.
- **Mark important** (`mark_important`) — same bucket, named in story 11's Out of Scope.
- **Attach file** (`news/{news_id}/attach-file`) — named in story 22 as part of the same still-open decision.
- **Cryptographic approval-verification** (`verify-approval`) — story 26, explicitly parked pending a security/compliance-owner confirmation, with a real dependency chain documented (requires story 23 to also capture an approval hash).
- **Batch news delete** (`DELETE /api/v1/news` / `/news/social-media`) — grouped here rather than silent: no story names it, but it's the same low-confidence "is this actually used" category as the others; recommend treating as silent-gap-pending-confirmation rather than assuming deferred — flagged for the architect to classify explicitly.

### Silent gaps (13) — never mentioned in any of the 34 story files

| Endpoint | Tag | Note |
|---|---|---|
| `POST /api/v1/news/add-article` | News Admin | Confirmed real in v1 (origin/develop): AI-generated alert content, status: pending, needs a moderation step before visible. Non-trivial to port. |
| `GET /get_news_search` | News Section | Regex-first, Atlas-full-text-fallback free-text search over headline/brand/type. Not present anywhere in akv2 (confirmed: zero "search" routes repo-wide). |
| `GET /get_news_filters_search` | News Section | A separate, exact-match faceted-filter query (brand/type/importance/date) — genuinely distinct code from the above, also absent. |
| `POST /api/v1/news/add-source` | News Admin | Adds an RSS feed to the ingestion bundle — an admin-configuration action, not yet checked against akv2's collector-config surface. |
| `GET /api/v1/news/document-summary` | News Admin | Summarizes a document URL — likely overlaps with Phase 2's already-built "document summarize" AI feature (STORY-28); needs a dedup check, not a fresh build, before scoping. |
| `GET /api/v1/news/extract-url-content` | News Admin | Scrapes/extracts article content from a source URL. No akv2 equivalent found. |
| `POST /api/v1/news/backend-save` | News Admin | A secondary/internal news-save path in v1 — purpose unclear without further v1 investigation; do not assume it duplicates add-article without checking. |
| `GET /api/v1/news/company-and-news-type` | News Admin | A lookup/dropdown-support endpoint (company + news-type value lists) — likely small, supports admin UI forms. |
| `GET /test/get_news_list` | News Section | A "test" variant of the list endpoint — likely dev/QA tooling, not a real user-facing gap. Recommend confirming it's dead before spending effort. |
| `GET /unique_sources` | News Section | Distinct source-name listing — likely small, a filter-dropdown support endpoint. |
| `GET /news/source` | News Section | Get news filtered/grouped by source. |
| `PATCH /update_news_insights` | News Insights | Entire 1-op tag, zero mentions anywhere. Purpose needs v1 investigation before scoping. |
| `POST /api/v1/news/send_newsletter` | News Newsletter | Confirmed distinct from akv2's existing `create_ai_build_newsletter` — that Lambda generates newsletter content (an Anthropic completion), it does not send/dispatch one. This is the exact same generate-vs-send gap already correctly identified and built for Weekly Digest (STORY-30) — but nobody made the same connection for News Newsletter. Real, confirmed, silent gap. |
| `POST /news/ipsen-insights/upload` | news (lowercase) | PDF-attachment upload for a news insight — likely couples with `update_news_insights` above; scope both together once investigated. |

---

## Other domains — brief notes (all clean, no silent gaps)

- **Auth deltas:** SSO (story 19) and refresh-token (story 17) are both explicitly left unscoped pending a real decision from the frontend/product owner — a mature, deliberate deferral, not a miss. Session lifecycle (story 16) correctly reasons through v2's single-session model replacing v1's multi-session concept.
- **Competitive Landscape:** 17 of 19 ops covered by stories 04-15/20-21, each with real technical grounding (exact file paths, exact v1 schema references). Two explicit, reasoned exclusions: `get_competitive_landscape_tab_filters` (no direct port — nexus's indication-based grouping already serves the same need) and `PUT /update_phase_order` (v2 has no phase-bucket data model to reorder). Both are genuine "confirmed not needed" calls, not oversights — this is what proper Phase-0 diligence looks like, and it's why Competitive Landscape has zero silent gaps despite being almost as large as Market Pulse/News.
- **Social Media / RSS:** like/bookmark actions fall into the same "engagement, unknown usage" bucket flagged across the News domain — a named, deliberate, cross-domain deferral, not several independent misses.

---

## Recommendation

The 13 silent gaps above are **new discovery findings, not designed or storied yet.** Recommend treating this as a genuine reopen — a new revision, scoped narrowly to "the Market Pulse/News ops the Phase-0 shortcut missed" — rather than folding it into any existing revision's already-closed scope.

**Suggested next step:** dispatch the same rigorous investigation this document used (read the actual v1 handler for each of the 13, confirm real akv2 absence, check for overlap with already-built Phase 2 features like document summarization) before any design decision, exactly the process every other phase already went through.
