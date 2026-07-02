# CV Tailoring Guide

`tooling/` holds the CV build assets (Pandoc template + Lua filter, `build.sh`)
and these tailoring rules, so the jobs-dashboard pipeline is self-contained.
The candidate's CV is compiled to PDF via Pandoc + XeLaTeX.

The master CV `data/cv.md`, the style-reference CVs in `data/references/`, and
the job criteria `data/search-profile.md` are personal and gitignored — the
repo ships sanitized templates under `templates/`. Copy the master template
into place once with `cp templates/cv.example.md data/cv.md`, then edit it.

## The one rule

**Only edit `data/cv.md` (or a tailored copy of it).** The layout files
(`tooling/cv-template.tex`, `tooling/cv-filter.lua`) must not be touched.

---

## Build

```bash
tooling/build.sh                          # data/cv.md → data/cv-output.pdf (master CV)
tooling/build.sh "data/cvs/cv Foo.md"     # named file → PDF next to it
tooling/build.sh input.md output.pdf      # explicit input and output
```

Template and filter paths are resolved relative to the script, so it can be run
from the repo root on files anywhere in the repo.

Requires: `pandoc`, `xelatex` (texlive-xetex), Carlito font (pre-installed).

---

## File overview

| Path | Purpose |
|---|---|
| `data/cv.md` | **Master CV content** — the base for every tailored variant (your copy of `templates/cv.example.md`; gitignored) |
| `templates/cv.example.md` | Sanitized master-CV template that ships in the repo |
| `templates/cv-example-*.md` | Sanitized worked-example CVs that ship as a fallback style reference for fresh clones |
| `data/references/*.md` | Your real worked-example CVs, read as **calibrated exemplars — authoritative for phrasing and claim scope** (gitignored). `tailor-job.sh` uses these when present and falls back to `templates/cv-example-*.md` otherwise. |
| `tooling/cv-template.tex` / `tooling/cv-filter.lua` | Layout — do not edit for content changes |
| `tooling/build.sh` | Compile command |

In this repo, pipeline-generated artifacts live under `data/` (gitignored):
- Job descriptions: `data/jds/JD $COMPANY $JOBID.txt` (the hiring.cafe job id is
  in the filename — one company can have several open roles)
- Tailored CVs: `data/cvs/cv <Candidate> $COMPANY.md` + `.pdf` (`tailor-job.sh`
  appends ` $TITLE` when the company has more than one CV-bearing job — kept
  human-readable so the file can be uploaded to application forms as-is; the
  job id is added only if even the title collides)

---

## Tailoring workflow

Given a JD file:

1. Read the JD in full, then `data/cv.md` (for structure, section order, and
   formatting conventions) and the worked example CVs (in `data/references/`,
   or `templates/cv-example-*.md`) for richer background and as **calibrated
   exemplars**. Treat the reference CVs as authoritative above `cv.md` for
   *phrasing and claim scope*: they are later, hand-tuned versions, so where a
   reference and `cv.md` state the same fact differently (e.g. "directed product
   *for* a 200+ FTE org" vs "led"; keeping the most recent role at the top),
   follow the reference. Use `cv.md` as the fact base for content the references
   don't cover. Before drafting, diff the references against `cv.md` and note
   where they deliberately soften, reframe, or retain a claim — carry those
   choices forward unless the JD demands otherwise.

   **Authority order:** references > `cv.md` for phrasing and claim scope;
   `cv.md` > references for completeness of older roles (never drop a role just
   because a reference omits it — see Tailoring scope).
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
   Then skim the rendered PDF for layout/escaping glitches that `pdfinfo`
   can't see — unescaped `$` (must be `\$`), a broken `|` H3 heading, a
   standalone `**bold**` line mis-rendering as a job title, or a bullet
   swallowed by the template. Fix and rebuild if any appear.
6. **Keyword-coverage check.** Map the JD's most-repeated must-have terms to
   where each lands in the CV (summary / Core Competencies / which role). Flag
   any high-frequency term that's absent and why — genuinely lacking (leave it
   out, per the no-fabrication rule) vs. missed (add it where truthful and
   rebuild).
7. Report the themes committed to in step 2 and the main changes made to serve
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
name:      Full name (rendered as bold small caps heading, navy accent)
headline:  One-line positioning tagline under the name (navy accent)
phone:     Phone number
city:      City, country (first item in contact row)
email:     Email address
linkedin:  LinkedIn URL without scheme, e.g. linkedin.com/in/your-handle
github:    GitHub URL without scheme, e.g. github.com/your-handle
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
