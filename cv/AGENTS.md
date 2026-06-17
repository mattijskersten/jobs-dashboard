# CV Tailoring Guide

This directory holds the candidate's CV as a Markdown source file compiled to
PDF via Pandoc + XeLaTeX, plus the tailoring rules, so the jobs-dashboard
pipeline is self-contained.

The real `cv/cv.md` and the worked examples in `cv/examples/` are personal and
gitignored — the repo ships `cv/cv.example.md` and `cv/examples/example-*.md`
as sanitized templates. Copy the master template into place once with
`cp cv/cv.example.md cv/cv.md`, then edit it.

## The one rule

**Only edit `cv.md` (or a tailored copy of it).** The layout files
(`cv-template.tex`, `cv-filter.lua`) must not be touched.

---

## Build

```bash
cv/build.sh                              # cv.md → cv-output.pdf (master CV)
cv/build.sh "data/cvs/cv Foo.md"         # named file → PDF next to it
cv/build.sh input.md output.pdf          # explicit input and output
```

Template and filter paths are resolved relative to the script, so it can be run
from the repo root on files anywhere in the repo.

Requires: `pandoc`, `xelatex` (texlive-xetex), Carlito font (pre-installed).

---

## File overview

| File | Purpose |
|---|---|
| `cv.md` | **Master CV content** — the base for every tailored variant (your copy of `cv.example.md`; gitignored) |
| `cv.example.md` | Sanitized master-CV template that ships in the repo |
| `examples/*.md` | Worked examples of tailored CVs, read as style references. Drop your real ones here (gitignored); the shipped `example-*.md` placeholders are skipped by `tailor-job.sh` whenever any real example is present, and used only as a fallback on a fresh clone. |
| `cv-template.tex` / `cv-filter.lua` | Layout — do not edit for content changes |
| `build.sh` | Compile command |

In this repo, pipeline-generated artifacts live under `data/` (gitignored):
- Job descriptions: `data/jds/JD $COMPANY $JOBID.txt` (the hiring.cafe job id is
  in the filename — one company can have several open roles)
- Tailored CVs: `data/cvs/cv <Candidate> $COMPANY.md` + `.pdf`

---

## Tailoring workflow

Given a JD file:

1. Read the JD in full, then `cv.md` (for structure, section order, and
   formatting conventions) and the worked example CVs in `cv/examples/` for
   richer background material and as style references.
2. **Write down the 3–5 most important themes/requirements** before drafting:
   seniority and scope signals (org size, revenue, company stage), domain
   emphasis, and terminology the JD repeats (mirror it per "Keyword mirroring"
   below). This is the brief the rest of the tailoring executes against —
   commit to it first, don't reverse-engineer it from a draft afterwards.
3. Write the tailored `cv <Candidate> $COMPANY.md`, leading with the themes
   from step 2 (most relevant content first).
4. Build the PDF with `build.sh`.
5. Check the page count: `pdfinfo "….pdf" | grep Pages`. Target is 2 pages. If
   it spills to 3, tighten bullets (cut the least relevant, shorten phrasing)
   and rebuild until it fits. If it shrinks to 1, that's fine — don't pad.
6. Report the themes committed to in step 2 and the main changes made to serve
   them and why.

### Keyword mirroring (ATS)

ATS screens largely on literal string matches, so when the candidate genuinely
has the experience, use the JD's exact wording for it rather than a synonym:

- **Prefer the JD's term over an equal-truth synonym.** JD says "Gen AI" →
  write "Gen AI", not only "LLMs"; "go-to-market" not only "commercialization";
  "BFSI" / "stakeholder management" / "product strategy and roadmap" verbatim
  where they apply.
- **Spell out an acronym with the acronym once:** "Banking, Financial Services
  & Insurance (BFSI)" — then either form matches.
- **Put the mirrored terms where they carry weight:** the summary, Core
  Competencies, and the first bullets of the most relevant roles — not buried
  in the last bullet of an old role.
- **Match the JD's grammatical form** ("product strategy and roadmap" vs
  "roadmapping") when both describe the same real work.

Hard limit — this never overrides the no-fabrication rule:

- Only mirror a keyword the candidate actually has behind it. A tool, skill, or
  domain they haven't done does not go in, however prominent it is in the JD.
- No keyword stuffing, keyword lists, hidden/white text, or repetition past
  what reads naturally. The CV must still be their factual, understated voice.

### Tailoring scope

- ✅ Rewrite/refocus the professional summary (two sentences, the candidate's
  voice — direct, confident, not buzzword-heavy)
- ✅ Reorder and rephrase bullets to match JD themes (most relevant first;
  minimum 2 bullets per role)
- ✅ Draw on material from the tailored examples not currently in cv.md
- ✅ Adjust Core Competencies ordering/emphasis
- ❌ Do not fabricate metrics, outcomes, or responsibilities
- ❌ Do not change dates, job titles, or company names
- ❌ Do not remove roles entirely
- ❌ Do not touch Education, header, languages, or layout

---

## cv.md conventions

### YAML front matter

```yaml
name:      Full name (rendered as bold small caps heading)
phone:     Phone number
city:      City, country (centered in contact row)
email:     Email address
languages: Displayed in italic below contact row (use · as separator)
```

### Section headers

```markdown
## Section Name          →  bold small caps section header with rule above
```

### Experience / Education entries

```markdown
### COMPANY, LOCATION | Date range    →  bold company left, bold date right
**Job Title**                          →  bold italic title (standalone bold paragraph)
- bullet point                         →  standard bullet
```

### Special divs

```markdown
::: summary
Two-sentence professional summary here.
:::
```

Renders as an indented block — always at the top of the body.

```markdown
::: twocol
- item 1
- item 2
:::
```

Renders as a two-column bullet list — available if needed.

### Core Competencies

```markdown
- **Category** — item; item; item
```

Standard bullets with inline bold labels — no special div needed.

---

## Content guidelines

- Dollar signs in body text must be escaped: `\$1B`
- The `|` separator in H3 headings is required on both sides
- A standalone `**bold paragraph**` becomes a job title — don't use this
  pattern for anything else
- The professional summary must be inside `::: summary`

---

## Candidate context

Fill this in for your own CV (it primes the tailoring with who you are):

- **Name** — your most recent senior title and location
- Background: your career arc in a line (companies, span of years)
- Focus: the domains / product areas you are strongest in
- Languages: native and working proficiencies
- Keep the CV factual and understated — preserve that tone when tailoring
