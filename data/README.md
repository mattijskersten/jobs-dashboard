# data/ — your personal content (gitignored)

Everything in this folder is **gitignored and never committed** (only this
README ships, to keep the folder in the repo). It holds all real, personal
content for the pipeline:

| Path | What it is |
|---|---|
| `cv.md` | Your master CV — copy from `templates/cv.example.md`, then edit |
| `search-profile.md` | Your job criteria — copy from `templates/search-profile.example.md` |
| `references/*.md` | Your real tailored CVs, used as style references when tailoring |
| `jobs.db` | SQLite pipeline state (`jobs` + `runs`) |
| `jds/` | Saved job descriptions, one file per job |
| `cvs/` | Tailored CV drafts (`.md` + `.pdf`) |
| `reports/` | Per-run digests |

## First-time setup

```sh
scripts/init-db.sh                                              # creates jobs.db + subfolders
cp templates/search-profile.example.md data/search-profile.md  # then edit
cp templates/cv.example.md             data/cv.md              # then edit
# optional: drop your real tailored CVs into data/references/ as style refs
```

The ignore rule lives in the repo root `.gitignore` (`/data/*` with a single
`!/data/README.md` exception). If you add files here, they stay local.
