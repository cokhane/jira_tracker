# Resume upgrade rubric

The editorial standard for the rewrite pass. Apply every section in order.

---

## 0. Truth lock — the rule that outranks every other rule

A resume is a factual claim made to an employer. **Never invent, inflate, or
"reasonably estimate" anything.**

Never fabricate: metrics, percentages, dollar amounts, user/request counts, team
sizes, dates, employers, titles, degrees, certifications, or tools the source
never mentions.

When a bullet is clearly missing its impact number, do **not** guess one. Write
the bullet as strongly as the known facts allow and append a marker:

```markdown
- Rebuilt the authentication flow, fixing a session bug affecting 20% of users [[TODO: time to resolution, or support tickets deflected?]]
```

The markers render highlighted in the PDF and `--final` refuses to build while any
remain, so nothing unverified can reach a recruiter by accident.

Rewriting *is* allowed: reordering, tightening, sharpening verbs, merging two weak
bullets into one strong one, and surfacing a number that already exists elsewhere
in the source. Restating the same fact better is the job. Adding a new fact is not.

---

## 1. The bullet formula

> **Strong verb + what you built or changed + the technical specifics + the measurable outcome**

```
weak    Responsible for the payment system
better  Built the rebilling engine using Primer and Celeris
best    Built a rebilling engine on Primer and Celeris, lifting payment
        authorization rates 40–60%
```

Rules:
- **One idea per bullet.** Two ideas joined by "and" are two bullets, or one is filler.
- **Lead with the outcome when the outcome is the story** — "Cut infrastructure
  spend 67% ($4.8K/yr) by migrating ... to Terraform IaC" beats burying the 67%.
- **Specifics over adjectives.** "high-performance" says nothing; "p95 380ms" does.
- **12–28 words.** Under 12 is usually vague; over 28 stops being skimmable.
- **No trailing period fragments mixed with full sentences** — pick one, apply
  to all. (Default: no terminal period on bullets.)
- **3–6 bullets** for recent roles, **1–3** for older ones.

## 2. Verb discipline

Delete on sight — these describe a job description, not a person:

> Responsible for · Helped with · Worked on · Assisted in · Participated in ·
> Involved in · Tasked with · Duties included · Various · Successfully ·
> Utilized (say "used") · Leveraged (usually) · Spearheaded (overused)

Prefer verbs that state a mechanism: *Architected, Built, Designed, Migrated,
Rebuilt, Automated, Instrumented, Consolidated, Eliminated, Cut, Scaled,
Parallelized, Hardened, Mentored, Led, Shipped, Diagnosed, Refactored.*

**Never repeat the same opening verb twice within one role**, and no more than
three times across the whole document. Repetition reads as a template.

**Tense:** present for the current role, past for every prior role. No first person
("I", "my"). Drop leading articles where it reads naturally.

## 3. The recency budget

Recruiters weight the last 3–5 years almost exclusively. Allocate space to match:

| Age of role | Treatment |
|---|---|
| Current + previous | Full depth — projects, stack lines, 3–6 bullets each |
| 3–6 years back | Compressed — 2–4 bullets, no per-project breakdown unless the project is the headline |
| 7+ years back | One line per role: company, title, dates, and a single sentence of scope |
| Pre-career / hobby | Cut entirely, unless it is the only evidence of a skill the target roles want |

**Target length: 2 pages** for 10+ years of experience; 1 page under ~5 years. A
3-page engineering resume is not thorough, it is unedited. If the page count is
over budget, cut from the bottom of the document upward — never thin out the
recent roles to save the old ones.

## 4. Professional summary

3–4 lines, no more. It must answer: *what kind of engineer, at what level, with
what specialty, and what is the single most impressive proof.*

- Open with the role and seniority, not with "Results-driven professional".
- Name the 2–3 technologies that define the specialty — not the whole stack.
- Land exactly one or two headline numbers. More than that and none of them stick.
- Cut every adjective that any candidate could claim: *passionate, dedicated,
  hard-working, detail-oriented, results-driven, proven track record, dynamic.*

## 5. Skills block

- Group into 4–7 labelled rows. More rows than that becomes a wall.
- **Order rows by relevance to the target role**, strongest first.
- Within a row, put the genuinely strong items first — readers stop scanning early.
- Cut anything not defensible in an interview, and anything now assumed (HTML,
  jQuery, Git as a standalone skill on a senior resume).
- Keep parenthetical depth where it is real: "Java (Spring Boot — 3 yrs)".
- No proficiency bars, star ratings, or percentages. They parse as noise and read
  as self-assessment.

## 6. ATS mechanics

- Standard section titles only: *Professional Summary, Technical Skills,
  Professional Experience, Education, Certifications, Key Achievements.* A clever
  heading ("Where I've Made Noise") gets the section dropped by the parser.
- **Spell out, then abbreviate on first use** for anything a keyword filter might
  search both ways: "Continuous Integration/Continuous Deployment (CI/CD)",
  "Infrastructure as Code (IaC)", "Amazon Web Services (AWS)".
- Reverse-chronological order, always. Dates on every role, formatted identically.
- Keep dates in one format throughout — `Feb 2025 – Present` and `2020 – 2023`
  must not coexist; pick `Mon YYYY – Mon YYYY` and apply it everywhere.
- No graphics, logos, columns, tables, text boxes, or content in headers/footers.
- Filename: `Firstname_Lastname_Resume.pdf`. Not `cv_final_v3.pdf`.

## 7. Derived-number audit

Recompute anything the resume states that is *derived* from other facts on the
page, and flag every disagreement rather than silently editing:

- **Years of experience** — compute from the earliest professional role to today.
  A summary claiming "9+ years" over a history starting in 2015 is understating by
  two years, which is a real cost.
- **Role date ranges** — check for gaps and overlaps; an unexplained gap is worth
  raising with the user, not papering over.
- **Totals repeated in two places** — team sizes, client counts, and cost savings
  quoted in both a bullet and the Key Achievements list must match exactly.

## 8. Consistency sweep

Run these as a final pass over the whole document:

- Date format, dash character (` – ` throughout), and spacing — identical everywhere.
- Capitalization of technology names as the vendors write them: PostgreSQL, MySQL,
  Node.js, GitHub, PySpark, Kubernetes, macOS, JavaScript, TypeScript.
- Serial commas — on or off, consistently.
- Bullet terminal punctuation — consistent (default: none).
- Numbers: numerals for all quantities ("3 to 16", not "three to 16"); `$4.8K/yr`
  or `$4,800/yr` but not both.
- One contact line format; no duplicated links; every URL live and lowercase.

## 9. What not to touch

Leave alone unless the user asks: employer names, job titles, employment dates,
degree and institution, and any claim the source states as fact. If a title looks
inflated or a date looks wrong, **raise it as a question** — do not quietly fix it.

---

## Quality bar

Before declaring the pass complete, every one of these must be true:

1. No fabricated fact anywhere; every gap is an explicit `[[TODO: ...]]`.
2. Zero banned phrases from §2 remain.
3. No opening verb repeats inside a single role.
4. Every recent-role bullet either carries a number or carries a concrete mechanism.
5. Page count is within budget at `normal` or `compact` density.
6. Derived numbers recomputed; disagreements reported to the user.
7. Dates, capitalization, and punctuation consistent throughout.
8. The summary would survive a 6-second skim and say what this person is.
