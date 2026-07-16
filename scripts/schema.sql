-- jobs-dashboard state schema. Applied idempotently by scripts/init-db.sh.
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,           -- hiring.cafe job id (dedup key)
    company             TEXT NOT NULL,
    title               TEXT NOT NULL,
    url                 TEXT,                       -- hiring.cafe job page
    apply_url           TEXT,                       -- application on the company/ATS portal
    track               TEXT CHECK (track IN ('A', 'B')),
    source              TEXT NOT NULL DEFAULT 'hiringcafe'   -- where the row came from
                        CHECK (source IN ('hiringcafe', 'linkedin', 'manual')),
    status              TEXT NOT NULL DEFAULT 'seen'
                        CHECK (status IN ('seen','triaged','needs-review',
                                          'shortlisted','tailored','applied','rejected',
                                          'closed','declined')),
    score               INTEGER CHECK (score BETWEEN 1 AND 10),
    starred             INTEGER NOT NULL DEFAULT 0,  -- manual priority flag, independent of status
    rationale           TEXT,                       -- one-line triage rationale
    posted_date         TEXT,                       -- hiring.cafe estimated_publish_date (YYYY-MM-DD)
    summary_json        TEXT,                       -- compact search summary captured at ingest (triage input)
    jd_path             TEXT,                       -- data/jds/JD $COMPANY $JOBID.txt (score >= 6 only)
    cv_md_path          TEXT,                       -- data/cvs/cv <Candidate> $COMPANY[ $TITLE].md
    cv_pdf_path         TEXT,
    tailoring_session_id TEXT,                      -- claude --resume <id> to fine-tune
    first_seen_run_id   INTEGER REFERENCES runs(run_id),
    date_seen           TEXT NOT NULL DEFAULT (datetime('now')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score);

CREATE TABLE IF NOT EXISTS runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
    jobs_seen     INTEGER NOT NULL DEFAULT 0,        -- new jobs this run
    shortlisted   INTEGER NOT NULL DEFAULT 0,
    needs_review  INTEGER NOT NULL DEFAULT 0,
    rejected      INTEGER NOT NULL DEFAULT 0,
    tailored      INTEGER NOT NULL DEFAULT 0,
    errors        TEXT,                              -- human-readable error summary, NULL if clean
    report_path   TEXT
);
