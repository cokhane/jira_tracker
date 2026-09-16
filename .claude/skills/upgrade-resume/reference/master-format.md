# master.md format

The Markdown subset `render_resume.py` understands. It is deliberately small —
everything in it maps to something an ATS can parse, and nothing in it needs a
Markdown library.

## Skeleton

```markdown
# RHIDZKHAN AHMAD
**Lead Backend Engineer / Solution Architect**
+63 927 457 7680 | rhidzkhan.ahmad99@gmail.com | linkedin.com/in/rhidzkhanahmad
github.com/cokhane | mehruemm99.pythonanywhere.com

## PROFESSIONAL SUMMARY
One paragraph. No bullet, no heading markers.

## TECHNICAL SKILLS
**Backend:** Python (FastAPI, Django, Flask), Java (Spring Boot), Node.js
**Cloud & DevOps:** AWS (ECS, RDS, ElastiCache), GCP, Azure, Terraform, Jenkins

## PROFESSIONAL EXPERIENCE
### RXLABS — Lead Backend Engineer / Solution Architect
*Feb 2025 – Present*
#### E-Commerce Orchestration Platform — multi-PSP storefront on MedusaJS
*FastAPI · MedusaJS · AWS ECS/RDS/ElastiCache · Docker*
- Architected the multi-PSP orchestration layer connecting ...
- Cut checkout p95 latency from 1.4s to 380ms by ...

## EDUCATION
### Ateneo de Zamboanga University — BS Information Technology
*2010 – 2015*

## KEY ACHIEVEMENTS
- Employee of the Year, Visibility (2022)
```

## The rules

| Syntax | Meaning |
|---|---|
| `# Name` | Once, first line. Required — the renderer errors without it. |
| `**Target Title**` | Tagline. The first bold-only line after the name. |
| plain line(s) before the first `##` | Contact rows. Separate items with ` \| `. |
| `## SECTION` | Section heading + horizontal rule. Uppercase by convention. |
| `### Left — Right` | Entry heading. `Left` renders uppercase (company/school), `Right` in accent (title/degree). |
| `*Feb 2025 – Present*` | An italic-only line **directly under** a `###` becomes the date, right-aligned onto the heading row. |
| `#### Project — blurb` | Sub-entry. Text after the dash renders in regular weight. |
| `*stack · stack*` | An italic-only line **directly under** a `####` becomes its meta line. |
| `**Label:** value` | Definition row — used for the skills block. |
| `**Label** value` | Same row without the colon — used for one-line Early Career entries, e.g. `**WIDEOUT — Frontend Engineer** *(2016 – 2017)* · Built ...`. The renderer never adds a colon the source did not have. |
| `- text` | Bullet. |
| `[[TODO: ask about X]]` | Unresolved fact. Renders highlighted in the PDF and blocks `--final`. |
| `<!-- note -->` | Editor comment. Never rendered. |
| `**bold**` `*italic*` `` `code` `` `[text](url)` | Inline spans. |

Separators accepted in `###`/`####` headings: ` — `, ` – `, ` -- `, ` | `, ` - `.

## What the format deliberately omits

No tables, images, columns, text boxes, headers or footers. Each is a known ATS
parse hazard, so the renderer has no syntax that could produce one. The two-column
*look* of a heading row is CSS flexbox over text that stays in reading order —
the extracted text layer still reads "RXLABS — Lead Backend Engineer  Feb 2025 – Present".

## Length control

`--density compact|normal|roomy` scales type size and vertical rhythm. Reach for
`compact` before cutting real content, but do not go below `compact` — shrink
further and you have a wall of grey, not a resume. Past that, cut the oldest roles
to one line each (see the rubric's recency budget).
