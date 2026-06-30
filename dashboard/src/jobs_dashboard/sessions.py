"""Remote Control session launcher for manual CV fine-tuning.

Each tailored job stores a `tailoring_session_id` (written by scripts/tailor-job.sh).
This module resumes that exact session with Remote Control enabled:

    claude --resume <session_id> --remote-control --name "<company> CV"

so Matt can continue the *same* interactive Claude session — full context (JD,
master CV, references, the themes it committed to) — from claude.ai/code or the
Claude mobile app, on any device. The dashboard's job is launch → capture the
claude.ai URL → track → stop.

Why this is its own module and not tasks.py: these are *long-lived* and need a
PTY. The interactive `claude` TUI requires a controlling terminal, so we launch
via `pty.fork` (proven in the Phase-1 spike); a reader thread drains the PTY for
the life of the session (if we stop reading, the PTY buffer fills and claude
blocks) and scrapes the session URL out of the output. Teardown kills the
process *group* — the TUI swallows SIGINT/SIGTERM aimed at the bare pid.

Unlike the one-shot ingest/tailor tasks we do NOT hold data/.pipeline.lock for
the session's life; that could block the nightly run for as long as Matt keeps
the session open. SQLite WAL covers concurrent DB writes, and a refine targets a
*tailored* job while the nightly run only tailors *shortlisted* ones.
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import signal
import struct
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import db

# The session URL claude prints in its footer:
#   "remote-control is active · Continue here ... at https://claude.ai/code/session_XXXX"
_URL_RE = re.compile(rb"https://claude\.ai/code/session_[A-Za-z0-9_-]+")
# Strip ANSI/control noise from the TUI so the URL (and log) are readable.
_ANSI_RE = re.compile(
    rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][AB012]|[\x00-\x08\x0b\x0c\x0e-\x1f]"
)
_MAX_BYTES = 256 * 1024  # cap URL-scan buffer and the debug log


@dataclass
class Session:
    job_id: str
    company: str
    session_id: str
    name: str
    pid: int
    master_fd: int
    log_path: Path
    url: str | None = None
    status: str = "launching"  # launching | live | ended | failed
    started: float = field(default_factory=time.time)
    ended: float | None = None


_sessions: dict[str, Session] = {}
_lock = threading.Lock()


def _reader(sess: Session) -> None:
    """Drain the PTY for the life of the process; scrape the URL; tee to a log.

    pty.fork makes the child its own session leader, so the master fd reaches EOF
    when the child exits — that ends this loop. We keep reading after the URL is
    found purely to keep the PTY from blocking the child.
    """
    buf = bytearray()
    logged = 0
    try:
        with sess.log_path.open("wb") as log:
            while True:
                try:
                    data = os.read(sess.master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                clean = _ANSI_RE.sub(b" ", data)
                if sess.url is None:
                    buf += clean
                    if len(buf) > _MAX_BYTES:
                        del buf[:-_MAX_BYTES]
                    m = _URL_RE.search(buf)
                    if m:
                        sess.url = m.group(0).decode(errors="replace")
                        sess.status = "live"
                if logged < _MAX_BYTES:
                    log.write(clean)
                    log.flush()
                    logged += len(clean)
    finally:
        if sess.status not in ("ended", "failed"):
            sess.status = "ended" if sess.url else "failed"
        sess.ended = time.time()
        try:
            os.close(sess.master_fd)
        except OSError:
            pass
        try:  # reap the child so it doesn't linger as a zombie
            os.waitpid(sess.pid, 0)
        except (ChildProcessError, OSError):
            pass


def launch(job_id: str) -> tuple[bool, str, Session | None]:
    """Resume the job's tailoring session with Remote Control.

    Returns (ok, message, session). Idempotent while a session is live: a second
    launch returns the existing one.
    """
    job = db.get_job(job_id)
    if not job:
        return False, "job not found", None
    session_id = (job.get("tailoring_session_id") or "").strip()
    if not session_id:
        return False, "no resumable tailoring session for this job", None

    company = job.get("company") or job_id
    name = f"{company} CV"
    root = str(db.repo_root())
    reports = db.data_dir() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / f".rc-{job_id}.log"

    with _lock:
        existing = _sessions.get(job_id)
        if existing and existing.status in ("launching", "live"):
            return True, "session already running", existing

        argv = ["claude", "--resume", session_id, "--remote-control", "--name", name]
        pid, fd = pty.fork()
        if pid == 0:
            # child: become the resumed session in the repo root, then exec.
            # Keep this minimal — no Python locks between fork and exec.
            try:
                os.chdir(root)
            except OSError:
                os._exit(127)
            os.execvp(argv[0], argv)
            os._exit(127)  # exec failed

        # parent: give the PTY a sane window so the TUI lays out and prints the URL
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 160, 0, 0))
        except OSError:
            pass
        sess = Session(
            job_id=job_id, company=company, session_id=session_id, name=name,
            pid=pid, master_fd=fd, log_path=log_path,
        )
        _sessions[job_id] = sess
        threading.Thread(target=_reader, args=(sess,), daemon=True).start()

    return True, "launched", sess


def stop(job_id: str) -> tuple[bool, str]:
    """Kill the session's process group (the TUI ignores signals to the bare pid)."""
    with _lock:
        sess = _sessions.get(job_id)
    if not sess:
        return False, "no session for this job"
    if sess.status in ("ended", "failed"):
        return True, "already stopped"
    try:
        os.killpg(sess.pid, signal.SIGKILL)  # pty.fork child's pgid == its pid
    except ProcessLookupError:
        pass
    except OSError as exc:
        return False, f"could not stop: {exc}"
    # the reader thread will observe EOF, reap the child, and finalize status
    return True, "stopped"


def get(job_id: str) -> Session | None:
    return _sessions.get(job_id)


def snapshot() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with _lock:
        items = list(_sessions.items())
    for jid, s in items:
        out[jid] = {
            "job_id": jid,
            "company": s.company,
            "name": s.name,
            "url": s.url,
            "status": s.status,
            "started": s.started,
            "ended": s.ended,
        }
    return out
