"""Starlette app: overview, job detail, JD/CV serving, state changes, triggers.

Run with scripts/dashboard.sh (uvicorn). Unauthenticated by design — keep it
behind Tailscale/localhost (it writes the DB and runs `claude`).
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from . import db, sessions, tasks

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

# Default list view: the queues a human actually reviews.
DEFAULT_STATUS = "needs-review,shortlisted"


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


async def index(request: Request):
    status = request.query_params.get("status", DEFAULT_STATUS)
    source = request.query_params.get("source") or None
    track = request.query_params.get("track") or None
    min_score = _int(request.query_params.get("min_score"))
    starred = request.query_params.get("starred") == "1"
    # status="" means "all" — pass None so the query doesn't filter on status.
    jobs = db.list_jobs(
        status=status or None, source=source, track=track,
        min_score=min_score, starred=starred,
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "overview": db.overview(),
            "jobs": jobs,
            "filters": {
                "status": status,
                "source": source or "",
                "track": track or "",
                "min_score": min_score if min_score is not None else "",
                "starred": starred,
            },
            "status_order": db.STATUS_ORDER,
            "tasks": tasks.snapshot(),
        },
    )


async def job_detail(request: Request):
    job_id = request.path_params["job_id"]
    job = db.get_job(job_id)
    if not job:
        return PlainTextResponse("job not found", status_code=404)
    jd_text = None
    jd_file = db.safe_data_path(job.get("jd_path"))
    if jd_file:
        jd_text = jd_file.read_text(encoding="utf-8", errors="replace")
    cv_file = db.safe_data_path(job.get("cv_pdf_path"))
    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "job": job,
            "jd_text": jd_text,
            "has_cv": cv_file is not None,
            # the real on-disk PDF name, used as the download URL's last segment
            # so "save as" defaults to it (e.g. "cv Jane Doe Acme.pdf")
            "cv_filename": cv_file.name if cv_file else None,
            "actions": db.ACTIONS,
            "tasks": tasks.snapshot(),
            "session": sessions.snapshot().get(job_id),
            # for the "resume in your shell" command in the Refine panel
            "repo_root": str(db.repo_root()),
        },
    )


async def run_digest(request: Request):
    try:
        run_id = int(request.path_params["run_id"])
    except ValueError:
        return PlainTextResponse("bad run id", status_code=404)
    run = db.get_run(run_id)
    if not run:
        return PlainTextResponse("run not found", status_code=404)
    digest_html = None
    report = db.safe_data_path(run.get("report_path"))
    if not report:
        # An interrupted run can write its digest file but never record
        # report_path back on the row (finished_at stays NULL). Fall back to the
        # filename convention scripts use: data/reports/run-<id>-*.md.
        matches = sorted((db.data_dir() / "reports").glob(f"run-{run_id}-*.md"))
        report = db.safe_data_path(
            str(matches[0].relative_to(db.repo_root())) if matches else None
        )
    if report:
        import markdown

        text = report.read_text(encoding="utf-8", errors="replace")
        # the page header already says "Run <id>" — drop the digest's own H1
        text = re.sub(r"^#\s[^\n]*\n+", "", text, count=1)
        digest_html = markdown.markdown(
            text, extensions=["extra", "sane_lists", "nl2br"]
        )
    return templates.TemplateResponse(
        request,
        "run.html",
        {"run": run, "digest_html": digest_html},
    )


async def job_jd(request: Request):
    job = db.get_job(request.path_params["job_id"])
    jd_file = db.safe_data_path(job.get("jd_path")) if job else None
    if not jd_file:
        return PlainTextResponse("no JD on file", status_code=404)
    return PlainTextResponse(jd_file.read_text(encoding="utf-8", errors="replace"))


async def job_cv(request: Request):
    job = db.get_job(request.path_params["job_id"])
    cv_file = db.safe_data_path(job.get("cv_pdf_path")) if job else None
    if not cv_file:
        return PlainTextResponse("no tailored CV on file", status_code=404)
    # inline so phone browsers render it rather than download it
    return FileResponse(
        cv_file,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{cv_file.name}"'},
    )


async def job_action(request: Request):
    job_id = request.path_params["job_id"]
    form = await request.form()
    action = form.get("action", "")
    changed, message = db.apply_action(job_id, action)
    # progressive enhancement: redirect back where the user was; a refused
    # action (stale page, illegal transition) surfaces as a flash message
    back = str(form.get("next") or request.url_for("job_detail", job_id=job_id))
    if not changed:
        back += ("&" if "?" in back else "?") + urlencode({"msg": message})
    return RedirectResponse(back, status_code=303)


async def trigger_ingest(request: Request):
    form = await request.form()
    days = _int(form.get("days")) or 7
    script = db.repo_root() / "scripts" / "ingest.sh"
    await tasks.start(
        kind="ingest",
        argv=[str(script), "--days", str(days)],
        label=f"hiring.cafe ingest ({days}d)",
        log_name=".last-ingest.log",
    )
    return RedirectResponse(str(request.url_for("index")), status_code=303)


async def job_star(request: Request):
    job_id = request.path_params["job_id"]
    db.toggle_star(job_id)
    form = await request.form()
    back = form.get("next") or request.url_for("job_detail", job_id=job_id)
    return RedirectResponse(str(back), status_code=303)


async def trigger_ingest_linkedin(request: Request):
    # LinkedIn has no plain script — it's the /ingest-linkedin Claude command
    # driving the browser-scraped linkedin MCP, so run it headless like the
    # nightly pipeline runs /pipeline. The MCP tools are pre-approved in
    # .claude/settings.json; a missing login cookie surfaces in the log.
    await tasks.start(
        kind="linkedin",
        argv=["claude", "-p", "/ingest-linkedin", "--output-format", "text"],
        label="LinkedIn ingest",
        log_name=".last-linkedin-ingest.log",
    )
    return RedirectResponse(str(request.url_for("index")), status_code=303)


async def trigger_tailor(request: Request):
    job_id = request.path_params["job_id"]
    job = db.get_job(job_id)
    if not job or job["status"] != "shortlisted":
        return PlainTextResponse(
            "tailoring only runs on shortlisted jobs", status_code=409
        )
    script = db.repo_root() / "scripts" / "tailor-job.sh"
    await tasks.start(
        kind="tailor",
        argv=[str(script), job_id],
        label=f"tailor {job['company']}",
        log_name=f".tailor-{job_id}.log",
    )
    return RedirectResponse(
        str(request.url_for("job_detail", job_id=job_id)), status_code=303
    )


async def tasks_status(request: Request):
    log = request.query_params.get("log")
    payload = {"tasks": tasks.snapshot(), "sessions": sessions.snapshot()}
    if log:
        payload["log_tail"] = tasks.tail_log(log)
    return JSONResponse(payload)


# --- Remote Control: resume a tailoring session to fine-tune the CV ---------

REFINABLE_STATUSES = {"tailored", "applied"}


async def trigger_remote(request: Request):
    """Launch a Remote Control session resumed on the job's tailoring session."""
    job_id = request.path_params["job_id"]
    job = db.get_job(job_id)
    if not job:
        return PlainTextResponse("job not found", status_code=404)
    if not (job.get("tailoring_session_id") or "").strip():
        return PlainTextResponse(
            "no resumable session — tailor this job first", status_code=409
        )
    # Don't launch into the middle of an active pipeline task editing the same DB/files.
    if tasks.is_running("tailor") or tasks.is_running("ingest"):
        return PlainTextResponse(
            "a pipeline task is running; try again shortly", status_code=409
        )
    sessions.launch(job_id)
    return RedirectResponse(
        str(request.url_for("job_detail", job_id=job_id)), status_code=303
    )


async def stop_remote(request: Request):
    sessions.stop(request.path_params["job_id"])
    return RedirectResponse(
        str(request.url_for("job_detail", job_id=request.path_params["job_id"])),
        status_code=303,
    )


async def remote_qr(request: Request):
    """SVG QR code for the live session URL, so a phone can scan straight in."""
    sess = sessions.get(request.path_params["job_id"])
    if not sess or not sess.url:
        return PlainTextResponse("no live session", status_code=404)
    import segno

    buf = io.BytesIO()
    segno.make(sess.url, error="m").save(
        buf, kind="svg", scale=5, border=2, dark="#11131a", light="#ffffff"
    )
    return Response(buf.getvalue(), media_type="image/svg+xml")


routes = [
    Route("/", index, name="index"),
    Route("/ingest", trigger_ingest, methods=["POST"], name="ingest"),
    Route("/ingest-linkedin", trigger_ingest_linkedin, methods=["POST"], name="ingest_linkedin"),
    Route("/tasks/status", tasks_status, name="tasks_status"),
    Route("/run/{run_id}", run_digest, name="run_digest"),
    Route("/job/{job_id}", job_detail, name="job_detail"),
    Route("/job/{job_id}/jd", job_jd, name="job_jd"),
    # {filename} is cosmetic — the file is looked up by job_id — but it makes the
    # browser's "save as" default to the real CV name instead of "cv.pdf".
    Route("/job/{job_id}/cv/{filename}", job_cv, name="job_cv"),
    Route("/job/{job_id}/action", job_action, methods=["POST"], name="job_action"),
    Route("/job/{job_id}/star", job_star, methods=["POST"], name="job_star"),
    Route("/job/{job_id}/tailor", trigger_tailor, methods=["POST"], name="job_tailor"),
    Route("/job/{job_id}/remote", trigger_remote, methods=["POST"], name="job_remote"),
    Route("/job/{job_id}/remote/stop", stop_remote, methods=["POST"], name="job_remote_stop"),
    Route("/job/{job_id}/remote/qr.svg", remote_qr, name="job_remote_qr"),
    Mount("/static", StaticFiles(directory=str(HERE / "static")), name="static"),
]

app = Starlette(routes=routes)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "jobs_dashboard.app:app",
        host=os.environ.get("JOBS_DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("JOBS_DASHBOARD_PORT", "8765")),
    )


if __name__ == "__main__":
    run()
